# Technical Specification — pi-stock-analysis (pi Extension)

**Feature:** `@jenningsloy318/pi-stock-analysis` — self-contained pi control-flow workflow extension for unified equity research
**Task type:** refactor / port (re-implement orchestration of an existing Claude Code plugin as a pi extension)
**Author:** spec-writer
**Status:** implementation-ready
**Scope:** backend-only (`UI Scope: none`); operates directly in `/home/jenningsl/development/personal/pi-finance` (skipWorktree — target is an empty git repo)

---

## 0. Document Map

This specification is the **single source of truth** for the technical implementation. It is cross-referenced as follows:

| Upstream artifact | Used for |
|---|---|
| `01-requirements.md` | AC-01…AC-25 (acceptance criteria) + DD-1…DD-4 (binding design decisions) + NFR-1…NFR-7 |
| `02-bdd-scenarios.md` | SCENARIO-001…SCENARIO-050 (behavioral coverage); every scenario is addressable by a design section below |
| `03-research-report.md` | OPT-A1/B1/C1/D1 (chosen options); OQ-1…OQ-7 resolutions; BP-01…BP-04 best practices; ISS-01…ISS-06 risks |
| `04-code-assessment.md` | PAT-001…PAT-011 patterns; REC-001…REC-004 recommendations; DEP-001…DEP-004 dependency rules |

**Coverage invariant:** Every AC-NN maps to at least one §N section below; every SCENARIO-NNN is addressable by the design in this document. A traceability matrix is provided in §12.

---

## 1. Overview & Architecture

### 1.1 What is being built

A pi extension npm package that re-implements the `stock-analysis` orchestration (from `~/jenningsloy318/stock-analysis-plugin`) as a **self-contained TypeScript control-flow workflow**, structurally and stylistically mirroring `~/jenningsloy318/pi-super-dev` (which was itself derived from `~/jenningsloy318/super-dev-plugin`).

The extension exposes:
- **ONE pi tool** `stock_analysis` (Typebox `Type.Object` parameters including a `mode` discriminator).
- **ONE pi command** `/stock-analysis` (natural-language arg parser → dispatches to the tool via `pi.sendUserMessage`).
- A **composable node algebra** (`task / sequence / branch / choose / parallel / loop / retry / gate / map / wait / tryCatch / noop`) that composes the 5-mode / 19-stage pipeline.
- **Copied domain assets verbatim:** 22 specialist agents, 76 Python scripts (+ `pyproject.toml` + `uv.lock` + `requirements.txt`), `references/`, `templates/`, `schemas/*.json`, `assets/`.

### 1.2 Architectural precedent (why this shape)

This is the **third** instance of the same port pattern:

```
super-dev-plugin (Claude Code)  ──port──▶  pi-super-dev (pi extension, TS node algebra)
stock-analysis-plugin (Claude)  ──port──▶  pi-stock-analysis  (THIS package)
```

Both ports share the identical boundary: **re-implement ORCHESTRATION in TypeScript; keep deterministic analysis code + domain-knowledge artifacts verbatim.** The node algebra, runner, supporting modules, and extension entry-point skeleton port near-verbatim from `pi-super-dev` (~90% reuse per REC-001). The novel work is concentrated in: (a) adapting `types.ts` domain shapes, (b) composing the 5-mode/19-stage tree in `stages/index.ts`, (c) adding `src/scripts.ts` to bridge to the verbatim Python via `uv run`, and (d) porting 22 agent `.md` files with a preamble-only edit.

### 1.3 High-level component diagram

```
                    ┌─────────────────────────────────────────────┐
   pi TUI/CLI ─────▶│  src/extension.ts                            │
   /stock-analysis   │  ┌───────────────┐  ┌────────────────────┐ │
                     │  │ stock_analysis │  │ /stock-analysis     │ │
                     │  │ tool           │  │ command (arg parse)│ │
                     │  │ (Type.Object)  │  │ + trigger fallback  │ │
                     │  └──────┬────────┘  └─────────┬──────────┘ │
                     │         │ execute()           │ sendUserMessage
                     │         ▼                     │            │
                     │  ┌────────────────────────────▼──────────┐ │
                     │  │ src/workflow.ts  runWorkflow(root,state)│
                     │  └────────────────────┬──────────────────┘ │
                     └───────────────────────┼───────────────────┘
                                              ▼
        ┌──────────────────────────────────────────────────────────┐
        │ src/stages/index.ts  (declarative pipeline tree)          │
        │  choose(state.mode)                                       │
        │   ├ pipeline: 0→1→1.5→2→3→4→4.5→[map 5-15]→16→16.5→…→19   │
        │   ├ screen:    0→1→1.5→2→3→4→4.5→17→17.5→18→18.5→19       │
        │   ├ analyze:   0→1→1.5→[map 5-15]→16→16.5→…→19            │
        │   ├ compare:   0→1→1.5→[map 5-15]→16→16.5→…→19            │
        │   └ walk:      0→1→1.5→walk→[map 5-15]→16→16.5→…→19       │
        └────────────────────────┬─────────────────────────────────┘
                                 ▼ node algebra (src/nodes.ts)
        ┌──────────────────────────────────────────────────────────┐
        │ task | sequence | branch | choose | parallel | loop |      │
        │ retry | gate | map | wait | tryCatch | noop               │
        │ + writerTask | helperTask | gateValidator                 │
        └──────┬───────────────────────────────────┬───────────────┘
               ▼ ctx.agent()                        ▼ ctx.helper()/runScript
   ┌───────────────────────┐              ┌─────────────────────────┐
   │ src/agents.ts         │              │ src/scripts.ts          │
   │  load agents/<n>.md   │              │  runScript(name,args)   │
   │ src/pi-spawn.ts       │              │  → uv run python        │
   │  pi -a <agent>        │              │    ${ROOT}/scripts/<n>  │
   │ src/session-agent.ts  │              │                         │
   │  in-process backend   │              │ scripts/*.py (76)       │
   └───────────────────────┘              │ + pyproject.toml/uv.lock│
                                          └─────────────────────────┘
```

### 1.4 Why no external workflow engine

The node algebra is **fully self-contained** in `src/nodes.ts` (PAT-004, NFR-4.1). `structure.test.ts` enforces the absence of `@agwab/pi-workflow` and any bundled runtime npm `dependencies` (peer-only — DEP-001). Adding a control-flow construct = one builder in `nodes.ts`, zero runner changes.

---

## 2. Resolved Decisions (binding)

All design questions are resolved. Implementers MUST apply these without re-litigating.

### 2.1 OPT-A1 — Mode dispatch: single tool + `choose` node (→ AC-04, AC-05, AC-10; SCENARIO-005…010, 018)
ONE tool `stock_analysis` carries a `mode` discriminator; the workflow ROOT is `choose(state.mode)` selecting the per-mode stage sequence. Rejected: five separate tools (namespace clutter, duplicated setup/teardown), single giant `task` (loses declarative visibility + per-stage tolerance).

### 2.2 OPT-B1 — Python scripts: KEEP verbatim; thin `runScript` shell-out (→ AC-13, AC-16; SCENARIO-027, 030…032)
76 scripts copied byte-identical. `src/scripts.ts` `runScript()` bridges via `uv run python ${EXTENSION_ROOT}/scripts/<name>.py`. Evidence: akshare + baostock (China A-share) have **no Node.js equivalent** (SRC-004). Same boundary pi-super-dev drew. Rejected: TS rewrite (infeasible), partial rewrite (duplicates the TS/Python boundary).

### 2.3 OPT-C1 — Backend: subprocess default; `STOCK_ANALYSIS_BACKEND=session` override (→ AC-17; SCENARIO-033)
Mirrors `SUPER_DEV_BACKEND` exactly (PAT-009, SRC-002). Subprocess isolation protects the orchestrator from a crashing/freezing agent across a 30-min+ multi-company run.

### 2.4 OPT-D1 — Agent adaptation: copy all 22 `.md`; edit invocation preamble ONLY (→ AC-12; SCENARIO-025, 026)
All analytical content, frameworks, personas, and output schemas preserved unchanged. Only the Claude-Code invocation notes are replaced with pi invocation notes.

### 2.5 Open-question resolutions (OQ-1…OQ-7, from `03-research-report.md §5`)

| # | Resolution |
|---|---|
| OQ-1 | Package name **`@jenningsloy318/pi-stock-analysis`**; repo dir stays `pi-finance`. |
| OQ-2 | **Copy all 22** specialist agents (see §2.6 for the count reconciliation). |
| OQ-3 | `market-daily-orchestrator` + `search-agent` copied but **NOT wired** into the 19-stage pipeline; tracked as a possible future `--mode daily`. |
| OQ-4 | Backend default **`subprocess`** (OPT-C1). |
| OQ-5 | **Rely on host `uv`** + the copied `uv.lock` for reproducibility; do NOT vendor the `uv` binary. |
| OQ-6 | README uses **ASCII** diagrams (terminal viewers, matches pi-super-dev); Mermaid under `docs/` for rendered views. |
| OQ-7 | `/stock-analysis` **accepts raw JSON** as the `query` (power-user escape hatch); if it parses and matches the tool params, dispatch directly. |

### 2.6 Agent-count reconciliation (resolves the AC-12 / REC-004 conflict)

`requirements §2.2 + OQ-2` enumerate **22** agents in the source `agents/` directory and resolve "copy all 22." `code-assessment REC-004` notes `pi-super-dev/tests/structure.test.ts:74` hard-asserts `agents.length === 21` and suggests dropping `team-lead-workflow.md`. **Resolution (binding):** ship all **22** (authoritative requirements win over a template's incidental test constant). The `team-lead-workflow.md` file is retained as a reference for ad-hoc team-lead invocation; it is superseded as the *orchestration* driver by the TS pipeline in `stages/index.ts`. `tests/structure.test.ts` asserts `>= 22` agents. This satisfies AC-12 ("all specialist agents copied") and OQ-2 verbatim.

---

## 3. Package Layout & Manifest

### 3.1 File tree (target)

```
pi-finance/                                    ← repo root (dir name unchanged)
├── package.json                               ← §3.2
├── tsconfig.json                              ← §3.3
├── vitest.config.ts                           ← §3.3
├── .gitignore                                 ← excludes node_modules/, reports/, .stock-analysis-logs/
├── LICENSE                                    ← MIT
├── CHANGELOG.md
├── README.md                                  ← §11
├── docs/
│   ├── specifications/01-pi-stock-analysis-workflow/  ← (existing) 01–05 + this 06,07,08
│   └── architecture.mmd                       ← OQ-6 mermaid (optional, low-stakes)
├── src/
│   ├── extension.ts                           ← §4 (tool + command + progress + summary)
│   ├── nodes.ts                               ← §5 (control-flow algebra)
│   ├── workflow.ts                            ← §6 (self-evaluating runner)
│   ├── types.ts                               ← §7 (domain shapes)
│   ├── stages/
│   │   └── index.ts                           ← §8 (5-mode / 19-stage tree)
│   ├── scripts.ts                             ← §9 (runScript → uv)
│   ├── agents.ts                              ← §10.1
│   ├── pi-spawn.ts                            ← §10.2
│   ├── session-agent.ts                       ← §10.3
│   ├── control.ts                             ← §10.4 (<control> JSON extractor)
│   ├── helpers.ts                             ← §10.5 (deterministic helpers + ticker normalize)
│   └── prompts.ts                             ← §10.6 (EXTENSION_ROOT injection)
├── agents/                                    ← §10.7 (22 .md, preamble-edited)
│   ├── team-lead.md, data-collector.md, sector-screener.md, company-screener.md,
│   ├── fundamental-analyst.md, industry-analyst.md, supply-chain-analyst.md,
│   ├── macro-analyst.md, quant-analyst.md, risk-analyst.md, alt-data-analyst.md,
│   ├── catalyst-analyst.md, china-market-analyst.md, roadmap-walker.md,
│   ├── scorer.md, equity-report-writer.md, screening-report-writer.md,
│   ├── report-validator.md, company-orchestrator.md, market-daily-orchestrator.md,
│   ├── search-agent.md, team-lead-workflow.md
├── skills/stock-analysis/SKILL.md             ← §10.8 (SHORT pointer)
├── scripts/                                   ← §10.9 (76 .py verbatim)
│   ├── *.py (76)
│   └── requirements.txt
├── pyproject.toml                             ← verbatim
├── uv.lock                                    ← verbatim
├── references/                                ← verbatim (gics_taxonomy, data_source_matrix, …)
├── templates/                                 ← verbatim (equity-report.md, …)
├── schemas/                                   ← verbatim (16 *.json)
├── assets/                                    ← verbatim (report_styles.css)
└── tests/                                     ← §13
    ├── structure.test.ts
    ├── nodes.test.ts
    ├── workflow.test.ts
    ├── arg-parser.test.ts
    ├── scripts.test.ts
    ├── ticker-normalize.test.ts
    ├── control.test.ts
    └── mode-dispatch.test.ts
```

### 3.2 `package.json` (→ AC-01, AC-02, AC-03; SCENARIO-001…004)

```jsonc
{
  "name": "@jenningsloy318/pi-stock-analysis",
  "version": "0.1.0",
  "description": "pi control-flow workflow extension for unified equity research (5 modes, 19 stages)",
  "type": "module",
  "license": "MIT",
  "keywords": ["pi", "pi-extension", "pi-package", "stock-analysis", "equity-research"],
  "engines": { "node": ">=22.19.0" },
  "exports": {
    "./extension": "./src/extension.ts",
    "./nodes":      "./src/nodes.ts",
    "./workflow":   "./src/workflow.ts",
    "./stages":     "./src/stages/index.ts",
    "./package.json": "./package.json"
  },
  "files": [
    "src", "agents", "skills", "scripts", "references", "templates", "schemas", "assets",
    "pyproject.toml", "uv.lock", "README.md", "LICENSE", "CHANGELOG.md"
  ],
  "scripts": {
    "build":     "tsc",
    "typecheck": "tsc --noEmit",
    "test":      "vitest run"
  },
  "pi": {
    "extensions": ["./src/extension.ts"],
    "skills":     ["./skills/stock-analysis"]
  },
  "peerDependencies": {
    "@earendil-works/pi-coding-agent": "*",
    "typebox": "*"
  },
  "devDependencies": {
    "@types/node": "*",
    "typebox": "*",
    "typescript": "*",
    "vitest": "*"
  }
}
```

**Constraints enforced by `structure.test.ts`:**
- `"type"` === `"module"`; `engines.node` >= 22.19; `keywords` includes `"pi-package"`.
- `dependencies` is **undefined** (peer-only — DEP-001, PAT-010).
- No `@agwab/pi-workflow` anywhere in the resolved tree (NFR-4.1).
- `pi.extensions[0]` === `"./src/extension.ts"`; `pi.skills[0]` === `"./skills/stock-analysis"`.
- `exports` exposes the five keys above.
- `files` includes all eight asset directories + `pyproject.toml` + `uv.lock` (ISS-06).

### 3.3 Config files (→ AC-03; SCENARIO-003)

- **`tsconfig.json`** — mirrors pi-super-dev: `target`/`module`/`moduleResolution` compatible with pi's TS loader; `strict: true`; `.ts`-suffix imports honored; `node_modules` + `reports` excluded.
- **`vitest.config.ts`** — `environment: "node"`; `include: ["tests/**/*.test.ts"]`; no network setup.
- **`.gitignore`** — `node_modules/`, `reports/`, `.stock-analysis-logs/`, `*.tsbuildinfo`, `.vitest-cache/`.
- **`LICENSE`** — MIT (match pi-super-dev).
- **`CHANGELOG.md`** — Keep-a-Changelog format; initial `## [0.1.0] - Unreleased`.

---

## 4. Extension Entry Point — `src/extension.ts` (→ AC-04, AC-05, AC-06; SCENARIO-005…013, 033)

Mirrors `pi-super-dev/src/extension.ts` (PAT-001, PAT-002, PAT-003). Exports `default activate(pi: ExtensionAPI)`.

### 4.1 `EXTENSION_ROOT` resolution (ISS-01)

Resolved **once** at module load and threaded through every prompt (NFR-3.3, BP-03):

```ts
// Resolve from the directory containing this package's package.json.
// Must work for BOTH: `pi -e .` (runs from source, .ts path) AND `pi package add` (installed).
export const EXTENSION_ROOT = resolvePackageRoot(import.meta.url); // → <dir of package.json>
```

`resolvePackageRoot` walks up from `import.meta.url` until it finds a `package.json` whose `name` === `"@jenningsloy318/pi-stock-analysis"`, then returns its directory. Validated by `tests/structure.test.ts` against both a source-tree path and a synthetic installed path.

### 4.2 Tool: `stock_analysis` (PAT-002, DEP-004)

Registered via `pi.registerTool`. Parameters via typebox `Type.Object`:

| Parameter | Typebox | Default | Validation |
|---|---|---|---|
| `mode` | `Type.Union([Type.Literal("pipeline"), Type.Literal("screen"), Type.Literal("analyze"), Type.Literal("compare"), Type.Literal("walk")])` | `"pipeline"` | enum enforced (SCENARIO-006) |
| `tickers` | `Type.Optional(Type.Array(Type.String()))` | `[]` | `analyze` → length ≥ 1; `compare` → length 2–5 (SCENARIO-007, ISS-04) |
| `theme` | `Type.Optional(Type.String())` | `undefined` | `walk` → non-empty |
| `topIndustry` | `Type.Optional(Type.Number({ minimum: 1 }))` | mode-aware: 8 pipeline / 40 screen / 7 walk | applied in setup |
| `totalCompany` | `Type.Optional(Type.Number({ minimum: 1, maximum: 50 }))` | `15` (pipeline only, cap 50) | pipeline only |
| `topPrice` | `Type.Optional(Type.Number({ minimum: 0 }))` | `200` | `0` disables |
| `minHeadroom` | `Type.Optional(Type.Number({ minimum: 1, maximum: 10 }))` | `5` | range 1–10 |
| `days` | `Type.Optional(Type.Number({ minimum: 1, maximum: 20 }))` | `1` | range 1–20 |
| `universe` | `Type.Union([Type.Literal("US"), Type.Literal("CN"), Type.Literal("ALL")])` | `"US"` | enum |
| `query` | `Type.Optional(Type.String())` | `undefined` | natural-language passthrough; if valid JSON matching params, parsed directly (OQ-7) |
| `model` | `Type.Optional(Type.String())` | `undefined` | passthrough |
| `maxAgents` | `Type.Optional(Type.Number({ minimum: 1 }))` | `undefined` | passthrough |

**`execute(toolCallId, params, signal, onUpdate)`** (PAT-002):
1. **Fail-fast input validation** (ISS-04): check per-mode requirements before any stage runs; throw a descriptive `pi` error on violation.
2. Build `StockAnalysisState` from `params` (§7.1); set `state.backend = options.backend ?? process.env.STOCK_ANALYSIS_BACKEND ?? "subprocess"` (PAT-009).
3. Construct `ProgressSink` — rolling tail (`TAIL_LINES = 400`), 80ms-throttled `text(partial)` typing stream, and full transcript buffered for the run log.
4. Resolve the pipeline root from `stages/index.ts`; call `await runWorkflow(root, state, { sink, signal, extensionRoot: EXTENSION_ROOT, model, maxAgents })`.
5. On completion: derive `RunStatus` via `formatSummary(state)` (§4.4, PAT-003); write transcript to `.stock-analysis-logs/<RUN_ID>.log`; emit final summary with completed/skipped/failed stage names.
6. Honor `signal.aborted` between stages (no-pause rule means we never *block* for input, but we DO respect an external abort).

### 4.3 Command: `/stock-analysis` (DD-2; SCENARIO-008…010)

Registered via `pi.registerCommand("/stock-analysis", { handler })`. The handler does NOT run the pipeline — it parses args then dispatches via `pi.sendUserMessage(...)` (PAT-001). Arg parser (`parseStockAnalysisArgs(argString)`, pure function, unit-tested in `tests/arg-parser.test.ts`):

1. **Structured-JSON escape hatch (OQ-7):** if the trimmed arg string parses as JSON and has a `mode` key, validate against the param contract and return the object directly.
2. **`--mode <name>` is authoritative** (SCENARIO-008). Supported spellings: `--mode`, `-m`.
3. **Positional extraction by mode:**
   - `analyze`: positional whitespace-separated tickers after the flag.
   - `compare`: comma-separated tickers (2–5) after the flag.
   - `walk`: quoted multi-word theme after the flag (`--mode walk "humanoid robotics"`).
4. **Remaining `--flags`** (kebab-case → camelCase): `--top-industry`, `--total-company`, `--top-price`, `--min-headroom`, `--days`, `--universe`, `--model`, `--max-agents`.
5. **Trigger-phrase fallback** (no `--mode`; SCENARIO-009) — per SKILL.md `<triggers>`:
   - `/\b(find|discover)\b.*\bbest\b/i` → `pipeline`
   - `/\b(screen|screener|sector scan)\b/i` → `screen`
   - `/\b(deep[ -]?dive|analyze|analyse)\b/i` (+ extracted `TICKER`) → `analyze`
   - `/\bvs\.?\b|\bversus\b|\bcompare\b/i` → `compare`
   - `/\b(walk|trace|map out)\b.*\b(chain|roadmap|ecosystem)\b/i` → `walk`
6. **Default:** `pipeline`.
7. Dispatch: `pi.sendUserMessage(\`Use the stock_analysis tool with ${JSON.stringify(parsedParams)}\`)`.

### 4.4 `formatSummary(state)` — honest status (PAT-003, SCENARIO-012, 013)

`RunStatus = "success" | "partial" | "failed"` derived **only** from produced artifacts + gate flags — never defaulted to `"success"`:

```ts
function formatSummary(state: StockAnalysisState): { status: RunStatus; completed: string[]; skipped: string[]; failed: StageFailure[]; reports: string[] } {
  const reports = listReports(state);              // files under ./reports/<RUN_ID>/
  const failed  = state.tracking.failures;         // logged stage failures
  const gates   = state.tracking.gateResults;      // pass/fail per gate
  const status: RunStatus =
    failed.length === 0 && gates.every(g => g.passed) && reports.length > 0 ? "success"
    : reports.length > 0                              ? "partial"
    :                                                   "failed";
  return { status, completed: state.tracking.completed, skipped: state.tracking.skipped, failed, reports };
}
```

---

## 5. Control-Flow Node Algebra — `src/nodes.ts` (→ AC-07, AC-08; SCENARIO-014…017)

Ported near-verbatim from `pi-super-dev/src/nodes.ts` (PAT-004, REC-001). **Self-contained; no `@agwab/pi-workflow`.**

### 5.1 Core types (§7 gives domain shapes; here the algebra types)

```ts
type NodeResult<T = unknown> =
  | { status: "ok";      value: T }
  | { status: "failed";  error: string; partial?: unknown }
  | { status: "skipped"; reason?: string };

interface Node<S = StockAnalysisState> {
  kind: string;
  run(state: S, ctx: StageContext): Promise<NodeResult>;
}

type Predicate<S> = (state: S, ctx: StageContext) => boolean | Promise<boolean>;
```

### 5.2 Node builders (minimum surface; SCENARIO-014, AC-07)

| Builder | Signature (abbreviated) | Semantics | Pipeline use |
|---|---|---|---|
| `task(stage)` | `task(stage: Stage): Node` | Leaf; stores return under `state[stage.id]`; if `stage.fatal`, re-throws (PAT-007) | every numbered stage |
| `sequence(children, opts?)` | `sequence(nodes: Node[], { tolerant?: boolean }): Node` | Runs in order; `tolerant:true` converts throws → `failed` and continues (PAT-007) | the per-mode stage chains + the tolerant root |
| `branch(predicate, { yes, no? })` | `branch(pred, branches): Node` | Runs `yes` iff predicate true else `no` (or skip) | A-share Stage 15; screening-only 2–4; walk replacement |
| `choose(cases, otherwise?)` | `choose(cases: { when, run }[]): Node` | First matching `when` wins; `otherwise` default | **ROOT mode dispatch** (§8.1) |
| `parallel(branches, { concurrency? })` | `parallel(nodes, opts): Node` | Runs branches concurrently; caps concurrency | wave-internal parallelism; adversarial verify; judge panel |
| `loop({ while, do }, body)` | `loop(opts, body): Node` | Repeats body until `while` false | (reserved; used for adaptive re-runs) |
| `retry({ attempts, until?, backoffMs? }, node)` | `retry(opts, node): Node` | Repeats on `failed`; optional `until(result)` success predicate | **retry-on-null 10×** around every analyst task (PAT-006) |
| `gate({ validate, attempts, feedbackKey }, node)` | `gate(opts, node): Node` | Re-runs `node` up to `attempts` until `validate` passes; on exhaustion stores errors under `state.__feedback[feedbackKey]` and returns `{status:"failed"}` (PAT-005) — **never throws** | the 5 validation stages (1.5/4.5/16.5/17.5/18.5) |
| `map({ over, as, concurrency, failFast? }, body)` | `map(opts, body): Node` | Applies body to each item of `state[over]`; caps `concurrency` (ISS-03) | **per-company DAG** (concurrency 4); adversarial verify per pick; completeness critic per report |
| `wait({ ms })` / `waitForEvent(name)` | `wait(opts): Node` | Suspends (no busy-spin) | reserved |
| `tryCatch(body, { onCaught? })` | `tryCatch(body, opts): Node` | Isolates failures; `onCaught` callback | explicit boundary around fragile stages |
| `noop()` | `noop(): Node` | No-op | placeholders |
| `writerTask(stage)` | `writerTask(stage): Node` | `task` variant whose value is written to a file path under `state.runId` | report writers |
| `helperTask(call)` | `helperTask(call): Node` | Calls `ctx.helper(call)` (deterministic) | scoring helpers |
| `gateValidator(helperName, sourceKey, stateKey)` | `gateValidator(...)` | Builds a `validate` fn backed by a deterministic helper (BP-02) | Stage 17.5 `validate_report.py` |

### 5.3 Concurrency-independence invariant (ISS-03)

`map`'s `concurrency` caps **collection-level** parallelism (e.g. 4 companies at once); inner `parallel` caps **stage-level** parallelism within one item (e.g. wave1's 4 analysts). These are two independent dials and MUST NOT be conflated. Documented in `src/stages/index.ts` header comment.

---

## 6. Workflow Runner — `src/workflow.ts` (→ AC-08; SCENARIO-016)

Ported near-verbatim (REC-001). Two exports:

```ts
function makeContext(opts: {
  sink: ProgressSink; signal: AbortSignal; extensionRoot: string;
  backend: "subprocess" | "session"; model?: string; maxAgents?: number;
}): StageContext;

async function runWorkflow(root: Node, state: StockAnalysisState, opts: RunOpts): Promise<{ state; summary }>;
```

`runWorkflow` builds the context, invokes `await root.run(state, ctx)`, captures per-node timing into `state.tracking`, and derives the summary. The runner is **host-agnostic and stage-agnostic** — it never changes when stages change (BP-01). All pipeline revisions live in `stages/index.ts`.

### 6.1 `StageContext` (PAT-008)

```ts
interface StageContext {
  agent(req: { id: string; agent: string; prompt: string; controlKeys?: string[] }): Promise<AgentResult>;
  helper(call: HelperCall): Promise<HelperResult>;   // dispatches to helpers.ts runHelper
  script(call: ScriptCall): Promise<ScriptResult>;    // dispatches to scripts.ts runScript (BP-03)
  parallel<T>(items: T[], fn: (item: T) => Promise<T>, concurrency: number): Promise<T[]>;
  budget: { check(): void; spent(): number };          // maxAgents cap
  log(line: string): void;                             // → ProgressSink.log
  events: EventEmitter;                                // backs waitForEvent
  signal: AbortSignal;
  extensionRoot: string;
}
```

### 6.2 Backend switch (PAT-009, OPT-C1)

`ctx.agent()` dispatches to `pi-spawn.ts spawnAgent()` when `backend === "subprocess"` (default), or `session-agent.ts createAgentSession()` when `backend === "session"`. Selected via `STOCK_ANALYSIS_BACKEND` env (mirrors `SUPER_DEV_BACKEND`).

### 6.3 Gate feedback injection (PAT-005)

When a `gate` exhausts attempts, its validator errors are stored under `state.__feedback[feedbackKey]`. The runner's `agent()` prepends those errors to the next attempt's prompt so the agent fixes the specific failure instead of resampling.

---

## 7. Domain Types — `src/types.ts` (→ AC-09; SCENARIO-017)

Adapted from pi-super-dev (REC-001). Super-dev's `SetupControl`/`Classification` shapes are **removed**; stock-analysis shapes replace them.

### 7.1 `StockAnalysisState`

```ts
interface StockAnalysisState {
  // ── inputs (from tool params) ──
  mode: "pipeline" | "screen" | "analyze" | "compare" | "walk";
  tickers: string[];            // normalized (A-share suffixes resolved)
  theme?: string;               // walk mode
  topIndustry: number;          // 8 pipeline / 40 screen / 7 walk
  totalCompany: number;         // default 15, cap 50, pipeline only
  topPrice: number;             // 0 disables
  minHeadroom: number;          // 1..10
  days: number;                 // 1..20
  universe: "US" | "CN" | "ALL";

  // ── run identity ──
  runId: string;                // YYYYMMDDHHmm LOCAL time (NFR-3.1)
  reportsDir: string;           // ./reports/<runId>/  (run cwd, NOT package dir — NFR-7.3)
  backend: "subprocess" | "session";
  model?: string;
  maxAgents?: number;

  // ── pipeline working sets ──
  sharedData?: SharedData;      // fetched ONCE at Stage 1, reused (AC-25, SCENARIO-048)
  industries?: Industry[];      // Stage 2 output
  subIndustries?: SubIndustry[];// Stage 3 output
  companies: Company[];         // Stage 4 output → input to map(5-15)
  scoring?: ScoringResult;      // Stage 16 output
  adversarial?: AdversarialResult[];   // Stage 16.6
  judgePanel?: JudgeVerdict[];         // Stage 16.7
  reports: ReportArtifact[];    // Stage 17/18 output
  bestPicks?: BestPick[];       // Stage 18 output

  // ── per-company scratch (used inside map body) ──
  company?: Company;            // current item when inside map({as:"company"})

  // ── bookkeeping ──
  tracking: Tracking;           // completed/skipped/failures/gateResults (NFR-2)
  __feedback: Record<string, ValidatorError[]>;  // gate feedback channel (PAT-005)
}
```

### 7.2 Supporting domain shapes

```ts
interface Company { ticker: string; name?: string; isAsh: boolean; exchange?: "SH"|"SZ"|"NASDAQ"|"NYSE"; /* …analyst outputs keyed by stage id…*/ }
interface SharedData { macro?: unknown; sectorMetrics?: unknown; /* …fetched-once datasets…*/ }
interface ScoringResult { companies: ScoredCompany[]; }
interface ReportArtifact { kind: "screening"|"company"|"comparison"|"walk"|"best-picks"; path: string; }
interface BestPick { ticker: string; positionType: "core"|"satellite"|"tactical"; }
interface Tracking {
  completed: string[]; skipped: string[]; failures: StageFailure[];
  gateResults: { stage: string; passed: boolean; errors?: ValidatorError[] }[];
  startedAt: string; finishedAt?: string;
}
interface StageFailure { stage: string; error: string; attempts?: number; }
interface RunSummary { status: RunStatus; completed: string[]; skipped: string[]; failed: StageFailure[]; reports: string[]; }
```

### 7.3 Stage / StageContext / Node / AgentResult (algebra glue)

```ts
interface Stage<S = StockAnalysisState> {
  id: string;                   // e.g. "stage-0-setup", "stage-15-ashare"
  fatal?: boolean;              // only Stage 0 sets this true (PAT-007)
  run(state: S, ctx: StageContext): Promise<unknown>;
}
interface AgentResult { control?: Record<string, unknown>; text: string; raw: string; }
interface HelperCall  { name: string; args?: unknown; }
interface HelperResult { ok: boolean; value?: unknown; error?: string; }
interface ScriptCall   { name: string; args?: string[]; cwd?: string; timeoutMs?: number; }
interface ScriptResult { ok: boolean; stdout?: string; stderr?: string; json?: unknown; exitCode?: number; error?: string; }
```

---

## 8. Pipeline Composition — `src/stages/index.ts` (→ AC-10, AC-11; SCENARIO-018…024)

The declarative tree. Authored per BP-01 (never mutate the runner). Composes the 5-mode / 19-stage pipeline from the node algebra. **Root** = `choose([...])` on `state.mode`, each case a `sequence([...], { tolerant: true })`, the whole wrapped so Stage 19 (cleanup) always runs last.

### 8.1 Mode dispatch (DD-1; SCENARIO-018)

```ts
export const root: Node = choose([
  { when: s => s.mode === "pipeline", run: pipelineSequence },
  { when: s => s.mode === "screen",   run: screenSequence   },
  { when: s => s.mode === "analyze",  run: analyzeSequence  },
  { when: s => s.mode === "compare",  run: compareSequence  },
  { when: s => s.mode === "walk",     run: walkSequence     },
], otherwise: cleanupOnly);  // defensive default
```

### 8.2 Per-mode stage sequences (DD-1 — exact)

| Stage | pipeline | screen | analyze | compare | walk |
|---|:---:|:---:|:---:|:---:|:---:|
| 0 Setup (fatal) | ✓ | ✓ | ✓ | ✓ | ✓ |
| 1 Data Collection | ✓ | ✓ | ✓ | ✓ | ✓ |
| 1.5 Data Validation gate | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2 Sub-Industry Screening | ✓ | ✓ | — | — | — |
| 3 Sub-Industry Deep-Dive | ✓ | ✓ | — | — | — |
| 4 Company Screening | ✓ | ✓ | — | — | — |
| 4.5 Screening Validation gate | ✓ | ✓ | — | — | — |
| walk (roadmap-walker) | — | — | — | — | ✓ (replaces 2–4) |
| 5–15 per-company waves | ✓ | — | ✓ | ✓ (max 5) | ✓ (top 3–5) |
| 16 Scoring | ✓ | — | ✓ | ✓ | ✓ |
| 16.5 Score Validation gate | ✓ | — | ✓ | ✓ | ✓ |
| 16.6 Adversarial Verify | ✓ | — | ✓ | ✓ | ✓ |
| 16.7 Judge Panel | ✓ | — | ✓ | ✓ | ✓ |
| 17 Reports | ✓ (screening) | ✓ (screening) | ✓ (company) | ✓ (comparison) | ✓ (walk) |
| 17.4 Completeness Critic | ✓ | ✓ | ✓ | ✓ | ✓ |
| 17.5 Report Validation gate | ✓ | ✓ | ✓ | ✓ | ✓ |
| 18 Best Picks | ✓ | — | ✓ | ✓ | ✓ |
| 18.5 Best Picks Validation gate | ✓ | — | ✓ | ✓ | ✓ |
| 19 Cleanup | ✓ | ✓ | ✓ | ✓ | ✓ |

Each per-mode sequence is a `sequence([...], { tolerant: true })` (PAT-007).

### 8.3 Conditional stages via `branch` (SCENARIO-019)

- **Screening-only (2,3,4,4.5):** `branch(s => s.mode === "pipeline" || s.mode === "screen", { yes: screeningBlock, no: noop() })`.
- **Walk replacement:** `branch(s => s.mode === "walk", { yes: task(roadmapWalkerStage), no: noop() })` in place of 2–4.
- **A-share Stage 15 (SCENARIO-044, 045):** inside the per-company `map` body, `branch(s => !!s.company?.isAsh, { yes: task(ashareAnalystStage), no: noop() })`.

### 8.4 Per-company DAG — `map` + nested `parallel` + `retry` (SCENARIO-021, 022; AC-25)

```ts
const perCompanyDag: Node = map(
  { over: "companies", as: "company", concurrency: 4 },   // ISS-03: caps COMPANY-level parallelism
  sequence([
    // ── wave 1 (parallel, no deps) ──
    parallel([ task(stage5Fundamental), task(stage7Industry), task(stage9Macro), task(stage13AltData) ], { concurrency: 4 }),
    // ── wave 2 (parallel; deps 6←5, 8←7, 10←5+7, 14←13) ──
    parallel([ task(stage6Quant), task(stage8SupplyChain), task(stage10Risk), task(stage14Catalyst) ], { concurrency: 4 }),
    // ── wave 3 (parallel; deps 11←10, 12←10) ──
    parallel([ task(stage11Sector), task(stage12ChinaMarket) ], { concurrency: 2 }),
    // ── wave 4 (A-share only) ──
    branch(s => !!s.company?.isAsh, { yes: task(stage15Ashare), no: noop() }),
  ])
);
// every analyst task above is wrapped: retry({ attempts: 10 }, task(stageNN))   ← PAT-006, AC-25
```

**Retry-on-null rule (AC-25, SCENARIO-047):** every analyst `task` is wrapped in `retry({ attempts: 10, until: r => r.status === "ok" && !isEmpty(r.value) })`. Exhausted retries mark the stage failed (logged) and continue.

### 8.5 The five gates (SCENARIO-020; AC-10)

| Stage | Gate | validator | feedbackKey |
|---|---|---|---|
| 1.5 | Data Validation | `reportValidator` agent | `"sharedData"` |
| 4.5 | Screening Validation | `reportValidator` agent | `"screening"` |
| 16.5 | Score Validation | `reportValidator` agent | `"scoring"` |
| 17.5 | Report Validation | `gateValidator("validate_report", …)` → `runScript("validate_report", …)` (8 sub-gates; BP-02) | `"reports"` |
| 18.5 | Best Picks Validation | `reportValidator` agent | `"bestPicks"` |

All gates use `attempts: 4`. **Non-vacuous pass discipline (ISS-02):** if the validator produces no output (e.g. `uv` missing), the gate is `failed` with the captured stderr — never a silent pass.

### 8.6 Adversarial Verify + Judge Panel (SCENARIO-022)

- **16.6 Adversarial Verify:** `map({ over: s => top5Picks(s.scoring), as: "pick", concurrency: 5 }, parallel([skeptic1, skeptic2, skeptic3], { concurrency: 3 }))` — survives if ≥ 2/3 do NOT refute.
- **16.7 Judge Panel:** `parallel([buffettLens, lynchLens, marksLens, druckenmillerLens], { concurrency: 4 })`.

### 8.7 Setup is fatal (SCENARIO-023, 024; PAT-007)

Stage 0 `task` has `fatal: true`; failure re-throws and aborts the run. **All other stages are tolerant** — failure is logged to `state.tracking.failures` and the run continues toward Stage 19 (NFR-2.1).

### 8.8 Behavioral rules wired into the tree (AC-22…AC-25)

| Rule | Where enforced |
|---|---|
| Chinese reports (AC-22) | every report-writer agent prompt (preamble in `agents/*.md`); `formatSummary` does not translate |
| Filters at Stage 4 only (AC-23) | `price`/`headroom`/`universe` pruning lives ONLY in `task(stage4CompanyScreening)`; earlier stages never prune |
| A-share mandatory (AC-24) | `branch(s.company.isAsh)` in §8.4 |
| Max-4 concurrency (AC-25) | `map({concurrency:4})` §8.4 |
| Retry-on-null 10× (AC-25) | `retry({attempts:10})` §8.4 |
| Shared-data-once (AC-25) | `state.sharedData` set at Stage 1, read-only thereafter |
| No-pause (AC-25) | pipeline never awaits user input; only `signal` abort |
| Context-eviction (AC-25) | each agent prompt includes ONLY its stage's required context (§10.6) |

---

## 9. Python Bridge — `src/scripts.ts` (→ AC-16; SCENARIO-030…032)

### 9.1 `runScript(name, args, opts)` contract (BP-03, DEP-003)

```ts
export interface RunScriptOptions { cwd?: string; root: string; timeoutMs?: number; sink?: ProgressSink; }
export interface RunScriptResult { ok: boolean; stdout?: string; stderr?: string; json?: unknown; exitCode?: number; error?: string; }

export async function runScript(name: string, args: string[] = [], opts: RunScriptOptions): Promise<RunScriptResult> {
  // 1. VALIDATE name (NFR-7.1, SCENARIO-032): reject anything containing path separators / ".."
  if (!/^[A-Za-z0-9_-]+$/.test(name)) return { ok: false, error: `invalid script name: ${name}` };
  const scriptPath = join(opts.root, "scripts", `${name}.py`);
  if (!existsSync(scriptPath)) return { ok: false, error: `script not found: ${name}` };
  // 2. spawn `uv run python <scriptPath> ...args`
  // 3. capture stdout + stderr; stream stderr line-by-line to opts.sink?.log (live diagnostics)
  // 4. enforce opts.timeoutMs ?? DEFAULT_TIMEOUT_MS (10 min, NFR-1.2); kill on timeout
  // 5. parse last JSON object from stdout via control.ts findLastJsonObject (BP-03)
  // 6. return structured result — NEVER throw (SCENARIO-031)
}
```

**Key properties:**
- **Path safety (NFR-7.1, SCENARIO-032):** `name` validated against `^[A-Za-z0-9_-]+$`; resolves strictly under `${root}/scripts/`.
- **Never throws (SCENARIO-031):** all errors → `{ ok: false, error, exitCode, stderr }` so tolerant stages continue.
- **Structured JSON parsing:** uses `src/control.ts findLastJsonObject(stdout)` (reuses the `<control>` extractor).
- **Timeout (NFR-1.2):** default 600_000 ms; hung script killed; result `{ ok:false, error:"timeout" }`.
- **`root` = `EXTENSION_ROOT`** (resolved in `extension.ts`, §4.1).

### 9.2 Deterministic helpers exposed (REC-003)

`helpers.ts runHelper(call)` dispatches by `call.name` to either a TS function or (new) a `script`-backed helper:
- `compute_scores`, `cross_check`, `calibrate_conviction`, `validate_report`, `score_bottleneck_asymmetry`, `compute_tam_adj_peg`, `compute_bayesian_growth` → all shell out via `runScript`.
- Exposed to stages via `helperTask(call)` (AC-16) and to gates via `gateValidator(name, …)` (Stage 17.5, §8.5).

---

## 10. Supporting Modules (ported from pi-super-dev, domain-adapted) (→ AC-17; SCENARIO-033)

### 10.1 `src/agents.ts`
Loads `agents/<name>.md` by name; parses YAML frontmatter (`name, description, model, kind, tools, max_turns, timeout_mins`) + body. Returns the agent definition for `ctx.agent()`. (PAT-011)

### 10.2 `src/pi-spawn.ts` — subprocess backend (OPT-C1, default)
`spawnAgent({ id, agent, prompt, controlKeys })` spawns `pi -a <agent>` as a subprocess with the prompt on stdin; captures stdout; uses `control.ts extractControlKeys` to pull structured output. Includes `abbreviatePath` for readable logs. (PAT-009)

### 10.3 `src/session-agent.ts` — in-process backend (OPT-C1, opt-in)
`createAgentSession(...)` runs the agent in-process (faster, no isolation). Selected when `STOCK_ANALYSIS_BACKEND=session`.

### 10.4 `src/control.ts`
Tolerant `<control>...</control>` JSON extractor: `extractControl(raw)`, `findLastJsonObject(text)`, `extractControlKeys(raw, keys[])`. Used by both `pi-spawn` (agent output) and `runScript` (script stdout). (BP-03)

### 10.5 `src/helpers.ts`
Deterministic helper dispatcher `runHelper(call)`; plus pure helpers including **A-share ticker normalization** (AC-25 prerequisite, used by Stage 0):
- `normalizeAshTicker(input)`:
  - `600519` → `600519.SH` (6-digit starting 60/68 → `.SH`; 00/30 → `.SZ`)
  - `贵州茅台` → akshare lookup → `600519.SH` (via `runScript` name lookup; best-effort, non-fatal on miss)
  - `600519.SH` / `AAPL` → pass-through (suffixed or non-numeric)
- `isAshTicker(ticker)` → `ticker.endsWith(".SH") || ticker.endsWith(".SZ")` (drives §8.4 A-share branch).

### 10.6 `src/prompts.ts`
Prompt builders that inject `EXTENSION_ROOT`, the run state slice, and (when present) `state.__feedback[feedbackKey]` into every agent prompt. **Context-eviction discipline (AC-25, SCENARIO-050):** each builder includes ONLY the keys its stage requires (e.g. the Stage-7 industry-analyst prompt never receives Stage-9 macro outputs).

### 10.7 Agent adaptation (`agents/*.md`, 22 files)
Copy verbatim from source; edit **only** the invocation preamble. Replacement text (mechanical):

```
- OLD: "uses the Agent tool with subagent_type=stock-analysis:<name>"
- NEW: "spawned as `pi -a <name>` subprocess (or in-process session backend); 
        deterministic calculations via `uv run python ${EXTENSION_ROOT}/scripts/<script>.py` 
        (use the runScript helper). Reference data at ${EXTENSION_ROOT}/references, 
        templates at ${EXTENSION_ROOT}/templates, schemas at ${EXTENSION_ROOT}/schemas."
```
All `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}` replaced with `${EXTENSION_ROOT}` (ISS-05; verified by `grep -r CLAUDE_PLUGIN agents/` returning nothing). Analytical content, frameworks, output schemas, personas **unchanged** (NG-5).

### 10.8 `skills/stock-analysis/SKILL.md` — SHORT pointer (→ AC-18; SCENARIO-034)
Comparable in length/style to `pi-super-dev/skills/super-dev/SKILL.md`. Contents: one-paragraph description, the `/stock-analysis` command, the 5 modes (one line each), the keep-Python contract (one line), and a pointer to `README.md` for full architecture. **NOT** the giant Claude skill — the orchestration now lives in TS.

### 10.9 Verbatim asset copies (→ AC-13, AC-14; SCENARIO-027, 028)
- `scripts/*.py` (76) + `scripts/requirements.txt` + `pyproject.toml` + `uv.lock` — **byte-identical**.
- `references/`, `templates/`, `schemas/*.json` (16), `assets/report_styles.css` — **byte-identical**.

### 10.10 Excluded artifacts (→ AC-15; SCENARIO-029)
Verified ABSENT in `structure.test.ts`: `workflows/`, `.claude/`, `.codex/`, `.claude-plugin/`, `.codex-plugin/`, `plugin.json`, `reports/`, `reports-deepseek/`, root `stage*.md`, root `*.py` (`parse_phase2.py` etc.), `run_triage.sh`, `test.py`, `rules/`, source `AGENTS.md`, source `CLAUDE.md`, source `new-analysis.md`, source `docs/`.

---

## 11. Documentation — `README.md` (→ AC-21; SCENARIO-040, 041)

Required sections:
1. **Title + one-paragraph** description (pi extension for unified equity research).
2. **Install** — `pi package add @jenningsloy318/pi-stock-analysis` (future publish) AND `pi -e .` (local dev).
3. **Prerequisites** — Node ≥ 22.19; **`uv` on PATH** (OQ-5); Python ≥ 3.11 (documented; not vendored).
4. **Usage** — one `/stock-analysis` example **per mode** (5 examples):
   - `/stock-analysis --mode pipeline --universe US`
   - `/stock-analysis --mode screen --top-industry 40`
   - `/stock-analysis --mode analyze AAPL MSFT`
   - `/stock-analysis --mode compare NVDA,AMD,INTC`
   - `/stock-analysis --mode walk "humanoid robotics"`
5. **Node-algebra reference table** — the §5.2 table (ASCII).
6. **Per-mode pipeline diagram** — ASCII per mode (OQ-6); Mermaid in `docs/architecture.mmd`.
7. **The Python decision (prominent)** — explicit rationale: 76 scripts; akshare/baostock have **no Node.js equivalent**; rewriting = hundreds of hours for real capability loss; same boundary pi-super-dev drew. (SCENARIO-041)
8. **How agents invoke scripts** — `runScript` → `uv run python ${EXTENSION_ROOT}/scripts/<name>.py`; `EXTENSION_ROOT` resolution.
9. **Architecture pointer** — short; full design in this spec (`06-specification.md`).

---

## 12. Traceability Matrix

### 12.1 AC → Spec section

| AC | Section | SCENARIO(s) |
|---|---|---|
| AC-01 (valid pi extension) | §3.2 | 001, 004 |
| AC-02 (files + exports) | §3.2 | 002 |
| AC-03 (config files) | §3.3 | 003 |
| AC-04 (tool params + validation) | §4.2 | 005, 006, 007 |
| AC-05 (command arg parser) | §4.3 | 008, 009, 010 |
| AC-06 (progress + log + summary) | §4.2, §4.4 | 011, 012, 013 |
| AC-07 (node algebra, no engine) | §5 | 014, 015 |
| AC-08 (runner) | §6 | 016 |
| AC-09 (domain shapes) | §7 | 017 |
| AC-10 (5-mode/19-stage composition) | §8 | 018, 019, 020, 021, 022 |
| AC-11 (setup fatal, others tolerant) | §8.7 | 023, 024 |
| AC-12 (agents copied + adapted) | §10.7, §2.6 | 025, 026 |
| AC-13 (scripts verbatim) | §10.9 | 027 |
| AC-14 (refs/templates/schemas/assets) | §10.9 | 028 |
| AC-15 (excluded absent) | §10.10 | 029 |
| AC-16 (runScript) | §9 | 030, 031, 032 |
| AC-17 (supporting modules) | §10 | 033 |
| AC-18 (short skill pointer) | §10.8 | 034 |
| AC-19 (hermetic tests) | §13 | 035, 036, 037, 038 |
| AC-20 (typecheck + test pass) | §13 | 039 |
| AC-21 (README) | §11 | 040, 041 |
| AC-22 (Chinese reports) | §8.8 | 042 |
| AC-23 (filters Stage 4 only) | §8.8 | 043 |
| AC-24 (A-share mandatory) | §8.3, §8.4 | 044, 045 |
| AC-25 (concurrency/retry/shared/no-pause/ctx) | §8.4, §8.8, §10.6 | 021, 046, 047, 048, 049, 050 |

**Every AC-01…AC-25 is mapped. Every SCENARIO-001…050 is addressable.**

### 12.2 NFR → enforcement

| NFR | Where enforced |
|---|---|
| NFR-1 (perf) | §9.1 timeout; §8.4 concurrency; §6.1 async pool |
| NFR-2 (tolerance) | §5.2 `gate`/`retry`/`tryCatch`; §8.7 |
| NFR-3 (determinism) | §4.1 EXTENSION_ROOT; §10.5 RUN_ID LOCAL; §9 Python truth |
| NFR-4 (portability) | §3.2 no engine dep; §6.2 backend env; §3.2 engines |
| NFR-5 (testability) | §13 hermetic |
| NFR-6 (maintainability) | §1.2 mirror pi-super-dev; §10.9 source-tree dirs |
| NFR-7 (safety) | §9.1 path validation; §7.1 reportsDir = run cwd |

---

## 13. Test Strategy — `tests/*.test.ts` (→ AC-19, AC-20; SCENARIO-035…039)

**Hermetic invariant (NFR-5, SCENARIO-035):** no `pi` subprocess spawns, no network, no `uv`/`python` execution (mocked). Suite completes in seconds.

| Test file | Covers | Approach |
|---|---|---|
| `structure.test.ts` | AC-01,02,03,15; SCENARIO-001…004, 029 | reads `package.json`, asserts `pi.*`, `exports`, `files`, no `dependencies`, no `@agwab/pi-workflow`, `>=22 agents`, `76 scripts`, 16 schemas, excluded-artifacts absent |
| `nodes.test.ts` | AC-07; SCENARIO-014, 036 | task/sequence/branch/choose/parallel/map/retry/gate/tryCatch semantics with fake `StageContext` (no spawns) |
| `workflow.test.ts` | AC-08; SCENARIO-016 | a small composed tree evaluates to completion, threads state, returns summary |
| `arg-parser.test.ts` | AC-05; SCENARIO-008, 009, 010 | all flag forms, JSON escape hatch, trigger-phrase fallback, default |
| `scripts.test.ts` | AC-16; SCENARIO-030, 031, 032 | `runScript` with `child_process.spawn` **mocked**: asserts command shape (`uv run python …/<name>.py …`), timeout kill path, structured-error path, path-traversal rejection |
| `ticker-normalize.test.ts` | AC-09, AC-24; SCENARIO-044, 045 | `normalizeAshTicker` (6-digit→suffix, name lookup, pass-through), `isAshTicker` |
| `control.test.ts` | §10.4 | `<control>` extraction, `findLastJsonObject`, malformed-input tolerance |
| `mode-dispatch.test.ts` | AC-10; SCENARIO-018, 019 | `choose` selects correct stage sequence per mode; conditional stages skip correctly |

**Pass gates (AC-20, SCENARIO-039):** `npm run typecheck` exits 0; `npm test` exits 0.

---

## 14. Risks & Mitigations (from research ISS-01…06)

| ID | Risk | Mitigation |
|---|---|---|
| ISS-01 | `EXTENSION_ROOT` resolution fails under installed-package load | `resolvePackageRoot` walks to `package.json` by name; tested in `structure.test.ts` for both load paths |
| ISS-02 | Gate silently passes when validator produces no output | Non-vacuous-pass discipline (§8.5); missing output → `failed` with stderr |
| ISS-03 | `map`/`parallel` concurrency conflated | Two-dial invariant documented (§5.3, §8.4); `mode-dispatch.test.ts` covers |
| ISS-04 | Invalid tickers discovered late at Stage 5 | Fail-fast validation in `execute()` (§4.2) |
| ISS-05 | Stray `${CLAUDE_PLUGIN_*}` in agents | `grep -r CLAUDE_PLUGIN agents/` returns nothing; asserted in copy step |
| ISS-06 | Large asset tree stripped by `npm publish` | `files` array lists all eight dirs + `pyproject.toml` + `uv.lock` (§3.2); asserted in `structure.test.ts` |

---

## 15. Out of Scope (Non-Goals, from `01-requirements.md §3`)

NG1 TS rewrite of scripts · NG2 Node replacements for akshare/baostock · NG3 non-pi hosts · NG4 Claude/Codex manifests · NG5 altering analytics/weights/personas/schemas · NG6 UI · NG7 new analytical capability. Behavior parity with the source plugin is the success bar.

---

## 16. Single-Implementation Guarantee (ambiguity prevention)

- Package name: **`@jenningsloy318/pi-stock-analysis`** (no alternative).
- Tool name: **`stock_analysis`**; command: **`/stock-analysis`**.
- Agent count: **22** (all copied; §2.6).
- Script count: **76** (verbatim).
- Schema count: **16** (verbatim).
- Backend env: **`STOCK_ANALYSIS_BACKEND`**; default **`subprocess`**.
- Log dir: **`.stock-analysis-logs/`**; report dir: **`./reports/<RUN_ID>/`** (run cwd).
- Gate attempts: **4**; retry attempts: **10**; per-company concurrency: **4**.
- RUN_ID format: **`YYYYMMDDHHmm` LOCAL**.
- All names, behaviors, and paths in this document are normative; no "etc." or vague terms remain.
