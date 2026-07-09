#!/usr/bin/env python3
"""Backtest past stock analysis reports against actual market outcomes.

Usage:
    backtest.py                                    # scan all reports
    backtest.py --ticker AAPL                      # single ticker
    backtest.py --ticker AAPL --since 2025-01-01   # date filter
    backtest.py --output ./reports/backtest.json         # output file

Reads reports from ./reports/[TICKER]/[TICKER]_[Type]_[Date].md,
extracts conviction ratings, target prices, and time horizons, then
fetches historical prices to determine whether predictions were accurate.

Metrics computed:
  - Hit rate: % of targets reached within time horizon
  - Directional accuracy: % correct direction predictions
  - Mean absolute error (MAE) for price targets
  - Mean percentage error (MPE)
  - Sharpe-style information ratio
  - Calibration data for conviction scoring weights
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: yfinance required. Run: pip install yfinance\n")
    sys.exit(1)


REPORTS_DIR = "reports"


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------

def parse_report(filepath: str) -> dict | None:
    """Parse a stock analysis report markdown file.

    Extracts: ticker, report_type, report_date, conviction, rating,
    target_price, time_horizon, entry_criteria, stop_loss.
    """
    try:
        with open(filepath, "r") as f:
            text = f.read()
    except Exception:
        return None

    result: dict[str, Any] = {"filepath": filepath}

    # Ticker from filename: [TICKER]_[Type]_[Date].md
    basename = os.path.basename(filepath)
    parts = basename.replace(".md", "").split("_")
    if len(parts) >= 3:
        result["ticker"] = parts[0]
        # Join middle parts for report type (long/mid/short/investment)
        result["report_type"] = "_".join(parts[1:-1])
        result["report_date_str"] = parts[-1]

    # Report date from filename
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', basename)
    if date_match:
        try:
            result["report_date"] = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass

    if "report_date" not in result:
        result["report_date"] = None

    # Conviction Rating
    conv_match = re.search(r'Conviction\s*Rating:\s*(\d+(?:\.\d+)?)\s*/\s*10', text)
    if conv_match:
        result["conviction"] = float(conv_match.group(1))

    # Confidence
    conf_match = re.search(r'Confidence:\s*(\w+)', text)
    if conf_match:
        result["confidence"] = conf_match.group(1)

    # Rating
    rating_match = re.search(r'\*\*Rating\*\*:\s*(Strong Buy|Buy|Hold(?:\s*/\s*Accumulate)?|Hold(?:\s*/\s*Reduce)?|Sell|Strong Sell|Avoid)', text, re.IGNORECASE)
    if rating_match:
        result["rating"] = rating_match.group(1).strip()

    # Target Price
    target_matches = re.findall(r'Target\s*Price:\s*\$?([\d,]+(?:\.\d+)?)\s*(?:\(([+-]?\d+)%?\s*(?:upside|downside)\))?', text, re.IGNORECASE)
    if not target_matches:
        target_matches = re.findall(r'\*\*Target\s*Price\*\*:\s*\$?([\d,]+(?:\.\d+)?)', text)
    if target_matches:
        try:
            price_str = target_matches[0] if isinstance(target_matches[0], str) else target_matches[0][0]
            result["target_price"] = float(price_str.replace(",", ""))
        except (ValueError, IndexError):
            pass

    # Time Horizon
    horizon_match = re.search(r'Time\s*Horizon:\s*(\d+(?:-\d+)?\s*(?:years?|months?|weeks?|days?))', text, re.IGNORECASE)
    if not horizon_match:
        horizon_match = re.search(r'horizon[\s:]*(\d+(?:-\d+)?\s*(?:years?|months?|weeks?|days?))', text, re.IGNORECASE)
    if horizon_match:
        result["time_horizon_str"] = horizon_match.group(1)

    # Stop Loss
    sl_match = re.search(r'Stop\s*Loss:\s*\$?([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if sl_match:
        try:
            result["stop_loss"] = float(sl_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Entry Price / Criteria
    entry_match = re.search(r'Entry\s*(?:Price|Criteria):\s*\$?([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if entry_match:
        try:
            result["entry_price"] = float(entry_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Current Price (at time of report) - from header
    price_match = re.search(r'Current\s*Price:\s*\$?([\d,]+(?:\.\d+)?)', text)
    if price_match:
        try:
            result["report_price"] = float(price_match.group(1).replace(",", ""))
        except ValueError:
            pass

    return result


# ---------------------------------------------------------------------------
# Price outcome checking
# ---------------------------------------------------------------------------

def check_outcome(report: dict) -> dict:
    """Check whether a report's target was met by fetching historical prices."""
    ticker = report.get("ticker", "")
    report_date = report.get("report_date")
    target_price = report.get("target_price")
    report_price = report.get("report_price")

    if not ticker or not report_date or not target_price:
        return {"status": "insufficient_data", "reason": "Missing ticker, date, or target price"}

    try:
        # Fetch price history from report date to horizon end
        horizon_days = _parse_horizon_days(report.get("time_horizon_str", "12 months"))
        end_date = report_date + timedelta(days=horizon_days)

        stock = yf.Ticker(ticker)
        hist = stock.history(start=report_date.isoformat(), end=end_date.isoformat())

        if hist.empty:
            return {"status": "no_data", "reason": "No price data available for period"}

        prices = hist["Close"].values
        if len(prices) == 0:
            return {"status": "no_data", "reason": "Empty price series"}

        start_price = prices[0]
        max_price = float(prices.max())
        min_price = float(prices.min())
        end_price = float(prices[-1])

        # Actual return
        if start_price > 0:
            actual_return = (end_price - start_price) / start_price
        else:
            actual_return = None

        # Target return
        if report_price and report_price > 0:
            target_return = (target_price - report_price) / report_price
        elif start_price > 0:
            target_return = (target_price - start_price) / start_price
        else:
            target_return = None

        # Did target get hit?
        target_hit = max_price >= target_price if target_price > start_price else min_price <= target_price

        # Directional accuracy
        if report_price and report_price > 0:
            predicted_direction = "up" if target_price > report_price else "down"
        else:
            predicted_direction = "up" if target_price > start_price else "down"
        actual_direction = "up" if end_price > start_price else "down"
        direction_correct = predicted_direction == actual_direction

        # Stop loss triggered?
        stop_loss = report.get("stop_loss")
        sl_triggered = False
        if stop_loss:
            sl_triggered = min_price <= stop_loss

        # Price target error
        price_error = None
        price_error_pct = None
        if target_price > 0:
            price_error = abs(max_price - target_price) if target_hit else abs(target_price - end_price)
            price_error_pct = price_error / target_price

        return {
            "status": "complete",
            "start_price": round(start_price, 2),
            "end_price": round(end_price, 2),
            "max_price": round(max_price, 2),
            "min_price": round(min_price, 2),
            "actual_return": round(actual_return, 4) if actual_return is not None else None,
            "target_return": round(target_return, 4) if target_return is not None else None,
            "target_hit": target_hit,
            "direction_correct": direction_correct,
            "stop_loss_triggered": sl_triggered,
            "price_error": round(price_error, 2) if price_error is not None else None,
            "price_error_pct": round(price_error_pct, 4) if price_error_pct is not None else None,
            "horizon_days": horizon_days,
            "actual_days": len(prices),
            "predicted_direction": predicted_direction,
            "actual_direction": actual_direction,
        }

    except Exception as e:
        return {"status": "error", "reason": str(e)}


def _parse_horizon_days(horizon_str: str | None) -> int:
    """Parse time horizon string to approximate days."""
    if not horizon_str:
        return 365  # Default 1 year

    horizon_str = horizon_str.lower().strip()
    # Extract number and unit
    match = re.search(r'(\d+(?:-\d+)?)\s*(years?|months?|weeks?|days?)', horizon_str)
    if not match:
        return 365

    num_part = match.group(1)
    unit = match.group(2)

    # Handle ranges like "1-3" → use midpoint
    if "-" in num_part:
        parts = num_part.split("-")
        try:
            num = (float(parts[0]) + float(parts[1])) / 2
        except ValueError:
            num = float(parts[0])
    else:
        num = float(num_part)

    if "year" in unit:
        return int(num * 365)
    elif "month" in unit:
        return int(num * 30)
    elif "week" in unit:
        return int(num * 7)
    else:
        return int(num)


# ---------------------------------------------------------------------------
# Aggregate metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(outcomes: list[dict]) -> dict:
    """Compute aggregate accuracy metrics from a list of outcomes."""
    complete = [o for o in outcomes if o.get("outcome", {}).get("status") == "complete"]
    if not complete:
        return {"error": "No complete outcomes to analyze", "total_reports": len(outcomes)}

    # Hit rate
    hits = [o for o in complete if o["outcome"]["target_hit"]]
    hit_rate = len(hits) / len(complete) if complete else 0

    # Directional accuracy
    dir_correct = [o for o in complete if o["outcome"]["direction_correct"]]
    dir_accuracy = len(dir_correct) / len(complete) if complete else 0

    # Price errors
    errors_pct = [o["outcome"]["price_error_pct"] for o in complete if o["outcome"].get("price_error_pct") is not None]
    mae_pct = sum(errors_pct) / len(errors_pct) if errors_pct else None

    # Returns
    actual_returns = [o["outcome"]["actual_return"] for o in complete if o["outcome"].get("actual_return") is not None]
    avg_return = sum(actual_returns) / len(actual_returns) if actual_returns else None

    # By conviction band
    bands = defaultdict(list)
    for o in complete:
        conv = o.get("conviction")
        if conv is not None:
            band = "high" if conv >= 7.5 else "mid" if conv >= 5.0 else "low"
            bands[band].append(o["outcome"])

    band_metrics = {}
    for band, band_outcomes in bands.items():
        band_hits = [bo for bo in band_outcomes if bo["target_hit"]]
        band_dir = [bo for bo in band_outcomes if bo["direction_correct"]]
        band_metrics[band] = {
            "count": len(band_outcomes),
            "hit_rate": len(band_hits) / len(band_outcomes) if band_outcomes else 0,
            "directional_accuracy": len(band_dir) / len(band_outcomes) if band_outcomes else 0,
        }

    # By rating
    rating_outcomes = defaultdict(list)
    for o in complete:
        rating = o.get("rating", "Unknown")
        rating_outcomes[rating].append(o["outcome"])

    rating_metrics = {}
    for rating, ros in rating_outcomes.items():
        rhits = [ro for ro in ros if ro["target_hit"]]
        rating_metrics[rating] = {
            "count": len(ros),
            "hit_rate": len(rhits) / len(ros) if ros else 0,
        }

    # Information ratio (approximate)
    # IR = (mean excess return) / (std of excess returns)
    excess_returns = []
    for o in complete:
        ar = o["outcome"].get("actual_return")
        tr = o["outcome"].get("target_return")
        if ar is not None and tr is not None:
            excess_returns.append(ar - tr)

    if excess_returns and len(excess_returns) > 1:
        mean_excess = sum(excess_returns) / len(excess_returns)
        variance = sum((x - mean_excess) ** 2 for x in excess_returns) / (len(excess_returns) - 1)
        std_excess = variance ** 0.5
        ir = mean_excess / std_excess if std_excess > 0 else 0
    else:
        ir = None

    return {
        "total_reports": len(outcomes),
        "complete_outcomes": len(complete),
        "hit_rate": round(hit_rate, 4),
        "directional_accuracy": round(dir_accuracy, 4),
        "mean_price_error_pct": round(mae_pct, 4) if mae_pct else None,
        "avg_actual_return": round(avg_return, 4) if avg_return else None,
        "information_ratio": round(ir, 4) if ir is not None else None,
        "by_conviction_band": band_metrics,
        "by_rating": rating_metrics,
        "individual_outcomes": [{
            "ticker": o.get("ticker"),
            "report_date": str(o.get("report_date", "")),
            "report_type": o.get("report_type"),
            "conviction": o.get("conviction"),
            "rating": o.get("rating"),
            "target_hit": o["outcome"]["target_hit"],
            "direction_correct": o["outcome"]["direction_correct"],
            "actual_return": o["outcome"]["actual_return"],
            "target_return": o["outcome"]["target_return"],
        } for o in complete],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_reports(ticker: str | None = None, since: str | None = None) -> list[str]:
    """Find all report markdown files matching criteria."""
    reports = []
    base = Path(REPORTS_DIR)

    if not base.exists():
        return []

    pattern = f"{ticker}/" if ticker else "*/"
    glob_pattern = f"{pattern}*.md"

    for filepath in base.glob(glob_pattern):
        if filepath.is_file():
            # Date filter
            if since:
                try:
                    since_date = datetime.strptime(since, "%Y-%m-%d").date()
                    # Extract date from filename
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filepath.name)
                    if date_match:
                        file_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
                        if file_date < since_date:
                            continue
                except ValueError:
                    pass
            reports.append(str(filepath))

    return sorted(reports)


def main():
    parser = argparse.ArgumentParser(description="Backtest stock analysis reports")
    parser.add_argument("--ticker", help="Filter to specific ticker")
    parser.add_argument("--since", help="Only reports on or after this date (YYYY-MM-DD)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--reports-dir", default=REPORTS_DIR, help="Reports directory")
    parser.add_argument("--verbose", action="store_true", help="Print per-report outcomes")
    args = parser.parse_args()

    global REPORTS_DIR
    REPORTS_DIR = args.reports_dir

    report_files = find_reports(args.ticker, args.since)

    if not report_files:
        result = {"error": "No reports found", "reports_dir": REPORTS_DIR, "reports_found": 0}
        output = json.dumps(result, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)
        sys.exit(0)

    outcomes = []
    for rf in report_files:
        report = parse_report(rf)
        if not report:
            outcomes.append({"filepath": rf, "error": "Could not parse report"})
            continue

        outcome = check_outcome(report)
        report["outcome"] = outcome
        outcomes.append(report)

        if args.verbose:
            tag = "✓" if outcome.get("target_hit") else "✗"
            print(f"{tag} {report.get('ticker','?'):<6} {report.get('report_type','?'):<15} "
                  f"Conv={report.get('conviction','?')} "
                  f"Target=${report.get('target_price','?')} "
                  f"Hit={outcome.get('target_hit')} "
                  f"Dir={'✓' if outcome.get('direction_correct') else '✗'} "
                  f"Return={outcome.get('actual_return','?')}",
                  file=sys.stderr)

    metrics = compute_metrics(outcomes)
    metrics["reports_dir"] = REPORTS_DIR
    metrics["reports_found"] = len(report_files)

    output = json.dumps(metrics, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)

    # Summary to stderr
    if metrics.get("hit_rate") is not None:
        print(f"\nBacktest Results: {metrics['complete_outcomes']} reports evaluated", file=sys.stderr)
        print(f"  Hit Rate: {metrics['hit_rate']:.1%}", file=sys.stderr)
        print(f"  Directional Accuracy: {metrics['directional_accuracy']:.1%}", file=sys.stderr)
        print(f"  Mean Price Error: {metrics.get('mean_price_error_pct', 0):.1%}", file=sys.stderr)
        if metrics.get("information_ratio") is not None:
            print(f"  Information Ratio: {metrics['information_ratio']:.3f}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
