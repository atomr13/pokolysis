"""
Weighted probability model — no ML library, pure formula.

Weights (must sum to 1.0):
  22%  Season points per game
  18%  Season goal difference per game  (approximated from goals when xG unavailable)
  18%  Last-5 form points per game      (recency-weighted: 1.0 / 0.85 / 0.70 / 0.55 / 0.40)
  12%  Last-5 xG difference             (same recency weighting)
  10%  Home/away base advantage
  10%  H2H record (last 10, decay by seasons ago)
   6%  Shots on target per game
   4%  Big chances created

Phase 1 improvements applied:
  - H2H recency decay (older seasons weighted down, >3 seasons dropped)
  - Last-5 recency weighting (most recent game counts most)
  - Dynamic draw baseline (low-scoring matchups push draw probability up)
  - Injury penalty (missing players reduce team score by position weight)
"""

import datetime

from sofascore import (
    COMPETITIONS,
    get_team_season_stats,
    get_team_last5,
    get_h2h,
    get_team_injuries,
    _sleep,
)

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

W_SEASON_PPG  = 0.22
W_SEASON_XGD  = 0.18
W_FORM_PPG    = 0.18
W_FORM_XGD    = 0.12
W_HOME_ADV    = 0.10
W_H2H         = 0.10
W_SOT_PG      = 0.06
W_BIG_CHANCES = 0.04

# Home/away base advantage (reflects ~47% home win rate in top leagues)
HOME_ADV_SCORE = 0.60
AWAY_ADV_SCORE = 0.40

# Historical baseline W/D/L rates used as the starting point
BASE_HOME_WIN = 0.45
BASE_DRAW     = 0.25
BASE_AWAY_WIN = 0.30

# Recency weights for last-5 matches (index 0 = most recent)
LAST5_WEIGHTS = [1.0, 0.85, 0.70, 0.55, 0.40]

# H2H decay by seasons ago — results older than 3 seasons are dropped
H2H_DECAY = {0: 1.0, 1: 0.70, 2: 0.40, 3: 0.10}

# Injury penalty by position (sum capped at 0.20)
INJURY_POSITION_WEIGHT = {
    "goalkeeper": 0.08,
    "forward":    0.07,
    "striker":    0.07,
    "attacking":  0.05,  # attacking midfielder
    "midfielder": 0.04,
    "defender":   0.03,
    "winger":     0.02,
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm_ppg(ppg):
    """Points per game 0–3 → 0–1."""
    if ppg is None:
        return None
    return max(0.0, min(1.0, ppg / 3.0))


def _norm_xgd(xgd_per_game):
    """xG difference per game (roughly −2 to +2) → 0–1."""
    if xgd_per_game is None:
        return None
    return max(0.0, min(1.0, (xgd_per_game + 2.0) / 4.0))


def _norm_sot_pg(sot_pg):
    """Shots on target per game (0–8 typical range) → 0–1."""
    if sot_pg is None:
        return None
    return max(0.0, min(1.0, sot_pg / 8.0))


def _norm_big_chances(bc, played):
    """Big chances per game (0–4 typical range) → 0–1."""
    if bc is None or not played:
        return None
    return max(0.0, min(1.0, (bc / played) / 4.0))


def _norm_h2h(wins, total):
    """Win rate in H2H → 0–1. Returns 0.5 (neutral) when no history."""
    if not total:
        return 0.5
    return wins / total


def _parse_float(value):
    """Sofascore returns some stats as strings like '1.25%' or '59%'."""
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Phase 1 helpers
# ---------------------------------------------------------------------------

def _seasons_ago(timestamp):
    """Returns how many seasons ago a match was played. Season starts in July."""
    if not timestamp:
        return 99
    match_dt = datetime.datetime.fromtimestamp(timestamp)
    now = datetime.datetime.now()
    current_season = now.year if now.month >= 7 else now.year - 1
    match_season   = match_dt.year if match_dt.month >= 7 else match_dt.year - 1
    return max(0, current_season - match_season)


def _injury_penalty(injuries):
    """
    Returns a score reduction in [0, 0.20] based on missing players.
    Matches position strings case-insensitively by substring.
    """
    if not injuries:
        return 0.0
    penalty = 0.0
    for player in injuries:
        pos = (player.get("position") or "").lower()
        weight = 0.03  # default for unknown position
        for keyword, w in INJURY_POSITION_WEIGHT.items():
            if keyword in pos:
                weight = w
                break
        penalty += weight
    return min(0.20, penalty)


def _draw_baseline(home_goals_pg, away_goals_pg):
    """
    Low-scoring matchups produce more draws.
    Returns a draw baseline in range [0.25, 0.35].
    """
    avg_goals = (home_goals_pg + away_goals_pg) / 2
    draw_pressure = max(0.0, (2.5 - avg_goals) / 2.5)  # 0 → 1
    return BASE_DRAW + (draw_pressure * 0.10)


# ---------------------------------------------------------------------------
# Per-team score builder
# ---------------------------------------------------------------------------

def _team_score(season_stats, last5, h2h_score, is_home, injury_penalty=0.0):
    """
    Returns a dict with each factor's normalised score (0–1) and a weighted total.
    None values mean that factor had no data and was skipped (weight redistributed).
    """
    factors = {}

    # --- Season PPG ---
    ppg = season_stats.get("points_per_game")
    factors["season_ppg"] = _norm_ppg(ppg)

    # --- Season xGD per game (approx from goals) ---
    played = season_stats.get("matches_played") or 1
    gf = season_stats.get("goals_scored") or 0
    ga = season_stats.get("goals_conceded") or 0
    gd_per_game = (gf - ga) / played
    factors["season_xgd"] = _norm_xgd(gd_per_game)

    # --- Last-5 form PPG — recency weighted ---
    if last5:
        result_pts = {"W": 3, "D": 1, "L": 0}
        weights = LAST5_WEIGHTS[:len(last5)]
        w_sum = sum(weights)
        form_ppg = sum(result_pts.get(m["result"], 0) * w
                       for m, w in zip(last5, weights)) / w_sum
        factors["form_ppg"] = _norm_ppg(form_ppg)
    else:
        factors["form_ppg"] = None

    # --- Last-5 xGD — recency weighted ---
    if last5:
        xgd_vals, xgd_weights = [], []
        for i, m in enumerate(last5):
            xg  = _parse_float(m.get("xg"))
            xga = _parse_float(m.get("xga"))
            if xg is not None and xga is not None:
                xgd_vals.append(xg - xga)
                xgd_weights.append(LAST5_WEIGHTS[i])
        if xgd_vals:
            w_sum = sum(xgd_weights)
            avg_xgd = sum(v * w for v, w in zip(xgd_vals, xgd_weights)) / w_sum
            factors["form_xgd"] = _norm_xgd(avg_xgd)
        else:
            factors["form_xgd"] = None
    else:
        factors["form_xgd"] = None

    # --- Shots on target per game ---
    factors["sot_pg"] = _norm_sot_pg(season_stats.get("sot_per_game"))

    # --- Big chances created per game ---
    factors["big_chances"] = _norm_big_chances(
        season_stats.get("big_chances_created"),
        season_stats.get("matches_played") or 1,
    )

    # --- Home/away base advantage ---
    factors["home_adv"] = HOME_ADV_SCORE if is_home else AWAY_ADV_SCORE

    # --- H2H ---
    factors["h2h"] = h2h_score

    # --- Weighted total (redistribute weight from missing factors) ---
    weight_map = {
        "season_ppg":  W_SEASON_PPG,
        "season_xgd":  W_SEASON_XGD,
        "form_ppg":    W_FORM_PPG,
        "form_xgd":    W_FORM_XGD,
        "home_adv":    W_HOME_ADV,
        "h2h":         W_H2H,
        "sot_pg":      W_SOT_PG,
        "big_chances": W_BIG_CHANCES,
    }

    available = {k: v for k, v in factors.items() if v is not None}
    available_weight = sum(weight_map[k] for k in available)

    if available_weight == 0:
        total = 0.5
    else:
        total = sum(
            factors[k] * (weight_map[k] / available_weight)
            for k in available
        )

    # Apply injury penalty as a downward multiplier
    if injury_penalty > 0:
        total = max(0.0, total * (1 - injury_penalty))

    return {"factors": factors, "total": total}


# ---------------------------------------------------------------------------
# Confidence level
# ---------------------------------------------------------------------------

def _confidence(home_data, away_data):
    all_factors = ["season_ppg", "season_xgd", "form_ppg", "form_xgd",
                   "home_adv", "h2h", "sot_pg", "big_chances"]
    present = sum(
        1 for k in all_factors
        if home_data["factors"].get(k) is not None
        and away_data["factors"].get(k) is not None
    )
    if present >= 7:
        return "high"
    if present >= 5:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Halftime recalculation
# ---------------------------------------------------------------------------

# Historical FT result probabilities given HT score (top European leagues)
# Tuple: (home_win, draw, away_win)
_HT_CONDITIONALS = {
    (0, 0): (0.35, 0.38, 0.27),
    (1, 0): (0.72, 0.16, 0.12),
    (0, 1): (0.12, 0.16, 0.72),
    (1, 1): (0.35, 0.38, 0.27),
    (2, 0): (0.88, 0.08, 0.04),
    (0, 2): (0.04, 0.08, 0.88),
    (2, 1): (0.78, 0.14, 0.08),
    (1, 2): (0.08, 0.14, 0.78),
    (2, 2): (0.36, 0.38, 0.26),
    (3, 0): (0.95, 0.04, 0.01),
    (0, 3): (0.01, 0.04, 0.95),
    (3, 1): (0.91, 0.06, 0.03),
    (1, 3): (0.03, 0.06, 0.91),
    (3, 2): (0.80, 0.12, 0.08),
    (2, 3): (0.08, 0.12, 0.80),
}


def _ht_lookup(home_ht, away_ht):
    """Return HT conditional probs, extrapolating for scores outside the table."""
    key = (home_ht, away_ht)
    if key in _HT_CONDITIONALS:
        return _HT_CONDITIONALS[key]
    # For large leads clamp to the most extreme entry
    diff = home_ht - away_ht
    if diff >= 3:
        return (0.97, 0.02, 0.01)
    if diff <= -3:
        return (0.01, 0.02, 0.97)
    # High-scoring draws (3-3, 4-4 etc) — treat like 0-0 dynamics
    if diff == 0:
        return (0.35, 0.38, 0.27)
    # Fallback: proportional to diff
    if diff == 2:
        return (0.88, 0.08, 0.04)
    if diff == -2:
        return (0.04, 0.08, 0.88)
    return (0.50, 0.25, 0.25)


def calculate_ht_probabilities(home_ht, away_ht, pre_probs, ht_stats=None):
    """
    Blends historical HT-conditional rates with pre-match quality,
    then applies an optional xG correction from first-half stats.

    pre_probs: dict with home_win_pct, draw_pct, away_win_pct
    ht_stats:  dict from get_live_match_stats (may be None)

    Returns dict: home_win_pct, draw_pct, away_win_pct, method, xg_correction
    """
    ht_hw, ht_draw, ht_aw = _ht_lookup(home_ht, away_ht)

    pre_hw   = (pre_probs.get("home_win_pct") or 45) / 100
    pre_draw = (pre_probs.get("draw_pct")     or 25) / 100
    pre_aw   = (pre_probs.get("away_win_pct") or 30) / 100

    # Blend: 60% HT conditional state, 40% pre-match team quality
    HT_WEIGHT = 0.60
    blended_hw   = HT_WEIGHT * ht_hw   + (1 - HT_WEIGHT) * pre_hw
    blended_draw = HT_WEIGHT * ht_draw + (1 - HT_WEIGHT) * pre_draw
    blended_aw   = HT_WEIGHT * ht_aw   + (1 - HT_WEIGHT) * pre_aw

    # xG correction: if first-half xG diverges from the score, adjust up to ±5%
    xg_correction = 0.0
    if ht_stats:
        try:
            home_xg = float(str(ht_stats.get("expected_goals", {}).get("home") or 0).replace("%", ""))
            away_xg = float(str(ht_stats.get("expected_goals", {}).get("away") or 0).replace("%", ""))
            if home_xg > 0 or away_xg > 0:
                xg_diff    = home_xg - away_xg
                score_diff = home_ht - away_ht
                divergence = xg_diff - score_diff   # positive = home "deserved" more
                xg_correction = max(-0.05, min(0.05, divergence * 0.03))
                blended_hw += xg_correction
                blended_aw -= xg_correction
        except (ValueError, TypeError):
            pass

    # Normalise to sum to 1
    total = blended_hw + blended_draw + blended_aw
    blended_hw   /= total
    blended_draw /= total
    blended_aw   /= total

    return {
        "home_win_pct": round(blended_hw * 100, 1),
        "draw_pct":     round(blended_draw * 100, 1),
        "away_win_pct": round(blended_aw * 100, 1),
        "ht_conditional": {
            "home_win_pct": round(ht_hw * 100, 1),
            "draw_pct":     round(ht_draw * 100, 1),
            "away_win_pct": round(ht_aw * 100, 1),
        },
        "xg_correction": round(xg_correction * 100, 1),
    }


# ---------------------------------------------------------------------------
# Score → probability conversion
# ---------------------------------------------------------------------------

def _scores_to_probabilities(home_total, away_total, draw_base=BASE_DRAW):
    """
    Converts two 0–1 team scores into W/D/L percentages.
    draw_base is computed dynamically from goals-per-game data.
    """
    delta = home_total - away_total  # positive = home stronger
    shift = delta * 0.50

    home_win = BASE_HOME_WIN + shift
    away_win = BASE_AWAY_WIN - shift
    draw     = draw_base

    home_win = max(0.05, min(0.88, home_win))
    away_win = max(0.05, min(0.88, away_win))
    draw     = max(0.05, min(0.40, draw))

    total = home_win + draw + away_win
    home_win /= total
    draw     /= total
    away_win /= total

    return round(home_win * 100, 1), round(draw * 100, 1), round(away_win * 100, 1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate_probabilities(
    competition_key,
    home_team_id,
    away_team_id,
    match_id=None,
    # Optional pre-fetched data — pass these to skip redundant Sofascore calls
    home_season=None,
    away_season=None,
    home_last5=None,
    away_last5=None,
    h2h_matches=None,
):
    """
    Returns data-only probabilities. Fetches from Sofascore unless pre-fetched
    data is supplied (pass all five to avoid redundant API calls).
    """
    comp = COMPETITIONS[competition_key]
    tid  = comp["tournament_id"]
    sid  = comp["season_id"]

    if tid is None:
        raise ValueError(f"{competition_key} is not yet available")

    # --- Fetch data only if not supplied ---
    if home_season is None:
        home_season = get_team_season_stats(home_team_id, tid, sid); _sleep()
    if away_season is None:
        away_season = get_team_season_stats(away_team_id, tid, sid); _sleep()
    if home_last5 is None:
        home_last5 = get_team_last5(home_team_id, tid, sid); _sleep()
    if away_last5 is None:
        away_last5 = get_team_last5(away_team_id, tid, sid); _sleep()
    if h2h_matches is None:
        h2h_matches = get_h2h(home_team_id, away_team_id)

    # --- H2H score with recency decay ---
    home_wins_w = 0.0
    total_w     = 0.0
    for m in h2h_matches:
        decay = H2H_DECAY.get(_seasons_ago(m.get("date")), 0.0)
        if decay == 0.0:
            continue
        total_w += decay
        home_won = (
            (m["winner"] == "home" and m.get("home_team_id") == home_team_id) or
            (m["winner"] == "away" and m.get("away_team_id") == home_team_id)
        )
        if home_won:
            home_wins_w += decay

    home_h2h_score = (home_wins_w / total_w) if total_w else 0.5
    away_h2h_score = ((total_w - home_wins_w) / total_w) if total_w else 0.5

    # --- Injury penalties (only when match_id is known) ---
    home_injury_penalty = 0.0
    away_injury_penalty = 0.0
    if match_id:
        try:
            _sleep()
            home_injuries = get_team_injuries(match_id, "home")
            _sleep()
            away_injuries = get_team_injuries(match_id, "away")
            home_injury_penalty = _injury_penalty(home_injuries)
            away_injury_penalty = _injury_penalty(away_injuries)
        except Exception:
            pass  # injuries are best-effort — never block the prediction

    # --- Dynamic draw baseline from goals per game ---
    home_gpg = (home_season.get("goals_scored") or 0) / (home_season.get("matches_played") or 1)
    away_gpg = (away_season.get("goals_scored") or 0) / (away_season.get("matches_played") or 1)
    draw_base = _draw_baseline(home_gpg, away_gpg)

    # --- Build team scores ---
    home_data = _team_score(home_season, home_last5, home_h2h_score,
                            is_home=True,  injury_penalty=home_injury_penalty)
    away_data = _team_score(away_season, away_last5, away_h2h_score,
                            is_home=False, injury_penalty=away_injury_penalty)

    home_win_pct, draw_pct, away_win_pct = _scores_to_probabilities(
        home_data["total"], away_data["total"], draw_base=draw_base
    )

    return {
        "home_win_pct": home_win_pct,
        "draw_pct":     draw_pct,
        "away_win_pct": away_win_pct,
        "confidence":   _confidence(home_data, away_data),
        "factors": {
            "home": home_data["factors"],
            "away": away_data["factors"],
        },
    }


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from sofascore import get_upcoming_matches

    print("Fetching an upcoming Premier League match...")
    upcoming = get_upcoming_matches("premier_league")
    match = upcoming[0]
    print(f"  {match['home_team']} vs {match['away_team']}")
    print()

    print("Running probability model...")
    result = calculate_probabilities(
        competition_key="premier_league",
        home_team_id=match["home_team_id"],
        away_team_id=match["away_team_id"],
        match_id=match["match_id"],
    )

    print(json.dumps(result, indent=2))
    total = result["home_win_pct"] + result["draw_pct"] + result["away_win_pct"]
    print(f"\nSum check: {total}%  (should be 100.0)")
