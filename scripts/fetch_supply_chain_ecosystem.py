#!/usr/bin/env python3
"""Supply Chain Ecosystem Health Assessment.

Usage:
    fetch_supply_chain_ecosystem.py NVDA
    fetch_supply_chain_ecosystem.py NVDA --output ./reports/NVDA/sc_ecosystem.json
    fetch_supply_chain_ecosystem.py AAPL --supply-chain-file ./reports/AAPL/supply_chain.json

Assesses the financial health of a company's upstream suppliers and downstream
customers to determine ecosystem momentum. A thriving ecosystem (suppliers
growing, customers expanding) is a leading indicator of future performance;
a collapsing ecosystem signals demand/cost headwinds 1-2 quarters ahead.

Analysis dimensions:
  1. Upstream Health   — supplier revenue growth, margins, stock momentum
  2. Downstream Health — customer revenue growth, margins, stock momentum
  3. Ecosystem Momentum — composite directional signal
  4. Propagation Risks — specific HIGH/MEDIUM/LOW risk flags

Data source: yfinance (public, no paid API required).
Missing data returned as null with explanatory note — never fabricated.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: 'numpy' required. Run: pip install numpy\n")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    sys.stderr.write("Error: 'yfinance' required. Run: pip install yfinance\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Known supply chain relationships (top sectors)
# Format: {target_ticker: {upstream: [...], downstream: [...]}}
# This is a heuristic fallback — prefer --supply-chain-file when available.
# ---------------------------------------------------------------------------

KNOWN_RELATIONSHIPS: dict[str, dict[str, list[dict]]] = {
    # Semiconductors — GPU/AI supply chain
    "NVDA": {
        "upstream": [
            {"ticker": "TSM", "name": "TSMC", "relationship": "foundry"},
            {"ticker": "ASML", "name": "ASML", "relationship": "lithography equipment"},
            {"ticker": "000660.KS", "name": "SK Hynix", "relationship": "HBM memory"},
        ],
        "downstream": [
            {"ticker": "MSFT", "name": "Microsoft", "relationship": "cloud/AI customer"},
            {"ticker": "META", "name": "Meta", "relationship": "AI training customer"},
            {"ticker": "GOOGL", "name": "Alphabet", "relationship": "cloud/AI customer"},
            {"ticker": "AMZN", "name": "Amazon", "relationship": "AWS customer"},
        ],
    },
    "AMD": {
        "upstream": [
            {"ticker": "TSM", "name": "TSMC", "relationship": "foundry"},
            {"ticker": "ASML", "name": "ASML", "relationship": "lithography equipment"},
        ],
        "downstream": [
            {"ticker": "MSFT", "name": "Microsoft", "relationship": "cloud customer"},
            {"ticker": "DELL", "name": "Dell", "relationship": "server customer"},
            {"ticker": "HPE", "name": "HPE", "relationship": "server customer"},
        ],
    },
    "TSM": {
        "upstream": [
            {"ticker": "ASML", "name": "ASML", "relationship": "EUV lithography"},
            {"ticker": "AMAT", "name": "Applied Materials", "relationship": "equipment"},
            {"ticker": "LRCX", "name": "Lam Research", "relationship": "etch equipment"},
        ],
        "downstream": [
            {"ticker": "NVDA", "name": "NVIDIA", "relationship": "GPU customer"},
            {"ticker": "AAPL", "name": "Apple", "relationship": "chip customer"},
            {"ticker": "AMD", "name": "AMD", "relationship": "CPU/GPU customer"},
            {"ticker": "QCOM", "name": "Qualcomm", "relationship": "mobile chip customer"},
        ],
    },
    # Tech Hardware
    "AAPL": {
        "upstream": [
            {"ticker": "TSM", "name": "TSMC", "relationship": "chip foundry"},
            {"ticker": "QCOM", "name": "Qualcomm", "relationship": "modem chips"},
            {"ticker": "MU", "name": "Micron", "relationship": "memory"},
        ],
        "downstream": [
            {"ticker": "AMZN", "name": "Amazon", "relationship": "retail distribution"},
            {"ticker": "VZ", "name": "Verizon", "relationship": "carrier distribution"},
            {"ticker": "T", "name": "AT&T", "relationship": "carrier distribution"},
        ],
    },
    # Software/Cloud
    "MSFT": {
        "upstream": [
            {"ticker": "NVDA", "name": "NVIDIA", "relationship": "AI/GPU supplier"},
            {"ticker": "AMD", "name": "AMD", "relationship": "CPU/GPU supplier"},
            {"ticker": "INTC", "name": "Intel", "relationship": "CPU supplier"},
        ],
        "downstream": [
            {"ticker": "CRM", "name": "Salesforce", "relationship": "platform customer"},
            {"ticker": "SAP", "name": "SAP", "relationship": "enterprise partner"},
        ],
    },
}

# Sector-level generic relationships (GICS 2-digit)
SECTOR_GENERIC: dict[str, dict[str, list[str]]] = {
    "45": {  # Information Technology
        "upstream": ["TSM", "ASML", "AMAT"],
        "downstream": ["MSFT", "AMZN", "GOOGL"],
    },
    "25": {  # Consumer Discretionary
        "upstream": ["UPS", "FDX", "AMZN"],
        "downstream": ["WMT", "TGT", "COST"],
    },
    "20": {  # Industrials
        "upstream": ["X", "NUE", "FCX"],
        "downstream": ["CAT", "DE", "BA"],
    },
}


# ---------------------------------------------------------------------------
# Data fetching utilities
# ---------------------------------------------------------------------------


def _fetch_company_health(ticker: str) -> dict[str, Any] | None:
    """Fetch key financial health metrics for a single company via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        hist = stock.history(period="1y")

        # Revenue growth YoY
        rev_growth = info.get("revenueGrowth")

        # Gross margin
        gross_margin = info.get("grossMargins")

        # Operating margin
        op_margin = info.get("operatingMargins")

        # FCF (trailing)
        fcf = info.get("freeCashflow")
        market_cap = info.get("marketCap")
        fcf_yield = (fcf / market_cap) if (fcf and market_cap and market_cap > 0) else None

        # Stock price 6-month return
        stock_6m_return = None
        if not hist.empty and len(hist) > 120:
            current = hist["Close"].iloc[-1]
            six_months_ago = hist["Close"].iloc[-126] if len(hist) >= 126 else hist["Close"].iloc[0]
            if six_months_ago > 0:
                stock_6m_return = round((current - six_months_ago) / six_months_ago, 4)

        # Margin trend (compare current quarter vs prior if available)
        financials = stock.quarterly_financials
        margin_trend = "unknown"
        if financials is not None and not financials.empty and financials.shape[1] >= 2:
            try:
                rev_cols = [c for c in financials.columns[:2]]
                gp_row = financials.loc["Gross Profit"] if "Gross Profit" in financials.index else None
                rev_row = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
                if gp_row is not None and rev_row is not None:
                    m_curr = gp_row.iloc[0] / rev_row.iloc[0] if rev_row.iloc[0] != 0 else None
                    m_prev = gp_row.iloc[1] / rev_row.iloc[1] if rev_row.iloc[1] != 0 else None
                    if m_curr is not None and m_prev is not None:
                        diff = m_curr - m_prev
                        if diff > 0.01:
                            margin_trend = "expanding"
                        elif diff < -0.01:
                            margin_trend = "contracting"
                        else:
                            margin_trend = "stable"
            except Exception:
                pass

        # Compute health score (1-10)
        scores = []
        if rev_growth is not None:
            # >20% growth = 9+, 10-20% = 7-9, 0-10% = 5-7, negative = 1-5
            if rev_growth >= 0.20:
                scores.append(min(10, 8.0 + rev_growth * 5))
            elif rev_growth >= 0.10:
                scores.append(7.0 + (rev_growth - 0.10) * 20)
            elif rev_growth >= 0:
                scores.append(5.0 + rev_growth * 20)
            else:
                scores.append(max(1.0, 5.0 + rev_growth * 10))

        if gross_margin is not None:
            # >60% = 9, 40-60% = 7, 20-40% = 5, <20% = 3
            scores.append(min(10, max(1, 3 + gross_margin * 10)))

        if stock_6m_return is not None:
            # >30% = 9, 10-30% = 7, -10 to 10% = 5, <-10% = 3
            if stock_6m_return >= 0.30:
                scores.append(9.0)
            elif stock_6m_return >= 0.10:
                scores.append(7.0 + (stock_6m_return - 0.10) * 10)
            elif stock_6m_return >= -0.10:
                scores.append(5.0 + stock_6m_return * 10)
            else:
                scores.append(max(1.0, 3.0 + (stock_6m_return + 0.10) * 10))

        health_score = round(float(np.mean(scores)), 1) if scores else None

        return {
            "ticker": ticker,
            "name": info.get("shortName", ticker),
            "rev_growth_yoy": round(rev_growth, 4) if rev_growth is not None else None,
            "gross_margin": round(gross_margin, 4) if gross_margin is not None else None,
            "op_margin": round(op_margin, 4) if op_margin is not None else None,
            "margin_trend": margin_trend,
            "stock_6m_return": stock_6m_return,
            "fcf_yield": round(fcf_yield, 4) if fcf_yield is not None else None,
            "health_score": health_score,
        }
    except Exception as e:
        sys.stderr.write(f"Warning: failed to fetch data for {ticker}: {e}\n")
        return None


def _identify_relationships(
    ticker: str, supply_chain_file: str | None = None
) -> dict[str, list[dict]]:
    """Identify upstream and downstream companies for a ticker."""
    relationships = {"upstream": [], "downstream": []}

    # Priority 1: Read from existing supply_chain.json if provided
    if supply_chain_file and os.path.exists(supply_chain_file):
        try:
            with open(supply_chain_file, "r") as f:
                sc_data = json.load(f)
            # Extract partner tickers from supply chain data
            suppliers = sc_data.get("suppliers", sc_data.get("upstream", []))
            customers = sc_data.get("customers", sc_data.get("downstream", []))
            if isinstance(suppliers, list):
                for s in suppliers[:5]:
                    if isinstance(s, dict) and s.get("ticker"):
                        relationships["upstream"].append(s)
                    elif isinstance(s, str):
                        relationships["upstream"].append({"ticker": s, "name": s, "relationship": "supplier"})
            if isinstance(customers, list):
                for c in customers[:5]:
                    if isinstance(c, dict) and c.get("ticker"):
                        relationships["downstream"].append(c)
                    elif isinstance(c, str):
                        relationships["downstream"].append({"ticker": c, "name": c, "relationship": "customer"})
        except (json.JSONDecodeError, IOError) as e:
            sys.stderr.write(f"Warning: could not read supply chain file: {e}\n")

    # Priority 2: Known relationships DB
    if not relationships["upstream"] and not relationships["downstream"]:
        known = KNOWN_RELATIONSHIPS.get(ticker.upper(), {})
        relationships["upstream"] = known.get("upstream", [])[:5]
        relationships["downstream"] = known.get("downstream", [])[:5]

    # Priority 3: Sector-level generic (very rough fallback)
    if not relationships["upstream"] and not relationships["downstream"]:
        try:
            stock = yf.Ticker(ticker)
            sector_code = str(stock.info.get("sectorKey", ""))[:2]
            generic = SECTOR_GENERIC.get(sector_code, {})
            for t in generic.get("upstream", [])[:3]:
                if t.upper() != ticker.upper():
                    relationships["upstream"].append({"ticker": t, "name": t, "relationship": "sector-generic"})
            for t in generic.get("downstream", [])[:3]:
                if t.upper() != ticker.upper():
                    relationships["downstream"].append({"ticker": t, "name": t, "relationship": "sector-generic"})
        except Exception:
            pass

    return relationships


def _compute_direction_score(
    upstream_score: float | None, downstream_score: float | None
) -> dict:
    """Compute ecosystem momentum direction and convergence."""
    if upstream_score is None and downstream_score is None:
        return {"score": None, "direction": "unknown", "convergence": False}

    scores = [s for s in [upstream_score, downstream_score] if s is not None]
    composite = round(float(np.mean(scores)), 1)

    # Direction
    if upstream_score is not None and downstream_score is not None:
        both_high = upstream_score >= 6.5 and downstream_score >= 6.5
        both_low = upstream_score <= 4.5 and downstream_score <= 4.5
        divergent = abs(upstream_score - downstream_score) >= 3.0

        if divergent:
            direction = "divergent"
        elif both_high:
            direction = "positive"
        elif both_low:
            direction = "negative"
        else:
            direction = "mixed"
        convergence = not divergent
    else:
        available = upstream_score or downstream_score
        direction = "positive" if available >= 6.5 else ("negative" if available <= 4.5 else "mixed")
        convergence = False

    return {"score": composite, "direction": direction, "convergence": convergence}


def _detect_propagation_risks(
    upstream_companies: list[dict], downstream_companies: list[dict]
) -> list[dict]:
    """Detect specific propagation risks from ecosystem health data."""
    risks = []

    for co in upstream_companies:
        if co is None:
            continue
        # Supplier margin contracting >500bps
        if co.get("margin_trend") == "contracting":
            risks.append({
                "direction": "upstream",
                "company": co.get("ticker", "unknown"),
                "risk": f"Supplier {co.get('name', co.get('ticker'))} margin contracting — potential cost pass-through",
                "severity": "HIGH",
            })
        # Supplier stock down >20% in 6M
        ret = co.get("stock_6m_return")
        if ret is not None and ret < -0.20:
            risks.append({
                "direction": "upstream",
                "company": co.get("ticker", "unknown"),
                "risk": f"Supplier {co.get('name', co.get('ticker'))} stock down {ret*100:.0f}% 6M — potential supply disruption",
                "severity": "HIGH",
            })
        # Supplier revenue declining
        rev = co.get("rev_growth_yoy")
        if rev is not None and rev < -0.10:
            risks.append({
                "direction": "upstream",
                "company": co.get("ticker", "unknown"),
                "risk": f"Supplier {co.get('name', co.get('ticker'))} revenue declining {rev*100:.0f}% YoY — capacity risk",
                "severity": "MEDIUM",
            })

    for co in downstream_companies:
        if co is None:
            continue
        # Customer revenue declining >10%
        rev = co.get("rev_growth_yoy")
        if rev is not None and rev < -0.10:
            risks.append({
                "direction": "downstream",
                "company": co.get("ticker", "unknown"),
                "risk": f"Customer {co.get('name', co.get('ticker'))} revenue declining {rev*100:.0f}% YoY — demand risk",
                "severity": "HIGH",
            })
        # Customer stock down >20%
        ret = co.get("stock_6m_return")
        if ret is not None and ret < -0.20:
            risks.append({
                "direction": "downstream",
                "company": co.get("ticker", "unknown"),
                "risk": f"Customer {co.get('name', co.get('ticker'))} stock down {ret*100:.0f}% 6M — demand headwind",
                "severity": "MEDIUM",
            })

    return risks


def _compute_chain_health_adjustment(ecosystem_score: float | None) -> float:
    """Compute ±0.10 screening bonus/penalty based on ecosystem momentum.

    >=7 → positive adjustment (+0.05 to +0.10)
    <=4 → negative adjustment (-0.05 to -0.10)
    4-7 → neutral (0)
    """
    if ecosystem_score is None:
        return 0.0
    if ecosystem_score >= 8.5:
        return 0.10
    elif ecosystem_score >= 7.0:
        return 0.05
    elif ecosystem_score <= 2.5:
        return -0.10
    elif ecosystem_score <= 4.0:
        return -0.05
    return 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Supply chain ecosystem health assessment"
    )
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument(
        "--supply-chain-file",
        help="Path to existing supply_chain.json for relationship data",
    )
    args = parser.parse_args()

    ticker = args.ticker.upper()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Identify relationships
    relationships = _identify_relationships(ticker, args.supply_chain_file)

    # Fetch upstream health
    upstream_companies = []
    for rel in relationships["upstream"]:
        t = rel.get("ticker", rel) if isinstance(rel, dict) else rel
        data = _fetch_company_health(t)
        if data:
            data["relationship"] = rel.get("relationship", "supplier") if isinstance(rel, dict) else "supplier"
            upstream_companies.append(data)

    # Fetch downstream health
    downstream_companies = []
    for rel in relationships["downstream"]:
        t = rel.get("ticker", rel) if isinstance(rel, dict) else rel
        data = _fetch_company_health(t)
        if data:
            data["relationship"] = rel.get("relationship", "customer") if isinstance(rel, dict) else "customer"
            downstream_companies.append(data)

    # Compute aggregate scores
    upstream_scores = [c["health_score"] for c in upstream_companies if c.get("health_score") is not None]
    downstream_scores = [c["health_score"] for c in downstream_companies if c.get("health_score") is not None]

    upstream_health = round(float(np.mean(upstream_scores)), 1) if upstream_scores else None
    downstream_health = round(float(np.mean(downstream_scores)), 1) if downstream_scores else None

    # Upstream trend
    upstream_trends = [c.get("margin_trend") for c in upstream_companies if c.get("margin_trend") != "unknown"]
    if upstream_trends:
        expanding = upstream_trends.count("expanding")
        contracting = upstream_trends.count("contracting")
        upstream_trend = "positive" if expanding > contracting else ("negative" if contracting > expanding else "mixed")
    else:
        upstream_trend = "unknown"

    # Downstream trend
    downstream_trends = [c.get("margin_trend") for c in downstream_companies if c.get("margin_trend") != "unknown"]
    if downstream_trends:
        expanding = downstream_trends.count("expanding")
        contracting = downstream_trends.count("contracting")
        downstream_trend = "positive" if expanding > contracting else ("negative" if contracting > expanding else "mixed")
    else:
        downstream_trend = "unknown"

    # Ecosystem momentum
    ecosystem = _compute_direction_score(upstream_health, downstream_health)

    # Propagation risks
    propagation_risks = _detect_propagation_risks(upstream_companies, downstream_companies)

    # Chain health adjustment for screening
    chain_health_adj = _compute_chain_health_adjustment(ecosystem.get("score"))

    # Data quality
    confidence = "high" if (len(upstream_companies) >= 3 and len(downstream_companies) >= 3) else \
                 "medium" if (len(upstream_companies) >= 1 and len(downstream_companies) >= 1) else \
                 "low"

    result = {
        "ticker": ticker,
        "timestamp": timestamp,
        "upstream": {
            "companies": upstream_companies,
            "health_score": upstream_health,
            "trend": upstream_trend,
        },
        "downstream": {
            "companies": downstream_companies,
            "health_score": downstream_health,
            "trend": downstream_trend,
        },
        "ecosystem_momentum": ecosystem,
        "propagation_risks": propagation_risks,
        "chain_health_adjustment": chain_health_adj,
        "data_quality": {
            "upstream_coverage": len(upstream_companies),
            "downstream_coverage": len(downstream_companies),
            "confidence": confidence,
        },
    }

    # Output
    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    print(output_json)

    if args.output:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        sys.stderr.write(f"Written to {args.output}\n")


if __name__ == "__main__":
    main()
