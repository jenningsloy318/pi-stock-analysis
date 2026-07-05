/**
 * runScript tests. Path-safety + arg-building are pure (no spawn). The actual
 * spawn path is exercised with `child_process.spawn` mocked at module level so
 * no real `uv`/`python` runs (hermetic).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { EventEmitter } from "node:events";
import { join } from "node:path";
import { isValidScriptName, resolveScriptPath, buildScriptArgs, runScript } from "../src/scripts.ts";

const ROOT = join(import.meta.dirname, "..");

// Hoisted mock: vi.mock is hoisted to the top of the file by vitest, so the
// `spawn` every `import("../src/scripts.ts")` resolves is this vi.fn().
const { spawnMock } = vi.hoisted(() => ({ spawnMock: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn: spawnMock }));

/** A fake child process backed by EventEmitter. */
function fakeChild(opts: { emitError?: Error; stdoutData?: string; exitCode?: number } = {}): ReturnType<typeof spawnMock> {
	const fake = new EventEmitter() as EventEmitter & {
		stdout: NodeJS.ReadableStream;
		stderr: NodeJS.ReadableStream;
		kill: (sig?: string) => void;
	};
	fake.stdout = new EventEmitter() as NodeJS.ReadableStream;
	fake.stderr = new EventEmitter() as NodeJS.ReadableStream;
	fake.kill = () => {};
	process.nextTick(() => {
		if (opts.emitError) {
			fake.emit("error", opts.emitError);
			return;
		}
		if (opts.stdoutData) (fake.stdout as EventEmitter).emit("data", Buffer.from(opts.stdoutData));
		fake.emit("close", opts.exitCode ?? 0);
	});
	return fake as unknown as ReturnType<typeof spawnMock>;
}

describe("isValidScriptName", () => {
	it("accepts plain identifiers", () => {
		expect(isValidScriptName("compute_scores")).toBe(true);
		expect(isValidScriptName("fetch-financials")).toBe(true);
		expect(isValidScriptName("validateReport3")).toBe(true);
	});
	it("rejects path separators and traversal", () => {
		expect(isValidScriptName("../etc/passwd")).toBe(false);
		expect(isValidScriptName("foo/bar")).toBe(false);
		expect(isValidScriptName("/abs/path")).toBe(false);
		expect(isValidScriptName("foo.py")).toBe(false);
		expect(isValidScriptName("")).toBe(false);
	});
});

describe("resolveScriptPath + buildScriptArgs (pure)", () => {
	it("resolves a known script under <root>/scripts/", () => {
		expect(resolveScriptPath("compute_scores", ROOT)).toBe(join(ROOT, "scripts", "compute_scores.py"));
	});
	it("returns null for an unknown script", () => {
		expect(resolveScriptPath("does_not_exist", ROOT)).toBeNull();
	});
	it("returns null for a path-traversal attempt", () => {
		expect(resolveScriptPath("../package.json", ROOT)).toBeNull();
	});
	it("builds the uv run python argv", () => {
		const argv = buildScriptArgs("compute_scores", ["--metrics", "m.json"], ROOT);
		expect(argv).not.toBeNull();
		expect(argv![0]).toBe("uv");
		expect(argv![1]).toBe("run");
		expect(argv![2]).toBe("--project");
		expect(argv![3]).toBe(ROOT);
		expect(argv![4]).toBe("python");
		expect(argv![5]).toBe(join(ROOT, "scripts", "compute_scores.py"));
		expect(argv!.slice(6)).toEqual(["--metrics", "m.json"]);
	});
});

describe("runScript (mocked spawn)", () => {
	beforeEach(() => { spawnMock.mockReset(); });

	it("rejects invalid names WITHOUT spawning (SCENARIO-032)", async () => {
		const r = await runScript("../evil", [], { root: ROOT });
		expect(r.ok).toBe(false);
		expect(r.error).toMatch(/invalid script name/);
		expect(spawnMock).not.toHaveBeenCalled();
	});

	it("returns a structured error when uv is missing — never throws (SCENARIO-031)", async () => {
		spawnMock.mockImplementation(() => fakeChild({ emitError: new Error("spawn uv ENOENT") }));
		const r = await runScript("compute_scores", [], { root: ROOT, timeoutMs: 1000 });
		expect(r.ok).toBe(false);
		expect(r.error).toMatch(/spawn uv/);
	});

	it("parses JSON from stdout on success", async () => {
		spawnMock.mockImplementation(() => fakeChild({ stdoutData: 'log\n{"score": 9, "rating": "BUY"}', exitCode: 0 }));
		const r = await runScript("compute_scores", [], { root: ROOT, timeoutMs: 1000 });
		expect(r.ok).toBe(true);
		expect(r.json).toEqual({ score: 9, rating: "BUY" });
	});

	it("returns ok:false with stderr tail on non-zero exit (never throws)", async () => {
		spawnMock.mockImplementation(() => fakeChild({ stdoutData: "", exitCode: 2 }));
		const r = await runScript("compute_scores", [], { root: ROOT, timeoutMs: 1000 });
		expect(r.ok).toBe(false);
		expect(r.exitCode).toBe(2);
	});
});
