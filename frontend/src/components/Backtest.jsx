import { useState, useEffect } from 'react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Tooltip, Legend, Filler
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

function fmt(n, prefix = '$') {
  if (n == null) return '—'
  return `${prefix}${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function KV({ label, value, valueClass }) {
  return (
    <div className="kv-row">
      <span className="k">{label}</span>
      <span className={`v ${valueClass || ''}`}>{value}</span>
    </div>
  )
}

function RecChip({ rec }) {
  if (!rec) return null
  return (
    <span className={'rec ' + rec.replace(' ', '.')} style={{ fontSize: 13, padding: '4px 14px' }}>
      {rec}
    </span>
  )
}

const TODAY = new Date().toISOString().split('T')[0]
const ONE_YEAR_AGO = new Date(Date.now() - 365 * 86400000).toISOString().split('T')[0]

export default function Backtest({ initialSymbol = '' }) {
  const [symbol, setSymbol] = useState(initialSymbol || '')
  const [simDate, setSimDate] = useState(ONE_YEAR_AGO)
  const [endDate, setEndDate] = useState(TODAY)
  const [capital, setCapital] = useState('10000')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  // When navigated from portfolio with a pre-filled symbol
  useEffect(() => {
    if (initialSymbol) setSymbol(initialSymbol)
  }, [initialSymbol])

  const run = async () => {
    const sym = symbol.trim().toUpperCase()
    if (!sym || !simDate) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const params = new URLSearchParams({
        sim_date: simDate,
        end_date: endDate,
        capital: capital || '10000',
      })
      const res = await fetch(`/api/backtest/${sym}?${params}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleKey = e => { if (e.key === 'Enter') run() }

  // Build combined chart: pre-context price + forward equity curve
  const chartData = result ? (() => {
    const pre = result.pre_equity_curve || []
    const post = result.equity_curve || []

    const allDates = [...pre.map(r => r.date), ...post.map(r => r.date)]
    // Pre: price (normalised to start at capital for visual continuity)
    const preFirst = pre[0]?.price || 1
    const preNorm = pre.map(r => ({
      date: r.date,
      equity: (r.price / preFirst) * Number(result.initial_capital),
    }))

    // Combine: pre price context (normalised), then transition point, then actual equity
    const preData = allDates.map(d => {
      const p = preNorm.find(r => r.date === d)
      return p ? p.equity : null
    })
    const postData = allDates.map(d => {
      const p = post.find(r => r.date === d)
      return p ? p.equity : null
    })

    return {
      labels: allDates,
      datasets: [
        {
          label: 'Pre-signal price (normalised)',
          data: preData,
          borderColor: '#475569',
          backgroundColor: 'transparent',
          borderDash: [4, 3],
          pointRadius: 0,
          borderWidth: 1.5,
          tension: 0.3,
        },
        {
          label: result.action === 'HOLD' ? 'Capital (no position)' : `${result.action} equity curve`,
          data: postData,
          borderColor: result.gain_loss_usd >= 0 ? '#22c55e' : '#ef4444',
          backgroundColor: result.gain_loss_usd >= 0
            ? 'rgba(34,197,94,0.08)'
            : 'rgba(239,68,68,0.08)',
          fill: true,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.3,
        },
      ],
    }
  })() : null

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { color: '#8892a4', font: { size: 11 } } },
      tooltip: {
        callbacks: {
          label: ctx => ` $${Number(ctx.raw).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
        }
      },
    },
    scales: {
      x: {
        ticks: { color: '#8892a4', maxTicksLimit: 8, font: { size: 10 } },
        grid: { color: '#2e3148' },
      },
      y: {
        ticks: { color: '#8892a4', font: { size: 10 }, callback: v => `$${Number(v).toLocaleString()}` },
        grid: { color: '#2e3148' },
      },
    },
  }

  const glColor = result
    ? (result.gain_loss_usd > 0 ? 'pos' : result.gain_loss_usd < 0 ? 'neg' : 'neu')
    : ''

  return (
    <div className="backtest">
      <div className="backtest-form">
        <h2>Back-Test Simulation</h2>
        <p className="backtest-desc">
          Choose a symbol and a past date. TraderBot will compute what signal it would have generated
          on that date (using only data available then) and show what the P&amp;L would have been
          if you followed.
        </p>

        <div className="backtest-inputs">
          <label>
            Symbol
            <input
              type="text"
              placeholder="e.g. AAPL"
              value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              onKeyDown={handleKey}
            />
          </label>
          <label>
            Signal Date
            <input type="date" value={simDate} max={endDate} onChange={e => setSimDate(e.target.value)} />
          </label>
          <label>
            End / Exit Date
            <input type="date" value={endDate} min={simDate} max={TODAY} onChange={e => setEndDate(e.target.value)} />
          </label>
          <label>
            Capital ($)
            <input
              type="number"
              min="100"
              step="100"
              value={capital}
              onChange={e => setCapital(e.target.value)}
              onKeyDown={handleKey}
            />
          </label>
          <button className="btn" onClick={run} disabled={loading || !symbol.trim()}>
            {loading ? <><span className="spinner" />Running…</> : '▶ Run Simulation'}
          </button>
        </div>

        {error && (
          <div className="error-banner" style={{ marginTop: 12 }}>
            <strong>Error:</strong> {error}
            <button onClick={() => setError(null)}>✕</button>
          </div>
        )}
      </div>

      {result && (
        <div className="backtest-result">
          {/* Summary header */}
          <div className="bt-summary">
            <div className="bt-symbol">{result.symbol}</div>
            <RecChip rec={result.final_recommendation} />
            <div className={`bt-gl ${glColor}`}>
              {result.action === 'HOLD'
                ? 'No position (HOLD)'
                : <>
                    {result.gain_loss_usd >= 0 ? '+' : ''}{fmt(result.gain_loss_usd)}
                    {' '}
                    <span style={{ fontSize: 14 }}>
                      ({result.gain_loss_pct >= 0 ? '+' : ''}{Number(result.gain_loss_pct).toFixed(2)}%)
                    </span>
                  </>
              }
            </div>
          </div>

          {/* Chart */}
          <div className="chart-container" style={{ height: 260 }}>
            <Line data={chartData} options={chartOptions} />
          </div>

          <div className="detail-grid" style={{ marginTop: 16 }}>

            {/* Trade summary */}
            <div className="detail-section">
              <h3>Simulation Summary</h3>
              <KV label="Signal Date" value={result.sim_date} />
              <KV label="Exit Date" value={result.end_date} />
              <KV label="Action Taken" value={result.action}
                valueClass={result.action === 'BUY' ? 'pos' : result.action === 'SELL' ? 'neg' : 'neu'} />
              <KV label="Entry Price" value={fmt(result.entry_price)} />
              <KV label="Exit Price" value={fmt(result.exit_price)} />
              <KV label="Shares" value={result.action !== 'HOLD' ? result.shares : '—'} />
              <KV label="Initial Capital" value={fmt(result.initial_capital)} />
              <KV label="Final Equity" value={fmt(result.final_equity)} valueClass={glColor} />
              <KV
                label="Gain / Loss"
                value={`${result.gain_loss_usd >= 0 ? '+' : ''}${fmt(result.gain_loss_usd)} (${result.gain_loss_pct >= 0 ? '+' : ''}${Number(result.gain_loss_pct).toFixed(2)}%)`}
                valueClass={glColor}
              />
            </div>

            {/* Signal breakdown */}
            <div className="detail-section">
              <h3>Signal Breakdown on {result.sim_date}</h3>
              <KV label="Combined Score" value={`${result.combined_score >= 0 ? '+' : ''}${result.combined_score}`}
                valueClass={result.combined_score > 0 ? 'pos' : result.combined_score < 0 ? 'neg' : 'neu'} />
              <KV label="Technical Score" value={`${result.technical_score >= 0 ? '+' : ''}${result.technical_score}`} />
              <KV label="Congress Score" value={`${result.congress_score >= 0 ? '+' : ''}${result.congress_score}`} />
              <KV label="Congress Signal" value={result.congress_signal_label}
                valueClass={result.congress_signal_label === 'BULLISH' ? 'pos' : result.congress_signal_label === 'BEARISH' ? 'neg' : 'neu'} />
              {Object.entries(result.indicators || {})
                .filter(([k]) => !k.endsWith('_signal') && !k.endsWith('_cross') && typeof result.indicators[k] !== 'string')
                .map(([k, v]) => <KV key={k} label={k.replace(/_/g, ' ').toUpperCase()} value={v} />)}
            </div>

            {/* Indicator signals */}
            <div className="detail-section">
              <h3>Indicator Signals on {result.sim_date}</h3>
              {Object.entries(result.indicators || {})
                .filter(([k]) => k.endsWith('_signal') || k.endsWith('_cross'))
                .map(([k, v]) => {
                  const isBull = /bullish|oversold|above/i.test(String(v))
                  const isBear = /bearish|overbought|below/i.test(String(v))
                  return (
                    <KV key={k}
                      label={k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                      value={String(v)}
                      valueClass={isBull ? 'pos' : isBear ? 'neg' : 'neu'}
                    />
                  )
                })}
            </div>

            {/* Congress trades visible at sim_date */}
            {result.congress_trades_at_sim_date?.length > 0 && (
              <div className="detail-section">
                <h3>Congress Trades Visible on {result.sim_date}</h3>
                {result.congress_trades_at_sim_date.map((t, i) => {
                  const isBuy = /purchase|buy/i.test(t.transaction)
                  return (
                    <div key={i} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                      <span className={isBuy ? 'tx-buy' : 'tx-sell'}>
                        {isBuy ? '▲' : '▼'} {t.transaction}
                      </span>
                      {' '}by {t.politician} ({t.party})
                      <span style={{ color: 'var(--text-muted)', float: 'right' }}>{t.trade_date}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
