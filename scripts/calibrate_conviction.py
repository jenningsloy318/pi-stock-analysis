#!/usr/bin/env python3
"""Bayesian-style conviction calibration against historical outcomes.

Usage:
    calibrate_conviction.py --db ~/.stock-analysis/state.db --output calibration.json
    calibrate_conviction.py --db ~/.stock-analysis/state.db --ticker AAPL --period 1y
    calibrate_conviction.py --db ~/.stock-analysis/state.db --period 6m --output ./reports/calibration.json

Reads conviction records from the SQLite persistence layer (persist.py schema),
fetches actual price returns via yfinance, then computes:
  - Per-bucket accuracy and mean return
  - Overconfidence ratio (strong calls underperforming)
  - Brier score for probability calibration
  - Reliability diagram data in quintiles
  - Bayesian adjustment recommendations
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: numpy required. Run: pip install numpy\n")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    sys.stderr.write("Error: yfinance required. Run: pip install yfinance\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Rating classification
# ---------------------------------------------------------------------------

# Maps a conviction score to a canonical rating label and correctness thresholds.
# Each bucket: (min_inclusive, max_exclusive, label, correct_if_return_above, correct_if_return_below)
# None means "no upper bound check" or "no lower bound check".
RATING_BUCKETS: list[tuple[float, float, str, float | None, float | None]] = [
    (9.0, 11.0, "Strong Buy", 0.20, None),
    (7.5, 9.0, "Buy", 0.10, None),
    (6.0, 7.5, "Hold/Accumulate", -0.05, 0.15),
    (4.0, 6.0, "Hold/Reduce", -0.15, 0.05),
    (2.0, 4.0, "Sell", None, -0.10),
    (0.0, 2.0, "Strong Sell", None, -0.20),
]

# Implied probability of outperformance per rating (used for Brier score).
BUCKET_PROBABILITIES: dict[str, float] = {
    "Strong Buy": 0.90,
    "Buy": 0.75,
    "Hold/Accumulate": 0.50,
    "Hold/Reduce": 0.35,
    "Sell": 0.20,
    "Strong Sell": 0.10,
}


def conviction_to_rating(score: float) -> str:
    """Map a numeric conviction score to a rating label."""
    for lo, hi, label, _, __ in RATING_BUCKETS:
        if lo <= score < hi:
            return label
    return "Strong Sell" if score < 2.0 else "Strong Buy"


def is_correct(rating: str, actual_return: float) -> bool:
    """Return True when a prediction matched its correctness threshold."""
    for _, __, label, ret_above, ret_below in RATING_BUCKETS:
        if label != rating:
            continue
        if ret_above is not None and ret_below is not None:
            # Range bucket: correct when return falls within the window
            return ret_above <= actual_return <= ret_below
        if ret_above is not None:
            return actual_return > ret_above
        if ret_below is not None:
            return actual_return < ret_below
    return False


# ---------------------------------------------------------------------------
# Period parsing
# ---------------------------------------------------------------------------

_PERIOD_DAYS: dict[str, int] = {
    "6m": 182,
    "1y": 365,
    "2y": 730,
}


def period_to_days(period: str) -> int:
    """Convert period string (6m|1y|2y) to approximate calendar days."""
    return _PERIOD_DAYS.get(period.lower(), 365)


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------


def open_db(db_path: str) -> sqlite3.Connection | None:
    """Open an existing SQLite database.  Returns None if the file is absent."""
    expanded = os.path.expanduser(db_path)
    if not os.path.exists(expanded):
        return None
    conn = sqlite3.connect(expanded)
    conn.row_factory = sqlite3.Row
    return conn


def load_conviction_records(
    conn: sqlite3.Connection,
    ticker: str | None,
    cutoff: date,
) -> list[dict]:
    """Read conviction records joined with ticker from the analyses table.

    Supports the persist.py schema:
        conviction_history(id, analysis_id, conviction, rating, component_scores, recorded_at)
        analyses(id, ticker, ...)

    Returns a list of dicts with keys: ticker, conviction, rating, recorded_at.
    """
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    if "conviction_history" not in tables or "analyses" not in tables:
        return []

    # Inspect columns to guard against schema drift
    ch_cols = {row[1] for row in conn.execute("PRAGMA table_info(conviction_history)")}
    required = {"analysis_id", "conviction", "rating", "recorded_at"}
    if not required.issubset(ch_cols):
        return []

    query = """
        SELECT ch.conviction, ch.rating, ch.recorded_at, a.ticker
        FROM conviction_history ch
        JOIN analyses a ON a.id = ch.analysis_id
        WHERE ch.recorded_at >= ?
    """
    params: list[Any] = [cutoff.isoformat()]

    if ticker:
        query += " AND UPPER(a.ticker) = ?"
        params.append(ticker.upper())

    query += " ORDER BY ch.recorded_at ASC"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Price return fetching
# ---------------------------------------------------------------------------


def fetch_return(ticker: str, from_date: date, horizon_days: int) -> float | None:
    """Fetch the total return for *ticker* over *horizon_days* starting at *from_date*.

    Returns None when price data is unavailable or the horizon has not elapsed yet.
    """
    today = date.today()
    end_date = from_date + timedelta(days=horizon_days)

    if end_date > today:
        # Horizon has not passed — outcome cannot be determined yet
        return None

    try:
        ticker_obj = yf.Ticker(ticker)
        hist = ticker_obj.history(
            start=from_date.isoformat(),
            end=(
                end_date + timedelta(days=5)
            ).isoformat(),  # small buffer for weekends/holidays
            auto_adjust=True,
        )
        if hist.empty or len(hist) < 2:
            return None

        prices = hist["Close"]
        start_price = float(prices.iloc[0])
        # End price = closest trading day at or before end_date.
        # horizon_days is calendar days, but `prices` is indexed by trading dates;
        # find the last bar with date ≤ end_date instead of indexing positionally.
        mask = hist.index.date <= end_date
        if not mask.any():
            return None
        end_price = float(prices[mask].iloc[-1])

        if start_price <= 0:
            return None

        return (end_price - start_price) / start_price
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_brier_score(
    records: list[dict],
    horizon_days: int,
) -> float | None:
    """Compute mean Brier score across all resolved predictions.

    Brier score = mean((p - o)^2), where p = implied probability and o = 1/0 outcome.
    Lower is better; 0.25 is the naive baseline for a binary problem.
    """
    squared_errors: list[float] = []
    for rec in records:
        actual_return = rec.get("actual_return")
        if actual_return is None:
            continue
        rating = rec["rating"]
        p = BUCKET_PROBABILITIES.get(rating, 0.5)
        outcome = 1.0 if actual_return > 0 else 0.0
        squared_errors.append((p - outcome) ** 2)

    if not squared_errors:
        return None
    return float(np.mean(squared_errors))


def compute_reliability_diagram(
    records: list[dict],
    n_quintiles: int = 5,
) -> list[dict]:
    """Bin predictions into quintiles by implied probability and report observed frequency.

    Each element: {"bin_center": float, "predicted_probability": float, "observed_frequency": float, "count": int}
    """
    resolved = [r for r in records if r.get("actual_return") is not None]
    if len(resolved) < n_quintiles:
        return []

    probs = np.array([BUCKET_PROBABILITIES.get(r["rating"], 0.5) for r in resolved])
    outcomes = np.array([1.0 if r["actual_return"] > 0 else 0.0 for r in resolved])

    bins = np.percentile(probs, np.linspace(0, 100, n_quintiles + 1))
    bins[0] -= 1e-9  # ensure first bin is inclusive
    bins[-1] += 1e-9

    diagram = []
    for i in range(n_quintiles):
        mask = (probs > bins[i]) & (probs <= bins[i + 1])
        count = int(mask.sum())
        if count == 0:
            continue
        diagram.append(
            {
                "bin_center": round(float(np.mean(probs[mask])), 3),
                "predicted_probability": round(float(np.mean(probs[mask])), 3),
                "observed_frequency": round(float(np.mean(outcomes[mask])), 3),
                "count": count,
            }
        )

    return diagram


def compute_calibration(
    raw_records: list[dict],
    horizon_days: int,
) -> dict:
    """Core calibration computation.

    Enriches each record with actual_return and correctness, then aggregates
    accuracy, mean return, overconfidence, Brier score, and reliability diagram.
    """
    warnings: list[str] = []

    # Enrich records with actual returns
    enriched: list[dict] = []
    skipped_future = 0
    skipped_no_data = 0

    for rec in raw_records:
        try:
            recorded_dt = datetime.fromisoformat(
                rec["recorded_at"].replace("Z", "+00:00")
            )
            pred_date = recorded_dt.date()
        except (ValueError, KeyError):
            skipped_no_data += 1
            continue

        actual_return = fetch_return(rec["ticker"], pred_date, horizon_days)

        # Normalise rating to canonical bucket label
        stored_rating = (rec.get("rating") or "").strip()
        try:
            conviction_score = float(rec["conviction"])
        except (TypeError, ValueError):
            skipped_no_data += 1
            continue
        canonical_rating = conviction_to_rating(conviction_score)

        enriched.append(
            {
                **rec,
                "pred_date": pred_date.isoformat(),
                "canonical_rating": canonical_rating,
                "actual_return": actual_return,
            }
        )

        if actual_return is None:
            skipped_future += 1

    if skipped_future:
        warnings.append(
            f"{skipped_future} predictions skipped: horizon has not elapsed yet or price data unavailable"
        )

    resolved = [r for r in enriched if r["actual_return"] is not None]
    total_predictions = len(enriched)
    total_resolved = len(resolved)

    if total_resolved == 0:
        return {
            "total_predictions": total_predictions,
            "total_resolved": 0,
            "overall_accuracy": None,
            "accuracy_by_rating": {},
            "overconfidence_ratio": None,
            "brier_score": None,
            "reliability_diagram": [],
            "bayesian_adjustment": _no_adjustment("Insufficient resolved predictions"),
            "warnings": warnings
            + ["No resolved predictions found — all horizons may be in the future"],
        }

    # Per-bucket aggregation
    bucket_data: dict[str, list[dict]] = defaultdict(list)
    for rec in resolved:
        bucket_data[rec["canonical_rating"]].append(rec)

    accuracy_by_rating: dict[str, dict] = {}
    for label, recs in bucket_data.items():
        returns = [r["actual_return"] for r in recs]
        correct = [r for r in recs if is_correct(label, r["actual_return"])]
        accuracy_by_rating[label] = {
            "count": len(recs),
            "correct": len(correct),
            "accuracy": round(len(correct) / len(recs), 4) if recs else None,
            "mean_return": round(float(np.mean(returns)), 4),
        }

    # Overall accuracy
    total_correct = sum(
        v["correct"] for v in accuracy_by_rating.values() if v["correct"] is not None
    )
    overall_accuracy = (
        round(total_correct / total_resolved, 4) if total_resolved else None
    )

    # Overconfidence ratio: fraction of Strong Buy + Buy that underperformed their threshold
    bullish_recs = [
        r for r in resolved if r["canonical_rating"] in ("Strong Buy", "Buy")
    ]
    if bullish_recs:
        underperformed = [
            r
            for r in bullish_recs
            if not is_correct(r["canonical_rating"], r["actual_return"])
        ]
        overconfidence_ratio = round(len(underperformed) / len(bullish_recs), 4)
    else:
        overconfidence_ratio = None

    brier = compute_brier_score(resolved, horizon_days)
    reliability = compute_reliability_diagram(resolved)

    # Bayesian adjustment
    bayesian = _compute_bayesian_adjustment(accuracy_by_rating, warnings)

    if skipped_no_data:
        warnings.append(
            f"{skipped_no_data} records skipped due to missing conviction/date fields"
        )

    return {
        "total_predictions": total_predictions,
        "total_resolved": total_resolved,
        "overall_accuracy": overall_accuracy,
        "accuracy_by_rating": accuracy_by_rating,
        "overconfidence_ratio": overconfidence_ratio,
        "brier_score": round(brier, 4) if brier is not None else None,
        "reliability_diagram": reliability,
        "bayesian_adjustment": bayesian,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Bayesian adjustment logic
# ---------------------------------------------------------------------------

_STRONG_BUY_ACCURACY_THRESHOLD = 0.60
_BUY_ACCURACY_THRESHOLD = 0.60
_SELL_ACCURACY_THRESHOLD = 0.50


def _no_adjustment(reason: str) -> dict:
    return {
        "recommended": False,
        "direction": "none",
        "magnitude": 0.0,
        "reasoning": reason,
    }


def _compute_bayesian_adjustment(
    accuracy_by_rating: dict[str, dict],
    warnings: list[str],
) -> dict:
    """Derive a Bayesian adjustment recommendation from accuracy data."""
    sb_acc = accuracy_by_rating.get("Strong Buy", {}).get("accuracy")
    buy_acc = accuracy_by_rating.get("Buy", {}).get("accuracy")
    sell_acc = accuracy_by_rating.get("Sell", {}).get("accuracy")
    ss_acc = accuracy_by_rating.get("Strong Sell", {}).get("accuracy")

    sb_mean = accuracy_by_rating.get("Strong Buy", {}).get("mean_return")
    buy_mean = accuracy_by_rating.get("Buy", {}).get("mean_return")

    reasons: list[str] = []
    reduce_bullish = False
    reduce_bearish = False

    if sb_acc is not None and sb_acc < _STRONG_BUY_ACCURACY_THRESHOLD:
        reduce_bullish = True
        reasons.append(
            f"Strong Buy accuracy {sb_acc:.0%} < {_STRONG_BUY_ACCURACY_THRESHOLD:.0%} threshold"
        )
    if buy_acc is not None and buy_acc < _BUY_ACCURACY_THRESHOLD:
        reduce_bullish = True
        reasons.append(
            f"Buy accuracy {buy_acc:.0%} < {_BUY_ACCURACY_THRESHOLD:.0%} threshold"
        )
    if sb_mean is not None and sb_mean < 0.20:
        reduce_bullish = True
        reasons.append(f"Strong Buy mean return {sb_mean:.1%} below 20% expectation")
    if buy_mean is not None and buy_mean < 0.10:
        reduce_bullish = True
        reasons.append(f"Buy mean return {buy_mean:.1%} below 10% expectation")

    if sell_acc is not None and sell_acc < _SELL_ACCURACY_THRESHOLD:
        reduce_bearish = True
        reasons.append(
            f"Sell accuracy {sell_acc:.0%} < {_SELL_ACCURACY_THRESHOLD:.0%} threshold"
        )
    if ss_acc is not None and ss_acc < _SELL_ACCURACY_THRESHOLD:
        reduce_bearish = True
        reasons.append(
            f"Strong Sell accuracy {ss_acc:.0%} < {_SELL_ACCURACY_THRESHOLD:.0%} threshold"
        )

    if not reasons:
        return _no_adjustment(
            "Historical accuracy meets all thresholds — no adjustment needed"
        )

    if reduce_bullish and reduce_bearish:
        direction = "reduce_both_extremes"
        magnitude = -0.5
        reasoning = (
            "; ".join(reasons)
            + ". Reduce conviction magnitude at both ends by 0.5 points."
        )
    elif reduce_bullish:
        direction = "reduce_bullish_bias"
        magnitude = -0.5
        reasoning = (
            "; ".join(reasons) + ". Reduce bullish conviction scores by 0.5 points."
        )
    else:
        direction = "reduce_bearish_bias"
        magnitude = 0.5  # positive = reduce how negative you are
        reasoning = (
            "; ".join(reasons) + ". Consider moderating bearish calls by 0.5 points."
        )

    return {
        "recommended": True,
        "direction": direction,
        "magnitude": magnitude,
        "reasoning": reasoning,
    }


# ---------------------------------------------------------------------------
# Empty calibration scaffold
# ---------------------------------------------------------------------------


def empty_calibration(reason: str, period: str) -> dict:
    return {
        "calibration_period": period,
        "total_predictions": 0,
        "overall_accuracy": None,
        "accuracy_by_rating": {},
        "overconfidence_ratio": None,
        "brier_score": None,
        "reliability_diagram": [],
        "bayesian_adjustment": _no_adjustment("No data available"),
        "warnings": [reason],
    }


# ---------------------------------------------------------------------------
# Hazard-rate adjusted target (Pitfall 6)
# ---------------------------------------------------------------------------


def estimate_termination_hazard(
    beneish_m: float | None = None,
    altman_z: float | None = None,
    short_interest_pct: float | None = None,
    debt_maturity_wall_12m_pct: float | None = None,
    tape_class: str | None = None,
    going_concern_flag: bool = False,
    activist_proxy_fight: bool = False,
) -> dict:
    """Estimate per-year termination hazard `q` ∈ [0, 0.5].

    Decompose hazard from existing pipeline signals (already computed in stages
    5/6/11). Higher q ⇒ lower optimal exit threshold (book sooner — pitfall 6).

    Returns:
        q_annual: float — per-year probability of thesis-ending event
        contributors: list[dict] — which signals drove q
        category: str — low|medium|high|extreme
    """
    contributors: list[dict] = []
    q = 0.01  # baseline: 1%/yr (broad-market base rate of single-name catastrophic events)

    if going_concern_flag:
        q += 0.30
        contributors.append({"signal": "going_concern_flag", "weight": +0.30})

    if beneish_m is not None and beneish_m > -1.78:
        # Beneish flagged earnings manipulation likely
        q += 0.08
        contributors.append(
            {"signal": "beneish_m_score", "value": beneish_m, "weight": +0.08}
        )

    if altman_z is not None:
        if altman_z < 1.81:
            q += 0.12
            contributors.append(
                {"signal": "altman_z_distress", "value": altman_z, "weight": +0.12}
            )
        elif altman_z < 2.99:
            q += 0.04
            contributors.append(
                {"signal": "altman_z_grey", "value": altman_z, "weight": +0.04}
            )

    if short_interest_pct is not None and short_interest_pct >= 25:
        # High short interest with no clear thesis-support is a *both-tail* signal —
        # squeeze upside but also concentrated bearish thesis pool. Counts toward q.
        q += 0.05
        contributors.append(
            {
                "signal": "short_interest_high",
                "value": short_interest_pct,
                "weight": +0.05,
            }
        )

    if debt_maturity_wall_12m_pct is not None and debt_maturity_wall_12m_pct >= 25:
        q += 0.06
        contributors.append(
            {
                "signal": "debt_maturity_wall",
                "value": debt_maturity_wall_12m_pct,
                "weight": +0.06,
            }
        )

    if tape_class == "manipulator":
        q += 0.05
        contributors.append({"signal": "manipulator_tape", "weight": +0.05})

    if activist_proxy_fight:
        q += 0.03  # binary outcome event raises tail probability
        contributors.append({"signal": "activist_proxy_fight", "weight": +0.03})

    q = min(q, 0.50)  # cap
    q = max(q, 0.005)  # floor

    if q < 0.03:
        category = "low"
    elif q < 0.10:
        category = "medium"
    elif q < 0.30:
        category = "high"
    else:
        category = "extreme"

    return {
        "q_annual": round(q, 4),
        "category": category,
        "contributors": contributors,
        "methodology": (
            "Pitfall 6 (hazard-rate discounting): decompose discount rate into time + "
            "termination hazard q. Inputs are existing forensic / structural signals "
            "from stages 5/6/11. See references/pitfalls/06-hazard-rate-discounting.md"
        ),
    }


def compute_hazard_adjusted_target(
    nominal_target: float,
    horizon_months: int,
    q_annual: float,
    forced_exit_q_annual: float = 0.0,
) -> dict:
    """Adjust a nominal price target by cumulative survival probability over the horizon.

    Cumulative survival = (1 − q_total)^horizon_years where
    q_total = q_annual + forced_exit_q_annual (margin / liquidity-need risk).

    Also derives the hazard-implied exit policy (act-now / trim / hold).
    """
    if horizon_months <= 0:
        return {"error": "horizon_months must be positive"}
    if not 0.0 <= q_annual <= 1.0:
        return {"error": "q_annual must be in [0, 1]"}

    q_total = min(q_annual + max(0.0, forced_exit_q_annual), 0.99)
    horizon_years = horizon_months / 12.0
    cumulative_survival = (1 - q_total) ** horizon_years
    adjusted_target = nominal_target * cumulative_survival

    if q_total < 0.03:
        exit_policy = "hold"
        rationale = "Low hazard — published target stands; bias is bailing too early"
    elif q_total < 0.10:
        exit_policy = "trim"
        rationale = "Medium hazard — book partial gains earlier than nominal target"
    elif q_total < 0.30:
        exit_policy = "sell_into_strength"
        rationale = (
            "High hazard — continuation value being eaten by termination probability"
        )
    else:
        exit_policy = "exit_now"
        rationale = "Extreme hazard — last 30% of expected move is nearly worthless after hazard discount"

    return {
        "nominal_target": round(nominal_target, 2),
        "horizon_months": horizon_months,
        "q_annual": round(q_annual, 4),
        "forced_exit_q_annual": round(forced_exit_q_annual, 4),
        "q_total": round(q_total, 4),
        "cumulative_survival": round(cumulative_survival, 4),
        "hazard_adjusted_target": round(adjusted_target, 2),
        "target_reduction_pct": round((1 - cumulative_survival) * 100, 1),
        "exit_policy": exit_policy,
        "rationale": rationale,
        "methodology": (
            "Pitfall 6: target × (1−q_total)^horizon_years. Forced-exit hazard "
            "(margin / cash-need) compounds with name termination hazard."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    default_db = os.path.expanduser("~/.stock-analysis/state.db")

    parser = argparse.ArgumentParser(
        description="Bayesian conviction calibration against historical price outcomes"
    )
    parser.add_argument(
        "--db",
        default=default_db,
        help=f"Path to SQLite database (default: {default_db})",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "--ticker",
        help="Filter to a single ticker symbol (e.g. AAPL)",
    )
    parser.add_argument(
        "--period",
        default="1y",
        choices=["6m", "1y", "2y"],
        help="Evaluation horizon per prediction: 6m, 1y, or 2y (default: 1y)",
    )
    # Hazard-rate target adjustment mode (pitfall 6) — orthogonal to backtest
    parser.add_argument(
        "--hazard",
        action="store_true",
        help=(
            "Hazard-adjusted-target mode: bypass DB backtest and instead compute "
            "cumulative-survival-adjusted price target. Requires --nominal-target "
            "and --horizon-months; consumes hazard inputs from flags below."
        ),
    )
    parser.add_argument("--nominal-target", type=float, help="Nominal price target")
    parser.add_argument(
        "--horizon-months", type=int, default=12, help="Target horizon in months"
    )
    parser.add_argument(
        "--beneish-m", type=float, help="Beneish M-Score (>−1.78 ⇒ flag)"
    )
    parser.add_argument(
        "--altman-z", type=float, help="Altman Z-Score (<1.81 ⇒ distress)"
    )
    parser.add_argument(
        "--short-interest-pct", type=float, help="Short interest % of float"
    )
    parser.add_argument(
        "--debt-maturity-wall-12m-pct",
        type=float,
        help="% of debt maturing in next 12 months",
    )
    parser.add_argument(
        "--tape-class",
        choices=["institutional", "retail", "manipulator", "lowliquidity"],
        help="Tape class (manipulator raises q; pitfall 8)",
    )
    parser.add_argument(
        "--going-concern-flag",
        action="store_true",
        help="Auditor going-concern flag (extreme hazard)",
    )
    parser.add_argument(
        "--activist-proxy-fight",
        action="store_true",
        help="Active proxy fight in progress (raises q)",
    )
    parser.add_argument(
        "--forced-exit-q-annual",
        type=float,
        default=0.0,
        help="Annual probability of forced exit (margin / cash-need)",
    )
    args = parser.parse_args()

    # Hazard-mode dispatch (pitfall 6)
    if args.hazard:
        if args.nominal_target is None:
            sys.stderr.write("--hazard requires --nominal-target\n")
            sys.exit(1)
        hazard = estimate_termination_hazard(
            beneish_m=args.beneish_m,
            altman_z=args.altman_z,
            short_interest_pct=args.short_interest_pct,
            debt_maturity_wall_12m_pct=args.debt_maturity_wall_12m_pct,
            tape_class=args.tape_class,
            going_concern_flag=args.going_concern_flag,
            activist_proxy_fight=args.activist_proxy_fight,
        )
        adjusted = compute_hazard_adjusted_target(
            nominal_target=args.nominal_target,
            horizon_months=args.horizon_months,
            q_annual=hazard["q_annual"],
            forced_exit_q_annual=args.forced_exit_q_annual,
        )
        result = {
            "mode": "hazard_adjusted_target",
            "ticker": args.ticker,
            "hazard_estimate": hazard,
            "target_adjustment": adjusted,
        }
        _write_output(result, args.output)
        sys.exit(0)

    horizon_days = period_to_days(args.period)
    # Cutoff: only load records old enough that the horizon could have elapsed
    cutoff = date.today() - timedelta(days=horizon_days)

    conn = open_db(args.db)
    if conn is None:
        result = empty_calibration(f"Database not found: {args.db}", args.period)
        _write_output(result, args.output)
        sys.exit(0)

    try:
        raw_records = load_conviction_records(conn, args.ticker, cutoff)
    except sqlite3.Error as exc:
        result = empty_calibration(f"Database error: {exc}", args.period)
        _write_output(result, args.output)
        sys.exit(0)
    finally:
        conn.close()

    if not raw_records:
        note = f"No conviction records found for period cutoff {cutoff.isoformat()}" + (
            f" and ticker {args.ticker.upper()}" if args.ticker else ""
        )
        result = empty_calibration(note, args.period)
        _write_output(result, args.output)
        sys.exit(0)

    sys.stderr.write(
        f"Loaded {len(raw_records)} conviction records; fetching price returns "
        f"(horizon: {args.period} = {horizon_days} days)...\n"
    )

    calibration = compute_calibration(raw_records, horizon_days)
    calibration["calibration_period"] = args.period

    # Reorder keys to match documented output schema
    ordered: dict = {
        "calibration_period": calibration["calibration_period"],
        "total_predictions": calibration["total_predictions"],
        "overall_accuracy": calibration["overall_accuracy"],
        "accuracy_by_rating": calibration["accuracy_by_rating"],
        "overconfidence_ratio": calibration["overconfidence_ratio"],
        "brier_score": calibration["brier_score"],
        "reliability_diagram": calibration["reliability_diagram"],
        "bayesian_adjustment": calibration["bayesian_adjustment"],
        "warnings": calibration["warnings"],
    }

    # Summary to stderr
    if calibration.get("overall_accuracy") is not None:
        sys.stderr.write(
            f"Calibration complete: {calibration['total_resolved']} resolved predictions, "
            f"overall accuracy {calibration['overall_accuracy']:.1%}, "
            f"Brier score {calibration.get('brier_score', 'N/A')}\n"
        )
        adj = calibration["bayesian_adjustment"]
        if adj["recommended"]:
            sys.stderr.write(
                f"Bayesian recommendation: {adj['direction']} (magnitude {adj['magnitude']:+.1f})\n"
            )

    _write_output(ordered, args.output)


def _write_output(data: dict, output_path: str | None) -> None:
    payload = json.dumps(data, indent=2)
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as fh:
            fh.write(payload)
        sys.stderr.write(f"Output written to {output_path}\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()
