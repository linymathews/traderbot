import { useState, useEffect, useCallback } from 'react'

const API = '/api/profile'

const BROKER_INFO = {
  alpaca: {
    label: 'Alpaca',
    icon: '🦙',
    url: 'https://alpaca.markets',
    description: 'Commission-free trading API. Supports paper & live trading.',
  },
  robinhood: {
    label: 'Robinhood',
    icon: '🏹',
    url: 'https://robinhood.com',
    description: 'Commission-free US stock & options broker.',
  },
  etrade: {
    label: 'E*TRADE',
    icon: '📊',
    url: 'https://developer.etrade.com',
    description: 'Full-service broker with OAuth1 API. Requires app registration.',
  },
}

const ALT_PROVIDER_CONTROLS = [
  { id: 'capitol_trades', label: 'Capitol Trades' },
  { id: 'openinsider', label: 'OpenInsider' },
  { id: 'whalewisdom', label: 'WhaleWisdom' },
  { id: 'quiver_quantitative', label: 'Quiver Quantitative' },
  { id: 'alpha_vantage', label: 'Alpha Vantage' },
  { id: 'polygon', label: 'Polygon.io' },
  { id: 'fmp', label: 'Financial Modeling Prep' },
  { id: 'eodhd', label: 'EODHD' },
  { id: 'fred', label: 'FRED' },
  { id: 'tiingo', label: 'Tiingo' },
  { id: 'lunarcrush', label: 'StockGeist / LunarCrush' },
]

function Field({ label, name, type = 'text', value, onChange, placeholder, hint, toggle }) {
  const [show, setShow] = useState(false)
  const inputType = type === 'password' ? (show ? 'text' : 'password') : type
  return (
    <div className="pf-field">
      <label className="pf-label">{label}</label>
      <div className="pf-input-wrap">
        <input
          className="pf-input"
          type={inputType}
          name={name}
          value={value}
          onChange={onChange}
          placeholder={placeholder || ''}
          autoComplete="off"
        />
        {type === 'password' && (
          <button
            type="button"
            className="pf-eye"
            onClick={() => setShow(s => !s)}
            tabIndex={-1}
            title={show ? 'Hide' : 'Show'}
          >
            {show ? '🙈' : '👁'}
          </button>
        )}
      </div>
      {hint && <div className="pf-hint">{hint}</div>}
    </div>
  )
}

function Toggle({ label, checked, onChange, hint }) {
  return (
    <div className="pf-field pf-toggle-field">
      <span className="pf-label">{label}</span>
      <label className="toggle-switch">
        <input type="checkbox" checked={checked} onChange={onChange} />
        <span className="toggle-slider" />
      </label>
      {hint && <div className="pf-hint">{hint}</div>}
    </div>
  )
}

function BrokerSection({ broker, active, form, onChange, onTest, testResult, testing }) {
  const info = BROKER_INFO[broker]
  const isActive = active === broker

  return (
    <div className={`broker-card ${isActive ? 'broker-active' : ''}`}>
      <div className="broker-card-header">
        <span className="broker-icon">{info.icon}</span>
        <div>
          <div className="broker-name">{info.label}</div>
          <div className="broker-desc">{info.description}</div>
        </div>
        {isActive && <span className="active-badge">ACTIVE</span>}
      </div>

      {broker === 'alpaca' && (
        <>
          <Field label="API Key" name="alpaca_api_key" type="password"
            value={form.alpaca_api_key} onChange={onChange}
            placeholder="Enter new key (or leave to keep current)"
            hint={form._masked?.alpaca_api_key_masked ? `Current: ${form._masked.alpaca_api_key_masked}` : ''} />
          <Field label="Secret Key" name="alpaca_secret_key" type="password"
            value={form.alpaca_secret_key} onChange={onChange}
            placeholder="Enter new secret"
            hint={form._masked?.alpaca_secret_key_masked ? `Current: ${form._masked.alpaca_secret_key_masked}` : ''} />
          <Toggle label="Paper Trading Mode"
            checked={form.alpaca_paper}
            onChange={e => onChange({ target: { name: 'alpaca_paper', value: e.target.checked, type: 'checkbox' } })}
            hint="Use paper trading (simulated) instead of real money" />
        </>
      )}

      {broker === 'robinhood' && (
        <>
          <Field label="Email / Username" name="robinhood_username" type="text"
            value={form.robinhood_username} onChange={onChange}
            placeholder="your@email.com" />
          <Field label="Password" name="robinhood_password" type="password"
            value={form.robinhood_password} onChange={onChange}
            placeholder="Enter new password" />
          <Field label="TOTP Secret (2FA)" name="robinhood_totp_secret" type="password"
            value={form.robinhood_totp_secret} onChange={onChange}
            placeholder="Base32 seed (optional)"
            hint={`2FA configured: ${form._masked?.robinhood_totp_configured ? 'Yes ✓' : 'No'}`} />
        </>
      )}

      {broker === 'etrade' && (
        <>
          <Field label="Consumer Key" name="etrade_consumer_key" type="password"
            value={form.etrade_consumer_key} onChange={onChange}
            placeholder="From developer.etrade.com"
            hint={form._masked?.etrade_consumer_key_masked ? `Current: ${form._masked.etrade_consumer_key_masked}` : ''} />
          <Field label="Consumer Secret" name="etrade_consumer_secret" type="password"
            value={form.etrade_consumer_secret} onChange={onChange}
            placeholder="Enter new secret" />
          <Toggle label="Sandbox Mode"
            checked={form.etrade_sandbox}
            onChange={e => onChange({ target: { name: 'etrade_sandbox', value: e.target.checked, type: 'checkbox' } })}
            hint="Use E-Trade sandbox instead of live" />
          <div className="pf-hint" style={{ marginTop: 4 }}>
            E-Trade uses OAuth1. After saving keys, use the OAuth flow from the Portfolio tab to connect.
          </div>
        </>
      )}

      <div className="broker-card-footer">
        {broker !== 'etrade' && (
          <button
            className={`btn btn-sm ${testing === broker ? '' : 'btn-ghost'}`}
            onClick={() => onTest(broker)}
            disabled={!!testing}
          >
            {testing === broker ? <><span className="spinner" />Testing…</> : '⚡ Test Connection'}
          </button>
        )}
        {testResult?.broker === broker && (
          <span className={`conn-result ${testResult.success ? 'pos' : 'neg'}`}>
            {testResult.success ? '✓ ' : '✗ '}{testResult.message}
            {testResult.portfolio_value != null && (
              <> — Portfolio: ${Number(testResult.portfolio_value).toLocaleString('en-US', { minimumFractionDigits: 2 })}</>
            )}
          </span>
        )}
      </div>
    </div>
  )
}

export default function Profile() {
  const [form, setForm] = useState({
    active_broker: 'alpaca',
    alpaca_api_key: '', alpaca_secret_key: '', alpaca_paper: true,
    robinhood_username: '', robinhood_password: '', robinhood_totp_secret: '',
    etrade_consumer_key: '', etrade_consumer_secret: '', etrade_sandbox: true,
    capitol_trades_enabled: true, quiver_quant_api_key: '',
    alt_enable_capitol_trades: true,
    alt_enable_openinsider: true,
    alt_enable_whalewisdom: true,
    alt_enable_quiver_quantitative: true,
    alt_enable_alpha_vantage: true,
    alt_enable_polygon: true,
    alt_enable_fmp: true,
    alt_enable_eodhd: true,
    alt_enable_fred: true,
    alt_enable_tiingo: true,
    alt_enable_lunarcrush: true,
    alt_weight_capitol_trades: 1.0,
    alt_weight_openinsider: 1.0,
    alt_weight_whalewisdom: 0.35,
    alt_weight_quiver_quantitative: 0.9,
    alt_weight_alpha_vantage: 0.85,
    alt_weight_polygon: 0.6,
    alt_weight_fmp: 0.35,
    alt_weight_eodhd: 0.55,
    alt_weight_fred: 0.45,
    alt_weight_tiingo: 0.25,
    alt_weight_lunarcrush: 0.5,
    refresh_interval_minutes: 15, signal_lookback_days: 90,
    _masked: {},
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)
  const [testing, setTesting] = useState(null)     // broker name being tested
  const [testResult, setTestResult] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(API)
      const data = await res.json()
      setForm(f => ({
        ...f,
        active_broker: data.active_broker,
        alpaca_paper: data.alpaca_paper,
        alpaca_api_key: '',
        alpaca_secret_key: '',
        robinhood_username: data.robinhood_username,
        robinhood_password: '',
        robinhood_totp_secret: '',
        etrade_consumer_key: '',
        etrade_consumer_secret: '',
        etrade_sandbox: data.etrade_sandbox,
        capitol_trades_enabled: data.capitol_trades_enabled,
        quiver_quant_api_key: '',
        alt_enable_capitol_trades: data.alt_enable_capitol_trades,
        alt_enable_openinsider: data.alt_enable_openinsider,
        alt_enable_whalewisdom: data.alt_enable_whalewisdom,
        alt_enable_quiver_quantitative: data.alt_enable_quiver_quantitative,
        alt_enable_alpha_vantage: data.alt_enable_alpha_vantage,
        alt_enable_polygon: data.alt_enable_polygon,
        alt_enable_fmp: data.alt_enable_fmp,
        alt_enable_eodhd: data.alt_enable_eodhd,
        alt_enable_fred: data.alt_enable_fred,
        alt_enable_tiingo: data.alt_enable_tiingo,
        alt_enable_lunarcrush: data.alt_enable_lunarcrush,
        alt_weight_capitol_trades: data.alt_weight_capitol_trades,
        alt_weight_openinsider: data.alt_weight_openinsider,
        alt_weight_whalewisdom: data.alt_weight_whalewisdom,
        alt_weight_quiver_quantitative: data.alt_weight_quiver_quantitative,
        alt_weight_alpha_vantage: data.alt_weight_alpha_vantage,
        alt_weight_polygon: data.alt_weight_polygon,
        alt_weight_fmp: data.alt_weight_fmp,
        alt_weight_eodhd: data.alt_weight_eodhd,
        alt_weight_fred: data.alt_weight_fred,
        alt_weight_tiingo: data.alt_weight_tiingo,
        alt_weight_lunarcrush: data.alt_weight_lunarcrush,
        refresh_interval_minutes: data.refresh_interval_minutes,
        signal_lookback_days: data.signal_lookback_days,
        _masked: data,
      }))
    } catch (e) {
      setError('Failed to load profile: ' + e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleChange = e => {
    const { name, value, type, checked } = e.target
    setForm(f => ({ ...f, [name]: type === 'checkbox' ? checked : value }))
    setSaved(false)
    setError(null)
  }

  const handleActiveBroker = broker => {
    setForm(f => ({ ...f, active_broker: broker }))
    setSaved(false)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const payload = {
        active_broker: form.active_broker,
        alpaca_paper: form.alpaca_paper,
        etrade_sandbox: form.etrade_sandbox,
        capitol_trades_enabled: form.capitol_trades_enabled,
        refresh_interval_minutes: Number(form.refresh_interval_minutes),
        signal_lookback_days: Number(form.signal_lookback_days),
        alt_enable_capitol_trades: form.alt_enable_capitol_trades,
        alt_enable_openinsider: form.alt_enable_openinsider,
        alt_enable_whalewisdom: form.alt_enable_whalewisdom,
        alt_enable_quiver_quantitative: form.alt_enable_quiver_quantitative,
        alt_enable_alpha_vantage: form.alt_enable_alpha_vantage,
        alt_enable_polygon: form.alt_enable_polygon,
        alt_enable_fmp: form.alt_enable_fmp,
        alt_enable_eodhd: form.alt_enable_eodhd,
        alt_enable_fred: form.alt_enable_fred,
        alt_enable_tiingo: form.alt_enable_tiingo,
        alt_enable_lunarcrush: form.alt_enable_lunarcrush,
        alt_weight_capitol_trades: Number(form.alt_weight_capitol_trades),
        alt_weight_openinsider: Number(form.alt_weight_openinsider),
        alt_weight_whalewisdom: Number(form.alt_weight_whalewisdom),
        alt_weight_quiver_quantitative: Number(form.alt_weight_quiver_quantitative),
        alt_weight_alpha_vantage: Number(form.alt_weight_alpha_vantage),
        alt_weight_polygon: Number(form.alt_weight_polygon),
        alt_weight_fmp: Number(form.alt_weight_fmp),
        alt_weight_eodhd: Number(form.alt_weight_eodhd),
        alt_weight_fred: Number(form.alt_weight_fred),
        alt_weight_tiingo: Number(form.alt_weight_tiingo),
        alt_weight_lunarcrush: Number(form.alt_weight_lunarcrush),
      }
      // Only send secret fields if they were actually typed (non-empty)
      if (form.alpaca_api_key.trim())        payload.alpaca_api_key = form.alpaca_api_key.trim()
      if (form.alpaca_secret_key.trim())     payload.alpaca_secret_key = form.alpaca_secret_key.trim()
      if (form.robinhood_username.trim())    payload.robinhood_username = form.robinhood_username.trim()
      if (form.robinhood_password.trim())    payload.robinhood_password = form.robinhood_password.trim()
      if (form.robinhood_totp_secret.trim()) payload.robinhood_totp_secret = form.robinhood_totp_secret.trim()
      if (form.etrade_consumer_key.trim())   payload.etrade_consumer_key = form.etrade_consumer_key.trim()
      if (form.etrade_consumer_secret.trim()) payload.etrade_consumer_secret = form.etrade_consumer_secret.trim()
      if (form.quiver_quant_api_key.trim())  payload.quiver_quant_api_key = form.quiver_quant_api_key.trim()

      const res = await fetch(API, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json()
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      setSaved(true)
      // Reload to refresh masked values
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async broker => {
    setTesting(broker)
    setTestResult(null)
    try {
      const res = await fetch(`${API}/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ broker }),
      })
      const data = await res.json()
      setTestResult(data)
    } catch (e) {
      setTestResult({ broker, success: false, message: e.message })
    } finally {
      setTesting(null)
    }
  }

  if (loading) {
    return <div className="pf-loading"><span className="spinner" /> Loading profile…</div>
  }

  return (
    <div className="profile-page">
      <div className="pf-header">
        <div>
          <h2>Account Profile &amp; Settings</h2>
          <p className="pf-subtitle">
            Configure broker credentials and application preferences.
            Secrets are stored in your local <code>.env</code> file and never transmitted externally.
          </p>
        </div>
        <div className="pf-actions">
          {saved && <span className="save-ok">✓ Saved</span>}
          <button className="btn" onClick={save} disabled={saving}>
            {saving ? <><span className="spinner" />Saving…</> : '💾 Save Changes'}
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <strong>Error:</strong> {error}
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* ── Active broker selector ── */}
      <section className="pf-section">
        <h3 className="pf-section-title">Active Broker</h3>
        <div className="broker-selector">
          {Object.entries(BROKER_INFO).map(([key, info]) => (
            <button
              key={key}
              className={`broker-pick ${form.active_broker === key ? 'broker-pick-active' : ''}`}
              onClick={() => handleActiveBroker(key)}
            >
              <span className="bp-icon">{info.icon}</span>
              <span className="bp-label">{info.label}</span>
              {form._masked?.[`${key}_configured`] && (
                <span className="bp-check" title="Credentials configured">✓</span>
              )}
            </button>
          ))}
        </div>
      </section>

      {/* ── Broker credential sections ── */}
      <section className="pf-section">
        <h3 className="pf-section-title">Broker Credentials</h3>
        <div className="broker-cards">
          {Object.keys(BROKER_INFO).map(broker => (
            <BrokerSection
              key={broker}
              broker={broker}
              active={form.active_broker}
              form={form}
              onChange={handleChange}
              onTest={testConnection}
              testResult={testResult}
              testing={testing}
            />
          ))}
        </div>
      </section>

      {/* ── Data sources ── */}
      <section className="pf-section">
        <h3 className="pf-section-title">Data Sources</h3>
        <div className="pf-grid">
          <div className="pf-card">
            <div className="pf-card-title">
              🏛 Capitol Trades
              <a href="https://capitoltrades.com" target="_blank" rel="noreferrer" className="pf-link">capitoltrades.com ↗</a>
            </div>
            <Toggle
              label="Enable Capitol Trades"
              checked={form.capitol_trades_enabled}
              onChange={e => handleChange({ target: { name: 'capitol_trades_enabled', value: e.target.checked, type: 'checkbox' } })}
              hint="Fetch congressional stock disclosures (no API key needed)"
            />
          </div>
          <div className="pf-card">
            <div className="pf-card-title">
              📈 QuiverQuant
              <a href="https://quiverquant.com" target="_blank" rel="noreferrer" className="pf-link">quiverquant.com ↗</a>
            </div>
            <Field
              label="API Key"
              name="quiver_quant_api_key"
              type="password"
              value={form.quiver_quant_api_key}
              onChange={handleChange}
              placeholder="Optional — enhances congress trade data"
              hint={form._masked?.quiver_quant_configured ? `Configured: ${form._masked.quiver_quant_api_key_masked}` : 'Not configured'}
            />
          </div>

          <div className="pf-card" style={{ gridColumn: '1 / -1' }}>
            <div className="pf-card-title">🧠 Alternative Data Weights & Toggles</div>
            <div className="table-wrap">
              <table className="cp-chain-table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Enabled</th>
                    <th>Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {ALT_PROVIDER_CONTROLS.map(p => {
                    const enableKey = `alt_enable_${p.id}`
                    const weightKey = `alt_weight_${p.id}`
                    return (
                      <tr key={p.id}>
                        <td>{p.label}</td>
                        <td>
                          <label className="toggle-switch">
                            <input
                              type="checkbox"
                              name={enableKey}
                              checked={!!form[enableKey]}
                              onChange={handleChange}
                            />
                            <span className="toggle-slider" />
                          </label>
                        </td>
                        <td>
                          <input
                            className="pf-input pf-input-sm"
                            style={{ width: 90 }}
                            type="number"
                            min="0"
                            max="3"
                            step="0.05"
                            name={weightKey}
                            value={form[weightKey]}
                            onChange={handleChange}
                          />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div className="pf-hint">Weight range 0-3. Higher values increase that provider's impact on signal and backtest.</div>
          </div>
        </div>
      </section>

      {/* ── App preferences ── */}
      <section className="pf-section">
        <h3 className="pf-section-title">Application Preferences</h3>
        <div className="pf-grid">
          <div className="pf-card">
            <div className="pf-card-title">🔄 Auto-Refresh</div>
            <div className="pf-field">
              <label className="pf-label">Refresh Interval (minutes)</label>
              <input
                className="pf-input pf-input-sm"
                type="number"
                min="1"
                max="60"
                name="refresh_interval_minutes"
                value={form.refresh_interval_minutes}
                onChange={handleChange}
              />
              <div className="pf-hint">How often to auto-refresh portfolio analysis (1–60 min)</div>
            </div>
          </div>
          <div className="pf-card">
            <div className="pf-card-title">📅 Signal History</div>
            <div className="pf-field">
              <label className="pf-label">Lookback Days</label>
              <input
                className="pf-input pf-input-sm"
                type="number"
                min="30"
                max="365"
                name="signal_lookback_days"
                value={form.signal_lookback_days}
                onChange={handleChange}
              />
              <div className="pf-hint">How many days of price history to use for signals (30–365)</div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Save footer ── */}
      <div className="pf-footer">
        {saved && <span className="save-ok">✓ All changes saved</span>}
        {error && <span className="neg">{error}</span>}
        <button className="btn" onClick={save} disabled={saving}>
          {saving ? <><span className="spinner" />Saving…</> : '💾 Save Changes'}
        </button>
      </div>
    </div>
  )
}
