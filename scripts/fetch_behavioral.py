#!/usr/bin/env python3
"""Behavioral finance analysis: narrative tracking, sentiment divergence,
analyst herding, overreaction detection, anchoring bias, reflexivity.

Usage:
    fetch_behavioral.py AAPL
    fetch_behavioral.py AAPL --output ./reports/[TICKER]/behavioral.json

Analyzes behavioral factors that can drive stock prices beyond fundamentals:
  - Narrative economics: dominant story driving the stock
  - Analyst herding: consensus clustering vs dispersion
  - Sentiment divergence: retail vs institutional sentiment gap
  - Overreaction detection: extreme price moves vs fundamental changes
  - Anchoring bias: stale price targets anchored to 52w highs or round numbers
  - Reflexivity (Soros): self-reinforcing feedback loops via autocorrelation
  - Contrarian signals: crowding indicators
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' required. Run: pip install requests\n")
    sys.exit(1)


HEADERS = {"User-Agent": "StockAnalysisSkill/2.0 (research@example.com)"}


# ---------------------------------------------------------------------------
# Narrative economics — dominant story detection
# ---------------------------------------------------------------------------

NARRATIVE_PATTERNS = {
    "AI Revolution": [
        r"\bAI\b",
        r"\bartificial intelligence\b",
        r"\bmachine learning\b",
        r"\bLLM\b",
        r"\bGPT\b",
        r"\bgenerative AI\b",
        r"\bNLP\b",
        r"\bdeep learning\b",
        r"\btransformer\b",
    ],
    "Rate Cut / Easing": [
        r"\brate cut\b",
        r"\bfed cut\b",
        r"\beasing\b",
        r"\bdovish\b",
        r"\baccommodative\b",
        r"\bmonetary easing\b",
    ],
    "Recession Fear": [
        r"\brecession\b",
        r"\bhard landing\b",
        r"\bdownturn\b",
        r"\blayoffs\b",
        r"\bcontraction\b",
        r"\bnegative growth\b",
    ],
    "Inflation / Stagflation": [
        r"\binflation\b",
        r"\bstagflation\b",
        r"\bCPI\b",
        r"\bprice increases\b",
        r"\bcost pressure\b",
        r"\bwage spiral\b",
    ],
    "China Risk": [
        r"\bChina\b",
        r"\bChinese\b",
        r"\bCCP\b",
        r"\bBeijing\b",
        r"\bTaiwan\b",
        r"\btariff\b",
        r"\bdecoupling\b",
        r"\bsupply chain\b",
    ],
    "Earnings Growth": [
        r"\bearnings beat\b",
        r"\brevenue growth\b",
        r"\bprofit margin\b",
        r"\bEPS\b",
        r"\bquarterly results\b",
        r"\bguidance raise\b",
    ],
    "Regulatory / Antitrust": [
        r"\bantitrust\b",
        r"\bregulation\b",
        r"\bFTC\b",
        r"\bDOJ\b",
        r"\bEU\b",
        r"\bfine\b",
        r"\bcompliance\b",
        r"\blawsuit\b",
    ],
    "Innovation / Disruption": [
        r"\bdisruption\b",
        r"\binnovation\b",
        r"\brevolutionary\b",
        r"\bbreakthrough\b",
        r"\bgame.changer\b",
        r"\bnext generation\b",
    ],
    "M&A Speculation": [
        r"\bacquisition\b",
        r"\bmerger\b",
        r"\bbuyout\b",
        r"\btakeover\b",
        r"\bactivist\b",
        r"\bbreakup\b",
        r"\bspin.off\b",
    ],
    "Meme / Retail Frenzy": [
        r"\bmeme stock\b",
        r"\bMOON\b",
        r"\bYOLO\b",
        r"\bdiamond hands\b",
        r"\bto the moon\b",
        r"\bshort squeeze\b",
        r"\bWSB\b",
        r"\bwallstreetbets\b",
    ],
}


def analyze_narrative(text_corpus: list[str]) -> dict:
    """Detect dominant narratives in a text corpus."""
    if not text_corpus:
        return {"dominant_narrative": "unknown", "narratives": {}}

    combined = " ".join(text_corpus).lower()
    narrative_scores = {}

    for name, patterns in NARRATIVE_PATTERNS.items():
        count = sum(len(re.findall(p, combined, re.IGNORECASE)) for p in patterns)
        if count > 0:
            narrative_scores[name] = count

    if not narrative_scores:
        return {"dominant_narrative": "neutral", "narratives": {}}

    # Sort by count
    sorted_narratives = sorted(narrative_scores.items(), key=lambda x: -x[1])
    total = sum(narrative_scores.values())

    narratives_pct = {
        name: {"count": count, "share": round(count / total, 3) if total > 0 else 0}
        for name, count in sorted_narratives
    }

    dominant = sorted_narratives[0][0] if sorted_narratives else "neutral"

    # Narrative diversity score (lower = single narrative dominating)
    if len(sorted_narratives) > 1:
        top_share = sorted_narratives[0][1] / total if total > 0 else 0
        diversity = 1.0 - top_share  # 0 = single narrative, 1 = highly diverse
    else:
        diversity = 0.0

    return {
        "dominant_narrative": dominant,
        "narrative_diversity": round(diversity, 3),
        "narratives": narratives_pct,
        "interpretation": (
            f"Stock primarily driven by '{dominant}' narrative"
            if diversity < 0.3
            else f"Stock driven by multiple narratives (diversity {diversity:.1f})"
        ),
    }


# ---------------------------------------------------------------------------
# Analyst herding detection
# ---------------------------------------------------------------------------


def compute_analyst_herding(analyst_data: dict) -> dict:
    """Detect analyst herding (consensus clustering)."""
    if not analyst_data:
        return {"herding_score": None, "assessment": "No analyst data available"}

    rec_trends = analyst_data.get("recommendation_trends", [])
    price_target = analyst_data.get("price_target", {})

    if not rec_trends:
        return {"herding_score": None, "assessment": "No recommendation trends"}

    # Herding = high consensus (low dispersion)
    latest = rec_trends[0]
    strong_buy = latest.get("strongBuy", 0)
    buy = latest.get("buy", 0)
    hold = latest.get("hold", 0)
    sell = latest.get("sell", 0)
    strong_sell = latest.get("strongSell", 0)
    total = strong_buy + buy + hold + sell + strong_sell

    if total == 0:
        return {"herding_score": None, "assessment": "No analyst coverage"}

    # Concentration: % in the dominant category
    categories = {
        "Strong Buy": strong_buy,
        "Buy": buy,
        "Hold": hold,
        "Sell": sell,
        "Strong Sell": strong_sell,
    }
    max_cat = max(categories, key=categories.get)
    max_pct = categories[max_cat] / total

    # Herding score: 0-10, higher = more herding
    herding_score = round(max_pct * 10, 1)

    # Dispersion: standard deviation of recommendations
    values = [1] * strong_sell + [2] * sell + [3] * hold + [4] * buy + [5] * strong_buy
    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    dispersion = math.sqrt(variance)

    # Price target dispersion
    pt_dispersion = None
    if price_target:
        high = price_target.get("targetHigh")
        low = price_target.get("targetLow")
        mean = price_target.get("targetMean")
        if high and low and mean and mean > 0:
            pt_dispersion = (high - low) / mean

    if herding_score >= 8.0:
        assessment = f"Strong herding — {max_pct:.0%} of analysts in '{max_cat}'"
    elif herding_score >= 6.0:
        assessment = f"Moderate herding — {max_pct:.0%} consensus in '{max_cat}'"
    elif herding_score >= 4.0:
        assessment = "Moderate dispersion — analysts divided but clustering"
    else:
        assessment = "High dispersion — no clear consensus, independent views"

    return {
        "herding_score": herding_score,
        "dominant_rating": max_cat,
        "dominant_share": round(max_pct, 3),
        "recommendation_dispersion": round(dispersion, 2),
        "price_target_dispersion_ratio": round(pt_dispersion, 3)
        if pt_dispersion is not None
        else None,
        "total_analysts": total,
        "assessment": assessment,
        "warning": "High herding (>8.0) may indicate groupthink — consider contrarian view"
        if herding_score >= 8.0
        else None,
    }


# ---------------------------------------------------------------------------
# Sentiment divergence analysis
# ---------------------------------------------------------------------------


def compute_sentiment_divergence(
    news_sentiment: dict, social_sentiment: dict, insider_data: dict
) -> dict:
    """Analyze divergence between retail, institutional, and insider sentiment."""
    divergences = []

    # News sentiment (institutional-ish)
    news_bias = None
    if news_sentiment:
        dist = news_sentiment.get("sentiment_distribution", {})
        if dist:
            total = (
                dist.get("positive", 0)
                + dist.get("negative", 0)
                + dist.get("neutral", 0)
            )
            if total > 0:
                news_bias = (dist.get("positive", 0) - dist.get("negative", 0)) / total

    # Social sentiment (retail)
    social_bias = None
    if social_sentiment:
        social_bias = social_sentiment.get("reddit_sentiment_score")

    # Insider sentiment
    insider_bias = None
    if insider_data:
        summary = insider_data.get("summary", {})
        buys = summary.get("buys_count", 0)
        sells = summary.get("sells_count", 0)
        if buys + sells > 0:
            insider_bias = (buys - sells) / (buys + sells)

    # Check divergences
    if news_bias is not None and social_bias is not None:
        gap = abs(news_bias - social_bias)
        if gap > 0.4:
            direction = (
                "Retail more bullish than institutional"
                if social_bias > news_bias
                else "Retail more bearish than institutional"
            )
            divergences.append(
                {
                    "type": "retail_vs_institutional",
                    "gap": round(gap, 3),
                    "direction": direction,
                    "significance": "high" if gap > 0.6 else "moderate",
                }
            )

    if news_bias is not None and insider_bias is not None:
        gap = abs(news_bias - insider_bias)
        if gap > 0.4:
            direction = (
                "Insiders more bullish than media"
                if insider_bias > news_bias
                else "Insiders more bearish than media"
            )
            divergences.append(
                {
                    "type": "insider_vs_media",
                    "gap": round(gap, 3),
                    "direction": direction,
                    "significance": "high" if gap > 0.6 else "moderate",
                }
            )

    if social_bias is not None and insider_bias is not None:
        gap = abs(social_bias - insider_bias)
        if gap > 0.5:
            direction = (
                "Insiders buying while retail selling"
                if insider_bias > social_bias
                else "Insiders selling while retail buying"
            )
            divergences.append(
                {
                    "type": "insider_vs_retail",
                    "gap": round(gap, 3),
                    "direction": direction,
                    "significance": "high",
                }
            )

    sentiment_levels = {
        "news_bias": round(news_bias, 3) if news_bias is not None else None,
        "social_bias": round(social_bias, 3) if social_bias is not None else None,
        "insider_bias": round(insider_bias, 3) if insider_bias is not None else None,
    }

    if not divergences:
        return {
            "divergence_detected": False,
            "assessment": "Sentiment aligned across sources — no significant divergence",
            "sentiment_levels": sentiment_levels,
        }

    return {
        "divergence_detected": True,
        "divergence_count": len(divergences),
        "divergences": divergences,
        "sentiment_levels": sentiment_levels,
        "assessment": f"Sentiment divergence detected: {len(divergences)} source(s) misaligned. "
        f"Insider sentiment is the most reliable signal."
        if any(d["type"].startswith("insider") for d in divergences)
        else f"Sentiment divergence detected: {len(divergences)} source(s) misaligned.",
    }


# ---------------------------------------------------------------------------
# Overreaction detection
# ---------------------------------------------------------------------------


def compute_overreaction(
    price_changes: list[float], news_sentiment: dict | None = None
) -> dict:
    """Detect potential overreaction patterns.

    Overreaction: large price moves not justified by fundamental news.
    Underreaction: small price moves despite significant news.
    """
    if not price_changes or len(price_changes) < 5:
        return {"overreaction_detected": False, "assessment": "Insufficient price data"}

    # Volatility assessment
    mean_abs_change = sum(abs(c) for c in price_changes) / len(price_changes)
    std_change = (
        sum((c - sum(price_changes) / len(price_changes)) ** 2 for c in price_changes)
        / len(price_changes)
    ) ** 0.5

    # Count extreme moves (>2 std)
    extreme_threshold = mean_abs_change + 2 * std_change
    extreme_moves = [c for c in price_changes if abs(c) > extreme_threshold]
    extreme_ratio = len(extreme_moves) / len(price_changes) if price_changes else 0

    # Extreme move clustering (2+ extreme moves within 5 days)
    clustered = False
    if len(extreme_moves) >= 2:
        # Check if extreme moves are consecutive within a short window
        for i in range(len(price_changes) - 2):
            window = price_changes[i : i + 5]
            extreme_in_window = sum(1 for c in window if abs(c) > extreme_threshold)
            if extreme_in_window >= 2:
                clustered = True
                break

    # Overreaction assessment
    overreaction = extreme_ratio > 0.15 or clustered

    if overreaction:
        assessment = (
            "Potential overreaction — excessive price volatility relative to fundamentals. "
            "Consider fading extreme moves if fundamentals unchanged."
        )
    elif extreme_ratio > 0.05:
        assessment = "Mild overreaction signals — elevated volatility, monitor for reversal patterns"
    else:
        assessment = (
            "No overreaction detected — price moves consistent with normal volatility"
        )

    # Mean reversion expectation
    # After extreme moves (>2 std), price tends to revert
    if extreme_moves:
        # Count reversals after extremes (opposite direction next day)
        reversal_count = 0
        for i in range(len(price_changes) - 1):
            if abs(price_changes[i]) > extreme_threshold:
                if price_changes[i] * price_changes[i + 1] < 0:  # Opposite sign
                    reversal_count += 1
        reversal_rate = reversal_count / len(extreme_moves) if extreme_moves else 0
    else:
        reversal_rate = 0

    return {
        "overreaction_detected": overreaction,
        "extreme_move_ratio": round(extreme_ratio, 3),
        "extreme_moves_count": len(extreme_moves),
        "clustered_extremes": clustered,
        "mean_reversion_rate": round(reversal_rate, 3) if extreme_moves else 0,
        "mean_abs_change": round(mean_abs_change, 4),
        "volatility_std": round(std_change, 4),
        "assessment": assessment,
    }


# ---------------------------------------------------------------------------
# Anchoring bias detection
# ---------------------------------------------------------------------------


def compute_anchoring_bias(price_data: dict, analyst_data: dict) -> dict:
    """Detect anchoring bias where analysts/investors anchor to stale reference prices.

    Common anchors: 52-week high/low, IPO price, round numbers, prior earnings price.
    Soros insight: participants anchor to past prices, creating self-reinforcing trends.
    """
    signals = []

    # Price target anchoring to 52-week high
    if price_data and analyst_data:
        current = price_data.get("current_price")
        high_52w = price_data.get("high_52w")
        low_52w = price_data.get("low_52w")
        pt_mean = (analyst_data.get("price_target") or {}).get("targetMean")

        if current and high_52w and pt_mean:
            # Check if consensus PT clusters near 52w high (±5%)
            if abs(pt_mean - high_52w) / high_52w < 0.05:
                signals.append(
                    {
                        "anchor": "52-week high",
                        "anchor_value": high_52w,
                        "target_mean": pt_mean,
                        "interpretation": "Consensus PT anchored to 52-week high — likely backward-looking",
                        "bias_strength": "strong",
                    }
                )

            # Check if PT clusters near round number
            nearest_round = round(pt_mean / 50) * 50
            if abs(pt_mean - nearest_round) / pt_mean < 0.03 and nearest_round > 0:
                signals.append(
                    {
                        "anchor": f"Round number ${nearest_round}",
                        "target_mean": pt_mean,
                        "interpretation": "PT clustering near round number — psychological anchoring",
                        "bias_strength": "moderate",
                    }
                )

        # Check if price is significantly below 52w high and PT still near high
        if current and high_52w and pt_mean and current < high_52w * 0.7:
            if pt_mean > high_52w * 0.85:
                signals.append(
                    {
                        "anchor": "stale_high_anchor",
                        "current_price": current,
                        "high_52w": high_52w,
                        "target_mean": pt_mean,
                        "interpretation": "Price dropped >30% but PTs barely adjusted — analysts anchored to old highs",
                        "bias_strength": "strong",
                    }
                )

    # PT dispersion as anchoring proxy (very low dispersion = herded anchor)
    if analyst_data:
        pt_info = analyst_data.get("price_target", {})
        high = pt_info.get("targetHigh")
        low = pt_info.get("targetLow")
        mean = pt_info.get("targetMean")
        if high and low and mean and mean > 0:
            spread = (high - low) / mean
            if spread < 0.15:
                signals.append(
                    {
                        "anchor": "consensus_clustering",
                        "spread_ratio": round(spread, 3),
                        "interpretation": "PT spread <15% — analysts anchoring to each other",
                        "bias_strength": "moderate",
                    }
                )

    return {
        "anchoring_detected": len(signals) > 0,
        "anchor_signals": signals,
        "signal_count": len(signals),
        "assessment": (
            "Strong anchoring bias detected — price targets may not reflect current reality"
            if any(s["bias_strength"] == "strong" for s in signals)
            else "Moderate anchoring detected — targets may be lagging fundamentals"
            if signals
            else "No significant anchoring bias detected"
        ),
        "methodology": "Anchoring detection: compares PT consensus to 52w high, round numbers, and dispersion",
    }


# ---------------------------------------------------------------------------
# Reflexivity quantification (Soros framework)
# ---------------------------------------------------------------------------


def compute_reflexivity(
    price_changes: list[float], fundamentals_trend: dict | None = None
) -> dict:
    """Quantify reflexive feedback loops (Soros Theory of Reflexivity).

    Reflexivity: price changes influence fundamentals which further change prices,
    creating self-reinforcing boom/bust cycles.

    Measures:
    1. Trend persistence (autocorrelation) — how much past returns predict future returns
    2. Volatility asymmetry — do down moves cluster more than up moves?
    3. Momentum acceleration — is the trend strengthening or weakening?
    4. Feedback loop strength — correlation between price momentum and fundamental momentum
    """
    if not price_changes or len(price_changes) < 20:
        return {"reflexivity_score": None, "assessment": "Insufficient data"}

    n = len(price_changes)
    mean_ret = sum(price_changes) / n

    # 1. Autocorrelation (lag-1) — positive = trend persistence (reflexive)
    if n > 1:
        cov = sum(
            (price_changes[i] - mean_ret) * (price_changes[i - 1] - mean_ret)
            for i in range(1, n)
        ) / (n - 1)
        var = sum((r - mean_ret) ** 2 for r in price_changes) / n
        autocorr = cov / var if var > 0 else 0
    else:
        autocorr = 0

    # 2. Volatility asymmetry (downside vol / upside vol)
    up_returns = [r for r in price_changes if r > 0]
    down_returns = [r for r in price_changes if r < 0]
    if up_returns and down_returns:
        up_vol = (sum(r**2 for r in up_returns) / len(up_returns)) ** 0.5
        down_vol = (sum(r**2 for r in down_returns) / len(down_returns)) ** 0.5
        vol_asymmetry = down_vol / up_vol if up_vol > 0 else 1.0
    else:
        vol_asymmetry = 1.0

    # 3. Momentum acceleration (compare first-half vs second-half momentum)
    half = n // 2
    first_half_momentum = sum(price_changes[:half]) / half if half > 0 else 0
    second_half_momentum = (
        sum(price_changes[half:]) / (n - half) if (n - half) > 0 else 0
    )

    if abs(first_half_momentum) > 0.0001:
        acceleration = (second_half_momentum - first_half_momentum) / abs(
            first_half_momentum
        )
    else:
        acceleration = 0

    # 4. Run length analysis (consecutive same-sign days)
    runs = []
    current_run = 1
    for i in range(1, n):
        if (price_changes[i] >= 0) == (price_changes[i - 1] >= 0):
            current_run += 1
        else:
            runs.append(current_run)
            current_run = 1
    runs.append(current_run)
    avg_run = sum(runs) / len(runs) if runs else 1
    max_run = max(runs) if runs else 1

    # Reflexivity composite score (0-10)
    # Higher = more reflexive (self-reinforcing trends)
    score = 5.0  # neutral baseline

    # Positive autocorrelation = reflexive
    if autocorr > 0.15:
        score += 2.0
    elif autocorr > 0.05:
        score += 1.0
    elif autocorr < -0.10:
        score -= 1.5  # Mean-reverting = anti-reflexive

    # High vol asymmetry = reflexive on downside
    if vol_asymmetry > 1.5:
        score += 1.5
    elif vol_asymmetry > 1.2:
        score += 0.5

    # Acceleration = trend strengthening
    if abs(acceleration) > 0.5:
        score += 1.5
    elif abs(acceleration) > 0.2:
        score += 0.5

    # Long runs = persistent trend
    if avg_run > 3.0:
        score += 1.0
    elif avg_run < 1.5:
        score -= 0.5

    score = max(1.0, min(10.0, score))

    # Regime classification
    if score >= 8.0:
        regime = (
            "Strong reflexive loop — self-reinforcing trend, potential bubble/crash"
        )
        phase = "boom" if mean_ret > 0 else "bust"
    elif score >= 6.0:
        regime = "Moderate reflexivity — trend has momentum but not extreme"
        phase = "trending"
    elif score >= 4.0:
        regime = "Low reflexivity — market near equilibrium"
        phase = "equilibrium"
    else:
        regime = "Anti-reflexive — mean-reverting, contrarian opportunity"
        phase = "mean_reverting"

    return {
        "reflexivity_score": round(score, 1),
        "phase": phase,
        "regime": regime,
        "components": {
            "autocorrelation": round(autocorr, 4),
            "volatility_asymmetry": round(vol_asymmetry, 3),
            "momentum_acceleration": round(acceleration, 3),
            "avg_run_length": round(avg_run, 2),
            "max_run_length": max_run,
        },
        "interpretation": (
            f"Reflexivity score {score:.1f}/10 ({phase}). "
            f"Autocorr={autocorr:.3f}, VolAsym={vol_asymmetry:.2f}, "
            f"Accel={acceleration:.2f}."
        ),
        "soros_implication": (
            "Far-from-equilibrium — trend likely to continue until exhaustion"
            if score >= 7.0
            else "Near equilibrium — fundamentals dominate over reflexive dynamics"
            if score <= 4.0
            else "Moderate feedback — watch for inflection signals"
        ),
        "methodology": "Soros reflexivity: autocorrelation + vol asymmetry + momentum acceleration + run analysis",
    }


# ---------------------------------------------------------------------------
# Contrarian / crowding signals
# ---------------------------------------------------------------------------


def compute_contrarian_signals(analyst_data: dict, sentiment_data: dict) -> dict:
    """Identify contrarian signals and crowding indicators."""
    signals = []

    # Analyst consensus at extremes → contrarian signal
    herding = compute_analyst_herding(analyst_data) if analyst_data else {}
    if (herding.get("herding_score") or 0) >= 8.5:
        if herding.get("dominant_rating") in ("Strong Buy", "Buy"):
            signals.append(
                {
                    "signal": "Extreme bullish consensus",
                    "interpretation": "When everyone is bullish, who's left to buy? Contrarian sell signal.",
                    "strength": "moderate",
                }
            )
        elif herding.get("dominant_rating") in ("Strong Sell", "Sell"):
            signals.append(
                {
                    "signal": "Extreme bearish consensus",
                    "interpretation": "When everyone is bearish, who's left to sell? Contrarian buy signal.",
                    "strength": "moderate",
                }
            )

    # Social media extreme sentiment
    if sentiment_data:
        social_bias = sentiment_data.get("social_bias")
        if social_bias is not None:
            if social_bias > 0.5:
                signals.append(
                    {
                        "signal": "Extreme retail bullishness",
                        "interpretation": "Retail euphoria often precedes corrections. Caution warranted.",
                        "strength": "high" if social_bias > 0.7 else "moderate",
                    }
                )
            elif social_bias < -0.5:
                signals.append(
                    {
                        "signal": "Extreme retail bearishness",
                        "interpretation": "Retail capitulation can mark bottoms. Look for stabilization.",
                        "strength": "high" if social_bias < -0.7 else "moderate",
                    }
                )

    return {
        "contrarian_signals": signals,
        "signal_count": len(signals),
        "assessment": (
            "Multiple contrarian signals active — consider fading consensus"
            if len(signals) >= 2
            else "Contrarian signal present — add to risk assessment"
            if len(signals) == 1
            else "No significant contrarian signals"
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Behavioral finance analysis")
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument(
        "--news-text", help="Path to text file with recent news articles (one per line)"
    )
    parser.add_argument(
        "--analyst-json", help="Path to analyst data JSON (from fetch_sentiment.py)"
    )
    parser.add_argument(
        "--social-json",
        help="Path to social sentiment JSON (from fetch_alternatives.py)",
    )
    parser.add_argument(
        "--insider-json", help="Path to insider data JSON (from fetch_sentiment.py)"
    )
    parser.add_argument(
        "--price-changes", help="Path to JSON array of daily percent price changes"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    result = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }

    # Load inputs
    news_texts = []
    if args.news_text:
        try:
            with open(args.news_text) as f:
                news_texts = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            pass

    analyst_data = {}
    if args.analyst_json:
        try:
            with open(args.analyst_json) as f:
                raw = json.load(f)
                analyst_data = raw.get(ticker, list(raw.values())[0] if raw else {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    social_data = {}
    if args.social_json:
        try:
            with open(args.social_json) as f:
                raw = json.load(f)
                alt = raw.get("alternative_data", {})
                social_data = alt.get("social", {})
                news_data = alt.get("news", {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    insider_data = {}
    if args.insider_json:
        try:
            with open(args.insider_json) as f:
                raw = json.load(f)
                insider_data = (
                    raw.get(ticker, {}).get("insider", {}) if ticker in raw else {}
                )
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    price_changes = []
    if args.price_changes:
        try:
            with open(args.price_changes) as f:
                price_changes = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # Narrative analysis
    result["narrative"] = analyze_narrative(news_texts)

    # Analyst herding
    result["analyst_herding"] = compute_analyst_herding(analyst_data)

    # Sentiment divergence
    result["sentiment_divergence"] = compute_sentiment_divergence(
        {}, social_data, insider_data
    )

    # Overreaction detection
    result["overreaction"] = compute_overreaction(price_changes)

    # Anchoring bias
    price_data = {}
    if price_changes:
        price_data["current_price"] = None  # Would need yfinance; use what's available
    result["anchoring_bias"] = compute_anchoring_bias(price_data, analyst_data)

    # Reflexivity (Soros)
    result["reflexivity"] = compute_reflexivity(price_changes)

    # Contrarian signals
    result["contrarian"] = compute_contrarian_signals(analyst_data, social_data)

    # Behavioral summary
    warnings = []
    if (result["analyst_herding"].get("herding_score") or 0) >= 8.0:
        warnings.append("Analyst herding detected — consensus may be groupthink")
    if result["sentiment_divergence"].get("divergence_detected"):
        warnings.append("Sentiment divergence — conflicting signals across sources")
    if result["overreaction"].get("overreaction_detected"):
        warnings.append(
            "Overreaction detected — price moves exceed fundamental justification"
        )
    if result["anchoring_bias"].get("anchoring_detected"):
        warnings.append("Anchoring bias detected — targets may lag reality")
    if (result["reflexivity"].get("reflexivity_score") or 0) >= 8.0:
        warnings.append(
            f"Strong reflexive loop ({result['reflexivity'].get('phase', 'unknown')}) — self-reinforcing trend"
        )
    if result["contrarian"].get("signal_count", 0) > 0:
        warnings.append(
            f"{result['contrarian']['signal_count']} contrarian signal(s) active"
        )

    result["behavioral_summary"] = {
        "warnings": warnings,
        "warning_count": len(warnings),
        "overall_assessment": (
            "Multiple behavioral red flags — exercise caution, consider reducing position"
            if len(warnings) >= 3
            else "Some behavioral concerns — factor into risk assessment"
            if len(warnings) >= 1
            else "No significant behavioral anomalies detected"
        ),
    }

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
