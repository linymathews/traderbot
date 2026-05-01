export default function Header({ brokerStatus, appSettings, searchSymbol, setSearchSymbol, onSearch, searchLoading }) {
  const connected = brokerStatus?.connected
  const broker = brokerStatus?.active_broker || appSettings?.active_broker || '...'
  const paper = brokerStatus?.paper_mode

  const handleKey = e => { if (e.key === 'Enter') onSearch() }

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

      <div className="header-search">
        <input
          type="text"
          placeholder="Search symbol, e.g. NVDA"
          value={searchSymbol}
          onChange={e => setSearchSymbol(e.target.value.toUpperCase())}
          onKeyDown={handleKey}
        />
        <button className="btn btn-sm" onClick={onSearch} disabled={searchLoading || !searchSymbol.trim()}>
          {searchLoading ? <span className="spinner" /> : 'Analyze'}
        </button>
      </div>
    </header>
  )
}
