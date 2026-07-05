#!/usr/bin/env python3
"""Fetch theme/style ETF performance data for market breadth analysis.

Usage:
    fetch_theme_performance.py                  # Full theme report
    fetch_theme_performance.py --output out.json

Fetches daily performance across theme ETFs and style factors for
market regime detection (risk-on/off, growth/value, sector rotation).

Output: JSON with 1D/5D/1M returns per ETF group.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    sys.stderr.write("Error: yfinance required. Run: pip install yfinance\n")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    sys.stderr.write("Error: pandas required\n")
    sys.exit(1)

# --- ETF Universe ---

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLV": "Healthcare",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
}

THEME_ETFS = {
    "semiconductors": {"tickers": ["SMH", "SOXX"], "label": "Semiconductors"},
    "software": {"tickers": ["IGV"], "label": "Software"},
    "cybersecurity": {"tickers": ["CIBR", "HACK"], "label": "Cybersecurity"},
    "cloud": {"tickers": ["CLOU", "WCLD"], "label": "Cloud Computing"},
    "ai_robotics": {"tickers": ["BOTZ", "AIQ"], "label": "AI & Robotics"},
    "fintech": {"tickers": ["FINX", "ARKF"], "label": "Fintech"},
    "biotech": {"tickers": ["XBI", "IBB"], "label": "Biotech"},
}

STYLE_ETFS = {
    "large_growth": {"tickers": ["QQQ", "SCHG", "VUG"], "label": "Large Cap Growth"},
    "large_value": {"tickers": ["VTV", "SCHV", "VYM"], "label": "Large Cap Value"},
    "small_growth": {"tickers": ["IWO"], "label": "Small Cap Growth"},
    "small_value": {"tickers": ["IWN"], "label": "Small Cap Value"},
    "equal_weight": {"tickers": ["RSP"], "label": "Equal Weight S&P 500"},
    "dividend": {"tickers": ["SCHD", "VYM"], "label": "Dividend"},
}

MACRO_ETFS = {
    "treasuries_20y": {"tickers": ["TLT"], "label": "20Y+ Treasuries"},
    "treasuries_7_10y": {"tickers": ["IEF"], "label": "7-10Y Treasuries"},
    "tips": {"tickers": ["TIP"], "label": "TIPS (Inflation-Protected)"},
    "high_yield": {"tickers": ["HYG", "JNK"], "label": "High Yield Credit"},
    "inv_grade": {"tickers": ["LQD"], "label": "Investment Grade Credit"},
    "gold": {"tickers": ["GLD"], "label": "Gold"},
    "oil": {"tickers": ["USO"], "label": "Oil"},
    "dollar": {"tickers": ["UUP"], "label": "US Dollar"},
    "volatility": {"tickers": ["VXX"], "label": "Volatility Futures"},
}

SPECIALTY_ETFS = {
    "homebuilders": {"tickers": ["XHB", "ITB"], "label": "Homebuilders"},
    "regional_banks": {"tickers": ["KRE"], "label": "Regional Banks"},
    "metals_mining": {"tickers": ["XME"], "label": "Metals & Mining"},
    "energy_exploration": {"tickers": ["XOP"], "label": "Oil & Gas Exploration"},
    "retail": {"tickers": ["XRT"], "label": "Retail"},
    "transport": {"tickers": ["XTN", "IYT"], "label": "Transportation"},
    "solar": {"tickers": ["TAN"], "label": "Solar Energy"},
    "clean_energy": {"tickers": ["ICLN"], "label": "Clean Energy"},
    "uranium": {"tickers": ["URA"], "label": "Uranium"},
    "nuclear": {"tickers": ["NLR"], "label": "Nuclear Energy"},
    "infrastructure": {"tickers": ["PAVE", "IFRA"], "label": "Infrastructure"},
}

INDEX_TICKERS = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "DIA": "Dow Jones ETF",
    "MDY": "S&P MidCap 400 ETF",
}

INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^DJI": "Dow Jones Industrial",
    "^RUT": "Russell 2000",
    "^VIX": "CBOE Volatility Index",
    "^TNX": "10Y Treasury Yield",
    "^TYX": "30Y Treasury Yield",
}

# Treasury yields direct mapping
TREASURY_TICKERS = {
    "^IRX": "13-Week T-Bill",
    "^FVX": "5Y Treasury Yield",
    "^TNX": "10Y Treasury Yield",
    "^TYX": "30Y Treasury Yield",
}


def _flatten_etf_map(etf_map: dict) -> list[tuple[str, str]]:
    """Normalize either {ticker: label} or {key: {tickers: [...], label: ...}}
    into a list of (ticker, label) pairs."""
    pairs: list[tuple[str, str]] = []
    for key, value in etf_map.items():
        if isinstance(value, dict) and "tickers" in value:
            label = value.get("label", key)
            for t in value["tickers"]:
                pairs.append((t, label))
        else:
            pairs.append((key, str(value)))
    return pairs


def fetch_etf_group(etf_map: dict, group_name: str) -> list[dict]:
    """Fetch performance data for a group of ETFs."""
    results = []
    for ticker, label in _flatten_etf_map(etf_map):
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo")
            if hist.empty or len(hist) < 2:
                results.append(
                    {
                        "ticker": ticker,
                        "label": label,
                        "error": "No data",
                    }
                )
                continue

            closes = hist["Close"]
            current = float(closes.iloc[-1])

            ret_1d = (
                (current / float(closes.iloc[-2]) - 1) * 100
                if len(closes) >= 2
                else None
            )
            ret_5d = (
                (current / float(closes.iloc[-5]) - 1) * 100
                if len(closes) >= 5
                else None
            )
            ret_1m = (
                (current / float(closes.iloc[0]) - 1) * 100
                if len(closes) >= 20
                else None
            )

            # Volume trend
            volumes = hist["Volume"]
            avg_vol_5d = float(volumes.iloc[-5:].mean()) if len(volumes) >= 5 else None
            avg_vol_20d = (
                float(volumes.iloc[-20:].mean()) if len(volumes) >= 20 else None
            )
            vol_ratio = avg_vol_5d / avg_vol_20d if avg_vol_5d and avg_vol_20d else None

            results.append(
                {
                    "ticker": ticker,
                    "label": label,
                    "close": round(current, 2),
                    "ret_1d": round(ret_1d, 2) if ret_1d is not None else None,
                    "ret_5d": round(ret_5d, 2) if ret_5d is not None else None,
                    "ret_1m": round(ret_1m, 2) if ret_1m is not None else None,
                    "vol_ratio_5d_vs_20d": round(vol_ratio, 2) if vol_ratio else None,
                }
            )
        except Exception as e:
            results.append(
                {
                    "ticker": ticker,
                    "label": label,
                    "error": str(e),
                }
            )
    return results


def fetch_index_data(index_map: dict) -> list[dict]:
    """Fetch index OHLCV data."""
    results = []
    for ticker, name in index_map.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo")
            if hist.empty:
                results.append({"ticker": ticker, "name": name, "error": "No data"})
                continue

            closes = hist["Close"]
            current = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
            ret_1d = (current / prev - 1) * 100 if prev else None
            ret_5d = (
                (current / float(closes.iloc[-5]) - 1) * 100
                if len(closes) >= 5
                else None
            )
            ret_1m = (
                (current / float(closes.iloc[0]) - 1) * 100
                if len(closes) >= 20
                else None
            )

            high_1m = float(hist["High"].max())
            low_1m = float(hist["Low"].min())

            # Compute SMAs
            sma_20 = float(closes.iloc[-20:].mean()) if len(closes) >= 20 else None
            sma_50 = float(closes.iloc[-50:].mean()) if len(closes) >= 50 else None
            sma_200 = float(closes.iloc[-200:].mean()) if len(closes) >= 200 else None

            # RSI-14
            rsi = None
            if len(closes) >= 15:
                delta = closes.diff()
                gain = delta.where(delta > 0, 0.0)
                loss = (-delta).where(delta < 0, 0.0)
                avg_gain = gain.iloc[-14:].mean()
                avg_loss = loss.iloc[-14:].mean()
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = round(100 - (100 / (1 + rs)), 1)

            # Volume
            latest_vol = (
                float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else None
            )
            avg_vol_20d = (
                float(hist["Volume"].iloc[-20:].mean())
                if "Volume" in hist.columns and len(hist) >= 20
                else None
            )

            above_sma20 = current > sma_20 if sma_20 else None
            above_sma50 = current > sma_50 if sma_50 else None
            above_sma200 = current > sma_200 if sma_200 else None

            results.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "close": round(current, 2),
                    "ret_1d": round(ret_1d, 2) if ret_1d is not None else None,
                    "ret_5d": round(ret_5d, 2) if ret_5d is not None else None,
                    "ret_1m": round(ret_1m, 2) if ret_1m is not None else None,
                    "high_1m": round(high_1m, 2),
                    "low_1m": round(low_1m, 2),
                    "sma_20": round(sma_20, 2) if sma_20 else None,
                    "sma_50": round(sma_50, 2) if sma_50 else None,
                    "sma_200": round(sma_200, 2) if sma_200 else None,
                    "rsi_14": rsi,
                    "above_sma20": above_sma20,
                    "above_sma50": above_sma50,
                    "above_sma200": above_sma200,
                    "latest_volume": int(latest_vol) if latest_vol else None,
                    "avg_volume_20d": int(avg_vol_20d) if avg_vol_20d else None,
                }
            )
        except Exception as e:
            results.append({"ticker": ticker, "name": name, "error": str(e)})
    return results


def compute_regime_summary(
    sectors: list[dict],
    themes: list[dict],
    styles: list[dict],
    indices: list[dict],
) -> dict:
    """Compute market regime summary from ETF/index data."""

    def _best_ticker(group: list[dict], label: str) -> float | None:
        for item in group:
            if item.get("error"):
                continue
            return item.get("ret_1d")
        return None

    def _find_idx(indices_list: list[dict], ticker: str) -> dict | None:
        for item in indices_list:
            if item.get("ticker") == ticker:
                return item
        return None

    # Growth vs Value
    growth_ret = _best_ticker(styles, "Large Cap Growth")
    value_ret = _best_ticker(styles, "Large Cap Value")

    # Tech vs Broad
    qqq_item = _find_idx(indices, "^IXIC")
    spy_item = _find_idx(indices, "^GSPC")
    nasdaq_ret = qqq_item.get("ret_1d") if qqq_item else None
    sp500_ret = spy_item.get("ret_1d") if spy_item else None

    # Sector leaders/laggards
    sector_sorted = sorted(
        [s for s in sectors if s.get("ret_1d") is not None],
        key=lambda x: x.get("ret_1d", 0),
        reverse=True,
    )
    leaders = [s["label"] for s in sector_sorted[:3]] if sector_sorted else []
    laggards = (
        [s["label"] for s in sector_sorted[-3:]] if len(sector_sorted) >= 3 else []
    )

    # Theme leaders
    theme_sorted = sorted(
        [t for t in themes if t.get("ret_1d") is not None],
        key=lambda x: x.get("ret_1d", 0),
        reverse=True,
    )
    theme_leaders = [t["label"] for t in theme_sorted[:3]] if theme_sorted else []

    # VIX
    vix_item = _find_idx(indices, "^VIX")
    vix_level = vix_item.get("close") if vix_item else None

    # Regime signals
    signals = []
    if growth_ret is not None and value_ret is not None:
        if growth_ret > value_ret + 0.3:
            signals.append("Growth outperforming Value — risk-on posture")
        elif value_ret > growth_ret + 0.3:
            signals.append("Value outperforming Growth — defensive rotation")

    if nasdaq_ret is not None and sp500_ret is not None:
        if nasdaq_ret > sp500_ret + 0.5:
            signals.append("Tech leading broad market — AI/tech dominance")
        elif sp500_ret > nasdaq_ret + 0.5:
            signals.append(
                "Broad market leading tech — rotation away from mega-cap tech"
            )

    if vix_level is not None:
        if vix_level < 15:
            signals.append("VIX below 15 — complacency / low volatility regime")
        elif vix_level > 25:
            signals.append("VIX above 25 — elevated fear / risk-off")

    return {
        "growth_vs_value": {
            "growth_1d": growth_ret,
            "value_1d": value_ret,
            "bias": "growth" if (growth_ret or 0) > (value_ret or 0) else "value",
        },
        "tech_vs_broad": {
            "nasdaq_1d": nasdaq_ret,
            "sp500_1d": sp500_ret,
            "bias": "tech" if (nasdaq_ret or 0) > (sp500_ret or 0) else "broad",
        },
        "sector_leaders": leaders,
        "sector_laggards": laggards,
        "theme_leaders": theme_leaders,
        "vix_level": vix_level,
        "signals": signals,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch theme/style ETF performance for market regime detection"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--groups",
        default="all",
        help="Comma-separated groups: sectors,themes,styles,macro,specialty,indices (default: all)",
    )
    args = parser.parse_args()

    groups = (
        args.groups.split(",")
        if args.groups != "all"
        else [
            "sectors",
            "themes",
            "styles",
            "macro",
            "specialty",
            "indices",
        ]
    )

    result = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
    }

    if "sectors" in groups:
        result["sectors"] = fetch_etf_group(SECTOR_ETFS, "sectors")

    if "themes" in groups:
        result["themes"] = fetch_etf_group(THEME_ETFS, "themes")

    if "styles" in groups:
        result["styles"] = fetch_etf_group(STYLE_ETFS, "styles")

    if "macro" in groups:
        result["macro"] = fetch_etf_group(MACRO_ETFS, "macro")

    if "specialty" in groups:
        result["specialty"] = fetch_etf_group(SPECIALTY_ETFS, "specialty")

    if "indices" in groups:
        result["indices"] = fetch_index_data(INDICES)
        result["treasuries"] = fetch_index_data(TREASURY_TICKERS)

    # Compute regime summary
    result["regime_summary"] = compute_regime_summary(
        result.get("sectors", []),
        result.get("themes", []),
        result.get("styles", []),
        result.get("indices", []),
    )

    output = json.dumps(result, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
