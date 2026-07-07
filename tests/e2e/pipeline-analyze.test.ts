/**
 * End-to-end pipeline test — `analyze` mode, single US ticker.
 *
 * Drives the FULL stage-graph (Stage 0 → 19) with a mock agent runner that
 * returns pre-recorded `<control>` responses. No `pi` spawns, no network, no
 * `uv`. Validates that:
 *   - the workflow traverses every stage to completion (status "success"),
 *   - the render path produces real .md reports under reportsDir,
 *   - the deterministic cleanup sweep (Stage 19) removes intermediates.
 *
 * Gated on E2E=1 so it does not slow down the default `npm test` run; it is
 * otherwise hermetic and safe to run anywhere.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync, readdirSync, readFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { STOCK_ANALYSIS_WORKFLOW } from "../../src/stages/index.ts";
import { runWorkflow } from "../../src/workflow.ts";
import type { StockAnalysisState } from "../../src/types.ts";
import { mockAgent } from "./fixtures.ts";

const SKIP = process.env.E2E !== "1";
const itOrSkip = SKIP ? it.skip : it;

let reportsDir: string;
let fakeRoot: string;

// Resolve the real templates/ dir (sibling of src/) so the render path can load
// Nunjucks templates without pointing extensionRoot at the package root (which
// would trigger `uv sync` via ensurePythonEnv and break hermeticity).
const TEMPLATES_DIR = join(fileURLToPath(new URL(".", import.meta.url)), "..", "..", "templates");

function buildState(): StockAnalysisState {
	reportsDir = mkdtempSync(join(tmpdir(), "e2e-analyze-"));
	// Fake root: has templates/ (symlink) but NO pyproject.toml → uv sync skipped.
	fakeRoot = mkdtempSync(join(tmpdir(), "e2e-fake-root-"));
	symlinkSync(TEMPLATES_DIR, join(fakeRoot, "templates"));
	return {
		mode: "analyze",
		tickers: ["AAPL"],
		topIndustry: 8,
		totalCompany: 15,
		topPrice: 200,
		minHeadroom: 5,
		days: 1,
		universe: "US",
		runId: "202601010000",
		reportsDir,
		backend: "subprocess",
		extensionRoot: fakeRoot,
		companies: [{ ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", subIndustry: "Consumer Electronics" }] as never,
		reports: [],
		tracking: { completed: [], skipped: [], failures: [], gateResults: [], startedAt: "2026-01-01T00:00:00Z" },
	};
}

beforeEach(() => {
	// reportsDir is created inside buildState (called per-test).
});

afterEach(() => {
	if (reportsDir) rmSync(reportsDir, { recursive: true, force: true });
	if (fakeRoot) rmSync(fakeRoot, { recursive: true, force: true });
});

describe.skipIf(SKIP)("e2e: pipeline analyze (recorded fixtures)", () => {
	itOrSkip("completes all stages and renders 3 horizon reports for one ticker", async () => {
		const state = buildState();

		const summary = await runWorkflow(STOCK_ANALYSIS_WORKFLOW, state, {
			agentRunner: mockAgent,
		});

		// ── the pipeline reached the end without aborting ──────────────────
		expect(summary.status).toBe("success");
		expect(summary.error).toBeUndefined();
		expect(summary.mode).toBe("analyze");

		// ── the render path wrote real reports ─────────────────────────────
		// 1 company × 3 horizons = 3 equity reports.
		expect(summary.reports.length).toBe(3);
		const tickers = summary.reports.map((r) => r.ticker);
		expect(tickers.every((t) => t === "AAPL")).toBe(true);
		const horizons = summary.reports.map((r) => r.horizon).sort();
		expect(horizons).toEqual(["long", "mid", "short"]);

		// The .md files exist on disk and are non-empty.
		for (const r of summary.reports) {
			expect(existsSync(r.path)).toBe(true);
			const content = readFileSync(r.path, "utf8");
			expect(content.length).toBeGreaterThan(100);
		}

		// ── best-picks highlight was rendered ──────────────────────────────
		expect(existsSync(join(reportsDir, "HIGHLIGHTS_BEST_PICKS.md"))).toBe(true);

		// ── Stage 19 deterministic cleanup ran ─────────────────────────────
		// No intermediate stage*/phase*/raw-data* files survive.
		const allFiles = readdirSync(reportsDir);
		const leftovers = allFiles.filter((f) => /^(stage|phase|raw[-_]data)/i.test(f));
		expect(leftovers).toEqual([]);

		// ── agent budget was exercised by the mock (not zero) ──────────────
		expect(summary.agentsSpawned).toBeGreaterThan(0);
	}, 30000);
});
