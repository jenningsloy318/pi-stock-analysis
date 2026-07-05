/**
 * Control-flow node algebra semantics: task/sequence/branch/choose/parallel/
 * retry/gate/map/tryCatch evaluated against a fake StageContext. No pi spawns.
 */

import { describe, it, expect } from "vitest";
import {
	task, sequence, branch, choose, parallel, retry, gate, map, noop, tryCatch,
} from "../src/nodes.ts";
import type { StockAnalysisState, Stage, NodeResult } from "../src/types.ts";
import { makeState, makeFakeCtx } from "./helpers/fake-context.ts";

function makeStage(id: string, run: (s: StockAnalysisState) => unknown, opts: { fatal?: boolean; enabled?: (s: StockAnalysisState) => boolean } = {}): Stage {
	return { id, label: id, fatal: opts.fatal, enabled: opts.enabled, async run(s) { return run(s); } };
}

describe("task", () => {
	it("runs the stage and stores the result under state[id]", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = task(makeStage("s1", () => ({ done: true })));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state["s1"]).toEqual({ done: true });
		expect(ctx.results[0]).toMatchObject({ id: "s1", status: "ok" });
	});
	it("skips when enabled() returns false", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = task(makeStage("s1", () => "ran", { enabled: () => false }));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("skipped");
		expect(state["s1"]).toBeUndefined();
	});
	it("records failed and swallows non-fatal errors", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = task(makeStage("s1", () => { throw new Error("boom"); }));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("failed");
		expect(r.error).toBe("boom");
	});
	it("re-throws fatal errors", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = task(makeStage("s1", () => { throw new Error("fatal"); }, { fatal: true }));
		await expect(node.run(state, ctx)).rejects.toThrow("fatal");
	});
});

describe("sequence", () => {
	it("runs children in order", async () => {
		const order: string[] = [];
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = sequence([
			task(makeStage("a", () => { order.push("a"); return 1; })),
			task(makeStage("b", () => { order.push("b"); return 2; })),
		]);
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(order).toEqual(["a", "b"]);
	});
	it("fail-fast: stops at first failure by default", async () => {
		const ran: string[] = [];
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = sequence([
			task(makeStage("a", () => { throw new Error("x"); })),
			task(makeStage("b", () => { ran.push("b"); return 2; })),
		]);
		const r = await node.run(state, ctx);
		expect(r.status).toBe("failed");
		expect(ran).toEqual([]);
	});
	it("tolerant: continues past failures", async () => {
		const ran: string[] = [];
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = sequence([
			task(makeStage("a", () => { throw new Error("x"); })),
			task(makeStage("b", () => { ran.push("b"); return 2; })),
		], { tolerant: true });
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok"); // tolerant sequence itself succeeds
		expect(ran).toEqual(["b"]);
	});
});

describe("branch", () => {
	it("takes the yes path when predicate is true", async () => {
		const state = makeState({ mode: "pipeline" });
		const ctx = makeFakeCtx(state);
		const node = branch((s) => s.mode === "pipeline", { yes: task(makeStage("y", () => "yes")) });
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state["y"]).toBe("yes");
	});
	it("takes the no path when predicate is false", async () => {
		const state = makeState({ mode: "analyze" });
		const ctx = makeFakeCtx(state);
		const node = branch((s) => s.mode === "pipeline", { yes: task(makeStage("y", () => "yes")), no: task(makeStage("n", () => "no")) });
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state["n"]).toBe("no");
	});
	it("skips when predicate is false and no no-path", async () => {
		const state = makeState({ mode: "analyze" });
		const ctx = makeFakeCtx(state);
		const node = branch(() => false, { yes: task(makeStage("y", () => "yes")) });
		expect((await node.run(state, ctx)).status).toBe("skipped");
	});
});

describe("choose", () => {
	it("picks the first matching case", async () => {
		const state = makeState({ mode: "walk" });
		const ctx = makeFakeCtx(state);
		const node = choose([
			{ when: (s) => s.mode === "pipeline", run: task(makeStage("p", () => "p")) },
			{ when: (s) => s.mode === "walk", run: task(makeStage("w", () => "w")) },
		]);
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state["w"]).toBe("w");
		expect(state["p"]).toBeUndefined();
	});
	it("falls back to otherwise", async () => {
		const state = makeState({ mode: "compare" });
		const ctx = makeFakeCtx(state);
		const node = choose([{ when: () => false, run: task(makeStage("x", () => "x")) }], task(makeStage("def", () => "def")));
		await node.run(state, ctx);
		expect(state["def"]).toBe("def");
	});
});

describe("parallel", () => {
	it("runs branches and joins results", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = parallel([
			task(makeStage("a", () => 1)),
			task(makeStage("b", () => 2)),
		], { into: "joined", join: (rs: NodeResult[]) => rs.map((r) => r.value) });
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state["joined"]).toEqual([1, 2]);
	});
	it("tolerant: continues even if a branch fails", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = parallel([
			task(makeStage("a", () => { throw new Error("x"); })),
			task(makeStage("b", () => 2)),
		], { tolerant: true });
		expect((await node.run(state, ctx)).status).toBe("ok");
	});
});

describe("retry", () => {
	it("retries on failure up to attempts", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		let tries = 0;
		const node = retry({ attempts: 3 }, task(makeStage("r", () => { if (++tries < 3) throw new Error("again"); return "ok"; })));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(r.attempts).toBe(3);
		expect(tries).toBe(3);
	});
	it("returns failed after exhausting attempts", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = retry({ attempts: 2 }, task(makeStage("r", () => { throw new Error("always"); })));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("failed");
		expect(r.attempts).toBe(2);
	});
});

describe("gate", () => {
	it("passes when validation succeeds", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = gate({ validate: async () => ({ pass: true, errors: [] }), attempts: 3 }, task(makeStage("g", () => ({ x: 1 }))));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
	});
	it("re-runs until validation passes", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		let attempt = 0;
		const node = gate({
			validate: async () => { attempt++; return { pass: attempt >= 2, errors: attempt < 2 ? ["nope"] : [] }; },
			attempts: 4,
			feedbackKey: "g",
		}, task(makeStage("g", () => ({ x: 1 }))));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state.__feedback?.g).toBeUndefined(); // cleared implicitly by success
	});
	it("exhausts non-fatally and records the gate result", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		const node = gate({ validate: async () => ({ pass: false, errors: ["never"] }), attempts: 2, feedbackKey: "g" }, task(makeStage("g", () => ({}))));
		const r = await node.run(state, ctx);
		expect(r.status).toBe("failed");
		expect(state.tracking.gateResults.some((g) => !g.passed)).toBe(true);
	});
});

describe("map", () => {
	it("fans out over a collection with a concurrency cap", async () => {
		const state = makeState({ companies: [{ ticker: "A", isAsh: false }, { ticker: "B", isAsh: false }, { ticker: "C", isAsh: false }] });
		const ctx = makeFakeCtx(state);
		const seen: string[] = [];
		const node = map(
			{ over: (s) => s.companies, as: "company", concurrency: 2 },
			task(makeStage("perco", (s) => { seen.push((s.company as { ticker: string }).ticker); return 1; })),
		);
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(seen.sort()).toEqual(["A", "B", "C"]);
	});
	it("exposes the current item at state[as]", async () => {
		const state = makeState({ companies: [{ ticker: "Z", isAsh: false }] });
		const ctx = makeFakeCtx(state);
		let captured;
		await map({ over: (s) => s.companies, as: "company" }, task(makeStage("c", (s) => { captured = s.company; return 1; }))).run(state, ctx);
		expect(captured).toEqual({ ticker: "Z", isAsh: false });
	});
});

describe("tryCatch + noop", () => {
	it("tryCatch catches a thrown (fatal) error", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		// A fatal task re-throws (non-fatal tasks swallow internally); tryCatch
		// catches the re-throw and runs the catch branch.
		const node = tryCatch(task({ id: "t", label: "t", fatal: true, async run() { throw new Error("oops"); } }), { catch: task(makeStage("h", () => "handled")) });
		const r = await node.run(state, ctx);
		expect(r.status).toBe("ok");
		expect(state["h"]).toBe("handled");
		expect(state.__lastError).toBe("oops");
	});
	it("noop returns ok", async () => {
		const state = makeState();
		const ctx = makeFakeCtx(state);
		expect((await noop().run(state, ctx)).status).toBe("ok");
	});
});
