/**
 * The Python bridge.
 *
 * The 76 deterministic financial scripts under `scripts/*.py` are kept VERBATIM
 * (akshare + baostock provide China A-share data with no Node.js equivalent;
 * yfinance / scipy / statsmodels / arch / pandas-ta are Python-only). This
 * module is the thin TS adapter that shells out to `uv run python` so the
 * orchestration layer (the node algebra) can invoke deterministic calculations
 * as if they were native helpers.
 *
 * Contract (rule "UV Run" from the source skill):
 *   runScript("compute_scores", ["--metrics", path, ...], { root })
 *     → spawns:  uv run python <root>/scripts/compute_scores.py --metrics path ...
 *     → captures stdout/stderr, parses the last JSON object, returns { ok, json, ... }
 *
 * Safety:
 *   - `name` is validated against ^[A-Za-z0-9_-]+$ and resolved strictly under
 *     <root>/scripts/ — no path traversal, no absolute paths (SCENARIO-032).
 *   - NEVER throws: all failures become { ok: false, error } so tolerant stages
 *     continue (SCENARIO-031). A hung script is killed after `timeoutMs`.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { parseLastJson } from "./control.ts";
import type { ProgressSink, ScriptCall, ScriptResult } from "./types.ts";

/** Per-invocation wall-clock cap. Data-fetch scripts can legitimately take
 *  several minutes (akshare/baostock rate limits); default 10 minutes. */
export const DEFAULT_SCRIPT_TIMEOUT_MS = 600_000;

const NAME_RE = /^[A-Za-z0-9_-]+$/;

export interface RunScriptOptions {
	/** Package root (dir containing package.json + scripts/). REQUIRED. */
	root: string;
	/** Run cwd. Defaults supplied by the caller (usually the run's reports dir). */
	cwd?: string;
	timeoutMs?: number;
	/** Live stderr → sink.log for diagnostics (python scripts log to stderr). */
	sink?: ProgressSink;
	signal?: AbortSignal;
}

/** Validate a script name. Rejects anything with path separators / ".." / etc. */
export function isValidScriptName(name: string): boolean {
	return NAME_RE.test(name);
}

/** Resolve the absolute path for a script name under <root>/scripts/. Returns
 *  null if the name is invalid or the file does not exist. */
export function resolveScriptPath(name: string, root: string): string | null {
	if (!isValidScriptName(name)) return null;
	const path = join(root, "scripts", `${name}.py`);
	return existsSync(path) ? path : null;
}

/** Build the full argv for a script invocation (unit-testable). Element 0 is
 *  the executable (`uv`), so callers can pass it straight to child_process. */
export function buildScriptArgs(name: string, args: string[] = [], root: string): string[] | null {
	const scriptPath = resolveScriptPath(name, root);
	if (!scriptPath) return null;
	return ["uv", "run", "python", scriptPath, ...args];
}

/** Run a python script via `uv run python`. Never throws. */
export async function runScript(name: string, args: string[] = [], opts: RunScriptOptions): Promise<ScriptResult> {
	const argv = buildScriptArgs(name, args, opts.root);
	if (!argv) {
		return { ok: false, error: isValidScriptName(name) ? `script not found: ${name}` : `invalid script name: ${name}` };
	}
	const cwd = opts.cwd ?? opts.root;
	const timeoutMs = opts.timeoutMs ?? DEFAULT_SCRIPT_TIMEOUT_MS;

	return new Promise<ScriptResult>((resolve) => {
		const child = spawn(argv[0], argv.slice(1), {
			cwd,
			stdio: ["ignore", "pipe", "pipe"],
			env: { ...process.env },
			windowsHide: true,
		});

		let stdout = "";
		let stderr = "";
		let timedOut = false;
		const STDOUT_CAP = 16 * 1024 * 1024; // bounded: scripts can be verbose
		const STDERR_CAP = 64 * 1024;
		let stderrLine = "";

		const onAbort = () => {
			try { child.kill("SIGTERM"); } catch { /* ignore */ }
		};
		opts.signal?.addEventListener("abort", onAbort, { once: true });
		const timer = setTimeout(() => {
			timedOut = true;
			try { child.kill("SIGTERM"); } catch { /* ignore */ }
		}, timeoutMs);

		const finish = (result: ScriptResult) => {
			opts.signal?.removeEventListener("abort", onAbort);
			clearTimeout(timer);
			resolve(result);
		};

		child.stdout.on("data", (c: Buffer) => {
			stdout += c.toString("utf8");
			if (stdout.length > STDOUT_CAP) stdout = stdout.slice(stdout.length - STDOUT_CAP);
		});
		child.stderr.on("data", (c: Buffer) => {
			stderr += c.toString("utf8");
			if (stderr.length > STDERR_CAP) stderr = stderr.slice(stderr.length - STDERR_CAP);
			// Stream stderr line-by-line to the sink for live diagnostics.
			if (opts.sink) {
				stderrLine += c.toString("utf8");
				let nl: number;
				while ((nl = stderrLine.indexOf("\n")) >= 0) {
					const line = stderrLine.slice(0, nl).trim();
					stderrLine = stderrLine.slice(nl + 1);
					if (line) opts.sink.log(`  [${name}] ${line}`);
				}
			}
		});
		child.on("error", (err) => {
			finish({ ok: false, error: `failed to spawn uv: ${err.message}. Is 'uv' on PATH?` });
		});
		child.on("close", (code) => {
			if (opts.signal?.aborted) {
				finish({ ok: false, stdout, stderr, error: "aborted" });
				return;
			}
			if (timedOut) {
				finish({ ok: false, stdout, stderr, error: `timed out after ${Math.round(timeoutMs / 1000)}s` });
				return;
			}
			const json = parseLastJson(stdout);
			if (code === 0) {
				finish({ ok: true, stdout, stderr, json, exitCode: code });
			} else {
				const tail = stderr.trim().split("\n").slice(-4).join(" | ");
				finish({ ok: false, stdout, stderr, json, exitCode: code ?? -1, error: `exit ${code}${tail ? `: ${tail}` : ""}` });
			}
		});
	});
}

/** Convenience: run a script and throw a structured error if it fails. Used by
 *  helpers/gates where a hard failure is preferable to silent partial data. */
export async function runScriptOrThrow(name: string, args: string[], opts: RunScriptOptions): Promise<ScriptResult> {
	const result = await runScript(name, args, opts);
	if (!result.ok) {
		throw new Error(`script ${name} failed: ${result.error ?? "unknown"}`);
	}
	return result;
}

/** Dispatcher entry: accepts a ScriptCall (as issued by `ctx.script()`). */
export async function runScriptCall(call: ScriptCall, fallback: { root: string; cwd?: string; sink?: ProgressSink; signal?: AbortSignal }): Promise<ScriptResult> {
	return runScript(call.name, call.args ?? [], {
		root: fallback.root,
		cwd: call.cwd ?? fallback.cwd,
		timeoutMs: call.timeoutMs,
		sink: fallback.sink,
		signal: fallback.signal,
	});
}
