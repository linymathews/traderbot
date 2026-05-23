import { useEffect, useRef, useState } from 'react'

export default function Header({
  brokerStatus,
  appSettings,
  user,
  onOpenProfile,
  onLogout,
  authBusy,
}) {
  const connected = brokerStatus?.connected
  const broker = brokerStatus?.active_broker || appSettings?.active_broker || '...'
  const paper = brokerStatus?.paper_mode
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)



  useEffect(() => {
    const onDocClick = e => {
      if (!menuRef.current?.contains(e.target)) {
        setMenuOpen(false)
      }
    }

    const onEscape = e => {
      if (e.key === 'Escape') setMenuOpen(false)
    }

    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEscape)
    }
  }, [])

  const displayName = user?.name || user?.email || 'Signed in'

  return (
    <header className="header">
      <div className="header-logo">📈 TraderBot</div>

      <span className={`broker-badge ${connected ? 'connected' : 'disconnected'}`}>
        {broker.toUpperCase()}
        {paper ? ' (paper)' : ''}
        {' '}
        {connected ? '● live' : '○ offline'}
      </span>

      {appSettings && (
        <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          Refresh: {appSettings.refresh_interval_minutes}m
        </span>
      )}



      <div className="header-user" ref={menuRef}>
        <button
          className="header-user-toggle"
          type="button"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(v => !v)}
        >
          <span className="header-user-name" title={displayName}>{displayName}</span>
          <span className="header-user-caret" aria-hidden="true">▾</span>
        </button>
        <div className={`header-user-menu ${menuOpen ? 'open' : ''}`} role="menu" aria-label="User menu">
          <button
            className="header-user-menu-item"
            role="menuitem"
            type="button"
            onClick={() => {
              setMenuOpen(false)
              onOpenProfile()
            }}
          >
            Profile
          </button>
          <button
            className="header-user-menu-item"
            role="menuitem"
            type="button"
            onClick={() => {
              setMenuOpen(false)
              onLogout()
            }}
            disabled={authBusy}
          >
            {authBusy ? 'Logging out...' : 'Logout'}
          </button>
        </div>
      </div>
    </header>
  )
}
