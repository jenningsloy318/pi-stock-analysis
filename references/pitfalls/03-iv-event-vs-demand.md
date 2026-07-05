---
title: Elevated IV without near-term event = demand-driven, not event-driven — check catalyst clock + flow
severity: HIGH
appliesTo: stage11, iv-elevation, structure-selection
tags: iv-crush, flow-check, demand-iv, event-iv, catalyst-clock
---

## Elevated IV without near-term event = demand-driven, not event-driven

IV crush is reflexively expected at any IV Rank >65. But IV elevation has **two distinct sources** with opposite forward dynamics:
- **Event-driven IV** (pre-earnings, FDA, regulatory): mean-reverts hard after the event
- **Demand-driven IV** (sustained options buying on thematic narrative): can persist or expand for weeks

Recommending vega-short structures based on IV level alone — without checking what's *causing* the IV — is the dominant failure mode when reading elevated IV in a momentum theme stock.

**Why it matters**: A stock can sit at IV Rank 65–75 for 4–8 weeks during a thematic re-rate while net options flow stays heavily call-side positive. Assuming "IV is too high, must crush" leads to (a) selling premium into a sustained bid (vega + delta both wrong), or (b) rolling out of long-vol positions just as IV continues to expand. The standard "high IV → sell premium" rule is correct *for event-driven IV*; it under-specifies the demand-driven case.

**How to apply**:

1. **Before calling IV crush, check the catalyst clock**:
   - Days to next earnings? <14 → event-driven (will crush hard post-print)
   - 14–45 → mixed
   - >45 days AND IVR elevated → **demand-driven default** — investigate flow before assuming crush

2. **Pull net premium data** before any vega recommendation. Net call premium >+$5M/day on 3+ consecutive days = sustained institutional accumulation; net premium turning negative = event-style top forming.

3. **Cross-expiry IV shape distinguishes event-IV from demand-IV**:
   - Event-IV: front-week IV >> back-month IV (steep term skew toward catalyst date)
   - Demand-IV: all expiries elevated proportionally; back-month LEAPS IV also high
   - Demand-IV often shows ATM AND OTM IV elevated (long call bid pushes OTM IV)

4. **`calculate_options.py` emits `iv_classification: event|demand|mixed`** with rationale. The short-term scorer reads this and inverts the default "high IVR → sell premium" rule when `demand`.

5. **Quantitative thresholds for "IV will sustain"** (all must hold):
   - IVR >50
   - No earnings/event in next 30 days
   - Net call premium positive on 5-day rolling sum
   - Sector index +5% trailing 5 days
   → Sustained-demand IV regime. Treat as "real vol bid", not "peak to fade."

**When the rule does NOT apply (event-IV is real)**:
- <14 days to earnings → assume event-driven, IV will crush regardless of flow
- Stock had a one-time catalyst that just resolved (M&A close, settlement)
- Net premium negative + IV elevated → distribution / hedging IV

**Cross-references**:
- Pitfall 4 — direction × vega × asymmetry (the structure decision after IV classification)
- Pitfall 8 — manipulator tapes show demand-IV-shaped IV but for different reasons
- Stage 11 (`agents/quant-analyst.md`) — must cite `iv_classification` in stage11.md
- `scripts/calculate_options.py` — IV classification logic
