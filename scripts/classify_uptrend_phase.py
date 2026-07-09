#!/usr/bin/env python3
"""Classify the current uptrend phase for stock tickers.

Phases (inspired by A-share screening reports):
  ACCELERATING  加速上涨  — momentum increasing, rate of gain accelerating
  STEADY        匀速上涨  — healthy consistent uptrend
  OSCILLATING   波动阶段  — net positive but choppy/volatile
  BOTTOMING     底部区域  — near lows, base forming or early recovery
  DECLINING     下跌阶段  — clear downtrend

Usage:
  uv run python classify_uptrend_phase.py AAPL MSFT 603738.SS --lookback 60
  uv run python classify_uptrend_phase.py TSLA --output /tmp/phase.json
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
# Phase definitions
# ---------------------------------------------------------------------------

PHASES = [
    {"id": "ACCELERATING", "name": "加速上涨", "name_en": "Accelerating Uptrend"},
    {"id": "STEADY", "name": "匀速上涨", "name_en": "Steady Uptrend"},
    {"id": "OSCILLATING", "name": "波动阶段", "name_en": "Oscillating"},
    {"id": "BOTTOMING", "name": "底部区域", "name_en": "Bottoming"},
    {"id": "DECLINING", "name": "下跌阶段", "name_en": "Declining"},
]

PHASE_PRIORITY = ["ACCELERATING", "STEADY", "OSCILLATING", "BOTTOMING", "DECLINING"]


# ---------------------------------------------------------------------------
# Technical indicator helpers (manual computation, no external TA library)
# ---------------------------------------------------------------------------


def _sma(closes: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    if len(closes) < period:
        return np.full(len(closes), np.nan)
    out = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        out[i] = np.mean(closes[i - period + 1 : i + 1])
    return out


def _rsi(closes: np.ndarray, period: int = 14) -> float | None:
    """RSI-14 (Wilder smoothing) — returns the latest value."""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Wilder EMA seed
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> float | None:
    """ADX-14 — returns the latest value."""
    n = len(closes)
    if n < period * 2 + 1:
        return None
    # True Range
    tr = np.zeros(n - 1)
    plus_dm = np.zeros(n - 1)
    minus_dm = np.zeros(n - 1)
    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        tr[i - 1] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        plus_dm[i - 1] = h_diff if (h_diff > l_diff and h_diff > 0) else 0.0
        minus_dm[i - 1] = l_diff if (l_diff > h_diff and l_diff > 0) else 0.0
    # Wilder smooth
    atr = np.mean(tr[:period])
    apdm = np.mean(plus_dm[:period])
    amdm = np.mean(minus_dm[:period])
    dx_values = []
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
        apdm = (apdm * (period - 1) + plus_dm[i]) / period
        amdm = (amdm * (period - 1) + minus_dm[i]) / period
        if atr == 0:
            continue
        plus_di = 100.0 * apdm / atr
        minus_di = 100.0 * amdm / atr
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(100.0 * abs(plus_di - minus_di) / di_sum)
    if len(dx_values) < period:
        return None
    adx_val = np.mean(dx_values[:period])
    for i in range(period, len(dx_values)):
        adx_val = (adx_val * (period - 1) + dx_values[i]) / period
    return float(adx_val)


def _bollinger_position(
    closes: np.ndarray, period: int = 20, num_std: float = 2.0
) -> float | None:
    """Position within Bollinger Bands: (close - lower) / (upper - lower). Range ~0-1."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = np.mean(window)
    std = np.std(window, ddof=1)
    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = upper - lower
    if band_width == 0:
        return 0.5
    return float((closes[-1] - lower) / band_width)


def _direction_changes(closes: np.ndarray, days: int = 10) -> int:
    """Count sign changes in daily returns over the last N days."""
    if len(closes) < days + 1:
        return 0
    rets = np.diff(closes[-(days + 1) :])
    changes = 0
    for i in range(1, len(rets)):
        if rets[i] * rets[i - 1] < 0:
            changes += 1
    return changes


def _higher_highs_lows(highs: np.ndarray, lows: np.ndarray, window: int = 20) -> bool:
    """Check if recent window shows higher highs and higher lows pattern."""
    if len(highs) < window:
        return False
    h = highs[-window:]
    l = lows[-window:]
    mid = window // 2
    first_half_high = np.max(h[:mid])
    second_half_high = np.max(h[mid:])
    first_half_low = np.min(l[:mid])
    second_half_low = np.min(l[mid:])
    return second_half_high > first_half_high and second_half_low > first_half_low


def _lower_highs_lows(highs: np.ndarray, lows: np.ndarray, window: int = 20) -> bool:
    """Check if recent window shows lower highs and lower lows."""
    if len(highs) < window:
        return False
    h = highs[-window:]
    l = lows[-window:]
    mid = window // 2
    first_half_high = np.max(h[:mid])
    second_half_high = np.max(h[mid:])
    first_half_low = np.min(l[:mid])
    second_half_low = np.min(l[mid:])
    return second_half_high < first_half_high and second_half_low < first_half_low


def _sma_slope(sma_arr: np.ndarray, window: int = 5) -> float:
    """Average slope of SMA over last N points (normalized by price level)."""
    valid = sma_arr[~np.isnan(sma_arr)]
    if len(valid) < window:
        return 0.0
    segment = valid[-window:]
    if segment[0] == 0:
        return 0.0
    return float((segment[-1] - segment[0]) / segment[0] * 100)


# ---------------------------------------------------------------------------
# Phase scoring functions
# ---------------------------------------------------------------------------


def _score_accelerating(ctx: dict) -> int:
    """Score ACCELERATING phase (0-100)."""
    score = 0
    total_weight = 0

    # 5D return > 10% AND 10D > 5D * 1.5 (acceleration) — weight 20
    total_weight += 20
    if ctx["ret_5d"] > 10 and ctx["ret_10d"] > ctx["ret_5d"] * 1.5:
        score += 20
    elif ctx["ret_5d"] > 7:
        score += 10

    # Perfect MA alignment: price > 5 > 10 > 20 > 50 — weight 20
    total_weight += 20
    price = ctx["close"]
    smas = [ctx["sma_5"], ctx["sma_10"], ctx["sma_20"], ctx["sma_50"]]
    if all(s is not None for s in smas):
        if price > smas[0] > smas[1] > smas[2] > smas[3]:
            score += 20
        elif price > smas[0] > smas[1] > smas[2]:
            score += 12

    # RSI > 60 but < 85 — weight 10 (penalize extreme overbought in acceleration)
    total_weight += 10
    if ctx["rsi"] is not None:
        if 60 <= ctx["rsi"] <= 75:
            score += 10
        elif 75 < ctx["rsi"] <= 85:
            score += 5
        elif ctx["rsi"] > 85:
            score += 2
        elif 55 < ctx["rsi"] < 60:
            score += 5

    # 5D return acceleration: recent 5D > prior 5D — weight 15
    total_weight += 15
    if ctx["ret_5d"] > ctx["ret_5d_prior"]:
        score += 15
    elif ctx["ret_5d"] > ctx["ret_5d_prior"] * 0.8:
        score += 7

    # Volume expanding: 5D avg > 20D avg * 1.2 — weight 10
    total_weight += 10
    if ctx["vol_ratio"] > 1.2:
        score += 10
    elif ctx["vol_ratio"] > 1.0:
        score += 5

    # ADX > 25 (trending) — weight 10
    total_weight += 10
    if ctx["adx"] is not None:
        if ctx["adx"] > 25:
            score += 10
        elif ctx["adx"] > 20:
            score += 5

    # Close near or above upper Bollinger Band — weight 10
    total_weight += 10
    if ctx["boll_pos"] is not None:
        if ctx["boll_pos"] > 0.9:
            score += 10
        elif ctx["boll_pos"] > 0.8:
            score += 7

    # Last 5 days mostly green — weight 5
    total_weight += 5
    if ctx["green_days_5"] >= 4:
        score += 5
    elif ctx["green_days_5"] >= 3:
        score += 3

    return int(score / total_weight * 100) if total_weight > 0 else 0


def _score_steady(ctx: dict) -> int:
    """Score STEADY phase (0-100)."""
    score = 0
    total_weight = 0

    # 20D return > 5% — weight 15
    total_weight += 15
    if ctx["ret_20d"] > 5:
        score += 15
    elif ctx["ret_20d"] > 3:
        score += 8

    # 5D return between 2-10% — weight 15
    total_weight += 15
    if 2 <= ctx["ret_5d"] <= 10:
        score += 15
    elif 0 < ctx["ret_5d"] < 2:
        score += 7

    # Price above 20-SMA and 50-SMA — weight 15
    total_weight += 15
    if ctx["sma_20"] is not None and ctx["sma_50"] is not None:
        if ctx["close"] > ctx["sma_20"] and ctx["close"] > ctx["sma_50"]:
            score += 15
        elif ctx["close"] > ctx["sma_20"]:
            score += 8

    # MA alignment: at least 5 > 20 > 50 — weight 10
    total_weight += 10
    if (
        ctx["sma_5"] is not None
        and ctx["sma_20"] is not None
        and ctx["sma_50"] is not None
    ):
        if ctx["sma_5"] > ctx["sma_20"] > ctx["sma_50"]:
            score += 10

    # RSI between 50-70 — weight 10
    total_weight += 10
    if ctx["rsi"] is not None:
        if 50 <= ctx["rsi"] <= 70:
            score += 10
        elif 45 <= ctx["rsi"] < 50:
            score += 5

    # Low variance (CV below median) — weight 10
    total_weight += 10
    if ctx["cv_daily"] is not None and ctx["cv_daily"] < ctx["cv_median"]:
        score += 10
    elif ctx["cv_daily"] is not None and ctx["cv_daily"] < ctx["cv_median"] * 1.2:
        score += 5

    # ADX between 15-30 — weight 10
    total_weight += 10
    if ctx["adx"] is not None:
        if 15 <= ctx["adx"] <= 30:
            score += 10
        elif 12 <= ctx["adx"] < 15:
            score += 5

    # Higher highs and higher lows — weight 10
    total_weight += 10
    if ctx["higher_hl"]:
        score += 10

    # Volume stable or slightly increasing — weight 5
    total_weight += 5
    if 0.9 <= ctx["vol_ratio"] <= 1.3:
        score += 5

    return int(score / total_weight * 100) if total_weight > 0 else 0


def _score_oscillating(ctx: dict) -> int:
    """Score OSCILLATING phase (0-100)."""
    score = 0
    total_weight = 0

    # 20D return > 0% (net positive) — weight 15
    total_weight += 15
    if ctx["ret_20d"] > 0:
        score += 15
    elif ctx["ret_20d"] > -2:
        score += 8

    # High daily return variance — weight 20
    total_weight += 20
    if ctx["cv_daily"] is not None and ctx["cv_daily"] > ctx["cv_median"]:
        score += 20
    elif ctx["cv_daily"] is not None and ctx["cv_daily"] > ctx["cv_median"] * 0.8:
        score += 10

    # Frequent direction changes (>4 in 10 days) — weight 20
    total_weight += 20
    if ctx["dir_changes_10"] > 4:
        score += 20
    elif ctx["dir_changes_10"] > 3:
        score += 12

    # RSI oscillating between 40-70 — weight 10
    total_weight += 10
    if ctx["rsi"] is not None:
        if 40 <= ctx["rsi"] <= 70:
            score += 10

    # Price crossing 10-SMA multiple times — weight 10
    total_weight += 10
    if ctx["sma10_crosses_20d"] > 2:
        score += 10
    elif ctx["sma10_crosses_20d"] > 1:
        score += 5

    # ADX < 20 (weak trend) — weight 10
    total_weight += 10
    if ctx["adx"] is not None:
        if ctx["adx"] < 20:
            score += 10
        elif ctx["adx"] < 25:
            score += 5

    # 5D return can be negative — weight 5
    total_weight += 5
    if ctx["ret_5d"] < 0 and ctx["ret_20d"] > 0:
        score += 5

    # Higher lows maintained (oscillating within uptrend) — weight 10
    total_weight += 10
    if ctx["higher_lows"]:
        score += 10

    return int(score / total_weight * 100) if total_weight > 0 else 0


def _score_bottoming(ctx: dict) -> int:
    """Score BOTTOMING phase (0-100)."""
    score = 0
    total_weight = 0

    # Price within 10% of lookback low — weight 25
    total_weight += 25
    if ctx["pct_from_low"] <= 10:
        score += 25
    elif ctx["pct_from_low"] <= 15:
        score += 12

    # RSI < 40 or recovering from < 30 — weight 15
    total_weight += 15
    if ctx["rsi"] is not None:
        if ctx["rsi"] < 40:
            score += 15
        elif ctx["rsi"] < 50 and ctx["rsi_was_below_30"]:
            score += 12

    # Volume declining (exhaustion) or picking up (accumulation) — weight 10
    total_weight += 10
    if ctx["vol_ratio"] < 0.8 or ctx["vol_ratio"] > 1.3:
        score += 10
    elif ctx["vol_ratio"] < 0.9:
        score += 5

    # 5D return >= 0 (not still falling) — weight 20
    total_weight += 20
    if ctx["ret_5d"] >= 0:
        score += 20
    elif ctx["ret_5d"] > -2:
        score += 10

    # 20-SMA slope turning flat — weight 15
    total_weight += 15
    if ctx["sma20_slope"] is not None:
        if -1.0 <= ctx["sma20_slope"] <= 1.0:
            score += 15
        elif -2.0 <= ctx["sma20_slope"] <= 2.0:
            score += 8

    # Price flattening after decline — weight 15
    total_weight += 15
    if ctx["ret_20d"] < 0 and ctx["ret_5d"] >= -1:
        score += 15
    elif ctx["ret_10d"] < ctx["ret_20d"] and ctx["ret_5d"] > ctx["ret_10d"]:
        score += 10

    return int(score / total_weight * 100) if total_weight > 0 else 0


def _score_declining(ctx: dict) -> int:
    """Score DECLINING phase (0-100)."""
    score = 0
    total_weight = 0

    # Price below 20-SMA and 50-SMA — weight 20
    total_weight += 20
    if ctx["sma_20"] is not None and ctx["sma_50"] is not None:
        if ctx["close"] < ctx["sma_20"] and ctx["close"] < ctx["sma_50"]:
            score += 20
        elif ctx["close"] < ctx["sma_20"]:
            score += 10

    # 20-SMA below 50-SMA (bearish) — weight 15
    total_weight += 15
    if ctx["sma_20"] is not None and ctx["sma_50"] is not None:
        if ctx["sma_20"] < ctx["sma_50"]:
            score += 15

    # 20D return < -5% — weight 20
    total_weight += 20
    if ctx["ret_20d"] < -5:
        score += 20
    elif ctx["ret_20d"] < -3:
        score += 10

    # Lower highs and lower lows — weight 20
    total_weight += 20
    if ctx["lower_hl"]:
        score += 20

    # RSI < 45 — weight 10
    total_weight += 10
    if ctx["rsi"] is not None:
        if ctx["rsi"] < 45:
            score += 10
        elif ctx["rsi"] < 50:
            score += 5

    # ADX > 20 (strong trend, downward) — weight 15
    total_weight += 15
    if ctx["adx"] is not None:
        if ctx["adx"] > 20 and ctx["ret_20d"] < 0:
            score += 15
        elif ctx["adx"] > 15 and ctx["ret_20d"] < 0:
            score += 7

    return int(score / total_weight * 100) if total_weight > 0 else 0


# ---------------------------------------------------------------------------
# Additional metric computations
# ---------------------------------------------------------------------------


def _momentum_score(ctx: dict) -> float:
    """Compute momentum score 0-10."""
    pts = 0.0
    # Returns contribution (max 4)
    if ctx["ret_5d"] > 10:
        pts += 2.0
    elif ctx["ret_5d"] > 5:
        pts += 1.5
    elif ctx["ret_5d"] > 2:
        pts += 1.0
    elif ctx["ret_5d"] > 0:
        pts += 0.5

    if ctx["ret_20d"] > 15:
        pts += 2.0
    elif ctx["ret_20d"] > 8:
        pts += 1.5
    elif ctx["ret_20d"] > 3:
        pts += 1.0
    elif ctx["ret_20d"] > 0:
        pts += 0.5

    # RSI contribution (max 3, but penalize extremes)
    if ctx["rsi"] is not None:
        if ctx["rsi"] > 80:
            # Overbought extreme: SUBTRACT instead of rewarding
            pts -= 1.0
        elif ctx["rsi"] > 70:
            pts += 2.0
        elif ctx["rsi"] > 60:
            pts += 2.5
        elif ctx["rsi"] > 50:
            pts += 1.5
        elif ctx["rsi"] > 40:
            pts += 0.5

    # MA alignment contribution (max 3)
    smas = [ctx["sma_5"], ctx["sma_10"], ctx["sma_20"], ctx["sma_50"]]
    if all(s is not None for s in smas):
        price = ctx["close"]
        if price > smas[0] > smas[1] > smas[2] > smas[3]:
            pts += 3.0
        elif price > smas[0] > smas[1] > smas[2]:
            pts += 2.0
        elif price > smas[0] > smas[1]:
            pts += 1.0
        elif price > smas[0]:
            pts += 0.5

    return round(max(0.0, min(10.0, pts)), 1)


def _trend_health(ctx: dict) -> float:
    """Compute trend health score 0-10. Higher = more sustainable."""
    pts = 0.0

    # Volume confirmation (max 3)
    if 1.0 <= ctx["vol_ratio"] <= 1.5:
        pts += 3.0
    elif 0.8 <= ctx["vol_ratio"] < 1.0:
        pts += 2.0
    elif ctx["vol_ratio"] > 1.5:
        pts += 1.5  # Too high volume can mean exhaustion
    else:
        pts += 0.5

    # Low volatility = healthier (max 4)
    if ctx["cv_daily"] is not None:
        if ctx["cv_daily"] < ctx["cv_median"] * 0.5:
            pts += 4.0
        elif ctx["cv_daily"] < ctx["cv_median"]:
            pts += 3.0
        elif ctx["cv_daily"] < ctx["cv_median"] * 1.5:
            pts += 1.5
        else:
            pts += 0.5

    # MA spacing consistency (max 3): are MAs evenly spaced?
    smas = [ctx["sma_5"], ctx["sma_10"], ctx["sma_20"], ctx["sma_50"]]
    if all(s is not None and s > 0 for s in smas):
        spreads = [
            (smas[0] - smas[1]) / smas[1] * 100,
            (smas[1] - smas[2]) / smas[2] * 100,
            (smas[2] - smas[3]) / smas[3] * 100,
        ]
        # All positive = bullish alignment
        if all(s > 0 for s in spreads):
            spread_cv = np.std(spreads) / (np.mean(spreads) + 1e-9)
            if spread_cv < 0.5:
                pts += 3.0
            elif spread_cv < 1.0:
                pts += 2.0
            else:
                pts += 1.0
        elif sum(1 for s in spreads if s > 0) >= 2:
            pts += 1.0

    return round(max(0.0, min(10.0, pts)), 1)


def _phase_duration(closes: np.ndarray, winning_phase: str, ctx: dict) -> int:
    """Estimate how many days the stock has been in the current phase.

    Simple heuristic: look back day-by-day and check if the core conditions
    of the winning phase were likely met. Returns approximate count.
    """
    n = len(closes)
    if n < 5:
        return 1

    # Heuristic based on recent return sign streaks and MA position
    duration = 1
    if winning_phase == "ACCELERATING":
        # Count consecutive days where close > sma_5 and strong gains
        for i in range(n - 2, max(n - 60, -1), -1):
            if closes[i] < closes[i + 1] * 0.97:  # More than 3% drop breaks streak
                break
            duration += 1
    elif winning_phase == "STEADY":
        # Count days above 20-SMA with positive drift
        sma20 = _sma(closes, 20)
        for i in range(n - 2, max(n - 60, -1), -1):
            if np.isnan(sma20[i]):
                break
            if closes[i] < sma20[i]:
                break
            duration += 1
    elif winning_phase == "OSCILLATING":
        # Count days of high direction-change density
        for window_end in range(n - 2, max(n - 60, -1), -1):
            start = max(0, window_end - 9)
            segment = closes[start : window_end + 1]
            if len(segment) < 5:
                break
            rets = np.diff(segment)
            changes = sum(1 for j in range(1, len(rets)) if rets[j] * rets[j - 1] < 0)
            if changes < 3:
                break
            duration += 1
    elif winning_phase == "BOTTOMING":
        # Count days within 10% of lookback low
        lookback_low = np.min(closes)
        for i in range(n - 2, max(n - 60, -1), -1):
            pct_above = (
                (closes[i] - lookback_low) / lookback_low * 100
                if lookback_low > 0
                else 100
            )
            if pct_above > 15:
                break
            duration += 1
    elif winning_phase == "DECLINING":
        # Count days below 20-SMA
        sma20 = _sma(closes, 20)
        for i in range(n - 2, max(n - 60, -1), -1):
            if np.isnan(sma20[i]):
                break
            if closes[i] > sma20[i]:
                break
            duration += 1

    return min(duration, 120)  # Cap at 120 days


def _phase_change_risk(
    winning_phase: str, ctx: dict, duration: int = 0
) -> tuple[str, str]:
    """Assess probability that phase is about to change. Returns (level, reason)."""
    if winning_phase == "ACCELERATING":
        # Check cumulative rally from recent base (pct_from_base)
        pct_from_base = ctx.get("pct_from_base_90d", 0.0)
        if pct_from_base > 100 and duration > 30:
            return "HIGH", f"累计涨幅过大(>{pct_from_base:.0f}%)，有见顶风险"
        if pct_from_base > 60:
            # Only upgrade to at least MEDIUM; don't downgrade from HIGH
            if ctx["rsi"] is not None and ctx["rsi"] > 80:
                return (
                    "HIGH",
                    f"RSI极度超买(>80)且累计涨幅{pct_from_base:.0f}%，见顶风险极高",
                )
            return "MEDIUM", f"涨幅较大({pct_from_base:.0f}%)，注意回调风险"
        if ctx["rsi"] is not None and ctx["rsi"] > 80:
            return "HIGH", "RSI极度超买 (>80)，加速可能耗尽"
        if ctx["rsi"] is not None and ctx["rsi"] > 70:
            return "MEDIUM", f"RSI接近超买 ({ctx['rsi']:.0f})，加速可能减弱"
        if ctx["vol_ratio"] > 2.0:
            return "MEDIUM", "成交量过度放大，可能是冲顶信号"
        return "LOW", "动能健康，暂无变盘信号"

    elif winning_phase == "STEADY":
        if ctx["vol_ratio"] < 0.7:
            return "MEDIUM", "成交量持续萎缩，上涨可能失去动力"
        if ctx["rsi"] is not None and ctx["rsi"] > 70:
            return "MEDIUM", "RSI偏高，可能从匀速转为加速或回调"
        return "LOW", "趋势稳健，暂无变盘信号"

    elif winning_phase == "OSCILLATING":
        if ctx["cv_daily"] is not None and ctx["cv_daily"] < ctx["cv_median"] * 0.5:
            return "MEDIUM", "波幅收窄，可能即将方向选择"
        if ctx["ret_20d"] < 0:
            return "HIGH", "整体收益转负，可能转为下跌"
        return "MEDIUM", "震荡区间可能向上或向下突破"

    elif winning_phase == "BOTTOMING":
        if ctx["ret_5d"] > 5:
            return "HIGH", "短期快速反弹，可能转为上涨阶段"
        if ctx["vol_ratio"] > 1.5:
            return "MEDIUM", "成交量放大，可能有资金介入"
        return "LOW", "底部构筑中，等待突破确认"

    elif winning_phase == "DECLINING":
        if ctx["rsi"] is not None and ctx["rsi"] < 25:
            return "HIGH", "RSI极度超卖，可能即将反弹"
        if ctx["ret_5d"] > 3:
            return "MEDIUM", "短期反弹迹象，关注是否形成底部"
        return "LOW", "下跌趋势延续，暂无反转信号"

    return "LOW", ""


# ---------------------------------------------------------------------------
# Context builder: compute all indicators needed by scoring functions
# ---------------------------------------------------------------------------


def _build_context(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, volumes: np.ndarray
) -> dict:
    """Build the indicator context dict from raw OHLCV arrays.

    NOTE: This function intentionally receives FULL price history (not trimmed to lookback).
    SMAs (especially SMA-50) need warmup data beyond the lookback window. The caller
    (classify_ticker) fetches lookback + 80 extra bars to ensure SMA stability.
    pct_from_base_90d uses an explicit slice; pct_from_low uses all available data.
    """
    n = len(closes)
    ctx = {}

    # Current close
    ctx["close"] = float(closes[-1])

    # Returns
    ctx["ret_1d"] = float((closes[-1] / closes[-2] - 1) * 100) if n >= 2 else 0.0
    ctx["ret_5d"] = float((closes[-1] / closes[-6] - 1) * 100) if n >= 6 else 0.0
    ctx["ret_10d"] = float((closes[-1] / closes[-11] - 1) * 100) if n >= 11 else 0.0
    ctx["ret_20d"] = float((closes[-1] / closes[-21] - 1) * 100) if n >= 21 else 0.0

    # Prior 5D return (days -10 to -5)
    if n >= 11:
        ctx["ret_5d_prior"] = float((closes[-6] / closes[-11] - 1) * 100)
    else:
        ctx["ret_5d_prior"] = 0.0

    # SMAs
    sma5 = _sma(closes, 5)
    sma10 = _sma(closes, 10)
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    ctx["sma_5"] = float(sma5[-1]) if not np.isnan(sma5[-1]) else None
    ctx["sma_10"] = float(sma10[-1]) if not np.isnan(sma10[-1]) else None
    ctx["sma_20"] = float(sma20[-1]) if not np.isnan(sma20[-1]) else None
    ctx["sma_50"] = float(sma50[-1]) if not np.isnan(sma50[-1]) else None

    # RSI
    ctx["rsi"] = _rsi(closes, 14)

    # Check if RSI was below 30 recently (last 20 days)
    ctx["rsi_was_below_30"] = False
    if n >= 35:  # Need enough data for RSI history
        for i in range(max(0, n - 20), n - 1):
            segment_rsi = _rsi(closes[: i + 1], 14)
            if segment_rsi is not None and segment_rsi < 30:
                ctx["rsi_was_below_30"] = True
                break

    # ADX
    ctx["adx"] = _adx(highs, lows, closes, 14)

    # Bollinger position
    ctx["boll_pos"] = _bollinger_position(closes, 20, 2.0)

    # Volume ratio: 5D avg / 20D avg
    if n >= 20:
        vol_5d = np.mean(volumes[-5:])
        vol_20d = np.mean(volumes[-20:])
        ctx["vol_ratio"] = float(vol_5d / vol_20d) if vol_20d > 0 else 1.0
    else:
        ctx["vol_ratio"] = 1.0

    # Direction changes in last 10 days
    ctx["dir_changes_10"] = _direction_changes(closes, 10)

    # Coefficient of variation of daily returns (recent 20 days)
    if n >= 21:
        daily_rets = np.diff(closes[-21:]) / closes[-21:-1] * 100
        mean_ret = np.mean(daily_rets)
        std_ret = np.std(daily_rets, ddof=1)
        ctx["cv_daily"] = (
            float(std_ret / abs(mean_ret)) if abs(mean_ret) > 0.001 else float(std_ret)
        )
    else:
        ctx["cv_daily"] = None

    # CV median across the full lookback (rolling 20-day CV)
    if n >= 40:
        cv_values = []
        for i in range(20, n):
            segment = closes[i - 20 : i + 1]
            seg_rets = np.diff(segment) / segment[:-1] * 100
            seg_mean = np.mean(seg_rets)
            seg_std = np.std(seg_rets, ddof=1)
            cv_val = seg_std / abs(seg_mean) if abs(seg_mean) > 0.001 else seg_std
            cv_values.append(cv_val)
        ctx["cv_median"] = float(np.median(cv_values)) if cv_values else 5.0
    else:
        ctx["cv_median"] = 5.0  # default fallback

    # Higher highs/lows and lower highs/lows
    ctx["higher_hl"] = _higher_highs_lows(highs, lows, 20)
    ctx["lower_hl"] = _lower_highs_lows(highs, lows, 20)

    # Higher lows only (for oscillating phase)
    if n >= 20:
        l = lows[-20:]
        mid = len(l) // 2
        ctx["higher_lows"] = np.min(l[mid:]) > np.min(l[:mid])
    else:
        ctx["higher_lows"] = False

    # SMA-10 crosses in last 20 days
    ctx["sma10_crosses_20d"] = 0
    if n >= 20 and not np.isnan(sma10[-1]):
        for i in range(max(1, n - 20), n):
            if not np.isnan(sma10[i]) and not np.isnan(sma10[i - 1]):
                above_now = closes[i] > sma10[i]
                above_prev = closes[i - 1] > sma10[i - 1]
                if above_now != above_prev:
                    ctx["sma10_crosses_20d"] += 1

    # Percent from lookback low
    lookback_low = float(np.min(lows))
    ctx["pct_from_low"] = (
        float((closes[-1] - lookback_low) / lookback_low * 100)
        if lookback_low > 0
        else 0.0
    )

    # Percent from base in last 60-120 days (for late-acceleration detection)
    # Uses lows[-base_window:] intentionally — a 90-day window for recent base detection,
    # distinct from pct_from_low which uses the FULL lookback history
    base_window = min(90, n)  # Use ~90 days as the base window
    base_low = float(np.min(lows[-base_window:]))
    ctx["pct_from_base_90d"] = (
        float((closes[-1] - base_low) / base_low * 100) if base_low > 0 else 0.0
    )

    # 20-SMA slope
    ctx["sma20_slope"] = _sma_slope(sma20, 5) if not np.all(np.isnan(sma20)) else None

    # Green days in last 5
    if n >= 5:
        ctx["green_days_5"] = (
            int(sum(1 for i in range(n - 5, n) if closes[i] > closes[i - 1]))
            if n > 5
            else 0
        )
    else:
        ctx["green_days_5"] = 0

    return ctx


# ---------------------------------------------------------------------------
# Main classification logic
# ---------------------------------------------------------------------------


def classify_ticker(ticker: str, lookback: int) -> dict:
    """Classify uptrend phase for a single ticker."""
    stock = yf.Ticker(ticker)
    # Fetch enough data for 50-SMA + lookback
    fetch_days = lookback + 80  # Extra buffer for SMA-50 warmup
    hist = stock.history(period=f"{fetch_days}d", interval="1d")

    if hist.empty or len(hist) < 20:
        return {"error": f"Insufficient price data for {ticker} (got {len(hist)} days)"}

    closes = hist["Close"].to_numpy()
    highs = hist["High"].to_numpy()
    lows = hist["Low"].to_numpy()
    volumes = hist["Volume"].to_numpy()

    # Use only the lookback window for analysis (but keep full data for SMA warmup)
    ctx = _build_context(closes, highs, lows, volumes)

    # Score each phase
    scores = {
        "ACCELERATING": _score_accelerating(ctx),
        "STEADY": _score_steady(ctx),
        "OSCILLATING": _score_oscillating(ctx),
        "BOTTOMING": _score_bottoming(ctx),
        "DECLINING": _score_declining(ctx),
    }

    # Winner: highest score, tiebreak by priority
    max_score = max(scores.values())
    candidates = [p for p in PHASE_PRIORITY if scores[p] == max_score]
    winning_phase = candidates[0]

    # Confidence
    sorted_scores = sorted(scores.values(), reverse=True)
    gap = (
        sorted_scores[0] - sorted_scores[1]
        if len(sorted_scores) > 1
        else sorted_scores[0]
    )
    if gap >= 20:
        confidence = "HIGH"
    elif gap >= 10:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Phase metadata
    phase_info = next(p for p in PHASES if p["id"] == winning_phase)

    # Additional metrics
    momentum = _momentum_score(ctx)
    health = _trend_health(ctx)
    duration = _phase_duration(
        closes[-lookback:] if len(closes) >= lookback else closes, winning_phase, ctx
    )
    risk_level, risk_reason = _phase_change_risk(winning_phase, ctx, duration)

    # MA alignment check
    smas = [ctx["sma_5"], ctx["sma_10"], ctx["sma_20"], ctx["sma_50"]]
    perfect_alignment = (
        all(s is not None for s in smas)
        and ctx["close"] > smas[0] > smas[1] > smas[2] > smas[3]
    )
    price_vs_20sma = (
        round((ctx["close"] - ctx["sma_20"]) / ctx["sma_20"] * 100, 1)
        if ctx["sma_20"] is not None and ctx["sma_20"] > 0
        else None
    )

    return {
        "ticker": ticker,
        "current_price": round(ctx["close"], 2),
        "phase": {
            "id": winning_phase,
            "name": phase_info["name"],
            "name_en": phase_info["name_en"],
            "score": scores[winning_phase],
            "confidence": confidence,
        },
        "phase_scores": scores,
        "metrics": {
            "momentum_score": momentum,
            "trend_health": health,
            "phase_duration_days": duration,
            "phase_change_risk": risk_level,
            "phase_change_reason": risk_reason,
        },
        "returns": {
            "ret_1d": round(ctx["ret_1d"], 2),
            "ret_5d": round(ctx["ret_5d"], 2),
            "ret_10d": round(ctx["ret_10d"], 2),
            "ret_20d": round(ctx["ret_20d"], 2),
        },
        "ma_alignment": {
            "sma_5": round(ctx["sma_5"], 2) if ctx["sma_5"] is not None else None,
            "sma_10": round(ctx["sma_10"], 2) if ctx["sma_10"] is not None else None,
            "sma_20": round(ctx["sma_20"], 2) if ctx["sma_20"] is not None else None,
            "sma_50": round(ctx["sma_50"], 2) if ctx["sma_50"] is not None else None,
            "perfect_alignment": perfect_alignment,
            "price_vs_20sma_pct": price_vs_20sma,
        },
        "technical_context": {
            "rsi_14": round(ctx["rsi"], 1) if ctx["rsi"] is not None else None,
            "adx_14": round(ctx["adx"], 1) if ctx["adx"] is not None else None,
            "volume_ratio_5d_20d": round(ctx["vol_ratio"], 2),
            "bollinger_position": round(ctx["boll_pos"], 2)
            if ctx["boll_pos"] is not None
            else None,
            "daily_direction_changes_10d": ctx["dir_changes_10"],
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Classify current uptrend phase for stock tickers "
        "(加速上涨 / 匀速上涨 / 波动阶段 / 底部区域 / 下跌阶段)"
    )
    parser.add_argument(
        "tickers", nargs="+", help="Ticker symbols (e.g., AAPL 603738.SS)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--lookback",
        type=int,
        default=60,
        help="Analysis window in trading days (default: 60)",
    )
    args = parser.parse_args()

    results = {}
    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()
        try:
            results[ticker] = classify_ticker(ticker, args.lookback)
        except Exception as e:
            results[ticker] = {"error": str(e)}

    output_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "lookback_days": args.lookback,
        "results": results,
    }

    output = json.dumps(output_data, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
