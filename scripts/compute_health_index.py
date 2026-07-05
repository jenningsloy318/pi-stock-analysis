#!/usr/bin/env python3
"""GF-DMA Health Index — fundamental speed × DMA structure × revisions composite.

Source framework: references/serenity/gf-dma-health-index.md.

Combines:
  1. Fundamental Speed (G_f)  = 0.35 G_Revenue + 0.25 G_GrossProfit + 0.30 G_EPS + 0.10 G_Revision
  2. DMA Speed (G_DMA)        = quarter-annualized slope of 20/50/100/200-day SMAs
  3. Price-to-DMA Divergence  = (Price - SMA_n) / SMA_n
  4. ATR Divergence           = abs(Price - SMA_50) / ATR_20  (escape ratio)
  5. Estimate Revisions       = 30-day consensus revision

Health Index 0-100 with bands:
  85-100  ELITE_HEALTHY   — strong fundamentals, strong DMA structure, low escape ratio
  70-84   HEALTHY         — fundamentals support trend
  50-69   MIXED           — some divergence between fundamentals and price
  30-49   OVERHEATED      — price escaped DMA; fundamentals lagging
  0-29    UNHEALTHY       — broken trend or fundamental deterioration

Usage:
    compute_health_index.py raw-data.json --technicals technicals.json --output health.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def safe_div(a, b):
    try:
        if b in (None, 0) or a is None:
            return None
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


def pct_change(latest, prior):
    if latest is None or prior is None or prior == 0:
        return None
    return (latest - prior) / prior


def compute_fundamental_speed(info, quarterly):
    """G_f = 0.35 G_Rev + 0.25 G_GP + 0.30 G_EPS + 0.10 G_Revision."""
    weights = {"revenue": 0.35, "gross_profit": 0.25, "eps": 0.30, "revision": 0.10}

    # Pull latest quarter vs prior
    def latest_two(series_name):
        s = quarterly.get(series_name) or []
        try:
            vals = [float(x.get("value", x) if isinstance(x, dict) else x) for x in s[-2:] if x is not None]
            if len(vals) == 2:
                return vals[1], vals[0]
        except (ValueError, TypeError):
            pass
        return None, None

    g_rev_latest, g_rev_prior = latest_two("revenue")
    g_rev = pct_change(g_rev_latest, g_rev_prior)

    g_gp_latest, g_gp_prior = latest_two("gross_profit")
    g_gp = pct_change(g_gp_latest, g_gp_prior)

    g_eps_latest, g_eps_prior = latest_two("eps")
    g_eps = pct_change(g_eps_latest, g_eps_prior)

    g_revision = info.get("earningsEstimateRevisionPct") or 0.0

    components = {"G_Revenue": g_rev, "G_GrossProfit": g_gp, "G_EPS": g_eps, "G_Revision": g_revision}

    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        return None, components, "no_quarterly_data"

    # Fallback rules per framework
    if g_rev is not None and g_gp is not None and g_eps is not None:
        g_f = sum(weights[k.lower().replace("g_", "")] * v for k, v in [("G_Revenue", g_rev), ("G_GrossProfit", g_gp), ("G_EPS", g_eps), ("G_Revision", g_revision)])
        return g_f, components, "full"
    if g_rev is not None and g_eps is not None:
        g_f = 0.5 * g_rev + 0.5 * g_eps
        return g_f, components, "rev_eps_only"
    if g_rev is not None:
        return g_rev, components, "rev_only"
    return None, components, "partial"


def compute_dma_speed(sma_series_now, sma_series_prior, k_days):
    """G_DMAx = ((SMA(t) - SMA(t-k)) / SMA(t-k)) * (63/k)."""
    if sma_series_now is None or sma_series_prior is None or sma_series_prior == 0:
        return None
    return ((sma_series_now - sma_series_prior) / sma_series_prior) * (63 / k_days)


def compute_health_score(g_f, g_dma_speeds, price_to_sma50, escape_ratio):
    """Composite 0-100. Each factor scaled then weight-summed."""
    score_parts = {}

    # Fundamental speed: scale roughly 0-1 around healthy 5%/quarter
    if g_f is not None:
        score_parts["fundamental"] = max(0, min(100, 50 + g_f * 500))  # 10%/Q → 100
    else:
        score_parts["fundamental"] = 50  # neutral

    # DMA structure: positive slopes good. Average across available DMAs.
    valid_slopes = [s for s in g_dma_speeds.values() if s is not None]
    if valid_slopes:
        avg_slope = sum(valid_slopes) / len(valid_slopes)
        score_parts["dma_speed"] = max(0, min(100, 50 + avg_slope * 250))
    else:
        score_parts["dma_speed"] = 50

    # Price vs SMA50 — small premium is healthy, extreme premium is overheated
    if price_to_sma50 is not None:
        prem = abs(price_to_sma50)
        if prem < 0.05:
            score_parts["price_to_dma"] = 90
        elif prem < 0.12:
            score_parts["price_to_dma"] = 70
        elif prem < 0.20:
            score_parts["price_to_dma"] = 50
        elif prem < 0.30:
            score_parts["price_to_dma"] = 30
        else:
            score_parts["price_to_dma"] = 10
    else:
        score_parts["price_to_dma"] = 50

    # Escape ratio: |price - SMA50| / ATR20. Higher = more stretched.
    if escape_ratio is not None:
        if escape_ratio < 2:
            score_parts["escape_ratio"] = 90
        elif escape_ratio < 4:
            score_parts["escape_ratio"] = 70
        elif escape_ratio < 6:
            score_parts["escape_ratio"] = 50
        elif escape_ratio < 10:
            score_parts["escape_ratio"] = 30
        else:
            score_parts["escape_ratio"] = 10
    else:
        score_parts["escape_ratio"] = 50

    weights = {"fundamental": 0.40, "dma_speed": 0.30, "price_to_dma": 0.15, "escape_ratio": 0.15}
    composite = sum(score_parts[k] * weights[k] for k in score_parts)
    return round(composite, 1), score_parts, weights


def band_for_score(score):
    if score >= 85: return "ELITE_HEALTHY"
    if score >= 70: return "HEALTHY"
    if score >= 50: return "MIXED"
    if score >= 30: return "OVERHEATED"
    return "UNHEALTHY"


def main():
    parser = argparse.ArgumentParser(description="GF-DMA Health Index")
    parser.add_argument("input", help="Path to raw-data.json (fundamentals)")
    parser.add_argument("--technicals", help="Path to technicals.json from fetch_technicals.py", required=False)
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    c = raw.get(ticker, {})
    info = c.get("info", {}) or {}
    quarterly = c.get("quarterly", {}) or {}

    tech = {}
    if args.technicals and os.path.isfile(args.technicals):
        try:
            with open(args.technicals) as f:
                tech = json.load(f)
            if isinstance(tech, dict) and ticker in tech:
                tech = tech[ticker]
        except (json.JSONDecodeError, OSError):
            tech = {}

    g_f, components, fund_mode = compute_fundamental_speed(info, quarterly)

    # DMA series from technicals (expected keys: sma_20, sma_50, sma_100, sma_200, atr_20, price)
    price = tech.get("price") or info.get("currentPrice") or info.get("regularMarketPrice")
    sma_20 = tech.get("sma_20")
    sma_50 = tech.get("sma_50")
    sma_100 = tech.get("sma_100")
    sma_200 = tech.get("sma_200")
    atr_20 = tech.get("atr_20")

    # For DMA SPEED we need prior values; if absent, use a crude proxy (current SMA vs longer SMA)
    sma_20_prior = tech.get("sma_20_prior") or sma_50
    sma_50_prior = tech.get("sma_50_prior") or sma_100
    sma_100_prior = tech.get("sma_100_prior") or sma_200
    sma_200_prior = tech.get("sma_200_prior") or sma_200

    g_dma = {
        "G_DMA20":  compute_dma_speed(sma_20, sma_20_prior, 20),
        "G_DMA50":  compute_dma_speed(sma_50, sma_50_prior, 50),
        "G_DMA100": compute_dma_speed(sma_100, sma_100_prior, 100),
        "G_DMA200": compute_dma_speed(sma_200, sma_200_prior, 200),
    }

    price_to_sma50 = ((price - sma_50) / sma_50) if (price and sma_50) else None
    escape_ratio = (abs(price - sma_50) / atr_20) if (price and sma_50 and atr_20) else None

    composite, parts, weights = compute_health_score(g_f, g_dma, price_to_sma50, escape_ratio)
    band = band_for_score(composite)

    result = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "methodology": "GF-DMA Health Index — composite of Fundamental Speed (G_f), DMA Speed (G_DMA20/50/100/200), Price-to-SMA50 divergence, and ATR-normalized escape ratio. Bands: ELITE_HEALTHY / HEALTHY / MIXED / OVERHEATED / UNHEALTHY. Source: references/serenity/gf-dma-health-index.md.",
        "fundamental_speed": {
            "G_f": g_f,
            "mode": fund_mode,
            "components": components,
        },
        "dma_speeds": g_dma,
        "price_to_sma50_divergence": price_to_sma50,
        "escape_ratio": escape_ratio,
        "score_components_0_100": parts,
        "component_weights": weights,
        "health_index_0_100": composite,
        "band": band,
        "interpretation": {
            "ELITE_HEALTHY": "Strong fundamentals + supportive DMA structure + room before stretch. Trend continuation favored.",
            "HEALTHY":       "Fundamentals support the price trend. Monitor for escape if score drops to MIXED.",
            "MIXED":         "Fundamentals and price diverging. Either price is ahead or fundamentals are catching up — verify next earnings.",
            "OVERHEATED":    "Price has escaped DMA structure relative to fundamental speed. Mean-reversion risk elevated.",
            "UNHEALTHY":     "Either trend broken or fundamentals deteriorating. Re-underwrite the thesis before adding.",
        }[band],
        "notes": [],
    }

    if g_f is None:
        result["notes"].append("Fundamental speed not computable — no quarterly data.")
    if not args.technicals:
        result["notes"].append("No technicals input — DMA components default to neutral.")
    if escape_ratio is not None and escape_ratio > 6:
        result["notes"].append(f"Escape ratio {escape_ratio:.1f} elevated — price stretched vs ATR.")

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
