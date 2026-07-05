---
title: Stale data without [STALE] flag silently corrupts every downstream score
severity: MEDIUM
appliesTo: all-stages, data-integrity, validation
tags: stale-data, data-freshness, validation, methodology
---

## Stale data without [STALE] flag silently corrupts every downstream score

The data freshness matrix (`references/data_source_matrix.md`) defines Max Freshness for every Tier-1 source. Data older than Max Freshness must be tagged `[STALE]` in the source citation. **Untagged stale data is the single most common silent failure mode** — every downstream score (DCF, sensitivity, conviction, hazard, options classification) is computed on the unflagged number and the report ships looking authoritative.

**Why it matters**:
- A 10-Q that's 95 days old (Max Freshness = 90 days) used in a DCF revenue projection silently locks in the prior quarter's growth rate
- A short-interest reading 3 weeks old can flip a "squeeze setup" call to a "covered" call (or vice versa)
- An analyst-consensus EPS from before a guidance cut becomes the "expected miss" baseline
- IV / options chain >24 hours old yields wrong vega-axis recommendations

**How to apply**:

1. **Every numeric claim in every stage summary cites freshness**:
   ```
   Revenue Q1 $X.XB [Source: 10-Q | Retrieved: 2026-05-12 | Fact]
   ```
   If retrieval date − publication date > Max Freshness for the source type, prepend `[STALE]`:
   ```
   Insider transactions [STALE] [Source: Form 4 aggregate | Retrieved: 2026-04-30 | Fact]
   ```

2. **`validate_report.py` gate**: pre-delivery checklist FAILS if any Tier-1 metric in the report is stale and unflagged. Rule:
   ```
   if max_age(source_type) > tier1_max_freshness[source_type] and "[STALE]" not in citation:
       FAIL with reason "stale data not flagged: <metric>"
   ```

3. **Refresh before scoring** — stages 5/10/11/16 must check timestamps from stage1.json and re-fetch any input that crossed Max Freshness during the run.

4. **Critical metrics that ALWAYS get a freshness check** (block report on stale):
   - Current stock price (Max Freshness: 1 trading day)
   - Latest 10-Q/10-K filings (90 days)
   - Short interest (14 days)
   - Analyst consensus EPS (30 days)
   - IV / options chain (1 trading day)
   - Insider transactions (90 days for "no insider activity"; 30 days if cited as signal)
   - Macro indicators in regime call (refresh per source matrix)

5. **Non-critical metrics** (allow stale with annotation): historical 5-year averages, peer baseline ratios, GICS classification.

**When the rule does NOT apply**:
- Backtest reports comparing past prediction vs realized outcome → "stale" data is the point
- Reference data deliberately frozen (e.g., 2020 sector RS for COVID baseline)

**Cross-references**:
- Pitfall 6 — hazard signals (Beneish, Altman) shift quarterly; stale = wrong hazard
- Pitfall 10 — DCF inputs go stale most-frequently silently
- `references/data_source_matrix.md` — Max Freshness per source type
- `scripts/validate_report.py` — stale-data lint
- All stage agents — must annotate freshness in citation format
