export default function StatusBar({ lastRefresh, loading }) {
  return (
    <div className="status-bar">
      <span>TraderBot v1.0 — for informational purposes only, not financial advice</span>
      <span>
        {loading && <><span className="spinner" />Updating… </>}
        {lastRefresh && !loading && `Last updated: ${lastRefresh.toLocaleTimeString()}`}
      </span>
    </div>
  )
}
