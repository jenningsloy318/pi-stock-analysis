/**
 * Core type system for the self-contained stock-analysis control-flow engine.
 *
 * Architecture: a pipeline is a tree of `Node`s evaluated over a shared
 * `StockAnalysisState`. Leaf nodes (`task`) wrap a `Stage` (a unit of work that
 * spawns agents / runs helpers / runs python scripts). Control nodes
 * (`sequence`, `branch`, `choose`, `parallel`, `loop`, `retry`, `gate`, `map`,
 * `wait`, `tryCatch`, ...) compose nodes and are self-evaluating: each
 * implements `run(state, ctx)`. The engine itself is just
 * `await root.run(state, ctx)` — adding a new control construct means writing
 * one builder function in `nodes.ts`, never touching the runner.
 *
 * Zero dependency on @agwab/pi-workflow or any external workflow engine: agents
 * are spawned directly as `pi` child processes (see `pi-spawn.ts`) or run
 * in-process via the pi SDK (see `session-agent.ts`). Deterministic financial
 * calculations run via the verbatim Python scripts through `uv run`
 * (see `scripts.ts`).
 */

import type { EventEmitter } from "node:events";

// ─── Primitive result types ─────────────────────────────────────────────────

/** Free-form control object returned by an agent or a python script. */
export type ControlObj = Record<string, unknown>;

/** Result of parsing an agent's final assistant message. */
export interface SpawnResult {
	text: string;
	control: ControlObj | null;
	model?: string;
	error?: string;
}

export interface AgentCall {
	id: string;
	agent: string;
	prompt: string;
	/** Control keys the caller expects back (for the session backend's
	 *  structured_output schema). Optional; omitted for non-writer calls. */
	controlKeys?: string[];
}

export interface AgentResult extends SpawnResult {}

export interface HelperCall {
	name: string;
	sources: Record<string, unknown>;
	options?: Record<string, unknown>;
	context?: Record<string, unknown>;
}

export interface HelperResult {
	value: ControlObj;
	digest: string;
}

export interface ScriptCall {
	name: string;
	args?: string[];
	/** Override the run cwd. Defaults to the run's reports dir. */
	cwd?: string;
	timeoutMs?: number;
}

export interface ScriptResult {
	ok: boolean;
	stdout?: string;
	stderr?: string;
	/** Parsed JSON object from stdout, when present. */
	json?: unknown;
	exitCode?: number;
	error?: string;
}

export interface Budget {
	check(): boolean;
	spent(): void;
	count: number;
}

export interface ProgressSink {
	phase(label: string): void;
	log(message: string): void;
	/** Live streaming text from the active agent (typing effect). `partial` is the
	 *  full accumulated text of the current text block so far. */
	text(partial: string): void;
	/** Per-stage status changes (running → ok/failed/skipped). Drives the TUI
	 *  workflow dashboard widget. */
	stage?(info: StageProgressEvent): void;
}

/** A stage lifecycle event emitted by `task()` nodes for the dashboard. */
export interface StageProgressEvent {
	id: string;
	label: string;
	status: NodeStatus | "running";
	error?: string;
}

/** Streaming callbacks from a spawned agent to the progress sink. */
export interface AgentProgress {
	/** A permanent log line (tool call, turn marker, finalized agent text). */
	event(message: string): void;
	/** Live partial text as the agent generates it (control block stripped). */
	text(partial: string): void;
}

// ─── Domain shapes (stock-analysis) ─────────────────────────────────────────

export type Mode = "pipeline" | "screen" | "analyze" | "compare" | "walk";
export type Universe = "US" | "CN" | "ALL";
export type Backend = "subprocess" | "session";
export type RunStatus = "success" | "partial" | "failed";

export interface ToolParams {
	mode: Mode;
	tickers?: string[];
	theme?: string;
	topIndustry?: number;
	totalCompany?: number;
	topPrice?: number;
	minHeadroom?: number;
	days?: number;
	universe?: Universe;
	query?: string;
	model?: string;
	maxAgents?: number;
}

/** A normalized company selected for deep-dive (Stage 4 output). */
export interface Company {
	ticker: string;
	name?: string;
	/** True for .SH / .SZ A-share tickers (drives Stage 15). */
	isAsh: boolean;
	exchange?: "SH" | "SZ" | "NASDAQ" | "NYSE" | "HK" | string;
	rank?: number;
	gicsCode?: string;
	subIndustry?: string;
	score?: number;
	/** Per-stage analyst outputs keyed by stage id (e.g. "stage-5"). */
	[index: string]: unknown;
}

export interface SubIndustry {
	code: string;
	name: string;
	score?: number;
	dimBreakdown?: Record<string, number>;
}

export interface Industry {
	code: string;
	name: string;
}

/** Shared data fetched ONCE at Stage 1, reused by all downstream stages
 *  (rule "shared-data-once"). */
export interface SharedData {
	macro?: ControlObj;
	sectorMetrics?: ControlObj;
	breadth?: ControlObj;
	themePerformance?: ControlObj;
	files?: string[];
	status?: "ok" | "partial" | "failed";
}

export interface ScoringResult {
	companies: Array<ScoredCompany>;
}

export interface ScoredCompany {
	ticker: string;
	composite: number;
	rating: string;
	components?: Record<string, number>;
}

export interface AdversarialResult {
	ticker: string;
	survived: boolean;
	skeptics: Array<{ lens: string; refuted: boolean; reasoning?: string }>;
}

export interface JudgeVerdict {
	ticker: string;
	lenses: Array<{ framework: string; score: number; verdict: string; disagreements?: string[] }>;
	disagreements?: unknown[];
	positionType?: "core" | "satellite" | "tactical";
}

export interface ReportArtifact {
	kind: "screening" | "company" | "comparison" | "walk" | "best-picks";
	horizon?: "long" | "mid" | "short";
	ticker?: string;
	path: string;
}

export interface BestPick {
	ticker: string;
	name?: string;
	positionType: "core" | "satellite" | "tactical";
	rank?: number;
	composite?: number;
	conviction?: string;
}

export interface StageFailure {
	stage: string;
	error: string;
	attempts?: number;
}

export interface Tracking {
	completed: string[];
	skipped: string[];
	failures: StageFailure[];
	gateResults: Array<{ stage: string; passed: boolean; errors?: string[] }>;
	startedAt: string;
	finishedAt?: string;
}

// ─── Pipeline state (shared blackboard) ─────────────────────────────────────

/**
 * Mutable state threaded through every node. A `task` node stores its return
 * value under `state[stage.id]`. Control nodes read upstream artifacts by key.
 * The index signature allows per-stage outputs without extending the interface.
 */
export interface StockAnalysisState {
	// ── inputs (from tool params, normalized in Stage 0) ──
	mode: Mode;
	tickers: string[];
	theme?: string;
	topIndustry: number;
	totalCompany: number;
	topPrice: number;
	minHeadroom: number;
	days: number;
	universe: Universe;
	query?: string;

	// ── run identity ──
	runId: string; // YYYYMMDDHHmm LOCAL time (rule "Run Directory")
	reportsDir: string; // ./reports/<runId>/ in the RUN cwd (not package dir)
	backend: Backend;
	model?: string;
	maxAgents?: number;
	extensionRoot: string;

	// ── pipeline working sets ──
	sharedData?: SharedData;
	industries?: Industry[];
	subIndustries?: SubIndustry[];
	companies: Company[];
	scoring?: ScoringResult;
	adversarial?: AdversarialResult[];
	judgePanel?: JudgeVerdict[];
	reports: ReportArtifact[];
	bestPicks?: BestPick[];

	// ── per-company scratch (current item inside a map body) ──
	company?: Company;

	// ── bookkeeping ──
	tracking: Tracking;
	/** Gate feedback channel: a gate stores validator errors under
	 *  `__feedback[feedbackKey]` so the next attempt's prompt names them. */
	__feedback?: Record<string, string[]>;
	__lastError?: string;

	[index: string]: unknown;
}

// ─── Stage (leaf unit of work) ──────────────────────────────────────────────

/** Outcome of one leaf-stage execution, recorded for honest run reporting. */
export interface StageResult {
	id: string;
	label: string;
	status: NodeStatus;
	error?: string;
}

/**
 * Execution primitives handed to every stage. The runner builds one context
 * and passes the same reference around.
 */
export interface StageContext {
	task: string;
	options: RunOptions;
	state: StockAnalysisState;
	agent(call: AgentCall): Promise<AgentResult>;
	helper(call: HelperCall): Promise<HelperResult>;
	script(call: ScriptCall): Promise<ScriptResult>;
	parallel<T>(items: T[], fn: (item: T) => Promise<T>, concurrency: number): Promise<T[]>;
	budget: Budget;
	log(message: string): void;
	events: EventEmitter;
	signal?: AbortSignal;
	extensionRoot: string;
	/** Every leaf-stage outcome, appended by `task()`. Used for honest summaries. */
	results: StageResult[];
}

/** A leaf unit of work. Its return value is stored under `state[id]`. */
export interface Stage {
	id: string;
	label: string;
	description?: string;
	enabled?: (state: StockAnalysisState) => boolean;
	run: (state: StockAnalysisState, ctx: StageContext) => Promise<unknown>;
	/** Only Stage 0 (Setup) sets this true; its failure aborts the run. */
	fatal?: boolean;
}

// ─── Control-flow node algebra ──────────────────────────────────────────────

export type NodeStatus = "ok" | "skipped" | "failed" | "cancelled";

export interface NodeResult {
	status: NodeStatus;
	/** Stored artifact (for tasks) or aggregate (for some control nodes). */
	value?: unknown;
	error?: string;
	/** Round/attempt count reached (for loop/retry/gate). */
	attempts?: number;
}

/**
 * A self-evaluating pipeline node. Leaf `task` nodes do work; control nodes
 * recursively evaluate children. The runner is `await root.run(state, ctx)`.
 */
export interface Node {
	kind: string;
	label?: string;
	run(state: StockAnalysisState, ctx: StageContext): Promise<NodeResult>;
}

/** A workflow: a root node plus metadata. */
export interface Workflow {
	id: string;
	description?: string;
	root: Node;
}

// ─── Run options + summary ──────────────────────────────────────────────────

export interface RunOptions {
	cwd?: string;
	model?: string;
	maxAgents?: number;
	maxConcurrency?: number;
	backend?: Backend;
	progress?: ProgressSink;
	signal?: AbortSignal;
	/** Override the agent execution backend. When set, every `ctx.agent(call)`
	 *  invokes this instead of spawning `pi` / using the session backend — used by
	 *  the recorded-fixture e2e tests (mock/replay) and any custom runner. The
	 *  budget counter still increments. */
	agentRunner?: (call: AgentCall) => Promise<AgentResult>;
}

/** Honest, derived overall outcome of a run. */
export interface RunSummary {
	workflowId: string;
	runId: string;
	reportsDir: string;
	mode: Mode;
	tickers: string[];
	theme?: string;
	agentsSpawned: number;
	state: StockAnalysisState;
	status: RunStatus;
	completed: string[];
	skipped: string[];
	failed: StageFailure[];
	reports: ReportArtifact[];
	error?: string;
}
