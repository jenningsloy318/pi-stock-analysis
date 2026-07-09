#!/usr/bin/env python3
"""Fetch market breadth indicators for US stock market analysis.

Usage:
    fetch_market_breadth.py                    # Full breadth report
    fetch_market_breadth.py --universe sp500   # S&P 500 only
    fetch_market_breadth.py --universe all     # S&P 500 + Nasdaq 100
    fetch_market_breadth.py --output out.json

Fetches market-wide breadth indicators including:
  - % stocks above 20/50/200-day moving averages
  - Advance/decline ratios
  - New 52-week highs/lows
  - Up/down volume ratios
  - McClellan Oscillator (approximation)
  - VIX term structure (spot vs futures)

Data sources: yfinance (constituent data), CBOE (VIX)

Output: JSON to stdout or --output file.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
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

# --- Constituent Lists ---

# Fallback S&P 500 list (top 200 by market cap, updated 2025)
_SP500_FALLBACK = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "BRK-B",
    "AVGO",
    "JPM",
    "LLY",
    "V",
    "UNH",
    "XOM",
    "MA",
    "JNJ",
    "PG",
    "HD",
    "COST",
    "WMT",
    "ABBV",
    "CVX",
    "MRK",
    "BAC",
    "NFLX",
    "KO",
    "ADBE",
    "CRM",
    "PEP",
    "AMD",
    "TMO",
    "ORCL",
    "LIN",
    "ACN",
    "CSCO",
    "MCD",
    "ABT",
    "WFC",
    "DHR",
    "QCOM",
    "GE",
    "INTU",
    "IBM",
    "PM",
    "CAT",
    "AMGN",
    "VZ",
    "TXN",
    "NOW",
    "DIS",
    "NEE",
    "SPGI",
    "RTX",
    "UBER",
    "PFE",
    "LOW",
    "AMAT",
    "UNP",
    "GS",
    "ISRG",
    "AXP",
    "CMCSA",
    "BKNG",
    "HON",
    "T",
    "ELV",
    "TJX",
    "LRCX",
    "SCHW",
    "BLK",
    "MS",
    "SYK",
    "BSX",
    "MU",
    "C",
    "PLD",
    "ETN",
    "CB",
    "ADI",
    "MMC",
    "INTC",
    "PANW",
    "MDT",
    "PLTR",
    "KLAC",
    "AMT",
    "DE",
    "LMT",
    "UPS",
    "CI",
    "SO",
    "MDLZ",
    "ANET",
    "BMY",
    "SNPS",
    "MO",
    "NKE",
    "DUK",
    "TT",
    "ICE",
    "BX",
    "CDNS",
    "BA",
    "WM",
    "GILD",
    "CL",
    "SHW",
    "MCO",
    "CME",
    "MCK",
    "CRWD",
    "ITW",
    "PH",
    "APH",
    "EQIX",
    "CMG",
    "ZTS",
    "APD",
    "TDG",
    "MSI",
    "CVS",
    "HCA",
    "GD",
    "AON",
    "CTAS",
    "REGN",
    "PYPL",
    "USB",
    "PNC",
    "EOG",
    "MMM",
    "WELL",
    "ORLY",
    "FCX",
    "FDX",
    "MAR",
    "CSX",
    "CEG",
    "ROP",
    "TGT",
    "NSC",
    "DHI",
    "ECL",
    "AJG",
    "HLT",
    "KKR",
    "COF",
    "PSA",
    "SLB",
    "BDX",
    "CARR",
    "MCHP",
    "EMR",
    "O",
    "NOC",
    "AFL",
    "TFC",
    "WMB",
    "NXPI",
    "DLR",
    "ADSK",
    "TRV",
    "AZO",
    "PCAR",
    "VST",
    "SRE",
    "OKE",
    "LEN",
    "GM",
]

# S&P 500 tickers from Wikipedia (cached, refreshed on fetch)
_SP500_CACHE: list[str] | None = None
_NDX100_CACHE: list[str] | None = None


def get_sp500_tickers() -> list[str]:
    """Get current S&P 500 constituents from Wikipedia, with fallback."""
    global _SP500_CACHE
    if _SP500_CACHE is not None:
        return _SP500_CACHE
    try:
        table = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        df = table[0]
        tickers = df["Symbol"].tolist()
        _SP500_CACHE = [t.replace(".", "-") for t in tickers]
        return _SP500_CACHE
    except Exception as e:
        sys.stderr.write(f"Wikipedia S&P 500 fetch failed: {e}, using fallback list\n")
        _SP500_CACHE = _SP500_FALLBACK
        return _SP500_CACHE


def get_nasdaq100_tickers() -> list[str]:
    """Get current Nasdaq 100 constituents from Wikipedia."""
    global _NDX100_CACHE
    if _NDX100_CACHE is not None:
        return _NDX100_CACHE
    try:
        table = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        # Find the constituents table
        for df in table:
            if "Ticker" in df.columns or "Symbol" in df.columns:
                col = "Ticker" if "Ticker" in df.columns else "Symbol"
                _NDX100_CACHE = df[col].tolist()
                return _NDX100_CACHE
        return []
    except Exception as e:
        sys.stderr.write(f"Failed to fetch Nasdaq 100 constituents: {e}\n")
        return []


# --- Breadth Computation ---


def compute_breadth(tickers: list[str], label: str, max_stocks: int = 500) -> dict:
    """Compute breadth indicators for a universe of stocks.

    Args:
        tickers: List of ticker symbols
        label: Universe name (e.g., 'S&P 500')
        max_stocks: Max stocks to process (for performance)

    Returns:
        Dict with breadth indicators
    """
    if not tickers:
        return {"error": f"No tickers for {label}", "universe": label}

    # Limit for performance
    sample = tickers[:max_stocks]
    total = len(sample)

    # Fetch OHLCV in bulk
    try:
        data = yf.download(
            sample,
            period="1y",
            interval="1d",
            progress=False,
            group_by="ticker",
            threads=True,
            auto_adjust=True,
        )
    except Exception as e:
        return {"error": f"Download failed: {e}", "universe": label}

    if data.empty:
        return {"error": "No data returned", "universe": label}

    # Handle single ticker vs multi ticker
    if len(sample) == 1:
        closes = data["Close"]
        volumes = data["Volume"] if "Volume" in data.columns else None
        all_closes = {sample[0]: closes}
        all_volumes = {sample[0]: volumes} if volumes is not None else {}
    else:
        all_closes = {}
        all_volumes = {}
        for t in sample:
            try:
                all_closes[t] = data[t]["Close"]
                if "Volume" in data[t].columns:
                    all_volumes[t] = data[t]["Volume"]
            except (KeyError, TypeError):
                pass

    # Compute % above MAs
    above_20 = 0
    above_50 = 0
    above_200 = 0
    advances = 0
    declines = 0
    new_highs = 0
    new_lows = 0
    up_volume = 0.0
    down_volume = 0.0
    total_stocks_with_data = 0
    a_d_diffs = []

    for t, closes in all_closes.items():
        closes = closes.dropna()
        if len(closes) < 2:
            continue

        total_stocks_with_data += 1
        latest = closes.iloc[-1]
        prev = closes.iloc[-2]

        # SMA computation
        if len(closes) >= 20:
            sma20 = closes.iloc[-20:].mean()
            if latest > sma20:
                above_20 += 1

        if len(closes) >= 50:
            sma50 = closes.iloc[-50:].mean()
            if latest > sma50:
                above_50 += 1

        if len(closes) >= 200:
            sma200 = closes.iloc[-200:].mean()
            if latest > sma200:
                above_200 += 1

        # Advance/Decline (daily change)
        if latest > prev:
            advances += 1
        elif latest < prev:
            declines += 1

        # New highs/lows (52-week)
        if len(closes) >= 252:
            high_52w = closes.iloc[-252:].max()
            low_52w = closes.iloc[-252:].min()
            if latest >= high_52w * 0.995:  # within 0.5% of 52w high
                new_highs += 1
            if latest <= low_52w * 1.005:  # within 0.5% of 52w low
                new_lows += 1

        # Volume analysis
        if t in all_volumes:
            vol = all_volumes[t].dropna()
            if len(vol) >= 2:
                latest_vol = vol.iloc[-1]
                if latest > prev:
                    up_volume += latest_vol
                elif latest < prev:
                    down_volume += latest_vol

        # For McClellan Oscillator: daily A-D difference
        if len(closes) >= 2:
            a_d_diffs.append(1 if latest > prev else (-1 if latest < prev else 0))

    if total_stocks_with_data == 0:
        return {"error": "No stocks with data", "universe": label}

    # Ratios
    total_movers = advances + declines
    advance_decline_ratio = advances / declines if declines > 0 else float("inf")
    advance_pct = (advances / total_movers * 100) if total_movers > 0 else 50

    ad_line = advances - declines  # Daily net

    # McClellan Oscillator: 19-day EMA of A-D minus 39-day EMA of A-D
    mcclellan = None
    if len(a_d_diffs) >= 39:
        ad_series = pd.Series(a_d_diffs)
        ema_19 = ad_series.ewm(span=19, adjust=False).mean()
        ema_39 = ad_series.ewm(span=39, adjust=False).mean()
        mcclellan = round(float(ema_19.iloc[-1] - ema_39.iloc[-1]), 2)

    # Volume ratio
    total_volume = up_volume + down_volume
    up_volume_pct = (up_volume / total_volume * 100) if total_volume > 0 else 50

    return {
        "universe": label,
        "stocks_analyzed": total_stocks_with_data,
        "stocks_total": total,
        "above_sma_20_pct": round(above_20 / total_stocks_with_data * 100, 1),
        "above_sma_50_pct": round(above_50 / total_stocks_with_data * 100, 1),
        "above_sma_200_pct": round(above_200 / total_stocks_with_data * 100, 1),
        "advances": advances,
        "declines": declines,
        "unchanged": total_stocks_with_data - advances - declines,
        "advance_decline_ratio": round(advance_decline_ratio, 2)
        if declines > 0
        else None,
        "advance_pct": round(advance_pct, 1),
        "ad_line_net": ad_line,
        "mcclellan_oscillator": mcclellan,
        "new_52w_highs": new_highs,
        "new_52w_lows": new_lows,
        "high_low_ratio": round(new_highs / new_lows, 2) if new_lows > 0 else None,
        "up_volume_pct": round(up_volume_pct, 1),
        "breadth_signal": _breadth_signal(
            above_20 / max(total_stocks_with_data, 1),
            advance_pct / 100,
            new_highs,
            new_lows,
        ),
    }


def _breadth_signal(
    above_20_pct: float,
    advance_pct: float,
    new_highs: int,
    new_lows: int,
) -> str:
    """Classify breadth signal from indicators."""
    bullish = 0
    bearish = 0

    if above_20_pct > 0.65:
        bullish += 1
    elif above_20_pct < 0.30:
        bearish += 1

    if advance_pct > 0.55:
        bullish += 1
    elif advance_pct < 0.45:
        bearish += 1

    if new_highs > new_lows * 2:
        bullish += 1
    elif new_lows > new_highs * 2:
        bearish += 1

    if bullish >= 3:
        return "strong_bullish"
    elif bullish >= 1:
        return "moderate_bullish"
    elif bearish >= 3:
        return "strong_bearish"
    elif bearish >= 1:
        return "moderate_bearish"
    return "neutral"


# --- VIX & Volatility ---


def fetch_vix_data() -> dict:
    """Fetch VIX and volatility-related indicators."""
    result = {}

    try:
        # VIX spot
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1mo")
        if not hist.empty:
            closes = hist["Close"]
            result["vix_spot"] = round(float(closes.iloc[-1]), 2)
            result["vix_5d_ago"] = (
                round(float(closes.iloc[-5]), 2) if len(closes) >= 5 else None
            )
            result["vix_1m_high"] = round(float(hist["High"].max()), 2)
            result["vix_1m_low"] = round(float(hist["Low"].min()), 2)
            result["vix_change_5d"] = (
                round(float((closes.iloc[-1] / closes.iloc[-5] - 1) * 100), 1)
                if len(closes) >= 5
                else None
            )
    except Exception:
        pass

    # VIX futures term structure via VIXM (mid-term) and VIX3M
    try:
        for ticker, label in [
            ("^VIX", "spot"),
            ("VXZ", "mid_term"),
            ("VXX", "short_term"),
        ]:
            t = yf.Ticker(ticker)
            h = t.history(period="5d")
            if not h.empty:
                result[f"vix_{label}_last"] = round(float(h["Close"].iloc[-1]), 2)
    except Exception:
        pass

    # Contango/backwardation signal
    if result.get("vix_spot") and result.get("vix_mid_term_last"):
        spot = result["vix_spot"]
        mid = result["vix_mid_term_last"]
        result["vix_term_structure"] = "contango" if mid > spot else "backwardation"
        result["vix_futures_premium"] = round((mid / spot - 1) * 100, 1)

    # VVIX (volatility of VIX) via SVXY or direct calculation
    try:
        svxy = yf.Ticker("SVXY")
        h = svxy.history(period="5d")
        if not h.empty:
            result["svxy_price"] = round(float(h["Close"].iloc[-1]), 2)
            result["svxy_change_1d"] = (
                round(float((h["Close"].iloc[-1] / h["Close"].iloc[-2] - 1) * 100), 1)
                if len(h) >= 2
                else None
            )
    except Exception:
        pass

    return result


# --- Credit & Bond Market ---


def fetch_credit_spreads() -> dict:
    """Fetch credit spread indicators."""
    result = {}
    credit_etfs = {
        "HYG": "high_yield_etf",
        "LQD": "investment_grade_etf",
        "JNK": "high_yield_etf_2",
        "TLT": "long_term_treasury",
        "IEF": "intermediate_treasury",
        "TIP": "tips_etf",
    }

    for ticker, key in credit_etfs.items():
        try:
            t = yf.Ticker(ticker)
            h = t.history(period="1mo")
            if not h.empty and len(h) >= 2:
                closes = h["Close"]
                current = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                ret_1d = round((current / prev - 1) * 100, 2)
                ret_5d = (
                    round((current / float(closes.iloc[-5]) - 1) * 100, 2)
                    if len(closes) >= 5
                    else None
                )
                result[key] = {
                    "price": round(current, 2),
                    "ret_1d": ret_1d,
                    "ret_5d": ret_5d,
                }
        except Exception:
            pass

    # High yield spread proxy: HYG yield - TLT yield (or price relationship)
    if "high_yield_etf" in result and "long_term_treasury" in result:
        hyg_ret = result["high_yield_etf"]["ret_1d"]
        tlt_ret = result["long_term_treasury"]["ret_1d"]
        result["credit_risk_signal"] = "risk_on" if hyg_ret > tlt_ret else "risk_off"
        result["hyg_tlt_spread_1d"] = round(hyg_ret - tlt_ret, 2)

    return result


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Fetch market breadth indicators")
    parser.add_argument(
        "--universe",
        default="sp500",
        choices=["sp500", "nasdaq100", "all"],
        help="Stock universe for breadth calculation (default: sp500)",
    )
    parser.add_argument(
        "--max-stocks",
        type=int,
        default=500,
        help="Max stocks to process per universe (default: 500)",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--skip-constituents",
        action="store_true",
        help="Skip breadth computation (faster, VIX/credit only)",
    )
    args = parser.parse_args()

    result = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "breadth": {},
        "volatility": {},
        "credit": {},
    }

    # Breadth for selected universes
    if not args.skip_constituents:
        if args.universe in ("sp500", "all"):
            sp500 = get_sp500_tickers()
            if sp500:
                sys.stderr.write(
                    f"Computing S&P 500 breadth ({len(sp500)} stocks)...\n"
                )
                result["breadth"]["sp500"] = compute_breadth(
                    sp500, "S&P 500", args.max_stocks
                )

        if args.universe in ("nasdaq100", "all"):
            ndx = get_nasdaq100_tickers()
            if ndx:
                sys.stderr.write(
                    f"Computing Nasdaq 100 breadth ({len(ndx)} stocks)...\n"
                )
                result["breadth"]["nasdaq100"] = compute_breadth(
                    ndx, "Nasdaq 100", min(args.max_stocks, 100)
                )

    # VIX and volatility
    sys.stderr.write("Fetching VIX and volatility data...\n")
    result["volatility"] = fetch_vix_data()

    # Credit spreads
    sys.stderr.write("Fetching credit spread data...\n")
    result["credit"] = fetch_credit_spreads()

    # Overall breadth summary
    if result["breadth"]:
        signals = []
        for universe, data in result["breadth"].items():
            if "breadth_signal" in data:
                signals.append(
                    f"{data.get('universe', universe)}: {data['breadth_signal']}"
                )

        result["breadth_summary"] = {
            "signals": signals,
            "overall": _overall_breadth(result["breadth"]),
        }

    output = json.dumps(result, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)


def _overall_breadth(breadths: dict) -> str:
    """Compute overall breadth assessment."""
    bullish = 0
    bearish = 0
    for data in breadths.values():
        signal = data.get("breadth_signal", "neutral")
        if "bullish" in signal:
            bullish += 1
        elif "bearish" in signal:
            bearish += 1

    if bullish > bearish:
        return "bullish"
    elif bearish > bullish:
        return "bearish"
    return "mixed"


if __name__ == "__main__":
    main()
