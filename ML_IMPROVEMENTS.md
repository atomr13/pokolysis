# ML Model — Improvements & Self-Training Roadmap

## Philosophy

The model launches as a formula. It evolves into something smarter.
Every prediction logged + every result recorded is a data point the model can learn from.
By World Cup 2026, it should be meaningfully more accurate than day one.

---

## Phase 1 — Quick Wins (Launch → First 20 Predictions)

These are code-level fixes that don't require historical data. Do these before launch.

### 1.1 Recency Decay on H2H
Results from 6 years ago reflect different squads entirely. Weight them down.

```python
# Current: all H2H results count equally
# Fix: apply decay by season distance
weights = {0: 1.0, 1: 0.70, 2: 0.40, 3: 0.10}  # seasons ago
# Results older than 3 seasons: drop entirely
```

### 1.2 Recency Weighting Within Last-5
The most recent game matters more than one from 6 weeks ago.

```python
# Current: all 5 games weighted equally
# Fix: most recent = 1.0, then 0.85, 0.70, 0.55, 0.40
last5_weights = [1.0, 0.85, 0.70, 0.55, 0.40]  # index 0 = most recent
```

### 1.3 Better Draw Model
The biggest structural flaw. Draw is currently fixed at 25% baseline and only moves with the overall delta. Draws are actually driven by defensive caution on both sides.

```python
# Add a draw pressure factor
avg_goals_per_game = (home_goals_pg + away_goals_pg) / 2

# Low-scoring games = more draw pressure
# High-scoring games = draw less likely
draw_pressure = max(0, (2.5 - avg_goals_per_game) / 2.5)  # 0 to 1

# Blend into draw baseline
draw_baseline = 0.25 + (draw_pressure * 0.10)  # can push draw up to ~35%
```

### 1.4 Injuries Into the Model
Data is already fetched from Sofascore but not used. Add a simple penalty.

```python
# Assign importance by position
POSITION_WEIGHT = {
    "goalkeeper": 0.08,
    "striker": 0.07,
    "attacking_midfielder": 0.05,
    "central_midfielder": 0.04,
    "defender": 0.03,
    "winger": 0.02,
}

# Sum penalties for injured/suspended players
# Apply as a downward multiplier to team score
team_score *= (1 - injury_penalty)  # capped at max 0.20 reduction
```

---

## Phase 2 — Score Prediction (20–50 Predictions)

Add a Poisson-based scoreline model alongside W/D/L probabilities.

### How It Works

1. Take each team's expected goals per game from season xG data
2. Adjust for opponent defensive strength (xGA/game)
3. Model goals scored as a Poisson distribution
4. Compute probability of every scoreline from 0-0 to 5-5
5. Sum scoreline probabilities to get W/D/L (cross-check against formula model)

```python
import math

def poisson_prob(lam, k):
    return (lam**k * math.exp(-lam)) / math.factorial(k)

def score_probabilities(home_xg, away_xg, max_goals=5):
    grid = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            grid[(h, a)] = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
    return grid
```

### New Output Fields
```python
{
  "most_likely_score": "1-1",
  "top_3_scorelines": [("1-1", 12.3), ("1-0", 10.1), ("2-1", 9.4)],
  "over_2_5_goals": 54.2,    # % chance of 3+ goals
  "both_teams_score": 61.0,  # % chance both teams score
}
```

---

## Phase 3 — Self-Training Loop (50+ Predictions)

This is where the model starts evolving. Every logged result teaches it something.

### What Gets Stored Per Prediction

Already in the SQLite schema:
- `data_home_win`, `data_draw`, `data_away_win` — what the model predicted
- `actual_outcome` — what actually happened
- `data_correct` — whether the model was right

We add one more table:

```sql
CREATE TABLE model_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_date TEXT,
  weight_season_ppg REAL,
  weight_season_gd REAL,
  weight_last5_ppg REAL,
  weight_last5_xgd REAL,
  weight_home_away REAL,
  weight_h2h REAL,
  weight_shots_ot REAL,
  weight_big_chances REAL,
  predictions_used INTEGER,   -- how many predictions this was trained on
  accuracy REAL,              -- overall accuracy at time of snapshot
  notes TEXT
);
```

### The Training Loop

Run this after every 10 new results are logged. It doesn't use ML libraries — just a grid search over weight combinations.

```python
# backtester.py

def backtest(weights, predictions):
    """
    Given a set of weights and historical predictions,
    recalculate what the model would have predicted,
    return accuracy vs actual outcomes.
    """
    correct = 0
    for pred in predictions:
        recalculated = run_model(pred["input_stats"], weights)
        if recalculated["predicted_outcome"] == pred["actual_outcome"]:
            correct += 1
    return correct / len(predictions)

def grid_search(predictions, current_weights, step=0.02):
    """
    Try small variations of each weight,
    keep changes that improve accuracy.
    Runs after every 10 new results.
    """
    best_weights = current_weights.copy()
    best_accuracy = backtest(current_weights, predictions)

    for factor in current_weights:
        for delta in [-step, +step]:
            candidate = current_weights.copy()
            candidate[factor] += delta
            # Re-normalise so weights still sum to 1.0
            total = sum(candidate.values())
            candidate = {k: v / total for k, v in candidate.items()}

            acc = backtest(candidate, predictions)
            if acc > best_accuracy:
                best_accuracy = acc
                best_weights = candidate

    return best_weights, best_accuracy
```

### Training Schedule

| Predictions logged | Action |
|---|---|
| 10 | First backtest — baseline accuracy established |
| 20 | First weight adjustment — small shifts allowed |
| 50 | Second adjustment — draw model parameters tuned |
| 100 | Full grid search — all weights and draw model together |
| 200+ | Consider replacing grid search with gradient descent |

### What the Model Learns Over Time

- Which factors actually predict outcomes in the competitions you track
- Whether H2H matters more or less than you assumed
- Whether your home advantage baseline (10%) is right for Süper Lig vs Premier League
- Whether the draw model needs different baselines per competition

---

## Phase 4 — Competition-Specific Models (100+ Predictions)

Not all competitions play the same. A single set of weights will underfit.

| Competition | Known characteristics |
|---|---|
| Premier League | High intensity, fewer draws than average, home advantage ~47% |
| Champions League | Knockout pressure distorts form, away goals matter psychologically |
| Turkish Süper Lig | Higher variance, stronger home advantage, form less predictive |

At 100+ predictions across all three, split the model:
- Train separate weight sets per competition
- Compare accuracy per competition to see where the model struggles most

---

## Phase 5 — Human Input Calibration (Ongoing)

Your manual notes shift the probabilities. Over time, track whether your adjustments help or hurt.

```sql
-- Add to results table
human_delta_helped INTEGER  -- 1 if human-adjusted was closer to actual, 0 if data-only was closer
```

After 50 predictions you'll know:
- Which types of observations you make that actually improve accuracy
- Whether you're systematically biased (always backing home teams, underrating draws)
- Which competitions your instinct adds most value in

This feedback loop is what makes the human input layer scientifically useful rather than just a feeling.

---

## Accuracy Targets

Realistic expectations based on how difficult football is to predict:

| Stage | Target accuracy (W/D/L) | Notes |
|---|---|---|
| Launch (formula only) | 48–52% | Baseline for top league prediction models |
| After Phase 1 fixes | 52–55% | Draw model + injuries make the difference |
| After 50 predictions + tuning | 55–58% | Weight optimisation kicking in |
| After 100+ predictions | 58–62% | Competition-specific models |
| Long term ceiling | ~65% | Roughly where professional models sit |

> Anything above 60% sustained accuracy on W/D/L is genuinely good.
> Draw prediction is hardest — professional models rarely exceed 30% accuracy on draws alone.

---

## What to Build First

```
Phase 1 fixes       → before launch, no data needed
Score prediction    → after 20 predictions, adds new output layer
backtester.py       → after 50 predictions, first real self-improvement
Competition split   → after 100 predictions
Human calibration   → runs passively from day one, reviewed at 50
```

The model doesn't need to be perfect at launch.
It needs to be honest, logged, and improving.
```
