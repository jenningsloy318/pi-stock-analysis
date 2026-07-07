/**
 * The workflow runner. Builds a `StageContext` and evaluates the workflow's
 * root node: `await workflow.root.run(state, ctx)`. All control logic lives in
 * the node algebra (`nodes.ts`); this file only wires execution primitives.
 *
 *   ctx.agent()    — spawn a specialist `pi` subprocess or in-process session
 *   ctx.helper()   — run a deterministic pure helper (gates.ts dispatch)
 *   ctx.script()   — run a verbatim python script via uv (scripts.ts)
 *   ctx.parallel() — run async fns with a concurrency cap
 *   ctx.budget()   — cap total agent spawns
 *   ctx.events     — EventEmitter for waitForEvent
 */

import { EventEmitter } from "node:events";
import { spawnAgent } from "./pi-spawn.ts";
import { runAgentViaSession } from "./session-agent.ts";
import { runHelper } from "./gates.ts";
import { runScriptCall } from "./scripts.ts";
import { extractControlKeys } from "./control.ts";
import type {
	AgentCall,
	AgentResult,
	Budget,
	HelperCall,
	HelperResult,
	Node,
	ScriptCall,
	ScriptResult,
	StockAnalysisState,
	RunOptions,
	RunStatus,
	RunSummary,
	StageContext,
	StageProgressEvent,
	ProgressSink,
} from "./types.ts";

const DEFAULT_MAX_AGENTS = 200;
const DEFAULT_MAX_CONCURRENCY = 4; // rule "Max 4 Concurrent"

function makeBudget(maxAgents: number): Budget {
	const s = { count: 0, max: maxAgents };
	return {
		count: 0,
		check: () => s.count < s.max,
		spent() {
			s.count++;
			this.count = s.count;
		},
	};
}

export interface MakeContextOptions {
	state: StockAnalysisState;
	task: string;
	options: RunOptions;
	extensionRoot: string;
	log: (m: string) => void;
}

/** Build a StageContext bound to a run's state + options. Exposed for unit
 *  tests (a fake context drives the node-algebra semantics tests). */
export function makeContext(opts: MakeContextOptions): StageContext {
	const { state, options, log } = opts;
	const budget = makeBudget(options.maxAgents ?? DEFAULT_MAX_AGENTS);
	const maxConcurrency = options.maxConcurrency ?? DEFAULT_MAX_CONCURRENCY;
	const model = options.model;
	const signal = options.signal;
	const extensionRoot = opts.extensionRoot;
	const progress = options.progress;
	const reportsDir = state.reportsDir;

	async function agent(call: AgentCall): Promise<AgentResult> {
		budget.spent();
		// Mock/replay hook: if an agentRunner override is set (e2e tests), use it
		// instead of the real backend. The budget still increments so agentsSpawned
		// stays honest.
		if (options.agentRunner) {
			return options.agentRunner(call);
		}
		const agentCwd = options.cwd ?? process.cwd();
		// Gate feedback convergence: if a gate rejected a prior attempt, it stored
		// structured errors under state.__feedback[stageId]. Prepend them so the
		// agent fixes the specific failure. The call.id is `pipeline.<id>`.
		const stageKey = (call.id ?? "").replace(/^pipeline\./, "");
		const feedback = state.__feedback?.[stageKey];
		const prompt = feedback?.length
			? `${call.prompt}\n\n${[
					"## Previous attempt rejected — fix these",
					"The validator rejected the prior attempt for these specific reasons:",
					...feedback.map((e) => `- ${e}`),
					"Address every point and re-produce the complete artifact, then call structured_output.",
				].join("\n")}`
			: call.prompt;
		const common = {
			agent: call.agent,
			prompt,
			cwd: agentCwd,
			controlKeys: call.controlKeys ?? extractControlKeys(call.prompt),
			model,
			signal,
			id: call.id,
			onProgress: {
				event: (m: string) => log(m),
				text: (partial: string) => progress?.text(partial),
			},
		};
		const backend = options.backend ?? (process.env.STOCK_ANALYSIS_BACKEND as "session" | "subprocess" | undefined) ?? "subprocess";
		return backend === "session" ? runAgentViaSession(common) : spawnAgent(common);
	}

	async function helper(call: HelperCall): Promise<HelperResult> {
		return runHelper(call);
	}

	async function script(call: ScriptCall): Promise<ScriptResult> {
		return runScriptCall(call, { root: extensionRoot, cwd: reportsDir ?? options.cwd, sink: progress, signal });
	}

	async function parallel<T>(items: T[], fn: (item: T) => Promise<T>, concurrency: number): Promise<T[]> {
		const results: T[] = [];
		const queue = items.map((item) => () => fn(item));
		async function worker(): Promise<void> {
			while (queue.length > 0) {
				const next = queue.shift();
				if (!next) return;
				results.push(await next());
			}
		}
		const n = Math.min(concurrency || maxConcurrency, items.length);
		await Promise.all(Array.from({ length: Math.max(1, n) }, worker));
		return results;
	}

	return { task: opts.task, options, state, agent, helper, script, parallel, budget, log, events: new EventEmitter(), signal, extensionRoot, results: [] };
}

/** Derive the honest overall status from per-stage results + gate flags.
 *  Never faked; never defaults to "success" on a real failure (ISS-02). */
function deriveStatus(state: StockAnalysisState, results: { status: string }[], aborted: boolean): RunStatus {
	if (aborted) return "failed";
	const failedStages = results.filter((r) => r.status === "failed");
	const failedGates = state.tracking.gateResults.filter((g) => !g.passed);
	if (failedStages.length === 0 && failedGates.length === 0) return "success";
	return "partial";
}

/** Run a workflow against an already-initialized state. */
export async function runWorkflow(
	root: Node,
	state: StockAnalysisState,
	options: RunOptions = {},
): Promise<RunSummary> {
	const progress = options.progress;
	const ctx = makeContext({
		state,
		task: state.query ?? "",
		options,
		extensionRoot: state.extensionRoot,
		log: (msg: string) => progress?.log(msg),
	});

	if (progress) {
		ctx.events.on("phase", (label: unknown) => progress.phase(String(label)));
		ctx.events.on("stage", (info: unknown) => progress.stage?.(info as StageProgressEvent));
	}

	let aborted = false;
	let abortError: string | undefined;
	try {
		await root.run(state, ctx);
	} catch (err) {
		aborted = true;
		abortError = err instanceof Error ? err.message : String(err);
		progress?.log(`Workflow aborted: ${abortError}`);
	}

	if (!aborted) {
		state.tracking.finishedAt = new Date().toISOString();
		progress?.log(`Workflow complete — run ${state.runId}`);
	}

	const status = deriveStatus(state, ctx.results, aborted);

	const seen = new Set<string>();
	const failedStages = state.tracking.failures.filter((f) => {
		if (seen.has(f.stage)) return false;
		seen.add(f.stage);
		return true;
	});

	return {
		workflowId: "stock-analysis",
		runId: state.runId,
		reportsDir: state.reportsDir,
		mode: state.mode,
		tickers: state.tickers,
		theme: state.theme,
		agentsSpawned: ctx.budget.count,
		state,
		status,
		completed: state.tracking.completed,
		skipped: state.tracking.skipped,
		failed: failedStages,
		reports: state.reports,
		error: abortError,
	};
}

// re-export for callers composing custom workflows
export type { ProgressSink };
