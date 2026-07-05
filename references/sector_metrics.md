# Sector-Specific Metrics & Thresholds

Select the sector based on GICS classification. If the company spans multiple sectors, apply metrics from the sector with the largest revenue share. Flag the classification confidence (High: >80% revenue, Medium: 50-80%, Low: <50%).

## SaaS / Technology (GICS 45 — Information Technology)

| Metric | Formula/Definition | Bullish Threshold | Bearish Threshold |
|--------|-------------------|-------------------|-------------------|
| **ARR** | Annual Recurring Revenue (sum of annualized contracts) | >30% YoY growth | <15% YoY growth |
| **NDR** | Net Dollar Retention (existing customer revenue expansion) | >120% | <100% |
| **Rule of 40** | Revenue Growth % + FCF Margin % | >40 | <25 |
| **Gross Margin** | (Revenue - COGS) / Revenue | >75% | <60% |
| **DAU/MAU** | Daily Active Users / Monthly Active Users | >40% (consumer), >60% (enterprise) | <20% |
| **RPO** | Remaining Performance Obligations (contracted but unrecognized revenue) | RPO/Revenue >1.0x and growing | RPO/Revenue <0.5x or declining |
| **CAC Payback** | Customer Acquisition Cost / Monthly Gross Margin per Customer | <12 months | >24 months |
| **LTV/CAC** | Lifetime Value / Customer Acquisition Cost | >5x | <3x |

## Pharma / Biotech (GICS 35 — Health Care)

| Metric | Formula/Definition | Context |
|--------|-------------------|---------|
| **Pipeline rNPV** | Risk-adjusted Net Present Value of pipeline (probability of success × peak sales × discount rate) | Sum across all pipeline assets |
| **Phase Probability** | Historical probability of success by phase: Phase 1 (10%), Phase 2 (15%), Phase 3 (50%), NDA (85%) | Apply to each pipeline asset |
| **Patent Cliff Exposure** | % of revenue from products losing exclusivity within 5 years | >30% requires pipeline offset |
| **R&D Productivity** | Pipeline rNPV / Cumulative R&D spend (last 10 years) | <1.0x = value-destroying R&D |
| **Revenue Concentration** | % of revenue from top 3 products | >60% = concentration risk |
| **Cash Runway** | Cash + Equivalents / Quarterly Net Burn | <8 quarters = dilution risk |

## Financials (GICS 40)

| Metric | Definition | Bullish | Bearish |
|--------|-----------|---------|---------|
| **ROTCE** | Return on Tangible Common Equity | >15% | <8% |
| **CET1 Ratio** | Common Equity Tier 1 / Risk-Weighted Assets | >12% (well-capitalized) | <7% (undercapitalized) |
| **NIM** | Net Interest Margin = (Interest Income - Interest Expense) / Earning Assets | >3.5% (regional), >2.5% (money center) | <2% |
| **Efficiency Ratio** | Non-Interest Expense / Revenue | <55% | >70% |
| **Net Charge-Offs** | Actual Loan Losses / Average Loans | <0.5% | >1.5% |
| **P/B** | Price / Book Value | <1.0 (potential value) | >2.5 (premium) |
| **Loan Growth** | YoY loan portfolio growth | 5-10% (healthy) | <0% (contracting) or >20% (aggressive) |

## Retail / Consumer (GICS 25/30)

| Metric | Definition | Bullish | Bearish |
|--------|-----------|---------|---------|
| **Same-Store Sales** | YoY revenue growth at stores open >1 year | >5% | Negative |
| **Sales/sqft** | Revenue / Total Selling Square Footage | Growing YoY | Declining YoY |
| **Inventory Turnover** | COGS / Average Inventory | >6x (general), >12x (grocery) | <4x |
| **E-commerce %** | Online Revenue / Total Revenue | >20% and growing | <10% and stagnant |
| **Gross Margin** | (Revenue - COGS) / Revenue | >40% (specialty), >25% (discount) | Declining 2+ quarters |
| **Customer Traffic** | Foot traffic or unique visitors | Growing YoY | Declining 2+ quarters |

## Industrials (GICS 20)

| Metric | Definition | Bullish | Bearish |
|--------|-----------|---------|---------|
| **Book-to-Bill** | Orders Received / Orders Filled | >1.1 (growing backlog) | <0.9 (shrinking backlog) |
| **Organic Revenue Growth** | Revenue growth ex-M&A and FX | >5% | Negative |
| **Operating Margin** | Operating Income / Revenue | >15% and expanding | <10% and contracting |
| **Capacity Utilization** | % of total production capacity in use | >85% (triggers capex cycle) | <70% (overcapacity) |
| **Backlog Coverage** | Backlog / Annual Revenue | >1.0x (strong visibility) | <0.5x (limited visibility) |
| **ROIC** | NOPAT / Invested Capital | >15% and >WACC | <WACC |

### Industrials — Transportation Sub-Sector (GICS 2030)

| Metric | Definition | Bullish | Bearish |
|--------|-----------|---------|---------|
| **Operating Ratio** | OpEx / Revenue (lower = better) | <60% (railroads), <85% (LTL) | >65% (rail), >92% (LTL) |
| **Load Factor** | Passengers or capacity utilized / Available | >85% (airlines) | <78% (airlines) |
| **RASM** | Revenue per Available Seat Mile (airlines) | Rising YoY | Declining YoY |
| **TCE Rate** | Time Charter Equivalent (shipping) | >1.5x breakeven | Near/below breakeven |
| **Cass Freight Index** | Leading freight demand indicator | Rising 3-month trend | Declining 3+ months |
| **Revenue per Carload** | Railroad pricing power indicator | Rising above inflation | Below inflation |
| **Fleet Utilization** | % of fleet generating revenue | >95% | <90% |
| **Net Debt/EBITDAR** | Lease-adjusted leverage (airlines) | <2.5x | >4.0x |

## Energy (GICS 10)

| Metric | Definition | Context |
|--------|-----------|---------|
| **Reserve Replacement Ratio** | New Reserves Added / Production | >100% = sustainable. <100% = liquidating. |
| **F&D Costs/BOE** | Finding & Development Costs per Barrel of Oil Equivalent | Lower than peer median = cost advantage |
| **Breakeven Price** | WTI/Brent price at which FCF = 0 (covers capex + dividend) | Compare to current strip pricing |
| **Debt/EBITDA** | Total Debt / EBITDA | <2.0x (safe), >3.5x (risk at low prices) |
| **Production Growth** | YoY production volume growth | 3-8% (sustainable). >15% (aggressive debt-funded). |
| **FCF Yield** | FCF / Market Cap | >10% (value signal). <5% (expensive). |

## REITs (GICS 60 — Real Estate)

| Metric | Definition | Bullish | Bearish |
|--------|-----------|---------|---------|
| **FFO/Share** | Funds From Operations per share (Net Income + Depreciation - Gains on Sale) | Growing >5% YoY | Declining |
| **AFFO/Share** | Adjusted FFO (FFO - Recurring Capex) | AFFO/Share > Dividend/Share | AFFO < Dividend (unsustainable) |
| **NAV/Share** | Net Asset Value per share (market value of properties - debt) / shares | Trading at discount to NAV | Trading at premium with deteriorating fundamentals |
| **Occupancy** | % of leasable space occupied | >95% | <90% and declining |
| **Cap Rate** | NOI / Property Value | Compressing (property values rising) | Expanding (values falling) |
| **Leasing Spreads** | New rent / Expiring rent | >1.0x (positive re-leasing) | <1.0x (negative re-leasing) |
| **Debt/EBITDA** | Total Debt / EBITDA | <6x (investment grade) | >8x |

## Communication Services (GICS 50)

| Metric | Formula/Definition | Bullish Threshold | Bearish Threshold |
|--------|-------------------|-------------------|-------------------|
| **DAU/MAU Ratio** | Daily Active Users / Monthly Active Users | >50% (social), >30% (content) | <20% |
| **ARPU Growth** | YoY change in avg revenue per user | >10% | <0% |
| **Ad Revenue Growth** | YoY advertising revenue | >15% | <5% |
| **Engagement Time** | Avg minutes per user per day | >40 min (growing) | <20 min (declining) |
| **Subscriber Growth** | YoY paying subscriber change | >15% (streaming/telecom) | <0% |
| **Churn Rate** | Monthly subscriber cancellations / avg subs | <3%/mo | >6%/mo |
| **Postpaid Phone Churn** | Monthly voluntary disconnects (telecom) | <0.80% | >1.20% |
| **EBITDA Margin** | EBITDA / Revenue | >40% | <25% |
| **Content Spend / Revenue** | Content cost amortization / Revenue | <50% (efficient) | >65% (overspending) |
| **FCF Conversion** | FCF / EBITDA | >80% | <50% |
| **Leverage** | Net Debt / EBITDA | <2.5x | >4.0x |
| **Spectrum Depth** | MHz/POP holdings vs peers | Above peer median | Below peer median |

## Materials (GICS 15)

| Metric | Formula/Definition | Bullish Threshold | Bearish Threshold |
|--------|-------------------|-------------------|-------------------|
| **Production Cost Percentile** | Position on global industry cost curve | Bottom quartile (lowest cost) | Top quartile (highest cost) |
| **Capacity Utilization** | Actual output / Nameplate capacity | >85% | <70% |
| **ROIC** | NOPAT / Invested Capital | >15% (through cycle) | <WACC |
| **FCF Yield** | FCF / Market Cap | >8% | <3% |
| **Debt/EBITDA** | Total Debt / EBITDA | <2.0x | >3.5x |
| **Commodity Price Sensitivity** | EBITDA change per 10% commodity price move | Managed via hedges | Unhedged, high beta |
| **Reserve Life (mining)** | Proven + Probable reserves / Annual production | >20 years | <10 years |
| **Replacement Capex Ratio** | Sustaining capex / Depreciation | <80% | >120% |
| **Environmental Liability** | Asset retirement obligations / Market cap | <10% | >25% |

## Utilities (GICS 55)

| Metric | Formula/Definition | Bullish Threshold | Bearish Threshold |
|--------|-------------------|-------------------|-------------------|
| **Allowed ROE vs Earned ROE** | Regulatory ROE - Actual ROE | Earned > Allowed (over-earning) | Earned < Allowed by >100bp |
| **Rate Base Growth** | YoY rate base change | >6% | <2% |
| **Regulatory Lag** | Time from capex to rate recovery | <12 months | >24 months |
| **Capacity Factor** | Actual generation / Maximum potential | >90% (nuclear), >35% (solar), >45% (wind) | Declining YoY |
| **Renewable Generation %** | Renewable MWh / Total MWh | Growing >5pp YoY | Declining or stagnant |
| **Debt/EBITDA** | Total Debt / EBITDA | <5.0x (regulated) | >6.5x |
| **FFO/Debt** | Funds From Operations / Total Debt | >18% | <12% |
| **Dividend Payout Ratio** | Dividends / EPS (or FFO) | 60-75% (regulated) | >90% (unsustainable) |
| **O&M Cost/MWh** | Operating & Maintenance cost per MWh | Declining or stable | Rising >3% YoY |
| **Carbon Intensity** | tCO2e / MWh generated | Declining >5% YoY | Above peer median |

## Insurance (GICS 40 — Financials sub-sector)

| Metric | Formula/Definition | Bullish Threshold | Bearish Threshold |
|--------|-------------------|-------------------|-------------------|
| **Combined Ratio (P&C)** | (Losses + Expenses) / Premiums | <95% | >105% |
| **Loss Ratio** | Incurred Losses / Earned Premiums | <65% | >75% |
| **Expense Ratio** | UW Expenses / Written Premiums | <30% | >38% |
| **Reserve Development** | Prior-year reserve change / Beginning reserves | Favorable +0 to +3% | Adverse >2% of equity |
| **NWP Growth** | YoY Net Written Premium change | 8-15% | <0% |
| **ROE (P&C)** | Net Income / Equity | >10% | <5% |
| **BVPS Growth** | Book Value Per Share YoY | >8% | <0% |
| **P/B Ratio** | Price / Book Value | 1.0-2.0× | <0.7× (distress) or >3.0× (overvalued) |
| **RBC Ratio (Life)** | Risk-Based Capital / Authorized Control Level | >400% | <250% |
| **MLR (Health)** | Medical Claims / Premiums | 80-85% (individual), 85%+ (large group) | >90% |
| **Investment Yield** | Net Investment Income / Invested Assets | >4% | <2% |
| **Embedded Value Growth** | YoY EV per share growth (Life) | >8% | <3% |
| **Catastrophe Load** | Cat losses / NWP (5yr avg) | <5% | >10% |

## GICS Sector Classification Reference

| GICS Code | Sector | Key Characteristics |
|-----------|--------|---------------------|
| 10 | Energy | Commodity-price-dependent, capital-intensive, reserve-based valuation |
| 15 | Materials | Cyclical, input-cost-sensitive, global demand exposure |
| 20 | Industrials | Capital goods, transportation, backlog-driven, economic-cycle-sensitive |
| 25 | Consumer Discretionary | Cyclical, brand-dependent, retail/metrics-driven |
| 30 | Consumer Staples | Defensive, pricing-power-dependent, volume-driven |
| 35 | Health Care | Regulatory-dependent, pipeline-driven (pharma/biotech), demographic tailwind |
| 40 | Financials | Rate-sensitive, regulatory-capital-constrained, credit-cycle-driven |
| 45 | Information Technology | Innovation-driven, moat-dependent (network effects, switching costs), high gross margins |
| 50 | Communication Services | Advertising/attention-dependent, platform/metrics-driven, regulatory (net neutrality) |
| 55 | Utilities | Rate-regulated, yield-driven, capital-intensive, inflation-sensitive |
| 60 | Real Estate | Interest-rate-sensitive, occupancy-driven, NAV-based valuation |
