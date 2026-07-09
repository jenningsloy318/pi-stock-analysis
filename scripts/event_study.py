#!/usr/bin/env python3
"""Event study: compute abnormal returns around corporate events.

Usage:
    event_study.py AAPL --event earnings --date 2026-01-30
    event_study.py AAPL --event fda_decision --date 2025-11-15 --window 10
    event_study.py AAPL --event custom --date 2025-06-01 --window 5
    event_study.py --ticker AAPL --event-file ./reports/[TICKER]/events.json

Computes Cumulative Abnormal Returns (CAR) around a specified event date.
Uses market model: estimates α and β over estimation window, then computes
abnormal returns = actual - (α + β × market_return) over the event window.

Event types: earnings, merger_announcement, fda_decision, spin_off,
             dividend_change, executive_departure, regulatory_action, custom

Output: CAR, statistical significance (t-test), and interpretation.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

try:
    import numpy as np
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: numpy and yfinance required. Run: pip install numpy yfinance\n")
    sys.exit(1)


def event_study(
    ticker: str,
    event_date: str,
    benchmark: str = "SPY",
    estimation_window: int = 120,
    event_window: int = 5,
    gap_days: int = 10,
) -> dict:
    """Compute abnormal returns around an event date.

    Args:
        ticker: Stock ticker
        event_date: Event date (YYYY-MM-DD)
        benchmark: Market benchmark ticker
        estimation_window: Trading days before event (excluding gap) for model estimation
        event_window: Trading days around event for CAR calculation
        gap_days: Trading days between estimation window end and event (to avoid contamination)

    Market model: R_t = α + β × R_mt + ε_t
    Abnormal return: AR_t = R_t - (α + β × R_mt)
    CAR = Σ AR_t over event window
    """
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": f"Invalid date format: {event_date}. Use YYYY-MM-DD."}

    # Fetch stock and benchmark data
    # Need estimation_window + gap_days + event_window * 2 trading days before + after event
    total_days_needed = (estimation_window + gap_days + event_window * 2) * 2  # ~2 calendar days per trading day
    start_date = event_dt - timedelta(days=total_days_needed)
    end_date = event_dt + timedelta(days=event_window * 2)

    try:
        stock = yf.Ticker(ticker)
        bench = yf.Ticker(benchmark)

        stock_hist = stock.history(start=start_date.isoformat(), end=end_date.isoformat())
        bench_hist = bench.history(start=start_date.isoformat(), end=end_date.isoformat())

        if stock_hist.empty or bench_hist.empty:
            return {"error": f"No price data for {ticker} or {benchmark}"}
    except Exception as e:
        return {"error": str(e)}

    # Compute daily returns
    stock_returns = stock_hist["Close"].pct_change().dropna()
    bench_returns = bench_hist["Close"].pct_change().dropna()

    # Find event date index (closest trading day on or after event_date)
    event_date_str = event_dt.isoformat()
    event_mask = stock_returns.index >= event_date_str
    if not event_mask.any():
        # Event date might be a non-trading day; find next trading day
        event_dt_adj = event_dt
        for _ in range(5):
            event_dt_adj += timedelta(days=1)
            event_mask = stock_returns.index >= event_dt_adj.isoformat()
            if event_mask.any():
                break

    if not event_mask.any():
        return {"error": f"No trading data near event date {event_date}"}

    event_idx = event_mask.argmax()

    # Estimation window: estimation_window days before event, skipping gap_days
    est_end = event_idx - gap_days
    est_start = max(0, est_end - estimation_window)

    if est_end - est_start < 30:
        return {"error": f"Insufficient estimation window ({est_end - est_start} days). Need ≥30."}

    # Align stock and benchmark returns
    common_idx = stock_returns.index.intersection(bench_returns.index)
    stock_aligned = stock_returns.loc[common_idx]
    bench_aligned = bench_returns.loc[common_idx]

    # Recalculate event index in aligned data
    event_idx_aligned = (stock_aligned.index >= event_date_str).argmax()

    # Estimation window returns
    stock_est = stock_aligned.iloc[est_start:event_idx_aligned - gap_days].values
    bench_est = bench_aligned.iloc[est_start:event_idx_aligned - gap_days].values

    if len(stock_est) < 30:
        return {"error": "Insufficient estimation window data."}

    # OLS: stock = α + β × bench
    X = np.column_stack([np.ones(len(bench_est)), bench_est])
    beta = np.linalg.inv(X.T @ X) @ X.T @ stock_est
    alpha, beta_mkt = beta[0], beta[1]

    # Model residuals in estimation window (for standard error)
    predicted_est = alpha + beta_mkt * bench_est
    residuals_est = stock_est - predicted_est
    sigma_ar = np.std(residuals_est)
    if sigma_ar == 0:
        sigma_ar = 0.01

    # Event window returns
    event_slice = slice(
        max(0, event_idx_aligned - event_window),
        min(len(stock_aligned), event_idx_aligned + event_window + 1),
    )
    event_dates = stock_aligned.index[event_slice]
    stock_event = stock_aligned.iloc[event_slice].values
    bench_event = bench_aligned.iloc[event_slice].values

    # Abnormal returns
    predicted_event = alpha + beta_mkt * bench_event
    abnormal_returns = stock_event - predicted_event

    # CAR
    car = float(np.sum(abnormal_returns))

    # Standard error of CAR = σ_AR × √(event_window_size)
    event_window_size = len(abnormal_returns)
    se_car = sigma_ar * math.sqrt(event_window_size)

    # t-statistic
    t_stat = car / se_car if se_car > 0 else 0

    # Statistical significance
    if abs(t_stat) > 2.576:
        significance = "significant_at_1pct"
    elif abs(t_stat) > 1.96:
        significance = "significant_at_5pct"
    elif abs(t_stat) > 1.645:
        significance = "significant_at_10pct"
    else:
        significance = "not_significant"

    # Daily AR breakdown
    ar_breakdown = []
    for i, dt in enumerate(event_dates):
        ar_breakdown.append({
            "date": dt.strftime("%Y-%m-%d"),
            "days_from_event": i - event_window,
            "actual_return": round(float(stock_event[i]) * 100, 3),
            "expected_return": round(float(predicted_event[i]) * 100, 3),
            "abnormal_return": round(float(abnormal_returns[i]) * 100, 3),
        })

    return {
        "ticker": ticker,
        "event_date": event_date,
        "event_date_actual": event_dates[event_window].strftime("%Y-%m-%d") if len(event_dates) > event_window else event_date,
        "benchmark": benchmark,
        "estimation_window_days": len(stock_est),
        "event_window_days": event_window_size,
        "market_model": {
            "alpha": round(float(alpha), 6),
            "beta": round(float(beta_mkt), 4),
            "sigma_ar": round(float(sigma_ar), 6),
        },
        "abnormal_returns": {
            "car": round(car * 100, 3),
            "car_pct": f"{car * 100:.2f}%",
            "se_car": round(se_car * 100, 3),
            "t_statistic": round(float(t_stat), 3),
            "significance": significance,
        },
        "daily_abnormal_returns": ar_breakdown,
        "interpretation": (
            f"CAR: {car * 100:.2f}% (t={t_stat:.2f}, {significance.replace('_', ' ')}). "
            f"{'Statistically significant market reaction to this event.' if significance != 'not_significant' else 'No statistically significant market reaction detected.'}"
        ),
        "methodology": "Market model: AR_t = R_t - (α + β × R_mt). "
                       f"Estimation window: {estimation_window} trading days. "
                       f"CAR = Σ AR_t over ±{event_window} day event window.",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Event study: compute abnormal returns around corporate events"
    )
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument("--event", default="custom",
                        choices=["earnings", "merger_announcement", "fda_decision",
                                 "spin_off", "dividend_change", "executive_departure",
                                 "regulatory_action", "custom"],
                        help="Event type")
    parser.add_argument("--date", required=True, help="Event date (YYYY-MM-DD)")
    parser.add_argument("--benchmark", default="SPY", help="Market benchmark (default: SPY)")
    parser.add_argument("--window", type=int, default=5,
                        help="Event window in trading days (±N around event, default: 5)")
    parser.add_argument("--estimation-window", type=int, default=120,
                        help="Estimation window in trading days (default: 120)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    result = event_study(
        ticker=ticker,
        event_date=args.date,
        benchmark=args.benchmark,
        estimation_window=args.estimation_window,
        event_window=args.window,
    )

    result["event_type"] = args.event
    result["computed_at"] = datetime.now(timezone.utc).isoformat()
    result["usage"] = (
        "Use CAR to measure whether the event had a statistically significant "
        "market impact. Significant positive CAR = event was bullish surprise. "
        "Significant negative CAR = event was bearish surprise. "
        "Non-significant = event was anticipated/priced in."
    )

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
