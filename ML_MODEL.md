# How the Probability Model Works

The model is a **weighted scoring formula** — no machine learning library, no training data. It takes stats from Sofascore, normalises each one to a 0–1 scale, combines them with fixed weights, then converts the resulting scores into win/draw/loss percentages.

---

## Step 1 — Fetch the Data

For each match the model collects:

| Data | Source |
|---|---|
| Season standings (W/D/L, points, position) | Sofascore standings endpoint |
| Season attack stats (goals, shots on target, big chances) | Sofascore team stats endpoint |
| Last 5 matches in that competition | Recent events endpoint |
| Per-match xG/xGA from those 5 games | Match statistics endpoint |
| Head-to-head record (last 10 meetings) | Team event history |
| Injured/missing players for both sides | Match lineups endpoint (when match_id known) |

---

## Step 2 — Normalise Each Factor to 0–1

Every raw number is scaled so factors are directly comparable regardless of unit.

| Factor | Raw range | Formula |
|---|---|---|
| Points per game (PPG) | 0–3 | `ppg / 3.0` |
| Goal difference per game | ~−2 to +2 | `(gd + 2.0) / 4.0` |
| Last-5 PPG | 0–3 | `ppg / 3.0` |
| Last-5 xG difference | ~−2 to +2 | `(xgd + 2.0) / 4.0` |
| Shots on target per game | 0–8 | `sot / 8.0` |
| Big chances created per game | 0–4 | `(bc / played) / 4.0` |
| Home/away base | fixed | Home = 0.60, Away = 0.40 |
| H2H win rate | 0–1 | weighted wins / weighted total |

All values are clamped to `[0.0, 1.0]` after the formula.

> **xG fallback:** If Sofascore doesn't return xG data for a match, the model uses actual goal difference instead. This is less precise but keeps the factor populated.

---

## Step 3 — Weighted Sum

Each normalised factor is multiplied by its weight, then summed. If a factor has no data (e.g. a team with no last-5 matches in that competition), its weight is redistributed proportionally across the remaining factors rather than zeroed out.

| Factor | Weight | Reasoning |
|---|---|---|
| Season PPG | **22%** | Most reliable single measure of team quality |
| Season goal difference/game | **18%** | Captures attack + defence balance over many games |
| Last-5 form PPG | **18%** | Recent momentum — form swings matter in football |
| Last-5 xG difference | **12%** | Quality-adjusted form, less luck-dependent than goals |
| Home/away base | **10%** | ~47% home win rate in top leagues is a real, persistent edge |
| H2H record | **10%** | Some matchups have strong historical patterns |
| Shots on target/game | **6%** | Attack effectiveness proxy |
| Big chances created/game | **4%** | Shot quality, not just volume |
| **Total** | **100%** | |

### Recency weighting within last-5

Rather than treating all 5 games equally, the most recent match counts most:

| Game | Weight |
|---|---|
| Most recent | 1.00 |
| 2nd most recent | 0.85 |
| 3rd | 0.70 |
| 4th | 0.55 |
| 5th (oldest) | 0.40 |

This applies to both form PPG and form xGD. For xGD, the weights are re-normalised to whichever games actually had xG data available.

### Injury penalty

If a match_id is known, the model fetches missing players for both sides and applies a downward multiplier to the team score based on position:

| Position | Penalty |
|---|---|
| Goalkeeper | 8% |
| Forward / Striker | 7% |
| Attacking Midfielder | 5% |
| Midfielder | 4% |
| Defender | 3% |
| Winger | 2% |

Penalties are summed and capped at a maximum 20% reduction. The multiplier is `team_score × (1 − penalty)`.

This produces a single **team score** between 0 and 1 for home and away.

---

## Step 4 — Convert Scores to Probabilities

The two team scores are compared to produce a **strength delta**:

```
delta = home_score − away_score   (range: −1 to +1)
```

This delta shifts the **historical baseline rates** for top European leagues:

| Outcome | Baseline |
|---|---|
| Home win | 45% |
| Draw | 25% (dynamic — see below) |
| Away win | 30% |

The shift is linear: each 0.1 delta = ~5 percentage points.

```
home_win = 0.45 + (delta × 0.50)
away_win = 0.30 − (delta × 0.50)
draw     = draw_baseline  (computed dynamically)
```

### Dynamic draw baseline

Low-scoring matchups produce more draws. The draw baseline is adjusted based on both teams' average goals per game:

```
avg_goals     = (home_goals_pg + away_goals_pg) / 2
draw_pressure = max(0, (2.5 − avg_goals) / 2.5)   # 0 → 1
draw_baseline = 0.25 + (draw_pressure × 0.10)      # 25% → 35%
```

A match between two defensive teams averaging 0.8 goals each gets a draw baseline of ~35%. A match between two high-scoring teams gets ~25%.

After shifting, all three are clamped to sensible minimums/maximums (5%–88% for wins, 5%–40% for draws), then re-normalised so they always sum to exactly 100%.

---

## Step 5 — H2H Recency Decay

Not all head-to-head results carry equal weight. Squads change; a result from 5 years ago means little. The model applies a decay based on how many seasons ago a match was played (seasons start in July):

| Seasons ago | Weight |
|---|---|
| Current season | 1.00 |
| 1 season ago | 0.70 |
| 2 seasons ago | 0.40 |
| 3 seasons ago | 0.10 |
| 4+ seasons ago | dropped |

The H2H score is computed as `weighted_wins / weighted_total` rather than a flat win rate.

---

## Step 6 — Confidence Level

Confidence tells you how complete the data was.

| Level | Condition |
|---|---|
| **High** | 7 or 8 of 8 factors had data for both teams |
| **Medium** | 5 or 6 of 8 factors had data |
| **Low** | Fewer than 5 factors had data |

Low confidence usually means a team is new to the competition (early in the season) or xG data is unavailable.

---

## Known Limitations & Planned Improvements

- **Draw probability is better but still approximate.** The dynamic baseline helps, but a fully separate draw model based on both teams' defensive records would be more accurate.

- **Weights were set manually.** They reflect general football intuition, not data-fitted coefficients. Phase 3 (50+ predictions) will introduce a grid search backtester to tune them against real results.

- **H2H ignores competition context.** A cup result counts the same as a league result. Filtering by competition type would improve signal.

- **No score-line prediction.** Phase 2 (20+ predictions) will add a Poisson model for most-likely scorelines and over/under probabilities.

- **Competition-specific baselines.** The 45/25/30 baseline is a top-league average. Süper Lig has higher home advantage; Champions League has different draw rates. Phase 4 (100+ predictions) will split these.
