"""
ai_analyst.py — Claude API integration for tactical analysis.

Takes the data-only ML probabilities plus user notes and returns
human-adjusted probabilities with tactical breakdown.

Output format:
{
    "home_win_pct":    49.0,
    "draw_pct":        25.0,
    "away_win_pct":    26.0,
    "key_battleground": "...",
    "what_to_watch":   "...",
    "upset_condition": "...",
    "summary":         "..."
}
"""

import json
import re
import anthropic

MODEL = "claude-opus-4-7"

# ---------------------------------------------------------------------------
# System prompt (cached — keep it stable, don't put variable data here)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a professional football analyst. Your job is to take structured match data \
and a human analyst's free-text observations, then produce adjusted match outcome probabilities \
plus a concise tactical breakdown.

Rules you must follow:
1. Always return valid JSON — no markdown fences, no extra commentary.
2. The three probability fields (home_win_pct, draw_pct, away_win_pct) must sum to exactly 100.0.
3. Use the data-only probabilities as your starting point — only shift them when the human notes \
   or tactical context gives you genuine reason to.
4. Keep each text field under 2 sentences. Be specific and precise, not generic.
5. If the user's notes are empty or uninformative, return probabilities very close to the data model.
6. Use the GOAL TIMING section to inform your tactical analysis: if one team scores heavily in a \
   half where the other concedes heavily, flag this as a key matchup dynamic. Timing mismatches \
   (e.g. a strong 2H scoring team vs a weak 2H defensive team) can justify a small probability \
   shift and should be surfaced in key_battleground or what_to_watch.

Return this exact JSON shape:
{
  "home_win_pct":    <float>,
  "draw_pct":        <float>,
  "away_win_pct":    <float>,
  "key_battleground": "<string>",
  "what_to_watch":   "<string>",
  "upset_condition": "<string>",
  "summary":         "<string>"
}"""


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _format_season_stats(label, stats):
    if not stats:
        return f"{label}: no season data available"
    pts   = stats.get("points_per_game", "?")
    played = stats.get("matches_played", "?")
    gf    = stats.get("goals_scored", "?")
    ga    = stats.get("goals_conceded", "?")
    ppg   = f"{pts:.2f}" if isinstance(pts, float) else pts
    return (
        f"{label}: {played} played | "
        f"PPG {ppg} | "
        f"Goals {gf}–{ga} | "
        f"W{stats.get('wins','?')} D{stats.get('draws','?')} L{stats.get('losses','?')}"
    )


def _format_last5(label, matches):
    if not matches:
        return f"{label} last 5: no data"
    lines = [f"{label} last 5:"]
    for m in matches:
        try:
            xg  = float(m.get("xg"))  if m.get("xg")  is not None else None
            xga = float(m.get("xga")) if m.get("xga") is not None else None
        except (ValueError, TypeError):
            xg, xga = None, None
        xg_str = f" (xG {xg:.2f}–{xga:.2f})" if xg is not None and xga is not None else ""
        lines.append(f"  {m['result']} {m['score']} vs {m['opponent']} ({m['home_away']}){xg_str}")
    return "\n".join(lines)


def _format_h2h(matches):
    if not matches:
        return "H2H: no history found"
    lines = ["H2H (last 10):"]
    for m in matches[:10]:
        lines.append(f"  {m['home_team']} {m['score']} {m['away_team']} → {m['winner']}")
    return "\n".join(lines)


def _format_goal_timing(label, timing):
    if not timing:
        return f"{label} goal timing: no data"
    sp1 = timing.get("scored_p1_avg", 0)
    sp2 = timing.get("scored_p2_avg", 0)
    cp1 = timing.get("conceded_p1_avg", 0)
    cp2 = timing.get("conceded_p2_avg", 0)
    stronger = timing.get("stronger_half", "?")
    weaker   = timing.get("weaker_half", "?")
    n        = timing.get("matches", "?")
    return (
        f"{label} goal timing (last {n} games): "
        f"Scored 1H {sp1:.2f} / 2H {sp2:.2f} (stronger: {stronger} half) | "
        f"Conceded 1H {cp1:.2f} / 2H {cp2:.2f} (more exposed: {weaker} half)"
    )


def _format_injuries(label, injuries):
    if not injuries:
        return f"{label} injuries: none reported"
    names = [p["name"] for p in injuries if p.get("name")]
    return f"{label} missing: {', '.join(names) if names else 'none'}"


def _build_user_message(
    home_team,
    away_team,
    home_season,
    away_season,
    home_last5,
    away_last5,
    h2h,
    home_injuries,
    away_injuries,
    data_probs,
    user_notes,
    home_goal_timing=None,
    away_goal_timing=None,
):
    sections = [
        f"MATCH: {home_team} (home) vs {away_team} (away)",
        "",
        "--- SEASON STATS ---",
        _format_season_stats(home_team, home_season),
        _format_season_stats(away_team, away_season),
        "",
        "--- RECENT FORM ---",
        _format_last5(home_team, home_last5),
        _format_last5(away_team, away_last5),
        "",
        "--- GOAL TIMING ---",
        _format_goal_timing(home_team, home_goal_timing),
        _format_goal_timing(away_team, away_goal_timing),
        "",
        "--- HEAD TO HEAD ---",
        _format_h2h(h2h),
        "",
        "--- INJURIES ---",
        _format_injuries(home_team, home_injuries),
        _format_injuries(away_team, away_injuries),
        "",
        "--- DATA MODEL PROBABILITIES ---",
        f"Home win: {data_probs['home_win_pct']}%",
        f"Draw:     {data_probs['draw_pct']}%",
        f"Away win: {data_probs['away_win_pct']}%",
        f"Confidence: {data_probs.get('confidence', 'unknown')}",
        "",
        "--- ANALYST NOTES ---",
        user_notes.strip() if user_notes and user_notes.strip() else "(none provided)",
        "",
        "Respond with your adjusted probabilities and tactical breakdown as JSON.",
    ]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# JSON extractor — handles Claude wrapping output in markdown fences
# ---------------------------------------------------------------------------

def _extract_json(text):
    # Strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Try to find a bare JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"No JSON object found in response:\n{text}")


# ---------------------------------------------------------------------------
# Probability normaliser
# ---------------------------------------------------------------------------

def _normalise(result):
    total = result["home_win_pct"] + result["draw_pct"] + result["away_win_pct"]
    if abs(total - 100.0) > 0.1:
        result["home_win_pct"] = round(result["home_win_pct"] / total * 100, 1)
        result["draw_pct"]     = round(result["draw_pct"]     / total * 100, 1)
        result["away_win_pct"] = round(result["away_win_pct"] / total * 100, 1)
        # Correct rounding drift on the largest value
        diff = 100.0 - (result["home_win_pct"] + result["draw_pct"] + result["away_win_pct"])
        largest = max(result, key=lambda k: result[k] if k in ("home_win_pct", "draw_pct", "away_win_pct") else -1)
        result[largest] = round(result[largest] + diff, 1)
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_ai_analysis(
    home_team,
    away_team,
    home_season,
    away_season,
    home_last5,
    away_last5,
    h2h,
    home_injuries,
    away_injuries,
    data_probs,
    user_notes="",
    home_goal_timing=None,
    away_goal_timing=None,
):
    """
    Calls Claude with full match context and returns adjusted probabilities
    plus tactical analysis.

    Parameters mirror what main.py will collect from sofascore + ml_engine.

    Returns a dict with keys:
        home_win_pct, draw_pct, away_win_pct,
        key_battleground, what_to_watch, upset_condition, summary
    """
    client = anthropic.Anthropic()

    user_message = _build_user_message(
        home_team, away_team,
        home_season, away_season,
        home_last5, away_last5,
        h2h,
        home_injuries, away_injuries,
        data_probs, user_notes,
        home_goal_timing=home_goal_timing,
        away_goal_timing=away_goal_timing,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": user_message}
        ],
    )

    # Extract text from response (may have thinking blocks before text block)
    text_block = next(
        (block.text for block in response.content if block.type == "text"),
        None,
    )
    if not text_block:
        raise ValueError("Claude returned no text block")

    result = _extract_json(text_block)

    required = {"home_win_pct", "draw_pct", "away_win_pct",
                 "key_battleground", "what_to_watch", "upset_condition", "summary"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"Claude response missing fields: {missing}")

    return _normalise(result)


# ---------------------------------------------------------------------------
# Analysis grader — scores user notes 0-10 against actual match stats
# ---------------------------------------------------------------------------

GRADER_PROMPT = """You are grading the quality of a football analyst's pre-match notes \
against what actually happened in the match.

Rules:
1. Return valid JSON only — no markdown fences, no commentary.
2. Score from 0 to 10 (decimals allowed, e.g. 7.5).
3. Score based on QUALITY OF REASONING, not just whether the predicted winner was correct.
   - High score: specific tactical observations that were verified by the stats (e.g. predicted \
counter-attack reliance and the team had low possession but scored on the break).
   - Medium score: correct outcome prediction with moderate reasoning.
   - Low score: vague notes, wrong outcome, or generic filler ("I think X will win").
   - Zero: no notes provided.
4. Keep the reasoning field under 2 sentences.

Return exactly:
{"score": <float 0-10>, "reasoning": "<string>"}"""


def grade_analysis(
    user_notes: str,
    home_team: str,
    away_team: str,
    actual_home_score: int,
    actual_away_score: int,
    actual_outcome: str,
    post_match_stats: dict | None = None,
) -> dict:
    """
    Asks Claude to score the analyst's pre-match notes against what happened.
    Returns {"score": float, "reasoning": str}.
    """
    if not user_notes or not user_notes.strip():
        return {"score": 0.0, "reasoning": "No notes were provided."}

    stats_lines = []
    if post_match_stats:
        for key, val in post_match_stats.items():
            stats_lines.append(f"  {key}: {val}")
    stats_block = "\n".join(stats_lines) if stats_lines else "  (no detailed stats available)"

    user_message = "\n".join([
        f"MATCH: {home_team} vs {away_team}",
        f"ACTUAL RESULT: {home_team} {actual_home_score}–{actual_away_score} {away_team} ({actual_outcome.replace('_', ' ')})",
        "",
        "POST-MATCH STATS:",
        stats_block,
        "",
        "ANALYST'S PRE-MATCH NOTES:",
        user_notes.strip(),
        "",
        "Grade the notes against what actually happened. Return JSON.",
    ])

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": GRADER_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    text_block = next(
        (block.text for block in response.content if block.type == "text"),
        None,
    )
    if not text_block:
        raise ValueError("Claude returned no text block in grader response")

    result = _extract_json(text_block)
    score = max(0.0, min(10.0, float(result["score"])))
    return {"score": round(score, 1), "reasoning": result.get("reasoning", "")}


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from sofascore import get_upcoming_matches, get_team_season_stats, get_team_last5, get_h2h, get_team_injuries, COMPETITIONS, _sleep
    from ml_engine import calculate_probabilities

    print("Fetching upcoming Premier League match...")
    upcoming = get_upcoming_matches("premier_league")
    if not upcoming:
        print("No upcoming matches found.")
        sys.exit(1)

    match = upcoming[0]
    home_id  = match["home_team_id"]
    away_id  = match["away_team_id"]
    match_id = match["match_id"]
    print(f"  {match['home_team']} vs {match['away_team']}\n")

    comp = COMPETITIONS["premier_league"]
    tid, sid = comp["tournament_id"], comp["season_id"]

    print("Fetching data...")
    home_season = get_team_season_stats(home_id, tid, sid); _sleep()
    away_season = get_team_season_stats(away_id, tid, sid); _sleep()
    home_last5  = get_team_last5(home_id, tid, sid);        _sleep()
    away_last5  = get_team_last5(away_id, tid, sid);        _sleep()
    h2h_data    = get_h2h(home_id, away_id);                _sleep()
    home_inj    = get_team_injuries(match_id, "home");      _sleep()
    away_inj    = get_team_injuries(match_id, "away")

    print("Running ML model...")
    data_probs = calculate_probabilities("premier_league", home_id, away_id)
    print(f"  Data-only: {data_probs['home_win_pct']}% / {data_probs['draw_pct']}% / {data_probs['away_win_pct']}%\n")

    user_notes = "Home team has been leaking set piece goals lately. Away keeper is on great form."

    print("Calling Claude for analysis...")
    result = get_ai_analysis(
        home_team    = match["home_team"],
        away_team    = match["away_team"],
        home_season  = home_season,
        away_season  = away_season,
        home_last5   = home_last5,
        away_last5   = away_last5,
        h2h          = h2h_data,
        home_injuries= home_inj,
        away_injuries= away_inj,
        data_probs   = data_probs,
        user_notes   = user_notes,
    )

    print(json.dumps(result, indent=2))
    total = result["home_win_pct"] + result["draw_pct"] + result["away_win_pct"]
    print(f"\nSum check: {total}%  (should be 100.0)")
