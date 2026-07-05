---
title: Direction and vega are independent axes — match BOTH to regime
severity: HIGH
appliesTo: stage11, stage18, structure-selection, short-term-report
tags: vega, structure-selection, credit-vs-debit, iv-regime
---

## Direction and vega are independent axes — match BOTH to regime

A bullish view ≠ a bullish structure. Direction (long/short delta) and vega (long/short premium) are **two separate axes** that must each match the current regime. The same directional view can be expressed by structures with opposite vega — picking the wrong vega side is direction-right + structure-wrong, and you can lose money even when direction is correct.

**Why it matters**: Four common bullish structures, four different vega signs:

| Structure | Net delta | Net vega | Net theta |
|---|---|---|---|
| Bull call debit spread | + | **+ (long vega)** | small − |
| Bull put credit spread | + | **− (short vega)** | + |
| Long call | + | + | − |
| Short put | + | − | + |

At **low IVR (<30)**, long vega is favored — IV mean-reverts upward, debit structures gain on both axes. At **high IVR (>70)**, short vega is favored — IV mean-reverts downward, credit structures gain on both axes. **Selecting a short-vega structure at low IV (or vice versa) means you lose on the vega leg even if direction is right.**

**Concrete failure**: ISRG 2026-05-10 — bullish view at IVR 26 → bull put credit spread recommended. Direction correct; vega wrong. Credit collected ($1.35) was suppressed by low IV; max loss ($8.65) fixed by strike distance → 1:6.4 R/R. The corresponding bull call **debit** spread at 455/475 had R/R 1:1.5 and was long vega (IV expansion would have added to the win). Same direction, completely different trade.

**How to apply**:

1. **After picking direction, re-derive the structure from the IV regime — do not skip this step.**
2. The short-term report MUST display direction + vega + asymmetry as 3 explicit axes:
   - Direction: net delta sign matches thesis ✓/✗
   - Vega: long vega at IVR <30, short vega at IVR >70 ✓/✗
   - Asymmetry: see Pitfall 5
3. `compute_scores.py` emits the recommended vega sign per IV regime. Override only with explicit reason (e.g., demand-IV per Pitfall 3).
4. **Cross-check IV classification first** (Pitfall 3): demand-IV inverts the default vega rule.

**When the rule does NOT apply**:
- IVR in 30–70 range (no clear vega edge from IV alone) → vega axis becomes "neutral", direction dominates
- Calendars / diagonals deliberately isolate term-structure vega rather than absolute vega

**Cross-references**:
- Pitfall 3 — IV classification (event vs demand) inverts the vega rule
- Pitfall 5 — asymmetry is the third axis beyond direction + vega
- Stage 11 (`agents/quant-analyst.md`) — 3-axis check enforcement point
- Stage 18 (`agents/equity-report-writer.md`) — short-term report must render all 3 axes
