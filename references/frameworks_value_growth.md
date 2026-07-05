# Value & Growth Frameworks

## Buffett's Four Filters

1. **Circle of Competence** — Can I understand this business? What does it do, how does it make money, who are its customers?
2. **Economic Moat** — Does it have durable competitive advantages? (See Morningstar framework below.)
3. **Management Quality** — Is management honest (candor in letters/calls) and competent (capital allocation track record)?
4. **Margin of Safety** — Is the price sensible relative to intrinsic value? (See valuation methods in templates/equity-report.md.)

## Munger's Mental Models

- **Inversion**: "How could this investment destroy my capital?" — List the top 3-5 ways.
- **Lollapalooza Effect**: Where do multiple competitive advantages combine synergistically?
- **Checklist Discipline**: Before committing to any thesis, run the pre-mortem (Stage 7.8).

### Key Quantitative Screens (Buffett/Munger)
- ROE > 15% consistently (check DuPont decomposition: is it leverage-driven or operational?)
- For every $1 of retained earnings, has the company created >$1 of market value over 5 years?
- Total debt payable within 3-4 years of normalized earnings (net debt / FCF or EBITDA).
- Owner earnings yield (FCF / market cap) > 10-year Treasury yield.

## Fisher's 15 Points (Summarized)

1. Multi-year sales growth potential (market + product)
2. Determination to develop new products/processes when growth slows
3. R&D effectiveness relative to company size
4. Above-average sales organization
5. Above-average profit margins with clear maintenance strategy
6. Actions to sustain or improve margins
7. Outstanding labor and personnel relations
8. Outstanding executive relations
9. Management depth (not a one-person show)
10. Cost analysis and accounting controls
11. Industry-specific competitive advantages
12. Long-range profit outlook (not short-term optimization)
13. No equity dilution to fund growth
14. Management communicates candidly in good times and bad
15. Management integrity (non-negotiable, absolute)

## Fisher's Scuttlebutt Method

Interview (or search for public statements from):
- **Competitors**: How do they describe this company?
- **Suppliers**: Order volumes, payment terms, relationship quality
- **Customers**: Satisfaction, switching intent, pricing sensitivity
- **Former employees**: Glassdoor reviews, LinkedIn departures, exit interviews

Score convergence: 4+ independent sources → High confidence. 2-3 → Moderate. 1 or conflicting → Low, flag as unverified.

## Lynch's Six Stock Categories

| Category | Characteristics | Buy Signal | Sell Signal |
|----------|----------------|------------|-------------|
| **Slow Growers** | GDP-level growth, mature, high dividend | Dividend yield > bond yield, low P/E | P/E expands to premium, dividend cut |
| **Stalwarts** | 10-12% growth, large cap | PEG < 1.5, 30-50% upside to target | PEG > 2.0, fundamental deterioration |
| **Fast Growers** | 20-25%+ growth | PEG < 1.0, untapped market, long runway | Growth decelerates 2+ quarters |
| **Cyclicals** | Earnings tied to economic cycle | Low P/E (peak earnings), inventory restocking | High P/E (trough earnings), capacity overshoot |
| **Turnarounds** | Distressed, restructuring | Cash > burn rate, credible restructuring plan | Restructuring fails, cash runs out |
| **Asset Plays** | Assets worth > market cap | Breakup value 30%+ above market cap | Asset value deteriorates, catalyst fades |

## Competitive Moat (Morningstar Framework)

Assess each moat source with evidence:

- **Cost Advantages**: Structural cost position (scale, process, location), economies of scale, process patents. Can competitors replicate this cost structure?
- **Network Effects**: Direct (more users = more value per user), indirect/cross-side (more supply = more demand), data network effects (more usage = better product).
- **Intangible Assets**: Brands (pricing power, customer preference), patents (remaining life, citation count), regulatory licenses (barrier to entry).
- **Switching Costs**: Contractual lock-in, data migration pain, workflow integration depth, retraining cost. How much would it cost a customer to leave?
- **Efficient Scale**: Natural monopoly characteristics, limited market that supports only 1-2 profitable players.

**Moat trajectory**: Is the moat widening (market share gaining, pricing power strengthening, switching costs increasing), stable, or narrowing? Cite specific evidence.

## 4-Moat Decision Framework (MUST follow for every company)

This is the **decision-discipline overlay** that condenses the Morningstar 5-source list into a 4-row decision table. It is MANDATORY in every long/mid/short equity report. The Morningstar list above is the analytical taxonomy; this is the output discipline.

### Rating scale (S/M/W mapped to 1-10)

| Rating | Numeric (1-10) | Meaning |
|--------|----------------|---------|
| **Strong** | 8-10 | Multi-year quantified evidence; competitor with $10B+ capital cannot replicate within 5 years |
| **Moderate** | 5-7 | Real advantage but contestable; replication possible with capital + time |
| **Weak** | 1-4 | No durable barrier; competitors can match on equal terms |

### The 4-row decision table (REQUIRED in every report)

| 护城河类型 (Moat Type) | 关键判断问题 (Key Question) | 评级 (Rating) | 量化证据 (Quantified Evidence) | 来源 (Source) |
|---|---|---|---|---|
| **网络效应 Network Effects** | Does user growth self-reinforce? Same-side or cross-side? | S/M/W (n/10) | e.g., "300万 CUDA developers; 12% YoY active dev growth; cross-side: dev count → workload demand" | [citation] |
| **转换成本 Switching Costs** | How costly to switch to a competitor (time, money, retraining, workflow rebuild)? | S/M/W (n/10) | e.g., "Salesforce 90%+ renewal rate; avg integration depth = 14 systems" | [citation] |
| **规模优势 Scale Advantages** | Does unit cost fall meaningfully with scale? Can a new entrant reach break-even? | S/M/W (n/10) | e.g., "TSMC capacity 90%+ utilization; new fab requires $20B+ capex; gross-margin gap vs #2 = 18pp" | [citation] |
| **无形资产 Intangible Assets** | Brand premium / patent / license / proprietary data competitors cannot copy? | S/M/W (n/10) | e.g., "Constellation 13 nuclear reactors; zero new US licenses issued in 30+ years" | [citation] |

**Evidence-specificity rule**: A vague claim ("strong brand") is not evidence. Required form: a quantified statement with a number AND a source. Reject placeholder evidence.

### The $10B counterfactual (forcing function)

For each moat rated **Strong**, the report MUST answer:

> 如果一个竞争者拥有 $100 亿美元资本和 5 年时间，能否复制这家公司的 [moat type]？
> *If a well-funded competitor had $10B and 5 years, could they replicate this [moat]?*

- **Yes** → downgrade to Moderate or Weak (cite *what specifically* could be replicated and at what cost).
- **No** → keep Strong (cite *what specifically* prevents replication: sequencing barrier, regulatory monopoly, install-base lock-in, dataset that took N years to accumulate, etc.).

This test prevents inflated moat scores driven by halo from current high margins or growth.

### Anti-pattern checks (MUST run for every Strong rating)

Every Strong rating must explicitly clear both anti-pattern checks:

1. **First-mover ≠ moat**. Being first only matters if it created a network/switching/scale lock-in that late entrants cannot match. MySpace/Nokia/BlackBerry were first; that didn't save them. State explicitly *what about being first translated into durable barriers*.
2. **High growth ≠ moat**. Growth often reflects industry tailwind, not company-specific advantage. State explicitly *what fraction of growth comes from the company's barriers vs. industry tailwind*. If growth is industry-driven, do NOT use it as moat evidence.

A Strong rating that fails either anti-pattern check must be downgraded to Moderate.

### Peer-pair moat comparison (REQUIRED)

For every company analyzed, identify ONE direct peer riding the SAME secular theme and produce a side-by-side moat table. The pair must share a tailwind (e.g., AI infra → NVIDIA vs. Dell; cloud → AWS vs. Oracle Cloud) so the comparison isolates moat from theme.

| 护城河 | [Company] | [Peer on same theme] |
|---|---|---|
| 网络效应 | S/M/W + 1-line evidence | S/M/W + 1-line evidence |
| 转换成本 | S/M/W + 1-line evidence | S/M/W + 1-line evidence |
| 规模优势 | S/M/W + 1-line evidence | S/M/W + 1-line evidence |
| 无形资产 | S/M/W + 1-line evidence | S/M/W + 1-line evidence |

This forces the analyst to distinguish *theme-driven* return potential from *moat-driven* durability. Two companies on the same theme can have radically different unit economics — the peer pair makes this visible (NVIDIA 60%+ op-margin vs Dell server single-digit op-margin under the same AI capex wave).

### How this maps to the deterministic moat score

`compute_moat_quality()` produces a quant proxy from op-margin / ROE / revenue-CAGR. The LLM may adjust ±2.0 based on the 4-moat table above. Adjustment rules:

- 4 Strong → may add up to +2.0
- 3 Strong → may add up to +1.0
- 2 Strong → no adjustment (neutral)
- 1 Strong → may subtract up to −1.0
- 0 Strong → may subtract up to −2.0

Every adjustment must cite the specific row(s) of the decision table that justify it.

## Porter's Five Forces

For each force, rate as High/Medium/Low and provide evidence:

1. **Threat of New Entrants** — Capital requirements, regulatory barriers, brand loyalty, scale advantages, access to distribution
2. **Supplier Power** — Supplier concentration, switching costs to alternative suppliers, input differentiation
3. **Buyer Power** — Customer concentration, price sensitivity, availability of substitutes, information symmetry
4. **Threat of Substitutes** — Alternative products/services, relative price-performance, buyer switching costs
5. **Competitive Rivalry** — Number of competitors, industry growth rate, exit barriers, product differentiation

## DuPont Decomposition

Break ROE into its drivers to identify whether returns come from profitability, efficiency, or leverage:

```
ROE = Net Profit Margin × Asset Turnover × Equity Multiplier
    = (Net Income / Revenue) × (Revenue / Total Assets) × (Total Assets / Shareholders' Equity)
```

**5-Factor Extended DuPont:**
```
ROE = Tax Burden × Interest Burden × Operating Margin × Asset Turnover × Leverage
    = (NI/EBT) × (EBT/EBIT) × (EBIT/Revenue) × (Revenue/Assets) × (Assets/Equity)
```

**Interpretation:**
- High ROE from high margin = strong pricing power / moat (bullish)
- High ROE from high turnover = efficient operations (neutral to bullish)
- High ROE from high leverage = financial risk (bearish signal — fragile)

Compare each component to: (1) company's own 5-year history, (2) sector median, (3) direct peers. Flag which component is driving ROE changes over time.

## BCG Matrix (Segment Classification)

For multi-segment companies, classify each business unit:

| Quadrant | Market Growth | Relative Market Share | Strategy |
|----------|--------------|----------------------|----------|
| **Star** | High (>10%) | High (>1.0x leader) | Invest to maintain leadership |
| **Cash Cow** | Low (<5%) | High (>1.0x leader) | Harvest cash, minimal reinvestment |
| **Question Mark** | High (>10%) | Low (<1.0x leader) | Invest selectively or divest |
| **Dog** | Low (<5%) | Low (<1.0x leader) | Divest or restructure |

**Application:**
1. Plot each segment on the matrix using segment revenue growth and estimated relative market share
2. Assess capital allocation: Is management investing in Stars/Question Marks and harvesting Cash Cows? Or subsidizing Dogs?
3. SOTP implications: Stars and Cash Cows justify premium multiples. Dogs may warrant discount or spin-off catalyst

## Ecosystem & Value Chain Framework

**Single-Point-of-Failure (SPOF) Analysis:**
For each critical dependency (supplier, platform, infrastructure, partner), score:
- Probability of disruption (1-5): based on historical incidents, financial health, geopolitical exposure
- Impact severity (1-5): revenue loss if unavailable for >48 hours
- SPOF Score = Probability × Severity (>15 = critical risk requiring mitigation plan)

**Complementor Health Assessment:**
- Are the ecosystem participants growing or declining?
- Are developer/partner counts increasing year-over-year?
- Is the platform investing in partner success (APIs, tooling, revenue share)?
- Counter-indicator: platform owner competing with its own ecosystem partners (e.g., Amazon vs. third-party sellers)
