# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-05

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
