#!/usr/bin/env python3
"""Bayesian Intrinsic Growth — probabilistic 3-5yr growth hypothesis with priors.

Source framework: references/serenity/bayesian-intrinsic-growth.md.

Maintains 5 growth hypotheses with prior probabilities, updates them from observable
evidence (revenue history, margin trend, TAM CAGR, market-share direction, valuation
percentile, FOMO signals), then compares the posterior-weighted intrinsic growth rate
to the market-IMPLIED growth rate derived from current valuation.

Hypotheses (3-5yr revenue CAGR):
  H1 STAGNANT      0-5%
  H2 MODERATE      5-15%
  H3 STRONG        15-25%
  H4 ACCELERATING  25-40%
  H5 EXPLOSIVE     40%+

Output:
  - posterior probabilities for each hypothesis
  - posterior-weighted intrinsic growth rate (expected CAGR)
  - market-implied growth (rough reverse-DCF from EV/Sales × terminal multiple assumption)
  - gap = intrinsic - implied (positive = market is underpricing growth)
  - FOMO score 0-100 (high = price moved more than fundamentals justify)

Usage:
    compute_bayesian_growth.py raw-data.json --output bayesian_growth.json
    compute_bayesian_growth.py raw-data.json --tam-cagr 0.18 --recent-price-return-1y 0.85
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone


HYPOTHESES = [
    {"id": "H1", "label": "STAGNANT",     "cagr_min": 0.00, "cagr_max": 0.05, "midpoint": 0.025},
    {"id": "H2", "label": "MODERATE",     "cagr_min": 0.05, "cagr_max": 0.15, "midpoint": 0.10},
    {"id": "H3", "label": "STRONG",       "cagr_min": 0.15, "cagr_max": 0.25, "midpoint": 0.20},
    {"id": "H4", "label": "ACCELERATING", "cagr_min": 0.25, "cagr_max": 0.40, "midpoint": 0.325},
    {"id": "H5", "label": "EXPLOSIVE",    "cagr_min": 0.40, "cagr_max": 0.80, "midpoint": 0.55},
]


def neutral_prior():
    """Flat prior across the 5 hypotheses, biased slightly toward MODERATE-STRONG."""
    return {"H1": 0.10, "H2": 0.30, "H3": 0.30, "H4": 0.20, "H5": 0.10}


def normalize(d: dict) -> dict:
    total = sum(d.values())
    if total <= 0:
        return d
    return {k: v / total for k, v in d.items()}


def likelihood_for_revenue_history(observed_cagr):
    """P(observed CAGR | hypothesis) — Gaussian-ish bump around hypothesis midpoint."""
    if observed_cagr is None:
        return {h["id"]: 1.0 for h in HYPOTHESES}
    out = {}
    for h in HYPOTHESES:
        mid = h["midpoint"]
        sigma = 0.08  # tolerance band
        likelihood = math.exp(-((observed_cagr - mid) ** 2) / (2 * sigma * sigma))
        out[h["id"]] = max(likelihood, 0.05)  # floor
    return out


def likelihood_for_tam_cagr(tam_cagr):
    """A high industry TAM CAGR boosts higher hypotheses."""
    if tam_cagr is None:
        return {h["id"]: 1.0 for h in HYPOTHESES}
    out = {}
    for h in HYPOTHESES:
        if tam_cagr >= h["cagr_min"] - 0.05:
            out[h["id"]] = 1.0 + min((tam_cagr - h["midpoint"]) * 2.0, 0.5)
        else:
            out[h["id"]] = max(0.1, 1.0 - (h["midpoint"] - tam_cagr) * 3.0)
    return out


def likelihood_for_margin_trend(margin_now, margin_3y_ago):
    """Margin expansion supports higher hypotheses (operating leverage)."""
    if margin_now is None or margin_3y_ago is None:
        return {h["id"]: 1.0 for h in HYPOTHESES}
    delta = margin_now - margin_3y_ago
    out = {}
    for h in HYPOTHESES:
        if h["midpoint"] > 0.15:  # strong+ hypotheses
            out[h["id"]] = 1.0 + max(min(delta * 4.0, 0.5), -0.4)
        else:
            out[h["id"]] = 1.0 - delta * 2.0
            out[h["id"]] = max(0.3, min(1.5, out[h["id"]]))
    return out


def compute_market_implied_growth(inputs: dict, years: int = 5):
    """Rough reverse-DCF: what revenue CAGR justifies current EV/Sales × terminal multiple?

    Simple model: assume terminal EV/Sales = 4x (a generic "mature growth" exit multiple).
    Solve for CAGR such that current EV / future revenue ≈ terminal multiple.
        EV = revenue_now × (1+g)^years × terminal_multiple
        (1+g) = (EV / (revenue_now × terminal_multiple)) ^ (1/years)
    """
    ev_sales = inputs.get("ev_sales")
    if ev_sales is None or ev_sales <= 0:
        return None
    terminal_multiple = 4.0
    ratio = ev_sales / terminal_multiple
    if ratio <= 0:
        return None
    return ratio ** (1 / years) - 1


def compute_fomo_score(price_return_1y, eps_cagr_pct, revenue_cagr_pct):
    """FOMO = % by which price return exceeds fundamental growth, capped 0-100."""
    if price_return_1y is None:
        return None
    fundamental = eps_cagr_pct or revenue_cagr_pct or 0.10
    gap = price_return_1y - fundamental
    fomo_raw = max(0, gap) * 100
    return min(100, int(round(fomo_raw)))


def extract_inputs(raw: dict, args) -> dict:
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    c = raw.get(ticker, {})
    info = c.get("info", {}) or {}
    annual = c.get("annual", {}) or {}

    revenue_cagr_pct = info.get("revenueGrowth")
    eps_cagr_pct = info.get("earningsGrowth")

    # 3-5yr historical revenue CAGR from annual
    ann_rev = annual.get("revenue") or []
    hist_cagr = None
    try:
        vals = [float(x.get("value", x) if isinstance(x, dict) else x) for x in ann_rev[-5:] if x is not None]
        if len(vals) >= 3 and vals[0] > 0:
            years = len(vals) - 1
            hist_cagr = (vals[-1] / vals[0]) ** (1 / years) - 1
    except (ValueError, TypeError, ZeroDivisionError):
        pass

    margin_now = info.get("operatingMargins")

    revenue = info.get("totalRevenue")
    ev = info.get("enterpriseValue")
    ev_sales = (ev / revenue) if (ev and revenue) else None

    return {
        "ticker": ticker,
        "revenue_cagr_recent": revenue_cagr_pct,
        "revenue_cagr_historical": hist_cagr,
        "eps_cagr_pct": eps_cagr_pct,
        "margin_now": margin_now,
        "tam_cagr": args.tam_cagr,
        "price_return_1y": args.recent_price_return_1y,
        "revenue": revenue,
        "ev": ev,
        "ev_sales": ev_sales,
    }


def main():
    parser = argparse.ArgumentParser(description="Bayesian intrinsic growth valuation")
    parser.add_argument("input", help="Path to raw-data.json from fetch_financials.py")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--tam-cagr", type=float, help="Industry TAM CAGR (decimal)")
    parser.add_argument("--recent-price-return-1y", type=float,
                        help="1y price return for FOMO calc (decimal, e.g. 0.85 = +85 percent)")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)

    inputs = extract_inputs(raw, args)
    prior = neutral_prior()
    posteriors = dict(prior)

    # Sequential Bayesian update
    update_steps = []
    for name, likelihoods in [
        ("revenue_history", likelihood_for_revenue_history(inputs["revenue_cagr_historical"])),
        ("recent_revenue", likelihood_for_revenue_history(inputs["revenue_cagr_recent"])),
        ("tam_cagr", likelihood_for_tam_cagr(inputs["tam_cagr"])),
    ]:
        posteriors = {h_id: posteriors[h_id] * likelihoods[h_id] for h_id in posteriors}
        posteriors = normalize(posteriors)
        update_steps.append({"step": name, "posteriors": dict(posteriors)})

    intrinsic_cagr = sum(posteriors[h["id"]] * h["midpoint"] for h in HYPOTHESES)
    implied_growth = compute_market_implied_growth(inputs)
    gap = (intrinsic_cagr - implied_growth) if implied_growth is not None else None
    fomo = compute_fomo_score(inputs["price_return_1y"], inputs["eps_cagr_pct"], inputs["revenue_cagr_recent"])

    verdict = "INSUFFICIENT_DATA"
    if implied_growth is not None:
        if gap > 0.05:
            verdict = "UNDERPRICED_GROWTH"   # intrinsic > implied by 5pp+
        elif gap < -0.05:
            verdict = "OVERPRICED_GROWTH"
        else:
            verdict = "FAIRLY_PRICED"

    result = {
        "ticker": inputs["ticker"],
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "methodology": "Bayesian intrinsic growth: prior over 5 CAGR hypotheses → sequential update from revenue history, recent growth, and TAM. Posterior-weighted CAGR vs market-implied (reverse-DCF on EV/Sales). Source: references/serenity/bayesian-intrinsic-growth.md.",
        "inputs": inputs,
        "prior": prior,
        "update_steps": update_steps,
        "posterior": posteriors,
        "hypotheses": HYPOTHESES,
        "intrinsic_cagr": intrinsic_cagr,
        "intrinsic_cagr_pct_display": f"{intrinsic_cagr * 100:.1f}%",
        "market_implied_growth": implied_growth,
        "market_implied_growth_pct_display": f"{implied_growth * 100:.1f}%" if implied_growth is not None else None,
        "intrinsic_minus_implied": gap,
        "fomo_score_0_100": fomo,
        "verdict": verdict,
        "interpretation": {
            "UNDERPRICED_GROWTH": "Posterior intrinsic CAGR exceeds market-implied by 5pp+. Watch for re-rating catalyst.",
            "OVERPRICED_GROWTH": "Market pricing in more growth than evidence supports. Vulnerable to disappointment.",
            "FAIRLY_PRICED": "Intrinsic and implied growth align within 5pp. Edge requires variant perception.",
            "INSUFFICIENT_DATA": "Missing EV or revenue — cannot compute market-implied growth.",
        }[verdict],
        "notes": [],
    }

    if inputs["revenue_cagr_historical"] is None:
        result["notes"].append("No 3y+ revenue history — posterior dominated by recent growth + TAM.")
    if inputs["tam_cagr"] is None:
        result["notes"].append("No TAM CAGR — TAM update step uses flat likelihoods.")
    if fomo is not None and fomo > 50:
        result["notes"].append(f"FOMO score {fomo}/100 — price has run ahead of fundamentals.")

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
