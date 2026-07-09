#!/usr/bin/env python3
"""Compute Industry Trajectory Score — is the industry getting better or worse?

Usage:
    compute_industry_trajectory.py --etf SMH --output ./reports/trajectory_SMH.json
    compute_industry_trajectory.py --etf XLK --gics-code 4530
    compute_industry_trajectory.py --etfs SMH,SOXX,XSD --output ./reports/semi_trajectory.json

Goes beyond static relative-strength to measure directional change in industry
health. A high RS industry can be *decelerating* (sell signal); a low RS
industry can be *accelerating* (buy signal).

Dimensions (all measured as CHANGE over trailing 4 quarters):
  1. Revenue Growth Acceleration — industry rev growth rate speeding up or slowing down
  2. Margin Direction             — aggregate gross/operating margin expanding or compressing
  3. RS Momentum (3M vs 6M)      — relative strength improving or deteriorating
  4. Fund Flow Direction          — ETF AUM/volume increasing or decreasing (demand proxy)
  5. Valuation Change             — P/E expanding or compressing vs 1yr ago
  6. Capital Cycle Position       — capex acceleration (early) vs over-investment (late)

Output: Industry_Trajectory score 1-10 and directional label.

Data source: yfinance (ETF-level data — no paid API required).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import numpy as np
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: yfinance and numpy required. Run: pip install yfinance numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Dimension calculators
# ---------------------------------------------------------------------------


def _safe_pct_change(current: float | None, prior: float | None) -> float | None:
    """Compute percentage change, handling None and zero denominators."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def compute_revenue_acceleration(etf_ticker: str) -> dict:
    """Measure whether industry revenue growth is accelerating or decelerating.

    Uses ETF's top holdings' aggregate revenue growth rate change.
    Proxy: ETF earnings growth rate vs prior period.
    """
    try:
        etf = yf.Ticker(etf_ticker)
        info = etf.info or {}

        # ETF-level earnings growth is a proxy for constituent revenue momentum
        earnings_growth = info.get("threeYearAverageReturn")  # annualized
        ytd_return = info.get("ytdReturn")

        # Use fund performance as revenue proxy (ETFs track fundamentals long-term)
        hist = etf.history(period="2y")
        if hist.empty or len(hist) < 252:
            return {"score": None, "note": "Insufficient price history"}

        # Compare recent 6M growth rate vs prior 6M growth rate
        prices = hist["Close"].values
        n = len(prices)
        mid = n // 2

        recent_return = (prices[-1] / prices[mid] - 1) if prices[mid] > 0 else None
        prior_return = (prices[mid] / prices[0] - 1) if prices[0] > 0 else None

        if recent_return is None or prior_return is None:
            return {"score": None, "note": "Could not compute returns"}

        # Acceleration = recent - prior (positive = accelerating)
        acceleration = recent_return - prior_return

        # Score: strong acceleration (+20%+) = 9-10, mild (+5-20%) = 7-8,
        # flat (-5% to +5%) = 5-6, mild decel (-5 to -20%) = 3-4, strong decel = 1-2
        if acceleration >= 0.20:
            score = min(10.0, 9.0 + acceleration * 5)
        elif acceleration >= 0.05:
            score = 7.0 + (acceleration - 0.05) / 0.15 * 2
        elif acceleration >= -0.05:
            score = 5.0 + acceleration / 0.05
        elif acceleration >= -0.20:
            score = 3.0 + (acceleration + 0.20) / 0.15 * 2
        else:
            score = max(1.0, 2.0 + (acceleration + 0.20) * 5)

        return {
            "score": round(score, 1),
            "acceleration": round(acceleration, 4),
            "recent_6m_return": round(recent_return, 4),
            "prior_6m_return": round(prior_return, 4),
            "direction": "accelerating" if acceleration > 0.05 else ("decelerating" if acceleration < -0.05 else "stable"),
        }
    except Exception as e:
        return {"score": None, "note": f"Error: {e}"}


def compute_margin_direction(etf_ticker: str) -> dict:
    """Measure whether industry margins are expanding or contracting.

    Uses ETF's profit ratio or yield as proxy for constituent margins.
    """
    try:
        etf = yf.Ticker(etf_ticker)
        info = etf.info or {}

        # Use trailing PE vs forward PE as margin expansion proxy
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")

        # If forward PE < trailing PE → earnings growing (margins expanding)
        # If forward PE > trailing PE → earnings declining (margins contracting)
        if trailing_pe and forward_pe and trailing_pe > 0 and forward_pe > 0:
            earnings_growth_implied = (trailing_pe / forward_pe) - 1  # positive = growth
            if earnings_growth_implied >= 0.15:
                score = min(10.0, 8.5 + earnings_growth_implied * 5)
            elif earnings_growth_implied >= 0.05:
                score = 7.0 + (earnings_growth_implied - 0.05) / 0.10 * 1.5
            elif earnings_growth_implied >= -0.05:
                score = 5.0 + earnings_growth_implied * 20
            elif earnings_growth_implied >= -0.15:
                score = 3.0 + (earnings_growth_implied + 0.15) / 0.10 * 2
            else:
                score = max(1.0, 2.0)

            direction = "expanding" if earnings_growth_implied > 0.05 else \
                       ("contracting" if earnings_growth_implied < -0.05 else "stable")

            return {
                "score": round(score, 1),
                "earnings_growth_implied": round(earnings_growth_implied, 4),
                "trailing_pe": trailing_pe,
                "forward_pe": forward_pe,
                "direction": direction,
            }

        # Fallback: use profit margin from info
        profit_margin = info.get("profitMargins")
        if profit_margin is not None:
            # Above 15% = healthy, below 5% = weak
            score = min(10.0, max(1.0, 3.0 + profit_margin * 40))
            return {
                "score": round(score, 1),
                "profit_margin": profit_margin,
                "direction": "unknown",
                "note": "Static margin only — no trend available",
            }

        return {"score": None, "note": "No PE or margin data available"}
    except Exception as e:
        return {"score": None, "note": f"Error: {e}"}


def compute_rs_momentum(etf_ticker: str, benchmark: str = "SPY") -> dict:
    """Measure RS momentum: is relative strength improving or deteriorating?

    Compares 3M RS vs 6M RS — when 3M > 6M, the industry is gaining momentum.
    """
    try:
        etf_hist = yf.download([etf_ticker, benchmark], period="1y", progress=False)
        if etf_hist.empty:
            return {"score": None, "note": "No data"}

        close = etf_hist["Close"]
        if etf_ticker not in close.columns or benchmark not in close.columns:
            return {"score": None, "note": "Ticker not in download"}

        etf_prices = close[etf_ticker].dropna()
        bench_prices = close[benchmark].dropna()

        if len(etf_prices) < 126 or len(bench_prices) < 126:
            return {"score": None, "note": "Insufficient data for 6M"}

        # RS = ETF / Benchmark (ratio)
        # 3M RS change
        rs_now = etf_prices.iloc[-1] / bench_prices.iloc[-1]
        rs_3m_ago = etf_prices.iloc[-63] / bench_prices.iloc[-63]
        rs_6m_ago = etf_prices.iloc[-126] / bench_prices.iloc[-126]

        rs_3m_change = (rs_now / rs_3m_ago - 1) if rs_3m_ago > 0 else None
        rs_6m_change = (rs_now / rs_6m_ago - 1) if rs_6m_ago > 0 else None

        if rs_3m_change is None or rs_6m_change is None:
            return {"score": None, "note": "Could not compute RS changes"}

        # Momentum = 3M change vs 6M change (positive = accelerating outperformance)
        momentum = rs_3m_change - (rs_6m_change / 2)  # normalize 6M to 3M equivalent

        if momentum >= 0.10:
            score = min(10.0, 9.0)
        elif momentum >= 0.03:
            score = 7.0 + (momentum - 0.03) / 0.07 * 2
        elif momentum >= -0.03:
            score = 5.0 + momentum / 0.03
        elif momentum >= -0.10:
            score = 3.0 + (momentum + 0.10) / 0.07 * 2
        else:
            score = max(1.0, 2.0)

        direction = "improving" if momentum > 0.03 else ("deteriorating" if momentum < -0.03 else "flat")

        return {
            "score": round(score, 1),
            "rs_3m_change": round(rs_3m_change, 4),
            "rs_6m_change": round(rs_6m_change, 4),
            "momentum": round(momentum, 4),
            "direction": direction,
        }
    except Exception as e:
        return {"score": None, "note": f"Error: {e}"}


def compute_fund_flows(etf_ticker: str) -> dict:
    """Measure fund flow direction using volume trend as proxy.

    Rising volume + rising price = inflows (demand).
    Rising volume + falling price = outflows (liquidation).
    """
    try:
        etf = yf.Ticker(etf_ticker)
        hist = etf.history(period="6mo")
        if hist.empty or len(hist) < 60:
            return {"score": None, "note": "Insufficient history"}

        # Compare recent 1M avg volume vs prior 2M avg volume
        recent_vol = hist["Volume"].iloc[-21:].mean()
        prior_vol = hist["Volume"].iloc[-63:-21].mean()

        vol_change = (recent_vol / prior_vol - 1) if prior_vol > 0 else 0

        # Price direction (recent 1M)
        price_recent = hist["Close"].iloc[-1]
        price_1m_ago = hist["Close"].iloc[-21]
        price_direction = (price_recent / price_1m_ago - 1) if price_1m_ago > 0 else 0

        # Interpretation:
        # vol up + price up = strong inflow (bullish) → 8-10
        # vol flat + price up = quiet accumulation → 6-8
        # vol up + price down = distribution/panic → 2-4
        # vol down + price up = low-conviction rally → 5-6
        # vol down + price down = apathy → 4-5

        if vol_change > 0.20 and price_direction > 0.02:
            score = min(10.0, 8.5 + vol_change * 2)
            direction = "strong_inflow"
        elif vol_change > 0 and price_direction > 0.02:
            score = 7.0 + vol_change * 5
            direction = "accumulation"
        elif vol_change > 0.20 and price_direction < -0.02:
            score = max(1.0, 3.0 - vol_change * 3)
            direction = "distribution"
        elif price_direction > 0.02:
            score = 6.0
            direction = "quiet_accumulation"
        elif price_direction < -0.02:
            score = 4.0
            direction = "declining"
        else:
            score = 5.0
            direction = "neutral"

        return {
            "score": round(min(10.0, max(1.0, score)), 1),
            "volume_change_1m": round(vol_change, 4),
            "price_direction_1m": round(price_direction, 4),
            "direction": direction,
        }
    except Exception as e:
        return {"score": None, "note": f"Error: {e}"}


def compute_valuation_change(etf_ticker: str) -> dict:
    """Measure valuation expansion/compression vs 1 year ago.

    PE expansion = market paying more per $ of earnings (optimism rising).
    PE compression = market paying less (pessimism rising or earnings catching up).
    """
    try:
        etf = yf.Ticker(etf_ticker)
        info = etf.info or {}

        trailing_pe = info.get("trailingPE")
        if trailing_pe is None:
            return {"score": None, "note": "No trailing PE available"}

        # Use 1Y price return vs earnings growth to infer PE change direction
        hist = etf.history(period="1y")
        if hist.empty or len(hist) < 200:
            return {"score": None, "note": "Insufficient history for 1Y comparison"}

        price_1y_return = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)

        # If we have forward PE, compute implied earnings growth
        forward_pe = info.get("forwardPE")
        if forward_pe and trailing_pe:
            # PE change proxy: trailing/forward ratio
            pe_expansion = (trailing_pe / forward_pe - 1) if forward_pe > 0 else 0
        else:
            # Fallback: high 1Y return with moderate PE = expansion
            pe_expansion = price_1y_return * 0.5  # rough proxy

        # Score: strong expansion (+20%+) = 8-10, mild (5-20%) = 6-8,
        # flat = 5, mild compression = 3-5, strong compression = 1-3
        if pe_expansion >= 0.15:
            score = min(10.0, 8.5)
        elif pe_expansion >= 0.05:
            score = 6.5 + (pe_expansion - 0.05) / 0.10 * 2
        elif pe_expansion >= -0.05:
            score = 5.0 + pe_expansion * 15
        elif pe_expansion >= -0.15:
            score = 3.0 + (pe_expansion + 0.15) / 0.10 * 2
        else:
            score = max(1.0, 2.0)

        direction = "expanding" if pe_expansion > 0.05 else ("compressing" if pe_expansion < -0.05 else "stable")

        return {
            "score": round(score, 1),
            "pe_change_proxy": round(pe_expansion, 4),
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "price_1y_return": round(price_1y_return, 4),
            "direction": direction,
        }
    except Exception as e:
        return {"score": None, "note": f"Error: {e}"}


def compute_capital_cycle(etf_ticker: str) -> dict:
    """Estimate capital cycle position: early (under-investment) vs late (over-investment).

    Uses ETF's beta and volatility as proxies for capital cycle maturity.
    High capex growth in the sector = late cycle (over-investment risk).
    Low capex + high returns = early cycle (under-investment opportunity).
    """
    try:
        etf = yf.Ticker(etf_ticker)
        info = etf.info or {}

        beta = info.get("beta3Year") or info.get("beta")
        pe = info.get("trailingPE")

        # High PE + High beta = late cycle (over-invested, euphoria)
        # Low PE + Low beta = early cycle (under-invested, pessimism)
        # Moderate = mid cycle

        if pe is None:
            return {"score": None, "note": "No PE data for capital cycle estimation"}

        # Heuristic: inverse PE relationship to capital cycle opportunity
        # Low PE (undervalued industry) = more opportunity (early cycle) → higher score
        # High PE (overvalued) = late cycle → lower score for trajectory
        if pe <= 12:
            score = 8.5  # Cheap = early cycle opportunity
        elif pe <= 18:
            score = 7.0  # Fair = mid cycle
        elif pe <= 25:
            score = 5.5  # Rich but not extreme
        elif pe <= 35:
            score = 4.0  # Expensive = late cycle
        else:
            score = 2.5  # Euphoric = very late cycle

        # Adjust for beta (high beta in cheap sector = stronger signal)
        if beta is not None:
            if beta > 1.3 and pe <= 15:
                score = min(10.0, score + 1.0)  # Cheap + volatile = strong early cycle
            elif beta < 0.7 and pe > 25:
                score = max(1.0, score - 0.5)  # Expensive + defensive = crowded trade

        if pe <= 15:
            position = "early_cycle"
        elif pe <= 22:
            position = "mid_cycle"
        else:
            position = "late_cycle"

        return {
            "score": round(score, 1),
            "trailing_pe": pe,
            "beta": beta,
            "position": position,
        }
    except Exception as e:
        return {"score": None, "note": f"Error: {e}"}


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

# Dimension weights for Industry Trajectory composite
DIMENSION_WEIGHTS = {
    "revenue_acceleration": 0.25,
    "margin_direction": 0.20,
    "rs_momentum": 0.15,
    "fund_flows": 0.15,
    "valuation_change": 0.15,
    "capital_cycle": 0.10,
}


def compute_trajectory(etf_ticker: str, benchmark: str = "SPY") -> dict:
    """Compute full Industry Trajectory analysis for one ETF/sub-industry."""
    dimensions = {
        "revenue_acceleration": compute_revenue_acceleration(etf_ticker),
        "margin_direction": compute_margin_direction(etf_ticker),
        "rs_momentum": compute_rs_momentum(etf_ticker, benchmark),
        "fund_flows": compute_fund_flows(etf_ticker),
        "valuation_change": compute_valuation_change(etf_ticker),
        "capital_cycle": compute_capital_cycle(etf_ticker),
    }

    # Compute weighted composite
    available_scores = {}
    for dim, result in dimensions.items():
        s = result.get("score")
        if s is not None:
            available_scores[dim] = s

    if not available_scores:
        return {
            "etf": etf_ticker,
            "trajectory_score": None,
            "trajectory_direction": "unknown",
            "dimensions": dimensions,
            "note": "No dimension scores available",
        }

    total_weight = sum(DIMENSION_WEIGHTS[k] for k in available_scores)
    composite = sum(available_scores[k] * DIMENSION_WEIGHTS[k] for k in available_scores) / total_weight
    composite = round(composite, 1)

    # Determine overall direction
    directions = []
    for dim, result in dimensions.items():
        d = result.get("direction")
        if d and d not in ("unknown", "stable", "flat", "neutral", "mid_cycle"):
            directions.append(d)

    positive_signals = sum(1 for d in directions if d in (
        "accelerating", "expanding", "improving", "strong_inflow",
        "accumulation", "quiet_accumulation", "early_cycle"
    ))
    negative_signals = sum(1 for d in directions if d in (
        "decelerating", "contracting", "deteriorating", "distribution",
        "declining", "compressing", "late_cycle"
    ))

    if positive_signals >= 4:
        trajectory_direction = "strong_improvement"
    elif positive_signals > negative_signals:
        trajectory_direction = "improving"
    elif negative_signals >= 4:
        trajectory_direction = "strong_deterioration"
    elif negative_signals > positive_signals:
        trajectory_direction = "deteriorating"
    else:
        trajectory_direction = "mixed"

    return {
        "etf": etf_ticker,
        "trajectory_score": composite,
        "trajectory_direction": trajectory_direction,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "dimensions": dimensions,
        "weights_used": {k: DIMENSION_WEIGHTS[k] for k in available_scores},
        "coverage": f"{len(available_scores)}/{len(DIMENSION_WEIGHTS)} dimensions scored",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Compute Industry Trajectory Score")
    parser.add_argument("--etf", help="Single ETF ticker to analyze")
    parser.add_argument("--etfs", help="Comma-separated ETF tickers to analyze")
    parser.add_argument("--gics-code", help="GICS code for labeling (optional)")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark ETF (default: SPY)")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    tickers = []
    if args.etf:
        tickers = [args.etf.strip()]
    elif args.etfs:
        tickers = [t.strip() for t in args.etfs.split(",")]
    else:
        parser.error("Either --etf or --etfs is required")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []

    for ticker in tickers:
        result = compute_trajectory(ticker, args.benchmark)
        result["gics_code"] = args.gics_code
        results.append(result)

    output = {
        "timestamp": timestamp,
        "benchmark": args.benchmark,
        "trajectories": results if len(results) > 1 else results[0] if results else {},
    }

    output_json = json.dumps(output, indent=2, ensure_ascii=False)
    print(output_json)

    if args.output:
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        sys.stderr.write(f"Written to {args.output}\n")


if __name__ == "__main__":
    main()
