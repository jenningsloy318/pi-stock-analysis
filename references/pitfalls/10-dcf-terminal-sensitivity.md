---
title: DCF terminal value dominates — sensitivity is mandatory
severity: HIGH
appliesTo: stage10, valuation, dcf, terminal-value
tags: dcf, terminal-value, sensitivity, wacc, growth-rate
---

## DCF terminal value dominates — sensitivity is mandatory

In a typical 10-year DCF, the terminal value (years 11+) accounts for **60–80%** of present-value equity. Anchoring on a single point estimate of terminal growth or terminal multiple silently makes the entire valuation a function of one number. Without a sensitivity table across (terminal growth × WACC) and (terminal multiple × discount rate), the DCF is not a valuation — it is a confidence interval of one.

**Why it matters**: A 50bp move in terminal growth (2.5% → 3.0%) typically shifts equity value by 15–25%. A 50bp move in WACC (8.0% → 8.5%) shifts it by another 10–15%. A point-estimate DCF that says "fair value $X" is hiding a true range of roughly ±25%. Any "buy/sell" call based on a 5% gap to that point estimate is noise.

**How to apply**:

1. **Always emit a 2D sensitivity table** in stage10.md:

   | Terminal growth →<br>WACC ↓ | 1.5% | 2.0% | 2.5% | 3.0% | 3.5% |
   |---|---|---|---|---|---|
   | 7.5% | $X | $X | $X | $X | $X |
   | 8.0% | $X | $X | $X | $X | $X |
   | 8.5% | $X | $X | $X | $X | $X |
   | 9.0% | $X | $X | $X | $X | $X |
   | 9.5% | $X | $X | $X | $X | $X |

2. **Cite the cell range, not the diagonal cell.** Report format: "DCF fair value $90–$130 (sensitivity grid; midpoint $110)".

3. **Cross-check with reverse DCF**: solve for the terminal growth rate that justifies *current* price. Compare to historical growth + analyst long-run estimates. If reverse-DCF growth implied >2× sector long-run average → priced for perfection.

4. **Cross-check with comps**: if DCF midpoint diverges from comps median by >20%, document why. A divergence without explanation = forensic flag.

5. **Monte Carlo for high-uncertainty cases** (already in `calculate_metrics.py`): 10,000 paths over (growth, margin, WACC) distributions → emit P10, P50, P90 fair value bands.

6. **Margin of safety**: only call "undervalued" if current price is below the **P25 of the sensitivity range**, not the midpoint. Symmetric for "overvalued" (above P75).

**When the rule does NOT apply**:
- High-quality compounders with long history and stable returns (KO, PG class) → narrow terminal range, sensitivity grid converges; can cite midpoint
- Early-stage / pre-profit / hyper-growth → DCF unstable; switch to scenario analysis (revenue × margin × multiple) or relative comps

**Cross-references**:
- Pitfall 6 — hazard-rate discounting (cumulative survival multiplies the DCF target)
- Pitfall 11 — stale revenue/margin data corrupts DCF inputs silently
- `references/frameworks_value_growth.md` — Buffett, Graham, Damodaran
- Stage 10 (`agents/quant-analyst.md`) — must emit sensitivity table + reverse DCF + comps cross-check
- `scripts/calculate_metrics.py` — DCF + Monte Carlo machinery
