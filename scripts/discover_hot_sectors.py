#!/usr/bin/env python3
"""Discover today's hottest sectors/板块 using real-time momentum, volume, and breadth signals.

Usage:
    discover_hot_sectors.py                          # US market, top 10, all methods
    discover_hot_sectors.py --market cn              # A-share market
    discover_hot_sectors.py --market both            # US + A-shares combined
    discover_hot_sectors.py --top 5                  # Top 5 hottest sectors
    discover_hot_sectors.py --method momentum        # Only momentum-based discovery
    discover_hot_sectors.py --method volume          # Only volume spike detection
    discover_hot_sectors.py --method breadth         # Only breadth breakout analysis
    discover_hot_sectors.py --output ./reports/hot.json

This script answers "what's trending RIGHT NOW" vs "what performed best over 3 months."
It uses real-time (intraday/1D) price and volume data to identify sectors where capital
is actively flowing TODAY.

Discovery methods:
  1. Intraday/1D Momentum: 1D return (40%) + 5D return (30%) + volume spike (30%)
  2. Volume Spike Detection: today's volume / 20D avg — identifies unusual activity
  3. Breadth Breakout: new 5D highs + above all MAs + RSI > 60

Hot Score Categories:
  80-100: 极度热门 (Extremely Hot)
  60-79:  热门 (Hot)
  40-59:  温和 (Warm)
  20-39:  冷淡 (Cool)
  0-19:   冷门 (Cold)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
    import numpy as np
    import pandas as pd
except ImportError:
    sys.stderr.write(
        "Error: yfinance, numpy, pandas required. "
        "Run: pip install yfinance numpy pandas\n"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# ETF Universe Definitions
# ---------------------------------------------------------------------------

US_SECTOR_ETFS = {
    "Technology": {"etf": "XLK", "label": "科技", "category": "growth"},
    "Financials": {"etf": "XLF", "label": "金融", "category": "cyclical"},
    "Industrials": {"etf": "XLI", "label": "工业", "category": "cyclical"},
    "Consumer Discretionary": {
        "etf": "XLY",
        "label": "可选消费",
        "category": "cyclical",
    },
    "Communication Services": {"etf": "XLC", "label": "通信", "category": "growth"},
    "Health Care": {"etf": "XLV", "label": "医疗", "category": "defensive"},
    "Consumer Staples": {"etf": "XLP", "label": "必选消费", "category": "defensive"},
    "Energy": {"etf": "XLE", "label": "能源", "category": "cyclical"},
    "Utilities": {"etf": "XLU", "label": "公用事业", "category": "defensive"},
    "Materials": {"etf": "XLB", "label": "材料", "category": "cyclical"},
    "Real Estate": {"etf": "XLRE", "label": "房地产", "category": "cyclical"},
}

US_THEME_ETFS = {
    "Semiconductors": {"etf": "SMH", "label": "半导体", "category": "growth"},
    "Software": {"etf": "IGV", "label": "软件", "category": "growth"},
    "Cloud Computing": {"etf": "SKYY", "label": "云计算", "category": "growth"},
    "Cybersecurity": {"etf": "HACK", "label": "网络安全", "category": "growth"},
    "AI & Robotics": {"etf": "BOTZ", "label": "AI/机器人", "category": "growth"},
    "Biotech": {"etf": "XBI", "label": "生物科技", "category": "growth"},
    "Clean Energy": {"etf": "TAN", "label": "清洁能源", "category": "growth"},
    "Lithium/Battery": {"etf": "LIT", "label": "锂电池", "category": "growth"},
    "Homebuilders": {"etf": "XHB", "label": "房建", "category": "cyclical"},
    "Regional Banks": {"etf": "KRE", "label": "区域银行", "category": "cyclical"},
    "Oil & Gas E&P": {"etf": "XOP", "label": "油气勘探", "category": "cyclical"},
    "Gold Miners": {"etf": "GDX", "label": "黄金矿业", "category": "defensive"},
    "Uranium": {"etf": "URA", "label": "铀", "category": "growth"},
    "Defense": {"etf": "ITA", "label": "国防", "category": "cyclical"},
    "Internet": {"etf": "FDN", "label": "互联网", "category": "growth"},
}

A_SHARE_SECTOR_ETFS = {
    "半导体": {"etf": "512480.SS", "label": "半导体", "category": "growth"},
    "芯片": {"etf": "159995.SZ", "label": "芯片", "category": "growth"},
    "人工智能": {"etf": "515980.SS", "label": "人工智能", "category": "growth"},
    "机器人": {"etf": "562600.SS", "label": "机器人", "category": "growth"},
    "新能源车": {"etf": "515030.SS", "label": "新能源车", "category": "growth"},
    "光伏": {"etf": "515790.SS", "label": "光伏", "category": "growth"},
    "锂电池": {"etf": "561120.SS", "label": "锂电池", "category": "growth"},
    "军工": {"etf": "512660.SS", "label": "军工", "category": "cyclical"},
    "医药": {"etf": "512010.SS", "label": "医药", "category": "defensive"},
    "创新药": {"etf": "515120.SS", "label": "创新药", "category": "growth"},
    "白酒": {"etf": "512690.SS", "label": "白酒", "category": "cyclical"},
    "消费": {"etf": "159928.SZ", "label": "消费", "category": "cyclical"},
    "银行": {"etf": "512800.SS", "label": "银行", "category": "defensive"},
    "证券": {"etf": "512880.SS", "label": "证券", "category": "cyclical"},
    "保险": {"etf": "512070.SS", "label": "保险", "category": "defensive"},
    "地产": {"etf": "512200.SS", "label": "地产", "category": "cyclical"},
    "基建": {"etf": "516950.SS", "label": "基建", "category": "cyclical"},
    "稀土": {"etf": "516150.SS", "label": "稀土", "category": "cyclical"},
    "有色金属": {"etf": "512400.SS", "label": "有色金属", "category": "cyclical"},
    "钢铁": {"etf": "515210.SS", "label": "钢铁", "category": "cyclical"},
    "煤炭": {"etf": "515220.SS", "label": "煤炭", "category": "cyclical"},
    "电力": {"etf": "159611.SZ", "label": "电力", "category": "defensive"},
    "农业": {"etf": "159825.SZ", "label": "农业", "category": "defensive"},
    "游戏": {"etf": "159869.SZ", "label": "游戏", "category": "growth"},
    "传媒": {"etf": "512980.SS", "label": "传媒", "category": "growth"},
    "科创50": {"etf": "588000.SS", "label": "科创50", "category": "growth"},
    "创业板": {"etf": "159915.SZ", "label": "创业板", "category": "growth"},
}

# Hot score category thresholds
HOT_CATEGORIES = [
    (80, "极度热门"),
    (60, "热门"),
    (40, "温和"),
    (20, "冷淡"),
    (0, "冷门"),
]


def categorize_hot_score(score: float) -> str:
    """Map a hot score (0-100) to a Chinese category label."""
    score = max(0, min(100, score))
    for threshold, label in HOT_CATEGORIES:
        if score >= threshold:
            return label
    return "冷门"


# ---------------------------------------------------------------------------
# RSI Computation (inline)
# ---------------------------------------------------------------------------


def compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI for the latest bar using Wilder's smoothing."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)


# ---------------------------------------------------------------------------
# Batch Data Fetching
# ---------------------------------------------------------------------------


def fetch_batch_data(tickers: list, period: str = "3mo") -> pd.DataFrame | None:
    """Batch-download OHLCV data for multiple tickers via single yf.download() call."""
    if not tickers:
        return None
    try:
        data = yf.download(
            tickers,
            period=period,
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )
        if data is None or data.empty:
            return None
        return data
    except Exception as e:
        sys.stderr.write(f"Warning: Batch download failed: {e}\n")
        return None


def extract_ticker_data(
    batch_df: pd.DataFrame, ticker: str, all_tickers: list
) -> dict | None:
    """Extract Close and Volume arrays for a single ticker from batch data."""
    try:
        if len(all_tickers) == 1:
            close = batch_df["Close"].dropna().values
            volume = batch_df["Volume"].dropna().values
        else:
            if ticker not in batch_df.columns.get_level_values(0):
                return None
            ticker_df = batch_df[ticker]
            close = ticker_df["Close"].dropna().values
            volume = ticker_df["Volume"].dropna().values
        if len(close) < 2 or len(volume) < 2:
            return None
        return {"close": close.astype(float), "volume": volume.astype(float)}
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Method 1: Intraday/1D Momentum
# ---------------------------------------------------------------------------


def compute_momentum_scores(
    batch_df: pd.DataFrame, etf_map: dict, all_tickers: list, days: int = 1
) -> list:
    """Score each ETF by momentum. `days` controls focus window:
    days=1: weight 1D heavily (today's hot)
    days=5: weight 5D heavily (this week's hot)
    days=10+: weight 10D/20D heavily (recent trend)
    """
    # Adjust weights based on days parameter
    if days <= 1:
        w_1d, w_5d, w_vol = 0.40, 0.30, 0.30
    elif days <= 5:
        w_1d, w_5d, w_vol = 0.20, 0.50, 0.30
    elif days <= 10:
        w_1d, w_5d, w_vol = 0.10, 0.40, 0.50
    else:  # 20+
        w_1d, w_5d, w_vol = 0.05, 0.35, 0.60

    results = []
    for name, info in etf_map.items():
        ticker = info["etf"]
        data = extract_ticker_data(batch_df, ticker, all_tickers)
        if data is None:
            continue
        close, volume = data["close"], data["volume"]
        if len(close) < 2:
            continue

        ret_1d = (close[-1] / close[-2] - 1) * 100
        ret_5d = (close[-1] / close[-6] - 1) * 100 if len(close) >= 6 else ret_1d
        # Extended returns for longer lookbacks
        ret_nd = ret_1d
        if days >= 5 and len(close) >= days + 1:
            ret_nd = (close[-1] / close[-(days + 1)] - 1) * 100
        elif days >= 5:
            ret_nd = ret_5d

        vol_avg_20d = np.mean(volume[-20:]) if len(volume) >= 20 else np.mean(volume)
        volume_ratio = volume[-1] / vol_avg_20d if vol_avg_20d > 0 else 1.0

        # Normalize components to 0-10 scale
        m1d_norm = max(0, min(10, (ret_1d + 5) * 1.0))
        m5d_norm = max(0, min(10, (ret_nd + 10) * 0.5))
        vol_norm = max(0, min(10, (volume_ratio - 0.5) / 0.3))

        composite = m1d_norm * w_1d + m5d_norm * w_5d + vol_norm * w_vol
        results.append(
            {
                "name": name,
                "name_cn": info["label"],
                "etf_proxy": ticker,
                "category": info.get("category", "other"),
                "momentum_1d_pct": round(ret_1d, 2),
                "momentum_5d_pct": round(ret_5d, 2),
                "volume_ratio": round(volume_ratio, 2),
                "momentum_score": round(composite, 2),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Method 2: Volume Spike Detection
# ---------------------------------------------------------------------------


def detect_volume_spikes(
    batch_df: pd.DataFrame, etf_map: dict, all_tickers: list
) -> list:
    """Detect unusual volume activity: surge / bullish / selling / elevated / normal."""
    results = []
    for name, info in etf_map.items():
        ticker = info["etf"]
        data = extract_ticker_data(batch_df, ticker, all_tickers)
        if data is None:
            continue
        close, volume = data["close"], data["volume"]
        if len(close) < 2:
            continue

        ret_1d = (close[-1] / close[-2] - 1) * 100
        vol_avg_20d = np.mean(volume[-20:]) if len(volume) >= 20 else np.mean(volume)
        volume_ratio = volume[-1] / vol_avg_20d if vol_avg_20d > 0 else 1.0

        # Classify volume activity
        if volume_ratio > 2.0:
            vol_signal, vol_signal_cn = "sector_surge", "极端放量"
        elif volume_ratio > 1.5 and ret_1d > 0:
            vol_signal, vol_signal_cn = "bullish_attention", "看涨关注"
        elif volume_ratio > 1.5 and ret_1d < 0:
            vol_signal, vol_signal_cn = "selling_pressure", "卖压"
        elif volume_ratio > 1.5:
            vol_signal, vol_signal_cn = "elevated", "放量"
        else:
            vol_signal, vol_signal_cn = "normal", "正常"

        volume_score = max(0, min(10, (volume_ratio - 1.0) * 5.0))
        results.append(
            {
                "name": name,
                "name_cn": info["label"],
                "etf_proxy": ticker,
                "category": info.get("category", "other"),
                "volume_ratio": round(volume_ratio, 2),
                "return_1d_pct": round(ret_1d, 2),
                "volume_signal": vol_signal,
                "volume_signal_cn": vol_signal_cn,
                "volume_score": round(volume_score, 2),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Method 3: Breadth Breakout Detection
# ---------------------------------------------------------------------------


def detect_breadth_breakouts(
    batch_df: pd.DataFrame, etf_map: dict, all_tickers: list
) -> list:
    """Check: new 5-day high + above all MAs (5/10/20/50) + RSI > 60."""
    results = []
    for name, info in etf_map.items():
        ticker = info["etf"]
        data = extract_ticker_data(batch_df, ticker, all_tickers)
        if data is None:
            continue
        close = data["close"]
        if len(close) < 20:
            continue

        current = close[-1]
        # Condition 1: New 5-day high
        is_new_5d_high = current >= np.max(close[-5:]) * 0.999
        # Condition 2: Above ALL moving averages
        ma_5 = np.mean(close[-5:])
        ma_10 = np.mean(close[-10:])
        ma_20 = np.mean(close[-20:])
        ma_50 = np.mean(close[-50:]) if len(close) >= 50 else ma_20
        above_all_mas = (
            current > ma_5 and current > ma_10 and current > ma_20 and current > ma_50
        )
        # Condition 3: RSI > 60
        rsi = compute_rsi(close, period=14)
        is_rsi_bullish = rsi > 60

        conditions_met = sum([is_new_5d_high, above_all_mas, is_rsi_bullish])
        signals = {
            3: ("full_breakout", "全面突破"),
            2: ("bullish", "看涨"),
            1: ("mixed", "分化"),
            0: ("weak", "弱势"),
        }
        breadth_signal, breadth_signal_cn = signals[conditions_met]
        breadth_score = (conditions_met / 3.0) * 10.0

        results.append(
            {
                "name": name,
                "name_cn": info["label"],
                "etf_proxy": ticker,
                "category": info.get("category", "other"),
                "is_new_5d_high": bool(is_new_5d_high),
                "above_all_mas": bool(above_all_mas),
                "rsi": rsi,
                "is_rsi_bullish": is_rsi_bullish,
                "breadth_signal": breadth_signal,
                "breadth_signal_cn": breadth_signal_cn,
                "breadth_score": round(breadth_score, 2),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Composite Hot Score Calculation
# ---------------------------------------------------------------------------


def _determine_driver(ret_1d: float, vol_ratio: float, breadth: dict) -> str:
    """Determine the primary driver description for a sector's heat."""
    drivers = []
    if ret_1d > 3:
        drivers.append("强势单日突破")
    elif ret_1d > 1.5:
        drivers.append("日内动量领先")
    elif ret_1d < -3:
        drivers.append("大幅回调")
    elif ret_1d < -1.5:
        drivers.append("短期承压")

    if vol_ratio > 3.0:
        drivers.append("巨量资金涌入")
    elif vol_ratio > 2.0:
        drivers.append("成交量显著放大")
    elif vol_ratio > 1.5:
        drivers.append("资金关注度提升")

    if breadth and breadth.get("breadth_signal") == "full_breakout":
        drivers.append("板块全面突破")
    elif breadth and breadth.get("breadth_signal") == "bullish":
        drivers.append("多数标的走强")

    if not drivers:
        drivers.append(
            "温和上涨" if ret_1d > 0 else "温和回落" if ret_1d < 0 else "横盘整理"
        )
    return "，".join(drivers[:2])


def compute_hot_scores(
    momentum_results: list,
    volume_results: list,
    breadth_results: list,
    method: str = "all",
) -> list:
    """Compute composite hot score (0-100) per sector from all discovery methods.

    Formula: hot_score = (momentum_1d*0.35 + momentum_5d*0.25 +
                          volume*0.25 + breadth*0.15) * 10
    Bonuses: +10 if 1D > 3%, +10 if volume > 3x, +20 if both.
    """
    momentum_map = {r["name"]: r for r in momentum_results}
    volume_map = {r["name"]: r for r in volume_results}
    breadth_map = {r["name"]: r for r in breadth_results}

    all_sectors = set()
    all_sectors.update(momentum_map.keys(), volume_map.keys(), breadth_map.keys())

    scored = []
    for name in all_sectors:
        mom = momentum_map.get(name, {})
        vol = volume_map.get(name, {})
        brd = breadth_map.get(name, {})
        base = mom or vol or brd
        if not base:
            continue

        # Extract component scores (0-10 scale)
        ret_1d = mom.get("momentum_1d_pct", 0)
        ret_5d = mom.get("momentum_5d_pct", 0)
        m1d_score = max(0, min(10, (ret_1d + 5) * 1.0)) if mom else 0
        m5d_score = max(0, min(10, (ret_5d + 10) * 0.5)) if mom else 0
        vol_score = vol.get("volume_score", 0) if vol else 0
        brd_score = brd.get("breadth_score", 0) if brd else 0

        # Composite based on method
        if method == "momentum":
            hot_score = (m1d_score * 0.55 + m5d_score * 0.45) * 10
        elif method == "volume":
            hot_score = vol_score * 10
        elif method == "breadth":
            hot_score = brd_score * 10
        else:
            hot_score = (
                m1d_score * 0.35
                + m5d_score * 0.25
                + vol_score * 0.25
                + brd_score * 0.15
            ) * 10

        # Bonuses for extreme signals
        vol_ratio_val = vol.get("volume_ratio", 1.0) if vol else 1.0
        bonus = 0
        if abs(ret_1d) > 3:
            bonus += 10
        if vol_ratio_val > 3.0:
            bonus += 10
        hot_score = min(100, hot_score + bonus)

        scored.append(
            {
                "name": name,
                "name_cn": base.get("name_cn", name),
                "etf_proxy": base.get("etf_proxy", ""),
                "category": base.get("category", "other"),
                "hot_score": round(hot_score, 1),
                "momentum_1d_pct": round(ret_1d, 2) if mom else None,
                "momentum_5d_pct": round(ret_5d, 2) if mom else None,
                "volume_ratio": round(vol_ratio_val, 2) if vol else None,
                "volume_signal": vol.get("volume_signal") if vol else None,
                "breadth_signal": brd.get("breadth_signal") if brd else None,
                "rsi": brd.get("rsi") if brd else None,
                "driver": _determine_driver(ret_1d, vol_ratio_val, brd),
                "hot_category": categorize_hot_score(hot_score),
            }
        )

    scored.sort(key=lambda x: x["hot_score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Rotation Signal Detection
# ---------------------------------------------------------------------------

ROTATION_PATTERNS = {
    ("growth", "defensive"): "资金从防御板块流向成长板块，风险偏好回升",
    ("growth", "cyclical"): "资金从周期板块流向成长板块，追逐高成长",
    ("defensive", "growth"): "资金从成长板块流向防御板块，避险情绪升温",
    ("defensive", "cyclical"): "资金从周期板块流向防御板块，经济预期转弱",
    ("cyclical", "growth"): "资金从成长板块流向周期板块，价值轮动",
    ("cyclical", "defensive"): "资金从防御板块流向周期板块，经济扩张预期",
}


def detect_rotation_signal(scored_sectors: list) -> dict:
    """Detect sector rotation by comparing top-3 hottest vs bottom-3 coldest."""
    if len(scored_sectors) < 6:
        return {
            "from": "N/A",
            "to": "N/A",
            "strength": "INSUFFICIENT_DATA",
            "interpretation": "数据不足，无法判断轮动方向",
        }

    top_3 = scored_sectors[:3]
    bottom_3 = scored_sectors[-3:]

    # Count category distribution
    hot_cats = {}
    for s in top_3:
        cat = s.get("category", "other")
        hot_cats[cat] = hot_cats.get(cat, 0) + 1
    cold_cats = {}
    for s in bottom_3:
        cat = s.get("category", "other")
        cold_cats[cat] = cold_cats.get(cat, 0) + 1

    hot_dominant = max(hot_cats, key=hot_cats.get) if hot_cats else "other"
    cold_dominant = max(cold_cats, key=cold_cats.get) if cold_cats else "other"

    # Strength from score spread
    top_avg = np.mean([s["hot_score"] for s in top_3])
    bottom_avg = np.mean([s["hot_score"] for s in bottom_3])
    spread = top_avg - bottom_avg
    if spread > 50:
        strength, strength_cn = "STRONG", "强"
    elif spread > 30:
        strength, strength_cn = "MODERATE", "中等"
    else:
        strength, strength_cn = "WEAK", "弱"

    # Interpret rotation
    key = (hot_dominant, cold_dominant)
    if key in ROTATION_PATTERNS:
        interpretation = f"{ROTATION_PATTERNS[key]}（{strength_cn}）"
    else:
        interpretation = f"板块轮动方向不明确，热门={hot_dominant}，冷门={cold_dominant}（{strength_cn}）"

    return {
        "from": ", ".join([s["name_cn"] for s in bottom_3]),
        "to": ", ".join([s["name_cn"] for s in top_3]),
        "hot_dominant_category": hot_dominant,
        "cold_dominant_category": cold_dominant,
        "strength": strength,
        "spread": round(spread, 1),
        "interpretation": interpretation,
    }


# ---------------------------------------------------------------------------
# A-Share Discovery (akshare integration)
# ---------------------------------------------------------------------------


def discover_ashare_sectors_akshare() -> list | None:
    """Discover hot A-share sectors via akshare 概念板块/行业板块 real-time data."""
    try:
        import akshare as ak
    except ImportError:
        sys.stderr.write("Info: akshare not available, falling back to ETF proxies\n")
        return None

    results = []
    # 概念板块实时行情
    try:
        concept_df = ak.stock_board_concept_name_em()
        if concept_df is not None and not concept_df.empty:
            for _, row in concept_df.head(30).iterrows():
                name = str(row.get("板块名称", ""))
                change_pct = float(row.get("涨跌幅", 0))
                turnover = float(row.get("成交额", 0))
                up_limit = int(row.get("涨停家数", 0)) if "涨停家数" in row.index else 0

                hot_score = max(0, min(100, (change_pct + 5) * 10))
                if up_limit > 5:
                    hot_score = min(100, hot_score + 15)
                elif up_limit > 2:
                    hot_score = min(100, hot_score + 8)

                results.append(
                    {
                        "name": name,
                        "name_cn": name,
                        "etf_proxy": "概念板块",
                        "category": "concept",
                        "hot_score": round(hot_score, 1),
                        "momentum_1d_pct": round(change_pct, 2),
                        "momentum_5d_pct": None,
                        "volume_ratio": None,
                        "volume_signal": None,
                        "breadth_signal": None,
                        "rsi": None,
                        "driver": f"涨停{up_limit}家" if up_limit > 0 else "板块动量",
                        "hot_category": categorize_hot_score(hot_score),
                        "up_limit_count": up_limit,
                        "turnover": turnover,
                    }
                )
    except Exception as e:
        sys.stderr.write(f"Warning: akshare concept board fetch failed: {e}\n")

    # 行业板块实时行情
    try:
        industry_df = ak.stock_board_industry_name_em()
        if industry_df is not None and not industry_df.empty:
            for _, row in industry_df.head(20).iterrows():
                name = str(row.get("板块名称", ""))
                change_pct = float(row.get("涨跌幅", 0))
                turnover = float(row.get("成交额", 0))
                hot_score = max(0, min(100, (change_pct + 5) * 10))

                results.append(
                    {
                        "name": name,
                        "name_cn": name,
                        "etf_proxy": "行业板块",
                        "category": "industry",
                        "hot_score": round(hot_score, 1),
                        "momentum_1d_pct": round(change_pct, 2),
                        "momentum_5d_pct": None,
                        "volume_ratio": None,
                        "volume_signal": None,
                        "breadth_signal": None,
                        "rsi": None,
                        "driver": "行业动量",
                        "hot_category": categorize_hot_score(hot_score),
                        "up_limit_count": 0,
                        "turnover": turnover,
                    }
                )
    except Exception as e:
        sys.stderr.write(f"Warning: akshare industry board fetch failed: {e}\n")

    if not results:
        return None
    results.sort(key=lambda x: x["hot_score"], reverse=True)
    return results


def discover_ashare_sectors_etf(
    batch_df: pd.DataFrame, all_tickers: list, method: str = "all"
) -> list:
    """Fallback: discover hot A-share sectors via ETF proxy method."""
    momentum_results, volume_results, breadth_results = [], [], []
    if method in ("all", "momentum"):
        momentum_results = compute_momentum_scores(
            batch_df, A_SHARE_SECTOR_ETFS, all_tickers
        )
    if method in ("all", "volume"):
        volume_results = detect_volume_spikes(
            batch_df, A_SHARE_SECTOR_ETFS, all_tickers
        )
    if method in ("all", "breadth"):
        breadth_results = detect_breadth_breakouts(
            batch_df, A_SHARE_SECTOR_ETFS, all_tickers
        )
    return compute_hot_scores(momentum_results, volume_results, breadth_results, method)


# ---------------------------------------------------------------------------
# Data Freshness Check
# ---------------------------------------------------------------------------


def check_data_freshness(batch_df: pd.DataFrame) -> dict:
    """Check if fetched data includes today's trading session."""
    if batch_df is None or batch_df.empty:
        return {"is_fresh": False, "latest_date": None, "warning": "No data available"}

    latest_date = batch_df.index[-1]
    today = pd.Timestamp.now(tz="UTC").normalize()
    if latest_date.tzinfo is None:
        latest_date = latest_date.tz_localize("UTC")

    days_stale = (today - latest_date).days
    if days_stale == 0:
        return {
            "is_fresh": True,
            "latest_date": str(latest_date.date()),
            "warning": None,
        }
    elif days_stale <= 3:
        return {
            "is_fresh": True,
            "latest_date": str(latest_date.date()),
            "warning": f"最新数据为{days_stale}天前（可能为周末/假日）",
        }
    else:
        return {
            "is_fresh": False,
            "latest_date": str(latest_date.date()),
            "warning": f"数据已过期{days_stale}天，市场可能休市",
        }


# ---------------------------------------------------------------------------
# Summary Generation
# ---------------------------------------------------------------------------


def generate_summary_cn(hot_sectors: list, cold_sectors: list) -> str:
    """Generate a Chinese one-line summary of today's hot/cold sectors."""
    hot_parts = []
    for s in hot_sectors[:3]:
        ret = s.get("momentum_1d_pct")
        hot_parts.append(
            f"{s['name_cn']}({ret:+.1f}%)" if ret is not None else s["name_cn"]
        )

    cold_parts = []
    for s in cold_sectors[:3]:
        ret = s.get("momentum_1d_pct")
        cold_parts.append(
            f"{s['name_cn']}({ret:+.1f}%)" if ret is not None else s["name_cn"]
        )

    summary = f"今日最热: {', '.join(hot_parts)}"
    if cold_parts:
        summary += f"; 最冷: {', '.join(cold_parts)}"
    return summary


# ---------------------------------------------------------------------------
# Main Discovery Pipeline
# ---------------------------------------------------------------------------


def discover_us_market(method: str = "all", top_n: int = 10, days: int = 1) -> dict:
    """Run the full US market hot sector discovery pipeline."""
    all_etfs = {**US_SECTOR_ETFS, **US_THEME_ETFS}
    all_tickers = [info["etf"] for info in all_etfs.values()]

    sys.stderr.write(f"Fetching {len(all_tickers)} US ETFs (days={days})...\n")
    batch_df = fetch_batch_data(all_tickers, period="3mo")

    if batch_df is None:
        return {
            "error": "Failed to fetch US market data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    freshness = check_data_freshness(batch_df)

    # Run discovery methods
    momentum_results, volume_results, breadth_results = [], [], []
    if method in ("all", "momentum"):
        momentum_results = compute_momentum_scores(
            batch_df, all_etfs, all_tickers, days=days
        )
    if method in ("all", "volume"):
        volume_results = detect_volume_spikes(batch_df, all_etfs, all_tickers)
    if method in ("all", "breadth"):
        breadth_results = detect_breadth_breakouts(batch_df, all_etfs, all_tickers)

    scored = compute_hot_scores(
        momentum_results, volume_results, breadth_results, method
    )
    if not scored:
        return {
            "error": "No sectors scored — possible market holiday",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_freshness": freshness,
        }

    hot_sectors = scored[:top_n]
    cold_sectors = scored[-top_n:] if len(scored) > top_n else scored[top_n:]
    for i, s in enumerate(hot_sectors):
        s["rank"] = i + 1
    for i, s in enumerate(cold_sectors):
        s["rank"] = i + 1

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": "us",
        "discovery_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "days_focus": days,
        "method": method,
        "data_freshness": freshness,
        "total_sectors_analyzed": len(scored),
        "hot_sectors": hot_sectors,
        "cold_sectors": cold_sectors,
        "rotation_signal": detect_rotation_signal(scored),
        "summary_cn": generate_summary_cn(hot_sectors, cold_sectors),
    }


def discover_cn_market(method: str = "all", top_n: int = 10, days: int = 1) -> dict:
    """Run the full A-share market hot sector discovery pipeline."""
    # Try akshare first (real-time, higher quality)
    akshare_results = discover_ashare_sectors_akshare()

    if akshare_results is not None and len(akshare_results) > 0:
        source = "akshare"
        scored = akshare_results
    else:
        source = "etf_proxy"
        all_tickers = [info["etf"] for info in A_SHARE_SECTOR_ETFS.values()]
        sys.stderr.write(f"Fetching {len(all_tickers)} A-share ETFs...\n")
        batch_df = fetch_batch_data(all_tickers, period="3mo")
        if batch_df is None:
            return {
                "error": "Failed to fetch A-share data (akshare + ETF both failed)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        scored = discover_ashare_sectors_etf(batch_df, all_tickers, method)

    if not scored:
        return {
            "error": "No A-share sectors scored",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    hot_sectors = scored[:top_n]
    cold_sectors = scored[-top_n:] if len(scored) > top_n else scored[top_n:]
    for i, s in enumerate(hot_sectors):
        s["rank"] = i + 1
    for i, s in enumerate(cold_sectors):
        s["rank"] = i + 1

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": "cn",
        "discovery_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "method": method,
        "data_source": source,
        "total_sectors_analyzed": len(scored),
        "hot_sectors": hot_sectors,
        "cold_sectors": cold_sectors,
        "rotation_signal": detect_rotation_signal(scored),
        "summary_cn": generate_summary_cn(hot_sectors, cold_sectors),
    }


def discover_both_markets(method: str = "all", top_n: int = 10, days: int = 1) -> dict:
    """Run discovery for both US and A-share markets."""
    us_result = discover_us_market(method=method, top_n=top_n, days=days)
    cn_result = discover_cn_market(method=method, top_n=top_n, days=days)

    # Cross-market analysis
    us_hot = us_result.get("hot_sectors", [])
    cn_hot = cn_result.get("hot_sectors", [])
    us_labels = {s.get("name_cn", ""): s for s in us_hot[:5]}
    cn_labels = {s.get("name_cn", ""): s for s in cn_hot[:5]}
    common_themes = [label for label in us_labels if label in cn_labels]

    us_cats = [s.get("category", "other") for s in us_hot[:5]]
    cn_cats = [s.get("category", "other") for s in cn_hot[:5]]
    us_growth = us_cats.count("growth")
    cn_growth = cn_cats.count("growth")

    if us_growth >= 3 and cn_growth >= 3:
        sentiment = "全球成长风格共振"
    elif us_growth >= 3 and cn_growth < 2:
        sentiment = "美股偏成长，A股偏周期/防御，风格分化"
    elif us_growth < 2 and cn_growth >= 3:
        sentiment = "A股偏成长，美股偏周期/防御，风格分化"
    else:
        sentiment = "两市风格类似，无明显分化"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": "both",
        "discovery_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "method": method,
        "us_market": us_result,
        "cn_market": cn_result,
        "cross_market_insight": {
            "common_hot_themes": common_themes,
            "us_dominant_style": "growth" if us_growth >= 3 else "cyclical/defensive",
            "cn_dominant_style": "growth" if cn_growth >= 3 else "cyclical/defensive",
            "cross_market_sentiment": sentiment,
        },
    }


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main():
    """Main entry point with argparse CLI."""
    parser = argparse.ArgumentParser(
        description="Discover today's hottest sectors using real-time signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # US market, all methods, top 10
  %(prog)s --market cn              # A-share market hot sectors
  %(prog)s --market both --top 5    # Both markets, top 5 each
  %(prog)s --method momentum        # Momentum-only scoring
  %(prog)s --output ./hot.json      # Save to file

Hot Score Categories:
  80-100: 极度热门 (Extremely Hot)
  60-79:  热门 (Hot)
  40-59:  温和 (Warm)
  20-39:  冷淡 (Cool)
  0-19:   冷门 (Cold)
        """,
    )
    parser.add_argument(
        "--market",
        choices=["us", "cn", "both"],
        default="us",
        help="Market to discover: us (default), cn (A-shares), both",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of hot sectors to return (default: 10)",
    )
    parser.add_argument(
        "--method",
        choices=["all", "momentum", "volume", "breadth"],
        default="all",
        help="Discovery method (default: all)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Momentum focus window in days: 1=today (default), 5=this week, 10=recent 2 weeks, 20=this month. "
        "Controls which timeframe is weighted most heavily for 'hot' ranking.",
    )
    args = parser.parse_args()

    # Run discovery
    if args.market == "us":
        result = discover_us_market(method=args.method, top_n=args.top, days=args.days)
    elif args.market == "cn":
        result = discover_cn_market(method=args.method, top_n=args.top, days=args.days)
    else:
        result = discover_both_markets(
            method=args.method, top_n=args.top, days=args.days
        )

    # Output
    result_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result_json)
        sys.stderr.write(f"Output written to: {args.output}\n")
    else:
        print(result_json)

    sys.exit(0)


if __name__ == "__main__":
    main()
