---
title: Capped-upside structures are forbidden in high-conviction directional setups — asymmetry is a third axis
severity: HIGH
appliesTo: stage11, stage18, structure-selection, high-conviction
tags: jade-lizard, iron-condor, calendar, asymmetry, upside-cap, conviction
---

## Capped-upside structures are forbidden in high-conviction setups

Pitfall 4 named **direction** and **vega** as two independent axes. There is a **third axis**: **upside profile / payoff asymmetry**. A structure that *technically* matches direction + vega can still be catastrophically wrong if it **caps the upside in the very scenario you predicted**. Jade Lizard, Iron Condor, Calendar, and Diagonal all cap upside — they are NEUTRAL or PIN structures, not directional ones. When directional conviction is high (channel-check confluence + thematic re-rate + de-risked tape), these structures are forbidden.

**Why it matters**: "High IV → sell premium" (Pitfall 4 / vega rule) is necessary but not sufficient. It tells you the vega sign, not the asymmetry. Selling premium can be done with structures whose bull-case max profit is *small* (Jade Lizard, IC) OR *large* (naked short put, bull put spread, risk reversal). When the bull tail prints, the small-max-profit structures are not just suboptimal — they actively **transform** into upside losers (Jade Lizard call spread fully ITM, IC short call ITM-to-cap, calendar short leg deep ITM).

**Concrete failure**: SNOW 2026-05-27 — pre-earnings setup had **5+ independent factors** screaming bull (6/6 partner channel checks confirming, AI Labs as top customers, stock −30% from 6M high, 4/5 prior quarters positive reactions, hot AI coding agent narrative). Recommendation: Jade Lizard capped upside at $450/contract for any move >$195. Actual outcome: AH +35.75% to $237.92 (a +3.2 SD move). Counterfactual long $185C would have returned +$4,500/contract; Jade Lizard captured ~1% of that.

**How to apply**:

### 1. Bull-conviction count (mandatory pre-structure check)

Tally these factors (each = 1 conviction point):

- [ ] 3+ independent channel checks aligned bullish
- [ ] Sector / thematic narrative actively re-rating
- [ ] Stock down >20% from recent high going into event (de-risked setup)
- [ ] Past 4 quarters: ≥3 positive earnings reactions
- [ ] NEW information likely to be disclosed (new customer tier, new product class, guide raise, M&A)
- [ ] Net options flow back-month bullish (call premium dominance, 5-day rolling)
- [ ] Short interest >10% (squeeze potential)
- [ ] Implied move materially below recent realized average

**Score ≥ 4 → high-conviction bull → asymmetry rule activates → banned structures take effect.**

(Symmetric rule for high-conviction bear.)

### 2. Banned structures in high-conviction directional setups (≥4)

| Structure | Why banned in high-conviction bull |
|---|---|
| Jade Lizard | Bear call spread caps upside; spread max loss in bull tail |
| Iron Condor | Short call ITM in bull tail; symmetric structure assumes range-bound |
| Calendar / Diagonal (tight strikes) | Pin structure; bull tail blows past short strike |
| Covered Call | Caps upside at strike + premium |
| Cash-Secured Put + simultaneous Bear Call | Same problem as Jade Lizard |

### 3. Required structures in high-conviction bull (≥4)

| Structure | Direction | Vega | Upside profile |
|---|---|---|---|
| **Naked Short Put** (cash-secured, far OTM) | + | − (good for high IV) | Capped at credit, no upside drag |
| **Bull Put Spread** | + | − | Capped at credit, no upside drag |
| **Risk Reversal** (sell put + buy call) | strong + | mixed | Uncapped upside |
| **Long Call (single)** | + | + (vega tax at high IV) | Uncapped upside |
| **Bull Call Debit Spread** | + | + | Capped at upper strike |
| **Synthetic Long** | strong + | mixed | Uncapped upside |
| **Stock + protective put** | + | small + | Uncapped upside |

### 4. Counterfactual P/L matrix (mandatory when conviction ≥ 4)

Calculate **max profit if the bull tail scenario hits** (+10%, +20%, +35%, +50%) for each candidate structure. Reject any that shows LOSS or flat at the +35% scenario.

| Structure | P/L @ spot | +10% | +20% | +35% | +50% |
|---|---|---|---|---|---|
| Jade Lizard | credit | credit | LOSS | LOSS | LOSS (capped) |
| Bull put spread | 0 | credit | credit ✓ | credit ✓ | credit ✓ |
| Naked short put | 0 | credit | credit ✓ | credit ✓ | credit ✓ |
| Long ATM call | 0 | gain | gain ✓ | gain ✓ | gain ✓ |
| Risk reversal | 0 | gain | gain ✓ | gain ✓ | gain ✓ |

`calculate_options.py` emits this table when `compute_scores.py` flags conviction ≥ 4.

### 5. Position sizing for high-conviction directional plays
- 1–2% capital max per single-name event trade
- Combined structures: 70% bull put spread (vol-clipper) + 30% long calls (tail catcher)

**Cross-references**:
- Pitfall 1 — channel-check confluence (3+ aligned channels override single-source discount → activates conviction)
- Pitfall 3 — demand-IV inverts the vega rule (still need asymmetry check)
- Pitfall 4 — direction + vega axes (asymmetry is the third)
- Pitfall 8 — manipulator tapes are the exception: Jade Lizard fits when you genuinely have no directional edge
- Stage 11 (`agents/quant-analyst.md`) — must run conviction count + banned-structure check
- `scripts/compute_scores.py` — emits `bull_conviction_count`, `banned_structures[]`
- `scripts/calculate_options.py` — emits counterfactual P/L matrix
