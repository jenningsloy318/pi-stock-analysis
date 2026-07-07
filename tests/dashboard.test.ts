/**
 * TUI workflow dashboard — packDashboardLines (pure renderer) + stage-event
 * flow through the node algebra. Hermetic: no pi spawns, no TUI, no network.
 */

import { describe, it, expect } from "vitest";
import { packDashboardLines, padTruncate } from "../src/extension.ts";
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

describe("packDashboardLines", () => {
	it("header shows done/total + current running stage + esc hint", () => {
		const lines = packDashboardLines([
			E("stage-0", "Stage 0 — Setup", "ok"),
			E("stage-1", "Stage 1 — Data", "running"),
			E("stage-2", "Stage 2 — Screen", "skipped"),
		], undefined, 120);
		// 2 of 3 terminal; running stage shown in header.
		expect(lines[0]).toContain("2/3");
		expect(lines[0]).toContain("● Stage 1 — Data");
		expect(lines[0]).toContain("esc to abort");
	});

	it("uses ⚠ for failed stages", () => {
		const lines = packDashboardLines([E("stage-9", "Stage 9 — Macro", "failed")], undefined, 120);
		expect(lines.some((l) => l.includes("⚠ Stage 9"))).toBe(true);
	});

	it("shows one activity line when provided", () => {
		const lines = packDashboardLines([E("stage-0", "Setup", "ok")], "Scanning GICS sub-industries", 120);
		expect(lines.some((l) => l === "▶ Scanning GICS sub-industries")).toBe(true);
	});

	it("omits activity line when undefined", () => {
		const lines = packDashboardLines([E("stage-0", "Setup", "ok")], undefined, 120);
		expect(lines.some((l) => l.startsWith("▶"))).toBe(false);
	});

	it("packs stages into columns based on width", () => {
		const entries = Array.from({ length: 10 }, (_, i) => E(`s${i}`, `Stage ${i}`, "ok"));
		const wide = packDashboardLines(entries, undefined, 200);
		const narrow = packDashboardLines(entries, undefined, 40);
		// Wide terminal fits more columns → fewer rows of stages.
		const wideStageRows = wide.filter((l) => l.startsWith("  ")).length;
		const narrowStageRows = narrow.filter((l) => l.startsWith("  ")).length;
		expect(wideStageRows).toBeLessThan(narrowStageRows);
		// All 10 stages appear in both.
		for (let i = 0; i < 10; i++) {
			expect(wide.some((l) => l.includes(`Stage ${i}`))).toBe(true);
			expect(narrow.some((l) => l.includes(`Stage ${i}`))).toBe(true);
		}
	});
});

describe("padTruncate", () => {
	it("pads short strings to width", () => {
		expect(padTruncate("hi", 5)).toBe("hi   ");
	});

	it("truncates long strings with ellipsis", () => {
		const result = padTruncate("hello world", 5);
		expect(result.length).toBe(5);
		expect(result).toContain("…");
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
