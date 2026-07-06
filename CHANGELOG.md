# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.7] - 2026-07-05

### Fixed
- **conviction field blocked valid reports.** The agent emits `conviction` as a
  label ("High"/"Medium"/"Low") but the schema demanded a number, so the
  gate-reports schema check rejected an otherwise-complete analysis and the
  rendered .md never got written. `EquityReportPayload.scores.conviction` and
  `BestPick.conviction` now accept `number | string` — the field is genuinely a
  label-or-score, and conviction-consistency uses the numeric composite, not
  conviction. Regression test added.

## [0.1.6] - 2026-07-05

### Added
- factCheck() TS validator completes the validate_report.py gate port —
  cross-references raw-data.json vs metrics.json (revenue, market cap, P/E,
  FCF sign, D/E direction), tolerant (neutral when data absent), wired into
  gate-reports alongside dataFreshness and forensicChecks.

### Notes
- validate_report.py is now FULLY retired on the render path. Every gate is
  handled in TS or guaranteed by the template: data freshness, conviction
  consistency, forensic presence (Beneish/Altman/Piotroski), kill-switch
  falsifiability, fact-check (raw↔metrics cross-reference), three_axis (moot —
  short-term template guarantees it), Chinese-language (moot — template is
  Chinese), source-coverage (moot — data stages produce the JSON files). The
  script remains only for the markdown path (STOCK_ANALYSIS_RENDER_REPORTS=0).

## [0.1.5] - 2026-07-05

### Added
- Stage 18 HIGHLIGHTS_BEST_PICKS now renders from a BestPicksPayload via
  templates/best-picks.njk (grouped 核心仓位/成长卫星/期权投机 table + 组合互补性
  check + caution notes + exact disclaimer) — same render default as Stage 17
  (STOCK_ANALYSIS_RENDER_REPORTS=0 reverts to the markdown writer).
- forensicChecks() TS validator (ports validate_report.py gate_forensic_checks):
  Beneish/Altman/Piotroski presence from metrics.json, wired into gate-reports.
- BestPicksPayload schema + bestPicksPayloadBody prompt.

### Notes
- validate_report.py is now retired on the render path: freshness, conviction
  consistency, kill-switch falsifiability, short-term 三轴, and forensic presence
  all run in TS. The fact_check gate is DEFERRED — it cross-references
  raw-data.json, whose shape is inconsistent across runs (per the data census);
  it will be ported once raw-data.json is stabilized.

## [0.1.4] - 2026-07-05

### Changed
- **Template-rendered reports are now the DEFAULT** (Phase 1 complete). Stage 17
  renders schema-validated payloads through Nunjucks templates instead of the
  agent hand-writing markdown, so format (001 ranking, 当前股价 column, exact
  disclaimer, short-term 三轴) is correct by construction. Set
  `STOCK_ANALYSIS_RENDER_REPORTS=0` to revert to the proven markdown writer.
- screen-mode Stage 17 renders sector-level screening reports via
  templates/screening-report.njk + ScreeningReportPayload (one per horizon);
  other modes render per-company equity reports (equity-report.njk).
- gate-reports now runs TS content gates on every render-path report payload
  (conviction consistency, kill-switch falsifiability, short-term 三轴) AND a
  per-company data-freshness check — replacing scripts/validate_report.py on
  this path (no Python round-trip, no markdown parsing).

### Added
- ScreeningReportPayload schema + screening-report.njk canonical template.
- renderScreeningReportsTask (screen mode) + screeningReportPayloadBody.
- dataFreshness() TS validator (ports validate_report.py gate_data_freshness).

## [0.1.3] - 2026-07-05

### Fixed
- **Theme was dropped in screen/pipeline mode (critical).**
  `parseStockAnalysisArgs` only captured positional text as `theme` for `walk`
  mode, so `/stock-analysis --mode screen 人形机器人` set `mode=screen` but
  DISCARDED the theme → `state.theme` was undefined → the theme-aware screener
  prompt never fired → the run screened all 163 sub-industries and picked
  unrelated hot sectors (the 2026-07-05 "mismatch with your intent" report).
  Theme is now captured for screen + pipeline (and the no-`--mode` inference
  path: a bare theme narrows the pipeline; `screen <theme>` narrows the screen).
  Covered by 7 regression tests in arg-parser.test.ts.
- Strengthened the sector-screener THEME-FOCUS prompt to preempt the agent's
  incorrect "theme filtering only happens in walk mode" inference — it now
  states screen IS theme-aware and that returning unrelated hot sectors is a
  failure.

## [0.1.2] - 2026-07-05

### Added
- **TickFlow as default data source.** `pyproject.toml` now declares
  `tickflow[all]` + `curl_cffi` + `polars` (previously only in
  `scripts/requirements.txt`, so `uv` never installed tickflow and the
  name-resolution cascade silently fell through to akshare). The cascade in
  `resolve_tickers.py` already prefers TickFlow — it now actually resolves.

### Changed
- **Python environment preflight (Stage 0).** `setupStage` runs
  `uv sync --project <root>` once before any data collection, so the `.venv`
  (tickflow/akshare/scipy/numba/...) is created/synced up front — every later
  `uv run --project <root> python ...` is instant and deterministic, and env
  failures surface at setup instead of mid-pipeline. Idempotent (<1s after the
  first run), gated on `pyproject.toml` so hermetic tests skip it, non-fatal.
- **Script invocations pin the package env.** `buildScriptArgs` + agent prompts
  now use `uv run --project ${EXTENSION_ROOT} python ...`, so agents running
  from the reports dir use the package's `.venv`/`uv.lock`/`.python-version`
  instead of an ephemeral env lacking tickflow.
- `requires-python = ">=3.12,<3.14"` + `.python-version` (3.12): pandas-ta needs
  >=3.12 and numba (its transitive dep) needs <3.14, so 3.12 is the sweet spot.
  Fixes the universal-lock resolution failure.

### Fixed
- **`TICKFLOW_API_KEY` now reaches spawned agents.** pi can be launched from a
  GUI entry that never sources `~/.bashrc`; `extension.ts` now reads the named
  data-source keys from `~/.bashrc` and exports them into `process.env` so
  spawned `pi` subprocesses + `uv run` children see the key (the 2026-07-05
  Stage-1 "akshare unavailable -> ETF proxy" root cause).

## [0.1.1] - 2026-07-05

### Fixed
- **Gates never validated (critical):** `gateValidator` dispatched through an
  always-empty `HELPER_REGISTRY`, so every gate returned `unknown helper:
  gate-*` and exhausted after 4 retries (8-min agent timeouts on stages
  1/2/4/17/18). `runHelperStub` now delegates to the real `helpers.ts`
  dispatcher. Covered by regression tests in `tests/nodes.test.ts`.
- **`EXTENSION_ROOT` leaked as a literal token:** agent prompts received
  `${EXTENSION_ROOT}` verbatim instead of the resolved package path, so agents
  searched the filesystem and latched onto the stale Claude Code plugin at
  `~/.claude/plugins/marketplaces/stock-analysis`. Now resolved to the actual
  path in the prompt AND exported into `process.env` so spawned `pi`
  subprocesses + bash expand it.
- **Theme ignored in screen/pipeline mode:** a `theme` was carried only as a
  logging string, so a humanoid-robotics screen collapsed onto top-RS financials.
  `dataCollectorBody` / `sectorScreenerBody` / `companyScreenerBody` are now
  theme-aware — when `state.theme` is set they restrict the screen to the
  theme's value-chain sub-industries (via `fetch_sub_industry_universe.py` +
  `fetch_theme_performance.py`).

### Added
- Initial port of the `stock-analysis` Claude Code plugin to a self-contained
  pi extension (`pi-stock-analysis`), mirroring the
  `pi-super-dev` ↔ `super-dev-plugin` port pattern.
- Re-implements the 5-mode / 19-stage equity-research orchestration as a
  TypeScript control-flow node algebra (`src/nodes.ts`) + declarative pipeline
  (`src/stages/index.ts`). No external workflow engine dependency.
- `stock_analysis` tool (Typebox params with `mode` discriminator) and
  `/stock-analysis` command (flag + trigger-phrase arg parser).
- `src/scripts.ts` bridges to the 76 verbatim Python scripts via
  `uv run python` (akshare/baostock have no Node.js equivalent).
- 22 specialist agents copied with invocation-preamble adaptation only.
- Hermetic vitest suite (no `pi` spawns, no network, no `uv` execution).
