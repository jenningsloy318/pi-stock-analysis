/**
 * Spawns `pi` child processes to run specialist agents — the subprocess
 * backend (default). The single primitive that replaces any external workflow
 * engine's agent runner. Verified invocation:
 *
 *   pi --mode json -p --no-session --no-skills --no-extensions \
 *      --tools read,bash,edit,write,ffgrep,fffind,uv \
 *      [--model <provider/id>] --system-prompt <temp-file> "Task: <prompt>"
 *
 * stdout is newline-delimited JSON; the final assistant text is in the last
 * `{"type":"message_end","message":{"role":"assistant",...}}` event.
 */

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadAgentPrompt } from "./agents.ts";
import { extractControl } from "./control.ts";
import type { AgentProgress, SpawnResult } from "./types.ts";

/** Tools every stock-analysis agent needs: file I/O, shell (for `uv run`),
 *  and the fuzzy finders. `bash` is what lets agents invoke the python scripts. */
const BASE_TOOLS = "read,bash,edit,write,ffgrep,fffind";

export function toolsForAgent(_agent: string): string {
	return BASE_TOOLS;
}

/** Per-spawn wall-clock cap. Stock-analysis agents that fetch data can be slow. */
const DEFAULT_SPAWN_TIMEOUT_MS = 480_000;

export interface SpawnAgentOptions {
	agent: string;
	prompt: string;
	cwd: string;
	model?: string;
	signal?: AbortSignal;
	id?: string;
	timeoutMs?: number;
	/** Declared control keys (ignored by the subprocess backend; accepted so the
	 *  same options object can feed both backends). */
	controlKeys?: string[];
	onProgress?: AgentProgress;
}

function resolvePiBinary(): { command: string; args: string[] } {
	const argv1 = process.argv[1] ?? "";
	if (argv1 && /\.(?:mjs|cjs|js)$/i.test(argv1)) {
		return { command: process.execPath, args: [argv1] };
	}
	return { command: "pi", args: [] };
}

export async function spawnAgent(opts: SpawnAgentOptions): Promise<SpawnResult> {
	const systemPrompt = loadAgentPrompt(opts.agent);
	const tempDir = mkdtempSync(join(tmpdir(), "stock-analysis-agent-"));
	const promptPath = join(tempDir, "agent.md");
	writeFileSync(promptPath, systemPrompt, { mode: 0o600 });

	const args = buildSpawnArgs(opts, promptPath);
	const result = await runPi(args, opts.cwd, opts.signal, opts.id ?? opts.agent, opts.timeoutMs ?? DEFAULT_SPAWN_TIMEOUT_MS, opts.onProgress);
	rmSync(tempDir, { recursive: true, force: true });
	return result;
}

/** Build the full argv vector for a specialist spawn, INCLUDING the executable
 *  as element 0 (extracted so command resolution is unit-testable). */
export function buildSpawnArgs(opts: SpawnAgentOptions, promptPath: string): string[] {
	const { command, args: prefix } = resolvePiBinary();
	const args = [
		command,
		...prefix,
		"--mode", "json", "-p", "--no-session", "--no-skills", "--no-extensions",
		"--tools", toolsForAgent(opts.agent),
		"--system-prompt", promptPath,
	];
	if (opts.model) args.push("--model", opts.model);
	args.push(`Task: ${opts.prompt}`);
	return args;
}

interface PiJsonEvent {
	type?: string;
	toolName?: string;
	args?: Record<string, unknown>;
	message?: { role?: string; model?: string; content?: Array<{ type: string; text?: string }> };
}

function assistantFromMessageEnd(ev: PiJsonEvent): { text: string; model?: string } | null {
	if (ev.type !== "message_end" || ev.message?.role !== "assistant") return null;
	const text = (ev.message.content ?? [])
		.filter((p) => p.type === "text" && typeof p.text === "string")
		.map((p) => p.text as string)
		.join("");
	return { text, model: ev.message.model };
}

type StreamEvent =
	| { kind: "text"; text: string }
	| { kind: "tool"; summary: string }
	| { kind: "turn"; n: number };

/** Strip the machine <control> block from displayed text. */
function stripControl(s: string): string {
	return s.replace(/<control>[\s\S]*?<\/control>/gi, "");
}

export function summarizeToolCall(name: string, args: Record<string, unknown> | undefined): string {
	const a = args ?? {};
	switch (name) {
		case "write": case "edit": case "read": return `${name} ${a.path ?? a.file_path ?? ""}`;
		case "bash": return `$ ${String(a.command ?? "").split("\n")[0]}`;
		case "ffgrep": case "fffind": return `${name} "${a.pattern ?? ""}"`;
		default: return name;
	}
}

/** Extract a renderable event from a parsed NDJSON line (pure). */
export function renderEvent(ev: PiJsonEvent, nextTurn: () => number): StreamEvent | null {
	switch (ev.type) {
		case "message_update": {
			const text = (ev.message?.content ?? []).filter((p) => p.type === "text").map((p) => p.text ?? "").join("");
			return text ? { kind: "text", text } : null;
		}
		case "tool_execution_start":
			return ev.toolName ? { kind: "tool", summary: summarizeToolCall(ev.toolName, ev.args) } : null;
		case "turn_start":
			return { kind: "turn", n: nextTurn() };
		default:
			return null;
	}
}

function runPi(args: string[], cwd: string, signal: AbortSignal | undefined, label: string, timeoutMs: number, onProgress?: AgentProgress): Promise<SpawnResult> {
	return new Promise((resolve, reject) => {
		const child = spawn(args[0], args.slice(1), {
			cwd,
			stdio: ["ignore", "pipe", "pipe"],
			env: { ...process.env },
			windowsHide: true,
		});
		// Bounded capture ONLY: stdout is a stream of NDJSON deltas where each
		// message_update re-emits the FULL accumulated partial — unbounded for a
		// verbose/long agent. Never buffer the whole stdout; parse line-by-line.
		let lineBuf = "";
		let lastAssistantText = "";
		let lastModel: string | undefined;
		let stderrBuf = "";
		let aborted = false;
		let timedOut = false;
		let turns = 0;
		let currentText = "";
		const STDERR_CAP = 16 * 1024;
		const LINE_CAP = 16 * 1024 * 1024;
		const cleanup = () => {
			signal?.removeEventListener("abort", onAbort);
			clearTimeout(timer);
		};
		const onAbort = () => {
			aborted = true;
			try { child.kill("SIGTERM"); } catch { /* ignore */ }
		};
		signal?.addEventListener("abort", onAbort, { once: true });
		const timer = setTimeout(() => {
			timedOut = true;
			try { child.kill("SIGTERM"); } catch { /* ignore */ }
		}, timeoutMs);

		child.stdout.on("data", (c: Buffer) => {
			lineBuf += c.toString("utf8");
			let nl: number;
			while ((nl = lineBuf.indexOf("\n")) >= 0) {
				const raw = lineBuf.slice(0, nl);
				lineBuf = lineBuf.slice(nl + 1);
				const trimmed = raw.trim();
				if (!trimmed) continue;
				let ev: PiJsonEvent;
				try { ev = JSON.parse(trimmed) as PiJsonEvent; } catch { continue; }
				const a = assistantFromMessageEnd(ev);
				if (a) {
					if (a.text) { lastAssistantText = a.text; if (a.model) lastModel = a.model; }
					if (onProgress && currentText.trim()) { onProgress.event(stripControl(currentText).trim()); currentText = ""; }
					continue;
				}
				if (!onProgress) continue;
				const se = renderEvent(ev, () => ++turns);
				if (!se) continue;
				if (se.kind === "text") {
					currentText = se.text;
					onProgress.text(stripControl(currentText));
				} else {
					if (currentText.trim()) { onProgress.event(stripControl(currentText).trim()); currentText = ""; }
					if (se.kind === "tool") onProgress.event(`→ ${se.summary}`);
					else if (se.kind === "turn" && se.n > 1) onProgress.event(`turn ${se.n}`);
				}
			}
			if (lineBuf.length > LINE_CAP) lineBuf = "";
		});
		child.stderr.on("data", (c: Buffer) => {
			stderrBuf += c.toString("utf8");
			if (stderrBuf.length > STDERR_CAP) stderrBuf = stderrBuf.slice(stderrBuf.length - STDERR_CAP);
		});
		child.on("error", (err) => {
			cleanup();
			reject(new Error(`stock-analysis [${label}]: failed to spawn pi: ${err.message}`));
		});
		child.on("close", (code) => {
			cleanup();
			if (aborted) { resolve({ text: "", control: null, error: "aborted" }); return; }
			if (lastAssistantText) {
				resolve({ text: lastAssistantText, control: extractControl(lastAssistantText), model: lastModel, error: timedOut ? `timed out after ${timeoutMs}ms (used partial output)` : undefined });
				return;
			}
			const tail = stderrBuf.trim().split("\n").slice(-3).join(" | ");
			const reason = timedOut ? `timed out after ${Math.round(timeoutMs / 1000)}s` : `produced no output (exit ${code})`;
			reject(new Error(`stock-analysis [${label}]: agent ${reason}.${tail ? ` stderr: ${tail}` : ""}`));
		});
	});
}

/** Shorten a path/string for display: cwd => ".", $HOME => "~". */
export function abbreviatePath(p: string, cwd?: string): string {
	if (!p) return p;
	let out = p;
	if (cwd && cwd.length > 1 && out.includes(cwd)) out = out.split(cwd).join(".");
	const home = process.env.HOME;
	if (home && out.startsWith(home)) out = "~" + out.slice(home.length);
	return out;
}
