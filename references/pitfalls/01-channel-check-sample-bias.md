---
title: Single channel-check is a sample, not a population — discount and require confluence
severity: HIGH
appliesTo: stage5, stage13, primary-research, channel-check
tags: sample-bias, confluence, primary-research, alt-data
---

## Single channel-check is a sample, not a population

One agency / one customer / one expert call is **n=1**. Aggressive growth signals from a single source are usually self-selection — agencies and customers willing to take channel-check calls are systematically not market-average. Extrapolating a single source to a company-wide trend produces directional misses on the order of 5–10pp on key metrics (revenue beat, ad spend QoQ, customer churn).

**Why it matters**: A single +19% QoQ data point from one ad agency does NOT imply +19% QoQ for an entire ad-tech company. The agency was top-quartile in spend — the population mean was +11%. Lifting a base case by 8pp on one anchor moves a "modest beat" thesis to "blowout beat", which corrupts catalyst probability, IV positioning, and short-term scoring.

**Concrete failure**: APP 2026-05 setup — agency reported +19% QoQ Q4→Q1 ad spend; thesis extrapolated to APP-wide trend → predicted +blowout beat. Reality was +11% QoQ. The agency was a top-quartile spender, not a market average. Resulting structure (Jade Lizard with bull-skewed strikes) underperformed.

**How to apply**:

1. **Discount any single channel-check by 30–40%** before using it as a base case. Document the discount in the source citation.
2. **Require 2–3 independent sources** before lifting a base case by more than 1pp on any KPI.
3. **Different demand profiles, not the same**: confirming sources should span profile types (large advertiser + small advertiser + agency, NOT 3 agencies).
4. In `synthesize_primary_research.py`, the convergence score MUST be ≥3 sources from ≥2 distinct profile types before a claim is "validated".
5. Single-source claims appear in the report tagged `[Source: X | n=1, discounted 35%]`.

**When the rule does NOT apply**:
- The single source is *the* counterparty — e.g., the only customer accounts for >50% of revenue. Then n=1 is the population.
- Public regulatory filing (10-K, 10-Q, FDA) — these are not channel-checks; they are population statements.

**Cross-references**:
- Pitfall 5 — high-conviction setups need ≥3 aligned sources to override single-source discount
- `references/frameworks_behavioral.md` — small-sample bias, base-rate neglect
- Stage 13 (`agents/alt-data-analyst.md`) — primary research synthesis enforcement point
- `scripts/synthesize_primary_research.py` — convergence scoring
