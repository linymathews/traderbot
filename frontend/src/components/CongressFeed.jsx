import { useMemo, useState } from 'react'

const COLUMNS = [
  { key: 'politician', label: 'Politician' },
  { key: 'traded_issuer', label: 'Traded Issuer' },
  { key: 'published', label: 'Published', date: true },
  { key: 'traded', label: 'Traded', date: true },
  { key: 'filed_after_days', label: 'Filed After' },
  { key: 'owner', label: 'Owner' },
  { key: 'type', label: 'Type' },
  { key: 'size', label: 'Size' },
  { key: 'price', label: 'Price' },
]

function parseDate(value) {
  if (!value) return null
  const ts = Date.parse(value)
  return Number.isNaN(ts) ? null : ts
}

function parseComparableNumber(value) {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return value
  const cleaned = String(value).replace(/[^0-9.-]/g, '')
  if (!cleaned) return null
  const num = Number(cleaned)
  return Number.isNaN(num) ? null : num
}

function dateFilterMatch(dateValue, rawFilter) {
  const filter = (rawFilter || '').trim()
  if (!filter) return true
  const rowTs = parseDate(dateValue)
  if (!rowTs) return false

  if (filter.startsWith('>') || filter.startsWith('<')) {
    const op = filter[0]
    const queryTs = parseDate(filter.slice(1).trim())
    if (!queryTs) return false
    return op === '>' ? rowTs > queryTs : rowTs < queryTs
  }

  return String(dateValue).toLowerCase().includes(filter.toLowerCase())
}

export default function CongressFeed({ trades, onSelectSymbol, onViewCompany }) {
  const [sortKey, setSortKey] = useState('published')
  const [sortDir, setSortDir] = useState('desc')
  const [filters, setFilters] = useState({})

  const rows = useMemo(() => {
    const normalized = (trades || []).map(t => ({
      politician: t.politician || '',
      traded_issuer: t.traded_issuer || t.description || '',
      published: t.published || t.disclosure_date || '',
      traded: t.traded || t.trade_date || '',
      filed_after_days: t.filed_after_days ?? '',
      owner: t.owner || '',
      type: t.type || t.transaction || '',
      size: t.size || t.amount_range || '',
      price: t.price || '',
      symbol: t.symbol || '',
      party: t.party || '',
      chamber: t.chamber || '',
    }))

    const filtered = normalized.filter(row => {
      return COLUMNS.every(col => {
        const f = (filters[col.key] || '').trim()
        if (!f) return true
        const value = row[col.key]
        if (col.date) return dateFilterMatch(value, f)
        return String(value).toLowerCase().includes(f.toLowerCase())
      })
    })

    const sorted = filtered.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]

      let cmp = 0
      if (sortKey === 'published' || sortKey === 'traded') {
        const ad = parseDate(av) || 0
        const bd = parseDate(bv) || 0
        cmp = ad - bd
      } else if (sortKey === 'filed_after_days' || sortKey === 'price') {
        const an = parseComparableNumber(av)
        const bn = parseComparableNumber(bv)
        if (an !== null && bn !== null) cmp = an - bn
        else cmp = String(av).localeCompare(String(bv))
      } else {
        cmp = String(av).localeCompare(String(bv))
      }

      return sortDir === 'asc' ? cmp : -cmp
    })

    return sorted
  }, [trades, filters, sortKey, sortDir])

  const onSort = key => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortKey(key)
    setSortDir('asc')
  }

  if (!trades?.length) {
    return (
      <div style={{ color: 'var(--text-muted)', padding: '40px 0', textAlign: 'center' }}>
        No recent congressional trades found. Check CAPITOL_TRADES_ENABLED in .env
      </div>
    )
  }

  return (
    <div>
      <div className="table-header">
        <h2>Congressional Stock Trades</h2>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {rows.length} shown / {trades.length} total
        </span>
      </div>

      <div className="table-wrap congress-table-wrap">
        <table className="congress-table">
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  className="sortable"
                  onClick={() => onSort(col.key)}
                  title={`Sort by ${col.label}`}
                >
                  {col.label}
                  <span className="sort-indicator">
                    {sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </span>
                </th>
              ))}
            </tr>
            <tr className="filter-row">
              {COLUMNS.map(col => (
                <th key={`${col.key}-filter`}>
                  <input
                    value={filters[col.key] || ''}
                    onChange={e => setFilters(prev => ({ ...prev, [col.key]: e.target.value }))}
                    placeholder={col.date ? '>2026-04-01 or <2026-05-01' : `Filter ${col.label}`}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((t, idx) => {
              const isBuy = /purchase|buy/i.test(t.type)
              const isSell = /sale|sell/i.test(t.type)
              return (
                <tr
                  key={`${t.symbol}-${t.traded}-${idx}`}
                  onClick={() => t.symbol && onSelectSymbol && onSelectSymbol(t.symbol)}
                  title={t.symbol ? `Analyze ${t.symbol}` : ''}
                >
                  <td>{t.politician} {t.party ? `(${t.party})` : ''}</td>
                  <td>
                    {t.traded_issuer || '-'}
                    {t.symbol ? (
                      <>
                        {' '}
                        <span
                          className="sym cp-ticker-btn"
                          title="View Company Profile"
                          onClick={e => {
                            e.stopPropagation()
                            onViewCompany && onViewCompany(t.symbol)
                          }}
                        >
                          ({t.symbol})
                        </span>
                      </>
                    ) : ''}
                  </td>
                  <td>{t.published || '-'}</td>
                  <td>{t.traded || '-'}</td>
                  <td>{t.filed_after_days !== '' ? `${t.filed_after_days}d` : '-'}</td>
                  <td>{t.owner || '-'}</td>
                  <td className={isBuy ? 'tx-buy' : isSell ? 'tx-sell' : 'tx-other'}>{t.type || '-'}</td>
                  <td>{t.size || '-'}</td>
                  <td>{t.price || '-'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {!rows.length && (
        <div style={{ color: 'var(--text-muted)', padding: '24px 0', textAlign: 'center' }}>
          No rows match current filters.
        </div>
      )}
    </div>
  )
}
