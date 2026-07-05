#!/usr/bin/env python3
"""CEO Quality Score (P0.3) — deterministic 1-10 leadership rubric.

Sources for design:
  - FinTwit practitioners (@10kdiver, @InvestmentTalk, @bluegrasscap) ranking
    CEO quality + capital allocation as #2 highest-alpha factor
  - Mauboussin "Capital Allocators" — comp alignment, retention test
  - Buffett: "skin in the game" (Taleb) — direct ownership %
  - docs/research/fintwit-reddit-practitioner-insights-2026-05.md (P0.3)

Inputs:
  --raw-data            raw-data.json (insider_transactions, profile)
  --capital-allocation  capital_allocation.json (composite grade from P0.1)
  --proxy-data          (optional) proxy_data.json with manual inputs:
                          {ceo_name, ceo_tenure_years, ceo_ownership_pct,
                           ceo_pay_total, ceo_pay_equity_pct,
                           cfo_changes_12mo, coo_changes_12mo,
                           prior_track_record: "strong"|"mixed"|"weak"|null,
                           officers_current: [{name, title}],
                           officers_prior:   [{name, title}]}
  --ticker              Ticker (informational)
  --output              Output JSON path

Output (json):
  {
    "scores": {
      "tenure_score":           int (0-10) | null,
      "comp_alignment_score":   int | null,
      "skin_in_the_game_score": int | null,
      "insider_activity_score": int | null,
      "leadership_stability":   int | null,
      "capital_allocation":     int | null,
      "prior_track_record":     int | null
    },
    "composite_score":  float (0-10),
    "letter_grade":     "A"|"B"|"C"|"D"|"F",
    "weights_used":     {dim: weight, ...},
    "red_flags":        [str, ...],
    "green_flags":      [str, ...]
  }

Deterministic only. Where qualitative input is missing, the dimension
is omitted and weights are renormalized — never fabricated.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta


WEIGHTS = {
    "tenure_score":           0.10,
    "comp_alignment_score":   0.15,
    "skin_in_the_game_score": 0.20,
    "insider_activity_score": 0.15,
    "leadership_stability":   0.15,
    "capital_allocation":     0.20,
    "prior_track_record":     0.05,
}


# ---------------------------------------------------------------------------
# Individual dimension graders
# ---------------------------------------------------------------------------


def grade_tenure(tenure_years: float | None) -> tuple[int | None, list[str]]:
    """Tenure: 5-15yr ideal (long enough for accountability, not entrenched)."""
    if tenure_years is None:
        return None, []
    flags = []
    if tenure_years < 1:
        return 3, ["CEO tenure <1yr — unproven; accountability gap"]
    if tenure_years < 3:
        return 5, ["CEO tenure <3yr — limited capital allocation history"]
    if tenure_years <= 15:
        return 9, []
    if tenure_years <= 25:
        flags.append(f"CEO tenure {tenure_years}yr — possible entrenchment risk")
        return 7, flags
    flags.append(f"CEO tenure {tenure_years}yr — high entrenchment / succession risk")
    return 5, flags


def grade_comp_alignment(equity_pct: float | None) -> tuple[int | None, list[str]]:
    """Comp alignment: % of total comp from equity (vs base+bonus)."""
    if equity_pct is None:
        return None, []
    flags = []
    if equity_pct >= 80:
        return 10, []
    if equity_pct >= 60:
        return 8, []
    if equity_pct >= 40:
        return 6, []
    if equity_pct >= 20:
        flags.append(f"CEO equity comp only {equity_pct}% — weak performance alignment")
        return 4, flags
    flags.append(f"CEO equity comp only {equity_pct}% — base-heavy, misaligned with shareholders")
    return 2, flags


def grade_skin_in_the_game(ownership_pct: float | None) -> tuple[int | None, list[str]]:
    """Direct ownership %: Taleb's skin-in-the-game / Buffett alignment."""
    if ownership_pct is None:
        return None, []
    flags = []
    if ownership_pct >= 5:
        return 10, []
    if ownership_pct >= 1:
        return 8, []
    if ownership_pct >= 0.25:
        return 6, []
    if ownership_pct >= 0.05:
        flags.append(f"CEO ownership {ownership_pct}% — minimal skin in the game")
        return 4, flags
    flags.append(f"CEO ownership {ownership_pct}% — effectively zero alignment")
    return 2, flags


def grade_insider_activity(insider_txns: list[dict]) -> tuple[int | None, list[str]]:
    """Score open-market buys vs sells in past 12mo across all insiders.

    Open-market PURCHASES are the strongest signal (Lynch, Greenblatt).
    10b5-1 PLAN sales are noise — we down-weight them.
    """
    if not insider_txns:
        return None, []

    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    flags = []

    buy_value = 0.0
    sell_value = 0.0
    plan_sell_count = 0
    open_buy_count = 0

    for tx in insider_txns:
        date_str = (tx.get("date") or "").strip()
        if not date_str:
            continue
        try:
            tx_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if tx_date.tzinfo is None:
                tx_date = tx_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if tx_date < cutoff:
            continue

        ttype = (tx.get("transaction_type") or "").lower()
        value = tx.get("value") or 0
        if not isinstance(value, (int, float)):
            continue
        value = abs(value)

        is_plan = "10b5" in ttype or "plan" in ttype
        if "purchase" in ttype or "buy" in ttype:
            buy_value += value
            open_buy_count += 1
        elif "sale" in ttype or "sell" in ttype:
            sell_value += value
            if is_plan:
                plan_sell_count += 1

    # Discount plan-based sales — they're scheduled, not informational
    effective_sell = sell_value * (0.4 if plan_sell_count > 0 else 1.0)

    if buy_value == 0 and effective_sell == 0:
        return None, []

    if buy_value > 0 and effective_sell == 0:
        flags.append(f"Open-market insider buying ({open_buy_count} txns) — bullish")
        return 9, flags

    if buy_value > effective_sell:
        flags.append(f"Net insider buying — {open_buy_count} purchases")
        return 8, flags

    if buy_value > 0 and buy_value >= 0.5 * effective_sell:
        return 6, []

    if effective_sell > 5 * max(buy_value, 1):
        flags.append("Heavy insider selling exceeds buying 5:1 — bearish")
        return 3, flags

    return 5, []


def grade_leadership_stability(
    cfo_changes: int | None,
    coo_changes: int | None,
    officers_current: list[dict] | None,
    officers_prior: list[dict] | None,
) -> tuple[int | None, list[str]]:
    """C-suite turnover in last 12mo. CFO/COO changes are accounting/operational red flags."""
    flags = []

    # Auto-detect from officer rosters if explicit counts not provided
    if cfo_changes is None and officers_current and officers_prior:
        prior_cfo = next(
            (o["name"] for o in officers_prior if "cfo" in (o.get("title") or "").lower()),
            None,
        )
        curr_cfo = next(
            (o["name"] for o in officers_current if "cfo" in (o.get("title") or "").lower()),
            None,
        )
        if prior_cfo and curr_cfo and prior_cfo != curr_cfo:
            cfo_changes = 1
        elif prior_cfo and curr_cfo and prior_cfo == curr_cfo:
            cfo_changes = 0

    if cfo_changes is None and coo_changes is None:
        return None, []

    cfo_changes = cfo_changes or 0
    coo_changes = coo_changes or 0

    if cfo_changes >= 1:
        flags.append(f"CFO change in last 12mo — accounting / governance flag")
    if coo_changes >= 1:
        flags.append(f"COO change in last 12mo — operational continuity flag")

    if cfo_changes == 0 and coo_changes == 0:
        return 9, []
    if cfo_changes + coo_changes == 1:
        return 6, flags
    if cfo_changes + coo_changes == 2:
        return 4, flags
    return 2, flags


def grade_capital_allocation(capital_allocation: dict | None) -> tuple[int | None, list[str]]:
    """Pull composite from P0.1 audit_capital_allocation.py output."""
    if not capital_allocation:
        return None, []
    composite = capital_allocation.get("composite", {})
    score = composite.get("composite_score")
    grade = composite.get("letter_grade")
    if score is None:
        return None, []
    # Composite is 0-100; rescale to 0-10
    rescaled = int(round(score / 10))
    flags = []
    if grade in ("D", "F"):
        flags.append(f"Capital allocation grade {grade} — destructive history")
    return max(0, min(10, rescaled)), flags


def grade_prior_track_record(track_record: str | None) -> tuple[int | None, list[str]]:
    if not track_record:
        return None, []
    mapping = {"strong": 9, "mixed": 6, "weak": 3}
    score = mapping.get(track_record.lower())
    if score is None:
        return None, []
    flags = []
    if track_record.lower() == "weak":
        flags.append("CEO prior track record: weak")
    return score, flags


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def composite(scores: dict[str, int | None]) -> dict:
    weight_used = 0.0
    weighted_sum = 0.0
    weights_applied = {}
    for dim, score in scores.items():
        if score is None:
            continue
        w = WEIGHTS[dim]
        weight_used += w
        weighted_sum += score * w
        weights_applied[dim] = w

    if weight_used == 0:
        return {
            "composite_score": None,
            "letter_grade": "N/A",
            "weights_used": {},
            "dimensions_scored": 0,
        }

    composite_0_10 = round(weighted_sum / weight_used, 2)

    if composite_0_10 >= 8.5:
        grade = "A"
    elif composite_0_10 >= 7:
        grade = "B"
    elif composite_0_10 >= 5.5:
        grade = "C"
    elif composite_0_10 >= 4:
        grade = "D"
    else:
        grade = "F"

    return {
        "composite_score": composite_0_10,
        "letter_grade": grade,
        "weights_used": weights_applied,
        "dimensions_scored": len(weights_applied),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def analyze(raw_data: dict, capital_alloc: dict | None, proxy: dict | None) -> dict:
    proxy = proxy or {}

    tenure_score, tenure_flags = grade_tenure(proxy.get("ceo_tenure_years"))
    comp_score, comp_flags = grade_comp_alignment(proxy.get("ceo_pay_equity_pct"))
    skin_score, skin_flags = grade_skin_in_the_game(proxy.get("ceo_ownership_pct"))
    insider_score, insider_flags = grade_insider_activity(
        raw_data.get("insider_transactions", []) or []
    )
    stability_score, stability_flags = grade_leadership_stability(
        proxy.get("cfo_changes_12mo"),
        proxy.get("coo_changes_12mo"),
        proxy.get("officers_current"),
        proxy.get("officers_prior"),
    )
    capalloc_score, capalloc_flags = grade_capital_allocation(capital_alloc)
    track_score, track_flags = grade_prior_track_record(proxy.get("prior_track_record"))

    scores = {
        "tenure_score": tenure_score,
        "comp_alignment_score": comp_score,
        "skin_in_the_game_score": skin_score,
        "insider_activity_score": insider_score,
        "leadership_stability": stability_score,
        "capital_allocation": capalloc_score,
        "prior_track_record": track_score,
    }

    comp = composite(scores)

    all_flags = (
        tenure_flags + comp_flags + skin_flags + insider_flags
        + stability_flags + capalloc_flags + track_flags
    )
    red_flags = [f for f in all_flags if any(
        marker in f.lower() for marker in
        ["red flag", "risk", "weak", "bearish", "destructive", "misaligned",
         "minimal", "zero", "unproven", "entrenchment", "flag"]
    )]
    green_flags = [f for f in all_flags if f not in red_flags]

    return {
        "scores": scores,
        "composite": comp,
        "red_flags": red_flags,
        "green_flags": green_flags,
        "missing_dimensions": [k for k, v in scores.items() if v is None],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CEO Quality Score (P0.3)")
    parser.add_argument("--raw-data", required=True, help="raw-data.json path")
    parser.add_argument("--capital-allocation", help="capital_allocation.json path")
    parser.add_argument("--proxy-data", help="proxy_data.json path with qualitative inputs")
    parser.add_argument("--ticker", help="Ticker (informational)")
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    try:
        with open(args.raw_data) as fh:
            raw_data = json.load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"Error: raw-data not found: {args.raw_data}\n")
        sys.exit(1)

    capital_alloc = None
    if args.capital_allocation:
        try:
            with open(args.capital_allocation) as fh:
                capital_alloc = json.load(fh)
        except FileNotFoundError:
            sys.stderr.write(f"Warning: capital_allocation not found: {args.capital_allocation}\n")

    proxy = None
    if args.proxy_data:
        try:
            with open(args.proxy_data) as fh:
                proxy = json.load(fh)
        except FileNotFoundError:
            sys.stderr.write(f"Warning: proxy_data not found: {args.proxy_data}\n")

    result = analyze(raw_data, capital_alloc, proxy)
    result["ticker"] = args.ticker
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["framework"] = "CEO Quality Score (P0.3)"
    result["framework_sources"] = [
        "FinTwit practitioners (@10kdiver, @InvestmentTalk, @bluegrasscap)",
        "Mauboussin Capital Allocators",
        "Taleb skin-in-the-game",
        "Buffett owner-operator alignment",
    ]

    if args.output:
        with open(args.output, "w") as fh:
            json.dump(result, fh, indent=2)
        sys.stderr.write(f"Wrote {args.output}\n")
    else:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
