/**
 * TUI workflow dashboard — formatDashboardLines (pure renderer) + stage-event
 * flow through the node algebra. Hermetic: no pi spawns, no TUI, no network.
 */

import { describe, it, expect } from "vitest";
import { formatDashboardLines } from "../src/extension.ts";
import { task, sequence } from "../src/nodes.ts";
import { runWorkflow } from "../src/workflow.ts";
import { STOCK_ANALYSIS_WORKFLOW } from "../src/stages/index.ts";
import { mockAgent } from "./e2e/fixtures.ts";
import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import type { StockAnalysisState, StageProgressEvent } from "../src/types.ts";

const E = (id: string, label: string, status: string) => ({ id, label, status });

describe("formatDashboardLines", () => {
	it("renders a header with done/total count and status icons", () => {
		const lines = formatDashboardLines([
			E("stage-0", "Stage 0 — Setup", "ok"),
			E("stage-1", "Stage 1 — Data Collection", "running"),
			E("stage-2", "Stage 2 — Screening", "skipped"),
		]);
		// 2 of 3 are terminal (ok + skipped); running is not counted as done.
		expect(lines[0]).toBe("stock-analysis · 2/3 stages");
		expect(lines[1]).toContain("✔ Stage 0");
		expect(lines[2]).toContain("● Stage 1");
		expect(lines[3]).toContain("↷ Stage 2");
	});

	it("uses ⚠ for failed stages", () => {
		const lines = formatDashboardLines([E("stage-9", "Stage 9 — Macro", "failed")]);
		expect(lines[1]).toContain("⚠ Stage 9");
	});

	it("appends the live-activity row when provided", () => {
		const lines = formatDashboardLines([E("stage-0", "Setup", "ok")], "Analyzing AAPL financials…");
		expect(lines.some((l) => l.includes("▶ Analyzing AAPL financials…"))).toBe(true);
	});

	it("omits the activity row when empty", () => {
		const lines = formatDashboardLines([E("stage-0", "Setup", "ok")]);
		expect(lines.some((l) => l.startsWith("  ▶"))).toBe(false);
	});

	it("always shows the esc-to-abort hint", () => {
		const lines = formatDashboardLines([E("stage-0", "Setup", "running")]);
		expect(lines[lines.length - 1]).toContain("esc to abort");
	});

	it("truncates long activity to a single line", () => {
		const long = "x".repeat(200);
		const lines = formatDashboardLines([], long);
		const activityLine = lines.find((l) => l.includes("▶"))!;
		expect(activityLine.length).toBeLessThan(120);
		expect(activityLine).toContain("…");
	});
});

describe("stage-event flow through the pipeline", () => {
	it("emits running → ok stage events for every task() node", async () => {
		const events: StageProgressEvent[] = [];
		let reportsDir: string;
		let fakeRoot: string;
		const TEMPLATES_DIR = join(fileURLToPath(new URL(".", import.meta.url)), "..", "templates");

		reportsDir = mkdtempSync(join(tmpdir(), "dash-evt-"));
		fakeRoot = mkdtempSync(join(tmpdir(), "dash-root-"));
		symlinkSync(TEMPLATES_DIR, join(fakeRoot, "templates"));

		const state: StockAnalysisState = {
			mode: "analyze", tickers: ["AAPL"], topIndustry: 8, totalCompany: 15, topPrice: 200,
			minHeadroom: 5, days: 1, universe: "US", runId: "202601010000", reportsDir,
			backend: "subprocess", extensionRoot: fakeRoot,
			companies: [{ ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", subIndustry: "Consumer Electronics" }] as never,
			reports: [], tracking: { completed: [], skipped: [], failures: [], gateResults: [], startedAt: "2026-01-01T00:00:00Z" },
		};

		await runWorkflow(STOCK_ANALYSIS_WORKFLOW, state, {
			agentRunner: mockAgent,
			progress: {
				phase: () => {},
				log: () => {},
				text: () => {},
				stage: (info) => events.push(info),
			},
		});

		rmSync(reportsDir, { recursive: true, force: true });
		rmSync(fakeRoot, { recursive: true, force: true });

		// Every emitted event has the required shape.
		expect(events.length).toBeGreaterThan(10);
		for (const e of events) {
			expect(typeof e.id).toBe("string");
			expect(typeof e.label).toBe("string");
			expect(["running", "ok", "skipped", "failed", "cancelled"]).toContain(e.status);
		}

		// Stage 0 (Setup) emitted running then ok.
		const s0 = events.filter((e) => e.id === "stage-0");
		expect(s0.map((e) => e.status)).toContain("running");
		expect(s0.map((e) => e.status)).toContain("ok");

		// Stage 17 (reports) emitted running then ok (render path succeeded).
		const s17 = events.filter((e) => e.id === "stage-17");
		expect(s17.map((e) => e.status)).toContain("running");
		expect(s17.map((e) => e.status)).toContain("ok");
	});

	it("a minimal task emits running + terminal status", async () => {
		const events: StageProgressEvent[] = [];
		const noop = task({ id: "t1", label: "T1", async run() { return 42; } });
		const state = { reportsDir: "/tmp", extensionRoot: "/tmp", tracking: { completed: [], skipped: [], failures: [], gateResults: [], startedAt: "" } } as unknown as StockAnalysisState;
		await runWorkflow(sequence([noop]), state, {
			progress: { phase: () => {}, log: () => {}, text: () => {}, stage: (i) => events.push(i) },
		});
		expect(events.map((e) => e.status)).toEqual(["running", "ok"]);
	});
});
