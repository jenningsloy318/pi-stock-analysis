# Research Report — pi-stock-analysis (pi Extension)

**Task:** Create a new pi extension that re-implements the `stock-analysis` orchestration (from `stock-analysis-plugin`) as a self-contained control-flow workflow, mirroring how `pi-super-dev` was derived from `super-dev-plugin`.
**Author:** research-agent
**Status:** decision-ready — all material design questions resolved; OQ-1 (package name) and OQ-4 (backend default) resolved by research below.
**Scope note:** This is a **port/refactor of orchestration**, not greenfield analytics. The two pivotal questions (multi-mode dispatch, Python-vs-TS) were pre-resolved in the requirements; this report validates those decisions against the actual `pi-super-dev` codebase and resolves the remaining open questions (OQ-1…OQ-7) surfaced in `01-requirements.md`.

---

## 1. Research Questions (the 3 that matter)

1. **RQ-1.** Does the `pi-super-dev` node algebra cleanly express the 5-mode / 19-stage stock-analysis pipeline (mode dispatch, conditional stages, per-company wave DAG, gates, retry, map concurrency)? → **Yes.** See §2.
2. **RQ-2.** Is keeping the 76 Python scripts (vs rewriting in TS) the correct boundary, and does a `runScript` helper map cleanly onto the existing `runHelper` pattern? → **Yes, directly.** See §3.
3. **RQ-3.** Resolve the 7 open questions (OQ-1…OQ-7) from requirements with evidence. → §5.

---

## 2. Node Algebra Fit (RQ-1) — VALIDATED

The `pi-super-dev` control-flow algebra (`src/nodes.ts`) was inspected. Every construct the stock-analysis pipeline needs **already exists** and maps one-to-one to a SKILL.md requirement (SRC-001):

| SKILL.md requirement | Node constructor | Confirmed signature |
|---|---|---|
| Root: 5-mode stage-sequence dispatch | `choose(cases, otherwise?)` | `ChooseCase { when: Predicate; run: Node }` (SRC-001 L186–192) |
| A-share-only Stage 15; screening-only 2/3/4; walk replacing 2–4 | `branch(predicate, { yes, no? })` | (SRC-001 L173) |
| Per-company waves 5–15, max-4 concurrency | `map({ over, as, concurrency }, body)` | `MapOptions { over, as, concurrency, failFast? }` (SRC-001 L366–379) |
| Wave-internal parallelism (wave1 [5,7,9,13]) | `parallel(branches, { concurrency? })` | (SRC-001 L219) |
| Retry-on-null 10× for analysts | `retry({ attempts, until? }, node)` | (SRC-001 L280) |
| 5 validation gates (1.5/4.5/16.5/17.5/18.5) | `gate({ validator, attempts, feedbackKey }, node)` | `GateOptions { attempts, feedbackKey, … }` (SRC-001 L304–327) |
| Adversarial verify (3 skeptics) + judge panel (4 lenses) | `parallel([...])` inside a `map` | — |
| Tolerant non-setup stages | `tryCatch(body, { onCaught? })` + sequence tolerance | (SRC-001 L455) |
| Run-id / setup / cleanup | `task(stage)` / `writerTask` / `helperTask` | (SRC-001 L92, 483, 515) |
| Gate validators backed by deterministic code | `gateValidator(helperName, sourceKey, stateKey)` | (SRC-001 L539) |

**Self-evaluating runner** (`src/workflow.ts` `await root.run(state, ctx)`) is host-agnostic and never changes when stages change — exactly the property the stock-analysis pipeline needs (SRC-001, SRC-002). This is the **strongest evidence** that the port is mechanical: the orchestration engine is already built and proven; we only author a new `stages/index.ts` tree.

> **BP-01.** Author the pipeline as a *purely declarative* tree in `src/stages/index.ts` — never mutate the runner. This is how `pi-super-dev` keeps `workflow.ts` stable across pipeline revisions (SRC-002, stages/index.ts header comment). Stock-analysis should do the same: all 19 stages are composed from existing nodes; `workflow.ts` is copied near-verbatim.

> **BP-02.** Reuse `gateValidator` for the `validate_report.py` gate (Stage 17.5) — it is the exact abstraction for "gate whose pass/fail is computed by deterministic code." The `helperName` dispatches to a thin wrapper that calls `runScript("validate_report", …)`. This avoids inventing a new validator mechanism (SRC-001 L539, SRC-002).

---

## 3. Python-Keep Decision (RQ-2) — VALIDATED

### Evidence the rewrite is infeasible / lossy
`scripts/requirements.txt` (SRC-004) pins 15 Python libraries, of which several have **no Node.js equivalent**:

| Lib | Purpose | Node equivalent? |
|---|---|---|
| `akshare>=1.18` | China A-share + macro data (SH/SZ exchanges) | **None** — wraps Chinese exchange/broker APIs |
| `baostock>=0.9.0` | China A-share historical data | **None** — dedicated SH/SZ protocol client |
| `arch>=6.0` | GARCH volatility models | Partial (no first-class GARCH lib) |
| `pandas-ta`, `polars`, `statsmodels`, `scipy`, `pytrends`, `praw`, `tickflow[all]`, `curl_cffi` | TA / dataframe / econometrics / trends / Reddit / market microstructure / TLS-fingerprint HTTP | Mostly none or lossy |

The source plugin's own SKILL.md mandates the invocation contract (SRC-005, rule "UV Run"):
> ALL Python scripts run via `uv run python ${PLUGIN_ROOT}/scripts/<script>.py`.

### The `runHelper` → `runScript` mapping is direct
`pi-super-dev` already separates deterministic helpers from LLM agents: `src/helpers.ts` `runHelper(call)` dispatches by `call.name` to a `SYNC` map (SRC-003). `helperTask` nodes call it (SRC-001 L515). For stock-analysis the deterministic helpers are **Python scripts**, not TS functions — so `runScript(name, args, opts)` is the exact analogue: it shells out to `uv run python ${EXTENSION_ROOT}/scripts/<name>.py` and parses structured result/stderr. No new abstraction is needed; the node algebra's `helperTask`/`gateValidator` already route through a `runHelper`-shaped dispatcher.

> **BP-03.** `runScript` must (a) resolve `EXTENSION_ROOT` from `package.json` dir once (not per call), (b) stream stderr to the `ProgressSink.log` for live diagnostics, (c) enforce a configurable timeout (network scripts can hang), (d) capture exit code + last JSON object for `<control>` extraction (reuse `src/control.ts` `findLastJsonObject`). This mirrors how `runHelper` returns a structured `HelperResult` (SRC-002, SRC-003).

> **BP-04.** Pin deps via the copied `pyproject.toml` + `uv.lock` (SRC-004) and document `uv` as a **host prerequisite** (do NOT vendor the `uv` binary — see OQ-5). `uv run` auto-creates the venv from the lockfile on first invocation, giving reproducibility without bundling ~50 MB.

---

## 4. Options Considered (decision points)

### OPT-A — Mode dispatch strategy
- **A1. Single tool `stock_analysis{mode}` + `choose(state.mode)` at workflow root.** *(RECOMMENDED, chosen)* One entrypoint; matches `super_dev`; discoverable; the `choose` node is purpose-built for this (SRC-001). The `/stock-analysis` command does NL → structured params → `pi.sendUserMessage`. Tradeoff: command arg-parser is non-trivial (must handle `--mode analyze AAPL MSFT`, `--mode compare A,B,C`, quoted `--mode walk "humanoid robotics"`, trigger-phrase fallback).
- **A2. Five separate tools/commands** (`stock_screen`, `stock_analyze`, …). Rejected: clutters the tool namespace, duplicates the setup/teardown stages, diverges from the `super_dev` precedent.
- **A3. One tool, dispatch inside a single giant `task`.** Rejected: loses the declarative visibility and per-stage tolerance the node algebra provides.

### OPT-B — Python boundary
- **B1. Keep 76 scripts verbatim; thin `runScript` shell-out.** *(RECOMMENDED, chosen)* Hundreds of hours saved; zero capability loss; identical to the `pi-super-dev` boundary (orchestration-in-TS, analysis-verbatim). Tradeoff: host must have `uv` + Python (documented prerequisite).
- **B2. Rewrite hot-path scripts in TS; keep only akshare/baostock in Python.** Rejected: re-introduces a TS/Python boundary *and* a TS/Python duplication problem; the deterministic-contract benefit (SRC-005 rule "UV Run") would fragment.
- **B3. Full TS rewrite.** Rejected: infeasible (no Node akshare/baostock — §3).

### OPT-C — Agent-spawn backend
- **C1. Subprocess default (`pi -a <agent>`), `session` override via env.** *(RECOMMENDED, resolves OQ-4)* Mirrors `SUPER_DEV_BACKEND` exactly (SRC-002). Subprocess isolation means a crashing/freezing agent cannot take down the orchestrator — important for a 19-stage, 50-company × 11-stage run. Tradeoff: ~slower spawn than in-process; acceptable for a long-running batch workflow.
- **C2. Session (in-process) default.** Rejected as default: a single runaway agent would kill the whole 30-min+ run.

### OPT-D — Agent adaptation depth
- **D1. Copy all 22 `.md` files; edit ONLY the invocation preamble** (swap Claude `Agent`/`subagent_type` notes for `pi -a <name>` + `${EXTENSION_ROOT}` injection). *(RECOMMENDED)* Preserves every framework/schema/weight (non-goal NG-5: do not alter analytics). Cheap, mechanical.
- **D2. Rewrite agent prompts.** Rejected: violates the "preserve domain truth" non-goal.

---

## 5. Open Questions — RESOLUTIONS

Resolved against `01-requirements.md §8` (OQ-1…OQ-7):

| # | Question | Resolution | Evidence |
|---|---|---|---|
| **OQ-1** | Package name `pi-stock-analysis` vs `pi-finance` | **`@jenningsloy318/pi-stock-analysis`** *(resolved)* | Matches npm scoped-name + `pi-<feature>` convention (SRC-006 best practice: name should signal contents). `pi-super-dev` already follows this; reserving `pi-finance` as a future umbrella is sound. Repo dir stays `pi-finance`. |
| **OQ-2** | 21 vs 22 agents | **Copy all 22** | `agents/` has 22 files (verified). Keeping all is harmless; unused-in-pipeline agents may be ad-hoc-invoked. |
| **OQ-3** | `market-daily-orchestrator` + `search-agent` not in stage table | **Copy but do NOT wire** into the 19-stage pipeline | Not referenced by SKILL.md `<modes>` (SRC-005). Track as a possible future `--mode daily` mode. |
| **OQ-4** | Backend default subprocess vs session | **subprocess default; `STOCK_ANALYSIS_BACKEND=session` override** *(resolved)* | Isolation safety for long multi-agent runs (OPT-C1); mirrors `SUPER_DEV_BACKEND` (SRC-002). |
| **OQ-5** | Vendor `uv` / pin Python? | **Rely on host `uv`; rely on copied `uv.lock` for deps** | Vendoring adds ~50 MB + maintenance; `uv run` reads the lockfile for reproducibility. Document `uv` install in README prereqs. |
| **OQ-6** | README diagrams: ascii vs mermaid | **Both** | ASCII in README (terminal viewers, matches `pi-super-dev`), Mermaid under `docs/` for rendered views. |
| **OQ-7** | `/stock-analysis` accept raw JSON arg? | **Yes** | If the NL `query` parses as JSON matching tool params, dispatch directly. Cheap scripting escape hatch. |

> All seven are resolved. No question is *blocking*; OQ-1/OQ-4 were the only "blocking-ish" ones and both now have an evidence-backed recommendation. Owner need only confirm OQ-1 if they prefer `pi-finance` as the package name.

---

## 6. Issues / Risks (to flag, not block)

- **ISS-01 (med).** `EXTENSION_ROOT` resolution must work for **both** `pi -e .` (runs from source, `.ts` path) **and** an installed package (`pi package add`). `pi-super-dev` resolves it from the `package.json` directory via `agentsDirectory()` (SRC-002 L36). Replicate that exact strategy; do **not** rely on `import.meta.url` + `__dirname` tricks alone — validate both load paths in `tests/structure.test.ts`.
- **ISS-02 (med).** The Stage-17.5 `validate_report.py` gate runs 8 sub-gates (requirements §6.4). If invoked via `runScript`, a Python dependency failure (e.g. `uv` not installed, network down) must surface as a **gate failure with clear stderr**, not a silent `no validator` pass — `pi-super-dev` already warns about "vacuous pass" for missing validation output (stages/index.ts `researchComplete` comment, SRC-002). Apply the same non-vacuous-pass discipline.
- **ISS-03 (low).** Per-company wave DAG (wave1 [5,7,9,13] → wave2 [6,8,10,14] → wave3 [11,12] → wave4 [15, A-share only]) is composed from nested `parallel`/`branch` inside a `map(..., {concurrency:4})` body. Confirm `map`'s `concurrency` caps **company-level** parallelism (4 companies at once) while inner `parallel` caps **stage-level** parallelism within one company — these are two independent dials and must not be conflated. Document in `stages/index.ts`.
- **ISS-04 (low).** `tickers` validation: `compare` requires 2–5; `analyze` requires ≥1. The tool's `execute()` should fail fast with a clear message (like `super_dev`'s empty-task guard, SRC-002) rather than letting the pipeline discover the error at Stage 5.
- **ISS-05 (low).** Agent prompt preamble edit must replace `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` **everywhere** they appear (not just the constraint named "Pass PLUGIN_ROOT"). A repo-wide `grep -r CLAUDE_PLUGIN` after copy is the cheapest correctness check.
- **ISS-06 (info).** 76 scripts copied verbatim means the package ships a large `scripts/` tree + `references/` + `templates/` + `schemas/`. Ensure `package.json` `"files"` array includes them (otherwise `npm publish` strips them). `pi-super-dev` lists `["src","agents","skills",...]` (SRC-006); add `scripts`, `references`, `templates`, `schemas`, `assets`, `pyproject.toml`, `uv.lock`.

---

## 7. Summary

The port is **low-risk and largely mechanical** because the orchestration engine already exists and is proven:

1. **Node algebra fit is exact** — every control-flow need (mode dispatch, conditional A-share/screening/walk stages, per-company max-4 waves, retry-on-null, 5 gates, adversarial/judge parallelism) maps to an existing `pi-super-dev` node (§2, SRC-001). No new engine code is required; only a new declarative `stages/index.ts` tree.
2. **Python-keep is correct** — akshare/baostock have no Node equivalent (§3, SRC-004); the `runHelper`→`runScript` mapping is a direct 1:1 (SRC-002/003). Same boundary `pi-super-dev` drew.
3. **All 7 open questions are resolved** with evidence (§5). Only OQ-1 (package name) wants an explicit owner confirmation; everything else proceeds on the stated recommendations.
4. **Risks are bounded and enumerable** (§6): extension-root resolution under both load modes, non-vacuous gate failure, two independent concurrency dials, fail-fast ticker validation, repo-wide `CLAUDE_PLUGIN` scrub, and the `files`-array inclusion of the large data tree.

**Bottom line:** proceed to the design/spec stage with the chosen options (OPT-A1, OPT-B1, OPT-C1, OPT-D1) and the OQ resolutions in §5. No further research is required; the remaining work is composition (copying assets, authoring `stages/index.ts`, writing the `runScript` helper and arg parser, and the hermetic test suite).

---

## Sources

- **SRC-001** — `pi-super-dev/src/nodes.ts` (control-flow algebra signatures: `task`, `sequence`, `branch`, `choose`, `parallel`, `loop`, `retry`, `gate`, `map`, `wait`, `tryCatch`, `noop`, `writerTask`, `helperTask`, `gateValidator`).
- **SRC-002** — `pi-super-dev/src/extension.ts`, `src/workflow.ts`, `src/stages/index.ts`, `src/helpers.ts`, `src/session-agent.ts`, `src/pi-spawn.ts`, `src/control.ts` (runner stability, `runHelper` dispatch, `EXTENSION_ROOT`/`agentsDirectory` resolution, `SUPER_DEV_BACKEND` env switch, progress/run-log/summary pattern, `pi.registerTool`/`registerCommand`/`sendUserMessage` API).
- **SRC-003** — `pi-super-dev/src/helpers.ts` `runHelper()` + `HELPER_NAMES` (the deterministic-helper dispatcher that `runScript` mirrors).
- **SRC-004** — `stock-analysis-plugin/scripts/requirements.txt` (akshare, baostock, yfinance, scipy, statsmodels, arch, pandas-ta, polars, praw, pytrends, tickflow, curl_cffi — evidence for Python-keep).
- **SRC-005** — `stock-analysis-plugin/skills/stock-analysis/SKILL.md` `<modes>`, `<triggers>`, rules ("UV Run", "Pass PLUGIN_ROOT", "Report Language") — authoritative orchestration spec being ported.
- **SRC-006** — `pi-super-dev/package.json` (`pi.extensions`/`pi.skills`/`peerDependencies`/`exports`/`files`/`engines` config to mirror).
- **SRC-007** — `@earendil-works/pi-coding-agent` `docs/extensions.md` (registerTool/registerCommand/ExtensionAPI contract).
