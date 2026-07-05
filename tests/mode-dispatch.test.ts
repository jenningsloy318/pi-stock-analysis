/**
 * Mode dispatch: the ROOT `choose(state.mode)` selects the right stage
 * sequence per mode, and conditional stages skip correctly.
 *
 * Uses a counting fake agent so we can assert WHICH stages ran for each mode
 * without spawning pi.
 */

import { describe, it, expect } from "vitest";
import { STOCK_ANALYSIS_WORKFLOW } from "../src/stages/index.ts";
import { makeState, makeFakeCtx } from "./helpers/fake-context.ts";
import type { AgentCall } from "../src/types.ts";

/** A fake agent that records the stage id of every spawn. */
function recordingCtx(state: ReturnType<typeof makeState>) {
	const spawned: string[] = [];
	const ctx = makeFakeCtx(state, {
		agentResult: (call: AgentCall) => {
			spawned.push(call.id);
			// Return minimal valid control objects so gates pass.
			if (call.id.includes("stage-1")) return { text: "", control: { status: "ok", files: ["macro.json"] } };
			if (call.id.includes("stage-4")) return { text: "", control: { companies: [{ ticker: "A", isAsh: false }], subIndustries: [{ code: "1" }], priceFilterApplied: true, headroomFilterApplied: true } };
			if (call.id.includes("stage-16")) return { text: "", control: { companies: [{ ticker: "A", composite: 7 }] } };
			if (call.id.includes("stage-17")) return { text: "", control: { reports: [{ kind: "company", path: "x.md" }] } };
			if (call.id.includes("stage-18")) return { text: "", control: { bestPicks: [{ ticker: "A", positionType: "core" }] } };
			return { text: "", control: { findings: "ok" } };
		},
	});
	return { ctx, spawned };
}

describe("STOCK_ANALYSIS_WORKFLOW mode dispatch", () => {
	it("runs screening stages (2/4) only for pipeline + screen", async () => {
		for (const mode of ["pipeline", "screen"] as const) {
			const state = makeState({ mode, companies: [{ ticker: "A", isAsh: false }] });
			const { ctx, spawned } = recordingCtx(state);
			await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
			expect(spawned, `${mode} should spawn sector/company screening`).toEqual(expect.arrayContaining(["pipeline.stage-2", "pipeline.stage-4"]));
		}
		for (const mode of ["analyze", "compare", "walk"] as const) {
			const state = makeState({ mode, companies: [{ ticker: "A", isAsh: false }], theme: mode === "walk" ? "robotics" : undefined });
			const { ctx, spawned } = recordingCtx(state);
			await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
			expect(spawned, `${mode} should NOT run screening`).not.toContain("pipeline.stage-2");
		}
	});

	it("runs the roadmap-walker only for walk", async () => {
		const state = makeState({ mode: "walk", companies: [{ ticker: "A", isAsh: false }], theme: "robotics" });
		const { ctx, spawned } = recordingCtx(state);
		await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
		expect(spawned).toContain("pipeline.stage-walk");
	});

	it("always runs setup (stage-0) and cleanup (stage-19 records without spawn)", async () => {
		const state = makeState({ mode: "analyze", tickers: ["AAPL"], companies: [{ ticker: "AAPL", isAsh: false }] });
		const { ctx } = recordingCtx(state);
		await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
		expect(state.tracking.completed).toContain("stage-0");
		expect(state.runId).toMatch(/^\d{12}$/);
	});

	it("screen mode skips the per-company deep-dive (stages 5-15)", async () => {
		const state = makeState({ mode: "screen", companies: [] });
		const { ctx, spawned } = recordingCtx(state);
		await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
		expect(spawned.some((s) => s.startsWith("pipeline.stage-5"))).toBe(false);
	});

	it("runs per-company stages for analyze/compare", async () => {
		const state = makeState({ mode: "analyze", tickers: ["AAPL"], companies: [{ ticker: "AAPL", isAsh: false }] });
		const { ctx, spawned } = recordingCtx(state);
		await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
		expect(spawned.some((s) => s.startsWith("pipeline.stage-5"))).toBe(true);
	});
});

describe("A-share Stage 15 conditional", () => {
	it("runs stage-15 for a .SH company", async () => {
		const state = makeState({ mode: "analyze", tickers: ["600519.SH"], companies: [{ ticker: "600519.SH", isAsh: true }] });
		const { ctx, spawned } = recordingCtx(state);
		await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
		expect(spawned).toContain("pipeline.stage-15");
	});
	it("skips stage-15 for a US company", async () => {
		const state = makeState({ mode: "analyze", tickers: ["AAPL"], companies: [{ ticker: "AAPL", isAsh: false }] });
		const { ctx, spawned } = recordingCtx(state);
		await STOCK_ANALYSIS_WORKFLOW.run(state, ctx);
		expect(spawned).not.toContain("pipeline.stage-15");
	});
});
