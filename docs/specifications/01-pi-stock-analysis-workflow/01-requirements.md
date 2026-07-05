# Requirements — pi-stock-analysis (pi Extension)

**Feature name:** `pi-stock-analysis` — self-contained pi control-flow workflow extension for unified equity research
**Task type:** refactor / port (re-implement orchestration of an existing Claude Code plugin as a pi extension)
**Author:** requirements-clarifier
**Status:** implementation-ready (pending resolution of Open Questions OQ-1, OQ-4)

---

## 1. Executive Summary

We will create a NEW npm pi extension package in `/home/jenningsl/development/personal/pi-finance` that re-implements the `stock-analysis` orchestration (currently a Claude Code plugin at `~/jenningsloy318/stock-analysis-plugin`) as a self-contained **pi control-flow workflow** — structurally and stylistically mirroring `~/jenningsloy318/pi-super-dev` (which was itself derived from `~/jenningsloy318/super-dev-plugin`).

The extension exposes ONE pi tool `stock_analysis` (with a `mode` parameter and per-mode options) and ONE pi command `/stock-analysis` (natural-language arg parser → tool dispatch). The workflow is composed from a composable node algebra (`task / sequence / branch / choose / parallel / loop / retry / gate / map / wait / tryCatch / noop`) that orchestrates 22 specialist agents across **5 execution modes** (`pipeline | screen | analyze | compare | walk`) and **19 pipeline stages** with per-company async waves, gate validations, adversarial verification, and a judge panel.

**Two pivotal design decisions are resolved up-front:**

1. **Multiple execution modes → `choose` node + tool parameter + arg-parsing command.** One tool, one command; the workflow ROOT uses `choose(state.mode)` to dispatch the correct stage sequence per the SKILL.md `<modes>` table. This is simpler and more discoverable than five separate tools/commands, and it matches how `super_dev` exposes a single entrypoint.
2. **Python scripts → KEEP, do NOT rewrite in TypeScript.** The 76 scientific/financial Python scripts (akshare, baostock, yfinance, scipy, statsmodels, arch, pandas-ta, polars, praw, pytrends, tickflow, curl_cffi) are copied verbatim. akshare + baostock have **no Node.js equivalent** — rewriting would be hundreds of hours for real capability loss. A thin TS helper `runScript()` shells out to `uv run python ${EXTENSION_ROOT}/scripts/<name>.py`. This is the **same boundary** pi-super-dev drew: re-implement ORCHESTRATION in TS; keep deterministic analysis code + domain artifacts verbatim.

The pipeline is **best-effort/tolerant** (a failed non-setup stage is logged, not fatal) and preserves every behavioral rule of the source SKILL.md (Chinese-language reports, all-3-horizons, price/headroom/universe filters applied at Stage 4 only, A-share analysis mandatory for `.SH`/`.SZ`, no-pause, retry-on-null 10×, shared-data-once, context-eviction, max-4-concurrent).

---

## 2. Background & Context

### 2.1 Reference: the pi-super-dev pattern to mirror

`~/jenningsloy318/pi-super-dev` is the structural template. Its layout (verified):

```
pi-super-dev/
  package.json          # name, pi.extensions, pi.skills, peerDeps, type:module, engines, exports
  src/
    extension.ts        # registers `super_dev` tool + `/super-dev` command (progress stream + run log)
    nodes.ts            # control-flow node algebra (task/sequence/branch/choose/parallel/loop/retry/gate/map/wait/tryCatch/noop)
    pipeline.ts         # (alias of stages/index)
    workflow.ts         # self-evaluating runner: `await root.run(state, ctx)`
    types.ts            # PipelineState, Node, Stage, StageContext, RunSummary, …
    stages/index.ts     # pipeline expressed as a tree of nodes
    agents.ts           # loads agents/<name>.md
    pi-spawn.ts         # spawns `pi -a <agent>` subprocesses
    session-agent.ts    # in-process backend (selectable via env)
    control.ts          # tolerant <control> JSON extractor
    helpers.ts          # deterministic helpers
    prompts.ts          # prompt builders
  skills/super-dev/SKILL.md   # SHORT pi skill pointer
  agents/*.md           # specialist agent definitions
  tests/*.test.ts       # hermetic vitest suite (no pi spawns, no network)
  README.md             # architecture doc with node-algebra table + pipeline diagram
```

`package.json` essentials (to replicate):
```json
{
  "type": "module",
  "pi": { "extensions": ["./src/extension.ts"], "skills": ["./skills/..."] },
  "peerDependencies": { "@earendil-works/pi-coding-agent": "*", "typebox": "*" },
  "engines": { "node": ">=22.19.0" },
  "scripts": { "build": "tsc", "typecheck": "tsc --noEmit", "test": "vitest run" },
  "exports": { "./extension": "./src/extension.ts", "./nodes": "./src/nodes.ts", … }
}
```

### 2.2 Source: what is being converted

`~/jenningsloy318/stock-analysis-plugin`:
- `skills/stock-analysis/SKILL.md` — THE authoritative spec (5 modes, 19 stages, per-company async DAG, gate validations, composite-weights, 14+ rules). Re-implemented in the pi node algebra.
- `agents/*.md` — 22 specialists (alt-data, catalyst, china-market, company-orchestrator, company-screener, data-collector, equity-report-writer, fundamental, industry, macro, market-daily-orchestrator, quant, report-validator, risk, roadmap-walker, scorer, screening-report-writer, search-agent, sector-screener, supply-chain, team-lead, team-lead-workflow). COPY + light adaptation (invocation preamble only).
- `scripts/*.py` (76) + `requirements.txt` + `pyproject.toml` + `uv.lock` → COPY verbatim.
- `references/`, `templates/`, `schemas/*.json` (16), `assets/report_styles.css` → COPY verbatim as package data.
- **DO NOT COPY:** `workflows/stock-analysis.js` (Claude Code Dynamic Workflow script — orchestration is re-implemented in TS), `.claude/`, `.codex/`, `.claude-plugin/`, `.codex-plugin/`, `plugin.json`, `reports/`, `reports-deepseek/`, root `stage*.md`, root `*.py` (`parse_phase2.py`, `generate_reports.py`, etc.), `run_triage.sh`, `test.py`, `rules/`, `AGENTS.md`, `CLAUDE.md`, `new-analysis.md`.

### 2.3 Adaptations: Claude Code → pi

| Concern | Claude Code (source) | pi (target) |
|---|---|---|
| Agent spawning | `Agent` tool, `subagent_type=stock-analysis:<name>` | `pi -a <name>` subprocess (`src/pi-spawn.ts`) OR in-process backend (`src/session-agent.ts`); selectable via env `STOCK_ANALYSIS_BACKEND` (mirrors `SUPER_DEV_BACKEND`) |
| Plugin paths | `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}` | Single `EXTENSION_ROOT` resolved from `package.json` dir in `src/extension.ts`; injected into every agent prompt |
| Report output | (plugin-relative) | `./reports/[RUN_ID]/` in the **run cwd** (not inside the package) |
| Orchestration | `workflows/stock-analysis.js` + hooks | `src/stages/index.ts` composed from node algebra |
| Reports language | 中文 | 中文 (preserved — rule "Report Language") |

---

## 3. Goals & Non-Goals

### Goals
- G1. Ship a valid, installable pi extension package that any pi user can `pi package add` or `pi -e` load.
- G2. Re-implement the full 5-mode / 19-stage stock-analysis orchestration in a composable TS node algebra (no external workflow engine dependency).
- G3. Preserve all source domain assets (agents, scripts, references, templates, schemas, assets) and every behavioral rule of the SKILL.md.
- G4. Provide a hermetic, fast test suite (no pi spawns, no network) that validates algebra semantics, mode dispatch, arg parsing, script invocation, and package structure.
- G5. Document the architecture, the node algebra, the per-mode pipeline diagrams, and the explicit Python-keep decision in README.md.

### Non-Goals (explicitly NOT building)
- NG1. Rewriting any Python analysis script in TypeScript.
- NG2. Replacing akshare/baostock/yfinance/etc. with Node equivalents (impossible — no equivalents exist).
- NG3. Supporting Claude Code, Codex, or any non-pi host. This is a pi extension only.
- NG4. Copying Claude/Codex plugin manifests, generated reports, or ad-hoc root scripts.
- NG5. Changing the analytical frameworks, scoring weights, agent personas, or output schemas. These are domain truth — preserved verbatim.
- NG6. Building a UI. Backend-only extension (`UI Scope: none`).
- NG7. New analytical capability. Behavior parity with the source plugin is the success bar.

---

## 4. Forcing-Question Summary (recorded for traceability)

| # | Question | Answer |
|---|---|---|
| 0 | **Who** | pi users running long-running equity-research workflows from the pi TUI/CLI on their own machine. |
| 1 | **Job** | Run the full stock-analysis pipeline (or any of its 4 sub-modes) as a single self-driving command with progress visibility, instead of manually orchestrating 22 agents across 19 stages. |
| 2 | **Why now** | The source plugin only runs under Claude Code; porting to pi makes it host-agnostic and reusable, and mirrors the already-proven pi-super-dev derivation. Not building it traps the workflow in a single host. |
| 3 | **Simplest** | One `stock_analysis` tool + one `/stock-analysis` command dispatching via `choose(mode)`; copy all domain assets verbatim; keep Python. |
| 4 | **Non-goals** | See §3 — no TS rewrite of scripts, no UI, no non-pi hosts, no new analytics. |
| 5 | **Success signal** | `pi -e .` then `/stock-analysis --mode analyze AAPL` completes all relevant stages, streams progress, writes `./reports/<RUN_ID>/` artifacts in Chinese, and exits with an honest summary; `npm test` + `npm run typecheck` pass. |

---

## 5. Design Decisions (binding)

### DD-1. Single tool + single command + `choose` node for modes
ONE tool `stock_analysis` with parameters (Type.Object):
- `mode`: enum `"pipeline" | "screen" | "analyze" | "compare" | "walk"` (default `"pipeline"`)
- `tickers`: `string[]` (optional; **required** for `analyze`/`compare`; `compare` needs 2–5)
- `theme`: `string` (optional; **required** for `walk`)
- `topIndustry`: `number` (defaults: 8 pipeline / 40 screen / 7 walk)
- `totalCompany`: `number` (default 15, pipeline only, cap 50)
- `topPrice`: `number` (default 200; 0 disables)
- `minHeadroom`: `number` (default 5, range 1–10)
- `days`: `number` (default 1, range 1–20)
- `universe`: enum `"US" | "CN" | "ALL"` (default `"US"`)
- `query`: `string` (optional natural-language; the **command** parses this into the structured params above)
- `model`, `maxAgents`: passthrough (mirrors `super_dev`)

The workflow ROOT is `choose([...])` on `state.mode`, dispatching the per-mode stage sequence from the SKILL.md `<modes>` table:
- **pipeline:** 0→1→1.5→2→3→4→4.5→[5–15 waves]→16→16.5→16.6→16.7→17→17.4→17.5→18→18.5→19
- **screen:** 0→1→1.5→2→3→4→4.5→17→17.5→18→18.5→19
- **analyze:** 0→1→1.5→[5–15 waves]→16→16.5→16.6→16.7→17→17.4→17.5→18→18.5→19
- **compare:** 0→1→1.5→[5–15 waves]→16→16.5→16.6→16.7→17→17.4→17.5→18→18.5→19 (max 5 tickers; identical valuation methodology)
- **walk:** 0→1→1.5→walk(roadmap-walker)→[5–15 on top 3–5 candidates]→16→16.5→16.6→16.7→17→17.4→17.5→18→18.5→19

### DD-2. `/stock-analysis` command: arg parsing + trigger-phrase fallback
The command parses the natural-language arg string (mirrors `/super-dev`):
1. **`--mode <name>` flag is authoritative.**
2. Positional tickers after `--mode analyze`; comma-list after `--mode compare`; positional (quoted, multi-word allowed) theme after `--mode walk`.
3. Other `--`-flags: `--top-industry`, `--total-company`, `--universe`, `--days`, `--top-price`, `--min-headroom`, `--model`, `--max-agents`.
4. **Fallback** (no `--mode`): trigger-phrase detection per SKILL.md `<triggers>` (e.g., "find best stocks"→pipeline, "screen sectors"→screen, "deep dive TICKER"→analyze, "T1 vs T2"→compare, "walk the chain for X"→walk).
5. Default → `pipeline`.
6. Dispatch via `pi.sendUserMessage` invoking the `stock_analysis` tool (same pattern as `/super-dev`).

### DD-3. Python scripts — KEEP, do NOT rewrite
- **Rationale:** 76 scripts depend on akshare + baostock (China A-share data — **no Node.js equivalent exists**), yfinance, scipy, statsmodels, arch (GARCH), pandas-ta, polars, praw (Reddit), pytrends (Google Trends), tickflow, curl_cffi. Rewriting = hundreds of hours, zero functional gain, real capability loss. The SKILL.md already mandates `uv run python ${PLUGIN_ROOT}/scripts/<script>.py`. This is the SAME boundary pi-super-dev drew.
- **Implementation:** copy `scripts/`, `scripts/requirements.txt`, `pyproject.toml`, `uv.lock` into the package. Add `src/scripts.ts`: `runScript(name, args, {cwd, root})` → shells out to `uv run python ${root}/scripts/<name>.py …` with timeout + structured stdout/stderr capture + JSON result parsing. `EXTENSION_ROOT` (dir of `package.json`) replaces `${CLAUDE_PLUGIN_ROOT}` everywhere; resolved in `src/extension.ts` and injected into every agent prompt (satisfies SKILL.md constraint "Pass PLUGIN_ROOT").

### DD-4. Control-flow mapping (SKILL.md → node algebra)
| Stage(s) | Node construct | Notes |
|---|---|---|
| 0 Setup | `task(setupStage)` | Detect mode; normalize A-share tickers (600519→.SH, 贵州茅台→akshare lookup, suffixed pass-through); create `RUN_ID` (YYYYMMDDHHmm **LOCAL** time); `mkdir reports/[RUN_ID]/`; init `tracking.json`. **FATAL on failure.** |
| 1, 1.5 | `task(dataCollector)` + `gate(reportValidator, attempts:4, feedbackKey:"sharedData")` | Data Validation is the first gate. |
| 2, 3, 4 | wrapped in `branch(modeIsPipelineOrScreen, …)` | Stage 2: `parallel` in 3 batches of ~54 (via `map`). Stage 3: parallel waves max 4. Stage 4: dual-channel FCF + cyclical adjustment; price/headroom/universe filters applied HERE ONLY. |
| 4.5 | `gate(reportValidator, …)` | Screening Validation. |
| 5–15 (per-company) | `map({over: state.companies, as:"company", concurrency:4})` | Each body = company-orchestrator sequence implementing the 4-wave DAG: **w1** [5,7,9,13] parallel; **w2** [6,8,10,14] parallel (6←5, 8←7, 10←5+7, 14←13); **w3** [11,12] parallel (←10); **w4** [15] (←all). Each analyst `task` wrapped in `retry({attempts:10})` (retry-on-null rule). |
| 15 (A-share) | `branch(tickerIsAsh, …)` inside company body | Mandatory for `.SH`/`.SZ`; skip otherwise. |
| walk stage | `branch(modeIsWalk, task(roadmapWalker))` | Replaces Stages 2–4; then top 3–5 candidates flow into 5–15. |
| 16 | `task(scorer)` | Deterministic `compute_scores.py` + `cross_check.py` + `calibrate_conviction.py` via `runScript`. |
| 16.5 | `gate(reportValidator)` | Score Validation. |
| 16.6 | `parallel`/`map` of 3 perspective-diverse skeptics per top-5 pick | Adversarial Verify; survives if ≥2/3 do NOT refute. |
| 16.7 | `parallel` of 4 framework lenses (Buffett/Lynch/Marks/Druckenmiller) | Judge Panel. |
| 17 | `branch` on mode (screening/company/comparison/walk reports) | All in 中文. |
| 17.4 | `map` one critic per report | Completeness Critic. |
| 17.5 | `gate` invoking `validate_report.py` (8 gates) via `runScript` | Report Validation. |
| 18 | `task(equityReportWriter)` grouping by position type | Best Picks. |
| 18.5 | `gate(reportValidator)` | Best Picks Validation. |
| 19 | `task`, always last | Cleanup; delete intermediate files. |
| **ROOT** | `choose([...])` on `state.mode` inside a tolerant `sequence`/`tryCatch` | Best-effort; failed non-setup stage logged, not fatal. |

---

## 6. Acceptance Criteria

> Numbered AC-XX. Each must be independently verifiable. A stage is DONE only when every AC it touches has evidence.

### Package & manifest
- **AC-01.** `/home/jenningsl/development/personal/pi-finance` is a valid pi extension npm package: `package.json` with `name` resolved per OQ-1 (`@jenningsloy318/pi-stock-analysis` recommended for consistency with `pi-super-dev`), `"pi": { "extensions": ["./src/extension.ts"], "skills": ["./skills/stock-analysis"] }`, `peerDependencies` on `@earendil-works/pi-coding-agent` + `typebox`, `"type": "module"`, `"engines": { "node": ">=22.19.0" }`, and `scripts` (`build`=`tsc`, `typecheck`=`tsc --noEmit`, `test`=`vitest run`).
- **AC-02.** `package.json` `files` array includes `src`, `agents`, `skills`, `scripts`, `references`, `templates`, `schemas`, `assets`, `README.md`, `LICENSE`, `CHANGELOG.md`. `exports` exposes `./extension`, `./nodes`, `./workflow`, `./stages`, `./package.json`.
- **AC-03.** Repo-root files present: `tsconfig.json` (`target`/`module`/`moduleResolution` compatible with pi-super-dev), `vitest.config.ts`, `.gitignore` (excludes `node_modules/`, `reports/`, `.stock-analysis-logs/`), `LICENSE` (MIT), `CHANGELOG.md`, `README.md`.

### Tool & command registration (src/extension.ts)
- **AC-04.** `src/extension.ts` registers a pi tool named `stock_analysis` with exactly the parameters listed in DD-1 (mode, tickers, theme, topIndustry, totalCompany, topPrice, minHeadroom, days, universe, query, model, maxAgents), with input validation (compare → 2–5 tickers; analyze → ≥1 ticker; walk → non-empty theme; ranges enforced).
- **AC-05.** `src/extension.ts` registers a pi command `/stock-analysis` implementing the arg parser of DD-2: `--mode` authoritative; positional/comma-list/quoted-theme extraction; remaining `--`-flags; trigger-phrase fallback; default `pipeline`; dispatch via `pi.sendUserMessage` to the `stock_analysis` tool.
- **AC-06.** The extension streams progress (per-stage start/complete/skip + per-company wave progress) with a rolling-tail live display, writes a run log to `.stock-analysis-logs/<RUN_ID>.log`, and returns an honest `success | partial | failed` summary naming completed/skipped/failed stages — structurally mirroring `pi-super-dev/src/extension.ts`.

### Control-flow algebra (src/nodes.ts, src/workflow.ts, src/types.ts)
- **AC-07.** `src/nodes.ts` exports a self-contained node algebra with **at minimum**: `task`, `sequence`, `branch`, `choose`, `parallel`, `loop`, `retry`, `gate`, `map`, `wait`, `tryCatch`, `noop`, `gateValidator`. Ported/adapted from pi-super-dev; **must NOT** depend on `@agwab/pi-workflow` or any external workflow engine.
- **AC-08.** `src/workflow.ts` provides the self-evaluating runner (`await root.run(state, ctx)`) ported from pi-super-dev.
- **AC-09.** `src/types.ts` defines stock-analysis domain shapes: `StockAnalysisState` (with `mode`, `runId`, `tickers`, `theme`, `topIndustry`, `totalCompany`, `topPrice`, `minHeadroom`, `days`, `universe`, `companies`, `sharedData`, `reports`, `tracking`), `Node`, `Stage`, `StageContext`, `RunSummary`, `AgentResult`. (Super-dev's `SetupControl`/`Classification` shapes are removed/replaced.)

### Pipeline composition (src/stages/)
- **AC-10.** `src/stages/index.ts` composes the 5-mode, 19-stage pipeline using `choose()` for mode dispatch, `branch()` for conditional stages (A-share Stage 15, screening-only Stages 2–4, walk replacement), `gate()` for the **five** validation stages (1.5, 4.5, 16.5, 17.5, 18.5), `map()`/`parallel()` for per-company waves (max-4 concurrency) + adversarial verify (3 skeptics per top-5 pick) + judge panel (4 lenses), and `retry({attempts:10})` wrapping every analyst task (retry-on-null rule). Per-mode stage sequences match DD-1 exactly.
- **AC-11.** Stage 0 (`setupStage`) is **fatal**: failure aborts the run with a clear message. All other stages are tolerant: failure is logged to `tracking.json` and the run continues with partial data (parity with super-dev + SKILL.md `<orchestration-model>` retry policy).

### Domain assets (copied verbatim unless noted)
- **AC-12.** All specialist agent definitions copied into `agents/*.md` and **lightly adapted** (invocation preamble only: replace Claude Code `Agent`/`subagent_type=…` notes with pi invocation notes — spawned as `pi -a <agent>` subprocess; scripts at `${EXTENSION_ROOT}/scripts`). All analytical content, frameworks, output schemas, and personas preserved unchanged.
- **AC-13.** `scripts/*.py` (76 files), `scripts/requirements.txt`, `pyproject.toml`, `uv.lock` copied **verbatim** (byte-identical content).
- **AC-14.** `references/` (gics_taxonomy, data_source_matrix, frameworks_*, pitfalls/*, serenity/*, scoring_calibration, sector_metrics, microstructure-framework, institutional_odd, international_markets), `templates/` (equity-report.md, screening-report.md, ecosystem-health.md.j2, industry-trajectory.md.j2, company-status.json, workflow-tracking.json), `schemas/*.json` (16), `assets/report_styles.css` copied **verbatim**.
- **AC-15.** **Excluded** (verified absent): `workflows/`, `.claude/`, `.codex/`, `.claude-plugin/`, `.codex-plugin/`, `plugin.json`, `reports/`, `reports-deepseek/`, root `stage*.md`, root `*.py` (`parse_phase2.py` etc.), `run_triage.sh`, `test.py`, `rules/`, `AGENTS.md`, `CLAUDE.md`, `new-analysis.md`, `docs/` (source plugin's own docs).

### Python invocation helper (src/scripts.ts)
- **AC-16.** `src/scripts.ts` exports `runScript(name: string, args: string[], opts: { cwd?: string; root: string; timeoutMs?: number })` that shells out to `uv run python ${root}/scripts/${name}.py …`, captures stdout/stderr, applies a timeout, and parses structured JSON results when present. Errors are returned as a structured `{ ok: false, stderr, exitCode }` value (not thrown) so tolerant stages can continue.

### Supporting modules (ported from pi-super-dev)
- **AC-17.** `src/agents.ts` (loads `agents/<name>.md`), `src/pi-spawn.ts` (spawns `pi -a <agent>` subprocess; backend selectable via env `STOCK_ANALYSIS_BACKEND` mirroring `SUPER_DEV_BACKEND`), `src/session-agent.ts` (in-process backend), `src/control.ts` (tolerant `<control>` JSON extractor), `src/helpers.ts` (deterministic helpers, incl. A-share ticker normalization), `src/prompts.ts` (prompt builders that inject `EXTENSION_ROOT` + run state into every agent prompt) are present and adapted to stock-analysis domain shapes.

### Skill pointer
- **AC-18.** `skills/stock-analysis/SKILL.md` is a **SHORT** pi skill pointer (comparable in length/style to `pi-super-dev/skills/super-dev/SKILL.md`) — NOT the giant Claude skill. It describes the `/stock-analysis` command, the 5 modes, the keep-Python contract, and points to README for full architecture. The orchestration now lives in TS.

### Tests (hermetic)
- **AC-19.** `tests/*.test.ts` is a hermetic vitest suite (**no pi subprocess spawns, no network calls**) covering at minimum:
  - node-algebra semantics (task/sequence/branch/choose/parallel/map/retry/gate/tryCatch) — port the spirit of pi-super-dev's `nodes.test.ts`/`workflow.test.ts`;
  - mode-dispatch `choose` (each of the 5 modes selects the correct stage sequence per DD-1);
  - `/stock-analysis` arg parser (all flag forms + trigger-phrase fallback + A-share ticker normalization);
  - `runScript` wrapper with `uv`/`python` invocation **mocked** (asserts command shape + timeout + structured-error path);
  - `tests/structure.test.ts` validating package layout, `package.json` `pi` config, `exports`, and presence of required directories/files (mirrors pi-super-dev's `structure.test.ts`).
- **AC-20.** `npm run typecheck` exits 0 and `npm test` exits 0 on a clean install.

### Documentation
- **AC-21.** `README.md` documents: install (`pi package add` / `pi -e .`), usage (`/stock-analysis` examples for **each** of the 5 modes), the node-algebra reference table, the per-mode pipeline diagram (ascii or mermaid), the **explicit** decision to keep Python scripts (with the akshare/baostock/no-JS-equivalent rationale), and how agents invoke scripts via `uv run python` through `runScript`.

### Behavioral parity (rules preserved from SKILL.md)
- **AC-22.** Reports are written in **中文 (Chinese)** throughout (rule "Report Language").
- **AC-23.** Price / headroom / universe filters are applied at **Stage 4 only** (not earlier).
- **AC-24.** A-share analysis (Stage 15) is **mandatory** for tickers ending `.SH`/`.SZ` and skipped for all others.
- **AC-25.** Per-company waves run with **max-4 concurrency**; retry-on-null up to **10 attempts**; shared data fetched **once** at Stage 1 and reused; the pipeline **never pauses** for user input mid-run; context-eviction discipline is applied between waves (agents receive only their stage's required context).

---

## 7. Non-Functional Requirements

### NFR-1. Performance
- N1.1 Workflow control-flow overhead (node traversal, state threading) adds negligible cost vs. agent execution; the bottleneck is always agent LLM calls + Python data fetches.
- N1.2 `runScript` default timeout is generous (configurable; default e.g. 10 min) but bounded; a hung script does not stall the run indefinitely.
- N1.3 Per-company concurrency capped at 4 (rule); cross-company scheduling is an async pool that refills on completion (not synchronous batches).

### NFR-2. Reliability / tolerance
- N2.1 Best-effort: any non-setup stage failure is logged, not fatal. The run always reaches Stage 19 (Cleanup) unless Stage 0 fails.
- N2.2 `retry({attempts:10})` on every agent spawn swallows transient null/empty results; exhausted retries mark the stage failed (logged) and continue.
- N2.3 Gates (1.5/4.5/16.5/17.5/18.5) block their immediate downstream stages on failure but do not abort the whole run; failed gates are surfaced in the final summary.

### NFR-3. Reproducibility / determinism
- N3.1 `RUN_ID` = `YYYYMMDDHHmm` in **LOCAL** time (not UTC) — matches SKILL.md.
- N3.2 Scoring (`compute_scores.py`), cross-check (`cross_check.py`), conviction calibration (`calibrate_conviction.py`), report validation (`validate_report.py`), and bottleneck asymmetry (`score_bottleneck_asymmetry.py`) are deterministic Python; the TS layer never re-implements their math.
- N3.3 `EXTENSION_ROOT` is resolved once in `src/extension.ts` (from the loaded module URL / `package.json` dir) and threaded through every prompt; no hardcoded absolute paths.

### NFR-4. Portability
- N4.1 No dependency on `@agab/pi-workflow`, LangChain, or any external workflow/orchestration engine. The node algebra is fully self-contained in `src/nodes.ts`.
- N4.2 Backend selectable via env (`STOCK_ANALYSIS_BACKEND=subprocess|session`) mirroring `SUPER_DEV_BACKEND`; default `subprocess` for isolation.
- N4.3 Requires Node `>=22.19.0` and `uv` on PATH (documented prerequisite; the extension does not bundle `uv`).

### NFR-5. Testability
- N5.1 All tests hermetic: no `pi` subprocess spawns, no network, no `uv`/`python` execution (mocked). `npm test` runs in seconds.
- N5.2 Pure functions (ticker normalization, arg parser, control JSON extractor, node algebra) are unit-tested independently of any agent/backend.

### NFR-6. Maintainability
- N6.1 Code style, file layout, and naming conventions mirror `pi-super-dev` (a reviewer familiar with one can navigate the other).
- N6.2 Domain assets (agents/scripts/references/templates/schemas) are kept in source-tree directories matching the source plugin, so future upstream syncs are mechanical `cp`.

### NFR-7. Security / safety
- N7.1 `runScript` only executes scripts under `${EXTENSION_ROOT}/scripts/` (validated path — no arbitrary `name` traversal).
- N7.2 No secrets handled by the TS layer; agents/scripts read credentials from the user's environment (`~/.env`, akshare/baostock tokens, etc.) as today.
- N7.3 Reports are written under the **run cwd** `./reports/<RUN_ID>/`, never inside the installed package directory.

---

## 8. Open Questions

- **OQ-1 (blocking-ish).** Package name: the task offers `@jenningsloy318/pi-stock-analysis` **or** `pi-finance`. **Recommendation:** `@jenningsloy318/pi-stock-analysis` — matches the `pi-super-dev` naming convention (`pi-<feature>`), is unambiguous about contents, and leaves `pi-finance` available as a future umbrella for additional finance extensions. The repo directory stays `pi-finance`. *Needs owner confirmation.*
- **OQ-2.** Agent count discrepancy: the task says "21 specialists" but the source `agents/` directory contains **22** files (includes `market-daily-orchestrator.md`, `search-agent.md`, `team-lead-workflow.md`). **Recommendation:** copy **all 22** verbatim; unused-in-pipeline agents are harmless and may be invoked ad hoc by the team-lead. Confirm no agent should be intentionally dropped.
- **OQ-3.** `market-daily-orchestrator` and `search-agent` are present in source but not referenced in the SKILL.md stage table. **Recommendation:** copy them (cheap), but do **not** wire them into the 19-stage pipeline unless the owner confirms a role (e.g., a daily-briefing mode). Track as a possible future mode.
- **OQ-4 (deferred to implementation).** Backend default: `subprocess` (isolated, matches super-dev) vs `session` (faster, in-process). **Recommendation:** default `subprocess`, allow `STOCK_ANALYSIS_BACKEND=session` override — mirrors super-dev exactly. Confirm acceptable.
- **OQ-5.** Whether to vendor `uv` / pin a Python version in `pyproject.toml` for reproducibility, or rely on the user's installed `uv`. **Recommendation:** rely on user's `uv` (document prerequisite); the copied `pyproject.toml` + `uv.lock` already pin the Python deps. Confirm.
- **OQ-6.** README diagrams: ascii vs mermaid. **Recommendation:** both — ascii in README for terminal viewers, mermaid in `docs/` for rendered docs. Low-stakes; implementer's call.
- **OQ-7.** Whether `/stock-analysis` should also accept a fully-structured JSON arg (power-user escape hatch) in addition to the NL parser. **Recommendation:** yes — if the parsed `query` is itself valid JSON matching the tool params, parse it directly. Cheap, useful for scripting. Confirm.

---

## 9. Assumptions (surfaced, non-blocking)

- A1. `~/jenningsloy318/pi-super-dev` and `~/jenningsloy318/stock-analysis-plugin` are present and readable at implementation time (verified during requirements gathering).
- A2. The user has `uv` and Python ≥3.11 available on PATH (prerequisite for running any analysis; documented in README).
- A3. The 76 Python scripts are correct and functional as-is in the source plugin (the TS layer does not fix Python bugs — it only invokes them).
- A4. pi's extension API (`pi.tool`, `pi.command`, `pi.sendUserMessage`, progress streaming, run-log writing) is stable and matches what `pi-super-dev/src/extension.ts` already uses.
- A5. The `typebox` peer dependency is the same one pi exposes (matches pi-super-dev's peerDeps).

---

## 10. Summary

This requirements document specifies a **port/refactor**, not greenfield work: re-implement the orchestration layer of an existing, proven Claude Code plugin (`stock-analysis-plugin`) as a pi extension package, copying all domain assets verbatim and preserving every behavioral rule. The two genuinely open design questions in the user's request — *how to handle multiple execution modes* and *whether to rewrite Python in TypeScript* — are resolved by DD-1 (`choose` node + single tool/command) and DD-3 (keep Python; thin `runScript` shell-out helper), both of which directly mirror the precedent set by `pi-super-dev`. The 25 acceptance criteria + 7 NFR categories are independently verifiable, grounded in the real file layout of both reference repos, and bounded by an explicit non-goals list. The single remaining owner-level decision is the package name (OQ-1); everything else can proceed on the stated recommendations.
