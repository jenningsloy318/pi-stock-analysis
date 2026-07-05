#!/usr/bin/env python3
"""Detect classic chart patterns from OHLCV data (O'Neil/欧奈尔 methodology).

Usage:
    detect_chart_patterns.py AAPL
    detect_chart_patterns.py 603738.SS --lookback 120 --min-base-days 25
    detect_chart_patterns.py AAPL MSFT NVDA --output ./reports/patterns.json
    detect_chart_patterns.py 002428.SZ 603738.SS --lookback 150

Identifies breakout patterns commonly used in A-share screening (Tushare Pro
reports) and US growth-stock selection:

  P1: 前高放量突破 (Previous High Volume Breakout)
  P2: 前高放量回踩 (Previous High Pullback)
  P3: 杯柄          (Cup with Handle)
  P4: 大平台突破    (Large Platform Breakout)
  P5: 前高附近蓄势  (Near Prior High Coiling)
  P6: 楔形收敛突破  (Wedge Convergence Breakout)

Data source: yfinance (free, no API key needed).
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

try:
    import pandas as pd
except ImportError:
    sys.stderr.write("Error: 'pandas' required. Run: pip install pandas\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a numeric value between lo and hi."""
    return max(lo, min(hi, value))


def _find_local_highs(prices: list[float], order: int = 3) -> list[int]:
    """Find indices of local highs (peaks).

    A peak at index i means prices[i] >= prices[j] for all j in
    [i-order, i+order]. Simple scan approach (no scipy needed).
    """
    peaks = []
    n = len(prices)
    for i in range(order, n - order):
        is_peak = True
        for j in range(1, order + 1):
            if prices[i] < prices[i - j] or prices[i] < prices[i + j]:
                is_peak = False
                break
        if is_peak:
            peaks.append(i)
    return peaks


def _find_local_lows(prices: list[float], order: int = 3) -> list[int]:
    """Find indices of local lows (troughs).

    A trough at index i means prices[i] <= prices[j] for all j in
    [i-order, i+order].
    """
    troughs = []
    n = len(prices)
    for i in range(order, n - order):
        is_trough = True
        for j in range(1, order + 1):
            if prices[i] > prices[i - j] or prices[i] > prices[i + j]:
                is_trough = False
                break
        if is_trough:
            troughs.append(i)
    return troughs


def _linear_regression_slope(values: list[float]) -> float:
    """Compute slope of OLS linear fit. Returns slope per bar."""
    n = len(values)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    y = np.array(values, dtype=float)
    # slope = cov(x,y) / var(x)
    x_mean = x.mean()
    y_mean = y.mean()
    numerator = ((x - x_mean) * (y - y_mean)).sum()
    denominator = ((x - x_mean) ** 2).sum()
    if denominator == 0:
        return 0.0
    return float(numerator / denominator)


def _r_squared(values: list[float]) -> float:
    """Compute R-squared for a linear fit (goodness of fit)."""
    n = len(values)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    y = np.array(values, dtype=float)
    coeffs = np.polyfit(x, y, 1)
    y_pred = np.polyval(coeffs, x)
    ss_res = ((y - y_pred) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    if ss_tot == 0:
        return 1.0
    return float(1.0 - ss_res / ss_tot)


def _volume_avg(volumes: list[float], window: int = 20) -> float:
    """Average volume over last `window` bars (excluding current)."""
    if len(volumes) < window + 1:
        return sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    return sum(volumes[-window - 1 : -1]) / window


def _bollinger_bandwidth(closes: list[float], window: int = 20) -> list[float]:
    """Compute Bollinger Band bandwidth series for the given closes."""
    bw = []
    for i in range(len(closes)):
        if i < window - 1:
            bw.append(float("nan"))
            continue
        segment = closes[i - window + 1 : i + 1]
        mean = sum(segment) / window
        std = float(np.std(segment, ddof=0))
        if mean == 0:
            bw.append(0.0)
        else:
            bw.append((2 * 2 * std) / mean)  # 2 std devs * 2 / mean
    return bw


def _detect_a_share(ticker: str) -> bool:
    """Check if ticker is a China A-share (SS/SZ suffix or 6-digit code)."""
    import re

    t = ticker.strip().upper()
    return bool(re.match(r"^\d{6}\.(SZ|SH|BJ|SS)$", t) or re.match(r"^\d{6}$", t))


# ---------------------------------------------------------------------------
# Pattern Detection Functions
# ---------------------------------------------------------------------------


def detect_p1_prev_high_breakout(
    closes: list[float],
    highs: list[float],
    volumes: list[float],
    lookback: int,
) -> dict:
    """P1: 前高放量突破 — Previous High Volume Breakout.

    Conditions:
    - prior_high = max close in lookback[20:-5] (exclude recent 5 days)
    - Current close > prior_high (broke above)
    - Breakout happened within last 5 trading days
    - Volume on breakout day > 1.5x 20-day average volume
    - Close above breakout level for 2+ consecutive days (confirmation)

    Score: 0-100 based on volume ratio, days held above, margin above high.
    """
    n = len(closes)
    if n < 30:
        return {
            "id": "P1",
            "name": "前高放量突破",
            "name_en": "Previous High Volume Breakout",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Use at most lookback bars
    start = max(0, n - lookback)
    window_closes = closes[start:]
    window_highs = highs[start:]
    window_volumes = volumes[start:]
    wn = len(window_closes)

    if wn < 30:
        return {
            "id": "P1",
            "name": "前高放量突破",
            "name_en": "Previous High Volume Breakout",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Prior high: max close excluding the most recent 5 days
    prior_segment = window_closes[20:-5] if wn > 25 else window_closes[: wn - 5]
    if not prior_segment:
        return {
            "id": "P1",
            "name": "前高放量突破",
            "name_en": "Previous High Volume Breakout",
            "score": 0,
            "detected": False,
            "reason": "no_prior_segment",
        }

    prior_high = max(prior_segment)
    current_close = window_closes[-1]

    # Check if breakout happened in last 5 days
    breakout_day = None
    for i in range(max(0, wn - 5), wn):
        if window_closes[i] > prior_high:
            if breakout_day is None:
                breakout_day = i
            break

    if breakout_day is None or current_close <= prior_high:
        return {
            "id": "P1",
            "name": "前高放量突破",
            "name_en": "Previous High Volume Breakout",
            "score": 0,
            "detected": False,
            "reason": "no_breakout_above_prior_high",
        }

    # Volume check on breakout day
    avg_vol = _volume_avg(window_volumes[: breakout_day + 1], 20)
    if avg_vol == 0:
        avg_vol = 1.0
    breakout_volume = window_volumes[breakout_day]
    volume_ratio = breakout_volume / avg_vol

    if volume_ratio < 1.5:
        return {
            "id": "P1",
            "name": "前高放量突破",
            "name_en": "Previous High Volume Breakout",
            "score": 0,
            "detected": False,
            "reason": f"volume_ratio_{volume_ratio:.2f}_below_1.5x",
        }

    # Days held above breakout level (consecutive from breakout day)
    days_above = 0
    for i in range(breakout_day, wn):
        if window_closes[i] > prior_high:
            days_above += 1
        else:
            break

    confirmed = days_above >= 2
    margin_above_pct = ((current_close - prior_high) / prior_high) * 100

    # Score calculation
    vol_component = _clamp((volume_ratio - 1.5) * 20, 0, 40)
    days_component = _clamp(days_above * 10, 0, 30)
    # Margin component: penalize extension beyond 5% (O'Neil: buy within 5% of pivot)
    if margin_above_pct <= 5:
        margin_component = _clamp(margin_above_pct * 5, 0, 25)
    else:
        # Beyond 5%: penalize instead of reward
        margin_component = _clamp(25 - (margin_above_pct - 5) * 5, -20, 25)
    score = int(_clamp(vol_component + days_component + margin_component))

    # Chase risk: penalize extended breakouts
    chase_risk = False
    if margin_above_pct > 8:
        score = int(_clamp(score - 20, 0, 100))
        chase_risk = True

    # Base distance check: if price has doubled from lookback low, flag extreme extension
    lookback_low = min(window_closes)
    extreme_extension = False
    if lookback_low > 0 and current_close / lookback_low > 2.0:
        extreme_extension = True
        score = int(_clamp(score - 25, 0, 100))

    days_since = wn - 1 - breakout_day

    # Category: extended breakout if too far above pivot
    if margin_above_pct > 5:
        category = "已突破延伸"
    else:
        category = "突破确认"

    result = {
        "id": "P1",
        "name": "前高放量突破",
        "name_en": "Previous High Volume Breakout",
        "score": score,
        "detected": True,
        "confidence": "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW",
        "category": category,
        "breakout_level": round(prior_high, 2),
        "breakout_date_offset": int(days_since),
        "volume_ratio": round(volume_ratio, 2),
        "margin_above_pct": round(margin_above_pct, 2),
        "days_confirmed": days_above,
        "confirmed": confirmed,
    }

    if chase_risk:
        result["chase_risk"] = True
        result["chase_warning"] = "突破后涨幅>8%，追高风险较大"

    if extreme_extension:
        result["extreme_extension"] = True
        result["extreme_warning"] = "股价距底部已翻倍，极端延伸风险"

    return result


def detect_p2_pullback_to_breakout(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    lookback: int,
) -> dict:
    """P2: 前高放量回踩 — Pullback to Breakout Level.

    Conditions:
    - A valid breakout occurred 5-20 days ago
    - Price pulled back toward prior_high level (within 3% above/below)
    - Volume during pullback is declining
    - Price has not broken below the prior_high level - 5%
    - Current day shows bounce (close > open or close > prior day close)

    Score: 0-100 based on support holding + volume decline + bounce quality.
    """
    n = len(closes)
    if n < 35:
        return {
            "id": "P2",
            "name": "前高放量回踩",
            "name_en": "Previous High Pullback",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    start = max(0, n - lookback)
    wc = closes[start:]
    wh = highs[start:]
    wl = lows[start:]
    wv = volumes[start:]
    wn = len(wc)

    if wn < 35:
        return {
            "id": "P2",
            "name": "前高放量回踩",
            "name_en": "Previous High Pullback",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Find prior high (excluding last 5 days for the original breakout)
    # Look for breakout that happened 5-20 days ago
    best_breakout = None
    for lookback_days in range(5, 21):
        if wn - lookback_days < 25:
            continue
        # Prior high before the candidate breakout day
        candidate_day = wn - lookback_days
        prior_segment = wc[max(0, candidate_day - 60) : candidate_day - 5]
        if len(prior_segment) < 10:
            continue
        prior_high = max(prior_segment)

        # Check if breakout happened at candidate_day
        if wc[candidate_day] > prior_high:
            avg_vol = _volume_avg(wv[: candidate_day + 1], 20)
            if avg_vol > 0 and wv[candidate_day] / avg_vol >= 1.5:
                best_breakout = {
                    "day": candidate_day,
                    "prior_high": prior_high,
                    "vol_ratio": wv[candidate_day] / avg_vol,
                }
                break

    if best_breakout is None:
        return {
            "id": "P2",
            "name": "前高放量回踩",
            "name_en": "Previous High Pullback",
            "score": 0,
            "detected": False,
            "reason": "no_prior_breakout_found",
        }

    prior_high = best_breakout["prior_high"]
    breakout_day = best_breakout["day"]

    # Check pullback: current price within 3% above/below prior_high
    current_close = wc[-1]
    distance_pct = ((current_close - prior_high) / prior_high) * 100

    if distance_pct < -3.0 or distance_pct > 3.0:
        return {
            "id": "P2",
            "name": "前高放量回踩",
            "name_en": "Previous High Pullback",
            "score": 0,
            "detected": False,
            "reason": f"price_not_near_breakout_level_{distance_pct:.1f}%",
        }

    # Check support held: price never broke below prior_high - 5%
    support_level = prior_high * 0.95
    pullback_lows = wl[breakout_day:]
    if any(low < support_level for low in pullback_lows):
        return {
            "id": "P2",
            "name": "前高放量回踩",
            "name_en": "Previous High Pullback",
            "score": 0,
            "detected": False,
            "reason": "support_broken",
        }

    # Volume declining during pullback
    pullback_vols = wv[breakout_day + 1 :]
    if len(pullback_vols) < 3:
        return {
            "id": "P2",
            "name": "前高放量回踩",
            "name_en": "Previous High Pullback",
            "score": 0,
            "detected": False,
            "reason": "pullback_too_short",
        }

    first_half_vol = sum(pullback_vols[: len(pullback_vols) // 2]) / max(
        len(pullback_vols) // 2, 1
    )
    second_half_vol = sum(pullback_vols[len(pullback_vols) // 2 :]) / max(
        len(pullback_vols) - len(pullback_vols) // 2, 1
    )
    vol_declining = second_half_vol < first_half_vol

    # Bounce quality: close > prior close or close > open (simple proxy)
    bounce = wc[-1] > wc[-2] if len(wc) >= 2 else False

    # Score
    support_score = _clamp((1.0 - abs(distance_pct) / 3.0) * 40, 0, 40)
    vol_score = 30.0 if vol_declining else 10.0
    bounce_score = 30.0 if bounce else 10.0
    score = int(_clamp(support_score + vol_score + bounce_score))

    return {
        "id": "P2",
        "name": "前高放量回踩",
        "name_en": "Previous High Pullback",
        "score": score,
        "detected": True,
        "confidence": "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW",
        "category": "回踩预警",
        "breakout_level": round(prior_high, 2),
        "distance_from_level_pct": round(distance_pct, 2),
        "volume_declining": vol_declining,
        "bounce_detected": bounce,
        "support_held": True,
        "days_since_breakout": wn - 1 - breakout_day,
    }


def detect_p3_cup_with_handle(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    lookback: int,
) -> dict:
    """P3: 杯柄 — Cup with Handle.

    Conditions:
    - U-shape: price declined, bottomed, recovered to near starting level
    - Left lip: local high 30-90 days ago
    - Cup bottom: lowest point between left lip and now, depth 12-35%
    - Right lip: current price within 5% of left lip level
    - Handle: small pullback (3-10%) from right lip on declining volume, 5-15 days
    - Handle pullback < 50% of cup depth (O'Neil rule)
    - Volume on handle days below average

    Score: symmetry of cup, handle depth, volume pattern.
    """
    n = len(closes)
    if n < 50:
        return {
            "id": "P3",
            "name": "杯柄",
            "name_en": "Cup with Handle",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    start = max(0, n - lookback)
    wc = closes[start:]
    wh = highs[start:]
    wl = lows[start:]
    wv = volumes[start:]
    wn = len(wc)

    if wn < 50:
        return {
            "id": "P3",
            "name": "杯柄",
            "name_en": "Cup with Handle",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Find left lip: a local high 30-90 days before the end
    local_highs = _find_local_highs(wc, order=5)
    left_lip_idx = None
    left_lip_price = 0

    for idx in reversed(local_highs):
        days_ago = wn - 1 - idx
        if 30 <= days_ago <= 90:
            if wc[idx] > left_lip_price:
                left_lip_idx = idx
                left_lip_price = wc[idx]

    if left_lip_idx is None:
        return {
            "id": "P3",
            "name": "杯柄",
            "name_en": "Cup with Handle",
            "score": 0,
            "detected": False,
            "reason": "no_left_lip_found",
        }

    # Cup bottom: lowest point between left lip and now
    cup_segment = wc[left_lip_idx:]
    cup_bottom_local_idx = int(np.argmin(cup_segment))
    cup_bottom_idx = left_lip_idx + cup_bottom_local_idx
    cup_bottom_price = wc[cup_bottom_idx]

    # Cup depth check: 12-35% from lip
    cup_depth_pct = ((left_lip_price - cup_bottom_price) / left_lip_price) * 100
    if cup_depth_pct < 12 or cup_depth_pct > 35:
        return {
            "id": "P3",
            "name": "杯柄",
            "name_en": "Cup with Handle",
            "score": 0,
            "detected": False,
            "reason": f"cup_depth_{cup_depth_pct:.1f}%_outside_12-35%",
        }

    # Right lip: current region should be near left lip level (within 5%)
    current_close = wc[-1]
    right_lip_distance_pct = abs(current_close - left_lip_price) / left_lip_price * 100

    # Check for handle: recent pullback of 3-10% from a recent high (right lip area)
    recent_high = max(wc[-20:]) if wn >= 20 else max(wc[-10:])
    recent_high_idx = (
        wn - 1 - list(reversed(wc[-20:])).index(recent_high) if wn >= 20 else wn - 1
    )

    # Handle detection: look for pullback in last 5-15 days
    handle_detected = False
    handle_depth_pct = 0.0
    handle_vol_below_avg = False

    if wn > 15:
        handle_segment = wc[-15:]
        handle_high = max(handle_segment)
        handle_low = (
            min(handle_segment[-10:])
            if len(handle_segment) >= 10
            else min(handle_segment)
        )
        handle_depth_pct = ((handle_high - handle_low) / handle_high) * 100

        if 3.0 <= handle_depth_pct <= 10.0:
            # O'Neil rule: handle depth < 50% of cup depth
            if handle_depth_pct < cup_depth_pct * 0.5:
                handle_detected = True
                # Volume in handle should be below average
                avg_vol = sum(wv[:-15]) / max(len(wv) - 15, 1)
                handle_avg_vol = sum(wv[-15:]) / 15
                handle_vol_below_avg = handle_avg_vol < avg_vol

    # Determine if pattern is present
    # Right lip proximity: must be within 5% for full cup, or handle forming
    pattern_valid = False
    note = ""

    if right_lip_distance_pct <= 5.0 and handle_detected:
        pattern_valid = True
        note = "full cup with handle forming"
    elif right_lip_distance_pct <= 5.0:
        pattern_valid = True
        note = "cup complete, no clear handle yet"
    elif right_lip_distance_pct <= 10.0 and cup_depth_pct >= 12:
        pattern_valid = True
        note = "partial cup forming"

    if not pattern_valid:
        return {
            "id": "P3",
            "name": "杯柄",
            "name_en": "Cup with Handle",
            "score": 0,
            "detected": False,
            "reason": f"right_lip_too_far_{right_lip_distance_pct:.1f}%",
        }

    # Symmetry: compare left side length vs right side length
    left_len = cup_bottom_idx - left_lip_idx
    right_len = wn - 1 - cup_bottom_idx
    symmetry = 1.0 - abs(left_len - right_len) / max(left_len + right_len, 1)

    # Score
    symmetry_score = _clamp(symmetry * 30, 0, 30)
    depth_score = _clamp((1.0 - abs(cup_depth_pct - 20) / 15) * 20, 0, 20)
    handle_score = (
        25.0
        if handle_detected and handle_vol_below_avg
        else 10.0
        if handle_detected
        else 0.0
    )
    proximity_score = _clamp((1.0 - right_lip_distance_pct / 10.0) * 25, 0, 25)
    score = int(_clamp(symmetry_score + depth_score + handle_score + proximity_score))

    return {
        "id": "P3",
        "name": "杯柄",
        "name_en": "Cup with Handle",
        "score": score,
        "detected": True,
        "confidence": "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW",
        "category": "强势蓄力",
        "left_lip_price": round(left_lip_price, 2),
        "cup_bottom_price": round(cup_bottom_price, 2),
        "cup_depth_pct": round(cup_depth_pct, 2),
        "right_lip_distance_pct": round(right_lip_distance_pct, 2),
        "symmetry": round(symmetry, 2),
        "handle_detected": handle_detected,
        "handle_depth_pct": round(handle_depth_pct, 2),
        "handle_vol_below_avg": handle_vol_below_avg,
        "note": note,
    }


def detect_p4_platform_breakout(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    lookback: int,
    min_base_days: int,
) -> dict:
    """P4: 大平台突破 — Large Platform Breakout.

    Conditions:
    - Price consolidated in tight range for min_base_days+ days (range < 15%)
    - The longer the base, the higher the score
    - Breakout: close above platform high on above-average volume
    - Platform must be "flat" (slope of regression < 0.1% per day)

    Score: 0-100 based on base duration, breakout volume ratio, range tightness.
    """
    n = len(closes)
    if n < min_base_days + 5:
        return {
            "id": "P4",
            "name": "大平台突破",
            "name_en": "Large Platform Breakout",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    start = max(0, n - lookback)
    wc = closes[start:]
    wh = highs[start:]
    wl = lows[start:]
    wv = volumes[start:]
    wn = len(wc)

    if wn < min_base_days + 5:
        return {
            "id": "P4",
            "name": "大平台突破",
            "name_en": "Large Platform Breakout",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Search for the longest platform ending near current day
    best_platform = None

    for end_offset in range(1, 6):  # breakout in last 1-5 days
        # Try different platform start positions
        for length in range(min(wn - 5, 100), min_base_days - 1, -1):
            platform_end = wn - end_offset
            platform_start = platform_end - length
            if platform_start < 0:
                continue

            segment = wc[platform_start:platform_end]
            seg_highs = wh[platform_start:platform_end]
            seg_lows = wl[platform_start:platform_end]

            seg_max = max(seg_highs)
            seg_min = min(seg_lows)
            if seg_min == 0:
                continue

            range_pct = (seg_max - seg_min) / seg_min * 100

            # Range must be < 15%
            if range_pct >= 15.0:
                continue

            # Slope must be flat (< 0.1% per day)
            slope = _linear_regression_slope(segment)
            slope_pct_per_day = (slope / segment[0]) * 100 if segment[0] != 0 else 0
            if abs(slope_pct_per_day) >= 0.1:
                continue

            # Valid platform found
            best_platform = {
                "start": platform_start,
                "end": platform_end,
                "length": length,
                "range_pct": range_pct,
                "slope_pct_per_day": slope_pct_per_day,
                "platform_high": seg_max,
                "platform_low": seg_min,
                "breakout_offset": end_offset,
            }
            break
        if best_platform is not None:
            break

    if best_platform is None:
        return {
            "id": "P4",
            "name": "大平台突破",
            "name_en": "Large Platform Breakout",
            "score": 0,
            "detected": False,
            "reason": "no_qualifying_platform",
        }

    # Check breakout: current close above platform high
    platform_high = best_platform["platform_high"]
    current_close = wc[-1]

    if current_close <= platform_high:
        return {
            "id": "P4",
            "name": "大平台突破",
            "name_en": "Large Platform Breakout",
            "score": 0,
            "detected": False,
            "reason": "price_not_above_platform_high",
        }

    # Volume check on breakout
    breakout_idx = best_platform["end"]
    avg_vol = _volume_avg(wv[: breakout_idx + 1], 20)
    if avg_vol == 0:
        avg_vol = 1.0
    breakout_vol = wv[breakout_idx] if breakout_idx < wn else wv[-1]
    vol_ratio = breakout_vol / avg_vol

    if vol_ratio < 1.0:
        return {
            "id": "P4",
            "name": "大平台突破",
            "name_en": "Large Platform Breakout",
            "score": 0,
            "detected": False,
            "reason": f"breakout_volume_ratio_{vol_ratio:.2f}_too_low",
        }

    # Score
    duration = best_platform["length"]
    duration_score = _clamp((duration - min_base_days) / 40 * 35, 0, 35)
    vol_score = _clamp((vol_ratio - 1.0) * 25, 0, 35)
    tightness_score = _clamp((1.0 - best_platform["range_pct"] / 15.0) * 30, 0, 30)
    score = int(_clamp(duration_score + vol_score + tightness_score))

    return {
        "id": "P4",
        "name": "大平台突破",
        "name_en": "Large Platform Breakout",
        "score": score,
        "detected": True,
        "confidence": "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW",
        "category": "突破确认",
        "platform_high": round(platform_high, 2),
        "platform_low": round(best_platform["platform_low"], 2),
        "base_duration_days": duration,
        "range_pct": round(best_platform["range_pct"], 2),
        "slope_pct_per_day": round(best_platform["slope_pct_per_day"], 4),
        "breakout_volume_ratio": round(vol_ratio, 2),
        "margin_above_pct": round(
            ((current_close - platform_high) / platform_high) * 100, 2
        ),
    }


def detect_p5_coiling_near_high(
    closes: list[float],
    highs: list[float],
    volumes: list[float],
    lookback: int,
) -> dict:
    """P5: 前高附近蓄势 — Near Prior High Coiling.

    Conditions:
    - Current price within 5% below prior 52-week or lookback high
    - Price in this "near-high" zone for 5-15 days
    - Volume declining during coiling phase (< 0.7x avg in recent 5 days)
    - Bollinger Bands squeezing (bandwidth decreasing over last 10 days)
    - NOT a breakout yet (close < prior_high)

    Score: proximity to high + volume decline + BB squeeze tightness.
    """
    n = len(closes)
    if n < 30:
        return {
            "id": "P5",
            "name": "前高附近蓄势",
            "name_en": "Near Prior High Coiling",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    start = max(0, n - lookback)
    wc = closes[start:]
    wh = highs[start:]
    wv = volumes[start:]
    wn = len(wc)

    if wn < 30:
        return {
            "id": "P5",
            "name": "前高附近蓄势",
            "name_en": "Near Prior High Coiling",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Prior high (lookback or 252-day high)
    prior_high = max(wh)
    current_close = wc[-1]

    # Must be below prior high
    if current_close >= prior_high:
        return {
            "id": "P5",
            "name": "前高附近蓄势",
            "name_en": "Near Prior High Coiling",
            "score": 0,
            "detected": False,
            "reason": "price_at_or_above_high",
        }

    # Must be within 5% below
    distance_pct = ((prior_high - current_close) / prior_high) * 100
    if distance_pct > 5.0:
        return {
            "id": "P5",
            "name": "前高附近蓄势",
            "name_en": "Near Prior High Coiling",
            "score": 0,
            "detected": False,
            "reason": f"price_{distance_pct:.1f}%_below_high_exceeds_5%",
        }

    # Days in near-high zone (within 5%)
    days_in_zone = 0
    for i in range(wn - 1, -1, -1):
        if ((prior_high - wc[i]) / prior_high) * 100 <= 5.0:
            days_in_zone += 1
        else:
            break

    if days_in_zone < 5 or days_in_zone > 15:
        return {
            "id": "P5",
            "name": "前高附近蓄势",
            "name_en": "Near Prior High Coiling",
            "score": 0,
            "detected": False,
            "reason": f"days_in_zone_{days_in_zone}_outside_5-15",
        }

    # Volume declining: recent 5-day avg < 0.7x 20-day avg
    avg_vol_20 = sum(wv[-25:-5]) / 20 if wn >= 25 else sum(wv[:-5]) / max(wn - 5, 1)
    avg_vol_5 = sum(wv[-5:]) / 5
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1.0
    vol_declining = vol_ratio < 0.7

    # Bollinger Bands squeeze
    bw_series = _bollinger_bandwidth(wc, 20)
    valid_bw = [b for b in bw_series[-15:] if not (b != b)]  # filter NaN
    bb_squeezing = False
    if len(valid_bw) >= 10:
        slope = _linear_regression_slope(valid_bw[-10:])
        bb_squeezing = slope < 0

    # Pattern detected if proximity + at least one confirming signal
    if not (vol_declining or bb_squeezing):
        return {
            "id": "P5",
            "name": "前高附近蓄势",
            "name_en": "Near Prior High Coiling",
            "score": 0,
            "detected": False,
            "reason": "no_volume_decline_or_bb_squeeze",
        }

    # Score
    proximity_score = _clamp((1.0 - distance_pct / 5.0) * 35, 0, 35)
    vol_decline_score = (
        _clamp((0.7 - vol_ratio) / 0.4 * 30, 0, 30) if vol_declining else 5.0
    )
    bb_score = 35.0 if bb_squeezing else 10.0
    score = int(_clamp(proximity_score + vol_decline_score + bb_score))

    return {
        "id": "P5",
        "name": "前高附近蓄势",
        "name_en": "Near Prior High Coiling",
        "score": score,
        "detected": True,
        "confidence": "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW",
        "category": "强势蓄力",
        "prior_high": round(prior_high, 2),
        "distance_from_high_pct": round(distance_pct, 2),
        "days_in_zone": days_in_zone,
        "volume_ratio_5d_vs_20d": round(vol_ratio, 2),
        "volume_declining": vol_declining,
        "bb_squeezing": bb_squeezing,
    }


def detect_p6_wedge_breakout(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    lookback: int,
) -> dict:
    """P6: 楔形收敛突破 — Wedge Convergence Breakout.

    Conditions:
    - Price making lower highs AND higher lows over 15-40 days (converging)
    - Upper trendline (regression of local highs) — slope negative
    - Lower trendline (regression of local lows) — slope positive
    - Lines converging (gap narrowing)
    - Breakout: price closes above upper trendline
    - Volume spike on breakout day (> 1.5x average)

    Score: convergence quality + breakout volume + momentum.
    """
    n = len(closes)
    if n < 25:
        return {
            "id": "P6",
            "name": "楔形收敛突破",
            "name_en": "Wedge Convergence Breakout",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    start = max(0, n - lookback)
    wc = closes[start:]
    wh = highs[start:]
    wl = lows[start:]
    wv = volumes[start:]
    wn = len(wc)

    if wn < 25:
        return {
            "id": "P6",
            "name": "楔形收敛突破",
            "name_en": "Wedge Convergence Breakout",
            "score": 0,
            "detected": False,
            "reason": "insufficient_data",
        }

    # Try different wedge windows (15-40 days before breakout)
    best_wedge = None

    for wedge_len in range(40, 14, -1):
        # Wedge ends just before potential breakout (1-3 days ago)
        for breakout_offset in range(1, 4):
            wedge_end = wn - breakout_offset
            wedge_start = wedge_end - wedge_len
            if wedge_start < 0:
                continue

            wedge_highs = wh[wedge_start:wedge_end]
            wedge_lows = wl[wedge_start:wedge_end]

            # Find local peaks and troughs within wedge
            peak_indices = _find_local_highs(wedge_highs, order=2)
            trough_indices = _find_local_lows(wedge_lows, order=2)

            if len(peak_indices) < 3 or len(trough_indices) < 3:
                continue

            # Regression on peaks (upper trendline)
            peak_prices = [wedge_highs[i] for i in peak_indices]
            peak_x = [float(i) for i in peak_indices]
            upper_slope = _linear_regression_slope_xy(peak_x, peak_prices)

            # Regression on troughs (lower trendline)
            trough_prices = [wedge_lows[i] for i in trough_indices]
            trough_x = [float(i) for i in trough_indices]
            lower_slope = _linear_regression_slope_xy(trough_x, trough_prices)

            # Convergence: upper slope negative, lower slope positive
            if upper_slope >= 0 or lower_slope <= 0:
                continue

            # Gap narrowing: difference at start vs end
            # Upper trendline value at start and end
            upper_start_val = peak_prices[0]
            upper_end_val = peak_prices[-1]
            lower_start_val = trough_prices[0]
            lower_end_val = trough_prices[-1]

            gap_start = upper_start_val - lower_start_val
            gap_end = upper_end_val - lower_end_val

            if gap_end >= gap_start or gap_start <= 0:
                continue

            convergence_ratio = gap_end / gap_start

            # R-squared for linearity of trends
            upper_r2 = _r_squared(peak_prices)
            lower_r2 = _r_squared(trough_prices)

            best_wedge = {
                "wedge_start": wedge_start,
                "wedge_end": wedge_end,
                "wedge_len": wedge_len,
                "upper_slope": upper_slope,
                "lower_slope": lower_slope,
                "convergence_ratio": convergence_ratio,
                "upper_r2": upper_r2,
                "lower_r2": lower_r2,
                "upper_end_val": upper_end_val,
                "breakout_offset": breakout_offset,
            }
            break
        if best_wedge is not None:
            break

    if best_wedge is None:
        return {
            "id": "P6",
            "name": "楔形收敛突破",
            "name_en": "Wedge Convergence Breakout",
            "score": 0,
            "detected": False,
            "reason": "no_converging_wedge_found",
        }

    # Check breakout above upper trendline
    upper_trendline_level = best_wedge["upper_end_val"]
    current_close = wc[-1]

    if current_close <= upper_trendline_level:
        return {
            "id": "P6",
            "name": "楔形收敛突破",
            "name_en": "Wedge Convergence Breakout",
            "score": 0,
            "detected": False,
            "reason": "price_not_above_upper_trendline",
        }

    # Volume spike on breakout
    breakout_idx = best_wedge["wedge_end"]
    avg_vol = _volume_avg(wv[: breakout_idx + 1], 20)
    if avg_vol == 0:
        avg_vol = 1.0
    breakout_vol = wv[breakout_idx] if breakout_idx < wn else wv[-1]
    vol_ratio = breakout_vol / avg_vol

    if vol_ratio < 1.5:
        return {
            "id": "P6",
            "name": "楔形收敛突破",
            "name_en": "Wedge Convergence Breakout",
            "score": 0,
            "detected": False,
            "reason": f"breakout_volume_ratio_{vol_ratio:.2f}_below_1.5x",
        }

    # Momentum: price above breakout level
    margin_above_pct = (
        (current_close - upper_trendline_level) / upper_trendline_level
    ) * 100

    # Score
    convergence_score = _clamp((1.0 - best_wedge["convergence_ratio"]) * 30, 0, 30)
    linearity_score = _clamp(
        (best_wedge["upper_r2"] + best_wedge["lower_r2"]) / 2 * 30, 0, 30
    )
    vol_component = _clamp((vol_ratio - 1.5) * 20, 0, 20)
    momentum_component = _clamp(margin_above_pct * 4, 0, 20)
    score = int(
        _clamp(convergence_score + linearity_score + vol_component + momentum_component)
    )

    # Extension penalty (same logic as P1): penalize if too far above breakout
    chase_risk = False
    if margin_above_pct > 5:
        score = int(_clamp(score - (margin_above_pct - 5) * 5, 0, 100))
    if margin_above_pct > 8:
        score = int(_clamp(score - 20, 0, 100))
        chase_risk = True

    result = {
        "id": "P6",
        "name": "楔形收敛突破",
        "name_en": "Wedge Convergence Breakout",
        "score": score,
        "detected": True,
        "confidence": "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW",
        "category": "突破确认",
        "wedge_duration_days": best_wedge["wedge_len"],
        "upper_slope": round(best_wedge["upper_slope"], 4),
        "lower_slope": round(best_wedge["lower_slope"], 4),
        "convergence_ratio": round(best_wedge["convergence_ratio"], 3),
        "upper_r2": round(best_wedge["upper_r2"], 3),
        "lower_r2": round(best_wedge["lower_r2"], 3),
        "breakout_level": round(upper_trendline_level, 2),
        "breakout_volume_ratio": round(vol_ratio, 2),
        "margin_above_pct": round(margin_above_pct, 2),
    }
    if chase_risk:
        result["chase_risk"] = True
        result["category"] = "追高风险"
    return result


def _linear_regression_slope_xy(x: list[float], y: list[float]) -> float:
    """Compute slope from explicit (x, y) pairs."""
    n = len(x)
    if n < 2:
        return 0.0
    xa = np.array(x, dtype=float)
    ya = np.array(y, dtype=float)
    x_mean = xa.mean()
    y_mean = ya.mean()
    numerator = ((xa - x_mean) * (ya - y_mean)).sum()
    denominator = ((xa - x_mean) ** 2).sum()
    if denominator == 0:
        return 0.0
    return float(numerator / denominator)


# ---------------------------------------------------------------------------
# Key Levels Computation
# ---------------------------------------------------------------------------


def compute_key_levels(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    lookback: int,
) -> dict:
    """Compute key price levels for context.

    Returns prior_high, support levels, resistance, breakout_level, 52w_high.
    """
    n = len(closes)
    start = max(0, n - lookback)
    wc = closes[start:]
    wh = highs[start:]
    wl = lows[start:]
    wn = len(wc)

    if wn < 10:
        return {}

    prior_high = max(wh)
    high_52w = max(highs[max(0, n - 252) :]) if n >= 50 else max(highs)
    current = wc[-1]

    # Support: recent swing lows
    local_lows = _find_local_lows(wl, order=3)
    supports = sorted(set(wl[i] for i in local_lows if wl[i] < current), reverse=True)

    support_1 = round(supports[0], 2) if len(supports) >= 1 else round(min(wl[-20:]), 2)
    support_2 = round(supports[1], 2) if len(supports) >= 2 else round(min(wl), 2)

    # Resistance: recent swing highs above current
    local_highs_idx = _find_local_highs(wh, order=3)
    resistances = sorted(set(wh[i] for i in local_highs_idx if wh[i] > current))

    resistance = round(resistances[0], 2) if resistances else round(prior_high, 2)

    # Breakout level: the most relevant resistance just above
    breakout_level = resistance

    return {
        "prior_high": round(prior_high, 2),
        "support_1": support_1,
        "support_2": support_2,
        "resistance": resistance,
        "breakout_level": breakout_level,
        "52w_high": round(high_52w, 2),
    }


# ---------------------------------------------------------------------------
# Context Computation
# ---------------------------------------------------------------------------


def compute_context(
    closes: list[float],
    highs: list[float],
    volumes: list[float],
) -> dict:
    """Compute additional context fields for the output."""
    n = len(closes)
    if n < 5:
        return {}

    high_52w = max(highs[max(0, n - 252) :]) if n >= 50 else max(highs)
    current = closes[-1]
    distance_52w = ((current - high_52w) / high_52w) * 100

    # Volume trend (5-day)
    if n >= 10:
        vol_5d = sum(volumes[-5:]) / 5
        vol_prev5d = sum(volumes[-10:-5]) / 5
        if vol_prev5d > 0:
            vol_change = (vol_5d - vol_prev5d) / vol_prev5d
            vol_trend = (
                "expanding"
                if vol_change > 0.1
                else "contracting"
                if vol_change < -0.1
                else "flat"
            )
        else:
            vol_trend = "unknown"
    else:
        vol_trend = "unknown"

    # Price trend (20-day slope direction)
    if n >= 20:
        slope = _linear_regression_slope(closes[-20:])
        price_trend = "up" if slope > 0 else "down"
    else:
        price_trend = "unknown"

    # Days since breakout (if any recent break above 20-day high)
    days_since_breakout = None
    breakout_level = None
    if n >= 25:
        high_20_excl_recent = max(closes[-25:-5])
        breakout_level = high_20_excl_recent
        for i in range(n - 1, max(n - 20, 0), -1):
            if closes[i] > high_20_excl_recent:
                days_since_breakout = n - 1 - i
                break

    # Extension risk: breakout > 5 days ago AND price still >5% above breakout level
    extension_risk = False
    if (
        days_since_breakout is not None
        and days_since_breakout > 5
        and breakout_level is not None
        and breakout_level > 0
        and current > breakout_level * 1.05
    ):
        extension_risk = True

    return {
        "distance_from_52w_high_pct": round(distance_52w, 2),
        "days_since_breakout": days_since_breakout,
        "extension_risk": extension_risk,
        "volume_trend_5d": vol_trend,
        "price_trend_20d": price_trend,
    }


# ---------------------------------------------------------------------------
# Orchestrator: analyze all patterns for one ticker
# ---------------------------------------------------------------------------


def analyze_ticker(
    ticker: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    opens: list[float],
    volumes: list[float],
    lookback: int,
    min_base_days: int,
) -> dict:
    """Run all pattern detectors for a single ticker and aggregate results."""

    current_price = closes[-1] if closes else 0.0

    # Detect all patterns
    p1 = detect_p1_prev_high_breakout(closes, highs, volumes, lookback)
    p2 = detect_p2_pullback_to_breakout(closes, highs, lows, volumes, lookback)
    p3 = detect_p3_cup_with_handle(closes, highs, lows, volumes, lookback)
    p4 = detect_p4_platform_breakout(
        closes, highs, lows, volumes, lookback, min_base_days
    )
    p5 = detect_p5_coiling_near_high(closes, highs, volumes, lookback)
    p6 = detect_p6_wedge_breakout(closes, highs, lows, volumes, lookback)

    all_patterns = [p1, p2, p3, p4, p5, p6]

    # Summarize for output
    all_patterns_summary = []
    for p in all_patterns:
        entry = {
            "id": p["id"],
            "name": p["name"],
            "score": p["score"],
            "detected": p.get("detected", False),
        }
        if p.get("note"):
            entry["note"] = p["note"]
        all_patterns_summary.append(entry)

    # Find dominant pattern (highest score among detected)
    detected_patterns = [p for p in all_patterns if p.get("detected", False)]
    dominant = None
    if detected_patterns:
        dominant = max(detected_patterns, key=lambda x: x["score"])

    # Pattern score = dominant score or 0
    pattern_score = dominant["score"] if dominant else 0

    # Pattern category
    if dominant:
        category = dominant.get("category", "无形态")
    else:
        category = "无形态"

    # Breakout / volume confirmation
    breakout_confirmed = False
    volume_confirmed = False
    if dominant:
        # P1, P4, P6 are breakout patterns
        if dominant["id"] in ("P1", "P4", "P6"):
            breakout_confirmed = dominant.get("confirmed", True)
            volume_confirmed = (
                dominant.get("breakout_volume_ratio", dominant.get("volume_ratio", 0))
                >= 1.5
            )
        elif dominant["id"] == "P2":
            breakout_confirmed = False  # pullback, not breakout
            volume_confirmed = dominant.get("volume_declining", False)
        elif dominant["id"] == "P3":
            breakout_confirmed = dominant.get("handle_detected", False)
            volume_confirmed = dominant.get("handle_vol_below_avg", False)
        elif dominant["id"] == "P5":
            breakout_confirmed = False  # not yet broken out
            volume_confirmed = dominant.get("volume_declining", False)

    # Key levels
    key_levels = compute_key_levels(closes, highs, lows, lookback)

    # Context
    context = compute_context(closes, highs, volumes)

    result = {
        "ticker": ticker,
        "current_price": round(current_price, 2),
        "dominant_pattern": dominant if dominant else None,
        "all_patterns": all_patterns_summary,
        "pattern_score": pattern_score,
        "pattern_category": category,
        "breakout_confirmation": breakout_confirmed,
        "volume_confirmation": volume_confirmed,
        "key_levels": key_levels,
        "context": context,
    }

    return result


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch_ohlcv_yfinance(ticker: str, lookback: int) -> tuple | None:
    """Fetch OHLCV data via yfinance.

    Returns (dates, opens, highs, lows, closes, volumes) or None.
    """
    # Determine period based on lookback (add buffer for indicators)
    days_needed = lookback + 50
    if days_needed <= 120:
        period = "6mo"
    elif days_needed <= 250:
        period = "1y"
    else:
        period = "2y"

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval="1d")
        if hist.empty:
            return None

        dates = hist.index.tolist()
        opens = hist["Open"].tolist()
        highs = hist["High"].tolist()
        lows = hist["Low"].tolist()
        closes = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()

        return dates, opens, highs, lows, closes, volumes
    except Exception:
        return None


def _fetch_ohlcv_a_share(ticker: str, lookback: int) -> tuple | None:
    """Fetch OHLCV data for A-share ticker using akshare or baostock.

    Returns (dates, opens, highs, lows, closes, volumes) or None.
    """
    import re

    code = (
        ticker.upper()
        .replace(".SZ", "")
        .replace(".SH", "")
        .replace(".SS", "")
        .replace(".BJ", "")
    )

    days_needed = lookback + 50
    from datetime import date, timedelta

    end_dt = date.today()
    start_dt = end_dt - timedelta(days=int(days_needed * 1.5))

    # Try akshare
    try:
        import akshare as ak

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is not None and not df.empty:
            dates = pd.to_datetime(df["日期"]).tolist()
            opens = df["开盘"].astype(float).tolist()
            highs = df["最高"].astype(float).tolist()
            lows = df["最低"].astype(float).tolist()
            closes = df["收盘"].astype(float).tolist()
            volumes = df["成交量"].astype(float).tolist()
            return dates, opens, highs, lows, closes, volumes
    except Exception:
        pass

    # Fallback to yfinance with .SS/.SZ suffix
    try:
        yf_ticker = ticker
        if not re.search(r"\.(SS|SZ|SH|BJ)$", ticker, re.IGNORECASE):
            # Guess suffix from code
            num = int(code) if code.isdigit() else 0
            if 600000 <= num <= 609999 or 688000 <= num <= 689999:
                yf_ticker = f"{code}.SS"
            else:
                yf_ticker = f"{code}.SZ"
        return _fetch_ohlcv_yfinance(yf_ticker, lookback)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Detect classic chart patterns from OHLCV data (O'Neil methodology)"
    )
    parser.add_argument(
        "tickers", nargs="+", help="Ticker symbols (e.g., AAPL 603738.SS 002428.SZ)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--lookback",
        type=int,
        default=120,
        help="Analysis window in trading days (default: 120)",
    )
    parser.add_argument(
        "--min-base-days",
        type=int,
        default=20,
        help="Minimum days for base/platform formation (default: 20)",
    )
    args = parser.parse_args()

    results = {}

    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()
        try:
            is_a_share = _detect_a_share(ticker)

            if is_a_share:
                ohlcv = _fetch_ohlcv_a_share(ticker, args.lookback)
                source_label = "akshare"
            else:
                ohlcv = _fetch_ohlcv_yfinance(ticker, args.lookback)
                source_label = "yfinance"

            if ohlcv is None:
                results[ticker] = {
                    "ticker": ticker,
                    "error": f"No price data for {ticker}",
                }
                continue

            dates, opens, highs, lows, closes, volumes = ohlcv

            # Filter out NaN/None values
            valid_data = [
                (d, o, h, l, c, v)
                for d, o, h, l, c, v in zip(dates, opens, highs, lows, closes, volumes)
                if c is not None
                and not (isinstance(c, float) and c != c)
                and h is not None
                and not (isinstance(h, float) and h != h)
                and l is not None
                and not (isinstance(l, float) and l != l)
                and v is not None
                and not (isinstance(v, float) and v != v)
            ]

            if len(valid_data) < 30:
                results[ticker] = {
                    "ticker": ticker,
                    "error": f"Insufficient valid data ({len(valid_data)} bars)",
                }
                continue

            dates, opens, highs, lows, closes, volumes = zip(*valid_data)
            dates = list(dates)
            opens = list(opens)
            highs = list(highs)
            lows = list(lows)
            closes = list(closes)
            volumes = list(volumes)

            # Run analysis
            ticker_result = analyze_ticker(
                ticker=ticker,
                closes=closes,
                highs=highs,
                lows=lows,
                opens=opens,
                volumes=volumes,
                lookback=args.lookback,
                min_base_days=args.min_base_days,
            )

            # Add metadata
            ticker_result["source"] = source_label
            ticker_result["data_points"] = len(closes)
            ticker_result["last_date"] = (
                str(dates[-1].date())
                if hasattr(dates[-1], "date")
                else str(dates[-1])[:10]
            )

            results[ticker] = ticker_result

        except Exception as e:
            results[ticker] = {"ticker": ticker, "error": str(e)}

    # Build final output
    output_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "lookback_days": args.lookback,
        "min_base_days": args.min_base_days,
        "results": results,
    }

    output_json = json.dumps(output_data, indent=2, ensure_ascii=False, default=str)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        sys.stderr.write(f"Output written to {args.output}\n")
    else:
        print(output_json)

    sys.exit(0)


if __name__ == "__main__":
    main()
