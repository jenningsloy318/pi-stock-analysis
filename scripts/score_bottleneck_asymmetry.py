#!/usr/bin/env python3
"""Bottleneck Asymmetry Scorer — universal 7-input composite.

Implements the Asymmetry Composite (0-100) defined in
references/frameworks_bottleneck_investing.md.

Industry-agnostic: applies to AI infrastructure, EV/battery materials, robotics,
defense, solar, biopharma, grid equipment, semiconductor capital equipment,
advanced materials, water/utilities — any industry with cascading capacity
constraints.

Inputs (one company at a time, JSON or CLI flags):
  --ticker             TICKER
  --tech-uniqueness    0|1                 (Step 3 element 1)
  --capex-years        FLOAT >= 0          (Step 3 element 2 raw value)
  --top5-buyer-pct     0..100              (Step 3 element 3 raw value)
  --vertical-resist    0|1                 (Step 3 element 4)
  --asymmetry-ratio    FLOAT > 0           (Step 5: mkt_cap / addressable_market_controlled)
  --inst-own-pct       0..100              (Step 4: institutional ownership %)
  --layer-name         STRING              (informational — chain layer)
  --roadmap-theme      STRING              (informational — driving roadmap)

  Geographic dimension (optional — enhances scoring when available):
  --geo-leader         US|JP|KR|CN|TW|EU|OTHER  (dominant country/region)
  --geo-hhi            0..10000            (geographic concentration HHI)
  --geo-risk-flags     JSON_ARRAY          (geopolitical risk flags)
  --geo-policy-support strong_national_priority|moderate_subsidy|weak|none
  --geo-alternatives   INT >= 0            (alternative-country suppliers)

Or --input-json path/to/inputs.json with the same fields.

Output (JSON to --output path or stdout):
  {
    "ticker": ...,
    "layer_name": ...,
    "roadmap_theme": ...,
    "chokepoint_score":   {value: 0-4, gate_pass: bool},
    "asymmetry_ratio":    {value, band: deep|ordinary|full|overpaid},
    "earliness":          {inst_own_pct, band: early|mid|late},
    "components": {
      "chokepoint":       {weight: 27|30, score_0_100, contribution},
      "capex_leadtime":   {weight: 14|15, years, score_0_100, contribution},
      "buyer_concentration": {weight: 14|15, top5_pct, score_0_100, contribution},
      "vertical_resist":  {weight: 9|10, score_0_100, contribution},
      "asymmetry":        {weight: 18|20, ratio, score_0_100, contribution},
      "earliness":        {weight: 8|10, inst_own_pct, score_0_100, contribution},
      "geo_strategic":    {weight: 10, score_0_100, contribution} | null
    },
    "geo_context": {...} | null,
    "composite_0_100": ...,
    "tier": "tier-1" | "strong" | "marginal" | "skip",
    "flags": [...],
    "generated_at": ISO8601
  }

Deterministic. No external API calls. Missing required field → exit 1 with reason.

When geographic inputs are provided, uses 7-dimension model (weights adjusted).
When no geographic inputs, falls back to original 6-dimension model (backward-compatible).

Conformance:
  Hard gate: chokepoint_score < 3 caps composite at 59 (per reference doc).
  Bands per reference doc.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WEIGHTS = {
    "chokepoint": 30,
    "capex_leadtime": 15,
    "buyer_concentration": 15,
    "vertical_resist": 10,
    "asymmetry": 20,
    "earliness": 10,
}

# 7-dimension weights used when geographic inputs are provided
WEIGHTS_WITH_GEO = {
    "chokepoint": 27,
    "capex_leadtime": 14,
    "buyer_concentration": 14,
    "vertical_resist": 9,
    "asymmetry": 18,
    "earliness": 8,
    "geo_strategic": 10,
}

CHOKEPOINT_GATE = 3  # raw score 0-4; must be >= this for tier-1/strong
HARD_CAP_BELOW_GATE = 59  # composite cap if chokepoint < gate


# ---------------------------------------------------------------------------
# Component scorers — each returns 0-100
# ---------------------------------------------------------------------------


def score_chokepoint(raw_0_4: int) -> int:
    """0-4 raw → 0-100. Linear. Gate at >=3 enforced separately at composite."""
    if raw_0_4 < 0 or raw_0_4 > 4:
        raise ValueError(f"chokepoint raw must be 0-4, got {raw_0_4}")
    return int(round(raw_0_4 * 25))  # 0,25,50,75,100


def score_capex_leadtime(years: float) -> int:
    """Saturated above 5 years (per reference doc)."""
    if years < 0:
        raise ValueError(f"capex years must be >= 0, got {years}")
    capped = min(years, 5.0)
    return int(round((capped / 5.0) * 100))


def score_buyer_concentration(top5_pct: float) -> int:
    """Saturated above 80% (per reference doc).

    Below the 60% threshold from Step 3 element 3, score is heavily discounted —
    a layer with diluted buyers is not a chokepoint regardless of other factors.
    """
    if top5_pct < 0 or top5_pct > 100:
        raise ValueError(f"top5_pct must be 0-100, got {top5_pct}")
    if top5_pct < 60:
        # Linear ramp 0-60% → 0-50 score (penalised band)
        return int(round((top5_pct / 60.0) * 50))
    # 60-80% → 50-100, then saturate
    capped = min(top5_pct, 80.0)
    return int(round(50 + ((capped - 60.0) / 20.0) * 50))


def score_vertical_resist(flag: int) -> int:
    """Binary: 0 or 1."""
    if flag not in (0, 1):
        raise ValueError(f"vertical_resist must be 0 or 1, got {flag}")
    return 100 if flag == 1 else 0


def score_asymmetry(ratio: float) -> int:
    """Lower ratio → higher score. Saturated below 0.05 (per reference doc).

    Bands (informational):
      < 0.10  deep      → score 80-100
      0.10-0.50 ordinary → score 40-80
      0.50-1.50 full     → score 10-40
      > 1.50  overpaid   → score 0-10
    """
    if ratio <= 0:
        raise ValueError(f"asymmetry_ratio must be > 0, got {ratio}")
    if ratio <= 0.05:
        return 100
    if ratio <= 0.10:
        # 0.05 → 100, 0.10 → 80
        return int(round(100 - ((ratio - 0.05) / 0.05) * 20))
    if ratio <= 0.50:
        # 0.10 → 80, 0.50 → 40
        return int(round(80 - ((ratio - 0.10) / 0.40) * 40))
    if ratio <= 1.50:
        # 0.50 → 40, 1.50 → 10
        return int(round(40 - ((ratio - 0.50) / 1.00) * 30))
    # > 1.50 → 0-10 cap
    return max(0, int(round(10 - min(ratio - 1.50, 5.0) * 2)))


def score_earliness(inst_own_pct: float) -> int:
    """Lower → higher score. Saturated below 10% (per reference doc)."""
    if inst_own_pct < 0 or inst_own_pct > 100:
        raise ValueError(f"inst_own_pct must be 0-100, got {inst_own_pct}")
    if inst_own_pct <= 10:
        return 100
    if inst_own_pct <= 30:
        # 10 → 100, 30 → 75 (early band)
        return int(round(100 - ((inst_own_pct - 10) / 20.0) * 25))
    if inst_own_pct <= 60:
        # 30 → 75, 60 → 30 (mid band)
        return int(round(75 - ((inst_own_pct - 30) / 30.0) * 45))
    # 60 → 30, 100 → 0 (late band)
    return int(round(30 - ((inst_own_pct - 60) / 40.0) * 30))


def score_geo_strategic(
    geo_hhi: int,
    geo_policy_support: str | None,
    geo_alternatives: int,
    geo_risk_flags: list[str] | None,
) -> int:
    """Geographic strategic score (0-100). Combines concentration risk, policy
    tailwind, alternative scarcity, and geopolitical risk penalty.

    Sub-components:
      concentration_risk: HHI-based (high HHI = high risk = low score)
      policy_tailwind: national priority programs boost score
      alternative_scarcity: fewer alternatives = higher chokepoint value
      risk_penalty: each geo risk flag = -10 (floor at 0)
    """
    # --- concentration_risk (0-100): lower HHI = more diversified = higher score
    if geo_hhi > 5000:
        # 5000 → 30, 10000 → 0  (high concentration = low score)
        concentration_risk = int(round(30 - ((geo_hhi - 5000) / 5000.0) * 30))
    elif geo_hhi > 2500:
        # 2500 → 60, 5000 → 30
        concentration_risk = int(round(60 - ((geo_hhi - 2500) / 2500.0) * 30))
    else:
        # 0 → 100, 2500 → 60
        concentration_risk = int(round(100 - ((geo_hhi) / 2500.0) * 40))

    concentration_risk = max(0, min(100, concentration_risk))

    # --- policy_tailwind (0-100)
    policy_map = {
        "strong_national_priority": 100,
        "moderate_subsidy": 60,
        "weak": 30,
        "none": 0,
    }
    policy_tailwind = policy_map.get(geo_policy_support or "none", 0)

    # --- alternative_scarcity (0-100): fewer alternatives = higher value
    if geo_alternatives == 0:
        alternative_scarcity = 100
    elif geo_alternatives == 1:
        alternative_scarcity = 75
    elif geo_alternatives == 2:
        alternative_scarcity = 50
    else:
        alternative_scarcity = 25

    # --- risk_penalty: each flag = -10
    risk_flags = geo_risk_flags or []
    risk_penalty = len(risk_flags) * 10

    # --- Combined
    raw = (
        concentration_risk * 0.3 + policy_tailwind * 0.3 + alternative_scarcity * 0.3
    ) - risk_penalty

    return max(0, min(100, int(round(raw))))


# ---------------------------------------------------------------------------
# Bands & flags
# ---------------------------------------------------------------------------


def asymmetry_band(ratio: float) -> str:
    if ratio < 0.10:
        return "deep"
    if ratio < 0.50:
        return "ordinary"
    if ratio < 1.50:
        return "full"
    return "overpaid"


def earliness_band(inst_own_pct: float) -> str:
    if inst_own_pct < 30:
        return "early"
    if inst_own_pct < 60:
        return "mid"
    return "late"


def composite_tier(score: int) -> str:
    if score >= 80:
        return "tier-1"
    if score >= 65:
        return "strong"
    if score >= 50:
        return "marginal"
    return "skip"


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


def compute(inputs: dict) -> dict:
    required = [
        "tech_uniqueness",
        "capex_years",
        "top5_buyer_pct",
        "vertical_resist",
        "asymmetry_ratio",
        "inst_own_pct",
    ]
    missing = [k for k in required if inputs.get(k) is None]
    if missing:
        raise ValueError(f"missing required inputs: {missing}")

    # Determine if geographic dimension is active
    geo_hhi = inputs.get("geo_hhi")
    geo_policy_support = inputs.get("geo_policy_support")
    geo_alternatives = inputs.get("geo_alternatives")
    geo_risk_flags = inputs.get("geo_risk_flags")
    geo_leader = inputs.get("geo_leader")

    has_geo = any(
        v is not None for v in [geo_hhi, geo_policy_support, geo_alternatives]
    )

    # Select weight set based on geo availability
    weights = WEIGHTS_WITH_GEO if has_geo else WEIGHTS

    # Step 3 raw score (sum of 4 binary elements; capex >= 2yrs and top5 >= 60% are the binary thresholds)
    cp_raw = (
        int(bool(inputs["tech_uniqueness"]))
        + (1 if inputs["capex_years"] >= 2.0 else 0)
        + (1 if inputs["top5_buyer_pct"] >= 60.0 else 0)
        + int(bool(inputs["vertical_resist"]))
    )

    # Component scores (0-100)
    s_chokepoint = score_chokepoint(cp_raw)
    s_capex = score_capex_leadtime(inputs["capex_years"])
    s_buyer = score_buyer_concentration(inputs["top5_buyer_pct"])
    s_vert = score_vertical_resist(int(bool(inputs["vertical_resist"])))
    s_asym = score_asymmetry(inputs["asymmetry_ratio"])
    s_early = score_earliness(inputs["inst_own_pct"])

    # Geographic score (optional)
    s_geo = None
    if has_geo:
        s_geo = score_geo_strategic(
            geo_hhi=geo_hhi if geo_hhi is not None else 5000,
            geo_policy_support=geo_policy_support,
            geo_alternatives=geo_alternatives if geo_alternatives is not None else 2,
            geo_risk_flags=geo_risk_flags,
        )

    # Weighted composite
    composite = (
        s_chokepoint * weights["chokepoint"]
        + s_capex * weights["capex_leadtime"]
        + s_buyer * weights["buyer_concentration"]
        + s_vert * weights["vertical_resist"]
        + s_asym * weights["asymmetry"]
        + s_early * weights["earliness"]
    )
    if has_geo and s_geo is not None:
        composite += s_geo * weights["geo_strategic"]
    composite = int(round(composite / 100.0))

    flags = []
    gate_pass = cp_raw >= CHOKEPOINT_GATE
    if not gate_pass:
        flags.append(
            f"CHOKEPOINT_GATE_FAIL: raw chokepoint score {cp_raw}/4 < {CHOKEPOINT_GATE} — composite hard-capped at {HARD_CAP_BELOW_GATE}"
        )
        composite = min(composite, HARD_CAP_BELOW_GATE)
    if inputs["asymmetry_ratio"] >= 1.50:
        flags.append(
            "ASYMMETRY_OVERPAID: asymmetry_ratio >= 1.50 — market already paying for upside not yet earned"
        )
    if inputs["inst_own_pct"] >= 60.0:
        flags.append(
            "EARLINESS_LATE: institutional ownership >= 60% — rotation likely already priced in"
        )
    if inputs["capex_years"] < 2.0:
        flags.append(
            "CAPEX_LEADTIME_SHORT: <2 years — chokepoint pricing power may be transient"
        )
    if inputs["top5_buyer_pct"] < 60.0:
        flags.append(
            "BUYER_DILUTED: top-5 buyers <60% — chokepoint customer concentration weak"
        )

    # Geographic flags
    if has_geo:
        if geo_hhi is not None and geo_hhi > 7500:
            flags.append(
                "GEO_EXTREME_CONCENTRATION: geographic HHI > 7500 — single-country dependency risk"
            )
        if geo_alternatives is not None and geo_alternatives == 0:
            flags.append(
                "GEO_NO_ALTERNATIVE: zero alternative-country suppliers — maximum geographic lock-in"
            )

    # --- Supplementary signal adjustment (±10 points max) ---
    # These are optional qualitative signals that adjust the final composite.
    signal_adj = 0
    signal_notes = []

    attention = inputs.get("attention_level")
    narrative = inputs.get("narrative_phase")
    fund_flow = inputs.get("fund_flow_direction")
    inst_trend = inputs.get("inst_trend")
    innovation = inputs.get("innovation_signal")
    hiring = inputs.get("hiring_signal")
    stakeholder = inputs.get("stakeholder_quality")

    # Hidden alpha bonus: low attention + early narrative + money flowing in
    if attention == "low":
        signal_adj += 3
        signal_notes.append("attention=low (+3 hidden alpha)")
    elif attention == "saturated":
        signal_adj -= 5
        signal_notes.append("attention=saturated (-5 likely priced in)")
    elif attention == "high":
        signal_adj -= 2
        signal_notes.append("attention=high (-2 partially priced)")

    if narrative == "unknown" or narrative == "emerging":
        signal_adj += 2
        signal_notes.append(f"narrative={narrative} (+2 early discovery)")
    elif narrative == "consensus":
        signal_adj -= 3
        signal_notes.append("narrative=consensus (-3 widely known)")

    if fund_flow == "strong_inflow":
        signal_adj += 3
        signal_notes.append("fund_flow=strong_inflow (+3 money confirming)")
    elif fund_flow == "inflow":
        signal_adj += 1
        signal_notes.append("fund_flow=inflow (+1)")
    elif fund_flow == "outflow":
        signal_adj -= 2
        signal_notes.append("fund_flow=outflow (-2 money leaving)")

    if inst_trend == "accumulating":
        signal_adj += 2
        signal_notes.append("inst_trend=accumulating (+2 smart money building)")
    elif inst_trend == "distributing":
        signal_adj -= 3
        signal_notes.append("inst_trend=distributing (-3 smart money exiting)")

    if innovation == "strong":
        signal_adj += 2
        signal_notes.append("innovation=strong (+2 moat reinforcing)")
    elif innovation == "weak":
        signal_adj -= 1
        signal_notes.append("innovation=weak (-1 moat may decay)")

    if hiring == "expanding":
        signal_adj += 1
        signal_notes.append("hiring=expanding (+1 demand confirmed)")
    elif hiring == "contracting":
        signal_adj -= 2
        signal_notes.append("hiring=contracting (-2 demand weakening)")

    # Stakeholder quality — strategic endorsement is the strongest signal
    if stakeholder == "strategic_endorsed":
        signal_adj += 4
        signal_notes.append(
            "stakeholder=strategic_endorsed (+4 supply-chain cross-holding confirms chokepoint)"
        )
    elif stakeholder == "smart_money_backed":
        signal_adj += 2
        signal_notes.append(
            "stakeholder=smart_money_backed (+2 top-tier funds position)"
        )
    elif stakeholder == "retail_dominated":
        signal_adj -= 2
        signal_notes.append(
            "stakeholder=retail_dominated (-2 no institutional/strategic validation)"
        )

    # Cap adjustment at ±10
    signal_adj = max(-10, min(10, signal_adj))
    composite = max(0, min(100, composite + signal_adj))

    def _contrib(weight: int, score: int) -> float:
        return round(score * weight / 100.0, 2)

    # Build components dict
    components = {
        "chokepoint": {
            "weight": weights["chokepoint"],
            "score_0_100": s_chokepoint,
            "contribution": _contrib(weights["chokepoint"], s_chokepoint),
        },
        "capex_leadtime": {
            "weight": weights["capex_leadtime"],
            "years": round(inputs["capex_years"], 2),
            "score_0_100": s_capex,
            "contribution": _contrib(weights["capex_leadtime"], s_capex),
        },
        "buyer_concentration": {
            "weight": weights["buyer_concentration"],
            "top5_pct": round(inputs["top5_buyer_pct"], 2),
            "score_0_100": s_buyer,
            "contribution": _contrib(weights["buyer_concentration"], s_buyer),
        },
        "vertical_resist": {
            "weight": weights["vertical_resist"],
            "flag": int(bool(inputs["vertical_resist"])),
            "score_0_100": s_vert,
            "contribution": _contrib(weights["vertical_resist"], s_vert),
        },
        "asymmetry": {
            "weight": weights["asymmetry"],
            "ratio": round(inputs["asymmetry_ratio"], 4),
            "score_0_100": s_asym,
            "contribution": _contrib(weights["asymmetry"], s_asym),
        },
        "earliness": {
            "weight": weights["earliness"],
            "inst_own_pct": round(inputs["inst_own_pct"], 2),
            "score_0_100": s_early,
            "contribution": _contrib(weights["earliness"], s_early),
        },
        "geo_strategic": (
            {
                "weight": weights["geo_strategic"],
                "score_0_100": s_geo,
                "contribution": _contrib(weights["geo_strategic"], s_geo),
            }
            if has_geo and s_geo is not None
            else None
        ),
    }

    # Build geo_context
    geo_context = None
    if has_geo:
        geo_context = {
            "leader": geo_leader,
            "hhi": geo_hhi,
            "risk_flags": geo_risk_flags or [],
            "policy_support": geo_policy_support,
            "alternatives": geo_alternatives,
        }

    return {
        "ticker": inputs.get("ticker"),
        "layer_name": inputs.get("layer_name"),
        "roadmap_theme": inputs.get("roadmap_theme"),
        "chokepoint_score": {"value": cp_raw, "gate_pass": gate_pass},
        "asymmetry_ratio": {
            "value": round(inputs["asymmetry_ratio"], 4),
            "band": asymmetry_band(inputs["asymmetry_ratio"]),
        },
        "earliness": {
            "inst_own_pct": round(inputs["inst_own_pct"], 2),
            "band": earliness_band(inputs["inst_own_pct"]),
        },
        "supplementary_signals": {
            "adjustment": signal_adj,
            "signals": {
                "attention_level": attention,
                "narrative_phase": narrative,
                "fund_flow_direction": fund_flow,
                "inst_trend": inst_trend,
                "innovation_signal": innovation,
                "hiring_signal": hiring,
                "stakeholder_quality": stakeholder,
            },
            "notes": signal_notes,
        },
        "components": components,
        "geo_context": geo_context,
        "composite_0_100": composite,
        "tier": composite_tier(composite),
        "flags": flags,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bottleneck Asymmetry Scorer (0-100 composite)"
    )
    p.add_argument("--ticker")
    p.add_argument("--tech-uniqueness", type=int, choices=[0, 1])
    p.add_argument("--capex-years", type=float)
    p.add_argument("--top5-buyer-pct", type=float)
    p.add_argument("--vertical-resist", type=int, choices=[0, 1])
    p.add_argument("--asymmetry-ratio", type=float)
    p.add_argument("--inst-own-pct", type=float)
    p.add_argument("--layer-name")
    p.add_argument("--roadmap-theme")
    # Supplementary signals (optional — enhance scoring when available)
    p.add_argument(
        "--attention-level",
        choices=["low", "moderate", "high", "saturated"],
        help="Social/retail attention level (low=hidden alpha, saturated=priced in)",
    )
    p.add_argument(
        "--narrative-phase",
        choices=["unknown", "emerging", "accelerating", "consensus"],
        help="News narrative lifecycle phase",
    )
    p.add_argument(
        "--fund-flow-direction",
        choices=["strong_inflow", "inflow", "neutral", "outflow"],
        help="ETF fund flow direction for this layer",
    )
    p.add_argument(
        "--inst-trend",
        choices=["accumulating", "stable", "distributing"],
        help="Institutional 13F quarterly change direction",
    )
    p.add_argument(
        "--innovation-signal",
        choices=["strong", "moderate", "weak"],
        help="Patent/R&D forward-looking signal",
    )
    p.add_argument(
        "--hiring-signal",
        choices=["expanding", "stable", "contracting"],
        help="Hiring activity signal (expansion proxy)",
    )
    p.add_argument(
        "--stakeholder-quality",
        choices=[
            "strategic_endorsed",
            "smart_money_backed",
            "mixed",
            "retail_dominated",
        ],
        help="Stakeholder/investor quality (strategic_endorsed = supply-chain cross-holding)",
    )
    # Geographic dimension (optional — enhances scoring when available)
    geo_group = p.add_argument_group(
        "Geographic dimension (optional — enhances scoring when available)"
    )
    geo_group.add_argument(
        "--geo-leader",
        choices=["US", "JP", "KR", "CN", "TW", "EU", "OTHER"],
        help="Country/region code that dominates this layer",
    )
    geo_group.add_argument(
        "--geo-hhi",
        type=int,
        help="Geographic concentration HHI (0-10000, where 10000 = single country monopoly)",
    )
    geo_group.add_argument(
        "--geo-risk-flags",
        help='JSON array of geopolitical risk flags (e.g., \'["us_export_control", "taiwan_strait"]\')',
    )
    geo_group.add_argument(
        "--geo-policy-support",
        choices=["strong_national_priority", "moderate_subsidy", "weak", "none"],
        help="Policy support level for the dominant country",
    )
    geo_group.add_argument(
        "--geo-alternatives",
        type=int,
        help="Number of alternative-country suppliers (0 = no alternative)",
    )
    p.add_argument(
        "--input-json", help="Read inputs from JSON file (overrides individual flags)"
    )
    p.add_argument("--output", help="Write result JSON to this path (default: stdout)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.input_json:
        path = Path(args.input_json)
        if not path.exists():
            print(f"ERROR: input JSON not found: {path}", file=sys.stderr)
            return 1
        try:
            inputs = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid JSON in {path}: {e}", file=sys.stderr)
            return 1
    else:
        inputs = {
            "ticker": args.ticker,
            "tech_uniqueness": args.tech_uniqueness,
            "capex_years": args.capex_years,
            "top5_buyer_pct": args.top5_buyer_pct,
            "vertical_resist": args.vertical_resist,
            "asymmetry_ratio": args.asymmetry_ratio,
            "inst_own_pct": args.inst_own_pct,
            "layer_name": args.layer_name,
            "roadmap_theme": args.roadmap_theme,
            # Supplementary signals (None if not provided)
            "attention_level": args.attention_level,
            "narrative_phase": args.narrative_phase,
            "fund_flow_direction": args.fund_flow_direction,
            "inst_trend": args.inst_trend,
            "innovation_signal": args.innovation_signal,
            "hiring_signal": args.hiring_signal,
            "stakeholder_quality": args.stakeholder_quality,
            # Geographic dimension (None if not provided)
            "geo_leader": args.geo_leader,
            "geo_hhi": args.geo_hhi,
            "geo_risk_flags": (
                json.loads(args.geo_risk_flags) if args.geo_risk_flags else None
            ),
            "geo_policy_support": args.geo_policy_support,
            "geo_alternatives": args.geo_alternatives,
        }

    try:
        result = compute(inputs)
    except (ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    payload = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload + "\n")
    else:
        print(payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
