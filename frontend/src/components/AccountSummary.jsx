function fmt(n, prefix = '$') {
  if (n == null) return '—'
  return `${prefix}${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function AccountSummary({ account }) {
  return (
    <div className="account-summary">
      <div className="stat-card">
        <div className="label">Portfolio Value</div>
        <div className="value">{fmt(account.portfolio_value)}</div>
        <div className="sub">{account.broker?.toUpperCase()}</div>
      </div>
      <div className="stat-card">
        <div className="label">Cash</div>
        <div className="value">{fmt(account.cash)}</div>
      </div>
      <div className="stat-card">
        <div className="label">Positions</div>
        <div className="value">{account.positions_count}</div>
        <div className="sub">open</div>
      </div>
    </div>
  )
}
