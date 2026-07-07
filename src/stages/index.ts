/**
 * The stock-analysis workflow, expressed as a tree of control-flow nodes.
 *
 * This is the declarative pipeline definition (rule "no-pause": Stage 0 → 19
 * runs continuously). To customize:
 *   - Remove a stage: delete the node from the sequence.
 *   - Reorder: move nodes (mind data dependencies — a node reads upstream
 *     artifacts by state key, e.g. `state["stage-1"]` is shared data).
 *   - Add a stage: write a `Stage`, wrap in `task`/`writerTask`, insert.
 *   - Change control flow: swap a `task` for `branch`/`gate`/`loop`/`parallel`/
 *     `retry`/`map`/`wait`/`tryCatch` from `nodes.ts`.
 *
 * The runner (`workflow.ts`) never changes.
 *
 *   ROOT = choose(state.mode)
 *     pipeline: 0→1→[gate 1.5]→2→3→4→[gate 4.5]→[map 5-15 waves]→16→[gate 16.5]
 *               →16.6→16.7→17→[map 17.4]→[gate 17.5]→18→[gate 18.5]→19
 *     screen:   0→1→[gate 1.5]→2→3→4→[gate 4.5]→17→[map 17.4]→[gate 17.5]→18→[gate 18.5]→19
 *     analyze:  0→1→[gate 1.5]→[map 5-15 waves]→16→[gate 16.5]→16.6→16.7→17→…→19
 *     compare:  0→1→[gate 1.5]→[map 5-15 waves]→16→[gate 16.5]→16.6→16.7→17→…→19
 *     walk:     0→1→[gate 1.5]→walk(roadmap-walker)→[map 5-15 top 3-5]→16→…→19
 */

import { existsSync } from "node:fs";
import { join } from "node:path";
import {
	task, sequence, branch, choose, parallel, retry, gate, map, noop,
	writerTask, gateValidator,
} from "../nodes.ts";
import type { Node, StockAnalysisState, StageContext } from "../types.ts";
import { isAshTicker } from "../helpers.ts";
import {
	stagePrompt, dataCollectorBody, sectorScreenerBody, companyScreenerBody,
	roadmapWalkerBody, perCompanyAnalystBody, scorerBody, adversarialBody,
	judgePanelBody, reportPayloadBody, screeningReportPayloadBody, bestPicksPayloadBody,
} from "../prompts.ts";
import { ensurePythonEnv } from "../scripts.ts";
import { renderDocTask, renderReportsTask, renderScreeningReportsTask } from "../render-node.ts";
import { sweepIntermediateFiles } from "../cleanup.ts";
import { EquityReportPayload, ScreeningReportPayload, BestPicksPayload } from "../render-schemas.ts";

// ─── Predicates ─────────────────────────────────────────────────────────────

const modeIs = (m: string) => (s: StockAnalysisState) => s.mode === m;
const isPipelineOrScreen = (s: StockAnalysisState) => s.mode === "pipeline" || s.mode === "screen";
const isNotScreen = (s: StockAnalysisState) => s.mode !== "screen";
const isWalk = modeIs("walk");

/** Stage 15 (A-share) runs only for the current company when it's a .SH/.SZ ticker. */
const companyIsAsh = (s: StockAnalysisState) => !!s.company && isAshTicker(s.company.ticker);

// ─── Leaf stages ────────────────────────────────────────────────────────────

/** Stage 0 — Setup. FATAL: mode detect, ticker normalize, RUN_ID, reports dir,
 *  tracking.json. Implemented in extension.ts (it owns the tool params); this
 *  stage just records the phase banner so the pipeline is observable. */
const setupStage = task({
	id: "stage-0",
	label: "Stage 0 — Setup",
	fatal: true,
	async run(s, ctx) {
		ctx.log(`Setup: mode=${s.mode} runId=${s.runId} tickers=[${s.tickers.join(",")}]`);
		// Preflight: create/sync the package .venv (tickflow, akshare, scipy, …)
		// via `uv sync --project root` ONCE so every later `uv run --project root
		// python …` is instant + deterministic. Heavy on first run (minutes);
		// <1s after. Gated on pyproject.toml so hermetic tests (fake root) skip it;
		// non-fatal on failure (scripts surface per-script errors if env is broken).
		if (existsSync(join(s.extensionRoot, "pyproject.toml"))) {
			ctx.log("Setup: ensuring Python environment (uv sync — first run may take several minutes)…");
			const env = await ensurePythonEnv(s.extensionRoot, { signal: ctx.signal, sink: { log: (m) => ctx.log(m) } });
			ctx.log(env.ok ? "Setup: Python environment ready ✓" : `Setup: ⚠️ env sync failed (non-fatal, scripts may error): ${env.error}`);
		}
		s.tracking.completed.push("stage-0");
		return { runId: s.runId, mode: s.mode };
	},
});

/** Stage 1 — Data Collection (shared, fetched ONCE). */
const dataCollectorStage = writerTask({
	id: "stage-1",
	label: "Stage 1 — Data Collection",
	agent: "data-collector",
	controlKeys: ["status", "files", "notes"],
	buildPrompt: (s) => stagePrompt(s, "stage-1", dataCollectorBody(s), { controlKeys: ["status", "files", "notes"] }),
});

/** Stage walk — Bottleneck Walk (roadmap-walker). Replaces Stages 2-4 in walk mode. */
const roadmapWalkerStage = writerTask({
	id: "stage-walk",
	label: "Stage walk — Bottleneck Walk",
	agent: "roadmap-walker",
	controlKeys: ["candidates", "chain", "roadmap"],
	buildPrompt: (s) => stagePrompt(s, "stage-walk", roadmapWalkerBody(s), { controlKeys: ["candidates", "chain", "roadmap"] }),
});

/** Stage 2 — Sub-Industry Screening. */
const sectorScreenerStage = writerTask({
	id: "stage-2",
	label: "Stage 2 — Sub-Industry Screening",
	agent: "sector-screener",
	controlKeys: ["subIndustries"],
	buildPrompt: (s) => stagePrompt(s, "stage-2", sectorScreenerBody(s), { controlKeys: ["subIndustries"] }),
});

/** Stage 4 — Company Screening (price/headroom/universe filters applied HERE only). */
const companyScreenerStage = writerTask({
	id: "stage-4",
	label: "Stage 4 — Company Screening",
	agent: "company-screener",
	controlKeys: ["companies", "subIndustries", "priceFilterApplied", "headroomFilterApplied"],
	buildPrompt: (s) => stagePrompt(s, "stage-4", companyScreenerBody(s), { controlKeys: ["companies", "priceFilterApplied", "headroomFilterApplied"] }),
});

// ─── Per-company analyst stages (5-15) ──────────────────────────────────────
// Each wrapped in retry({attempts:10}) for the retry-on-null rule. The current
// company is exposed at state.company by the enclosing map() node.

function analystStage(stageId: string, label: string, agent: string): Node {
	return retry(
		{ attempts: 10 },
		task(writerTask({
			id: stageId,
			label,
			agent,
			controlKeys: ["findings"],
			buildPrompt: (s) => stagePrompt(s, stageId, perCompanyAnalystBody(stageId, s), { controlKeys: ["findings"] }),
		})),
	);
}

const stage5 = analystStage("stage-5", "Stage 5 — Financial Health", "fundamental-analyst");
const stage6 = analystStage("stage-6", "Stage 6 — Earnings Quality", "fundamental-analyst");
const stage7 = analystStage("stage-7", "Stage 7 — Industry & Competitive", "industry-analyst");
const stage8 = analystStage("stage-8", "Stage 8 — Supply Chain", "supply-chain-analyst");
const stage9 = analystStage("stage-9", "Stage 9 — Macro & Geopolitics", "macro-analyst");
const stage10 = analystStage("stage-10", "Stage 10 — Valuation", "quant-analyst");
const stage11 = analystStage("stage-11", "Stage 11 — Market Regime", "quant-analyst");
const stage12 = analystStage("stage-12", "Stage 12 — Risk Assessment", "risk-analyst");
const stage13 = analystStage("stage-13", "Alt Data & Digital", "alt-data-analyst");
const stage14 = analystStage("stage-14", "Catalyst Intelligence", "catalyst-analyst");
const stage15 = analystStage("stage-15", "Stage 15 — A-Share Analysis", "china-market-analyst");

/**
 * The per-company dependency DAG (rule "dependencies": 4 waves).
 *   wave 1: [5, 7, 9, 13]            — all independent
 *   wave 2: [6, 8, 10, 14]           — 6←5, 8←7, 10←5+7, 14←13
 *   wave 3: [11, 12]                 — 11←10, 12←10
 *   wave 4: [15]                     — A-share only (←all)
 *
 * NOTE on concurrency (ISS-03): the OUTER `map` caps COMPANY-level parallelism
 * at 4; the INNER `parallel` caps STAGE-level parallelism within one company.
 * Two independent dials.
 */
const perCompanyDag: Node = sequence([
	parallel([stage5, stage7, stage9, stage13], { concurrency: 4, tolerant: true }),
	parallel([stage6, stage8, stage10, stage14], { concurrency: 4, tolerant: true }),
	parallel([stage11, stage12], { concurrency: 2, tolerant: true }),
	// Stage 15 (A-share) is conditional on the current company's ticker suffix.
	branch(companyIsAsh, { yes: stage15, no: noop() }),
]);

/** Fan out the per-company DAG over all selected companies (max 4 at once). */
const perCompanyBlock: Node = map(
	{ over: (s: StockAnalysisState) => s.companies, as: "company", concurrency: 4 },
	perCompanyDag,
);

// ─── Scoring + adversarial + judge panel (16 / 16.6 / 16.7) ─────────────────

const scorerStage = writerTask({
	id: "stage-16",
	label: "Stage 16 — Scoring & Cross-Check",
	agent: "scorer",
	controlKeys: ["companies"],
	buildPrompt: (s) => stagePrompt(s, "stage-16", scorerBody(s), { controlKeys: ["companies"] }),
});

/** 16.6 — Adversarial Verify: 3 skeptics per top-5 pick, survives if ≥2/3 don't refute. */
const adversarialStage: Node = map(
	{
		over: (s: StockAnalysisState) => {
			const scored = (s.scoring?.companies ?? []) as Array<{ ticker: string }>;
			return scored.slice(0, 5);
		},
		as: "pick",
		concurrency: 5,
		into: "adversarial",
	},
	retry(
		{ attempts: 10 },
		task(writerTask({
			id: "stage-16.6",
			label: "Stage 16.6 — Adversarial Verify",
			agent: "risk-analyst",
			controlKeys: ["survived", "skeptics"],
			buildPrompt: (s) => stagePrompt(s, "stage-16.6", adversarialBody(s), { controlKeys: ["survived", "skeptics"] }),
		})),
	),
);

/** 16.7 — Judge Panel: 4 framework lenses in parallel. */
const judgePanelStage: Node = retry(
	{ attempts: 10 },
	task(writerTask({
		id: "stage-16.7",
		label: "Stage 16.7 — Judge Panel",
		agent: "quant-analyst",
		controlKeys: ["lenses", "disagreements", "positionType"],
		buildPrompt: (s) => stagePrompt(s, "stage-16.7", judgePanelBody(s), { controlKeys: ["lenses", "disagreements"] }),
	})),
);

// ─── Reports + critic (17 / 17.4) ───────────────────────────────────────────

/** Stage 17 — one schema-validated payload → template render per company ×
 *  horizon (templates/equity-report.njk). The agent emits content; the template
 *  owns all formatting. */
const renderReportsStage = renderReportsTask({
	id: "stage-17",
	label: "Stage 17 — Report Generation (rendered)",
	agent: "equity-report-writer",
	controlKeys: ["report"],
	payloadKey: "report",
	schema: EquityReportPayload,
	templateForHorizon: (_h) => "equity-report.njk",
	outputPathFor: (s, job) => join(s.reportsDir, job.company.ticker, `${job.company.ticker}_${job.horizon}.md`),
	buildPrompt: (s, _ctx, job) => stagePrompt(s, "stage-17", reportPayloadBody(job.company, job.horizon), { controlKeys: ["report"] }),
});

/** Stage 17 screen-mode (rendered) — one sector-level screening report per
 *  horizon via templates/screening-report.njk. Same agent as the equity path. */
const screenReportsRenderStage = renderScreeningReportsTask({
	id: "stage-17",
	label: "Stage 17 — Screening Report (rendered)",
	agent: "equity-report-writer",
	controlKeys: ["report"],
	payloadKey: "report",
	schema: ScreeningReportPayload,
	templateName: "screening-report.njk",
	outputPathFor: (s, horizon) => join(s.reportsDir, `SCREEN_${horizon}.md`),
	buildPrompt: (s, _ctx, horizon) => stagePrompt(s, "stage-17", screeningReportPayloadBody(horizon, s), { controlKeys: ["report"] }),
});

/** 17.4 — Completeness Critic: one critic per report. */
const completenessCriticStage: Node = map(
	{
		over: (s: StockAnalysisState) => (s.reports ?? []).map((r) => r.path),
		as: "reportPath",
		concurrency: 4,
		into: "criticFindings",
	},
	task(writerTask({
		id: "stage-17.4",
		label: "Stage 17.4 — Completeness Critic",
		agent: "report-validator",
		controlKeys: ["findings", "severity"],
		buildPrompt: (s) => stagePrompt(s, "stage-17.4", "One critic per report. Detect missing modality/claim/source (HIGH/MEDIUM/LOW). Verify kill-switch falsifiability.", { controlKeys: ["findings", "severity"] }),
	})),
);

// ─── Best picks + cleanup (18 / 19) ────────────────────────────────────────

/** Stage 18 — HIGHLIGHTS_BEST_PICKS.md from a BestPicksPayload via
 *  templates/best-picks.njk. */
const bestPicksRenderStage = task(renderDocTask({
	id: "stage-18",
	label: "Stage 18 — Best Picks Highlight (rendered)",
	agent: "equity-report-writer",
	controlKeys: ["bestPicks"],
	payloadKey: "bestPicks",
	schema: BestPicksPayload,
	templateName: "best-picks.njk",
	outputPath: (s) => join(s.reportsDir, "HIGHLIGHTS_BEST_PICKS.md"),
	buildPrompt: (s) => stagePrompt(s, "stage-18", bestPicksPayloadBody(s), { controlKeys: ["bestPicks"] }),
}));

/** Stage 19 — Cleanup (ALWAYS last). Deterministic allow-list sweep: deletes
 *  intermediate artifacts (stage_*, phase_*, raw-data_*) from state.reportsDir,
 *  preserves final reports + HIGHLIGHTS_BEST_PICKS.md + workflow-tracking.json. */
const cleanupStage = task({
	id: "stage-19",
	label: "Stage 19 — Cleanup",
	async run(s, ctx) {
		const keepPaths = (s.reports ?? []).map((r) => r.path);
		const { removed } = sweepIntermediateFiles(s.reportsDir, keepPaths);
		ctx.log(`Cleanup: removed ${removed.length} intermediate file(s) from ${s.reportsDir}`);
		return { cleanup: "done", removed: removed.length };
	},
});

// ─── Quality gates (1.5 / 4.5 / 16.5 / 17.5 / 18.5) ─────────────────────────
// Each gate re-runs its writer up to `attempts` until the validator passes; on
// exhaustion it logs + continues (non-fatal). Validators live in gates.ts and
// are non-vacuous (no output ⇒ FAIL, never a silent pass).

const gateSharedData = gate(
	{ validate: gateValidator("gate-shared-data", "stage-1"), attempts: 4, feedbackKey: "sharedData" },
	task(dataCollectorStage),
);

const gateScreening = gate(
	{ validate: gateValidator("gate-screening", "stage-4"), attempts: 4, feedbackKey: "screening" },
	task(companyScreenerStage),
);

const gateScoring = gate(
	{ validate: gateValidator("gate-scoring", "stage-16"), attempts: 4, feedbackKey: "scoring" },
	task(scorerStage),
);

const gateReports = gate(
	{ validate: gateValidator("gate-reports", "stage-17"), attempts: 4, feedbackKey: "reports" },
	// Render path only: schema-validated, template-rendered reports. screen
	// mode → one sector report per horizon; other modes → per-company equity
	// reports (one per horizon).
	choose(
		[{ when: (s) => s.mode === "screen", run: task(screenReportsRenderStage) }],
		task(renderReportsStage),
	),
);

const gateBestPicks = gate(
	{ validate: gateValidator("gate-best-picks", "stage-18"), attempts: 4, feedbackKey: "bestPicks" },
	bestPicksRenderStage,
);

// ─── The common tail: critic → report-validation-gate → best-picks-gate → cleanup ─
// (Stages 17.5 report-validation is folded into gateReports above; 18.5 into
//  gateBestPicks. The critic always runs after reports; cleanup always last.)

const reportTail: Node = sequence([
	completenessCriticStage,
	gateBestPicks,
	cleanupStage,
], { tolerant: true });

// ─── Per-mode stage sequences ───────────────────────────────────────────────
// Composed per the SKILL.md <modes> stage lists. Each is a tolerant sequence so
// a single failing analyst never aborts the whole run.

const pipelineSequence: Node = sequence([
	setupStage,
	gateSharedData,
	task(sectorScreenerStage),
	task(companyScreenerStage),
	gateScreening,
	perCompanyBlock,
	gateScoring,
	adversarialStage,
	judgePanelStage,
	gateReports,
	reportTail,
], { tolerant: true });

const screenSequence: Node = sequence([
	setupStage,
	gateSharedData,
	task(sectorScreenerStage),
	task(companyScreenerStage),
	gateScreening,
	gateReports,
	reportTail,
], { tolerant: true });

const analyzeSequence: Node = sequence([
	setupStage,
	gateSharedData,
	perCompanyBlock,
	gateScoring,
	adversarialStage,
	judgePanelStage,
	gateReports,
	reportTail,
], { tolerant: true });

// compare is structurally identical to analyze (the contract difference —
// identical valuation methodology, max 5 — is enforced in setup validation).
const compareSequence: Node = analyzeSequence;

const walkSequence: Node = sequence([
	setupStage,
	gateSharedData,
	task(roadmapWalkerStage),
	perCompanyBlock, // operates on the top 3-5 candidates roadmap-walker selected
	gateScoring,
	adversarialStage,
	judgePanelStage,
	gateReports,
	reportTail,
], { tolerant: true });

// ─── ROOT: mode dispatch via choose() ───────────────────────────────────────

export const STOCK_ANALYSIS_WORKFLOW: Node = choose(
	[
		{ when: modeIs("pipeline"), run: pipelineSequence },
		{ when: modeIs("screen"), run: screenSequence },
		{ when: modeIs("analyze"), run: analyzeSequence },
		{ when: modeIs("compare"), run: compareSequence },
		{ when: isWalk, run: walkSequence },
	],
	// Defensive default: pipeline.
	pipelineSequence,
);

// Re-exports for users composing custom workflows.
export {
	task, sequence, branch, choose, parallel, retry, gate, map, noop, writerTask, gateValidator,
};
export type { Node, StageContext };
