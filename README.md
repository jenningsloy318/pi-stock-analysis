# pi-stock-analysis

A **self-contained**, modular equity-research pipeline for the [Pi coding
agent](https://github.com/earendil-works/pi-coding-agent), built on a composable
**control-flow node algebra** (branch / parallel / loop / retry / gate / map /
choose / wait). It re-implements the `stock-analysis` Claude Code plugin's
orchestration as a TypeScript workflow — the same port pattern used for
[`pi-super-dev`](https://github.com/) ↔ `super-dev-plugin`.

Runs 5 modes × 19 stages — screen GICS sub-industries → deep-dive companies →
scoring → adversarial verify → judge panel → 3-horizon reports → best picks —
by spawning 22 specialist `pi` subagents directly. **No dependency on any
external workflow engine.**

## Install

```bash
pi package add pi-stock-analysis
# or, from a local checkout:
pi -e /path/to/pi-stock-analysis
```

### Prerequisites

- Node ≥ 22.19
- **`uv` on PATH** (the deterministic Python scripts run via `uv run`)
- Python ≥ 3.11 (handled automatically by `uv` against the bundled `pyproject.toml` + `uv.lock`)

## Use

```text
# From the pi TUI:
/stock-analysis --mode pipeline --universe US
/stock-analysis --mode screen --top-industry 40
/stock-analysis --mode analyze AAPL MSFT
/stock-analysis --mode compare NVDA,AMD,INTC
/stock-analysis --mode walk "humanoid robotics"

# Or directly via the tool call:
stock_analysis({ mode: "analyze", tickers: ["AAPL"], universe: "US" })
```

Tool options: `mode`, `tickers`, `theme`, `topIndustry`, `totalCompany`,
`topPrice`, `minHeadroom`, `days`, `universe`, `model`, `maxAgents`.

### Modes

The `--mode <name>` flag is authoritative. The **positional arguments that
follow it depend on the mode** (tickers for analyze, a comma-list for compare,
a quoted theme for walk). Omit `--mode` to infer it from the request phrasing.

| Mode | What it does | Positional args after `--mode` | Example |
|---|---|---|---|
| `pipeline` *(default)* | Screen sectors **and** deep-dive the top companies end-to-end (Stage 0→19) | — (uses filters) | `/stock-analysis --mode pipeline --universe US --total-company 15` |
| `screen` | Screen GICS sub-industries + companies only (no per-company deep-dive) | — (uses filters) | `/stock-analysis --mode screen --top-industry 40 --days 5` |
| `analyze` | Deep-dive one or more tickers (full 5→15 analyst waves + scoring + reports) | whitespace-separated tickers | `/stock-analysis --mode analyze AAPL MSFT` |
| `compare` | Compare 2–5 tickers with identical valuation methodology | comma-separated tickers | `/stock-analysis --mode compare NVDA,AMD,INTC` |
| `walk` | Bottleneck walk: trace a theme's supply chain → score chokepoint candidates → deep-dive the top 3–5 | quoted multi-word theme | `/stock-analysis --mode walk "humanoid robotics"` |

**Trigger-phrase fallback** (when `--mode` is omitted — the parser infers mode
from the request):

| Phrase pattern | Inferred mode |
|---|---|
| "find best stocks", "top picks", "全面筛选" | `pipeline` |
| "screen sectors", "筛选行业", "best industries" | `screen` |
| "analyze TICKER", "deep dive X", "valuation of X", "DCF X" | `analyze` (+ extracted ticker) |
| "X vs Y", "compare X,Y", "which is better" | `compare` (+ extracted tickers) |
| "walk the chain for X", "chokepoint analysis X", "瓶颈分析 X" | `walk` (+ theme) |

**A-share tickers**: bare 6-digit codes auto-suffixed (`600519` → `600519.SH`,
`000001` → `000001.SZ`); Chinese names (e.g. `贵州茅台`) are flagged for akshare
resolution at Stage 1.

**JSON escape hatch**: `/stock-analysis` also accepts a raw JSON object, e.g.
`/stock-analysis {"mode":"analyze","tickers":["AAPL"]}`.

### Options reference

| Flag | Tool param | Default | Notes |
|---|---|---|---|
| `--top-industry N` | `topIndustry` | 8 pipeline / 40 screen / 7 walk | top sub-industries (or walk candidates) |
| `--total-company M` | `totalCompany` | 15 | pipeline only, cap 50 |
| `--top-price N` | `topPrice` | 200 | max price filter; `0` disables |
| `--min-headroom N` | `minHeadroom` | 5 | Growth-Headroom floor 1–10 |
| `--days N` | `days` | 1 | hot-sector window 1–20 (1=today, 5=week) |
| `--universe US\|CN\|ALL` | `universe` | US | listing-exchange filter |
| `--model <id>` | `model` | — | override specialist model |
| `--max-agents N` | `maxAgents` | 200 | cap specialist spawns |


## The Python decision (keep, do not rewrite)

The 76 deterministic financial scripts under `scripts/*.py` are kept **verbatim**.
This is deliberate, not a stop-gap:

- **akshare + baostock** provide China A-share market data with **no Node.js
  equivalent**. Rewriting would be a real capability loss, not just effort.
- **scipy, statsmodels, arch (GARCH), pandas-ta, polars** are Python-only
  scientific/financial stacks.
- The source skill already mandates `uv run python ${EXTENSION_ROOT}/scripts/<name>.py`;
  this package preserves that contract.

This is the **same boundary** `pi-super-dev` drew: re-implement the
*orchestration* in TypeScript; keep *deterministic analysis code* + *domain
knowledge* verbatim. The TS layer orchestrates + spawns agents; agents invoke
the Python via the thin `src/scripts.ts` bridge.

## Architecture

```
extension.ts  ──►  registers  stock_analysis tool + /stock-analysis command
      │                       (arg parser: --mode flag > trigger phrase > default)
      ▼
workflow.ts  ──►  runs a tree of Nodes (ctx.agent / ctx.helper / ctx.script)
      │
      ▼
stages/index.ts  ──►  choose(state.mode) → per-mode stage sequence
      │
      ├─ nodes.ts        the control-flow algebra (task/sequence/branch/choose/
      │                   parallel/loop/retry/gate/map/wait/tryCatch/noop)
      ├─ helpers.ts      A-share ticker normalize, mode-aware defaults, gates
      ├─ prompts.ts      per-stage prompt builders (inject EXTENSION_ROOT)
      ├─ agents.ts       loads agents/<name>.md (22 specialists)
      ├─ pi-spawn.ts     spawns `pi` subprocesses (default backend)
      ├─ session-agent.ts  in-process backend (STOCK_ANALYSIS_BACKEND=session)
      ├─ scripts.ts      runScript → `uv run python` bridge to verbatim Python
      ├─ control.ts      tolerant <control> JSON extractor
      └─ args.ts         /stock-analysis arg parser (pure, unit-tested)
```

### Control-flow node algebra (`src/nodes.ts`)

| Node | Purpose |
|---|---|
| `task(stage)` | Leaf — runs a `Stage`, stores return value at `state[stage.id]` |
| `sequence([...], {tolerant?})` | Ordered composition — fail-fast or tolerant-continue |
| `branch(pred, {yes, no?})` | Binary conditional |
| `choose([{when, run}, ...])` | Multi-way switch — **ROOT mode dispatch** |
| `parallel([...], {concurrency?})` | Fork-join with a concurrency cap |
| `loop({while?, until?, times?})` | Iterate a body until a condition holds |
| `retry({attempts, backoff?})` | Re-run on failure (**retry-on-null 10×**) |
| `gate({validate, attempts})` | Write → validate → re-write (quality-gate loop) |
| `map({over, as, concurrency?})` | Fan out over a collection (**per-company DAG**) |
| `wait(ms)` / `waitForEvent(name)` | Time or event synchronization |
| `tryCatch(body, {catch, finally})` | Error boundary |
| `noop()` | Identity |

Grounded in [AWS Step Functions ASL](https://states-language.net/), the Workflow
Control Patterns taxonomy (van der Aalst), Temporal workflows, and LangGraph.

### The pipeline (`src/stages/index.ts`)

The root is `choose(state.mode)` dispatching to one of five tolerant sequences:

```
pipeline: 0→1→[gate 1.5]→2→3→4→[gate 4.5]→[map 5-15 waves]→16→[gate 16.5]
          →16.6→16.7→17→[map 17.4 critic]→[gate 17.5]→18→[gate 18.5]→19
screen:   0→1→[gate 1.5]→2→3→4→[gate 4.5]→17→[map 17.4]→[gate 17.5]→18→[gate 18.5]→19
analyze:  0→1→[gate 1.5]→[map 5-15 waves]→16→[gate 16.5]→16.6→16.7→17→…→19
compare:  (structurally analyze; max 5 tickers, identical valuation methodology)
walk:     0→1→[gate 1.5]→walk(roadmap-walker)→[map 5-15 top 3-5]→16→…→19
```

The per-company DAG (Stages 5–15) is `map({over: companies, concurrency: 4})`
around 4 dependency-ordered waves of `parallel` analysts, each wrapped in
`retry({attempts: 10})`. Stage 15 (A-share) is gated by `branch(company.isAsh)`.

### How agents invoke scripts

Agents receive `${EXTENSION_ROOT}` and call deterministic calculations via:

```bash
uv run python ${EXTENSION_ROOT}/scripts/compute_scores.py --metrics ./reports/<RUN_ID>/metrics.json ...
```

`src/scripts.ts` wraps this with path-safety (script names validated against
`^[A-Za-z0-9_-]+$`), a 10-minute timeout, structured-JSON parsing, and
**never-throws** semantics so tolerant stages continue on a script failure.

### Backends

The default `subprocess` backend spawns isolated `pi` child processes (robust
for 30-min+ multi-company runs). Set `STOCK_ANALYSIS_BACKEND=session` for the
faster in-process backend via the pi SDK.

## Testing

```bash
npm run typecheck   # tsc --noEmit
npm test            # vitest — hermetic, no pi spawns, no network, no uv
```

The suite covers: package structure, control-flow algebra semantics, mode
dispatch, arg parser, runScript wrapper (mocked spawn), A-share ticker
normalization, control-JSON extraction, and workflow composition.

## License

MIT
