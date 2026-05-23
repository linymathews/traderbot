import { useCallback, useEffect, useState } from 'react'

const API = '/api/jobs'

const ALGO_INFO = {
  recommendation: {
    label: 'AI Recommendation (all signals)',
    short: 'Combines RSI, MACD, Bollinger Bands, SMA, Support/Resistance, and Volume into a single scored decision. Best for general-purpose automated trading.',
    buy:  'Aggregate score ≥ +2 across all indicators → BUY',
    sell: 'Aggregate score ≤ −2 across all indicators → SELL',
    neutral: 'Score between −1 and +1 → HOLD',
    example: 'AAPL: RSI = 28 (oversold, +1), MACD histogram positive (+1), price below lower Bollinger Band (+1), SMA50 > SMA200 golden cross (+1) → total score +4 → STRONG BUY signal generated.',
    tags: ['RSI (14)', 'MACD (12,26,9)', 'Bollinger Bands', 'SMA 50/200', 'Support/Resistance', 'Volume'],
  },
  rsi_mean_reversion: {
    label: 'RSI Mean Reversion',
    short: 'Trades the assumption that extreme RSI values will snap back toward 50. Best for range-bound, volatile stocks.',
    buy:  'RSI(14) < 30 → oversold → BUY',
    sell: 'RSI(14) > 70 → overbought → SELL',
    neutral: '30 ≤ RSI ≤ 70 → HOLD',
    example: 'TSLA drops 15% in 3 days and RSI hits 24 (oversold). Strategy buys expecting a bounce. When price recovers and RSI reaches 72 (overbought), strategy sells.',
    tags: ['RSI (14)'],
  },
  macd_cross: {
    label: 'MACD Crossover',
    short: 'Uses MACD line vs signal line crossovers to detect trend momentum shifts. Best for trending stocks.',
    buy:  'MACD line > Signal line AND histogram > 0 → BUY',
    sell: 'MACD line < Signal line AND histogram < 0 → SELL',
    neutral: 'Lines converging or histogram near zero → HOLD',
    example: 'NVDA: 12-day EMA crosses above 26-day EMA; MACD histogram flips to +0.42. Strategy buys. Two weeks later histogram turns to −0.18 → strategy sells.',
    tags: ['MACD (12,26,9)', 'EMA 12', 'EMA 26'],
  },
  bollinger_bands: {
    label: 'Bollinger Band Breakout',
    short: 'Buys when price dips below the lower band (oversold) and sells when price rises above the upper band (overbought). Best for mean-reverting stocks.',
    buy:  'Price < Lower Band (SMA20 − 2σ) → BUY',
    sell: 'Price > Upper Band (SMA20 + 2σ) → SELL',
    neutral: 'Price inside the bands → HOLD',
    example: "MSFT 20-day SMA is $415. Bands: upper $435, lower $395. Price falls to $392 (below lower band) → strategy buys. Price recovers to $438 (above upper band) → strategy sells.",
    tags: ['Bollinger Bands (20, 2σ)', 'SMA 20'],
  },
  sma_cross: {
    label: 'SMA Golden / Death Cross',
    short: 'Classic long-term trend strategy: hold while 50-day SMA is above 200-day SMA (uptrend), exit on death cross. Best for index ETFs and blue-chips.',
    buy:  'SMA(50) > SMA(200) → Golden Cross → BUY',
    sell: 'SMA(50) < SMA(200) → Death Cross → SELL',
    neutral: 'SMAs equal or insufficient history → HOLD',
    example: 'SPY: In March the 50-day SMA ($500) crosses above the 200-day SMA ($495) — Golden Cross. Strategy buys. In November the 50-day ($480) falls below 200-day ($487) — Death Cross. Strategy sells.',
    tags: ['SMA 50', 'SMA 200'],
  },
  support_resistance: {
    label: 'Support / Resistance Levels',
    short: 'Buys near recent support (20-day lows) and sells near recent resistance (20-day highs). Best for stocks with a clear trading range.',
    buy:  'Price within 2% above the 20-day support low → BUY',
    sell: 'Price within 2% below the 20-day resistance high → SELL',
    neutral: 'Price in mid-range → HOLD',
    example: 'AMZN trades between $190 support and $215 resistance. Price dips to $191.80 (≤ $190 × 1.02) → strategy buys. Price rises to $213.70 (≥ $215 × 0.98) → strategy sells.',
    tags: ['Support (20-day low)', 'Resistance (20-day high)'],
  },
  volume_momentum: {
    label: 'Volume + Momentum Confirmation',
    short: 'Requires an unusual volume spike to confirm MACD momentum, filtering out low-conviction moves. Best around earnings and news events.',
    buy:  'Volume spike (> 1.5× 20-day avg) AND MACD histogram > 0 → BUY',
    sell: 'Volume spike AND MACD histogram < 0 → SELL',
    neutral: 'No volume spike, or MACD direction unclear → HOLD (falls back to MACD alone)',
    example: 'META earnings day: volume is 3× the 20-day average. MACD histogram is +0.65 (bullish). Both conditions met → strategy buys. Next session volume is normal → strategy holds until MACD turns negative.',
    tags: ['Volume (20-day avg)', 'MACD (12,26,9)'],
  },
}

const initialForm = {
  id: null,
  ticker: '',
  algorithm: 'recommendation',
  allocated_amount: 1000,
  max_loss_pct: 2,
  quantity: '',
  trailing_stop_pct: 3,
}

function fmtTs(ts) {
  if (!ts) return '—'
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function fmtErrDetail(detail) {
  if (!detail) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(e => {
      const loc = Array.isArray(e.loc) ? e.loc.filter(l => l !== 'body').join(' → ') : ''
      return loc ? `${loc}: ${e.msg}` : e.msg
    }).join(' | ')
  }
  return String(detail)
}

function StatusChip({ status }) {
  const map = {
    active: { bg: 'rgba(34,197,94,0.12)', color: '#4ade80', border: 'rgba(34,197,94,0.3)', label: 'Active' },
    paused: { bg: 'rgba(234,179,8,0.1)', color: '#fde047', border: 'rgba(234,179,8,0.3)', label: 'Paused' },
    stopped: { bg: 'rgba(239,68,68,0.1)', color: '#fca5a5', border: 'rgba(239,68,68,0.25)', label: 'Stopped' },
  }
  const s = map[status] || { bg: 'var(--surface2)', color: 'var(--text-muted)', border: 'var(--border)', label: status }
  return (
    <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: s.bg, color: s.color, border: `1px solid ${s.border}` }}>
      {s.label}
    </span>
  )
}

function DecisionChip({ d }) {
  if (!d) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const map = {
    BUY:  { color: '#4ade80' },
    SELL: { color: '#f87171' },
    HOLD: { color: '#fde047' },
  }
  const s = map[d] || { color: 'var(--text-muted)' }
  return <span style={{ fontWeight: 600, fontSize: 12, color: s.color }}>{d}</span>
}

export default function JobsManager() {
  const [jobs, setJobs] = useState([])
  const [settings, setSettings] = useState({ max_total_loss_pct: 10, baseline_portfolio_value: null })
  const [market, setMarket] = useState(null)
  const [form, setForm] = useState(initialForm)
  const [formErrors, setFormErrors] = useState({})
  const [showAlgoInfo, setShowAlgoInfo] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [jobsRes, settingsRes, marketRes] = await Promise.all([
        fetch(API),
        fetch(`${API}/settings`),
        fetch(`${API}/market-status`),
      ])
      const jobsData = await jobsRes.json()
      const settingsData = await settingsRes.json()
      const marketData = await marketRes.json()
      if (!jobsRes.ok) throw new Error(fmtErrDetail(jobsData.detail) || `HTTP ${jobsRes.status}`)
      if (!settingsRes.ok) throw new Error(fmtErrDetail(settingsData.detail) || `HTTP ${settingsRes.status}`)
      if (!marketRes.ok) throw new Error(fmtErrDetail(marketData.detail) || `HTTP ${marketRes.status}`)
      setJobs(jobsData.jobs || [])
      setMarket(marketData)
      setSettings({
        max_total_loss_pct: Number(settingsData.max_total_loss_pct ?? 10),
        baseline_portfolio_value: settingsData.baseline_portfolio_value,
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const onChange = e => {
    const { name, value } = e.target
    setFormErrors(fe => ({ ...fe, [name]: undefined }))
    setForm(f => ({ ...f, [name]: value }))
  }

  const validateForm = () => {
    const errs = {}
    const ticker = String(form.ticker || '').trim()
    if (!ticker) errs.ticker = 'Ticker is required'
    else if (!/^[A-Za-z]{1,10}$/.test(ticker)) errs.ticker = 'Enter a valid ticker (letters only)'
    if (!form.allocated_amount || Number(form.allocated_amount) <= 0) errs.allocated_amount = 'Must be > 0'
    if (form.max_loss_pct === '' || Number(form.max_loss_pct) < 0 || Number(form.max_loss_pct) > 100) errs.max_loss_pct = '0–100'
    if (form.trailing_stop_pct === '' || Number(form.trailing_stop_pct) < 0 || Number(form.trailing_stop_pct) > 50) errs.trailing_stop_pct = '0–50'
    const qty = String(form.quantity).trim()
    if (qty && Number(qty) <= 0) errs.quantity = 'Must be > 0 if set'
    return errs
  }

  const saveSettings = async () => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const res = await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_total_loss_pct: Number(settings.max_total_loss_pct) }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(fmtErrDetail(data.detail) || `HTTP ${res.status}`)
      setMessage('Global max loss setting saved.')
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const saveJob = async () => {
    setMessage('')
    setError('')
    const errs = validateForm()
    if (Object.keys(errs).length) {
      setFormErrors(errs)
      return
    }
    setSaving(true)
    try {
      const payload = {
        ticker: String(form.ticker).trim().toUpperCase(),
        algorithm: form.algorithm,
        allocated_amount: Number(form.allocated_amount),
        max_loss_pct: Number(form.max_loss_pct),
        trailing_stop_pct: Number(form.trailing_stop_pct),
      }
      const qty = String(form.quantity).trim()
      if (qty) payload.quantity = Number(qty)

      const editMode = !!form.id
      const res = await fetch(editMode ? `${API}/${form.id}` : API, {
        method: editMode ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(fmtErrDetail(data.detail) || `HTTP ${res.status}`)
      setMessage(editMode ? `Job "${payload.ticker}" updated.` : `Job "${payload.ticker}" created.`)
      setForm(initialForm)
      setFormErrors({})
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const cancelEdit = () => {
    setForm(initialForm)
    setFormErrors({})
    setError('')
    setMessage('')
  }

  const doAction = async (jobId, action) => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const method = action === 'delete' ? 'DELETE' : 'POST'
      const url = action === 'delete' ? `${API}/${jobId}` : `${API}/${jobId}/${action}`
      const res = await fetch(url, { method })
      const data = await res.json()
      if (!res.ok) throw new Error(fmtErrDetail(data.detail) || `HTTP ${res.status}`)
      setMessage(data.message || 'Done.')
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const editJob = job => {
    setMessage('')
    setError('')
    setFormErrors({})
    setForm({
      id: job.id,
      ticker: job.ticker,
      algorithm: job.algorithm,
      allocated_amount: job.allocated_amount,
      max_loss_pct: job.max_loss_pct,
      quantity: job.quantity ?? '',
      trailing_stop_pct: job.trailing_stop_pct,
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const editMode = !!form.id

  return (
    <div className="profile-page" style={{ maxWidth: '100%' }}>

      {/* ── Page header ── */}
      <div className="pf-header">
        <div>
          <h2>Automated Trading Jobs</h2>
          <p className="pf-subtitle">Configure and monitor automated buy/sell jobs. Jobs run every 5 minutes during market hours.</p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading || saving}>
          {loading ? <><span className="spinner" />Refreshing…</> : '↻ Refresh'}
        </button>
      </div>

      {/* ── Alerts ── */}
      {error && (
        <div className="error-banner">
          <span><strong>Error:</strong> {error}</span>
          <button onClick={() => setError('')}>✕</button>
        </div>
      )}
      {message && (
        <div style={{ background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', color: '#4ade80', borderRadius: 8, padding: '10px 16px', fontSize: 13 }}>
          {message}
        </div>
      )}

      {/* ── Top row: Market Status + Global Risk ── */}
      <div className="pf-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>

        {/* Market Status card */}
        <div className="pf-card">
          <div className="pf-card-title">Market Status</div>
          {market ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    padding: '4px 12px', borderRadius: 20, fontSize: 13, fontWeight: 700,
                    background: market.is_open ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.1)',
                    color: market.is_open ? '#4ade80' : '#f87171',
                    border: `1px solid ${market.is_open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.25)'}`,
                  }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'currentColor', display: 'inline-block' }} />
                  US Market {market.is_open ? 'OPEN' : 'CLOSED'}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div className="kv-row"><span className="k">Current ET</span><span className="v">{fmtTs(market.current_time_et)}</span></div>
                {market.is_open
                  ? <div className="kv-row"><span className="k">Closes at</span><span className="v">{fmtTs(market.next_close_at)}</span></div>
                  : <div className="kv-row"><span className="k">Opens at</span><span className="v">{fmtTs(market.next_open_at)}</span></div>
                }
                <div className="kv-row"><span className="k">Job interval</span><span className="v">{Math.round((market.check_interval_seconds || 300) / 60)} min</span></div>
              </div>
            </div>
          ) : (
            <div className="pf-hint">{loading ? 'Loading…' : 'Unavailable'}</div>
          )}
        </div>

        {/* Global Risk card */}
        <div className="pf-card">
          <div className="pf-card-title">Global Risk Guard</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="pf-field">
              <label className="pf-label">Max Total Portfolio Loss % (all jobs)</label>
              <input
                className="pf-input"
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={settings.max_total_loss_pct}
                onChange={e => setSettings(s => ({ ...s, max_total_loss_pct: e.target.value }))}
                style={{ maxWidth: 140 }}
              />
              <p className="pf-hint">All active jobs are paused if drawdown exceeds this threshold.</p>
            </div>
            <div className="kv-row">
              <span className="k">Baseline portfolio value</span>
              <span className="v">
                {settings.baseline_portfolio_value == null ? 'Not set (recorded on first run)' : `$${Number(settings.baseline_portfolio_value).toLocaleString()}`}
              </span>
            </div>
            <div>
              <button className="btn btn-sm" onClick={saveSettings} disabled={saving}>Save Risk Setting</button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Create / Edit Job ── */}
      <div className="pf-card">
        <div className="pf-card-title">
          {editMode ? `✏️ Edit Job — ${form.ticker}` : '＋ Create New Job'}
        </div>

        <div className="pf-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>

          {/* Ticker */}
          <div className="pf-field">
            <label className="pf-label">Ticker *</label>
            <input
              className={`pf-input${formErrors.ticker ? ' pf-input-err' : ''}`}
              name="ticker"
              value={form.ticker}
              onChange={onChange}
              placeholder="e.g. AAPL"
              style={{ textTransform: 'uppercase' }}
            />
            {formErrors.ticker && <p className="pf-hint" style={{ color: 'var(--red)' }}>{formErrors.ticker}</p>}
          </div>

          {/* Algorithm */}
          <div className="pf-field" style={{ gridColumn: '1 / -1' }}>
            <label className="pf-label">Algorithm</label>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select
                className="pf-input"
                name="algorithm"
                value={form.algorithm}
                onChange={e => { onChange(e); setShowAlgoInfo(true) }}
                style={{ maxWidth: 340 }}
              >
                {Object.entries(ALGO_INFO).map(([key, info]) => (
                  <option key={key} value={key}>{info.label}</option>
                ))}
              </select>
              <button
                type="button"
                title={showAlgoInfo ? 'Hide info' : 'About this algorithm'}
                onClick={() => setShowAlgoInfo(v => !v)}
                style={{
                  width: 28, height: 28, borderRadius: '50%',
                  border: `1px solid ${showAlgoInfo ? 'var(--accent)' : 'var(--border)'}`,
                  background: showAlgoInfo ? 'rgba(99,102,241,0.15)' : 'var(--surface2)',
                  color: showAlgoInfo ? 'var(--accent)' : 'var(--text-muted)',
                  cursor: 'pointer', fontSize: 13, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0, transition: 'all 0.15s',
                }}
              >ℹ</button>
            </div>

            {showAlgoInfo && (() => {
              const info = ALGO_INFO[form.algorithm]
              if (!info) return null
              return (
                <div style={{
                  marginTop: 10, padding: '14px 16px', borderRadius: 10,
                  background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.2)',
                  display: 'flex', flexDirection: 'column', gap: 10,
                }}>
                  {/* Header */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--accent)' }}>{info.label}</span>
                    <button
                      type="button"
                      onClick={() => setShowAlgoInfo(false)}
                      style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}
                    >✕</button>
                  </div>

                  {/* Description */}
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--text)', lineHeight: 1.55 }}>{info.short}</p>

                  {/* Tags */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {info.tags.map(t => (
                      <span key={t} style={{
                        fontSize: 10, padding: '2px 8px', borderRadius: 8, fontWeight: 600,
                        background: 'rgba(99,102,241,0.12)', color: 'var(--accent)',
                        border: '1px solid rgba(99,102,241,0.22)',
                      }}>{t}</span>
                    ))}
                  </div>

                  {/* BUY / SELL / HOLD conditions */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
                    <div style={{ background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: '#4ade80', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>↑ BUY Signal</div>
                      <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>{info.buy}</div>
                    </div>
                    <div style={{ background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: '#f87171', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>↓ SELL Signal</div>
                      <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>{info.sell}</div>
                    </div>
                    <div style={{ background: 'rgba(234,179,8,0.07)', border: '1px solid rgba(234,179,8,0.2)', borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: '#fde047', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>— HOLD</div>
                      <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>{info.neutral}</div>
                    </div>
                  </div>

                  {/* Example scenario */}
                  <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '10px 12px', borderLeft: '3px solid var(--accent)' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>
                      Example Scenario
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.6 }}>{info.example}</div>
                  </div>
                </div>
              )
            })()}
          </div>

          {/* Allocated Amount */}
          <div className="pf-field">
            <label className="pf-label">Allocated Amount ($) *</label>
            <input
              className={`pf-input${formErrors.allocated_amount ? ' pf-input-err' : ''}`}
              type="number"
              min="1"
              step="0.01"
              name="allocated_amount"
              value={form.allocated_amount}
              onChange={onChange}
            />
            {formErrors.allocated_amount
              ? <p className="pf-hint" style={{ color: 'var(--red)' }}>{formErrors.allocated_amount}</p>
              : <p className="pf-hint">Capital used to calculate buy quantity when no quantity override is set.</p>
            }
          </div>

          {/* Max Loss % */}
          <div className="pf-field">
            <label className="pf-label">Max Loss % (this job)</label>
            <input
              className={`pf-input${formErrors.max_loss_pct ? ' pf-input-err' : ''}`}
              type="number"
              min="0"
              max="100"
              step="0.1"
              name="max_loss_pct"
              value={form.max_loss_pct}
              onChange={onChange}
            />
            {formErrors.max_loss_pct
              ? <p className="pf-hint" style={{ color: 'var(--red)' }}>{formErrors.max_loss_pct}</p>
              : <p className="pf-hint">Stop-loss triggered if position drops below this % from entry price.</p>
            }
          </div>

          {/* Trailing Stop % */}
          <div className="pf-field">
            <label className="pf-label">Trailing Stop %</label>
            <input
              className={`pf-input${formErrors.trailing_stop_pct ? ' pf-input-err' : ''}`}
              type="number"
              min="0"
              max="50"
              step="0.1"
              name="trailing_stop_pct"
              value={form.trailing_stop_pct}
              onChange={onChange}
            />
            {formErrors.trailing_stop_pct
              ? <p className="pf-hint" style={{ color: 'var(--red)' }}>{formErrors.trailing_stop_pct}</p>
              : <p className="pf-hint">Sell if price drops this % from the highest price seen while holding.</p>
            }
          </div>

          {/* Quantity override */}
          <div className="pf-field">
            <label className="pf-label">Qty Override <span style={{ textTransform: 'none', fontStyle: 'italic' }}>(optional)</span></label>
            <input
              className={`pf-input${formErrors.quantity ? ' pf-input-err' : ''}`}
              type="number"
              min="0.0001"
              step="0.0001"
              name="quantity"
              value={form.quantity}
              onChange={onChange}
              placeholder="Auto from Alloc $"
            />
            {formErrors.quantity
              ? <p className="pf-hint" style={{ color: 'var(--red)' }}>{formErrors.quantity}</p>
              : <p className="pf-hint">Fixed number of shares to trade. Overrides allocated amount calculation.</p>
            }
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
          <button className="btn" onClick={saveJob} disabled={saving}>
            {saving ? 'Saving…' : editMode ? 'Update Job' : 'Create Job'}
          </button>
          {editMode && (
            <button className="btn btn-ghost btn-sm" onClick={cancelEdit} disabled={saving}>Cancel</button>
          )}
        </div>
      </div>

      {/* ── Jobs table ── */}
      <div>
        <h3 className="pf-section-title" style={{ marginBottom: 10 }}>
          Active Jobs
          {jobs.length > 0 && <span className="badge" style={{ marginLeft: 8 }}>{jobs.length}</span>}
        </h3>

        {loading && jobs.length === 0 ? (
          <div className="pf-loading"><span className="spinner" /> Loading jobs…</div>
        ) : jobs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }}>
            No automated jobs yet. Create one above to get started.
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Algorithm</th>
                  <th>Alloc $</th>
                  <th>Max Loss %</th>
                  <th>Trail %</th>
                  <th>Qty</th>
                  <th>Owned</th>
                  <th>Cost Basis</th>
                  <th>Mkt Value</th>
                  <th>P&amp;L %</th>
                  <th>Stop Price</th>
                  <th>Trail Stop</th>
                  <th>Status</th>
                  <th>Decision</th>
                  <th>Last Action</th>
                  <th>Last Check</th>
                  <th>Next Check</th>
                  <th>Note</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(j => (
                  <tr key={j.id}>
                    <td style={{ fontWeight: 700 }}>{j.ticker}</td>
                    <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>{(ALGO_INFO[j.algorithm] || {}).label || j.algorithm}</td>
                    <td>{j.allocated_amount != null ? `$${Number(j.allocated_amount).toLocaleString()}` : '—'}</td>
                    <td>{j.max_loss_pct != null ? `${j.max_loss_pct}%` : '—'}</td>
                    <td>{j.trailing_stop_pct != null ? `${j.trailing_stop_pct}%` : '—'}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{j.quantity != null ? j.quantity : <span style={{ fontStyle: 'italic' }}>auto</span>}</td>
                    <td style={{ fontWeight: 600 }}>
                      {j.held_qty != null && j.held_qty > 0
                        ? j.held_qty
                        : <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>0</span>}
                    </td>
                    <td>
                      {j.cost_basis != null
                        ? `$${Number(j.cost_basis).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : '—'}
                    </td>
                    <td>
                      {j.market_value != null
                        ? `$${Number(j.market_value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : '—'}
                    </td>
                    <td>
                      {j.gain_loss_pct != null
                        ? <span style={{ fontWeight: 700, color: j.gain_loss_pct >= 0 ? 'var(--green)' : 'var(--red)' }}>
                            {j.gain_loss_pct >= 0 ? '+' : ''}{j.gain_loss_pct.toFixed(2)}%
                          </span>
                        : '—'}
                    </td>
                    <td>{j.stop_loss_price != null ? `$${Number(j.stop_loss_price).toFixed(2)}` : '—'}</td>
                    <td>{j.trailing_stop_price != null ? `$${Number(j.trailing_stop_price).toFixed(2)}` : '—'}</td>
                    <td><StatusChip status={j.status} /></td>
                    <td><DecisionChip d={j.last_decision} /></td>
                    <td style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 160, whiteSpace: 'normal' }}>{j.last_action || '—'}</td>
                    <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{fmtTs(j.last_checked_at)}</td>
                    <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {j.last_checked_at
                        ? fmtTs((j.last_checked_at || 0) + (market?.check_interval_seconds || 300))
                        : '—'}
                    </td>
                    <td style={{ fontSize: 11, color: j.last_error ? 'var(--red)' : 'var(--text-muted)', maxWidth: 200, whiteSpace: 'normal' }}>
                      {j.last_error || '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => editJob(j)} disabled={saving}>Edit</button>
                        {j.status === 'active'
                          ? <button className="btn btn-ghost btn-sm" onClick={() => doAction(j.id, 'pause')} disabled={saving}>Pause</button>
                          : <button className="btn btn-ghost btn-sm" onClick={() => doAction(j.id, 'resume')} disabled={saving}>Resume</button>
                        }
                        {j.status !== 'stopped' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => doAction(j.id, 'stop')} disabled={saving}>Stop</button>
                        )}
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ color: 'var(--red)', borderColor: 'rgba(239,68,68,0.3)' }}
                          onClick={() => doAction(j.id, 'delete')}
                          disabled={saving}
                        >Del</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
