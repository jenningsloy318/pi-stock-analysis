#!/usr/bin/env python3
"""Compute correlation regime analysis: rolling beta, correlation breakdown detection.

Usage:
    compute_correlation_regime.py AAPL --output ./reports/AAPL/correlation.json
    compute_correlation_regime.py AAPL --benchmark SPY --window 60

Analyzes from yfinance price data:
  - Rolling beta vs benchmark (SPY default)
  - Correlation regime (high/normal/low/divergent)
  - Tail correlation — does correlation spike during drawdowns?
  - Beta expansion/compression during stress
  - Sector correlation (vs sector ETF)
  - Diversification benefit score (for portfolio context)

Free data source: yfinance (daily returns).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
    import numpy as np
except ImportError:
    sys.stderr.write(
        "Error: yfinance and numpy required. Run: pip install yfinance numpy\n"
    )
    sys.exit(1)


def compute_rolling_beta(
    stock_returns: np.ndarray, bench_returns: np.ndarray, window: int = 60
) -> dict:
    """Compute rolling beta with regime detection."""
    n = len(stock_returns)
    if n < window + 20:
        return {"error": f"Insufficient data ({n} points, need {window + 20})"}

    betas = []
    for i in range(window, n):
        s = stock_returns[i - window : i]
        b = bench_returns[i - window : i]
        cov = np.cov(s, b)[0][1]
        var = np.var(b)
        if var > 0:
            betas.append(cov / var)

    if not betas:
        return {"error": "Could not compute rolling beta"}

    current_beta = betas[-1]
    avg_beta = float(np.mean(betas))
    beta_std = float(np.std(betas))
    max_beta = float(np.max(betas))
    min_beta = float(np.min(betas))

    beta_z = (current_beta - avg_beta) / beta_std if beta_std > 0 else 0

    regime = "normal"
    if beta_z > 1.5:
        regime = "elevated"
    elif beta_z < -1.5:
        regime = "compressed"

    return {
        "current_beta": round(current_beta, 3),
        "average_beta": round(avg_beta, 3),
        "beta_std": round(beta_std, 3),
        "max_beta": round(max_beta, 3),
        "min_beta": round(min_beta, 3),
        "beta_z_score": round(beta_z, 2),
        "regime": regime,
        "window_days": window,
    }


def compute_tail_correlation(
    stock_returns: np.ndarray, bench_returns: np.ndarray, threshold_pct: float = 5.0
) -> dict:
    """Measure correlation during tail events (worst N% of market days).

    Tail correlation > normal correlation = diversification fails when needed most.
    """
    n = len(stock_returns)
    if n < 60:
        return {"error": "Insufficient data for tail analysis"}

    full_corr = float(np.corrcoef(stock_returns, bench_returns)[0][1])

    cutoff = np.percentile(bench_returns, threshold_pct)
    tail_mask = bench_returns <= cutoff
    tail_count = int(np.sum(tail_mask))

    if tail_count < 10:
        return {
            "full_correlation": round(full_corr, 3),
            "error": "Too few tail events for reliable estimate",
        }

    tail_stock = stock_returns[tail_mask]
    tail_bench = bench_returns[tail_mask]
    tail_corr = float(np.corrcoef(tail_stock, tail_bench)[0][1])

    corr_spike = tail_corr - full_corr

    return {
        "full_correlation": round(full_corr, 3),
        "tail_correlation": round(tail_corr, 3),
        "correlation_spike": round(corr_spike, 3),
        "tail_days_analyzed": tail_count,
        "threshold_percentile": threshold_pct,
        "diversification_reliable": corr_spike < 0.15,
        "interpretation": (
            "Diversification holds during stress — correlation stable in tails"
            if corr_spike < 0.10
            else "Moderate correlation spike during stress — diversification partially degrades"
            if corr_spike < 0.25
            else "Severe correlation spike — diversification fails during drawdowns. Reduce position or hedge explicitly."
        ),
    }


def compute_drawdown_beta(stock_returns: np.ndarray, bench_returns: np.ndarray) -> dict:
    """Compute upside vs downside beta (asymmetric risk).

    Downside beta > upside beta = stock falls more than market in drops (bad).
    Upside beta > downside beta = stock captures more upside (good).
    """
    up_mask = bench_returns > 0
    down_mask = bench_returns < 0

    up_stock = stock_returns[up_mask]
    up_bench = bench_returns[up_mask]
    down_stock = stock_returns[down_mask]
    down_bench = bench_returns[down_mask]

    def beta_from(s, b):
        if len(s) < 20 or np.var(b) == 0:
            return None
        return float(np.cov(s, b)[0][1] / np.var(b))

    upside_beta = beta_from(up_stock, up_bench)
    downside_beta = beta_from(down_stock, down_bench)

    if upside_beta is None or downside_beta is None:
        return {"error": "Insufficient data for asymmetric beta"}

    capture_ratio = upside_beta / downside_beta if downside_beta != 0 else None

    return {
        "upside_beta": round(upside_beta, 3),
        "downside_beta": round(downside_beta, 3),
        "capture_ratio": round(capture_ratio, 3) if capture_ratio else None,
        "asymmetry": (
            "Favorable — captures more upside than downside"
            if capture_ratio and capture_ratio > 1.1
            else "Unfavorable — falls more than it rises relative to market"
            if capture_ratio and capture_ratio < 0.9
            else "Symmetric — proportional participation in both directions"
        ),
    }


def compute_regime_classification(
    stock_returns: np.ndarray, bench_returns: np.ndarray, window: int = 60
) -> dict:
    """Classify current correlation regime and detect shifts."""
    n = len(stock_returns)
    if n < window * 2:
        return {"error": "Insufficient data for regime classification"}

    correlations = []
    for i in range(window, n):
        s = stock_returns[i - window : i]
        b = bench_returns[i - window : i]
        corr = np.corrcoef(s, b)[0][1]
        if not np.isnan(corr):
            correlations.append(corr)

    if len(correlations) < 20:
        return {"error": "Could not compute sufficient rolling correlations"}

    current_corr = correlations[-1]
    avg_corr = float(np.mean(correlations))
    std_corr = float(np.std(correlations))

    recent_10 = correlations[-10:]
    prior_10 = correlations[-20:-10] if len(correlations) >= 20 else correlations[:10]
    recent_avg = float(np.mean(recent_10))
    prior_avg = float(np.mean(prior_10))
    trend = recent_avg - prior_avg

    if current_corr > 0.8:
        regime = "high_correlation"
    elif current_corr > 0.5:
        regime = "normal"
    elif current_corr > 0.2:
        regime = "low_correlation"
    else:
        regime = "divergent"

    return {
        "current_correlation": round(current_corr, 3),
        "average_correlation": round(avg_corr, 3),
        "correlation_std": round(std_corr, 3),
        "regime": regime,
        "trend": round(trend, 3),
        "trend_direction": (
            "rising" if trend > 0.05 else "falling" if trend < -0.05 else "stable"
        ),
        "interpretation": {
            "high_correlation": "High correlation — stock moves with market. Limited diversification. Position sizing should assume full market exposure.",
            "normal": "Normal correlation — standard market sensitivity. Standard position sizing appropriate.",
            "low_correlation": "Low correlation — idiosyncratic drivers dominate. Good diversifier. Focus on company-specific thesis.",
            "divergent": "Divergent — stock decoupled from market. Either unique catalyst or broken relationship. Verify thesis is intact.",
        }[regime],
    }


def main():
    parser = argparse.ArgumentParser(description="Compute correlation regime analysis")
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument(
        "--benchmark", default="SPY", help="Benchmark ticker (default: SPY)"
    )
    parser.add_argument(
        "--window", type=int, default=60, help="Rolling window in days (default: 60)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    benchmark = args.benchmark.strip().upper()

    try:
        stock_data = yf.download(ticker, period="2y", progress=False)
        bench_data = yf.download(benchmark, period="2y", progress=False)

        if stock_data.empty or bench_data.empty:
            print(
                f"Error: Cannot fetch data for {ticker} or {benchmark}", file=sys.stderr
            )
            sys.exit(1)

        stock_close = stock_data["Close"].dropna()
        bench_close = bench_data["Close"].dropna()

        common_idx = stock_close.index.intersection(bench_close.index)
        if len(common_idx) < 100:
            print("Error: Insufficient overlapping data", file=sys.stderr)
            sys.exit(1)

        stock_aligned = stock_close.loc[common_idx].values.flatten()
        bench_aligned = bench_close.loc[common_idx].values.flatten()

        stock_returns = np.diff(stock_aligned) / stock_aligned[:-1]
        bench_returns = np.diff(bench_aligned) / bench_aligned[:-1]

        valid = ~(np.isnan(stock_returns) | np.isnan(bench_returns))
        stock_returns = stock_returns[valid]
        bench_returns = bench_returns[valid]

        result = {
            "ticker": ticker,
            "benchmark": benchmark,
            "data_points": len(stock_returns),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "yfinance (daily returns, 2yr history)",
        }

        result["rolling_beta"] = compute_rolling_beta(
            stock_returns, bench_returns, args.window
        )
        result["tail_correlation"] = compute_tail_correlation(
            stock_returns, bench_returns
        )
        result["asymmetric_beta"] = compute_drawdown_beta(stock_returns, bench_returns)
        result["regime"] = compute_regime_classification(
            stock_returns, bench_returns, args.window
        )

        # Position sizing implication
        beta = result["rolling_beta"].get("current_beta", 1.0)
        tail_spike = result["tail_correlation"].get("correlation_spike", 0)
        downside_beta = result["asymmetric_beta"].get("downside_beta", beta)

        stress_adjusted_beta = max(beta, downside_beta) * (1 + max(0, tail_spike))
        result["position_sizing"] = {
            "stress_adjusted_beta": round(stress_adjusted_beta, 3),
            "effective_exposure_multiplier": round(stress_adjusted_beta, 2),
            "note": "Multiply notional position by this factor to estimate true portfolio exposure during stress events.",
        }

    except Exception as e:
        result = {"ticker": ticker, "error": str(e)}

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
