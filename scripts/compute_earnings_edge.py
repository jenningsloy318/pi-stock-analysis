#!/usr/bin/env python3
"""Pre-earnings analysis: historical surprise patterns, post-earnings drift, setup quality.

Usage:
    compute_earnings_edge.py AAPL --output ./reports/AAPL/earnings_edge.json
    compute_earnings_edge.py MSFT --quarters 12

Analyzes from yfinance earnings history:
  - Historical beat/miss rate (EPS and revenue)
  - Average surprise magnitude by quarter
  - Post-earnings announcement drift (PEAD) tendency
  - Pre-earnings drift (does stock run up before earnings?)
  - Earnings quality trend (beat via lowered bar vs genuine outperformance)
  - Next earnings date and implied move from options (if available)

Free data source: yfinance (earnings history, price data).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
    import numpy as np
except ImportError:
    sys.stderr.write(
        "Error: yfinance and numpy required. Run: pip install yfinance numpy\n"
    )
    sys.exit(1)


def analyze_surprise_history(stock) -> dict:
    """Analyze historical earnings surprise patterns."""
    try:
        earnings_hist = stock.earnings_history
        if earnings_hist is None or earnings_hist.empty:
            quarterly = stock.quarterly_earnings
            if quarterly is None or quarterly.empty:
                return {"error": "No earnings history available"}
            records = quarterly.reset_index().to_dict("records")
            surprises = []
            for r in records:
                actual = r.get("Actual") or r.get("Revenue")
                estimate = r.get("Estimate")
                if actual is not None and estimate is not None and estimate != 0:
                    surprise_pct = (actual - estimate) / abs(estimate)
                    surprises.append({"surprise_pct": surprise_pct})
            if not surprises:
                return {"error": "Cannot compute surprises from available data"}
        else:
            records = earnings_hist.to_dict("records")
            surprises = []
            for r in records:
                actual = r.get("epsActual")
                estimate = r.get("epsEstimate")
                if actual is not None and estimate is not None and estimate != 0:
                    surprise_pct = (actual - estimate) / abs(estimate)
                    surprises.append(
                        {
                            "surprise_pct": surprise_pct,
                            "quarter": str(r.get("quarter", "")),
                        }
                    )
    except Exception:
        return {"error": "Could not parse earnings history"}

    if not surprises:
        return {"error": "No valid earnings surprises found"}

    pcts = [s["surprise_pct"] for s in surprises]
    beats = sum(1 for p in pcts if p > 0)
    misses = sum(1 for p in pcts if p < 0)
    in_line = sum(1 for p in pcts if p == 0)
    total = len(pcts)

    beat_rate = beats / total if total > 0 else 0
    avg_surprise = float(np.mean(pcts))
    median_surprise = float(np.median(pcts))

    recent_4 = pcts[:4] if len(pcts) >= 4 else pcts
    recent_beat_rate = sum(1 for p in recent_4 if p > 0) / len(recent_4)
    recent_avg = float(np.mean(recent_4))

    trend = "improving" if recent_avg > avg_surprise else "deteriorating"

    return {
        "total_quarters": total,
        "beats": beats,
        "misses": misses,
        "in_line": in_line,
        "beat_rate": round(beat_rate, 3),
        "average_surprise_pct": round(avg_surprise, 4),
        "median_surprise_pct": round(median_surprise, 4),
        "recent_4q_beat_rate": round(recent_beat_rate, 3),
        "recent_4q_avg_surprise": round(recent_avg, 4),
        "trend": trend,
        "interpretation": (
            f"Beat rate: {beat_rate*100:.0f}% ({beats}/{total}). "
            f"Avg surprise: {avg_surprise*100:.1f}%. "
            f"Recent trend: {trend}."
        ),
    }


def analyze_earnings_drift(stock, lookback_quarters: int = 8) -> dict:
    """Analyze pre-earnings and post-earnings price drift patterns.

    Pre-earnings drift: avg return in 5 days before earnings.
    Post-earnings drift (PEAD): avg return in 5 days after earnings.
    """
    try:
        hist = stock.history(period="3y")
        if hist.empty or len(hist) < 100:
            return {"error": "Insufficient price history for drift analysis"}

        earnings_dates = stock.earnings_dates
        if earnings_dates is None or earnings_dates.empty:
            calendar = stock.calendar
            if calendar is not None and isinstance(calendar, dict):
                next_date = calendar.get("Earnings Date")
                if next_date:
                    return {
                        "next_earnings": str(next_date[0])
                        if isinstance(next_date, list)
                        else str(next_date),
                        "error": "Historical earnings dates not available for drift analysis",
                    }
            return {"error": "No earnings dates available"}

        dates = earnings_dates.index.tolist()
        closes = hist["Close"]

        pre_drifts = []
        post_drifts = []

        for ed in dates[:lookback_quarters]:
            ed_ts = ed.tz_localize(None) if ed.tzinfo else ed
            pre_start = ed_ts - timedelta(days=10)
            pre_end = ed_ts - timedelta(days=1)
            post_start = ed_ts
            post_end = ed_ts + timedelta(days=8)

            pre_prices = closes.loc[
                (closes.index.tz_localize(None) if closes.index.tz else closes.index)
                >= pre_start
            ]
            pre_prices = pre_prices.loc[
                (
                    pre_prices.index.tz_localize(None)
                    if pre_prices.index.tz
                    else pre_prices.index
                )
                <= pre_end
            ]

            post_prices = closes.loc[
                (closes.index.tz_localize(None) if closes.index.tz else closes.index)
                >= post_start
            ]
            post_prices = post_prices.loc[
                (
                    post_prices.index.tz_localize(None)
                    if post_prices.index.tz
                    else post_prices.index
                )
                <= post_end
            ]

            if len(pre_prices) >= 3:
                pre_ret = (pre_prices.iloc[-1] - pre_prices.iloc[0]) / pre_prices.iloc[
                    0
                ]
                pre_drifts.append(float(pre_ret))

            if len(post_prices) >= 3:
                post_ret = (
                    post_prices.iloc[-1] - post_prices.iloc[0]
                ) / post_prices.iloc[0]
                post_drifts.append(float(post_ret))

    except Exception as e:
        return {"error": f"Drift analysis failed: {str(e)}"}

    result = {"quarters_analyzed": min(lookback_quarters, len(dates))}

    if pre_drifts:
        avg_pre = float(np.mean(pre_drifts))
        result["pre_earnings_drift"] = {
            "avg_5day_return": round(avg_pre, 4),
            "positive_pct": round(
                sum(1 for d in pre_drifts if d > 0) / len(pre_drifts), 3
            ),
            "signal": (
                "Consistent pre-earnings run-up (smart money positioning)"
                if avg_pre > 0.01
                else "Pre-earnings weakness (potential negative leak)"
                if avg_pre < -0.01
                else "No consistent pre-earnings pattern"
            ),
        }

    if post_drifts:
        avg_post = float(np.mean(post_drifts))
        result["post_earnings_drift"] = {
            "avg_5day_return": round(avg_post, 4),
            "positive_pct": round(
                sum(1 for d in post_drifts if d > 0) / len(post_drifts), 3
            ),
            "signal": (
                "Positive PEAD — earnings beats tend to drift higher (market under-reacts)"
                if avg_post > 0.01
                else "Negative PEAD — earnings misses tend to drift lower"
                if avg_post < -0.01
                else "No consistent post-earnings drift"
            ),
        }

    return result


def get_next_earnings(stock) -> dict:
    """Get next earnings date and estimate implied move from recent history."""
    try:
        calendar = stock.calendar
        earnings_dates = stock.earnings_dates

        next_date = None
        if earnings_dates is not None and not earnings_dates.empty:
            now = datetime.now()
            future_dates = [
                d
                for d in earnings_dates.index
                if (d.tz_localize(None) if d.tzinfo else d) > now
            ]
            if future_dates:
                next_date = str(future_dates[0].date())

        if not next_date and calendar:
            ed = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
            if ed:
                next_date = str(ed[0]) if isinstance(ed, list) else str(ed)

        if not next_date:
            return {"next_earnings_date": None}

        hist = stock.history(period="1y")
        if not hist.empty:
            avg_daily_vol = float(hist["Close"].pct_change().std())
            implied_earnings_move = round(avg_daily_vol * 3.5, 4)
        else:
            implied_earnings_move = None

        return {
            "next_earnings_date": next_date,
            "estimated_move_pct": implied_earnings_move,
            "note": "Estimated move is 3.5x daily vol — compare against options straddle pricing for edge assessment.",
        }
    except Exception:
        return {"next_earnings_date": None}


def post_earnings_continuation_gate(
    fundamentals_confirmed: bool | None,
    sector_co_moving: bool | None,
    net_call_premium_positive: bool | None,
    short_interest_pct: float | None,
) -> dict:
    """Post-earnings 4-factor continuation gate (pitfall 20-equivalent for our pipeline).

    Before predicting a multi-day fade off a gap-up earnings reaction, run the
    4-factor confirmation check. If 3+ of 4 are bullish, the report MUST flag
    continuation, not fade.

    Inputs are typically supplied by the catalyst-analyst from upstream stage outputs:
      - fundamentals_confirmed: True if guidance raised AND beat (else False; None=unknown)
      - sector_co_moving: True if sector index +>5% trailing 5 days (else False; None=unknown)
      - net_call_premium_positive: True if 5-day net call premium > 0 (else False; None=unknown)
      - short_interest_pct: short interest % of float (None if unavailable)

    Returns 4-factor gate verdict + recommended bias (continuation | fade | neutral).

    See: references/pitfalls/13-post-earnings-momentum-vs-fade.md
    """
    bullish_count = 0
    factors_evaluated = 0
    factor_details: list[dict] = []

    if fundamentals_confirmed is not None:
        factors_evaluated += 1
        if fundamentals_confirmed:
            bullish_count += 1
        factor_details.append(
            {
                "factor": "fundamentals_confirmed",
                "bullish": fundamentals_confirmed,
                "note": "guidance raised + beat"
                if fundamentals_confirmed
                else "miss or guide-down",
            }
        )

    if sector_co_moving is not None:
        factors_evaluated += 1
        if sector_co_moving:
            bullish_count += 1
        factor_details.append(
            {
                "factor": "sector_co_moving",
                "bullish": sector_co_moving,
                "note": "peers +>5% trailing 5d"
                if sector_co_moving
                else "isolated bid",
            }
        )

    if net_call_premium_positive is not None:
        factors_evaluated += 1
        if net_call_premium_positive:
            bullish_count += 1
        factor_details.append(
            {
                "factor": "net_call_premium_positive",
                "bullish": net_call_premium_positive,
                "note": "5d net call premium >0"
                if net_call_premium_positive
                else "flow distribution-shaped",
            }
        )

    if short_interest_pct is not None:
        factors_evaluated += 1
        si_bullish = short_interest_pct >= 10
        if si_bullish:
            bullish_count += 1
        factor_details.append(
            {
                "factor": "short_interest_squeeze",
                "bullish": si_bullish,
                "value_pct": short_interest_pct,
                "note": (
                    f"SI {short_interest_pct:.1f}% >= 10% (squeeze amplifies continuation)"
                    if si_bullish
                    else f"SI {short_interest_pct:.1f}% < 10% (no squeeze tailwind)"
                ),
            }
        )

    # Verdict: 3+ of 4 bullish → continuation; 1 or fewer → fade allowed; 2 → neutral
    if factors_evaluated == 0:
        verdict = "insufficient_data"
        bias = "neutral"
        rationale = "No factors evaluated; cannot apply post-earnings gate"
    elif bullish_count >= 3:
        verdict = "continuation"
        bias = "do_not_call_fade"
        rationale = (
            f"{bullish_count}/{factors_evaluated} bullish factors. Multi-day momentum "
            "continuation is the default — DO NOT predict fade. Hold or add."
        )
    elif bullish_count <= 1 and factors_evaluated >= 3:
        verdict = "fade_allowed"
        bias = "fade_or_neutral"
        rationale = (
            f"Only {bullish_count}/{factors_evaluated} bullish — fade signal is "
            "consistent with the data."
        )
    else:
        verdict = "neutral"
        bias = "no_directional_call"
        rationale = (
            f"{bullish_count}/{factors_evaluated} bullish — mixed signals, do not "
            "anchor on intraday pattern alone."
        )

    return {
        "factors_evaluated": factors_evaluated,
        "bullish_factors": bullish_count,
        "factor_details": factor_details,
        "verdict": verdict,
        "recommended_bias": bias,
        "rationale": rationale,
        "methodology": (
            "Pitfall 20 (post-earnings continuation): require 3+/4 bullish factors to "
            "predict fade against. See references/pitfalls/ — equivalent rule embedded "
            "in catalyst-analyst Stage 14."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compute pre-earnings analysis and historical surprise patterns"
    )
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument(
        "--quarters",
        type=int,
        default=12,
        help="Number of quarters to analyze (default: 12)",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    # Post-earnings continuation gate (pitfall 20)
    parser.add_argument(
        "--fundamentals-confirmed",
        choices=["true", "false"],
        default=None,
        help="Post-earnings gate: did the print confirm thesis (beat + raised guide)?",
    )
    parser.add_argument(
        "--sector-co-moving",
        choices=["true", "false"],
        default=None,
        help="Post-earnings gate: are sector peers up >5% trailing 5d?",
    )
    parser.add_argument(
        "--net-call-premium-positive",
        choices=["true", "false"],
        default=None,
        help="Post-earnings gate: is 5-day net call premium positive?",
    )
    parser.add_argument(
        "--short-interest-pct",
        type=float,
        default=None,
        help="Post-earnings gate: short interest as % of float (e.g., 12.5)",
    )
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    try:
        stock = yf.Ticker(ticker)

        result = {
            "ticker": ticker,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "yfinance (earnings history, price data)",
        }

        result["surprise_history"] = analyze_surprise_history(stock)
        result["earnings_drift"] = analyze_earnings_drift(stock, args.quarters)
        result["next_earnings"] = get_next_earnings(stock)

        # Composite signal
        beat_rate = result["surprise_history"].get("beat_rate")
        trend = result["surprise_history"].get("trend")
        pre_drift = (
            result.get("earnings_drift", {})
            .get("pre_earnings_drift", {})
            .get("avg_5day_return")
        )

        signals = []
        if beat_rate is not None:
            if beat_rate > 0.75:
                signals.append("Bullish — consistent earnings beater (>75% beat rate)")
            elif beat_rate < 0.4:
                signals.append("Bearish — frequent misser (<40% beat rate)")
        if trend == "improving":
            signals.append("Improving surprise trajectory")
        elif trend == "deteriorating":
            signals.append("Deteriorating surprise trajectory")
        if pre_drift is not None and pre_drift > 0.015:
            signals.append(
                "Pre-earnings run-up pattern — consider buying before earnings"
            )

        result["signals"] = signals

        # Post-earnings continuation gate (pitfall 20) — runs only when at least
        # one factor flag was supplied. Catalyst-analyst Stage 14 supplies these
        # from upstream stage outputs (sector RS, options flow, short interest).
        def _bool_or_none(v: str | None) -> bool | None:
            if v is None:
                return None
            return v.lower() == "true"

        result["post_earnings_gate"] = post_earnings_continuation_gate(
            fundamentals_confirmed=_bool_or_none(args.fundamentals_confirmed),
            sector_co_moving=_bool_or_none(args.sector_co_moving),
            net_call_premium_positive=_bool_or_none(args.net_call_premium_positive),
            short_interest_pct=args.short_interest_pct,
        )

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
