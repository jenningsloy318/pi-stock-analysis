# Price Action Microstructure Framework

How price moves at the orderbook level — a mental model built on 8 primitives. Used to read tape and explain *why* the same news produces opposite reactions in different orderbook structures.

**Loading rule**: Load on demand for short-term horizon, alt-data Stage 13, and risk-analyst Stage 12 retail-saturation work. Skip for long-term fundamental reports.

**Critical rule**: This framework explains *how* price moves and *why* the same catalyst lands differently depending on orderbook state. It does **not** predict direction. Direction comes from catalysts + tape; this framework explains why the tape looks the way it does.

Adapted from `himself65/trade-skills` price-action-framework.md.

---

## Primitive 1: Price movement = buy/sell flow imbalance per unit time

- Up move = buy flow penetrates the ask side (eats ask quotes)
- Down move = sell flow penetrates the bid side (eats bid quotes)
- Flat = buy and sell flow consume each other at the same price; volume can be high while price barely moves

**Implication**: Any "sudden rip / sudden flush" must have one side of the orderbook getting eaten fast. If you don't see corresponding volume, the move is either an illiquidity wick or manipulator-tape (Pitfall 8).

---

## Primitive 2: Every buyer is a future seller

Every buyer has a target price; only the distribution differs. So "buy flow always exceeds sell flow" cannot persist:
- Today's buyers become tomorrow's sellers at higher prices
- A sustained uptrend requires a **continuous supply of new buyers with higher target prices**

**Implication**: Without fresh marginal bulls (new catalyst / new narrative / new capital), a one-way trend must exhaust. "Who hasn't bought yet?" is closer to the answer than "what should it be worth?"

---

## Primitive 3: Consensus vs divergence — the source of price action

| Market state | Price action | Cause |
|---|---|---|
| Everyone shares the same target | **Low-volume drift** | No disagreement → no transactional need |
| Targets dispersed | **High-volume chop** | Counterparty on both sides |
| Consensus shifts from one fair value to another | **High-volume breakout/breakdown** | Repricing in progress |

**Counter-intuitive implication**: **High volume is not a bull signal — it is a *divergence* signal.** Low-volume drift up can be more bullish than high-volume breakout. A high-volume breakout marks new consensus forming; a low-volume continuation marks existing consensus holding. Both can be bullish.

---

## Primitive 4: Vacuum zones (air pockets)

The microstructure explanation for "the breakout held":
1. Price grinds up, eating ask quotes
2. Sellers who originally posted limits at $X get filled
3. With those quotes gone, the orderbook above is sparse — the vacuum zone
4. The next push of the same magnitude needs less buy flow → "acceleration after breakout"

Air pockets exist symmetrically below: support breaks → bids stacked at $Y are gone → orderbook below is sparse → accelerating downside.

**Implications**:
- "Retest holds" = vacuum above is still intact; next buy push meets less resistance
- "Sharp bounce after high-volume breakdown" = false breakdown; vacuum never formed
- Identifying air pockets > predicting them. Tape with fast, near-frictionless travel = live confirmation a vacuum exists

---

## Primitive 5: Pullbacks are symmetric — rotation, not collapse

On a pullback, someone sold lower than originally planned. Reasons matter:

| Trigger | Read |
|---|---|
| Profit-take | Healthy pullback |
| Panic stop-out | Dangerous |
| Position rebalance | Neutral |
| Information update | Possible trend reversal |

**Implication**: Pullbacks are *holder rotation*, not necessarily warnings. The real question is *who is selling and who is bidding*:
- Retail panic + institutions bidding → healthy shakeout
- Institutions distributing + retail bidding → FOMO top (dangerous)
- Everyone selling → consensus collapse (Primitive 6)

---

## Primitive 6: High-volume breakdown = consensus shifted lower

Not a TA ritual — a real orderbook event:
1. Bids stacked at support get eaten
2. Bids below are sparser (vacuum zone)
3. Large volume now prints at lower prices = market accepted fair value moved down
4. Yesterday's consensus is dead; new one must form at a new level

**Implication**: After high-volume breakdown, *don't bottom-fish just below the old support*. Wait for new consensus to form at a new level before sizing in.

---

## Primitive 7: Information re-prices fair value across the whole tape

> Fundamentals do not change instantly — but the *market's perception* of fundamentals can change in seconds.

The same company before and after an earnings call is the same company. The collective *valuation* is not. The fundamental difference between trending and ranging:
- **Ranging**: no new information → participants negotiate around known fair value → orderbook is deep → low-volume chop dominates
- **Trending**: new information re-rates fair value → old orderbook is invalidated → price hunts for new equilibrium

**The key real-time question**: "Is today's stock the same stock as yesterday's?"
- Yes → range trading; mean-reversion edges
- No → repricing regime; momentum edges

Things that flip "same → different": earnings, guidance changes, sustained large institutional flow (not a single block), sector co-moves, regulatory or supply-chain news.

---

## Primitive 8: Float composition determines stress behavior

Who holds the float determines how the stock reacts under pressure:

| Holder mix | Up move behavior | Down move behavior |
|---|---|---|
| Institutional / long-term dominant | Low-volume orderly grind up | Resilient — bids step in |
| Retail / FOMO dominant | High-volume parabolic | Brittle — panic flush |
| High short interest | Easy squeeze up | Sharp give-back after squeeze |
| **High retail social-media saturation** | Easy blow-off top | Sharp decline once top confirms |

**Implication (contrarian sentiment read)**: When a name has too much retail on board (heavy social-media discussion, KOL cascade, retail chat saturation), the condition *"no new retail left to relay-buy"* is approaching. This is **not** "if KOLs pump it, the stock is bad" — it is "retail demand pool is exhausted; marginal-bull supply is drying."

This is the foundation of the `social_saturation_score` emitted by `fetch_alternatives.py` and consumed by Stage 13. See Pitfall 9.

---

## Putting it together — from framework to trade decision

### Decision tree

```
1. Is this a "repricing regime" or "range trading"?
   - New catalyst / sector co-move / fair-value re-rate underway → repricing
   - None of the above → ranging

2. If repricing:
   - What direction does consensus point? (volume + breakout direction + sector alignment)
   - Is there a vacuum zone? (tape moves through prices with almost no resistance)
   - Is the holder structure healthy? (institutions still net-buying / retail not saturated)
   - All three yes → trade with the trend
   - Any no → stand aside, OR wait for a pullback + second confirmation

3. If ranging:
   - Is the vacuum zone above or below?
   - Approaching the vacuum boundary on LOW volume → fade back into the range (mean revert)
   - Approaching the vacuum boundary on HIGH volume → wait for the breakout to confirm, then re-evaluate under repricing logic
```

### Microstructure signal → trade structure

| Microstructure signal | Trade structure |
|---|---|
| Low-volume grind up + vacuum above | Continuation: bull put spread (high IV) / bull call debit (low IV) |
| High-volume parabolic up + retail saturation high | Trim / don't chase / wait for pullback (top signal) |
| High-volume breakdown + vacuum below | Don't bottom-fish; wait for new-level consensus |
| Low-volume chop with vacuums both sides | Iron condor (high IV) / wait for breakout direction (low IV) |
| Retest holds + low volume | Add with trend (vacuum still intact) |
| Retest fails + high volume | Flip to bearish (per Pitfall 4 — flip on invalidation cousin) |

### "Should have moved but didn't" as a fade signal

If a new catalyst hits but price *does not break out* (upside quotes in the orderbook are not getting eaten):
- Either marginal sellers are too thick (institutions distributing into the news) or marginal buyers are too thin (FOMO already spent)
- This is an early top / inflection signal
- More reliable than "rallied less than expected"

---

## When the framework helps

- **Explaining what the tape is doing**: why high volume isn't moving price, why low volume keeps grinding higher, why a retest holds
- **Judging catalyst absorption**: same news produces opposite reactions in different orderbook states
- **Spotting air-pocket entries**: first pullback after a clean breakout = lowest-risk entry
- **Avoiding TA superstition**: "support bounce" or "breakout on volume" without an orderbook explanation is folklore

## When the framework fails or doesn't apply

- **Thin / illiquid small-caps**: orderbook too shallow; single block can fake any signal → use Pitfall 8 (manipulator-tape) instead
- **0DTE-dominated names (SPX, QQQ)**: dealer gamma + 0DTE flow swamp natural orderbook → use dealer GEX analysis
- **Macro shock days (Fed / CPI)**: cross-asset flow overrides single-name microstructure
- **Ultra-low float / high short interest**: gamma-squeeze / short-squeeze dynamics run independently

---

## Cross-References

- Pitfall 8 — manipulator-tape (when the orderbook itself is unreliable)
- Pitfall 9 — float saturation (Primitive 8 operationalized)
- Pitfall 4 — flip on invalidation cousin (don't get attached when consensus shifts)
- `references/frameworks_behavioral.md` — Soros reflexivity, Shiller narrative
- Stage 11 (`agents/quant-analyst.md`) — short-term tape reading
- Stage 13 (`agents/alt-data-analyst.md`) — float composition + social saturation
- `scripts/fetch_alternatives.py` — `social_saturation_score`
