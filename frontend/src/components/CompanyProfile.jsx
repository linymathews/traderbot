import { useState, useEffect, useMemo } from 'react'

const API = '/api'

// ── Formatting helpers ────────────────────────────────────────────────────────
function fmtMoney(n, decimals = 2) {
  if (n == null) return '—'
  const abs = Math.abs(n)
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6)  return `$${(n / 1e6).toFixed(2)}M`
  return `$${Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`
}

function fmtNum(n, decimals = 2, suffix = '') {
  if (n == null) return '—'
  return `${Number(n).toFixed(decimals)}${suffix}`
}

function fmtPct(n) {
  if (n == null) return '—'
  const v = Number(n) * 100
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function fmtPctRaw(n) {
  if (n == null) return '—'
  const v = Number(n) * 100
  return `${v.toFixed(2)}%`
}

function fmtChange(change, changePct) {
  if (change == null) return null
  const cls = change >= 0 ? 'pos' : 'neg'
  const sign = change >= 0 ? '+' : ''
  const p = changePct != null ? ` (${sign}${Number(changePct).toFixed(2)}%)` : ''
  return <span className={cls}>{sign}{Number(change).toFixed(2)}{p}</span>
}

function fmtVol(n) {
  if (n == null) return '—'
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`
  return String(n)
}

function fmtShares(n) {
  if (n == null) return '—'
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9)  return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6)  return `${(n / 1e6).toFixed(2)}M`
  return n.toLocaleString()
}

// ── Small components ──────────────────────────────────────────────────────────
function Stat({ label, value, valueClass }) {
  return (
    <div className="cp-stat">
      <span className="cp-stat-label">{label}</span>
      <span className={`cp-stat-value ${valueClass || ''}`}>{value ?? '—'}</span>
    </div>
  )
}

function SectionTitle({ children }) {
  return <h3 className="cp-section-title">{children}</h3>
}

function RecBadge({ rec }) {
  if (!rec) return null
  const r = rec.toLowerCase()
  const cls = r.includes('buy') || r === 'strong_buy' ? 'pos'
            : r.includes('sell') || r === 'strong_sell' ? 'neg'
            : 'neu'
  return <span className={`cp-rec-badge ${cls}`}>{rec.replace(/_/g, ' ').toUpperCase()}</span>
}

function getAltLiveSignal(score10) {
  if (score10 >= 6.5) return 'STRONG BUY'
  if (score10 >= 3.5) return 'BUY'
  if (score10 <= -6.5) return 'STRONG SELL'
  if (score10 <= -3.5) return 'SELL'
  return 'HOLD'
}

function AltDataPanel({ alt }) {
  const [expanded, setExpanded] = useState({})
  if (!alt) return null

  const providers = Object.entries(alt.providers || {}).sort(([, a], [, b]) => {
    const av = Number(a?.weighted_score ?? 0)
    const bv = Number(b?.weighted_score ?? 0)
    return bv - av
  })
  const scoreClass = alt.alternative_score > 0 ? 'pos' : alt.alternative_score < 0 ? 'neg' : 'neu'

  const sourceLinkFor = (key, p) => {
    const symbol = (alt.symbol || '').toUpperCase()
    const detailsUrl = p?.details?.url
    if (detailsUrl) return detailsUrl

    const map = {
      capitol_trades: symbol ? `https://www.capitoltrades.com/trades?assetType=stock&page=1&ticker=${symbol}` : 'https://www.capitoltrades.com/trades',
      openinsider: symbol ? `https://openinsider.com/screener?s=${symbol}` : 'https://openinsider.com/screener',
      whalewisdom: symbol ? `https://whalewisdom.com/stock/${symbol.toLowerCase()}` : 'https://whalewisdom.com',
      quiver_quantitative: symbol ? `https://www.quiverquant.com/stock/${symbol}` : 'https://www.quiverquant.com',
      alpha_vantage_news_sentiment: 'https://www.alphavantage.co/documentation/#news-sentiment',
      polygon: 'https://polygon.io',
      financial_modeling_prep: symbol ? `https://site.financialmodelingprep.com/financial-summary/${symbol}` : 'https://site.financialmodelingprep.com',
      eodhd: symbol ? `https://eodhd.com/financial-summary/${symbol}.US` : 'https://eodhd.com',
      fred: 'https://fred.stlouisfed.org',
      tiingo: symbol ? `https://www.tiingo.com/?ticker=${symbol}` : 'https://www.tiingo.com',
      stockgeist_lunarcrush: symbol ? `https://lunarcrush.com/topic/${symbol}` : 'https://lunarcrush.com',
    }

    return map[key] || null
  }

  const getSummary = p => {
    const d = p.details || {}
    const picks = []

    if (d.trades_count != null) picks.push(`Trades: ${d.trades_count}`)
    if (d.filings_count != null) picks.push(`Filings: ${d.filings_count}`)
    if (d.news_count != null) picks.push(`News: ${d.news_count}`)
    if (d.avg_sentiment != null) picks.push(`Sentiment: ${d.avg_sentiment}`)
    if (d.net_buy_minus_sell != null) picks.push(`Net Buys: ${d.net_buy_minus_sell}`)
    if (d.close != null) picks.push(`Close: ${d.close}`)
    if (d.change_p != null) picks.push(`Change%: ${d.change_p}`)
    if (d.company_name) picks.push(`Company: ${d.company_name}`)
    if (d.name) picks.push(`Name: ${d.name}`)
    if (d.market_cap != null) picks.push(`Mkt Cap: ${d.market_cap}`)

    if (!p.available && p.error) return p.error
    if (p.available && picks.length) return picks.slice(0, 3).join(' | ')
    return p.available ? 'Data available' : 'No summary available'
  }

  return (
    <div className="cp-chain-section">
      <div className="cp-chain-header">
        <span className="cp-chain-icon">🌐</span>
        <SectionTitle>Alternative Data Integrations</SectionTitle>
        <span className="cp-chain-count">{alt.available_sources}/{providers.length} live</span>
      </div>

      <div className="cp-alt-summary">
        <div className="cp-alt-score-wrap">
          <span className="cp-stat-label">Alternative Score (used in signals/backtests)</span>
          <span className={`cp-alt-score ${scoreClass}`}>{alt.alternative_score}</span>
        </div>
        <div className="cp-alt-meta">
          <span className="cp-badge">Signal: {alt.alternative_signal}</span>
          <span className="cp-badge">As of: {alt.as_of_date}</span>
          <span className="cp-badge">Window: {alt.lookback_days}d</span>
        </div>
      </div>

      <div className="cp-stats-grid cp-alt-cards-grid">
        {providers.map(([key, p]) => {
          const status = p.available ? 'Live' : (p.configured ? 'Configured (No Data)' : 'Missing Key')
          const isOpen = !!expanded[key]
          const summary = getSummary(p)
          const detailEntries = Object.entries(p.details || {})
          const sourceUrl = sourceLinkFor(key, p)

          return (
            <div key={key} className="cp-stats-card cp-alt-provider-card">
              <div className="cp-alt-provider-head">
                <div className="cp-stats-card-title">{p.name || key}</div>
                <span className={`cp-alt-status ${p.available ? 'pos' : p.configured ? 'neu' : 'neg'}`}>{status}</span>
              </div>

              <Stat
                label="Signal"
                value={Number(p.signal_score || 0).toFixed(2)}
                valueClass={p.signal_score > 0 ? 'pos' : p.signal_score < 0 ? 'neg' : 'neu'}
              />
              <Stat label="Weight" value={Number(p.weight || 0).toFixed(2)} />
              <Stat label="Weighted Score" value={Number(p.weighted_score || 0).toFixed(4)} />
              <Stat label="Summary" value={summary} />

              <div className="cp-alt-card-actions">
                <button
                  type="button"
                  className="cp-alt-expand-btn"
                  onClick={() => setExpanded(prev => ({ ...prev, [key]: !prev[key] }))}
                  aria-label={isOpen ? `Collapse ${p.name || key}` : `Expand ${p.name || key}`}
                >
                  {isOpen ? 'Hide details ▾' : 'Show details ▸'}
                </button>
                {sourceUrl ? (
                  <a
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="cp-source-link"
                    title={`Open ${p.name || key}`}
                  >
                    Open source ↗
                  </a>
                ) : null}
              </div>

              {isOpen && (
                <div className="cp-alt-detail-wrap">
                  <div className="cp-alt-detail-meta">
                    <span className="cp-badge">Configured: {p.configured ? 'Yes' : 'No'}</span>
                    <span className="cp-badge">Enabled: {p.enabled ? 'Yes' : 'No'}</span>
                    <span className="cp-badge">Available: {p.available ? 'Yes' : 'No'}</span>
                  </div>
                  {p.error && <div className="cp-alt-detail-error">Error: {p.error}</div>}
                  {detailEntries.length > 0 ? (
                    <div className="cp-alt-kv-grid">
                      {detailEntries.map(([k, v]) => (
                        <div className="cp-alt-kv" key={`${key}-${k}`}>
                          <span className="cp-alt-k">{k}</span>
                          <span className="cp-alt-v">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="cp-alt-detail-empty">No additional fields from this provider.</div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Supply-chain table ────────────────────────────────────────────────────────
function ChainTable({ title, rows, icon, onNavigate }) {
  const [sortKey, setSortKey]     = useState('market_cap')
  const [sortDir, setSortDir]     = useState('desc')
  const [filterText, setFilter]   = useState('')
  const [roleFilter, setRoleFilter] = useState('')

  const allRoles = useMemo(() => {
    const set = new Set()
    rows.forEach(r => r.role && set.add(r.role.split(' — ')[0].split('(')[0].trim().substring(0, 40)))
    return [...set].sort()
  }, [rows])

  const sorted = useMemo(() => {
    let filtered = rows.filter(r => {
      const text = filterText.toLowerCase()
      const matchText = !text
        || r.symbol?.toLowerCase().includes(text)
        || r.name?.toLowerCase().includes(text)
        || r.role?.toLowerCase().includes(text)
        || r.sector?.toLowerCase().includes(text)
        || r.industry?.toLowerCase().includes(text)
      const matchRole = !roleFilter || r.role?.startsWith(roleFilter)
      return matchText && matchRole
    })

    return [...filtered].sort((a, b) => {
      let av = a[sortKey] ?? -Infinity
      let bv = b[sortKey] ?? -Infinity
      if (typeof av === 'string') av = av.toLowerCase()
      if (typeof bv === 'string') bv = bv.toLowerCase()
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [rows, sortKey, sortDir, filterText, roleFilter])

  function toggleSort(key) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  function SortTh({ k, children }) {
    const active = sortKey === k
    return (
      <th
        className={`sortable ${active ? 'sort-active' : ''}`}
        onClick={() => toggleSort(k)}
      >
        {children} {active ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}
      </th>
    )
  }

  if (!rows.length) return null

  return (
    <div className="cp-chain-section">
      <div className="cp-chain-header">
        <span className="cp-chain-icon">{icon}</span>
        <SectionTitle>{title}</SectionTitle>
        <span className="cp-chain-count">{rows.length} companies</span>
      </div>

      <div className="cp-chain-filters">
        <input
          className="cp-filter-input"
          placeholder="Filter by name, symbol, role…"
          value={filterText}
          onChange={e => setFilter(e.target.value)}
        />
        {allRoles.length > 1 && (
          <select
            className="cp-filter-select"
            value={roleFilter}
            onChange={e => setRoleFilter(e.target.value)}
          >
            <option value="">All roles</option>
            {allRoles.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        )}
        {(filterText || roleFilter) && (
          <button className="btn btn-ghost btn-sm" onClick={() => { setFilter(''); setRoleFilter('') }}>
            ✕ Clear
          </button>
        )}
        <span className="cp-chain-result-count">{sorted.length} showing</span>
      </div>

      <div className="table-wrap">
        <table className="cp-chain-table">
          <thead>
            <tr>
              <SortTh k="symbol">Symbol</SortTh>
              <SortTh k="name">Company</SortTh>
              <th>Role / Relationship</th>
              <SortTh k="market_cap">Market Cap</SortTh>
              <SortTh k="price">Price</SortTh>
              <SortTh k="sector">Sector</SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={6} className="cp-empty-row">No matches</td></tr>
            ) : sorted.map(r => (
              <tr key={r.symbol} className="cp-chain-row">
                <td>
                  <button className="cp-ticker-btn" onClick={() => onNavigate(r.symbol)}>
                    {r.symbol}
                  </button>
                </td>
                <td>{r.name || r.symbol}</td>
                <td className="cp-role-cell">{r.role || '—'}</td>
                <td>{fmtMoney(r.market_cap, 0)}</td>
                <td>{r.price != null ? `$${Number(r.price).toFixed(2)}` : '—'}</td>
                <td>
                  <span className="cp-sector-chip">
                    {r.sector || r.industry || '—'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Peer table ────────────────────────────────────────────────────────────────
function PeersTable({ peers, onNavigate }) {
  const [sortKey, setSortKey] = useState('market_cap')
  const [sortDir, setSortDir] = useState('desc')
  const [filterText, setFilter] = useState('')

  const sorted = useMemo(() => {
    const filtered = peers.filter(r => {
      const t = filterText.toLowerCase()
      return !t || r.symbol?.toLowerCase().includes(t) || r.name?.toLowerCase().includes(t) || r.sector?.toLowerCase().includes(t)
    })
    return [...filtered].sort((a, b) => {
      let av = a[sortKey] ?? -Infinity
      let bv = b[sortKey] ?? -Infinity
      if (typeof av === 'string') av = av.toLowerCase()
      if (typeof bv === 'string') bv = bv.toLowerCase()
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [peers, sortKey, sortDir, filterText])

  function toggleSort(key) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  function SortTh({ k, children }) {
    const active = sortKey === k
    return (
      <th className={`sortable ${active ? 'sort-active' : ''}`} onClick={() => toggleSort(k)}>
        {children} {active ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}
      </th>
    )
  }

  if (!peers.length) return null

  return (
    <div className="cp-chain-section">
      <div className="cp-chain-header">
        <span className="cp-chain-icon">🏢</span>
        <SectionTitle>Sector Peers</SectionTitle>
        <span className="cp-chain-count">{peers.length} companies</span>
      </div>
      <div className="cp-chain-filters">
        <input
          className="cp-filter-input"
          placeholder="Filter peers…"
          value={filterText}
          onChange={e => setFilter(e.target.value)}
        />
        {filterText && (
          <button className="btn btn-ghost btn-sm" onClick={() => setFilter('')}>✕ Clear</button>
        )}
        <span className="cp-chain-result-count">{sorted.length} showing</span>
      </div>
      <div className="table-wrap">
        <table className="cp-chain-table">
          <thead>
            <tr>
              <SortTh k="symbol">Symbol</SortTh>
              <SortTh k="name">Company</SortTh>
              <SortTh k="market_cap">Market Cap</SortTh>
              <SortTh k="price">Price</SortTh>
              <SortTh k="sector">Sector</SortTh>
              <SortTh k="industry">Industry</SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={6} className="cp-empty-row">No matches</td></tr>
            ) : sorted.map(r => (
              <tr key={r.symbol} className="cp-chain-row">
                <td>
                  <button className="cp-ticker-btn" onClick={() => onNavigate(r.symbol)}>
                    {r.symbol}
                  </button>
                </td>
                <td>{r.name || r.symbol}</td>
                <td>{fmtMoney(r.market_cap, 0)}</td>
                <td>{r.price != null ? `$${Number(r.price).toFixed(2)}` : '—'}</td>
                <td><span className="cp-sector-chip">{r.sector || '—'}</span></td>
                <td>{r.industry || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function CompanyProfile({ symbol: initialSymbol, onNavigate }) {
  const [symbol, setSymbol]   = useState((initialSymbol || '').toUpperCase())
  const [inputSym, setInput]  = useState(initialSymbol || '')
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [history, setHistory] = useState([])
  const [expandedBuckets, setExpandedBuckets] = useState({})
  const [expandedAltSources, setExpandedAltSources] = useState({})

  async function load(sym) {
    if (!sym) return
    setLoading(true)
    setError(null)
    setData(null)
    try {
      const res = await fetch(`${API}/company/${sym}`)
      if (!res.ok) {
        const b = await res.json()
        throw new Error(b.detail || `HTTP ${res.status}`)
      }
      const d = await res.json()
      setData(d)
      setSymbol(sym)
      setInput(sym)
      setHistory(prev => {
        const next = [sym, ...prev.filter(s => s !== sym)].slice(0, 8)
        return next
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialSymbol) load(initialSymbol.toUpperCase())
  }, [initialSymbol])

  useEffect(() => {
    setExpandedBuckets({})
    setExpandedAltSources({})
  }, [symbol])

  function navigate(sym) {
    if (sym === symbol) return
    if (onNavigate) onNavigate(sym)
    else load(sym.toUpperCase())
  }

  function handleSearch(e) {
    e.preventDefault()
    const s = inputSym.trim().toUpperCase()
    if (s) load(s)
  }

  const d = data
  const expiryBuckets = useMemo(
    () => d?.options_chain?.expiry_groups || [],
    [d?.options_chain?.expiry_groups],
  )
  const altLiveSummary = useMemo(() => {
    const alt = d?.alternative_data
    const providers = Object.entries(alt?.providers || {})
    const liveProviders = providers
      .filter(([, p]) => !!p?.available)
      .sort(([, a], [, b]) => Number(b?.weighted_score || 0) - Number(a?.weighted_score || 0))

    const totalWeight = liveProviders.reduce((sum, [, p]) => sum + Number(p?.weight || 0), 0)
    const weightedSum = liveProviders.reduce((sum, [, p]) => sum + Number(p?.weighted_score || 0), 0)
    const normalized = totalWeight > 0 ? weightedSum / totalWeight : 0
    const score10 = normalized * 10
    const signal = getAltLiveSignal(score10)

    return {
      providers: liveProviders,
      totalCount: providers.length,
      liveCount: liveProviders.length,
      totalWeight,
      weightedSum,
      score10,
      signal,
    }
  }, [d?.alternative_data])

  return (
    <div className="cp-page">
      {/* Search bar */}
      <form className="cp-search-bar" onSubmit={handleSearch}>
        <input
          className="cp-search-input"
          value={inputSym}
          onChange={e => setInput(e.target.value.toUpperCase())}
          placeholder="Enter ticker symbol (e.g. AAPL)"
          spellCheck={false}
        />
        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? <><span className="spinner" />Loading…</> : '🔍 Search'}
        </button>
        {history.length > 1 && (
          <div className="cp-history">
            {history.filter(s => s !== symbol).map(s => (
              <button key={s} className="cp-hist-chip" type="button" onClick={() => load(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
      </form>

      {error && (
        <div className="error-banner">
          <strong>Error:</strong> {error}
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {loading && !d && (
        <div className="cp-loading">
          <span className="spinner" /> Loading company profile for {symbol}…
        </div>
      )}

      {d && (
        <>
          {/* ── Company Header ───────────────────────────────────── */}
          <div className="cp-header">
            <div className="cp-header-left">
              <div className="cp-ticker">{d.symbol}</div>
              <div className="cp-company-name">{d.name}</div>
              <div className="cp-meta-row">
                {d.exchange && <span className="cp-badge">{d.exchange}</span>}
                {d.currency && <span className="cp-badge">{d.currency}</span>}
                {d.sector   && <span className="cp-badge cp-badge-sector">{d.sector}</span>}
                {d.industry && <span className="cp-badge cp-badge-industry">{d.industry}</span>}
                {d.country  && <span className="cp-badge">{d.country}</span>}
              </div>
            </div>
            <div className="cp-header-right">
              {d.price != null && (
                <div className="cp-price-block">
                  <span className="cp-price">${Number(d.price).toFixed(2)}</span>
                  <span className="cp-change">{fmtChange(d.price_change, d.price_change_pct)}</span>
                  <div className="cp-price-sub">
                    {d.day_low != null && d.day_high != null && (
                      <span>Day: ${Number(d.day_low).toFixed(2)} – ${Number(d.day_high).toFixed(2)}</span>
                    )}
                  </div>
                </div>
              )}
              {d.recommendation_key && (
                <RecBadge rec={d.recommendation_key} />
              )}
            </div>
          </div>

          {/* ── Key Stats Grid ───────────────────────────────────── */}
          <div className="cp-stats-grid">
            <div className="cp-stats-card">
              <div className="cp-stats-card-title">💡 Buy/Sell Signal</div>
              {d.buy_sell_signal && (
                <>
                  <div className={`cp-buysell-signal-card ${d.buy_sell_signal.signal.includes('BUY') ? 'pos' : d.buy_sell_signal.signal.includes('SELL') ? 'neg' : 'neu'}`}>
                    {d.buy_sell_signal.signal.replace(/_/g, ' ')}
                  </div>
                  <Stat 
                    label="Score" 
                    value={`${d.buy_sell_signal.score >= 0 ? '+' : ''}${d.buy_sell_signal.score}/10`}
                    valueClass={d.buy_sell_signal.score > 2.5 ? 'pos' : d.buy_sell_signal.score < -2.5 ? 'neg' : ''}
                  />
                  {d.buy_sell_signal.factors?.alternative_data && (
                    <Stat 
                      label="Alternative Data" 
                      value={d.buy_sell_signal.factors.alternative_data.score}
                      valueClass={d.buy_sell_signal.factors.alternative_data.score > 0 ? 'pos' : d.buy_sell_signal.factors.alternative_data.score < 0 ? 'neg' : ''}
                    />
                  )}
                  {d.buy_sell_signal.factors?.options_chain && (
                    <Stat 
                      label="Put/Call Ratio" 
                      value={d.buy_sell_signal.factors.options_chain.put_call_ratio ? d.buy_sell_signal.factors.options_chain.put_call_ratio.toFixed(2) : '—'}
                    />
                  )}
                  {d.buy_sell_signal.factors?.momentum?.day_change_pct != null && (
                    <Stat 
                      label="Day Change" 
                      value={`${d.buy_sell_signal.factors.momentum.day_change_pct >= 0 ? '+' : ''}${d.buy_sell_signal.factors.momentum.day_change_pct.toFixed(2)}%`}
                      valueClass={d.buy_sell_signal.factors.momentum.day_change_pct >= 0 ? 'pos' : 'neg'}
                    />
                  )}
                </>
              )}
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Options Expiry Buckets</div>
              {!d.options_chain?.available && (
                <Stat label="Status" value={d.options_chain?.reason || 'Unavailable'} />
              )}
              {d.options_chain?.available && expiryBuckets.length === 0 && (
                <Stat label="Status" value="No listed expirations" />
              )}
              {d.options_chain?.available && expiryBuckets.map((bucket) => (
                <div key={bucket.label} className="cp-expiry-bucket-row">
                  <button
                    type="button"
                    className="cp-expiry-bucket-btn"
                    onClick={() => setExpandedBuckets((prev) => ({ ...prev, [bucket.label]: !prev[bucket.label] }))}
                    disabled={bucket.expiration_count === 0}
                  >
                    <span className="cp-expiry-bucket-btn-left">
                      <span className="cp-expiry-bucket-label">{bucket.label}</span>
                      <span className="cp-expiry-bucket-count">{bucket.expiration_count > 0 ? `${bucket.expiration_count} expiries` : 'No expiries'}</span>
                    </span>
                    <span
                      className={`cp-expiry-bucket-signal ${
                        bucket.future_demand_signal === 'BULLISH'
                          ? 'pos'
                          : bucket.future_demand_signal === 'BEARISH'
                            ? 'neg'
                            : 'neu'
                      }`}
                    >
                      {bucket.expiration_count > 0 ? bucket.future_demand_signal : '—'}
                    </span>
                    <span className="cp-expiry-bucket-chevron">
                      {expandedBuckets[bucket.label] ? '▾' : '▸'}
                    </span>
                  </button>
                  {bucket.expiration_count > 0 && expandedBuckets[bucket.label] && (
                    <div className="cp-expiry-bucket-meta">
                      <span>P/C OI Ratio: {bucket.put_call_oi_ratio != null ? bucket.put_call_oi_ratio.toFixed(2) : '—'}</span>
                      <span>P/C Volume Ratio: {bucket.put_call_volume_ratio != null ? bucket.put_call_volume_ratio.toFixed(2) : '—'}</span>
                      <span>Demand Score: {bucket.future_demand_score != null ? bucket.future_demand_score.toFixed(2) : '—'}</span>
                      <span>Call OI: {fmtNum(bucket.total_call_open_interest || 0, 0)}</span>
                      <span>Put OI: {fmtNum(bucket.total_put_open_interest || 0, 0)}</span>
                      <span>Call Vol: {fmtNum(bucket.total_call_volume || 0, 0)}</span>
                      <span>Put Vol: {fmtNum(bucket.total_put_volume || 0, 0)}</span>
                      <span>
                        Expiries: {Array.isArray(bucket.dates) && bucket.dates.length ? bucket.dates.join(', ') : '—'}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Alternative Live Sources</div>
              <div className={`cp-buysell-signal-card ${altLiveSummary.signal.includes('BUY') ? 'pos' : altLiveSummary.signal.includes('SELL') ? 'neg' : 'neu'}`}>
                {altLiveSummary.signal}
              </div>
              <Stat label="Live Sources" value={`${altLiveSummary.liveCount}/${altLiveSummary.totalCount}`} />
              <Stat
                label="Composite Score"
                value={`${altLiveSummary.score10 >= 0 ? '+' : ''}${altLiveSummary.score10.toFixed(2)}/10`}
                valueClass={altLiveSummary.score10 > 3.5 ? 'pos' : altLiveSummary.score10 < -3.5 ? 'neg' : ''}
              />
              {altLiveSummary.liveCount === 0 && <Stat label="Status" value="No live alternative sources" />}

              {altLiveSummary.providers.map(([key, p]) => {
                const isOpen = !!expandedAltSources[key]
                const detailEntries = Object.entries(p.details || {})
                const sourceSignal = Number(p.signal_score || 0) > 0 ? 'BULLISH' : Number(p.signal_score || 0) < 0 ? 'BEARISH' : 'NEUTRAL'

                return (
                  <div key={key} className="cp-expiry-bucket-row">
                    <button
                      type="button"
                      className="cp-expiry-bucket-btn"
                      onClick={() => setExpandedAltSources((prev) => ({ ...prev, [key]: !prev[key] }))}
                    >
                      <span className="cp-expiry-bucket-btn-left">
                        <span className="cp-expiry-bucket-label">{p.name || key}</span>
                        <span className="cp-expiry-bucket-count">
                          Signal: {Number(p.signal_score || 0).toFixed(2)} | Weight: {Number(p.weight || 0).toFixed(2)}
                        </span>
                      </span>
                      <span className={`cp-expiry-bucket-signal ${sourceSignal === 'BULLISH' ? 'pos' : sourceSignal === 'BEARISH' ? 'neg' : 'neu'}`}>
                        {sourceSignal}
                      </span>
                      <span className="cp-expiry-bucket-chevron">{isOpen ? '▾' : '▸'}</span>
                    </button>
                    {isOpen && (
                      <div className="cp-expiry-bucket-meta">
                        <span>Weighted Score: {Number(p.weighted_score || 0).toFixed(4)}</span>
                        <span>Configured: {p.configured ? 'Yes' : 'No'}</span>
                        <span>Enabled: {p.enabled ? 'Yes' : 'No'}</span>
                        {p.error ? <span>Error: {p.error}</span> : <span>Error: None</span>}
                        {detailEntries.length > 0 ? (
                          <span>
                            Fields: {detailEntries.slice(0, 4).map(([k]) => k).join(', ')}
                          </span>
                        ) : (
                          <span>Fields: None</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Valuation</div>
              <Stat label="Market Cap"         value={fmtMoney(d.market_cap, 0)} />
              <Stat label="Enterprise Value"   value={fmtMoney(d.enterprise_value, 0)} />
              <Stat label="P/E (TTM)"          value={d.pe_ratio != null ? fmtNum(d.pe_ratio) : '—'} />
              <Stat label="Forward P/E"        value={d.forward_pe != null ? fmtNum(d.forward_pe) : '—'} />
              <Stat label="PEG Ratio"          value={d.peg_ratio != null ? fmtNum(d.peg_ratio) : '—'} />
              <Stat label="Price / Book"       value={d.price_to_book != null ? fmtNum(d.price_to_book) : '—'} />
              <Stat label="Price / Sales"      value={d.price_to_sales != null ? fmtNum(d.price_to_sales) : '—'} />
              <Stat label="EV / Revenue"       value={d.enterprise_to_revenue != null ? fmtNum(d.enterprise_to_revenue) : '—'} />
              <Stat label="EV / EBITDA"        value={d.enterprise_to_ebitda != null ? fmtNum(d.enterprise_to_ebitda) : '—'} />
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Per Share</div>
              <Stat label="Price"              value={d.price != null ? `$${Number(d.price).toFixed(2)}` : '—'} />
              <Stat label="EPS (TTM)"          value={d.eps != null ? `$${Number(d.eps).toFixed(2)}` : '—'} />
              <Stat label="Forward EPS"        value={d.eps_forward != null ? `$${Number(d.eps_forward).toFixed(2)}` : '—'} />
              <Stat label="Book Value / Share" value={d.book_value != null ? `$${Number(d.book_value).toFixed(2)}` : '—'} />
              <Stat label="Dividend Rate"      value={d.dividend_rate != null ? `$${Number(d.dividend_rate).toFixed(2)}` : '—'} />
              <Stat label="Dividend Yield"     value={d.dividend_yield != null ? fmtPctRaw(d.dividend_yield) : '—'} />
              <Stat label="Payout Ratio"       value={d.payout_ratio != null ? fmtPctRaw(d.payout_ratio) : '—'} />
              <Stat label="Shares Outstanding" value={fmtShares(d.shares_outstanding)} />
              <Stat label="Float"              value={fmtShares(d.float_shares)} />
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Price History</div>
              <Stat label="52-Wk High"   value={d.fifty_two_week_high != null ? `$${Number(d.fifty_two_week_high).toFixed(2)}` : '—'} />
              <Stat label="52-Wk Low"    value={d.fifty_two_week_low  != null ? `$${Number(d.fifty_two_week_low).toFixed(2)}` : '—'} />
              <Stat label="50-Day Avg"   value={d.fifty_day_avg        != null ? `$${Number(d.fifty_day_avg).toFixed(2)}` : '—'} />
              <Stat label="200-Day Avg"  value={d.two_hundred_day_avg  != null ? `$${Number(d.two_hundred_day_avg).toFixed(2)}` : '—'} />
              <Stat label="Beta"         value={d.beta != null ? fmtNum(d.beta) : '—'} />
              <Stat label="Volume"       value={fmtVol(d.volume)} />
              <Stat label="Avg Volume"   value={fmtVol(d.avg_volume)} />
              <Stat label="Short Ratio"  value={d.short_ratio != null ? fmtNum(d.short_ratio) : '—'} />
              <Stat label="Short % Float" value={d.short_percent_float != null ? fmtPctRaw(d.short_percent_float) : '—'} />
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Financials (TTM)</div>
              <Stat label="Revenue"          value={fmtMoney(d.revenue_ttm, 0)} />
              <Stat label="Gross Margin"     value={d.gross_margins     != null ? fmtPctRaw(d.gross_margins) : '—'} />
              <Stat label="Operating Margin" value={d.operating_margins != null ? fmtPctRaw(d.operating_margins) : '—'} />
              <Stat label="Net Margin"       value={d.profit_margins    != null ? fmtPctRaw(d.profit_margins) : '—'} />
              <Stat label="ROE"              value={d.return_on_equity  != null ? fmtPctRaw(d.return_on_equity) : '—'} />
              <Stat label="ROA"              value={d.return_on_assets  != null ? fmtPctRaw(d.return_on_assets) : '—'} />
              <Stat label="Revenue Growth"   value={d.revenue_growth    != null ? fmtPct(d.revenue_growth) : '—'}
                valueClass={d.revenue_growth > 0 ? 'pos' : d.revenue_growth < 0 ? 'neg' : ''} />
              <Stat label="Earnings Growth"  value={d.earnings_growth   != null ? fmtPct(d.earnings_growth) : '—'}
                valueClass={d.earnings_growth > 0 ? 'pos' : d.earnings_growth < 0 ? 'neg' : ''} />
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Balance Sheet</div>
              <Stat label="Total Cash"    value={fmtMoney(d.total_cash, 0)} />
              <Stat label="Total Debt"    value={fmtMoney(d.total_debt, 0)} />
              <Stat label="Debt / Equity" value={d.debt_to_equity != null ? fmtNum(d.debt_to_equity) : '—'} />
              <Stat label="Current Ratio" value={d.current_ratio  != null ? fmtNum(d.current_ratio) : '—'} />
              <Stat label="Quick Ratio"   value={d.quick_ratio    != null ? fmtNum(d.quick_ratio) : '—'} />
              <Stat label="Free Cash Flow"      value={fmtMoney(d.free_cashflow, 0)} />
              <Stat label="Operating Cash Flow" value={fmtMoney(d.operating_cashflow, 0)} />
            </div>

            <div className="cp-stats-card">
              <div className="cp-stats-card-title">Analyst Consensus</div>
              {d.recommendation_key && (
                <div style={{ marginBottom: 10 }}>
                  <RecBadge rec={d.recommendation_key} />
                </div>
              )}
              <Stat label="Target (Mean)"  value={d.target_mean_price != null ? `$${Number(d.target_mean_price).toFixed(2)}` : '—'} />
              <Stat label="Target (High)"  value={d.target_high_price != null ? `$${Number(d.target_high_price).toFixed(2)}` : '—'} />
              <Stat label="Target (Low)"   value={d.target_low_price  != null ? `$${Number(d.target_low_price).toFixed(2)}` : '—'} />
              <Stat label="# Analysts"     value={d.analyst_count ?? '—'} />
              {d.price != null && d.target_mean_price != null && (
                <Stat
                  label="Upside to Target"
                  value={fmtPct((d.target_mean_price - d.price) / d.price)}
                  valueClass={(d.target_mean_price - d.price) >= 0 ? 'pos' : 'neg'}
                />
              )}
              <Stat label="Employees"  value={d.employees != null ? d.employees.toLocaleString() : '—'} />
              {d.city && d.country && (
                <Stat label="HQ" value={[d.city, d.state, d.country].filter(Boolean).join(', ')} />
              )}
              {d.website && (
                <div className="cp-stat">
                  <span className="cp-stat-label">Website</span>
                  <a className="cp-link" href={d.website} target="_blank" rel="noreferrer">
                    {d.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                  </a>
                </div>
              )}
            </div>
          </div>

          {/* ── Business Description ─────────────────────────────── */}
          {d.description && (
            <div className="cp-desc-section">
              <SectionTitle>About {d.name}</SectionTitle>
              <p className="cp-desc-text">{d.description}</p>
            </div>
          )}

          <AltDataPanel alt={d.alternative_data} />

          {/* ── Supply Chain ─────────────────────────────────────── */}
          {!d.has_supply_chain_data && (
            <div className="cp-no-chain">
              <span>📋</span>
              <div>
                <strong>No supply chain data for {d.symbol}</strong>
                <p>
                  Supply chain relationships are currently available for major S&P 500 constituents
                  (AAPL, MSFT, NVDA, AMZN, TSLA, GOOGL, META, AMD, TSM, QCOM, AVGO, MU, INTC, and more).
                  Sector peers from Yahoo Finance are shown below.
                </p>
              </div>
            </div>
          )}

          <ChainTable
            title="Upstream Dependencies — Companies This Company Depends On"
            icon="⬆️"
            rows={d.suppliers}
            onNavigate={navigate}
          />

          <ChainTable
            title="Downstream Dependents — Companies That Depend On This Company"
            icon="⬇️"
            rows={d.customers}
            onNavigate={navigate}
          />

          <PeersTable peers={d.peers} onNavigate={navigate} />
        </>
      )}
    </div>
  )
}
