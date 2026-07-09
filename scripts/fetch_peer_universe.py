#!/usr/bin/env python3
"""Build a peer universe for a given ticker — automated peer identification.

Usage:
    fetch_peer_universe.py AAPL                          # Find peers via GICS + industry
    fetch_peer_universe.py AAPL --source gics            # GICS sub-industry peers
    fetch_peer_universe.py AAPL --source etf             # ETF-holding-based peers
    fetch_peer_universe.py AAPL --source all --max 20    # Combined approach
    fetch_peer_universe.py AAPL --output ./reports/[TICKER]/peers.json

Sources:
  - GICS: yfinance sector/industry classification -> sub-industry peers
  - ETF: Top sector ETF holdings -> market-cap neighbors
  - Description: Company description similarity (fuzzy matching fallback)

Output: Ranked peer list with market cap, sector, industry, and peer relevance score.
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: yfinance required. Run: pip install yfinance\n")
    sys.exit(1)


# Pre-built sector ETF → GICS sectors mapping
SECTOR_ETF_MAP = {
    "Technology": ["XLK", "VGT", "QQQ"],
    "Financials": ["XLF", "VFH"],
    "Healthcare": ["XLV", "VHT", "IBB"],
    "Consumer Discretionary": ["XLY", "VCR"],
    "Communication Services": ["XLC", "VOX"],
    "Industrials": ["XLI", "VIS"],
    "Energy": ["XLE", "VDE"],
    "Consumer Staples": ["XLP", "VDC"],
    "Utilities": ["XLU", "VPU"],
    "Real Estate": ["XLRE", "VNQ"],
    "Materials": ["XLB", "VAW"],
}

# S&P 500 constituent list for universe fallback
SP500_TICKERS = None  # Lazy-loaded


def get_sp500_tickers() -> list[str]:
    """Get current S&P 500 constituents."""
    global SP500_TICKERS
    if SP500_TICKERS is not None:
        return SP500_TICKERS
    try:
        # Wikipedia has a regularly updated table
        import pandas as pd
        table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        SP500_TICKERS = table[0]["Symbol"].str.replace(".", "-").tolist()
        return SP500_TICKERS
    except Exception:
        # Fallback: use yfinance on SPY holdings
        try:
            spy = yf.Ticker("SPY")
            holdings = spy.get_institutional_holders()
            # This won't work well; use a static fallback
        except Exception:
            pass
        SP500_TICKERS = []
        return SP500_TICKERS


def get_company_info(ticker: str) -> dict:
    """Get company sector, industry, market cap, and description from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "ticker": ticker,
            "name": info.get("shortName", info.get("longName", "")),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "revenue": info.get("totalRevenue"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "description": info.get("longBusinessSummary", ""),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country", ""),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def find_gics_peers(ticker_info: dict) -> list[str]:
    """Find peers by GICS industry classification using yfinance sector/industry lookups.

    This searches across S&P 500 constituents for companies in the same industry.
    """
    industry = ticker_info.get("industry", "")
    sector = ticker_info.get("sector", "")

    if not industry and not sector:
        return []

    sp500 = get_sp500_tickers()
    peers = []

    # Check all S&P 500 names (can be slow; sample approach)
    candidates = sp500[:100] if len(sp500) > 100 else sp500  # Sample for speed

    for candidate_ticker in candidates:
        if candidate_ticker == ticker_info["ticker"]:
            continue
        try:
            info = get_company_info(candidate_ticker)
            if info.get("error"):
                continue
            # Match by industry first (more specific), then sector
            if industry and info.get("industry") == industry:
                peers.append(candidate_ticker)
            elif sector and info.get("sector") == sector:
                # Only add sector-level peers if we don't have enough industry peers
                peers.append(candidate_ticker)
        except Exception:
            continue

    return peers


def find_etf_peers(ticker: str, ticker_info: dict) -> list[str]:
    """Find peers from sector ETF holdings — market-cap-adjacent companies.

    Uses yfinance .funds_data.top_holdings when available. The previous
    implementation called .get_institutional_holders() (institutional shareholders
    of the ETF, not its constituent holdings) and never appended to peers, so
    every call returned [].
    """
    sector = ticker_info.get("sector", "")
    sector_etfs = SECTOR_ETF_MAP.get(sector, [])

    if not sector_etfs:
        return []

    peers: set[str] = set()
    self_ticker = (ticker_info.get("ticker") or ticker or "").upper()

    for etf_ticker in sector_etfs[:2]:  # Limit to 2 ETFs for speed
        try:
            etf = yf.Ticker(etf_ticker)
            holdings_df = None

            funds_data = getattr(etf, "funds_data", None)
            if funds_data is not None:
                top_holdings = getattr(funds_data, "top_holdings", None)
                if top_holdings is not None:
                    holdings_df = top_holdings

            if holdings_df is not None and hasattr(holdings_df, "index"):
                for sym in list(holdings_df.index)[:25]:
                    sym_str = str(sym).upper().strip()
                    if sym_str and sym_str != self_ticker:
                        peers.add(sym_str)
        except Exception:
            continue

    return sorted(peers)


def find_description_peers(ticker_info: dict, universe: list[str], max_results: int = 10) -> list[str]:
    """Find peers by company description keyword similarity.

    Simple keyword overlap approach — not NLP-based but fast and transparent.
    """
    desc = ticker_info.get("description", "").lower()
    if not desc:
        return []

    # Extract keywords from company description (simple approach)
    keywords = set()
    for word in desc.split():
        word = word.strip(".,;:()[]{}'\"")
        if len(word) > 4 and word not in ("company", "business", "companies", "including", "through"):
            keywords.add(word)

    # Score candidates by keyword overlap
    scores = []
    for candidate_ticker in universe[:50]:  # Sample for speed
        if candidate_ticker == ticker_info["ticker"]:
            continue
        try:
            info = get_company_info(candidate_ticker)
            if info.get("error"):
                continue
            cand_desc = info.get("description", "").lower()
            if not cand_desc:
                continue
            overlap = len(keywords & set(cand_desc.split()))
            if overlap > 3:  # Minimum keyword overlap
                scores.append((candidate_ticker, overlap, info))
        except Exception:
            continue

    scores.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scores[:max_results]]


def rank_peers(peers: list[str], ticker_info: dict) -> list[dict]:
    """Rank peers by relevance: market cap proximity, industry match, size similarity."""
    target_mcap = ticker_info.get("market_cap")
    target_sector = ticker_info.get("sector", "")
    target_industry = ticker_info.get("industry", "")

    ranked = []
    for peer_ticker in peers:
        info = get_company_info(peer_ticker)
        if info.get("error"):
            continue

        score = 0.0

        # Industry match: +3 points
        if info.get("industry") == target_industry:
            score += 3.0
        elif info.get("sector") == target_sector:
            score += 1.5

        # Market cap proximity: +0 to +2 points
        if target_mcap and info.get("market_cap"):
            ratio = min(target_mcap, info["market_cap"]) / max(target_mcap, info["market_cap"])
            score += ratio * 2.0

        ranked.append({
            "ticker": peer_ticker,
            "name": info.get("name", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("market_cap"),
            "pe_ratio": info.get("pe_ratio"),
            "forward_pe": info.get("forward_pe"),
            "relevance_score": round(score, 2),
            "source": "gics" if info.get("industry") == target_industry else "sector",
        })

    ranked.sort(key=lambda x: x["relevance_score"], reverse=True)
    return ranked


def main():
    parser = argparse.ArgumentParser(
        description="Build automated peer universe for a stock ticker"
    )
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument("--source", choices=["gics", "etf", "description", "all"], default="all",
                        help="Peer discovery method")
    parser.add_argument("--max", type=int, default=15, dest="max_peers",
                        help="Maximum peers to return")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--fetch-metrics", action="store_true",
                        help="Also fetch key financial metrics for each peer")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    # Get target company info
    ticker_info = get_company_info(ticker)
    if "error" in ticker_info:
        print(f"Error fetching data for {ticker}: {ticker_info['error']}", file=sys.stderr)
        sys.exit(1)

    # Discover peers
    peers = set()
    sp500 = get_sp500_tickers()
    universe = sp500 if sp500 else [ticker]  # Fallback to just the ticker

    if args.source in ("gics", "all"):
        gics_peers = find_gics_peers(ticker_info)
        peers.update(gics_peers)

    if args.source in ("etf", "all"):
        etf_peers = find_etf_peers(ticker, ticker_info)
        peers.update(etf_peers)

    if args.source in ("description", "all") and len(peers) < 5:
        desc_peers = find_description_peers(ticker_info, universe, args.max_peers)
        peers.update(desc_peers)

    # Rank and limit
    ranked = rank_peers(list(peers), ticker_info)
    ranked = ranked[:args.max_peers]

    result = {
        "target": {
            "ticker": ticker,
            "name": ticker_info.get("name"),
            "sector": ticker_info.get("sector"),
            "industry": ticker_info.get("industry"),
            "market_cap": ticker_info.get("market_cap"),
            "pe_ratio": ticker_info.get("pe_ratio"),
        },
        "peers": ranked,
        "peer_count": len(ranked),
        "sources_used": args.source,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "Peers identified by GICS industry match → ETF holding overlap → description keyword similarity. "
                       "Ranked by industry proximity + market cap similarity.",
        "usage": "Feed this peer universe to calculate_metrics.py --peers for relative valuation comparison.",
    }

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
