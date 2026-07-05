---
title: Discount rate = time + termination hazard — high-q names cap exit threshold
severity: HIGH
appliesTo: stage16, stage17, exit, take-profit, optimal-stopping, distressed
tags: discounting, hazard-rate, optimal-stopping, real-options, price-target
---

## Discount rate = time + termination hazard — high-q names cap exit threshold

A 12-month price target silently assumes survival. "Hold for the higher exit" is an optimal-stopping decision: keep holding (a live wait-option on a better price) until value crosses threshold `V*`, then act. The mistake is discounting that future exit **only for time** (theta, cost of carry, risk-free rate) while ignoring the term that usually dominates: the **hazard that you never get to act at all** — the name delists, halts, gaps to zero, blows up on fraud, files Ch.11, or *you* are forced out (margin call). The hazard *is* part of the discount rate, and it pulls the optimal threshold **toward acting now**.

**Why it matters — the math is exact, not hand-waving** (Oprea, Friedman, Anderson 2009; Dixit & Pindyck 1994 ch. 5):

A risk-neutral agent holds an opportunity whose value `V` follows GBM with drift `α`, vol `σ`. The optimal policy is a threshold `V* = (1 + w*)C` where:

```
w* = 1 / (B − 1),   B = ½ − α/σ² + √[ (α/σ² − ½)² + 2ρ/σ² ]   (>1)
```

Comparative statics:
- **↑ discount rate `ρ` ⇒ ↑ B ⇒ ↓ w* ⇒ lower threshold.** More impatience ⇒ act at a lower bar.
- **↑ volatility `σ` ⇒ B → 1 ⇒ ↑ w* ⇒ higher threshold.** More uncertainty ⇒ wait-option is worth more.

The non-obvious part: **where `ρ` comes from**. The lab discount rate was the **per-period delisting hazard `q`**:

```
ρ = −ln(1 − q) / Δt
```

Per-period discount factor `e^{−ρ}` is **your survival probability**, not the T-bill rate. A 2%/yr risk-free rate is rounding error next to a name carrying a 10–30%/yr probability of a thesis-ending event.

**How to apply**:

1. **Decompose the discount rate into time + hazard.** Before publishing a 12-month target, ask: "What's the probability of an event that takes the *entire* payoff to zero (not just a drawdown)?" That hazard, not the risk-free rate, sets `V*`.

2. **Two levers, opposite signs.** High hazard pulls the exit threshold *down* (act sooner); high vol pushes it *up* (don't cut a high-vol winner short on a low-hazard name). Most analysts adjust one and forget the other.

3. **Score the hazard `q` per name** (`calibrate_conviction.py` derives this automatically):
   - **Low q (0–3%/yr)**: Quality large-caps in benign regime → published target stands
   - **Medium q (3–10%/yr)**: Cyclical / unprofitable / mid-cap → target cut by 10–20%
   - **High q (10–30%/yr)**: Manipulator tapes (Pitfall 8), micro-floats, going-concern risk, distressed → target cut by 30–50%; "sell into strength" is the dominant policy
   - **Extreme q (>30%/yr)**: Sub-$1 / delisting watch / Ch.11-risk → continuation value near zero; don't publish a 12-month target

4. **Hazard signal sources** (already computed in our pipeline):
   - Beneish M-Score >−1.78 → fraud risk hazard
   - Altman Z-Score <1.81 → bankruptcy hazard
   - Short interest >25% with rising debt-maturity wall → squeeze + funding risk
   - Manipulator-tape tag (Pitfall 8) → high q
   - Going-concern flag from auditor → extreme q

5. **Long-dated holds compound hazard.** A LEAPS / multi-year thesis compounds `q` over the whole horizon; cumulative survival `(1−q)^n` decays fast. A 5-year thesis on a 10%/yr-q name has 59% cumulative survival — the "huge target" you didn't write down is multiplied by 0.59.

6. **Forced-exit hazard counts too.** Margin on the position, hard cash-need date, or any path to forced liquidation before thesis matures is part of `q` even if the underlying is fine.

7. **Sanity test**: if the reason to hold is "the discounted target still beats exiting now," multiply by `(1−q)^n`. If that flips the decision, exit.

**Output format** (`calibrate_conviction.py`):
```
nominal_target_12m: $XX.XX
hazard_q_annual: 0.YY  
cumulative_survival_12m: Z.ZZ  
hazard_adjusted_target: $XX.XX  (= nominal_target × cumulative_survival)
exit_policy: "hold" | "trim" | "sell_into_strength" | "exit_now"
```

**When the rule does NOT apply**:
- Quality large-caps in benign regime → low q → human bias is *bailing too early*, not too late
- Index ETFs (SPY, QQQ) → q ≈ 0 at the index level

**Cross-references**:
- Pitfall 8 — manipulator tapes carry the highest single-name termination hazard
- Pitfall 11 — stale data could mask deteriorating hazard signals (Beneish, Altman shift quarterly)
- `references/frameworks_taleb_graham.md` — fat-tail and margin-of-safety machinery
- Stage 16 (`agents/scorer.md`) — hazard adjustment to conviction
- `scripts/calibrate_conviction.py` — hazard-rate machinery
