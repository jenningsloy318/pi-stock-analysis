#!/usr/bin/env python3
"""Compute comprehensive money flow confirmation score with multi-day consecutive
inflow detection and volume confirmation (量价齐升).

Reads price/volume data via yfinance and produces a deterministic flow score
emphasizing consecutive inflow streaks with rising volume.

Usage:
    compute_money_flow.py AAPL
    compute_money_flow.py AAPL MSFT NVDA --lookback 90 --min-streak 4
    compute_money_flow.py TSLA --output ./reports/money_flow.json

Indicators computed (all manual, no pandas-ta dependency):
    - MFI-14 (Money Flow Index)
    - OBV (On-Balance Volume) with 5D/20D slope
    - CMF-20 (Chaikin Money Flow)
    - Volume ratio (5D/20D SMA)
    - Streak detection (consecutive inflow/outflow days)
    - Volume-Price Symmetry (量价齐升 confirmation)
    - Composite Money Flow Score (0-10)

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
    sys.stderr.write("Error: 'yfinance' required. Run: pip install yfinance\n")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: 'numpy' required. Run: pip install numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _safe_float(val, default=None):
    """Convert value to float, returning default if None/NaN."""
    if val is None:
        return default
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return default
        return round(f, 4)
    except (TypeError, ValueError):
        return default


def _clamp(score: float, lo: float = 0.0, hi: float = 10.0) -> float:
    """Clamp score to [lo, hi] and round to 1 decimal."""
    return round(max(lo, min(hi, score)), 1)


# ---------------------------------------------------------------------------
# Technical indicator computations (manual, no pandas-ta)
# ---------------------------------------------------------------------------


def compute_mfi(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Compute Money Flow Index (MFI) for the given arrays.

    Returns array of same length with NaN for warm-up period.
    """
    n = len(close)
    mfi = np.full(n, np.nan)

    typical_price = (high + low + close) / 3.0
    raw_money_flow = typical_price * volume

    # Determine direction: positive if typical_price rises, negative if falls
    for i in range(period, n):
        pos_flow = 0.0
        neg_flow = 0.0
        for j in range(i - period + 1, i + 1):
            if j == 0:
                continue
            if typical_price[j] > typical_price[j - 1]:
                pos_flow += raw_money_flow[j]
            elif typical_price[j] < typical_price[j - 1]:
                neg_flow += raw_money_flow[j]
            # Equal: neither positive nor negative

        if neg_flow == 0:
            mfi[i] = 100.0
        else:
            money_ratio = pos_flow / neg_flow
            mfi[i] = 100.0 - (100.0 / (1.0 + money_ratio))

    return mfi


def compute_obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Compute On-Balance Volume (OBV)."""
    n = len(close)
    obv = np.zeros(n)
    obv[0] = volume[0]

    for i in range(1, n):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]

    return obv


def compute_cmf(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    period: int = 20,
) -> np.ndarray:
    """Compute Chaikin Money Flow (CMF) over given period.

    CMF = sum((2*close - high - low) / (high - low) * volume, period) / sum(volume, period)
    """
    n = len(close)
    cmf = np.full(n, np.nan)

    # Money Flow Multiplier
    hl_range = high - low
    # Avoid division by zero
    hl_range_safe = np.where(hl_range == 0, 1.0, hl_range)
    mf_multiplier = (2.0 * close - high - low) / hl_range_safe
    mf_volume = mf_multiplier * volume

    for i in range(period - 1, n):
        vol_sum = np.sum(volume[i - period + 1 : i + 1])
        if vol_sum == 0:
            cmf[i] = 0.0
        else:
            cmf[i] = np.sum(mf_volume[i - period + 1 : i + 1]) / vol_sum

    return cmf


def compute_sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    n = len(data)
    sma = np.full(n, np.nan)
    for i in range(period - 1, n):
        sma[i] = np.mean(data[i - period + 1 : i + 1])
    return sma


def compute_slope(data: np.ndarray, period: int) -> float:
    """Compute linear regression slope over the last `period` values.

    Returns slope normalized by mean of data to get a direction signal.
    """
    valid = data[~np.isnan(data)]
    if len(valid) < period:
        return 0.0
    segment = valid[-period:]
    x = np.arange(period, dtype=float)
    # Simple linear regression slope
    x_mean = x.mean()
    y_mean = segment.mean()
    if y_mean == 0:
        return 0.0
    numerator = np.sum((x - x_mean) * (segment - y_mean))
    denominator = np.sum((x - x_mean) ** 2)
    if denominator == 0:
        return 0.0
    slope = numerator / denominator
    # Normalize by mean for comparability
    return slope / abs(y_mean) if y_mean != 0 else 0.0


# ---------------------------------------------------------------------------
# Daily flow signal computation
# ---------------------------------------------------------------------------


def compute_daily_flow_signals(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray
):
    """Compute per-day flow signals.

    Returns dict with arrays: mfi, obv, cmf, volume_ratio, volume_trend,
    daily_flow (list of str), daily_strength (array).
    """
    n = len(close)
    mfi = compute_mfi(high, low, close, volume, 14)
    obv = compute_obv(close, volume)
    cmf = compute_cmf(high, low, close, volume, 20)
    vol_sma_20 = compute_sma(volume, 20)
    vol_sma_5 = compute_sma(volume, 5)

    # Volume ratio: current volume / 20D SMA volume
    volume_ratio = np.full(n, np.nan)
    for i in range(n):
        if (
            vol_sma_20[i] is not None
            and not np.isnan(vol_sma_20[i])
            and vol_sma_20[i] > 0
        ):
            volume_ratio[i] = volume[i] / vol_sma_20[i]

    # Volume trend: 5D vol SMA / 20D vol SMA
    volume_trend = np.full(n, np.nan)
    for i in range(n):
        if (
            not np.isnan(vol_sma_5[i])
            and not np.isnan(vol_sma_20[i])
            and vol_sma_20[i] > 0
        ):
            volume_trend[i] = vol_sma_5[i] / vol_sma_20[i]

    # Daily composite flow signal
    daily_flow = []
    daily_strength = np.full(n, np.nan)

    for i in range(n):
        votes = 0
        valid_votes = 0

        # MFI signal
        if not np.isnan(mfi[i]):
            valid_votes += 1
            if mfi[i] > 50:
                votes += 1

        # OBV direction
        if i > 0:
            valid_votes += 1
            if obv[i] > obv[i - 1]:
                votes += 1

        # CMF signal
        if not np.isnan(cmf[i]):
            valid_votes += 1
            if cmf[i] > 0:
                votes += 1

        if valid_votes == 0:
            daily_flow.append("neutral")
            daily_strength[i] = 0.5
        else:
            ratio = votes / valid_votes
            if ratio >= 0.67:  # 2/3 or more
                daily_flow.append("inflow")
            elif ratio <= 0.33:  # 1/3 or less
                daily_flow.append("outflow")
            else:
                daily_flow.append("neutral")
            daily_strength[i] = ratio

    return {
        "mfi": mfi,
        "obv": obv,
        "cmf": cmf,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,
        "vol_sma_5": vol_sma_5,
        "vol_sma_20": vol_sma_20,
        "daily_flow": daily_flow,
        "daily_strength": daily_strength,
    }


# ---------------------------------------------------------------------------
# Streak detection
# ---------------------------------------------------------------------------


def detect_streaks(daily_flow: list, volume_ratio: np.ndarray, dates: list) -> dict:
    """Detect consecutive inflow/outflow streaks.

    Returns current streak info, max streaks, and streak history.
    """
    n = len(daily_flow)
    if n == 0:
        return {
            "current_streak_type": "neutral",
            "current_streak_days": 0,
            "current_streak_avg_volume_ratio": 1.0,
            "current_streak_volume_trend": "flat",
            "max_inflow_streak": 0,
            "max_outflow_streak": 0,
            "streak_history": [],
        }

    # Build streak segments
    streaks = []
    current_type = (
        daily_flow[0] if daily_flow[0] in ("inflow", "outflow") else "neutral"
    )
    streak_start = 0

    for i in range(1, n):
        flow = daily_flow[i]
        # Neutral days don't break a streak but don't extend it either
        # For simplicity: neutral is treated as its own type
        effective_type = flow if flow in ("inflow", "outflow") else "neutral"

        if effective_type != current_type:
            # Record completed streak (skip neutral streaks for history)
            if current_type in ("inflow", "outflow"):
                streak_vol_ratios = volume_ratio[streak_start:i]
                valid_ratios = streak_vol_ratios[~np.isnan(streak_vol_ratios)]
                avg_vol = float(np.mean(valid_ratios)) if len(valid_ratios) > 0 else 1.0

                # Check if volume was rising during streak
                vol_rising = False
                if len(valid_ratios) >= 2:
                    # Check if latter half > first half
                    mid = len(valid_ratios) // 2
                    if mid > 0:
                        vol_rising = float(np.mean(valid_ratios[mid:])) > float(
                            np.mean(valid_ratios[:mid])
                        )

                streaks.append(
                    {
                        "type": current_type,
                        "days": i - streak_start,
                        "start": str(dates[streak_start])
                        if streak_start < len(dates)
                        else None,
                        "end": str(dates[i - 1]) if (i - 1) < len(dates) else None,
                        "avg_vol_ratio": round(avg_vol, 2),
                        "volume_rising": vol_rising,
                    }
                )

            current_type = effective_type
            streak_start = i

    # Record final streak
    if current_type in ("inflow", "outflow"):
        streak_vol_ratios = volume_ratio[streak_start:n]
        valid_ratios = streak_vol_ratios[~np.isnan(streak_vol_ratios)]
        avg_vol = float(np.mean(valid_ratios)) if len(valid_ratios) > 0 else 1.0
        vol_rising = False
        if len(valid_ratios) >= 2:
            mid = len(valid_ratios) // 2
            if mid > 0:
                vol_rising = float(np.mean(valid_ratios[mid:])) > float(
                    np.mean(valid_ratios[:mid])
                )

        streaks.append(
            {
                "type": current_type,
                "days": n - streak_start,
                "start": str(dates[streak_start])
                if streak_start < len(dates)
                else None,
                "end": str(dates[n - 1]) if (n - 1) < len(dates) else None,
                "avg_vol_ratio": round(avg_vol, 2),
                "volume_rising": vol_rising,
            }
        )

    # Current streak (last entry)
    current_streak = (
        streaks[-1]
        if streaks
        else {
            "type": "neutral",
            "days": 0,
            "avg_vol_ratio": 1.0,
            "volume_rising": False,
        }
    )

    # Max streaks
    max_inflow = max((s["days"] for s in streaks if s["type"] == "inflow"), default=0)
    max_outflow = max((s["days"] for s in streaks if s["type"] == "outflow"), default=0)

    # Volume trend for current streak
    if current_streak["volume_rising"]:
        vol_trend = "rising"
    elif current_streak.get("avg_vol_ratio", 1.0) < 0.9:
        vol_trend = "declining"
    else:
        vol_trend = "flat"

    return {
        "current_streak_type": current_streak["type"],
        "current_streak_days": current_streak["days"],
        "current_streak_avg_volume_ratio": current_streak["avg_vol_ratio"],
        "current_streak_volume_trend": vol_trend,
        "max_inflow_streak_lookback": max_inflow,
        "max_outflow_streak_lookback": max_outflow,
        "streak_history": streaks[-10:],  # Last 10 streaks
    }


# ---------------------------------------------------------------------------
# Volume-Price Symmetry (量价对称)
# ---------------------------------------------------------------------------


def compute_symmetry(streak_info: dict, min_streak: int) -> dict:
    """Compute volume-price symmetry score for current streak."""
    streak_type = streak_info["current_streak_type"]
    streak_days = streak_info["current_streak_days"]
    avg_vol = streak_info["current_streak_avg_volume_ratio"]
    vol_rising = streak_info["current_streak_volume_trend"] == "rising"

    # Symmetry score: streak_days × volume_confirmation × multiplier
    multiplier = 1.2 if vol_rising else 0.8
    symmetry_score = round(streak_days * avg_vol * multiplier, 1)

    # TRUE 量价齐升 check
    volume_price_symmetry = (
        streak_type == "inflow"
        and streak_days >= min_streak
        and avg_vol > 1.0
        and vol_rising
    )

    if volume_price_symmetry:
        interpretation = f"量价齐升确认: 连续{streak_days}日净流入且成交量递增"
    elif streak_type == "inflow" and streak_days >= min_streak:
        if avg_vol <= 1.0:
            interpretation = f"连续{streak_days}日流入但成交量偏低，信号待确认"
        else:
            interpretation = f"连续{streak_days}日流入，量能充足但未递增"
    elif streak_type == "outflow":
        if vol_rising:
            interpretation = f"连续{streak_days}日流出且放量，卖压明显"
        else:
            interpretation = f"连续{streak_days}日流出但缩量，抛压减弱"
    else:
        interpretation = "资金面信号不明确，观望为主"

    return {
        "volume_price_symmetry": volume_price_symmetry,
        "symmetry_score": symmetry_score,
        "interpretation": interpretation,
    }


# ---------------------------------------------------------------------------
# Composite Money Flow Score (0-10)
# ---------------------------------------------------------------------------


def compute_composite_score(streak_info: dict, signals: dict, min_streak: int) -> dict:
    """Compute the 5-component composite money flow score."""
    streak_type = streak_info["current_streak_type"]
    streak_days = streak_info["current_streak_days"]
    vol_trend = streak_info["current_streak_volume_trend"]

    # Get latest valid values
    mfi_arr = signals["mfi"]
    valid_mfi = mfi_arr[~np.isnan(mfi_arr)]
    current_mfi = float(valid_mfi[-1]) if len(valid_mfi) > 0 else 50.0

    vol_trend_arr = signals["volume_trend"]
    valid_vt = vol_trend_arr[~np.isnan(vol_trend_arr)]
    current_vol_ratio = float(valid_vt[-1]) if len(valid_vt) > 0 else 1.0

    obv = signals["obv"]

    # Component 1: Current streak strength (30% weight)
    if streak_type == "inflow":
        if streak_days <= 0:
            streak_score = 0
        elif streak_days <= 3:
            streak_score = streak_days * 2.5  # ramp up: 2.5, 5.0, 7.5
        elif streak_days <= 7:
            streak_score = 10.0  # peak zone
        elif streak_days <= 14:
            streak_score = 10.0 - (streak_days - 7) * 0.5  # gentle decay: 9.5→6.5
        elif streak_days <= 30:
            streak_score = 6.5 - (streak_days - 14) * 0.3  # steeper decay: 6.2→1.7
        else:
            streak_score = max(1.0, 1.7 - (streak_days - 30) * 0.05)  # floor at 1.0
    elif streak_type == "outflow":
        if streak_days >= 3:
            streak_score = 0.0
        else:
            streak_score = 1.0
    else:
        streak_score = 3.0  # neutral

    # Component 2: Volume confirmation (25% weight)
    if current_vol_ratio > 2.0:
        vol_score = 10.0
    elif current_vol_ratio > 1.5:
        vol_score = 8.0
    elif current_vol_ratio > 1.2:
        vol_score = 6.0
    elif current_vol_ratio > 1.0:
        vol_score = 4.0
    elif current_vol_ratio > 0.8:
        vol_score = 2.0
    else:
        vol_score = 0.0

    # Component 3: Flow-Volume symmetry (25% weight)
    if streak_type == "inflow":
        if vol_trend == "rising":
            symmetry_score = 10.0
        elif vol_trend == "flat":
            symmetry_score = 6.0
        else:  # declining
            symmetry_score = 3.0
    elif streak_type == "outflow":
        if vol_trend == "rising":
            symmetry_score = 0.0  # selling pressure
        else:
            symmetry_score = 4.0  # selling exhaustion
    else:
        symmetry_score = 5.0  # neutral

    # Component 4: MFI level (10% weight)
    # MFI > 80 is overbought (distribution risk), 55-70 is healthy inflow zone
    if current_mfi > 80:
        mfi_score = 4.0
    elif current_mfi > 70:
        mfi_score = 6.0
    elif current_mfi > 55:
        mfi_score = 10.0
    elif current_mfi > 40:
        mfi_score = 8.0
    else:
        mfi_score = 5.0

    # Component 5: OBV trend (10% weight)
    obv_slope_5d = compute_slope(obv, 5)
    obv_slope_20d = compute_slope(obv, 20)

    if obv_slope_5d > 0 and obv_slope_20d > 0:
        obv_score = 10.0
    elif obv_slope_5d > 0:
        obv_score = 7.0
    elif abs(obv_slope_5d) < 0.001 and abs(obv_slope_20d) < 0.001:
        obv_score = 5.0
    elif obv_slope_5d < 0 and obv_slope_20d >= 0:
        obv_score = 3.0
    else:
        obv_score = 0.0

    # Weighted composite
    composite = (
        streak_score * 0.30
        + vol_score * 0.25
        + symmetry_score * 0.25
        + mfi_score * 0.10
        + obv_score * 0.10
    )
    composite = _clamp(composite, 0.0, 10.0)

    # Determine OBV trend labels for output
    obv_trend_5d = (
        "rising"
        if obv_slope_5d > 0.001
        else ("falling" if obv_slope_5d < -0.001 else "flat")
    )
    obv_trend_20d = (
        "rising"
        if obv_slope_20d > 0.001
        else ("falling" if obv_slope_20d < -0.001 else "flat")
    )

    components = {
        "streak_strength": {"value": round(streak_score, 1), "weight": 0.30},
        "volume_confirmation": {"value": round(vol_score, 1), "weight": 0.25},
        "flow_volume_symmetry": {"value": round(symmetry_score, 1), "weight": 0.25},
        "mfi_level": {"value": round(mfi_score, 1), "weight": 0.10},
        "obv_trend": {"value": round(obv_score, 1), "weight": 0.10},
    }

    return {
        "composite": composite,
        "components": components,
        "current_mfi": round(current_mfi, 1),
        "obv_trend_5d": obv_trend_5d,
        "obv_trend_20d": obv_trend_20d,
        "current_vol_ratio": round(current_vol_ratio, 2),
        "obv_slope_5d": obv_slope_5d,
        "obv_slope_20d": obv_slope_20d,
    }


# ---------------------------------------------------------------------------
# Verdict and flags
# ---------------------------------------------------------------------------


def determine_verdict(score: float) -> str:
    """Map composite score to verdict string."""
    if score >= 8.0:
        return "STRONG_INFLOW"
    elif score >= 6.0:
        return "MODERATE_INFLOW"
    elif score >= 4.0:
        return "NEUTRAL"
    elif score >= 2.0:
        return "MODERATE_OUTFLOW"
    else:
        return "STRONG_OUTFLOW"


def generate_flags(
    streak_info: dict, score_data: dict, symmetry: dict, min_streak: int
) -> list:
    """Generate signal flags based on analysis results."""
    flags = []

    streak_days = streak_info["current_streak_days"]
    streak_type = streak_info["current_streak_type"]
    vol_ratio = score_data["current_vol_ratio"]
    current_mfi = score_data["current_mfi"]
    obv_slope_5d = score_data["obv_slope_5d"]

    # Consecutive inflow flag
    if streak_type == "inflow" and streak_days >= min_streak:
        flags.append(f"CONSECUTIVE_INFLOW_{streak_days}_DAYS")

    # Volume expanding
    if vol_ratio > 1.2:
        flags.append("VOLUME_EXPANDING")

    # Volume-Price Symmetry (量价齐升)
    if symmetry["volume_price_symmetry"]:
        flags.append("VOLUME_PRICE_SYMMETRY")

    # Divergence warning: price rising but OBV declining (or vice versa)
    if streak_type == "inflow" and obv_slope_5d < -0.001:
        flags.append("DIVERGENCE_WARNING")

    # Selling exhaustion
    if streak_type == "outflow" and vol_ratio < 0.9:
        flags.append("SELLING_EXHAUSTION")

    # Overbought/Oversold flow
    if current_mfi > 80:
        flags.append("OVERBOUGHT_FLOW")
    elif current_mfi < 20:
        flags.append("OVERSOLD_FLOW")

    return flags


def generate_recommendation(
    verdict: str, streak_info: dict, symmetry: dict, flags: list
) -> str:
    """Generate a Chinese-language recommendation summary."""
    streak_days = streak_info["current_streak_days"]
    streak_type = streak_info["current_streak_type"]

    if verdict == "STRONG_INFLOW":
        base = f"资金面强势，连续{streak_days}日量价齐升，机构持续买入信号明确"
    elif verdict == "DISTRIBUTION_RISK":
        base = "高位放量疑似派发，价格远超均线，资金流入或为机构出货"
    elif verdict == "MODERATE_INFLOW":
        base = f"资金面积极，连续{streak_days}日流入"
        if "VOLUME_PRICE_SYMMETRY" in flags:
            base += "，量价齐升确认，关注是否突破前高"
        else:
            base += "，但量能未完全确认，需继续观察"
    elif verdict == "NEUTRAL":
        base = "资金面中性，多空分歧，暂无明确方向"
    elif verdict == "MODERATE_OUTFLOW":
        if "SELLING_EXHAUSTION" in flags:
            base = "资金流出但缩量，抛压减弱，可能接近底部"
        else:
            base = f"资金面偏弱，连续{streak_days}日流出，谨慎观望"
    else:  # STRONG_OUTFLOW
        base = "资金持续放量流出，卖压沉重，建议回避"

    if "DIVERGENCE_WARNING" in flags:
        base += "。注意：量价背离，需警惕假突破"
    if "OVERBOUGHT_FLOW" in flags:
        base += "。注意：MFI超买，短期或有回调"
    if "DISTRIBUTION_WARNING" in flags:
        base += "。警告：价格偏离200日均线>30%且持续流入>20日，需警惕高位派发"

    return base


# ---------------------------------------------------------------------------
# Valuation snapshot
# ---------------------------------------------------------------------------


def fetch_valuation_snapshot(ticker_obj) -> dict:
    """Fetch valuation metrics from yfinance Ticker info."""
    try:
        info = ticker_obj.info
    except Exception:
        info = {}

    return {
        "pb_ratio": _safe_float(info.get("priceToBook")),
        "pe_trailing": _safe_float(info.get("trailingPE")),
        "pe_forward": _safe_float(info.get("forwardPE")),
        "peg_ratio": _safe_float(info.get("pegRatio")),
        "market_cap": _safe_float(info.get("marketCap")),
    }


# ---------------------------------------------------------------------------
# Main per-ticker analysis
# ---------------------------------------------------------------------------


def analyze_ticker(ticker: str, lookback: int, min_streak: int) -> dict:
    """Run full money flow analysis for a single ticker.

    Returns result dict or error dict.
    """
    # Fetch data: lookback + 20 extra days for indicator warm-up
    total_days = lookback + 30  # Extra buffer for warm-up and weekends
    period_str = f"{total_days}d"

    yf_ticker = yf.Ticker(ticker)
    df = yf_ticker.history(period=period_str, interval="1d")

    if df is None or df.empty or len(df) < 30:
        return {
            "error": f"Insufficient data for {ticker}. Got {len(df) if df is not None else 0} rows."
        }

    # Extract arrays
    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    close = df["Close"].values.astype(float)
    volume = df["Volume"].values.astype(float)
    dates = [d.strftime("%Y-%m-%d") for d in df.index]

    # Trim to lookback period after warm-up (keep full data for indicators, slice for analysis)
    # Use all available data for indicator computation, then focus last `lookback` days for streaks
    analysis_start = max(0, len(close) - lookback)

    # Step 2: Compute daily flow indicators (on full data for warm-up)
    signals = compute_daily_flow_signals(high, low, close, volume)

    # Step 3-4: Focus on lookback window for streak detection
    flow_window = signals["daily_flow"][analysis_start:]
    vol_ratio_window = signals["volume_ratio"][analysis_start:]
    dates_window = dates[analysis_start:]

    # Step 4: Streak detection
    streak_info = detect_streaks(flow_window, vol_ratio_window, dates_window)

    # Step 5: Volume-Price Symmetry
    symmetry = compute_symmetry(streak_info, min_streak)

    # Step 6: Composite score
    score_data = compute_composite_score(streak_info, signals, min_streak)

    # Step 7: Verdict and flags
    composite = score_data["composite"]
    verdict = determine_verdict(composite)
    flags = generate_flags(streak_info, score_data, symmetry, min_streak)

    # Step 7.5: Price extension penalty — detect distribution disguised as inflow
    sma_200 = None
    price_extension_pct = 0.0
    if len(close) >= 200:
        sma_200 = float(np.mean(close[-200:]))
    elif len(close) >= 100:
        # Fallback: use available data as proxy
        sma_200 = float(np.mean(close))

    if sma_200 is not None and sma_200 > 0:
        price_extension_pct = (close[-1] - sma_200) / sma_200 * 100

        if price_extension_pct > 50:
            # Severe extension: likely distribution, not accumulation
            composite = composite * 0.6
            score_data["composite"] = composite
            # Recompute verdict from penalized composite
            if composite >= 8.0:
                verdict = "STRONG_INFLOW"
            elif composite >= 6.0:
                verdict = "MODERATE_INFLOW"
            elif composite >= 4.0:
                verdict = "DISTRIBUTION_RISK"
            else:
                verdict = "DISTRIBUTION_RISK"
            flags.append("DISTRIBUTION_RISK")
            # Suppress VOLUME_PRICE_SYMMETRY when severely extended
            if "VOLUME_PRICE_SYMMETRY" in flags:
                flags.remove("VOLUME_PRICE_SYMMETRY")
                symmetry["volume_price_symmetry"] = False
                symmetry["interpretation"] = (
                    f"价格远超200日均线({price_extension_pct:.0f}%)，"
                    "高位放量更可能是派发而非吸筹"
                )
        elif price_extension_pct > 30:
            streak_days = streak_info["current_streak_days"]
            if streak_days > 20:
                flags.append("DISTRIBUTION_WARNING")

    recommendation = generate_recommendation(verdict, streak_info, symmetry, flags)

    # Additional distribution warning: sustained inflow at high composite may be distribution
    if (
        streak_info["current_streak_type"] == "inflow"
        and streak_info["current_streak_days"] > 20
        and composite > 7
    ):
        recommendation += "。注意: 连续流入超20天，高位可能为派发"

    # Current price
    current_price = _safe_float(close[-1])

    # Valuation snapshot
    valuation = fetch_valuation_snapshot(yf_ticker)

    # Get latest CMF
    cmf_arr = signals["cmf"]
    valid_cmf = cmf_arr[~np.isnan(cmf_arr)]
    current_cmf = round(float(valid_cmf[-1]), 4) if len(valid_cmf) > 0 else None

    # Volume trend direction
    vol_trend_val = score_data["current_vol_ratio"]
    if vol_trend_val > 1.2:
        vol_trend_dir = "expanding"
    elif vol_trend_val < 0.8:
        vol_trend_dir = "contracting"
    else:
        vol_trend_dir = "stable"

    return {
        "current_price": current_price,
        "valuation_snapshot": valuation,
        "flow_indicators": {
            "mfi_14": round(score_data["current_mfi"], 1),
            "obv_trend_5d": score_data["obv_trend_5d"],
            "obv_trend_20d": score_data["obv_trend_20d"],
            "cmf_20": current_cmf,
            "volume_ratio_5d_vs_20d": score_data["current_vol_ratio"],
            "volume_trend_direction": vol_trend_dir,
        },
        "streak_analysis": streak_info,
        "symmetry": symmetry,
        "composite_score": composite,
        "verdict": verdict,
        "flags": flags,
        "recommendation": recommendation,
        "components": score_data["components"],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compute money flow confirmation score with volume-price "
        "symmetry detection (量价齐升)"
    )
    parser.add_argument(
        "tickers", nargs="+", help="Ticker symbols (e.g., AAPL MSFT NVDA)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--lookback",
        type=int,
        default=60,
        help="Days of history to analyze (default: 60)",
    )
    parser.add_argument(
        "--min-streak",
        type=int,
        default=3,
        help="Minimum consecutive inflow days to flag as significant (default: 3)",
    )
    args = parser.parse_args()

    results = {}
    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()
        try:
            results[ticker] = analyze_ticker(ticker, args.lookback, args.min_streak)
        except Exception as e:
            results[ticker] = {"error": str(e)}

    output_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "lookback_days": args.lookback,
        "min_streak_threshold": args.min_streak,
        "results": results,
    }

    output = json.dumps(output_payload, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
