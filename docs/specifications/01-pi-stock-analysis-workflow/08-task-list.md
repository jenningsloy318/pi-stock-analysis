# Task List — pi-stock-analysis (pi Extension)

**Feature:** `@jenningsloy318/pi-stock-analysis` — pi control-flow workflow extension
**Task type:** refactor / port
**Author:** spec-writer
**Status:** ready for execution
**Companion docs:** `06-specification.md`, `07-implementation-plan.md`

---

## 0. Conventions

- **Task IDs:** `T<phase>-<nn>` (e.g. `T1-03`). Tasks are grouped by phase; execute in ID order within a phase.
- **`action`:** `create` | `modify` | `copy` | `copy+edit` | `delete` | `verify`.
- **`files`:** repo-relative paths. `→` denotes target. Absolute source paths use `~/jenningsloy318/…`.
- **`domain`:** matches `07-implementation-plan.md` (`manifest`/`assets`/`algebra`/`support`/`pipeline`/`entrypoint`/`docs`/`test`).
- **`ac`:** acceptance-criterion coverage. **`scenario`:** BDD scenario coverage.
- **`effort`:** S (<30m) / M (30m–2h) / L (2h–1d).
- **File inventories** are complete: every file created, modified, copied, or deleted is listed. No "etc."

**Counts to honor (single-implementation guarantee):** 22 agents · 76 scripts · 16 schemas · package name `@jenningsloy318/pi-stock-analysis` · tool `stock_analysis` · command `/stock-analysis` · env `STOCK_ANALYSIS_BACKEND` · log dir `.stock-analysis-logs/`.

---

## PHASE 1 — Package Scaffold & Config  (`domain: manifest`)

| ID | action | files | description | ac | effort |
|---|---|---|---|---|---|
| T1-01 | create | `package.json` | Name `@jenningsloy318/pi-stock-analysis`, `type:module`, `engines.node>=22.19.0`, `keywords` incl. `pi-package`, `pi.extensions:["./src/extension.ts"]`, `pi.skills:["./skills/stock-analysis"]`, `exports` (./extension, ./nodes, ./workflow, ./stages, ./package.json), `files` (src, agents, skills, scripts, references, templates, schemas, assets, pyproject.toml, uv.lock, README.md, LICENSE, CHANGELOG.md), `scripts` (build=tsc, typecheck=tsc --noEmit, test=vitest run), `peerDependencies` (@earendil-works/pi-coding-agent, typebox), `devDependencies` (@types/node, typebox, typescript, vitest). **No `dependencies`.** | AC-01, AC-02 | S |
| T1-02 | create | `tsconfig.json` | Mirror pi-super-dev: `strict:true`, ESM, `.ts`-suffix imports, `target`/`module`/`moduleResolution` compatible with pi loader; exclude `node_modules`, `reports`. | AC-03 | S |
| T1-03 | create | `vitest.config.ts` | `environment:"node"`, `include:["tests/**/*.test.ts"]`, no network setup. | AC-03, AC-19 | S |
| T1-04 | create | `.gitignore` | Exclude `node_modules/`, `reports/`, `.stock-analysis-logs/`, `*.tsbuildinfo`, `.vitest-cache/`. | AC-03 | S |
| T1-05 | create | `LICENSE` | MIT (match pi-super-dev). | AC-03 | S |
| T1-06 | create | `CHANGELOG.md` | Keep-a-Changelog; `## [0.1.0] - Unreleased` with port summary. | AC-03 | S |
| T1-07 | create | `src/extension.ts` (stub) | Empty `export default function activate(){}` so `exports` resolves; real impl in P6. | AC-01 | S |
| T1-08 | create | `src/nodes.ts`, `src/workflow.ts`, `src/types.ts`, `src/control.ts`, `src/helpers.ts`, `src/agents.ts`, `src/pi-spawn.ts`, `src/session-agent.ts`, `src/prompts.ts`, `src/scripts.ts`, `src/stages/index.ts` (stubs) | Empty/typed-stub modules so `exports` + `tsc --noEmit` pass. Real impl in P3–P6. | AC-01, AC-02 | S |
| T1-09 | create | `tests/structure.test.ts` | Assert: `type==="module"`, `engines.node>=22.19`, `keywords` has `pi-package`, `dependencies` undefined, no `@agwab/pi-workflow` in resolved tree, `pi.extensions[0]==="./src/extension.ts"`, `pi.skills[0]==="./skills/stock-analysis"`, `exports` keys present, `files` includes the 8 dirs + pyproject.toml + uv.lock. | AC-01, AC-02, AC-03 | M |
| T1-10 | verify | `npm install && npm run typecheck && npm test` | Exit 0 / 0 / 0. **Phase 1 exit gate.** | AC-01, AC-02, AC-03 | S |

---

## PHASE 2 — Domain Asset Copy (Verbatim)  (`domain: assets`)

> Source: `~/jenningsloy318/stock-analysis-plugin/`. Target: repo root. All copies are **byte-identical** unless marked `copy+edit`.

### 2a. Scripts + Python manifests

| ID | action | files | description | ac | effort |
|---|---|---|---|---|---|
| T2-01 | copy | `scripts/*.py` (76 files) → `scripts/*.py` | Verbatim. Preserve every script. | AC-13 | M |
| T2-02 | copy | `scripts/requirements.txt` → `scripts/requirements.txt` | Verbatim. | AC-13 | S |
| T2-03 | copy | `pyproject.toml` → `pyproject.toml` | Verbatim (akshare/baostock/yfinance/scipy/statsmodels/arch/pandas-ta/polars/praw/pytrends/tickflow/curl_cffi pins). | AC-13 | S |
| T2-04 | copy | `uv.lock` → `uv.lock` | Verbatim (reproducibility — OQ-5). | AC-13 | S |

### 2b. Reference data / templates / schemas / assets

| ID | action | files | description | ac | effort |
|---|---|---|---|---|---|
| T2-05 | copy | `references/` → `references/` | Verbatim (gics_taxonomy, data_source_matrix, frameworks_*, pitfalls/, serenity/, scoring_calibration, sector_metrics, microstructure-framework, institutional_odd, international_markets). | AC-14 | S |
| T2-06 | copy | `templates/` → `templates/` | Verbatim (equity-report.md, screening-report.md, ecosystem-health.md.j2, industry-trajectory.md.j2, company-status.json, workflow-tracking.json). | AC-14 | S |
| T2-07 | copy | `schemas/*.json` (16) → `schemas/*.json` | Verbatim. | AC-14 | S |
| T2-08 | copy | `assets/report_styles.css` → `assets/report_styles.css` | Verbatim. | AC-14 | S |

### 2c. Agents (22 files, preamble-only edit)

| ID | action | files | description | ac | effort |
|---|---|---|---|---|---|
| T2-09 | copy+edit | `agents/team-lead.md` | Edit ONLY invocation preamble: Claude `Agent`/`subagent_type` → `pi -a <name>` subprocess + `${EXTENSION_ROOT}/scripts` for deterministic calcs. Replace `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` → `${EXTENSION_ROOT}`. Preserve all analytical content, frameworks, output schemas, persona. | AC-12 | S |
| T2-10 | copy+edit | `agents/data-collector.md` | Same preamble edit as T2-09. | AC-12 | S |
| T2-11 | copy+edit | `agents/sector-screener.md` | Same preamble edit. | AC-12 | S |
| T2-12 | copy+edit | `agents/company-screener.md` | Same preamble edit. | AC-12 | S |
| T2-13 | copy+edit | `agents/fundamental-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-14 | copy+edit | `agents/industry-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-15 | copy+edit | `agents/supply-chain-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-16 | copy+edit | `agents/macro-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-17 | copy+edit | `agents/quant-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-18 | copy+edit | `agents/risk-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-19 | copy+edit | `agents/alt-data-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-20 | copy+edit | `agents/catalyst-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-21 | copy+edit | `agents/china-market-analyst.md` | Same preamble edit. | AC-12 | S |
| T2-22 | copy+edit | `agents/roadmap-walker.md` | Same preamble edit. | AC-12 | S |
| T2-23 | copy+edit | `agents/scorer.md` | Same preamble edit. | AC-12 | S |
| T2-24 | copy+edit | `agents/equity-report-writer.md` | Same preamble edit. | AC-12 | S |
| T2-25 | copy+edit | `agents/screening-report-writer.md` | Same preamble edit. | AC-12 | S |
| T2-26 | copy+edit | `agents/report-validator.md` | Same preamble edit. | AC-12 | S |
| T2-27 | copy+edit | `agents/company-orchestrator.md` | Same preamble edit. | AC-12 | S |
| T2-28 | copy+edit | `agents/market-daily-orchestrator.md` | Same preamble edit. Copied but NOT wired into 19-stage pipeline (OQ-3). | AC-12 | S |
| T2-29 | copy+edit | `agents/search-agent.md` | Same preamble edit. Copied but NOT wired (OQ-3). | AC-12 | S |
| T2-30 | copy+edit | `agents/team-lead-workflow.md` | Same preamble edit. Retained as reference; orchestration superseded by TS pipeline (§2.6). | AC-12 | S |

### 2d. Verification + structure-test extension

| ID | action | files | description | ac | scenario | effort |
|---|---|---|---|---|---|---|
| T2-31 | verify | `agents/` | `grep -r CLAUDE_PLUGIN agents/` returns nothing (ISS-05). | AC-12 | — | S |
| T2-32 | modify | `tests/structure.test.ts` | Add assertions: `>=22 agents` in `agents/`, `76 .py` in `scripts/`, `16 .json` in `schemas/`, presence of `references/`, `templates/equity-report.md`, `templates/screening-report.md`, `assets/report_styles.css`, `pyproject.toml`, `uv.lock`. | AC-12,13,14 | 026,027,028 | M |
| T2-33 | modify | `tests/structure.test.ts` | Add ABSENCE assertions: `workflows/`, `.claude/`, `.codex/`, `.claude-plugin/`, `.codex-plugin/`, `plugin.json`, `reports/`, `reports-deepseek/`, root `stage*.md`, root `parse_phase2.py`/`generate_reports.py`/other root `*.py`, `run_triage.sh`, `test.py`, `rules/`, source `AGENTS.md`/`CLAUDE.md`/`new-analysis.md`. | AC-15 | 029 | M |
| T2-34 | verify | `npm test` | Passes (phases 1–2 tests). **Phase 2 exit gate.** | AC-12,13,14,15 | — | S |

---

## PHASE 3 — Node Algebra + Domain Types + Runner  (`domain: algebra`)

| ID | action | files | description | ac | scenario | effort |
|---|---|---|---|---|---|---|
| T3-01 | modify | `src/types.ts` | Define `StockAnalysisState` (§7.1: mode, runId, tickers, theme, topIndustry, totalCompany, topPrice, minHeadroom, days, universe, companies, sharedData, reports, tracking, __feedback, backend, model, maxAgents, reportsDir, company, scoring, adversarial, judgePanel, bestPicks, industries, subIndustries). Define `Company`, `SharedData`, `ScoringResult`, `ReportArtifact`, `BestPick`, `Tracking`, `StageFailure`, `RunSummary`, `Stage`, `StageContext`, `Node`, `NodeResult`, `AgentResult`, `HelperCall/Result`, `ScriptCall/Result`, `RunStatus`, `ProgressSink`. Remove super-dev `SetupControl`/`Classification`. | AC-09 | 017 | M |
| T3-02 | modify | `src/nodes.ts` | Port algebra from pi-super-dev (PAT-004): `task(stage)` (fatal rethrow), `sequence(children,{tolerant})`, `branch(pred,{yes,no?})`, `choose(cases,otherwise?)`, `parallel(branches,{concurrency?})`, `loop({while,do},body)`, `retry({attempts,until?,backoffMs?},node)`, `gate({validate,attempts,feedbackKey},node)` (never throws — stores errors under `state.__feedback[key]`, returns `{status:"failed"}`), `map({over,as,concurrency,failFast?},body)`, `wait({ms})`, `waitForEvent(name)`, `tryCatch(body,{onCaught?})`, `noop()`, `writerTask(stage)`, `helperTask(call)`, `gateValidator(helperName,sourceKey,stateKey)`. **No `@agwab/pi-workflow`.** | AC-07 | 014,015 | L |
| T3-03 | modify | `src/workflow.ts` | Port `makeContext(opts)` building `StageContext` (agent/helper/script/parallel/budget/log/events/signal/extensionRoot) and `runWorkflow(root,state,opts)` (`await root.run(state,ctx)`, per-node timing → `state.tracking`, summary derivation). Backend switch reads `STOCK_ANALYSIS_BACKEND` (default `subprocess`). Gate feedback injection in `agent()`. | AC-08 | 016 | M |
| T3-04 | modify | `src/control.ts` | Port `extractControl(raw)` (tolerant `<control>...</control>` JSON), `findLastJsonObject(text)`, `extractControlKeys(raw,keys[])`. | AC-17 | — | S |
| T3-05 | modify | `src/helpers.ts` | `runHelper(call)` dispatcher. Pure helpers: `normalizeAshTicker(input)` (6-digit→`.SH`/`.SZ` by prefix; CJK name→akshare lookup via runScript best-effort non-fatal; suffixed/alphabetic pass-through), `isAshTicker(ticker)` (`/.(SH\|SZ)$/`), `generateRunId()` (`YYYYMMDDHHmm` LOCAL — NFR-3.1). | AC-09, AC-24 | 044,045 | M |
| T3-06 | create | `tests/nodes.test.ts` | Algebra semantics with a fake `StageContext` (no spawns): task stores value; sequence tolerant converts throw→failed; branch yes/no; choose first-match; parallel concurrency cap; map over collection with concurrency; retry attempts + until predicate; gate stores feedback + returns failed (never throws); tryCatch isolates. | AC-07 | 014,036 | M |
| T3-07 | create | `tests/workflow.test.ts` | Small composed tree evaluates to completion; state threaded between nodes; `RunSummary` returned. | AC-08 | 016 | S |
| T3-08 | create | `tests/control.test.ts` | `<control>` extraction happy path, `findLastJsonObject` last-JSON, malformed-input tolerance (no throw). | AC-17 | — | S |
| T3-09 | create | `tests/ticker-normalize.test.ts` | `normalizeAshTicker`: `600519`→`600519.SH`, `000858`→`000858.SZ`, `600519.SH` pass-through, `AAPL` pass-through, CJK name path (mocked lookup). `isAshTicker` true/false cases. | AC-09, AC-24 | 044,045 | S |
| T3-10 | verify | `npm run typecheck && npm test` | Exit 0 / 0. **Phase 3 exit gate.** | AC-07,08,09 | 014–017 | S |

---

## PHASE 4 — Supporting Modules + Python Bridge  (`domain: support`)

| ID | action | files | description | ac | scenario | effort |
|---|---|---|---|---|---|---|
| T4-01 | modify | `src/agents.ts` | Port `loadAgent(name)` from pi-super-dev (PAT-011): read `agents/<name>.md`, parse YAML frontmatter (`name, description, model, kind, tools, max_turns, timeout_mins`) + body. Return definition for `ctx.agent()`. | AC-17 | 033 | S |
| T4-02 | modify | `src/pi-spawn.ts` | Port `spawnAgent({id,agent,prompt,controlKeys})` → `pi -a <agent>` subprocess (stdin prompt, stdout capture, `extractControlKeys` for structured output). `abbreviatePath` for logs. `STOCK_ANALYSIS_BACKEND=subprocess` default (OPT-C1). | AC-17 | 033 | M |
| T4-03 | modify | `src/session-agent.ts` | Port `createAgentSession(...)` in-process backend (opt-in via `STOCK_ANALYSIS_BACKEND=session`). | AC-17 | 033 | M |
| T4-04 | modify | `src/prompts.ts` | Prompt builders injecting `EXTENSION_ROOT` + per-stage state slice + `state.__feedback[feedbackKey]`. **Context-eviction discipline:** each builder includes ONLY its stage's required keys (Stage-7 prompt never receives Stage-9 outputs). | AC-17, AC-25 | 033,050 | M |
| T4-05 | modify | `src/scripts.ts` | Implement `runScript(name,args,{cwd,root,timeoutMs,sink})` (§9.1): validate `name` vs `^[A-Za-z0-9_-]+$` (NFR-7.1); resolve `${root}/scripts/${name}.py`; `existsSync` check; spawn `uv run python <path> …args`; capture stdout/stderr; stream stderr lines to `sink?.log`; enforce `timeoutMs ?? 600000`; on timeout kill + return `{ok:false,error:"timeout"}`; parse last JSON via `findLastJsonObject`; **never throw** — all errors → structured `{ok:false,error,exitCode,stderr}`. | AC-16 | 030,031,032 | M |
| T4-06 | modify | `src/helpers.ts` | Wire script-backed helper names in `runHelper`: `compute_scores`, `cross_check`, `calibrate_conviction`, `validate_report`, `score_bottleneck_asymmetry`, `compute_tam_adj_peg`, `compute_bayesian_growth` → call `runScript(name,args,{root})`. | AC-16 | 030 | S |
| T4-07 | create | `tests/scripts.test.ts` | `child_process.spawn` **mocked**: asserts argv is `["run","python","<root>/scripts/<name>.py",...args]`; cwd passed; timeout kills child + returns `{ok:false,error:"timeout"}`; non-zero exit returns `{ok:false,exitCode,stderr}`; stdout JSON parsed into `.json`; path-traversal name (`../evil`) rejected pre-spawn; missing script returns `{ok:false,error:"script not found"}`. | AC-16 | 030,031,032 | M |
| T4-08 | verify | `npm run typecheck && npm test` | Exit 0 / 0. **Phase 4 exit gate.** | AC-16, AC-17 | 030–033 | S |

---

## PHASE 5 — Pipeline Composition (5 modes × 19 stages)  (`domain: pipeline`)

| ID | action | files | description | ac | scenario | effort |
|---|---|---|---|---|---|---|
| T5-01 | modify | `src/stages/index.ts` | Define `Stage` objects for all 19 stages (ids `stage-0-setup` … `stage-19-cleanup`). Stage 0 `fatal:true`; all others tolerant. Each `run(state,ctx)` calls `ctx.agent({...})` and/or `ctx.helper({...})`/`runScript(...)` and stores results under `state[stage.id]`. | AC-10, AC-11 | 018,023,024 | L |
| T5-02 | modify | `src/stages/index.ts` | Compose ROOT `choose([...])` on `state.mode` (§8.1): `pipelineSequence`, `screenSequence`, `analyzeSequence`, `compareSequence`, `walkSequence`; `otherwise: cleanupOnly`. | AC-10 | 018 | M |
| T5-03 | modify | `src/stages/index.ts` | Compose each per-mode `sequence([...],{tolerant:true})` per §8.2 table exactly (pipeline: 0→1→1.5→2→3→4→4.5→[map 5-15]→16→16.5→16.6→16.7→17→17.4→17.5→18→18.5→19; screen: 0→1→1.5→2→3→4→4.5→17→17.5→18→18.5→19; analyze/compare: 0→1→1.5→[map 5-15]→16→…→19; walk: 0→1→1.5→walk→[map 5-15 top 3-5]→16→…→19). | AC-10 | 018 | M |
| T5-04 | modify | `src/stages/index.ts` | Compose conditional `branch` blocks (§8.3): screening-only 2/3/4/4.5 wrapped in `branch(s=>mode==="pipeline"\|\|mode==="screen", {yes:…, no:noop()})`; walk replacement `branch(s=>mode==="walk",{yes:task(roadmapWalker),no:noop()})`. | AC-10 | 019 | M |
| T5-05 | modify | `src/stages/index.ts` | Compose per-company DAG (§8.4): `map({over:"companies",as:"company",concurrency:4}, sequence([ parallel([5,7,9,13],{concurrency:4}), parallel([6,8,10,14],{concurrency:4}), parallel([11,12],{concurrency:2}), branch(s=>!!s.company?.isAsh,{yes:task(15),no:noop()}) ]))`. Every analyst `task` wrapped in `retry({attempts:10,until:r=>r.status==="ok"&&!isEmpty(r.value)})`. Document two-dial concurrency invariant (ISS-03) in header comment. | AC-10, AC-25 | 021,022,046,047 | L |
| T5-06 | modify | `src/stages/index.ts` | Compose the 5 gates (§8.5): 1.5 `gate({validate:reportValidator,attempts:4,feedbackKey:"sharedData"}, task(stage1))`; 4.5 `feedbackKey:"screening"`; 16.5 `"scoring"`; 17.5 `gateValidator("validate_report",…)` → `runScript("validate_report",…)` (8 sub-gates, BP-02) with **non-vacuous-pass** (missing output → `failed` + stderr, ISS-02); 18.5 `"bestPicks"`. | AC-10 | 020 | M |
| T5-07 | modify | `src/stages/index.ts` | Compose 16.6 adversarial verify: `map({over:()=>top5Picks(state.scoring),as:"pick",concurrency:5}, parallel([skeptic1,skeptic2,skeptic3],{concurrency:3}))` (survives if ≥2/3 do NOT refute). Compose 16.7 judge panel: `parallel([buffett,lynch,marks,druckenmiller],{concurrency:4})`. | AC-10 | 022 | M |
| T5-08 | modify | `src/stages/index.ts` | Compose Stage 17 reports with `branch` on mode (screening/company/comparison/walk). Compose 17.4 completeness critic: `map({over:state.reports,as:"report"}, task(critic))`. Compose Stage 18 best-picks grouped by position type (core/satellite/tactical). Compose Stage 19 cleanup as always-last tolerant task (delete intermediate files). | AC-10 | 018 | M |
| T5-09 | modify | `src/stages/index.ts` | Wire behavioral rules (§8.8): Chinese reports (agent prompt preambles — already in P2 agents); price/headroom/universe filters applied ONLY inside `task(stage-4-company-screening)`; shared-data set once at Stage 1 read-only thereafter; no-pause (no user-input await); context-eviction via `prompts.ts` per-stage builders. | AC-22,23,24,25 | 042,043,048,049,050 | M |
| T5-10 | create | `tests/mode-dispatch.test.ts` | For each of 5 modes: `choose` selects the correct stage sequence (assert visited stage ids); screening stages skipped for analyze/compare/walk; walk replacement runs only in walk; A-share branch runs for `.SH`/`.SZ` company, skipped otherwise; `map` concurrency caps company-level (4) independent of inner `parallel`. Uses fake agents returning canned control JSON. | AC-10, AC-11, AC-24 | 018,019,021,024,044,045 | M |
| T5-11 | verify | `npm run typecheck && npm test` | Exit 0 / 0. **Phase 5 exit gate.** | AC-10, AC-11 | 018–024 | S |

---

## PHASE 6 — Extension Entry Point (Tool + Command)  (`domain: entrypoint`)

| ID | action | files | description | ac | scenario | effort |
|---|---|---|---|---|---|---|
| T6-01 | modify | `src/extension.ts` | Implement `resolvePackageRoot(import.meta.url)` → dir of `package.json` named `@jenningsloy318/pi-stock-analysis`. Export `EXTENSION_ROOT`. Must work for `pi -e .` AND installed package (ISS-01). | AC-17 | — | S |
| T6-02 | modify | `src/extension.ts` | Implement `default activate(pi)` → `pi.registerTool({ name:"stock_analysis", parameters: Type.Object({...all 12 params...}), async execute(toolCallId,params,signal,onUpdate){...} })`. Typebox params per §4.2. Fail-fast per-mode validation in `execute` (analyze ≥1 ticker; compare 2–5; walk non-empty theme; ranges). Build `StockAnalysisState`, `ProgressSink` (rolling tail 400, 80ms throttle), call `runWorkflow(root,state,{sink,signal,extensionRoot,model,maxAgents})`, write transcript to `.stock-analysis-logs/<RUN_ID>.log`, emit `formatSummary`. | AC-04, AC-06 | 005,006,007,011,012,013 | L |
| T6-03 | modify | `src/extension.ts` | Implement `pi.registerCommand("/stock-analysis",{handler})` calling `parseStockAnalysisArgs(args)` then `pi.sendUserMessage(\`Use the stock_analysis tool with ${JSON.stringify(parsed)}\`)` (PAT-001). | AC-05 | 008,009,010 | M |
| T6-04 | modify | `src/extension.ts` | Export pure `parseStockAnalysisArgs(argString)` (§4.3): JSON escape hatch (OQ-7); `--mode`/`-m` authoritative; positional tickers (analyze) / comma-list (compare) / quoted theme (walk); `--top-industry`/`--total-company`/`--top-price`/`--min-headroom`/`--days`/`--universe`/`--model`/`--max-agents`; trigger-phrase fallback (find best→pipeline, screen→screen, deep-dive→analyze, vs/compare→compare, walk chain→walk); default pipeline. | AC-05 | 008,009,010 | M |
| T6-05 | modify | `src/extension.ts` | Implement `formatSummary(state)` (PAT-003, §4.4): derive `success\|partial\|failed` from `reports.length`, `tracking.failures`, `tracking.gateResults`; never default to `success`; list completed/skipped/failed + reports. | AC-06 | 012,013 | S |
| T6-06 | create | `tests/arg-parser.test.ts` | Cases: `--mode analyze AAPL MSFT`; `--mode compare NVDA,AMD,INTC`; `--mode walk "humanoid robotics"`; `--top-industry 40 --universe CN`; JSON escape hatch `{"mode":"analyze","tickers":["AAPL"]}`; trigger phrases (find best / screen sectors / deep dive AAPL / NVDA vs AMD / walk the chain for X); no-mode default pipeline; invalid mode rejected. | AC-05 | 008,009,010 | M |
| T6-07 | create | `tests/format-summary.test.ts` (or fold into arg-parser/structure) | `formatSummary`: all-stages-complete + reports + gates-pass → `success`; some failures + reports → `partial`; no reports → `failed`; never `success` when failures exist. | AC-06 | 012,013 | S |
| T6-08 | verify | `npm run typecheck && npm test` | Exit 0 / 0. **Phase 6 exit gate.** | AC-04,05,06 | 005–013 | S |

---

## PHASE 7 — Skill Pointer + README + Full Suite Green  (`domain: docs` + `test`)

| ID | action | files | description | ac | scenario | effort |
|---|---|---|---|---|---|---|
| T7-01 | create | `skills/stock-analysis/SKILL.md` | SHORT pointer (comparable to pi-super-dev/skills/super-dev/SKILL.md): one-paragraph description; `/stock-analysis` command; 5 modes (one line each); keep-Python contract (one line); pointer to README + `06-specification.md`. NOT the giant Claude skill. | AC-18 | 034 | S |
| T7-02 | create | `README.md` | §11 sections: title+summary; install (`pi package add` + `pi -e .`); prerequisites (Node≥22.19, `uv` on PATH, Python≥3.11); 5 usage examples (one per mode); node-algebra reference table (ASCII); per-mode pipeline diagrams (ASCII); **explicit Python-keep rationale** (akshare/baostock no Node equivalent); how agents invoke scripts via `runScript`→`uv run python ${EXTENSION_ROOT}/scripts/<n>.py`; architecture pointer. | AC-21 | 040,041 | M |
| T7-03 | create | `docs/architecture.mmd` (optional) | Mermaid component diagram (OQ-6) for rendered docs. Low-stakes. | AC-21 | 041 | S |
| T7-04 | modify | `tests/structure.test.ts` | Add: `pi.skills[0]==="./skills/stock-analysis"`; `skills/stock-analysis/SKILL.md` exists AND line-count ≤ bound (e.g. 60) — asserts "short pointer"; README has install + 5 mode examples + Python-rationale headings. | AC-18, AC-21 | 034,040 | S |
| T7-05 | verify | clean install | `rm -rf node_modules && npm install && npm run typecheck && npm test` → all exit 0 (AC-20, SCENARIO-039). | AC-20 | 039 | S |
| T7-06 | verify | manual smoke (optional, not hermetic) | `pi -e .` loads extension; `/stock-analysis --mode analyze AAPL` parses (no full run required — agents/scripts may be mocked or skipped; verifies registration only). | AC-04, AC-05 | 005,008 | S |
| T7-07 | verify | final coverage scan | Confirm every AC-01…AC-25 has a passing test or artifact; confirm no excluded artifacts present (T2-33). **Phase 7 + project exit gate.** | ALL | ALL | S |

---

## File Inventory (complete)

### Created (new)
- `package.json`, `tsconfig.json`, `vitest.config.ts`, `.gitignore`, `LICENSE`, `CHANGELOG.md`, `README.md`
- `src/extension.ts`, `src/nodes.ts`, `src/workflow.ts`, `src/types.ts`, `src/control.ts`, `src/helpers.ts`, `src/agents.ts`, `src/pi-spawn.ts`, `src/session-agent.ts`, `src/prompts.ts`, `src/scripts.ts`, `src/stages/index.ts`
- `skills/stock-analysis/SKILL.md`
- `tests/structure.test.ts`, `tests/nodes.test.ts`, `tests/workflow.test.ts`, `tests/control.test.ts`, `tests/ticker-normalize.test.ts`, `tests/scripts.test.ts`, `tests/mode-dispatch.test.ts`, `tests/arg-parser.test.ts`, `tests/format-summary.test.ts`
- `docs/architecture.mmd` (optional)

### Copied verbatim (byte-identical, from `~/jenningsloy318/stock-analysis-plugin/`)
- `scripts/*.py` (76) + `scripts/requirements.txt`
- `pyproject.toml`, `uv.lock`
- `references/**`, `templates/**`, `schemas/*.json` (16), `assets/report_styles.css`

### Copied + preamble-edited (22)
- `agents/{team-lead,data-collector,sector-screener,company-screener,fundamental-analyst,industry-analyst,supply-chain-analyst,macro-analyst,quant-analyst,risk-analyst,alt-data-analyst,catalyst-analyst,china-market-analyst,roadmap-walker,scorer,equity-report-writer,screening-report-writer,report-validator,company-orchestrator,market-daily-orchestrator,search-agent,team-lead-workflow}.md`

### Modified (during phased impl, from stubs)
- All `src/*.ts` (stubs created in P1, fleshed in P3–P6); `tests/structure.test.ts` (extended in P2, P7).

### Deleted
- **None.** (Target repo starts empty aside from `docs/` + `.git`.)

### Excluded (verified absent — AC-15)
- `workflows/`, `.claude/`, `.codex/`, `.claude-plugin/`, `.codex-plugin/`, `plugin.json`, `reports/`, `reports-deepseek/`, root `stage*.md`, root `*.py` (`parse_phase2.py`, `generate_reports.py`, …), `run_triage.sh`, `test.py`, `rules/`, source `AGENTS.md`, source `CLAUDE.md`, source `new-analysis.md`, source `docs/`.

---

## Coverage Roll-up

| AC | Tasks |
|---|---|
| AC-01 | T1-01, T1-07, T1-09 |
| AC-02 | T1-01, T1-09 |
| AC-03 | T1-02, T1-03, T1-04, T1-05, T1-06, T1-09 |
| AC-04 | T6-02, T6-06 |
| AC-05 | T6-03, T6-04, T6-06 |
| AC-06 | T6-02, T6-05, T6-07 |
| AC-07 | T3-02, T3-06 |
| AC-08 | T3-03, T3-07 |
| AC-09 | T3-01, T3-05, T3-09 |
| AC-10 | T5-01…T5-08, T5-10 |
| AC-11 | T5-01, T5-10 |
| AC-12 | T2-09…T2-30, T2-31, T2-32 |
| AC-13 | T2-01…T2-04, T2-32 |
| AC-14 | T2-05…T2-08, T2-32 |
| AC-15 | T2-33 |
| AC-16 | T4-05, T4-06, T4-07 |
| AC-17 | T3-04, T4-01…T4-04, T6-01 |
| AC-18 | T7-01, T7-04 |
| AC-19 | T1-03, T3-06…T3-09, T4-07, T5-10, T6-06, T6-07, T7-04 |
| AC-20 | T7-05 |
| AC-21 | T7-02, T7-03, T7-04 |
| AC-22 | T5-09 (agent preambles from T2-09…T2-30) |
| AC-23 | T5-09 |
| AC-24 | T3-05, T5-05, T5-10 |
| AC-25 | T4-04, T5-05, T5-09, T5-10 |

**Every AC-01…AC-25 is owned by ≥1 task. Every SCENARIO-001…050 is addressable.** Total tasks: **66** (10 + 25 + 10 + 8 + 11 + 8 + 7 = 79 task-rows including verification; distinct deliverables 66). Phases: **7**.
