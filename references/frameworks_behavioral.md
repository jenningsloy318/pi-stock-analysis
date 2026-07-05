# Behavioral Finance Frameworks

## Soros Theory of Reflexivity

### Core Principle
Market prices are not just passive reflections of fundamentals — they actively influence fundamentals through feedback loops. Price increases attract capital, improve confidence, enable cheap financing, boost earnings, which further increases prices (boom). Reverse in bust.

### Reflexivity Detection Criteria

| Signal | Measurement | Threshold | Interpretation |
|--------|-------------|-----------|----------------|
| Autocorrelation (lag-1) | Correlation of daily returns with prior day | > 0.15 | Trend self-reinforcing |
| Volatility asymmetry | Downside vol / Upside vol | > 1.5 | Reflexive on downside (panic) |
| Momentum acceleration | 2nd half momentum / 1st half | Acceleration > 0.3 | Trend strengthening |
| Run length | Average consecutive same-sign days | > 3.0 days | Persistent trend |
| Price-fundamental divergence | Price CAGR vs EPS CAGR | Gap > 20pp | Far from equilibrium |

### Phase Classification

| Phase | Reflexivity Score | Action |
|-------|-------------------|--------|
| Strong Boom | 8-10, positive mean return | Monitor for exhaustion signals; trim don't add |
| Strong Bust | 8-10, negative mean return | Wait for stabilization; don't catch falling knives |
| Trending | 6-7.9 | Ride trend with trailing stop |
| Equilibrium | 4-5.9 | Fundamentals dominate; use value frameworks |
| Mean-Reverting | 1-3.9 | Contrarian opportunity; fade extremes |

### Soros Trading Rules
1. Never fight a reflexive trend in its acceleration phase
2. Largest positions when thesis AND trend align
3. Cut positions immediately when reflexive loop breaks (don't wait for fundamentals)
4. Far-from-equilibrium states are unstable — expect sudden reversals

## Anchoring Bias Framework

### Common Price Anchors

| Anchor Type | Detection Method | Danger Level |
|-------------|-----------------|--------------|
| 52-week high | PT consensus within 5% of 52w high | High (backward-looking) |
| Round numbers | PT clustering at $50/$100/$200 intervals | Moderate (psychological) |
| IPO price | Reference to IPO level in reports | High (irrelevant to current value) |
| Prior earnings price | Pre-announcement level as "fair value" | Moderate |
| Analyst consensus | PT spread < 15% of mean | High (herding amplifies anchoring) |

### Anchoring Adjustment Protocol
1. Identify the anchor (what number are people fixated on?)
2. Assess freshness (is the anchor from >6 months ago?)
3. Test relevance (has the business changed since the anchor was set?)
4. Compute de-anchored value using current fundamentals only
5. If de-anchored value differs >20% from consensus, flag as opportunity/risk

## Kahneman Prospect Theory

### Loss Aversion in Markets
- Investors feel losses ~2.5x more intensely than equivalent gains
- Creates: slow selling of losers (disposition effect), premature selling of winners
- Implication: stocks that have declined may be over-held (creating supply overhang)

### Framing Effects
| Frame | Market Behavior | Exploitation |
|-------|----------------|--------------|
| % return vs $ return | Small-cap moves seem larger in % | Absolute dollar moves drive institutional flow |
| Drawdown from ATH | "Down 40%" anchor vs "up 200% from 2020" | Use multiple time horizons |
| Relative vs absolute | "Cheap vs peers" masks "expensive vs history" | Always compare both |

## Herding & Information Cascades

### Analyst Herding Detection

| Metric | Herding Signal | Threshold |
|--------|---------------|-----------|
| Recommendation concentration | % in dominant bucket | > 80% |
| PT spread / mean | Normalized dispersion | < 15% (too tight) |
| Revision simultaneity | Multiple revisions within 5 days | 3+ same-direction |
| Earnings estimate range | High-low / mean | < 10% (artificial consensus) |

### Contrarian Rules (When to Fade the Herd)
1. Herding score ≥ 8/10 AND price at 52-week extreme → contrarian signal active
2. Unanimous Buy + rising price → "who's left to buy?" → reduce
3. Unanimous Sell + falling price → "who's left to sell?" → investigate value
4. Exception: don't fade herding during genuine structural change (paradigm shift)

## Overreaction / Underreaction Model

### DeBondt & Thaler (1985): Long-Term Overreaction
- Stocks that performed worst over 3 years outperform over next 3 years
- Implication: mean reversion works at multi-year horizons
- Application: long-term report contrarian screen

### Jegadeesh & Titman (1993): Short-Term Underreaction
- Stocks that performed best over 6-12 months continue outperforming
- Implication: momentum works at intermediate horizons
- Application: mid-term report trend-following, CANSLIM L-factor

### Combined Model for Reports

| Horizon | Dominant Bias | Strategy |
|---------|--------------|----------|
| 1-5 days | Overreaction to news | Fade extreme moves (contrarian) |
| 1-12 months | Underreaction to trends | Follow momentum (Weinstein Stage 2) |
| 3-5 years | Overreaction to narratives | Value + mean reversion (Klarman) |

## Narrative Economics (Shiller)

### Narrative Detection Framework
1. Identify dominant narrative (AI Revolution, Rate Cuts, Recession, etc.)
2. Measure narrative diversity (single story = fragile to shift)
3. Track narrative lifecycle: emergence → virality → peak → fatigue → replacement
4. Flag narrative-fundamental divergence (price driven by story, not cash flows)

### Narrative Risk Assessment

| Condition | Risk Level | Action |
|-----------|-----------|--------|
| Single dominant narrative (>50% share) + high valuation | High | Narrative shift = crash risk |
| Multiple narratives (diversity > 0.6) | Low | More robust to any single story fading |
| Narrative shifting (dominant changed in last 30 days) | Elevated | Price discovering new equilibrium |
| Counter-narrative emerging (bear narrative gaining share) | Watch | May signal trend change |

## Integration with Report Types

| Report Type | Primary Behavioral Checks |
|-------------|---------------------------|
| Long-term | Narrative lifecycle stage, mean reversion (3yr), reflexivity phase, anchoring to old narrative |
| Mid-term | Momentum persistence, herding level, sentiment divergence, reflexivity acceleration |
| Short-term | Overreaction detection, anchoring to round/52w, contrarian signals, reflexivity extremes |
