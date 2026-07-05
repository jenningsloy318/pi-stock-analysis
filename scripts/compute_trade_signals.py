#!/usr/bin/env python3
"""Generate explicit BUY/SELL/HOLD trade signals by combining technical,
flow, and fundamental triggers.

Usage:
    compute_trade_signals.py AAPL
    compute_trade_signals.py AAPL MSFT --horizon short
    compute_trade_signals.py NVDA --money-flow-json ./reports/nvda_flow.json
    compute_trade_signals.py AAPL --output ./reports/signals.json

Design Philosophy:
  - A signal fires when MULTIPLE conditions align simultaneously (不是单一指标)
  - Each signal has confidence level and recommended action
  - Distinguish: 建仓(initial buy), 加仓(add), 减仓(reduce), 清仓(exit)
  - Time-horizon aware: short-term (days-weeks), mid-term (weeks-months)

Signals:
  BUY:  B1 量价齐升突破, B2 超跌反转, B3 均线金叉+量能确认,
        B4 缩量回踩支撑, B5 资金持续流入+蓄势, B6 突破新高回踩确认
  SELL: S1 放量跌破支撑, S2 超买反转, S3 均线死叉,
        S4 量价背离, S5 资金持续流出, S6 跌破200日均线
  HOLD: H1 无方向信号, H2 信号冲突

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
# Technical Indicator Helpers (computed from raw OHLCV)
# ---------------------------------------------------------------------------


def compute_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period, min_periods=period).mean()
    loss = (
        (-delta.where(delta < 0, 0.0)).rolling(window=period, min_periods=period).mean()
    )
    rs = gain / loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.fillna(100.0)
    return rsi


def compute_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Bollinger Bands: returns (middle, upper, lower, bandwidth, position)."""
    middle = compute_sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    bandwidth = (upper - lower) / middle
    position = (close - lower) / (upper - lower)
    return middle, upper, lower, bandwidth, position


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD: returns (macd_line, signal_line, histogram)."""
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Average Directional Index."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    plus_dm = (high - prev_high).where((high - prev_high) > (prev_low - low), 0.0)
    plus_dm = plus_dm.where(plus_dm > 0, 0.0)
    minus_dm = (prev_low - low).where((prev_low - low) > (high - prev_high), 0.0)
    minus_dm = minus_dm.where(minus_dm > 0, 0.0)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(span=period, adjust=False).mean() / atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.where(
        close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0)
    )
    obv = (volume * direction).cumsum()
    return pd.Series(obv, index=close.index)


def compute_mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Money Flow Index."""
    typical_price = (high + low + close) / 3.0
    money_flow = typical_price * volume
    prev_tp = typical_price.shift(1)

    positive_flow = money_flow.where(typical_price > prev_tp, 0.0)
    negative_flow = money_flow.where(typical_price < prev_tp, 0.0)

    pos_sum = positive_flow.rolling(window=period, min_periods=period).sum()
    neg_sum = negative_flow.rolling(window=period, min_periods=period).sum()

    money_ratio = pos_sum / neg_sum.replace(0, np.nan)
    mfi = 100.0 - (100.0 / (1.0 + money_ratio))
    return mfi


def compute_cmf(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """Chaikin Money Flow."""
    hl_range = high - low
    clv = ((close - low) - (high - close)) / hl_range.replace(0, np.nan)
    mf_volume = clv * volume
    cmf = (
        mf_volume.rolling(window=period, min_periods=period).sum()
        / volume.rolling(window=period, min_periods=period).sum()
    )
    return cmf


def compute_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    return atr


# ---------------------------------------------------------------------------
# Signal Detection Functions
# ---------------------------------------------------------------------------


def check_b1_volume_breakout(
    close: pd.Series,
    volume: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
    mfi: pd.Series,
    cmf: pd.Series,
    money_flow_data: dict | None,
) -> dict | None:
    """B1: 量价齐升突破 (Volume Breakout Buy)."""
    if len(close) < 25:
        return None

    curr_close = close.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol_20 = volume.iloc[-20:].mean()
    high_5d = close.iloc[-6:-1].max()
    curr_mfi = mfi.iloc[-1]
    curr_cmf = cmf.iloc[-1]

    # Conditions
    above_sma20 = curr_close > curr_sma20
    vol_surge = curr_vol > 1.5 * avg_vol_20
    breakout_5d = curr_close > high_5d
    flow_positive = curr_mfi > 50 or curr_cmf > 0

    # Override with money flow composite if available
    if money_flow_data and "composite_score" in money_flow_data:
        composite = money_flow_data["composite_score"]
        if isinstance(composite, dict):
            composite = composite.get("score", 5)
        flow_positive = composite > 5

    if not (above_sma20 and vol_surge and breakout_5d and flow_positive):
        return None

    # Confidence
    confidence = "HIGH" if curr_close > curr_sma50 else "MEDIUM"
    action = "建仓" if confidence == "HIGH" else "加仓"

    conditions_met = []
    conditions_met.append(f"Price ${curr_close:.2f} > 20-SMA ${curr_sma20:.2f}")
    conditions_met.append(
        f"Volume {curr_vol:.0f} = {curr_vol/avg_vol_20:.1f}x avg (>1.5x)"
    )
    conditions_met.append(f"Close > 5-day high ${high_5d:.2f} (breakout)")
    if money_flow_data:
        conditions_met.append("Money flow composite > 5 (institutional participation)")
    else:
        conditions_met.append(f"MFI={curr_mfi:.1f}>50 or CMF={curr_cmf:.3f}>0")

    return {
        "id": "B1",
        "name": "量价齐升突破",
        "name_en": "Volume Breakout Buy",
        "type": "BUY",
        "action": action,
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(high_5d), 2),
        "horizon": "short",
    }


def check_b2_oversold_reversal(
    close: pd.Series,
    volume: pd.Series,
    rsi: pd.Series,
    bb_lower: pd.Series,
    sma200: pd.Series,
) -> dict | None:
    """B2: 超跌反转 (Oversold Reversal Buy)."""
    if len(close) < 200:
        return None

    curr_close = close.iloc[-1]
    prev_close = close.iloc[-2]
    curr_rsi = rsi.iloc[-1]
    curr_bb_lower = bb_lower.iloc[-1]
    curr_sma200 = sma200.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = volume.iloc[-20:].mean()

    # Conditions
    oversold = curr_rsi < 30
    touches_lower_bb = curr_close <= curr_bb_lower * 1.01  # within 1%
    reversal_candle = curr_close > prev_close
    vol_on_reversal = curr_vol > avg_vol
    trend_intact = curr_close > curr_sma200 or (
        curr_close > curr_sma200 * 0.95
    )  # within 5% of 200-SMA

    if not (oversold and touches_lower_bb and reversal_candle and vol_on_reversal):
        return None

    confidence = "HIGH" if curr_close > curr_sma200 else "MEDIUM"

    conditions_met = [
        f"RSI-14 = {curr_rsi:.1f} (< 30, oversold)",
        f"Price ${curr_close:.2f} at/below lower BB ${curr_bb_lower:.2f}",
        f"Reversal candle: close ${curr_close:.2f} > prev ${prev_close:.2f}",
        f"Volume {curr_vol:.0f} > avg {avg_vol:.0f} (buyers stepping in)",
    ]
    if curr_close > curr_sma200:
        conditions_met.append(f"Above 200-SMA ${curr_sma200:.2f} (uptrend intact)")
    else:
        conditions_met.append(f"Within 5% of 200-SMA ${curr_sma200:.2f}")

    return {
        "id": "B2",
        "name": "超跌反转",
        "name_en": "Oversold Reversal Buy",
        "type": "BUY",
        "action": "建仓",
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_bb_lower), 2),
        "horizon": "short",
    }


def check_b3_golden_cross(
    close: pd.Series,
    volume: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
    sma200: pd.Series,
    adx: pd.Series,
) -> dict | None:
    """B3: 均线金叉 + 量能确认 (Moving Average Golden Cross)."""
    if len(close) < 55:
        return None

    curr_close = close.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_sma200 = sma200.iloc[-1] if len(sma200.dropna()) > 0 else None
    curr_adx = adx.iloc[-1]

    # Check for golden cross within last 3 days
    cross_detected = False
    for i in range(-3, 0):
        if len(sma20) + i >= 1 and len(sma50) + i >= 1:
            prev_sma20 = sma20.iloc[i - 1]
            prev_sma50 = sma50.iloc[i - 1]
            cur_sma20 = sma20.iloc[i]
            cur_sma50 = sma50.iloc[i]
            if (
                not pd.isna(prev_sma20)
                and not pd.isna(prev_sma50)
                and not pd.isna(cur_sma20)
                and not pd.isna(cur_sma50)
            ):
                if prev_sma20 <= prev_sma50 and cur_sma20 > cur_sma50:
                    cross_detected = True
                    break

    if not cross_detected:
        return None

    # Additional conditions
    above_cross = curr_close > curr_sma20
    vol_5d = volume.iloc[-5:].mean()
    vol_20d = volume.iloc[-20:].mean()
    vol_expanding = vol_5d > vol_20d
    trend_strength = curr_adx > 20 if not pd.isna(curr_adx) else True

    if not (above_cross and vol_expanding and trend_strength):
        return None

    major_uptrend = (
        curr_sma200 is not None
        and not pd.isna(curr_sma200)
        and curr_sma50 > curr_sma200
    )
    confidence = "HIGH" if major_uptrend else "MEDIUM"

    conditions_met = [
        "20-SMA crossed above 50-SMA within last 3 days (golden cross)",
        f"Price ${curr_close:.2f} > 20-SMA ${curr_sma20:.2f} (confirming)",
        f"5D avg volume {vol_5d:.0f} > 20D avg {vol_20d:.0f} (expanding)",
        f"ADX = {curr_adx:.1f} (> 20, trend developing)",
    ]
    if major_uptrend:
        conditions_met.append("50-SMA > 200-SMA (major uptrend confirmed)")

    return {
        "id": "B3",
        "name": "均线金叉+量能确认",
        "name_en": "Moving Average Golden Cross",
        "type": "BUY",
        "action": "建仓",
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_sma20), 2),
        "horizon": "mid",
    }


def check_b4_pullback_to_support(
    close: pd.Series,
    volume: pd.Series,
    rsi: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
) -> dict | None:
    """B4: 缩量回踩支撑 (Low-Volume Pullback to Support)."""
    if len(close) < 55:
        return None

    curr_close = close.iloc[-1]
    prev_close = close.iloc[-2]
    curr_rsi = rsi.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = volume.iloc[-20:].mean()

    # Check pullback to support (within 1% of SMA)
    near_sma20 = abs(curr_close - curr_sma20) / curr_sma20 < 0.01
    near_sma50 = abs(curr_close - curr_sma50) / curr_sma50 < 0.01
    if not (near_sma20 or near_sma50):
        return None

    # Volume declining during pullback
    low_vol = curr_vol < 0.7 * avg_vol

    # RSI healthy range
    rsi_healthy = 40 <= curr_rsi <= 55 if not pd.isna(curr_rsi) else False

    # Previous trend was up (20-day return positive)
    if len(close) >= 20:
        prev_trend_up = close.iloc[-1] > close.iloc[-20]
    else:
        prev_trend_up = False

    # Bounce: today > yesterday
    bounce = curr_close > prev_close

    if not (low_vol and rsi_healthy and prev_trend_up and bounce):
        return None

    # Confidence based on which SMA is support
    support_level = curr_sma50 if near_sma50 else curr_sma20
    support_name = "50-SMA" if near_sma50 else "20-SMA"
    confidence = "HIGH" if near_sma50 else "MEDIUM"

    pct_from_support = abs(curr_close - support_level) / support_level * 100
    pct_20d_gain = (curr_close / close.iloc[-20] - 1) * 100

    conditions_met = [
        f"Price within {pct_from_support:.1f}% of {support_name} ${support_level:.2f}",
        f"Pullback volume {curr_vol/avg_vol:.1f}x avg (< 0.7x, no selling pressure)",
        f"RSI at {curr_rsi:.1f} (healthy, not overbought)",
        f"Previous 20-day trend was UP (+{pct_20d_gain:.1f}%)",
        f"Today's close > yesterday's (+${curr_close - prev_close:.2f} bounce)",
    ]

    return {
        "id": "B4",
        "name": "缩量回踩支撑",
        "name_en": "Low-Volume Pullback to Support",
        "type": "BUY",
        "action": "加仓",
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(support_level), 2),
        "horizon": "mid",
    }


def check_b5_accumulation_coiling(
    close: pd.Series, bb_bandwidth: pd.Series, money_flow_data: dict | None
) -> dict | None:
    """B5: 资金持续流入 + 蓄势 (Accumulation + Coiling). Requires money-flow-json."""
    if money_flow_data is None:
        return None

    # Extract money flow fields
    streak_info = money_flow_data.get("streak_analysis", {})
    symmetry = money_flow_data.get("symmetry", {})
    streak_type = streak_info.get("current_streak_type", "neutral")
    streak_days = streak_info.get("current_streak_days", 0)
    vol_price_sym = symmetry.get("volume_price_symmetry", False)

    # Conditions
    consecutive_inflow = streak_type == "inflow" and streak_days >= 5
    if not consecutive_inflow:
        return None

    # Price consolidation (3% range over last 10 days)
    if len(close) < 10:
        return None
    recent_range = (close.iloc[-10:].max() - close.iloc[-10:].min()) / close.iloc[-1]
    tight_consolidation = recent_range < 0.03

    # Bollinger squeezing
    if len(bb_bandwidth.dropna()) < 20:
        return None
    curr_bw = bb_bandwidth.iloc[-1]
    avg_bw = bb_bandwidth.iloc[-20:].mean()
    squeezing = (
        curr_bw < avg_bw if not pd.isna(curr_bw) and not pd.isna(avg_bw) else False
    )

    if not (vol_price_sym and tight_consolidation and squeezing):
        return None

    conditions_met = [
        f"Consecutive inflow: {streak_days} days (>= 5)",
        "Volume-price symmetry = TRUE (量价齐升)",
        f"Price range {recent_range*100:.1f}% over 10 days (< 3%, coiling)",
        f"BB bandwidth {curr_bw:.4f} < avg {avg_bw:.4f} (squeezing)",
    ]

    return {
        "id": "B5",
        "name": "资金持续流入+蓄势",
        "name_en": "Accumulation + Coiling",
        "type": "BUY",
        "action": "建仓",
        "confidence": "HIGH",
        "conditions_met": conditions_met,
        "trigger_price": round(float(close.iloc[-1]), 2),
        "horizon": "mid",
    }


def check_b6_breakout_retest(
    close: pd.Series, volume: pd.Series, high_52w: float
) -> dict | None:
    """B6: 突破新高回踩确认 (Breakout Retest Buy)."""
    if len(close) < 15:
        return None

    curr_close = close.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = volume.iloc[-20:].mean()

    # Find if there was a breakout above 52-week high in last 10 days
    breakout_level = None
    for i in range(-10, -1):
        if close.iloc[i] > high_52w * 0.99:  # crossed 52w high
            breakout_level = high_52w
            break

    if breakout_level is None:
        return None

    # Currently pulling back to breakout level (within 2%)
    near_breakout = abs(curr_close - breakout_level) / breakout_level < 0.02
    holding_above = curr_close >= breakout_level * 0.99

    # Volume declining on pullback
    vol_declining = curr_vol < avg_vol

    if not (near_breakout and holding_above and vol_declining):
        return None

    conditions_met = [
        f"Broke above 52-week high ${high_52w:.2f} within last 10 days",
        "Pulled back to breakout level (within 2%)",
        f"Holding above breakout: ${curr_close:.2f} >= ${breakout_level*0.99:.2f}",
        f"Volume declining on retest ({curr_vol/avg_vol:.1f}x avg)",
    ]

    return {
        "id": "B6",
        "name": "突破新高回踩确认",
        "name_en": "Breakout Retest Buy",
        "type": "BUY",
        "action": "加仓",
        "confidence": "HIGH",
        "conditions_met": conditions_met,
        "trigger_price": round(float(breakout_level), 2),
        "horizon": "short",
    }


def check_s1_volume_breakdown(
    close: pd.Series,
    volume: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
    mfi: pd.Series,
    obv: pd.Series,
    money_flow_data: dict | None,
) -> dict | None:
    """S1: 放量跌破支撑 (Volume Breakdown Sell)."""
    if len(close) < 55:
        return None

    curr_close = close.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = volume.iloc[-20:].mean()
    low_5d = close.iloc[-6:-1].min()
    curr_mfi = mfi.iloc[-1]

    # OBV declining (last 5 days)
    obv_declining = obv.iloc[-1] < obv.iloc[-5] if len(obv) >= 5 else False

    # Conditions
    below_50sma = curr_close < curr_sma50
    vol_surge = curr_vol > 1.5 * avg_vol
    breakdown_5d = curr_close < low_5d
    flow_negative = curr_mfi < 50 and obv_declining

    # Override with money flow composite
    if money_flow_data and "composite_score" in money_flow_data:
        composite = money_flow_data["composite_score"]
        if isinstance(composite, dict):
            composite = composite.get("score", 5)
        flow_negative = composite < 4

    if not (below_50sma and vol_surge and breakdown_5d and flow_negative):
        return None

    confidence = "HIGH" if curr_close < curr_sma20 else "MEDIUM"
    action = "清仓" if confidence == "HIGH" else "减仓"

    conditions_met = [
        f"Price ${curr_close:.2f} < 50-SMA ${curr_sma50:.2f}",
        f"Volume {curr_vol:.0f} = {curr_vol/avg_vol:.1f}x avg (>1.5x, institutional selling)",
        f"Close < 5-day low ${low_5d:.2f} (breakdown)",
    ]
    if money_flow_data:
        conditions_met.append("Money flow composite < 4 (outflow)")
    else:
        conditions_met.append(f"MFI={curr_mfi:.1f}<50 and OBV declining")

    return {
        "id": "S1",
        "name": "放量跌破支撑",
        "name_en": "Volume Breakdown Sell",
        "type": "SELL",
        "action": action,
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_sma50), 2),
        "horizon": "short",
    }


def check_s2_overbought_reversal(
    close: pd.Series,
    volume: pd.Series,
    rsi: pd.Series,
    bb_upper: pd.Series,
    macd_hist: pd.Series,
    sma200: pd.Series | None = None,
) -> dict | None:
    """S2: 超买反转 (Overbought Reversal Sell)."""
    if len(close) < 25:
        return None

    curr_close = close.iloc[-1]
    prev_close = close.iloc[-2]
    curr_rsi = rsi.iloc[-1]
    curr_bb_upper = bb_upper.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = volume.iloc[-20:].mean()
    curr_macd_hist = macd_hist.iloc[-1]
    prev_macd_hist = macd_hist.iloc[-2] if len(macd_hist) >= 2 else 0

    # Contextual RSI threshold based on distance from 200MA
    # Stocks far above 200MA are in strong trends where RSI 70 is normal consolidation
    rsi_threshold = 70  # default
    pct_above_200ma = 0.0
    if sma200 is not None and len(sma200.dropna()) > 0:
        curr_sma200 = sma200.iloc[-1]
        if not pd.isna(curr_sma200) and curr_sma200 > 0:
            pct_above_200ma = (curr_close - curr_sma200) / curr_sma200 * 100
            if pct_above_200ma > 80:
                rsi_threshold = 60
            elif pct_above_200ma > 50:
                rsi_threshold = 65
            # else: keep default 70

    # Conditions
    overbought = curr_rsi > rsi_threshold if not pd.isna(curr_rsi) else False
    touches_upper_bb = (
        curr_close >= curr_bb_upper * 0.99 if not pd.isna(curr_bb_upper) else False
    )
    reversal_candle = curr_close < prev_close
    vol_spike = curr_vol > avg_vol

    if not (overbought and touches_upper_bb and reversal_candle and vol_spike):
        return None

    # MACD histogram turning negative
    macd_turning = (
        not pd.isna(curr_macd_hist)
        and not pd.isna(prev_macd_hist)
        and curr_macd_hist < prev_macd_hist
    )
    confidence = "HIGH" if macd_turning else "MEDIUM"

    conditions_met = [
        f"RSI-14 = {curr_rsi:.1f} (> {rsi_threshold}, overbought; 200MA距离={pct_above_200ma:.0f}%)",
        f"Price ${curr_close:.2f} at/above upper BB ${curr_bb_upper:.2f}",
        f"Reversal candle: close ${curr_close:.2f} < prev ${prev_close:.2f}",
        f"Volume spike: {curr_vol/avg_vol:.1f}x avg (distribution)",
    ]
    if macd_turning:
        conditions_met.append("MACD histogram turning negative (momentum fading)")

    return {
        "id": "S2",
        "name": "超买反转",
        "name_en": "Overbought Reversal Sell",
        "type": "SELL",
        "action": "减仓",
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_bb_upper), 2),
        "horizon": "short",
    }


def check_s3_death_cross(
    close: pd.Series,
    volume: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
    sma200: pd.Series,
    adx: pd.Series,
) -> dict | None:
    """S3: 均线死叉 (Death Cross)."""
    if len(close) < 55:
        return None

    curr_close = close.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_sma200 = sma200.iloc[-1] if len(sma200.dropna()) > 0 else None
    curr_adx = adx.iloc[-1]

    # Check for death cross within last 3 days
    cross_detected = False
    for i in range(-3, 0):
        if len(sma20) + i >= 1 and len(sma50) + i >= 1:
            prev_sma20 = sma20.iloc[i - 1]
            prev_sma50 = sma50.iloc[i - 1]
            cur_sma20 = sma20.iloc[i]
            cur_sma50 = sma50.iloc[i]
            if (
                not pd.isna(prev_sma20)
                and not pd.isna(prev_sma50)
                and not pd.isna(cur_sma20)
                and not pd.isna(cur_sma50)
            ):
                if prev_sma20 >= prev_sma50 and cur_sma20 < cur_sma50:
                    cross_detected = True
                    break

    if not cross_detected:
        return None

    # Additional conditions
    below_cross = curr_close < curr_sma20
    vol_5d = volume.iloc[-5:].mean()
    vol_20d = volume.iloc[-20:].mean()
    vol_not_declining = vol_5d >= vol_20d * 0.8  # flat or expanding
    trend_strength = curr_adx > 20 if not pd.isna(curr_adx) else True

    if not (below_cross and vol_not_declining and trend_strength):
        return None

    major_downtrend = (
        curr_sma200 is not None
        and not pd.isna(curr_sma200)
        and curr_sma50 < curr_sma200
    )
    confidence = "HIGH" if major_downtrend else "MEDIUM"

    conditions_met = [
        "20-SMA crossed below 50-SMA within last 3 days (death cross)",
        f"Price ${curr_close:.2f} < 20-SMA ${curr_sma20:.2f} (confirming)",
        f"Volume flat/expanding (5D/20D ratio: {vol_5d/vol_20d:.2f})",
        f"ADX = {curr_adx:.1f} (> 20, trend developing)",
    ]
    if major_downtrend:
        conditions_met.append("50-SMA < 200-SMA (major downtrend)")

    return {
        "id": "S3",
        "name": "均线死叉",
        "name_en": "Death Cross",
        "type": "SELL",
        "action": "清仓",
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_sma50), 2),
        "horizon": "mid",
    }


def check_s4_volume_price_divergence(
    close: pd.Series, volume: pd.Series, obv: pd.Series, mfi: pd.Series
) -> dict | None:
    """S4: 量价背离 (Volume-Price Divergence Sell)."""
    if len(close) < 25:
        return None

    # Price making new 20-day high
    curr_close = close.iloc[-1]
    high_20d = close.iloc[-20:].max()
    price_at_high = curr_close >= high_20d * 0.99

    if not price_at_high:
        return None

    # OBV NOT making new high
    curr_obv = obv.iloc[-1]
    obv_20d_high = obv.iloc[-20:].max()
    obv_diverging = curr_obv < obv_20d_high * 0.98  # OBV below its 20d high

    # Volume on up-days declining vs down-days
    up_days_vol = []
    down_days_vol = []
    for i in range(-10, 0):
        if close.iloc[i] > close.iloc[i - 1]:
            up_days_vol.append(volume.iloc[i])
        else:
            down_days_vol.append(volume.iloc[i])

    vol_weakness = False
    if up_days_vol and down_days_vol:
        avg_up_vol = np.mean(up_days_vol)
        avg_down_vol = np.mean(down_days_vol)
        vol_weakness = avg_up_vol < avg_down_vol

    # MFI trending down
    mfi_declining = False
    if len(mfi.dropna()) >= 10:
        mfi_5d_ago = mfi.iloc[-5]
        mfi_now = mfi.iloc[-1]
        if not pd.isna(mfi_5d_ago) and not pd.isna(mfi_now):
            mfi_declining = mfi_now < mfi_5d_ago

    if not (obv_diverging and (vol_weakness or mfi_declining)):
        return None

    conditions_met = [
        f"Price at 20-day high ${curr_close:.2f}",
        f"OBV NOT making new high (divergence: {curr_obv:.0f} vs peak {obv_20d_high:.0f})",
    ]
    if vol_weakness:
        conditions_met.append("Up-day volume < down-day volume (buyers thinning)")
    if mfi_declining:
        conditions_met.append("MFI declining despite rising price")

    return {
        "id": "S4",
        "name": "量价背离",
        "name_en": "Volume-Price Divergence Sell",
        "type": "SELL",
        "action": "减仓",
        "confidence": "MEDIUM",
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_close), 2),
        "horizon": "short",
    }


def check_s5_sustained_outflow(
    close: pd.Series, volume: pd.Series, money_flow_data: dict | None
) -> dict | None:
    """S5: 资金持续流出 (Sustained Outflow Sell). Requires money-flow-json."""
    if money_flow_data is None:
        return None

    streak_info = money_flow_data.get("streak_analysis", {})
    streak_type = streak_info.get("current_streak_type", "neutral")
    streak_days = streak_info.get("current_streak_days", 0)
    vol_trend = streak_info.get("current_streak_volume_trend", "flat")

    # Conditions
    consecutive_outflow = streak_type == "outflow" and streak_days >= 5
    if not consecutive_outflow:
        return None

    # Volume expanding during outflow
    vol_expanding = vol_trend == "rising"

    # Price breaking lower lows
    if len(close) < 10:
        return None
    lower_lows = close.iloc[-1] < close.iloc[-6:-1].min()

    if not (vol_expanding and lower_lows):
        return None

    conditions_met = [
        f"Consecutive outflow: {streak_days} days (>= 5)",
        "Volume expanding during outflow (放量出货)",
        f"Price ${close.iloc[-1]:.2f} breaking lower lows",
    ]

    return {
        "id": "S5",
        "name": "资金持续流出",
        "name_en": "Sustained Outflow Sell",
        "type": "SELL",
        "action": "清仓",
        "confidence": "HIGH",
        "conditions_met": conditions_met,
        "trigger_price": round(float(close.iloc[-1]), 2),
        "horizon": "mid",
    }


def check_s6_200sma_breakdown(
    close: pd.Series, volume: pd.Series, sma200: pd.Series
) -> dict | None:
    """S6: 跌破200日均线 (200-SMA Breakdown)."""
    if len(close) < 220 or len(sma200.dropna()) < 20:
        return None

    curr_close = close.iloc[-1]
    curr_sma200 = sma200.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = volume.iloc[-20:].mean()

    if pd.isna(curr_sma200):
        return None

    # Price below 200-SMA
    below_200 = curr_close < curr_sma200

    # Was above 200-SMA for at least 20 days prior
    above_prior = True
    for i in range(-21, -1):
        if close.iloc[i] < sma200.iloc[i]:
            above_prior = False
            break

    # Volume on breakdown
    vol_elevated = curr_vol > avg_vol

    # 200-SMA slope turning negative
    sma200_slope_neg = (
        sma200.iloc[-1] < sma200.iloc[-5] if len(sma200.dropna()) >= 5 else False
    )

    if not (below_200 and above_prior and vol_elevated):
        return None

    confidence = "HIGH" if sma200_slope_neg else "MEDIUM"

    conditions_met = [
        f"Price ${curr_close:.2f} closed below 200-SMA ${curr_sma200:.2f}",
        "Was above 200-SMA for 20+ consecutive days prior",
        f"Volume on breakdown: {curr_vol/avg_vol:.1f}x avg",
    ]
    if sma200_slope_neg:
        conditions_met.append("200-SMA slope turning negative (major trend change)")

    return {
        "id": "S6",
        "name": "跌破200日均线",
        "name_en": "200-SMA Breakdown",
        "type": "SELL",
        "action": "清仓",
        "confidence": confidence,
        "conditions_met": conditions_met,
        "trigger_price": round(float(curr_sma200), 2),
        "horizon": "mid",
    }


# ---------------------------------------------------------------------------
# Hold/Wait Signal Detection
# ---------------------------------------------------------------------------


def check_hold_signals(
    close: pd.Series,
    rsi: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
    volume: pd.Series,
    buy_signals: list,
    sell_signals: list,
) -> dict | None:
    """Check for H1 (no direction) or H2 (conflicting) signals."""
    if len(close) < 55:
        return None

    curr_close = close.iloc[-1]
    curr_rsi = rsi.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]

    # H2: Conflicting signals
    if buy_signals and sell_signals:
        return {
            "id": "H2",
            "name": "信号冲突",
            "name_en": "Conflicting Signals",
            "type": "HOLD",
            "action": "观望",
            "confidence": "LOW",
            "conditions_met": [
                f"{len(buy_signals)} buy signal(s) active: {[s['id'] for s in buy_signals]}",
                f"{len(sell_signals)} sell signal(s) active: {[s['id'] for s in sell_signals]}",
                "多空分歧, 等待确认",
            ],
            "trigger_price": round(float(curr_close), 2),
            "horizon": "short",
        }

    # H1: No clear signal
    if not buy_signals and not sell_signals:
        rsi_neutral = (40 <= curr_rsi <= 60) if not pd.isna(curr_rsi) else True
        between_smas = (
            min(curr_sma20, curr_sma50) <= curr_close <= max(curr_sma20, curr_sma50)
        )
        curr_vol = volume.iloc[-1]
        avg_vol = volume.iloc[-20:].mean()
        vol_average = 0.8 <= curr_vol / avg_vol <= 1.2

        if rsi_neutral or between_smas or vol_average:
            return {
                "id": "H1",
                "name": "无方向信号",
                "name_en": "No Clear Signal",
                "type": "HOLD",
                "action": "观望",
                "confidence": "LOW",
                "conditions_met": [
                    f"RSI = {curr_rsi:.1f} (neutral range 40-60)",
                    f"Price ${curr_close:.2f} between SMAs",
                    "No buy or sell signals firing",
                    "等待方向明确",
                ],
                "trigger_price": round(float(curr_close), 2),
                "horizon": "short",
            }

    return None


# ---------------------------------------------------------------------------
# Composite Signal Synthesis
# ---------------------------------------------------------------------------


def compute_key_levels(
    close: pd.Series,
    sma20: pd.Series,
    sma50: pd.Series,
    sma200: pd.Series,
    atr: pd.Series,
    high_52w: float,
    low_52w: float,
) -> dict:
    """Compute support/resistance levels."""
    curr_close = close.iloc[-1]
    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_sma200 = sma200.iloc[-1] if len(sma200.dropna()) > 0 else None
    curr_atr = atr.iloc[-1] if len(atr.dropna()) > 0 else curr_close * 0.02

    # Determine support levels (ordered by proximity below price)
    supports = []
    if not pd.isna(curr_sma20) and curr_sma20 < curr_close:
        supports.append(("20-SMA", curr_sma20))
    if not pd.isna(curr_sma50) and curr_sma50 < curr_close:
        supports.append(("50-SMA", curr_sma50))
    if (
        curr_sma200 is not None
        and not pd.isna(curr_sma200)
        and curr_sma200 < curr_close
    ):
        supports.append(("200-SMA", curr_sma200))

    supports.sort(key=lambda x: x[1], reverse=True)

    immediate_support = supports[0][1] if supports else curr_close - 2 * curr_atr
    major_support = supports[-1][1] if len(supports) > 1 else curr_close - 3 * curr_atr

    # Resistance levels
    resistances = []
    if not pd.isna(curr_sma20) and curr_sma20 > curr_close:
        resistances.append(("20-SMA", curr_sma20))
    if not pd.isna(curr_sma50) and curr_sma50 > curr_close:
        resistances.append(("50-SMA", curr_sma50))
    resistances.append(("52w-high", high_52w))
    resistances.sort(key=lambda x: x[1])

    immediate_resistance = (
        resistances[0][1] if resistances else curr_close + 2 * curr_atr
    )
    breakout_trigger = high_52w

    # ATR-based stop loss
    stop_loss = curr_close - 2 * curr_atr

    # Mean-reversion aware stop: tighten if price is extended far above 200MA
    if curr_sma200 is not None and not pd.isna(curr_sma200):
        pct_above = curr_close / curr_sma200 - 1.0
        if pct_above > 0.30:
            # Tighten stop: use max of ATR-based and extension-based
            ma_based_stop = curr_close * (1 - min(pct_above * 0.3, 0.15))
            stop_loss = max(stop_loss, ma_based_stop)

    return {
        "immediate_support": round(float(immediate_support), 2),
        "major_support": round(float(major_support), 2),
        "immediate_resistance": round(float(immediate_resistance), 2),
        "breakout_trigger": round(float(breakout_trigger), 2),
        "stop_loss_suggested": round(float(stop_loss), 2),
    }


def compute_risk_management(
    curr_close: float, atr: float, net_direction: str, sma200: float | None = None
) -> dict:
    """Compute risk management parameters with mean-reversion awareness."""
    if net_direction == "BUY":
        stop_loss = curr_close - 2 * atr
        # Mean-reversion aware stop tightening for BUY
        if sma200 and not pd.isna(sma200):
            pct_above = curr_close / sma200 - 1.0
            if pct_above > 0.30:
                ma_based_stop = sma200 * (1 + min(pct_above * 0.5, 0.30))
                stop_loss = max(stop_loss, ma_based_stop)
        risk = curr_close - stop_loss
        target_1 = curr_close + 2 * risk
        target_2 = curr_close + 3 * risk
        max_loss_pct = -round((risk / curr_close) * 100, 1)
        target_gain_pct = round((target_1 - curr_close) / curr_close * 100, 1)
        # Compute actual risk/reward from stop to target
        reward = target_1 - curr_close
        rr_ratio = round(reward / risk, 2) if risk > 0 else 2.0
    elif net_direction == "SELL":
        stop_loss = curr_close + 2 * atr
        risk = stop_loss - curr_close
        target_1 = curr_close - 2 * risk
        target_2 = curr_close - 3 * risk
        max_loss_pct = round((risk / curr_close) * 100, 1)
        target_gain_pct = -round((curr_close - target_1) / curr_close * 100, 1)
        reward = curr_close - target_1
        rr_ratio = round(reward / risk, 2) if risk > 0 else 2.0
    else:
        stop_loss = curr_close - 2 * atr
        # Mean-reversion aware stop tightening for HOLD
        if sma200 and not pd.isna(sma200):
            pct_above = curr_close / sma200 - 1.0
            if pct_above > 0.30:
                ma_based_stop = sma200 * (1 + min(pct_above * 0.5, 0.30))
                stop_loss = max(stop_loss, ma_based_stop)
        risk = curr_close - stop_loss
        target_1 = curr_close + risk
        target_2 = curr_close + 1.5 * risk
        max_loss_pct = -round((risk / curr_close) * 100, 1) if risk > 0 else 0.0
        target_gain_pct = round((target_1 - curr_close) / curr_close * 100, 1)
        reward = target_1 - curr_close
        rr_ratio = round(reward / risk, 2) if risk > 0 else 1.0

    return {
        "atr_stop": round(float(stop_loss), 2),
        "risk_reward_ratio": rr_ratio,
        "max_loss_pct": max_loss_pct,
        "target_gain_pct": target_gain_pct,
    }


def determine_net_direction(buy_signals: list, sell_signals: list) -> str:
    """Determine overall net signal direction."""
    if buy_signals and not sell_signals:
        return "BUY"
    elif sell_signals and not buy_signals:
        return "SELL"
    elif buy_signals and sell_signals:
        return "CONFLICTING"
    else:
        return "HOLD"


def determine_recommended_action(
    net_direction: str, buy_signals: list, sell_signals: list, hold_signal: dict | None
) -> dict:
    """Determine the recommended action with reasoning."""
    if net_direction == "BUY":
        # Check if any signal is 建仓 vs 加仓
        has_entry = any(s["action"] == "建仓" for s in buy_signals)
        high_conf = any(s["confidence"] == "HIGH" for s in buy_signals)
        action = "建仓" if has_entry else "加仓"
        confidence = "HIGH" if high_conf else "MEDIUM"

        # Determine horizon
        horizons = [s.get("horizon", "mid") for s in buy_signals]
        if "short" in horizons and "mid" in horizons:
            time_horizon = "short-to-mid (1-8周)"
        elif "short" in horizons:
            time_horizon = "short-term (1-3周)"
        else:
            time_horizon = "mid-term (2-8周)"

        signal_names = [s["name"] for s in buy_signals]
        reasoning = f"{'、'.join(signal_names)}同时触发，多重买入信号共振"

        sizing = (
            "可建仓至目标仓位的30%" if action == "建仓" else "可加仓至目标仓位的25%"
        )

        return {
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "position_sizing": sizing,
            "time_horizon": time_horizon,
        }

    elif net_direction == "SELL":
        has_exit = any(s["action"] == "清仓" for s in sell_signals)
        high_conf = any(s["confidence"] == "HIGH" for s in sell_signals)
        action = "清仓" if has_exit else "减仓"
        confidence = "HIGH" if high_conf else "MEDIUM"

        horizons = [s.get("horizon", "short") for s in sell_signals]
        if "mid" in horizons:
            time_horizon = "mid-term (趋势转弱)"
        else:
            time_horizon = "short-term (及时止损)"

        signal_names = [s["name"] for s in sell_signals]
        reasoning = f"{'、'.join(signal_names)}同时触发，卖出信号明确"

        sizing = "建议清仓离场" if action == "清仓" else "建议减仓50%"

        return {
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "position_sizing": sizing,
            "time_horizon": time_horizon,
        }

    elif net_direction == "CONFLICTING":
        return {
            "action": "观望",
            "confidence": "LOW",
            "reasoning": "买卖信号同时存在，多空分歧明显，等待方向确认",
            "position_sizing": "不宜加仓，可持有现有仓位",
            "time_horizon": "等待1-3日确认方向",
        }

    else:  # HOLD
        return {
            "action": "观望",
            "confidence": "LOW",
            "reasoning": "当前无明确方向性信号，等待突破或回调触发条件",
            "position_sizing": "维持现有仓位不动",
            "time_horizon": "持续监控，等待信号触发",
        }


def filter_by_horizon(signals: list, horizon: str) -> list:
    """Filter signals by time horizon."""
    if horizon == "both":
        return signals
    return [
        s for s in signals if s.get("horizon", "both") == horizon or horizon == "both"
    ]


# ---------------------------------------------------------------------------
# Main Analysis Function
# ---------------------------------------------------------------------------


def analyze_ticker(ticker: str, money_flow_data: dict | None, horizon: str) -> dict:
    """Run full signal analysis for a single ticker."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y", interval="1d")

        if hist.empty or len(hist) < 30:
            return {"error": f"Insufficient data for {ticker} (need >= 30 days)"}

        # Extract OHLCV
        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]

        curr_close = float(close.iloc[-1])

        # Compute all technical indicators
        sma20 = compute_sma(close, 20)
        sma50 = compute_sma(close, 50)
        sma200 = compute_sma(close, 200)
        rsi = compute_rsi(close, 14)
        bb_middle, bb_upper, bb_lower, bb_bandwidth, bb_position = compute_bollinger(
            close
        )
        macd_line, macd_signal, macd_hist = compute_macd(close)
        adx = compute_adx(high, low, close, 14)
        obv = compute_obv(close, volume)
        mfi = compute_mfi(high, low, close, volume, 14)
        cmf = compute_cmf(high, low, close, volume, 20)
        atr = compute_atr(high, low, close, 14)

        # 52-week high/low
        high_52w = float(high.max())
        low_52w = float(low.min())

        # Price context snapshot
        price_context = {
            "sma_20": round(float(sma20.iloc[-1]), 2)
            if not pd.isna(sma20.iloc[-1])
            else None,
            "sma_50": round(float(sma50.iloc[-1]), 2)
            if not pd.isna(sma50.iloc[-1])
            else None,
            "sma_200": round(float(sma200.iloc[-1]), 2)
            if len(sma200.dropna()) > 0 and not pd.isna(sma200.iloc[-1])
            else None,
            "rsi_14": round(float(rsi.iloc[-1]), 1)
            if not pd.isna(rsi.iloc[-1])
            else None,
            "macd_histogram": round(float(macd_hist.iloc[-1]), 3)
            if not pd.isna(macd_hist.iloc[-1])
            else None,
            "adx": round(float(adx.iloc[-1]), 1) if not pd.isna(adx.iloc[-1]) else None,
            "bollinger_position": round(float(bb_position.iloc[-1]), 2)
            if not pd.isna(bb_position.iloc[-1])
            else None,
            "atr_14": round(float(atr.iloc[-1]), 2)
            if not pd.isna(atr.iloc[-1])
            else None,
            "distance_52w_high_pct": round((curr_close - high_52w) / high_52w * 100, 1),
            "distance_52w_low_pct": round((curr_close - low_52w) / low_52w * 100, 1),
        }

        # Run all signal checks
        buy_signals_raw = []
        sell_signals_raw = []

        # BUY signals
        b1 = check_b1_volume_breakout(
            close, volume, sma20, sma50, mfi, cmf, money_flow_data
        )
        if b1:
            buy_signals_raw.append(b1)

        b2 = check_b2_oversold_reversal(close, volume, rsi, bb_lower, sma200)
        if b2:
            buy_signals_raw.append(b2)

        b3 = check_b3_golden_cross(close, volume, sma20, sma50, sma200, adx)
        if b3:
            buy_signals_raw.append(b3)

        b4 = check_b4_pullback_to_support(close, volume, rsi, sma20, sma50)
        if b4:
            buy_signals_raw.append(b4)

        b5 = check_b5_accumulation_coiling(close, bb_bandwidth, money_flow_data)
        if b5:
            buy_signals_raw.append(b5)

        b6 = check_b6_breakout_retest(close, volume, high_52w)
        if b6:
            buy_signals_raw.append(b6)

        # SELL signals
        s1 = check_s1_volume_breakdown(
            close, volume, sma20, sma50, mfi, obv, money_flow_data
        )
        if s1:
            sell_signals_raw.append(s1)

        s2 = check_s2_overbought_reversal(
            close, volume, rsi, bb_upper, macd_hist, sma200
        )
        if s2:
            sell_signals_raw.append(s2)

        s3 = check_s3_death_cross(close, volume, sma20, sma50, sma200, adx)
        if s3:
            sell_signals_raw.append(s3)

        s4 = check_s4_volume_price_divergence(close, volume, obv, mfi)
        if s4:
            sell_signals_raw.append(s4)

        s5 = check_s5_sustained_outflow(close, volume, money_flow_data)
        if s5:
            sell_signals_raw.append(s5)

        s6 = check_s6_200sma_breakdown(close, volume, sma200)
        if s6:
            sell_signals_raw.append(s6)

        # Filter by horizon
        buy_signals = filter_by_horizon(buy_signals_raw, horizon)
        sell_signals = filter_by_horizon(sell_signals_raw, horizon)

        # Overextension guard: suppress BUY signals when stock is >50% above 200MA
        # Affected signals: B1 (量价突破), B3 (金叉), B4 (回踩支撑), B5 (蓄势), B6 (突破回踩)
        overextension_suppressed_ids = {"B1", "B3", "B4", "B5", "B6"}
        if len(sma200.dropna()) > 0 and not pd.isna(sma200.iloc[-1]):
            curr_sma200_val = float(sma200.iloc[-1])
            if curr_sma200_val > 0:
                pct_above_200ma = (curr_close - curr_sma200_val) / curr_sma200_val * 100
                if pct_above_200ma > 50:
                    buy_signals = [
                        s
                        for s in buy_signals
                        if s["id"] not in overextension_suppressed_ids
                    ]

        # Determine net direction and action
        net_direction = determine_net_direction(buy_signals, sell_signals)

        # Overextension override: when >30% above 200MA, SELL dominates in conflict
        if net_direction == "CONFLICTING":
            if len(sma200.dropna()) > 0 and not pd.isna(sma200.iloc[-1]):
                _sma200_val = float(sma200.iloc[-1])
                if _sma200_val > 0:
                    _pct_above = (curr_close - _sma200_val) / _sma200_val
                    if _pct_above > 0.30:
                        net_direction = "SELL"

        # HOLD signal check
        hold_signal = check_hold_signals(
            close, rsi, sma20, sma50, volume, buy_signals, sell_signals
        )

        # Combine all active signals
        active_signals = buy_signals + sell_signals
        if hold_signal and not active_signals:
            active_signals.append(hold_signal)

        # Add invalidation and stop/target to each signal
        curr_atr = (
            float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else curr_close * 0.02
        )
        for sig in active_signals:
            if "invalidation" not in sig:
                trigger = sig.get("trigger_price", curr_close)
                if sig["type"] == "BUY":
                    inv_price = trigger - 2 * curr_atr
                    sig["invalidation"] = f"跌破${inv_price:.2f}则信号失效"
                    sig["stop_loss"] = round(inv_price, 2)
                    risk = curr_close - inv_price
                    sig["target_range"] = [
                        round(curr_close + 2 * risk, 2),
                        round(curr_close + 3 * risk, 2),
                    ]
                elif sig["type"] == "SELL":
                    inv_price = trigger + 2 * curr_atr
                    sig["invalidation"] = f"突破${inv_price:.2f}则卖出信号失效"
                    sig["stop_loss"] = round(inv_price, 2)
                    sig["target_range"] = [
                        round(curr_close - 2 * curr_atr, 2),
                        round(curr_close - 3 * curr_atr, 2),
                    ]
                else:
                    sig["invalidation"] = "等待方向确认"
                    sig["stop_loss"] = None
                    sig["target_range"] = None

        # Signal strength
        signal_strength = {
            "buy_signals_active": len(buy_signals),
            "sell_signals_active": len(sell_signals),
            "net": f"+{len(buy_signals)} (偏多)"
            if len(buy_signals) > len(sell_signals)
            else f"-{len(sell_signals)} (偏空)"
            if len(sell_signals) > len(buy_signals)
            else "0 (中性)",
        }

        # Recommended action
        recommended_action = determine_recommended_action(
            net_direction, buy_signals, sell_signals, hold_signal
        )

        # Key levels
        key_levels = compute_key_levels(
            close, sma20, sma50, sma200, atr, high_52w, low_52w
        )

        # Risk management
        curr_sma200_val = (
            float(sma200.iloc[-1])
            if len(sma200.dropna()) > 0 and not pd.isna(sma200.iloc[-1])
            else None
        )
        risk_mgmt = compute_risk_management(
            curr_close, curr_atr, net_direction, sma200=curr_sma200_val
        )

        # Historical signal context (simplified)
        # Find last direction change by scanning backwards
        trend_duration = 0
        if len(close) >= 50:
            for i in range(len(close) - 1, max(len(close) - 90, 0), -1):
                sma20_val = (
                    sma20.iloc[i]
                    if i < len(sma20) and not pd.isna(sma20.iloc[i])
                    else None
                )
                if sma20_val is None:
                    break
                if close.iloc[i] > sma20_val:
                    trend_duration += 1
                else:
                    break

        historical_context = {
            "signal_note": "First run — no prior signal history tracked",
            "trend_duration_days": trend_duration,
        }

        return {
            "current_price": round(curr_close, 2),
            "price_context": price_context,
            "active_signals": active_signals,
            "net_direction": net_direction,
            "signal_strength": signal_strength,
            "recommended_action": recommended_action,
            "key_levels": key_levels,
            "risk_management": risk_mgmt,
            "historical_signal_context": historical_context,
        }

    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate BUY/SELL/HOLD trade signals combining technical, "
        "flow, and fundamental triggers (多重条件共振)"
    )
    parser.add_argument(
        "tickers", nargs="+", help="Ticker symbols (e.g., AAPL MSFT NVDA)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--money-flow-json",
        help="Path to compute_money_flow.py output JSON (enriches signals)",
    )
    parser.add_argument(
        "--horizon",
        default="both",
        choices=["short", "mid", "both"],
        help="Signal horizon: short (days-weeks), mid (weeks-months), both (default)",
    )
    args = parser.parse_args()

    # Load money flow data if provided
    money_flow_all = None
    if args.money_flow_json:
        try:
            with open(args.money_flow_json, "r") as f:
                money_flow_all = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            sys.stderr.write(f"Warning: Could not load money-flow-json: {e}\n")

    results = {}
    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()

        # Extract per-ticker money flow data
        money_flow_data = None
        if money_flow_all:
            if ticker in money_flow_all:
                money_flow_data = money_flow_all[ticker]
            elif "results" in money_flow_all and ticker in money_flow_all["results"]:
                money_flow_data = money_flow_all["results"][ticker]

        results[ticker] = analyze_ticker(ticker, money_flow_data, args.horizon)

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "horizon": args.horizon,
        "results": results,
    }

    output_str = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_str)
    else:
        print(output_str)

    sys.exit(0)


if __name__ == "__main__":
    main()
