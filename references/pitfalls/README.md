# Equity Research Pitfalls Library

Lazy-loaded analytical biases and methodology errors specific to multi-horizon equity research. Inspired by `himself65/trade-skills` pitfall pattern; adapted for our 25-stage analysis pipeline.

**Purpose**: Codify failure modes as first-class artifacts so post-mortem learnings persist across analyses and the validator can reference them.

**Loading rule**: Read individual files only when relevant. The "Quick Lookup" table below routes by stage / scenario.

## Index

| # | Severity | Title | File | Stage(s) |
|---|----------|-------|------|----------|
| 1 | HIGH | Single channel-check is a sample, not a population | `01-channel-check-sample-bias.md` | 13, 5 |
| 2 | HIGH | Bond yields don't cause equity moves — both downstream of macro drivers | `02-yields-not-causal.md` | 4, 5 |
| 3 | HIGH | Elevated IV without near-term event = demand-driven, not event-driven | `03-iv-event-vs-demand.md` | 11 |
| 4 | HIGH | Direction and vega are independent axes — match BOTH to regime | `04-direction-vega-asymmetry.md` | 11, 18 |
| 5 | HIGH | Capped-upside structures forbidden in high-conviction setups | `05-capped-upside-vs-conviction.md` | 11, 18 |
| 6 | HIGH | Discount rate = time + termination hazard; high-q names cap exit threshold | `06-hazard-rate-discounting.md` | 16, 17 |
| 7 | MEDIUM | "Priced in" is a percentage, not yes/no | `07-priced-in-percentage.md` | 14 |
| 8 | HIGH | Manipulator-tape names — sell premium, don't buy direction | `08-manipulator-tape.md` | 11, 13 |
| 9 | MEDIUM | Float / social saturation is a contrarian top signal | `09-float-saturation.md` | 13 |
| 10 | HIGH | DCF terminal value dominates — sensitivity is mandatory | `10-dcf-terminal-sensitivity.md` | 10 |
| 11 | MEDIUM | Stale data without [STALE] flag silently corrupts every downstream score | `11-stale-data-not-flagged.md` | All |
| 12 | MEDIUM | Single-framework anchoring — Buffett-only or Dalio-only is incomplete | `12-single-framework-anchoring.md` | 17, 18 |
| 13 | HIGH | Post-earnings momentum continuation overrides intraday fade pattern when 3+/4 confirmed | `13-post-earnings-momentum-vs-fade.md` | 14 |

## Quick Lookup by Stage

- **Stage 1 / Data collection**: 11
- **Stage 4 (macro)**: 2, 11
- **Stage 5–6 (fundamentals + forensics)**: 1, 11
- **Stage 10 (valuation)**: 10, 11
- **Stage 11 (quant / market regime)**: 3, 4, 5, 8, 11
- **Stage 13 (alt data)**: 1, 8, 9
- **Stage 14 (catalysts)**: 7, 11, 13
- **Stage 16 (scoring)**: 6, 12
- **Stage 17–18 (report writing)**: 6, 12
- **Short-term horizon report**: 3, 4, 5, 8

## Quick Lookup by Scenario

- **About to claim "IV crush coming"** → MANDATORY: 3, 4 (pull catalyst clock + flow first)
- **About to recommend Jade Lizard / Iron Condor / Calendar / Diagonal** → MANDATORY: 4, 5 (run bull-conviction count first)
- **Channel-check-driven thesis revision** → 1 (need 2–3 independent sources)
- **Long-term price target on distressed / high-vol single name** → 6 (decompose discount rate; distressed names → book sooner)
- **DCF terminal multiple ≥40% of equity value** → 10 (sensitivity table mandatory)
- **Macro narrative cites yields as cause** → 2 (rewrite as both downstream of upstream driver)
- **Stock with KOL / Reddit / fintwit saturation** → 9 (marginal-bull pool drying)
- **Catalyst calendar with binary event** → 7 (estimate priced-in %, not yes/no)
- **Just-printed earnings, considering fade call** → MANDATORY: 13 (run 4-factor gate first)
- **Manipulator-tape candidate (APP/MSTR/COIN/PLTR/DJT)** → 8 (sell premium, never naked directional)
- **Single-framework conviction (e.g., "Buffett says undervalued")** → 12 (require ≥2 frameworks to converge)
- **Critical metric flagged [STALE]** → 11 (BLOCK report; refresh or annotate)

## Adding a New Pitfall

1. Copy `_template.md` → `NN-slug.md` (next sequential number)
2. Fill out frontmatter (`title`, `severity`, `appliesTo`, `tags`)
3. Write rule + why it matters + how to apply + concrete failure case
4. Reference relevant case study if available
5. Add row to the Index table above; update Quick Lookup tables

**File-naming convention**: `NN-kebab-case-slug.md` where NN is zero-padded sequential. Once assigned, NN is permanent (linked from validator + agents).
