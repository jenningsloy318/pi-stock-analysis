---
title: Single-framework anchoring — Buffett-only or Dalio-only is incomplete
severity: MEDIUM
appliesTo: stage17, stage18, report-writing, methodology
tags: framework-divergence, methodology-attribution, multi-framework
---

## Single-framework anchoring — one framework is incomplete

Every conviction score must be traceable to ≥2 analytical frameworks. Citing only Buffett (long-term moat lens) or only Dalio (macro regime) or only Soros (reflexivity) produces lensed conclusions that miss the dimensions the chosen framework de-emphasizes. A "buy" call grounded in Buffett-only metrics ignores macro regime; a "sell" call grounded in Dalio-only ignores idiosyncratic moat strength. The report MUST show framework convergence (or acknowledged divergence) to be valid.

**Why it matters**: Frameworks see the world through specific lenses:
- **Buffett / Munger / Graham**: moat, ROIC, margin of safety, capital allocation — blind to macro cycle and momentum
- **Dalio / Soros / Druckenmiller**: macro regime, reflexivity, monetary cycle — blind to idiosyncratic moat
- **Lynch / Fisher**: growth phase, scuttlebutt — blind to mature-cycle deterioration
- **ARK / growth**: TAM × adoption → blind to terminal value sensitivity (Pitfall 10)
- **Marks / Taleb / Burry**: risk, fat-tail, contrarian → blind to compounding upside
- **Mauboussin / Damodaran**: process + valuation → blind to behavioral / sentiment

A buy-the-dip call coming from "Buffett ROIC 25%, Munger quality, Graham margin of safety" is logically consistent but ignores whether Dalio's regime supports the trade. Conversely a sell call from "Dalio late-cycle + Soros reflexivity exhaustion" ignores Buffett-strong fundamentals that may justify holding through cycle.

**How to apply**:

1. **Every conviction conclusion must cite ≥2 frameworks**:
   ```
   Long-term: BUY (Conviction 78/100)
   Frameworks: Buffett (moat: wide; ROIC 28%; pricing power) ✓
              Mauboussin (capital allocation A; reinvestment runway) ✓
              Dalio (regime: late-mid cycle, supportive) ✓
   Divergence acknowledged: Burry (margin debt high; tail risk elevated) ✗
   ```

2. **Acknowledge divergence explicitly** — every report must contain at least 1 framework that disagrees with the conclusion + a reasoned override. "All frameworks agree" reads as cherry-picking; the validator should be suspicious.

3. **Horizon-appropriate frameworks**:
   - Long-term report: Buffett, Munger, Graham, Mauboussin, Lynch, ARK (≥3 of 6)
   - Mid-term report: Dalio, Soros, Druckenmiller, Marks, Greenblatt (≥3 of 5)
   - Short-term report: Soros (reflexivity), Druckenmiller (positioning), Taleb (tail), Burry (forensic) (≥3 of 4)

4. **Dimension transparency** (CLAUDE.md rule): every report decomposes conviction into all dimensions with numeric scores AND raw data per dimension. A conviction that loads heavily on a single dimension = de facto single-framework.

5. **`validate_report.py` rule**: if frameworks_cited.count < 2 OR divergence_acknowledged == False, FAIL with `INSUFFICIENT_FRAMEWORK_DIVERSITY`.

**When the rule does NOT apply**:
- Pure quant report (factor exposure, technical only) — frameworks are statistical models, not investor lenses
- Screening reports — apply at watchlist construction, not per-name

**Cross-references**:
- Pitfall 11 — stale data could make a framework look like it disagrees when actually inputs are stale
- All `references/frameworks_*.md` files — load on demand per stage
- Stage 16 (`agents/scorer.md`) — must emit per-framework score + divergence flag
- Stage 17/18 (`agents/equity-report-writer.md`) — must render framework divergence section
- `scripts/validate_report.py` — framework diversity gate
