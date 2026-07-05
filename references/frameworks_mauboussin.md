# Mauboussin's Expectations Investing & Capital Allocation Frameworks

## Mauboussin: Expectations Investing (Reverse DCF)

### Core Principle
The current stock price embeds the market's expectations for future financial performance. The analyst's job is to reverse-engineer those expectations and ask: are they realistic? The gap between market-implied expectations and your fundamental forecast is the investment opportunity.

### The Expectations Infrastructure

| Layer | Question | Method |
|-------|----------|--------|
| **Price-Implied Expectations** | What does the current stock price imply about future growth, margins, and ROIC? | Reverse DCF, reverse DDM |
| **Fundamental Forecast** | What do I think growth, margins, and ROIC will be? | DCF, DuPont, competitive analysis |
| **Trigger Event** | What will cause the market to revise its expectations? | Catalyst calendar, earnings, regulatory |

### Reverse DCF Methodology
Instead of computing intrinsic value from assumptions, compute the assumptions the market is pricing in:

1. Start with current stock price as the "fair value"
2. Solve for the implied revenue growth rate over 5-10 years (holding margins and investment constant)
3. Solve for the implied operating margin (holding growth constant)
4. Compare to:
   - Historical growth/margins of the company
   - Industry growth rates and margin profiles
   - TAM penetration rates (is implied growth > TAM?)
   - Peer company growth/margins

### Expectations Gap Analysis

| Gap Type | Implication | Action |
|----------|-------------|--------|
| **Implied growth < Fundamental forecast** | Market is underpricing growth | Buy (growth at value price) |
| **Implied growth > Fundamental forecast** | Market is over-optimistic | Sell/Avoid (growth trap) |
| **Implied margin < Historical margin** | Negative expectations; potential mean reversion | Investigate: permanent impairment or temporary? |
| **Implied margin > Historical margin** | Optimistic expectations; mean reversion risk | Investigate: structural margin improvement or peak? |

## Mauboussin: Capital Allocation Framework

### The CEO's 5 Capital Allocation Levers

Every dollar of free cash flow must be allocated to one of five uses. Management's skill in this allocation is the single most important determinant of long-term shareholder returns.

| Lever | Good Allocation | Bad Allocation | Assessment Metric |
|-------|----------------|----------------|-------------------|
| **1. Reinvest in the Business** | Organic investment at ROIC > WACC | Empire-building; investing below cost of capital | Incremental ROIC vs WACC |
| **2. M&A** | Acquisitions at < intrinsic value with synergy | Overpaying; "strategic" acquisitions without synergy quantification | ROIC on acquisitions 3 years post-close |
| **3. Buybacks** | Repurchasing below intrinsic value | Buying at peak prices; offsetting SBC without net reduction | Buyback ROI: (Intrinsic Value - Avg Buyback Price) / Avg Buyback Price |
| **4. Dividends** | Sustainable payout from FCF; tax-efficient return | Debt-funded dividends; cutting growth investment for payout | Payout ratio < 80% of FCF |
| **5. Debt Paydown** | Reducing leverage when spreads are wide | De-levering at the bottom of the cycle | Optimal leverage range (sector-adjusted) |

### The Buffett Retention Test (Mauboussin Extensions)

**The "One-Dollar Test"**: For every $1.00 of retained earnings (earnings minus dividends), has the company generated at least $1.00 of market value over the past 5 years?

Compute:
- **5-Year Cumulative Retained Earnings** = Sum of (Net Income - Dividends) over 5 years
- **5-Year Market Cap Change** = Current Market Cap - Market Cap 5 Years Ago
- **Retention Ratio** = 5-Year Market Cap Change / 5-Year Cumulative Retained Earnings

| Retention Ratio | Interpretation |
|-----------------|----------------|
| >1.5x | Excellent — management has created >$1.50 for every $1 retained |
| 1.0-1.5x | Good — management creating value |
| 0.5-1.0x | Poor — retained earnings destroying value; should have paid dividends |
| <0.5x | Destructive — serious capital allocation failure |

### Capital Allocation Scorecard (1-10)

Score each lever on 1-10, then compute weighted average:

| Lever | Weight | 8-10 (Excellent) | 5-7 (Adequate) | 1-4 (Poor) |
|-------|--------|-----------------|----------------|------------|
| Organic Reinvestment | 30% | ROIC > 15%, incremental ROIC > 20% | ROIC > WACC | ROIC < WACC |
| M&A | 20% | ROIC on acquisitions > 15% after 3 years | ROIC > WACC; integration successful | Destroyed value; write-downs |
| Buybacks | 20% | Bought below intrinsic value; net share count declining | Bought at fair value; offset SBC only | Bought at peak; net share count flat or rising |
| Dividends | 15% | Sustainable (FCF payout < 60%); growing | Stable; FCF payout 60-80% | Dividend cut or funded by debt |
| Debt Management | 15% | Optimal leverage; opportunistic refinancing | Within sector norms | Excessive leverage; covenant risk |

### SBC (Stock-Based Compensation) Dilution Analysis

| Metric | Threshold | Interpretation |
|--------|-----------|----------------|
| SBC as % of Revenue | <5% acceptable, >10% aggressive | Higher = more dilution from equity-based pay |
| Net Share Count Change (5yr) | Negative (buying back) = good; >2% annual dilution = red flag | Factor SBC into per-share metrics |
| SBC / FCF | <20% manageable; >50% consumption of cash generation | High SBC companies can look FCF-positive but are diluting shareholders |

## Mauboussin: Competitive Advantage Period (CAP)

The CAP is the number of years a company can earn returns above its cost of capital. It is the single most important driver of intrinsic value.

### CAP Estimation Framework

| Factor | High CAP (>15 years) | Medium CAP (5-15 years) | Low CAP (<5 years) |
|--------|---------------------|------------------------|---------------------|
| **Moat Width** | Wide & widening | Narrow but stable | None or narrowing |
| **Industry Structure** | Oligopoly or monopoly | Concentrated; some competition | Fragmented; low barriers |
| **Innovation Cycle** | Long cycle (10+ years) | Medium cycle (5-10 years) | Short cycle (1-3 years) |
| **Customer Stickiness** | High switching costs or network effects | Moderate brand loyalty | Low switching costs |
| **Regulatory Protection** | License-gated; patent-protected | Some regulatory advantage | No regulatory moat |
| **Disruption Risk** | Low — technology is a moat | Moderate — watch for disruption | High — disruptive technology exists |

### CAP Impact on Intrinsic Value
- Extending CAP from 5 to 10 years can increase intrinsic value by 40-60% (for high-ROIC companies)
- CAP is more important than near-term growth for value — a wide-moat company growing at 5% can be worth more than a no-moat company growing at 15%

## Damodaran: Narrative-to-Numbers Framework

### The 5-Step Process

1. **Narrative**: Tell the story of the company — what does it do, why does it have an edge, what's the growth runway?
2. **Narrative Check**: Can the story be backed by data? Is it plausible given industry structure?
3. **Numbers**: Translate each element of the narrative into a specific forecast input:
   - Market size → Revenue growth
   - Market share → Revenue trajectory
   - Pricing power → Gross margin
   - Operating leverage → Operating margin
   - Reinvestment needs → Capex/Sales and ROIC
   - Risk → Cost of capital
4. **Numbers Check**: Do the numbers make sense? Can the company really grow revenue at 25% for 10 years in a $100B TAM?
5. **Connect Narrative to Numbers**: For every forecast assumption, link back to the narrative. For every narrative claim, link to a forecast input.

### Narrative Archetypes (Damodaran)

| Archetype | Narrative | Key Forecast Drivers | Risk Factor |
|-----------|-----------|---------------------|-------------|
| **Disrupter** | New technology changes the game | High revenue growth (30%+), expanding TAM, improving unit economics | Adoption risk, incumbent response, capital needs |
| **Compounders** | Steady, consistent growth | Moderate growth (8-15%), stable margins, high ROC | Valuation multiple compression; growth deceleration |
| **Cyclical Recovery** | Earnings to recover from trough | Revenue recovery to prior peak, margin normalization | Recovery timeline uncertainty; structural damage |
| **Turnaround** | Distressed company improving | Revenue stabilization, cost cutting, asset sales | Insolvency risk; restructuring failure |
| **Mature Cash Cow** | Slow growth, high cash generation | Low growth (2-4%), high margins, high payout | Disruption risk; terminal decline |

### Narrative Breaks & Pivot Signals

A "narrative break" occurs when the market's story about a company changes. These create the largest price moves:

| Signal | Old Narrative | New Narrative |
|--------|--------------|---------------|
| Revenue growth decelerates 2+ quarters | Growth company | Mature company |
| Margins structurally improve | Commodity business | Brand business |
| New competitor enters with 10x better product | Moat company | Commodity business |
| Regulatory approval/denial | Pre-revenue speculative | Operating company (or zero) |
| Management change to proven operator | Mismanaged | Turnaround candidate |
