import { useState, useEffect } from 'react'
import './MatchFeed.css'

const API = 'http://localhost:8002'

const COMP_LABELS = {
  premier_league:   'Premier League',
  champions_league: 'Champions League',
  super_lig:        'Süper Lig',
  fa_cup:           'FA Cup',
  eliteserien:      'Eliteserien',
}

const COMP_TOURNAMENT_IDS = {
  premier_league:   17,
  champions_league: 7,
  super_lig:        52,
  fa_cup:           19,
  eliteserien:      20,
}

// Reverse map: unique_tournament_id → competition_key (for analysis support)
const TOURNAMENT_TO_COMP_KEY = {
  17: 'premier_league',
  7:  'champions_league',
  52: 'super_lig',
  19: 'fa_cup',
  20: 'eliteserien',
}

const ACTIVE_COMPS = ['premier_league', 'champions_league', 'super_lig', 'fa_cup', 'eliteserien']

const SOFA_IMG = 'https://api.sofascore.com/api/v1'

function TeamBadge({ teamId, name, size = 22 }) {
  const [err, setErr] = useState(false)
  if (!teamId || err) {
    return (
      <span className="badge-fallback" style={{ width: size, height: size, fontSize: size * 0.45 }}>
        {name?.[0] ?? '?'}
      </span>
    )
  }
  return (
    <img
      src={`${SOFA_IMG}/team/${teamId}/image`}
      alt={name}
      width={size}
      height={size}
      className="team-badge"
      onError={() => setErr(true)}
    />
  )
}

function LeagueBadge({ compKey, size = 20 }) {
  const tid = COMP_TOURNAMENT_IDS[compKey]
  const [err, setErr] = useState(false)
  if (!tid || err) return <span className="comp-dot" />
  return (
    <img
      src={`${SOFA_IMG}/unique-tournament/${tid}/image`}
      alt={compKey}
      width={size}
      height={size}
      className="league-badge"
      onError={() => setErr(true)}
    />
  )
}

function formatKickoff(ts) {
  if (!ts) return '--:--'
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function isSameDay(ts, date) {
  const d = new Date(ts * 1000)
  return d.toDateString() === date.toDateString()
}

function addDays(date, n) {
  const d = new Date(date)
  d.setDate(d.getDate() + n)
  return d
}

function dateLabel(date) {
  const today    = new Date()
  const tomorrow = addDays(today, 1)
  const yesterday = addDays(today, -1)
  if (date.toDateString() === today.toDateString())     return 'Today'
  if (date.toDateString() === tomorrow.toDateString())  return 'Tomorrow'
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

// tab: null = default (all today), 'live' = live only, 'finished', 'upcoming'
export default function MatchFeed({ onSelectMatch, selectedMatchId }) {
  const [tab, setTab]           = useState(null)   // null = "all today" default
  const [viewDate, setViewDate] = useState(new Date())
  const [allMatches, setAllMatches] = useState({}) // upcoming + live merged, keyed by comp
  const [liveOnly,  setLiveOnly]  = useState({})   // live only, keyed by comp
  const [finished,  setFinished]  = useState({})   // recent/finished, keyed by comp
  const [loading,   setLoading]   = useState(false)
  const [collapsed, setCollapsed] = useState({})
  const [liveCount, setLiveCount] = useState(0)

  // Fetch on mount and when tab or date changes
  useEffect(() => { fetchMatches() }, [tab, viewDate])

  // Poll live data every 60s and sync the selected match score if it's live
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const allLive = await fetch(`${API}/matches/live`).then(r => r.json())
        if (selectedMatchId) {
          const updated = allLive.find(m => m.match_id === selectedMatchId)
          if (updated) {
            const compKey = TOURNAMENT_TO_COMP_KEY[updated.unique_tournament_id] || null
            onSelectMatch({ ...updated, competition_key: compKey })
          }
        }
        // Also refresh the feed counts
        setLiveCount(allLive.length)
      } catch {}
    }, 60_000)
    return () => clearInterval(interval)
  }, [selectedMatchId])

  async function fetchMatches() {
    setLoading(true)
    try {
      if (tab === 'finished') {
        const results = await Promise.all(
          ACTIVE_COMPS.map(c =>
            fetch(`${API}/matches/${c}/recent`)
              .then(r => r.json())
              .then(data => ({ comp: c, matches: data }))
              .catch(() => ({ comp: c, matches: [] }))
          )
        )
        const map = {}
        results.forEach(({ comp, matches }) => {
          const filtered = matches.filter(
            m => m.status_code === 100 && m.start_timestamp && isSameDay(m.start_timestamp, viewDate)
          )
          if (filtered.length) map[comp] = filtered
        })
        setFinished(map)
      } else {
        // Fetch upcoming (per tracked comp) + all live (global) in parallel
        const [upcomingRes, allLive] = await Promise.all([
          Promise.all(ACTIVE_COMPS.map(c =>
            fetch(`${API}/matches/${c}/upcoming`)
              .then(r => r.json())
              .then(data => ({ comp: c, matches: data }))
              .catch(() => ({ comp: c, matches: [] }))
          )),
          fetch(`${API}/matches/live`)
            .then(r => r.json())
            .catch(() => []),
        ])

        // Group all live matches by competition_name
        const liveMap = {}
        allLive.forEach(m => {
          const key = m.competition_name || 'Other'
          if (!liveMap[key]) liveMap[key] = []
          liveMap[key].push(m)
        })
        setLiveOnly(liveMap)
        setLiveCount(allLive.length)

        // Build "all today" map using tracked-comp upcoming + live for today
        const allMap = {}
        ACTIVE_COMPS.forEach((comp, i) => {
          const liveForComp = allLive.filter(
            m => TOURNAMENT_TO_COMP_KEY[m.unique_tournament_id] === comp
              && m.start_timestamp && isSameDay(m.start_timestamp, viewDate)
          )
          const upcoming = upcomingRes[i].matches.filter(
            m => m.status_code === 0 && m.start_timestamp && isSameDay(m.start_timestamp, viewDate)
          )
          const merged = [...liveForComp, ...upcoming].sort(
            (a, b) => (a.start_timestamp || 0) - (b.start_timestamp || 0)
          )
          if (merged.length) allMap[comp] = merged
        })
        setAllMatches(allMap)
      }
    } finally {
      setLoading(false)
    }
  }

  function matchesForComp(comp) {
    if (tab === 'finished') return finished[comp]  || []
    if (tab === 'upcoming') {
      const all = allMatches[comp] || []
      return all.filter(m => m.status_code === 0)
    }
    return allMatches[comp] || []
  }

  function handleTabClick(clicked) {
    setTab(prev => prev === clicked ? null : clicked)
  }

  // For non-live tabs: groups are tracked comp keys
  // For live tab: groups are competition_name strings
  const liveGroups   = Object.keys(liveOnly).sort()
  const trackedComps = ACTIVE_COMPS.filter(c => matchesForComp(c).length > 0)

  function renderMatch(m, compKey) {
    const isLive     = m.status_code != null && m.status_code !== 0 && m.status_code !== 100
    const isFinished = m.status_code === 100
    const homeWins   = isFinished && (m.home_score ?? 0) > (m.away_score ?? 0)
    const awayWins   = isFinished && (m.away_score ?? 0) > (m.home_score ?? 0)
    return (
      <button
        key={m.match_id}
        className={`match-row ${m.match_id === selectedMatchId ? 'is-selected' : ''}`}
        onClick={() => onSelectMatch({ ...m, competition_key: compKey || null })}
      >
        <div className={`match-time ${isLive ? 'is-live' : isFinished ? 'is-final' : ''}`}>
          <span className="label">{isFinished ? 'FT' : isLive ? '' : 'KO'}</span>
          <span className="value">
            {isLive
              ? m.time_str || 'Live'
              : formatKickoff(m.start_timestamp)}
          </span>
        </div>
        <div className="match-teams">
          <div className={`match-team ${isFinished && awayWins ? 'is-loser' : ''}`}>
            <span className="name">{m.home_team}</span>
            {(isLive || isFinished) && (
              <span className={`score ${isLive ? 'live' : ''}`}>{m.home_score ?? 0}</span>
            )}
          </div>
          <div className={`match-team ${isFinished && homeWins ? 'is-loser' : ''}`}>
            <span className="name">{m.away_team}</span>
            {(isLive || isFinished) && (
              <span className={`score ${isLive ? 'live' : ''}`}>{m.away_score ?? 0}</span>
            )}
          </div>
        </div>
        <div className="match-meta">
          <TeamBadge teamId={m.home_team_id} name={m.home_team} size={18} />
          <TeamBadge teamId={m.away_team_id} name={m.away_team} size={18} />
        </div>
      </button>
    )
  }

  return (
    <div className="feed">
      {tab !== 'live' && (
        <div className="date-strip">
          <button className="date-arrow" onClick={() => setViewDate(d => addDays(d, -1))}>&#8249;</button>
          <div className="date-center">
            <div className="date-day">{dateLabel(viewDate)}</div>
          </div>
          <button className="date-arrow" onClick={() => setViewDate(d => addDays(d, 1))}>&#8250;</button>
        </div>
      )}

      <div className="feed-tabs">
        <button
          className={`feed-tab feed-tab--live ${tab === 'live' ? 'is-active' : ''}`}
          onClick={() => handleTabClick('live')}
        >
          <span className="live-pip" /> Live {liveCount > 0 && <span className="count">{liveCount}</span>}
        </button>
        <button
          className={`feed-tab ${tab === 'finished' ? 'is-active' : ''}`}
          onClick={() => handleTabClick('finished')}
        >
          Finished
        </button>
        <button
          className={`feed-tab ${tab === 'upcoming' ? 'is-active' : ''}`}
          onClick={() => handleTabClick('upcoming')}
        >
          Upcoming
        </button>
      </div>

      <div className="match-list">
        {loading && <p className="feed-msg">Loading…</p>}

        {/* Live tab — all competitions globally */}
        {!loading && tab === 'live' && (
          liveGroups.length === 0
            ? <p className="feed-msg">No live matches right now</p>
            : liveGroups.map(compName => {
                const matches = liveOnly[compName] || []
                const isCollapsed = collapsed[compName]
                // Map back to comp key if it's a tracked competition
                const compKey = TOURNAMENT_TO_COMP_KEY[matches[0]?.unique_tournament_id] || null
                return (
                  <div key={compName} className="comp-group">
                    <button
                      className="comp-header"
                      onClick={() => setCollapsed(c => ({ ...c, [compName]: !c[compName] }))}
                    >
                      {compKey
                        ? <LeagueBadge compKey={compKey} />
                        : <span className="comp-dot" />
                      }
                      <span className="comp-name">{compName}</span>
                      <span className="comp-count">{matches.length}</span>
                      <span className={`comp-toggle ${isCollapsed ? 'is-collapsed' : ''}`}>▾</span>
                    </button>
                    {!isCollapsed && matches.map(m => renderMatch(m, compKey))}
                  </div>
                )
              })
        )}

        {/* Default / Finished / Upcoming tabs — tracked comps only */}
        {!loading && tab !== 'live' && (
          trackedComps.length === 0
            ? <p className="feed-msg">{`No matches for ${dateLabel(viewDate)}`}</p>
            : trackedComps.map(comp => {
                const matches     = matchesForComp(comp)
                const isCollapsed = collapsed[comp]
                return (
                  <div key={comp} className="comp-group">
                    <button
                      className="comp-header"
                      onClick={() => setCollapsed(c => ({ ...c, [comp]: !c[comp] }))}
                    >
                      <LeagueBadge compKey={comp} />
                      <span className="comp-name">{COMP_LABELS[comp]}</span>
                      <span className="comp-count">{matches.length}</span>
                      <span className={`comp-toggle ${isCollapsed ? 'is-collapsed' : ''}`}>▾</span>
                    </button>
                    {!isCollapsed && matches.map(m => renderMatch(m, comp))}
                  </div>
                )
              })
        )}
      </div>
    </div>
  )
}
