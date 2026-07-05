#!/usr/bin/env python3
"""Quarterly seasonality analysis for revenue and earnings patterns.

Usage:
    compute_seasonality.py ./reports/AAPL/raw-data.json
    compute_seasonality.py raw-data.json --output ./reports/AAPL/seasonality.json

Detects seasonal patterns in quarterly revenue/EPS data and computes:
  - Seasonal strength index per fiscal quarter (Q1-Q4)
  - Year-over-year growth decomposition (trend vs seasonal)
  - Current quarter position vs seasonal expectation
  - Coefficient of variation across quarters (seasonality strength)
"""

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np


def extract_quarterly_data(quarterly: list[dict]) -> list[tuple[int, int, float]]:
    """Extract (year, quarter, value) tuples from quarterly series."""
    results = []
    for entry in quarterly:
        period = entry.get("period", "")
        value = entry.get("value")
        if value is None:
            continue
        try:
            dt = datetime.strptime(period[:10], "%Y-%m-%d")
            quarter = (dt.month - 1) // 3 + 1
            results.append((dt.year, quarter, float(value)))
        except (ValueError, TypeError):
            continue
    return sorted(results, key=lambda x: (x[0], x[1]))


def compute_seasonal_indices(data: list[tuple[int, int, float]]) -> dict:
    """Compute seasonal strength indices for each quarter.

    Returns index where 1.0 = average quarter; >1.0 = above-average; <1.0 = below-average.
    """
    if len(data) < 4:
        return {"error": "Insufficient quarterly data (need at least 4 quarters)"}

    by_quarter: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    for _, q, val in data:
        by_quarter[q].append(val)

    quarterly_means = {}
    for q in range(1, 5):
        if by_quarter[q]:
            quarterly_means[q] = np.mean(by_quarter[q])
        else:
            quarterly_means[q] = None

    valid_means = [v for v in quarterly_means.values() if v is not None]
    if not valid_means:
        return {"error": "No valid quarterly data"}

    overall_mean = np.mean(valid_means)
    if overall_mean == 0:
        return {"error": "Zero mean revenue — cannot compute seasonal index"}

    indices = {}
    for q in range(1, 5):
        if quarterly_means[q] is not None:
            indices[f"Q{q}"] = round(quarterly_means[q] / overall_mean, 4)
        else:
            indices[f"Q{q}"] = None

    valid_indices = [v for v in indices.values() if v is not None]
    seasonality_strength = round(float(np.std(valid_indices)), 4) if len(valid_indices) >= 3 else None

    strongest = max(indices, key=lambda k: indices[k] or 0)
    weakest = min(indices, key=lambda k: indices[k] or float("inf"))

    return {
        "seasonal_indices": indices,
        "seasonality_strength": seasonality_strength,
        "strongest_quarter": strongest,
        "weakest_quarter": weakest,
        "interpretation": (
            f"Strong seasonality (CV={seasonality_strength:.3f}): {strongest} is peak, {weakest} is trough"
            if seasonality_strength and seasonality_strength > 0.10
            else f"Mild seasonality (CV={seasonality_strength:.3f}): relatively consistent across quarters"
            if seasonality_strength
            else "Insufficient data for seasonality assessment"
        ),
        "quarters_analyzed": len(data),
        "years_covered": len(set(y for y, _, _ in data)),
    }


def compute_yoy_decomposition(data: list[tuple[int, int, float]]) -> list[dict]:
    """Decompose year-over-year growth into trend and seasonal components."""
    if len(data) < 8:
        return []

    by_yq: dict[tuple[int, int], float] = {(y, q): v for y, q, v in data}
    decomposition = []

    for y, q, val in data:
        prior_val = by_yq.get((y - 1, q))
        if prior_val and prior_val != 0:
            yoy_growth = (val - prior_val) / abs(prior_val)
            decomposition.append({
                "year": y,
                "quarter": q,
                "value": round(val, 2),
                "yoy_growth": round(yoy_growth, 4),
            })

    return decomposition


def assess_current_quarter(
    data: list[tuple[int, int, float]], seasonal_indices: dict
) -> dict | None:
    """Assess most recent quarter vs seasonal expectation."""
    if not data or not seasonal_indices.get("seasonal_indices"):
        return None

    latest = data[-1]
    year, quarter, value = latest

    idx_key = f"Q{quarter}"
    seasonal_idx = seasonal_indices["seasonal_indices"].get(idx_key)
    if seasonal_idx is None:
        return None

    same_quarter_vals = [v for y, q, v in data[:-1] if q == quarter]
    if not same_quarter_vals:
        return None

    historical_mean = np.mean(same_quarter_vals)
    if historical_mean == 0:
        return None

    vs_historical = (value - historical_mean) / abs(historical_mean)

    return {
        "period": f"{year}-Q{quarter}",
        "value": round(value, 2),
        "seasonal_index": seasonal_idx,
        "vs_same_quarter_history": round(vs_historical, 4),
        "assessment": (
            "Above seasonal expectation"
            if vs_historical > 0.05
            else "Below seasonal expectation"
            if vs_historical < -0.05
            else "In line with seasonal expectation"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Quarterly seasonality analysis")
    parser.add_argument("input", help="Path to raw-data.json from fetch_financials.py")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    with open(args.input) as f:
        raw_data = json.load(f)

    ticker = list(raw_data.keys())[0] if raw_data else "UNKNOWN"
    data = raw_data.get(ticker, {})
    quarterly = data.get("quarterly", {})

    quarterly_revenue = quarterly.get("revenue", [])
    quarterly_eps = quarterly.get("eps", [])

    result = {
        "ticker": ticker,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "Seasonal index = quarter mean / overall mean. Index > 1.0 = above-average quarter.",
    }

    rev_data = extract_quarterly_data(quarterly_revenue)
    if rev_data:
        rev_seasonality = compute_seasonal_indices(rev_data)
        rev_yoy = compute_yoy_decomposition(rev_data)
        rev_current = assess_current_quarter(rev_data, rev_seasonality)
        result["revenue_seasonality"] = {
            **rev_seasonality,
            "yoy_decomposition": rev_yoy[-8:] if rev_yoy else [],
            "current_assessment": rev_current,
        }
    else:
        result["revenue_seasonality"] = {"error": "No quarterly revenue data available"}

    eps_data = extract_quarterly_data(quarterly_eps)
    if eps_data:
        eps_seasonality = compute_seasonal_indices(eps_data)
        eps_yoy = compute_yoy_decomposition(eps_data)
        eps_current = assess_current_quarter(eps_data, eps_seasonality)
        result["eps_seasonality"] = {
            **eps_seasonality,
            "yoy_decomposition": eps_yoy[-8:] if eps_yoy else [],
            "current_assessment": eps_current,
        }
    else:
        result["eps_seasonality"] = {"error": "No quarterly EPS data available"}

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
