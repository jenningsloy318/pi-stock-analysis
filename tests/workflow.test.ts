/**
 * Workflow runner composition: makeContext wiring + runWorkflow produces an
 * honest summary derived from produced state (never faked). Hermetic.
 */

import { describe, it, expect } from "vitest";
import { makeContext, runWorkflow } from "../src/workflow.ts";
import { task, sequence, parallel } from "../src/nodes.ts";
import { makeState } from "./helpers/fake-context.ts";
import type { StockAnalysisState, Stage } from "../src/types.ts";

function makeStage(id: string, run: (s: StockAnalysisState) => unknown): Stage {
	return { id, label: id, async run(s) { return run(s); } };
}

describe("makeContext", () => {
	it("wires agent/helper/script/parallel/budget", () => {
		const state = makeState();
		const ctx = makeContext({
			state, task: "test", options: {}, extensionRoot: state.extensionRoot,
			log: () => {},
		});
		expect(typeof ctx.agent).toBe("function");
		expect(typeof ctx.helper).toBe("function");
		expect(typeof ctx.script).toBe("function");
		expect(typeof ctx.parallel).toBe("function");
		expect(ctx.budget.check()).toBe(true);
		expect(ctx.extensionRoot).toBe(state.extensionRoot);
	});
	it("budget.spent increments and eventually blocks", () => {
		const state = makeState();
		const ctx = makeContext({
			state, task: "test", options: { maxAgents: 2 }, extensionRoot: state.extensionRoot,
			log: () => {},
		});
		expect(ctx.budget.check()).toBe(true);
		ctx.budget.spent();
		ctx.budget.spent();
		expect(ctx.budget.check()).toBe(false);
		expect(ctx.budget.count).toBe(2);
	});
});

describe("runWorkflow", () => {
	it("evaluates a small tree and threads state", async () => {
		const state = makeState();
		const root = sequence([
			task(makeStage("a", (s) => { s.companies = [{ ticker: "X", isAsh: false }]; return 1; })),
			task(makeStage("b", () => 2)),
		]);
		const summary = await runWorkflow(root, state, {
			cwd: "/tmp", extensionRootPath: undefined as never,
			progress: undefined as never, maxAgents: 5,
		} as never);
		expect(summary.status).toBe("success");
		expect(state.companies).toEqual([{ ticker: "X", isAsh: false }]);
		expect(state["a"]).toBe(1);
		expect(state["b"]).toBe(2);
	});

	it("derives 'partial' when a stage fails but artifacts exist", async () => {
		const state = makeState();
		const root = sequence([
			task(makeStage("a", () => 1)),
			task(makeStage("b", () => { throw new Error("fail"); })),
			task(makeStage("c", (s) => { s.reports = [{ kind: "company", path: "x.md" }]; return 1; })),
		], { tolerant: true });
		const summary = await runWorkflow(root, state, { cwd: "/tmp" } as never);
		expect(summary.status).toBe("partial"); // reports exist, but a stage failed
	});

	it("derives 'failed' when no artifacts produced and a fatal stage threw", async () => {
		const state = makeState();
		const root = sequence([
			task({ id: "a", label: "a", fatal: true, async run() { throw new Error("fatal"); } }),
		]);
		const summary = await runWorkflow(root, state, { cwd: "/tmp" } as never);
		expect(summary.status).toBe("failed");
		expect(summary.error).toBe("fatal");
	});

	it("parallel within a sequence completes", async () => {
		const state = makeState();
		const root = sequence([
			parallel([
				task(makeStage("a", () => 1)),
				task(makeStage("b", () => 2)),
			], { into: "joined", join: (rs) => rs.map((r) => r.value) }),
		]);
		const summary = await runWorkflow(root, state, { cwd: "/tmp" } as never);
		expect(summary.status).toBe("success");
		expect(state["joined"]).toEqual([1, 2]);
	});
});
