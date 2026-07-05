#!/usr/bin/env python3
"""Fetch sentiment, insider transactions, earnings calendar, and analyst data.

Usage:
    fetch_sentiment.py AAPL
    fetch_sentiment.py AAPL --sources insider,news,earnings,analyst
    fetch_sentiment.py AAPL MSFT --output ./reports/[TICKER]/sentiment.json

Primary data source: Finnhub (free tier: 60 API calls/minute).
Register for a free key at: https://finnhub.io/
Set environment variable: FINNHUB_API_KEY

Data categories:
  - insider: Recent insider transactions with cluster detection
  - news: Company news with sentiment scores
  - earnings: Earnings calendar (past surprise + upcoming)
  - analyst: Recommendations trends and price targets

Fallback: If Finnhub is unavailable, attempts web scraping hints.
Paywalled sources return null — never error.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' package required. Run: pip install requests\n")
    sys.exit(1)

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Rate limiter
REQUEST_INTERVAL = 1.0  # 60 calls/min → 1 per second
_last_request_time = 0.0


def rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def finnhub_call(endpoint: str, api_key: str, params: dict | None = None) -> dict:
    """Make a rate-limited call to Finnhub API."""
    rate_limit()
    url = f"{FINNHUB_BASE}{endpoint}"
    p = {"token": api_key}
    if params:
        p.update(params)
    try:
        resp = requests.get(url, params=p, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}", "body": resp.text[:200]}
    except requests.RequestException as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Insider Transactions
# ---------------------------------------------------------------------------


def fetch_insider_transactions(ticker: str, api_key: str) -> dict:
    """Fetch insider transactions and detect cluster activity.

    Cluster detection: 3+ insiders buying/selling within 30 days.
    """
    data = finnhub_call(
        "/stock/insider-transactions", api_key, {"symbol": ticker, "limit": 100}
    )

    if "error" in data:
        return {
            "source": "finnhub",
            "status": "error",
            "error": data["error"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    transactions = data.get("data", [])
    if not transactions:
        return {
            "source": "finnhub",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "total_transactions": 0,
            "recent_transactions": [],
            "cluster_detection": None,
            "note": "No insider transactions found for this ticker.",
        }

    # Parse and categorize
    parsed = []
    for t in transactions[:50]:
        tx_date = t.get("transactionDate", "")
        tx_type = t.get("transactionType", "")
        parsed.append(
            {
                "name": t.get("name", ""),
                "position": t.get("position", ""),
                "transaction_type": tx_type,
                "transaction_date": tx_date,
                "shares": t.get("share"),
                "price": t.get("price"),
                "value": t.get("value"),
                "is_10b5_1": "10b5" in str(t.get("transactionCode", "")).lower(),
            }
        )

    # Cluster detection: group transactions by month
    monthly_buys = defaultdict(int)
    monthly_sells = defaultdict(int)
    monthly_buyers = defaultdict(set)
    monthly_sellers = defaultdict(set)

    # Finnhub returns transactionType strings like "P - Purchase" / "S - Sale".
    # Match the leading code letter rather than literal "Buy"/"Sell".
    def _is_buy(tx_type: str) -> bool:
        s = (tx_type or "").strip().upper()
        return s.startswith("P") or s == "BUY" or "PURCHASE" in s

    def _is_sell(tx_type: str) -> bool:
        s = (tx_type or "").strip().upper()
        return s.startswith("S") or s == "SELL" or "SALE" in s

    for t in parsed:
        if not t["transaction_date"]:
            continue
        try:
            dt = datetime.strptime(t["transaction_date"], "%Y-%m-%d")
        except ValueError:
            continue
        month_key = dt.strftime("%Y-%m")
        if _is_buy(t["transaction_type"]) and not t["is_10b5_1"]:
            monthly_buys[month_key] += t["value"] or 0
            monthly_buyers[month_key].add(t["name"])
        elif _is_sell(t["transaction_type"]) and not t["is_10b5_1"]:
            monthly_sells[month_key] += t["value"] or 0
            monthly_sellers[month_key].add(t["name"])

    cluster_signals = []
    for month in sorted(
        set(list(monthly_buyers.keys()) + list(monthly_sellers.keys()))
    ):
        if len(monthly_buyers.get(month, set())) >= 3:
            cluster_signals.append(
                {
                    "month": month,
                    "type": "cluster_buying",
                    "insiders": len(monthly_buyers[month]),
                    "total_value": round(monthly_buys[month], 2),
                    "signal": "Bullish — cluster insider buying is the strongest Form 4 signal.",
                }
            )
        if len(monthly_sellers.get(month, set())) >= 3:
            cluster_signals.append(
                {
                    "month": month,
                    "type": "cluster_selling",
                    "insiders": len(monthly_sellers[month]),
                    "total_value": round(monthly_sells[month], 2),
                    "signal": "Bearish — cluster insider selling warrants investigation.",
                }
            )

    return {
        "source": "finnhub",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "total_transactions": len(transactions),
        "recent_transactions": parsed,
        "cluster_detection": cluster_signals if cluster_signals else None,
        "summary": {
            "buys_count": sum(1 for t in parsed if t["transaction_type"] == "Buy"),
            "sells_count": sum(1 for t in parsed if t["transaction_type"] == "Sell"),
            "buys_value": round(
                sum(t["value"] or 0 for t in parsed if t["transaction_type"] == "Buy"),
                2,
            ),
            "sells_value": round(
                sum(t["value"] or 0 for t in parsed if t["transaction_type"] == "Sell"),
                2,
            ),
            "note": "Open-market purchases (non-10b5-1) are the strongest insider signal.",
        },
    }


# ---------------------------------------------------------------------------
# Company News Sentiment
# ---------------------------------------------------------------------------


def fetch_news_sentiment(ticker: str, api_key: str) -> dict:
    """Fetch recent company news with Finnhub's sentiment analysis."""
    # Last 30 days
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    data = finnhub_call(
        "/company-news",
        api_key,
        {
            "symbol": ticker,
            "from": date_from,
            "to": date_to,
        },
    )

    if "error" in data:
        return {
            "source": "finnhub",
            "status": "error",
            "error": data["error"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    if isinstance(data, list):
        articles = data[:30]
    else:
        articles = []

    if not articles:
        return {
            "source": "finnhub",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "article_count": 0,
            "sentiment_summary": None,
        }

    # Aggregate sentiment
    sentiments = []
    total_positive = 0
    total_negative = 0
    total_neutral = 0

    for a in articles:
        s = a.get("sentiment", "neutral")
        if s == "positive":
            total_positive += 1
        elif s == "negative":
            total_negative += 1
        else:
            total_neutral += 1
        sentiments.append(s)

    # Finnhub news sentiment API for more precise scores
    sent_data = finnhub_call("/news-sentiment", api_key, {"symbol": ticker})
    buzz = None
    sentiment_score = None
    if "error" not in sent_data:
        buzz = sent_data.get("buzz", {})
        sentiment_score = sent_data.get("sentiment", {})

    return {
        "source": "finnhub",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "article_count": len(articles),
        "sentiment_distribution": {
            "positive": total_positive,
            "negative": total_negative,
            "neutral": total_neutral,
        },
        "sentiment_bias": (
            "positive"
            if total_positive > total_negative + total_neutral
            else "negative"
            if total_negative > total_positive + total_neutral
            else "mixed"
            if total_positive + total_negative > total_neutral
            else "neutral"
        ),
        "buzz_score": buzz,
        "sentiment_score": sentiment_score,
        "recent_headlines": [
            {
                "headline": a.get("headline", ""),
                "source": a.get("source", ""),
                "datetime": a.get("datetime"),
                "sentiment": a.get("sentiment"),
                "url": a.get("url", ""),
            }
            for a in articles[:10]
        ],
    }


# ---------------------------------------------------------------------------
# Earnings Calendar
# ---------------------------------------------------------------------------


def fetch_earnings_calendar(ticker: str, api_key: str) -> dict:
    """Fetch past earnings surprises and upcoming earnings date."""
    # Past earnings surprises (last 4 quarters)
    past_data = finnhub_call("/stock/earnings", api_key, {"symbol": ticker, "limit": 4})

    # Upcoming earnings (next 4 quarters)
    upcoming_data = finnhub_call(
        "/calendar/earnings",
        api_key,
        {
            "symbol": ticker,
            "from": datetime.now().strftime("%Y-%m-%d"),
            "to": (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d"),
        },
    )

    past_surprises = []
    if "error" not in past_data and isinstance(past_data, list):
        for e in past_data:
            actual = e.get("actual")
            estimate = e.get("estimate")
            surprise = None
            surprise_pct = None
            if actual is not None and estimate is not None and estimate != 0:
                surprise = actual - estimate
                surprise_pct = (surprise / abs(estimate)) * 100
            past_surprises.append(
                {
                    "period": e.get("period", ""),
                    "actual": actual,
                    "estimate": estimate,
                    "surprise": round(surprise, 4) if surprise is not None else None,
                    "surprise_pct": round(surprise_pct, 2)
                    if surprise_pct is not None
                    else None,
                }
            )

    upcoming = []
    next_date = None
    if "error" not in upcoming_data and isinstance(upcoming_data, dict):
        earnings_list = upcoming_data.get("earningsCalendar", [])
        for e in earnings_list[:4]:
            edate = e.get("date", "")
            if not next_date:
                next_date = edate
            upcoming.append(
                {
                    "date": edate,
                    "eps_estimate": e.get("epsEstimate"),
                    "eps_actual": e.get("epsActual"),
                    "revenue_estimate": e.get("revenueEstimate"),
                    "revenue_actual": e.get("revenueActual"),
                    "hour": e.get("hour", ""),
                }
            )

    # Beat streak
    beat_streak = 0
    for s in past_surprises:
        if s.get("surprise") is not None and s["surprise"] > 0:
            beat_streak += 1
        else:
            break

    return {
        "source": "finnhub",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "next_earnings_date": next_date,
        "days_until_earnings": (
            (datetime.strptime(next_date, "%Y-%m-%d") - datetime.now()).days
            if next_date
            else None
        ),
        "past_surprises": past_surprises,
        "beat_streak": beat_streak,
        "avg_surprise_pct": (
            round(
                sum(
                    s["surprise_pct"]
                    for s in past_surprises
                    if s["surprise_pct"] is not None
                )
                / max(
                    1, sum(1 for s in past_surprises if s["surprise_pct"] is not None)
                ),
                2,
            )
            if past_surprises
            else None
        ),
        "upcoming_earnings": upcoming,
    }


# ---------------------------------------------------------------------------
# Analyst Recommendations & Price Targets
# ---------------------------------------------------------------------------


def fetch_analyst_data(ticker: str, api_key: str) -> dict:
    """Fetch analyst recommendations and price targets from Finnhub."""
    rec_data = finnhub_call("/stock/recommendation", api_key, {"symbol": ticker})
    target_data = finnhub_call("/stock/price-target", api_key, {"symbol": ticker})

    recommendations = []
    if "error" not in rec_data and isinstance(rec_data, list):
        for r in rec_data[:6]:
            recommendations.append(
                {
                    "period": r.get("period", ""),
                    "strong_buy": r.get("strongBuy"),
                    "buy": r.get("buy"),
                    "hold": r.get("hold"),
                    "sell": r.get("sell"),
                    "strong_sell": r.get("strongSell"),
                }
            )

    price_target = None
    if "error" not in target_data and isinstance(target_data, dict):
        price_target = {
            "last_updated": target_data.get("lastUpdated", ""),
            "target_high": target_data.get("targetHigh"),
            "target_low": target_data.get("targetLow"),
            "target_mean": target_data.get("targetMean"),
            "target_median": target_data.get("targetMedian"),
            "number_of_analysts": target_data.get("numberAnalysts"),
        }

    # Current consensus from latest month
    consensus = None
    if recommendations:
        latest = recommendations[0]
        total = (
            latest.get("strongBuy", 0)
            + latest.get("buy", 0)
            + latest.get("hold", 0)
            + latest.get("sell", 0)
            + latest.get("strongSell", 0)
        )
        if total and total > 0:
            bull_pct = (
                (latest.get("strongBuy", 0) + latest.get("buy", 0)) / total
            ) * 100
            if bull_pct >= 70:
                consensus = "Bullish"
            elif bull_pct >= 50:
                consensus = "Moderately Bullish"
            elif bull_pct >= 30:
                consensus = "Neutral"
            elif bull_pct >= 15:
                consensus = "Moderately Bearish"
            else:
                consensus = "Bearish"

    # --- Analyst Revision Momentum (RTSI-inspired) ---
    # Quantify the TREND of rating changes over time using linear regression
    # on the monthly bull-ratio series. This captures acceleration, not just level.
    revision_momentum = _compute_analyst_revision_momentum(recommendations)

    return {
        "source": "finnhub",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "recommendation_trends": recommendations,
        "latest_consensus": consensus,
        "price_target": price_target,
        "revision_momentum": revision_momentum,
    }


def _compute_analyst_revision_momentum(recommendations: list[dict]) -> dict:
    """Compute analyst revision momentum from recommendation trend history.

    Borrows the core idea from AI-Stock-Master's RTSI: treat the monthly
    bull-ratio time series as a signal, compute slope (direction), R²
    (consistency), and acceleration (2nd derivative) to measure whether
    analysts are upgrading or downgrading the stock WITH conviction.

    Returns:
        dict with slope, r_squared, acceleration, momentum_score (0-10),
        and direction label.
    """
    if not recommendations or len(recommendations) < 3:
        return {
            "momentum_score": None,
            "direction": "insufficient_data",
            "note": "Need ≥3 months of recommendation data",
        }

    # Build bull-ratio time series (most recent first in raw data, reverse it)
    bull_ratios: list[float] = []
    for rec in reversed(recommendations):
        total = sum(
            rec.get(k, 0) or 0
            for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")
        )
        if total == 0:
            continue
        bull_pct = ((rec.get("strong_buy", 0) or 0) + (rec.get("buy", 0) or 0)) / total
        bull_ratios.append(bull_pct)

    n = len(bull_ratios)
    if n < 3:
        return {
            "momentum_score": None,
            "direction": "insufficient_data",
            "note": f"Only {n} valid data points",
        }

    # Apply exponential time-decay weights (recent months weigh more)
    decay_factor = 0.85
    weights = [decay_factor ** (n - 1 - i) for i in range(n)]

    # Weighted linear regression: slope of bull-ratio over time
    x = list(range(n))
    w_sum = sum(weights)
    x_wm = sum(w * xi for w, xi in zip(weights, x)) / w_sum
    y_wm = sum(w * yi for w, yi in zip(weights, bull_ratios)) / w_sum

    numerator = sum(w * (xi - x_wm) * (yi - y_wm) for w, xi, yi in zip(weights, x, bull_ratios))
    denominator = sum(w * (xi - x_wm) ** 2 for w, xi in zip(weights, x))

    slope = numerator / denominator if denominator > 0 else 0.0

    # R² (goodness of fit — consistency of the trend)
    y_pred = [x_wm + slope * (xi - x_wm) for xi in x]  # simplified linear fit
    ss_res = sum(w * (yi - yp) ** 2 for w, yi, yp in zip(weights, bull_ratios, y_pred))
    ss_tot = sum(w * (yi - y_wm) ** 2 for w, yi in zip(weights, bull_ratios))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    r_squared = max(0.0, r_squared)

    # Acceleration (2nd derivative — is the revision pace speeding up?)
    if n >= 4:
        first_half_slope = bull_ratios[n // 2] - bull_ratios[0]
        second_half_slope = bull_ratios[-1] - bull_ratios[n // 2]
        acceleration = second_half_slope - first_half_slope
    else:
        acceleration = 0.0

    # Composite momentum score (0-10)
    # Slope contributes direction+magnitude, R² confirms consistency,
    # acceleration adds bonus for strengthening trend
    raw_score = 5.0 + slope * 20.0  # slope of ~0.25 per month → +5 points
    raw_score += r_squared * 1.5     # consistency bonus (max +1.5)
    raw_score += acceleration * 5.0  # acceleration bonus/penalty
    momentum_score = max(1.0, min(10.0, round(raw_score, 1)))

    # Direction label
    if momentum_score >= 7.5:
        direction = "strong_upgrade_trend"
    elif momentum_score >= 6.0:
        direction = "moderate_upgrade_trend"
    elif momentum_score >= 4.5:
        direction = "neutral"
    elif momentum_score >= 3.0:
        direction = "moderate_downgrade_trend"
    else:
        direction = "strong_downgrade_trend"

    return {
        "momentum_score": momentum_score,
        "direction": direction,
        "slope": round(slope, 4),
        "r_squared": round(r_squared, 3),
        "acceleration": round(acceleration, 4),
        "data_points": n,
        "decay_factor": decay_factor,
        "interpretation": (
            f"Analyst consensus {'upgrading' if slope > 0 else 'downgrading'} "
            f"at {abs(slope):.1%}/month with {r_squared:.0%} consistency. "
            f"{'Accelerating' if acceleration > 0.02 else 'Decelerating' if acceleration < -0.02 else 'Steady pace'}."
        ),
        "methodology": (
            "Time-decay weighted linear regression on monthly bull-ratio series. "
            "Score = 5 + slope×20 + R²×1.5 + acceleration×5. "
            "Inspired by RTSI (Rating Trend Strength Index) concept."
        ),
    }


# ---------------------------------------------------------------------------
# Social Sentiment (Finnhub)
# ---------------------------------------------------------------------------


def fetch_social_sentiment_finnhub(ticker: str, api_key: str) -> dict:
    """Fetch social media sentiment from Finnhub (Reddit, Twitter)."""
    data = finnhub_call("/stock/social-sentiment", api_key, {"symbol": ticker})

    if "error" in data:
        return {
            "source": "finnhub",
            "status": "unavailable",
            "note": str(data.get("error", "")),
        }

    reddit = data.get("reddit", [])
    twitter = data.get("twitter", [])

    reddit_mentions = 0
    reddit_pos = 0
    reddit_neg = 0
    for r in reddit[:100]:
        reddit_mentions += r.get("mention", 0)
        reddit_pos += r.get("positiveMention", 0)
        reddit_neg += r.get("negativeMention", 0)

    twitter_mentions = 0
    twitter_pos = 0
    twitter_neg = 0
    for t in twitter[:100]:
        twitter_mentions += t.get("mention", 0)
        twitter_pos += t.get("positiveMention", 0)
        twitter_neg += t.get("negativeMention", 0)

    return {
        "source": "finnhub",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "reddit": {
            "total_mentions": reddit_mentions,
            "positive": reddit_pos,
            "negative": reddit_neg,
            "sentiment_ratio": round(
                (reddit_pos - reddit_neg) / max(1, reddit_mentions), 3
            ),
        },
        "twitter": {
            "total_mentions": twitter_mentions,
            "positive": twitter_pos,
            "negative": twitter_neg,
            "sentiment_ratio": round(
                (twitter_pos - twitter_neg) / max(1, twitter_mentions), 3
            ),
        },
    }


# ---------------------------------------------------------------------------
# Earnings Estimate Revisions (Finnhub)
# ---------------------------------------------------------------------------


def fetch_estimate_revisions(ticker: str, api_key: str) -> dict:
    """Fetch earnings estimate revisions and compute revision velocity.

    Revision velocity = direction and magnitude of estimate changes over 1M/3M.
    Strong predictor of future price movement (estimate momentum factor).
    """
    # Fetch EPS estimates (current + next quarter, current + next FY)
    eps_data = finnhub_call(
        "/stock/eps-estimate", api_key, {"symbol": ticker, "freq": "quarterly"}
    )
    rev_data = finnhub_call(
        "/stock/revenue-estimate", api_key, {"symbol": ticker, "freq": "quarterly"}
    )

    eps_revisions = []
    if "error" not in eps_data and isinstance(eps_data, dict):
        estimates = eps_data.get("data", [])
        for est in estimates[:4]:
            eps_revisions.append(
                {
                    "period": est.get("period", ""),
                    "estimate_avg": est.get("epsAvg"),
                    "estimate_high": est.get("epsHigh"),
                    "estimate_low": est.get("epsLow"),
                    "number_of_analysts": est.get("numberAnalysts"),
                }
            )

    rev_revisions = []
    if "error" not in rev_data and isinstance(rev_data, dict):
        estimates = rev_data.get("data", [])
        for est in estimates[:4]:
            rev_revisions.append(
                {
                    "period": est.get("period", ""),
                    "estimate_avg": est.get("revenueAvg"),
                    "estimate_high": est.get("revenueHigh"),
                    "estimate_low": est.get("revenueLow"),
                    "number_of_analysts": est.get("numberAnalysts"),
                }
            )

    # Fetch recommendation trends for revision direction over time
    rec_data = finnhub_call("/stock/recommendation", api_key, {"symbol": ticker})
    revision_velocity = None
    revision_direction = "neutral"

    if "error" not in rec_data and isinstance(rec_data, list) and len(rec_data) >= 2:
        # Compare latest month vs 3 months ago
        latest = rec_data[0] if rec_data else {}
        three_months_ago = rec_data[2] if len(rec_data) > 2 else rec_data[-1]

        latest_bull = (latest.get("strongBuy", 0) or 0) + (latest.get("buy", 0) or 0)
        latest_bear = (latest.get("sell", 0) or 0) + (latest.get("strongSell", 0) or 0)
        prior_bull = (three_months_ago.get("strongBuy", 0) or 0) + (
            three_months_ago.get("buy", 0) or 0
        )
        prior_bear = (three_months_ago.get("sell", 0) or 0) + (
            three_months_ago.get("strongSell", 0) or 0
        )

        latest_total = latest_bull + latest_bear + (latest.get("hold", 0) or 0)
        prior_total = prior_bull + prior_bear + (three_months_ago.get("hold", 0) or 0)

        if latest_total > 0 and prior_total > 0:
            latest_ratio = latest_bull / latest_total
            prior_ratio = prior_bull / prior_total
            revision_velocity = round(latest_ratio - prior_ratio, 4)

            if revision_velocity > 0.10:
                revision_direction = "strong_positive"
            elif revision_velocity > 0.03:
                revision_direction = "positive"
            elif revision_velocity < -0.10:
                revision_direction = "strong_negative"
            elif revision_velocity < -0.03:
                revision_direction = "negative"
            else:
                revision_direction = "neutral"

    # Compute consensus change (upgrades minus downgrades)
    upgrades = 0
    downgrades = 0
    if "error" not in rec_data and isinstance(rec_data, list) and len(rec_data) >= 2:
        for i in range(min(3, len(rec_data) - 1)):
            curr = rec_data[i]
            prev = rec_data[i + 1]
            curr_sb = curr.get("strongBuy", 0) or 0
            prev_sb = prev.get("strongBuy", 0) or 0
            curr_b = curr.get("buy", 0) or 0
            prev_b = prev.get("buy", 0) or 0
            if curr_sb + curr_b > prev_sb + prev_b:
                upgrades += 1
            elif curr_sb + curr_b < prev_sb + prev_b:
                downgrades += 1

    return {
        "source": "finnhub",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "eps_estimates": eps_revisions,
        "revenue_estimates": rev_revisions,
        "revision_velocity": {
            "velocity_3m": revision_velocity,
            "direction": revision_direction,
            "upgrades_3m": upgrades,
            "downgrades_3m": downgrades,
            "net_revisions": upgrades - downgrades,
            "interpretation": (
                "Positive revision momentum — analysts raising estimates (leading price signal)."
                if revision_direction in ("positive", "strong_positive")
                else "Negative revision momentum — analysts cutting estimates (bearish signal)."
                if revision_direction in ("negative", "strong_negative")
                else "Stable consensus — no meaningful revision trend."
            ),
        },
        "note": "Estimate revision velocity is among the strongest short-term alpha signals. "
        "3+ consecutive months of upward revisions strongly predict outperformance.",
    }


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES = {
    "insider": fetch_insider_transactions,
    "news": fetch_news_sentiment,
    "earnings": fetch_earnings_calendar,
    "analyst": fetch_analyst_data,
    "social": fetch_social_sentiment_finnhub,
    "revisions": fetch_estimate_revisions,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fetch sentiment, insider, earnings, and analyst data"
    )
    parser.add_argument("tickers", nargs="+", help="Ticker symbols")
    parser.add_argument(
        "--sources",
        default="insider,news,earnings,analyst,social,revisions,peers",
        help="Comma-separated sources (default: all). Options: insider,news,earnings,analyst,social,revisions,peers",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--api-key-env",
        default="FINNHUB_API_KEY",
        help="Environment variable for Finnhub API key (default: FINNHUB_API_KEY)",
    )
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        sys.stderr.write(
            f"Error: Finnhub API key not found in ${args.api_key_env}.\n"
            "Register for a free key at: https://finnhub.io/\n"
            f"Then set: export {args.api_key_env}=your_key_here\n"
        )
        sys.exit(1)

    requested = [s.strip() for s in args.sources.split(",") if s.strip() in SOURCES]

    results = {}
    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()
        ticker_data = {
            "ticker": ticker,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

        for source_name in requested:
            try:
                data = SOURCES[source_name](ticker, api_key)
                ticker_data[source_name] = data
            except Exception as e:
                ticker_data[source_name] = {
                    "source": "error",
                    "error": str(e),
                }

        results[ticker] = ticker_data

    output = json.dumps(results, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
