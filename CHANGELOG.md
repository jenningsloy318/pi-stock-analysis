# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
