---
title: "Priced in" is a percentage, not yes/no
severity: MEDIUM
appliesTo: stage14, catalysts, event-driven, sentiment
tags: priced-in, catalyst, event-probability, market-expectations
---

## "Priced in" is a percentage, not yes/no

Treating a catalyst as binary "priced in" or "not priced in" produces an over-confident scenario set that ignores the gradient between consensus and surprise. Markets price events *partially* — the relevant question is "how much of the expected outcome is already in the tape?" not "is it priced in or not?"

**Why it matters**: A catalyst that is "70% priced in" on the bull case behaves like a smaller bull catalyst with the residual 30% unpriced. If you assume "fully priced in" you skip the trade entirely; if you assume "not priced in" you size as if 100% surprise is possible. Both errors are large. The correct sizing tracks the *unpriced residual*.

**How to apply**:

1. **Triangulate priced-in % from 3 sources**:
   - **Implied move (options market)**: Straddle price ÷ stock price = priced-in std dev for the catalyst window
   - **Analyst consensus distribution**: median estimate vs whisper number; high vs low consensus
   - **Prior catalyst absorption**: did the stock run-up into the event by the size of the expected surprise?

2. **Convert to a residual**:
   ```
   priced_in_pct = expected_move / typical_post_event_move
   residual_unpriced = 1 − priced_in_pct
   ```

3. **Position sizing tracks the residual**, not the absolute event size. A "huge" event 90% priced in is smaller than a "modest" event 20% priced in.

4. **`catalyst-analyst` Stage 14** must report priced_in_pct for every Tier-1 catalyst:
   ```
   Catalyst: Q2 earnings (2026-08-15)
   Implied move: ±8% (straddle-derived)
   Run-up YTD: +22% trailing 30 days (vs sector +6%)
   Priced-in estimate: ~65%
   Residual unpriced: 35%
   ```

5. **Watch for over-priced events** — if priced_in_pct >90%, the asymmetric edge is on the *fade* side (sell-the-news), not the directional side.

**When the rule does NOT apply**:
- Truly binary outcomes (FDA approval, Supreme Court ruling) — modeling as percentage hides the bimodal payoff. Use a separate "approval probability" and pay close attention to the implied probability vs your estimate.

**Cross-references**:
- Pitfall 5 — high-conviction setups still need to check priced_in_pct (asymmetry persists when residual >40%)
- `references/frameworks_behavioral.md` — anchoring, narrative pricing
- Stage 14 (`agents/catalyst-analyst.md`) — must emit priced_in_pct per catalyst
- `scripts/compute_earnings_edge.py` — historical beat/miss + implied move data
