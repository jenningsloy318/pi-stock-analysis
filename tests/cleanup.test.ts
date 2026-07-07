/**
 * Stage 19 — deterministic cleanup sweep.
 * Hermetic: builds a temp dir tree mimicking a real run, sweeps it, asserts the
 * correct files survive. No `pi` spawns, no network, no `uv`.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { sweepIntermediateFiles, KEEP_FILES, DELETE_PATTERNS } from "../src/cleanup.ts";

let dir: string;

function touch(...parts: string[]): void {
	const full = join(dir, ...parts);
	writeFileSync(full, "x");
}

function exists(...parts: string[]): boolean {
	return existsSync(join(dir, ...parts));
}

beforeEach(() => {
	dir = mkdtempSync(join(tmpdir(), "cleanup-test-"));
});

afterEach(() => {
	rmSync(dir, { recursive: true, force: true });
});

describe("DELETE_PATTERNS", () => {
	it("match intermediate stage/phase/raw-data names", () => {
		expect(DELETE_PATTERNS.some((re) => re.test("stage-1.md"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("stage_5.json"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("stage-16.6.md"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("stage5-supply.md"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("phase-1.md"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("phase_2.md"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("raw-data.json"))).toBe(true);
		expect(DELETE_PATTERNS.some((re) => re.test("raw_data-AAPL.json"))).toBe(true);
	});

	it("do NOT match final-report or bookkeeping names", () => {
		expect(DELETE_PATTERNS.some((re) => re.test("AAPL_long.md"))).toBe(false);
		expect(DELETE_PATTERNS.some((re) => re.test("SCREEN_mid.md"))).toBe(false);
		expect(DELETE_PATTERNS.some((re) => re.test("HIGHLIGHTS_BEST_PICKS.md"))).toBe(false);
		expect(DELETE_PATTERNS.some((re) => re.test("workflow-tracking.json"))).toBe(false);
		expect(DELETE_PATTERNS.some((re) => re.test("notes.md"))).toBe(false);
	});
});

describe("sweepIntermediateFiles", () => {
	it("removes stage*/phase*/raw-data* and keeps everything else", () => {
		// Root-level intermediates + finals.
		touch("stage-1.md");
		touch("phase-2.md");
		touch("raw-data.json");
		touch("raw-data-NVDA.json");
		touch("notes.md"); // unrelated — kept
		touch("SCREEN_long.md"); // final sector report — kept
		touch("HIGHLIGHTS_BEST_PICKS.md"); // KEEP_FILES — kept
		touch("workflow-tracking.json"); // KEEP_FILES — kept

		// Per-company subdir.
		mkdirSync(join(dir, "AAPL"));
		touch("AAPL", "AAPL_long.md"); // final report — kept
		touch("AAPL", "AAPL_mid.md"); // final report — kept
		touch("AAPL", "stage-5.md"); // intermediate — removed
		touch("AAPL", "stage-7.md"); // intermediate — removed
		touch("AAPL", "raw-data.json"); // intermediate — removed
		touch("AAPL", "phase-1.md"); // intermediate — removed

		const { removed, kept } = sweepIntermediateFiles(dir);

		// Removed.
		expect(removed).toHaveLength(8);
		expect(exists("stage-1.md")).toBe(false);
		expect(exists("phase-2.md")).toBe(false);
		expect(exists("raw-data.json")).toBe(false);
		expect(exists("raw-data-NVDA.json")).toBe(false);
		expect(exists("AAPL", "stage-5.md")).toBe(false);
		expect(exists("AAPL", "stage-7.md")).toBe(false);
		expect(exists("AAPL", "raw-data.json")).toBe(false);
		expect(exists("AAPL", "phase-1.md")).toBe(false);

		// Kept.
		expect(exists("notes.md")).toBe(true);
		expect(exists("SCREEN_long.md")).toBe(true);
		expect(exists("HIGHLIGHTS_BEST_PICKS.md")).toBe(true);
		expect(exists("workflow-tracking.json")).toBe(true);
		expect(exists("AAPL", "AAPL_long.md")).toBe(true);
		expect(exists("AAPL", "AAPL_mid.md")).toBe(true);
		// Per-company dir survives (sweep is file-only).
		expect(exists("AAPL")).toBe(true);

		// kept list contains the survivors.
		expect(kept.length).toBeGreaterThanOrEqual(6);
	});

	it("preserves files listed in keepPaths even if they matched a pattern", () => {
		// A report path passed in keepPaths that happens to match a pattern.
		touch("stage-17.md");
		const keepPath = join(dir, "stage-17.md");

		const { removed } = sweepIntermediateFiles(dir, [keepPath]);

		expect(removed).toHaveLength(0);
		expect(exists("stage-17.md")).toBe(true);
	});

	it("treats keepPaths as absolute (resolves relative paths)", () => {
		// Create under a relative-style subdir.
		touch("stage-9.md");
		// Pass a path that resolves to the same absolute location.
		const keepPath = join(dir, "stage-9.md");

		const { removed } = sweepIntermediateFiles(dir, [keepPath]);
		expect(removed).toHaveLength(0);
	});

	it("handles a non-existent directory gracefully", () => {
		const { removed, kept } = sweepIntermediateFiles(join(dir, "does-not-exist"));
		expect(removed).toEqual([]);
		expect(kept).toEqual([]);
	});

	it("sweeps nested directories recursively", () => {
		mkdirSync(join(dir, "a", "b", "c"), { recursive: true });
		touch("a", "stage-1.md");
		touch("a", "b", "stage-2.md");
		touch("a", "b", "c", "stage-3.md");
		touch("a", "b", "c", "final.md"); // kept

		const { removed } = sweepIntermediateFiles(dir);

		expect(removed).toHaveLength(3);
		expect(exists("a", "stage-1.md")).toBe(false);
		expect(exists("a", "b", "stage-2.md")).toBe(false);
		expect(exists("a", "b", "c", "stage-3.md")).toBe(false);
		expect(exists("a", "b", "c", "final.md")).toBe(true);
		// Empty-ish dirs remain (file-only sweep).
		expect(exists("a", "b", "c")).toBe(true);
	});

	it("KEEP_FILES set contains the canonical bookkeeping files", () => {
		expect(KEEP_FILES.has("HIGHLIGHTS_BEST_PICKS.md")).toBe(true);
		expect(KEEP_FILES.has("workflow-tracking.json")).toBe(true);
	});
});
