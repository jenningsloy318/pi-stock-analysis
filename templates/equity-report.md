# Report Templates & Scoring Formulas

## 投资镜像测试（5句话说不完整 = 信号不足）

我以 ___元/$ 买入 ___，因为：
1. 这门生意的本质是___，我理解它
2. 护城河是___，在变宽/稳定/变窄
3. 管理层___，值得/不值得信赖，因为___
4. 当前价格 = 内在价值的___折，安全边际来自___
5. 即使我错了，下行风险可控，因为___

## 快速否决检查
- [ ] 说不清楚这家公司怎么赚钱 → ⚠️ FAST_FAIL
- [ ] 连续3年自由现金流为负且无改善趋势 → ⚠️ FAST_FAIL
- [ ] 管理层有诚信污点（财务造假/内幕交易/重大诉讼）→ ⚠️ FAST_FAIL
- [ ] 核心竞争优势正在被不可逆侵蚀 → ⚠️ FAST_FAIL
- [ ] 业务本质是"等下一个接盘者出更高价" → ⚠️ FAST_FAIL
- [ ] 无法用200字以内写清楚买入理由 → ⚠️ FAST_FAIL

## Conviction Scoring Formulas

Source of truth: `scripts/compute_scores.py` → `compute_conviction()`

### Long-term Report Conviction
```
Conviction = (financial_health × 0.15) + (moat_quality × 0.15) +
             (management_quality × 0.15) + (valuation_attractiveness × 0.15) +
             (capital_structure × 0.10) + (macro_tailwind × 0.05) +
             (risk_profile × 0.10) + (weinstein_alignment × 0.05) +
             (ecosystem_momentum × 0.05) + (industry_trajectory × 0.05)
```
Note: Ecosystem_Momentum = upstream supplier health + downstream customer health composite.
Industry_Trajectory = is the industry improving or deteriorating (6-dimension directional score).

### Mid-term Report Conviction
```
Conviction = (financial_health × 0.10) + (moat_quality × 0.10) +
             (management_quality × 0.10) + (valuation_attractiveness × 0.15) +
             (macro_tailwind × 0.10) + (risk_profile × 0.10) +
             (weinstein_alignment × 0.10) + (canslim × 0.10) +
             (ecosystem_momentum × 0.05) + (industry_trajectory × 0.05) +
             (money_flow_confirmation × 0.05)
```

### Short-term Report Conviction
```
Conviction = (valuation_attractiveness × 0.10) + (macro_tailwind × 0.10) +
             (risk_profile × 0.10) + (alternative_alignment × 0.15) +
             (technical_setup × 0.15) + (weinstein_alignment × 0.10) +
             (canslim × 0.10) + (ecosystem_momentum × 0.10) +
             (industry_trajectory × 0.05) + (money_flow_confirmation × 0.05)
```
Note: Industry_Trajectory weighted higher in short-term than long-term because industry momentum
(fund flows, RS acceleration, margin direction) is a strong 3-6 month signal.

## Component Scoring (1-10 Scale)

| Component | 1-3 (Bearish) | 4-6 (Neutral) | 7-10 (Bullish) |
|-----------|--------------|---------------|----------------|
| Financial Health | Declining margins, FCF negative, leverage >5x | Stable margins, FCF covers capex, leverage 2-4x | Expanding margins, FCF >> capex, leverage <2x |
| Moat Quality | Narrowing moat, share loss, pricing pressure | Stable moat, flat share, pricing intact | Widening moat, gaining share, pricing power |
| Management Quality | Poor allocation, insider selling, guidance misses | Average allocation, neutral insider, mixed guidance | Excellent allocation, insider buying, beats |
| Valuation Attractiveness | >30% above intrinsic, 5yr high multiples | ±15% of intrinsic, near historical avg | >30% below intrinsic, 5yr low multiples |
| Capital Structure | Value-destructive buybacks, SBC >10%, suboptimal leverage | Neutral buybacks, moderate SBC, average capital returns | Buybacks at discount, low SBC, total return >4% |
| Macro Tailwind | 3+ headwinds | 1-2 headwinds, offset | 3+ tailwinds |
| Risk Profile | 3+ red flags, litigation, Altman Z <1.81 | Manageable risks, mitigants present | Clean, low litigation, strong balance sheet |
| Alternative Alignment | Digital diverging negative from reported | Mixed, no clear divergence | Digital confirming/exceeding reported |
| Technical Setup | Broken trend, distribution, below support | Mixed, range-bound | Strong trend, accumulation, above support |
| Weinstein Alignment | Stage 4 (Declining), RS < 0.9 | Stage 1/3 (Basing/Topping) | Stage 2 (Advancing), RS > 1.1 |
| CANSLIM | <3/7 factors passing, EPS declining | 3-4/7 factors, mixed signals | 5+/7 factors passing, strong EPS + RS |
| Capital Allocation | Retention ratio <0.5x, value-destructive buybacks, SBC >10% | Retention ratio 0.5-1.0x, neutral buybacks, moderate SBC | Retention ratio >1.5x, buybacks at discount, SBC <5% |
| Earnings Quality | Beneish > -1.78, OCF/NI <0.5, aggressive revenue recognition | Beneish -2.22 to -1.78, OCF/NI 0.5-0.9 | Beneish < -2.22, OCF/NI >0.9, clean accruals |
| Supply Chain Resilience | HHI >5,000, single-source critical inputs, no contingency plan | HHI 2,500-5,000, dual-source, some buffer | HHI <2,500, multi-source, documented contingency plans |
| Ecosystem Momentum | Top supplier/customer rev declining >10%, margins contracting, stock down >20% 6M | Mixed signals, some up some down, no clear trend | Top supplier/customer rev growing >10%, margins expanding, stock up >15% 6M |
| Industry Trajectory | Revenue decelerating, margins contracting, RS deteriorating, fund outflows, valuation compressing, late-cycle over-investment | Mixed signals, no clear direction | Revenue accelerating, margins expanding, RS improving, fund inflows, valuation expanding, early-cycle under-investment |
| ESG & Sustainability | MSCI red-flag controversy, <25% TCFD aligned, high carbon intensity | No controversies, partially TCFD aligned, moderate carbon | Leader in ESG, fully TCFD aligned, net-zero pathway |
| Catalyst Alignment | No positive catalysts, 1+ negative binary event upcoming | Mixed catalysts, uncertain timing | 2+ positive catalysts, at least 1 hard catalyst with timeline |
| China Policy Alignment* | Regulatory headwinds, policy tightening, no 专精特新 designation | Neutral policy, stable regulation | Strong policy support, 专精特新, 国产替代 beneficiary |
| China Capital Flows* | Northbound net selling, margin balance spiking, 游资 selling | Mixed flows, stable margin | Northbound net buying, institutional 龙虎榜 buying, 国家队 adding |

*China-specific dimensions apply to A-share tickers only (SH/SZ suffix).

## Rating Anchors

| Score | Rating | Description |
|-------|--------|-------------|
| 9.0-10.0 | Strong Buy | Exceptional alignment. 5+ frameworks supportive. Margin of safety >30%. |
| 7.5-8.9 | Buy | Strong alignment. 3-4 frameworks supportive. Margin of safety 15-30%. |
| 6.0-7.4 | Hold / Accumulate | Mixed. Positive thesis but near-term headwinds or valuation uncompelling. |
| 4.0-5.9 | Hold / Reduce | Weakening. 1-2 dimensions deteriorating. Monitor for downgrade. |
| 2.0-3.9 | Sell | Multiple negatives. Thesis broken in 2+ frameworks. |
| 1.0-1.9 | Strong Sell | Invalidated. Forensic red flags or structural decline. |

**Override rule**: If any single component scores ≤3, the rating cannot exceed "Hold."

## Data Coverage Confidence

Load `references/data_source_matrix.md` before report writing. Confidence is not just analyst certainty; it is capped by source coverage:

| Coverage Result | Maximum Confidence |
|-----------------|--------------------|
| All blocking Tier 0/Tier 1 dimensions pass freshness and source quorum | High |
| One non-central blocking dimension unavailable or stale | Medium |
| Any central blocking dimension unavailable or two or more blocking dimensions stale | Low |
| Thesis support relies mainly on Tier 3 alternative data | Low |
| Numeric claim fails fact check | Remove claim; rerun affected stage if material |

Every report must include a Data Quality & Coverage appendix with source freshness, missing/stale dimensions, source conflicts, and confidence impact.

## Framework Conflict Resolution (Rules 1-4)

When frameworks produce contradictory conclusions:

**Rule 1 — Report-Type Priority**: Highest-weight frameworks for the active report type take precedence.
**Rule 2 — Quantitative Override**: Beneish M-Score > -1.78 or Altman Z < 1.81 overrides all qualitative assessments. No Buy rating with active red flags.
**Rule 3 — Consensus Distance**: When rules 1-2 don't resolve, explicitly quantify the disagreement and synthesize an intermediate recommendation.
**Rule 4 — Second-Level Tiebreaker**: Apply Marks: "What does consensus think, and how does my view differ?" Default to consensus-aligned if no variant perception.

## Visual Conviction Scorecard

Include this Mermaid radar chart in every Long-term and Mid-term report to visualize component balance:

```mermaid
%%{init: {'theme': 'neutral'}}%%
radar
  title Conviction Scorecard
  "Financial Health": [SCORE]
  "Moat Quality": [SCORE]
  "Management": [SCORE]
  "Valuation": [SCORE]
  "Macro": [SCORE]
  "Risk Profile": [SCORE]
  "Technical": [SCORE]
  "Alt Data": [SCORE]
```

Replace `[SCORE]` with actual 1-10 values from `scores.json`. Omit dimensions with null scores. For Short-term reports, use a simplified 5-dimension chart (Valuation, Macro, Risk, Technical, Alt Data).

## Report Templates

### Long-term Report (1-3+ years)

**Methodology Weights**: Buffett/Munger (35%), Fisher (25%), Marks (20%), Dalio (20%)

```
# [COMPANY NAME] ([TICKER]) — Long-term Investment Analysis

**Header**
- Company Name | Ticker | Exchange
- Current Price | 52-week Range | Market Cap | Enterprise Value
- Report Date | Analyst: AI Stock Research Skill (stock-analysis)
- Report Type: Long-term (1-3+ years)

---

## Executive Summary
[1 paragraph, max 150 words]

**Conviction Rating: [X.X]/10 | Confidence: [Low/Medium/High]**
[Rationale in 1 sentence]

**Management Candor Index: [Score]/100 ([Verdict])**
[Lollapalooza Alert: (Only if synergistic advantages detected)]

---

## 投资评分维度分解 (Conviction Score Decomposition)

### Dimension Scores & Rationale

| Dimension | Weight | Score | Weighted | Key Data Points | Rationale |
|-----------|--------|-------|----------|-----------------|-----------|
| financial_health | 15% | X.X | X.XX | ROIC: XX%, FCF margin: XX%, Z-Score: X.X | [1-sentence: why this score] |
| moat_quality | 15% | X.X | X.XX | GM stability CV: X.XX, ROIC-WACC: X.Xpp, retention: XX% | [1-sentence: why this score] |
| management_quality | 15% | X.X | X.XX | CEO tenure: X yrs, insider own: X%, alloc: [grade] | [1-sentence: why this score] |
| valuation_attractiveness | 15% | X.X | X.XX | P/E: XX.X (vs XX.X), MoS: XX%, PEG: X.X | [1-sentence: why this score] |
| capital_structure | 10% | X.X | X.XX | Buyback ROI: XX%, SBC: X%, D/E: X.X | [1-sentence: why this score] |
| macro_tailwind | 5% | X.X | X.XX | [Key tailwind/headwind with data] | [1-sentence: why this score] |
| risk_profile | 10% | X.X | X.XX | Red flags: X, Z-Score: X.X, litigation: [Y/N] | [1-sentence: why this score] |
| weinstein_alignment | 5% | X.X | X.XX | Stage: X, decay-wtd RS: X.XX, 30W MA: [direction] | [1-sentence: why this score] |
| ecosystem_momentum | 5% | X.X | X.XX | Upstream: [X.X], downstream: [X.X], direction: [up/flat/down] | [1-sentence] |
| industry_trajectory | 5% | X.X | X.XX | Rev accel: [Y/N], margin: [expanding/flat/contracting], fund flows: [in/out] | [1-sentence] |
| **TOTAL** | 100% | — | **X.XX** | — | — |

**Three-Layer Alignment**: [fully_aligned/partially_aligned/divergent] — Stock([X.X]) × Industry([X.X]) × Macro([X.X]) → adj: [+0.5/0/-0.5]
**Analyst Revision Momentum**: [X.X]/10 ([upgrade/neutral/downgrade]) — CANSLIM I-factor adj: [±X.X]

### 关键决定维度 (Key Decisive Dimensions)
[Which 2-3 dimensions MOST influenced the final conviction. State which scored highest/lowest and WHY.
Example: "本次评级主要由Moat(8.5)和Valuation(8.0)驱动——公司拥有强网络效应(月活用户3.2亿, 留存率95%)，且当前估值P/E 18.5x显著低于行业中位数25.2x，提供32%安全边际。Risk维度(4.5)是主要拖累因素，因客户集中度达35%。"]

### Peer Dimension Comparison (if peers available)
| Dimension | [TICKER] | Peer 1 | Peer 2 | Peer 3 | Peer Median |
|-----------|----------|--------|--------|--------|-------------|
| Financial Health | X.X | X.X | X.X | X.X | X.X |
| Moat Quality | X.X | X.X | X.X | X.X | X.X |
| Valuation | X.X | X.X | X.X | X.X | X.X |
| ... | ... | ... | ... | ... | ... |
[Explain where the subject stock is STRONGER and WEAKER vs peers, and why]

---

## Investment Thesis
- [Bullet 1 — max 2 sentences]
- [Bullet 2 — max 2 sentences]
- [Bullet 3 — max 2 sentences]
- [Bullet 4 — max 2 sentences]
- [Bullet 5 — max 2 sentences]

**Rating: [Strong Buy / Buy / Hold / Sell / Strong Sell]**
- Target Price: $X ([X]% upside/downside)
- Time Horizon: 1-3+ years
- Key Catalyst: [single most important trigger]

---

## 1. Moat Assessment

### 1a. 护城河决策表 (4-Moat Decision Table — REQUIRED)

| 护城河类型 | 关键判断问题 | 评级 | 量化证据 (Quantified) | 来源 |
|---|---|---|---|---|
| 网络效应 (Network Effects) | Self-reinforcing user growth? Same-side or cross-side? | Strong/Moderate/Weak (n/10) | [Specific number + mechanism, e.g., "300万 CUDA developers, 12% YoY"] | [citation] |
| 转换成本 (Switching Costs) | Cost (time/money/retraining) for customers to leave? | Strong/Moderate/Weak (n/10) | [e.g., "renewal rate 92%, avg integration depth = 14 systems"] | [citation] |
| 规模优势 (Scale Advantages) | Unit cost falls with scale? Can new entrant break even? | Strong/Moderate/Weak (n/10) | [e.g., "capacity utilization 90%+, $20B+ minimum efficient scale"] | [citation] |
| 无形资产 (Intangible Assets) | Brand/patent/license/data competitors cannot copy? | Strong/Moderate/Weak (n/10) | [e.g., "13 nuclear licenses, zero new US issuances since 1996"] | [citation] |

**Vague evidence is rejected.** "Strong brand" is NOT evidence; "brand commands 30% price premium and 70% of customers cite brand as primary reason in NPS surveys" IS evidence.

### 1b. $10B 反事实测试 (Counterfactual Test — REQUIRED for every Strong rating)

For each row above rated **Strong**, answer in 1-2 sentences:
> 如果一个竞争者拥有 $100 亿美元资本和 5 年时间，能否复制这个护城河？

- If **Yes** → downgrade to Moderate/Weak above (state what is replicable and at what cost).
- If **No** → keep Strong (state *what specifically* prevents replication: regulatory monopoly, install-base lock-in, dataset accumulation lag, etc.).

### 1c. 反例检查 (Anti-Pattern Checks — REQUIRED for every Strong rating)

- **First-mover ≠ moat**: Was being first translated into a structural lock-in (network/switching/scale) that late entrants cannot match? Reference: MySpace, Nokia, BlackBerry.
- **Growth ≠ moat**: What % of growth is industry tailwind vs company-specific barriers? If growth is industry-driven, do NOT count it as moat evidence. Strong moat companies grow when the industry shrinks.

A Strong rating that fails either check is auto-downgraded to Moderate.

### 1d. 同业护城河对比 (Peer-Pair Moat Comparison — REQUIRED)

Pick ONE direct peer riding the SAME secular theme to isolate moat-driven returns from theme-driven returns. Pair example: NVIDIA vs Dell (both ride AI infra capex; one captures 60%+ op-margin, one captures single-digit).

| 护城河 | [TICKER] | [PEER on same theme] | Why the gap matters |
|---|---|---|---|
| 网络效应 | S/M/W + 1-line evidence | S/M/W + 1-line evidence | [How this drives margin/durability gap] |
| 转换成本 | S/M/W + 1-line evidence | S/M/W + 1-line evidence | [...] |
| 规模优势 | S/M/W + 1-line evidence | S/M/W + 1-line evidence | [...] |
| 无形资产 | S/M/W + 1-line evidence | S/M/W + 1-line evidence | [...] |

### 1e. 护城河趋势 (Moat Trajectory)

State explicitly: **widening / stable / narrowing** with specific 12-24 month evidence (market share delta, pricing power evidence, switching-cost depth change, regulatory/competitive shifts). Tie to ROIC and gross-margin trajectory from §3.

[Detailed moat analysis using Morningstar framework here, supporting the table above. Reference: frameworks_value_growth.md §"4-Moat Decision Framework".]

## 2. Management Quality Score
[Score: X/10. Capital allocation track record. Insider ownership. Compensation structure. Fisher's 15 points assessment.]

## 3. Intrinsic Value Estimate
[Embed Mermaid charts (e.g., Revenue vs FCF trend) here if provided by the metrics data]
[Include Economic Value Added (EVA) calculation and ROIC vs WACC spread to assess moat expansion/destruction]
[Gross margin trajectory: expanding/stable/contracting (delta in bps). Incremental ROIC: efficiency of new capital deployment.]
[Multiple methods: DCF (base case), Trading Comps, SOTP if applicable. Sensitivity table: WACC vs terminal growth. Reverse DCF implied growth. Margin of safety calculation.]
[DCF terminal value disclosure (Damodaran framework): TV as % of total value. If TV>75%: this is NORMAL for growth companies — disclose assumptions transparently, show sensitivity to ±1% terminal growth rate. If TV>85%: add explicit narrative coherence check — "Does the story (TAM, competitive position, margin trajectory) justify these numbers?" Never switch away from DCF solely because TV is high — instead, scrutinize growth-period assumptions more carefully.]
[Private market comp / LBO floor (if market cap < $100B): maximum PE buyout price at 20% IRR. Precedent transaction premiums in sector.]

## 4. Capital Structure & Shareholder Returns
[Buyback ROI: avg buyback price vs current price (value created/destroyed per dollar). SBC dilution rate (net share count trajectory). Total capital return yield: (Dividends + Net Buybacks) / Market Cap. Debt maturity assessment. Optimal leverage vs sector peers. Cash Conversion Cycle (DIO + DSO - DPO): working capital efficiency vs peers. Current ratio and quick ratio.]

## 5. Narrative & Growth Runway
[Damodaran Narrative+Numbers: 3-sentence company future narrative. Each sentence → model variable mapping (growth, margin, reinvestment, risk). Narrative plausibility score. TAM/SAM/SOM. Secular trends. Industry life cycle. Multi-year compounding potential.]

## 6. Key Long-term Risks
[Top 3-5 risks to permanent capital loss (Klarman: permanent vs temporary impairment distinction). Mitigants for each. ESG/carbon pricing risk for carbon-intensive sectors. M&A/activist probability flag (if score >60/100).]

## 7. Factor Attribution & Liquidity
[Fama-French 5-factor loadings (market, SMB, HML, RMW, CMA). Alpha after factor decomposition. Liquidity score and position sizing constraint. Days to liquidate at 10% participation. Market impact estimate for target position size. Short interest dynamics: SI% float, days to cover, squeeze score. Activist exposure: 13D presence, proxy fight probability, insider confidence ratio.]

## 7b. Tail Risk & Portfolio Context (if portfolio specified)
[VaR/CVaR at 95% and 99% confidence. Max drawdown and drawdown duration. Calmar ratio. Correlation regime (normal/elevated/crisis) from `correlation.json`. Tail correlation spike (does diversification fail under stress?). Asymmetric beta: upside capture vs downside capture ratio. Stress-adjusted beta for position sizing. Drawdown recovery history (mean/median recovery days). Current drawdown status.]

## 8. Capital Allocation Deep-Dive (Long-term reports)
[Mauboussin Capital Allocation Scorecard: score each of 5 levers (Organic Reinvestment, M&A, Buybacks, Dividends, Debt Mgmt). Buffett Retention Test: 5yr market cap change / cumulative retained earnings. Score: >1.5x (Excellent), 1.0-1.5x (Good), 0.5-1.0x (Poor), <0.5x (Destructive). SBC dilution analysis: % of revenue, net share count trajectory, SBC/FCF ratio. Buyback ROI: average repurchase price vs current intrinsic value. M&A track record: ROIC on acquisitions 3yr post-close. Capital allocation verdict: Value Creator / Neutral / Value Destroyer.]

## 9. Supply Chain Resilience (Long-term & Mid-term)
[GICS-industry-specific supply chain mapping: Tier 1 suppliers (direct), Tier 2 (suppliers' suppliers), Tier 3 (raw materials). Geographic HHI: supplier country concentration. Chokepoints identified: single-source components, geographic bottlenecks, regulatory risks. Disruption scenarios modeled: trade war, blockade, natural disaster, supplier failure, logistics crisis. Resilience score (1-10) with component breakdown. Buffer inventory adequacy. Nearshoring/Friendshoring progress.]

## 10. ESG & Sustainability Assessment (Long-term)
[TCFD/ISSB alignment score. Carbon pricing scenario: EBITDA impact at $50/$100/$150/tCO2. Physical risk: asset-level exposure to flood/fire/hurricane/sea-level rise. Transition risk: stranded asset potential. Social license: labor practices, community relations, supply chain human rights. Governance: board independence, dual-class shares, shareholder rights. ESG verdict: Leader / Neutral / Laggard with material risk.]

## 11. Catalyst Calendar (All horizons)
[Forward-looking catalyst table covering 3-12 months. Columns: Date/Window, Event Type (Earnings/Regulatory/Product/Corporate/Macro), Expected Impact (1-5), Probability, Direction. Key binary event scenario: P(positive)×Upside% - P(negative)×Downside% = Expected value. Pre/post-event drift analysis. Options market implied move vs assessed expected move. Top 3 high-conviction catalysts where assessed probability differs from market-implied.]

## 12. China-Specific Analysis (A-Share Only — Mandatory for SH/SZ)
[政策敏感性矩阵: 5-dimension policy sensitivity score. Industrial policy cycle position. 专精特新/国产替代 designation status. Regulatory risk score. 北向资金 flow trend: direction + momentum. 融资融券: margin balance as % free float, margin concentration. 龙虎榜: institutional vs 游资 seat analysis. 行业轮动: sector rotation position. 国家队 positioning: 证金/汇金/社保基金 activity. Concept board membership and speculative risk flag. China Policy Score (1-10) and Capital Flow Score (1-10).]

## 推荐标的排名 (Recommended Stock Ranking)

| # | 代码 | 名称 | 当前股价 | 评分 | 推荐理由 (一句话) |
|---|------|------|----------|------|-------------------|
| 001 | [TICKER] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |
| 002 | [PEER1] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |
| 003 | [PEER2] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |

**首选标的**: 001 [TICKER] 是本分析的首选标的，因为[一句话理由]

---

## 红线条件（触发任何一条 = 强制重新评估）
| # | 红线条件 | 触发动作 | 监测频率 |
|---|---------|---------|---------|
| 1 | [具体可观测条件] | [动作] | [频率] |

## 核心假设追踪表
| # | 核心假设 | 验证方法 | 频率 | 当前状态 |
|---|---------|---------|------|---------|
| 1 | [假设] | [方法] | [频率] | 🟢/🟡/🔴 |

## 多框架交叉验证

### 框架评分
| 框架 | 评分 | 判定 | 关键论点 |
|------|------|------|---------|
| 巴菲特 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 林奇 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 马克斯 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 德鲁肯米勒 | X/10 | BUY/HOLD/AVOID | [一句话] |

### 关键分歧点（这是真正的投资决策点）
| # | 分歧 | 解决指标 | 指标正面 → | 指标负面 → |
|---|------|---------|-----------|-----------|
| 1 | [描述] | [可观测指标] | [结论A] | [结论B] |
| 2 | [描述] | [可观测指标] | [结论A] | [结论B] |

### 框架共识
- 共识强度：HIGH_CONSENSUS_BUY / MIXED / LOW_CONSENSUS / HIGH_CONSENSUS_AVOID
- 评分离散度：X.X（>2.0 = 框架间严重分歧）
- 仓位建议：core / satellite / option（基于共识强度 × 分歧严重程度）

## 投资结论

**结论类型**：✅ 买入 / ❌ 回避 / ⏳ 等待

禁止使用："风险与机会并存"、"需要进一步观察"、"投资者应根据自身风险偏好决定"

如果 ✅ 买入：
- 仓位类型：核心(>20%) / 卫星(5-20%) / 期权(<5%)
- 建议买入区间：$___-$___
- 目标价（三情景，不做概率加权）：
  - 乐观：$___ （触发条件：___）
  - 中性：$___ （触发条件：___）
  - 悲观：$___ （触发条件：___）

如果 ❌ 回避：
- 具体原因（1-3句）
- 何时重新评估的触发条件

如果 ⏳ 等待：
- 等待的具体催化事件
- 时间窗口

## Appendix: Data Quality & Coverage
- Blocking sources checked: [Tier 0/Tier 1 list]
- Missing/stale dimensions: [None / list with impact]
- Source conflicts: [None / list]
- Framework divergences resolved: [count resolved / total detected]
- Confidence cap applied: [None / Medium / Low]
```

### Mid-term Report (1-12 months)

**Methodology Weights**: Lynch (25%), Druckenmiller (20%), Greenblatt (15%), Marks (20%), Weinstein/CANSLIM (20%)

```
# [COMPANY NAME] ([TICKER]) — Mid-term Investment Analysis

**Header**
- Company Name | Ticker | Exchange
- Current Price | 52-week Range | Market Cap | Enterprise Value
- Report Date | Analyst: AI Stock Research Skill (stock-analysis)
- Report Type: Mid-term (1-12 months)

---

## Executive Summary
[1 paragraph, max 150 words]

**Conviction Rating: [X.X]/10 | Confidence: [Low/Medium/High]**

---

## 投资评分维度分解 (Conviction Score Decomposition — Mid-term)

### Dimension Scores & Rationale

| Dimension | Weight | Score | Weighted | Key Data Points | Rationale |
|-----------|--------|-------|----------|-----------------|-----------|
| financial_health | 10% | X.X | X.XX | ROIC: XX%, FCF: $XM, coverage: X.Xx | [1-sentence] |
| moat_quality | 10% | X.X | X.XX | GM stability CV: X.XX, ROIC-WACC: X.Xpp | [1-sentence] |
| management_quality | 10% | X.X | X.XX | CEO tenure: X yrs, beat rate: X/X qtrs | [1-sentence] |
| valuation_attractiveness | 15% | X.X | X.XX | P/E: XX.X vs peer XX.X, PEG: X.X | [1-sentence] |
| macro_tailwind | 10% | X.X | X.XX | [Rates/GDP/PMI direction + impact] | [1-sentence] |
| risk_profile | 10% | X.X | X.XX | Red flags: X, maturity wall: [Y/N] | [1-sentence] |
| weinstein_alignment | 10% | X.X | X.XX | Stage: X, RS rank: top X%, decay-wtd RS: X.XX | [1-sentence] |
| canslim | 10% | X.X | X.XX | [X/7 pass]: C[P/F] A[P/F] N[P/F] S[P/F] L[P/F] I[P/F(rev momentum ±adj)] M[P/F] | [1-sentence] |
| ecosystem_momentum | 5% | X.X | X.XX | Upstream: [healthy/mixed/weak], downstream: [healthy/mixed/weak] | [1-sentence] |
| industry_trajectory | 5% | X.X | X.XX | Direction: [improving/stable/deteriorating], fund flows: [inflow/outflow] | [1-sentence] |
| money_flow_confirmation | 5% | X.X | X.XX | MFI/OBV/CMF: [bullish/neutral/bearish], inflow streak: X days | [1-sentence] |
| **TOTAL** | 100% | — | **X.XX** | — | — |

### 关键决定维度 (Key Decisive Dimensions — Mid-term)
[Which 2-3 dimensions MOST influenced mid-term conviction. Mid-term prioritizes Valuation + Macro.
Example: "中期评级由Macro(8.0)和CANSLIM(7.5)主导——当前周期中期扩张阶段利好该公司，且EPS加速增长连续3季超预期(beat rate: 4/4)。Valuation维度(5.5)限制了更高评级，因P/E 25x已接近历史均值。"]

---

## 1. Category & Thesis
**Lynch Category**: [Slow Grower / Stalwart / Fast Grower / Cyclical / Turnaround / Asset Play]
[Why this category? Why now? PEG ratio context. 1-paragraph thesis.]

## 1b. 护城河决策表 (4-Moat Decision Table — REQUIRED, mid-horizon focus)

Mid-horizon weight: moat determines whether mid-cycle margin compression is temporary (wide moat, snaps back) or terminal (no moat, structural). Render condensed table:

| 护城河 | 评级 (S/M/W, n/10) | 量化证据 (1 line) | 12mo 趋势 (widening/stable/narrowing) |
|---|---|---|---|
| 网络效应 | | | |
| 转换成本 | | | |
| 规模优势 | | | |
| 无形资产 | | | |

**Mid-horizon implication** (1 paragraph): How does the moat profile interact with the next 6-18mo macro/cycle setup? Does the moat let the company gain share *during* the setup (compounding), or is the moat irrelevant to the catalyst (one-time event)?

For full $10B counterfactual + anti-pattern checks + peer-pair table, refer to the long-horizon report. Mid-horizon report only carries the condensed table + trajectory + 1-paragraph implication.

## 2. Catalyst Map
| Catalyst | Date (est.) | Direction | Magnitude | Probability |
|----------|-------------|-----------|-----------|-------------|
| [Event] | [Q/Month] | Positive | High/Med/Low | X% |
| ... | ... | ... | ... | ... |

## 3. Earnings Estimate vs. Consensus
- Our Estimate: Revenue $X, EPS $X
- Consensus: Revenue $X, EPS $X
- Variant View: [where and why we differ]
- Seasonality: [Q seasonal index (1.0=avg). Current quarter vs seasonal expectation (above/in-line/below). Historical beat rate in this quarter.]
- Earnings Edge: Beat rate [X]% (last [N] quarters). Pre-earnings drift: [positive/negative/none]. PEAD tendency: [positive/negative/none]. Next earnings: [date] ([X] days away).

## 4. Relative Valuation

**Peer Comparison Table:**
| Company | Ticker | P/E (NTM) | EV/EBITDA | P/FCF | Rev Growth | Op Margin | ROIC |
|---------|--------|-----------|-----------|-------|------------|-----------|------|
| **[Subject]** | **[TICKER]** | **X** | **X** | **X** | **X%** | **X%** | **X%** |
| [Peer 1] | [TKR] | X | X | X | X% | X% | X% |
| [Peer 2] | [TKR] | X | X | X | X% | X% | X% |
| [Peer 3] | [TKR] | X | X | X | X% | X% | X% |
| *Peer Median* | — | X | X | X | X% | X% | X% |

[P/E (trailing/forward/NTM) vs 5yr avg and peers. EV/EBITDA vs peers with growth justification. P/FCF yield vs risk-free rate. PEG ratio. Private market comp: LBO floor price (if market cap < $100B). Precedent transaction premium range.]

## 5. Technical Structure & Timing
**Weinstein Stage**: [1/2/3/4] — [Evidence: 30-week MA direction, volume pattern, RS rank]
**CANSLIM Score**: [X/7 pass] — C:[P/F] A:[P/F] N:[P/F] S:[P/F] L:[P/F] I:[P/F] M:[P/F]
[Stage 2 breakout confirmed? Volume confirmation? Relative strength rank position.]

### Analyst Revision Momentum
- **Momentum Score**: [X.X]/10 — Direction: [strong_upgrade_trend / moderate_upgrade / neutral / moderate_downgrade / strong_downgrade_trend]
- **Slope**: [X.XXXX]/month — Consistency (R²): [X.XX]
- **Acceleration**: [Accelerating / Steady / Decelerating]
- [Interpretation: "Analysts upgrading/downgrading at X%/month with X% consistency"]

### Multi-Layer Alignment (Stock × Industry × Macro)
- **Alignment Status**: [fully_aligned / partially_aligned / divergent]
- Stock (Technical): [X.X] — [bullish/neutral/bearish]
- Industry (Trajectory): [X.X] — [bullish/neutral/bearish]
- Macro (Tailwind): [X.X] — [bullish/neutral/bearish]
- **Conviction Adjustment**: [+0.5 (all aligned) / 0 / -0.5 (divergent warning)]
- [If divergent: 1-paragraph explaining why stock deviates from environment — outlier leader or swimming against tide?]

## 6. Macro Tailwinds/Headwinds
[Tailwinds: 1-3 factors. Headwinds: 1-3 factors. Net assessment.]

### Currency/FX Exposure (if international_revenue_pct > 25%)
| Metric | Value |
|--------|-------|
| International Revenue % | X% |
| Reporting Currency | [USD/EUR/etc.] |
| ADR Status | [Yes/No] |
| DXY Correlation (1Y) | [X.XX] |
| FX EPS Impact (YTD) | [±X.X% headwind/tailwind] |
| Hedging Program | [Active/Partial/None] |

[If material: state whether current USD cycle is headwind or tailwind, and whether consensus EPS estimates already reflect FX guidance.]

## 8. Capital Allocation Deep-Dive (Long-term reports)
[Mauboussin Capital Allocation Scorecard: score each of 5 levers (Organic Reinvestment, M&A, Buybacks, Dividends, Debt Mgmt). Buffett Retention Test: 5yr market cap change / cumulative retained earnings. Score: >1.5x (Excellent), 1.0-1.5x (Good), 0.5-1.0x (Poor), <0.5x (Destructive). SBC dilution analysis: % of revenue, net share count trajectory, SBC/FCF ratio. Buyback ROI: average repurchase price vs current intrinsic value. M&A track record: ROIC on acquisitions 3yr post-close. Capital allocation verdict: Value Creator / Neutral / Value Destroyer.]

## 9. Supply Chain Resilience (Long-term & Mid-term)
[GICS-industry-specific supply chain mapping: Tier 1 suppliers (direct), Tier 2 (suppliers' suppliers), Tier 3 (raw materials). Geographic HHI: supplier country concentration. Chokepoints identified: single-source components, geographic bottlenecks, regulatory risks. Disruption scenarios modeled: trade war, blockade, natural disaster, supplier failure, logistics crisis. Resilience score (1-10) with component breakdown. Buffer inventory adequacy. Nearshoring/Friendshoring progress.]

## 10. ESG & Sustainability Assessment (Long-term)
[TCFD/ISSB alignment score. Carbon pricing scenario: EBITDA impact at $50/$100/$150/tCO2. Physical risk: asset-level exposure to flood/fire/hurricane/sea-level rise. Transition risk: stranded asset potential. Social license: labor practices, community relations, supply chain human rights. Governance: board independence, dual-class shares, shareholder rights. ESG verdict: Leader / Neutral / Laggard with material risk.]

## 11. Catalyst Calendar (All horizons)
[Forward-looking catalyst table covering 3-12 months. Columns: Date/Window, Event Type (Earnings/Regulatory/Product/Corporate/Macro), Expected Impact (1-5), Probability, Direction. Key binary event scenario: P(positive)×Upside% - P(negative)×Downside% = Expected value. Pre/post-event drift analysis. Options market implied move vs assessed expected move. Top 3 high-conviction catalysts where assessed probability differs from market-implied.]

## 12. China-Specific Analysis (A-Share Only — Mandatory for SH/SZ)
[政策敏感性矩阵: 5-dimension policy sensitivity score. Industrial policy cycle position. 专精特新/国产替代 designation status. Regulatory risk score. 北向资金 flow trend: direction + momentum. 融资融券: margin balance as % free float, margin concentration. 龙虎榜: institutional vs 游资 seat analysis. 行业轮动: sector rotation position. 国家队 positioning: 证金/汇金/社保基金 activity. Concept board membership and speculative risk flag. China Policy Score (1-10) and Capital Flow Score (1-10).]

## 推荐标的排名 (Recommended Stock Ranking)

| # | 代码 | 名称 | 当前股价 | 评分 | 推荐理由 (一句话) |
|---|------|------|----------|------|-------------------|
| 001 | [TICKER] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |
| 002 | [PEER1] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |
| 003 | [PEER2] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |

**首选标的**: 001 [TICKER] 是本分析的首选标的，因为[一句话理由]

---

## 多框架交叉验证

### 框架评分
| 框架 | 评分 | 判定 | 关键论点 |
|------|------|------|---------|
| 巴菲特 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 林奇 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 马克斯 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 德鲁肯米勒 | X/10 | BUY/HOLD/AVOID | [一句话] |

### 关键分歧点（这是真正的投资决策点）
| # | 分歧 | 解决指标 | 指标正面 → | 指标负面 → |
|---|------|---------|-----------|-----------|
| 1 | [描述] | [可观测指标] | [结论A] | [结论B] |
| 2 | [描述] | [可观测指标] | [结论A] | [结论B] |

### 框架共识
- 共识强度：HIGH_CONSENSUS_BUY / MIXED / LOW_CONSENSUS / HIGH_CONSENSUS_AVOID
- 评分离散度：X.X（>2.0 = 框架间严重分歧）
- 仓位建议：core / satellite / option（基于共识强度 × 分歧严重程度）

## 投资结论

**结论类型**：✅ 买入 / ❌ 回避 / ⏳ 等待

禁止使用："风险与机会并存"、"需要进一步观察"、"投资者应根据自身风险偏好决定"

如果 ✅ 买入：
- 仓位类型：核心(>20%) / 卫星(5-20%) / 期权(<5%)
- 建议买入区间：$___-$___
- 目标价（三情景，不做概率加权）：
  - 乐观：$___ （触发条件：___）
  - 中性：$___ （触发条件：___）
  - 悲观：$___ （触发条件：___）

如果 ❌ 回避：
- 具体原因（1-3句）
- 何时重新评估的触发条件

如果 ⏳ 等待：
- 等待的具体催化事件
- 时间窗口

## Appendix: Data Quality & Coverage
- Blocking sources checked: [Tier 0/Tier 1 list]
- Missing/stale dimensions: [None / list with impact]
- Source conflicts: [None / list]
- Confidence cap applied: [None / Medium / Low]
```

### Short-term Report (days to weeks)

**Methodology Weights**: Quantitative/Technical (35%), Soros (25%), Alternative Data (25%), Druckenmiller (15%)

```
# [COMPANY NAME] ([TICKER]) — Short-term Trading Setup

**Header**
- Current Price | 52-week Range | Market Cap
- Report Date | Analyst: AI Stock Research Skill (stock-analysis)
- Report Type: Short-term (days to weeks)

---

## Setup Summary
[1 paragraph: why now, what's the trade? What is priced in vs what is likely?]

**52周位置: XX% | 20日涨幅: +XX% | RSI-14: XX | 入场风险: 低/中/高/极高**

**Conviction Rating: [X.X]/10 | Confidence: [Low/Medium/High]**

---

## 交易评分维度分解 (Conviction Score Decomposition — Short-term)

### Dimension Scores & Rationale

| Dimension | Weight | Score | Weighted | Key Data Points | Rationale |
|-----------|--------|-------|----------|-----------------|-----------|
| valuation_attractiveness | 10% | X.X | X.XX | P/E vs sector: XXx vs XXx, catalyst premium: [Y/N] | [1-sentence] |
| macro_tailwind | 10% | X.X | X.XX | [Rate direction, PMI trend, sector rotation] | [1-sentence] |
| risk_profile | 10% | X.X | X.XX | Earnings in X days, event risk: [low/med/high] | [1-sentence] |
| alternative_alignment | 15% | X.X | X.XX | Web traffic: +X%, app rank: #X, social: [bullish/bearish] | [1-sentence] |
| technical_setup | 15% | X.X | X.XX | RSI: XX, MACD: [signal], decay-wtd RS: X.XX, above MA: [Y/N] | [1-sentence] |
| weinstein_alignment | 10% | X.X | X.XX | Stage: X, breakout: [confirmed/pending], volume: [X vs avg] | [1-sentence] |
| canslim | 10% | X.X | X.XX | M-factor: [confirmed uptrend/correction], rev momentum: X.X/10 | [1-sentence] |
| ecosystem_momentum | 10% | X.X | X.XX | Upstream health: X.X, downstream: X.X, direction: [up/down] | [1-sentence] |
| industry_trajectory | 5% | X.X | X.XX | Sector RS: [rising/falling], fund flows: [in/out] | [1-sentence] |
| money_flow_confirmation | 5% | X.X | X.XX | MFI/OBV/CMF: [bullish/neutral/bearish], volume-price: [量价齐升/背离] | [1-sentence] |
| **TOTAL** | 100% | — | **X.XX** | — | — |

### 关键决定维度 (Key Decisive Dimensions — Short-term)
[Which 2-3 dimensions MOST influenced the trade setup. Short-term prioritizes Alt Data + Technical.
Example: "短期交易信号主要由Alt Alignment(9.0)和Technical(8.5)驱动——网站流量周环比+32%暗示需求加速，且股价刚突破Stage 2阻力位伴随2.5x平均成交量确认。Risk维度(6.0)因5天后财报发布略有折扣。"]

---

## 1. Technical Analysis
- **Weinstein Stage**: [1/2/3/4] — [30-week MA direction, volume confirmation]
- **Trend**: [primary trend direction, moving averages, higher highs/lows]
- **Key Levels**: Support $X, Resistance $X
- **Volume Profile**: POC $X | Value Area $X–$X | Price [above/within/below] VA — [interpretation]
- **Momentum**: RSI [X], MACD [bullish/bearish cross]
- **Volume**: [accumulation / distribution, OBV trend]
- **CANSLIM M-factor**: [Market direction confirmed uptrend? Follow-through day?]

## 2. Flow & Sentiment Signals
- Put/Call ratio: [value] — [contrarian interpretation]
- Short interest: X% of float, X days to cover — Squeeze score: X/10 ([Low/Moderate/High/Extreme])
- Positioning divergence: [convergent/divergent] — momentum [direction] vs short interest [direction]
- Options flow: [unusual activity callout]
- Gamma exposure (GEX): [positive/negative] regime — [pinning/amplification]. Flip strike: $X. Top GEX strikes: [$X, $X]
- Institutional flow: [dark pool, 13F timing]
- Activist exposure: [None / Fund name (X% ownership)] — Proxy fight probability: [Low/Moderate/High]
- AAII sentiment: [% bullish — contrarian at extremes >50% or <25%]

### Analyst Revision Momentum (Short-term signal)
- **Momentum Score**: [X.X]/10 — Direction: [upgrade/neutral/downgrade trend]
- **Slope**: [X.XXXX]/month — Consistency (R²): [X.XX] — Acceleration: [accelerating/steady/decelerating]
- [If score ≥7.5: "Strong upgrade momentum — leading price signal, supports bullish setup"]
- [If score ≤3.0: "Strong downgrade momentum — estimate cuts likely, bearish backdrop"]

### Multi-Layer Alignment (Stock × Industry × Macro)
- **Status**: [fully_aligned / partially_aligned / divergent]
- Stock: [X.X], Industry: [X.X], Macro: [X.X] → Conviction adj: [+0.5/0/-0.5]
- [If divergent: brief note on whether stock is an outlier or the environment is the signal]

## 3. Alternative Data Readings
[Digital signals: web traffic, app engagement, social sentiment. Composite score. Real-time divergences.]

## 3b. 护城河快照 (Moat Snapshot — REQUIRED, short-horizon)

Even short-term setups need a moat sanity-check: a Strong-moat name with a technical breakdown is a *buyable dip*; a No-moat name with a technical breakdown is a *short candidate*. One-line per moat:

| 护城河 | 评级 (S/M/W) | 1-line evidence | Trade implication |
|---|---|---|---|
| 网络效应 | | | |
| 转换成本 | | | |
| 规模优势 | | | |
| 无形资产 | | | |

**Moat-vs-setup interaction** (1 sentence): How does the moat profile change the asymmetry of this short-term trade? Examples: "Strong moat across 3/4 → buy-the-dip bias on technical pullback"; "Weak moat + late-cycle tape → reduce position size by 50%."

For full table + counterfactual + peer pair, see the long-horizon report.

## 8. Capital Allocation Deep-Dive (Long-term reports)
[Mauboussin Capital Allocation Scorecard: score each of 5 levers (Organic Reinvestment, M&A, Buybacks, Dividends, Debt Mgmt). Buffett Retention Test: 5yr market cap change / cumulative retained earnings. Score: >1.5x (Excellent), 1.0-1.5x (Good), 0.5-1.0x (Poor), <0.5x (Destructive). SBC dilution analysis: % of revenue, net share count trajectory, SBC/FCF ratio. Buyback ROI: average repurchase price vs current intrinsic value. M&A track record: ROIC on acquisitions 3yr post-close. Capital allocation verdict: Value Creator / Neutral / Value Destroyer.]

## 9. Supply Chain Resilience (Long-term & Mid-term)
[GICS-industry-specific supply chain mapping: Tier 1 suppliers (direct), Tier 2 (suppliers' suppliers), Tier 3 (raw materials). Geographic HHI: supplier country concentration. Chokepoints identified: single-source components, geographic bottlenecks, regulatory risks. Disruption scenarios modeled: trade war, blockade, natural disaster, supplier failure, logistics crisis. Resilience score (1-10) with component breakdown. Buffer inventory adequacy. Nearshoring/Friendshoring progress.]

## 10. ESG & Sustainability Assessment (Long-term)
[TCFD/ISSB alignment score. Carbon pricing scenario: EBITDA impact at $50/$100/$150/tCO2. Physical risk: asset-level exposure to flood/fire/hurricane/sea-level rise. Transition risk: stranded asset potential. Social license: labor practices, community relations, supply chain human rights. Governance: board independence, dual-class shares, shareholder rights. ESG verdict: Leader / Neutral / Laggard with material risk.]

## 11. Catalyst Calendar (All horizons)
[Forward-looking catalyst table covering 3-12 months. Columns: Date/Window, Event Type (Earnings/Regulatory/Product/Corporate/Macro), Expected Impact (1-5), Probability, Direction. Key binary event scenario: P(positive)×Upside% - P(negative)×Downside% = Expected value. Pre/post-event drift analysis. Options market implied move vs assessed expected move. Top 3 high-conviction catalysts where assessed probability differs from market-implied.]

## 12. China-Specific Analysis (A-Share Only — Mandatory for SH/SZ)
[政策敏感性矩阵: 5-dimension policy sensitivity score. Industrial policy cycle position. 专精特新/国产替代 designation status. Regulatory risk score. 北向资金 flow trend: direction + momentum. 融资融券: margin balance as % free float, margin concentration. 龙虎榜: institutional vs 游资 seat analysis. 行业轮动: sector rotation position. 国家队 positioning: 证金/汇金/社保基金 activity. Concept board membership and speculative risk flag. China Policy Score (1-10) and Capital Flow Score (1-10).]

## 推荐标的排名 (Recommended Stock Ranking)

| # | 代码 | 名称 | 当前股价 | 评分 | 推荐理由 (一句话) |
|---|------|------|----------|------|-------------------|
| 001 | [TICKER] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |
| 002 | [PEER1] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |
| 003 | [PEER2] | [公司名称] | $XX.XX | X.X/10 | [一句话推荐理由] |

**首选标的**: 001 [TICKER] 是本分析的首选标的，因为[一句话理由]

---

## 多框架交叉验证

### 框架评分
| 框架 | 评分 | 判定 | 关键论点 |
|------|------|------|---------|
| 巴菲特 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 林奇 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 马克斯 | X/10 | BUY/HOLD/AVOID | [一句话] |
| 德鲁肯米勒 | X/10 | BUY/HOLD/AVOID | [一句话] |

### 关键分歧点（这是真正的投资决策点）
| # | 分歧 | 解决指标 | 指标正面 → | 指标负面 → |
|---|------|---------|-----------|-----------|
| 1 | [描述] | [可观测指标] | [结论A] | [结论B] |
| 2 | [描述] | [可观测指标] | [结论A] | [结论B] |

### 框架共识
- 共识强度：HIGH_CONSENSUS_BUY / MIXED / LOW_CONSENSUS / HIGH_CONSENSUS_AVOID
- 评分离散度：X.X（>2.0 = 框架间严重分歧）
- 仓位建议：core / satellite / option（基于共识强度 × 分歧严重程度）

## 投资结论

**结论类型**：✅ 买入 / ❌ 回避 / ⏳ 等待

禁止使用："风险与机会并存"、"需要进一步观察"、"投资者应根据自身风险偏好决定"

如果 ✅ 买入：
- 仓位类型：核心(>20%) / 卫星(5-20%) / 期权(<5%)
- 建议买入区间：$___-$___
- 目标价（三情景，不做概率加权）：
  - 乐观：$___ （触发条件：___）
  - 中性：$___ （触发条件：___）
  - 悲观：$___ （触发条件：___）

如果 ❌ 回避：
- 具体原因（1-3句）
- 何时重新评估的触发条件

如果 ⏳ 等待：
- 等待的具体催化事件
- 时间窗口

## Appendix: Data Quality & Coverage
- Quote/options/technicals freshness: [timestamp]
- Missing/stale dimensions: [None / list with impact]
- Source conflicts: [None / list]
- Confidence cap applied: [None / Medium / Low]
```

## Scenario Analysis Template (All Reports)

| Scenario | Probability | Key Assumptions | Implied Price |
|----------|------------|-----------------|---------------|
| Bull | X% | [Best realistic outcome: revenue, margin, multiple] | $X |
| Base | X% | [Most likely outcome] | $X |
| Bear | X% | [Worst realistic outcome] | $X |

**Risk/Reward Ratio**: X:1

### Scenario Probability Derivation (Regime-Adjusted)

Do NOT assign fixed probabilities. Derive them from the macro regime identified in Stage 4:

**Step 1**: Identify 3-5 key driver variables (revenue growth rate, operating margin, terminal multiple, etc.)
**Step 2**: Set driver ranges — Base = consensus midpoint; Bull/Bear = ±1 standard deviation on 2+ drivers
**Step 3**: Run DCF for each scenario's driver combination
**Step 4**: Apply regime-adjusted probabilities:

| Macro Regime (from Stage 4) | Bull % | Base % | Bear % |
|-----------------------------|--------|--------|--------|
| Expansion (early cycle) | 30 | 55 | 15 |
| Expansion (mid cycle) | 20 | 60 | 20 |
| Expansion (late cycle) | 15 | 55 | 30 |
| Recession (early) | 10 | 40 | 50 |
| Recession (late) | 25 | 50 | 25 |
| Stagflation | 10 | 35 | 55 |
| Ambiguous / Transition | 20 | 60 | 20 |

**Step 5**: Compute Risk/Reward Ratio:
```
R/R = (Bull_Price - Current_Price) × Bull_Prob / (Current_Price - Bear_Price) × Bear_Prob
```
- R/R > 3:1 → Attractive
- R/R 1.5-3:1 → Moderate
- R/R < 1:1 → Avoid

## Update Report Template (Re-Analysis)

When re-running analysis after a trigger event (earnings, price target hit, macro regime change,
kill switch approaching), produce an **UPDATE REPORT** rather than a full re-report. The update
report focuses on what changed, what stayed the same, and conviction delta.

**When to use**: Trigger events from the Post-Report Monitoring Protocol (see SKILL.md):
- Earnings release (within 3 days)
- Price hits bull or bear scenario target
- Kill switch condition >80% of trigger level
- Material news (M&A, regulatory, executive departure)
- Macro regime change (Dalio quadrant shift)
- 90/30/7-day elapsed (long/mid/short reports)

**Update report is NOT a full re-report.** Only re-run affected stages. If conviction changes
by ≥1.5 points, flag as "MATERIAL CHANGE."

```
# [TICKER] — Analysis Update

**Update Type**: [Earnings Update / Price Target Hit / Catalyst Triggered / Macro Shift / Scheduled Refresh]
**Update Date**: YYYY-MM-DD
**Original Report**: [TICKER]_[Type]_[Original Date].md (Conviction: X.X/10)

---

## What Changed

| Dimension | Prior (Date) | Current (Date) | Δ | Impact |
|-----------|-------------|----------------|----|--------|
| Price | $X | $Y | +Z% | [Closer to/further from target] |
| Earnings/Fundamentals | [key metric change] | [value] | [delta] | [Thesis strengthened/weakened] |
| Valuation | $X/share (MoS: +Y%) | $Z/share (MoS: +W%) | [delta] | [More/less attractive] |
| Macro | [Regime before] | [Regime now] | [delta] | [Tailwind/headwind shift] |
| Technical | [Setup before] | [Setup now] | - | [Trend intact/broken] |
| Risk | [Red flags: N] | [Red flags: M] | [delta] | [Risk increased/decreased] |

## Conviction Delta

| Component | Prior Score | Current Score | Δ |
|-----------|------------|---------------|----|
| Financial Health | X.X | Y.Y | ±Z.Z |
| Moat Quality | X.X | Y.Y | ±Z.Z |
| Management Quality | X.X | Y.Y | ±Z.Z |
| Valuation Attractiveness | X.X | Y.Y | ±Z.Z |
| Capital Structure | X.X | Y.Y | ±Z.Z |
| Macro Tailwind | X.X | Y.Y | ±Z.Z |
| Risk Profile | X.X | Y.Y | ±Z.Z |
| Alternative Alignment | X.X | Y.Y | ±Z.Z |
| Technical Setup | X.X | Y.Y | ±Z.Z |
| Weinstein Alignment | X.X | Y.Y | ±Z.Z |
| CANSLIM | X.X | Y.Y | ±Z.Z |

**Prior Conviction**: X.X/10 ([Rating]) | **Current Conviction**: Y.Y/10 ([Rating]) | **Δ**: ±Z.Z

**[If Δ ≥ 1.5: "MATERIAL CHANGE — thesis significantly altered"]**
**[If Δ < 1.5: "MINOR ADJUSTMENT — thesis largely intact"]**

## Thesis Status

### Still Valid
- [Aspect of thesis that remains unchanged]
- [Aspect of thesis that remains unchanged]

### Modified
- [What changed and why]
- [What changed and why]

### New Considerations
- [New factor not in original thesis]
- [New factor not in original thesis]

## Updated Recommendation

- **Rating**: [Buy/Hold/Sell] (Prior: [Rating])
- **Target Price**: $X (Prior: $Y) — [X% upside from current]
- **Stop Loss**: $X (Prior: $Y)
- **Time Remaining**: [X months/days] from original horizon
- **Position Size**: X% [Unchanged / Adjust to Y%]

### Action
- [ ] Maintain position (thesis intact, within target range)
- [ ] Add to position (thesis strengthened, larger margin of safety)
- [ ] Reduce position (thesis partially invalidated, reduce risk)
- [ ] Exit position (kill switch triggered or thesis broken)

## Kill Switch Status

| Condition | Trigger Level | Current Level | Status |
|-----------|--------------|---------------|--------|
| [Condition 1] | [Threshold] | [Value] | [OK / APPROACHING / TRIGGERED] |
| [Condition 2] | [Threshold] | [Value] | [OK / APPROACHING / TRIGGERED] |

## Next Update
[Scheduled / Trigger-based: next earnings date, X days, or if price reaches $Y]

## Appendix: Data Quality & Coverage (for re-run stages only)
- Re-run stages: [List of stage numbers]
- Data freshness of re-run data: [Dates]
- Source conflicts introduced: [None / list]
```

### Update Report Rules

1. **Only re-run affected stages.** Don't redo the full analysis for a minor trigger.
2. **Compare scores explicitly.** Always show prior vs current component scores side-by-side.
3. **Flag material changes.** If conviction moves ≥1.5 points, the update report carries "MATERIAL CHANGE" warning.
4. **Action clarity.** Every update report must give an explicit action (maintain/add/reduce/exit).
5. **Kill switch always checked.** Re-evaluate all kill switch conditions against fresh data.
6. **Update report replaces nothing.** The original report remains for audit trail; the update is a supplement.
7. **Scheduled refreshes are lighter.** A 90-day scheduled refresh for a long-term report only re-runs Stages 6+7+10+11; fundamentals/moat assessments carry forward unless a material event occurred.

## Source Attribution Format

Every data claim must use:
```
[Source: EDGAR 10-K FY2024 | Retrieved: YYYY-MM-DD | Fact]
[Source: Seeking Alpha Q3 Transcript | Retrieved: YYYY-MM-DD | Interpretation]
[Source: Analyst estimate | Retrieved: YYYY-MM-DD | Speculation]
```

## Disclaimer (MUST include in every report)

```
---
**Disclaimer:** This analysis is generated by an AI system for informational and educational purposes only. It does not constitute financial advice, investment recommendation, or solicitation to buy or sell securities. The analysis may contain errors, outdated information, or incomplete data. Past performance does not guarantee future results. Always consult a qualified financial advisor before making investment decisions. The authors and tool creators accept no liability for losses arising from use of this analysis.
```
