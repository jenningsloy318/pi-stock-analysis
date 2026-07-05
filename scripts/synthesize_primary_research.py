#!/usr/bin/env python3
"""Primary Research Synthesis (P0.2) — convergence scoring across expert/channel sources.

Sources for design:
  - Tegus / GLG expert network methodology
  - Fisher Scuttlebutt approach (customer/supplier/competitor/ex-employee triangulation)
  - FinTwit practitioners (@10kdiver, sell-side primary research desks)
  - docs/research/fintwit-reddit-practitioner-insights-2026-05.md (P0.2)

Inputs:
  --research  research_inputs.json with shape:
    {
      "ticker": "AAPL",
      "claims": [
        {
          "topic":      "iPhone unit demand 2026Q3",
          "thesis_dir": "bullish" | "bearish" | "neutral",
          "evidence": [
            {
              "source_type": "customer" | "supplier" | "competitor" |
                             "former_employee" | "industry_expert" |
                             "earnings_call" | "youtube_interview" |
                             "seeking_alpha" | "industry_report",
              "source_name": "Best Buy buyer (channel check)",
              "date":        "2026-05-15",
              "claim":       "Strong pull-through, sell-out tracking +12% YoY",
              "sentiment":   "bullish" | "bearish" | "neutral",
              "confidence":  0.0..1.0
            },
            ...
          ]
        },
        ...
      ]
    }

  --ticker    Ticker (informational)
  --output    Output JSON path

Output (json):
  {
    "claims": [
      {
        "topic":              str,
        "thesis_dir":         str,
        "convergence_score":  "high" | "moderate" | "low" | "conflicting",
        "agreement_count":    int (sources matching thesis_dir),
        "disagreement_count": int (sources disagreeing),
        "source_diversity":   int (count of distinct source_types in evidence),
        "weighted_sentiment": float (-1..+1),
        "summary_label":      str  # e.g. "High convergence (5/6 agree)"
      },
      ...
    ],
    "overall": {
      "high_convergence_claims":    int,
      "conflicting_claims":         int,
      "avg_source_diversity":       float,
      "directional_signal":         "bullish" | "bearish" | "mixed" | "neutral"
    },
    "red_flags":  [str, ...]   # e.g. "Bearish thesis convergence high — 4 ex-employees agree"
  }

Deterministic only. No LLM scoring. Convergence rules per docs/research/...

Convergence rules:
  - high       : 4+ independent agreeing sources, ≤1 disagreeing, ≥3 source_types
  - moderate   : 2-3 agreeing sources, ≤1 disagreeing, ≥2 source_types
  - low        : 1 agreeing source OR ≤2 sources total
  - conflicting: agreement_count > 0 AND disagreement_count > 0 with similar magnitudes
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


SENTIMENT_VALUES = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


def grade_claim(claim: dict) -> dict:
    thesis = (claim.get("thesis_dir") or "neutral").lower()
    evidence = claim.get("evidence", []) or []

    n_total = len(evidence)
    if n_total == 0:
        return {
            **claim,
            "convergence_score": "low",
            "agreement_count": 0,
            "disagreement_count": 0,
            "source_diversity": 0,
            "weighted_sentiment": 0.0,
            "summary_label": "No evidence supplied",
        }

    agreeing = 0
    disagreeing = 0
    weighted_sum = 0.0
    weight_total = 0.0
    source_types = set()

    for ev in evidence:
        sentiment = (ev.get("sentiment") or "neutral").lower()
        confidence = ev.get("confidence")
        if confidence is None:
            confidence = 0.5
        confidence = max(0.0, min(1.0, float(confidence)))
        sentiment_val = SENTIMENT_VALUES.get(sentiment, 0.0)

        weighted_sum += sentiment_val * confidence
        weight_total += confidence

        source_types.add(ev.get("source_type", "unknown"))

        # Match against thesis direction
        if thesis == "bullish" and sentiment == "bullish":
            agreeing += 1
        elif thesis == "bearish" and sentiment == "bearish":
            agreeing += 1
        elif thesis == "neutral" and sentiment == "neutral":
            agreeing += 1
        elif sentiment != "neutral" and thesis != "neutral" and sentiment != thesis:
            disagreeing += 1

    weighted_sentiment = round(
        weighted_sum / weight_total if weight_total > 0 else 0.0, 4
    )
    diversity = len(source_types)

    # Convergence classification
    if agreeing > 0 and disagreeing > 0 and abs(agreeing - disagreeing) <= 1:
        convergence = "conflicting"
    elif agreeing >= 4 and disagreeing <= 1 and diversity >= 3:
        convergence = "high"
    elif agreeing >= 2 and disagreeing <= 1 and diversity >= 2:
        convergence = "moderate"
    else:
        convergence = "low"

    summary = f"{convergence.title()} convergence ({agreeing}/{n_total} agree, {diversity} source types)"

    return {
        "topic": claim.get("topic"),
        "thesis_dir": thesis,
        "convergence_score": convergence,
        "agreement_count": agreeing,
        "disagreement_count": disagreeing,
        "total_sources": n_total,
        "source_diversity": diversity,
        "source_types": sorted(source_types),
        "weighted_sentiment": weighted_sentiment,
        "summary_label": summary,
    }


def overall(graded_claims: list[dict]) -> tuple[dict, list[str]]:
    if not graded_claims:
        return {
            "high_convergence_claims": 0,
            "conflicting_claims": 0,
            "avg_source_diversity": 0.0,
            "directional_signal": "neutral",
        }, []

    high = sum(1 for c in graded_claims if c["convergence_score"] == "high")
    conflicting = sum(1 for c in graded_claims if c["convergence_score"] == "conflicting")
    avg_div = round(
        sum(c["source_diversity"] for c in graded_claims) / len(graded_claims), 2
    )

    # Directional signal: weight by convergence × thesis_dir
    weight_map = {"high": 3, "moderate": 2, "low": 1, "conflicting": 0}
    score_map = {"bullish": 1, "neutral": 0, "bearish": -1}
    dir_score = sum(
        weight_map.get(c["convergence_score"], 0) * score_map.get(c["thesis_dir"], 0)
        for c in graded_claims
    )
    if dir_score >= 3:
        signal = "bullish"
    elif dir_score <= -3:
        signal = "bearish"
    elif conflicting > high:
        signal = "mixed"
    else:
        signal = "neutral"

    flags = []
    for c in graded_claims:
        if c["convergence_score"] == "high" and c["thesis_dir"] == "bearish":
            flags.append(
                f"Bearish thesis '{c['topic']}' has HIGH convergence "
                f"({c['agreement_count']} sources, {c['source_diversity']} types)"
            )
        if c["convergence_score"] == "conflicting":
            flags.append(
                f"Conflicting evidence on '{c['topic']}' — "
                f"{c['agreement_count']} agree vs {c['disagreement_count']} disagree"
            )

    return {
        "high_convergence_claims": high,
        "conflicting_claims": conflicting,
        "avg_source_diversity": avg_div,
        "directional_signal": signal,
    }, flags


def analyze(payload: dict) -> dict:
    graded = [grade_claim(c) for c in (payload.get("claims") or [])]
    summary, flags = overall(graded)
    return {"claims": graded, "overall": summary, "red_flags": flags}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Primary Research Synthesis with convergence scoring (P0.2)"
    )
    parser.add_argument("--research", required=True, help="research_inputs.json path")
    parser.add_argument("--ticker", help="Ticker (informational)")
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    try:
        with open(args.research) as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"Error: research file not found: {args.research}\n")
        sys.exit(1)

    result = analyze(payload)
    result["ticker"] = args.ticker or payload.get("ticker")
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["framework"] = "Primary Research Synthesis (P0.2)"
    result["framework_sources"] = [
        "Tegus / GLG expert network methodology",
        "Fisher Scuttlebutt triangulation",
        "FinTwit primary research desks",
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
