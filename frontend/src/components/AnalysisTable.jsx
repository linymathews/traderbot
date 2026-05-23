function RecChip({ rec }) {
  const classes = 'rec ' + (rec || '').replace(' ', '.')
  return <span className={classes}>{rec || '—'}</span>
}

function Score({ score }) {
  const cls = score > 0 ? 'pos' : score < 0 ? 'neg' : 'neu'
  return (
    <span className={`score-val ${cls}`}>
      {score > 0 ? '+' : ''}{score}
    </span>
  )
}

function fmt(n, prefix = '$') {
  if (n == null) return '—'
  return `${prefix}${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function pct(n) {
  if (n == null) return '—'
  const v = Number(n)
  const cls = v >= 0 ? 'pos' : 'neg'
  return <span className={cls}>{v >= 0 ? '+' : ''}{v.toFixed(2)}%</span>
}

export default function AnalysisTable({ analyses, rawPositions = [], pendingOrders = [], loading, onSelect, selectedSymbol, onRefresh, onViewCompany, emptyMessage }) {
  const hasRawFallback = !loading && analyses.length === 0 && rawPositions.length > 0

  return (
    <div>
      <div className="table-header">
        <h2>Portfolio Analysis</h2>
        <button className="btn btn-ghost btn-sm" onClick={onRefresh} disabled={loading}>
          {loading ? <><span className="spinner" />Refreshing…</> : '↻ Refresh'}
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Recommendation</th>
              <th>Score</th>
              <th>Price</th>
              <th>Qty</th>
              <th>Mkt Value</th>
              <th>P&L</th>
              <th>P&L %</th>
              <th>RSI</th>
              <th>MACD</th>
              <th>Congress</th>
            </tr>
          </thead>
          <tbody>
            {loading && analyses.length === 0 ? (
              <tr className="loading-row">
                <td colSpan={11}><span className="spinner" />Loading portfolio analysis…</td>
              </tr>
            ) : analyses.length === 0 ? (
              <tr className="loading-row">
                <td colSpan={11}>{emptyMessage || 'No positions found for this account.'}</td>
              </tr>
            ) : (
              analyses.map(a => (
                <tr
                  key={a.symbol}
                  onClick={() => onSelect(a.symbol === selectedSymbol ? null : a.symbol)}
                  className={a.symbol === selectedSymbol ? 'selected' : ''}
                >
                  <td>
                    <button
                      className="cp-ticker-btn"
                      title="View Company Profile"
                      onClick={e => { e.stopPropagation(); onViewCompany && onViewCompany(a.symbol) }}
                    >{a.symbol}</button>
                  </td>
                  <td><RecChip rec={a.final_recommendation} /></td>
                  <td><Score score={a.combined_score} /></td>
                  <td>{fmt(a.technical?.current_price)}</td>
                  <td>{a.position?.quantity}</td>
                  <td>{fmt(a.position?.market_value)}</td>
                  <td>
                    <span className={a.position?.unrealized_pl >= 0 ? 'pos' : 'neg'}>
                      {fmt(a.position?.unrealized_pl)}
                    </span>
                  </td>
                  <td>{pct(a.position?.unrealized_pl_pct)}</td>
                  <td>
                    <span className={
                      a.technical?.indicators?.rsi < 30 ? 'pos' :
                      a.technical?.indicators?.rsi > 70 ? 'neg' : 'neu'
                    }>
                      {a.technical?.indicators?.rsi ?? '—'}
                    </span>
                  </td>
                  <td>
                    <span className={a.technical?.indicators?.macd_histogram > 0 ? 'pos' : 'neg'}>
                      {a.technical?.indicators?.macd_histogram != null
                        ? Number(a.technical.indicators.macd_histogram).toFixed(3)
                        : '—'}
                    </span>
                  </td>
                  <td>
                    <span className={
                      a.congress?.congress_signal === 'BULLISH' ? 'pos' :
                      a.congress?.congress_signal === 'BEARISH' ? 'neg' : 'neu'
                    }>
                      {a.congress?.congress_signal ?? '—'}
                      {a.congress?.congress_buys || a.congress?.congress_sells
                        ? ` (${a.congress.congress_buys}B/${a.congress.congress_sells}S)` : ''}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {hasRawFallback && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th colSpan={4}>Raw Broker Positions (analysis unavailable)</th>
              </tr>
              <tr>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Mkt Value</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {rawPositions.map((p, idx) => (
                <tr key={`${p.symbol || 'pos'}-${idx}`}>
                  <td>{p.symbol || '—'}</td>
                  <td>{p.quantity ?? '—'}</td>
                  <td>{fmt(p.market_value)}</td>
                  <td>{p.asset_type || 'stock'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && pendingOrders.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th colSpan={7}>Pending Orders</th>
              </tr>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Type</th>
                <th>Status</th>
                <th>Limit</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {pendingOrders.map((o, idx) => (
                <tr key={`${o.id || 'ord'}-${idx}`}>
                  <td>{o.symbol || '—'}</td>
                  <td>{(o.side || '—').toUpperCase()}</td>
                  <td>{o.qty ?? '—'}</td>
                  <td>{o.type || '—'}</td>
                  <td>{o.status || '—'}</td>
                  <td>{o.limit_price ? fmt(o.limit_price) : '—'}</td>
                  <td>{o.submitted_at ? new Date(o.submitted_at).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
