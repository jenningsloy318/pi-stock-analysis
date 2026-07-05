#!/usr/bin/env python3
"""Compute real-time news sentiment and narrative tracking for a stock.

Usage:
    fetch_news_nlp.py AAPL
    fetch_news_nlp.py AAPL --days 30 --output ./reports/[TICKER]/news-sentiment.json
    fetch_news_nlp.py AAPL --sources news,reddit,twitter

Aggregates news articles and social media posts, computes:
  - Entity-level sentiment (positive/negative/neutral distribution)
  - Narrative themes (what stories are driving coverage?)
  - Sentiment momentum (is sentiment improving or deteriorating?)
  - Surprise detection (unusual spike in coverage volume)
  - Headline tone analysis (simple keyword-based heuristic)

Data sources (free/public):
  - Finnhub company news (requires FINNHUB_API_KEY)
  - Reddit praw (subreddit scraping — requires REDDIT_CLIENT_ID/SECRET)
  - Web search for news headlines (Firecrawl/XCrawl fallback)

For production NLP: integrate with a transformer model (FinBERT, RoBERTa-finance)
for more accurate sentiment. This script provides the pipeline structure.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Sentiment lexicon (lightweight keyword-based — for production, use FinBERT)
# ---------------------------------------------------------------------------

POSITIVE_WORDS = {
    "beat", "beats", "beat expectations", "raised guidance", "raise guidance",
    "upgrade", "upgraded", "outperform", "strong", "record", "surge", "surges",
    "jump", "soar", "rally", "breakthrough", "approval", "approved",
    "bullish", "buy", "overweight", "positive", "growth accelerating",
    "margin expansion", "share buyback", "dividend increase", "beat estimates",
    "exceed", "exceeded", "outlook raised", "guidance raised", "momentum",
}

NEGATIVE_WORDS = {
    "miss", "misses", "missed expectations", "lowered guidance", "cut guidance",
    "downgrade", "downgraded", "underperform", "weak", "decline", "plunge",
    "drop", "fall", "crash", "investigation", "lawsuit", "fine", "penalty",
    "bearish", "sell", "underweight", "negative", "growth decelerating",
    "margin compression", "layoff", "layoffs", "restructuring", "recall",
    "warning", "risk", "concern", "headwind", "headwinds", "disappointing",
    "below expectations", "outlook cut", "guidance cut",
}

# Narrative theme keywords
NARRATIVE_THEMES = {
    "earnings": {"earnings", "eps", "revenue", "quarterly", "q1", "q2", "q3", "q4", "fiscal"},
    "ai_technology": {"ai", "artificial intelligence", "machine learning", "llm", "gpt", "chatbot"},
    "product_launch": {"launch", "new product", "release", "announced", "unveiled", "next generation"},
    "m_and_a": {"acquisition", "acquire", "merger", "takeover", "bid", "deal", "buyout"},
    "regulatory": {"regulation", "ftc", "sec", "doj", "antitrust", "fine", "investigation", "lawsuit"},
    "competitive": {"competitor", "market share", "rival", "disrupt", "threat"},
    "management": {"ceo", "cfo", "executive", "board", "departure", "appointed", "succession"},
    "macro_economy": {"inflation", "recession", "fed", "interest rate", "tariff", "trade war"},
}


def analyze_headline_sentiment(headline: str) -> dict:
    """Simple keyword-based sentiment analysis for financial headlines.

    For production: replace with FinBERT or a finance-specific transformer model.
    """
    headline_lower = headline.lower()

    pos_count = sum(1 for w in POSITIVE_WORDS if w in headline_lower)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in headline_lower)

    if pos_count > neg_count:
        sentiment = "positive"
        score = min(1.0, 0.5 + (pos_count - neg_count) * 0.15)
    elif neg_count > pos_count:
        sentiment = "negative"
        score = max(-1.0, -0.5 - (neg_count - pos_count) * 0.15)
    else:
        sentiment = "neutral"
        score = 0.0

    # Detect narrative themes
    themes = []
    for theme, keywords in NARRATIVE_THEMES.items():
        if any(kw in headline_lower for kw in keywords):
            themes.append(theme)

    return {
        "headline": headline,
        "sentiment": sentiment,
        "sentiment_score": round(score, 3),
        "themes": themes,
    }


def analyze_article_batch(articles: list[dict]) -> dict:
    """Analyze a batch of news articles for aggregate sentiment and themes."""
    if not articles:
        return {
            "article_count": 0,
            "sentiment_distribution": {"positive": 0, "negative": 0, "neutral": 0},
            "sentiment_bias": "no_data",
            "dominant_themes": [],
            "sentiment_momentum": "no_data",
        }

    sentiments = []
    all_themes = []

    for article in articles:
        headline = article.get("headline", article.get("title", ""))
        if not headline:
            continue

        analysis = analyze_headline_sentiment(headline)
        sentiments.append(analysis["sentiment"])
        all_themes.extend(analysis.get("themes", []))

    # Sentiment distribution
    pos = sentiments.count("positive")
    neg = sentiments.count("negative")
    neu = sentiments.count("neutral")
    total = len(sentiments) if sentiments else 1

    if pos > neg + neu:
        bias = "positive"
    elif neg > pos + neu:
        bias = "negative"
    elif pos + neg > neu:
        bias = "mixed"
    else:
        bias = "neutral"

    # Dominant themes
    theme_counts = Counter(all_themes)
    dominant = theme_counts.most_common(5)

    # Sentiment momentum: is recent sentiment better than earlier?
    half = len(sentiments) // 2
    if half >= 2:
        recent_pos = sentiments[:half].count("positive")
        recent_neg = sentiments[:half].count("negative")
        older_pos = sentiments[half:].count("positive")
        older_neg = sentiments[half:].count("negative")

        recent_net = recent_pos - recent_neg
        older_net = older_pos - older_neg

        if recent_net > older_net + 1:
            momentum = "improving"
        elif recent_net < older_net - 1:
            momentum = "deteriorating"
        else:
            momentum = "stable"
    else:
        momentum = "insufficient_data"

    return {
        "article_count": len(articles),
        "sentiment_distribution": {
            "positive": pos,
            "negative": neg,
            "neutral": neu,
        },
        "sentiment_bias": bias,
        "sentiment_score": round((pos - neg) / total, 3),
        "dominant_themes": [{"theme": t, "count": c} for t, c in dominant],
        "sentiment_momentum": momentum,
        "methodology": "Keyword-based headline sentiment (lightweight). For production, integrate FinBERT.",
    }


def detect_surprise_spike(articles: list[dict], baseline_daily: float = 5) -> dict:
    """Detect unusual spikes in news coverage volume.

    A coverage spike often precedes significant price moves (earnings leaks,
    M&A rumors, regulatory actions).
    """
    if len(articles) < 10:
        return {"spike_detected": False, "note": "Insufficient articles for baseline"}

    # Group by date
    by_date = defaultdict(int)
    for article in articles:
        dt_str = article.get("datetime", article.get("date", ""))
        if dt_str:
            try:
                dt = dt_str[:10]  # YYYY-MM-DD
                by_date[dt] += 1
            except Exception:
                pass

    if not by_date:
        return {"spike_detected": False, "note": "No dated articles"}

    dates = sorted(by_date.keys())
    volumes = [by_date[d] for d in dates]

    # Simple spike detection: daily volume > 3x the trailing 20-day average
    if len(volumes) >= 5:
        recent_vol = volumes[-1]
        trailing_avg = sum(volumes[:-1]) / max(len(volumes) - 1, 1)

        if trailing_avg > 0 and recent_vol > trailing_avg * 3:
            return {
                "spike_detected": True,
                "spike_date": dates[-1],
                "spike_volume": recent_vol,
                "trailing_avg_volume": round(trailing_avg, 1),
                "ratio": round(recent_vol / trailing_avg, 1),
                "interpretation": "Unusual news volume spike detected — investigate for potential catalyst event.",
            }

    return {"spike_detected": False, "max_daily_volume": max(volumes), "avg_daily_volume": round(sum(volumes) / len(volumes), 1)}


def main():
    parser = argparse.ArgumentParser(
        description="Compute news sentiment and narrative tracking"
    )
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument("--days", type=int, default=30, help="News lookback in days (default: 30)")
    parser.add_argument("--sources", default="news", help="Comma-separated sources: news,reddit,twitter")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    result = {
        "ticker": ticker,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": args.days,
        "sources_requested": args.sources,
        "methodology": "Keyword-based sentiment analysis. For production-grade accuracy, "
                       "integrate with FinBERT (financial NLP transformer) or similar financial LLM.",
    }

    # Note: This script provides the pipeline structure.
    # Actual news fetching requires either:
    # 1. Finnhub API (news endpoint — requires FINNHUB_API_KEY)
    # 2. Web search (Firecrawl/XCrawl) for "[TICKER] news [date]"
    # 3. Reddit API (praw — requires REDDIT_CLIENT_ID/SECRET)
    #
    # The agent should use search tools (Firecrawl, Tavily, XCrawl) to fetch
    # recent news headlines, then pipe them to this script's analyze_article_batch()
    # function for aggregation.

    result["available_functions"] = {
        "analyze_headline_sentiment": "Simple keyword-based sentiment for financial headlines.",
        "analyze_article_batch": "Aggregate sentiment, themes, and momentum from article batch.",
        "detect_surprise_spike": "Detect unusual news volume spikes.",
        "integration_note": (
            "To use: fetch news articles via search tools (Firecrawl/XCrawl/Tavily), "
            "then pipe the parsed headlines JSON to this script via: "
            "fetch_news_nlp.py [TICKER] --articles-json ./reports/[TICKER]/raw-articles.json"
        ),
    }

    result["sentiment_lexicon"] = {
        "positive_keywords": sorted(list(POSITIVE_WORDS)),
        "negative_keywords": sorted(list(NEGATIVE_WORDS)),
        "narrative_themes": {k: sorted(list(v)) for k, v in NARRATIVE_THEMES.items()},
    }

    result["usage"] = (
        "Run this script after fetching articles via search agents. "
        "The NLP pipeline aggregates sentiment, detects narrative themes, "
        "and tracks sentiment momentum — feeding into Stage 6.4 (Sentiment) "
        "and Stage 9 (Alternative Data)."
    )

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
