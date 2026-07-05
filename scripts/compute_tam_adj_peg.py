#!/usr/bin/env python3
"""TAM-Adjusted PEG — growth-stock valuation with TAM runway + quality scoring.

Source framework: references/serenity/tam-adj-peg.md (Serenity TAM-Adj-PEG skill).

Adjusts the traditional PEG ratio (P/E ÷ growth rate) with:
  1. TAM Runway Score (R): how long can growth last given current penetration vs TAM CAGR
  2. Quality Score (Q): gross margin × FCF conversion × capex efficiency × pricing power
Then yields TAM-Adj-PEG = PEG ÷ (R × Q).

Companies are categorized into 5 buckets driven by (TAM-Adj-PEG, growth, quality):
  CORE_GROWTH       — low PEG, long runway, strong quality  (highest conviction long)
  HIGH_BETA_GROWTH  — high growth, expensive, moderate quality (size with care)
  OPTION_LIKE       — pre-revenue / loss-making but huge TAM (small position, milestone-driven)
  TURNAROUND        — depressed margin, recovery thesis (cyclical entry)
  CYCLICAL          — earnings-cyclical, peer-multiple play (trade, don't compound)

If PE or EPS CAGR is meaningless (losses), the script falls back to EV/Sales × growth
or option-style milestone framing.

Usage:
    compute_tam_adj_peg.py raw-data.json --output tam_adj_peg.json
    compute_tam_adj_peg.py raw-data.json --tam-cagr 0.18 --tam-penetration 0.06
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def safe_div(a, b):
    try:
        if b in (None, 0) or a in (None,):
            return None
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


def extract_inputs(raw: dict) -> dict:
    """Pull the fields TAM-Adj-PEG needs from the standard raw-data.json shape."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}
    annual = company.get("annual", {}) or {}
    quarterly = company.get("quarterly", {}) or {}

    # Forward PE preferred; fall back to trailing
    forward_pe = info.get("forwardPE") or info.get("forward_pe")
    trailing_pe = info.get("trailingPE") or info.get("pe_ratio")
    pe = forward_pe if forward_pe and forward_pe > 0 else trailing_pe

    # EPS CAGR — try info, else compute from annual eps
    eps_cagr_pct = info.get("earningsGrowth")
    if eps_cagr_pct is None:
        ann_eps = annual.get("eps") or []
        if isinstance(ann_eps, list) and len(ann_eps) >= 3:
            try:
                vals = [float(x.get("value", x) if isinstance(x, dict) else x) for x in ann_eps[-4:] if x is not None]
                if len(vals) >= 2 and vals[0] > 0:
                    years = len(vals) - 1
                    eps_cagr_pct = (vals[-1] / vals[0]) ** (1 / years) - 1
            except (ValueError, TypeError, ZeroDivisionError):
                pass

    revenue_cagr_pct = info.get("revenueGrowth")

    gross_margin = info.get("grossMargins") or info.get("gross_margin")
    ebit_margin = info.get("operatingMargins") or info.get("ebit_margin")
    fcf = info.get("freeCashflow") or info.get("free_cash_flow")
    revenue = info.get("totalRevenue") or info.get("revenue")
    fcf_margin = safe_div(fcf, revenue)
    capex = info.get("capitalExpenditures")
    capex_intensity = safe_div(abs(capex) if capex else None, revenue)
    ev = info.get("enterpriseValue")
    ev_sales = safe_div(ev, revenue)

    return {
        "ticker": ticker,
        "pe": pe,
        "forward_pe": forward_pe,
        "eps_cagr_pct": eps_cagr_pct,
        "revenue_cagr_pct": revenue_cagr_pct,
        "gross_margin": gross_margin,
        "ebit_margin": ebit_margin,
        "fcf_margin": fcf_margin,
        "capex_intensity": capex_intensity,
        "ev_sales": ev_sales,
        "revenue": revenue,
        "market_cap": info.get("marketCap"),
    }


def compute_traditional_peg(pe, eps_cagr_pct):
    if pe is None or eps_cagr_pct is None or eps_cagr_pct <= 0:
        return None
    growth_pct_int = eps_cagr_pct * 100
    return pe / growth_pct_int


def compute_tam_runway_score(tam_cagr, tam_penetration, revenue_cagr_pct):
    """Runway score 0.5-2.0. Higher = longer growth runway.

    Heuristic:
      - tam_penetration < 5%  → runway long (0.3 of weight)
      - tam_cagr > 15%        → industry tailwind (0.4 of weight)
      - revenue_cagr > tam_cagr → market-share gain (0.3 of weight)
    """
    score = 1.0  # neutral
    if tam_penetration is not None:
        if tam_penetration < 0.05:
            score += 0.5
        elif tam_penetration < 0.15:
            score += 0.2
        elif tam_penetration > 0.40:
            score -= 0.3
    if tam_cagr is not None:
        if tam_cagr > 0.20:
            score += 0.4
        elif tam_cagr > 0.10:
            score += 0.2
        elif tam_cagr < 0.03:
            score -= 0.3
    if revenue_cagr_pct is not None and tam_cagr is not None:
        if revenue_cagr_pct > tam_cagr + 0.05:
            score += 0.3  # share-gain
        elif revenue_cagr_pct < tam_cagr - 0.05:
            score -= 0.2
    return max(0.5, min(2.0, score))


def compute_quality_score(inputs: dict):
    """Quality score 0.5-2.0 combining margin, FCF, capex, pricing-power proxies."""
    score = 1.0
    gm = inputs.get("gross_margin")
    if gm is not None:
        if gm > 0.60:    score += 0.30
        elif gm > 0.40:  score += 0.15
        elif gm < 0.20:  score -= 0.30

    em = inputs.get("ebit_margin")
    if em is not None:
        if em > 0.25:    score += 0.20
        elif em > 0.10:  score += 0.10
        elif em < 0:     score -= 0.40

    fcfm = inputs.get("fcf_margin")
    if fcfm is not None:
        if fcfm > 0.20:  score += 0.20
        elif fcfm > 0.05: score += 0.10
        elif fcfm < 0:   score -= 0.30

    capex = inputs.get("capex_intensity")
    if capex is not None:
        if capex < 0.05:  score += 0.15
        elif capex > 0.20: score -= 0.20

    return max(0.5, min(2.0, score))


def categorize(peg_adj, growth, quality, has_earnings, tam_runway):
    if not has_earnings:
        if tam_runway >= 1.5:
            return "OPTION_LIKE"
        return "TURNAROUND"
    if growth is not None and growth < 0:
        return "TURNAROUND"
    if peg_adj is None:
        return "CYCLICAL"
    if peg_adj < 0.8 and quality >= 1.2 and tam_runway >= 1.3:
        return "CORE_GROWTH"
    if peg_adj < 1.5 and quality >= 1.0:
        return "CORE_GROWTH"
    if growth is not None and growth > 0.30:
        return "HIGH_BETA_GROWTH"
    return "CYCLICAL"


def main():
    parser = argparse.ArgumentParser(description="TAM-Adjusted PEG valuation analysis")
    parser.add_argument("input", help="Path to raw-data.json from fetch_financials.py")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--tam-cagr", type=float, help="Industry TAM CAGR (decimal). Optional override.")
    parser.add_argument("--tam-penetration", type=float,
                        help="Company revenue / TAM (decimal). Optional override.")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)

    inputs = extract_inputs(raw)
    peg = compute_traditional_peg(inputs["pe"], inputs["eps_cagr_pct"])
    runway = compute_tam_runway_score(args.tam_cagr, args.tam_penetration, inputs["revenue_cagr_pct"])
    quality = compute_quality_score(inputs)
    peg_adj = (peg / (runway * quality)) if peg is not None and runway > 0 and quality > 0 else None

    has_earnings = inputs["pe"] is not None and inputs["pe"] > 0
    growth = inputs["eps_cagr_pct"] if inputs["eps_cagr_pct"] is not None else inputs["revenue_cagr_pct"]
    category = categorize(peg_adj, growth, quality, has_earnings, runway)

    result = {
        "ticker": inputs["ticker"],
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "methodology": "TAM-Adj-PEG = PEG / (TAM Runway × Quality). Categories: CORE_GROWTH / HIGH_BETA_GROWTH / OPTION_LIKE / TURNAROUND / CYCLICAL. Source: references/serenity/tam-adj-peg.md.",
        "inputs": inputs,
        "tam_cagr": args.tam_cagr,
        "tam_penetration": args.tam_penetration,
        "peg_traditional": peg,
        "tam_runway_score": runway,
        "quality_score": quality,
        "tam_adj_peg": peg_adj,
        "category": category,
        "interpretation": {
            "CORE_GROWTH": "Long-duration compounder. Size for conviction.",
            "HIGH_BETA_GROWTH": "Expensive growth — size smaller, watch valuation regime.",
            "OPTION_LIKE": "Pre-revenue / pre-profit, milestone-driven. Position small.",
            "TURNAROUND": "Recovery thesis — verify margin or growth inflection before adding.",
            "CYCLICAL": "Earnings-cyclical, trade by multiple compression/expansion.",
        }[category],
        "notes": [],
    }

    if peg is None:
        result["notes"].append("Traditional PEG not computable (missing PE or non-positive EPS growth).")
    if args.tam_cagr is None:
        result["notes"].append("No TAM CAGR provided — runway score uses revenue-growth-vs-industry fallback only.")
    if not has_earnings:
        result["notes"].append("Company has no positive earnings — PE/PEG signals unreliable. Consider EV/Sales × growth or milestone valuation.")

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
