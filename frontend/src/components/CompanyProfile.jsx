import { useState, useEffect, useMemo, useRef } from 'react'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Tooltip, Legend, Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import Backtest from './Backtest'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

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

function StatsCard({ cardId, title, expandedMap = {}, onToggle, collapsible = false, children }) {
  const expanded = collapsible && !!expandedMap[cardId]
  return (
    <div className={`cp-stats-card cp-stats-card-eq ${expanded ? 'expanded' : ''}`}>
      <div className="cp-stats-card-head">
        <div className="cp-stats-card-title">{title}</div>
        {collapsible && (
          <button
            type="button"
            className="cp-card-expand-btn"
            onClick={() => onToggle(cardId)}
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        )}
      </div>
      <div className="cp-stats-card-body">
        {children}
      </div>
    </div>
  )
}

function RecBadge({ rec, onClick }) {
  if (!rec) return null
  const r = rec.toLowerCase()
  const cls = r.includes('buy') || r === 'strong_buy' ? 'pos'
            : r.includes('sell') || r === 'strong_sell' ? 'neg'
            : 'neu'
  if (onClick) {
    return (
      <button
        type="button"
        className={`cp-rec-badge ${cls} cp-rec-badge-btn`}
        onClick={onClick}
        title="Click to explain this signal"
      >
        {rec.replace(/_/g, ' ').toUpperCase()} ℹ
      </button>
    )
  }
  return <span className={`cp-rec-badge ${cls}`}>{rec.replace(/_/g, ' ').toUpperCase()}</span>
}

// ── Signal Breakdown Dialog ───────────────────────────────────────────────────
const FACTOR_META = {
  technical:        { label: 'Technical Indicators',   icon: '📈', maxContrib: 1.2,  desc: 'RSI(14), MACD(12/26/9), Bollinger Bands(20), SMA50 vs SMA200. Each indicator contributes ±1 to the raw score, then capped at ±1.2.' },
  support_resistance:{ label: 'Support / Resistance',  icon: '🧭', maxContrib: 0.8,  desc: 'Near support is bullish, near resistance is bearish. Also provides suggested stop-loss and take-profit levels.' },
  congressional:    { label: 'Congressional Trades',   icon: '🏛', maxContrib: 1.0,  desc: 'Net purchases vs sales disclosed by US Congress members in the last 30 days. Score capped at ±1.0.' },
  news_research:    { label: 'News & Research',        icon: '📰', maxContrib: 1.0,  desc: 'Headline-level sentiment from related news and analyst research, weighted by recency. Positive tone biases bullish, negative tone biases bearish.' },
  alternative_data: { label: 'Alternative Data',       icon: '📡', maxContrib: 2.0,  desc: 'Aggregated sentiment from news, social signals, and alternative data providers. Score range −2 to +2.' },
  fundamentals:     { label: 'Fundamentals',           icon: '📊', maxContrib: 2.0,  desc: 'P/E Ratio (< 15 bullish / > 30 bearish), Debt-to-Equity (< 0.5 bullish / > 2 bearish), Current Ratio (> 1.5 bullish / < 1 bearish).' },
  options_chain:    { label: 'Options Chain (P/C)',    icon: '🎯', maxContrib: 2.0,  desc: 'Put/Call open interest ratio. < 0.6 = strong bullish, < 0.8 = moderate bullish, > 1.3 = bearish, > 1.5 = strong bearish.' },
  momentum:         { label: 'Price Momentum',         icon: '🚀', maxContrib: 1.5,  desc: 'Daily price change (> +2% bullish, < −2% bearish) and 52-week return (> 20% bullish, < −20% bearish).' },
}

const THRESHOLDS = [
  { range: '≥ +5',      signal: 'STRONG BUY',  cls: 'pos' },
  { range: '+2.5 to +5', signal: 'BUY',        cls: 'pos' },
  { range: '−2.5 to +2.5', signal: 'HOLD',    cls: 'neu' },
  { range: '−5 to −2.5', signal: 'SELL',       cls: 'neg' },
  { range: '≤ −5',      signal: 'STRONG SELL', cls: 'neg' },
]

function SignalBreakdownDialog({ signal, score, factors, title, riskTolerance, onClose }) {
  if (!factors) return null
  const sigText = (signal || 'HOLD').replace(/_/g, ' ')
  const isBuy  = sigText.includes('BUY')
  const isSell = sigText.includes('SELL')
  const sigCls = isBuy ? 'pos' : isSell ? 'neg' : 'neu'
  const scoreNum = typeof score === 'number' ? score : 0
  const scoreColor = scoreNum > 0 ? 'pos' : scoreNum < 0 ? 'neg' : ''

  function FactorBar({ contrib, maxContrib = 2 }) {
    const pct = Math.min(100, Math.abs(contrib) / maxContrib * 50)
    return (
      <div className="sig-factor-bar-wrap">
        {contrib >= 0
          ? <div className="sig-factor-bar pos" style={{ width: `${pct}%` }} />
          : <div className="sig-factor-bar neg" style={{ width: `${pct}%` }} />
        }
      </div>
    )
  }

  const factorOrder = ['technical', 'support_resistance', 'congressional', 'news_research', 'alternative_data', 'fundamentals', 'options_chain', 'momentum']

  return (
    <div className="sig-dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="sig-dialog">
        <div className="sig-dialog-header">
          <div>
            <div className="sig-dialog-title">💡 Signal Explanation</div>
            <div className="sig-dialog-subtitle">{title ? `${title} — ` : ''}How this signal is calculated</div>
          </div>
          <button className="sig-dialog-close" onClick={onClose}>✕</button>
        </div>

        {/* Overall result */}
        <div className="sig-score-band">
          <span className={`sig-overall-signal ${sigCls}`}>{sigText}</span>
          <div>
            <div className="sig-score-label">Combined Score</div>
            <div className={`sig-score-num ${scoreColor}`}>{scoreNum >= 0 ? '+' : ''}{scoreNum.toFixed(2)}</div>
          </div>
          {riskTolerance != null && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <div className="sig-score-label">Risk Tolerance</div>
              <div className="sig-score-num" style={{ fontSize: 18 }}>{riskTolerance}/10</div>
              <div style={{ fontSize: 11, opacity: 0.65 }}>
                {riskTolerance <= 3 ? 'Conservative' : riskTolerance <= 6 ? 'Moderate' : 'Aggressive'}
              </div>
            </div>
          )}
          <div className="sig-scale-hint">
            {THRESHOLDS.map(t => (
              <div key={t.signal} style={{ display: 'flex', gap: 8, justifyContent: 'space-between' }}>
                <span>{t.range}</span>
                <span className={t.cls} style={{ fontWeight: 700 }}>{t.signal}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Factor rows */}
        <div className="sig-factors-list">
          {factorOrder.map(key => {
            const f = factors[key]
            if (!f) return null
            const meta = FACTOR_META[key] || { label: key, icon: '•', maxContrib: 2, desc: '' }
            const contrib = typeof f.contribution === 'number' ? f.contribution : 0
            const cls = contrib > 0 ? 'pos' : contrib < 0 ? 'neg' : ''
            const details = []
            if (key === 'technical') {
              if (f.score != null) details.push(`Raw score: ${f.score >= 0 ? '+' : ''}${f.score}`)
              if (f.recommendation) details.push(`Signal: ${f.recommendation}`)
            } else if (key === 'congressional') {
              if (f.signal) details.push(`Signal: ${f.signal}`)
              if (f.score != null) details.push(`Raw score: ${f.score >= 0 ? '+' : ''}${f.score}`)
            } else if (key === 'alternative_data') {
              if (f.score != null) details.push(`Score: ${f.score}`)
              if (f.label) details.push(`Status: ${f.label}`)
            } else if (key === 'news_research') {
              if (f.signal) details.push(`Signal: ${f.signal}`)
              if (f.score != null) details.push(`Sentiment: ${Number(f.score).toFixed(2)}`)
              if (f.bullish_mentions != null) details.push(`Bullish hits: ${f.bullish_mentions}`)
              if (f.bearish_mentions != null) details.push(`Bearish hits: ${f.bearish_mentions}`)
              if (f.scored_items != null && f.considered_items != null) details.push(`Scored items: ${f.scored_items}/${f.considered_items}`)
            } else if (key === 'fundamentals') {
              if (f.pe_ratio != null) details.push(`P/E: ${f.pe_ratio}`)
              if (f.debt_to_equity != null) details.push(`D/E: ${f.debt_to_equity}`)
              if (f.current_ratio != null) details.push(`Current Ratio: ${f.current_ratio}`)
            } else if (key === 'support_resistance') {
              if (f.signal) details.push(`Signal: ${f.signal}`)
              if (f.stop_loss_suggestion != null) details.push(`Stop: $${Number(f.stop_loss_suggestion).toFixed(2)}`)
              if (f.take_profit_1 != null) details.push(`TP1: $${Number(f.take_profit_1).toFixed(2)}`)
              if (f.take_profit_2 != null) details.push(`TP2: $${Number(f.take_profit_2).toFixed(2)}`)
              if (f.risk_reward_tp1 != null) details.push(`R/R TP1: ${Number(f.risk_reward_tp1).toFixed(2)}`)
            } else if (key === 'options_chain') {
              if (f.put_call_ratio != null) details.push(`P/C Ratio: ${Number(f.put_call_ratio).toFixed(2)}`)
              else details.push('No options data')
            } else if (key === 'momentum') {
              if (f.day_change_pct != null) details.push(`Day: ${f.day_change_pct >= 0 ? '+' : ''}${Number(f.day_change_pct).toFixed(2)}%`)
              if (f['52w_change_pct'] != null) details.push(`52w: ${f['52w_change_pct'] >= 0 ? '+' : ''}${Number(f['52w_change_pct']).toFixed(2)}%`)
            }
            return (
              <div key={key} className="sig-factor-row">
                <div className="sig-factor-top">
                  <span style={{ fontSize: 14 }}>{meta.icon}</span>
                  <span className="sig-factor-name">{meta.label}</span>
                  <span className="sig-factor-weight">{f.weight || meta.weight || '—'}</span>
                  <span className={`sig-factor-contrib ${cls}`}>{contrib >= 0 ? '+' : ''}{contrib.toFixed(2)}</span>
                </div>
                <FactorBar contrib={contrib} maxContrib={meta.maxContrib} />
                {details.length > 0 && (
                  <div className="sig-factor-detail">
                    {details.map((d, i) => <span key={i}>{d}</span>)}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Technical indicator details */}
        {factors.technical?.indicators && Object.keys(factors.technical.indicators).length > 0 && (
          <div className="sig-indicator-list">
            <div className="sig-indicator-list-title">📐 Technical Indicator Values</div>
            {Object.entries(factors.technical.indicators)
              .filter(([k]) => k.endsWith('_signal') || k.endsWith('_cross'))
              .map(([k, v]) => {
                const isBull = /bullish|oversold|above/i.test(String(v))
                const isBear = /bearish|overbought|below/i.test(String(v))
                return (
                  <div className="sig-indicator-row" key={k}>
                    <span className="sig-indicator-k">{k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
                    <span className={isBull ? 'pos' : isBear ? 'neg' : 'neu'}>{String(v)}</span>
                  </div>
                )
              })}
          </div>
        )}

        {/* Formula note */}
        <div className="sig-formula-note" style={{ marginTop: 14 }}>
          <strong>How it works:</strong> Each factor above contributes a score between its minimum and maximum.
          The contributions are summed to produce the combined score.
          {riskTolerance != null && riskTolerance <= 3
            ? ' Conservative profile: requires score ≥ +6 → STRONG BUY, ≥ +3.5 → BUY, ≤ −6 → STRONG SELL, ≤ −3.5 → SELL.'
            : riskTolerance != null && riskTolerance >= 7
              ? ' Aggressive profile: score ≥ +3.5 → STRONG BUY, ≥ +1.5 → BUY, ≤ −3.5 → STRONG SELL, ≤ −1.5 → SELL.'
              : ' Moderate profile: score ≥ +5 → STRONG BUY, ≥ +2.5 → BUY, ≤ −5 → STRONG SELL, ≤ −2.5 → SELL.'}
          {' '}Congressional and options data may not be available for historical back-test dates.
        </div>
      </div>
    </div>
  )
}

function getAltLiveSignal(score10) {
  if (score10 >= 6.5) return 'STRONG BUY'
  if (score10 >= 3.5) return 'BUY'
  if (score10 <= -6.5) return 'STRONG SELL'
  if (score10 <= -3.5) return 'SELL'
  return 'HOLD'
}

// ── FMP Enrichment Panel ──────────────────────────────────────────────────────
function FmpDataPanel({ fmp, loading }) {
  const [showAllInsiders, setShowAllInsiders] = useState(false)
  const [showAllGrades, setShowAllGrades]     = useState(false)

  if (loading && (!fmp || !fmp.available)) {
    return (
      <div className="cp-chain-section">
        <div className="cp-chain-header">
          <span className="cp-chain-icon">💹</span>
          <h3 className="cp-section-title">FMP Financial Intelligence</h3>
        </div>
        <div className="cp-skeleton-rows" style={{ padding: '12px 0' }}>
          <div className="cp-skeleton" style={{ height: 32, marginBottom: 8 }} />
          <div className="cp-skeleton" />
          <div className="cp-skeleton" />
        </div>
      </div>
    )
  }

  if (!fmp || !fmp.available) return null

  const v    = fmp.valuation   || {}
  const r    = fmp.rating      || {}
  const km   = fmp.key_metrics || {}
  const prof = fmp.profile     || {}

  const pioClass = km.piotroski_score != null
    ? km.piotroski_score >= 7 ? 'pos' : km.piotroski_score <= 3 ? 'neg' : 'neu'
    : ''

  const dcfClass = v.dcf_upside_pct != null
    ? v.dcf_upside_pct > 10 ? 'pos' : v.dcf_upside_pct < -10 ? 'neg' : 'neu'
    : ''

  const targetClass = v.target_upside_pct != null
    ? v.target_upside_pct > 10 ? 'pos' : v.target_upside_pct < -10 ? 'neg' : 'neu'
    : ''

  const ratingCls = r.score != null
    ? r.score >= 4 ? 'pos' : r.score <= 2 ? 'neg' : 'neu'
    : ''

  const fmtScore = n => n != null ? (n >= 0 ? `+${Number(n).toFixed(2)}` : `${Number(n).toFixed(2)}`) : '—'
  const fmtPctS  = n => n != null ? `${n >= 0 ? '+' : ''}${Number(n).toFixed(2)}%` : '—'
  const fmtP     = n => n != null ? `$${Number(n).toFixed(2)}` : '—'
  const fmtN2    = n => n != null ? Number(n).toFixed(2) : '—'
  const fmtPct100 = n => n != null ? `${(Number(n) * 100).toFixed(2)}%` : '—'

  const SCORE_LABELS = { 1: 'Strong Sell', 2: 'Sell', 3: 'Neutral', 4: 'Buy', 5: 'Strong Buy' }

  const insiders  = fmp.insider_trades    || []
  const grades    = fmp.analyst_grades    || []
  const surprises = fmp.earnings_surprises|| []
  const estimates = fmp.analyst_estimates || []

  const recentInsiders = insiders.filter(t => t.recent)
  const displayInsiders= showAllInsiders ? insiders : insiders.slice(0, 6)
  const displayGrades  = showAllGrades   ? grades   : grades.slice(0, 5)

  return (
    <div className="cp-chain-section cp-fmp-section">
      <div className="cp-chain-header">
        <span className="cp-chain-icon">💹</span>
        <h3 className="cp-section-title">FMP Financial Intelligence</h3>
        <a
          href={`https://site.financialmodelingprep.com/financial-summary/${fmp.profile?.symbol || ''}`}
          className="cp-source-link"
          target="_blank"
          rel="noreferrer"
          style={{ marginLeft: 'auto' }}
        >
          View on FMP ↗
        </a>
      </div>

      <div className="cp-stats-grid">

        {/* Valuation card */}
        <div className="cp-stats-card">
          <div className="cp-stats-card-title">📐 Intrinsic Valuation</div>
          <div className="cp-stats-card-body">
            <div className="cp-stat"><span className="cp-stat-label">Current Price</span><span className="cp-stat-value">{fmtP(v.price)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">DCF Fair Value</span><span className={`cp-stat-value ${dcfClass}`}>{fmtP(v.dcf)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">DCF Upside</span><span className={`cp-stat-value ${dcfClass}`}>{fmtPctS(v.dcf_upside_pct)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Analyst Consensus</span><span className={`cp-stat-value ${targetClass}`}>{fmtP(v.target_consensus)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Target Upside</span><span className={`cp-stat-value ${targetClass}`}>{fmtPctS(v.target_upside_pct)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Target High</span><span className="cp-stat-value">{fmtP(v.target_high)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Target Low</span><span className="cp-stat-value">{fmtP(v.target_low)}</span></div>
          </div>
        </div>

        {/* FMP Rating card */}
        <div className="cp-stats-card">
          <div className="cp-stats-card-title">⭐ FMP Composite Rating</div>
          <div className="cp-stats-card-body">
            {r.rating && (
              <div className="cp-fmp-rating-badge-row">
                <span className={`cp-fmp-rating-badge ${ratingCls}`}>{r.rating}</span>
                <span className={`cp-stat-value ${ratingCls}`}>{r.recommendation || '—'}</span>
              </div>
            )}
            <div className="cp-stat"><span className="cp-stat-label">Overall Score</span><span className={`cp-stat-value ${ratingCls}`}>{r.score != null ? `${r.score}/5 — ${SCORE_LABELS[r.score] || ''}` : '—'}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">DCF Score</span><span className="cp-stat-value">{r.dcf_score != null ? `${r.dcf_score}/5 — ${r.dcf_rec || ''}` : '—'}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">ROE Score</span><span className="cp-stat-value">{r.roe_score != null ? `${r.roe_score}/5 — ${r.roe_rec || ''}` : '—'}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">ROA Score</span><span className="cp-stat-value">{r.roa_score != null ? `${r.roa_score}/5 — ${r.roa_rec || ''}` : '—'}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">D/E Score</span><span className="cp-stat-value">{r.de_score != null ? `${r.de_score}/5 — ${r.de_rec || ''}` : '—'}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">P/E Score</span><span className="cp-stat-value">{r.pe_score != null ? `${r.pe_score}/5 — ${r.pe_rec || ''}` : '—'}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">P/B Score</span><span className="cp-stat-value">{r.pb_score != null ? `${r.pb_score}/5 — ${r.pb_rec || ''}` : '—'}</span></div>
          </div>
        </div>

        {/* Key Metrics card */}
        <div className="cp-stats-card">
          <div className="cp-stats-card-title">📊 Key Metrics (FMP)</div>
          <div className="cp-stats-card-body">
            <div className="cp-stat"><span className="cp-stat-label">P/E Ratio</span><span className="cp-stat-value">{fmtN2(km.pe_ratio)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">P/B Ratio</span><span className="cp-stat-value">{fmtN2(km.pb_ratio)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">EV/EBITDA</span><span className="cp-stat-value">{fmtN2(km.ev_to_ebitda)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">EV/Sales</span><span className="cp-stat-value">{fmtN2(km.ev_to_sales)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">ROE</span><span className={`cp-stat-value ${km.roe > 0.15 ? 'pos' : km.roe < 0 ? 'neg' : ''}`}>{fmtPct100(km.roe)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">ROA</span><span className={`cp-stat-value ${km.roa > 0.05 ? 'pos' : km.roa < 0 ? 'neg' : ''}`}>{fmtPct100(km.roa)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">ROIC</span><span className="cp-stat-value">{fmtPct100(km.roic)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Debt/Equity</span><span className={`cp-stat-value ${km.debt_to_equity < 0.5 ? 'pos' : km.debt_to_equity > 2 ? 'neg' : ''}`}>{fmtN2(km.debt_to_equity)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Current Ratio</span><span className={`cp-stat-value ${km.current_ratio > 1.5 ? 'pos' : km.current_ratio < 1 ? 'neg' : ''}`}>{fmtN2(km.current_ratio)}</span></div>
            <div className="cp-stat">
              <span className="cp-stat-label">Piotroski F-Score</span>
              <span className={`cp-stat-value ${pioClass}`}>
                {km.piotroski_score != null ? `${km.piotroski_score}/9${km.piotroski_score >= 7 ? ' (Strong)' : km.piotroski_score <= 3 ? ' (Weak)' : ' (Neutral)'}` : '—'}
              </span>
            </div>
            <div className="cp-stat"><span className="cp-stat-label">FCF Yield</span><span className="cp-stat-value">{fmtPct100(km.free_cashflow_yield)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Earnings Yield</span><span className="cp-stat-value">{fmtPct100(km.earnings_yield)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Dividend Yield</span><span className="cp-stat-value">{fmtPct100(km.dividend_yield)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Gross Margin</span><span className="cp-stat-value">{fmtPct100(km.gross_profit_margin)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Net Margin</span><span className="cp-stat-value">{fmtPct100(km.net_profit_margin)}</span></div>
            <div className="cp-stat"><span className="cp-stat-label">Operating Margin</span><span className="cp-stat-value">{fmtPct100(km.operating_profit_margin)}</span></div>
          </div>
        </div>

        {/* Forward Estimates card */}
        {estimates.length > 0 && (
          <div className="cp-stats-card">
            <div className="cp-stats-card-title">🔮 Analyst Estimates (Forward)</div>
            <div className="cp-stats-card-body">
              {estimates.map((e, i) => (
                <div key={i} className="cp-fmp-estimate-row">
                  <div className="cp-fmp-estimate-date">{e.date || '—'}</div>
                  <div className="cp-fmp-estimate-vals">
                    <span>EPS avg: <strong>{e.eps_avg != null ? `$${Number(e.eps_avg).toFixed(2)}` : '—'}</strong></span>
                    <span>Range: {e.eps_low != null ? `$${Number(e.eps_low).toFixed(2)}` : '—'} – {e.eps_high != null ? `$${Number(e.eps_high).toFixed(2)}` : '—'}</span>
                    <span>Rev avg: <strong>{e.revenue_avg != null ? fmtMoney(e.revenue_avg, 0) : '—'}</strong></span>
                    <span className="cp-fmp-analyst-count">{e.analysts_eps != null ? `${e.analysts_eps} analysts` : ''}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* Earnings Surprises */}
      {surprises.length > 0 && (
        <div className="cp-fmp-surprises-section">
          <div className="cp-fmp-subsection-title">📋 Earnings Surprise History</div>
          <div className="table-wrap">
            <table className="cp-chain-table">
              <thead>
                <tr>
                  <th>Quarter</th>
                  <th>Estimated EPS</th>
                  <th>Actual EPS</th>
                  <th>Surprise</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {surprises.map((s, i) => (
                  <tr key={i}>
                    <td>{s.date || '—'}</td>
                    <td>${s.estimated != null ? Number(s.estimated).toFixed(4) : '—'}</td>
                    <td>${s.actual    != null ? Number(s.actual).toFixed(4)    : '—'}</td>
                    <td className={s.surprise_pct > 0 ? 'pos' : s.surprise_pct < 0 ? 'neg' : ''}>
                      {s.surprise_pct != null ? `${s.surprise_pct > 0 ? '+' : ''}${Number(s.surprise_pct).toFixed(2)}%` : '—'}
                    </td>
                    <td>
                      <span className={`cp-fmp-beat-badge ${s.beat ? 'pos' : 'neg'}`}>
                        {s.beat ? 'BEAT' : 'MISS'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Insider Activity */}
      {insiders.length > 0 && (
        <div className="cp-fmp-surprises-section">
          <div className="cp-fmp-subsection-title">
            🕵️ Insider Activity
            {recentInsiders.length > 0 && (
              <span className="cp-chain-count" style={{ marginLeft: 8 }}>{recentInsiders.length} in last 90 days</span>
            )}
          </div>
          <div className="table-wrap">
            <table className="cp-chain-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Shares</th>
                  <th>Price</th>
                </tr>
              </thead>
              <tbody>
                {displayInsiders.map((t, i) => (
                  <tr key={i} className={t.recent ? 'cp-fmp-insider-recent' : ''}>
                    <td>{t.name || '—'}</td>
                    <td>{t.date || '—'}</td>
                    <td><span className={`cp-fmp-beat-badge ${t.type === 'BUY' ? 'pos' : 'neg'}`}>{t.type}</span></td>
                    <td>{t.shares != null ? t.shares.toLocaleString() : '—'}</td>
                    <td>{t.price != null ? `$${Number(t.price).toFixed(2)}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {insiders.length > 6 && (
            <button
              type="button"
              className="btn btn-ghost btn-sm cp-news-toggle"
              onClick={() => setShowAllInsiders(v => !v)}
            >
              {showAllInsiders ? 'Show fewer' : `Show all ${insiders.length} trades`}
            </button>
          )}
        </div>
      )}

      {/* Analyst Grades */}
      {grades.length > 0 && (
        <div className="cp-fmp-surprises-section">
          <div className="cp-fmp-subsection-title">🏦 Recent Analyst Grades</div>
          <div className="table-wrap">
            <table className="cp-chain-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Firm</th>
                  <th>Action</th>
                  <th>From</th>
                  <th>To</th>
                </tr>
              </thead>
              <tbody>
                {displayGrades.map((g, i) => {
                  const actionCls = /upgrade/i.test(g.action || '') ? 'pos'
                                  : /downgrade/i.test(g.action || '') ? 'neg' : ''
                  return (
                    <tr key={i}>
                      <td>{g.date || '—'}</td>
                      <td>{g.company || '—'}</td>
                      <td className={actionCls}>{g.action || '—'}</td>
                      <td>{g.from || '—'}</td>
                      <td>{g.to || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {grades.length > 5 && (
            <button
              type="button"
              className="btn btn-ghost btn-sm cp-news-toggle"
              onClick={() => setShowAllGrades(v => !v)}
            >
              {showAllGrades ? 'Show fewer' : `Show all ${grades.length} grades`}
            </button>
          )}
        </div>
      )}

    </div>
  )
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
      alpha_vantage_news_sentiment: symbol ? `https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=${symbol}&sort=LATEST&limit=10&apikey=demo` : 'https://www.alphavantage.co/documentation/#news-sentiment',
      polygon: symbol ? `https://polygon.io/stocks/${symbol}` : 'https://polygon.io',
      financial_modeling_prep: symbol ? `https://site.financialmodelingprep.com/financial-summary/${symbol}` : 'https://site.financialmodelingprep.com',
      eodhd: symbol ? `https://eodhd.com/financial-summary/${symbol}.US` : 'https://eodhd.com',
      fred: `https://fred.stlouisfed.org/graph/?id=DFF,UNRATE,CPIAUCSL`,
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

function NewsResearchPanel({ relatedNews = [], analystResearch = [], newsUpdatedAt, newsFactor, loading = false }) {
  const initialVisibleCount = 5
  const [showAllNews, setShowAllNews] = useState(false)
  const [showAllResearch, setShowAllResearch] = useState(false)

  const toSortedWithTs = items => (
    [...items]
      .map((item, idx) => {
        const ts = Date.parse(item?.published_at || '')
        return { ...item, _ts: Number.isFinite(ts) ? ts : null, _idx: idx }
      })
      .sort((a, b) => {
        const at = a._ts ?? -1
        const bt = b._ts ?? -1
        if (bt !== at) return bt - at
        return a._idx - b._idx
      })
  )

  const fmtAge = ts => {
    if (!ts) return 'age unknown'
    const deltaMs = Math.max(0, Date.now() - ts)
    const mins = Math.floor(deltaMs / 60000)
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days}d ago`
    const weeks = Math.floor(days / 7)
    if (weeks < 5) return `${weeks}w ago`
    const months = Math.floor(days / 30)
    if (months < 12) return `${months}mo ago`
    const years = Math.floor(days / 365)
    return `${years}y ago`
  }

  const fmtPublisher = publisher => {
    if (!publisher) return 'Source'

    if (typeof publisher === 'object') {
      return publisher.displayName || publisher.name || publisher.publisher || publisher.sourceId || 'Source'
    }

    const raw = String(publisher).trim()
    if (!raw) return 'Source'

    const looksLikePayload = raw.startsWith('{') && raw.endsWith('}')
    if (!looksLikePayload) return raw

    const displayNameMatch = raw.match(/['\"]?displayName['\"]?\s*:\s*['\"]([^'\"]+)['\"]/i)
    if (displayNameMatch?.[1]) return displayNameMatch[1]

    const nameMatch = raw.match(/['\"]?name['\"]?\s*:\s*['\"]([^'\"]+)['\"]/i)
    if (nameMatch?.[1]) return nameMatch[1]

    const sourceIdMatch = raw.match(/['\"]?sourceId['\"]?\s*:\s*['\"]([^'\"]+)['\"]/i)
    if (sourceIdMatch?.[1]) {
      return sourceIdMatch[1]
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase())
    }

    return 'Source'
  }

  const sortedNews = useMemo(() => toSortedWithTs(relatedNews), [relatedNews])
  const sortedResearch = useMemo(() => toSortedWithTs(analystResearch), [analystResearch])

  const visibleNews = showAllNews ? sortedNews : sortedNews.slice(0, initialVisibleCount)
  const visibleResearch = showAllResearch ? sortedResearch : sortedResearch.slice(0, initialVisibleCount)
  const hasMoreNews = sortedNews.length > initialVisibleCount
  const hasMoreResearch = sortedResearch.length > initialVisibleCount

  return (
    <div className="cp-chain-section cp-news-section">
      <div className="cp-chain-header">
        <span className="cp-chain-icon">📰</span>
        <SectionTitle>News & Research</SectionTitle>
        <span className="cp-chain-count">{relatedNews.length + analystResearch.length} items</span>
      </div>

      {newsUpdatedAt && (
        <div className="cp-news-updated">Updated: {String(newsUpdatedAt).replace('T', ' ').slice(0, 16)} UTC</div>
      )}

      {newsFactor?.signal && (
        <div className="cp-news-signal-row">
          <span className="cp-news-signal-label">News Signal</span>
          <RecBadge rec={newsFactor.signal} />
          {newsFactor.contribution != null && (
            <span className={`cp-news-signal-contrib ${Number(newsFactor.contribution) > 0 ? 'pos' : Number(newsFactor.contribution) < 0 ? 'neg' : 'neu'}`}>
              {Number(newsFactor.contribution) >= 0 ? '+' : ''}{Number(newsFactor.contribution).toFixed(2)}
            </span>
          )}
          {newsFactor.scored_items != null && newsFactor.considered_items != null && (
            <span className="cp-news-signal-meta">{newsFactor.scored_items}/{newsFactor.considered_items} items scored</span>
          )}
        </div>
      )}

      {loading && relatedNews.length === 0 && analystResearch.length === 0 ? (
        <div className="cp-skeleton-rows">
          <div className="cp-skeleton" style={{ height: 24, marginBottom: 8 }} />
          <div className="cp-skeleton" />
          <div className="cp-skeleton" />
          <div className="cp-skeleton" style={{ marginTop: 10 }} />
          <div className="cp-skeleton" />
        </div>
      ) : (
        <div className="cp-news-columns">
          <div className="cp-news-column">
            <div className="cp-news-group-title">Price Impact News</div>
            {relatedNews.length === 0 ? (
              <div className="cp-news-empty">No recent related news found.</div>
            ) : (
              visibleNews.map((n, idx) => (
                <div className="cp-news-row" key={`news-panel-${n._ts || 'na'}-${idx}`}>
                  <a className="cp-link" href={n.link} target="_blank" rel="noreferrer">{n.title}</a>
                  <div className="cp-news-meta">
                    {fmtPublisher(n.publisher)}
                    {n.published_at ? ` · ${String(n.published_at).slice(0, 10)}` : ''}
                    <span className="cp-news-age-pill">{fmtAge(n._ts)}</span>
                  </div>
                </div>
              ))
            )}
            {hasMoreNews && (
              <button
                type="button"
                className="btn btn-ghost btn-sm cp-news-toggle"
                onClick={() => setShowAllNews(prev => !prev)}
              >
                {showAllNews ? 'Show fewer' : `Show ${sortedNews.length - initialVisibleCount} more`}
              </button>
            )}
          </div>

          <div className="cp-news-column">
            <div className="cp-news-group-title">Analyst Research & Notes</div>
            {analystResearch.length === 0 ? (
              <div className="cp-news-empty">No recent analyst research links found.</div>
            ) : (
              visibleResearch.map((n, idx) => (
                <div className="cp-news-row" key={`research-panel-${n._ts || 'na'}-${idx}`}>
                  <a className="cp-link" href={n.link} target="_blank" rel="noreferrer">{n.title}</a>
                  <div className="cp-news-meta">
                    {fmtPublisher(n.publisher)}
                    {n.published_at ? ` · ${String(n.published_at).slice(0, 10)}` : ''}
                    <span className="cp-news-age-pill">{fmtAge(n._ts)}</span>
                  </div>
                </div>
              ))
            )}
            {hasMoreResearch && (
              <button
                type="button"
                className="btn btn-ghost btn-sm cp-news-toggle"
                onClick={() => setShowAllResearch(prev => !prev)}
              >
                {showAllResearch ? 'Show fewer' : `Show ${sortedResearch.length - initialVisibleCount} more`}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Supply-chain table ────────────────────────────────────────────────────────
function ChainTable({ title, rows = [], icon, onNavigate }) {
  const [sortKey, setSortKey]     = useState('market_cap')
  const [sortDir, setSortDir]     = useState('desc')
  const [filterText, setFilter]   = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [pageSize, setPageSize]   = useState(10)
  const [page, setPage]           = useState(1)

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

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const startIndex = (currentPage - 1) * pageSize
  const pagedRows = sorted.slice(startIndex, startIndex + pageSize)

  useEffect(() => {
    setPage(1)
  }, [filterText, roleFilter, sortKey, sortDir, rows, pageSize])

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
        <select
          className="cp-filter-select"
          value={String(pageSize)}
          onChange={e => setPageSize(Number(e.target.value))}
          title="Rows per page"
        >
          <option value="10">10 / page</option>
          <option value="25">25 / page</option>
          <option value="50">50 / page</option>
        </select>
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
            ) : pagedRows.map(r => (
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

      {sorted.length > 0 && (
        <div className="cp-table-pagination">
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            disabled={currentPage <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
          >
            Prev
          </button>
          <span className="cp-pagination-text">
            Page {currentPage} of {pageCount}
          </span>
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            disabled={currentPage >= pageCount}
            onClick={() => setPage(p => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

// ── Peer table ────────────────────────────────────────────────────────────────
function PeersTable({ peers = [], onNavigate }) {
  const [sortKey, setSortKey] = useState('market_cap')
  const [sortDir, setSortDir] = useState('desc')
  const [filterText, setFilter] = useState('')
  const [pageSize, setPageSize] = useState(10)
  const [page, setPage] = useState(1)

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

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const startIndex = (currentPage - 1) * pageSize
  const pagedRows = sorted.slice(startIndex, startIndex + pageSize)

  useEffect(() => {
    setPage(1)
  }, [filterText, sortKey, sortDir, peers, pageSize])

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
        <select
          className="cp-filter-select"
          value={String(pageSize)}
          onChange={e => setPageSize(Number(e.target.value))}
          title="Rows per page"
        >
          <option value="10">10 / page</option>
          <option value="25">25 / page</option>
          <option value="50">50 / page</option>
        </select>
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
            ) : pagedRows.map(r => (
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

      {sorted.length > 0 && (
        <div className="cp-table-pagination">
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            disabled={currentPage <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
          >
            Prev
          </button>
          <span className="cp-pagination-text">
            Page {currentPage} of {pageCount}
          </span>
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            disabled={currentPage >= pageCount}
            onClick={() => setPage(p => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

// ── Price Chart ───────────────────────────────────────────────────────────────
const RANGES = [
  { label: '1D', value: '1d' },
  { label: '1W', value: '1w' },
  { label: '1M', value: '1mo' },
  { label: '3M', value: '3mo' },
  { label: '6M', value: '6mo' },
  { label: '1Y', value: '1y' },
  { label: '3Y', value: '3y' },
  { label: '5Y', value: '5y' },
]

const LINE_COLORS = [
  { border: '#3b82f6', bg: 'rgba(59,130,246,0.08)' },
  { border: '#f97316', bg: 'rgba(249,115,22,0.06)' },
  { border: '#10b981', bg: 'rgba(16,185,129,0.06)' },
]

function PriceChart({ symbol }) {
  const getProjectionConfidence = (target) => {
    const avg = Number(target?.avg || 0)
    if (!avg) return { cls: 'low', label: 'Low' }
    const spreadPct = (Number(target.max || 0) - Number(target.min || 0)) / avg
    if (spreadPct <= 0.18) return { cls: 'high', label: 'High' }
    if (spreadPct <= 0.35) return { cls: 'medium', label: 'Medium' }
    return { cls: 'low', label: 'Low' }
  }

  const [range, setRange] = useState('1y')
  const [chartData, setChartData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [normalised, setNormalised] = useState(true)
  const [projectionData, setProjectionData] = useState(null)
  const [projectionLoading, setProjectionLoading] = useState(false)
  const [projectionError, setProjectionError] = useState(null)
  const [projectionInfoOpen, setProjectionInfoOpen] = useState(false)
  const abortRef = useRef(null)
  const projectionAbortRef = useRef(null)

  useEffect(() => {
    if (!symbol) return
    if (abortRef.current) abortRef.current.abort()
    abortRef.current = new AbortController()
    setLoading(true)
    setError(null)
    fetch(`${API}/price-history/${symbol}?range=${range}`, { signal: abortRef.current.signal })
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || `HTTP ${r.status}`)))
      .then(data => {
        setChartData(data)
        setLoading(false)
      })
      .catch(e => {
        if (e?.name === 'AbortError') return
        setError(String(e))
        setLoading(false)
      })
  }, [symbol, range])

  useEffect(() => {
    if (!symbol) return
    if (projectionAbortRef.current) projectionAbortRef.current.abort()
    projectionAbortRef.current = new AbortController()
    setProjectionLoading(true)
    setProjectionError(null)
    fetch(`${API}/future-projection/${symbol}`, { signal: projectionAbortRef.current.signal })
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || `HTTP ${r.status}`)))
      .then(data => {
        setProjectionData(data)
        setProjectionLoading(false)
      })
      .catch(e => {
        if (e?.name === 'AbortError') return
        setProjectionError(String(e))
        setProjectionLoading(false)
      })
  }, [symbol])

  const chartJs = useMemo(() => {
    if (!chartData) return null
    const key = normalised ? 'n' : 'v'
    const series = chartData.series || []
    const labels = series.map(p => p.t)

    const datasets = [
      {
        label: chartData.symbol,
        data: series.map(p => p[key]),
        borderColor: LINE_COLORS[0].border,
        backgroundColor: LINE_COLORS[0].bg,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
      },
    ]

    let colorIdx = 1
    for (const [label, pts] of Object.entries(chartData.comparisons || {})) {
      const col = LINE_COLORS[colorIdx % LINE_COLORS.length]
      colorIdx++
      datasets.push({
        label,
        data: pts.map(p => p[key]),
        borderColor: col.border,
        backgroundColor: col.bg,
        borderWidth: 1.5,
        borderDash: [4, 3],
        pointRadius: 0,
        tension: 0.3,
        fill: false,
      })
    }

    return { labels, datasets }
  }, [chartData, normalised])

  const projectionChartJs = useMemo(() => {
    if (!projectionData?.targets?.length) return null
    return {
      labels: projectionData.targets.map(t => t.label),
      datasets: [
        {
          label: 'Max',
          data: projectionData.targets.map(t => t.max),
          borderColor: '#22c55e',
          backgroundColor: 'rgba(34,197,94,0.08)',
          borderWidth: 2,
          pointRadius: 3,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'Average',
          data: projectionData.targets.map(t => t.avg),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.12)',
          borderWidth: 2,
          pointRadius: 3,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'Min',
          data: projectionData.targets.map(t => t.min),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239,68,68,0.08)',
          borderWidth: 2,
          pointRadius: 3,
          tension: 0.3,
          fill: false,
        },
      ],
    }
  }, [projectionData])

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        labels: { color: '#94a3b8', font: { size: 12 }, boxWidth: 18, padding: 16 },
      },
      tooltip: {
        backgroundColor: '#1e293b',
        titleColor: '#e2e8f0',
        bodyColor: '#94a3b8',
        callbacks: {
          label: ctx => normalised
            ? `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} (rebased)`
            : `${ctx.dataset.label}: $${ctx.parsed.y.toFixed(2)}`,
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: '#64748b',
          maxTicksLimit: 8,
          maxRotation: 0,
          font: { size: 11 },
        },
        grid: { color: 'rgba(255,255,255,0.04)' },
      },
      y: {
        ticks: {
          color: '#64748b',
          font: { size: 11 },
          callback: v => normalised ? `${v.toFixed(0)}` : `$${v.toFixed(0)}`,
        },
        grid: { color: 'rgba(255,255,255,0.06)' },
      },
    },
  }), [normalised])

  const projectionOptions = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        labels: { color: '#94a3b8', font: { size: 12 }, boxWidth: 18, padding: 16 },
      },
      tooltip: {
        backgroundColor: '#1e293b',
        titleColor: '#e2e8f0',
        bodyColor: '#94a3b8',
        callbacks: {
          label: ctx => `${ctx.dataset.label}: $${ctx.parsed.y.toFixed(2)}`,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: '#64748b', maxRotation: 0, font: { size: 11 } },
        grid: { color: 'rgba(255,255,255,0.04)' },
      },
      y: {
        ticks: {
          color: '#64748b',
          font: { size: 11 },
          callback: v => `$${v.toFixed(0)}`,
        },
        grid: { color: 'rgba(255,255,255,0.06)' },
      },
    },
  }), [])

  return (
    <div className="cp-price-chart-section">
      <div className="cp-chart-compare-grid">
        <div className="cp-chart-panel">
          <div className="cp-chart-title-row">
            <div className="cp-stats-card-title">Price vs Sector & S&P 500</div>
          </div>
          <div className="cp-chart-toolbar">
            <div className="cp-chart-ranges">
              {RANGES.map(r => (
                <button
                  key={r.value}
                  className={`cp-range-btn${range === r.value ? ' active' : ''}`}
                  onClick={() => setRange(r.value)}
                  type="button"
                >
                  {r.label}
                </button>
              ))}
            </div>
            <button
              className={`cp-range-btn${normalised ? ' active' : ''}`}
              onClick={() => setNormalised(v => !v)}
              type="button"
              title="Toggle between rebased (100=start) and raw price"
            >
              {normalised ? 'Rebased' : 'Price'}
            </button>
          </div>
          <div className="cp-chart-wrap">
            {loading && <div className="cp-chart-overlay">Loading…</div>}
            {error && <div className="cp-chart-overlay cp-chart-error">{error}</div>}
            {chartJs && <Line data={chartJs} options={options} />}
          </div>
        </div>

        <div className="cp-chart-panel">
          <div className="cp-chart-title-row">
            <div className="cp-projection-title-wrap">
              <div className="cp-stats-card-title">Future Projection (Min / Avg / Max)</div>
              <button
                type="button"
                className="cp-projection-info-btn"
                title="How future projection is calculated"
                aria-label="How future projection is calculated"
                onClick={() => setProjectionInfoOpen(true)}
              >
                i
              </button>
            </div>
            {projectionData?.current_price != null && (
              <span className="cp-chart-current-price">Now: ${projectionData.current_price.toFixed(2)}</span>
            )}
          </div>
          <div className="cp-chart-wrap">
            {projectionLoading && <div className="cp-chart-overlay">Loading…</div>}
            {projectionError && <div className="cp-chart-overlay cp-chart-error">{projectionError}</div>}
            {projectionChartJs && <Line data={projectionChartJs} options={projectionOptions} />}
          </div>
          {projectionData?.targets?.length > 0 && (
            <div className="cp-projection-grid">
              {projectionData.targets.map(t => {
                const confidence = getProjectionConfidence(t)
                return (
                <div key={t.key} className={`cp-projection-chip cp-projection-chip-${confidence.cls}`}>
                  <div className="cp-projection-horizon">{t.label}</div>
                  <div className="cp-projection-values-table" title={`Confidence: ${confidence.label}`}>
                    <span className="cp-projection-col-head">Min</span>
                    <span className="cp-projection-col-head">Avg</span>
                    <span className="cp-projection-col-head">Max</span>
                    <span className="cp-projection-col-val neg">${t.min.toFixed(2)}</span>
                    <span className="cp-projection-col-val">${t.avg.toFixed(2)}</span>
                    <span className="cp-projection-col-val pos">${t.max.toFixed(2)}</span>
                  </div>
                </div>
              )})}
            </div>
          )}
        </div>
      </div>

      {projectionInfoOpen && (
        <div
          className="cp-modal-backdrop"
          role="dialog"
          aria-modal="true"
          onClick={(e) => { if (e.target === e.currentTarget) setProjectionInfoOpen(false) }}
        >
          <div className="cp-modal-card cp-projection-info-dialog">
            <div className="cp-modal-title">Future Projection Method</div>
            <div className="cp-modal-body">
              <div>
                Min / Avg / Max values are produced by the backend projection model for each horizon (1M, 3M, 6M, 1Y).
              </div>
              <div>
                The model uses recent price action, trend behavior, and volatility to estimate a future range, not a single exact price.
              </div>
              <div>
                Min = conservative downside scenario, Avg = base-case estimate, Max = optimistic upside scenario.
              </div>
              <div>
                Confidence is derived from range width: narrower (max - min) relative to avg means higher confidence; wider means lower confidence.
              </div>
              <div>
                These outputs are probabilistic estimates and should be combined with other analysis and risk management.
              </div>
            </div>
            <div className="cp-modal-actions">
              <button className="btn btn-sm" type="button" onClick={() => setProjectionInfoOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function CompanyProfile({ symbol: initialSymbol, onNavigate, riskTolerance = 5, brokerConfigured = false }) {
  const [symbol, setSymbol]   = useState((initialSymbol || '').toUpperCase())
  const [inputSym, setInput]  = useState(initialSymbol || '')
  const [searchSuggestions, setSearchSuggestions] = useState([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchActiveIdx, setSearchActiveIdx] = useState(-1)
  const [searchBusy, setSearchBusy] = useState(false)
  const [data, setData]             = useState(null)
  const [sections, setSections]     = useState(null)   // slow sections loaded in parallel
  const [sectionsLoading, setSectionsLoading] = useState(false)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [history, setHistory] = useState([])
  const [expandedBuckets, setExpandedBuckets] = useState({})
  const [expandedAltSources, setExpandedAltSources] = useState({})
  const [expandedStatCards, setExpandedStatCards] = useState({})
  const [signalDialog, setSignalDialog] = useState(null) // { signal, score, factors, title }
  const [tradeSummary, setTradeSummary] = useState(null)
  const [tradeLoading, setTradeLoading] = useState(false)
  const [tradeError, setTradeError] = useState(null)
  const [selectedAccount, setSelectedAccount] = useState('')
  const [stockQty, setStockQty] = useState('1')
  const [optionSymbol, setOptionSymbol] = useState('')
  const [optionQty, setOptionQty] = useState('1')
  const [orderType, setOrderType] = useState('market')
  const [timeInForce, setTimeInForce] = useState('day')
  const [limitPrice, setLimitPrice] = useState('')
  const [tradeBusy, setTradeBusy] = useState(false)
  const [tradeMsg, setTradeMsg] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingOrder, setPendingOrder] = useState(null)
  const [tradeDialogOpen, setTradeDialogOpen] = useState(false)
  const [tradeDialogSide, setTradeDialogSide] = useState('buy')
  const [tradeDialogInstrument, setTradeDialogInstrument] = useState('stock')
  const [aboutExpanded, setAboutExpanded] = useState(false)
  const searchCloseTimerRef = useRef(null)
  const searchAbortRef = useRef(null)

  async function readErrorDetail(response, fallback) {
    const raw = await response.text()
    if (!raw) return fallback
    try {
      const parsed = JSON.parse(raw)
      return parsed?.detail || parsed?.message || fallback
    } catch {
      return raw
    }
  }

  async function load(sym) {
    if (!sym) return
    if (searchAbortRef.current) {
      searchAbortRef.current.abort()
      searchAbortRef.current = null
    }
    setInput(sym)
    setSymbol(sym)
    setSearchOpen(false)
    setSearchSuggestions([])
    setSearchActiveIdx(-1)
    setSearchBusy(false)
    setLoading(true)
    setSectionsLoading(true)
    setError(null)
    setData(null)
    setSections(null)

    // ── Fire core + sections requests simultaneously ───────────────────────
    const corePromise = fetch(`${API}/company/${sym}`)
    // sections call starts right away; peer_syms added once core returns
    let sectionsStarted = false

    try {
      const coreRes = await corePromise
      if (!coreRes.ok) {
        const detail = await readErrorDetail(coreRes, `HTTP ${coreRes.status}`)
        throw new Error(detail)
      }
      const coreData = await coreRes.json()
      // Merge placeholder fields so existing JSX references don't break
      setData({
        ...coreData,
        suppliers: [],
        customers: [],
        peers: [],
        has_supply_chain_data: false,
        alternative_data: null,
        options_chain: null,
        congress_activity: null,
        buy_sell_signal: null,
      })
      setHistory(prev => [sym, ...prev.filter(s => s !== sym)].slice(0, 8))
      setLoading(false)

      // ── Now fetch slow sections using peer_syms from core ─────────────────
      sectionsStarted = true
      const peerParam = (coreData._peer_syms || []).join(',')
      const secRes = await fetch(`${API}/company/${sym}/sections?peer_syms=${encodeURIComponent(peerParam)}&risk_tolerance=${riskTolerance}`)
      if (secRes.ok) {
        const secData = await secRes.json()
        setSections(secData)
        // Merge sections into data so all downstream code still works
        setData(prev => prev ? { ...prev, ...secData } : prev)
      }
    } catch (e) {
      setError(e.message)
      setLoading(false)
    } finally {
      setSectionsLoading(false)
    }
  }

  useEffect(() => {
    if (initialSymbol) load(initialSymbol.toUpperCase())
  }, [initialSymbol])

  useEffect(() => {
    setExpandedBuckets({})
    setExpandedAltSources({})
    setAboutExpanded(false)
    setExpandedStatCards({})
  }, [symbol])

  async function refreshTradeSummary(sym) {
    setTradeLoading(true)
    setTradeError(null)
    try {
      const r = await fetch(`${API}/trade/summary/${sym}`)
      const body = await r.json()
      if (!r.ok) {
        const detail = body?.detail || body?.message || `HTTP ${r.status}`
        throw new Error(detail)
      }
      setTradeSummary(body)
      setSelectedAccount(body?.selected_account || body?.accounts?.[0]?.account_id || '')
    } catch (e) {
      setTradeError(String(e.message || e))
    } finally {
      setTradeLoading(false)
    }
  }

  useEffect(() => {
    if (!symbol) return
    if (!brokerConfigured) {
      setTradeSummary(null)
      setTradeError(null)
      return
    }
    refreshTradeSummary(symbol)
  }, [symbol, brokerConfigured])

  function requestOrder(instrumentType, side) {
    const qtyRaw = instrumentType === 'stock' ? stockQty : optionQty
    const quantity = Number(qtyRaw)
    const selectedSymbol = instrumentType === 'stock' ? symbol : optionSymbol.trim().toUpperCase()
    if (!selectedSymbol) {
      setTradeMsg('Option symbol is required')
      return
    }
    if (!quantity || quantity <= 0) {
      setTradeMsg('Quantity must be greater than 0')
      return
    }
    if (orderType === 'limit') {
      const lp = Number(limitPrice)
      if (!lp || lp <= 0) {
        setTradeMsg('Limit price must be greater than 0')
        return
      }
    }

    setPendingOrder({
      instrumentType,
      side,
      symbol: selectedSymbol,
      quantity,
      orderType,
      timeInForce,
      limitPrice: orderType === 'limit' ? Number(limitPrice) : null,
    })
    setConfirmOpen(true)
  }

  async function executePendingOrder() {
    if (!pendingOrder) return
    setTradeBusy(true)
    setTradeMsg('')
    setTradeError(null)
    try {
      const res = await fetch(`${API}/trade/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: selectedAccount || undefined,
          symbol: pendingOrder.symbol,
          side: pendingOrder.side,
          quantity: pendingOrder.quantity,
          instrument_type: pendingOrder.instrumentType,
          order_type: pendingOrder.orderType,
          time_in_force: pendingOrder.timeInForce,
          limit_price: pendingOrder.limitPrice,
        }),
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      setTradeMsg(body.message || 'Order submitted')
      setConfirmOpen(false)
      setPendingOrder(null)
      setTradeDialogOpen(false)
      await refreshTradeSummary(symbol)
    } catch (e) {
      setTradeError(String(e.message || e))
    } finally {
      setTradeBusy(false)
    }
  }

  function navigate(sym) {
    if (sym === symbol) return
    if (onNavigate) onNavigate(sym)
    else load(sym.toUpperCase())
  }

  function handleSearch(e) {
    e.preventDefault()
    const active = searchActiveIdx >= 0 ? searchSuggestions[searchActiveIdx] : null
    const s = (active?.symbol || inputSym).trim().toUpperCase()
    if (s) load(s)
    setSearchOpen(false)
    setSearchActiveIdx(-1)
  }

  function chooseSuggestion(item) {
    if (!item?.symbol) return
    setInput(item.symbol)
    setSearchOpen(false)
    setSearchActiveIdx(-1)
    load(item.symbol)
  }

  useEffect(() => {
    const q = inputSym.trim()
    if (!q) {
      setSearchSuggestions([])
      setSearchOpen(false)
      setSearchBusy(false)
      setSearchActiveIdx(-1)
      return
    }

    // When query already matches the loaded symbol, keep typeahead hidden.
    if (q.toUpperCase() === (symbol || '').toUpperCase()) {
      setSearchSuggestions([])
      setSearchOpen(false)
      setSearchBusy(false)
      setSearchActiveIdx(-1)
      return
    }

    const ctl = new AbortController()
    searchAbortRef.current = ctl
    const timer = setTimeout(async () => {
      setSearchBusy(true)
      try {
        const r = await fetch(`${API}/company-search?q=${encodeURIComponent(q)}&limit=8`, { signal: ctl.signal })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const body = await r.json()
        const list = Array.isArray(body?.results) ? body.results : []
        setSearchSuggestions(list)
        setSearchOpen(list.length > 0)
        setSearchActiveIdx(-1)
      } catch {
        if (!ctl.signal.aborted) {
          setSearchSuggestions([])
          setSearchOpen(false)
        }
      } finally {
        if (!ctl.signal.aborted) setSearchBusy(false)
      }
    }, 180)

    return () => {
      clearTimeout(timer)
      ctl.abort()
      if (searchAbortRef.current === ctl) {
        searchAbortRef.current = null
      }
    }
  }, [inputSym, symbol])

  function toggleStatCard(cardId) {
    setExpandedStatCards(prev => ({ ...prev, [cardId]: !prev[cardId] }))
  }

  const d = data
  const expiryBuckets = useMemo(
    () => d?.options_chain?.expiry_groups || [],
    [d?.options_chain?.expiry_groups],
  )
  const competitorRows = useMemo(() => {
    const peers = d?.peers || []
    const companyIndustry = String(d?.industry || '').toLowerCase().trim()
    if (!companyIndustry) return peers
    return peers.filter(p => String(p?.industry || '').toLowerCase().trim() === companyIndustry)
  }, [d?.peers, d?.industry])
  const sameSectorRows = useMemo(() => {
    const peers = d?.peers || []
    const companySector = String(d?.sector || '').toLowerCase().trim()
    const companyIndustry = String(d?.industry || '').toLowerCase().trim()
    if (!companySector) return []
    return peers.filter((p) => {
      const peerSector = String(p?.sector || '').toLowerCase().trim()
      const peerIndustry = String(p?.industry || '').toLowerCase().trim()
      return peerSector === companySector && peerIndustry !== companyIndustry
    })
  }, [d?.peers, d?.sector, d?.industry])
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
        <div className="cp-search-typeahead">
          <input
            className="cp-search-input"
            value={inputSym}
            onChange={e => setInput(e.target.value)}
            onFocus={() => {
              if (searchCloseTimerRef.current) clearTimeout(searchCloseTimerRef.current)
              if (searchSuggestions.length > 0) setSearchOpen(true)
            }}
            onBlur={() => {
              searchCloseTimerRef.current = setTimeout(() => setSearchOpen(false), 120)
            }}
            onKeyDown={e => {
              if (!searchOpen || searchSuggestions.length === 0) return
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setSearchActiveIdx(prev => Math.min(prev + 1, searchSuggestions.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setSearchActiveIdx(prev => Math.max(prev - 1, 0))
              } else if (e.key === 'Enter') {
                if (searchActiveIdx >= 0) {
                  e.preventDefault()
                  chooseSuggestion(searchSuggestions[searchActiveIdx])
                }
              } else if (e.key === 'Escape') {
                setSearchOpen(false)
                setSearchActiveIdx(-1)
              }
            }}
            placeholder="Search company name or ticker (e.g. Apple or AAPL)"
            spellCheck={false}
            autoComplete="off"
          />
          {searchOpen && (
            <div className="cp-search-suggest-box">
              {searchBusy && (
                <div className="cp-search-suggest-item cp-search-suggest-loading">
                  <span className="spinner" /> Searching…
                </div>
              )}
              {!searchBusy && searchSuggestions.length === 0 && (
                <div className="cp-search-suggest-item cp-search-suggest-empty">No matches found</div>
              )}
              {!searchBusy && searchSuggestions.map((item, idx) => (
                <button
                  key={`${item.symbol}-${idx}`}
                  type="button"
                  className={`cp-search-suggest-item ${idx === searchActiveIdx ? 'active' : ''}`}
                  onMouseDown={e => e.preventDefault()}
                  onClick={() => chooseSuggestion(item)}
                >
                  <span className="cp-search-suggest-symbol">{item.symbol}</span>
                  <span className="cp-search-suggest-name">{item.name || item.symbol}</span>
                  {item.exchange ? <span className="cp-search-suggest-exch">{item.exchange}</span> : null}
                </button>
              ))}
            </div>
          )}
        </div>
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
                {d.recommendation_key && <RecBadge rec={d.recommendation_key} />}
                              {d.buy_sell_signal && (
                                <RecBadge
                                  rec={d.buy_sell_signal.signal}
                                  onClick={() => setSignalDialog({
                                    signal: d.buy_sell_signal.signal,
                                    score: d.buy_sell_signal.score,
                                    factors: d.buy_sell_signal.factors,
                                    title: d.symbol,
                                    riskTolerance: d.buy_sell_signal.risk_tolerance_used ?? riskTolerance,
                                  })}
                                />
                              )}
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
              <div className="cp-header-trade-btns">
                <button
                  className="btn btn-sm cp-header-buy-btn"
                  type="button"
                  disabled={!brokerConfigured}
                  title={!brokerConfigured ? 'Configure and connect a broker to place trades' : undefined}
                  onClick={() => { setTradeDialogSide('buy'); setTradeDialogInstrument('stock'); setTradeDialogOpen(true) }}
                >
                  Buy
                </button>
                <button
                  className="btn btn-sm cp-header-sell-btn"
                  type="button"
                  disabled={!brokerConfigured}
                  title={!brokerConfigured ? 'Configure and connect a broker to place trades' : undefined}
                  onClick={() => { setTradeDialogSide('sell'); setTradeDialogInstrument('stock'); setTradeDialogOpen(true) }}
                >
                  Sell
                </button>
              </div>
            </div>
            {d.description && (
              <div className="cp-about-inline">
                <p className={`cp-about-inline-text ${aboutExpanded ? 'expanded' : ''}`}>
                  {d.description}
                </p>
                <button
                  type="button"
                  className="cp-about-inline-more"
                  onClick={() => setAboutExpanded(v => !v)}
                >
                  {aboutExpanded ? 'Less' : 'More'}
                </button>
              </div>
            )}
          </div>

          {/* ── Price Chart ──────────────────────────────────────── */}
          <PriceChart symbol={d.symbol} />

          <div className="cp-desc-section">
            <SectionTitle>Back-Test Simulation</SectionTitle>
            <Backtest initialSymbol={d.symbol} />
          </div>

          {/* ── Key Stats Grid ───────────────────────────────────── */}
          <div className="cp-stats-grid">
            <StatsCard
              cardId="support-resistance"
              title="Support / Resistance"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
              collapsible
            >
              {sectionsLoading && !d.technical_signal && (
                <div className="cp-skeleton-rows">
                  <div className="cp-skeleton" style={{height:32,marginBottom:8}} />
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                </div>
              )}

              {!sectionsLoading && !d.technical_signal && (
                <Stat label="Status" value="Technical signal unavailable" />
              )}

              {d.technical_signal && (
                (() => {
                  const ind = d.technical_signal.indicators || {}
                  const srSignal = ind.sr_signal || 'N/A'
                  const srClass = /bullish/i.test(srSignal) ? 'pos' : /bearish/i.test(srSignal) ? 'neg' : 'neu'
                  const currentPx = Number(d.technical_signal.current_price ?? d.price ?? 0)
                  const supportNear = ind.support_near != null ? Number(ind.support_near) : null
                  const resistanceNear = ind.resistance_near != null ? Number(ind.resistance_near) : null
                  const distSupport = currentPx > 0 && supportNear != null
                    ? ((currentPx - supportNear) / currentPx) * 100
                    : null
                  const distRes = currentPx > 0 && resistanceNear != null
                    ? ((resistanceNear - currentPx) / currentPx) * 100
                    : null

                  return (
                    <>
                      <Stat label="S/R Signal" value={srSignal} valueClass={srClass} />
                      <Stat label="Current Price" value={currentPx ? `$${currentPx.toFixed(2)}` : '—'} />
                      <Stat label="Support (Near)" value={supportNear != null ? `$${supportNear.toFixed(2)}` : '—'} />
                      <Stat label="Support (Major)" value={ind.support_major != null ? `$${Number(ind.support_major).toFixed(2)}` : '—'} />
                      <Stat label="Resistance (Near)" value={resistanceNear != null ? `$${resistanceNear.toFixed(2)}` : '—'} />
                      <Stat label="Resistance (Major)" value={ind.resistance_major != null ? `$${Number(ind.resistance_major).toFixed(2)}` : '—'} />
                      <Stat
                        label="Distance To Support"
                        value={distSupport != null ? `${distSupport >= 0 ? '+' : ''}${distSupport.toFixed(2)}%` : '—'}
                        valueClass={distSupport != null && distSupport <= 2 ? 'pos' : ''}
                      />
                      <Stat
                        label="Distance To Resistance"
                        value={distRes != null ? `${distRes >= 0 ? '+' : ''}${distRes.toFixed(2)}%` : '—'}
                        valueClass={distRes != null && distRes <= 2 ? 'neg' : ''}
                      />
                      <Stat label="Suggested Stop Loss" value={ind.stop_loss_suggestion != null ? `$${Number(ind.stop_loss_suggestion).toFixed(2)}` : '—'} />
                      <Stat label="Suggested Exit (TP1)" value={ind.take_profit_1 != null ? `$${Number(ind.take_profit_1).toFixed(2)}` : '—'} />
                      <Stat label="Suggested Exit (TP2)" value={ind.take_profit_2 != null ? `$${Number(ind.take_profit_2).toFixed(2)}` : '—'} />
                      <Stat
                        label="Risk/Reward (TP1)"
                        value={ind.risk_reward_tp1 != null ? Number(ind.risk_reward_tp1).toFixed(2) : '—'}
                        valueClass={ind.risk_reward_tp1 != null && Number(ind.risk_reward_tp1) >= 1.5 ? 'pos' : ''}
                      />
                    </>
                  )
                })()
              )}
            </StatsCard>

            <StatsCard
              cardId="options-expiry-buckets"
              title="Options Expiry Buckets"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
              collapsible
            >
              {sectionsLoading && !d.options_chain && (
                <div className="cp-skeleton-rows">
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                </div>
              )}
              {!sectionsLoading && !d.options_chain?.available && (
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
            </StatsCard>

            <StatsCard
              cardId="congressional-stock-trades"
              title="Congressional Trades"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
              collapsible
            >
              {sectionsLoading && !d.congress_activity && (
                <div className="cp-skeleton-rows">
                  <div className="cp-skeleton" style={{height:32,marginBottom:8}} />
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                </div>
              )}
              {d.congress_activity && (
                <>
                  <div className={`cp-buysell-signal-card ${d.congress_activity.signal.includes('BUY') ? 'pos' : d.congress_activity.signal.includes('SELL') ? 'neg' : 'neu'}`}>
                    {d.congress_activity.signal}
                  </div>
                  <Stat
                    label="30-Day Signal Score"
                    value={`${d.congress_activity.signal_score >= 0 ? '+' : ''}${d.congress_activity.signal_score}`}
                    valueClass={d.congress_activity.signal_score > 0 ? 'pos' : d.congress_activity.signal_score < 0 ? 'neg' : 'neu'}
                  />
                  <Stat label="30-Day Signal" value={d.congress_activity.signal_label} />
                  <Stat label="Trades In 90 Days" value={d.congress_activity.trades_90d_count} />
                  <Stat label="90-Day Purchases" value={d.congress_activity.purchases_90d} valueClass={d.congress_activity.purchases_90d > 0 ? 'pos' : ''} />
                  <Stat label="90-Day Sales" value={d.congress_activity.sales_90d} valueClass={d.congress_activity.sales_90d > 0 ? 'neg' : ''} />
                  <Stat
                    label="90-Day Net"
                    value={`${d.congress_activity.net_90d >= 0 ? '+' : ''}${d.congress_activity.net_90d}`}
                    valueClass={d.congress_activity.net_90d > 0 ? 'pos' : d.congress_activity.net_90d < 0 ? 'neg' : 'neu'}
                  />
                  <Stat label="Last Disclosure" value={d.congress_activity.latest_disclosure_date || '—'} />
                  {d.congress_activity.unavailable_reason && (
                    <Stat label="Status" value={d.congress_activity.unavailable_reason} valueClass="neg" />
                  )}
                  {!d.congress_activity.unavailable_reason && d.congress_activity.recent_trades?.length === 0 && (
                    <Stat label="Recent Activity" value="No congressional trades in the last 90 days" />
                  )}

                  {d.congress_activity.recent_trades?.map((trade, index) => (
                    <div key={`${trade.politician}-${trade.trade_date}-${index}`} className="cp-expiry-bucket-row">
                      <div className="cp-expiry-bucket-btn" style={{ cursor: 'default' }}>
                        <span className="cp-expiry-bucket-btn-left">
                          <span className="cp-expiry-bucket-label">{trade.politician || 'Unknown filer'}</span>
                          <span className="cp-expiry-bucket-count">
                            {trade.transaction || 'Unknown transaction'}
                            {trade.amount_range ? ` | ${trade.amount_range}` : ''}
                          </span>
                        </span>
                        <span className={`cp-expiry-bucket-signal ${(trade.transaction || '').toLowerCase().includes('purchase') || (trade.transaction || '').toLowerCase().includes('buy') ? 'pos' : (trade.transaction || '').toLowerCase().includes('sale') || (trade.transaction || '').toLowerCase().includes('sell') ? 'neg' : 'neu'}`}>
                          {trade.transaction || 'TRADE'}
                        </span>
                      </div>
                      <div className="cp-expiry-bucket-meta">
                        <span>Trade Date: {trade.trade_date || '—'}</span>
                        <span>Disclosure Date: {trade.disclosure_date || '—'}</span>
                        <span>Party: {trade.party || '—'}</span>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </StatsCard>

            <StatsCard
              cardId="alternative-live-sources"
              title="Alternative Live Sources"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
              collapsible
            >
              {sectionsLoading && !d.alternative_data && (
                <div className="cp-skeleton-rows">
                  <div className="cp-skeleton" style={{height:32,marginBottom:8}} />
                  <div className="cp-skeleton" />
                  <div className="cp-skeleton" />
                </div>
              )}
              {d.alternative_data && (<>
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
              </>)}
            </StatsCard>

            <StatsCard
              cardId="valuation"
              title="Valuation"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
            >
              <Stat label="Market Cap"         value={fmtMoney(d.market_cap, 0)} />
              <Stat label="Enterprise Value"   value={fmtMoney(d.enterprise_value, 0)} />
              <Stat label="P/E (TTM)"          value={d.pe_ratio != null ? fmtNum(d.pe_ratio) : '—'} />
              <Stat label="Forward P/E"        value={d.forward_pe != null ? fmtNum(d.forward_pe) : '—'} />
              <Stat label="PEG Ratio"          value={d.peg_ratio != null ? fmtNum(d.peg_ratio) : '—'} />
              <Stat label="Price / Book"       value={d.price_to_book != null ? fmtNum(d.price_to_book) : '—'} />
              <Stat label="Price / Sales"      value={d.price_to_sales != null ? fmtNum(d.price_to_sales) : '—'} />
              <Stat label="EV / Revenue"       value={d.enterprise_to_revenue != null ? fmtNum(d.enterprise_to_revenue) : '—'} />
              <Stat label="EV / EBITDA"        value={d.enterprise_to_ebitda != null ? fmtNum(d.enterprise_to_ebitda) : '—'} />
            </StatsCard>

            <StatsCard
              cardId="per-share"
              title="Per Share"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
            >
              <Stat label="Price"              value={d.price != null ? `$${Number(d.price).toFixed(2)}` : '—'} />
              <Stat label="EPS (TTM)"          value={d.eps != null ? `$${Number(d.eps).toFixed(2)}` : '—'} />
              <Stat label="Forward EPS"        value={d.eps_forward != null ? `$${Number(d.eps_forward).toFixed(2)}` : '—'} />
              <Stat label="Book Value / Share" value={d.book_value != null ? `$${Number(d.book_value).toFixed(2)}` : '—'} />
              <Stat label="Dividend Rate"      value={d.dividend_rate != null ? `$${Number(d.dividend_rate).toFixed(2)}` : '—'} />
              <Stat label="Dividend Yield"     value={d.dividend_yield != null ? fmtPctRaw(d.dividend_yield) : '—'} />
              <Stat label="Payout Ratio"       value={d.payout_ratio != null ? fmtPctRaw(d.payout_ratio) : '—'} />
              <Stat label="Shares Outstanding" value={fmtShares(d.shares_outstanding)} />
              <Stat label="Float"              value={fmtShares(d.float_shares)} />
            </StatsCard>

            <StatsCard
              cardId="price-history"
              title="Price History"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
            >
              <Stat label="52-Wk High"   value={d.fifty_two_week_high != null ? `$${Number(d.fifty_two_week_high).toFixed(2)}` : '—'} />
              <Stat label="52-Wk Low"    value={d.fifty_two_week_low  != null ? `$${Number(d.fifty_two_week_low).toFixed(2)}` : '—'} />
              <Stat label="50-Day Avg"   value={d.fifty_day_avg        != null ? `$${Number(d.fifty_day_avg).toFixed(2)}` : '—'} />
              <Stat label="200-Day Avg"  value={d.two_hundred_day_avg  != null ? `$${Number(d.two_hundred_day_avg).toFixed(2)}` : '—'} />
              <Stat label="Beta"         value={d.beta != null ? fmtNum(d.beta) : '—'} />
              <Stat label="Volume"       value={fmtVol(d.volume)} />
              <Stat label="Avg Volume"   value={fmtVol(d.avg_volume)} />
              <Stat label="Short Ratio"  value={d.short_ratio != null ? fmtNum(d.short_ratio) : '—'} />
              <Stat label="Short % Float" value={d.short_percent_float != null ? fmtPctRaw(d.short_percent_float) : '—'} />
            </StatsCard>

            <StatsCard
              cardId="financials-ttm"
              title="Financials (TTM)"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
            >
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
            </StatsCard>

            <StatsCard
              cardId="balance-sheet"
              title="Balance Sheet"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
            >
              <Stat label="Total Cash"    value={fmtMoney(d.total_cash, 0)} />
              <Stat label="Total Debt"    value={fmtMoney(d.total_debt, 0)} />
              <Stat label="Debt / Equity" value={d.debt_to_equity != null ? fmtNum(d.debt_to_equity) : '—'} />
              <Stat label="Current Ratio" value={d.current_ratio  != null ? fmtNum(d.current_ratio) : '—'} />
              <Stat label="Quick Ratio"   value={d.quick_ratio    != null ? fmtNum(d.quick_ratio) : '—'} />
              <Stat label="Free Cash Flow"      value={fmtMoney(d.free_cashflow, 0)} />
              <Stat label="Operating Cash Flow" value={fmtMoney(d.operating_cashflow, 0)} />
            </StatsCard>

            <StatsCard
              cardId="analyst-consensus"
              title="Analyst Consensus"
              expandedMap={expandedStatCards}
              onToggle={toggleStatCard}
            >
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
              </StatsCard>

          </div>

          <NewsResearchPanel
            relatedNews={d.related_news || []}
            analystResearch={d.analyst_research || []}
            newsUpdatedAt={d.news_updated_at}
            newsFactor={d.buy_sell_signal?.factors?.news_research}
            loading={sectionsLoading}
          />

          <FmpDataPanel fmp={d.fmp_data} loading={sectionsLoading} />

          <AltDataPanel alt={d.alternative_data} />

          {/* ── Supply Chain ─────────────────────────────────────── */}
          {sectionsLoading && !d.suppliers && (
            <div className="cp-skeleton-rows" style={{padding:'12px 0'}}>
              <div className="cp-skeleton" style={{height:20,width:'40%',marginBottom:12}} />
              <div className="cp-skeleton" style={{height:60}} />
              <div className="cp-skeleton" style={{height:60,marginTop:8}} />
            </div>
          )}
          {!sectionsLoading && !d.has_supply_chain_data && (
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

          <ChainTable
            title="Competitors — Similar Industry"
            icon="⚔️"
            rows={competitorRows}
            onNavigate={navigate}
          />

          <ChainTable
            title="Companies in Same Sector"
            icon="🏢"
            rows={sameSectorRows}
            onNavigate={navigate}
          />

          <PeersTable peers={d.peers} onNavigate={navigate} />
        </>
      )}

      {/* ── Trade Dialog ─────────────────────────────────────── */}
      {tradeDialogOpen && (
        <div className="cp-modal-backdrop" role="dialog" aria-modal="true">
          <div className="cp-modal-card cp-trade-dialog">
            <div className="cp-modal-title">
              Trade {d?.symbol}
              {tradeSummary && (
                <span className="cp-trade-dialog-holdings">
                  {tradeSummary.stock_shares ?? 0} shares · {tradeSummary.option_contracts ?? 0} options owned
                  {tradeSummary.broker ? ` · ${tradeSummary.broker.toUpperCase()}` : ''}
                </span>
              )}
            </div>
            <div className="cp-modal-body">

              {/* Side toggle */}
              <div className="cp-trade-dialog-row">
                <label className="cp-trade-label">Action</label>
                <div className="cp-trade-dialog-toggle">
                  <button
                    type="button"
                    className={`btn btn-sm ${tradeDialogSide === 'buy' ? '' : 'btn-ghost'}`}
                    onClick={() => setTradeDialogSide('buy')}
                  >Buy</button>
                  <button
                    type="button"
                    className={`btn btn-sm ${tradeDialogSide === 'sell' ? '' : 'btn-ghost'}`}
                    onClick={() => setTradeDialogSide('sell')}
                  >Sell</button>
                </div>
              </div>

              {/* Instrument toggle */}
              <div className="cp-trade-dialog-row">
                <label className="cp-trade-label">Instrument</label>
                <div className="cp-trade-dialog-toggle">
                  <button
                    type="button"
                    className={`btn btn-sm ${tradeDialogInstrument === 'stock' ? '' : 'btn-ghost'}`}
                    onClick={() => setTradeDialogInstrument('stock')}
                  >Stock</button>
                  <button
                    type="button"
                    className={`btn btn-sm ${tradeDialogInstrument === 'option' ? '' : 'btn-ghost'}`}
                    onClick={() => setTradeDialogInstrument('option')}
                  >Option</button>
                </div>
              </div>

              {/* Account */}
              <div className="cp-trade-dialog-row">
                <label className="cp-trade-label">Account</label>
                <select
                  className="cp-trade-input"
                  value={selectedAccount}
                  onChange={e => setSelectedAccount(e.target.value)}
                >
                  {(tradeSummary?.accounts || []).map(a => (
                    <option key={a.account_id} value={a.account_id}>{a.label}</option>
                  ))}
                  {(!tradeSummary?.accounts || tradeSummary.accounts.length === 0) && (
                    <option value="">No accounts loaded</option>
                  )}
                </select>
              </div>

              {/* Quantity */}
              <div className="cp-trade-dialog-row">
                <label className="cp-trade-label">{tradeDialogInstrument === 'stock' ? 'Shares' : 'Contracts'}</label>
                <input
                  className="cp-trade-input"
                  type="number"
                  min="1"
                  step="1"
                  value={tradeDialogInstrument === 'stock' ? stockQty : optionQty}
                  onChange={e => tradeDialogInstrument === 'stock' ? setStockQty(e.target.value) : setOptionQty(e.target.value)}
                  placeholder="Quantity"
                />
              </div>

              {/* Option symbol (options only) */}
              {tradeDialogInstrument === 'option' && (
                <div className="cp-trade-dialog-row">
                  <label className="cp-trade-label">Option Symbol</label>
                  <input
                    className="cp-trade-input cp-trade-symbol"
                    value={optionSymbol}
                    onChange={e => setOptionSymbol(e.target.value.toUpperCase())}
                    placeholder="e.g. AAPL250620C00220000"
                  />
                </div>
              )}

              {/* Order Type */}
              <div className="cp-trade-dialog-row">
                <label className="cp-trade-label">Order Type</label>
                <select className="cp-trade-input" value={orderType} onChange={e => setOrderType(e.target.value)}>
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                </select>
              </div>

              {/* Limit Price */}
              {orderType === 'limit' && (
                <div className="cp-trade-dialog-row">
                  <label className="cp-trade-label">Limit Price</label>
                  <input
                    className="cp-trade-input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={limitPrice}
                    onChange={e => setLimitPrice(e.target.value)}
                    placeholder="0.00"
                  />
                </div>
              )}

              {/* Time in Force */}
              <div className="cp-trade-dialog-row">
                <label className="cp-trade-label">Time in Force</label>
                <select className="cp-trade-input" value={timeInForce} onChange={e => setTimeInForce(e.target.value)}>
                  <option value="day">DAY</option>
                  <option value="gtc">GTC</option>
                  <option value="ioc">IOC</option>
                  <option value="fok">FOK</option>
                </select>
              </div>

              {/* Open option positions */}
              {(tradeSummary?.option_positions || []).length > 0 && (
                <div className="cp-open-options" style={{marginTop: 8}}>
                  <div className="cp-trade-label">Open Option Positions</div>
                  {tradeSummary.option_positions.map(op => (
                    <div className="cp-open-option-row" key={op.symbol}
                      style={{cursor:'pointer'}}
                      onClick={() => { setOptionSymbol(op.symbol); setTradeDialogInstrument('option') }}
                    >
                      <span>{op.symbol}</span>
                      <span>{op.quantity} contracts</span>
                      <span>{op.option_type || '—'} {op.strike != null ? `$${Number(op.strike).toFixed(2)}` : ''}</span>
                      <span>{op.expiration || '—'}</span>
                    </div>
                  ))}
                </div>
              )}

              {tradeMsg && <div className="cp-trade-msg pos" style={{marginTop:8}}>{tradeMsg}</div>}
              {tradeError && <div className="cp-trade-msg neg" style={{marginTop:8}}>{tradeError}</div>}
              {!brokerConfigured && (
                <div className="cp-trade-msg neg" style={{marginTop:8}}>
                  Broker is not configured. Configure and connect a broker from Profile to place orders.
                </div>
              )}
            </div>

            <div className="cp-modal-actions">
              <button
                className="btn btn-ghost"
                type="button"
                disabled={tradeBusy}
                onClick={() => { setTradeDialogOpen(false); setTradeMsg(''); setTradeError(null) }}
              >
                Cancel
              </button>
              <button
                className="btn"
                type="button"
                disabled={tradeBusy || !brokerConfigured}
                onClick={() => requestOrder(tradeDialogInstrument, tradeDialogSide)}
              >
                Review Order
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmOpen && pendingOrder && (
        <div className="cp-modal-backdrop" role="dialog" aria-modal="true">
          <div className="cp-modal-card">
            <div className="cp-modal-title">Confirm Order</div>
            <div className="cp-modal-body">
              <div><strong>Account:</strong> {selectedAccount || tradeSummary?.selected_account || 'Default account'}</div>
              <div><strong>Action:</strong> {pendingOrder.side.toUpperCase()} {pendingOrder.instrumentType.toUpperCase()}</div>
              <div><strong>Symbol:</strong> {pendingOrder.symbol}</div>
              <div><strong>Quantity:</strong> {pendingOrder.quantity}</div>
              <div><strong>Order Type:</strong> {pendingOrder.orderType.toUpperCase()}</div>
              <div><strong>TIF:</strong> {pendingOrder.timeInForce.toUpperCase()}</div>
              {pendingOrder.orderType === 'limit' && (
                <div><strong>Limit Price:</strong> ${Number(pendingOrder.limitPrice || 0).toFixed(2)}</div>
              )}
            </div>
            <div className="cp-modal-actions">
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => { setConfirmOpen(false); setPendingOrder(null) }}
                disabled={tradeBusy}
              >
                Back
              </button>
              <button
                className="btn"
                type="button"
                onClick={executePendingOrder}
                disabled={tradeBusy}
              >
                {tradeBusy ? 'Submitting...' : 'Confirm & Submit'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Signal Breakdown Dialog ── */}
      {signalDialog && (
        <SignalBreakdownDialog
          signal={signalDialog.signal}
          score={signalDialog.score}
          factors={signalDialog.factors}
          title={signalDialog.title}
          riskTolerance={signalDialog.riskTolerance}
          onClose={() => setSignalDialog(null)}
        />
      )}
    </div>
  )
}
