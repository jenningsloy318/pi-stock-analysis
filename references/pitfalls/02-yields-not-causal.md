---
title: Bond yields don't cause equity moves — both are downstream of the same macro drivers
severity: HIGH
appliesTo: stage4, macro-framing, regime-identification, report-prose
tags: bond-yields, macro, causality, real-yield, term-premium
---

## Bond yields don't cause equity moves — both are downstream of the same macro drivers

The reflex commentary "stocks fell because 10Y hit X%" treats a **downstream price variable as a causal explanation**. Bond yields and equity returns are both endogenous outputs of a deeper set of macro inputs (growth expectations, inflation expectations, term premium, liquidity preference, policy path). Their correlation **changes sign across regimes** — mechanically impossible if one truly caused the other.

**Why it matters**: Building a macro thesis on "yields up → stocks down" — or any fixed-sign rule — is the rooster-crowing-at-sunrise fallacy. The yield/equity correlation has flipped sign multiple times in living memory:

| Period | Dominant driver | Correlation (yield ↑ vs. SPX) |
|---|---|---|
| 1970s–early 1990s | Inflation | **Negative** |
| Mid 1990s–2008 | Growth | **Positive** |
| 2022–2024 | Duration / valuation re-pricing | **Negative** |
| Japan 2013–2023 (YCC) | BOJ administered | **~Zero** |
| Japan 2024–present | YCC exit + governance reform | **Positive** |

A rule that flips sign with the regime is not a causal law — it is co-movement reflecting a shared upstream driver.

**How to apply**:

1. **Never write "X happened because yields moved Y" as a thesis sentence.** Replace it with: "X and yields both moved because the market revised its [growth / inflation / policy] expectation."
2. **Identify the dominant driver before applying any yield/equity rule**:
   - Inflation-dominant (CPI prints leading): yield up = stocks down
   - Growth-dominant (ISM/payrolls leading): yield up = stocks up
   - Policy-dominant (FOMC leading): correlation flips with the surprise direction
   - Liquidity-dominant (QT/QE, TGA, RRP): both move with the liquidity tide
3. **Look at the right yield decomposition**: real yield (10Y TIPS) for valuation anchor, term premium (ACM, Kim-Wright) for risk-off signal, 2s10s slope for regime classification. Don't anchor on headline nominal.
4. `validate_report.py` lints for the bad pattern: `because yields/dollar/oil moved`. Auto-flag as `WEAK_CAUSALITY`.

**When the rule does NOT apply**:
- Auction tail / failed Treasury auction → yield spike reflects real supply/demand imbalance.
- Funding stress (repo blow-up, SVB-style bank run) → front-end yields move because liquidity broke.
- Single-day FOMC surprise → yield + equity share a common cause and same 30-min window.

**Cross-references**:
- Pitfall 3 — event-IV vs demand-IV (the equivalent "check the source before applying" structure for vol)
- `references/frameworks_macro_quant.md` — Dalio regime classification, Soros reflexivity
- Stage 4 (`agents/macro-analyst.md`) — must cite real yield + term premium, not nominal
- `scripts/validate_report.py` — yields-not-causal lint rule
