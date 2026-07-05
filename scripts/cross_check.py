#!/usr/bin/env python3
"""Cross-check pass: identify contradictions between scoring dimensions.

Usage:
    cross_check.py ./reports/AAPL/scores.json
    cross_check.py ./reports/AAPL/scores.json --behavioral ./reports/AAPL/behavioral.json --output ./reports/AAPL/cross_check.json

Runs AFTER compute_scores.py and flags internal contradictions:
  1. Overvaluation + wide moat → moat erosion question
  2. Red flags ≥3 → re-examine financials
  3. Alt data negative + financials strong → early warning
  4. Herding high + Strong Buy consensus → contrarian overlay
  5. Framework divergence requiring investigation

Output: JSON with list of flags, severity, and recommended actions.
"""

import argparse
import json
import sys


def run_cross_check(scores: dict, behavioral: dict | None = None) -> dict:
    """Identify contradictions in the scoring output."""
    flags: list[dict] = []
    adjustments: list[dict] = []

    def _get_score(key: str) -> float | None:
        obj = scores.get(key, {})
        if isinstance(obj, dict):
            return obj.get("score")
        return None

    valuation = _get_score("valuation_attractiveness")
    moat = _get_score("moat_quality")
    risk = _get_score("risk_profile")
    financial = _get_score("financial_health")
    alt = _get_score("alternative_alignment")
    technical = _get_score("technical_setup")
    macro = _get_score("macro_tailwind")
    industry_traj = _get_score("industry_trajectory")
    weinstein = _get_score("weinstein_alignment")

    # Rule 1: Overvaluation + wide moat
    if valuation is not None and moat is not None:
        if valuation <= 3.0 and moat >= 7.5:
            flags.append(
                {
                    "rule": 1,
                    "severity": "high",
                    "finding": f"Valuation={valuation} (overvalued) but Moat={moat} (wide)",
                    "action": "Re-examine moat — is market correctly pricing moat erosion or competitive threat?",
                    "dimensions": ["valuation_attractiveness", "moat_quality"],
                }
            )

    # Rule 2: Red flags → re-examine financials
    risk_obj = scores.get("risk_profile", {})
    red_flag_count = risk_obj.get("red_flag_count", 0)
    if red_flag_count >= 3:
        flags.append(
            {
                "rule": 2,
                "severity": "high",
                "finding": f"{red_flag_count} forensic red flags detected",
                "action": "Re-examine Financial Health and Moat Quality with higher skepticism. Consider downgrade.",
                "dimensions": ["risk_profile", "financial_health", "moat_quality"],
            }
        )

    # Rule 3: Alt data negative + financials strong
    if alt is not None and financial is not None:
        if alt <= 3.0 and financial >= 7.0:
            flags.append(
                {
                    "rule": 3,
                    "severity": "medium",
                    "finding": f"Alt Data={alt} (negative) but Financial Health={financial} (strong)",
                    "action": "Investigate: are alt signals an early warning of undetected deterioration?",
                    "dimensions": ["alternative_alignment", "financial_health"],
                }
            )

    # Rule 4: Herding + Strong Buy consensus
    if behavioral:
        herding_score = behavioral.get("analyst_herding", {}).get("herding_score", 0)
        dominant_rating = behavioral.get("analyst_herding", {}).get(
            "dominant_recommendation", ""
        )
        if herding_score is not None and herding_score >= 8.0 and "buy" in dominant_rating.lower():
            flags.append(
                {
                    "rule": 4,
                    "severity": "medium",
                    "finding": f"Herding score={herding_score}, dominant='{dominant_rating}'",
                    "action": "Apply contrarian overlay — reduce conviction by 0.5-1.0 points",
                    "dimensions": ["behavioral"],
                }
            )
            adjustments.append(
                {
                    "type": "contrarian_overlay",
                    "conviction_adjustment": -0.75,
                    "reason": f"Analyst herding score {herding_score} with {dominant_rating} consensus",
                }
            )

    # Rule 5: Framework divergence
    divergence = scores.get("framework_divergence", {})
    if divergence.get("investigation_required"):
        pairs = divergence.get("divergences", [])
        flags.append(
            {
                "rule": 5,
                "severity": "medium",
                "finding": f"{divergence.get('divergence_count', 0)} framework divergences requiring investigation",
                "action": "Examine each divergent pair and resolve or flag as unresolved",
                "divergent_pairs": pairs,
                "dimensions": ["framework_divergence"],
            }
        )

    # Rule 6: Technical vs Fundamental divergence
    if technical is not None and valuation is not None:
        if abs(technical - valuation) >= 4.0:
            direction = (
                "bullish technicals vs bearish valuation"
                if technical > valuation
                else "bearish technicals vs bullish valuation"
            )
            flags.append(
                {
                    "rule": 6,
                    "severity": "low",
                    "finding": f"Technical={technical}, Valuation={valuation} — {direction}",
                    "action": "Note divergence in report; technical often leads short-term, fundamentals lead long-term",
                    "dimensions": ["technical_setup", "valuation_attractiveness"],
                }
            )

    # Rule 7: Three-Layer Alignment/Divergence (Stock × Industry × Macro)
    # Inspired by AI-Stock-Master's multi-dimensional confirmation logic.
    # When all three layers point the same direction → high conviction bonus.
    # When stock diverges from industry+macro → potential early warning or outlier.
    stock_signal = technical  # Stock-level: technical setup
    industry_signal = industry_traj  # Industry-level: trajectory
    macro_signal = macro  # Macro-level: tailwind/headwind

    layer_scores = {
        "stock": stock_signal,
        "industry": industry_signal,
        "macro": macro_signal,
    }
    available_layers = {k: v for k, v in layer_scores.items() if v is not None}

    if len(available_layers) >= 2:
        # Classify each layer as bullish (≥6.5), bearish (≤4.0), or neutral
        def _classify(score: float) -> str:
            if score >= 6.5:
                return "bullish"
            elif score <= 4.0:
                return "bearish"
            return "neutral"

        classifications = {k: _classify(v) for k, v in available_layers.items()}
        bullish_count = sum(1 for c in classifications.values() if c == "bullish")
        bearish_count = sum(1 for c in classifications.values() if c == "bearish")
        total_layers = len(available_layers)

        # Three-layer alignment bonus (all bullish or all bearish)
        if total_layers >= 3 and (bullish_count == total_layers or bearish_count == total_layers):
            alignment_dir = "bullish" if bullish_count == total_layers else "bearish"
            adjustments.append(
                {
                    "type": "three_layer_alignment",
                    "conviction_adjustment": 0.5 if alignment_dir == "bullish" else -0.5,
                    "reason": (
                        f"All 3 layers aligned {alignment_dir}: "
                        f"stock={stock_signal:.1f}, industry={industry_signal:.1f}, macro={macro_signal:.1f}"
                    ),
                }
            )

        # Stock vs environment divergence (stock bullish but industry+macro bearish, or vice versa)
        if total_layers >= 3:
            stock_class = classifications.get("stock", "neutral")
            env_classes = [classifications.get(k) for k in ("industry", "macro") if k in classifications]

            if stock_class == "bullish" and all(c == "bearish" for c in env_classes):
                flags.append(
                    {
                        "rule": 7,
                        "severity": "medium",
                        "finding": (
                            f"Stock bullish ({stock_signal:.1f}) but industry ({industry_signal:.1f}) "
                            f"and macro ({macro_signal:.1f}) both bearish"
                        ),
                        "action": (
                            "Investigate: is stock an outlier leader, or swimming against the tide? "
                            "Check if company-specific catalysts justify divergence from sector/macro."
                        ),
                        "dimensions": ["technical_setup", "industry_trajectory", "macro_tailwind"],
                    }
                )
            elif stock_class == "bearish" and all(c == "bullish" for c in env_classes):
                flags.append(
                    {
                        "rule": 7,
                        "severity": "medium",
                        "finding": (
                            f"Stock bearish ({stock_signal:.1f}) but industry ({industry_signal:.1f}) "
                            f"and macro ({macro_signal:.1f}) both bullish"
                        ),
                        "action": (
                            "Investigate: is stock a laggard catch-up candidate, or signaling "
                            "company-specific deterioration not reflected in sector peers?"
                        ),
                        "dimensions": ["technical_setup", "industry_trajectory", "macro_tailwind"],
                    }
                )

        # Industry-Macro divergence (industry strong but macro weak → sector-specific strength)
        if "industry" in classifications and "macro" in classifications:
            if classifications["industry"] == "bullish" and classifications["macro"] == "bearish":
                flags.append(
                    {
                        "rule": 7,
                        "severity": "low",
                        "finding": (
                            f"Industry bullish ({industry_signal:.1f}) despite bearish macro ({macro_signal:.1f})"
                        ),
                        "action": "Industry may be counter-cyclical or in secular growth phase; validate durability.",
                        "dimensions": ["industry_trajectory", "macro_tailwind"],
                    }
                )

    # Add alignment metadata to result
    alignment_meta = {
        "layers_available": list(available_layers.keys()) if len(available_layers) >= 2 else [],
        "layer_scores": {k: round(v, 1) for k, v in available_layers.items()} if len(available_layers) >= 2 else {},
        "alignment_status": (
            "fully_aligned" if len(available_layers) >= 3 and (bullish_count == len(available_layers) or bearish_count == len(available_layers))
            else "partially_aligned" if len(available_layers) >= 2 and (bullish_count >= 2 or bearish_count >= 2)
            else "divergent" if len(available_layers) >= 2
            else "insufficient_data"
        ) if len(available_layers) >= 2 else "insufficient_data",
    }

    # Summary
    unresolved_count = len([f for f in flags if f["severity"] == "high"])
    overall_status = "PASS" if unresolved_count == 0 else "NEEDS_RESOLUTION"

    return {
        "status": overall_status,
        "flags": flags,
        "adjustments": adjustments,
        "flag_count": len(flags),
        "high_severity_count": unresolved_count,
        "multi_layer_alignment": alignment_meta,
        "computed_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Cross-check scoring contradictions")
    parser.add_argument("scores_file", help="Path to scores.json")
    parser.add_argument("--behavioral", help="Path to behavioral.json (optional)")
    parser.add_argument("--output", "-o", help="Output JSON path")
    args = parser.parse_args()

    try:
        with open(args.scores_file) as f:
            scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        sys.stderr.write(f"Error reading scores: {e}\n")
        sys.exit(1)

    behavioral = None
    if args.behavioral:
        try:
            with open(args.behavioral) as f:
                behavioral = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    result = run_cross_check(scores, behavioral)

    output = json.dumps(result, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        sys.stderr.write(f"Cross-check results written to {args.output}\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
