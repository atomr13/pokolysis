"""
FastAPI backend for Football Analyst — port 8002.

Routes:
  GET  /competitions
  GET  /matches/{comp_key}/upcoming
  GET  /matches/{comp_key}/recent
  GET  /matches/{comp_key}/live
  GET  /match/{match_id}/preview       body params: home_team_id, away_team_id, comp_key
  POST /match/{match_id}/analyze
  GET  /match/{match_id}/live-stats
  POST /prediction/{pred_id}/result
  GET  /history
"""

import asyncio
import os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load ANTHROPIC_API_KEY from ~/.zshrc if not already in environment
if not os.environ.get("ANTHROPIC_API_KEY"):
    zshrc = os.path.expanduser("~/.zshrc")
    if os.path.exists(zshrc):
        for line in open(zshrc):
            m = re.match(r'export ANTHROPIC_API_KEY=["\']?([^"\']+)["\']?', line.strip())
            if m:
                os.environ["ANTHROPIC_API_KEY"] = m.group(1)
                break

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    init_db,
    save_prediction,
    save_result,
    get_history,
    get_accuracy_stats,
    get_user,
    get_user_stats,
    update_analysis_score,
    get_pending_predictions,
    get_prediction_by_match_id,
)
from sofascore import (
    COMPETITIONS,
    get_upcoming_matches,
    get_recent_matches,
    get_live_matches,
    get_all_live_matches,
    get_live_match_stats,
    get_match_event,
    get_match_incidents,
    get_match_lineups,
    get_team_season_stats,
    get_team_last5,
    get_h2h,
    get_team_injuries,
    get_match_odds,
    get_full_match_stats,
    get_referee_data,
    get_team_goal_timing,
    get_current_season_id,
    _sleep,
)
from ml_engine import calculate_probabilities, calculate_ht_probabilities
from ai_analyst import get_ai_analysis, grade_analysis


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Preview cache — avoids re-fetching the same match within 10 minutes
# ---------------------------------------------------------------------------

_preview_cache: dict = {}   # match_id → {"ts": float, "data": dict}
_CACHE_TTL = 600            # seconds


def _cache_get(match_id: int):
    entry = _preview_cache.get(match_id)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(match_id: int, data: dict):
    _preview_cache[match_id] = {"ts": time.time(), "data": data}


# ---------------------------------------------------------------------------
# Auto result poller — checks every 60s if any pending predictions finished
# ---------------------------------------------------------------------------

def _poll_pending_results():
    """Synchronous worker: runs in a thread every 60s."""
    pending = get_pending_predictions()
    for pred in pending:
        try:
            _sleep()
            event = get_match_event(pred["match_id"])
            if event.get("status_code") != 100:
                continue

            home_score = event.get("home_score") or 0
            away_score = event.get("away_score") or 0
            save_result(pred["id"], home_score, away_score)

            # Only grade if user left notes
            if pred.get("user_notes") and pred["user_notes"].strip():
                actual_outcome = (
                    "home_win" if home_score > away_score
                    else "away_win" if away_score > home_score
                    else "draw"
                )
                try:
                    post_stats = get_live_match_stats(pred["match_id"])
                except Exception:
                    post_stats = {}
                grade = grade_analysis(
                    user_notes        = pred["user_notes"],
                    home_team         = pred["home_team"],
                    away_team         = pred["away_team"],
                    actual_home_score = home_score,
                    actual_away_score = away_score,
                    actual_outcome    = actual_outcome,
                    post_match_stats  = post_stats,
                )
                update_analysis_score(pred["id"], grade["score"])
        except Exception:
            pass  # never crash the poller


async def _auto_result_poller():
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(_poll_pending_results)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Resolve season IDs for any competition that doesn't have one yet (e.g. FA Cup)
    for comp in COMPETITIONS.values():
        if comp["tournament_id"] and comp["season_id"] is None:
            try:
                comp["season_id"] = get_current_season_id(comp["tournament_id"])
                _sleep()
            except Exception:
                pass
    task = asyncio.create_task(_auto_result_poller())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Football Analyst", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    home_team_id:   int
    away_team_id:   int
    home_team:      str
    away_team:      str
    competition_key: str
    match_date:     str | None = None
    user_notes:     str = ""


class ResultRequest(BaseModel):
    home_score: int
    away_score: int


# ---------------------------------------------------------------------------
# Competitions
# ---------------------------------------------------------------------------

@app.get("/competitions")
def list_competitions():
    return [
        {
            "key":    key,
            "name":   _display_name(key),
            "active": comp["tournament_id"] is not None,
        }
        for key, comp in COMPETITIONS.items()
    ]


def _display_name(key):
    return {
        "premier_league":   "Premier League",
        "champions_league": "Champions League",
        "super_lig":        "Süper Lig",
        "fa_cup":           "FA Cup",
        "eliteserien":      "Eliteserien",
        "world_cup_2026":   "World Cup 2026",
    }.get(key, key)


# ---------------------------------------------------------------------------
# Match lists
# ---------------------------------------------------------------------------

@app.get("/matches/live")
def all_live():
    tracked_ids = {
        comp["tournament_id"]
        for comp in COMPETITIONS.values()
        if comp["tournament_id"] is not None
    }
    matches = get_all_live_matches()
    return [m for m in matches if m.get("unique_tournament_id") in tracked_ids]


@app.get("/matches/{comp_key}/upcoming")
def upcoming(comp_key: str, page: int = Query(default=0, ge=0)):
    _require_active(comp_key)
    return get_upcoming_matches(comp_key, page=page)


@app.get("/matches/{comp_key}/recent")
def recent(comp_key: str, page: int = Query(default=0, ge=0)):
    _require_active(comp_key)
    return get_recent_matches(comp_key, page=page)


@app.get("/matches/{comp_key}/live")
def live(comp_key: str):
    _require_active(comp_key)
    return get_live_matches(comp_key)


def _require_active(comp_key: str):
    if comp_key not in COMPETITIONS:
        raise HTTPException(404, f"Unknown competition: {comp_key}")
    if COMPETITIONS[comp_key]["tournament_id"] is None:
        raise HTTPException(400, f"{comp_key} is Coming Soon — no data available yet")


# ---------------------------------------------------------------------------
# Match preview  (all data the frontend needs before user submits notes)
# ---------------------------------------------------------------------------

@app.get("/match/{match_id}/preview")
def match_preview(
    match_id:       int,
    home_team_id:   int = Query(...),
    away_team_id:   int = Query(...),
    competition_key: str = Query(...),
):
    _require_active(competition_key)

    cached = _cache_get(match_id)
    if cached:
        return cached

    comp = COMPETITIONS[competition_key]
    tid, sid = comp["tournament_id"], comp["season_id"]

    # Fetch all 8 endpoints in parallel — drops wall time from ~10s to ~2s
    tasks = {
        "home_season":        lambda: get_team_season_stats(home_team_id, tid, sid),
        "away_season":        lambda: get_team_season_stats(away_team_id, tid, sid),
        "home_last5":         lambda: get_team_last5(home_team_id, tid, sid),
        "away_last5":         lambda: get_team_last5(away_team_id, tid, sid),
        "h2h":                lambda: get_h2h(home_team_id, away_team_id),
        "home_injuries":      lambda: get_team_injuries(match_id, "home"),
        "away_injuries":      lambda: get_team_injuries(match_id, "away"),
        "odds":               lambda: get_match_odds(match_id),
        "home_goal_timing":   lambda: get_team_goal_timing(home_team_id),
        "away_goal_timing":   lambda: get_team_goal_timing(away_team_id),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = None

    data_probs = calculate_probabilities(
        competition_key,
        home_team_id,
        away_team_id,
        home_season  = results["home_season"],
        away_season  = results["away_season"],
        home_last5   = results["home_last5"],
        away_last5   = results["away_last5"],
        h2h_matches  = results["h2h"],
    )

    payload = {**results, "data_probs": data_probs}
    _cache_set(match_id, payload)
    return payload


# ---------------------------------------------------------------------------
# Analyze  (ML model + Claude → dual probabilities → saved prediction)
# ---------------------------------------------------------------------------

@app.post("/match/{match_id}/analyze")
def analyze(match_id: int, body: AnalyzeRequest):
    _require_active(body.competition_key)
    comp = COMPETITIONS[body.competition_key]
    tid, sid = comp["tournament_id"], comp["season_id"]

    # Fetch all data in parallel
    tasks = {
        "home_season":      lambda: get_team_season_stats(body.home_team_id, tid, sid),
        "away_season":      lambda: get_team_season_stats(body.away_team_id, tid, sid),
        "home_last5":       lambda: get_team_last5(body.home_team_id, tid, sid),
        "away_last5":       lambda: get_team_last5(body.away_team_id, tid, sid),
        "h2h":              lambda: get_h2h(body.home_team_id, body.away_team_id),
        "home_injuries":    lambda: get_team_injuries(match_id, "home"),
        "away_injuries":    lambda: get_team_injuries(match_id, "away"),
        "home_goal_timing": lambda: get_team_goal_timing(body.home_team_id),
        "away_goal_timing": lambda: get_team_goal_timing(body.away_team_id),
    }
    fetched = {}
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = {pool.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                fetched[key] = future.result()
            except Exception:
                fetched[key] = None

    home_season   = fetched["home_season"]   or {}
    away_season   = fetched["away_season"]   or {}
    home_last5    = fetched["home_last5"]    or []
    away_last5    = fetched["away_last5"]    or []
    h2h_matches   = fetched["h2h"]           or []
    home_injuries = fetched["home_injuries"] or []
    away_injuries = fetched["away_injuries"] or []

    # Data-only probabilities
    data_probs = calculate_probabilities(
        body.competition_key, body.home_team_id, body.away_team_id,
        home_season=home_season, away_season=away_season,
        home_last5=home_last5,   away_last5=away_last5,
        h2h_matches=h2h_matches,
    )

    # AI-adjusted probabilities
    ai_result = get_ai_analysis(
        home_team         = body.home_team,
        away_team         = body.away_team,
        home_season       = home_season,
        away_season       = away_season,
        home_last5        = home_last5,
        away_last5        = away_last5,
        h2h               = h2h_matches,
        home_injuries     = home_injuries,
        away_injuries     = away_injuries,
        data_probs        = data_probs,
        user_notes        = body.user_notes,
        home_goal_timing  = fetched["home_goal_timing"],
        away_goal_timing  = fetched["away_goal_timing"],
    )

    # Delta — how much the human input shifted each value
    delta = {
        "home_win": round(ai_result["home_win_pct"] - data_probs["home_win_pct"], 1),
        "draw":     round(ai_result["draw_pct"]     - data_probs["draw_pct"],     1),
        "away_win": round(ai_result["away_win_pct"] - data_probs["away_win_pct"], 1),
    }

    # Save prediction (always attributed to user id=1 for now)
    pred_id = save_prediction({
        "match_id":         match_id,
        "competition":      body.competition_key,
        "home_team":        body.home_team,
        "away_team":        body.away_team,
        "match_date":       body.match_date or "",
        "data_home_win":    data_probs["home_win_pct"],
        "data_draw":        data_probs["draw_pct"],
        "data_away_win":    data_probs["away_win_pct"],
        "human_home_win":   ai_result["home_win_pct"],
        "human_draw":       ai_result["draw_pct"],
        "human_away_win":   ai_result["away_win_pct"],
        "user_notes":       body.user_notes,
        "key_battleground": ai_result["key_battleground"],
        "what_to_watch":    ai_result["what_to_watch"],
        "upset_condition":  ai_result["upset_condition"],
        "ai_summary":       ai_result["summary"],
        "user_id":          1,
    })

    return {
        "prediction_id": pred_id,
        "data_only": {
            "home_win_pct": data_probs["home_win_pct"],
            "draw_pct":     data_probs["draw_pct"],
            "away_win_pct": data_probs["away_win_pct"],
            "confidence":   data_probs["confidence"],
        },
        "human_adjusted": {
            "home_win_pct": ai_result["home_win_pct"],
            "draw_pct":     ai_result["draw_pct"],
            "away_win_pct": ai_result["away_win_pct"],
        },
        "delta":           delta,
        "key_battleground": ai_result["key_battleground"],
        "what_to_watch":    ai_result["what_to_watch"],
        "upset_condition":  ai_result["upset_condition"],
        "summary":          ai_result["summary"],
    }


# ---------------------------------------------------------------------------
# Live stats  (polled every 60s by LiveTracker)
# ---------------------------------------------------------------------------

@app.get("/match/{match_id}/live-stats")
def live_stats(match_id: int):
    return get_live_match_stats(match_id)


@app.get("/match/{match_id}/halftime-analysis")
def halftime_analysis(
    match_id:        int,
    home_team_id:    int = Query(...),
    away_team_id:    int = Query(...),
    competition_key: str = Query(...),
    home_ht:         int = Query(...),
    away_ht:         int = Query(...),
):
    _require_active(competition_key)

    # Get first-half live stats for xG correction (best-effort)
    try:
        ht_stats = get_live_match_stats(match_id)
    except Exception:
        ht_stats = {}

    # Get pre-match probabilities from cache or recalculate
    cached = _cache_get(match_id)
    if cached and cached.get("data_probs"):
        pre_probs = cached["data_probs"]
    else:
        comp = COMPETITIONS[competition_key]
        pre_probs = calculate_probabilities(
            competition_key, home_team_id, away_team_id
        )

    ht_result = calculate_ht_probabilities(home_ht, away_ht, pre_probs, ht_stats)

    return {
        "home_ht":    home_ht,
        "away_ht":    away_ht,
        "pre_match":  {
            "home_win_pct": pre_probs["home_win_pct"],
            "draw_pct":     pre_probs["draw_pct"],
            "away_win_pct": pre_probs["away_win_pct"],
        },
        "ht_recalc":      ht_result,
        "delta": {
            "home_win": round(ht_result["home_win_pct"] - pre_probs["home_win_pct"], 1),
            "draw":     round(ht_result["draw_pct"]     - pre_probs["draw_pct"],     1),
            "away_win": round(ht_result["away_win_pct"] - pre_probs["away_win_pct"], 1),
        },
        "first_half_stats": ht_stats,
    }


@app.get("/match/{match_id}/referee")
def referee(
    match_id:     int,
    home_team_id: int = Query(...),
    away_team_id: int = Query(...),
):
    data = get_referee_data(match_id, home_team_id, away_team_id)
    if data is None:
        raise HTTPException(404, "Referee data not available for this match")
    return data


@app.get("/match/{match_id}/stats")
def full_stats(match_id: int):
    try:
        return get_full_match_stats(match_id)
    except Exception:
        raise HTTPException(404, "Stats not available for this match")


@app.get("/match/{match_id}/incidents")
def incidents(match_id: int):
    try:
        return get_match_incidents(match_id)
    except Exception:
        raise HTTPException(404, "Incidents not available")


@app.get("/match/{match_id}/lineups")
def lineups(match_id: int):
    try:
        return get_match_lineups(match_id)
    except Exception:
        raise HTTPException(404, "Lineups not available yet")


# ---------------------------------------------------------------------------
# Log result after a match
# ---------------------------------------------------------------------------

@app.post("/prediction/{pred_id}/result")
def log_result(pred_id: int, body: ResultRequest):
    try:
        result_id = save_result(pred_id, body.home_score, body.away_score)
    except ValueError as e:
        raise HTTPException(404, str(e))

    # Auto-grade the analyst's notes against the actual result
    from database import get_prediction
    pred = get_prediction(pred_id)
    grade_result = None
    if pred and pred.get("user_notes") and pred["user_notes"].strip():
        try:
            # Fetch post-match live stats for richer grading context
            try:
                post_stats = get_live_match_stats(pred["match_id"])
            except Exception:
                post_stats = {}

            if pred["match_id"] > 0:
                actual_outcome = (
                    "home_win" if body.home_score > body.away_score
                    else "away_win" if body.away_score > body.home_score
                    else "draw"
                )
                grade_result = grade_analysis(
                    user_notes        = pred["user_notes"],
                    home_team         = pred["home_team"],
                    away_team         = pred["away_team"],
                    actual_home_score = body.home_score,
                    actual_away_score = body.away_score,
                    actual_outcome    = actual_outcome,
                    post_match_stats  = post_stats,
                )
                update_analysis_score(pred_id, grade_result["score"])
        except Exception as e:
            # Grading failure must not block result logging
            grade_result = {"error": str(e)}

    return {
        "result_id":   result_id,
        "message":     "Result logged",
        "grade":       grade_result,
    }


@app.get("/match/{match_id}/prediction")
def get_saved_prediction(match_id: int):
    return get_prediction_by_match_id(match_id)  # None → null in JSON, that's fine


@app.get("/user/{user_id}")
def user_profile(user_id: int):
    user = get_user(user_id)
    if not user:
        raise HTTPException(404, f"User {user_id} not found")
    stats = get_user_stats(user_id)
    return {**user, **stats}


# ---------------------------------------------------------------------------
# Prediction history + accuracy
# ---------------------------------------------------------------------------

@app.get("/history")
def history():
    return {
        "predictions": get_history(),
        "accuracy":    get_accuracy_stats(),
    }


# ---------------------------------------------------------------------------
# Run  (python main.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
