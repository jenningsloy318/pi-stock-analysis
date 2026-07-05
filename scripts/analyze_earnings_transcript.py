#!/usr/bin/env python3
"""Earnings Transcript NLP — tone shift + guidance change detection (P0.4).

Sources for design:
  - FinTwit practitioners ranking guidance shift as #1 EPS-surprise predictor
  - Mauboussin "Numerical Rigor" — guidance language scoring
  - Damodaran narrative-vs-numbers — tone vs reported financials divergence
  - docs/research/fintwit-reddit-practitioner-insights-2026-05.md (P0.4)

Inputs:
  --current  path to current-quarter transcript (text file, one line per paragraph)
  --prior    (optional) path to prior-quarter transcript for delta comparison

Outputs (json):
  {
    "tone": {
      "prepared_remarks_score": float (-1..+1),
      "qa_score": float,
      "label": "bullish|neutral|bearish",
      "tone_delta_vs_prior": float | null
    },
    "guidance": {
      "current_guidance_excerpts": [str, ...],
      "prior_guidance_excerpts":   [str, ...],
      "guidance_shift": "raised|reaffirmed|lowered|withdrawn|unclear",
      "shift_evidence": [str, ...]
    },
    "miss_explanation": {
      "classification": "transitory|structural|mixed|n/a",
      "evidence": [str, ...]
    },
    "qa_evasion": {
      "evasion_score_0_100": int,
      "flagged_questions": [str, ...]
    },
    "summary_flags": [str, ...]
  }

Deterministic only — no LLM calls. Pure lexicon + regex pipeline.
For production: swap sentiment scorer for FinBERT.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone


POSITIVE_WORDS = {
    "beat", "beats", "exceeded", "raised", "raising", "raise", "upgrade",
    "outperform", "strong", "record", "robust", "accelerate", "accelerating",
    "expand", "expansion", "momentum", "improving", "improved", "outlook raised",
    "guidance raised", "upside", "tailwind", "tailwinds", "confident",
    "encouraged", "pleased", "well-positioned", "ahead of plan", "exceeded expectations",
}

NEGATIVE_WORDS = {
    "miss", "missed", "below expectations", "lowered", "lowering", "cut",
    "downgrade", "underperform", "weak", "decline", "decelerate", "decelerating",
    "compression", "layoff", "restructuring", "warning", "concern", "headwind",
    "headwinds", "disappointing", "soft", "softness", "softer", "challenged",
    "pressure", "pressures", "uncertainty", "uncertain", "cautious", "challenging",
    "shortfall", "delays", "delay", "writedown", "impair", "impairment",
}

GUIDANCE_TRIGGERS = {
    "guide", "guidance", "expect", "expects", "expected", "expecting",
    "anticipate", "anticipated", "forecast", "forecasting", "outlook",
    "project", "projected", "projecting", "target", "targets", "we see",
    "for the year", "for fiscal", "for Q", "next quarter", "next year",
    "full year", "full-year", "FY",
}

GUIDANCE_DIRECTION_RAISED = {
    "raised", "raising", "increased", "above prior", "ahead of", "higher than",
    "stronger than", "above guidance", "upside to", "upward revision",
}

GUIDANCE_DIRECTION_LOWERED = {
    "lowered", "lowering", "reduced", "below prior", "behind", "lower than",
    "weaker than", "below guidance", "downside to", "downward revision",
    "withdrawing", "suspending guidance",
}

GUIDANCE_DIRECTION_REAFFIRMED = {
    "reaffirm", "reaffirming", "maintaining", "unchanged", "in line with",
    "consistent with prior", "no change to",
}

TRANSITORY_MARKERS = {
    "one-time", "one time", "non-recurring", "transitory", "temporary",
    "weather", "fx", "foreign exchange", "currency headwind", "calendar",
    "calendar shift", "tough comp", "difficult comparison", "easter shift",
    "channel inventory", "destocking", "supply chain", "covid", "covid-19",
    "shutdown", "logistics", "shipping delay",
}

STRUCTURAL_MARKERS = {
    "competitive pressure", "market share loss", "secular decline",
    "demand destruction", "permanent", "structural", "saturated", "saturation",
    "pricing power eroded", "moat eroding", "obsolete", "disruption",
    "regulatory headwind", "category decline",
}

EVASION_MARKERS = {
    "we'll address that later", "we don't comment", "we don't disclose",
    "i don't have that in front of me", "we'll get back to you",
    "i'd rather not", "we're not prepared to", "we'll provide that in",
    "next quarter", "future call", "let me come back to that",
    "i think you can appreciate", "for competitive reasons",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def split_remarks_qa(transcript: str) -> tuple[str, str]:
    """Heuristic: split prepared remarks from Q&A using common cue phrases."""
    cues = [
        "operator: thank you",
        "operator: we'll now",
        "open it up to questions",
        "we'll now take questions",
        "question-and-answer",
        "q&a session",
        "first question comes from",
    ]
    text_lower = transcript.lower()
    split_idx = None
    for cue in cues:
        idx = text_lower.find(cue)
        if idx > 0:
            split_idx = idx
            break
    if split_idx is None:
        return transcript, ""
    return transcript[:split_idx], transcript[split_idx:]


def score_sentiment(text: str) -> float:
    """Return tone score in [-1, +1] based on lexicon counts.

    Normalized by total positive+negative hits (not raw counts).
    """
    if not text:
        return 0.0
    text_lower = text.lower()
    pos = sum(text_lower.count(w) for w in POSITIVE_WORDS)
    neg = sum(text_lower.count(w) for w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


def label_tone(score: float) -> str:
    if score > 0.2:
        return "bullish"
    if score < -0.2:
        return "bearish"
    return "neutral"


def extract_guidance_sentences(text: str, max_results: int = 12) -> list[str]:
    """Pull sentences containing guidance trigger words + a number."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    matches = []
    for s in sentences:
        s_lower = s.lower()
        has_trigger = any(t in s_lower for t in GUIDANCE_TRIGGERS)
        has_number = bool(re.search(r"\d", s))
        if has_trigger and has_number and len(s) < 400:
            matches.append(s.strip())
        if len(matches) >= max_results:
            break
    return matches


def classify_guidance_shift(current_text: str, prior_text: str) -> tuple[str, list[str]]:
    """Return ('raised'|'reaffirmed'|'lowered'|'withdrawn'|'unclear', evidence_sentences)."""
    ctext = current_text.lower()

    raised_hits = [w for w in GUIDANCE_DIRECTION_RAISED if w in ctext]
    lowered_hits = [w for w in GUIDANCE_DIRECTION_LOWERED if w in ctext]
    reaffirm_hits = [w for w in GUIDANCE_DIRECTION_REAFFIRMED if w in ctext]

    if "withdraw" in ctext or "suspend" in ctext or "no longer providing guidance" in ctext:
        return "withdrawn", ["Guidance language: 'withdrawn/suspended' detected"]

    if len(raised_hits) >= 2 and len(lowered_hits) == 0:
        return "raised", [f"Trigger words: {', '.join(raised_hits[:5])}"]
    if len(lowered_hits) >= 2 and len(raised_hits) == 0:
        return "lowered", [f"Trigger words: {', '.join(lowered_hits[:5])}"]
    if len(raised_hits) >= 1 and len(lowered_hits) == 0:
        return "raised", [f"Single raised cue ({', '.join(raised_hits)}), no lowered cues"]
    if len(lowered_hits) >= 1 and len(raised_hits) == 0:
        return "lowered", [f"Single lowered cue ({', '.join(lowered_hits)}), no raised cues"]
    if len(raised_hits) > len(lowered_hits) + 1:
        return "raised", [f"Net upward language: {len(raised_hits)} raised vs {len(lowered_hits)} lowered"]
    if len(lowered_hits) > len(raised_hits) + 1:
        return "lowered", [f"Net downward language: {len(lowered_hits)} lowered vs {len(raised_hits)} raised"]
    if reaffirm_hits:
        return "reaffirmed", [f"Reaffirmation language: {', '.join(reaffirm_hits[:3])}"]
    return "unclear", ["No dominant directional guidance language detected"]


def classify_miss_explanation(text: str) -> tuple[str, list[str]]:
    text_lower = text.lower()
    transitory_hits = [m for m in TRANSITORY_MARKERS if m in text_lower]
    structural_hits = [m for m in STRUCTURAL_MARKERS if m in text_lower]

    evidence = []
    if transitory_hits:
        evidence.append(f"Transitory markers: {', '.join(transitory_hits[:5])}")
    if structural_hits:
        evidence.append(f"Structural markers: {', '.join(structural_hits[:5])}")

    if not transitory_hits and not structural_hits:
        return "n/a", evidence
    if transitory_hits and not structural_hits:
        return "transitory", evidence
    if structural_hits and not transitory_hits:
        return "structural", evidence
    return "mixed", evidence


def score_qa_evasion(qa_text: str) -> tuple[int, list[str]]:
    """0-100 evasion score based on marker frequency.

    Higher = more evasive (red flag).
    """
    if not qa_text:
        return 0, []
    text_lower = qa_text.lower()
    hits = [m for m in EVASION_MARKERS if m in text_lower]
    raw_count = sum(text_lower.count(m) for m in EVASION_MARKERS)
    score = min(raw_count * 12, 100)
    return score, hits[:5]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def analyze(current: str, prior: str | None) -> dict:
    prepared, qa = split_remarks_qa(current)
    prep_score = score_sentiment(prepared)
    qa_score = score_sentiment(qa) if qa else None

    overall_tone = prep_score if qa_score is None else round(prep_score * 0.7 + qa_score * 0.3, 4)
    tone_label = label_tone(overall_tone)

    tone_delta_vs_prior = None
    if prior:
        prior_prepared, _ = split_remarks_qa(prior)
        prior_score = score_sentiment(prior_prepared)
        tone_delta_vs_prior = round(prep_score - prior_score, 4)

    current_guidance = extract_guidance_sentences(prepared + " " + qa)
    prior_guidance = extract_guidance_sentences(prior) if prior else []

    if prior:
        shift, evidence = classify_guidance_shift(current, prior)
    else:
        shift, evidence = "unclear", ["No prior transcript provided — cannot compute shift"]

    miss_class, miss_evidence = classify_miss_explanation(qa or current)
    evasion_score, evasion_hits = score_qa_evasion(qa)

    flags = []
    if tone_label == "bearish":
        flags.append(f"Bearish prepared-remarks tone ({prep_score})")
    if tone_delta_vs_prior is not None and tone_delta_vs_prior < -0.2:
        flags.append(f"Tone deteriorated vs prior quarter (Δ={tone_delta_vs_prior})")
    if shift == "lowered":
        flags.append("Guidance LOWERED vs prior — directional sell signal")
    if shift == "withdrawn":
        flags.append("Guidance WITHDRAWN — high uncertainty signal")
    if miss_class == "structural":
        flags.append("Miss explained by STRUCTURAL factors — likely persistent (concerning)")
    if evasion_score >= 50:
        flags.append(f"High Q&A evasion ({evasion_score}/100) — management dodging hard questions")

    return {
        "tone": {
            "prepared_remarks_score": prep_score,
            "qa_score": qa_score,
            "overall": overall_tone,
            "label": tone_label,
            "tone_delta_vs_prior": tone_delta_vs_prior,
        },
        "guidance": {
            "current_guidance_excerpts": current_guidance[:8],
            "prior_guidance_excerpts": prior_guidance[:8],
            "guidance_shift": shift,
            "shift_evidence": evidence,
        },
        "miss_explanation": {
            "classification": miss_class,
            "evidence": miss_evidence,
        },
        "qa_evasion": {
            "evasion_score_0_100": evasion_score,
            "flagged_phrases": evasion_hits,
        },
        "summary_flags": flags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Earnings Transcript NLP — tone + guidance shift (P0.4)"
    )
    parser.add_argument("--current", required=True, help="Path to current-quarter transcript text file")
    parser.add_argument("--prior", help="Path to prior-quarter transcript (optional, enables delta)")
    parser.add_argument("--ticker", help="Ticker symbol (informational)")
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    try:
        with open(args.current) as fh:
            current = fh.read()
    except FileNotFoundError:
        sys.stderr.write(f"Error: current transcript not found: {args.current}\n")
        sys.exit(1)

    prior = None
    if args.prior:
        try:
            with open(args.prior) as fh:
                prior = fh.read()
        except FileNotFoundError:
            sys.stderr.write(f"Warning: prior transcript not found: {args.prior}\n")

    result = analyze(current, prior)
    result["ticker"] = args.ticker
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["framework"] = "Earnings Transcript NLP (P0.4)"
    result["framework_sources"] = [
        "FinTwit guidance-shift practitioners (@unusual_whales, @SpotGamma, sell-side desks)",
        "Mauboussin numerical rigor / guidance language scoring",
        "Damodaran narrative-vs-numbers divergence",
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
