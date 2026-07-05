---
title: Manipulator-tape names — sell premium, don't buy direction
severity: HIGH
appliesTo: stage11, stage13, high-vol, single-name, structure-selection
tags: manipulator, premium-selling, oscillation-scalp, retail-saturation
---

## Manipulator-tape names — sell premium, don't buy direction

Some high-IV single names trade with heavy market-maker / large-trader pump-dump patterns. Frequent ±3% intraday swings without news, $10–20 AH wicks on thin liquidity, programmatic algo selling on specific keywords. **For these names, premium-selling and oscillation-scalping outperform directional buying.** A correct directional thesis can still lose money in a manipulator tape because the price oscillates faster than your conviction window.

**Why it matters**: Buying calls in these names pays for vol that will be harvested by the next pump-dump cycle. The IV is high not because of an upcoming event but because realized vol is structurally high — and that vol works *against* long premium and *for* short premium. The standard "high IV → sell premium" rule still applies, but the **structure** must accept being range-bound, not directional.

**How to apply**:

1. **Maintain a `tape_class` tag** per company in profile:
   - `institutional` — orderly grind, low overnight gaps, deep liquidity → standard frameworks apply
   - `retail` — high volume, parabolic moves, brittle reversals → use Pitfall 9 (saturation check)
   - **`manipulator`** — frequent ±3% no-news swings, AH wicks, algo-driven oscillation → this rule
   - `lowliquidity` — wide spreads, single-block tape → orderbook framework fails

2. **Initial seed list of manipulator-class names** (expand based on observed behavior):
   - APP, MSTR, COIN, PLTR, DJT, TSLA (occasional)
   - Add when 2+ of: realized 30D vol >70%, mean overnight gap >2.5%, implied/realized ratio <0.85 for 60+ days

3. **Default short-term structure for manipulator class**:
   - Jade Lizard / Iron Condor / Bull Put Spread (sell premium, accept range-bound)
   - Pair with: scalp leveraged proxy (APPX for APP, MSTU for MSTR, etc.) on the oscillation
   - **AVOID**: Long-dated call buying — vol gets harvested out from under you

4. **The conviction-count exception** (Pitfall 5):
   - Manipulator tapes typically score conviction ≤ 3 because no single direction sustains
   - If conviction count somehow reaches ≥4 on a manipulator name (rare), the asymmetry rule still wins — the move overpowers the manipulation

5. **`quant-analyst` Stage 11 emits `tape_class`**; `compute_scores.py` adjusts the recommended structure based on it.

**When the rule does NOT apply**:
- Genuine fundamental catalyst dominates (earnings beat + sector co-move + 3+ channel checks) → conviction count overrides manipulator default
- Tape class is `institutional` or `retail` (different frameworks; this rule does not apply)

**Cross-references**:
- Pitfall 4 — vega rule still applies (sell premium at high IV)
- Pitfall 5 — asymmetry rule overrides manipulator default if conviction ≥ 4
- Pitfall 6 — manipulator names carry high termination hazard (high `q`)
- Pitfall 9 — float saturation often co-occurs with manipulator class
- Stage 11 (`agents/quant-analyst.md`) — emits `tape_class`
- `references/frameworks_behavioral.md` — Soros reflexivity, retail-driven feedback loops
