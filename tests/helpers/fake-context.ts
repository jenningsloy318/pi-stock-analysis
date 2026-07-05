/**
 * A fake StageContext for hermetic node-algebra / workflow tests.
 * No `pi` spawns, no network, no `uv` — everything is in-memory stubs.
 */

import { EventEmitter } from "node:events";
import type {
	StockAnalysisState, StageContext, AgentCall, AgentResult,
	HelperCall, HelperResult, ScriptCall, ScriptResult, Budget,
} from "../../src/types.ts";

export function makeState(overrides: Partial<StockAnalysisState> = {}): StockAnalysisState {
	return {
		mode: "pipeline",
		tickers: [],
		topIndustry: 8,
		totalCompany: 15,
		topPrice: 200,
		minHeadroom: 5,
		days: 1,
		universe: "US",
		runId: "202601010000",
		reportsDir: "/tmp/reports/202601010000",
		backend: "subprocess",
		extensionRoot: "/tmp/ext",
		companies: [],
		reports: [],
		tracking: { completed: [], skipped: [], failures: [], gateResults: [], startedAt: "2026-01-01T00:00:00Z" },
		...overrides,
	};
}

export interface FakeCtxOptions {
	agentResult?: (call: AgentCall) => AgentResult;
	helperResult?: (call: HelperCall) => HelperResult;
	scriptResult?: (call: ScriptCall) => ScriptResult;
	maxAgents?: number;
}

export function makeFakeCtx(state: StockAnalysisState, opts: FakeCtxOptions = {}): StageContext {
	const budget: Budget = {
		count: 0,
		check: () => budget.count < (opts.maxAgents ?? 100),
		spent: () => { budget.count++; },
	};
	const logs: string[] = [];
	return {
		task: "",
		options: {},
		state,
		budget,
		log: (m: string) => { logs.push(m); (state as StockAnalysisState & { __logs?: string[] }).__logs = logs; },
		events: new EventEmitter(),
		extensionRoot: state.extensionRoot,
		results: [],
		async agent(call) {
			budget.spent();
			if (opts.agentResult) return opts.agentResult(call);
			return { text: "ok", control: {} };
		},
		async helper(call) {
			return opts.helperResult ? opts.helperResult(call) : { value: { pass: true, errors: [] }, digest: "PASS" };
		},
		async script(call) {
			return opts.scriptResult ? opts.scriptResult(call) : { ok: true, stdout: "{}", json: {} };
		},
		async parallel(items, fn, concurrency) {
			const out: unknown[] = [];
			const queue = items.map((it) => () => fn(it));
			async function worker() { while (queue.length) { const n = queue.shift(); if (n) out.push(await n()); } }
			await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
			return out as never[];
		},
	};
}
