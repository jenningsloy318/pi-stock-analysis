# Risk & Alternative Frameworks

## Howard Marks — Second-Level Thinking

### Six Questions (Answer for Every Analysis)
1. What is the range of likely outcomes?
2. Which outcome do I think will occur?
3. What does consensus think?
4. How does my expectation DIFFER from consensus?
5. How does the current price fit consensus expectations vs. my view?
6. Is the psychology driving the price too optimistic or too pessimistic?

The differentiated view (#4) is the most important output. If you can't articulate a clear variant perception, you don't have an edge.

### Cycle Position Checklist
- Economy: Vigor or Slowing?
- Lenders: Eager or Restrained?
- Spreads: Narrow or Wide?
- Investors: Optimistic or Pessimistic?

| Left-column answers > right → Defensive posture (raise cash, tighten stops)
| Right-column answers > left → Aggressive posture (deploy capital, widen stops)

### Risk Principles
- Risk means the probability of permanent capital loss, not volatility.
- Risk is highest when it feels lowest (complacency).
- The greatest risk comes from assets everyone agrees are safe.
- Price is the ultimate risk arbiter: high prices = high risk; low prices = low risk.

## Michael Burry — SEC Filing Deep-Dive

### Priority Order (read in this sequence)
1. **Footnotes first** — Problems hide and assets are buried in footnotes. Off-balance-sheet items, contingent liabilities, related-party transactions.
2. **Cash flow statement over income statement** — Cash flow is harder to fake than earnings. Compare OCF to Net Income over 5 years. Persistent OCF < Net Income is a red flag.
3. **MD&A tone analysis** — Compare year-over-year language. Is management acknowledging challenges or deflecting? Look for buried trend changes (e.g., "revenue growth decelerated" buried in paragraph 8).
4. **Accounts receivable growth vs. revenue growth** — AR growing faster than revenue suggests channel stuffing or deteriorating collection. Compute: AR Growth Rate / Revenue Growth Rate. Ratio > 1.2 is a warning.
5. **Inventory growth vs. COGS growth** — Inventory growing faster than COGS suggests obsolete inventory or demand weakness.
6. **Capitalization of expenses** — Are costs being capitalized rather than expensed? Software development, customer acquisition, R&D.

## ARK Invest — Disruption Framework

### Five Questions for Disruptive Companies
1. **Technology S-Curve Position**: Has the technology passed the 10-15% adoption tipping point? Below this = speculative. Above this = adoption accelerates.
2. **Wright's Law Cost Modeling**: For each cumulative doubling of production, how much does unit cost decline? Apply this curve to project future costs.
3. **First-Principles TAM**: What is the total addressable market if the technology achieves its theoretical potential — not the incumbent-defined TAM?
4. **Unit Economics at Scale**: At projected scale (5-year forward), what are the unit economics? CAC, LTV, gross margin, payback period. Are they improving with scale?
5. **5-Year Forward Valuation**: Value the company at projected scale, not current scale. Apply a mature-company multiple to 5-year-forward revenue/EBITDA.

## Primary Research & Channel Checks (Stage 8.6)

### Convergence Scoring

Rate independent-source alignment:

| Level | Criteria | Confidence | Action |
|-------|----------|------------|--------|
| **High Convergence** | 4+ independent sources agree on the same directional signal | High | Can inform thesis; cite as supporting evidence |
| **Moderate Convergence** | 2-3 sources agree | Moderate | Directional indicator; flag uncertainty |
| **Low Convergence** | Single source or sources conflict | Low | Cannot inform thesis; flag as "unverified" |

### Source Hierarchy (Most to Least Reliable)

1. SEC filings and regulatory documents (verifiable, legal liability)
2. Earnings call transcripts (public, on record)
3. Competitor filings mentioning the company (independent validation)
4. Expert network transcripts / industry conference notes
5. Customer/supplier reviews (Glassdoor, G2, TrustRadius)
6. Social media and forums (lowest reliability, highest recency)

### Conflicting Source Protocol

When sources disagree:
- Report BOTH sides explicitly: "Channel checks produced mixed signals: [bull view] from [source A], but [bear view] from [source B]."
- Do NOT cherry-pick confirming evidence
- Weight by source hierarchy (SEC filing > social media)
- If conflict is material to thesis, it must appear in the Risk section (Stage 7)

### Limitations Disclosure (Required)

Every channel check finding must include:
```
[Channel Check: Based on N independent sources. Not statistically representative. Directional only.]
```

---

## Forensic Accounting Red Flags

### 9 Red Flags (Immediate deep investigation if 3+ present)

| # | Red Flag | Threshold |
|---|----------|-----------|
| 1 | **Beneish M-Score** | > -1.78 (manipulation probability) |
| 2 | **Altman Z-Score** | < 1.81 (bankruptcy risk) |
| 3 | **OCF vs Net Income** | OCF declining while Net Income grows (divergence) |
| 4 | **Insider Sales** | Multiple insider sales in 30 days (non-10b5-1 plans) |
| 5 | **Glassdoor Rating** | Declining >0.5 points in 6 months |
| 6 | **Institutional Holdings** | Top 10 holders reducing positions (check 13F) |
| 7 | **Auditor Change** | Auditor change or qualified opinion |
| 8 | **Web Traffic vs Revenue** | Web traffic declining while company reports growth |
| 9 | **Leadership Departures** | Senior leadership departures clustering (2+ in 6 months) |

### Beneish M-Score Calculation (8 Variables)
- DSRI: Days Sales in Receivables Index
- GMI: Gross Margin Index
- AQI: Asset Quality Index
- SGI: Sales Growth Index
- DEPI: Depreciation Index
- SGAI: Sales, General & Admin Expenses Index
- LVGI: Leverage Index
- TATA: Total Accruals to Total Assets

M-Score = -4.84 + 0.920×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI + 0.115×DEPI - 0.172×SGAI + 4.679×TATA - 0.327×LVGI

### Altman Z-Score
Z = 1.2×A + 1.4×B + 3.3×C + 0.6×D + 1.0×E
- A: Working Capital / Total Assets
- B: Retained Earnings / Total Assets
- C: EBIT / Total Assets
- D: Market Value of Equity / Total Liabilities
- E: Sales / Total Assets

Z > 2.99: Safe. 1.81 < Z < 2.99: Grey zone. Z < 1.81: Distress.

## Thesis Falsifiability & Pre-Mortem

### Pre-Mortem Exercise

Before finalizing any thesis, run this structured exercise:

**Prompt**: "It is [report horizon + 6 months]. The investment in [TICKER] has been a disaster — capital is down 40%+. Write the post-mortem explaining exactly what happened."

Generate 3-5 plausible failure narratives. For each, identify:
- The specific trigger event
- Why the analyst missed it (what bias was operating?)
- What early warning signal existed but was dismissed?

### Falsification Conditions

Define 3-5 conditions that would invalidate the thesis. Each must be:

| Property | Requirement | Example |
|----------|-------------|---------|
| **Falsifiable** | Objectively verifiable true/false | "Revenue growth falls below 10% for 2 consecutive quarters" |
| **Timely** | Observable within report horizon | Not "someday the moat might erode" |
| **Actionable** | Triggers specific portfolio action | "If triggered → reduce position by 50%" |
| **Leading** | Detectable before full thesis collapse | Use leading indicators, not lagging |

### Kill Switch Template

```
KILL SWITCH for [TICKER] [Report Type]:
- Condition: [specific, observable, measurable]
- Data source to monitor: [where to check]
- Check frequency: [daily / weekly / quarterly]
- Action if triggered: [exit / reduce X% / hedge with Y]
- Current status: [NOT triggered / APPROACHING / TRIGGERED]
```

### Inversion Checklist (Munger)

Answer each before finalizing any Buy/Strong Buy rating:
1. "How could this investment destroy my capital?" — List top 3 paths to permanent loss.
2. "What am I not seeing because of confirmation bias?" — What evidence have I ignored or dismissed?
3. "If I had to argue the bear case to a skeptical audience, what are my 3 strongest points?"
4. "What would need to happen for this company to go bankrupt in 5 years?" — Even if unlikely, trace the path.
5. "Who is the most credible person/analyst arguing against this stock, and what is their best argument?"

### Confidence Calibration
Rate each thesis pillar:
- 8-10: High confidence — backed by quantitative data from Tier 1 sources
- 5-7: Moderate confidence — supported by directional evidence but some assumptions unverified
- 1-4: Low confidence — speculative, based on extrapolation or single sources

Pillars rated <6 must be flagged as "[SPECULATIVE]" in the report body.

## The Lollapalooza Matrix (Munger Synthesis)

Identify if multiple factors are combining synergistically to create a non-linear outcome. A "Lollapalooza Event" occurs when 3+ high-strength factors overlap.

| Factor A | Factor B | Factor C | Outcome Synergy |
| :--- | :--- | :--- | :--- |
| Wide Moat | Macro Tailwind | Insider Buying | **Extreme Conviction Long** |
| High Leverage | Macro Headwind | Mgmt Departure | **High Probability Short/Avoid** |
| Disruption | Adoption Tipping Pt | Unit Econ Scale | **ARK Exponential Play** |
| Forensic Red Flag | OCF < Net Income | Auditor Change | **Forensic Meltdown Warning** |

**Action**: If a Lollapalooza synergy is detected, the agent must upgrade the Conviction Score by **+1.5 points** and add a "Lollapalooza Alert" callout to the Executive Summary.

