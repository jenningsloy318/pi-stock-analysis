# International Market-Specific Adjustments

Apply these adjustments when the primary listing exchange is outside the US, or when >20% of revenue comes from one of the four markets below. Layer on top of standard frameworks in `frameworks_value_growth.md`, `frameworks_risk_alt.md`, and `frameworks_macro_quant.md`. Tag every country-specific adjustment with `[INTL]` in the report narrative.

---

## China A-Shares (SSE / SZSE)

### SOE Discount Quantification

State-Owned Enterprises trade at a structural 20–40% discount to private-sector peers due to policy mandate drag, weaker ROE, and misaligned incentives. Score each company on the rubric below, then map to a discount.

| Criterion | Max Points | Scoring Guide |
|-----------|-----------|---------------|
| State ownership % | 3 | 1 = <30% state; 2 = 30–60%; 3 = >60% SASAC direct control |
| Strategic sector classification | 3 | 0 = consumer/tech; 2 = materials/industrials; 3 = defense/telecom/energy/banking |
| Management appointment source | 2 | 2 = market-recruited CEO; 1 = mixed; 0 = Party-appointed, capped comp |
| Capital allocation discipline (ROIC vs. WACC 3-yr avg) | 2 | 0 = ROIC > WACC; 1 = breakeven; 2 = value-destroying |

**Score → Discount:** 0–3 = 0–10%; 4–6 = 15–25%; 7–10 = 30–40% vs private peers.

---

### "Common Prosperity" Regulatory Risk Score (10-point scale)

Higher score = higher regulatory risk. Add score × 50 bp to WACC.

| Risk Factor | Points | Threshold |
|-------------|--------|-----------|
| Platform / marketplace business model | 3 | 3 = >50% revenue from platform intermediation; 1 = ancillary; 0 = none |
| Consumer data concentration | 2 | 2 = top-3 national consumer dataset; 1 = regional; 0 = B2B only |
| "Excessive profit" sector (edtech, gaming for minors, gig labor) | 2 | 2 = primary revenue; 1 = meaningful segment; 0 = not exposed |
| Recent SAMR / CAC / MIIT enforcement action (≤18 months) | 2 | 2 = formal investigation or fine; 1 = industry-wide notice; 0 = none |
| Founder prominence / political exposure | 1 | 1 = founder made high-profile statements or withdrew from public life |

| Score | Risk Level | Portfolio Action |
|-------|-----------|-----------------|
| 0–2 | Low | No discount; standard analysis |
| 3–5 | Moderate | 10–15% regulatory risk discount on target price |
| 6–8 | High | 20–30% discount; watch-list only, not core position |
| 9–10 | Severe | Do not initiate; exit signal if held |

---

### VIE Structure Risk (Offshore-Listed ADRs / HKEx)

Applies to all Cayman Islands–incorporated entities with mainland operating VIEs (BABA, JD, PDD, BIDU, etc.).

| Risk Dimension | Low (1) | Medium (2) | High (3) |
|----------------|---------|------------|---------|
| Contract enforceability | Tested in Chinese courts | Untested; arbitration clause only | No tested path |
| Regulatory stance (past 24 months) | CSRC expressed support for offshore listings | Neutral / ambiguous | Active statements questioning VIE legality |
| VIE revenue dependency | VIE entity <20% of revenue | 20–60% | >60% |
| PCAOB audit access | Full access granted | Partial / recent | No access |

Sum: 4–6 = manageable (5% VIE discount); 7–9 = elevated (10–15%); 10–12 = structurally impaired (20–25% or avoid).

---

### Northbound / Southbound Stock Connect Flow Thresholds

**Northbound (foreign buying mainland A-shares) — weekly net vs. 90-day rolling average**

| Signal | Threshold |
|--------|-----------|
| Strong accumulation (bullish) | Net inflow >2× 90-day average for 3 consecutive weeks |
| Mildly bullish | Net inflow 1–2× average |
| Neutral | −1× to +1× average |
| Distribution (bearish) | Net outflow >1× average |
| Panic / forced selling | Net outflow >3× average; watch for reversal |

**Southbound (mainland buying HK-listed):** Retail-driven momentum amplifier. Net inflow >HKD 3B/day sustained 5 days = speculative demand. Outflow >HKD 3B/day = risk-off. Data: HKEX daily disclosure (free).

---

### China Valuation Adjustments

| Factor | Adjustment | Rationale |
|--------|-----------|-----------|
| AH Premium | Discount H-shares / ADRs by current AH premium if buying A-share is impractical for the investor base | A-shares trade at 20–150% premium to H-shares for the same company; Hang Seng AH Premium Index (HSAHP) average ~130 |
| Retail dominance | Lower target P/E by 1–2× vs comparable US/global peers | ~80% retail trading volume drives momentum bias and 30–50% higher annualized volatility |
| T+1 settlement + 10% daily limit | Add 3–5% illiquidity premium for small-/mid-cap A-shares | Exit may require multiple days; stop-loss execution impaired during limit-down queues |
| Earnings quality | Apply 0.8× earnings quality multiplier if CFO/Net Income <0.7 in 2+ of last 3 years | State subsidy income frequently inflates GAAP earnings |

**Data Sources:** akshare (`stock_zh_a_hist`, `stock_financial_report_sina`), CSRC filings at `cninfo.com.cn`, HKEX Connect daily flow data.

---

## Japan (TSE)

### TSE P/B Reform Impact

Since March 2023, the TSE has publicly required sub-1.0× P/B companies to disclose capital efficiency improvement plans. Approximately 50% of TSE Prime constituents trade below 1.0× P/B.

| P/B Level | TSE Status | Analyst Implication |
|-----------|-----------|---------------------|
| >1.5× | Not targeted | Assess whether premium is justified by ROE |
| 1.0–1.5× | Watch list | Check if improvement plan filed and buyback/dividend increase announced |
| 0.7–1.0× | Actively targeted | High probability of value-unlocking action within 12–18 months |
| <0.7× | Priority target | Strong catalyst probability; also check for hidden real estate or equity portfolio value |

**Improvement Plan Quality Score (for sub-1.0× companies)**

| Element | Score |
|---------|-------|
| Buyback announced and executing (>1% of shares) | +2 |
| Dividend increase >10% YoY | +1 |
| Cross-shareholding reduction plan with specific timeline | +2 |
| ROE target with 3-year roadmap | +2 |
| Non-core asset disposal / business restructuring | +2 |
| No plan disclosed despite TSE request | −3 |

Score ≥5 = high probability of re-rating to 1.0–1.3× P/B within 18 months. Score <2 = discount likely persists.

---

### Cross-Shareholding Unwind Tracking

1. Source from annual securities report (有価証券報告書 on EDINET), section "特定投資株式" (specific investment shares).
2. Compute: Cross-held equity market value / Total equity. Ratio >15% = material balance-sheet distortion.
3. Unwind rate: Has the company reduced any cross-held positions in the past 3 fiscal years? >5%/year reduction = active unwind → positive catalyst.
4. Reveal operational ROE: Remove cross-held equity from the denominator. If operational ROE >15% but reported ROE <10%, the discount is capital-structure–driven, not operational — a stronger re-rating signal.

---

### BOJ ETF Ownership Distortion

The Bank of Japan holds approximately ¥60 trillion in domestic ETFs, creating artificial demand for TOPIX / Nikkei 225 index constituents.

| BOJ Effective Free-Float Ownership | Distortion Level | Adjustment |
|------------------------------------|-----------------|------------|
| <5% of free float | Minimal | None |
| 5–10% | Moderate | Note in risk section; reduce liquidity premium slightly |
| >10% | High (large-cap index names) | Mark-to-market price may be artificially supported; apply 5–10% haircut to price-derived momentum signals |

BOJ has signaled gradual tapering of ETF purchases. Acceleration of taper increases selling pressure on high-ownership names.

---

### Governance Reform Scoring (JPX Prime Requirements)

| Criterion | Prime Requirement | Score Guide |
|-----------|------------------|-------------|
| Board independence | ≥1/3 independent directors | +2 if ≥1/3; +3 if majority |
| Audit committee independence | Independent majority required | +2 if compliant; 0 if not |
| Cross-shareholding reduction | Active reduction expected | +2 if ≥5%/year; 0 if static |
| English-language disclosure | Timely English TDnet filings | +1 if same-day English |
| ROE target with timeline | Implied by Prime listing standards | +2 if explicit; +1 if vague; 0 if absent |
| Shareholder return policy | Specified payout ratio or buyback policy | +2 if explicit and executing |

Score 9–12 = governance premium (+5–10% to target). Score 5–8 = average. Score <5 = governance discount (−10–15%).

**JPX400 vs. TOPIX:** JPX400 uses ROE and operating profit screens. Inclusion in JPX400 = governance quality signal; exclusion from JPX400 despite TOPIX membership = potential red flag.

**Data Sources:** EDINET (`disclosure.edinet-fsa.go.jp`), TDnet (`tdnet.info`), TSE Prime constituent list, JPX400 constituent list.

---

## India (BSE / NSE)

### Promoter Holdings Impact

"Promoter" = founding family / controlling shareholder. Influences governance, float, and forced-selling risk.

| Promoter Holding % | Governance Reading | Float / Liquidity Implication |
|--------------------|-------------------|-----------------------------|
| <20% | Weak promoter control; higher institutional discipline | Large float; liquid |
| 20–50% | Moderate control; watch related-party transactions | Adequate float |
| 50–70% | Strong control; check pledging ratio | Moderate float; monitor insider selling |
| >70% | Dominant control; limited minority recourse | Small public float; add 5–15% illiquidity premium for small/mid cap |

**Pledging Alert:** Promoter shares pledged as collateral >20% of promoter holding = high distress risk. Forced selling of pledged shares triggers cascading declines. Source: BSE/NSE quarterly shareholding pattern and pledge disclosure filings.

---

### FPI / DII Flow Analysis

Flows disclosed monthly by SEBI / NSDL. Key thresholds for monthly net:

| FPI Net Flow (USD) | Signal |
|--------------------|--------|
| Inflow >$2B | Strong foreign accumulation; risk-on |
| Inflow $500M–$2B | Moderate positive; consistent accumulation |
| Outflow $500M–$2B | Caution; monitor for INR pressure |
| Outflow >$2B | Significant risk-off; elevated INR depreciation probability |
| Outflow >$2B for 3 consecutive months | Systemic de-risking; raise defensive allocation |

**DII offset rule:** DIIs (domestic mutual funds, LIC) historically buy during FPI selling, limiting drawdowns. If DII inflows do not offset FPI outflows, treat as an unusual broad-based risk-off signal.

---

### SEBI Regulatory Framework Differences

| Dimension | US (SEC) | India (SEBI) Specifics | Analytical Impact |
|-----------|---------|----------------------|------------------|
| Insider trading windows | Company-defined blackout | PIT Regulations 2015: structured trading windows | Stricter; fewer leakage events |
| Related-party transactions | Audit committee approval | LODR Regulation 23: RPT >10% of turnover requires shareholder vote | Check RPT disclosures in annual report carefully |
| Promoter pledge | Not directly applicable | Mandatory quarterly pledge filing to exchanges | High pledge ratio = distress signal |
| Dividend withholding | Qualified dividend rate | DDT abolished 2020; dividends taxed at investor's marginal rate; 20% WHT for foreign investors | Material drag on gross yield for foreign investors |
| Delisting | SEC Rule 13e-3 | SEBI Delisting Regulations 2021: reverse book building, floor price | Historical delisting premium 25–40% above market |

---

### India Structural Growth Premium Quantification

India trades at 20–30% P/E premium to EM peers. Justified premium drivers:

| Driver | Max Premium | Assessment |
|--------|------------|------------|
| GDP growth differential vs. EM average | +10% | India GDP >6% and >3 pp above EM average = full premium |
| Demographics (median age <30, growing labor force) | +5% | Labor force growing >1.5%/year |
| Economy formalization (GST, digital payments) | +5% | Track GST e-way bill volumes YoY |
| Policy stability / FDI openness | +5% | PLI scheme execution, ease-of-doing-business ranking trend |
| Corporate earnings quality (Nifty50 ROE >14% and expanding) | +5% | Check aggregate Nifty50 ROE trend |

Justified premium = sum of applicable drivers (max +30% to EM baseline P/E). If current market P/E already embeds the full premium, returns must come from earnings growth alone.

**When premium is NOT justified:** Nifty P/E >25× trailing + EPS growth <12% + FII outflows + INR depreciation >5% = premium compression risk. Reduce India allocation.

**Data Sources:** NSE/BSE filings (`nseindia.com`, `bseindia.com`), NSDL FPI data, SEBI LODR disclosures, AMFI monthly reports.

---

## South Korea (KRX)

### Chaebol / Conglomerate Discount Quantification

| Chaebol Affiliation | Base Discount to Global Peers | Notes |
|--------------------|------------------------------|-------|
| Core holding company (e.g., Samsung C&T) | 40–60% to SOTP NAV | Holding discount is structural |
| Flagship operating subsidiary (e.g., Samsung Electronics) | 15–25% | Governance + capital allocation drag |
| Mid-tier affiliate | 20–35% | Lower liquidity; minority squeeze risk |
| Non-affiliated large-cap | 10–15% | Residual "Korea Discount" |

**Korea Discount Decomposition**

| Component | Typical Contribution | Measurement |
|-----------|---------------------|-------------|
| Governance (minority shareholder expropriation risk) | 8–12 pp | Board independence, RPT size, stewardship code compliance |
| Geopolitical risk (North Korea) | 3–5 pp | Tension index; missile test frequency; diplomatic calendar |
| Cross-holding complexity | 5–10 pp | Number of circular ownership loops; treasury share ratio |
| Low shareholder returns | 4–8 pp | Payout ratio vs. regional peers; buyback frequency and cancellation rate |

Fair value = Global sector peer EV/EBIT × Korean EBIT × (1 − justified discount). Justified discount = geopolitical only = 5–10% if governance issues are resolved.

---

### Corporate Value-up Program Tracking (2024–)

Korea's FSC launched the Value-up Program in 2024, modeled on Japan's TSE P/B reform, with added tax incentives aligning founding family interests with minority shareholders.

| Participation Status | Expected Impact |
|----------------------|----------------|
| Voluntary plan with ROE/P/B targets and timeline | Strong positive; 10–20% re-rating potential |
| Plan disclosed but vague (no numeric targets) | Mild positive; monitor for follow-through |
| KRX Value-up Index constituent | Positive; passive fund inflows |
| P/B <0.7× but no plan filed | Potential activist target; watch for NPS or foreign fund pressure |
| Plan disclosed but contradicted by subsequent capex | Negative; management credibility impaired |

---

### Korea Valuation Adjustments

| Factor | Methodology |
|--------|------------|
| Treasury shares | Exclude from market cap denominator. Korean companies often hold 5–15% treasury. Adjusted market cap = price × (total shares − treasury shares). |
| Cross-holding value | Subtract market value of listed equity stakes from EV (SOTP approach). Full equity investment schedule in DART filings. |
| Preferred vs. common discount | Korean preferred shares (우선주) trade at 15–40% discount to common despite same economic rights. Discount >40% with adequate liquidity (>$1M daily volume) is a value signal if governance is improving. |
| NPS stewardship | NPS owns ~8% of KOSPI. Track AGM voting record. NPS vote against management on capital return = high pressure signal (+5–10% re-rating expectation). |

**Data Sources:** DART (`dart.fss.or.kr`), KRX (`krx.co.kr`), Korea Corporate Governance Service (KCGS) ratings, FSC/FSS press releases.

---

## General Non-US Adjustments

### Currency Hedging Cost Impact on Returns

| Annual Hedging Cost (Cross-Currency Basis) | Net Return Impact | Decision Rule |
|-------------------------------------------|------------------|---------------|
| <50 bps/year | Negligible | Hedge or unhedged; preference-driven |
| 50–150 bps/year | Moderate drag | Justify only if alpha thesis >300 bps/year |
| 150–300 bps/year | Material drag | Require strong alpha; consider unhedged if currency trend is favorable |
| >300 bps/year (USD/BRL, USD/TRY) | Severe drag | Rarely worth hedging; assess unhedged total return explicitly |

Calculate hedging cost: 3-month cross-currency basis swap spread + forward points differential.

---

### Withholding Tax Drag by Country

| Country | WHT (Non-Treaty) | WHT (US Investor, Treaty) | Net Yield Impact |
|---------|-----------------|--------------------------|-----------------|
| Japan | 15.315% | 10% | Deduct 10% from gross dividend yield |
| China (via Stock Connect / QFI) | 10% | 10% | Deduct 10% |
| India | 20% | ~20–25% (limited standard reduction) | Material; always factor into total return |
| South Korea | 22% | 15% | Deduct 15% for US investors |
| Taiwan | 21% | 10% if >25% stake; else 21% | Significant for income investors |
| Germany | 26.375% | 15% (often partially recoverable) | Net ~15% |

Rule: Always gross up dividend yield using the applicable treaty WHT rate before comparing yields across markets.

---

### Emerging Market Liquidity Premium

| Market Cap Tier | EM Liquidity Premium | Application |
|-----------------|---------------------|-------------|
| Large cap, MSCI EM constituent | 0–2% | No adjustment for liquid names |
| Mid cap, EM index constituent | 2–5% | Add to discount rate (WACC) |
| Small cap, local exchange only | 5–10% | Add to discount rate; flag in risk section |
| Micro cap, thin float (<30% free float) | 10–20% | DCF unreliable; use relative / asset-based valuation |

Liquidity premium is additive to the Country Risk Premium below.

---

### Country Risk Premium (CRP) — Damodaran Approach

**Formula:** `ERP (Country) = ERP (Mature Market, US base ~5%) + CRP`

| CRP Method | Formula | Use Case |
|-----------|---------|----------|
| CDS-Based (preferred) | `CRP = Sovereign CDS Spread × (σ_equity / σ_bonds)` where σ ratio ≈ 1.5 for most EMs | Countries with liquid CDS markets (CN, IN, KR, BR, MX) |
| Moody's Rating Spread | Map sovereign rating to historical default spread × 1.5 equity volatility scalar | Countries without liquid CDS (frontier markets) |
| Damodaran Table | Direct lookup from `pages.stern.nyu.edu/~adamodar` (updated January each year) | Quick reference |

**Apply CRP to WACC:** `WACC (EM) = WACC (US baseline) + CRP × λ`

λ = degree of revenue exposure to local economy: 1.0 = 100% local revenue; 0.3–0.5 = multinational with local listing; 0.0 = pure USD earner with local listing.

**Reference CRP Levels (approximate 2025; update from Damodaran annually)**

| Country | Approx. CRP | Total ERP |
|---------|------------|-----------|
| Japan | 0.3–0.5% | 5.3–5.5% |
| South Korea | 0.5–1.0% | 5.5–6.0% |
| China | 1.5–2.5% | 6.5–7.5% |
| India | 1.5–2.0% | 6.5–7.0% |
| Taiwan | 0.5–1.0% | 5.5–6.0% |
| Brazil | 3.5–5.0% | 8.5–10.0% |

Always cite: `[Source: Damodaran CRP Table | Retrieved: Jan 2025 | Fact — update annually]`

---

### Quick Reference: Adjustment Trigger Checklist

| Trigger | Required Adjustment |
|---------|-------------------|
| Chinese SOE | SOE discount rubric + common prosperity score |
| Offshore-listed China ADR / HK | VIE risk score + AH premium check |
| Japan P/B <1.0× | TSE reform quality score + cross-shareholding analysis |
| Japan large-cap index constituent | BOJ ETF ownership distortion check |
| Korea chaebol affiliate | Conglomerate SOTP discount + value-up program status |
| India promoter holding >50% | Pledging ratio check + float-adjusted valuation |
| Any EM stock | CRP via Damodaran + WHT drag on yield + liquidity premium |
| Non-USD reporting currency | Hedging cost drag analysis + FX sensitivity on earnings |
