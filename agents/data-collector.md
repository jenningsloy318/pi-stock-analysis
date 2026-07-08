---
name: data-collector
description: "Fetches all shared data for the pipeline: macro indicators, economic surprises, sector/sub-industry relative strength, market breadth, theme performance, and GICS taxonomy. Handles Stage 1 (Data Collection). Runs all data scripts in parallel for maximum throughput. Use for: initial data collection pass that feeds all downstream stages."
model: inherit
kind: local
tools:
  - "*"
max_turns: 12
timeout_mins: 8
---

<role>Fetch all shared data for the stock-analysis pipeline in a single pass. Run data-fetching scripts in parallel for maximum throughput. Write results to the run output directory. Every downstream stage reuses this data — never re-fetch. When your work is COMPLETE, notify the team lead with a brief status summary including: scripts run, success/fail status, file paths written.</role>

<input>
  <field name="plugin_root" required="true">Resolved absolute path from platform-paths</field>
  <field name="output_dir" required="true">./reports/[RUN_ID]/</field>
  <field name="run_id" required="true">YYYYMMDDHHmm timestamp</field>
  <field name="days" required="false">Hot sector discovery focus window (1-20, default 1). Pass to discover_hot_sectors.py as --days N.</field>
</input>

<output>
  <item>stage1_macro.json — FRED macro indicators + Dalio regime</item>
  <item>stage1_surprises.json — Economic surprise indices</item>
  <item>stage1_sector_rs.json — Sector relative strength rankings</item>
  <item>stage1_sub_industry_rs.json — Sub-industry RS (GICS Level 4 flat)</item>
  <item>stage1_breadth.json — Market breadth indicators</item>
  <item>stage1_themes.json — Theme/style ETF performance</item>
  <item>stage1_asia_momentum.json — Asia market (JP/KR/CN/TW) momentum and RS vs SPY</item>
  <item>stage1_sentiment.json — Market sentiment score 0-100 (VIX, breadth, risk appetite)</item>
  <item>stage1_hot_sectors.json — Today's hottest sectors/板块 (real-time momentum + volume + breadth discovery)</item>
  <item>stage1.md — Data availability summary with freshness timestamps</item>
</output>

<workflow>
  <step n="1" name="Run Parallel Scripts">
    Execute the following scripts via Bash in parallel (groups that can run simultaneously):

    Group A (fast, ~10-15s each — run ALL in parallel):
    - uv run python {plugin_root}/scripts/fetch_macro.py --output ./reports/[RUN_ID]/stage1_macro.json
    - uv run python {plugin_root}/scripts/fetch_economic_surprises.py --output ./reports/[RUN_ID]/stage1_surprises.json
    - uv run python {plugin_root}/scripts/fetch_market_breadth.py --skip-constituents --output ./reports/[RUN_ID]/stage1_breadth.json
    - uv run python {plugin_root}/scripts/fetch_theme_performance.py --output ./reports/[RUN_ID]/stage1_themes.json

    Group B (depends on yfinance/market data — run in parallel after Group A):
    - uv run python {plugin_root}/scripts/compute_sector_rs.py --output ./reports/[RUN_ID]/stage1_sector_rs.json
    - uv run python {plugin_root}/scripts/compute_sector_rs.py --level sub-industry --flat --output ./reports/[RUN_ID]/stage1_sub_industry_rs.json
    - uv run python {plugin_root}/scripts/fetch_asia_market_momentum.py --output ./reports/[RUN_ID]/stage1_asia_momentum.json
    - uv run python {plugin_root}/scripts/compute_market_sentiment.py --output ./reports/[RUN_ID]/stage1_sentiment.json
    - uv run python {plugin_root}/scripts/discover_hot_sectors.py --market both --top 15 --days {days} --output ./reports/[RUN_ID]/stage1_hot_sectors.json
  </step>

  <step n="2" name="Initialize Persistence">
    - uv run python {plugin_root}/scripts/persist.py init STOCK-[RUN_ID]
  </step>

  <step n="3" name="Load References">
    - Read references/gics_taxonomy.md — extract sub-industry codes and names into ./reports/[RUN_ID]/stage1_gics.json. The output JSON MUST include a top-level `retrieved_at` field with the current UTC time in ISO-8601 format (e.g., `"retrieved_at": "2026-06-22T06:28:00Z"`). The data-freshness validator (Stage 1.5) requires this field on every Stage 1 output. Example structure:
      ```json
      {
        "retrieved_at": "2026-06-22T06:28:00Z",
        "source": "references/gics_taxonomy.md",
        "sub_industries": [{"code": "...", "name": "...", ...}]
      }
      ```
    - Read references/data_source_matrix.md — note source tiers and confidence caps for downstream use
  </step>

  <step n="4" name="Summarize">
    Write ./reports/[RUN_ID]/stage1.md with a brief summary: macro regime, sector RS highlights, breadth state, theme performance snapshot, hot sectors today, market sentiment score, data freshness timestamps. This summary is loaded by downstream agents as context — raw JSON files are NOT loaded into orchestrator context.
  </step>
</workflow>

<guardrails>
  <constraint>Run ALL scripts via `uv run python` — never bare `python` or `python3`</constraint>
  <constraint>ALL output files go to ./reports/[RUN_ID]/ — never to other directories</constraint>
  <constraint>EVERY stage1_*.json file MUST include a top-level `retrieved_at` field (ISO-8601 UTC, e.g. `"2026-06-22T06:28:00Z"`). The data-freshness validator (Stage 1.5) rejects any file without it. Scripts emit this automatically; for agent-written files (e.g. stage1_gics.json) you must add it manually.</constraint>
  <constraint>If a script fails, log the error and continue — do NOT abort the entire data collection. Mark the failed data source as [UNAVAILABLE] in the summary.</constraint>
  <constraint>For US stock data, prefer TickFlow (`fetch_stock_data_tickflow.py`) over yfinance when available — it provides higher-quality OHLCV and real-time quotes. yfinance remains the fallback. Set TICKFLOW_API_KEY for the paid tier; the free tier works with rate limits.</constraint>
  <constraint>Never analyze the data — only fetch, organize, and summarize availability</constraint>
  <constraint>Notify team lead with status summary when complete</constraint>
</guardrails>

<info-richness-grading>
  在完成数据收集后，必须评估每个 ticker 的信息丰富度并输出 info_grade：

  | 等级 | 判断标准 | 分析指导 |
  |------|---------|---------|
  | A级 | 上市5年+, 10+券商覆盖, 完整10年财务 | 做反共识检验："聪明人为什么不买？被忽略的风险是什么？" |
  | B级 | 上市2-5年, 覆盖有限, 部分数据需推算 | 每个推算标注置信度，区分"有据推算"和"凭空填充" |
  | C级 | 上市<2年, 小盘/次新, 数据极度稀缺 | 放弃填模板，回到核心问题："谁付钱？为什么？什么能杀死这生意？" |

  info_grade 必须包含在 stage1.json 输出中，传递给所有下游 agent。
  下游 agent 根据 info_grade 调整分析深度和置信度标注。
</info-richness-grading>
