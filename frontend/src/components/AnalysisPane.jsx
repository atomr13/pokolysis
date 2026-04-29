import { useState, useEffect } from 'react'
import './AnalysisPane.css'

const API = 'http://localhost:8002'
const SOFA_IMG = 'https://api.sofascore.com/api/v1'

function TeamCrest({ teamId, name, side }) {
  const [err, setErr] = useState(false)
  const initial = name?.[0]?.toUpperCase() ?? '?'
  return (
    <div className={`team-crest ${side || ''}`}>
      {teamId && !err
        ? <img
            src={`${SOFA_IMG}/team/${teamId}/image`}
            alt={name}
            onError={() => setErr(true)}
          />
        : initial
      }
    </div>
  )
}

function formatDate(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString('en-GB', {
    weekday: 'short', day: 'numeric', month: 'short'
  })
}

function formatH2HDate(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' })
}

// Market-style probability bar
function MarketRow({ label, pct, colorClass, delta }) {
  const sign = delta > 0 ? '+' : ''
  const deltaCls = delta > 0 ? 'up' : delta < 0 ? 'down' : ''
  return (
    <div className="market-row">
      <span className="market-name">{label}</span>
      <div className="market-track">
        <div className={`market-fill ${colorClass || ''}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="market-pct">{pct}%</span>
      <span className={`market-delta ${deltaCls}`}>
        {delta != null && delta !== 0 ? `${sign}${delta}%` : '—'}
      </span>
    </div>
  )
}

// Delta pill for the winprob ribbon
function DeltaPill({ val }) {
  if (val == null || val === 0) return <span className="winprob-delta flat mono">±0</span>
  const sign = val > 0 ? '+' : ''
  return <span className={`winprob-delta ${val > 0 ? 'up' : 'down'} mono`}>{sign}{val}%</span>
}

function buildReasoningSummary(factors, homeTeam, awayTeam, homeWinPct, drawPct, awayWinPct) {
  if (!factors?.home || !factors?.away) return null

  const pct = (hVal, aVal) => {
    const h = hVal ?? 0.5, a = aVal ?? 0.5, total = h + a || 1
    return { h: Math.round((h / total) * 100), a: 100 - Math.round((h / total) * 100) }
  }

  const f = {
    season_ppg: pct(factors.home.season_ppg, factors.away.season_ppg),
    season_xgd: pct(factors.home.season_xgd, factors.away.season_xgd),
    form_ppg:   pct(factors.home.form_ppg,   factors.away.form_ppg),
    form_xgd:   pct(factors.home.form_xgd,   factors.away.form_xgd),
    h2h:        pct(factors.home.h2h,        factors.away.h2h),
  }

  const gap    = (p) => Math.abs(p.h - p.a)
  const leader = (p) => p.h >= p.a ? homeTeam : awayTeam
  const parts  = []

  const seasonAdv = leader(f.season_ppg)
  const seasonGap = gap(f.season_ppg)
  if (seasonGap > 15)
    parts.push(`${seasonAdv} have been the stronger side across the season by a clear margin in both points and goal difference`)
  else if (seasonGap > 6)
    parts.push(`${seasonAdv} hold a slight edge in season-long form, though the gap is not commanding`)
  else
    parts.push(`the two sides are closely matched on season-long metrics — neither has a clear league-form advantage`)

  const formAdv = leader(f.form_ppg)
  const formGap = gap(f.form_ppg)
  const xgAdv   = leader(f.form_xgd)
  const xgGap   = gap(f.form_xgd)
  if (formAdv === xgAdv && formGap > 8 && xgGap > 8)
    parts.push(`${formAdv} are also in noticeably better recent form — winning more and creating better chances in the last five`)
  else if (formAdv !== xgAdv)
    parts.push(`recent form is mixed: ${formAdv} have picked up more points lately but ${xgAdv} have been the more dangerous side by chance quality`)
  else
    parts.push(`neither team has been convincingly better in their last five games`)

  const h2hAdv = leader(f.h2h)
  const h2hGap = gap(f.h2h)
  if (h2hGap > 20)
    parts.push(`historically ${h2hAdv} have dominated this fixture, which weighs noticeably on the final number`)
  else if (h2hGap > 8)
    parts.push(`the head-to-head record leans toward ${h2hAdv}, adding a modest push in their favour`)
  else
    parts.push(`the head-to-head record between the clubs is roughly even and adds little weight either way`)

  const favourite = homeWinPct > awayWinPct ? homeTeam : awayTeam
  const favPct    = Math.max(homeWinPct, awayWinPct)
  const isClose   = Math.abs(homeWinPct - awayWinPct) < 10
  if (isClose)
    parts.push(`home advantage gives ${homeTeam} a small boost, but overall this is a close call — the model sees it as nearly even with a ${drawPct}% chance of a draw`)
  else
    parts.push(`home advantage adds to ${homeTeam}'s side, leaving the model with ${favourite} as the ${favPct >= 55 ? 'clear' : 'narrow'} favourite at ${favPct}%`)

  return parts.map(p => p[0].toUpperCase() + p.slice(1)).join('. ') + '.'
}

function IncidentsSection({ matchId, isLive }) {
  const [incidents, setIncidents] = useState([])

  function load() {
    fetch(`${API}/match/${matchId}/incidents`)
      .then(r => r.ok ? r.json() : [])
      .then(setIncidents)
      .catch(() => {})
  }

  useEffect(() => {
    if (!matchId) return
    load()
    if (!isLive) return
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [matchId, isLive])

  if (!incidents.length) return null

  function incidentIcon(inc) {
    if (inc.type === 'goal') {
      if (inc.cls === 'ownGoal') return '⚽ OG'
      if (inc.cls === 'penalty') return '⚽ P'
      return '⚽'
    }
    if (inc.type === 'card') {
      if (inc.cls === 'red' || inc.cls === 'yellowRed') return '🟥'
      return '🟨'
    }
    if (inc.type === 'substitution') return '🔄'
    if (inc.type === 'var') {
      if (inc.cls === 'goalAwarded')  return 'VAR ✓'
      if (inc.cls === 'goalCancelled') return 'VAR ✗'
      return 'VAR'
    }
    return ''
  }

  return (
    <section className="pane-section incidents-section">
      {incidents.map((inc, i) => {
        if (inc.type === 'period') {
          return (
            <div key={i} className="incident-period">
              <span className="incident-period-label">{inc.text}</span>
              {inc.home_score != null &&
                <span className="incident-period-score">{inc.home_score} – {inc.away_score}</span>}
            </div>
          )
        }
        const side    = inc.is_home ? 'home' : 'away'
        const timeStr = inc.added_time ? `${inc.time}+${inc.added_time}'` : `${inc.time}'`
        return (
          <div key={i} className={`incident-row incident-row--${side}`}>
            <span className="incident-time">{timeStr}</span>
            <span className="incident-icon">{incidentIcon(inc)}</span>
            {inc.type === 'substitution' ? (
              <span className="incident-player">
                {inc.player_in} <span className="incident-sub-out">↓ {inc.player_out}</span>
              </span>
            ) : (
              <span className="incident-player">{inc.player}</span>
            )}
          </div>
        )
      })}
    </section>
  )
}

function PlayerAvatar({ playerId, name, rating }) {
  const [err, setErr] = useState(false)
  const ratingCls = !rating ? 'none' : rating >= 7.0 ? 'good' : rating >= 6.5 ? 'ok' : 'poor'
  const initials  = name?.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?'
  return (
    <div className="player-avatar-wrap">
      {!err
        ? <img src={`${SOFA_IMG}/player/${playerId}/image`} alt={name} className="player-img" onError={() => setErr(true)} />
        : <div className="player-initials">{initials}</div>
      }
      {rating && <span className={`player-rating player-rating--${ratingCls}`}>{rating.toFixed(1)}</span>}
    </div>
  )
}

function splitIntoRows(starters, formation) {
  if (!formation) return [starters]
  const parts = formation.split('-').map(Number)
  const rows  = [[starters[0]]]
  let idx = 1
  for (const count of parts) {
    rows.push(starters.slice(idx, idx + count))
    idx += count
  }
  return rows
}

function PitchSide({ side, team, data }) {
  if (!data) return null
  const { formation, starters, substitutes } = data
  const rows        = splitIntoRows(starters, formation)
  const orderedRows = [...rows].reverse()
  return (
    <div className={`lineup-side lineup-side--${side}`}>
      <div className="lineup-formation">{team} · {formation}</div>
      <div className={`lineup-pitch lineup-pitch--${side}`}>
        {orderedRows.map((row, ri) => (
          <div key={ri} className="lineup-row">
            {row.map(p => (
              <div key={p.id} className="lineup-player">
                <PlayerAvatar playerId={p.id} name={p.name} rating={p.rating} />
                <span className="player-name">{p.name}</span>
                <span className="player-jersey">{p.jersey}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="lineup-subs">
        <div className="lineup-subs-title">Substitutes</div>
        <div className="lineup-sub-list">
          {substitutes.map(p => (
            <div key={p.id} className="lineup-sub-item">
              <span className="sub-jersey">{p.jersey}</span>
              <span>{p.name}</span>
              {p.rating && <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--muted)' }}>{p.rating.toFixed(1)}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function LineupsTab({ matchId, homeTeam, awayTeam, isLive }) {
  const [lineups,  setLineups]  = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  useEffect(() => {
    if (!matchId) return
    let timer = null
    function fetchLineups(silent = false) {
      if (!silent) setLoading(true)
      fetch(`${API}/match/${matchId}/lineups`)
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(data => { setLineups(data); setLoading(false); setError(null) })
        .catch(() => {
          setLoading(false)
          if (!lineups) setError('Lineups not published yet — will check again in 60s.')
          timer = setTimeout(() => fetchLineups(true), 60_000)
        })
    }
    fetchLineups()
    return () => { if (timer) clearTimeout(timer) }
  }, [matchId])

  useEffect(() => {
    if (!isLive || !lineups) return
    const t = setInterval(() => {
      fetch(`${API}/match/${matchId}/lineups`)
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) setLineups(data) })
        .catch(() => {})
    }, 60_000)
    return () => clearInterval(t)
  }, [isLive, matchId, !!lineups])

  if (loading)  return <p className="lineup-msg">Loading lineups…</p>
  if (error)    return <p className="lineup-msg">{error}</p>
  if (!lineups) return null

  return (
    <div className="lineups-wrap">
      <PitchSide side="home" team={homeTeam} data={lineups.home} />
      <PitchSide side="away" team={awayTeam} data={lineups.away} />
    </div>
  )
}

const STAT_GROUP_ORDER = ['Match overview', 'Shots', 'Attack', 'Passes', 'Duels', 'Defending', 'Goalkeeping']

function parseStatVal(val) {
  if (val == null) return null
  const s   = String(val)
  const pct = s.match(/^(\d+(?:\.\d+)?)%$/)
  if (pct) return { display: s, numeric: parseFloat(pct[1]), isPct: true }
  const ratio = s.match(/\((\d+)%\)$/)
  if (ratio) return { display: s, numeric: parseFloat(ratio[1]), isPct: true }
  const num = parseFloat(s)
  if (!isNaN(num)) return { display: s, numeric: num, isPct: false }
  return { display: s, numeric: null, isPct: false }
}

function StatBar({ home, away }) {
  const h = parseStatVal(home)
  const a = parseStatVal(away)
  let hPct = 50, aPct = 50
  if (h?.numeric != null && a?.numeric != null) {
    if (h.isPct && a.isPct) {
      hPct = h.numeric; aPct = a.numeric
    } else {
      const total = h.numeric + a.numeric || 1
      hPct = Math.round((h.numeric / total) * 100)
      aPct = 100 - hPct
    }
  }
  return (
    <div className="ls-row">
      <span className="ls-val ls-val--home">{h?.display ?? '—'}</span>
      <div className="ls-bar">
        <div className="ls-bar-home" style={{ width: `${hPct}%` }} />
        <div className="ls-bar-away" style={{ width: `${aPct}%` }} />
      </div>
      <span className="ls-val ls-val--away">{a?.display ?? '—'}</span>
    </div>
  )
}

function LiveStatsPanel({ matchId, homeTeam, awayTeam, isLive }) {
  const [stats,    setStats]    = useState(null)
  const [period,   setPeriod]   = useState('ALL')
  const [expanded, setExpanded] = useState({})

  function load() {
    fetch(`${API}/match/${matchId}/stats`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setStats(data) })
      .catch(() => {})
  }

  useEffect(() => {
    if (!matchId) return
    load()
    if (!isLive) return
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [matchId, isLive])

  if (!stats) return null

  const groups  = stats[period] || stats['ALL'] || []
  const periods = Object.keys(stats).filter(p => stats[p]?.length > 0)
  const ordered = STAT_GROUP_ORDER.filter(n => groups.some(g => g.name === n))

  return (
    <section className="pane-section ls-section">
      <div className="ls-header">
        <div className="section-head" style={{ paddingBottom: 0 }}>
          <span className="dot" />
          <span>Match Stats</span>
        </div>
        {periods.length > 1 && (
          <div className="ls-period-tabs">
            {periods.map(p => (
              <button
                key={p}
                className={`ls-period-tab ${period === p ? 'ls-period-tab--active' : ''}`}
                onClick={() => setPeriod(p)}
              >
                {p === 'ALL' ? 'All' : p === '1ST' ? '1st Half' : '2nd Half'}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="ls-col-heads">
        <span style={{ color: 'var(--home)' }}>{homeTeam}</span>
        <span />
        <span style={{ color: 'var(--away)' }}>{awayTeam}</span>
      </div>

      {ordered.map(groupName => {
        const group  = groups.find(g => g.name === groupName)
        if (!group) return null
        const isOpen = expanded[groupName] !== false
        return (
          <div key={groupName} className="ls-group">
            <button
              className="ls-group-header"
              onClick={() => setExpanded(e => ({ ...e, [groupName]: !isOpen }))}
            >
              <span>{groupName}</span>
              <span className="ls-chevron">{isOpen ? '▴' : '▾'}</span>
            </button>
            {isOpen && group.items.map((item, i) => (
              <div key={i} className="ls-item">
                <span className="ls-item-label">{item.label}</span>
                <StatBar home={item.home} away={item.away} />
              </div>
            ))}
          </div>
        )
      })}
    </section>
  )
}

function HalftimePanel({ match }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!match?.match_id || match.status_code !== 31) return
    if (match.home_score == null || match.away_score == null) return
    const homeHt = match.home_period1 ?? match.home_score
    const awayHt = match.away_period1 ?? match.away_score
    setLoading(true)
    const params = new URLSearchParams({
      home_team_id:    match.home_team_id,
      away_team_id:    match.away_team_id,
      competition_key: match.competition_key,
      home_ht:         homeHt,
      away_ht:         awayHt,
    })
    fetch(`${API}/match/${match.match_id}/halftime-analysis?${params}`)
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [match?.match_id, match?.status_code])

  if (match?.status_code !== 31) return null

  return (
    <section className="pane-section ht-panel">
      <div className="section-head">
        <span className="dot" style={{ background: 'var(--live)' }} />
        <span>Half Time</span>
      </div>

      {loading && <p className="pane-msg" style={{ padding: '8px 0', fontSize: 12 }}>Recalculating…</p>}

      {data && (
        <>
          <div className="ht-score-row">
            <span className="ht-score-team">{match.home_team}</span>
            <span className="ht-score-num">{data.home_ht} – {data.away_ht}</span>
            <span className="ht-score-team ht-score-team--right">{match.away_team}</span>
          </div>

          {data.first_half_stats && Object.keys(data.first_half_stats).length > 0 && (() => {
            const s = data.first_half_stats
            const rows = [
              { label: 'xG',              home: s.expected_goals?.home,    away: s.expected_goals?.away },
              { label: 'Possession',      home: s.ball_possession?.home,   away: s.ball_possession?.away },
              { label: 'Shots',           home: s.total_shots?.home,       away: s.total_shots?.away },
              { label: 'Shots on Target', home: s.shots_on_target?.home,   away: s.shots_on_target?.away },
            ].filter(r => r.home != null || r.away != null)
            if (!rows.length) return null
            return (
              <div className="ht-stats-block">
                <div className="ht-stats-title">1st Half Stats</div>
                {rows.map((r, i) => (
                  <div key={i} className="stat-row">
                    <span>{r.home ?? '—'}</span>
                    <span className="stat-label">{r.label}</span>
                    <span>{r.away ?? '—'}</span>
                  </div>
                ))}
              </div>
            )
          })()}

          <div className="ht-probs-block">
            <div className="ht-probs-title">2nd Half Outlook</div>
            <div className="ht-probs-row">
              {[
                { label: match.home_team, pct: data.ht_recalc.home_win_pct, delta: data.delta.home_win, color: 'var(--home)' },
                { label: 'Draw',          pct: data.ht_recalc.draw_pct,     delta: data.delta.draw,     color: 'var(--muted)' },
                { label: match.away_team, pct: data.ht_recalc.away_win_pct, delta: data.delta.away_win, color: 'var(--away)' },
              ].map(({ label, pct, delta, color }) => (
                <div key={label} className="ht-prob-item">
                  <div className="ht-prob-pct" style={{ color }}>{pct}%</div>
                  <div className="ht-prob-label">{label}</div>
                  {delta !== 0 && (
                    <div className={`ht-prob-delta ${delta > 0 ? 'delta--up' : 'delta--down'}`}>
                      {delta > 0 ? '+' : ''}{delta}%
                    </div>
                  )}
                </div>
              ))}
            </div>
            {data.ht_recalc.xg_correction !== 0 && (
              <div className="ht-xg-note">
                xG correction applied: {data.ht_recalc.xg_correction > 0 ? '+' : ''}{data.ht_recalc.xg_correction}% toward {match.home_team}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}

function GoalTimingSection({ homeTeam, awayTeam, homeTiming, awayTiming }) {
  if (!homeTiming && !awayTiming) return null
  const h = homeTiming || {}
  const a = awayTiming || {}

  function HalfBar({ homeVal, awayVal }) {
    const total = (homeVal || 0) + (awayVal || 0) || 1
    const hPct  = Math.round(((homeVal || 0) / total) * 100)
    return (
      <div className="timing-bar">
        <div className="timing-bar-home" style={{ width: `${hPct}%` }} />
        <div className="timing-bar-away" style={{ width: `${100 - hPct}%` }} />
      </div>
    )
  }

  function HalfBadge({ val, better, half }) {
    return (
      <span className={`timing-half-badge ${better === half ? 'timing-half-badge--best' : ''}`}>
        {half === 'first' ? '1H' : '2H'} {val != null ? val.toFixed(2) : '—'}
      </span>
    )
  }

  return (
    <section className="pane-section">
      <div className="section-head">
        <span className="dot" />
        <span>Goal Timing</span>
      </div>
      <div className="timing-col-heads">
        <span style={{ color: 'var(--home)' }}>{homeTeam}</span>
        <span />
        <span style={{ color: 'var(--away)' }}>{awayTeam}</span>
      </div>

      <div className="timing-block">
        <div className="timing-block-label">Goals Scored / game</div>
        <div className="timing-row">
          <div className="timing-halves">
            <HalfBadge val={h.scored_p1_avg} better={h.stronger_half} half="first" />
            <HalfBadge val={h.scored_p2_avg} better={h.stronger_half} half="second" />
          </div>
          <HalfBar homeVal={(h.scored_p1_avg||0)+(h.scored_p2_avg||0)} awayVal={(a.scored_p1_avg||0)+(a.scored_p2_avg||0)} />
          <div className="timing-halves timing-halves--right">
            <HalfBadge val={a.scored_p1_avg} better={a.stronger_half} half="first" />
            <HalfBadge val={a.scored_p2_avg} better={a.stronger_half} half="second" />
          </div>
        </div>
      </div>

      <div className="timing-block">
        <div className="timing-block-label">Goals Conceded / game</div>
        <div className="timing-row">
          <div className="timing-halves">
            <HalfBadge val={h.conceded_p1_avg} better={h.weaker_half === 'first' ? 'second' : 'first'} half="first" />
            <HalfBadge val={h.conceded_p2_avg} better={h.weaker_half === 'second' ? 'first' : 'second'} half="second" />
          </div>
          <HalfBar homeVal={(h.conceded_p1_avg||0)+(h.conceded_p2_avg||0)} awayVal={(a.conceded_p1_avg||0)+(a.conceded_p2_avg||0)} />
          <div className="timing-halves timing-halves--right">
            <HalfBadge val={a.conceded_p1_avg} better={a.weaker_half === 'first' ? 'second' : 'first'} half="first" />
            <HalfBadge val={a.conceded_p2_avg} better={a.weaker_half === 'second' ? 'first' : 'second'} half="second" />
          </div>
        </div>
      </div>

      {h.matches && <div className="timing-sample">Based on last {h.matches} matches</div>}
    </section>
  )
}

function RefereeCard({ matchId, homeTeamId, awayTeamId, homeTeam, awayTeam }) {
  const [ref,  setRef]  = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!matchId || !homeTeamId || !awayTeamId) return
    const params = new URLSearchParams({ home_team_id: homeTeamId, away_team_id: awayTeamId })
    fetch(`${API}/match/${matchId}/referee?${params}`)
      .then(r => r.ok ? r.json() : null)
      .then(setRef)
      .catch(() => {})
  }, [matchId])

  if (!ref) return null

  const cardRate = ref.total_games > 0
    ? `${ref.avg_yellows_per_game} 🟨 / ${ref.avg_reds_per_game} 🟥 per game`
    : null

  function RefGame({ g }) {
    const d = g.date ? new Date(g.date * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
    return (
      <div className="ref-game-row">
        <span className="ref-game-date">{d}</span>
        <span className="ref-game-teams">{g.home_team} <strong>{g.home_score ?? '?'}–{g.away_score ?? '?'}</strong> {g.away_team}</span>
        <span className="ref-game-comp">{g.competition}</span>
      </div>
    )
  }

  return (
    <section className="pane-section ref-section">
      <button className="ref-header" onClick={() => setOpen(o => !o)}>
        <span className="ref-icon">🏴</span>
        <div className="ref-header-info">
          <span className="ref-name">{ref.name}</span>
          <span className="ref-country">{ref.country}</span>
        </div>
        <div className="ref-summary-stats">
          <span>{ref.total_games} games</span>
          {cardRate && <span className="ref-card-rate">{cardRate}</span>}
        </div>
        <span className="ref-chevron">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="ref-body">
          {ref.competition_stats.length > 0 && (
            <div className="ref-comp-stats">
              <div className="ref-comp-header">
                <span>Competition</span><span>Apps</span><span>🟨</span><span>🟥</span><span>Avg 🟨</span>
              </div>
              {ref.competition_stats.map((s, i) => (
                <div key={i} className="ref-comp-row">
                  <span>{s.competition}</span>
                  <span>{s.appearances}</span>
                  <span>{s.yellow_cards}</span>
                  <span>{s.red_cards + s.yellow_red_cards}</span>
                  <span>{s.avg_yellows}</span>
                </div>
              ))}
            </div>
          )}
          {ref.last_5_games.length > 0 && (
            <div className="ref-games-block">
              <div className="ref-games-title">Last 5 games</div>
              {ref.last_5_games.map((g, i) => <RefGame key={i} g={g} />)}
            </div>
          )}
          {(ref.home_team_history.length > 0 || ref.away_team_history.length > 0) && (
            <div className="ref-team-history">
              {ref.home_team_history.length > 0 && (
                <div className="ref-games-block">
                  <div className="ref-games-title">With {homeTeam}</div>
                  {ref.home_team_history.map((g, i) => <RefGame key={i} g={g} />)}
                </div>
              )}
              {ref.away_team_history.length > 0 && (
                <div className="ref-games-block">
                  <div className="ref-games-title">With {awayTeam}</div>
                  {ref.away_team_history.map((g, i) => <RefGame key={i} g={g} />)}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function StatRow({ label, home, away }) {
  return (
    <div className="stat-row">
      <span>{home ?? '—'}</span>
      <span className="stat-label">{label}</span>
      <span style={{ textAlign: 'right' }}>{away ?? '—'}</span>
    </div>
  )
}

function CompareRow({ label, homeVal, awayVal, lowerIsBetter = false }) {
  const h = parseFloat(homeVal), a = parseFloat(awayVal)
  if (isNaN(h) && isNaN(a)) return null
  const hv = isNaN(h) ? 0 : h, av = isNaN(a) ? 0 : a
  const total  = hv + av || 1
  const hPct   = Math.round((hv / total) * 100)
  const aPct   = 100 - hPct
  const hLeads = lowerIsBetter ? hv <= av : hv >= av
  return (
    <div className="cmp-row">
      <span className={`cmp-val cmp-val--home ${hLeads ? 'cmp-val--win' : ''}`}>{homeVal ?? '—'}</span>
      <div className="cmp-mid">
        <span className="cmp-label">{label}</span>
        <div className="cmp-bar">
          <div className="cmp-bar-home" style={{ width: `${hPct}%` }} />
          <div className="cmp-bar-away" style={{ width: `${aPct}%` }} />
        </div>
      </div>
      <span className={`cmp-val cmp-val--away ${!hLeads ? 'cmp-val--win' : ''}`}>{awayVal ?? '—'}</span>
    </div>
  )
}

function CompareGroup({ title, children }) {
  return (
    <section className="pane-section">
      <div className="section-head"><span className="dot" /><span>{title}</span></div>
      <div className="cmp-table">{children}</div>
    </section>
  )
}

function CompareTab({ homeTeam, awayTeam, homeSt, awaySt }) {
  return (
    <>
      <div className="cmp-header">
        <span style={{ color: 'var(--home)' }}>{homeTeam}</span>
        <span />
        <span style={{ color: 'var(--away)' }}>{awayTeam}</span>
      </div>
      <CompareGroup title="Attacking">
        <CompareRow label="Goals Scored"     homeVal={homeSt.goals_scored}        awayVal={awaySt.goals_scored} />
        <CompareRow label="Shots / Game"     homeVal={homeSt.shots_per_game}      awayVal={awaySt.shots_per_game} />
        <CompareRow label="On Target / Game" homeVal={homeSt.sot_per_game}        awayVal={awaySt.sot_per_game} />
        <CompareRow label="Big Chances"      homeVal={homeSt.big_chances_created} awayVal={awaySt.big_chances_created} />
        <CompareRow label="Assists"          homeVal={homeSt.assists}             awayVal={awaySt.assists} />
      </CompareGroup>
      <CompareGroup title="Possession & Passing">
        <CompareRow label="Avg Possession %" homeVal={homeSt.avg_possession} awayVal={awaySt.avg_possession} />
        <CompareRow label="Pass Accuracy %"  homeVal={homeSt.pass_accuracy}  awayVal={awaySt.pass_accuracy} />
      </CompareGroup>
      <CompareGroup title="Defensive">
        <CompareRow label="Goals Conceded" homeVal={homeSt.goals_conceded} awayVal={awaySt.goals_conceded} lowerIsBetter />
        <CompareRow label="Clean Sheets"   homeVal={homeSt.clean_sheets}   awayVal={awaySt.clean_sheets} />
        <CompareRow label="Tackles"        homeVal={homeSt.tackles}        awayVal={awaySt.tackles} />
        <CompareRow label="Interceptions"  homeVal={homeSt.interceptions}  awayVal={awaySt.interceptions} />
      </CompareGroup>
      <CompareGroup title="Discipline">
        <CompareRow label="Yellow Cards" homeVal={homeSt.yellow_cards} awayVal={awaySt.yellow_cards} lowerIsBetter />
        <CompareRow label="Red Cards"    homeVal={homeSt.red_cards}    awayVal={awaySt.red_cards}    lowerIsBetter />
      </CompareGroup>
    </>
  )
}

// ── ConfidenceRow ────────────────────────────────────────────────
function ConfidenceRow({ confidence }) {
  const level = confidence === 'high' ? 5 : confidence === 'medium' ? 3 : 1
  return (
    <div className="confidence-row">
      <div className="conf-bars">
        {[1, 2, 3, 4, 5].map(i => (
          <span key={i} className={`conf-bar ${i <= level ? 'is-on' : ''}`} />
        ))}
      </div>
      <span className="conf-label">Confidence</span>
      <span className="conf-value">{confidence}</span>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────
export default function AnalysisPane({ match, onClose }) {
  const [preview,          setPreview]          = useState(null)
  const [loadingPrev,      setLoadingPrev]      = useState(false)
  const [notes,            setNotes]            = useState('')
  const [analyzing,        setAnalyzing]        = useState(false)
  const [result,           setResult]           = useState(null)
  const [error,            setError]            = useState(null)
  const [activeTab,        setActiveTab]        = useState('overview')
  const [savedPrediction,  setSavedPrediction]  = useState(null)

  useEffect(() => {
    setPreview(null); setResult(null); setNotes(''); setError(null)
    setActiveTab('overview'); setSavedPrediction(null)
    if (match) fetchPreview()
  }, [match?.match_id])

  useEffect(() => {
    if (!match?.match_id) return
    fetch(`${API}/match/${match.match_id}/prediction`)
      .then(r => r.ok ? r.json() : null)
      .then(saved => {
        if (saved) {
          setSavedPrediction(saved)
          setNotes(saved.user_notes || '')
          setResult({
            human_adjusted: {
              home_win_pct: saved.human_home_win,
              draw_pct:     saved.human_draw,
              away_win_pct: saved.human_away_win,
            },
            delta: {
              home_win: Math.round((saved.human_home_win - saved.data_home_win) * 10) / 10,
              draw:     Math.round((saved.human_draw     - saved.data_draw)     * 10) / 10,
              away_win: Math.round((saved.human_away_win - saved.data_away_win) * 10) / 10,
            },
            key_battleground: saved.key_battleground,
            what_to_watch:    saved.what_to_watch,
            upset_condition:  saved.upset_condition,
            summary:          saved.ai_summary,
            analysis_score:   saved.analysis_score,
          })
        }
      })
      .catch(() => {})
  }, [match?.match_id])

  async function fetchPreview() {
    if (!match.competition_key) {
      setError('Analysis is only available for tracked competitions (Premier League, Champions League, Süper Lig, etc.).')
      return
    }
    setLoadingPrev(true)
    try {
      const params = new URLSearchParams({
        home_team_id:    match.home_team_id,
        away_team_id:    match.away_team_id,
        competition_key: match.competition_key,
      })
      const r = await fetch(`${API}/match/${match.match_id}/preview?${params}`)
      if (!r.ok) throw new Error()
      setPreview(await r.json())
    } catch {
      setError('Could not load match data.')
    } finally {
      setLoadingPrev(false)
    }
  }

  async function runAnalysis() {
    setAnalyzing(true); setError(null)
    try {
      const r = await fetch(`${API}/match/${match.match_id}/analyze`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          home_team_id:    match.home_team_id,
          away_team_id:    match.away_team_id,
          home_team:       match.home_team,
          away_team:       match.away_team,
          competition_key: match.competition_key,
          match_date:      match.start_timestamp
            ? new Date(match.start_timestamp * 1000).toISOString().slice(0, 10)
            : null,
          user_notes: notes,
        }),
      })
      if (!r.ok) throw new Error()
      const res = await r.json()
      setResult(res)
      try {
        const pr = await fetch(`${API}/match/${match.match_id}/prediction`)
        if (pr.ok) { const saved = await pr.json(); if (saved) setSavedPrediction(saved) }
      } catch {}
    } catch {
      setError('Analysis failed. Check the backend is running.')
    } finally {
      setAnalyzing(false)
    }
  }

  // ── Empty state ──────────────────────────────────────────────
  if (!match) {
    return (
      <div className="pane pane-empty">
        <div className="glyph"><span className="ico">⚽</span></div>
        <div>
          <h2>Select a match to analyze</h2>
          <p>Pick a fixture from the feed to load live stats, lineups, head-to-head data, and AI-driven insights.</p>
        </div>
        <div className="hint-row">
          <span>Click any match</span><span>in the feed to begin</span>
        </div>
      </div>
    )
  }

  const homeInj = preview?.home_injuries || []
  const awayInj = preview?.away_injuries || []
  const h2h     = preview?.h2h || []
  const homeSt  = preview?.home_season || {}
  const awaySt  = preview?.away_season || {}
  const isLive  = match.status_code != null && match.status_code !== 0 && match.status_code !== 100

  // Win prob values — use human-adjusted if result is available
  const probHome = result ? result.human_adjusted.home_win_pct : (preview?.data_probs?.home_win_pct ?? 0)
  const probDraw = result ? result.human_adjusted.draw_pct     : (preview?.data_probs?.draw_pct     ?? 0)
  const probAway = result ? result.human_adjusted.away_win_pct : (preview?.data_probs?.away_win_pct ?? 0)

  return (
    <div className="pane">

      {/* ── Fixed header ── */}
      <div className="pane-head">
        <div className="pane-head-meta">
          <span className="crumb">
            {match.competition_key?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Match'}
          </span>
          <span className="sep">/</span>
          <span className="stage">{formatDate(match.start_timestamp)}</span>
          <span className="right">
            <button className="pane-close" onClick={onClose}>✕</button>
          </span>
        </div>

        <div className="match-hero">
          {/* Home team */}
          <div className="team-block home">
            <TeamCrest teamId={match.home_team_id} name={match.home_team} side="home" />
            <div>
              <div className="team-name">{match.home_team}</div>
              <div className="team-meta">
                {preview?.home_season?.position != null &&
                  <span className="pos">#{preview.home_season.position}</span>}
                {preview?.home_last5?.length > 0 && (
                  <span className="form">
                    {preview.home_last5.map((m, i) => (
                      <span key={i} className={`form-pip ${m.result}`} />
                    ))}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Score / VS */}
          <div className="match-mid">
            <div className={`match-status ${isLive ? 'is-live' : match.status_code === 100 ? 'is-final' : ''}`}>
              {isLive && <span className="live-pip" />}
              {isLive ? (match.time_str || 'Live') : match.status_code === 100 ? 'Full time' : `KO · ${
                match.start_timestamp
                  ? new Date(match.start_timestamp * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
                  : '--:--'
              }`}
            </div>

            {match.home_score != null && match.away_score != null ? (
              <div className={`match-score ${isLive ? 'is-live' : ''}`}>
                <span>{match.home_score}</span>
                <span className="dash">–</span>
                <span>{match.away_score}</span>
              </div>
            ) : (
              <div className="match-score vs">VS</div>
            )}
          </div>

          {/* Away team */}
          <div className="team-block away">
            <TeamCrest teamId={match.away_team_id} name={match.away_team} side="away" />
            <div style={{ textAlign: 'right' }}>
              <div className="team-name">{match.away_team}</div>
              <div className="team-meta" style={{ justifyContent: 'flex-end' }}>
                {preview?.away_last5?.length > 0 && (
                  <span className="form">
                    {preview.away_last5.map((m, i) => (
                      <span key={i} className={`form-pip ${m.result}`} />
                    ))}
                  </span>
                )}
                {preview?.away_season?.position != null &&
                  <span className="pos">#{preview.away_season.position}</span>}
              </div>
            </div>
          </div>
        </div>

        {/* Win probability ribbon */}
        {(preview?.data_probs || result) && (
          <div className="winprob">
            <div className="winprob-bar">
              <div className="winprob-seg home" style={{ flex: probHome }} />
              <div className="winprob-seg draw" style={{ flex: probDraw }} />
              <div className="winprob-seg away" style={{ flex: probAway }} />
            </div>
            <div className="winprob-labels">
              <div className="winprob-cell home">
                <span className="winprob-key">Home win</span>
                <span className="winprob-pct num">{probHome}%</span>
                {result && <DeltaPill val={result.delta.home_win} />}
              </div>
              <div className="winprob-cell draw">
                <span className="winprob-key">Draw</span>
                <span className="winprob-pct num">{probDraw}%</span>
                {result && <DeltaPill val={result.delta.draw} />}
              </div>
              <div className="winprob-cell away">
                <span className="winprob-key">Away win</span>
                <span className="winprob-pct num">{probAway}%</span>
                {result && <DeltaPill val={result.delta.away_win} />}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Tab bar ── */}
      {preview && !loadingPrev && (
        <div className="pane-tabs">
          <button className={`pane-tab ${activeTab === 'overview' ? 'is-active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
          <button className={`pane-tab ${activeTab === 'lineups'  ? 'is-active' : ''}`} onClick={() => setActiveTab('lineups')}>Lineups</button>
          <button className={`pane-tab ${activeTab === 'compare'  ? 'is-active' : ''}`} onClick={() => setActiveTab('compare')}>Compare</button>
          <button className={`pane-tab ${activeTab === 'notes'    ? 'is-active' : ''}`} onClick={() => setActiveTab('notes')}>My Analysis</button>
        </div>
      )}

      {/* ── Scrollable body ── */}
      <div className="pane-body">
        {loadingPrev && <p className="pane-msg">Loading match data…</p>}
        {error && <p className="pane-msg pane-msg--error">{error}</p>}

        {preview && !loadingPrev && (

          <>
            {/* ── OVERVIEW TAB ── */}
            {activeTab === 'overview' && (
              <>
                <HalftimePanel match={match} />

                {/* Season stats */}
                <section className="pane-section">
                  <div className="section-head"><span className="dot" /><span>Season Stats</span></div>
                  <div className="stat-table">
                    <div className="stat-table-heads">
                      <span style={{ color: 'var(--home)' }}>{match.home_team}</span>
                      <span />
                      <span style={{ color: 'var(--away)', textAlign: 'right' }}>{match.away_team}</span>
                    </div>
                    <StatRow label="PPG"     home={homeSt.points_per_game} away={awaySt.points_per_game} />
                    <StatRow label="Goals F" home={homeSt.goals_scored}    away={awaySt.goals_scored} />
                    <StatRow label="Goals A" home={homeSt.goals_conceded}  away={awaySt.goals_conceded} />
                    <StatRow label="Played"  home={homeSt.matches_played}  away={awaySt.matches_played} />
                  </div>
                </section>

                {/* Last 5 */}
                <section className="pane-section">
                  <div className="section-head"><span className="dot" /><span>Last 5 Results</span></div>
                  <div className="form-strip">
                    <div className="form-side">
                      {(preview.home_last5 || []).map((m, i) => (
                        <span key={i} className={`form-tile ${m.result}`}>{m.result}</span>
                      ))}
                    </div>
                    <span className="form-divider">VS</span>
                    <div className="form-side away">
                      {(preview.away_last5 || []).map((m, i) => (
                        <span key={i} className={`form-tile ${m.result}`}>{m.result}</span>
                      ))}
                    </div>
                  </div>
                </section>

                {/* Goal Timing */}
                <GoalTimingSection
                  homeTeam={match.home_team}
                  awayTeam={match.away_team}
                  homeTiming={preview.home_goal_timing}
                  awayTiming={preview.away_goal_timing}
                />

                {/* H2H */}
                {h2h.length > 0 && (
                  <section className="pane-section">
                    <div className="section-head"><span className="dot" /><span>Head to Head</span></div>
                    <div>
                      {h2h.slice(0, 5).map((m, i) => (
                        <div key={i} className="h2h-row">
                          <span className="h2h-date">{formatH2HDate(m.start_timestamp)}</span>
                          <span className="h2h-team-h">{m.home_team}</span>
                          <span className="h2h-score">{m.score}</span>
                          <span className="h2h-team-a">{m.away_team}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Referee */}
                <RefereeCard
                  matchId={match.match_id}
                  homeTeamId={match.home_team_id}
                  awayTeamId={match.away_team_id}
                  homeTeam={match.home_team}
                  awayTeam={match.away_team}
                />

                {/* Injuries */}
                {(homeInj.length > 0 || awayInj.length > 0) && (
                  <section className="pane-section">
                    <div className="section-head"><span className="dot" /><span>Missing Players</span></div>
                    <div className="injury-cols">
                      <div className="injury-col">
                        {homeInj.map((p, i) => (
                          <div key={i} className="injury-item">
                            <span className="injury-name">{p.name}</span>
                            <span className="injury-type">{p.injury_type || '?'}</span>
                          </div>
                        ))}
                        {homeInj.length === 0 && <span className="injury-none">None</span>}
                      </div>
                      <div className="injury-col injury-col--right">
                        {awayInj.map((p, i) => (
                          <div key={i} className="injury-item injury-item--right">
                            <span className="injury-type">{p.injury_type || '?'}</span>
                            <span className="injury-name">{p.name}</span>
                          </div>
                        ))}
                        {awayInj.length === 0 && <span className="injury-none">None</span>}
                      </div>
                    </div>
                  </section>
                )}

                {/* Data model prediction */}
                {preview.data_probs && (
                  <section className="pane-section">
                    <div className="section-head"><span className="dot" /><span>Data Model Prediction</span></div>
                    <div className="market">
                      <MarketRow label={match.home_team} pct={preview.data_probs.home_win_pct} colorClass="home" delta={result?.delta?.home_win ?? null} />
                      <MarketRow label="Draw"            pct={preview.data_probs.draw_pct}     colorClass="draw" delta={result?.delta?.draw     ?? null} />
                      <MarketRow label={match.away_team} pct={preview.data_probs.away_win_pct} colorClass="away" delta={result?.delta?.away_win ?? null} />
                    </div>
                    <ConfidenceRow confidence={preview.data_probs.confidence} />

                    {/* Statistical Reasoning */}
                    <div className="reasoning-title">Statistical Reasoning</div>
                    <div className="reasoning-grid">
                      {[
                        { key: 'season_ppg', label: 'Season Form (PPG)' },
                        { key: 'season_xgd', label: 'Season xG Diff' },
                        { key: 'form_ppg',   label: 'Last 5 Form' },
                        { key: 'form_xgd',   label: 'Last 5 xG' },
                        { key: 'h2h',        label: 'Head to Head' },
                        { key: 'home_adv',   label: 'Home / Away' },
                      ].map(({ key, label }) => {
                        const hVal = preview.data_probs.factors?.home?.[key]
                        const aVal = preview.data_probs.factors?.away?.[key]
                        if (hVal == null && aVal == null) return null
                        const h     = hVal ?? 0.5, a = aVal ?? 0.5
                        const total = h + a || 1
                        const hPct  = Math.round((h / total) * 100)
                        const aPct  = 100 - hPct
                        return (
                          <div key={key} className="reasoning-row">
                            <span className="reasoning-label">{label}</span>
                            <div className="reasoning-bar">
                              <div className="reasoning-home" style={{ width: `${hPct}%` }} />
                              <div className="reasoning-away" style={{ width: `${aPct}%` }} />
                            </div>
                            <div className="reasoning-vals">
                              <span style={{ color: 'var(--home)' }}>{hPct}%</span>
                              <span style={{ color: 'var(--away)' }}>{aPct}%</span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {(() => {
                      const summary = buildReasoningSummary(
                        preview.data_probs.factors,
                        match.home_team, match.away_team,
                        preview.data_probs.home_win_pct,
                        preview.data_probs.draw_pct,
                        preview.data_probs.away_win_pct,
                      )
                      return summary ? <p className="reasoning-summary">{summary}</p> : null
                    })()}
                  </section>
                )}

                {/* Human-adjusted result */}
                {result && (
                  <section className="pane-section">
                    <div className="section-head">
                      <span className="dot" />
                      <span>Data + Your Notes</span>
                      <span className="delta-legend">vs data model</span>
                    </div>
                    <div className="ai-insights">
                      {[
                        { icon: '⚔️', label: 'Key Battleground', val: result.key_battleground },
                        { icon: '👁️', label: 'What to Watch',    val: result.what_to_watch },
                        { icon: '⚡', label: 'Upset Condition',  val: result.upset_condition },
                        { icon: '📝', label: 'Summary',          val: result.summary },
                      ].map(({ icon, label, val }) => val && (
                        <div key={label} className="insight">
                          <div className="insight-icon">{icon}</div>
                          <div>
                            <div className="insight-label">{label}</div>
                            <div className="insight-text">{val}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Notes + Analyze (pre-result) */}
                {!result && (
                  <section className="pane-section">
                    <div className="section-head"><span className="dot" /><span>Your Analysis Notes</span></div>
                    <div className="notes-card">
                      <textarea
                        className="notes-input"
                        placeholder="What have you noticed watching these teams lately? Injuries, form, tactical trends…"
                        value={notes}
                        onChange={e => setNotes(e.target.value)}
                        rows={4}
                      />
                      <div className="notes-toolbar">
                        <span className="notes-count">{notes.length} chars</span>
                      </div>
                    </div>
                    <button className="btn btn--primary btn--block" onClick={runAnalysis} disabled={analyzing}>
                      {analyzing ? 'Analysing…' : '🧠 Add Your Analysis'}
                    </button>
                  </section>
                )}

                {/* Re-analyse + score (post-result) */}
                {result && (
                  <section className="pane-section">
                    {result.analysis_score != null && (
                      <div className="analysis-score">
                        <div>
                          <div className="label">Your analysis score</div>
                          <div className="text">Based on your notes quality and relevance</div>
                        </div>
                        <div
                          className="val"
                          style={{
                            color: result.analysis_score >= 7 ? 'var(--win)'
                                 : result.analysis_score >= 4 ? 'var(--warn)'
                                 : 'var(--live)'
                          }}
                        >
                          {result.analysis_score.toFixed(1)}
                        </div>
                      </div>
                    )}
                    <button className="btn btn--ghost" onClick={() => setResult(null)}>
                      ↩ Re-analyse with new notes
                    </button>
                  </section>
                )}

                {/* Incidents — live or finished */}
                {match.status_code !== 0 && (
                  <IncidentsSection matchId={match.match_id} isLive={isLive} />
                )}

                {/* Live stats — live or finished */}
                {match.status_code !== 0 && (
                  <LiveStatsPanel
                    matchId={match.match_id}
                    homeTeam={match.home_team}
                    awayTeam={match.away_team}
                    isLive={isLive}
                  />
                )}
              </>
            )}

            {/* ── MY ANALYSIS TAB ── */}
            {activeTab === 'notes' && (() => {
              const isPreKickoff = match.status_code === 0
              const insights = savedPrediction ? [
                { icon: '⚔️', label: 'Key Battleground', val: savedPrediction.key_battleground },
                { icon: '👁️', label: 'What to Watch',    val: savedPrediction.what_to_watch },
                { icon: '⚡', label: 'Upset Condition',  val: savedPrediction.upset_condition },
                { icon: '📝', label: 'Summary',          val: savedPrediction.ai_summary },
              ].filter(i => i.val) : []
              return (
                <>
                  <section className="pane-section">
                    <div className="section-head">
                      <span className="dot" />
                      <span>Your Analysis</span>
                      {!isPreKickoff && <span className="delta-legend">view only — match started</span>}
                    </div>
                    {!savedPrediction ? (
                      <p className="pane-msg" style={{ padding: '8px 0' }}>No analysis saved yet. Add notes in the Overview tab.</p>
                    ) : isPreKickoff ? (
                      <>
                        <div className="notes-card">
                          <textarea
                            className="notes-input"
                            value={notes}
                            onChange={e => setNotes(e.target.value)}
                            rows={8}
                          />
                          <div className="notes-toolbar">
                            <span className="notes-count">{notes.length} chars</span>
                          </div>
                        </div>
                        <button className="btn btn--primary btn--block" onClick={runAnalysis} disabled={analyzing}>
                          {analyzing ? 'Analysing…' : '🧠 Re-analyze'}
                        </button>
                      </>
                    ) : (
                      <div className="notes-readonly">{savedPrediction.user_notes}</div>
                    )}
                  </section>
                  {insights.length > 0 && (
                    <section className="pane-section">
                      <div className="section-head"><span className="dot" /><span>AI Insights</span></div>
                      <div className="ai-insights">
                        {insights.map(({ icon, label, val }) => (
                          <div key={label} className="insight">
                            <div className="insight-icon">{icon}</div>
                            <div>
                              <div className="insight-label">{label}</div>
                              <div className="insight-text">{val}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                </>
              )
            })()}

            {/* ── LINEUPS TAB ── */}
            {activeTab === 'lineups' && (
              <LineupsTab
                matchId={match.match_id}
                homeTeam={match.home_team}
                awayTeam={match.away_team}
                isLive={isLive}
              />
            )}

            {/* ── COMPARE TAB ── */}
            {activeTab === 'compare' && (
              <CompareTab
                homeTeam={match.home_team}
                awayTeam={match.away_team}
                homeSt={homeSt}
                awaySt={awaySt}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}
