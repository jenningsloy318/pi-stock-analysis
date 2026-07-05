---
title: Float / social saturation is a contrarian top signal
severity: MEDIUM
appliesTo: stage13, alt-data, sentiment, retail-flow
tags: retail-saturation, kol-cascade, float-composition, sentiment, contrarian
---

## Float / social saturation is a contrarian top signal

When a name has **too much retail on board** — heavy social media discussion, KOL cascade, retail chat saturation, Reddit/Stocktwits/Chinese-platform daily mentions — the condition *"no new retail left to relay-buy"* is approaching. Marginal-bull supply is drying up. This is **not** "if KOLs are pumping it, the stock is bad" — it is "retail demand pool is exhausted; the trend needs fresh institutional bid to continue."

**Why it matters**: Every buyer is a future seller (orderbook primitive). A sustained uptrend requires a continuous supply of new buyers with higher target prices. When retail is saturated:
- Institutional bid becomes the deciding signal
- Net options premium turning negative or distribution-shaped is the early top signal
- Single-name technical patterns become noise overshadowed by holder-mix exhaustion

**Concrete case**: NOK 2026-04 — KOL cascade (@KawzInvests → @AntonLaVay → @ShanghaoJin) was both the rally's accelerant *and* a saturation gauge. At peak saturation, the question "are institutions still net-buying or net-selling into the crowd?" became the entire trade.

**How to apply**:

1. **Compute a `social_saturation_score` (0–100)** in `fetch_alternatives.py` from existing signals:
   - Reddit daily mention growth rate (5-day vs 20-day)
   - Stocktwits sentiment volume (vs 30-day baseline)
   - Google Trends search volume (vs trailing 1-year peak)
   - Twitter/X mention concentration (HHI of accounts driving mentions; concentration drops at saturation)
   - News coverage spike vs trailing 90D

   ```
   saturation_score = weighted_sum / 100
   - <30: low (room for new entrants)
   - 30–60: medium
   - 60–85: high (caution — KOL cascade likely active)
   - >85: extreme (top forming; institutional flow becomes the deciding signal)
   ```

2. **At saturation_score >60, the report MUST cite institutional flow direction** (Funda or Finnhub net options premium, 13F changes if available) as the deciding signal. Do not rely on sentiment alone — sentiment IS the saturation signal.

3. **At saturation_score >85**:
   - Treat as inflection-watch
   - Look for "should have moved but didn't" — new catalyst hits but price doesn't break out → distribution forming
   - Recommend defensive structures (trim positions, tighter stops, no new size)

4. **Symmetric for short-side saturation** — heavy bearish KOL cascade + Reddit short conviction at peak = short squeeze setup, not bear continuation.

**When the rule does NOT apply**:
- Quality large-caps with broad institutional ownership → retail mentions are noise; saturation_score loses meaning (institutions dominate the float)
- Names with no retail visibility (small-cap industrials, foreign listings) → no signal to read

**Cross-references**:
- Pitfall 1 — channel-check single sample: KOL = single source amplified, not a population
- Pitfall 8 — manipulator tapes often coincide with saturation (the manipulation feeds on retail)
- `references/frameworks_behavioral.md` — Shiller narrative economics, Soros reflexivity
- `references/microstructure-framework.md` — float composition primitive
- Stage 13 (`agents/alt-data-analyst.md`) — emits `social_saturation_score`
- `scripts/fetch_alternatives.py` — saturation computation
