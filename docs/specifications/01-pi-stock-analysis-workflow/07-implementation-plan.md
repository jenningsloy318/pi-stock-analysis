# Implementation Plan — pi-stock-analysis (pi Extension)

**Feature:** `@jenningsloy318/pi-stock-analysis` — pi control-flow workflow extension for unified equity research
**Task type:** refactor / port
**Author:** spec-writer
**Status:** ready for execution
**Companion docs:** `06-specification.md` (technical spec), `08-task-list.md` (granular tasks)

---

## 0. Plan Structure

This plan is a **dependency-ordered DAG of phases**. Each phase is **independently testable**: it has a clear exit gate (a runnable test or command) that proves the phase is complete. Phases carry:

- **`domain`** — the concern area (`manifest`, `assets`, `algebra`, `support`, `pipeline`, `entrypoint`, `docs`, `test`).
- **`depends_on`** — phases that MUST complete first.
- **`parallelizable_with`** — phases with NO dependency on this one (may run concurrently).
- **`exit_gate`** — the concrete verification (test/command) that closes the phase.
- **`maps_to`** — AC-NN / SCENARIO-NNN coverage.

**Phase count:** 7. Phases 1 and 2 are parallelizable (scaffolding vs. asset copy). The critical path is **1 → 3 → 4 → 5 → 6 → 7**.

---

## 1. Phase DAG (visual)

```
   ┌──────────────────────────┐
   │ PHASE 1: Scaffold        │──────────┐
   │ (manifest + config)      │          │
   └──────────┬───────────────┘          │
              │                            │
              │   ┌────────────────────────▼───────────┐
              │   │ PHASE 2: Domain Asset Copy          │  ← parallelizable with 1
              │   │ (agents/scripts/refs/templates/…)   │
              │   └──────────────────┬──────────────────┘
              │                      │
              ▼                      ▼
   ┌──────────────────────────────────────┐
   │ PHASE 3: Node Algebra + Types + Runner │
   │ (nodes.ts, types.ts, workflow.ts,      │
   │  control.ts, helpers.ts)               │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ PHASE 4: Supporting Modules + Python Bridge │
   │ (agents.ts, pi-spawn.ts, session-agent.ts,  │
   │  prompts.ts, scripts.ts)                    │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ PHASE 5: Pipeline Composition        │
   │ (stages/index.ts: choose + 5 modes + │
   │  19 stages + gates + map + retry)    │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ PHASE 6: Extension Entry Point       │
   │ (extension.ts: tool + command +      │
   │  arg parser + progress + summary)    │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ PHASE 7: Skill Pointer + README +     │
   │ Full Test Suite Green                  │
   └───────────────────────────────────────┘
```

---

## 2. Phase Definitions

### PHASE 1 — Package Scaffold & Config
- **`domain`:** `manifest`
- **`depends_on`:** (none — foundation)
- **`parallelizable_with`:** Phase 2
- **Goal:** Establish a valid, type-checkable pi extension skeleton with all config files. No runtime logic yet.
- **Work:**
  - Create `package.json` (name `@jenningsloy318/pi-stock-analysis`, `type: module`, `pi.extensions`/`pi.skills`, peerDeps, `exports`, `files`, `engines`, `scripts`).
  - Create `tsconfig.json`, `vitest.config.ts`, `.gitignore`, `LICENSE` (MIT), `CHANGELOG.md`.
  - Create `src/` directory with empty stub files (`extension.ts`, `nodes.ts`, `workflow.ts`, `types.ts`, `stages/index.ts`, `scripts.ts`, `agents.ts`, `pi-spawn.ts`, `session-agent.ts`, `control.ts`, `helpers.ts`, `prompts.ts`) so `exports` resolve and `tsc --noEmit` passes.
  - Create `tests/structure.test.ts` (asserts manifest shape, `pi.*` config, `exports`, `files`, no `dependencies`, no `@agwab/pi-workflow` keyword absence, engines).
- **`exit_gate`:** `npm run typecheck` exits 0; `npm test` (only `structure.test.ts`) passes. (→ AC-01, AC-02, AC-03; SCENARIO-001…004)
- **`maps_to`:** AC-01, AC-02, AC-03

### PHASE 2 — Domain Asset Copy (Verbatim)
- **`domain`:** `assets`
- **`depends_on`:** (none — pure file copy)
- **`parallelizable_with`:** Phase 1
- **Goal:** Bring all source domain assets into the package byte-identical (scripts/references/templates/schemas/assets) + agents with preamble-only edits.
- **Work:**
  - Copy `scripts/*.py` (76) + `scripts/requirements.txt` + `pyproject.toml` + `uv.lock` from `stock-analysis-plugin/` → repo root **verbatim** (byte-identical).
  - Copy `references/`, `templates/`, `schemas/*.json` (16), `assets/report_styles.css` → repo root **verbatim**.
  - Copy 22 `agents/*.md`; for each, edit **only** the invocation preamble (replace Claude `Agent`/`subagent_type` notes + `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` → pi invocation + `${EXTENSION_ROOT}`). Preserve all analytical content, frameworks, schemas, personas.
  - Verify `grep -r CLAUDE_PLUGIN agents/` returns nothing (ISS-05).
  - Extend `tests/structure.test.ts` to assert: `>=22 agents`, `76 scripts`, `16 schemas`, presence of `references/`/`templates/`/`assets/report_styles.css`, and **absence** of excluded artifacts (`workflows/`, `.claude*`, `plugin.json`, `reports/`, root `stage*.md`, root `*.py`, `run_triage.sh`, `test.py`, `rules/`).
- **`exit_gate`:** `npm test` passes; byte-identity of scripts verified by a checksum assertion (optional) or file-count + spot-check. (→ AC-12, AC-13, AC-14, AC-15; SCENARIO-025…029)
- **`maps_to`:** AC-12, AC-13, AC-14, AC-15

### PHASE 3 — Node Algebra + Domain Types + Runner
- **`domain`:** `algebra`
- **`depends_on`:** Phase 1
- **`parallelizable_with`:** (none — on critical path)
- **Goal:** Port the self-contained control-flow engine from pi-super-dev; adapt domain shapes to stock-analysis.
- **Work:**
  - Port `src/nodes.ts` near-verbatim (PAT-004): `task`, `sequence({tolerant})`, `branch`, `choose`, `parallel({concurrency})`, `loop`, `retry({attempts,until,backoffMs})`, `gate({validate,attempts,feedbackKey})`, `map({over,as,concurrency})`, `wait`, `waitForEvent`, `tryCatch`, `noop`, `writerTask`, `helperTask`, `gateValidator`. **No `@agwab/pi-workflow`.**
  - Adapt `src/types.ts` (§7): `StockAnalysisState` (mode, runId, tickers, theme, screening controls, companies, sharedData, reports, tracking, __feedback), `Company`, `Stage`, `StageContext`, `Node`, `NodeResult`, `AgentResult`, `HelperCall/Result`, `ScriptCall/Result`, `RunSummary`, `Tracking`. Remove super-dev's `SetupControl`/`Classification`.
  - Port `src/workflow.ts` near-verbatim (§6): `makeContext`, `runWorkflow` (`await root.run(state, ctx)`), backend switch (`STOCK_ANALYSIS_BACKEND`), gate feedback injection.
  - Port `src/control.ts` (§10.4): `extractControl`, `findLastJsonObject`, `extractControlKeys`.
  - Port `src/helpers.ts` skeleton (§10.5): `runHelper` dispatcher + `normalizeAshTicker` + `isAshTicker` + `RUN_ID` generator (`YYYYMMDDHHmm` LOCAL).
  - Write `tests/nodes.test.ts` (algebra semantics with a fake `StageContext`), `tests/workflow.test.ts` (composed tree runs to completion), `tests/control.test.ts`, `tests/ticker-normalize.test.ts`.
- **`exit_gate`:** `npm run typecheck` 0; `npm test` (phases 1–3 tests) passes. (→ AC-07, AC-08, AC-09; SCENARIO-014…017, 044, 045)
- **`maps_to`:** AC-07, AC-08, AC-09

### PHASE 4 — Supporting Modules + Python Bridge
- **`domain`:** `support`
- **`depends_on`:** Phase 3
- **`parallelizable_with`:** (none)
- **Goal:** Provide the agent-loading + spawning + script-invocation infrastructure that stages will call.
- **Work:**
  - Port `src/agents.ts` (§10.1): load `agents/<name>.md`, parse YAML frontmatter + body.
  - Port `src/pi-spawn.ts` (§10.2): `spawnAgent` → `pi -a <agent>` subprocess; `abbreviatePath`.
  - Port `src/session-agent.ts` (§10.3): `createAgentSession` in-process backend.
  - Port `src/prompts.ts` (§10.6): prompt builders injecting `EXTENSION_ROOT` + per-stage state slice + gate feedback; context-eviction discipline.
  - Implement `src/scripts.ts` (§9): `runScript(name, args, {cwd, root, timeoutMs, sink})` → `uv run python ${root}/scripts/<name>.py …`; path validation (`^[A-Za-z0-9_-]+$`), timeout, structured-error path, `findLastJsonObject` parsing. Wire `helpers.ts runHelper` script-backed names (`compute_scores`, `cross_check`, `calibrate_conviction`, `validate_report`, `score_bottleneck_asymmetry`, `compute_tam_adj_peg`, `compute_bayesian_growth`) to `runScript`.
  - Write `tests/scripts.test.ts` with `child_process.spawn` **mocked**: asserts command shape, timeout kill, structured-error path, path-traversal rejection (SCENARIO-030, 031, 032).
- **`exit_gate`:** `npm run typecheck` 0; `npm test` passes (now includes scripts tests). (→ AC-16, AC-17; SCENARIO-030…033)
- **`maps_to`:** AC-16, AC-17

### PHASE 5 — Pipeline Composition (5 modes × 19 stages)
- **`domain`:** `pipeline`
- **`depends_on`:** Phase 3, Phase 4
- **`parallelizable_with`:** (none)
- **Goal:** Compose the declarative pipeline tree using the node algebra; this is where the 5-mode dispatch + per-company DAG + gates + retry live.
- **Work:**
  - Implement `src/stages/index.ts` (§8): export `root: Node = choose([...])` over `state.mode`, each case a `sequence([...], {tolerant:true})` per §8.2 table.
  - Define per-stage `Stage` objects (id, fatal flag for Stage 0 only, run fn). Wire agents via `ctx.agent()` and deterministic calcs via `ctx.helper()`/`runScript`.
  - Compose conditional `branch` blocks: screening-only (2–4.5) for pipeline/screen; walk replacement; A-share Stage 15 inside company body.
  - Compose per-company DAG (§8.4): `map({over:"companies", as:"company", concurrency:4}, sequence([wave1 parallel, wave2 parallel, wave3 parallel, branch(ashare)]))` with every analyst `task` wrapped in `retry({attempts:10})`.
  - Compose the 5 gates (§8.5): 1.5/4.5/16.5/18.5 via `reportValidator` agent; 17.5 via `gateValidator("validate_report", …)` → `runScript`. Non-vacuous-pass discipline.
  - Compose 16.6 adversarial verify (`map` over top-5 picks × `parallel` of 3 skeptics) and 16.7 judge panel (`parallel` of 4 lenses).
  - Compose Stage 19 cleanup as the always-last tolerant task.
  - Write `tests/mode-dispatch.test.ts`: each of the 5 modes selects the correct stage sequence; conditional stages skip correctly; concurrency-independence (ISS-03) asserted. (→ AC-10; SCENARIO-018, 019, 021, 022)
- **`exit_gate`:** `npm run typecheck` 0; `npm test` passes (includes mode-dispatch tests with fake agents). (→ AC-10, AC-11; SCENARIO-018…024)
- **`maps_to`:** AC-10, AC-11

### PHASE 6 — Extension Entry Point (Tool + Command)
- **`domain`:** `entrypoint`
- **`depends_on`:** Phase 5
- **`parallelizable_with`:** (none)
- **Goal:** Register the `stock_analysis` tool and `/stock-analysis` command; wire progress streaming + run log + honest summary.
- **Work:**
  - Implement `src/extension.ts` (§4): `EXTENSION_ROOT` resolution (`resolvePackageRoot`); `default activate(pi)` registering the tool (Typebox params, fail-fast per-mode validation, `execute` building state + `ProgressSink` + calling `runWorkflow`) and the command (arg parser + trigger-phrase fallback + JSON escape hatch + `pi.sendUserMessage` dispatch).
  - Implement `parseStockAnalysisArgs(argString)` as a pure exported function (unit-testable).
  - Implement `formatSummary(state)` (PAT-003): derive `success|partial|failed` from artifacts + gate flags; never default to success.
  - Write `tests/arg-parser.test.ts`: all flag forms, JSON escape hatch, trigger-phrase fallback, default pipeline; plus `formatSummary` honest-status cases. (→ AC-04, AC-05, AC-06; SCENARIO-005…013)
- **`exit_gate`:** `npm run typecheck` 0; `npm test` passes (arg-parser + summary tests). (→ AC-04, AC-05, AC-06)
- **`maps_to`:** AC-04, AC-05, AC-06

### PHASE 7 — Skill Pointer + README + Full Suite Green
- **`domain`:** `docs`, `test`
- **`depends_on`:** Phase 6
- **`parallelizable_with`:** (none — final integration)
- **Goal:** Close out documentation and prove the whole package is green.
- **Work:**
  - Write `skills/stock-analysis/SKILL.md` (§10.8) — SHORT pointer: description, `/stock-analysis` command, 5 modes (one line each), keep-Python contract, pointer to README/spec.
  - Write `README.md` (§11): install, prerequisites (`uv`), 5 usage examples, node-algebra table, per-mode diagrams (ASCII), the explicit Python-keep rationale, agent→script invocation, architecture pointer.
  - Optional: `docs/architecture.mmd` (Mermaid, OQ-6).
  - Finalize `tests/structure.test.ts`: assert `pi.skills[0]` resolves, skill file is "short" (line-count bound), README sections present.
  - Full suite run: `npm run typecheck` && `npm test` both exit 0.
- **`exit_gate`:** `npm run typecheck` 0 AND `npm test` 0 on a clean install; README + skill pointer present. (→ AC-18, AC-19, AC-20, AC-21; SCENARIO-034…041)
- **`maps_to`:** AC-18, AC-19, AC-20, AC-21

---

## 3. Critical Path & Parallelism

- **Critical path:** P1 → P3 → P4 → P5 → P6 → P7 (6 sequential steps).
- **Parallel fan-out:** P1 and P2 are fully independent and MAY execute concurrently (different `domain`s, no shared files: P1 writes `package.json`/config/stubs; P2 writes `agents/`/`scripts/`/`references/`/`templates/`/`schemas/`/`assets/`).
- **No other parallelism** is safe: P3+ each mutate `src/` and depend on prior types/nodes.
- **Sub-agent execution model (per `pi-subagents` skill):** P1 and P2 can be dispatched as a 2-task `parallel` fan-out; P3–P7 are a strict `chain`. All child agents use `fresh` context (no shared writer contention because P1/P2 touch disjoint files).

---

## 4. Cross-Domain Dependencies (explicit)

| From (phase) | Needs from (phase) | Artifact |
|---|---|---|
| P3 | P1 | `tsconfig.json`, `package.json` peers, `tests/` harness |
| P4 | P3 | `types.ts` shapes, `StageContext`, `control.ts`, `helpers.ts` dispatcher |
| P4 | P2 | `agents/*.md` files (for `agents.ts` to load), `scripts/*.py` (for `runScript` to target) |
| P5 | P3 | node algebra (`nodes.ts`), runner (`workflow.ts`), types |
| P5 | P4 | `ctx.agent()`, `ctx.helper()`, `runScript`, prompt builders |
| P6 | P5 | the `root` pipeline node |
| P6 | P4 | `EXTENSION_ROOT`, prompts, scripts helper |
| P7 | P6 | the registered extension (for structure/skill assertions) |
| P7 | P2 | copied assets (for README references + skill pointer accuracy) |

---

## 5. Phase → Acceptance-Criteria Coverage

| AC | Phase(s) |
|---|---|
| AC-01, AC-02, AC-03 | P1 |
| AC-04, AC-05, AC-06 | P6 |
| AC-07, AC-08, AC-09 | P3 |
| AC-10, AC-11 | P5 |
| AC-12, AC-13, AC-14, AC-15 | P2 |
| AC-16, AC-17 | P4 |
| AC-18, AC-19, AC-20, AC-21 | P7 |
| AC-22, AC-23, AC-24, AC-25 | P5 (composition) + P4 (prompts/scripts) + P2 (agent preambles) |

**Every AC-01…AC-25 is owned by at least one phase.** Behavioral-parity ACs (22–25) are enforced across P2/P4/P5 and validated by P5/P7 tests.

---

## 6. Risk-Aware Sequencing Notes

- **ISS-01 (EXTENSION_ROOT):** resolved in P6 but tested in P7 `structure.test.ts` (both load paths). P3 stubs the resolution point so P4/P5 can thread `ctx.extensionRoot`.
- **ISS-02 (non-vacuous gate):** enforced in P5 (gate composition); P4 provides `runScript` structured errors so a missing `uv` surfaces as `failed`, not silent pass.
- **ISS-03 (concurrency dials):** P5 documents + P5 `mode-dispatch.test.ts` asserts.
- **ISS-04 (fail-fast tickers):** P6 `execute()`.
- **ISS-05 (CLAUDE_PLUGIN scrub):** P2 copy step + grep check.
- **ISS-06 (files array):** P1 declares; P2/P7 populate + assert.

---

## 7. Definition of Done (per phase)

A phase is DONE when **all** hold:
1. Every task in that phase (see `08-task-list.md`) is complete.
2. The phase `exit_gate` command/test passes.
3. `npm run typecheck` still exits 0 (no type regressions introduced).
4. No file outside the phase's declared `domain` is modified (keeps merges clean).

---

## 8. Summary

Seven phases, one critical path (P1→P3→P4→P5→P6→P7), one parallel fan-out (P1 ∥ P2). Every phase is independently testable via a concrete exit gate. Every AC-01…AC-25 and SCENARIO-001…050 is owned by a phase. The plan mirrors the pi-super-dev derivation: ~90% engine reuse (P3/P4), novel work concentrated in P5 (pipeline composition) and P6 (entry point), with verbatim domain assets (P2) and closing docs/tests (P7).
