# 04 — Code Assessment

**Task:** Create a new pi extension package (`@jenningsloy318/pi-finance` / `pi-stock-analysis`) in `/home/jenningsl/development/personal/pi-finance` that re-implements the stock-analysis orchestration as a self-contained pi control-flow workflow, **mirroring** how `pi-super-dev` was built from `super-dev-plugin`.

**Scope assessed:**
- **Template (mirror this):** `/home/jenningsl/development/personal/jenningsloy318/pi-super-dev` — full src/, tests/, package.json, README, agents/.
- **Source (convert this):** `/home/jenningsl/development/personal/jenningsloy318/stock-analysis-plugin` — `skills/stock-analysis/SKILL.md`, `agents/`, `scripts/`, `references/`, `templates/`, `schemas/`, `assets/`.
- **Target:** `/home/jenningsl/development/personal/pi-finance` — empty git repo (only `docs/` + `.git`).

---

## 1. Structure

### 1.1 Template package layout (`pi-super-dev`) — replicate verbatim

```
pi-super-dev/
├── package.json          # type:module, "pi":{extensions,skills}, peerDeps pi-coding-agent + typebox
├── tsconfig.json
├── vitest.config.ts
├── README.md             # architecture doc: node-algebra table + pipeline diagram
├── CHANGELOG.md, LICENSE (MIT), .gitignore
├── src/
│   ├── extension.ts      # default activate(pi): registerTool + registerCommand
│   ├── pipeline.ts       # thin public entry: runPipelineTask → runWorkflow(WORKFLOW,...)
│   ├── nodes.ts          # control-flow node algebra (task/sequence/branch/choose/parallel/loop/retry/gate/map/wait/waitForEvent/tryCatch/noop + writerTask/helperTask/gateValidator)
│   ├── workflow.ts       # makeContext + runWorkflow (just `await root.run(state,ctx)`)
│   ├── types.ts          # PipelineState, Stage, StageContext, Node, NodeResult, RunSummary, domain shapes
│   ├── agents.ts         # loads agents/<name>.md
│   ├── pi-spawn.ts       # spawns `pi` subprocess; abbreviatePath, spawnAgent
│   ├── session-agent.ts  # in-process createAgentSession backend
│   ├── control.ts        # tolerant <control> JSON extractor + extractControlKeys
│   ├── helpers.ts        # deterministic helpers (runHelper)
│   ├── prompts.ts        # prompt builders
│   ├── setup.ts, doc-validators.ts
│   └── stages/index.ts   # the pipeline expressed as a tree of nodes (root + per-stage tasks)
├── tests/                # *.test.ts hermetic vitest; structure.test.ts asserts package layout
├── agents/               # 21 × <name>.md specialist definitions
└── skills/super-dev/SKILL.md   # SHORT pointer skill
```

Evidence: `pi-super-dev/package.json` (`exports`, `"pi": { "extensions": ["./src/extension.ts"], "skills": ["./skills/super-dev"] }`, peerDeps `@earendil-works/pi-coding-agent` + `typebox`, `engines.node >=22.19.0`); `pi-super-dev/src/extension.ts:1-160`; `pi-super-dev/tests/structure.test.ts:1-90`.

### 1.2 Target repo state

`/home/jenningsl/development/personal/pi-finance` is an **empty git repo** containing only `docs/specifications/01-pi-stock-analysis-workflow/{01-requirements.md, 02-bdd-scenarios.md, 03-research-report.md}` and `.git/`. There is **no existing code** to align with — the implementation must import the conventions from `pi-super-dev` directly. Zero findings against "existing target code" is expected; every finding below cites the **template**.

### 1.3 Source artifacts to port (COPY verbatim unless noted)

From `stock-analysis-plugin/`:
- `skills/stock-analysis/SKILL.md` → the authoritative 5-mode / 19-stage spec (re-implemented in TS; do NOT ship as the skill body).
- `agents/*.md` — **22 files present** (see `ARCH-003` discrepancy); copy + light preamble edit.
- `scripts/*.py` (76) + `scripts/requirements.txt` + `pyproject.toml` + `uv.lock` → copy verbatim. KEEP PYTHON (decision §2 of the goal).
- `references/` (gics_taxonomy, data_source_matrix, frameworks_*, pitfalls/, serenity/, scoring_calibration, sector_metrics, microstructure-framework, institutional_odd, international_markets) → copy as package data.
- `templates/` (equity-report.md, screening-report.md, ecosystem-health.md.j2, industry-trajectory.md.j2, company-status.json, workflow-tracking.json) → copy.
- `schemas/*.json` (16) → copy.
- `assets/report_styles.css` → copy.

**Do NOT copy:** `workflows/stock-analysis.js`, `.claude/`, `.codex/`, `.claude-plugin/`, `.codex-plugin/`, `plugin.json`, `reports/`, `reports-deepseek/`, root `stage*.md`, root `*.py` (`generate_reports.py`, `parse_phase2.py`, …), `run_triage.sh`, `test.py`, `AGENTS.md`, `CLAUDE.md`, `new-analysis.md`.

---

## 2. Patterns to follow (with canonical examples)

### PAT-001 — Extension entry point: `default activate(pi)` registering ONE tool + ONE command
The extension exports a default `activate(pi: ExtensionAPI)` that calls `pi.registerTool({...})` then `pi.registerCommand(name, {...})`. The command does NOT run the pipeline itself — it parses args, then dispatches via `pi.sendUserMessage(...)` so the agent invokes the tool (interruptible, streams progress).
- Canonical: `pi-super-dev/src/extension.ts:99` (`export default function activate(pi)`) → `pi.registerTool({ name: SUPER_DEV_TOOL, ... parameters: Type.Object({...}), async execute(...) {...} })` at `:104`; `pi.registerCommand(SUPER_DEV_COMMAND, { handler: async (args, ctx) => { ...; pi.sendUserMessage(\`Use the ${TOOL} tool ...\`) } })` at `:149`.
- **For this task:** tool name `stock_analysis`, command `/stock-analysis`. The command parses the NL arg string (`--mode`, positional tickers/theme, `--top-industry`, etc.) then `pi.sendUserMessage`.

### PAT-002 — Tool params via Typebox `Type.Object`; progress streaming via rolling-tail `ProgressSink`
Parameters are declared with `Type.Object({ task: Type.String(...), skipWorktree: Type.Optional(Type.Boolean(...)), ... })`. The `execute(_toolCallId, params, signal, onUpdate)` builds a `ProgressSink` that keeps a **rolling tail** (`TAIL_LINES = 400`) plus an 80ms-throttled `text(partial)` typing stream, and writes the **full transcript** to `.stock-analysis-logs/<ISO>-<runId>.log` at run end.
- Canonical: `pi-super-dev/src/extension.ts:115-147` (the `transcript`/`live`/`flush`/`finalizeLive` block + `writeFileSync(logPath, transcript.join("\n"))`).
- **For this task:** swap the param shape for the stock-analysis params (`mode`, `tickers[]`, `theme`, `topIndustry`, `totalCompany`, `topPrice`, `minHeadroom`, `days`, `universe`, `query`, `model`, `maxAgents`); change log dir to `.stock-analysis-logs/`.

### PAT-003 — Honest summary: `formatSummary` derives success/partial/failed from state, never fakes
A `RunStatus = "success" | "partial" | "failed"` is derived from produced artifacts (`impl.allGreen`, `review.verdict`, phase count) — **never** optimistically defaulted. Failed stages are deduped and listed with their error.
- Canonical: `pi-super-dev/src/extension.ts:31-58` (`formatSummary`) + `pi-super-dev/src/workflow.ts:120-140` (status derivation in `runWorkflow`).
- **For this task:** derive stock-analysis status from e.g. presence of `state.reports` / `state.bestPicks` / `state.scoring` and gate pass/fail flags.

### PAT-004 — Control-flow node algebra: self-evaluating `Node`, runner is `await root.run(state, ctx)`
`Node { kind; run(state, ctx): Promise<NodeResult> }`. Leaf `task(stage)` stores return value under `state[stage.id]`. Control nodes (`sequence`, `branch`, `choose`, `parallel`, `loop`, `retry`, `gate`, `map`, `wait`, `waitForEvent`, `tryCatch`, `noop`) recurse into children. **Adding a construct = one builder in `nodes.ts`, zero runner changes.** No `@agwab/pi-workflow` dependency.
- Canonical: `pi-super-dev/src/nodes.ts:33-340` (full algebra); `pi-super-dev/src/workflow.ts:99` (`await workflow.root.run(state, ctx)`).
- **For this task:** port `nodes.ts` near-verbatim; the 5-mode dispatch is `choose([…], otherwise)` and the per-company DAG is `map({over: state.companies, as: "company", concurrency: 4}, body)` with the body itself a `parallel`/`sequence` of waves.

### PAT-005 — `gate` returns structured errors; retries CONVERGE via `state.__feedback[feedbackKey]`
`gate({ validate, attempts, feedbackKey })` does NOT throw on exhaustion — it logs, stores validator errors under `state.__feedback[key]`, and returns `{status:"failed"}` so the tolerant sequence proceeds with the best artifact. `workflow.ts` agent() prepends those errors to the next attempt's prompt so the agent fixes the specific failure instead of resampling.
- Canonical: `pi-super-dev/src/nodes.ts:235-285` (`gate`); feedback injection at `pi-super-dev/src/workflow.ts:55-62`.
- **For this task:** the 5 validation stages (1.5 / 4.5 / 16.5 / 17.5 / 18.5) are `gate({validate, attempts: 4, feedbackKey: "sharedData" | ...})`. `validate_report.py` (8 gates) is invoked through `runScript` inside the validator.

### PAT-006 — `retry({attempts:10})` for retry-on-null over probabilistic agents
`retry` repeats a node on `failed`, with optional `matches(result,state,ctx)` predicate and backoff. Use this to implement SKILL.md's "retry-on-null 10×" rule around each analyst `task`.
- Canonical: `pi-super-dev/src/nodes.ts:200-228` (`retry`).

### PAT-007 — Tolerant pipeline: a thrown/fatal stage must NOT abort the run except setup
`sequence(children, { tolerant: true })` converts throws to `failed` and continues; only `stage.fatal === true` re-throws (setup is the one fatal stage). `tryCatch` provides explicit boundaries.
- Canonical: `pi-super-dev/src/nodes.ts:148-175` (`sequence` tolerant handling) + `:88-100` (`task` `if (stage.fatal) throw err`); `tryCatch` at `:300-320`.
- **For this task:** Stage 0 Setup is `fatal:true`; every other stage is tolerant. Wrap the whole root in `sequence([...], {tolerant:true})` inside `choose([...])`.

### PAT-008 — `StageContext` provides `agent`/`helper`/`parallel`/`budget`/`log`/`events`/`signal`
The runner builds ONE context and threads the same reference through every node. `ctx.agent({id, agent, prompt, controlKeys})` spawns a specialist (subprocess or session backend); `ctx.budget.check()/spent()` caps total agents; `ctx.events` (EventEmitter) backs `waitForEvent`.
- Canonical: `pi-super-dev/src/types.ts:113-130` (`StageContext`); `pi-super-dev/src/workflow.ts:30-85` (`makeContext`).
- **For this task:** add a `runScript` path — either extend `StageContext` with a `script(call)` primitive or expose it as a `helper` (preferred: `helpers.ts` `runHelper` already dispatches by `name`; add a `script` helper name that shells to `uv run python`).

### PAT-009 — Backend selectable via env: `SUPER_DEV_BACKEND = session | subprocess`
Default `"session"` (in-process `createAgentSession` with a per-stage structured-output schema); `"subprocess"` (`pi -a <agent>` spawn) available. The choice is read from `options.backend ?? process.env.SUPER_DEV_BACKEND ?? "session"`.
- Canonical: `pi-super-dev/src/workflow.ts:70-73`.
- **For this task:** mirror exactly but rename env to `STOCK_ANALYSIS_BACKEND`.

### PAT-010 — Hermetic vitest tests; `structure.test.ts` asserts package layout + exports + no pi-workflow dep
Tests use only `vitest` + `node:fs`; NO pi spawns, NO network. `structure.test.ts` reads `package.json`, asserts `pi.extensions`, the `pi-package` keyword, **no bundled runtime deps**, **no `@agwab/pi-workflow`**, the node-algebra exports, the tool+command registration, and the agent count.
- Canonical: `pi-super-dev/tests/structure.test.ts:1-90`; node-semantics tests at `pi-super-dev/tests/nodes.test.ts`.
- **For this task:** replicate `structure.test.ts` (asserting `stock_analysis` tool + `/stock-analysis` command + 76 scripts + 22 agents + node exports); add tests for the `/stock-analysis` arg-parser, A-share ticker normalization, `runScript` (mocked child_process), and `choose` mode-dispatch.

### PAT-011 — Agents are `.md` files with YAML frontmatter; loaded by `agents.ts`
Each agent is a markdown doc with `--- { name, description, model, kind, tools, max_turns, timeout_mins } ---` frontmatter + `<role>`/`<input>`/`<output>` body. `agents.ts` loads them by name.
- Canonical: `pi-super-dev/src/agents.ts`; source example `stock-analysis-plugin/agents/data-collector.md:1-10`.
- **For this task:** copy the 22 source agents; edit only the invocation preamble (replace Claude Code `Agent`/`subagent_type` references with "spawned as `pi -a <agent>`; deterministic calcs via `uv run python ${EXTENSION_ROOT}/scripts/...`"). Keep all analytical content + output schemas.

---

## 3. Dependencies

### DEP-001 — Runtime: zero bundled npm dependencies (peer-only)
`package.json` declares **no `dependencies`** — only `peerDependencies` (`@earendil-works/pi-coding-agent`, `typebox`) and `devDependencies` (`@types/node`, `typebox`, `typescript`, `vitest`). `structure.test.ts:25-29` enforces `dependencies` is undefined.
- Canonical: `pi-super-dev/package.json:24-39`.

### DEP-002 — TypeScript ESM, Node ≥ 22.19, `.ts` imports with explicit extensions
`"type": "module"`, `engines.node >= 22.19.0`, imports use the `.ts` suffix (`import { X } from "./nodes.ts"`), `tsc` build + `tsc --noEmit` typecheck, `vitest run` test.
- Canonical: `pi-super-dev/package.json:14-23`, `:40`; every `import` in `pi-super-dev/src/*.ts`.

### DEP-003 — Python runtime (NEW for this package): `uv` + the scripts' scientific stack
`pyproject.toml` pins `akshare`, `baostock` (China A-share — **no Node equivalent**), `yfinance`, `scipy`, `statsmodels`, `arch` (GARCH), `pandas-ta`, `praw` (Reddit), `pytrends`, etc. SKILL.md rule "UV Run" mandates `uv run python ${PLUGIN_ROOT}/scripts/<script>.py`. The TS layer must NOT reimplement these.
- Canonical: `stock-analysis-plugin/pyproject.toml:1-21`; rule at `stock-analysis-plugin/skills/stock-analysis/SKILL.md:192`.
- **For this task:** ship `scripts/`, `pyproject.toml`, `uv.lock`, `requirements.txt` verbatim; add `src/scripts.ts` `runScript(name, args, {cwd, root})` → `child_process.spawn("uv", ["run", "python", join(root,"scripts",`${name}.py`), ...args], {cwd})` with timeout + structured stderr capture. Resolve `root` from the package dir (`EXTENSION_ROOT`) and inject into every agent prompt (SKILL.md constraint "Pass PLUGIN_ROOT" at `:210`).

### DEP-004 — `typebox` for the tool parameter schema (NOT zod)
Pi's `registerTool` consumes `Type.Object(...)` from `typebox`. Match the peer-dep version.
- Canonical: `pi-super-dev/src/extension.ts:7` (`import { Type } from "typebox"`) + `:127`.

---

## 4. Recommendations (prioritized)

- **REC-001 (HIGHEST) — Port `nodes.ts`, `workflow.ts`, `types.ts`, `control.ts`, `helpers.ts`, `agents.ts`, `pi-spawn.ts`, `session-agent.ts`, `prompts.ts` near-verbatim from `pi-super-dev`.** Then adapt only `types.ts` domain shapes (replace `SetupControl`/`Classification` with stock-analysis shapes: `mode`, `runId`, `tickers`, `theme`, `topIndustry`, `totalCompany`, `topPrice`, `minHeadroom`, `days`, `universe`, `companies[]`) and rewrite `stages/index.ts` to compose the 5-mode/19-stage tree. This is the single highest-leverage decision: ~90% of the engine is reusable as-is.

- **REC-002 — Compose the pipeline with `choose()` at the root keyed on `state.mode`, each branch a `sequence([...], {tolerant:true})`.** Use `branch()` for the cross-cutting conditionals (A-share Stage 15 inside the company body via `ticker.endsWith(".SH")||ticker.endsWith(".SZ")`; screening-only Stages 2–4.5 via `mode ∈ {pipeline,screen}`; walk Stage via `mode==="walk"`). Use `map({over: state.companies, as:"company", concurrency:4})` for the per-company DAG with the 4-wave dependency ordering from SKILL.md (`[5,7,9,13]` → `[6,8,10,14]` → `[11,12]` → `[15]`), wrapping each analyst `task` in `retry({attempts:10})`. Mirror the `formatSummary` honesty rule.

- **REC-003 — Keep Python; do NOT rewrite.** Add `src/scripts.ts` `runScript(name, args, opts)` shelling to `uv run python ${EXTENSION_ROOT}/scripts/<name>.py`. Expose deterministic calcs (compute_scores, cross_check, calibrate_conviction, validate_report, score_bottleneck_asymmetry, compute_tam_adj_peg, compute_bayesian_growth) as `helperTask`/gate validators that call `runScript`. Document the akshare/baostock/no-JS-equivalent rationale prominently in README (this is the same boundary pi-super-dev drew: re-implement ORCHESTRATION in TS; keep deterministic analysis verbatim).

- **REC-004 — Reconcile the agent count + invocation preamble before copying.** The source `agents/` dir contains **22** `.md` files (includes both `team-lead.md` and `team-lead-workflow.md`, plus `market-daily-orchestrator.md` and `search-agent.md`), but the goal text says "21 specialists" and `pi-super-dev/tests/structure.test.ts:74` hard-asserts `agents.length === 21`. Decide explicitly which agents to ship (likely drop `team-lead-workflow.md` — it's the Claude-Code workflow variant superseded by the TS pipeline) and set the structure-test expectation to match. When editing preambles, replace `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` with a single `${EXTENSION_ROOT}` resolved in `extension.ts` and threaded through every prompt.

---

## 5. Anti-patterns to avoid

- **Do NOT depend on `@agwab/pi-workflow`** or any external workflow engine — the algebra is self-contained (`structure.test.ts` enforces absence).
- **Do NOT ship bundled `dependencies`** — peer-only (the structure test fails otherwise).
- **Do NOT let a `gate` throw on exhaustion** — it must return `{status:"failed"}` so the tolerant sequence keeps the best artifact (the bug documented at `nodes.ts:251-285`).
- **Do NOT copy `workflows/stock-analysis.js`** or any Claude/Codex plugin manifest (`plugin.json`, `.claude-plugin/`, `.codex-plugin/`, root `stage*.md`, root `*.py`, `reports/`).
- **Do NOT rewrite the 76 Python scripts in TS** — capability loss (akshare/baostock) + hundreds of hours for zero gain.
- **Do NOT fake the run summary** — `status` is derived from produced artifacts, never defaulted to "success".

---

## 6. Files assessed

**Template (`pi-super-dev`):** `package.json`, `src/extension.ts`, `src/nodes.ts`, `src/types.ts`, `src/workflow.ts`, `src/pipeline.ts`, `tests/structure.test.ts`, `agents/` (dir listing), `README.md`.

**Source (`stock-analysis-plugin`):** `skills/stock-analysis/SKILL.md` (modes/triggers/stages/rules/constraints), `agents/` (22 files), `scripts/` (76 `.py` + `pyproject.toml` + `uv.lock`), `references/`, `templates/`, `schemas/`, `assets/`, `pyproject.toml`.

**Target (`pi-finance`):** repo root + `docs/specifications/01-pi-stock-analysis-workflow/` (artifacts 01/02/03 only; no source code).

## 7. Summary

The target repo is empty, so there is no existing codebase to align with — the conventions to follow come **entirely from `pi-super-dev`**, which is a clean, production-grade reference for exactly this kind of port (TS control-flow engine + spawned specialist agents + copied domain assets). ~90% of the engine (`nodes.ts`, `workflow.ts`, `types.ts` primitives, `control.ts`, `helpers.ts`, `agents.ts`, `pi-spawn.ts`, `session-agent.ts`, `prompts.ts`, `extension.ts` skeleton, test harness) ports near-verbatim; the work is concentrated in (a) adapting `types.ts` domain shapes, (b) composing the 5-mode/19-stage tree in `stages/index.ts` using `choose`+`branch`+`map`+`gate`+`retry`, (c) adding `src/scripts.ts` to bridge to the verbatim Python scripts via `uv run`, and (d) porting the 22 agent `.md` files with a preamble-only edit. The two open design questions (multiple modes → `choose` + arg-parsing command; Python → keep) are already resolved by the goal's design decisions and align with the template's established boundary.
