# Narrative, Structure & Event Frameworks

## Damodaran's Narrative + Numbers

### The Methodology
Every valuation begins with a story about the company's future. The narrative must be:
1. **Possible** — Not violating laws of economics/physics
2. **Plausible** — Consistent with macro environment and company history  
3. **Probable** — Has evidence supporting it over alternatives

### Narrative Articulation (3-Sentence Rule)
Before any financial modeling, write exactly 3 sentences describing the company's future:
- Sentence 1: Revenue story (where growth comes from, market evolution)
- Sentence 2: Profitability story (margin trajectory, operating leverage, competitive dynamics)
- Sentence 3: Risk story (what could go wrong, reinvestment needs, capital structure)

### Narrative-to-Model Variable Mapping

| Narrative Element | Financial Variable | Typical Range | Evidence Required |
|---|---|---|---|
| "Dominant market position" | Revenue growth rate, pricing power | Above-industry growth, stable/expanding margins | Market share data, pricing trends |
| "Expanding into adjacencies" | TAM expansion, reinvestment rate | Higher capex/revenue, lower near-term FCF | Product roadmap, M&A history |
| "Margin expansion" | Operating margin trajectory | Convergence to best-in-class peers | Operating leverage, mix shift evidence |
| "Commoditizing industry" | Declining margins, price competition | Revenue growth slowing, margin compression | Industry pricing data, new entrants |
| "Platform network effects" | Winner-take-most, declining CAC | Increasing returns to scale | DAU/MAU trends, engagement, retention |
| "Cyclical recovery" | Reversion to mean earnings | Historical peak/trough margins | Capacity utilization, order book |
| "Turnaround/restructuring" | Improving from depressed base | ROIC approaching WACC | Management actions, cost cuts, divestitures |
| "Cash cow / mature" | Minimal growth, maximum FCF | Low reinvestment, high payout | Declining capex/revenue, buyback intensity |

### Competing Narrative Framework
For every stock, identify 2-3 competing narratives and assign probabilities:

| Narrative | Probability | Revenue CAGR | Terminal Margin | Fair Value |
|---|---|---|---|---|
| Bull narrative | X% | Y% | Z% | $A |
| Base narrative | X% | Y% | Z% | $B |  
| Bear narrative | X% | Y% | Z% | $C |

**Probability-weighted value** = Sum(Prob x Fair Value)

### Narrative Shift Detection
Monitor these signals for narrative changes:
- Management language shifts in earnings calls (compute via `calculate_candor.py`)
- Capital allocation changes inconsistent with stated narrative
- Insider activity diverging from stated optimism
- Revenue mix shifting away from narrative's core driver
- Analyst consensus revisions accelerating in one direction

### "What Story Is the Market Telling?" (Reverse Narrative)
1. Compute reverse DCF implied growth rate (from `calculate_metrics.py`)
2. Translate the implied growth into a narrative: "The market is pricing in [X]"
3. Compare to your narrative: If market's implied narrative is more pessimistic than yours, potential opportunity. If more optimistic, potential risk.
4. Quantify the gap: "Market expects 8% growth for 10 years. I expect 12% for 5 years then 5%. My narrative implies $X vs market price of $Y."

### Narrative Consistency Checks
Flag if ANY of these inconsistencies exist (indicates unreliable management):
- Management says "growth" but buyback > R&D spending
- Management says "investing in future" but reducing sales headcount
- Management says "strong demand" but inventory is rising >20% YoY
- Management says "disciplined M&A" but acquisition multiples are expanding
- Management says "market leader" but market share is declining

---

## Seth Klarman's Margin of Safety Framework

### Core Principle
**Downside-first analysis**: Before asking "what can go right?", rigorously answer "what can go wrong?" and "how much can I lose permanently?"

### Margin of Safety Calculation

| Method | Formula | Application |
|---|---|---|
| DCF-based | (Intrinsic Value - Market Price) / Intrinsic Value | All companies |
| Liquidation-based | (Liquidation Value - Market Price) / Liquidation Value | Asset-heavy, distressed |
| Private market-based | (LBO Floor - Market Price) / LBO Floor | PE-buyable companies |
| Replacement cost-based | (Replacement Cost - EV) / EV | Capital-intensive industries |

### Required Margin by Confidence Level

| Confidence in Intrinsic Value | Minimum Required Margin |
|---|---|
| High (Tier 1 data, stable business) | 15-20% |
| Medium (some uncertainty in key drivers) | 25-35% |
| Low (cyclical, early-stage, limited data) | 40-50%+ |

### Catalyst Requirement (Mandatory for Buy Ratings)

Every "Buy" recommendation MUST include at least one catalyst. Classify each:

| Type | Definition | Examples | Reliability |
|---|---|---|---|
| **Hard Catalyst** | Definite event with known date | Earnings release, FDA decision, spin-off record date, dividend initiation, index inclusion | High — event WILL happen, outcome uncertain |
| **Soft Catalyst** | Gradual recognition, no fixed date | Market re-rating, multiple expansion, analyst coverage initiation, peer M&A | Low — may never occur |
| **Structural Catalyst** | Change in company structure | Activist campaign, management change, strategic review, debt refinancing | Medium — in progress but timeline uncertain |

**Rule**: A thesis with ONLY soft catalysts cannot receive a "Buy" rating — maximum "Hold/Accumulate."

### Permanent vs Temporary Impairment

| Factor | Temporary (Buy opportunity) | Permanent (Avoid/Sell) |
|---|---|---|
| Revenue decline | Cyclical downturn, one-time event | Secular disruption, market share loss to superior technology |
| Margin compression | Input cost spike, promotional spending | Structural cost disadvantage, pricing power permanently eroded |
| Management issue | Execution miss (fixable) | Integrity breach, fraud, systematic misallocation |
| Balance sheet | Short-term liquidity (refinanceable) | Structural insolvency, covenant breach with no cure |
| Competitive position | Temporary headwind from new entrant | Moat permanently breached, switching costs eliminated |

### Value Trap Avoidance Checklist
Before recommending any "cheap" stock, verify it is NOT a value trap:
1. [ ] Revenue is stable or growing (not in secular decline)
2. [ ] There is at least ONE hard or structural catalyst within the time horizon
3. [ ] Management is actively returning capital OR investing at ROIC > WACC
4. [ ] The "cheapness" has NOT persisted for >3 years without catalyst (if so, likely deserved)
5. [ ] Industry structure is not permanently impaired (not a declining industry with no barriers)
6. [ ] No governance issues preventing value realization (entrenched management, dual-class)

If ANY box is unchecked, classify as "Potential Value Trap" and require additional justification.

### Klarman's Edge Taxonomy

| Edge Type | Description | Durability | Example |
|---|---|---|---|
| **Informational** | Know something others don't | Low (disappearing in information age) | Channel checks revealing demand shift before quarterly report |
| **Analytical** | Process same information better | Medium | Superior modeling, framework integration, second-level thinking |
| **Behavioral** | Act rationally when others panic | High (human nature is constant) | Buying during forced selling, selling during euphoria |
| **Structural** | Exploit market mechanism limits | High | Small-cap neglect, spin-off forced selling, index rebalancing |

---

## Stan Weinstein's Stage Analysis

### Four Stages of Price Structure

| Stage | Name | 30-Week MA | Volume Pattern | Duration | Action |
|---|---|---|---|---|---|
| **1** | Basing / Accumulation | Flattening after decline | Low, sporadic volume spikes | 3-12+ months | Watch, do not buy |
| **2** | Advancing | Rising, price above | Expanding on rallies, contracting on pullbacks | Months to years | BUY on breakout |
| **3** | Topping / Distribution | Flattening after advance | High volume on down days, low on up | 1-6 months | SELL, take profits |
| **4** | Declining | Falling, price below | Expanding on selloffs | Months to years | AVOID, never buy |

### Stage Transition Detection Rules

**Stage 1 → Stage 2 Breakout (BUY signal)**:
1. Price breaks above the Stage 1 trading range on ABOVE-AVERAGE weekly volume (>150% of 10-week avg)
2. 30-week MA has flattened and begins to turn up
3. Relative strength vs market is improving (not lagging)
4. Volume confirmation: breakout week volume must be highest in 10+ weeks

**Stage 2 → Stage 3 (SELL warning)**:
1. Price begins trading sideways after extended advance
2. 30-week MA flattens (no longer rising)
3. Volume shifts: heavy volume on down weeks, light on up weeks
4. New highs made on declining volume (bearish divergence)
5. Price violates rising trendline from Stage 2 base

**Stage 3 → Stage 4 (EXIT signal)**:
1. Price breaks below Stage 3 support on heavy volume
2. 30-week MA turns decisively down
3. First rally attempt fails at the 30-week MA (kiss of death)
4. Relative strength turns negative

### Weekly Chart Primacy
- **ALWAYS use weekly charts** for stage classification (not daily)
- The 30-week moving average is the structural backbone
- Daily charts are only for timing entries/exits within the stage framework
- Monthly charts confirm the secular trend

### Relative Strength Requirement
- Only buy stocks with relative strength rank in the TOP 20% of the market
- RS is calculated as: stock performance / market performance over 6-12 months
- A stock in Stage 2 with poor RS will underperform even in a bull market

---

## William O'Neil's CANSLIM

### Scoring Methodology (Pass/Fail per dimension)

| Letter | Criterion | Pass Threshold | Fail Threshold | Data Source |
|---|---|---|---|---|
| **C** | Current quarterly EPS growth (YoY) | ≥25% | <15% | `fetch_financials.py` quarterly earnings |
| **A** | Annual EPS growth (5-year CAGR) | ≥25% | <15% | `fetch_financials.py` annual earnings |
| **N** | New product, management, or price high | Identifiable catalyst + within 5% of 52wk high | No catalyst, >15% below high | Web search + `fetch_technicals.py` |
| **S** | Supply (shares outstanding) + Demand (volume) | Float <25M shares OR volume surge >50% on breakout | Oversupplied, no volume interest | `fetch_financials.py` shares + volume data |
| **L** | Leader (RS rank) | RS rank top 20% of market (>80) | RS rank bottom 50% (<50) | `fetch_technicals.py` relative strength |
| **I** | Institutional sponsorship | Growing # of institutional owners + quality funds | Declining institutions, no quality names | `fetch_sentiment.py` institutional data |
| **M** | Market direction | Confirmed uptrend (follow-through day) | Distribution day count >5, confirmed downtrend | `fetch_technicals.py` market indices |

### Composite Score
- **7/7 Pass** = Strong Buy candidate (all stars aligned)
- **5-6/7 Pass** = Buy candidate (minor weaknesses acceptable)
- **3-4/7 Pass** = Hold / Watch only
- **<3/7 Pass** = Avoid (fundamental or technical weakness)

### Follow-Through Day (FTD) Methodology for M-Factor
A market bottom is confirmed when:
1. Major index (S&P 500 or Nasdaq) makes a swing low
2. On Day 4 or later of the attempted rally, index gains >1.5% on volume higher than prior day
3. This is the "follow-through day" — signal that institutional buyers are committing

Distribution day count: A day when index drops >0.2% on volume higher than prior day. When 5+ distribution days accumulate in 25 trading sessions, market is under distribution → M-Factor fails.

---

## Capital Structure & Shareholder Return Analysis

### Buyback Effectiveness Score

| Metric | Excellent (8-10) | Average (4-7) | Poor (1-3) |
|---|---|---|---|
| Buyback ROI (5yr) | Avg buyback price 20%+ below current | Within ±10% of current | Avg buyback price >20% above current |
| Net dilution | Net shares declining >2%/yr | Net shares flat (±0.5%) | Net shares growing >1%/yr (SBC > buybacks) |
| SBC/Revenue | <3% | 3-8% | >8% (excessive dilution) |
| Capital return yield | >6% total (div + net buyback) | 3-6% | <3% |
| FCF payout ratio | 40-80% (balanced) | <40% (hoarding) or 80-100% | >100% (unsustainable, funding from debt) |

### Debt Maturity Risk Assessment

| Risk Level | Condition | Action |
|---|---|---|
| **Low** | No major maturities within 2 years, or cash covers next maturity | No concern |
| **Medium** | Maturity wall in 12-24 months, refinancing likely at higher rates | Flag: estimate interest expense impact |
| **High** | Maturity in <12 months, credit spreads widening, or sub-investment-grade | Flag as material risk to thesis |

### Optimal Capital Structure Reference

| Sector | Typical Debt/EBITDA | Typical Interest Coverage | Notes |
|---|---|---|---|
| Technology | 0-2x | >10x | Conservative, abundant FCF |
| Healthcare | 2-4x | 5-8x | Moderate, pipeline uncertainty |
| Industrials | 2-3x | 5-10x | Cyclical, needs buffer |
| Consumer | 2-4x | 4-8x | Stable, supports higher leverage |
| Utilities/REITs | 4-6x | 2-4x | Regulated/contractual cash flows |
| Energy | 1-3x | 4-8x | Commodity volatility needs lower leverage |

---

## M&A Probability & Private Market Valuation

### Acquisition Target Probability Score (0-100)

| Factor | Weight | Score 0 | Score 10 |
|---|---|---|---|
| Below-peer EV/EBITDA | 10 | At or above sector median | >30% below sector median |
| Strategic asset value | 10 | No unique assets | Critical patents/licenses/data/market access |
| Buyable size (<$50B market cap) | 10 | >$100B | <$10B |
| Clean balance sheet (net debt/EBITDA <2x) | 10 | >4x | <1x |
| Stable/predictable FCF (margin >10%) | 10 | Volatile/negative FCF | Consistent FCF >15% margin |
| Consolidating industry | 10 | Fragmented, no M&A activity | Recent sector M&A wave |
| No anti-takeover provisions | 10 | Poison pill + staggered board + dual class | Clean governance, simple structure |
| Low insider ownership (<10%) | 10 | >30% (hard to force) | <5% (easy to accumulate) |
| Recent activist 13D filing | 10 | No activist interest | Active 13D with strategic demands |
| Conglomerate discount >20% | 10 | Trading at/above SOTP | SOTP >30% above market cap |

**Interpretation**: Score >70 = High acquisition probability. 40-70 = Moderate. <40 = Low.

### LBO Affordability Model

**Methodology**: Solve for the maximum entry price at which a PE firm achieves 20% IRR over 5 years.

Assumptions (standard PE model):
- Entry leverage: 5.0x Debt/EBITDA (sensitivity: 4.0x to 6.0x)
- EBITDA growth: Company's 3-year CAGR (capped at 15% per year)
- Debt paydown: 50% of FCF applied to debt reduction
- Exit multiple: Same as entry (conservative) or +1x (optimistic)
- Transaction costs: 3% of EV

**LBO Floor Price** = The maximum per-share price that satisfies 20% equity IRR.
- If LBO Floor > Current Price → Valuation support exists (PE "put")
- If LBO Floor < Current Price → No PE floor, stock is priced above private market value

### Activist Investor Probability Score (0-100)

| Factor | Weight | Score 0 | Score 10-15 |
|---|---|---|---|
| Undervalued vs peers (P/E below median) | 15 | At or above peer median | >25% below peer median |
| Excess cash (cash >20% market cap) | 15 | Cash < 5% market cap | Cash > 25% market cap |
| Below-peer margins (op improvement opportunity) | 15 | At or above peer margins | >500bp below peer margins |
| Low insider ownership (<5%) | 15 | >20% | <3% |
| No anti-takeover provisions | 10 | Full defense package | No defenses |
| Conglomerate structure (breakup potential) | 15 | Pure-play, single segment | 3+ unrelated segments |
| Recent underperformance (1yr return below sector) | 15 | Outperforming sector | Underperforming by >20% |

**Interpretation**: Score >65 = High activist risk/opportunity. 35-65 = Moderate. <35 = Low.

### Precedent Transaction Premium Estimation

| Sector | Typical Acquisition Premium | Notes |
|---|---|---|
| Technology/Software | 30-50% | Higher for strategic (synergy value) |
| Healthcare/Pharma | 40-60% | Pipeline value, patent protection |
| Industrials | 20-35% | Mature businesses, lower synergies |
| Consumer | 25-40% | Brand value, distribution |
| Financial Services | 15-30% | Book value anchor limits premium |
| Energy | 20-35% | Reserve-based valuation limits premium |

**Takeout Price Range**: [Current Price x (1 + Low Premium)] to [Current Price x (1 + High Premium)]
