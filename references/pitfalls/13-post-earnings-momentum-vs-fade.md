---
title: Post-earnings momentum continuation overrides intraday fade pattern when fundamentals + sector + flow + short-interest align
severity: HIGH
appliesTo: stage14, earnings, post-earnings, catalyst
tags: post-earnings, fade, continuation, sector-co-move, gap-up, pead
---

## Post-earnings momentum continuation overrides intraday fade pattern

A gap-up earnings reaction with intraday fade ("exhaustion gap") looks like a multi-day top, but **multi-day momentum continuation is the default outcome** when (a) fundamentals confirmed decisively, (b) sector is in a thematic bull regime, (c) net options flow is bullish, and (d) short interest is high enough to amplify continuation. Calling for a 1–3 day pullback on the technical pattern alone overrides the more powerful underlying setup.

**Why it matters**: A "gap up → fade to close below VWAP → distribution day" pattern is a real signal in *isolated* names. But in a stock that just printed a fundamental beat + raised guidance + sits in a sector co-rally, the same intraday shape often resolves as **mid-day profit-taking absorbed by next-day continuation**. Predicting "60–70% probability of retest of the gap fill" against this combined tailwind systematically underperforms holding into the drift.

**Concrete failure**: NOK 2026-04-23 → 04-30 — NOK reported Q1 with NI guidance raised from 6–8% → 12–14%, Optical +20%, AI&Cloud customers +49%. Gap-up open $10.78, intraday high $10.86, faded to close $10.33. Initial call: 60–70% probability of T+1 fade to $10.00–10.10 — based on closing below VWAP $10.52, distribution-day volume 176M (3× average), "exhaustion gap" formation. NOK never traded below $10.31 again; closed +25% in 5 sessions, +41% in 13 sessions. The intraday fade was real but bounded to that single session.

**How to apply**:

1. **`compute_earnings_edge.py` enforces this rule via `post_earnings_continuation_gate()`**. Before calling a multi-day fade in Stage 14, run the 4-factor gate:
   - Fundamentals confirmed decisively? (beat + raised guidance, NOT just beat)
   - Sector co-moving? (peers up >5% trailing 5d → continuation; peers flat/down → isolated)
   - Net options flow direction? (5-day net call premium >0 = continuation)
   - Short interest >10%? (squeeze risk amplifies continuation)

   **3+/4 bullish → DO NOT predict fade. Hold or add.**
   **1 or fewer bullish → fade signal is consistent with data.**
   **Exactly 2 → neutral, no directional call.**

2. **Distinguish "exhaustion gap" from "first-leg pause"**:
   - Exhaustion gap: stock had multi-day run *into* earnings, IV peaked, no new info delivered → fade probable
   - First-leg pause: stock at relative low going into earnings, surprise beat unlocks new thesis tier → continuation default
   - Check 5-day trailing % move *before* earnings; <+10% = first-leg setup, not exhaustion

3. **Read intraday fade as intra-session profit-taking, not multi-day reversal**:
   - "Close below VWAP" is one-day information, not three-day forecast
   - Distribution-day volume on the FIRST day post-thesis-confirmation is often institutional rotation IN, mis-labeled as distribution
   - Wait for T+1 to T+2 closing action before declaring a top

4. **Sector co-move is the loudest signal**: 3+ peers in the same theme printing fresh highs the same week (e.g., LITE +16%, COHR +13%, CIEN +7% alongside NOK +8%) → single-name technical patterns are noise.

5. **Stage 14 catalyst-analyst MUST cite the gate verdict** in the post-event commentary: "post_earnings_gate: continuation (4/4 bullish factors)".

**When the rule does NOT apply (legitimate fade setups)**:
- Stock already +30%+ in 30 days into earnings (priced-in exhaustion)
- Beat but guidance LOWERED → gap-up was reflex, will fade
- Sector breaking down same week → isolated bid
- Net options flow turning negative T+1 → institutional distribution real

**Cross-references**:
- Pitfall 3 — IV classification (event vs demand) — earnings IV crush is the event-IV case
- Pitfall 7 — "priced in" is a percentage; pre-earnings run-up >+30% pulls priced_in_pct toward 1.0
- Pitfall 9 — float saturation can flip continuation to fade if retail is exhausted
- Stage 14 (`agents/catalyst-analyst.md`) — must run gate in post-earnings window
- `scripts/compute_earnings_edge.py` — `post_earnings_continuation_gate()` implementation
