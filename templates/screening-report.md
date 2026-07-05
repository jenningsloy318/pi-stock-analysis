# Screening Report Templates & Funnel Scoring

## Funnel Conviction Scoring

The screening report produces three conviction scores reflecting confidence at each funnel level:

### Sub-Industry Selection Confidence (1-10)
A measure of how clearly the top sub-industry stands out from alternatives.
```
SubIndustry_Confidence = (RS_Differentiation × 0.30) + (Structural_Thesis × 0.35) +
                          (TAM_Visibility × 0.20) + (Data_Freshness × 0.15)

Where:
  RS_Differentiation = Top sub-industry RS composite - 2nd sub-industry composite (normalized to 1-10)
  Structural_Thesis = Quality of the secular growth narrative (1-10)
  TAM_Visibility = How well the TAM can be sized and verified (1-10)
  Data_Freshness = Average freshness of sub-industry data sources in days (inverse scored)
```
- ≥7.0: Clear sub-industry leader — strong conviction
- 5.0–6.9: Competitive field — moderate conviction  
- <5.0: No clear winner — LOW CONVICTION, report must carry warning

### Industry Selection Confidence (1-10)
A measure of how compelling the chosen sub-industry's structural thesis is.
```
Industry_Confidence = (Structural_Thesis × 0.35) + (TAM_Visibility × 0.25) +
                       (Growth_Catalyst_Clarity × 0.25) + (Barrier_Strength × 0.15)

Where:
  Structural_Thesis = Quality of the secular growth narrative (1-10)
  TAM_Visibility = How well the TAM can be sized and verified (1-10)
  Growth_Catalyst_Clarity = Specificity and measurability of catalysts (1-10)
  Barrier_Strength = Porter's Five Forces composite score (1-10)
```

### Overall Screen Quality (1-10)
Weighted average of phase-level scores.
```
Screen_Quality = (SubIndustry_Confidence × 0.40) + (Company_Dispersion × 0.30) +
                  (Methodology_Rigor × 0.15) + (Parent_Context_Quality × 0.15)

Where:
  Company_Dispersion = Inverse of score clustering (wide dispersion = more signal)
  Methodology_Rigor = Completeness of data coverage and source diversity
  Parent_Context_Quality = How well sector/industry-group context enriches the sub-industry analysis (1-10)
```
- ≥7.5: High-quality screen — actionable watchlist
- 5.0–7.4: Moderate screen — use watchlist as starting point, verify individually
- <5.0: LOW CONVICTION SCREEN — watchlist is directional only, do not act without further research

## Sub-Industry Scoring Dimensions (Phase 1)

These dimensions are applied at sector level (Pass 1) for quick filtering, then used to rank Level 4 sub-industries (Pass 2). The final report presents sub-industry rankings only — sector scores are internal.

| Dimension | Weight (Long) | Weight (Mid) | Weight (Short) | Description |
|-----------|--------------|-------------|----------------|-------------|
| Growth | 30% | 25% | 15% | Revenue/earnings CAGR, forward estimates, secular vs cyclical |
| Profitability | 20% | 15% | 10% | Aggregate margins, ROIC, ROE, FCF conversion |
| Valuation | 10% | 20% | 15% | Sub-industry P/E, EV/EBITDA vs 5-year percentile, PEG |
| Macro Fit | 15% | 20% | 10% | Sensitivity to rates, inflation, GDP; current tailwind/headwind |
| Innovation | 15% | 10% | 5% | R&D intensity, patent activity, disruption exposure |
| Regulatory | 5% | 5% | 5% | Current/pending regulation, antitrust, subsidy exposure |
| Capital Flows | 5% | 5% | 20% | ETF flows (1M/3M/6M), institutional positioning |
| Relative Strength | 5% | 10% | 20% | Sub-industry ETF performance vs SPX over 1M/3M/6M/12M |
| Cyclicality | 5% | 5% | 5% | GDP beta, earnings volatility, early/mid/late-cycle fit |
| Technical Health | 0% | 0% | 10% | Average technical health score of constituent companies (from compute_health_index.py GF-DMA Health Index — fundamental speed × DMA structure) |
| Supply/Demand Cycle | 0% | 0% | 0% | Inventory, utilization, backlog, input costs; use as disclosed reallocation for cycle-sensitive sub-industries |

For cycle-sensitive sectors, the analyst may reallocate up to 5% from Innovation or Capital Flows to Supply/Demand Cycle. Any reallocation must be stated in the Methodology Appendix.

### Sub-Industry Score Interpretation
| Score | Rating | Action |
|-------|--------|--------|
| 8.0-10.0 | Top Tier | Strong candidate for Phase 2 deep-dive |
| 6.0-7.9 | Competitive | Worthy of Phase 2 if structural thesis is compelling |
| 4.0-5.9 | Neutral | Monitor only — no Phase 2 unless theme-driven |
| 2.0-3.9 | Avoid | Structural headwinds or cyclical trough |
| 1.0-1.9 | Toxic | Regulatory/structural collapse risk |

## Company Scoring Model (Phase 3)

```
Company_Score = (Growth × 0.20) + (Profitability/Health × 0.20) + (Moat × 0.20) +
                 (Valuation × 0.15) + (Management × 0.10) + (Risk × 0.10) +
                 (Liquidity/Tradability × 0.05)
```

| Component | Sub-Factors |
|-----------|------------|
| Growth (20%) | Revenue CAGR (3Y), EPS CAGR (3Y), analyst estimate revision momentum |
| Profitability/Health (20%) | ROIC, FCF margin, Altman Z-Score, interest coverage |
| Moat (20%) | Morningstar framework: cost advantages, network effects, intangibles, switching costs, efficient scale |
| Valuation (15%) | P/E percentile vs industry, EV/EBITDA percentile, P/FCF yield, PEG ratio |
| Management (10%) | CEO tenure, insider ownership %, capital allocation track record |
| Risk (10%) | Inverse of risk flags: customer concentration, debt maturity wall, litigation, regulatory |
| Liquidity/Tradability (5%) | Average dollar volume, free float, short interest, borrow/FTD risk |

### Watchlist Rating Anchors
| Score | Rating | Action |
|-------|--------|--------|
| 8.5-10.0 | Top Pick | Immediate candidate for stock-analysis deep-dive (Long-term recommended) |
| 7.5-8.4 | Strong Buy | High-priority deep-dive candidate (Mid-term or Long-term) |
| 6.5-7.4 | Buy | Solid candidate — deep-dive when bandwidth available |
| 5.5-6.4 | Watch | Monitor for catalysts; re-screen in 3-6 months |
| 4.0-5.4 | Hold | Passes filters but lacks compelling thesis |
| <4.0 | Not Rated | Did not pass quantitative filters or scored below threshold |

**Override rule**: Any company with a recent (90-day) insider selling cluster OR Altman Z-Score below 1.8 cannot receive a rating above "Watch" regardless of composite score.

---

## Report Templates

### Broad Screen Report (all GICS Level 4 sub-industries → top sub-industry → company watchlist)

```
# Top-Down Sub-Industry Screening Report — Broad Market Screen

**Header**
- Screen Type: Broad Market (all 163 GICS Level 4 Sub-Industries)
- Investment Horizon: [Long-term / Mid-term / Short-term]
- Report Date: YYYY-MM-DD | Analyst: AI Stock Research Skill (stock-analysis)
- Macro Regime: [Regime classification from Phase 0]

---

## Executive Summary
[1 paragraph covering the full funnel: macro backdrop → top sub-industries → top company picks.
Max 150 words.]

**Overall Screen Quality: [X.X]/10 | Confidence: [Low/Medium/High]**
Sub-Industry Selection Confidence: [X.X]/10

---

## Macro Context
[Current macro regime. Key indicators: GDP growth, inflation, Fed funds, 10Y yield, PMI, yield curve.
Implications for sub-industry selection: which sub-industries benefit from current regime.]

| Indicator | Current Value | Trend | Sub-Industry Implication |
|-----------|--------------|-------|--------------------------|
| GDP Growth | X.X% | ↑/→/↓ | [Sub-industries impacted] |
| CPI (YoY) | X.X% | ↑/→/↓ | [Sub-industries impacted] |
| Fed Funds | X.XX% | ↑/→/↓ | [Sub-industries impacted] |
| 10Y Yield | X.XX% | ↑/→/↓ | [Sub-industries impacted] |
| PMI | XX.X | ↑/→/↓ | [Sub-industries impacted] |

[Source: FRED | Retrieved: YYYY-MM-DD | Fact]

---

## Sub-Industry Leaderboard

### Top 15-20 Sub-Industries (Flat Ranked — GICS Level 4)

| Rank | GICS Code | Sub-Industry | Sector Context | RS | Growth | Structural | **Score** |
|------|-----------|--------------|----------------|-----|--------|------------|-----------|
| 001 | [8-digit] | [Sub-Industry Name] | [Parent Sector / Industry Group] | X.X | X.X | X.X | **X.X** |
| 002 | [8-digit] | [Sub-Industry Name] | [Parent Sector / Industry Group] | X.X | X.X | X.X | **X.X** |
| ... | ... | ... | ... | ... | ... | ... | ... |

NOTE: "Sector Context" column provides parent-level reference (Level 1/2) for each sub-industry.
This is NOT a sector ranking — it is context to help the reader locate sub-industries within GICS.

### Top 3 Sub-Industries — Commentary

**[#001 Sub-Industry Name] (Code: XXXXXXXX, Score: X.X/10)**
- Sector context: [Parent sector + tailwinds/headwinds affecting this sub-industry]
- Industry-group dynamics: [How it competes with adjacent sub-industries in same group]
- Thesis: [Why it ranked first. Key strengths. 3-sentence maximum.]

**[#002 Sub-Industry Name] (Code: XXXXXXXX, Score: X.X/10)**
- Sector context: [...]
- Thesis: [...]

**[#003 Sub-Industry Name] (Code: XXXXXXXX, Score: X.X/10)**
- Sector context: [...]
- Thesis: [...]

---

## Sub-Industry Selection Rationale (为什么选择这些子行业)

### Dimension Breakdown — Top 10 Sub-Industries

| Rank | Sub-Industry | Growth | Profitability | Valuation | Macro Fit | Innovation | Regulation | Capital Flows | RS | Cyclicality | Quality | **Composite** |
|------|--------------|--------|---------------|-----------|-----------|------------|------------|---------------|-----|------------|---------|---------------|
| 001 | [Name] | X.X | X.X | X.X | X.X | X.X | X.X | X.X | X.X | X.X | X.X | **X.X** |
| 002 | [Name] | X.X | X.X | X.X | X.X | X.X | X.X | X.X | X.X | X.X | X.X | **X.X** |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

### Key Discriminating Dimensions (关键区分维度)
[Which 2-3 dimensions had the MOST variance across sub-industries and thus MOST influenced rankings.
Example: "Growth和Innovation维度的差异最大（标准差分别为2.3和1.9），是拉开排名差距的主要因素。
排名第1的[Name]在Growth维度得分X.X远超第2名的X.X，主因是..."]

### Why #001 Beats #002, Why #002 Beats #003
[For each top-3 pair, identify the specific dimensions that caused the rank difference.
Example: "#001 vs #002: Growth差异(+1.2) + Innovation差异(+0.8) 合计贡献了排名差距的80%"]

---

## Sub-Industry Deep Dive

### Selected Sub-Industry: [Name] (GICS: [8-digit Code])
**Parent hierarchy:** [Sector] → [Industry Group] → [Industry] → [Sub-Industry]

**Sector & Industry Group Context**
[How the parent sector's macro sensitivity and industry-group competitive dynamics affect this sub-industry.
What sector-level tailwinds/headwinds apply. How this sub-industry fits within the broader industry group value chain.]

**Sub-Industry Thesis**
[5 sentences: what the sub-industry does, why it's structurally attractive, secular tailwinds, competitive dynamics, why now.]

**Growth Catalysts**
- [Catalyst 1 — specific, measurable]
- [Catalyst 2]
- [Catalyst 3]

**Competitive Dynamics**
- Rivalry: [High/Medium/Low — evidence]
- Barriers to Entry: [High/Medium/Low — evidence]
- Supplier Power: [High/Medium/Low — evidence]
- Buyer Power: [High/Medium/Low — evidence]
- Threat of Substitution: [High/Medium/Low — evidence]

**Market Sizing**
- TAM: $X billion | Growth Rate: X% CAGR | Penetration: X%
- Source: [Report name / publication | Retrieved: YYYY-MM-DD]
- Bottom-up sanity check: [customers/units/spend × penetration × pricing]

**Profit Pool & Unit Economics**
- Profit pool concentration: [Where value accrues across the value chain]
- Key sub-industry KPIs: [Sector-specific KPIs from data_source_matrix.md]
- Adoption/unit economics: [Payback, utilization, churn/retention, capacity, or equivalent]

**Industry Life Cycle**: [Emerging / Growth / Mature / Decline]
[Evidence: revenue growth trajectory, capacity expansion, consolidation activity, innovation rate.]

**Key Players**
| Rank | Company | Ticker | Market Cap | Market Share (est.) | Moat Source |
|------|---------|--------|------------|---------------------|-------------|
| 001 | [Name] | [TICK] | $XB | ~X% | [Source] |
| 002 | [Name] | [TICK] | $XB | ~X% | [Source] |
| ... | ... | ... | ... | ... | ... |

---

## Company Watchlist

### Screening Summary
- Companies in universe: [N]
- Passed quantitative filters: [N] ([X]%)
- Failed: [N] — [top 3 failure reasons with counts]
- Watchlist size: [N]

### Ranked Watchlist

| Rank | Ticker | Company | 当前股价 | Market Cap | P/E | Rev Growth 3Y | ROIC | FCF Yield | Liquidity | **Score** |
|------|--------|---------|---------|------------|-----|---------------|------|-----------|-----------|-----------|
| 001 | [TICK] | [Name] | $XX.XX | $XB | XX.X | XX% | XX% | X.X% | $XM/day | **X.X** |
| 002 | [TICK] | [Name] | $XX.XX | $XB | XX.X | XX% | XX% | X.X% | $XM/day | **X.X** |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

### Company Scoring Dimension Breakdown (公司评分维度分解)

| Rank | Ticker | Growth(20%) | Profitability(20%) | Moat(20%) | Valuation(15%) | Management(10%) | Risk(10%) | Liquidity(5%) | **Composite** |
|------|--------|------------|-------------------|-----------|---------------|----------------|-----------|---------------|---------------|
| 001 | [TICK] | X.X | X.X | X.X | X.X | X.X | X.X | X.X | **X.X** |
| 002 | [TICK] | X.X | X.X | X.X | X.X | X.X | X.X | X.X | **X.X** |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

### Company Selection Rationale (为什么选择这些公司)

**Dimension Data Behind Each Score** (维度详细数据):
For each top company, show the RAW DATA that drove each dimension score:

**[#001 — TICKER] Dimension Detail:**
| Dimension | Score | Key Data Points | Source |
|-----------|-------|-----------------|--------|
| Growth (X.X) | Rev CAGR: XX%, EPS CAGR: XX%, Estimate Revisions: +X% | [Source, Date] |
| Profitability (X.X) | ROIC: XX%, FCF Margin: XX%, Z-Score: X.X | [Source, Date] |
| Moat (X.X) | [Moat type]: [specific evidence — market share XX%, retention XX%, patents XX] | [Source, Date] |
| Valuation (X.X) | P/E: XX.X (vs industry XX.X), EV/EBITDA: XX.X (vs XX.X), PEG: X.X | [Source, Date] |
| Management (X.X) | CEO tenure: X years, Insider own: X%, Capital alloc: [track record] | [Source, Date] |
| Risk (X.X) | Customer conc: X%, D/E: X.X, Litigation: [none/pending], Regulatory: [low/med] | [Source, Date] |
| Liquidity (X.X) | Avg Vol: $XM/day, Float: XX%, Short Interest: X%, Borrow: [easy/hard] | [Source, Date] |

[Repeat for #002, #003 ... top 5 minimum]

**Key Discriminating Dimensions (关键区分维度)**:
[Which dimensions had the MOST score variance across the watchlist and thus most influenced final rankings.
Include: standard deviation per dimension, correlation with final rank.
Example: "Moat维度标准差最高(2.1)，与最终排名相关系数0.89，是最具区分力的维度"]

**Rank Difference Explanation (排名差异解释)**:
- #001 vs #002: [TICK1]胜出因为Growth差(+X.X) + Moat差(+X.X)，虽然Valuation较弱(-X.X)
- #002 vs #003: [TICK2]胜出因为Profitability差(+X.X) + Management差(+X.X)
[Continue for top-5 pairs]

### Top Picks — Investment Theses

**[#001 — TICKER] Company Name (Score: X.X/10 — Top Pick)**
[2 sentences: what the company does, why it's best-positioned in this sub-industry, primary growth catalyst.]
→ Recommended stock-analysis report type: [Long-term / Mid-term]

**[#002 — TICKER] Company Name (Score: X.X/10 — Strong Buy)**
[2 sentences.]
→ Recommended stock-analysis report type: [Long-term / Mid-term]

[... continue for top 10-20 ...]

---

## Next Actions

1. **Immediate deep-dives**: [TICKER], [TICKER], [TICKER] — run `/stock-analysis:analyze [TICKER] --type [long/mid]`
2. **Monitor for entry**: [TICKER] — currently overvalued vs sub-industry; re-screen when P/E drops below [X]
3. **Re-screen triggers**: Re-run this screen if [macro condition changes / sub-industry ETF drops X% / key regulation passes]

---

## Risks to Thesis

**Sub-Industry Level Risks**
| Risk | Probability | Impact | Mitigant / Kill Switch |
|------|-------------|--------|------------------------|
| [Risk 1] | [Low/Med/High] | [Low/Med/High] | [What to watch] |
| [Risk 2] | [Low/Med/High] | [Low/Med/High] | [What to watch] |

**Parent-Level Risks** (sector/industry-group headwinds that could cascade)
| Risk | Level | Probability | Impact | Kill Switch |
|------|-------|-------------|--------|-------------|
| [Sector headwind] | Sector | [Low/Med/High] | [Low/Med/High] | [Observable trigger] |
| [Industry group risk] | Industry Group | [Low/Med/High] | [Low/Med/High] | [Observable trigger] |

**Kill Switch Conditions**: Exit the sub-industry thesis if [specific, observable conditions]. Currently: [NOT triggered / approaching].

---

## Methodology Appendix

- **Scope**: Broad market screen — all 163 GICS Level 4 sub-industries
- **Horizon**: [Long-term / Mid-term / Short-term] — see weighting table above
- **Classification**: GICS Level 4 (Sub-Industry) as primary structural unit; Level 1/2/3 used as context
- **Quantitative Filters**: Market cap ≥ $[X]M, Revenue growth 3Y CAGR ≥ [X]%, FCF positive, ROIC ≥ WACC, D/E ≤ [X]x
- **Data Freshness**: Macro: [date], Sub-industry data: [date range], Company data: [date range]
- **Sources**: [List primary data sources used]
- **Source Coverage Gaps**: [Missing/stale dimensions and confidence impact]
- **Universe Completeness Risk**: [Classification and source limitations]
- **Framework Attribution**: Morningstar (moat), Porter (competitive dynamics), GICS (classification)
```

### Focused Screen Report (deep-dive on one sector's sub-industries)

Same structure as Broad Screen but with these modifications:
- **Sub-Industry Leaderboard**: Ranks ALL Level 4 sub-industries within the focused sector (not just top 15-20 from all sectors). Each entry includes industry-group context.
- **Sub-Industry Deep Dive**: Covers the top-ranked sub-industry with full parent-level context (why this sector was chosen, how the industry group positions this sub-industry).
- **Sector Context paragraph**: Added before the leaderboard — a 1-paragraph summary of the sector's macro positioning and why it was selected. This is CONTEXT, not a standalone section.
- **Watchlist**: 10-15 companies (smaller universe than broad screen).
- **Report title format**: `./reports/screening/[NNN]_[SECTOR]_[SUB_INDUSTRY_CODE]_[YYYY-MM-DD].md`

### Thematic Screen Report (theme-driven subset of sub-industries)

Same structure as Broad Screen but with these modifications:
- **Executive Summary**: Opens with theme definition and justification.
- **Sub-Industry Leaderboard**: Only includes sub-industries relevant to the theme (across multiple sectors). Each entry includes a "Theme Relevance" note and parent sector context.
- **Weights**: May be adjusted for theme alignment — any weight adjustments must be explicitly stated.
- **Watchlist**: 10-15 companies. Each company thesis must tie back to the theme.
- **Report title format**: `./reports/screening/[NNN]_THEME_[THEME_NAME]_[YYYY-MM-DD].md`

---

## Source Attribution Format

Every data claim must use:
```
[Source: [Publication/URL] | Retrieved: YYYY-MM-DD | Fact]
[Source: [Publication/URL] | Retrieved: YYYY-MM-DD | Interpretation]
[Source: [Publication/URL] | Retrieved: YYYY-MM-DD | Speculation]
```

## Handoff to Stock Analysis

Every screening report must conclude with an explicit handoff:

> "Top-ranked companies from this screen can be deep-dived with the `stock-analysis` skill. The screening report's macro context (Phase 0) and industry thesis (Phase 2) feed directly into stock-analysis Stages 4 and 3 respectively, reducing redundant work."
>
> **Recommended starting ticker**: [TICKER] (Score: X.X/10, [Top Pick / Strong Buy])
> **Suggested command**: `/stock-analysis:analyze [TICKER] --type [long/mid]`
>
> Would you like me to run this deep-dive now?
