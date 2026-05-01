import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend, Filler
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

function fmt(n, prefix = '$') {
  if (n == null) return '—'
  return `${prefix}${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function RecChip({ rec }) {
  const classes = 'rec ' + (rec || '').replace(' ', '.')
  return <span className={classes} style={{ fontSize: 16, padding: '5px 16px' }}>{rec || '—'}</span>
}

function KV({ label, value, valueClass }) {
  return (
    <div className="kv-row">
      <span className="k">{label}</span>
      <span className={`v ${valueClass || ''}`}>{value}</span>
    </div>
  )
}

export default function SymbolDetail({ data, onClose, onBacktest, onViewCompany }) {
  if (!data) return null

  const { symbol, final_recommendation, combined_score, technical, congress, position, price_history } = data
  const ind = technical?.indicators || {}

  // Chart data
  const chartLabels = (price_history || []).map(d => d.date)
  const chartPrices = (price_history || []).map(d => d.close)

  const chartData = {
    labels: chartLabels,
    datasets: [{
      label: 'Close',
      data: chartPrices,
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99,102,241,0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 1.5,
    }],
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
    scales: {
      x: { ticks: { color: '#8892a4', maxTicksLimit: 6, font: { size: 10 } }, grid: { color: '#2e3148' } },
      y: { ticks: { color: '#8892a4', font: { size: 10 } }, grid: { color: '#2e3148' } },
    },
  }

  const scoreColor = combined_score > 0 ? 'pos' : combined_score < 0 ? 'neg' : 'neu'

  return (
    <div className="detail-overlay">
      <button className="close-btn" onClick={onClose}>✕</button>

      <div className="detail-top">
        <span className="detail-symbol">{symbol}</span>
        <span className="detail-price">{fmt(technical?.current_price)}</span>
        <RecChip rec={final_recommendation} />
        <span className={`score-val ${scoreColor}`} style={{ fontSize: 16 }}>
          Score: {combined_score > 0 ? '+' : ''}{combined_score}
        </span>
        {onBacktest && (
          <button className="btn btn-ghost btn-sm" onClick={() => onBacktest(symbol)}
            style={{ marginLeft: 'auto' }}>
            ⏱ Back-Test
          </button>
        )}
        {onViewCompany && (
          <button className="btn btn-ghost btn-sm" onClick={() => onViewCompany(symbol)}>
            🏢 Company Profile
          </button>
        )}
      </div>

      {price_history?.length > 0 && (
        <div className="chart-container">
          <Line data={chartData} options={chartOptions} />
        </div>
      )}

      <div className="detail-grid" style={{ marginTop: 16 }}>

        {/* Position */}
        {position && (
          <div className="detail-section">
            <h3>Position</h3>
            <KV label="Quantity" value={position.quantity} />
            <KV label="Avg Cost" value={fmt(position.avg_cost)} />
            <KV label="Market Value" value={fmt(position.market_value)} />
            <KV label="Unrealized P&L" value={fmt(position.unrealized_pl)}
              valueClass={position.unrealized_pl >= 0 ? 'pos' : 'neg'} />
            <KV label="P&L %" value={`${position.unrealized_pl_pct >= 0 ? '+' : ''}${Number(position.unrealized_pl_pct).toFixed(2)}%`}
              valueClass={position.unrealized_pl_pct >= 0 ? 'pos' : 'neg'} />
          </div>
        )}

        {/* Technical */}
        <div className="detail-section">
          <h3>Technical Indicators</h3>
          <KV label="RSI(14)" value={ind.rsi ?? '—'} valueClass={
            ind.rsi < 30 ? 'pos' : ind.rsi > 70 ? 'neg' : 'neu'
          } />
          <KV label="RSI Signal" value={ind.rsi_signal ?? '—'} />
          <KV label="MACD" value={ind.macd ?? '—'} />
          <KV label="MACD Signal" value={ind.macd_signal ?? '—'} />
          <KV label="MACD Cross" value={ind.macd_cross ?? '—'} />
          <KV label="BB Signal" value={ind.bb_signal ?? '—'} />
          {ind.sma50 && <KV label="SMA 50" value={fmt(ind.sma50)} />}
          {ind.sma200 && <KV label="SMA 200" value={fmt(ind.sma200)} />}
          {ind.sma_cross && <KV label="SMA Cross" value={ind.sma_cross} />}
          <KV label="Volume Signal" value={ind.volume_signal ?? '—'} />
        </div>

        {/* Congress */}
        <div className="detail-section">
          <h3>Congressional Trades</h3>
          <KV label="Signal" value={congress?.congress_signal ?? '—'}
            valueClass={congress?.congress_signal === 'BULLISH' ? 'pos' : congress?.congress_signal === 'BEARISH' ? 'neg' : 'neu'} />
          <KV label="Score" value={congress?.congress_score ?? 0} />
          <KV label="Buys" value={congress?.congress_buys ?? 0} valueClass="pos" />
          <KV label="Sells" value={congress?.congress_sells ?? 0} valueClass="neg" />

          {congress?.recent_trades?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Recent trades:</div>
              {congress.recent_trades.slice(0, 5).map((t, i) => {
                const isBuy = /purchase|buy/i.test(t.transaction)
                return (
                  <div key={i} style={{ fontSize: 12, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
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
    </div>
  )
}
