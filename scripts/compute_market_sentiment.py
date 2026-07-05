#!/usr/bin/env python3
"""Compute a single 0-100 market sentiment score (市场情绪).

Aggregates VIX level, market trend, breadth, risk appetite, credit stress,
and momentum breadth into one composite dashboard number.

Usage:
    compute_market_sentiment.py [--market us|cn|all] [--output PATH] [--breadth-json PATH]

Output: JSON to stdout or --output file.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    sys.stderr.write("Error: yfinance required. Run: pip install yfinance\n")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: numpy required. Run: pip install numpy\n")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    sys.stderr.write("Error: pandas required. Run: pip install pandas\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

US_TICKERS = [
    "SPY",
    "^VIX",
    "QQQ",
    "IWM",
    "HYG",
    "TLT",
    "XLK",
    "XLF",
    "XLI",
    "XLY",
    "XLC",
    "XLV",
    "XLP",
    "XLE",
    "XLU",
    "XLB",
    "XLRE",
]

CN_TICKERS = [
    "000001.SS",  # Shanghai Composite
    "399006.SZ",  # ChiNext
    "510050.SS",  # SSE 50 ETF proxy
    "510300.SS",  # CSI 300 ETF proxy
    "510500.SS",  # CSI 500 ETF proxy
]

SECTOR_ETFS = [
    "XLK",
    "XLF",
    "XLI",
    "XLY",
    "XLC",
    "XLV",
    "XLP",
    "XLE",
    "XLU",
    "XLB",
    "XLRE",
]

WEIGHTS = {
    "vix_level": 0.20,
    "market_trend": 0.25,
    "breadth": 0.20,
    "risk_appetite": 0.15,
    "credit_stress": 0.10,
    "momentum_breadth": 0.10,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def _pct_return(series: pd.Series, days: int) -> float | None:
    """Compute percentage return over last N trading days."""
    if series is None or len(series) < days + 1:
        return None
    current = series.iloc[-1]
    prior = series.iloc[-(days + 1)]
    if prior == 0 or pd.isna(prior) or pd.isna(current):
        return None
    return ((current - prior) / prior) * 100.0


def _fetch_data(tickers: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    """Batch download historical data via yfinance."""
    sys.stderr.write(f"Fetching data for {len(tickers)} tickers...\n")
    try:
        data = yf.download(
            tickers, period=period, progress=False, group_by="ticker", threads=True
        )
        result = {}
        if len(tickers) == 1:
            ticker = tickers[0]
            if not data.empty:
                result[ticker] = data
        else:
            for ticker in tickers:
                try:
                    df = data[ticker].dropna(how="all")
                    if not df.empty:
                        result[ticker] = df
                except (KeyError, TypeError):
                    pass
        return result
    except Exception as e:
        sys.stderr.write(f"Warning: batch download failed: {e}\n")
        return {}


def _get_close(data: dict[str, pd.DataFrame], ticker: str) -> pd.Series | None:
    """Extract Close price series for a ticker."""
    if ticker not in data:
        return None
    df = data[ticker]
    if "Close" in df.columns:
        series = df["Close"].dropna()
        # Handle multi-level columns from yfinance
        if isinstance(series, pd.DataFrame):
            series = series.iloc[:, 0]
        return series if not series.empty else None
    return None


def _sentiment_label(score: float) -> tuple[str, str]:
    """Return (label, emoji) for sentiment score."""
    if score >= 80:
        return "极度贪婪", "🔥"
    elif score >= 65:
        return "活跃", "📈"
    elif score >= 50:
        return "中性", "➡️"
    elif score >= 35:
        return "谨慎", "⚠️"
    elif score >= 20:
        return "恐惧", "📉"
    else:
        return "极度恐惧", "💀"


# ---------------------------------------------------------------------------
# Scoring Components (US Market)
# ---------------------------------------------------------------------------


def _score_vix(data: dict[str, pd.DataFrame]) -> dict:
    """Score VIX level (20% weight)."""
    vix_series = _get_close(data, "^VIX")
    if vix_series is None or vix_series.empty:
        return {
            "score": 50,
            "weight": WEIGHTS["vix_level"],
            "raw_value": None,
            "detail": "VIX data unavailable",
        }

    vix = float(vix_series.iloc[-1])

    if vix < 12:
        score = 90
    elif vix < 15:
        score = 80
    elif vix < 20:
        score = 65
    elif vix < 25:
        score = 45
    elif vix < 30:
        score = 30
    elif vix < 35:
        score = 15
    else:
        score = 5

    detail = f"VIX {vix:.1f}"
    if vix < 15:
        detail += " — low volatility/bullish calm"
    elif vix < 20:
        detail += " — neutral range"
    elif vix < 25:
        detail += " — elevated concern"
    elif vix < 30:
        detail += " — fear zone"
    else:
        detail += " — high fear/panic"

    return {
        "score": score,
        "weight": WEIGHTS["vix_level"],
        "raw_value": round(vix, 2),
        "detail": detail,
    }


def _score_market_trend(data: dict[str, pd.DataFrame]) -> dict:
    """Score SPY trend relative to moving averages (25% weight)."""
    spy_close = _get_close(data, "SPY")
    if spy_close is None or len(spy_close) < 200:
        return {
            "score": 50,
            "weight": WEIGHTS["market_trend"],
            "raw_value": None,
            "detail": "SPY data insufficient",
        }

    current_price = float(spy_close.iloc[-1])
    sma20 = float(_sma(spy_close, 20).iloc[-1])
    sma50 = float(_sma(spy_close, 50).iloc[-1])
    sma200 = float(_sma(spy_close, 200).iloc[-1])

    above_20 = current_price > sma20
    above_50 = current_price > sma50
    above_200 = current_price > sma200

    if above_20 and above_50 and above_200:
        score = 90.0
        position = "above_20_50_200"
    elif above_50 and above_200 and not above_20:
        score = 70.0
        position = "above_50_200"
    elif above_200 and not above_50:
        score = 50.0
        position = "above_200_only"
    elif not above_200 and above_50:
        score = 35.0
        position = "above_50_below_200"
    else:
        score = 15.0
        position = "below_all"

    # 5-day momentum adjustment
    ret_5d = _pct_return(spy_close, 5)
    momentum_adj = 0.0
    if ret_5d is not None:
        momentum_adj = _clamp(ret_5d * 5, -10, 10)  # Scale: ±2% → ±10
    score = _clamp(score + momentum_adj)

    detail_parts = [f"SPY {position.replace('_', ' ')}"]
    if ret_5d is not None:
        detail_parts.append(f"5D return {ret_5d:+.1f}%")

    return {
        "score": round(score),
        "weight": WEIGHTS["market_trend"],
        "raw_value": position,
        "detail": ", ".join(detail_parts),
    }


def _score_breadth(data: dict[str, pd.DataFrame]) -> dict:
    """Score market breadth: sectors above 20-SMA (20% weight)."""
    count_above = 0
    total = 0

    for etf in SECTOR_ETFS:
        close = _get_close(data, etf)
        if close is None or len(close) < 20:
            continue
        total += 1
        sma20_val = float(_sma(close, 20).iloc[-1])
        current = float(close.iloc[-1])
        if current > sma20_val:
            count_above += 1

    if total == 0:
        return {
            "score": 50,
            "weight": WEIGHTS["breadth"],
            "raw_value": None,
            "detail": "Sector data unavailable",
        }

    ratio = count_above / total
    if count_above >= 9:
        score = 90
    elif count_above >= 7:
        score = 70
    elif count_above >= 5:
        score = 50
    elif count_above >= 3:
        score = 30
    else:
        score = 10

    return {
        "score": score,
        "weight": WEIGHTS["breadth"],
        "raw_value": f"{count_above}/{total}",
        "detail": f"{count_above} of {total} sectors above 20-SMA",
    }


def _score_risk_appetite(data: dict[str, pd.DataFrame]) -> dict:
    """Score risk appetite via growth-vs-defensive pairs (15% weight)."""
    pairs = [
        ("QQQ", "XLU", "QQQ_vs_XLU"),
        ("IWM", "SPY", "IWM_vs_SPY"),
        ("HYG", "TLT", "HYG_vs_TLT"),
    ]

    pair_scores = []
    pair_details = {}
    for risk_ticker, safe_ticker, label in pairs:
        risk_ret = _pct_return(_get_close(data, risk_ticker), 5)
        safe_ret = _pct_return(_get_close(data, safe_ticker), 5)
        if risk_ret is None or safe_ret is None:
            pair_scores.append(15.0)  # neutral-ish fallback
            pair_details[label] = None
            continue

        diff = risk_ret - safe_ret
        pair_details[label] = round(diff, 2)
        # Map diff to 0-30 score per pair
        # diff > +2% → 30 (strong risk-on), diff < -2% → 0 (strong risk-off)
        pair_score = _clamp((diff + 2) / 4 * 30, 0, 30)
        pair_scores.append(pair_score)

    score = _clamp(sum(pair_scores), 0, 100)

    # Build detail string
    detail_parts = []
    for risk_ticker, safe_ticker, label in pairs:
        val = pair_details.get(label)
        if val is not None:
            direction = ">" if val > 0 else "<"
            detail_parts.append(f"{risk_ticker}{direction}{safe_ticker}")

    raw = "mixed"
    if all(v is not None and v > 0 for v in pair_details.values()):
        raw = "risk-on"
    elif all(v is not None and v < 0 for v in pair_details.values()):
        raw = "risk-off"

    return {
        "score": round(score),
        "weight": WEIGHTS["risk_appetite"],
        "raw_value": raw,
        "detail": ", ".join(detail_parts) if detail_parts else "insufficient data",
    }


def _score_credit_stress(data: dict[str, pd.DataFrame]) -> dict:
    """Score credit stress via HYG/TLT ratio trend (10% weight)."""
    hyg_close = _get_close(data, "HYG")
    tlt_close = _get_close(data, "TLT")

    if (
        hyg_close is None
        or tlt_close is None
        or len(hyg_close) < 6
        or len(tlt_close) < 6
    ):
        return {
            "score": 50,
            "weight": WEIGHTS["credit_stress"],
            "raw_value": None,
            "detail": "Credit data unavailable",
        }

    # Align series by index
    combined = pd.DataFrame({"HYG": hyg_close, "TLT": tlt_close}).dropna()
    if len(combined) < 6:
        return {
            "score": 50,
            "weight": WEIGHTS["credit_stress"],
            "raw_value": None,
            "detail": "Insufficient aligned data",
        }

    ratio = combined["HYG"] / combined["TLT"]
    ratio_current = float(ratio.iloc[-1])
    ratio_5d_ago = float(ratio.iloc[-6]) if len(ratio) >= 6 else float(ratio.iloc[0])

    change_pct = ((ratio_current - ratio_5d_ago) / ratio_5d_ago) * 100

    if change_pct > 0.3:
        score = 80
        raw = "improving"
    elif change_pct > -0.3:
        score = 50
        raw = "stable"
    else:
        score = 20
        raw = "stress"

    return {
        "score": score,
        "weight": WEIGHTS["credit_stress"],
        "raw_value": raw,
        "detail": f"HYG/TLT ratio 5D change {change_pct:+.2f}%",
    }


def _score_momentum_breadth(data: dict[str, pd.DataFrame]) -> dict:
    """Score momentum breadth: sectors with positive 5D returns (10% weight)."""
    count_positive = 0
    total = 0

    for etf in SECTOR_ETFS:
        close = _get_close(data, etf)
        if close is None or len(close) < 6:
            continue
        total += 1
        ret = _pct_return(close, 5)
        if ret is not None and ret > 0:
            count_positive += 1

    if total == 0:
        return {
            "score": 50,
            "weight": WEIGHTS["momentum_breadth"],
            "raw_value": None,
            "detail": "Sector data unavailable",
        }

    if count_positive >= 9:
        score = 90
    elif count_positive >= 7:
        score = 70
    elif count_positive >= 5:
        score = 50
    elif count_positive >= 3:
        score = 30
    else:
        score = 10

    return {
        "score": score,
        "weight": WEIGHTS["momentum_breadth"],
        "raw_value": f"{count_positive}/{total}",
        "detail": f"{count_positive} of {total} sectors positive 5D",
    }


# ---------------------------------------------------------------------------
# Composite Scoring
# ---------------------------------------------------------------------------


def _compute_us_sentiment(data: dict[str, pd.DataFrame]) -> dict:
    """Compute US market sentiment composite."""
    components = {
        "vix_level": _score_vix(data),
        "market_trend": _score_market_trend(data),
        "breadth": _score_breadth(data),
        "risk_appetite": _score_risk_appetite(data),
        "credit_stress": _score_credit_stress(data),
        "momentum_breadth": _score_momentum_breadth(data),
    }

    # Weighted composite
    composite = 0.0
    for key, comp in components.items():
        composite += comp["score"] * comp["weight"]
    composite = round(_clamp(composite))

    label, emoji = _sentiment_label(composite)

    # Market context
    spy_close = _get_close(data, "SPY")
    spy_price = (
        round(float(spy_close.iloc[-1]), 2)
        if spy_close is not None and not spy_close.empty
        else None
    )
    spy_5d = round(_pct_return(spy_close, 5), 2) if spy_close is not None else None

    vix_series = _get_close(data, "^VIX")
    vix_val = (
        round(float(vix_series.iloc[-1]), 2)
        if vix_series is not None and not vix_series.empty
        else None
    )

    # Risk-on pair diffs
    risk_on_pairs = {}
    for risk_t, safe_t, label_key in [
        ("QQQ", "XLU", "QQQ_vs_XLU"),
        ("IWM", "SPY", "IWM_vs_SPY"),
        ("HYG", "TLT", "HYG_vs_TLT"),
    ]:
        r_ret = _pct_return(_get_close(data, risk_t), 5)
        s_ret = _pct_return(_get_close(data, safe_t), 5)
        if r_ret is not None and s_ret is not None:
            risk_on_pairs[label_key] = round(r_ret - s_ret, 2)
        else:
            risk_on_pairs[label_key] = None

    # Generate signal text
    signal_parts = []
    if composite >= 65:
        signal_parts.append("市场情绪偏多")
    elif composite >= 50:
        signal_parts.append("市场情绪中性")
    elif composite >= 35:
        signal_parts.append("市场情绪谨慎")
    else:
        signal_parts.append("市场情绪偏空")

    if vix_val is not None:
        if vix_val < 15:
            signal_parts.append("VIX低位")
        elif vix_val < 20:
            signal_parts.append("VIX温和")
        else:
            signal_parts.append("VIX偏高")

    breadth_raw = components["breadth"]["raw_value"]
    if breadth_raw and "/" in str(breadth_raw):
        above, total_s = str(breadth_raw).split("/")
        if int(above) >= 8:
            signal_parts.append("多数板块维持上升趋势")
        elif int(above) >= 5:
            signal_parts.append("板块分化")
        else:
            signal_parts.append("多数板块走弱")

    risk_raw = components["risk_appetite"]["raw_value"]
    if risk_raw == "risk-off":
        signal_parts.append("资金偏向防御")
    elif risk_raw == "risk-on":
        signal_parts.append("资金偏向进攻")
    else:
        signal_parts.append("风险偏好混合")

    signal = "，".join(signal_parts)

    return {
        "market": "us",
        "sentiment_score": composite,
        "sentiment_label": label,
        "sentiment_emoji": emoji,
        "components": components,
        "market_context": {
            "spy_price": spy_price,
            "spy_5d_pct": spy_5d,
            "vix": vix_val,
            "advance_decline_ratio": components["breadth"]["raw_value"],
            "risk_on_pairs": risk_on_pairs,
        },
        "signal": signal,
        "comparison_to_prior": None,
    }


def _compute_cn_sentiment(data: dict[str, pd.DataFrame]) -> dict | None:
    """Compute China A-share market sentiment (simplified)."""
    shcomp = _get_close(data, "000001.SS")
    if shcomp is None or len(shcomp) < 20:
        return {
            "market": "cn",
            "sentiment_score": None,
            "sentiment_label": None,
            "sentiment_emoji": None,
            "components": {},
            "market_context": {},
            "signal": "中国A股数据不可用 (China A-share data unavailable via yfinance)",
            "comparison_to_prior": None,
            "error": "Insufficient data for China market. Consider using akshare for A-share data.",
        }

    current = float(shcomp.iloc[-1])
    sma20 = float(_sma(shcomp, 20).iloc[-1]) if len(shcomp) >= 20 else current
    sma50 = float(_sma(shcomp, 50).iloc[-1]) if len(shcomp) >= 50 else current
    sma200 = float(_sma(shcomp, 200).iloc[-1]) if len(shcomp) >= 200 else current

    # Simplified trend score
    above_20 = current > sma20
    above_50 = current > sma50
    above_200 = current > sma200

    if above_20 and above_50 and above_200:
        trend_score = 85
    elif above_50 and above_200:
        trend_score = 65
    elif above_200:
        trend_score = 45
    else:
        trend_score = 20

    # 5D momentum
    ret_5d = _pct_return(shcomp, 5)
    momentum_adj = 0.0
    if ret_5d is not None:
        momentum_adj = _clamp(ret_5d * 5, -15, 15)

    composite = round(_clamp(trend_score + momentum_adj))
    label, emoji = _sentiment_label(composite)

    return {
        "market": "cn",
        "sentiment_score": composite,
        "sentiment_label": label,
        "sentiment_emoji": emoji,
        "components": {
            "market_trend": {
                "score": trend_score,
                "weight": 1.0,
                "raw_value": f"above_{'20+' if above_20 else ''}{'50+' if above_50 else ''}{'200' if above_200 else 'none'}",
                "detail": f"Shanghai Composite trend, 5D return {ret_5d:+.1f}%"
                if ret_5d
                else "Shanghai Composite trend",
            },
        },
        "market_context": {
            "shcomp_price": round(current, 2),
            "shcomp_5d_pct": round(ret_5d, 2) if ret_5d else None,
        },
        "signal": f"上证综指{'偏强' if composite >= 60 else '偏弱' if composite < 40 else '震荡'}，仅基于趋势判断（缺少完整A股情绪数据）",
        "comparison_to_prior": None,
        "note": "A-share sentiment is simplified — full analysis requires akshare/baostock for breadth, margin, and northbound flow data.",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compute market sentiment score (0-100) with component breakdown"
    )
    parser.add_argument(
        "--market",
        choices=["us", "cn", "all"],
        default="us",
        help="Market to score (default: us)",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--breadth-json",
        help="Path to pre-computed fetch_market_breadth.py output (optional, avoids re-fetching)",
    )
    args = parser.parse_args()

    # Determine tickers to fetch
    tickers_needed = []
    if args.market in ("us", "all"):
        tickers_needed.extend(US_TICKERS)
    if args.market in ("cn", "all"):
        tickers_needed.extend(CN_TICKERS)

    # Deduplicate while preserving order
    seen = set()
    unique_tickers = []
    for t in tickers_needed:
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    # Fetch all data in one batch
    data = _fetch_data(unique_tickers, period="6mo")

    if not data:
        sys.stderr.write("Error: no market data could be fetched\n")
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Failed to fetch market data",
            "market": args.market,
            "sentiment_score": None,
        }
        output = json.dumps(result, indent=2, default=str)
        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)
        sys.exit(1)

    # Compute sentiment per market
    results = {}
    if args.market in ("us", "all"):
        results["us"] = _compute_us_sentiment(data)
    if args.market in ("cn", "all"):
        results["cn"] = _compute_cn_sentiment(data)

    # Build final output
    if args.market == "all":
        output_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance",
            "markets": results,
        }
    else:
        market_result = results.get(args.market, {})
        output_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance",
            **market_result,
        }

    output = json.dumps(output_data, indent=2, default=str, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        sys.stderr.write(f"Output written to {args.output}\n")
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
