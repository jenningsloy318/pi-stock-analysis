# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] / 0.1.0]

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
