import time
from curl_cffi import requests

BASE_URL = "https://api.sofascore.com/api/v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}

# Season IDs are for 2025/26. Use get_current_season_id() if these go stale.
COMPETITIONS = {
    "premier_league":    {"tournament_id": 17,   "season_id": 76986},
    "champions_league":  {"tournament_id": 7,    "season_id": 76953},
    "super_lig":         {"tournament_id": 52,   "season_id": 77805},
    "fa_cup":            {"tournament_id": 19,   "season_id": 82557},  # FA Cup 25/26
    "eliteserien":       {"tournament_id": 20,   "season_id": 87809},  # Norwegian Eliteserien 2025
    "world_cup_2026":    {"tournament_id": None, "season_id": None},   # Coming Soon
}

DELAY = 1.0  # seconds between requests — do not remove


def _get(path):
    """Single point of entry for all Sofascore requests. Impersonates Chrome to bypass Cloudflare."""
    url = f"{BASE_URL}/{path}"
    response = requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=15)
    response.raise_for_status()
    return response.json()


def _sleep():
    time.sleep(DELAY)


def get_current_season_id(tournament_id):
    """
    Fetches the current active season_id for a tournament dynamically.
    Call this if you suspect the hardcoded season_id is stale (404 responses).
    """
    data = _get(f"unique-tournament/{tournament_id}/seasons")
    seasons = data.get("seasons", [])
    if not seasons:
        return None
    return seasons[0]["id"]


# ---------------------------------------------------------------------------
# Match parsers
# ---------------------------------------------------------------------------

def _parse_match(event):
    """Normalise a raw Sofascore event dict into a clean match dict."""
    home = event.get("homeTeam", {})
    away = event.get("awayTeam", {})
    score = event.get("homeScore", {})
    status = event.get("status", {})

    tourn = event.get("tournament", {})
    unique = tourn.get("uniqueTournament", {})
    return {
        "match_id":         event.get("id"),
        "home_team":        home.get("name"),
        "home_team_id":     home.get("id"),
        "away_team":        away.get("name"),
        "away_team_id":     away.get("id"),
        "start_timestamp":  event.get("startTimestamp"),
        "status_code":      status.get("code"),
        "status_desc":      status.get("description"),
        "home_score":        score.get("current"),
        "away_score":        event.get("awayScore", {}).get("current"),
        "home_period1":      score.get("period1"),
        "away_period1":      event.get("awayScore", {}).get("period1"),
        "round":            event.get("roundInfo", {}).get("round"),
        "tournament_id":    event.get("tournament", {}).get("id"),
        "season_id":        event.get("season", {}).get("id"),
        "competition_name": unique.get("name") or tourn.get("name", "Unknown"),
        "unique_tournament_id": unique.get("id"),
    }


# ---------------------------------------------------------------------------
# Match lists
# ---------------------------------------------------------------------------

def get_upcoming_matches(competition_key, page=0):
    """Returns upcoming (not yet started) matches for a competition."""
    comp = COMPETITIONS[competition_key]
    if comp["tournament_id"] is None:
        return []
    tid = comp["tournament_id"]
    sid = comp["season_id"]
    try:
        data = _get(f"unique-tournament/{tid}/season/{sid}/events/next/{page}")
    except Exception:
        return []
    return [_parse_match(e) for e in data.get("events", [])]


def get_recent_matches(competition_key, page=0):
    """Returns recently finished matches for a competition."""
    comp = COMPETITIONS[competition_key]
    if comp["tournament_id"] is None:
        return []
    tid = comp["tournament_id"]
    sid = comp["season_id"]
    data = _get(f"unique-tournament/{tid}/season/{sid}/events/last/{page}")
    return [_parse_match(e) for e in data.get("events", [])]


def get_all_live_matches():
    """Returns all currently live football matches across every competition."""
    data = _get("sport/football/events/live")
    return [_parse_match(e) for e in data.get("events", [])]


def get_live_matches(competition_key):
    """Returns currently live matches for a competition."""
    comp = COMPETITIONS[competition_key]
    if comp["tournament_id"] is None:
        return []
    tid = comp["tournament_id"]
    sid = comp["season_id"]
    data = _get(f"unique-tournament/{tid}/season/{sid}/events/live")
    return [_parse_match(e) for e in data.get("events", [])]


# ---------------------------------------------------------------------------
# Live match stats
# ---------------------------------------------------------------------------

def get_live_match_stats(match_id):
    """
    Returns live in-game stats for a match.
    Uses period index 0 which represents the full-game aggregated stats.
    """
    data = _get(f"event/{match_id}/statistics")
    periods = data.get("statistics", [])

    # Period 0 = "All" (full game stats)
    all_period = next((p for p in periods if p.get("period") == "ALL"), None)
    if not all_period:
        # Fall back to first available period
        all_period = periods[0] if periods else None
    if not all_period:
        return {}

    stat_map = {}
    for group in all_period.get("groups", []):
        for item in group.get("statisticsItems", []):
            key = item.get("key")
            stat_map[key] = {
                "home": item.get("home"),
                "away": item.get("away"),
            }

    def pick(key):
        return stat_map.get(key, {"home": None, "away": None})

    return {
        "possession":      pick("ballPossession"),
        "shots":           pick("totalShotsOnGoal"),
        "shots_on_target": pick("shotsOnGoal"),
        "xg":              pick("expectedGoals"),
        "corners":         pick("cornerKicks"),
        "fouls":           pick("fouls"),
        "yellow_cards":    pick("yellowCards"),
    }


# Human-readable labels for Sofascore stat keys
_STAT_LABELS = {
    "ballPossession":          "Ball Possession",
    "expectedGoals":           "Expected Goals (xG)",
    "bigChanceCreated":        "Total Shots",
    "totalShotsOnGoal":        "Total Shots",
    "shotsOnGoal":             "Shots on Target",
    "shotsOffGoal":            "Shots off Target",
    "blockedScoringAttempt":   "Blocked Shots",
    "hitWoodwork":             "Hit Woodwork",
    "totalShotsInsideBox":     "Shots Inside Box",
    "totalShotsOutsideBox":    "Shots Outside Box",
    "bigChanceScored":         "Big Chances Scored",
    "bigChanceMissed":         "Big Chances Missed",
    "bigChanceCreated":        "Big Chances Created",
    "goalkeeperSaves":         "Goalkeeper Saves",
    "goalsPrevented":          "Goals Prevented",
    "cornerKicks":             "Corners",
    "fouls":                   "Fouls",
    "yellowCards":             "Yellow Cards",
    "passes":                  "Total Passes",
    "accuratePasses":          "Accurate Passes",
    "finalThirdEntries":       "Final Third Entries",
    "accurateLongBalls":       "Long Balls",
    "accurateCross":           "Crosses",
    "totalTackle":             "Tackles",
    "interceptionWon":         "Interceptions",
    "totalClearance":          "Clearances",
    "ballRecovery":            "Ball Recoveries",
    "duelWonPercent":          "Duels Won",
    "groundDuelsPercentage":   "Ground Duels",
    "aerialDuelsPercentage":   "Aerial Duels",
    "dribblesPercentage":      "Dribbles",
    "dispossessed":            "Dispossessed",
    "offsides":                "Offsides",
    "touchesInOppBox":         "Touches in Opp Box",
    "errorsLeadToShot":        "Errors Leading to Shot",
    "errorsLeadToGoal":        "Errors Leading to Goal",
    "freeKicks":               "Free Kicks",
    "throwIns":                "Throw Ins",
    "wonTacklePercent":        "Tackle Success %",
    "accurateThroughBall":     "Through Balls",
    "fouledFinalThird":        "Fouls Suffered (Final 3rd)",
    "highClaims":              "GK High Claims",
    "diveSaves":               "GK Dive Saves",
    "punches":                 "GK Punches",
    "goalKicks":               "Goal Kicks",
    "finalThirdPhaseStatistic":"Final Third Passes",
}


def get_full_match_stats(match_id):
    """
    Returns all match statistics grouped by period (ALL, 1ST, 2ND) and group name.
    Used for the live stats panel in the frontend.
    """
    data = _get(f"event/{match_id}/statistics")
    periods_raw = data.get("statistics", [])

    result = {}
    for period in periods_raw:
        period_key = period.get("period", "ALL")
        groups = []
        for group in period.get("groups", []):
            items = []
            for item in group.get("statisticsItems", []):
                key = item.get("key", "")
                items.append({
                    "key":   key,
                    "label": _STAT_LABELS.get(key, key),
                    "home":  item.get("home"),
                    "away":  item.get("away"),
                })
            if items:
                groups.append({
                    "name":  group.get("groupName", ""),
                    "items": items,
                })
        result[period_key] = groups

    return result


# ---------------------------------------------------------------------------
# Team season stats
# ---------------------------------------------------------------------------

def get_team_season_stats(team_id, tournament_id, season_id):
    """
    Returns a team's aggregated season stats.
    Merges two endpoints: detailed stats (goals, possession) + standings (W/D/L).
    """
    _sleep()
    try:
        stat_data = _get(f"team/{team_id}/unique-tournament/{tournament_id}/season/{season_id}/statistics/overall")
    except Exception:
        stat_data = {}
    stats = stat_data.get("statistics", {})

    _sleep()
    try:
        stand_data = _get(f"unique-tournament/{tournament_id}/season/{season_id}/standings/total")
    except Exception:
        stand_data = {}
    rows = stand_data.get("standings", [{}])[0].get("rows", [])
    row = next((r for r in rows if r.get("team", {}).get("id") == team_id), {})

    played = row.get("matches") or stats.get("matches") or 1

    shots    = stats.get("shots") or stats.get("totalShots")
    sot      = stats.get("shotsOnTarget")
    passes   = stats.get("accuratePasses")
    total_p  = stats.get("totalPasses")

    return {
        "matches_played":       played,
        "wins":                 row.get("wins"),
        "draws":                row.get("draws"),
        "losses":               row.get("losses"),
        "points":               row.get("points"),
        "position":             row.get("position"),
        "goals_scored":         stats.get("goalsScored"),
        "goals_conceded":       stats.get("goalsConceded"),
        "assists":              stats.get("assists"),
        "shots":                shots,
        "shots_on_target":      sot,
        "shots_per_game":       round(shots / played, 1) if shots else None,
        "sot_per_game":         round(sot / played, 1) if sot else None,
        "big_chances_created":  stats.get("bigChancesCreated"),
        "avg_possession":       round(stats.get("averageBallPossession", 0), 1) or None,
        "pass_accuracy":        round(stats.get("accuratePassesPercentage", 0), 1) or None,
        "tackles":              stats.get("tackles"),
        "interceptions":        stats.get("interceptions"),
        "clean_sheets":         stats.get("cleanSheets"),
        "yellow_cards":         stats.get("yellowCards"),
        "red_cards":            stats.get("redCards"),
        "points_per_game":      round(row.get("points", 0) / played, 2) if row.get("points") else None,
    }


# ---------------------------------------------------------------------------
# Last 5 matches
# ---------------------------------------------------------------------------

def get_match_stats(match_id):
    """Returns post-match stats for a finished match (same structure as live stats)."""
    _sleep()
    return get_live_match_stats(match_id)


def get_team_last5(team_id, tournament_id, season_id):
    """
    Returns the last 5 matches for a team with per-match stats.
    Filters from get_recent_matches for the relevant competition.
    """
    # Find which competition key matches this tournament
    comp_key = next(
        (k for k, v in COMPETITIONS.items() if v["tournament_id"] == tournament_id),
        None
    )
    if comp_key is None:
        return []

    # Collect matches across pages until we have 5 for this team
    results = []
    for page in range(5):  # look back up to 5 pages
        _sleep()
        matches = get_recent_matches(comp_key, page=page)
        for m in matches:
            if m["home_team_id"] == team_id or m["away_team_id"] == team_id:
                is_home = m["home_team_id"] == team_id
                home_s = m["home_score"] or 0
                away_s = m["away_score"] or 0

                if is_home:
                    scored, conceded = home_s, away_s
                    result = "W" if home_s > away_s else ("D" if home_s == away_s else "L")
                else:
                    scored, conceded = away_s, home_s
                    result = "W" if away_s > home_s else ("D" if away_s == home_s else "L")

                match_stats = get_match_stats(m["match_id"])
                side = "home" if is_home else "away"

                results.append({
                    "match_id":   m["match_id"],
                    "opponent":   m["away_team"] if is_home else m["home_team"],
                    "home_away":  "home" if is_home else "away",
                    "result":     result,
                    "score":      f"{scored}-{conceded}",
                    "xg":         match_stats.get("xg", {}).get(side),
                    "xga":        match_stats.get("xg", {}).get("away" if is_home else "home"),
                    "possession": match_stats.get("possession", {}).get(side),
                })

            if len(results) == 5:
                break
        if len(results) == 5:
            break

    return results


# ---------------------------------------------------------------------------
# Head-to-head
# ---------------------------------------------------------------------------

def get_h2h(home_team_id, away_team_id):
    """
    Returns last 10 H2H matches between two teams.
    Iterates through the home team's match history and filters by opponent.
    """
    found = []
    for page in range(8):
        _sleep()
        data = _get(f"team/{home_team_id}/events/last/{page}")
        events = data.get("events", [])
        for e in events:
            ht = e.get("homeTeam", {}).get("id")
            at = e.get("awayTeam", {}).get("id")
            if away_team_id in (ht, at):
                m = _parse_match(e)
                home_s = m["home_score"] or 0
                away_s = m["away_score"] or 0
                if home_s > away_s:
                    winner = "home"
                elif away_s > home_s:
                    winner = "away"
                else:
                    winner = "draw"
                found.append({
                    "match_id":    m["match_id"],
                    "home_team":   m["home_team"],
                    "home_team_id": m["home_team_id"],
                    "away_team":   m["away_team"],
                    "away_team_id": m["away_team_id"],
                    "score":       f"{home_s}-{away_s}",
                    "winner":      winner,
                    "date":        m["start_timestamp"],
                })
        if len(found) >= 10 or not data.get("hasNextPage"):
            break

    return found[:10]


# ---------------------------------------------------------------------------
# Single event status
# ---------------------------------------------------------------------------

def get_match_event(match_id):
    """Returns the current status and score for a single match."""
    data = _get(f"event/{match_id}")
    return _parse_match(data.get("event", {}))


def get_match_incidents(match_id):
    """Returns parsed match incidents: goals, cards, subs, VAR, period markers."""
    data = _get(f"event/{match_id}/incidents")
    result = []
    for inc in data.get("incidents", []):
        t = inc.get("incidentType")
        if t == "period":
            result.append({
                "type":       "period",
                "text":       inc.get("text", ""),
                "home_score": inc.get("homeScore"),
                "away_score": inc.get("awayScore"),
                "time":       inc.get("time"),
            })
        elif t == "goal":
            result.append({
                "type":       "goal",
                "player":     inc.get("player", {}).get("shortName", ""),
                "time":       inc.get("time"),
                "added_time": inc.get("addedTime"),
                "is_home":    inc.get("isHome"),
                "cls":        inc.get("incidentClass", "regular"),
                "home_score": inc.get("homeScore"),
                "away_score": inc.get("awayScore"),
            })
        elif t == "card":
            result.append({
                "type":    "card",
                "player":  inc.get("player", {}).get("shortName", ""),
                "time":    inc.get("time"),
                "is_home": inc.get("isHome"),
                "cls":     inc.get("incidentClass", "yellow"),
            })
        elif t == "substitution":
            result.append({
                "type":       "substitution",
                "player_in":  inc.get("playerIn",  {}).get("shortName", ""),
                "player_out": inc.get("playerOut", {}).get("shortName", ""),
                "time":       inc.get("time"),
                "is_home":    inc.get("isHome"),
            })
        elif t == "varDecision":
            result.append({
                "type":    "var",
                "player":  inc.get("player", {}).get("shortName", ""),
                "time":    inc.get("time"),
                "is_home": inc.get("isHome"),
                "cls":     inc.get("incidentClass", ""),
            })
    return result


def get_match_lineups(match_id):
    """Returns starting XI and substitutes for both teams."""
    data = _get(f"event/{match_id}/lineups")
    result = {}
    for side in ("home", "away"):
        side_data = data.get(side, {})
        players = side_data.get("players", [])
        def parse_player(p):
            return {
                "id":       p["player"]["id"],
                "name":     p["player"]["shortName"],
                "jersey":   p.get("jerseyNumber", ""),
                "position": p.get("position", ""),
                "rating":   p.get("avgRating"),
            }
        result[side] = {
            "formation":  side_data.get("formation"),
            "starters":   [parse_player(p) for p in players if not p.get("substitute")],
            "substitutes":[parse_player(p) for p in players if p.get("substitute")],
        }
    return result


# ---------------------------------------------------------------------------
# Injuries
# ---------------------------------------------------------------------------

def get_team_injuries(match_id, side):
    """
    Returns missing/injured players for one side of a specific match.
    side: 'home' or 'away'
    Reads from the lineups endpoint which includes a missingPlayers list.
    """
    _sleep()
    data = _get(f"event/{match_id}/lineups")
    team_data = data.get(side, {})
    missing = team_data.get("missingPlayers", [])

    injured = []
    for entry in missing:
        player = entry.get("player", {})
        injured.append({
            "name":            player.get("name"),
            "position":        player.get("position"),
            "injury_type":     entry.get("description"),
            "expected_return": entry.get("expectedEndDate"),
        })

    return injured


# ---------------------------------------------------------------------------
# Goal timing (first half vs second half scoring/conceding averages)
# ---------------------------------------------------------------------------

def get_team_goal_timing(team_id):
    """
    Aggregates period1/period2 scoring and conceding stats from the team's
    last 30 finished matches. Returns per-half averages.
    """
    try:
        data = _get(f"team/{team_id}/events/last/0")
    except Exception:
        return None

    events = data.get("events", [])
    scored_p1 = scored_p2 = conc_p1 = conc_p2 = n = 0

    for e in events:
        if e.get("status", {}).get("code") != 100:
            continue
        hs  = e.get("homeScore", {})
        aws = e.get("awayScore", {})
        is_home  = e.get("homeTeam", {}).get("id") == team_id
        my_score  = hs  if is_home else aws
        opp_score = aws if is_home else hs
        if my_score.get("period1") is None:
            continue
        scored_p1 += my_score["period1"]
        scored_p2 += my_score["period2"]
        conc_p1   += opp_score["period1"]
        conc_p2   += opp_score["period2"]
        n += 1

    if n == 0:
        return None

    r = lambda v: round(v / n, 2)
    return {
        "matches":           n,
        "scored_p1_avg":     r(scored_p1),
        "scored_p2_avg":     r(scored_p2),
        "conceded_p1_avg":   r(conc_p1),
        "conceded_p2_avg":   r(conc_p2),
        "scored_p1_total":   scored_p1,
        "scored_p2_total":   scored_p2,
        "conceded_p1_total": conc_p1,
        "conceded_p2_total": conc_p2,
        "stronger_half":     "first" if scored_p1 >= scored_p2 else "second",
        "weaker_half":       "second" if conc_p2 >= conc_p1 else "first",
    }


# ---------------------------------------------------------------------------
# Referee data
# ---------------------------------------------------------------------------

# Tournament IDs we track — used to filter referee competition stats
_TRACKED_TOURNAMENT_IDS = {17, 7, 52, 19, 20}


def get_referee_data(match_id, home_team_id, away_team_id):
    """
    Returns referee info, career stats, per-competition stats,
    last 5 games, and history with each team.
    """
    event_data = _get(f"event/{match_id}")
    referee = event_data.get("event", {}).get("referee")
    if not referee:
        return None

    ref_id = referee["id"]
    total_games = referee.get("games", 0)

    # Per-competition stats
    _sleep()
    stats_data = _get(f"referee/{ref_id}/statistics")
    comp_stats = []
    for s in stats_data.get("statistics", []):
        tid = s.get("uniqueTournament", {}).get("id")
        if tid in _TRACKED_TOURNAMENT_IDS:
            apps = s.get("appearances", 0)
            comp_stats.append({
                "competition":      s["uniqueTournament"]["name"],
                "appearances":      apps,
                "yellow_cards":     s.get("yellowCards", 0),
                "red_cards":        s.get("redCards", 0),
                "yellow_red_cards": s.get("yellowRedCards", 0),
                "penalties":        s.get("penalty", 0),
                "avg_yellows":      round(s.get("yellowCards", 0) / max(apps, 1), 2),
            })

    # Recent events — scan two pages to find team history
    _sleep()
    recent_raw = _get(f"referee/{ref_id}/events/last/0").get("events", [])

    def _parse_ref_event(e):
        return {
            "home_team":    e.get("homeTeam", {}).get("name"),
            "home_team_id": e.get("homeTeam", {}).get("id"),
            "away_team":    e.get("awayTeam", {}).get("name"),
            "away_team_id": e.get("awayTeam", {}).get("id"),
            "home_score":   e.get("homeScore", {}).get("current"),
            "away_score":   e.get("awayScore", {}).get("current"),
            "date":         e.get("startTimestamp"),
            "competition":  e.get("tournament", {}).get("uniqueTournament", {}).get("name")
                            or e.get("tournament", {}).get("name", ""),
        }

    last_5 = [_parse_ref_event(e) for e in recent_raw[:5]]

    home_history, away_history = [], []
    for e in recent_raw:
        ht_id = e.get("homeTeam", {}).get("id")
        at_id = e.get("awayTeam", {}).get("id")
        parsed = _parse_ref_event(e)
        if ht_id == home_team_id or at_id == home_team_id:
            home_history.append(parsed)
        if ht_id == away_team_id or at_id == away_team_id:
            away_history.append(parsed)

    return {
        "id":                   ref_id,
        "name":                 referee["name"],
        "country":              referee.get("country", {}).get("name", ""),
        "total_games":          total_games,
        "total_yellow_cards":   referee.get("yellowCards", 0),
        "total_red_cards":      referee.get("redCards", 0),
        "total_yellow_red_cards": referee.get("yellowRedCards", 0),
        "avg_yellows_per_game": round(referee.get("yellowCards", 0) / max(total_games, 1), 2),
        "avg_reds_per_game":    round(referee.get("redCards", 0) / max(total_games, 1), 2),
        "competition_stats":    comp_stats,
        "last_5_games":         last_5,
        "home_team_history":    home_history[:5],
        "away_team_history":    away_history[:5],
    }


# ---------------------------------------------------------------------------
# Match odds (optional)
# ---------------------------------------------------------------------------

def get_match_odds(match_id):
    """
    Returns 1X2 odds from the first available bookmaker for a match.
    Returns None if odds are unavailable.
    """
    _sleep()
    try:
        data = _get(f"event/{match_id}/odds/1/all")
        markets = data.get("markets", [])
        if not markets:
            return None
        choices = markets[0].get("choices", [])
        odds = {}
        for c in choices:
            name = c.get("name")  # "1", "X", "2"
            fractional = c.get("fractionalValue")
            if name == "1":
                odds["home"] = fractional
            elif name == "X":
                odds["draw"] = fractional
            elif name == "2":
                odds["away"] = fractional
        return odds if odds else None
    except requests.HTTPError:
        return None


# ---------------------------------------------------------------------------
# Quick test — run `python sofascore.py` to verify each function
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    def show(label, data):
        print(f"\n{'='*60}")
        print(f"  {label}")
        print('='*60)
        print(json.dumps(data, indent=2, default=str))

    print("Testing sofascore.py against live API...")

    # 1. Upcoming Premier League matches
    upcoming = get_upcoming_matches("premier_league")
    show("Premier League — upcoming (first 3)", upcoming[:3])

    _sleep()

    # 2. Recent Premier League matches
    recent = get_recent_matches("premier_league")
    show("Premier League — recent (first 3)", recent[:3])

    if recent:
        match = recent[0]
        mid = match["match_id"]
        home_id = match["home_team_id"]
        away_id = match["away_team_id"]
        tid = match["tournament_id"]
        sid = match["season_id"]

        _sleep()

        # 3. Match stats for most recent game
        stats = get_match_stats(mid)
        show(f"Match stats — {match['home_team']} vs {match['away_team']}", stats)

        _sleep()

        # 4. Team season stats (home team) — uses competition's tournament_id, not event's
        comp = COMPETITIONS["premier_league"]
        season_stats = get_team_season_stats(home_id, comp["tournament_id"], comp["season_id"])
        show(f"Season stats — {match['home_team']}", season_stats)

        _sleep()

        # 5. H2H
        h2h = get_h2h(home_id, away_id)
        show(f"H2H — {match['home_team']} vs {match['away_team']} (last 10)", h2h)

        _sleep()

        # 6. Missing players for both sides
        injuries_home = get_team_injuries(mid, "home")
        injuries_away = get_team_injuries(mid, "away")
        show(f"Missing players — {match['home_team']}", injuries_home)
        show(f"Missing players — {match['away_team']}", injuries_away)

        _sleep()

        # 7. Odds
        odds = get_match_odds(mid)
        show(f"Odds — {match['home_team']} vs {match['away_team']}", odds)

    print("\nDone.")
