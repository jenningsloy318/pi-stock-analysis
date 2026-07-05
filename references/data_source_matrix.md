# Data Source Matrix

Use this matrix before running the stock-analysis skill. The goal is coverage by dimension, source quality, and freshness, not volume of citations.

## Source Tiers

| Tier | Use | Examples | Completion Rule |
|------|-----|----------|-----------------|
| Tier 0 | Market prices and tradable instruments | Exchange/finance tool, yfinance, Polygon/Alpaca when configured | Required for current price, market cap, beta, technicals, and options-sensitive reports |
| Tier 1 | Primary filings and official statistics | SEC EDGAR submissions/companyfacts, company IR filings, FRED/Federal Reserve, BEA, BLS, Treasury FiscalData, CFTC COT, FINRA short interest, EIA, FDA, FDIC/OCC | Blocking for any claim directly supported by these datasets |
| Tier 2 | Audited or institutionally curated secondary data | Exchange filings outside the US, S&P/FactSet/Capital IQ if available, ETF issuer holdings, rating agency releases, consensus providers, reputable industry reports | Allowed when Tier 1 does not cover the dimension; must be labeled |
| Tier 3 | Directional alternative data | Google Trends, Similarweb snippets, app-store ranks, Glassdoor public pages, Reddit/social sentiment, patents, hiring pages, channel-check summaries | Never decisive alone; requires convergence with at least one Tier 1 or Tier 2 signal |

## Coverage Requirements By Dimension

| Dimension | Minimum Sources | Freshness Target | Notes |
|-----------|-----------------|------------------|-------|
| Current price, volume, options | 1 Tier 0 source | Same day for short-term, 7 days for mid/long | Quote staleness must be explicit in reports |
| Financial statements | SEC/company filings plus script output | Latest 10-K/10-Q or local market equivalent | For non-US companies, use exchange filings and label accounting standard |
| Segment and geography | Latest annual report, 10-K/20-F/40-F, investor presentation | Latest annual filing; update if material 8-K/6-K exists | Required for multi-segment valuation and geopolitical exposure |
| Management and governance | DEF 14A/proxy, Form 4, board/company filings | Proxy within 15 months; Form 4 within 90 days | If no recent Form 4 exists, state "No recent Form 4 found" instead of failing |
| Macro | FRED/Fed plus BEA/BLS/Treasury where relevant | 30 days for monthly/daily series; latest quarter for GDP | Use regional official sources for non-US issuers |
| Credit and liquidity | FRED spreads, Treasury, company debt notes, ratings releases | 7 days for spreads; latest filing for maturity schedule | Mandatory for levered companies and financials |
| Positioning and flow | CFTC COT, FINRA short interest, ETF holdings/flows, 13F/13D/13G | 7 days for COT, latest settlement for short interest, latest quarter for 13F | Distinguish short interest from short-sale volume |
| Industry structure | GICS/NAICS mapping, BEA industry data, reputable industry report | 90 days for market data; 12 months for structural reports | Require both top-down and bottom-up TAM sanity checks |
| Company screening universe | GICS/ETF holdings/exchange lists plus web verification | 90 days | Missing companies must be reported as universe risk |
| Alternative data | At least 3 independent directional signals | 30 days for social/search/app; 12 months for patents | Mark as directional and non-representative |
| Capital structure & returns | yfinance shares/buyback data, SEC filings (10-K cash flow statement), proxy | Latest filing for buyback data; 90 days for share count | Required for capital allocation scoring and SBC dilution flag |
| Private market / M&A | yfinance fundamentals, web search for precedent transactions, 13D filings | 90 days for fundamentals; 12 months for M&A comps | LBO floor is computed deterministically; precedent transactions need web search |
| Technical structure (Weinstein) | yfinance weekly OHLCV (2yr), SPY benchmark | Same day for short-term; 7 days otherwise | Required for Stage 6 Weinstein classification and CANSLIM L-factor |
| ESG & carbon risk | yfinance sustainability fields, sector benchmarks, GICS emission intensity tables | 90 days for ESG scores; 12 months for carbon intensity | Required for long-term risk assessment in carbon-intensive sectors (GICS 10, 15, 20, 55) |
| International market adjustments | akshare (China), EDINET/TDnet (Japan), BSE/NSE (India), DART/KRX (Korea) | 90 days for structural metrics; 30 days for flows | Required when primary listing is non-US or >20% revenue from covered markets |
| Volatility & tail risk | yfinance daily returns (2yr), GARCH model output, Student-t fitting | 7 days for short-term; 30 days otherwise | Required for enhanced risk metrics and position sizing |
| Supply chain concentration | yfinance geographic segments, GICS sector chokepoint mapping, revenue HHI | 90 days for segments; 12 months for structural | Required for industry analysis (Stage 3) and operational due diligence |
| Earnings quality | Financial statements (income, cash flow, balance sheet), 3-5yr history | Latest filing | Required for forensic accounting and fundamental quality assessment |
| Liquidity & microstructure | yfinance daily OHLCV (1yr), bid-ask when available, shares outstanding | 7 days for short-term; 30 days otherwise | Required for position sizing constraints and market impact estimation |
| Short interest & squeeze | yfinance short interest, float shares, institutional holdings, catalyst calendar | 7 days for short-term; 14 days otherwise | Required for short-term positioning analysis and squeeze risk scoring |
| Activist & governance catalysts | yfinance institutional holders, insider transactions, 13D/proxy filings | 30 days for institutional; 90 days for proxy | Required for governance catalyst identification and proxy fight probability |
| Tail risk & drawdowns | yfinance daily returns (2yr), portfolio positions, correlation matrix | 7 days for short-term; 30 days otherwise | Required for portfolio-level risk assessment and position sizing |
| Correlation regime | yfinance daily returns (2yr) vs benchmark, rolling beta, tail correlation | 7 days for short-term; 30 days otherwise | Required for stress-adjusted position sizing and diversification assessment |
| Earnings edge / PEAD | yfinance earnings history, quarterly price data around earnings dates | Latest quarter | Required for earnings catalyst assessment and pre/post-earnings drift analysis |
| Options microstructure | yfinance options chains (multi-expiry), IV surface, GEX, term structure | Same day for short-term; 7 days otherwise | Required for dealer positioning, vol regime, and options flow signals |

## Freshness SLA

| Data Class | Max Freshness | Blocks Stage? |
|------------|---------------|---------------|
| Quote, options, technicals | Same day for short-term; 7 days otherwise | Yes for short-term and valuation |
| News and catalysts | 7 days | Yes for short-term and event-driven mid-term |
| Macro daily/weekly series | 30 days | Yes for Stages 4, 7 and screening Phase 0 |
| Financial statements | Latest reported quarter/year | Yes for Stages 1, 6, 8 and company screening |
| Insider/Form 4 | 90 days if activity exists | No if no filing exists; annotate |
| Sector valuation/growth | 90 days | Yes for broad screening |
| Industry reports/TAM | 12 months | No, but confidence drops if older |
| Patents/governance/proxy | 12-15 months | Yes for long-term management or innovation claims |

## Source Quorum Rules

1. A numeric investment claim needs one Tier 1/Tier 0 source or two independent Tier 2 sources.
2. A qualitative thesis claim needs at least two independent sources, unless it is directly stated in a company filing.
3. Alternative data can support direction, timing, or divergence only after convergence scoring.
4. If sources conflict, preserve the conflict in the report and assign lower confidence.
5. If a critical source is unavailable, write "Data not available" and lower confidence instead of substituting an unverifiable proxy.

## Non-US Coverage

For non-US companies, replace US-only sources with local equivalents:

| Dimension | Preferred Sources |
|-----------|-------------------|
| Filings | Local exchange filings, annual report, 20-F/40-F/6-K if SEC-listed ADR |
| Macro | Central bank, national statistics office, IMF/OECD/World Bank where official local APIs are unavailable |
| Rates and currency | Local central bank, Treasury/sovereign yield data, FX market data |
| Industry | Local industry regulator, trade body, exchange sector classification, regional government statistics |
| Governance | Local proxy/annual meeting materials, exchange governance filings |

### World Bank Open Data — Indicator Map

`fetch_global_macro.py` exposes 23 WB indicators across 8 categories (default: `core,demographics,trade`). All free, no auth required, REST endpoint `api.worldbank.org/v2/`. **Max Freshness: annual data, 3–12 month lag** — suitable for long-term reports; cross-reference with FRED (US) or local statistics offices for shorter horizons.

| Category | Indicator (key) | WB Code | Used By Stage | Why It Matters |
|---|---|---|---|---|
| `core` | GDP growth | `NY.GDP.MKTP.KD.ZG` | 4, 9 | Cycle position |
| `core` | GDP (USD) | `NY.GDP.MKTP.CD` | 4 | Country size denominator |
| `core` | CPI | `FP.CPI.TOTL.ZG` | 4 | Inflation regime |
| `core` | Unemployment | `SL.UEM.TOTL.ZS` | 4 | Slack indicator |
| `core` | Current account % GDP | `BN.CAB.XOKA.GD.ZS` | 9 | External-balance / FX risk |
| `core` | Exports / Imports growth | `NE.EXP.GNFS.ZS`, `NE.IMP.GNFS.ZS` | 4, 9 | Trade pulse |
| `core` | FDI % GDP | `BX.KLT.DINV.WD.GD.ZS` | 9 | Capital-flow regime |
| `demographics` | Population growth | `SP.POP.GROW` | 4, 9 | Long-term demand multiplier; Japan-thesis flip detection |
| `demographics` | Working-age % | `SP.POP.1564.TO.ZS` | 4 | Productivity ceiling; pension burden |
| `demographics` | Urban % | `SP.URB.TOTL.IN.ZS` | 9 | China/India consumption-tier story |
| `innovation` | R&D % GDP | `GB.XPD.RSDV.GD.ZS` | 4, 7 | Country-level innovation moat (US 3.5% / CN 2.4% / IN 0.7%) |
| `innovation` | Tertiary enrollment | `SE.TER.ENRR` | 7 | Labor pool quality |
| `trade` | Trade % GDP | `NE.TRD.GNFS.ZS` | 4, 9 | Tariff exposure quantification |
| `trade` | High-tech exports % | `TX.VAL.TECH.MF.ZS` | 8 | Tech supply-chain dependency |
| `infrastructure` | Internet users % | `IT.NET.USER.ZS` | 7 | SaaS / digital TAM saturation |
| `infrastructure` | Mobile per 100 | `IT.CEL.SETS.P2` | 7 | Same |
| `infrastructure` | Electricity per capita | `EG.USE.ELEC.KH.PC` | 9 | EV / data-center demand floor |
| `energy` | Energy per GDP | `EG.USE.COMM.GD.PP.KD` | 8, 9 | Supply-chain energy exposure |
| `energy` | CO2 per GDP | `EN.GHG.CO2.RT.GDP.PP` | 12 | Carbon-pricing risk |
| `financial` | Private credit % GDP | `FS.AST.PRVT.GD.ZS` | 4 | Liquidity floor for cyclicals |
| `financial` | Market cap % GDP | `CM.MKT.LCAP.GD.ZS` | 4 | Per-country Buffett ratio (over/undervaluation regime) |
| `sovereign` | Gov debt % GDP | `GC.DOD.TOTL.GD.ZS` | 4, 9 | Fiscal-cliff / sovereign-debt risk |

CLI: `fetch_global_macro.py --categories core,demographics,innovation` (subset) or `--categories all` (full 23 indicators).

## Sector-Specific Add-Ons

| Sector | Required Add-Ons |
|--------|------------------|
| Banks | Regulatory capital, CET1, NIM, loan loss provisions, deposit beta, unrealized securities losses, FDIC/OCC/Fed data where available |
| Insurance | Combined ratio, reserves, float yield, catastrophe exposure, solvency capital |
| REITs | FFO/AFFO, occupancy, lease maturities, cap rates, debt maturity schedule |
| Energy | Production volumes, reserves, decline rates, realized prices, hedges, EIA commodity data |
| Biotech/Pharma | Pipeline phase probabilities, trial readouts, FDA calendar, patent cliff, payer/reimbursement risk |
| SaaS/Software | ARR, NRR/GRR, CAC payback, rule of 40, RPO, churn, seat expansion, cloud gross margin |
| Semiconductors | Node exposure, wafer starts, utilization, inventory days, customer concentration, export controls |
| Industrials | Backlog, book-to-bill, capacity utilization, input costs, order cycle |
| Consumer | Same-store sales, traffic, basket size, inventory turns, promotion intensity |

## IFRS vs US GAAP Reconciliation

When analyzing non-US companies reporting under IFRS, adjust for these key differences:

| Area | US GAAP | IFRS | Analysis Impact |
|------|---------|------|-----------------|
| **Revenue Recognition** | ASC 606 (similar to IFRS 15) | IFRS 15 | Largely converged. Watch for principal vs agent classification in marketplace/platform companies. |
| **Leases** | ASC 842: all leases on balance sheet | IFRS 16: all leases on balance sheet | Largely converged. Both capitalize operating leases now. |
| **Inventory** | LIFO permitted | LIFO prohibited | US companies using LIFO → inventory and COGS not comparable to IFRS peers. Adjust to FIFO for peer comparison. |
| **Goodwill** | Amortized over ≤10 years (private companies) or tested for impairment (public) | Tested for impairment only (no amortization) | Different impairment triggers and measurement. IFRS goodwill may be overstated. |
| **Development Costs** | Expensed (with narrow exceptions for software) | Capitalized if certain criteria met | IFRS companies may show higher assets and lower current expenses. Adjust for comparability. |
| **PP&E Revaluation** | Historical cost only | Revaluation model permitted | IFRS companies may show inflated asset values. Check if revaluation model is used. |
| **Extraordinary Items** | Permitted (rare) | Prohibited | IFRS income statements are cleaner — no below-the-line extraordinary classification. |
| **Cash Flow Statement** | Interest paid/received = operating; dividends paid = financing | Choice: interest/dividends can be operating or financing | Classification differences change OCF and FCF. Always check classification choices. |
| **Financial Instruments** | Complex (ASC 820 fair value hierarchy) | IFRS 9 (simpler classification) | Different hedge accounting and impairment models. |
| **Consolidation** | Variable interest entity (VIE) model | Control-based model (power + returns) | Different consolidation conclusions for SPVs, structured entities. |

### Analyst Adjustments Required

When comparing IFRS and US GAAP companies:

1. **Always state accounting standard in reports.** "FY2024 results (IFRS)" or "FY2024 (US GAAP)."
2. **Normalize inventory accounting.** If US peer uses LIFO, adjust to FIFO before comparing gross margins.
3. **Check for development cost capitalization.** IFRS tech/pharma companies may have higher assets. Subtract capitalized development from assets and add to expenses for comparability.
4. **Reconcile OCF.** IFRS companies with interest in financing cash flow → OCF overstated. Adjust to US GAAP OCF definition.
5. **Verify goodwill impairment.** IFRS impairment-only model → goodwill may be stale. Apply a simplified DCF reasonableness test.
6. **Watch segment reporting.** IFRS 8 is similar to ASC 280 but companies have more discretion in segment definition under IFRS.

### Non-US Filing Equivalents

| Country/Region | Filing Equivalent | Accounting Standard | Access |
|---------------|-------------------|---------------------|--------|
| **Canada** | SEDAR (sedar.com) | IFRS (public companies) | Free web |
| **UK** | Companies House | IFRS (UK-adopted) | Free web |
| **EU** | National registers + ESMA | IFRS (EU-adopted) | Free web (varies by country) |
| **Japan** | EDINET | JGAAP or IFRS (choice) | Free web |
| **China** | CSRC + SSE/SZSE | CAS (converging to IFRS) | akshare / free web |
| **India** | BSE/NSE + MCA | Ind AS (converged IFRS) | Free web |
| **Australia** | ASIC | IFRS (AASB) | Free web |
| **Brazil** | CVM | IFRS (CPC) | Free web |
| **Hong Kong** | HKEX | HKFRS (IFRS-equivalent) | Free web |
| **Singapore** | SGX | SFRS (IFRS-equivalent) | Free web |
| **ADR (US-listed foreign)** | SEC 20-F / 40-F | IFRS or home-country GAAP with reconciliation | SEC EDGAR |

## Coverage Add-Ons for New Analysis Dimensions

### Capital Allocation (Stage 1b)

| Source | Tier | What It Provides | Access |
|--------|------|-----------------|--------|
| 10-K Cash Flow Statement | 1 | Buyback spending, dividend payments, debt issuance/repayment | SEC EDGAR |
| DEF 14A (Proxy) | 1 | SBC grants, compensation structure, equity plan | SEC EDGAR |
| yfinance | 0 | Shares outstanding history (5yr), buyback yield, dividend yield | Free |
| Company IR presentations | 2 | Capital allocation policy, ROIC targets, M&A strategy | Company website |
| SEC Form S-3 / S-4 | 1 | Share issuance, M&A registration | SEC EDGAR |
| Seeking Alpha / Bloomberg | 2 | M&A deal terms, synergy estimates, integration progress | Web search |

### Supply Chain Resilience (Stage 3b)

| Source | Tier | What It Provides | Access |
|--------|------|-----------------|--------|
| 10-K Item 1 (Business) | 1 | Major suppliers, raw material sources, manufacturing locations | SEC EDGAR |
| 10-K Risk Factors | 1 | Supply chain risk disclosure, concentration warnings | SEC EDGAR |
| ImportYeti / Panjiva | 2 | US import/export bills of lading, supplier shipment data | Web (free tier) |
| Supplier annual reports (public) | 1 | Financial health of critical Tier 1 suppliers | SEC EDGAR / exchange filings |
| Freightos Baltic Index (FBX) | 2 | Container shipping rates by route | Web |
| BEA / Census trade data | 1 | Aggregate import/export by country and commodity | Free |
| Company sustainability reports | 2 | Supplier diversity, geographic sourcing, audit results | Company website |
| US BIS Entity List / OFAC SDN | 1 | Export controls, sanctions affecting suppliers | US Government |

### ESG & Sustainability (Stage 8b)

| Source | Tier | What It Provides | Access |
|--------|------|-----------------|--------|
| MSCI ESG Ratings | 2 | ESG rating, controversy flags, industry ranking | Paywalled (search for summaries) |
| Sustainalytics | 2 | ESG risk rating, material ESG issues | Paywalled (search for summaries) |
| CDP (Carbon Disclosure Project) | 1 | Company-reported carbon emissions, climate strategy | Free (if company reports) |
| TCFD / ISSB disclosures | 1 | Climate risk governance, scenario analysis, metrics | Company filings |
| EPA GHG Reporting | 1 | Facility-level emissions (US) | Free |
| SASB Materiality Map | 1 | Industry-specific material ESG issues | Free |
| Carbon pricing databases | 2 | Regional carbon prices (EU ETS, UK ETS, RGGI, California) | Web |
| EIA energy data | 1 | Sector-level energy consumption, emissions intensity | Free |
| Company CSR/sustainability reports | 2 | Self-reported ESG metrics, targets, progress | Company website |

### Catalyst Intelligence (Stage 9b)

| Source | Tier | What It Provides | Access |
|--------|------|-----------------|--------|
| FDA (fda.gov) | 1 | PDUFA dates, advisory committee meetings, approval actions | Free |
| ClinicalTrials.gov | 1 | Trial status, phase, enrollment, primary completion dates | Free |
| Company IR calendar | 1 | Earnings dates, investor days, conference presentations | Company website |
| SEC Form 8-K | 1 | Material events, earnings releases, guidance changes | SEC EDGAR |
| Earnings whisper / Estimize | 2 | Crowdsourced earnings estimates vs consensus | Web |
| CBOE options data | 0 | Implied volatility around event dates, unusual options activity | yfinance / Polygon |
| Wall Street Horizon | 2 | Corporate event dates (earnings, investor days, ex-dividend) | Paywalled (search alternatives) |
| Congress.gov / EU Parliament | 1 | Pending legislation timelines | Free |
| FTC / DOJ Antitrust | 1 | Merger review timelines, antitrust decisions | Free |

### China A-Share Specific (Stages CN1, CN2)

| Source | Tier | What It Provides | Access |
|--------|------|-----------------|--------|
| 东方财富 (East Money) | 2 | 北向资金 flows, 融资融券数据, 龙虎榜, sector performance | Free web |
| 同花顺 (10jqka) | 2 | Sector rotation data, fund flows, concept board tracking | Free web |
| 雪球 (Xueqiu) | 3 | Retail investor sentiment, discussion analysis, portfolio disclosures | Free web |
| 沪深交易所 (SSE/SZSE) | 1 | Official margin data, 龙虎榜, IPO calendar | Free |
| 国务院 (State Council) | 1 | Policy documents, 产业规划, 中央经济工作会议 readout | Free (gov.cn) |
| 国家统计局 (NBS) | 1 | China GDP, PMI, industrial production, retail sales | Free |
| PBOC (人民银行) | 1 | Monetary policy, LPR, RRR, open market operations | Free |
| Wind (万得) | 2 | Comprehensive A-share financial data, consensus estimates | Paywalled (search alternatives) |
| CSRC (证监会) | 1 | IPO approvals, regulatory actions, policy statements | Free |
| 集思录 (Jisilu) | 2 | Convertible bond data, structured products, arbitrage signals | Free web |
| 中国证券报 / 上海证券报 | 2 | Official financial news, policy interpretation | Free web |
| 东方财富Choice / iFinD | 2 | Comprehensive financial terminal data | Paywalled |
| Stock Connect (沪深港通) | 1 | Daily northbound/southbound flow data | HKEX / SSE / SZSE |

## Report Confidence Mapping

| Coverage Result | Confidence Impact |
|-----------------|-------------------|
| All blocking dimensions pass, 0-1 stale non-critical sources | High confidence eligible |
| One blocking dimension unavailable but not central to thesis | Medium confidence maximum |
| Two or more blocking dimensions unavailable or stale | Low confidence maximum |
| Alternative-data-only thesis support | Low confidence maximum |
| Numeric claims fail fact check | Remove claim; rerun affected stage if material |
