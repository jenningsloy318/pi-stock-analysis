# 05 — Design: `@jenningsloy318/pi-stock-analysis` Pi Extension

> **Design philosophy.** This package converts an *orchestration* — the 5-mode / 19-stage equity-research pipeline in `stock-analysis-plugin/skills/stock-analysis/SKILL.md` — from a Claude-Code skill (prose instructions interpreted by an LLM) into a **deterministic TypeScript control-flow engine** that drives spawned specialist agents. It mirrors `pi-super-dev` exactly: re-implement the orchestration in TS, keep the deterministic analysis scripts + domain-knowledge artifacts verbatim, and never depend on an external workflow engine.
>
> The single most important architectural decision is the **boundary**: TS owns *when/whether/in-what-order* agents run (control flow); Python + `.md` knowledge files own *what the analysis actually computes* (domain logic). Everything below follows from drawing that seam in the right place.

---

## 1. Goals & non-goals

### 1.1 Goals
1. A valid pi extension npm package (`@jenningsloy318/pi-stock-analysis`) registered as `stock_analysis` tool + `/stock-analysis` command.
2. One unified engine over all **5 execution modes** (`pipeline`, `screen`, `analyze`, `compare`, `walk`) via a `choose` node keyed on `state.mode`.
3. Every one of the **19 stages**, **5 validation gates** (1.5 / 4.5 / 16.5 / 17.5 / 18.5), the **4-wave per-company dependency DAG**, the **adversarial-verify** (3 skeptics × top-5) and **judge-panel** (4 lenses × top-5) fan-outs, and the **retry-on-null 10×** rule, expressed as composable nodes — not prose.
4. The 76 Python scripts kept **verbatim** and invoked through a thin `runScript` shell-out to `uv run python`. Zero functional rewrites.
5. Hermetic vitest suite (`npm run typecheck` + `npm test` pass with no pi spawns, no network).
6. Tolerant execution: a failed non-setup stage is logged, not fatal; the run produces the best partial artifact set.

### 1.2 Non-goals (explicitly out of scope)
- Rewriting any of the 76 Python scripts in TS (akshare/baostock have **no Node equivalent** — see §6.2).
- Changing analytical content, frameworks, output schemas, or the composite-weights table.
- Porting the Claude/Codex plugin manifests (`plugin.json`, `.claude-plugin/`, `.codex-plugin/`, root `stage*.md`, root `*.py`, `reports/`).
- Shipping bundled runtime npm deps (peer-only — enforced by `structure.test.ts`).
- Depending on `@agwab/pi-workflow` or any external workflow engine (enforced by `structure.test.ts`).

---

## 2. Package layout (target)

```
pi-finance/                                  # the new extension repo
├── package.json                             # name @jenningsloy318/pi-stock-analysis; "pi":{extensions,skills}
├── tsconfig.json  vitest.config.ts  .gitignore  LICENSE(MIT)  CHANGELOG.md  README.md
├── pyproject.toml  uv.lock  requirements.txt   # ← copied verbatim (Python runtime for scripts/)
├── src/
│   ├── extension.ts          # default activate(pi): registerTool(stock_analysis) + registerCommand(/stock-analysis)
│   ├── pipeline.ts           # thin public entry: runStockAnalysis → runWorkflow(WORKFLOW, state, options)
│   ├── nodes.ts              # control-flow node algebra (ported from pi-super-dev verbatim)
│   ├── workflow.ts           # makeContext + runWorkflow (await root.run(state, ctx))  [ported]
│   ├── types.ts              # PipelineState/Stage/StageContext/Node/RunSummary + stock-analysis domain shapes
│   ├── agents.ts             # load agents/<name>.md                                      [ported]
│   ├── pi-spawn.ts           # spawn `pi -a <agent>` subprocess                            [ported]
│   ├── session-agent.ts      # in-process createAgentSession backend                      [ported]
│   ├── control.ts            # tolerant <control> JSON extractor                          [ported]
│   ├── helpers.ts            # deterministic helpers (runHelper dispatcher)               [ported]
│   ├── prompts.ts            # prompt builders (EXTENSION_ROOT injection)                 [adapted]
│   ├── scripts.ts            # NEW: runScript(name, args, {cwd, root}) → uv run python    [new]
│   ├── tickers.ts            # NEW: A-share ticker normalization                          [new]
│   ├── args.ts               # NEW: /stock-analysis NL arg parser                          [new]
│   └── stages/
│       ├── index.ts          # WORKFLOW root: choose(mode) → 5 branches                   [new — the heart]
│       ├── setup.ts          # Stage 0 (fatal)                                             [new]
│       ├── data.ts           # Stages 1, 1.5                                               [new]
│       ├── screening.ts      # Stages 2, 3, 4, 4.5 (pipeline+screen only)                 [new]
│       ├── company.ts        # Stages 5–15 per-company DAG (map concurrency:4, 4 waves)   [new]
│       ├── walk.ts           # walk mode Stage                                             [new]
│       ├── scoring.ts        # Stages 16, 16.5, 16.6, 16.7                                 [new]
│       ├── reports.ts        # Stages 17, 17.4, 17.5                                       [new]
│       ├── bestpicks.ts      # Stages 18, 18.5                                             [new]
│       └── cleanup.ts        # Stage 19                                                    [new]
├── tests/                    # hermetic vitest (structure, nodes, control, args, tickers, scripts-mock, mode-dispatch)
├── agents/                   # 21 × <name>.md (copied + preamble-only edit; drop team-lead-workflow.md)
├── skills/stock-analysis/SKILL.md   # SHORT pointer (orchestration now lives in TS)
├── scripts/                  # 76 × *.py (copied verbatim)
├── references/               # gics_taxonomy, data_source_matrix, frameworks_*, pitfalls/, serenity/, … (copied)
├── templates/                # equity-report.md, screening-report.md, *.j2, *.json (copied)
├── schemas/                  # 16 × *.json (copied)
└── assets/                   # report_styles.css (copied)
```

**Ported vs new vs copied** (the three buckets — see §6.1 for the boundary rationale):

| Bucket | Files | Action |
|---|---|---|
| **Engine** (`src/*.ts` except `scripts/tickers/args/stages/*`) | `nodes.ts`, `workflow.ts`, `types.ts` (adapt domain shapes), `agents.ts`, `pi-spawn.ts`, `session-agent.ts`, `control.ts`, `helpers.ts`, `prompts.ts`, `extension.ts` skeleton, `pipeline.ts` | **Port ~90% verbatim** from `pi-super-dev`; adapt only `types.ts` domain shapes + `prompts.ts` EXTENSION_ROOT injection + `extension.ts` param shape/log dir. |
| **Domain** (`src/scripts.ts`, `tickers.ts`, `args.ts`, `stages/*`) | the 5-mode tree, runScript, ticker normalization, arg parser | **New** — this is where the SKILL.md gets translated into the node algebra. |
| **Assets** (`agents/`, `scripts/`, `references/`, `templates/`, `schemas/`, `assets/`, `pyproject.toml`, `uv.lock`, `requirements.txt`) | 21 agents, 76 scripts, all knowledge files | **Copy verbatim**; agents get a preamble-only edit (Claude→pi invocation notes). |

---

## 3. Module decomposition (interfaces + depth)

Each module below is a **deep module**: small interface, large behavior behind it. The interface column is everything a caller must know; the implementation is free to grow.

### M-01 `nodes.ts` — control-flow node algebra *(ported verbatim)*
- **Interface:** `task(stage)`, `sequence(children, {tolerant})`, `branch(pred, a, b)`, `choose(cases, otherwise)`, `parallel(nodes, {concurrency})`, `loop({while, body})`, `retry(node, {attempts, matches})`, `gate({validate, attempts, feedbackKey})`, `map({over, as, concurrency}, body)`, `wait(ms)`, `waitForEvent(event)`, `tryCatch(node, recover)`, `noop()`, plus writers `writerTask`/`helperTask`/`gateValidator`.
- **Implementation:** every node is `{kind, run(state, ctx): Promise<NodeResult>}`; control nodes recurse into children; the engine is literally `await root.run(state, ctx)`.
- **Depth rationale (Deletion Test):** deleting this module would force every stage file to reimplement parallelism, retries, and gate feedback — complexity would reappear across ~10 callers. It earns its keep.
- **Seam:** the `Node` interface is the one thing every stage composes against; adding a construct = one builder, zero runner changes.

### M-02 `workflow.ts` — runner + context factory *(ported)*
- **Interface:** `makeContext(state, options): StageContext`, `runWorkflow(workflow, state, options): Promise<RunSummary>`.
- **Implementation:** builds one `StageContext` (agent/helper/parallel/budget/log/events/signal), threads it through `root.run`, derives `RunStatus` from produced artifacts (never fakes).
- **Depth:** callers see `runWorkflow(WORKFLOW, state, opts)`; behind it sit the entire agent-spawn backend selection (`STOCK_ANALYSIS_BACKEND = session|subprocess`), budget enforcement, feedback injection, and honest-status derivation.

### M-03 `types.ts` — domain shapes *(adapted)*
- **Interface:** `PipelineState` (with stock-analysis keys), `Stage`, `StageContext`, `Node`, `NodeResult`, `RunSummary`, plus new domain shapes below.
- **Stock-analysis domain shapes (replace super-dev's `SetupControl`/`Classification`):**
  ```ts
  type Mode = "pipeline" | "screen" | "analyze" | "compare" | "walk";
  type Universe = "US" | "CN" | "ALL";

  interface RunSetup {                  // state.setup  (Stage 0 output, fatal)
    mode: Mode;
    runId: string;                      // YYYYMMDDHHmm LOCAL TIME
    reportDir: string;                  // ./reports/[runId]/
    tickers: string[];                  // normalized (analyze/compare: user-supplied; pipeline/screen: populated at St 4; walk: populated post-walk)
    theme?: string;                     // walk only
    universe: Universe;
    topIndustry: number; totalCompany: number; topPrice: number;
    minHeadroom: number; days: number;
    extensionRoot: string;              // EXTENSION_ROOT (dir of package.json)
  }
  interface Company { ticker: string; name?: string; gics?: string; isAsh: boolean; }
  // state.companies: Company[]          (populated at Stage 4 / walk)
  // state.sharedData, state.screening, state.scoring, state.verify, state.judge,
  // state.reports[], state.bestPicks, state.gates{...}, state.__feedback{...}
  ```

### M-04 `extension.ts` — tool + command registration *(adapted from pi-super-dev)*
- **Interface:**
  - `registerTool("stock_analysis", { parameters: Type.Object({...}), execute(toolCallId, params, signal, onUpdate) })`
  - `registerCommand("/stock-analysis", { handler(args, ctx) })`
- **Tool parameters (Type.Object):** see §5.1.
- **execute() contract:** build a `ProgressSink` (rolling tail `TAIL_LINES = 400`, 80ms-throttled `text(partial)` typing stream), run `runWorkflow`, write full transcript to `.stock-analysis-logs/<ISO>-<runId>.log`, return honest `formatSummary` (success/partial/failed derived from `state.reports`/`state.bestPicks`/`state.gates`).
- **command handler contract:** parse NL args (§5.2) → `pi.sendUserMessage("Use the stock_analysis tool with mode=..., tickers=[...] ...")` so the agent invokes the tool (interruptible, streams progress). **The command never runs the pipeline itself** — same seam as `/super-dev`.

### M-05 `stages/index.ts` — the WORKFLOW root *(new — the heart of the port)*
- **Interface:** `export const WORKFLOW: Workflow` — one tree, evaluated by `runWorkflow`.
- **Structure:** `choose([{when: mode==="pipeline", then: pipelineSeq}, ...screen, ...analyze, ...compare, ...walk], otherwise: pipelineSeq)` where each branch is `sequence([...], {tolerant:true})`. See §7 for the full per-mode composition.
- **Depth:** this is the deepest module — 19 stages, 5 gates, 4-wave DAG, 2 fan-outs (verify/judge), all behind one `WORKFLOW` reference. The interface is "run it"; the implementation is the entire orchestration.

### M-06 `scripts.ts` — Python bridge *(new)*
- **Interface:** `runScript(name, args?, opts?: {cwd?, root?, timeoutMs?}): Promise<{stdout, stderr, json?, exitCode}>`.
- **Implementation:** `child_process.spawn("uv", ["run","python", join(root,"scripts",`${name}.py`), ...args], {cwd})` with stderr capture, timeout (default 10 min), and best-effort JSON parse of stdout's trailing `<control>{...}</control>` or pure-JSON block. `root` defaults to `EXTENSION_ROOT` resolved once in `extension.ts`.
- **Depth rationale:** one function stands between 21 agents and 76 scripts. Callers pass a name + args; they get parsed structured output. The alternative (every agent hand-shelling `uv run python ...`) scatters path/timeout/parse logic across hundreds of call sites.

### M-07 `tickers.ts` — A-share normalization *(new)*
- **Interface:** `normalizeTicker(input: string): {ticker, isAsh, resolvedFrom?}`; `normalizeTickers(inputs: string[]): string[]`.
- **Rules (from SKILL.md):** numeric-only starting with `6` → `.SH`; other numeric → `.SZ`; Chinese name → akshare lookup (via `runScript("resolve_ticker", [name])`); already-suffixed → pass-through. `isAsh = ticker.endsWith(".SH") || ticker.endsWith(".SZ")`.
- **Testability:** pure for the numeric/suffix cases (deterministic unit tests); the name-lookup path is isolated behind one seam so tests mock `runScript`.

### M-08 `args.ts` — `/stock-analysis` arg parser *(new)*
- **Interface:** `parseCommandArgs(argString: string): {mode, tickers?, theme?, topIndustry?, totalCompany?, topPrice?, minHeadroom?, days?, universe?, query?}`.
- **Precedence (from SKILL.md `<triggers>`):** explicit `--mode <name>` (authoritative) → trigger-phrase detection → default `pipeline`. Positional tickers after `--mode analyze`; comma-list after `--mode compare` (2–5); positional/quoted theme after `--mode walk`. Plus `--top-industry`, `--total-company`, `--top-price`, `--min-headroom`, `--days`, `--universe`.
- **Depth:** one parser owns all 5 modes' input shape; the command handler is a 3-liner around it.

### M-09 `helpers.ts` — deterministic helper dispatcher *(ported + extended)*
- **Interface:** `runHelper(call: HelperCall): Promise<HelperResult>` dispatching by `call.name`.
- **Extension:** add helper names that wrap `runScript` for the deterministic calcs SKILL.md names explicitly: `compute_scores`, `cross_check`, `calibrate_conviction`, `validate_report`, `score_bottleneck_asymmetry`, `compute_tam_adj_peg`, `compute_bayesian_growth`, `compute_health_index`, `compute_factors`. Each is a thin `runScript(name, args)` + digest. Gates and the scorer stage call these via `helperTask`/`gateValidator` so the deterministic logic is testable with a mocked `runScript`.

### M-10 `agents.ts`, `pi-spawn.ts`, `session-agent.ts`, `control.ts`, `prompts.ts` *(ported)*
- **`agents.ts`:** `loadAgent(name): string` reads `agents/<name>.md`.
- **`pi-spawn.ts`:** `spawnAgent({agent, prompt, cwd, model, signal})` → `pi -a <agent>` subprocess with progress streaming; `abbreviatePath`.
- **`session-agent.ts`:** `createAgentSession(...)` in-process backend (default).
- **`control.ts`:** tolerant `<control>{...}</control>` JSON extractor + `extractControlKeys`.
- **`prompts.ts`:** prompt builders; **adaptation:** inject `${EXTENSION_ROOT}` (resolved in `extension.ts`) into every prompt so agents reference `${EXTENSION_ROOT}/scripts`, `/references`, `/templates`, `/schemas` — replacing SKILL.md's `${CLAUDE_PLUGIN_ROOT}`.

---

## 4. Data flow

```
User →  /stock-analysis "analyze AAPL,MSFT --top-price 300"
          │
          ▼  args.parseCommandArgs()                      [M-08]
        {mode:"analyze", tickers:["AAPL","MSFT"], topPrice:300}
          │
          ▼  pi.sendUserMessage("Use stock_analysis tool …")
        agent invokes tool stock_analysis(params)
          │
          ▼  extension.execute() → runWorkflow(WORKFLOW, state, opts)   [M-02,M-05]
        ┌──────────────────── WORKFLOW (choose on state.mode) ───────────────────┐
        │                                                                          │
        │  Stage 0 setup (FATAL): normalize tickers [M-07], RUN_ID, mkdir,        │
        │      init tracking.json, resolve EXTENSION_ROOT                          │
        │          │                                                               │
        │  Stage 1 data-collector (shared ONCE) → state.sharedData                │
        │  Stage 1.5 GATE (report-validator ×4, feedbackKey "sharedData")         │
        │          │                                                               │
        │  ┌─ branch(mode ∈ {pipeline,screen}) ──────────────────────────────┐    │
        │  │  St 2 sector-screener (map 3 batches × ~54)                     │    │
        │  │  St 3 sub-industry deep-dive (parallel waves max 4)             │    │
        │  │  St 4 company-screener → state.companies                        │    │
        │  │  St 4.5 GATE                                                     │    │
        │  └─────────────────────────────────────────────────────────────────┘    │
        │  ┌─ branch(mode === "walk") ───────────────────────────────────────┐    │
        │  │  walk roadmap-walker → state.companies (top 3-5 by asymmetry)   │    │
        │  └─────────────────────────────────────────────────────────────────┘    │
        │          │                                                               │
        │  ┌─ map({over: state.companies, concurrency:4}) ───────────────────┐    │
        │  │   per-company company-orchestrator sequence:                     │    │
        │  │     wave1 parallel [5,7,9,13]   each wrapped retry(attempts:10) │    │
        │  │     wave2 parallel [6,8,10,14]  (6←5,8←7,10←5+7,14←13)          │    │
        │  │     wave3 parallel [11,12]      (←10)                           │    │
        │  │     wave4 branch(isAsh) [15]    (←all, .SH/.SZ only)            │    │
        │  └─────────────────────────────────────────────────────────────────┘    │
        │          │                                                               │
        │  St 16 scorer (helperTask compute_scores/cross_check/calibrate)         │
        │  St 16.5 GATE (validate scoring, feedbackKey "scoring")                 │
        │  St 16.6 adversarial verify: map(top5 × 3 skeptics), ≥2/3 survive       │
        │  St 16.7 judge panel:      map(top5 × 4 lenses)  Buffett/Lynch/Marks/Dr │
        │          │                                                               │
        │  St 17 reports (branch on mode: screening | company | comparison | walk)│
        │  St 17.4 completeness critic: map(1 critic per report)                  │
        │  St 17.5 GATE (helperTask validate_report — 8 gates via runScript)      │
        │          │                                                               │
        │  St 18 best-picks highlight (group by position type core/satellite/opt) │
        │  St 18.5 GATE                                                            │
        │  St 19 cleanup (always last)                                            │
        └──────────────────────────────────────────────────────────────────────────┘
          │
          ▼  formatSummary(state) → success|partial|failed      [PAT-003]
        transcript → .stock-analysis-logs/<ISO>-<runId>.log
        final markdown summary streamed to user
```

**Key data-flow invariants (from SKILL.md, enforced by the tree shape):**
- **Shared data once:** Stage 1 writes `state.sharedData` exactly once; every downstream analyst reuses it (no re-fetching). The `1.5` gate blocks Stages 2+ on staleness.
- **Price/headroom/universe filters at Stage 4 only** — never re-applied downstream (the analysis stages see the already-filtered `state.companies`).
- **A-share mandatory:** Stage 15 runs iff `company.isAsh`; the `branch` lives *inside* the per-company body so non-A-share companies skip it without affecting siblings.
- **Retry-on-null 10×** wraps **every** spawned analyst/scorer/validator/writer task; exhaustion → `{status:"failed"}`, logged in `tracking.json`, pipeline continues.
- **Max-4 concurrency:** the per-company `map({concurrency:4})` plus each company's internal `parallel({concurrency:4})` mirror SKILL.md's async-pool scheduling.
- **Reports in 中文** (rule "Report Language") — preserved verbatim in agent prompts + templates.

---

## 5. Interfaces (detailed)

### 5.1 `stock_analysis` tool parameters (Type.Object)

```ts
Type.Object({
  mode:        Type.Optional(Type.Union([
                 Type.Literal("pipeline"), Type.Literal("screen"),
                 Type.Literal("analyze"),  Type.Literal("compare"),
                 Type.Literal("walk")
               ], { description: "Execution mode. Default 'pipeline'." })),
  tickers:     Type.Optional(Type.Array(Type.String(), {
                 description: "Required for analyze/compare. compare needs 2-5. A-share numeric/name auto-normalized."
               })),
  theme:       Type.Optional(Type.String({ description: "Required for walk. Quoted multi-word allowed." })),
  topIndustry: Type.Optional(Type.Number({ description: "Top sub-industries (or walk candidates). Default 8/40/7 by mode." })),
  totalCompany:Type.Optional(Type.Number({ description: "Companies to deep-dive. pipeline only. Default 15, cap 50." })),
  topPrice:    Type.Optional(Type.Number({ description: "Max price filter at Stage 4. Default 200. 0 disables." })),
  minHeadroom: Type.Optional(Type.Number({ description: "Min Growth-Headroom score 1-10. Default 5." })),
  days:        Type.Optional(Type.Number({ description: "Hot-sector focus window 1-20. Default 1." })),
  universe:    Type.Optional(Type.Union([Type.Literal("US"), Type.Literal("CN"), Type.Literal("ALL")], { description: "Default US." })),
  query:       Type.Optional(Type.String({ description: "Raw NL query (the command parses this into the fields above)." })),
  model:       Type.Optional(Type.String()),
  maxAgents:   Type.Optional(Type.Number()),
})
```

### 5.2 `/stock-analysis` command arg-parser contract (args.ts)

```
parseCommandArgs(s: string) → ParsedArgs

Precedence:
  1. --mode <name>         (authoritative; overrides triggers)
       analyze  → consume positional tokens until next --flag as tickers[]
       compare  → consume one token, split on "," → tickers[] (validate 2-5)
       walk     → consume rest-of-line (quoted) as theme
  2. trigger-phrase match  (SKILL.md <triggers> tables; EN + 中文)
  3. default pipeline

Also parse: --top-industry N, --total-company M, --top-price N,
            --min-headroom N, --days N, --universe US|CN|ALL
Unknown flags ignored (lenient). Original string preserved as `query`.
```

### 5.3 `runScript` contract (scripts.ts)

```ts
runScript(name: string, args?: string[], opts?: {
  cwd?: string;            // default: process.cwd()
  root?: string;           // default: EXTENSION_ROOT
  timeoutMs?: number;      // default: 600_000 (10 min)
  signal?: AbortSignal;
}): Promise<{
  stdout: string;
  stderr: string;
  exitCode: number;
  json?: unknown;          // best-effort parse of trailing JSON / <control> block
}>
```
Throws on non-zero exit (caught by the enclosing `task`/`retry`/`gate`).

---

## 6. Design decisions

### 6.1 Boundary: TS owns control flow; Python + `.md` own domain logic
This is the same seam `pi-super-dev` drew. The Deletion Test confirms it: if `scripts.ts` were deleted, the 76 scripts' invocation logic (path resolution, `uv` env, timeout, JSON parsing) would have to be reimplemented in every agent prompt — and agents are bad at reliable shelling. Concentrating it in one deep module gives us locality (change the invocation contract in one place) and leverage (21 agents reuse one helper).

### 6.2 Keep Python — do NOT rewrite (the explicit user-facing decision)
**Rationale (to document in README):**
- **76 scripts** with heavy scientific/financial deps: `akshare` + `baostock` (China A-share — **no Node.js equivalent exists, full stop**), `yfinance`, `scipy`, `statsmodels`, `arch` (GARCH), `pandas-ta`, `polars`, `praw` (Reddit), `pytrends` (Google Trends), `tickflow`, `curl_cffi`.
- Rewriting = hundreds of hours, zero functional gain, **real capability loss** (akshare/baostock cannot be replaced).
- SKILL.md already mandates `uv run python ${PLUGIN_ROOT}/scripts/<script>.py` — we keep that contract, swapping `${PLUGIN_ROOT}` → `${EXTENSION_ROOT}`.
- The TS layer orchestrates + spawns agents; agents invoke python via `runScript` / `uv run`. Exactly the super-dev boundary.

### 6.3 Multiple modes → `choose` node + tool param + arg-parsing command
One tool, one command, one `WORKFLOW` root. The `choose([{when, then}], otherwise)` node dispatches on `state.mode` → the correct stage sequence per SKILL.md `<modes>`. Cross-cutting conditionals (`A-share Stage 15`, `screening-only 2–4.5`, `walk`) are `branch()` inside the relevant sequence. This avoids 5 separate pipelines and keeps the per-mode diff visible in one file (`stages/index.ts`).

### 6.4 Per-company DAG → `map` + nested `parallel` waves
`map({over: state.companies, as: "company", concurrency: 4}, body)` where `body` is a `sequence` of 4 `parallel` waves matching SKILL.md `<dependencies>`: `[5,7,9,13]` → `[6,8,10,14]` → `[11,12]` → `[15]`. Each analyst `task` is wrapped in `retry({attempts: 10})` for retry-on-null. Wave 4's Stage 15 is `branch(company.isAsh, task(...), noop())`.

### 6.5 Gates converge via `state.__feedback[feedbackKey]`
The 5 validation stages (1.5 / 4.5 / 16.5 / 17.5 / 18.5) are `gate({validate, attempts: 4, feedbackKey})`. On failure the gate stores validator errors under `state.__feedback[key]`; `workflow.ts` prepends them to the next attempt's prompt so the agent fixes the specific failure rather than resampling blindly. **A gate never throws on exhaustion** — it returns `{status:"failed"}` and the tolerant sequence keeps the best artifact.

### 6.6 Agent count reconciliation (22 → 21)
Source `agents/` has **22** files. We **drop `team-lead-workflow.md`** (the Claude-Code workflow variant — superseded by the TS pipeline; `team-lead.md` stays as the per-run coordinator). `search-agent.md` and `market-daily-orchestrator.md` stay (used by data-collector / walk). `structure.test.ts` asserts `agents.length === 21`.

### 6.7 Backend selectable via env (`STOCK_ANALYSIS_BACKEND`)
Mirror `pi-super-dev`: default `"session"` (in-process `createAgentSession` with per-stage structured-output schema); `"subprocess"` (`pi -a <agent>` spawn). Read from `options.backend ?? process.env.STOCK_ANALYSIS_BACKEND ?? "session"`.

### 6.8 EXTENSION_ROOT resolution
Resolved once in `extension.ts` (dir of `package.json` via `fileURLToPath(import.meta.url)`), stored in `state.setup.extensionRoot`, injected into every agent prompt by `prompts.ts`. Replaces all `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}` references. Agents reference `${EXTENSION_ROOT}/scripts|references|templates|schemas`.

---

## 7. Pipeline composition (per mode)

Legend: `→` sequence, `‖` parallel, `↻` retry(attempts:10), `▣` gate(attempts:4), `?` branch.

```
ROOT = choose([
  { when: s.mode==="pipeline", then: PIPELINE },
  { when: s.mode==="screen",   then: SCREEN   },
  { when: s.mode==="analyze",  then: ANALYZE  },
  { when: s.mode==="compare",  then: COMPARE  },
  { when: s.mode==="walk",     then: WALK     },
], otherwise: PIPELINE)

COMMON_HEAD = 0(setup,FATAL) → 1(data) → ▣1.5(validate shared, key="sharedData")
COMMON_TAIL = 16(scorer) → ▣16.5(key="scoring") → 16.6(verify) → 16.7(judge)
           → 17(reports) → 17.4(critic) → ▣17.5(validate_report×8) 
           → 18(bestpicks) → ▣18.5 → 19(cleanup)

PIPELINE = sequence([ COMMON_HEAD,
   2(sector-screener: map 3 batches × ~54) → 3(deep-dive ‖ max4) → 4(company-screen) → ▣4.5,
   PER_COMPANY_DAG,
   COMMON_TAIL ], {tolerant:true})

SCREEN = sequence([ COMMON_HEAD,
   2 → 3 → 4 → ▣4.5,
   17(screening reports only) → 17.4 → ▣17.5 → 19 ], {tolerant:true})
   // NOTE: screen skips 16/16.6/16.7/18 — no per-company deep-dive

ANALYZE  = sequence([ COMMON_HEAD, PER_COMPANY_DAG, COMMON_TAIL ], {tolerant:true})
COMPARE  = ANALYZE   // identical valuation methodology; tickers validated 2-5 at setup
WALK     = sequence([ COMMON_HEAD,
   walk(roadmap-walker) → populate state.companies (top 3-5 by asymmetry_composite),
   PER_COMPANY_DAG, COMMON_TAIL ], {tolerant:true})

PER_COMPANY_DAG = map({over: s.companies, as:"company", concurrency:4}, c =>
   sequence([
     ‖([ ↻task(5,c),  ↻task(7,c),  ↻task(9,c),  ↻task(13,c) ]),   // wave 1 (concurrency 4)
     ‖([ ↻task(6,c),  ↻task(8,c),  ↻task(10,c), ↻task(14,c) ]),   // wave 2 (deps satisfied by wave 1)
     ‖([ ↻task(11,c), ↻task(12,c) ]),                             // wave 3 (←10)
     branch(c.isAsh, ↻task(15,c), noop())                         // wave 4 (A-share only)
   ]))

16.6 verify = map({over: top5, concurrency:5}, pick =>
   ‖([ skeptic("fundamentals",pick), skeptic("macro",pick), skeptic("flow",pick) ]))
   // pick survives iff ≥2 of 3 do NOT refute

16.7 judge = map({over: top5, concurrency:5}, pick =>
   ‖([ lens("Buffett",pick), lens("Lynch",pick), lens("Marks",pick), lens("Druckenmiller",pick) ]))
```

---

## 8. Numeric constants requiring validation

These are the **bounded/numeric invariants** the code must enforce (in `setup.ts` arg normalization and `structure.test.ts` / `args.test.ts`). Each is sourced from SKILL.md `<triggers>` / `<stages>`.

| Constant | Valid range / value | Default | Source | Where enforced |
|---|---|---|---|---|
| `topIndustry` | 1 – 163 | pipeline 8 / screen 40 / walk 7 | SKILL `<stage n=0>` `--top-industry (1-163)` | `setup.ts` + `args.ts` |
| `totalCompany` | 1 – 50 | 15 (pipeline only) | SKILL `--total-company (1-50, pipeline only)` | `setup.ts` |
| `topPrice` | 0 – 9999 | 200 (0 = disabled) | SKILL `--top-price (0-9999, default 200)` | `setup.ts` |
| `minHeadroom` | 1 – 10 | 5 | SKILL `--min-headroom (1-10, default 5)` | `setup.ts` |
| `days` | 1 – 20 | 1 | SKILL `--days (1-20, default 1)` | `setup.ts` |
| `compare` ticker count | 2 – 5 | — | SKILL `<mode compare>` `Max 5 stocks` | `setup.ts` |
| `walk` deep-dive candidates | 3 – 5 | top by asymmetry | SKILL `<stage walk>` `TOP 3-5 candidates` | `walk.ts` |
| GICS Level-4 sub-industries | exactly 163 | — | SKILL `<stage n=2>` `ALL 163 GICS Level 4` | constant in `screening.ts` |
| Stage 2 batches | 3 × ~54 | — | SKILL `<stage n=2>` `3 parallel batches of ~54` | `screening.ts` |
| Per-company concurrency | 4 | 4 | SKILL `<orchestration-model>` `max 4 concurrent` | `map({concurrency:4})` |
| Analyst wave concurrency | 4 | 4 | SKILL `<wave n=1 agents="4">` etc. | `parallel({concurrency:4})` |
| retry attempts (null/crash) | 10 | 10 | SKILL `<orchestration-model>` `retry up to 10 times` | `retry({attempts:10})` |
| gate attempts | 4 | 4 | PAT-005 convention | `gate({attempts:4})` |
| Adversarial verify skeptics/pick | 3 | 3 | SKILL `<stage 16.6>` `3 perspective-diverse skeptics` | `16.6 map` |
| Verify survival threshold | ≥ 2 of 3 | — | SKILL `<stage 16.6>` `≥2 of 3 do NOT refute` | verify result reducer |
| Judge panel lenses | 4 (Buffett/Lynch/Marks/Druckenmiller) | 4 | SKILL `<stage 16.7>` | `16.7 map` |
| Judge top-N picks | 5 | 5 | SKILL `<stage 16.6/16.7>` `For top 5 picks` | top-5 selector |
| Moat/Management LLM adjust | ±2.0 | — | SKILL `<stage 16>` `±2.0` | scorer prompt + gate 16.5 |
| Valuation qualitative adjust | ±15% | — | SKILL `<stage 10 Step 3c>` `±15%` | quant-analyst prompt |
| Bottleneck chokepoint threshold | score ≥ 3 | — | SKILL `<stage walk>` `score ≥3` | walk.ts |
| validate_report gates | 8 | 8 | SKILL `<stage 17.5>` `8 gates` | helperTask `validate_report` |
| `runScript` timeout | 600 000 ms | 10 min | convention | `scripts.ts` |
| Progress `TAIL_LINES` | 400 | 400 | PAT-002 | `extension.ts` |
| Progress text throttle | 80 ms | 80 ms | PAT-002 | `extension.ts` |
| Composite score components | 11 | 11 | SKILL `<stage 2/16>` `11 dimensions/components` | scorer + gate 16.5 |
| Composite weights | weighted-sum table | — | SKILL `<composite-weights>` | `compute_scores.py` (verbatim) + gate 16.5 verifies |
| Agent count shipped | 21 | 21 | §6.6 reconciliation | `structure.test.ts` |
| Python scripts shipped | 76 | 76 | source dir count | `structure.test.ts` |
| Schemas shipped | 16 | 16 | source `schemas/` | `structure.test.ts` |
| Node engine | ≥ 22.19 | — | pi-super-dev convention | `package.json` `engines` |

**Validation strategy:** bounded params are clamped/rejected in `setup.ts` (FATAL stage — bad input stops the run before any fetch); structural counts are asserted in `tests/structure.test.ts`; behavioral thresholds (retry 10, gate 4, concurrency 4, ≥2/3 survive, ±2.0, ±15%) are encoded as node-builder arguments and asserted in `tests/nodes.test.ts` / `tests/mode-dispatch.test.ts`.

---

## 9. Interface alternatives considered (Design It Twice)

For the **mode-dispatch** seam, three radically different interfaces were considered:

### Alt A — Single `choose` node (RECOMMENDED)
One `WORKFLOW` root; `choose` on `state.mode`. Cross-cutting conditionals are inner `branch`es.
- **Pros:** one file (`stages/index.ts`) shows the entire 5-mode diff; reuses the generic `choose`/`branch` algebra; trivially testable (assert `choose` picks the right branch per mode).
- **Cons:** the file is large.

### Alt B — Five separate `Workflow` exports (`PIPELINE`, `SCREEN`, …)
`extension.ts` selects `WORKFLOWS[mode]`.
- **Pros:** each mode isolated.
- **Cons:** duplicates `COMMON_HEAD`/`COMMON_TAIL` 5×; the cross-mode invariants (shared-data-once, A-share, retry-10) must be re-asserted in each; drift risk. Rejected — violates locality.

### Alt C — Data-driven stage table (`stages: StageDef[]` filtered by `modes:` field)
A declarative table; a generic runner filters by mode + dependency order.
- **Pros:** most declarative; closest to SKILL.md's `<stage modes="...">` annotations.
- **Cons:** requires a *new* runtime (the very thing we're avoiding by porting `nodes.ts`); loses the self-evaluating `Node` algebra; the per-company DAG and fan-outs don't fit a flat table. Rejected — re-introduces an external workflow engine in disguise.

**Decision:** Alt A. It maximizes reuse of the ported algebra, keeps one source of truth, and the only cost (file size) is acceptable for the orchestration heart.

---

## 10. Test strategy (hermetic, no pi spawns, no network)

| Test file | Covers |
|---|---|
| `tests/structure.test.ts` | package layout: `pi.extensions`=[`./src/extension.ts`], `pi.skills`=[`./skills/stock-analysis`], `pi-package` keyword, **no `dependencies`**, **no `@agwab/pi-workflow`**, node-algebra exports, `stock_analysis` tool + `/stock-analysis` command registration, agent count === 21, scripts count === 76, schemas === 16, `EXTENSION_ROOT` resolution. |
| `tests/nodes.test.ts` | `task`/`sequence`/`branch`/`choose`/`parallel`/`loop`/`retry`/`gate`/`map`/`wait`/`tryCatch`/`noop` semantics (ported test, re-asserted). |
| `tests/control.test.ts` | tolerant `<control>` extraction, `extractControlKeys`. |
| `tests/args.test.ts` | `parseCommandArgs`: all 5 `--mode` shapes, trigger-phrase fallback (EN + 中文), `--flags`, compare 2-5 validation, quoted walk theme. |
| `tests/tickers.test.ts` | `normalizeTicker`: `600519→.SH`, `000001→.SZ`, `600519.SH` pass-through, Chinese-name→akshare (mocked `runScript`). |
| `tests/scripts.test.ts` | `runScript`: mocked `child_process.spawn` — asserts `uv run python <root>/scripts/<name>.py` argv, timeout, stderr capture, JSON parse, non-zero-exit throw. |
| `tests/mode-dispatch.test.ts` | `WORKFLOW` root: for each `state.mode`, `choose` selects the correct branch and the expected stage IDs appear in execution order (using a recording `StageContext` with a stub `agent`). |

**Replace, don't layer:** tests exercise the real `WORKFLOW` tree with a stubbed `agent`/`helper`/`runScript` — no parallel process, no network, no Python invocation. The same seam callers cross is the seam tests cross.

---

## 11. Migration path (incremental, each step green)

1. **Scaffold** — `package.json`, `tsconfig.json`, `vitest.config.ts`, `.gitignore`, `LICENSE`, `CHANGELOG.md`, empty `src/`, `tests/`, `skills/`. `npm run typecheck` passes on an empty extension stub.
2. **Port engine** — copy `nodes.ts`, `workflow.ts`, `types.ts`, `agents.ts`, `pi-spawn.ts`, `session-agent.ts`, `control.ts`, `helpers.ts`, `prompts.ts` from `pi-super-dev`; adapt `types.ts` domain shapes + `prompts.ts` EXTENSION_ROOT. Port + adapt the corresponding `tests/`. `npm test` green.
3. **Copy assets** — `agents/` (21, drop `team-lead-workflow.md`, preamble-edit the rest), `scripts/` (76) + `pyproject.toml` + `uv.lock` + `requirements.txt`, `references/`, `templates/`, `schemas/`, `assets/`. `structure.test.ts` green.
4. **New domain modules** — `scripts.ts`, `tickers.ts`, `args.ts` + their tests. Green.
5. **Stages** — compose `stages/index.ts` + per-stage files (setup/data/screening/company/walk/scoring/reports/bestpicks/cleanup). `mode-dispatch.test.ts` green.
6. **Extension** — `extension.ts` (tool + command + progress sink + log + `formatSummary`) + short `skills/stock-analysis/SKILL.md`. Full `structure.test.ts` green.
7. **README** — install, 5-mode `/stock-analysis` examples, node-algebra table, per-mode pipeline diagram, the explicit keep-Python rationale, `uv` invocation notes.

Each step leaves `npm run typecheck && npm test` green.

---

## 12. Open questions / risks

- **R-001** `akshare`/`baostock` require a working `uv` env on the host. README must document `uv sync` as a prerequisite; `runScript` should surface a clear error if `uv` is missing (detect once at setup, fail FATAL with actionable message rather than per-script).
- **R-002** The composite-weights table lives in `compute_scores.py` (verbatim) — gate 16.5 must read the **same** weights the script used. Mitigation: gate reads weights from the script's own output artifact, not a TS re-declaration.
- **R-003** Agent preamble edits are mechanical but numerous (21 files). A `tests/agents.test.ts` asserting no remaining `${CLAUDE_PLUGIN_ROOT}` / `subagent_type=` literals catches misses.
- **R-004** `search-agent.md` / `market-daily-orchestrator.md` aren't on the main 19-stage spine — confirm they're invoked by `data-collector` / `walk` before shipping (else drop to 19 agents + update the structure test).

---

## 13. Summary

This design converts a 1,500-line prose skill into a deterministic TypeScript control-flow engine by **porting ~90% of `pi-super-dev`'s engine verbatim** and concentrating the new work in four places: (1) `types.ts` domain shapes, (2) `stages/index.ts` — the 5-mode/19-stage tree composed from `choose`/`branch`/`map`/`gate`/`retry`, (3) `scripts.ts` — a one-function Python bridge preserving the 76 verbatim scripts, and (4) `args.ts`/`tickers.ts` — the command parser and A-share normalizer. The boundary is deliberate and tested: TS owns *control flow*, Python + `.md` own *domain logic*, and `structure.test.ts` enforces the invariants (no bundled deps, no external workflow engine, exact asset counts, tool+command registration).
