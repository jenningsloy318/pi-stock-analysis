# Scoring Calibration & Interpretation Guide

## Score-to-Outcome Mapping

This reference defines what each conviction score should mean in terms of expected forward returns. Use it to calibrate analyst judgments and avoid grade inflation.

### Expected 12-Month Return Ranges by Rating

| Score | Rating | Expected Return Range | Win Rate Target | Notes |
|-------|--------|----------------------|-----------------|-------|
| 9.0-10.0 | Strong Buy | +25% to +50%+ | >70% | Multiple framework convergence required |
| 7.5-8.9 | Buy | +15% to +30% | >60% | At least 3 frameworks supportive |
| 6.0-7.4 | Hold / Accumulate | +5% to +15% | >55% | Market-perform or slight outperformance |
| 4.0-5.9 | Hold / Reduce | -5% to +5% | N/A | Market-perform; no edge |
| 2.0-3.9 | Sell | -10% to -25% | >60% (decline) | Active deterioration expected |
| 1.0-1.9 | Strong Sell | -25% to -50%+ | >65% (decline) | Structural impairment |

### Position Sizing by Conviction

| Conviction | Max Position (% AUM) | Kelly Fraction Estimate |
|------------|---------------------|------------------------|
| 9.0+ | 8-12% | Full Kelly |
| 7.5-8.9 | 5-8% | Half Kelly |
| 6.0-7.4 | 3-5% | Quarter Kelly |
| < 6.0 | 0% (no new position) | Zero |

## Confidence Level Definitions

| Confidence | Quantitative Meaning | Source Coverage | Score Uncertainty |
|------------|---------------------|-----------------|-------------------|
| High | 80%+ probability that true value is within ±1.0 of stated score | All blocking dimensions pass, 0-1 stale non-critical | ±0.5 points |
| Medium | 65-80% probability | One non-central dimension missing/stale | ±1.5 points |
| Low | 50-65% probability | Two+ dimensions missing or stale | ±2.5 points |

### Confidence Impact on Position Sizing
- High confidence → use full conviction-based sizing
- Medium confidence → reduce position by 40%
- Low confidence → reduce position by 70% (or skip entirely)

## Component Score Calibration

### What a "7" Means for Each Component

| Component | Score = 7 Benchmark |
|-----------|---------------------|
| Financial Health | Top-quartile margins for sector, expanding trajectory, 10-15% ROE, incremental ROIC > 20%, D/E < 1.5x (sector-adjusted), current ratio > 1.5, CCC improving or negative, positive FCF growth |
| Capital Allocation | Buffett retention ratio > 1.0x over 5yr, buyback ROI positive (bought below intrinsic value), M&A ROIC > WACC 3yr post-close, SBC < 5% revenue, net share count flat or declining, payout ratio < 80% FCF |
| Quality of Earnings | Beneish M-Score < -2.22 (clean), OCF/NI ratio > 0.9 over 5yr (strong cash conversion), accruals < 5% of assets, no revenue recognition red flags, expense capitalization within industry norms |
| Moat Quality | Clear competitive advantage, stable/gaining share, 5yr ROIC > WACC, CAP (Competitive Advantage Period) estimated > 10 years |
| Management Quality | 3+ consecutive earnings beats, net insider buying, competent capital allocation, candid communication, skin in the game (insider ownership > 5%) |
| Valuation | 10-20% below DCF fair value, PEG 1.0-1.3, FCF yield > 4%, EV/EBIT < sector median, reverse DCF implied growth < analyst consensus |
| Capital Structure | Buybacks creating value (above-market ROI), SBC < 5% revenue, near-optimal leverage, debt maturity well-laddered, interest coverage > 5x |
| Supply Chain Resilience | Geographic HHI < 2,500 (supplier), < 20% COGS from single-source, at least dual-source for critical components, DIO adequate vs lead times, documented contingency plans |
| Macro Tailwind | Goldilocks or reflation regime, no yield curve inversion, PMI > 52, central bank neutral-to-easing, economic surprises positive |
| Regulatory / Policy | Stable regulatory framework, no pending adverse legislation, government policy neutral-to-supportive, trade policy steady |
| Market Regime | Weinstein Stage 2, RS composite > 1.0, institutional flows net positive, VIX < 25, credit spreads within normal range |
| Risk Profile | Altman Z safe (>2.99), Beneish clean (< -2.22), manageable leverage, stable earnings, Taleb fragility score > 40 (robust-to-antifragile) |
| ESG & Sustainability | TCFD aligned, carbon pricing NPV impact < 5% of market cap, no MSCI/Sustainalytics red-flag controversies, SASB material issues managed, board > 30% independent |
| Alternative Alignment | 3+ alt signals confirming (web traffic rising, social positive, patents growing), NLP candor index > 0.6, channel check convergence > 60% |
| Catalyst | 2+ positive catalysts within 6 months, at least 1 hard catalyst with specific timeline, PEAD pattern favorable, options market not overpricing event risk |
| Technical Setup | Stage 2 advancing OR above rising 200-day MA with positive RSI |
| Weinstein Alignment | Stage 2 with 30WMA slope positive, RS composite > 1.0 |
| CANSLIM | 5+/7 factors passing, EPS growth > 25%, near 52-week high, above-avg volume |

### China-Specific Dimensions (A-Share Only)

| Component | Score = 7 Benchmark |
|-----------|---------------------|
| Policy Alignment (政策契合度) | Industry in 十四五规划 key priorities, company designated 专精特新 or similar, no recent regulatory headwinds, government procurement exposure > 10% revenue |
| Capital Flow Signal (资金流向) | Northbound net buying over 3M, institutional seat net buying on 龙虎榜, margin balance stable (not rapidly expanding), 国家队 holding steady or adding |
| A-Share Sentiment | No 游资 speculative frenzy in stock, 龙虎榜 appearances infrequent and institutional-driven, 换手率 within normal range, concept board membership but not concept-hype driven |

### Score Inflation Warnings

Avoid these common biases that inflate scores:
1. **Halo effect**: One exceptional metric lifting all scores (e.g., amazing growth → inflated moat score)
2. **Recency bias**: Weighting last quarter too heavily vs 5-year trend
3. **Narrative capture**: High score because the story is compelling, not the data
4. **Anchoring to prior rating**: Reluctance to downgrade from a prior Buy rating
5. **Denominator neglect**: Ignoring small sample sizes in alt data

## Override Rules (Mandatory)

| Condition | Override | Rationale |
|-----------|----------|-----------|
| Any component ≤ 3.0 | Max rating = Hold (5.9) | Single catastrophic weakness dominates |
| 3+ red flags (Beneish + Altman + poor OCF) | Max rating = Sell (3.9) | Forensic evidence of distress |
| Capital Allocation Score ≤ 3.0 (destructive) | Max rating = Hold (5.9) | Poor capital allocation destroys long-term value regardless of other strengths |
| Supply Chain Resilience ≤ 3.0 (critical risk) | Max rating = Hold (5.9) | Single-source dependency or geographic concentration that could impair operations |
| Weinstein Stage 4 | Max rating for short-term = Sell | Never buy into a declining trend |
| 3+ components missing | Confidence = Low | Insufficient data to have conviction |
| Lollapalooza (3+ components ≥ 7.5) | +1.5 bonus | Multiple force convergence (Munger) |
| Carbon breakeven < current carbon price trajectory | Flag as stranded asset risk | For energy/materials only |
| China Policy Score ≤ 3.0 (A-share only) | Max rating = Hold (5.9) | Regulatory headwinds override fundamentals in A-shares |
| Margin balance % of free float > 8% (A-share) | Flag as speculative risk; reduce confidence 1 level | High margin concentration = forced liquidation risk |
| Taleb Fragility Score < 25 | Max rating for long-term = Hold (5.9) | Fragile companies are unsuitable for long-term buy-and-hold |
| Price within 5% of 52-week high AND Valuation_Attractiveness ≤ 4.0 AND 30-day return > 25% | Max short-term rating = Hold (6.0) | Overextended stock with poor valuation — short-term entry risk too high |

## Historical Calibration Benchmarks

Use these as sanity checks for output scores:

| Market Condition | Expected Score Distribution |
|-----------------|----------------------------|
| Bull market (SPY up >15% YTD) | Median score 6.5-7.0; more Buys than Sells |
| Bear market (SPY down >15% YTD) | Median score 4.5-5.5; more opportunities but higher risk |
| Neutral market (SPY ±5% YTD) | Median score 5.5-6.5; selective opportunities |

### Score Stability Expectations
- Long-term scores should change by ≤ 0.5 points per quarter (unless material event)
- Mid-term scores may shift 1-2 points per quarter (macro-sensitive)
- Short-term scores can shift 2-3 points per week (sentiment/technical-driven)

## Backtest Validation Protocol

When running `scripts/backtest.py`, verify:
1. Strong Buys (9+) outperformed index by >15% over 12 months in >65% of cases
2. Sells (2-3.9) underperformed index by >10% over 12 months in >60% of cases
3. Kill switches triggered before >20% adverse move in >50% of cases
4. Confidence level correlated with accuracy (High > Medium > Low)

If backtest shows systematic over/under-performance vs expectations, recalibrate thresholds.

## Bayesian Conviction Calibration

Run `scripts/calibrate_conviction.py --db ./reports/state.db` periodically (after 20+ predictions) to assess systematic biases.

### Interpreting Calibration Output

| Metric | Healthy Range | Action if Outside |
|--------|--------------|-------------------|
| Overall accuracy | >60% | Review scoring thresholds; check for data quality issues |
| Brier score | <0.25 | Values above 0.25 indicate worse than naive random; requires full recalibration |
| Overconfidence ratio | <0.35 | Above 35% means too many Strong Buy/Buy calls underperform |
| Strong Buy accuracy | >65% | Below 65% suggests score inflation; apply -0.5 Bayesian adjustment |
| Sell accuracy | >55% | Below 55% suggests bearish bias; apply +0.5 adjustment |

### Applying Bayesian Adjustments

When calibration recommends an adjustment:
1. **Do NOT automatically modify scores.** The adjustment is advisory context.
2. Report the calibration finding in the Data Quality appendix: "Historical calibration suggests [direction] bias of [magnitude]."
3. If the adjustment has persisted across 3+ calibration runs, consider permanent threshold revision.
4. Per-sector calibration may differ — if biotech Strong Buys historically underperform while bank Strong Buys outperform, the issue is sector threshold calibration, not global bias.

### Reliability Diagram Interpretation

The reliability diagram shows predicted probability vs observed frequency in quintiles:
- **Well-calibrated:** Points lie on the diagonal (predicted 70% → observed ~70%)
- **Overconfident:** Points below the diagonal (predicted 80% → observed only 55%)
- **Underconfident:** Points above the diagonal (predicted 40% → observed 65%)

## Regime-Aware Weight Context

The conviction weights in `compute_scores.py` are fixed per report type. However, the cross-check step (10b) should apply regime-aware interpretation:

| Market Regime | Weight Emphasis Shift | Rationale |
|--------------|----------------------|-----------|
| Risk-Off (VIX > 30, spreads widening) | Elevate Risk Profile, Capital Structure importance | Survival matters more than growth |
| Reflation (rates rising, PMI expanding) | Elevate Macro Tailwind, Technical Setup | Cyclical momentum dominant |
| Late Cycle (yield curve flat, unemployment at lows) | Elevate Valuation, Risk Profile | Margin of safety critical |
| Deflation / Recession | Elevate Financial Health, Moat Quality | Only strongest survive |
| Speculative (VIX low, margin debt high) | Elevate Alternative Alignment, CANSLIM | Momentum/sentiment drives short-term |

These are NOT automatic weight changes — they inform the cross-check investigation prompts and the confidence narrative in the report.

## Framework Divergence Resolution Protocol

When `compute_scores.py` detects framework divergences (high `score_dispersion` or specific tension pairs):

| Divergence Pattern | Most Likely Explanation | Investigation Path |
|-------------------|------------------------|-------------------|
| High Moat + Low Technical | Market pricing in moat erosion early | Check if moat score is stale; review competitive dynamics |
| High Financial Health + Low Valuation | Cheap for good reason? Or contrarian opportunity? | Check if there's a catalyst or structural issue |
| High Alt Alignment + Low Financial Health | Alt data seeing recovery before financials | Check revenue leading indicators, order book visibility |
| High Macro + Low Risk Profile | Tailwind present but company-specific risk dominates | Assess whether risk is idiosyncratic or macro-correlated |
| High Valuation + Low Technical | Cheap and getting cheaper — value trap risk | Requires hard catalyst with timeline (Klarman) |
| Low Macro + High CANSLIM | Individual stock defying macro weakness | Verify relative strength is genuine, not sector rotation artifact |

Resolution actions:
1. If tension is **explainable** (e.g., company is turning around, moat evolving): note in report, no score change
2. If tension is **suspicious** (e.g., scores based on stale data): refresh data, re-run scoring
3. If tension is **unresolvable**: reduce confidence one level, flag as "DIVERGENCE NOTED" in report
