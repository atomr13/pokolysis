import { useState, useEffect, useRef } from 'react'
import './UserMenu.css'

const API = 'http://localhost:8002'
const USER_ID = 1

export default function UserMenu() {
  const [open, setOpen]   = useState(false)
  const [user, setUser]   = useState(null)
  const ref               = useRef(null)

  useEffect(() => {
    fetch(`${API}/user/${USER_ID}`)
      .then(r => r.json())
      .then(setUser)
      .catch(() => {})
  }, [])

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  if (!user) return null

  const avgScore  = user.avg_score != null ? user.avg_score.toFixed(1) : '—'
  const scoreColor = user.avg_score == null
    ? 'var(--muted)'
    : user.avg_score >= 7   ? 'var(--green)'
    : user.avg_score >= 4   ? 'var(--yellow)'
    : 'var(--live)'

  return (
    <div className="user-menu" ref={ref}>
      <button className="user-trigger" onClick={() => setOpen(o => !o)}>
        <span className="user-avatar">{user.nickname[0].toUpperCase()}</span>
        <span className="user-nick">{user.nickname}</span>
        <span className="user-score-pill" style={{ color: scoreColor }}>
          {avgScore !== '—' ? `${avgScore}/10` : '—'}
        </span>
        <span className="user-chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="user-dropdown">
          <div className="user-dropdown-row">
            <span className="user-dropdown-label">Nickname</span>
            <span className="user-dropdown-val">{user.nickname}</span>
          </div>
          <div className="user-dropdown-row">
            <span className="user-dropdown-label">Commented matches</span>
            <span className="user-dropdown-val">{user.commented_matches}</span>
          </div>
          <div className="user-dropdown-row">
            <span className="user-dropdown-label">My Score</span>
            <span className="user-dropdown-val" style={{ color: scoreColor, fontWeight: 700 }}>
              {avgScore !== '—' ? `${avgScore} / 10` : 'No graded matches yet'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
