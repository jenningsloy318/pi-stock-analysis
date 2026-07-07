---
name: stock-analysis
description: "Self-contained pi control-flow workflow for unified equity research. 5 modes (pipeline/screen/analyze/compare/walk) × 19 stages: screen GICS sub-industries → deep-dive companies → scoring → adversarial verify → judge panel → 3-horizon reports → best picks. Spawns specialist pi subagents; deterministic calculations run via verbatim Python scripts."
author: Jennings Liu
version: "0.1.7"
license: MIT
---

# Stock Analysis

Use this skill for equity research: screening sectors, deep-diving tickers,
comparing stocks, or walking a supply-chain theme for bottleneck candidates.

## When to use

Triggers: "find best stocks", "screen sectors", "analyze TICKER", "compare T1,T2",
"walk the chain for THEME", "deep dive", "valuation of", "瓶颈分析".

Do NOT trigger on: general market commentary, non-financial queries.

## Action

Use the `stock_analysis` tool to start the pipeline. It spawns specialist `pi`
subagents directly — there is no external workflow engine.

```text
stock_analysis({ mode: "pipeline", universe: "US" })
```

Five modes (one `mode` parameter dispatches the entire stage graph):

| Mode | Use | Example |
|---|---|---|
| `pipeline` (default) | screen sectors + deep-dive top companies | `--mode pipeline --universe US` |
| `screen` | screen sub-industries only | `--mode screen --top-industry 40` |
| `analyze` | deep-dive one or more tickers | `--mode analyze AAPL MSFT` |
| `compare` | compare 2-5 tickers | `--mode compare NVDA,AMD,INTC` |
| `walk` | bottleneck walk for a theme | `--mode walk "humanoid robotics"` |

## Command

```text
/stock-analysis [--mode <name>] [tickers|theme] [options]
```

Omit `--mode` to infer from the request ("find best stocks" → pipeline,
"analyze AAPL" → analyze, "NVDA vs AMD" → compare, "walk humanoid robotics" → walk).

## Notes

- Deterministic financial calculations run via the **verbatim Python scripts**
  (`scripts/*.py`) through `uv run python` — they are kept as-is because
  akshare + baostock provide China A-share data with no Node.js equivalent.
- All reports are written in Chinese (中文); technical terms in English.
- Full architecture: see `README.md` and
  `docs/specifications/01-pi-stock-analysis-workflow/06-specification.md`.
