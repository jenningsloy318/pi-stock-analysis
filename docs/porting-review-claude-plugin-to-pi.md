# Porting Review — `stock-analysis-plugin` (Claude Code) → `pi-stock-analysis` (pi extension)

**Scope of review.** Comparison of the original Claude Code plugin
(`~/development/personal/jenningsloy318/stock-analysis-plugin`, ref commit and
current tip) against the pi rewrite (`~/development/personal/pi-stock-analysis`,
first meaningful commit `bc26bc0` through current tip `0.1.7`). Goal: what was
achieved, what gaps remain, and what improvements to consider next.

Structural axis: **agents, references, scripts, templates, schemas, orchestration.**

---

## 1. TL;DR

The rewrite is a **faithful, complete port** of the 5-mode / 19-stage
equity-research pipeline with a **substantially better architecture**:

- All 22 specialist agent prompts, all Python scripts (77 vs 78 — the 78th was
  `__pycache__`), all reference documents, and all templates carried over.
- The 1 828-line procedural JavaScript workflow (`workflows/stock-analysis.js`)
  was replaced by a **declarative control-flow node algebra** (~570 LOC of
  reusable node primitives) and a **433-line pipeline definition**
  (`src/stages/index.ts`) that reads top-to-bottom like the SKILL.md prose.
- Runtime is TypeScript with **TypeBox** schemas end-to-end (params → payloads
  → validation) and 186 hermetic Vitest tests (the original had one test.py stub).
- Since the port, the project has moved **beyond** the original in three ways:
  (1) TickFlow as the default data source with automatic `uv sync` preflight,
  (2) Nunjucks + TypeBox schema-driven document rendering that fully retires
  `scripts/validate_report.py` on the render path, (3) structured gate feedback
  that lets a rejected agent see the specific validator errors on retry.

No stage was dropped. No specialist agent was dropped. No Python calculation
was reimplemented in TS — the deterministic core is preserved verbatim.

---

## 2. What was achieved

### 2.1 Orchestration rewritten as a node algebra

The original 1 828-line `workflows/stock-analysis.js` was a single procedural
script that inlined:

- Argument parsing (three separate regex passes for a string form, an object
  form, and inference fallbacks).
- 15 JSON Schema constants inlined at the top of the file.
- An `agentWithRetry` wrapper (10 attempts) wrapping every `agent()` call.
- Manual phase tracking (`PHASE_REGISTRY`, `trackPhaseStart/End`,
  `persistTracking`) driven by spawning an agent whose only job is to
  `Write file`.
- Per-mode branching hand-coded as `if (MODE === 'walk') {...}` blocks.
- Per-company DAG fanout via a hand-rolled `asyncPool(4, companies, orchestrate)`.

The rewrite factors these into 14 named primitives in `src/nodes.ts`:

```
task, sequence, branch, choose, parallel, loop, retry, gate,
map, wait, waitForEvent, tryCatch, noop, writerTask
```

Every primitive is a `Node` with a single `.run(state, ctx)` contract. The
pipeline (`src/stages/index.ts`) reads like the SKILL.md `<stages>` block:

```ts
const pipelineSequence = sequence([
  setupStage,
  gateSharedData,
  task(sectorScreenerStage),
  task(companyScreenerStage),
  gateScreening,
  perCompanyBlock,        // map(concurrency:4) over companies
  gateScoring,
  adversarialStage,       // map over top-5
  judgePanelStage,
  gateReports,            // gate → choose(render vs markdown) → writerTask
  reportTail,             // critic → best-picks-gate → cleanup
], { tolerant: true });
```

Concrete gains:

- **Declarative:** stages are values, not code paths. Mode dispatch is a single
  `choose([...], defaultPipeline)`. Reordering a stage is one line.
- **Reusable:** `map`, `retry`, `gate`, `parallel` are used by all 5 modes.
- **Testable:** node semantics are covered by `tests/nodes.test.ts`,
  `tests/control.test.ts`, `tests/structure.test.ts` (62 tests total) using a
  fake context (`tests/helpers/fake-context.ts`), no real `pi` spawns.
- **Runner is trivial:** `src/workflow.ts` is 203 LOC total; the top of `run` is
  literally `await root.run(state, ctx)`.

### 2.2 Type-safe surface end to end

`src/types.ts` (365 LOC) captures every previously-loose object as a TypeScript
type: `StockAnalysisState`, `Company`, `AgentCall`, `AgentResult`, `HelperCall`,
`ScriptCall`, `StageContext`, `RunOptions`, `RunSummary`, `Node`, `Budget`,
`ProgressSink`.

`src/extension.ts` uses TypeBox for the tool's parameter schema — pi's tool
gateway validates params before `execute()` is called, so the fail-fast
validation (`validateParams`) fires on structurally-valid input rather than
free-text argument parsing failures like the original.

### 2.3 Schema-driven rendering (post-port improvement)

The single largest architectural upgrade past the original.

Original: the equity-report-writer agent hand-wrote the full markdown report,
and `scripts/validate_report.py` parsed the markdown back with regex to check
format (001-format ranking, 当前股价 column, disclaimer, three-axis short-term,
kill-switch specificity, conviction consistency, forensic presence, fact-check).
Every format drift the LLM introduced was a validator failure.

Rewrite (v0.1.3 → v0.1.7): the agent emits a **schema-validated JSON payload**
(`EquityReportPayload`, `ScreeningReportPayload`, `BestPicksPayload` — TypeBox)
containing only content strings. The Nunjucks template
(`templates/equity-report.njk` etc.) owns all formatting. As a result:

| Original gate                     | Rewrite path                                  |
| --------------------------------- | --------------------------------------------- |
| gate_data_freshness (regex md)    | `dataFreshness()` TS, checks JSON files       |
| gate_conviction_consistency       | `convictionConsistency()` TS, checks payload  |
| gate_kill_switch (falsifiability) | `killSwitchFalsifiable()` TS, checks payload  |
| gate_three_axis                   | Guaranteed by template — no gate needed       |
| gate_chinese_language             | Guaranteed by template — no gate needed       |
| gate_source_coverage              | Guaranteed by data stages producing JSON      |
| gate_forensic_checks (Beneish/…)  | `forensicChecks()` TS, checks metrics.json    |
| gate_fact_check                   | `factCheck()` TS, cross-references raw/metrics|

`scripts/validate_report.py` is retained only for the fallback markdown path
(`STOCK_ANALYSIS_RENDER_REPORTS=0`). On the default render path it is retired.

### 2.4 Gate feedback loop

`state.__feedback[stageId]` — a rejected gate now stores the specific validator
errors, and the retry prompt prepends them under
`## Previous attempt rejected — fix these` (`src/workflow.ts` `agent()`). The
original just retried with the same prompt and hoped the LLM sampled a
different answer.

### 2.5 Environment robustness

Three infrastructure fixes that the original had left as documented workarounds:

- **`uv sync` preflight** at Stage 0 — creates the package `.venv` up front so
  the first `uv run` is not a several-minute stall mid-pipeline.
- **`--project ${EXTENSION_ROOT}`** on every `uv run` — scripts running in the
  reports dir now use the package's `pyproject.toml`/`uv.lock`/`.python-version`
  instead of an ephemeral env missing tickflow. (Original quietly fell through
  to akshare, then to ETF proxies.)
- **`TICKFLOW_API_KEY` bashrc scavenge** — pi can be launched from a GUI entry
  that never sourced `~/.bashrc`; `extension.ts` reads the named keys with a
  regex (never sources the file) and exports them into `process.env`.

### 2.6 Full parity of surface

| Surface           | Original                           | Rewrite                    | Status |
| ----------------- | ---------------------------------- | -------------------------- | :---:  |
| Agents (`.md`)    | 22                                 | 22                         | ✅     |
| Python scripts    | 77 + `__pycache__`                 | 77                         | ✅     |
| References        | frameworks_*, gics_taxonomy, …     | identical set               | ✅     |
| Templates         | equity-report.md, screening-report.md, ecosystem-health.md.j2, industry-trajectory.md.j2, company-status.json, workflow-tracking.json | all 6 present + new .njk render templates | ✅ + additions |
| Schemas (JSON)    | inline in `workflows/stock-analysis.js` (15 schema constants) | extracted to `schemas/*.json` (16 files) | ✅ + refactor |
| Modes             | pipeline, screen, analyze, compare, walk | identical, per-mode sequences in TS | ✅ |
| Stage IDs         | 0, 1, 1.5, 2, 3, 4, 4.5, 5-15, 16, 16.5, 16.6, 16.7, 17, 17.4, 17.5, 18, 18.5, 19 | identical IDs | ✅ |
| Retry policy      | 10 attempts on null (`agentWithRetry`) | `retry({ attempts: 10 })` around every analyst | ✅ |
| Concurrency       | `asyncPool(4, ...)`                | `map({ concurrency: 4 })` + `parallel(..., { concurrency })` | ✅ + split |
| Chinese reports   | required                           | preserved in prompts + templates | ✅ |
| 3-horizon output  | long / mid / short                 | preserved                  | ✅ |
| CN/US universe    | `passUniverse` regex               | `helpers.ts` — same regex, unit tested | ✅ |
| A-share normalize | inline `normalizeCNTicker`         | `normalizeAshTicker`, 21 tests | ✅ |
| Trigger phrases   | inline arg parsing                 | `src/args.ts` + 30 arg-parser tests | ✅ |
| version-sync rule | manual `sed` across manifests      | (see gap 3.1)              | ⚠️  |

---

## 3. Gaps and residual risk

### 3.1 Version-sync ceremony not automated (minor)

The original CLAUDE.md documents "Version Bump Rule" as a hard requirement: on
any change, bump `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`,
`.antigravitycli/plugin.json`, `skills/stock-analysis/SKILL.md`,
`skills/workflow/SKILL.md`, `CHANGELOG.md`, and `README.md`.

The rewrite reduced the manifest surface (one `package.json`, one
`skills/stock-analysis/SKILL.md`, `CHANGELOG.md`, `README.md`), but the sync is
still manual. Consider a `scripts/bump-version.sh` or a `npm version` hook that
propagates the new version into the SKILL.md front-matter and prepends a
CHANGELOG stub. Cost: ~30 lines.

### 3.2 Stage 19 cleanup is a stub

`cleanupStage` currently just logs — the actual file deletion is delegated to
the equity-report-writer agent's post-processing per its `.md` protocol. This
matches the original (also non-deterministic on cleanup), but the rewrite has
enough type-safety to reclaim this: `state.reports` holds every canonical output
path and `state.reportsDir` is known, so a deterministic sweep of
`stage*.md`/`raw-data.json`/`phase*.md` from `state.reportsDir` — keeping paths
in `state.reports` and `HIGHLIGHTS_BEST_PICKS.md` — is straightforward. This
would remove an agent spawn from the critical path.

### 3.3 `runHelper` still stubs `gate-*` through helpers

Fixed in v0.1.1 for the reachability bug, but the gate helpers still live in
`helpers.ts` next to pure calculation helpers. As gate count grows,
splitting `helpers.ts` into `helpers.ts` (pure functions) and `gates.ts`
(state-aware validators) would clarify the responsibility split.

### 3.4 No integration test that exercises the real pipeline

The 186 hermetic tests cover node semantics, arg parsing, validators, ticker
normalization, and rendering — but no test end-to-end runs a real (or recorded)
`pi` spawn against a stubbed model. The original had none either, so this is
strictly a *preservation* of the gap, not a regression. Options:

- Add a `tests/e2e/*.test.ts` gated behind an env var that spawns `pi` with a
  fake model provider (dev only).
- Record a fixture run under `tests/fixtures/run-<hash>/` and replay it via
  the `session` backend with a mocked agent tool.

### 3.5 Two agent files carry render-mode drift

`agents/equity-report-writer.md` and `agents/team-lead-workflow.md` in the
rewrite gained a `<render-mode>` preamble that the original lacks. This is
intentional (payload mode vs markdown mode). But the same information is *also*
in the prompt body (`reportPayloadBody`, `bestPicksPayloadBody`). Duplication is
minor but real — pick one canonical location (recommend: prompt body only, so
the agent .md stays authoritative for the markdown/legacy path).

### 3.6 `market-daily-orchestrator.md` also differs

Not investigated in depth. Diff is likely cosmetic — worth a quick spot-check
so drift doesn't accumulate.

### 3.7 Two duplicate template pairs

The rewrite keeps `templates/equity-report.md` **and** `templates/equity-report.njk`,
`templates/screening-report.md` **and** `templates/screening-report.njk`. The
`.md` versions are the fallback markdown-writer templates the agent references
when `STOCK_ANALYSIS_RENDER_REPORTS=0`. Now that the render path is the default,
and given `validate_report.py` is retired on that path, consider:

- Add a deprecation banner to the `.md` templates.
- Set a target release (e.g. 0.2.0) to remove the markdown path — collapses two
  code paths and one large Python script.

---

## 4. Improvements the rewrite made (beyond parity)

Ordered by impact.

1. **Declarative pipeline** — `src/stages/index.ts` reads like SKILL.md. One
   place to see every mode's stage flow. Adding a stage is one `sequence` entry.

2. **Node algebra** — `retry`, `gate`, `map`, `parallel`, `choose`, `branch`
   are values, not code paths. This is what makes (1) possible.

3. **Two independent concurrency dials** (ISS-03) — the original conflated
   company-level and stage-level concurrency into a single `asyncPool(4, ...)`.
   The rewrite has `map(concurrency: 4)` for companies and
   `parallel(concurrency: N)` for stages *within* one company. This lets a run
   scale to more companies without oversubscribing per-company waves (or vice
   versa).

4. **TypeBox-backed schemas** — the 15 inline JSON Schema constants in the
   original are now typed TypeScript objects with `Static<typeof T>` inferring
   the runtime shape. Payloads are validated with a JIT-compiled checker
   (`typebox/compile`).

5. **Schema-driven rendering** — the largest quality win. The agent no longer
   owns markdown formatting. `validate_report.py` becomes retired-code on the
   default path.

6. **Structured gate feedback** — a rejected gate now feeds the specific errors
   back into the retry prompt. Convergence in fewer attempts.

7. **`uv sync` preflight + `--project` pinning** — deterministic Python env,
   fast subsequent invocations.

8. **`TICKFLOW_API_KEY` bashrc scavenge** — resolves the GUI-launch data-source
   gap without asking the user to reconfigure their environment.

9. **Fail-fast input validation** (ISS-04) — `validateParams` runs before any
   work starts and returns a structured error. Original would run Stage 0
   before discovering the ticker set was empty.

10. **`EXTENSION_ROOT` resolution** (ISS-01) — supports both `pi -e .`
    (development from source) and `pi package add` (published npm install) by
    walking up until it finds the `pi-stock-analysis` `package.json`.

11. **186 hermetic tests, 2.3s runtime** — up from `test.py` in the original.
    Every regression bug (theme dropped, gate never validated, `EXTENSION_ROOT`
    literal leak, conviction schema mismatch) has an accompanying regression
    test.

12. **Honest run status** (ISS-02) — `deriveStatus()` never defaults to
    "success" on real failure; a failed stage or gate downgrades to "partial";
    an aborted run is "failed". Original had `tracking.status = 'running'`
    hard-coded and only flipped at the end.

13. **Rolling live-tail log** (`.stock-analysis-logs/<runId>.log`) — the tool
    surface shows the last 400 lines; the full transcript is persisted to disk.

14. **Explicit backend switch** — `subprocess` (default) vs `session`
    (in-process) selected via `STOCK_ANALYSIS_BACKEND` env or per-call option.
    Enables faster local iteration.

---

## 5. Recommended next steps

Ordered by ROI.

> **See `docs/roadmap-next-steps.md` for the detailed execution plan** — file
> references, code sketches, effort estimates, and validation criteria for
> each item below.

**A. Remove the markdown-path duplication (v0.2.0 candidate).** Kill the
`.md` templates, delete `scripts/validate_report.py`, delete the
`STOCK_ANALYSIS_RENDER_REPORTS=0` branch, delete `writerTask`-based Stage 17/18.
Estimated **~3 050 LOC removed** (`validate_report.py` alone is 1 650), one
Python round-trip removed. Prerequisite: Item F below (recorded-fixture e2e)
validates the render path against a real run.

**B. Make Stage 19 deterministic.** Replace the `cleanupStage` stub with a
`node:fs` sweep that keeps `state.reports[].path`, `HIGHLIGHTS_BEST_PICKS.md`,
and `workflow-tracking.json`, deletes everything else. Removes one agent spawn
from the critical path.

**C. Consolidate render-mode instructions.** Choose either the agent `.md` file
or the prompt body as the canonical location for `<render-mode>` guidance. Kill
the other.

**D. Split `helpers.ts` into pure helpers + state-aware gates.** As gate count
grows, this will pay for itself.

**E. Add a version-bump helper.** `scripts/bump-version.sh <newver>` that
updates `package.json`, `skills/stock-analysis/SKILL.md` front-matter, and
prepends a `CHANGELOG.md` stub.

**F. Recorded-fixture e2e test** (prerequisite for A). One golden run under
`tests/fixtures/` replayed via the `session` backend against a mock model,
gated behind `E2E=1`. Catches the class of bugs the current 186 hermetic tests
cannot (integration between stages, agent prompt drift, script arg drift).

**G. Doc improvement — a diagram of the node algebra.** A short
`docs/architecture.md` with a rendered SVG of the pipeline tree (e.g. using
`mermaid`) would make (1) even more discoverable for new contributors.

---

## 6. Verdict

The rewrite is not a straight port — it is a **rewrite that reorganizes the
1 828-line procedural workflow into a small, orthogonal control-flow algebra**,
carries every functional piece intact, and has already advanced past the
original on the two hardest problems the original faced:

1. **Format-drift-driven validator failures** (fixed by schema + template
   rendering, `validate_report.py` retired on the default path).
2. **Silent data-source fallthrough** (fixed by TickFlow default,
   `TICKFLOW_API_KEY` scavenge, `uv sync` preflight, `--project` pinning).

Remaining gaps are cleanup opportunities, not blockers. The default answer to
"should we keep both code paths?" is now "no" — the render path has crossed
into production quality.
