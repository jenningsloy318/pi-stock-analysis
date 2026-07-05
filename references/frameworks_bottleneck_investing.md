# Bottleneck Investing — Universal Framework

A roadmap-anchored, top-down chain-walk methodology for finding **mispriced chokepoint companies** ahead of institutional rotation. Industry-agnostic: applies to AI infrastructure, EV/battery materials, robotics, defense, solar, biopharma, grid equipment, semiconductor capital equipment, advanced materials, water/utilities — any industry where capacity constraints cascade upstream.

The premise: **physical bottlenecks resolve sequentially, not simultaneously**. When the most-visible chokepoint (Layer N) gets resolved by capacity build-out, the marginal constraint moves up to Layer N-1 (less visible, smaller market, more concentrated supply). Walk the chain from finished product → raw inputs to find the layer where mkt-cap-controlled-by-investor-coverage is mismatched against the addressable-market-the-company-controls.

## Why this is non-overlapping with existing analysis

| Existing framework | Asks | Bottleneck framework asks |
|--------------------|------|--------------------------|
| DCF / valuation | What are FCFs worth today? | What chokepoint is the market funding next? |
| Porter Five Forces | How attractive is the industry? | Which layer cannot be replicated within 3 years? |
| Supply chain (concentration) | Where is risk? | Where is **pricing power** durable for 18-36 months? |
| Quant momentum | What is the price doing? | Is institutional ownership still <30% (early)? |

This framework is a **complement**, not a replacement. It identifies *which company in a chain to study*, then the existing 11-stage deep-dive does the actual work.

---

## The 5-Step Methodology

### Step 1 — Anchor the Roadmap

Pick a **demand signal with a published multi-year capacity roadmap**. Examples (illustrative — not exhaustive):

- AI/data-center capex (hyperscaler $-spend forecasts)
- EV unit production targets (national EV mandates, automaker capex)
- Renewable energy buildout (IEA / national net-zero plans)
- Defense procurement programs (DoD FYDP, NATO 2% mandates)
- Drug pipeline approvals (FDA priority review, breakthrough designations)
- Semiconductor wafer-start additions (SEMI / foundry capex)
- Grid expansion (utility capex, IRA transmission allocations)
- Robotics deployment targets (industry roadmaps, national plans)

Required: roadmap must be **quantitative and dated** (e.g., "+X GW by 2028", "+Y wafer starts/month by 2027"), not aspirational.

Output: `roadmap_anchor.json` — `{theme, time_horizon_years, demand_growth_pct, key_milestones[], roadmap_sources[]}`.

### Step 2 — Reverse-Decompose the Chain

Working **backwards** from finished product to raw input, list every distinct value-add layer. For each layer, capture:

- **Layer name** (e.g., "finished module", "subassembly", "key component", "specialty material", "raw substrate")
- **What it does** (1 line — the function it adds to the chain)
- **Visibility** (high = retail-discussed / sell-side covered; medium = trade press; low = industry insiders only)
- **Public companies in the layer** (tickers + market cap)
- **Concentration** (HHI or "top-3 share %" if disclosed)

Output: `chain_decomposition.json` — list of layers, ordered from finished-product (Layer 1) to raw-substrate (Layer N).

A typical industrial chain has 5-9 layers. Stop walking upstream when you reach a **commodity** (deep liquid market, no pricing power) — that is past the chokepoint zone.

### Step 3 — Verify Chokepoint (4-Element Checklist)

For each layer, score 0–4 on the chokepoint checklist. A layer is a **true chokepoint** only if it scores **3 or 4**.

1. **Tech uniqueness** (0/1): Is the production process protected by IP, trade secret, or accumulated process know-how that takes 5+ years to replicate from scratch? *No → 0. Yes (proven unique) → 1.*
2. **Capex lead-time ≥ 2 years** (0/1): Does adding meaningful new capacity require 2+ years of build time (greenfield fab, specialty crystal furnace, large-aperture lithography tool, certified clean-room, etc.)? *<2 years → 0. ≥2 years → 1.*
3. **Customer concentration** (0/1): Are top-5 buyers ≥ 60% of revenue (i.e., would-be substitutes can't realistically peel off this customer base)? *<60% → 0. ≥60% → 1.*
4. **Vertical-integration resistance** (0/1): Have downstream customers attempted to vertically integrate or dual-source and failed (or never attempted because cost-prohibitive)? *Successful internal program exists → 0. No successful program → 1.*

A layer scoring **0–2** is a commodity-leaning intermediate — pricing power is short-lived and any current margins compress quickly. **Score 3** = real chokepoint. **Score 4** = textbook chokepoint.

Output: per-layer `chokepoint_score` 0-4, plus a `chokepoint_layers` list of all layers ≥ 3.

### Step 4 — Frontrun Institutional Rotation

The **edge** is buying chokepoint operators **before** the rotation arrives. Two signals:

- **Coverage gap**: The chokepoint layer has fewer than 3 sell-side initiations or fewer than 5 buy-side institutional holders > 1% — i.e., institutions haven't rotated in yet.
- **Time-arbitrage signal**: Use **institutional ownership %** as an "earliness" proxy:
  - Inst-own < 30% → Early (1-2 years before consensus rotation). Lowest reflexivity, highest asymmetry.
  - Inst-own 30-60% → Mid (rotation underway, but mid-cycle). Asymmetry decaying.
  - Inst-own > 60% → Late (rotation already priced in). Asymmetry largely realized.

Output: per-candidate `inst_own_pct`, `coverage_count`, `earliness_band`.

### Step 5 — Asymmetry Valuation

The valuation question is **not** "what is the DCF"; it is "**how big is the market this company controls relative to its market cap?**". Compute:

```
asymmetry_ratio = market_cap_usd / addressable_market_controlled_usd
```

Where `addressable_market_controlled` = company's defensible share of the chokepoint layer's revenue (today + reasonable 3-yr expansion *given* its stated capex).

Interpretation (heuristic, not a hard rule):

- **< 0.10** = deep asymmetry. Market cap is < 10% of the value the company will route through its chokepoint over the rotation cycle.
- **0.10 – 0.50** = ordinary asymmetry. Some upside, but already partially recognized.
- **0.50 – 1.50** = full recognition. Risk-reward is symmetric.
- **> 1.50** = market is paying for upside not yet earned. Avoid.

This ratio is **not** a substitute for traditional valuation — it is an **earliness/recognition gauge**. Always cross-check with the existing Stage 10 multi-method DCF/comps before sizing a position.

Output: per-candidate `asymmetry_ratio`, `asymmetry_band` (deep/ordinary/full/overpaid).

---

## The Composite Bottleneck Score (0-100)

Combine into a single **Asymmetry Composite** (used by `scripts/score_bottleneck_asymmetry.py`):

| Input | Weight | Notes |
|-------|--------|-------|
| Chokepoint score (0-4 from Step 3) | 30% | Hard gate: raw chokepoint score < 3 → composite hard-capped at 59 (matches scorer's `HARD_CAP_BELOW_GATE`). |
| Capex lead-time (years) | 15% | Saturated above 5 years. |
| Customer concentration (top-5 %) | 15% | Saturated above 80%. |
| Vertical-integration resistance (0/1) | 10% | Binary. |
| Asymmetry ratio (Step 5) | 20% | Lower ratio → higher score. Saturated below 0.05. |
| Institutional ownership % (Step 4) | 10% | Lower → higher score. Saturated below 10%. |

Bands:
- **80-100**: Tier-1 conviction candidate (rare). Pair with Stage 16 deep-dive.
- **65-79**: Strong candidate. Promote to watchlist.
- **50-64**: Marginal — needs catalyst clarity (Stage 14) before sizing.
- **< 50**: Skip.

The scorer is deterministic, no hidden ML — see `scripts/score_bottleneck_asymmetry.py`.

---

## Rotation Discipline (Risk Management)

Bottleneck rotations decay. The **same** company that scored 85 in early-cycle can score 45 mid-cycle as institutional ownership crosses 60% and asymmetry compresses below 0.5. Recompute the Asymmetry Composite **every quarter** and rotate out when:

- Composite drops below 50, OR
- Asymmetry ratio crosses above 1.0, OR
- Institutional ownership crosses 60% (late band) **and** capacity additions in the layer are confirmed (chokepoint resolving).

Bottleneck investing is **not** buy-and-hold. It is a sequenced rotation across layers as each is resolved.

---

## Validation Gates (mandatory in all walk runs)

1. **Roadmap anchor cited** — at least one quantitative dated source (regulatory filing, industry consortium, gov't plan).
2. **Chain decomposed to ≥ 5 layers** with public companies named per layer (or "no public exposure" explicitly noted).
3. **Chokepoint scored** for every layer with the 4-element checklist.
4. **At least one layer scores ≥ 3** — otherwise the chain has no investable bottleneck right now (return "no chokepoint identified, retest in 6 months").
5. **Asymmetry composite computed** for every named candidate via `score_bottleneck_asymmetry.py` (no hand-eyeballed scores).
6. **Coverage gap and earliness band reported** for every candidate.
7. **Cross-link to existing analysis**: every candidate that proceeds to deep-dive must run the standard 11-stage company analysis (Stages 5-15) — bottleneck score is an *additional* signal, not a replacement.

---

## Failure modes to avoid

- **Story stocks dressed as chokepoints**: A high-narrative ticker with no chokepoint score ≥ 3 is not a bottleneck. The 4-element checklist is the gate.
- **Over-fitting to one roadmap**: A candidate that passes asymmetry only under one roadmap scenario is fragile. Cross-check that the chokepoint matters under at least two independent demand drivers (e.g., AI compute *and* defense electronics both pulling the same substrate).
- **Confusing concentration with chokepoint**: Single-source ≠ chokepoint. Single-source + 2+ year capex lead time + IP moat = chokepoint. Single-source alone is just risk.
- **Buying after institutional rotation**: If Inst-own > 60%, the asymmetry has been claimed. Use the standard pipeline instead.

---

## Stage integration map

| Stage | Existing role | Bottleneck addition |
|-------|---------------|---------------------|
| 7 (industry-analyst) | Porter, TAM, moat | **Step 1 (roadmap anchor)** for the company's industry. |
| 8 (supply-chain-analyst) | Tier 1-3 mapping, HHI, chokepoints | **Step 2-3 (chain decomposition + chokepoint scoring)**. Run `score_bottleneck_asymmetry.py` per candidate. |
| 10 (quant-analyst) | DCF, comps, SOTP | **Step 5 (asymmetry ratio)** — read scorer output, fold into valuation summary. |

A new dedicated agent `roadmap-walker` performs the full top-down walk in `walk` mode (triggered via `--mode walk THEME`) without going through the per-company deep-dive.
