#!/usr/bin/env python3
"""Alpha Elasticity — Serenity-Alpha demand-to-financial-line transmission scoring.

Source framework: references/serenity/serenity-alpha.md.

For a company under a thematic / catalyst-driven thesis, this script computes:

  alpha_elasticity = incremental_demand_impact_usd / current_company_scale_usd

Then scores 7 dimensions (1-5 each):
  - demand_certainty       (is demand already observable?)
  - transmission_clarity   (can demand clearly flow to revenue line?)
  - business_purity        (% of company exposed to this demand vector)
  - market_cap_elasticity  (small-cap → high impact-to-scale ratio)
  - market_neglect         (is the market mislabeling the company?)
  - verification_speed     (will filings confirm in 1-4 quarters?)
  - downside_risk          (severity of the bear case)

Composite alpha-rank 0-100. Categories:
  HIGH_ELASTICITY_ALPHA      — small, pure, near-term verifiable, market mislabeled
  MODERATE_ELASTICITY_ALPHA  — solid thesis but transmission distance is longer
  WATCH_ONLY                 — demand real but no clear transmission yet
  NARRATIVE_ONLY             — talk-only, no observable demand change

Usage:
    analyze_alpha_elasticity.py raw-data.json \
        --incremental-demand-usd 500_000_000 \
        --business-purity 0.40 \
        --verification-quarters 2 \
        --market-mislabel "currently labeled traditional industrial; becoming AI infrastructure play" \
        --output alpha_elasticity.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def score_demand_certainty(observed_demand_evidence_count, has_management_confirmation):
    """1-5 based on # of observable evidence points."""
    score = 1
    if observed_demand_evidence_count >= 1: score = 2
    if observed_demand_evidence_count >= 3: score = 3
    if observed_demand_evidence_count >= 5: score = 4
    if observed_demand_evidence_count >= 5 and has_management_confirmation: score = 5
    return score


def score_transmission_clarity(transmission_steps, named_revenue_line):
    """Fewer steps + named revenue line = clearer."""
    if not named_revenue_line:
        return 1
    if transmission_steps == 1: return 5
    if transmission_steps == 2: return 4
    if transmission_steps == 3: return 3
    if transmission_steps == 4: return 2
    return 1


def score_business_purity(purity_pct):
    """purity_pct = % of company revenue exposed to the demand vector."""
    if purity_pct is None: return 3
    if purity_pct >= 0.70: return 5
    if purity_pct >= 0.40: return 4
    if purity_pct >= 0.20: return 3
    if purity_pct >= 0.10: return 2
    return 1


def score_market_cap_elasticity(elasticity_ratio):
    """elasticity = incremental_demand / current_scale.
    > 0.30 = transformative
    """
    if elasticity_ratio is None: return 3
    if elasticity_ratio >= 0.50: return 5
    if elasticity_ratio >= 0.20: return 4
    if elasticity_ratio >= 0.10: return 3
    if elasticity_ratio >= 0.03: return 2
    return 1


def score_market_neglect(mislabel_text, analyst_coverage_count):
    if not mislabel_text or len(mislabel_text.strip()) < 10:
        if analyst_coverage_count is None: return 3
        if analyst_coverage_count <= 3:  return 4
        if analyst_coverage_count <= 8:  return 3
        return 2
    base = 3
    if analyst_coverage_count is not None:
        if analyst_coverage_count <= 3:  base += 2
        elif analyst_coverage_count <= 8:  base += 1
    return min(5, base)


def score_verification_speed(quarters_to_verification):
    if quarters_to_verification is None: return 3
    if quarters_to_verification <= 1: return 5
    if quarters_to_verification <= 2: return 4
    if quarters_to_verification <= 4: return 3
    if quarters_to_verification <= 8: return 2
    return 1


def score_downside_risk(downside_pct):
    """Inverse: lower downside = higher score."""
    if downside_pct is None: return 3
    if downside_pct <= 0.15: return 5
    if downside_pct <= 0.30: return 4
    if downside_pct <= 0.50: return 3
    if downside_pct <= 0.70: return 2
    return 1


def categorize(composite, dimensions):
    if dimensions["demand_certainty"] <= 1:
        return "NARRATIVE_ONLY"
    if dimensions["transmission_clarity"] <= 2 and composite < 50:
        return "WATCH_ONLY"
    if composite >= 75 and dimensions["business_purity"] >= 4 and dimensions["market_cap_elasticity"] >= 4:
        return "HIGH_ELASTICITY_ALPHA"
    if composite >= 55:
        return "MODERATE_ELASTICITY_ALPHA"
    return "WATCH_ONLY"


def main():
    parser = argparse.ArgumentParser(description="Serenity-Alpha elasticity scoring")
    parser.add_argument("input", help="Path to raw-data.json (used to pull current scale)")
    parser.add_argument("--output", help="Output file path (default: stdout)")

    # User-supplied alpha-thesis inputs
    parser.add_argument("--incremental-demand-usd", type=float,
                        help="Estimated incremental demand USD from the catalyst/news")
    parser.add_argument("--business-purity", type=float,
                        help="Fraction of revenue exposed to demand vector (0-1)")
    parser.add_argument("--transmission-steps", type=int, default=2,
                        help="Number of supply-chain hops from demand source to revenue (1-5)")
    parser.add_argument("--named-revenue-line", action="store_true", default=True,
                        help="Whether the affected revenue line is identified")
    parser.add_argument("--demand-evidence-count", type=int, default=0,
                        help="Number of observable demand-confirmation points (filings, calls, orders)")
    parser.add_argument("--management-confirmation", action="store_true", default=False,
                        help="Has management confirmed the demand driver unprompted")
    parser.add_argument("--analyst-coverage-count", type=int,
                        help="Number of sell-side analysts covering the name")
    parser.add_argument("--market-mislabel", default="",
                        help="Text describing what market labels vs what it could become")
    parser.add_argument("--verification-quarters", type=int,
                        help="Quarters until filings can confirm/reject the thesis")
    parser.add_argument("--downside-pct", type=float,
                        help="Estimated downside in bear case (decimal, e.g. 0.30 = minus 30 percent)")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    info = raw.get(ticker, {}).get("info", {}) or {}

    current_revenue = info.get("totalRevenue")
    current_mcap = info.get("marketCap")

    elasticity_ratio = None
    if args.incremental_demand_usd and current_revenue:
        elasticity_ratio = args.incremental_demand_usd / current_revenue

    dims = {
        "demand_certainty":      score_demand_certainty(args.demand_evidence_count, args.management_confirmation),
        "transmission_clarity":  score_transmission_clarity(args.transmission_steps, args.named_revenue_line),
        "business_purity":       score_business_purity(args.business_purity),
        "market_cap_elasticity": score_market_cap_elasticity(elasticity_ratio),
        "market_neglect":        score_market_neglect(args.market_mislabel, args.analyst_coverage_count),
        "verification_speed":    score_verification_speed(args.verification_quarters),
        "downside_risk":         score_downside_risk(args.downside_pct),
    }

    # Weighted composite 0-100. Demand+transmission+purity are core; rest amplify.
    weights = {
        "demand_certainty":      0.20,
        "transmission_clarity":  0.18,
        "business_purity":       0.16,
        "market_cap_elasticity": 0.16,
        "market_neglect":        0.10,
        "verification_speed":    0.12,
        "downside_risk":         0.08,
    }
    composite = sum((dims[k] / 5.0) * 100 * weights[k] for k in dims)
    composite = round(composite, 1)
    category = categorize(composite, dims)

    result = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "methodology": "Serenity-Alpha elasticity composite: 7 dimensions (1-5) weighted to 0-100. alpha_elasticity = incremental_demand / current_revenue. Categories: HIGH_ELASTICITY_ALPHA / MODERATE_ELASTICITY_ALPHA / WATCH_ONLY / NARRATIVE_ONLY. Source: references/serenity/serenity-alpha.md.",
        "company_scale": {
            "current_revenue_usd": current_revenue,
            "current_market_cap_usd": current_mcap,
        },
        "thesis_inputs": {
            "incremental_demand_usd": args.incremental_demand_usd,
            "business_purity_pct": args.business_purity,
            "transmission_steps": args.transmission_steps,
            "demand_evidence_count": args.demand_evidence_count,
            "management_confirmation": args.management_confirmation,
            "analyst_coverage_count": args.analyst_coverage_count,
            "market_mislabel_text": args.market_mislabel,
            "verification_quarters": args.verification_quarters,
            "downside_pct": args.downside_pct,
        },
        "alpha_elasticity_ratio": elasticity_ratio,
        "dimensions_1_5": dims,
        "dimension_weights": weights,
        "composite_0_100": composite,
        "category": category,
        "interpretation": {
            "HIGH_ELASTICITY_ALPHA":     "Small, pure, near-term-verifiable, market-mislabeled candidate. Highest-conviction alpha bucket.",
            "MODERATE_ELASTICITY_ALPHA": "Solid thesis but either longer transmission, lower purity, or slower verification.",
            "WATCH_ONLY":                "Demand may be real, but transmission to this specific name is unclear. Watchlist.",
            "NARRATIVE_ONLY":            "No observable demand change yet — story-only. Do not size.",
        }[category],
        "notes": [],
    }

    if elasticity_ratio is None:
        result["notes"].append("No incremental_demand_usd or revenue — elasticity ratio defaulted to neutral.")
    if not args.market_mislabel:
        result["notes"].append("No market-mislabel text — market-neglect score limited.")
    if args.verification_quarters is None:
        result["notes"].append("No verification window specified — verification-speed defaulted to neutral.")

    out_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(out_json)
    else:
        print(out_json)
    sys.exit(0)


if __name__ == "__main__":
    main()
