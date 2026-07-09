#!/usr/bin/env python3
"""Detect "拉高出货" (pump-and-dump / distribution) patterns.

Identifies stocks where price is rising but smart money is quietly selling.
This is a SELL WARNING signal — flags stocks with distribution characteristics.

Usage:
    uv run python detect_distribution.py AAPL MSFT --lookback 30
    uv run python detect_distribution.py 603738.SS --output dist.json --money-flow-json mf.json

Data sources: yfinance (OHLCV), optional money-flow JSON enrichment.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: 'yfinance' required. Run: pip install yfinance\n")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: 'numpy' required. Run: pip install numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Technical Indicator Computations
# ---------------------------------------------------------------------------


def compute_obv(closes, volumes):
    """On-Balance Volume: cumulative volume * sign(close_change)."""
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def compute_mfi(highs, lows, closes, volumes, period=14):
    """Money Flow Index (0-100)."""
    if len(closes) < period + 1:
        return None
    typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    raw_money_flows = [tp * v for tp, v in zip(typical_prices, volumes)]

    positive_flow = 0.0
    negative_flow = 0.0
    for i in range(len(typical_prices) - period, len(typical_prices)):
        if typical_prices[i] > typical_prices[i - 1]:
            positive_flow += raw_money_flows[i]
        elif typical_prices[i] < typical_prices[i - 1]:
            negative_flow += raw_money_flows[i]

    if negative_flow == 0:
        return 100.0
    money_ratio = positive_flow / negative_flow
    mfi = 100.0 - (100.0 / (1.0 + money_ratio))
    return round(mfi, 2)


def compute_cmf(highs, lows, closes, volumes, period=20):
    """Chaikin Money Flow (-1 to +1)."""
    if len(closes) < period:
        return None
    numerator = 0.0
    denominator = 0.0
    for i in range(len(closes) - period, len(closes)):
        hl_range = highs[i] - lows[i]
        if hl_range == 0:
            clv = 0.0
        else:
            clv = (2 * closes[i] - highs[i] - lows[i]) / hl_range
        numerator += clv * volumes[i]
        denominator += volumes[i]

    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def linear_slope(values):
    """Simple linear regression slope (normalized per unit index)."""
    n = len(values)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    y = np.array(values, dtype=float)
    x_mean = x.mean()
    y_mean = y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return 0.0
    return float(((x - x_mean) * (y - y_mean)).sum() / denom)


# ---------------------------------------------------------------------------
# D1: 量价背离出货 (Volume-Price Divergence Distribution)
# ---------------------------------------------------------------------------


def detect_d1(closes, volumes, obv, lookback):
    """Volume-Price Divergence Distribution.

    Price rising over 5-10 days BUT:
    - OBV is flat or declining (smart money selling into strength)
    - Volume on up-days declining each day (buyers exhausting)
    - Volume on down-days stable or increasing (sellers active)
    """
    result = {"name": "量价背离出货", "score": 0, "detected": False, "detail": ""}

    # Use last 10 days (or lookback if shorter)
    window = min(10, lookback, len(closes) - 1)
    if window < 5:
        return result

    recent_closes = closes[-window:]
    recent_obv = obv[-window:]
    recent_volumes = volumes[-window:]

    # Price return over window
    price_ret = (recent_closes[-1] - recent_closes[0]) / recent_closes[0] * 100
    if price_ret <= 0:
        return result  # No distribution if price not rising

    # OBV slope
    obv_slope = linear_slope(recent_obv)
    obv_normalized_slope = obv_slope / (abs(recent_obv[-1]) + 1e-9)

    # Separate up-day and down-day volumes
    up_day_volumes = []
    down_day_volumes = []
    for i in range(1, len(recent_closes)):
        if recent_closes[i] > recent_closes[i - 1]:
            up_day_volumes.append(recent_volumes[i])
        elif recent_closes[i] < recent_closes[i - 1]:
            down_day_volumes.append(recent_volumes[i])

    # Check if up-day volume declining
    up_vol_declining = False
    if len(up_day_volumes) >= 3:
        up_slope = linear_slope(up_day_volumes)
        up_vol_declining = up_slope < 0

    # Check if down-day volume stable/increasing
    down_vol_increasing = False
    if len(down_day_volumes) >= 2:
        down_slope = linear_slope(down_day_volumes)
        down_vol_increasing = down_slope >= 0

    # Score components
    score = 0.0

    # OBV divergence: price up but OBV flat/down
    if obv_normalized_slope < 0:
        score += min(50, abs(obv_normalized_slope) * 5000)
    elif obv_normalized_slope < 0.001:
        score += 20  # OBV flat while price rising

    # Up-day volume declining
    if up_vol_declining:
        score += 25

    # Down-day volume stable/increasing
    if down_vol_increasing:
        score += 25

    # Scale by price return magnitude (stronger divergence if bigger price move)
    ret_factor = min(2.0, price_ret / 5.0)
    score = min(100, score * ret_factor)

    result["score"] = int(round(score))
    result["detected"] = score >= 30
    if result["detected"]:
        obv_dir = "declining" if obv_normalized_slope < 0 else "flat"
        result["detail"] = f"OBV {obv_dir} while price +{price_ret:.1f}% in {window}D"

    return result


# ---------------------------------------------------------------------------
# D2: 高位放量滞涨 (High Volume Stagnation at Top)
# ---------------------------------------------------------------------------


def detect_d2(opens, highs, lows, closes, volumes, lookback):
    """High Volume Stagnation at Top.

    - Price near 20-day high (within 3%)
    - Recent days have volume > 2x average
    - BUT price barely moved (daily range < 1% OR close ≈ open)
    """
    result = {"name": "高位放量滞涨", "score": 0, "detected": False, "detail": ""}

    window = min(20, len(closes))
    if window < 5:
        return result

    recent_closes = closes[-window:]
    recent_highs = highs[-window:]
    recent_opens = opens[-window:]
    recent_volumes = volumes[-window:]

    high_20d = max(recent_highs)
    current_price = recent_closes[-1]

    # Check if price near high (within 3%)
    if high_20d == 0:
        return result
    pct_from_high = (high_20d - current_price) / high_20d * 100
    if pct_from_high > 3.0:
        return result

    # Average volume
    avg_volume = np.mean(recent_volumes) if len(recent_volumes) > 0 else 1
    if avg_volume == 0:
        return result

    # Check last 2 days for high-volume stagnation
    max_score = 0.0
    best_detail = ""
    for offset in range(1, min(3, len(recent_closes))):
        idx = -offset
        day_vol = recent_volumes[idx]
        vol_ratio = day_vol / avg_volume

        if vol_ratio < 1.5:
            continue

        # Price stagnation: small body or small range
        day_close = recent_closes[idx]
        day_open = recent_opens[idx]
        day_high = recent_highs[idx]
        day_low = lows[-window:][idx] if len(lows) >= window else lows[idx]

        body_pct = abs(day_close - day_open) / (day_close + 1e-9) * 100
        range_pct = (day_high - day_low) / (day_close + 1e-9) * 100

        stagnation = 0.0
        if body_pct < 0.5:
            stagnation = 1.0
        elif body_pct < 1.0:
            stagnation = 0.7
        elif range_pct < 1.5:
            stagnation = 0.5

        if stagnation > 0:
            day_score = min(100, (vol_ratio - 1.0) * 40 * stagnation)
            if day_score > max_score:
                max_score = day_score
                best_detail = (
                    f"Volume {vol_ratio:.1f}x avg, body {body_pct:.2f}% "
                    f"near 20D high"
                )

    result["score"] = int(round(max_score))
    result["detected"] = max_score >= 30
    if result["detected"]:
        result["detail"] = best_detail

    return result


# ---------------------------------------------------------------------------
# D3: 长上影线出货 (Long Upper Shadow Distribution)
# ---------------------------------------------------------------------------


def detect_d3(opens, highs, lows, closes, volumes, lookback):
    """Long Upper Shadow Distribution.

    - Recent day has long upper shadow: (high - close) > 2 * (close - open)
      AND (high - close) > 1.5% of close
    - Combined with above-average volume
    - Price was near recent high when the shadow formed
    """
    result = {"name": "长上影线出货", "score": 0, "detected": False, "detail": ""}

    window = min(20, len(closes))
    if window < 5:
        return result

    recent_closes = closes[-window:]
    recent_highs = highs[-window:]
    recent_opens = opens[-window:]
    recent_lows = lows[-window:]
    recent_volumes = volumes[-window:]

    avg_volume = np.mean(recent_volumes) if len(recent_volumes) > 0 else 1
    high_20d = max(recent_highs)

    # Scan last 5 days for upper shadow signals
    max_score = 0.0
    best_detail = ""

    for offset in range(1, min(6, window)):
        idx = -offset
        c = recent_closes[idx]
        o = recent_opens[idx]
        h = recent_highs[idx]
        vol = recent_volumes[idx]

        if c == 0 or h == 0:
            continue

        # Upper shadow length
        upper_body = max(c, o)
        upper_shadow = h - upper_body
        upper_shadow_pct = upper_shadow / c * 100

        # Body size
        body = abs(c - o)

        # Conditions
        shadow_gt_body = upper_shadow > 2 * body if body > 0 else upper_shadow_pct > 1.5
        shadow_significant = upper_shadow_pct > 1.5
        vol_above_avg = vol > avg_volume

        # Near recent high
        near_high = (high_20d - h) / (high_20d + 1e-9) < 0.03

        if shadow_gt_body and shadow_significant:
            vol_factor = min(2.0, vol / avg_volume) if avg_volume > 0 else 1.0
            shadow_factor = min(3.0, upper_shadow_pct / 1.5)
            near_high_bonus = 1.3 if near_high else 1.0

            day_score = min(100, 30 * shadow_factor * vol_factor * near_high_bonus)

            if day_score > max_score:
                max_score = day_score
                days_ago = offset
                best_detail = f"Upper shadow {upper_shadow_pct:.1f}% {days_ago}D ago"

    result["score"] = int(round(max_score))
    result["detected"] = max_score >= 25
    if result["detected"]:
        result["detail"] = best_detail

    return result


# ---------------------------------------------------------------------------
# D4: 资金净流出 + 价格上涨 (Net Outflow + Price Up)
# ---------------------------------------------------------------------------


def detect_d4(closes, highs, lows, volumes, obv, money_flow_data, lookback):
    """Net Outflow + Price Up.

    Using MFI, CMF, OBV:
    - 5-day return is positive (price going up)
    - BUT MFI < 45 (money flowing out despite price up)
    - AND CMF < 0 (Chaikin money flow negative)
    - AND OBV trend declining over 5 days
    - If money-flow-json available: composite < 4 while price rising
    """
    result = {"name": "资金净流出+价涨", "score": 0, "detected": False, "detail": ""}

    if len(closes) < 6:
        return result

    # 5-day return
    ret_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
    if ret_5d <= 0:
        return result

    # Compute indicators
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    cmf = compute_cmf(highs, lows, closes, volumes, period=20)
    obv_5d = obv[-5:] if len(obv) >= 5 else obv
    obv_slope = linear_slope(obv_5d)
    obv_declining = obv_slope < 0

    # Score components
    score = 0.0
    details = []

    if mfi is not None and mfi < 45:
        mfi_score = (45 - mfi) / 45 * 40  # Max 40 points
        score += mfi_score
        details.append(f"MFI={mfi}")

    if cmf is not None and cmf < 0:
        cmf_score = min(30, abs(cmf) * 200)  # Max 30 points
        score += cmf_score
        details.append(f"CMF={cmf}")

    if obv_declining:
        score += 20
        details.append("OBV declining")

    # Enrichment from money-flow JSON
    if money_flow_data:
        composite = money_flow_data.get("composite_score")
        if composite is not None and composite < 4:
            score += 15
            details.append(f"MF composite={composite}")

    # Scale by price return (bigger divergence = worse)
    ret_factor = min(2.0, ret_5d / 5.0)
    score = min(100, score * ret_factor)

    result["score"] = int(round(score))
    result["detected"] = score >= 30
    if result["detected"]:
        result["detail"] = f"{', '.join(details)}, yet price +{ret_5d:.1f}%"

    return result


# ---------------------------------------------------------------------------
# D5: 缩量新高 (New High on Declining Volume)
# ---------------------------------------------------------------------------


def detect_d5(closes, volumes, lookback):
    """New High on Declining Volume.

    - Price makes new 20-day high
    - BUT volume is below average (< 0.7x 20D avg)
    - No conviction in the breakout, potential false breakout
    - Especially dangerous if followed by volume expansion on down-days
    """
    result = {"name": "缩量新高", "score": 0, "detected": False, "detail": ""}

    window = min(20, len(closes))
    if window < 5:
        return result

    recent_closes = closes[-window:]
    recent_volumes = volumes[-window:]

    current_close = recent_closes[-1]
    high_20d = max(recent_closes[:-1]) if len(recent_closes) > 1 else recent_closes[0]

    # Is current price a new 20-day high?
    if current_close <= high_20d:
        # Check if any of last 3 days was a new high
        new_high_found = False
        new_high_vol = 0
        for offset in range(1, min(4, len(recent_closes))):
            idx = -offset
            prev_high = max(recent_closes[:idx]) if abs(idx) < len(recent_closes) else 0
            if recent_closes[idx] > prev_high and prev_high > 0:
                new_high_found = True
                new_high_vol = recent_volumes[idx]
                break
        if not new_high_found:
            return result
    else:
        new_high_vol = recent_volumes[-1]

    # Average volume
    avg_volume = np.mean(recent_volumes[:-1]) if len(recent_volumes) > 1 else 1
    if avg_volume == 0:
        return result

    vol_ratio = new_high_vol / avg_volume

    # Must be below 0.7x average
    if vol_ratio >= 0.7:
        return result

    # Score: how far below average
    # vol_ratio of 0.5 → strong signal, 0.3 → very strong
    volume_deficit = (0.7 - vol_ratio) / 0.7
    new_high_margin = (
        (current_close - high_20d) / (high_20d + 1e-9) * 100
        if current_close > high_20d
        else 0.5
    )

    score = min(100, volume_deficit * 100 * min(2.0, max(0.5, new_high_margin)))

    # Bonus: check if down-days after have higher volume
    if len(closes) > window + 2:
        post_days = closes[-3:]
        post_vols = volumes[-3:]
        down_vol_expansion = False
        for i in range(1, len(post_days)):
            if post_days[i] < post_days[i - 1] and post_vols[i] > avg_volume:
                down_vol_expansion = True
                break
        if down_vol_expansion:
            score = min(100, score * 1.4)

    result["score"] = int(round(score))
    result["detected"] = score >= 25
    if result["detected"]:
        result["detail"] = f"New high on {vol_ratio:.2f}x avg volume (< 0.7x threshold)"

    return result


# ---------------------------------------------------------------------------
# Composite Score & Verdict
# ---------------------------------------------------------------------------

WEIGHTS = {"D1": 0.30, "D2": 0.25, "D3": 0.15, "D4": 0.20, "D5": 0.10}

VERDICTS = [
    (80, "EXTREME_DISTRIBUTION_RISK", "极高出货风险", "拉高出货确认"),
    (60, "HIGH_DISTRIBUTION_RISK", "高出货风险", "疑似拉高出货"),
    (40, "MODERATE_RISK", "中等风险", "需关注资金动向"),
    (20, "LOW_RISK", "低风险", ""),
    (0, "NO_DISTRIBUTION", "无出货迹象", ""),
]


def compute_verdict(composite_score):
    """Map composite score to verdict."""
    for threshold, code, cn, warning_text in VERDICTS:
        if composite_score >= threshold:
            return code, cn, warning_text
    return "NO_DISTRIBUTION", "无出货迹象", ""


def generate_warning(ticker, ret_5d, signals, verdict_cn):
    """Generate human-readable warning string."""
    if verdict_cn in ("低风险", "无出货迹象"):
        return ""

    active_signals = [s for s in signals.values() if s["detected"]]
    if not active_signals:
        return ""

    top_signal = max(active_signals, key=lambda s: s["score"])
    warning = f"⚠️ {top_signal['detail']}"
    return warning


# ---------------------------------------------------------------------------
# Per-Ticker Analysis
# ---------------------------------------------------------------------------


def analyze_ticker(ticker, lookback, money_flow_data):
    """Run all 5 distribution signals for a single ticker."""
    stock = yf.Ticker(ticker)
    # Fetch extra history to ensure we have enough data
    fetch_period = max(lookback + 30, 60)
    hist = stock.history(period=f"{fetch_period}d", interval="1d")

    if hist.empty or len(hist) < 10:
        return {"error": f"Insufficient price data for {ticker} (got {len(hist)} bars)"}

    closes = hist["Close"].tolist()
    opens = hist["Open"].tolist()
    highs = hist["High"].tolist()
    lows = hist["Low"].tolist()
    volumes = hist["Volume"].tolist()

    # Trim to lookback + buffer for indicators
    indicator_buffer = 25  # Extra days for MFI-14, CMF-20, etc.
    trim_len = min(len(closes), lookback + indicator_buffer)
    closes = closes[-trim_len:]
    opens = opens[-trim_len:]
    highs = highs[-trim_len:]
    lows = lows[-trim_len:]
    volumes = volumes[-trim_len:]

    # Compute shared indicators
    obv = compute_obv(closes, volumes)

    # Run all 5 signals
    d1 = detect_d1(closes, volumes, obv, lookback)
    d2 = detect_d2(opens, highs, lows, closes, volumes, lookback)
    d3 = detect_d3(opens, highs, lows, closes, volumes, lookback)
    d4 = detect_d4(closes, highs, lows, volumes, obv, money_flow_data, lookback)
    d5 = detect_d5(closes, volumes, lookback)

    signals = {"D1": d1, "D2": d2, "D3": d3, "D4": d4, "D5": d5}

    # Composite score
    composite = (
        WEIGHTS["D1"] * d1["score"]
        + WEIGHTS["D2"] * d2["score"]
        + WEIGHTS["D3"] * d3["score"]
        + WEIGHTS["D4"] * d4["score"]
        + WEIGHTS["D5"] * d5["score"]
    )
    composite = int(round(min(100, composite)))

    verdict_code, verdict_cn, _ = compute_verdict(composite)

    # Context metrics
    ret_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    ret_10d = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0

    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    cmf = compute_cmf(highs, lows, closes, volumes, period=20)

    obv_5d = obv[-5:] if len(obv) >= 5 else obv
    obv_trend = "declining" if linear_slope(obv_5d) < 0 else "rising"

    avg_vol_20d = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
    avg_vol_5d = np.mean(volumes[-5:]) if len(volumes) >= 5 else np.mean(volumes)
    vol_ratio = round(avg_vol_5d / avg_vol_20d, 2) if avg_vol_20d > 0 else 0

    recent_highs_20d = highs[-20:] if len(highs) >= 20 else highs
    price_at_high = closes[-1] >= max(recent_highs_20d) * 0.97

    # Upper shadow max in last 5 days
    upper_shadow_max = 0.0
    for i in range(-1, max(-6, -len(closes)), -1):
        upper_body = max(closes[i], opens[i])
        shadow = (highs[i] - upper_body) / (closes[i] + 1e-9) * 100
        upper_shadow_max = max(upper_shadow_max, shadow)

    # Warning message
    warning = generate_warning(ticker, ret_5d, signals, verdict_cn)

    # Recommendation
    if composite >= 80:
        recommendation = "立即减仓/清仓: 多维度确认主力出货，继续持有风险极高"
    elif composite >= 60:
        recommendation = "减仓/离场: 价格虽涨但资金面不支撑，典型主力出货特征"
    elif composite >= 40:
        recommendation = "警惕观望: 部分出货信号出现，建议缩减仓位并设止损"
    elif composite >= 20:
        recommendation = "继续持有: 暂无明显出货迹象，保持关注"
    else:
        recommendation = "安全: 无出货特征，资金面健康"

    return {
        "ticker": ticker,
        "current_price": round(closes[-1], 2),
        "distribution_risk_score": composite,
        "verdict": verdict_code,
        "verdict_cn": verdict_cn,
        "warning": warning,
        "signals": signals,
        "context": {
            "ret_5d_pct": round(ret_5d, 1),
            "ret_10d_pct": round(ret_10d, 1),
            "obv_5d_trend": obv_trend,
            "mfi_14": mfi,
            "cmf_20": cmf,
            "volume_ratio_5d_20d": vol_ratio,
            "upper_shadow_max_pct": round(upper_shadow_max, 1),
            "price_at_high": price_at_high,
        },
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def load_money_flow_json(path):
    """Load money-flow JSON and index by ticker."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        # Support both {ticker: {...}} and {"results": {ticker: {...}}} formats
        if "results" in data and isinstance(data["results"], dict):
            return data["results"]
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, IOError) as e:
        sys.stderr.write(f"Warning: Could not parse money-flow JSON: {e}\n")
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Detect distribution (拉高出货) patterns in stock price action"
    )
    parser.add_argument(
        "tickers", nargs="+", help="Ticker symbols (e.g., AAPL 603738.SS)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--lookback",
        type=int,
        default=30,
        help="Analysis window in trading days (default: 30)",
    )
    parser.add_argument(
        "--money-flow-json",
        help="Optional path to compute_money_flow.py output for enrichment",
    )
    args = parser.parse_args()

    # Load optional money-flow enrichment
    money_flow_index = load_money_flow_json(args.money_flow_json)

    results = {}
    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()
        try:
            mf_data = money_flow_index.get(ticker, None)
            ticker_result = analyze_ticker(ticker, args.lookback, mf_data)
            results[ticker] = ticker_result
        except Exception as e:
            results[ticker] = {
                "ticker": ticker,
                "error": str(e),
                "distribution_risk_score": None,
                "verdict": "ERROR",
                "verdict_cn": "分析失败",
            }

    output_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "lookback_days": args.lookback,
        "results": results,
    }

    class _Encoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            return super().default(obj)

    output = json.dumps(output_payload, indent=2, ensure_ascii=False, cls=_Encoder)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
