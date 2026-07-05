#!/usr/bin/env python3
"""Calculate Management Candor Index from earnings call transcripts.

Usage:
    calculate_candor.py ./reports/AAPL/transcript.txt

Analyzes transcripts for linguistic deception indicators:
1. Hedging Word Density (uncertainty: 'maybe', 'perhaps', 'could')
2. Certainty Word Density (confidence: 'clearly', 'definitely', 'committed')
3. Q&A vs Prepared Remarks Differential (spontaneous tone shift)
4. Distancing Language (passive voice, collective deflection)

Output: JSON with candor_score (0-100), section breakdown, and verdict.
"""

import argparse
import json
import re
import sys

HEDGING_WORDS = [
    "maybe",
    "perhaps",
    "might",
    "could",
    "possibly",
    "presumably",
    "uncertain",
    "unclear",
    "potentially",
    "around",
    "about",
    "approximately",
    "somewhat",
    "largely",
    "generally",
    "likely",
]

CERTAINTY_WORDS = [
    "clearly",
    "definitely",
    "certainly",
    "will",
    "committed",
    "confident",
    "assured",
    "proven",
    "demonstrated",
    "visible",
    "absolutely",
    "undoubtedly",
    "strong",
    "robust",
]

DISTANCING_PATTERNS = [
    r"\b(it was decided|management feels|the team believes)\b",
    r"\b(one might say|it could be argued|some would say)\b",
    r"\b(mistakes were made|issues were identified)\b",
]

PROMOTIONAL_PATTERNS = [
    r"\b(extraordinary|revolutionary|unprecedented|game-changer)\b",
    r"\b(best-in-class|world-class|industry-leading|unmatched)\b",
]

QA_SPLIT_MARKERS = [
    r"(?i)\bquestion[- ]and[- ]answer\b",
    r"(?i)\bQ\s*&\s*A\s*(session|segment|portion)?\b",
    r"(?i)\boperator:\s*(thank you|we will now|our first question)\b",
    r"(?i)\b(now|we will)\s+(take|open).{0,20}questions\b",
]


def split_prepared_vs_qa(text: str) -> tuple[str, str]:
    """Split transcript into Prepared Remarks and Q&A sections.

    Returns (prepared_remarks, qa_section). If no split found, returns (text, "").
    """
    for pattern in QA_SPLIT_MARKERS:
        match = re.search(pattern, text)
        if match:
            split_pos = match.start()
            return text[:split_pos], text[split_pos:]
    return text, ""


def analyze_section(text: str) -> dict | None:
    """Analyze a text section for candor indicators."""
    words = text.lower().split()
    total_words = len(words)
    if total_words < 50:
        return None

    lower_text = text.lower()
    hedge_count = sum(
        len(re.findall(r"\b" + re.escape(w) + r"\b", lower_text)) for w in HEDGING_WORDS
    )
    certainty_count = sum(
        len(re.findall(r"\b" + re.escape(w) + r"\b", lower_text))
        for w in CERTAINTY_WORDS
    )

    distancing_count = sum(
        len(re.findall(p, text, re.IGNORECASE)) for p in DISTANCING_PATTERNS
    )
    promotional_count = sum(
        len(re.findall(p, text, re.IGNORECASE)) for p in PROMOTIONAL_PATTERNS
    )

    hedge_pct = (hedge_count / total_words) * 100
    certainty_pct = (certainty_count / total_words) * 100
    distancing_density = (distancing_count / total_words) * 1000
    promotional_density = (promotional_count / total_words) * 1000

    score = (
        100
        - (hedge_pct * 8)
        + (certainty_pct * 5)
        - (distancing_density * 30)
        - (promotional_density * 15)
    )
    score = max(0, min(100, score))

    return {
        "word_count": total_words,
        "candor_score": round(score, 1),
        "hedge_density": round(hedge_pct, 4),
        "certainty_density": round(certainty_pct, 4),
        "distancing_density": round(distancing_density, 4),
        "promotional_density": round(promotional_density, 4),
    }


def analyze_transcript(text: str) -> dict:
    """Full transcript analysis with Q&A differential."""
    prepared, qa = split_prepared_vs_qa(text)

    prepared_analysis = analyze_section(prepared)
    qa_analysis = analyze_section(qa) if qa else None

    if prepared_analysis is None:
        overall = analyze_section(text)
        if overall is None:
            return {"error": "Transcript too short for analysis (< 50 words)"}
        return {
            "candor_score": overall["candor_score"],
            "verdict": _verdict(overall["candor_score"]),
            "sections_split": False,
            "overall": overall,
        }

    overall_score = prepared_analysis["candor_score"]
    qa_delta = None

    if qa_analysis:
        qa_delta = round(
            qa_analysis["candor_score"] - prepared_analysis["candor_score"], 1
        )
        overall_score = round(
            prepared_analysis["candor_score"] * 0.4 + qa_analysis["candor_score"] * 0.6,
            1,
        )

    return {
        "candor_score": overall_score,
        "verdict": _verdict(overall_score),
        "sections_split": qa_analysis is not None,
        "prepared_remarks": prepared_analysis,
        "qa_section": qa_analysis,
        "qa_vs_prepared_delta": qa_delta,
        "qa_delta_interpretation": _interpret_delta(qa_delta)
        if qa_delta is not None
        else None,
    }


def _verdict(score: float) -> str:
    if score > 75:
        return "Candid"
    if score > 50:
        return "Cautious"
    return "Deceptive/Obscure"


def _interpret_delta(delta: float) -> str:
    """Interpret the Q&A vs Prepared delta.

    Prepared remarks are always more polished, so a mild negative delta (-5 to -25)
    is normal. Only flag when the gap is extreme (>30 points) suggesting evasion.
    """
    if delta > 10:
        return "Q&A significantly more candid than prepared remarks (positive — direct, unscripted)"
    if delta > -5:
        return "Minimal difference between sections (consistent tone)"
    if delta > -25:
        return "Q&A slightly less candid — normal pattern for spontaneous speech"
    if delta > -40:
        return "Q&A notably less candid — possible evasion under questioning"
    return (
        "Q&A significantly less candid — red flag: confidence collapses under scrutiny"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Calculate Management Candor Index from earnings transcript"
    )
    parser.add_argument("transcript_path", help="Path to transcript text file")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    try:
        with open(args.transcript_path, "r") as f:
            text = f.read()
    except FileNotFoundError:
        sys.stderr.write(f"Error: File not found: {args.transcript_path}\n")
        sys.exit(1)

    result = analyze_transcript(text)
    output = json.dumps(result, indent=2)

    if args.output:
        import os

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
