/**
 * Pi extension entry point.
 *
 * Registers:
 *   - `stock_analysis` tool — the LLM-callable entry that runs the 5-mode /
 *     19-stage equity-research pipeline by spawning `pi` child processes (or
 *     in-process sessions). Fully self-contained: no dependency on any external
 *     workflow engine. The pipeline is a tree of control-flow nodes composed in
 *     src/stages/index.ts.
 *   - `/stock-analysis <args>` command — parses natural-language / flag args,
 *     dispatches the task to the agent, which invokes the `stock_analysis` tool.
 */

import type { ExtensionAPI, Theme } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { mkdirSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { runWorkflow } from "./workflow.ts";
import { STOCK_ANALYSIS_WORKFLOW } from "./stages/index.ts";
import { normalizeAshTicker, validateParams, defaultTopIndustry, clampRange } from "./helpers.ts";
import { abbreviatePath } from "./pi-spawn.ts";
import type {
	Mode, Universe, StockAnalysisState, RunSummary, RunStatus, ToolParams,
} from "./types.ts";

export { runWorkflow } from "./workflow.ts";
export { STOCK_ANALYSIS_WORKFLOW } from "./stages/index.ts";
export { parseStockAnalysisArgs } from "./args.ts";
export * as nodes from "./nodes.ts";
import { parseStockAnalysisArgs } from "./args.ts";

const STOCK_ANALYSIS_TOOL = "stock_analysis";
const STOCK_ANALYSIS_COMMAND = "stock-analysis";
const PACKAGE_NAME = "pi-stock-analysis";

// ─── EXTENSION_ROOT resolution (ISS-01) ─────────────────────────────────────

/**
 * Resolve the package root (dir containing this package's package.json). Works
 * for BOTH `pi -e .` (runs from source, .ts path via import.meta.url) AND
 * `pi package add` (installed under node_modules). Walks up until it finds a
 * package.json whose `name` === PACKAGE_NAME.
 */
export function resolvePackageRoot(startUrl: string): string {
	let dir = dirname(fileURLToPath(startUrl));
	for (let i = 0; i < 12; i++) {
		const pkgPath = join(dir, "package.json");
		if (existsSync(pkgPath)) {
			try {
				const pkg = JSON.parse(readFileSync(pkgPath, "utf8")) as { name?: string };
				if (pkg.name === PACKAGE_NAME) return dir;
			} catch { /* malformed — keep walking */ }
		}
		const parent = dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}
	// Fallback: assume source layout (<root>/src/extension.ts → <root>).
	return dirname(dirname(fileURLToPath(startUrl)));
}

export const EXTENSION_ROOT = resolvePackageRoot(import.meta.url);

// Export into the process env so spawned `pi` subprocesses inherit it
// (env: { ...process.env }) AND in-process session agents' bash commands expand
// ${EXTENSION_ROOT}. Agent .md files + prompts reference this path.
process.env.EXTENSION_ROOT = EXTENSION_ROOT;

// ─── Data-source API keys (TICKFLOW_API_KEY etc.) ───────────────────────
// pi may be launched from a GUI/desktop entry that never sourced ~/.bashrc,
// so spawned `pi` subprocesses + `uv run` children wouldn't see the key and
// the TickFlow-primary resolution cascade would silently fall through to
// akshare (the 2026-07-05 Stage-1 "akshare unavailable → ETF proxy" gap).
// Read ONLY the named keys from ~/.bashrc (regex, never source the file).
ensureDataSourceKeys(["TICKFLOW_API_KEY"]);

function ensureDataSourceKeys(keys: string[]): void {
	let bashrc: string;
	try {
		bashrc = readFileSync(join(homedir(), ".bashrc"), "utf8");
	} catch {
		return; // no ~/.bashrc — keys may already be in env
	}
	for (const key of keys) {
		if (process.env[key]) continue;
		const escKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
		const re = new RegExp(`^\\s*(?:export\\s+)?${escKey}=["']?([^"'\n#]+)["']?`, "m");
		const m = bashrc.match(re);
		if (m?.[1]) process.env[key] = m[1].trim();
	}
}

// ─── State initialization (Stage 0 setup) ───────────────────────────────────

/** Build the initial StockAnalysisState from tool params (Stage 0 setup). */
export function buildInitialState(params: ToolParams, opts: { extensionRoot: string; cwd: string }): StockAnalysisState {
	const mode = params.mode ?? "pipeline";
	const topIndustry = clampRange(params.topIndustry, 1, 163, defaultTopIndustry(mode));
	const totalCompany = clampRange(params.totalCompany, 1, 50, mode === "pipeline" ? 15 : 5);
	const topPrice = clampRange(params.topPrice, 0, 9999, 200);
	const minHeadroom = clampRange(params.minHeadroom, 1, 10, 5);
	const days = clampRange(params.days, 1, 20, 1);
	const universe: Universe = (params.universe as Universe) ?? "US";

	// Normalize tickers (A-share bare 6-digit → .SH/.SZ; names flagged for resolve).
	const tickers = (params.tickers ?? []).map((t) => normalizeAshTicker(t).ticker);

	// RUN_ID = YYYYMMDDHHmm in LOCAL time (rule "Run Directory").
	const now = new Date();
	const pad = (n: number) => String(n).padStart(2, "0");
	const runId = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}`;
	const reportsDir = join(opts.cwd, "reports", runId);
	mkdirSync(reportsDir, { recursive: true });

	return {
		mode,
		tickers,
		theme: params.theme?.trim() || undefined,
		topIndustry,
		totalCompany,
		topPrice,
		minHeadroom,
		days,
		universe,
		query: params.query,
		runId,
		reportsDir,
		backend: "subprocess",
		model: params.model,
		maxAgents: params.maxAgents,
		extensionRoot: opts.extensionRoot,
		companies: [],
		reports: [],
		tracking: {
			completed: [],
			skipped: [],
			failures: [],
			gateResults: [],
			startedAt: now.toISOString(),
		},
	};
}

// ─── Summary formatting (PAT-003: honest, never faked) ──────────────────────

function formatSummary(s: RunSummary, cwd?: string): string[] {
	const icon: Record<RunStatus, string> = { success: "✅", partial: "⚠️", failed: "❌" };
	const title: Record<RunStatus, string> = {
		success: "stock-analysis pipeline complete",
		partial: "stock-analysis pipeline completed with issues",
		failed: "stock-analysis pipeline did NOT complete",
	};
	const lines = [
		`${icon[s.status]} ${title[s.status]}`,
		`  Mode:      ${s.mode}`,
		`  Run ID:    ${s.runId}`,
		`  Reports:   ${abbreviatePath(s.reportsDir, cwd)} (${s.reports.length} file(s))`,
	];
	if (s.tickers.length) lines.push(`  Tickers:   ${s.tickers.join(", ")}`);
	if (s.theme) lines.push(`  Theme:     ${s.theme}`);
	lines.push(`  Agents:    ${s.agentsSpawned} spawned`);
	lines.push(`  Completed: ${s.completed.length} stage(s)`);
	if (s.skipped.length) lines.push(`  Skipped:   ${s.skipped.length} stage(s)`);
	if (s.failed.length > 0) {
		const fmt = (f: { stage: string; error?: string }) => `${f.stage}${f.error ? ` — ${f.error}` : ""}`;
		lines.push(`  Failed:    ${s.failed.map(fmt).join("\n            ")}`);
	}
	if (s.error) lines.push(`  Error:     ${s.error}`);
	return lines;
}

// ─── TUI workflow dashboard (idiomatic Pi setWidget pattern) ────────────────
// The widget (setWidget) is a simple inline stage tracker, single-column,
// rendered directly in execute(). The final result uses renderResult() for a
// themed 3-section display (dimmed logs / stage progress / summary).

// ─── Extension activation ───────────────────────────────────────────────────

export default function activate(pi: ExtensionAPI): void {
	pi.registerTool({
		name: STOCK_ANALYSIS_TOOL,
		label: "Stock Analysis",
		description:
			"Run the self-contained 5-mode / 19-stage equity-research pipeline (screen → deep-dive → scoring → adversarial verify → judge panel → 3-horizon reports → best picks). Modes: pipeline, screen, analyze, compare, walk. Spawns specialist `pi` subagents and runs deterministic calculations via the verbatim Python scripts (`uv run`).",
		promptSnippet: "Run the stock-analysis equity-research pipeline (screen / analyze / compare / walk / pipeline)",
		promptGuidelines: [
			"Use stock_analysis for equity research: screening sectors, deep-diving tickers, comparing stocks, or walking a supply-chain theme.",
			"Pass mode + tickers/theme. The pipeline runs Stage 0→19 continuously (no confirmation prompts).",
		],
		parameters: Type.Object({
			mode: Type.Union(
				[
					Type.Literal("pipeline"), Type.Literal("screen"), Type.Literal("analyze"),
					Type.Literal("compare"), Type.Literal("walk"),
				],
				{ description: "Execution mode. pipeline=screen+analyze; screen=sectors only; analyze=TICKER deep-dive; compare=2-5 tickers; walk=theme bottleneck chain. Default: pipeline." },
			),
			tickers: Type.Optional(Type.Array(Type.String(), { description: "Ticker(s). Required for analyze (≥1) and compare (2-5). A-share bare 6-digit codes auto-suffixed (.SH/.SZ)." })),
			theme: Type.Optional(Type.String({ description: "Roadmap theme for walk mode (e.g. \"humanoid robotics\"). Required for walk." })),
			topIndustry: Type.Optional(Type.Number({ description: "Top sub-industries to select. Default: 8 pipeline / 40 screen / 7 walk." })),
			totalCompany: Type.Optional(Type.Number({ description: "Total companies to deep-dive (pipeline only, cap 50). Default: 15." })),
			topPrice: Type.Optional(Type.Number({ description: "Max stock price for screening (0 disables). Default: 200." })),
			minHeadroom: Type.Optional(Type.Number({ description: "Min Growth Headroom score 1-10. Default: 5." })),
			days: Type.Optional(Type.Number({ description: "Hot-sector focus window 1-20 (1=today, 5=week). Default: 1." })),
			universe: Type.Optional(Type.Union([Type.Literal("US"), Type.Literal("CN"), Type.Literal("ALL")], { description: "Listing-exchange filter. Default: US." })),
			query: Type.Optional(Type.String({ description: "Natural-language request (passthrough / for logging)." })),
			model: Type.Optional(Type.String({ description: "Model override for spawned specialist agents in provider/id form." })),
			maxAgents: Type.Optional(Type.Number({ description: "Maximum specialist agent spawns. Default: 200." })),
		}),
		async execute(_toolCallId, params, signal, onUpdate, ctx) {
			// Fail-fast input validation (ISS-04): check per-mode requirements early.
			const mode = (params.mode as Mode | undefined) ?? "pipeline";
			const paramErrors = validateParams({ mode, tickers: params.tickers as string[] | undefined, theme: params.theme as string | undefined });
			if (paramErrors.length > 0) {
				return { content: [{ type: "text", text: `❌ Invalid parameters: ${paramErrors.join("; ")}` }], isError: true, details: {} };
			}

			const transcript: string[] = [];
			let live = "";
			let lastFlush = 0;
			const FLUSH_MS = 80;
			const finalizeLive = () => { if (live) { transcript.push(live); live = ""; } };
			const flush = () => {
				const all = live ? [...transcript, live] : transcript;
				onUpdate?.({ content: [{ type: "text", text: all.join("\n") }], details: {} });
			};

			// Workflow dashboard (idiomatic Pi setWidget pattern — see plan-mode).
			// Always-on phase tracker above the editor, TUI-only. Stage changes render
			// at once; high-rate text/log updates throttle at 200 ms.
			const DASHBOARD_KEY = "stock-analysis";
			const dashboardStages = new Map<string, { label: string; status: string }>();
			const dashboardOrder: string[] = [];
			let lastWidget = 0;
			const WIDGET_MS = 200;
			const renderDashboard = () => {
				if (ctx?.mode !== "tui") return;
				const icon = (st: string) => (st === "ok" ? "✔" : st === "failed" ? "⚠" : st === "skipped" ? "↷" : st === "running" ? "●" : "·");
				const entries = dashboardOrder.map((id) => dashboardStages.get(id)).filter(Boolean) as Array<{ label: string; status: string }>;
				const done = entries.filter((e) => e.status !== "running").length;
				const running = entries.find((e) => e.status === "running");
				// 2-column layout, column-first (left column fills before right).
				const COLS = 2;
				const rows = Math.ceil(entries.length / COLS);
				const col = (c: number) => entries.slice(c * rows, (c + 1) * rows);
				const cellWidth = 38;
				const pad = (s: string, w: number) => s.length >= w ? s.slice(0, w - 1) + "…" : s + " ".repeat(w - s.length);
				const lines = [
					`stock-analysis · ${done}/${entries.length}${running ? ` · ${icon(running.status)} ${running.label}` : ""}  (esc to abort)`,
				];
				for (let r = 0; r < rows; r++) {
					const cells: string[] = [];
					for (let c = 0; c < COLS; c++) {
						const e = col(c)[r];
						if (e) cells.push(pad(`  ${icon(e.status)} ${e.label}`, cellWidth));
					}
					lines.push(cells.join(""));
				}
				try { ctx?.ui?.setWidget?.(DASHBOARD_KEY, lines); } catch { /* best-effort */ }
			};
			const renderDashboardThrottled = () => { const now = Date.now(); if (now - lastWidget >= WIDGET_MS) { renderDashboard(); lastWidget = now; } };

			const sink = {
				phase: (label: string) => { finalizeLive(); transcript.push(`▶ ${label}`); renderDashboard(); flush(); },
				log: (message: string) => { finalizeLive(); transcript.push(`  ${message}`); renderDashboardThrottled(); flush(); },
				text: (partial: string) => {
					live = partial;
						const now = Date.now();
					if (now - lastFlush >= FLUSH_MS) { flush(); lastFlush = now; renderDashboardThrottled(); }
				},
				stage: (info: { id: string; label: string; status: string }) => {
					if (!dashboardOrder.includes(info.id)) dashboardOrder.push(info.id);
					dashboardStages.set(info.id, { label: info.label, status: info.status });
					renderDashboard();
				},
			};

			try {
				const state = buildInitialState(params as ToolParams, { extensionRoot: EXTENSION_ROOT, cwd: process.cwd() });
				const summary = await runWorkflow(
					STOCK_ANALYSIS_WORKFLOW,
					state,
					{
						cwd: process.cwd(),
						model: params.model as string | undefined,
						maxAgents: typeof params.maxAgents === "number" ? params.maxAgents : undefined,
						progress: sink,
						signal,
					},
				);
				const summaryLines = formatSummary(summary, process.cwd());
				// Preserve the full run log to disk.
				let logPath = "";
				try {
					const logDir = join(process.cwd(), ".stock-analysis-logs");
					mkdirSync(logDir, { recursive: true });
					logPath = join(logDir, `${state.runId}.log`);
					writeFileSync(logPath, transcript.join("\n") + "\n");
				} catch { /* best-effort */ }
				if (logPath) summaryLines.push(`Full run log: ${logPath}`);
				if (logPath) summaryLines.push(`Full run log: ${logPath}`);
				const isError = summary.status === "failed";
				// Stages for renderResult’s stage-progress section, from the live tracker.
				finalizeLive();
				const stages = dashboardOrder.map((id) => ({ id, ...(dashboardStages.get(id) ?? { label: id, status: "·" }) }));
				// content = text fallback (print/json/headless); details = data for renderResult (TUI).
				const fallback = [...summaryLines];
				return {
					content: [{ type: "text", text: fallback.join("\n") }],
					isError,
					details: { summary, summaryLines, transcriptTail: transcript.slice(-50), stages, logPath },
				};
			} catch (err) {
				const message = err instanceof Error ? err.message : String(err);
				return { content: [{ type: "text", text: `❌ stock-analysis pipeline failed: ${message}` }], isError: true, details: {} };
			} finally {
				// Always clear the dashboard widget when the run ends (success or failure).
				try { ctx?.ui?.setWidget?.(DASHBOARD_KEY, undefined); } catch { /* best-effort */ }
			}
		},
		// Pi-native result rendering: 3 sections. §1 detail logs DIMMED (thought-like);
		// §2 stage progress NORMAL; §3 summary.
		renderResult(result, _opts: any, theme: Theme) {
			const d = (result.details ?? {}) as {
				summaryLines?: string[];
				transcriptTail?: string[];
				stages?: Array<{ label: string; status: string }>;
				logPath?: string;
			};
			// During streaming (onUpdate), details are empty — fall back to plain content.
			if (!d.stages?.length) {
				const text = result.content[0];
				return new Text(text?.type === "text" ? text.text : "", 0, 0);
			}
			const icon = (st: string) => (st === "ok" ? "✔" : st === "failed" ? "⚠" : st === "skipped" ? "↷" : st === "running" ? "●" : "·");
			const parts: string[] = [];
			// §1 detail log — DIMMED (like agent thought progress; persisted, not transient)
			parts.push(theme.fg("dim", "── detail log (last 50 lines) ──"));
			for (const line of (d.transcriptTail ?? [])) parts.push(theme.fg("dim", line));
			if (d.logPath) parts.push(theme.fg("dim", `(full log: ${d.logPath})`));
			// §2 stage progress — NORMAL (like the real answer)
			parts.push("");
			parts.push(theme.bold("── stage progress ──"));
			for (const s of (d.stages ?? [])) parts.push(`  ${icon(s.status)} ${s.label}`);
			// §3 summary — NORMAL/bold
			if (d.summaryLines?.length) {
				parts.push("");
				parts.push(...d.summaryLines);
			}
			return new Text(parts.join("\n"), 0, 0);
		},
	});

	pi.registerCommand(STOCK_ANALYSIS_COMMAND, {
		description: "Run the stock-analysis equity-research pipeline. Usage: /stock-analysis [--mode <pipeline|screen|analyze|compare|walk>] [tickers|theme] [options]",
		handler: async (args, ctx) => {
			const argString = String(args ?? "").trim();
			if (!argString) {
				ctx.ui.notify(
					[
						"Usage: /stock-analysis [--mode <name>] [tickers|theme] [options]",
						"",
						"Modes:",
						"  /stock-analysis --mode pipeline --universe US",
						"  /stock-analysis --mode screen --top-industry 40",
						"  /stock-analysis --mode analyze AAPL MSFT",
						"  /stock-analysis --mode compare NVDA,AMD,INTC",
						"  /stock-analysis --mode walk \"humanoid robotics\"",
						"",
						"(omit --mode to infer from the request: 'find best stocks' → pipeline, 'analyze X' → analyze, etc.)",
					].join("\n"),
					"info",
				);
				return;
			}
			const parsed = parseStockAnalysisArgs(argString);
			pi.sendUserMessage(`Use the ${STOCK_ANALYSIS_TOOL} tool to run the stock-analysis pipeline with these parameters: ${JSON.stringify(parsed)}`);
		},
	});
}
