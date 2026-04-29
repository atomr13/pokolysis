import UserMenu from './UserMenu'

export default function TopBar() {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">⚽</div>
        <div className="brand-word">Pokolysis<span className="dot">.</span></div>
        <div className="brand-sub">Match Intelligence</div>
      </div>
      <div className="topbar-tools">
        <div className="tool-divider"/>
        <UserMenu />
      </div>
    </header>
  )
}
