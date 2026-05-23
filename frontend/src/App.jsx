import { useState, useEffect, useCallback } from 'react'
import Header from './components/Header'
import AccountSummary from './components/AccountSummary'
import AnalysisTable from './components/AnalysisTable'
import SymbolDetail from './components/SymbolDetail'
import CongressFeed from './components/CongressFeed'
import Profile from './components/Profile'
import CompanyProfile from './components/CompanyProfile'
import JobsManager from './components/JobsManager'
import StatusBar from './components/StatusBar'
import LoginGate from './components/LoginGate'
import './App.css'

const API = '/api'

export default function App() {
  const [tab, setTab] = useState('portfolio')  // portfolio | congress | search | company
  const [companySymbol, setCompanySymbol] = useState('')
  const [account, setAccount] = useState(null)
  const [analyses, setAnalyses] = useState([])
  const [rawPositions, setRawPositions] = useState([])
  const [pendingOrders, setPendingOrders] = useState([])
  const [portfolioMessage, setPortfolioMessage] = useState('')
  const [congressTrades, setCongressTrades] = useState([])
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [appSettings, setAppSettings] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [searchSymbol, setSearchSymbol] = useState('')
  const [searchResult, setSearchResult] = useState(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState(null)
  const [user, setUser] = useState(null)
  const [authConfig, setAuthConfig] = useState(null)
  const [showBrokerNotice, setShowBrokerNotice] = useState(true)

  const checkSession = useCallback(async () => {
    setAuthLoading(true)
    try {
      const res = await fetch(`${API}/auth/session`)
      const data = await res.json()
      if (res.ok && data.authenticated) {
        setUser(data.user || null)
      } else {
        setUser(null)
      }
      setAuthConfig({
        googleEnabled: data.google_enabled ?? false,
        localLoginEnabled: data.local_login_enabled ?? true,
      })
    } catch (e) {
      setUser(null)
      setAuthError('Unable to verify session. Please refresh and try again.')
    } finally {
      setAuthLoading(false)
    }
  }, [])
  const fetchStatus = useCallback(async () => {
    try {
      const [statusRes, settingsRes] = await Promise.all([
        fetch(`${API}/broker/status`),
        fetch(`${API}/settings`),
      ])
      setBrokerStatus(await statusRes.json())
      setAppSettings(await settingsRes.json())
    } catch (e) {
      console.error('Status fetch failed', e)
    }
  }, [])

  const fetchPortfolio = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/analysis`)
      if (!res.ok) {
        const body = await res.json()
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setAccount(data.account_summary)
      setAnalyses(data.analyses || [])
      setPendingOrders(data.pending_orders || [])
      setPortfolioMessage(data.message || '')

      // Fallback: show raw positions if analysis is empty but account has holdings.
      if ((data.analyses || []).length === 0 && (data.account_summary?.positions_count || 0) > 0) {
        try {
          const accountRes = await fetch(`${API}/account`)
          if (accountRes.ok) {
            const accountData = await accountRes.json()
            setRawPositions(accountData.positions || [])
          } else {
            setRawPositions([])
          }
        } catch {
          setRawPositions([])
        }
      } else {
        setRawPositions([])
      }

      setLastRefresh(new Date())
    } catch (e) {
      setError(e.message)
      setRawPositions([])
      setPendingOrders([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchCongressTrades = useCallback(async () => {
    try {
      const res = await fetch(`${API}/congress-trades`)
      const data = await res.json()
      setCongressTrades(data.trades || [])
    } catch (e) {
      console.error('Congress trades fetch failed', e)
    }
  }, [])

  const handleSearch = useCallback(async () => {
    const sym = searchSymbol.trim().toUpperCase()
    if (!sym) return
    setSearchLoading(true)
    setSearchResult(null)
    setError(null)
    try {
      const res = await fetch(`${API}/analysis/${sym}`)
      if (!res.ok) {
        const body = await res.json()
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setSearchResult(data)
      setSelectedSymbol(sym)
      setTab('search')
    } catch (e) {
      setError(e.message)
    } finally {
      setSearchLoading(false)
    }
  }, [searchSymbol])

  // Initial load
  useEffect(() => {
    checkSession()
  }, [checkSession])

  useEffect(() => {
    if (!user) return
    fetchStatus()
    fetchCongressTrades()
  }, [user, fetchStatus, fetchCongressTrades])

  useEffect(() => {
    if (!user) return
    if (!brokerStatus?.connected) return
    fetchPortfolio()
  }, [user, brokerStatus?.connected, fetchPortfolio])

  // Auto-refresh
  useEffect(() => {
    if (!user) return
    if (!appSettings?.refresh_interval_minutes) return
    const interval = setInterval(() => {
      fetchCongressTrades()
      if (brokerStatus?.connected) {
        fetchPortfolio()
      }
    }, appSettings.refresh_interval_minutes * 60 * 1000)
    return () => clearInterval(interval)
  }, [user, appSettings, brokerStatus?.connected, fetchPortfolio, fetchCongressTrades])

  const handleGoogleCredential = useCallback(async credential => {
    if (!credential) return
    setAuthBusy(true)
    setAuthError(null)
    try {
      const res = await fetch(`${API}/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail || 'Login failed')
      }
      setUser(data.user || null)
    } catch (e) {
      setAuthError(e.message || 'Login failed')
      setUser(null)
    } finally {
      setAuthBusy(false)
    }
  }, [])

  const handleLocalLogin = useCallback(async ({ name, email }) => {
    setAuthBusy(true)
    setAuthError(null)
    try {
      const res = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail || 'Login failed')
      }
      setUser(data.user || null)
    } catch (e) {
      setAuthError(e.message || 'Login failed')
      setUser(null)
    } finally {
      setAuthBusy(false)
    }
  }, [])

  const handleLogout = useCallback(async () => {
    setAuthBusy(true)
    try {
      await fetch(`${API}/auth/logout`, { method: 'POST' })
    } catch (e) {
      console.error('Logout failed', e)
    } finally {
      setUser(null)
      setAuthBusy(false)
    }
  }, [])

  if (authLoading) {
    return (
      <div className="login-shell">
        <div className="login-card"><p>Checking session...</p></div>
      </div>
    )
  }

  if (!user) {
    return (
      <LoginGate
        onCredential={handleGoogleCredential}
        onLocalLogin={handleLocalLogin}
        disabled={authBusy}
        error={authError}
        googleEnabled={authConfig?.googleEnabled ?? false}
        localLoginEnabled={authConfig?.localLoginEnabled ?? true}
      />
    )
  }

  const selectedAnalysis = selectedSymbol
    ? (analyses.find(a => a.symbol === selectedSymbol) || searchResult)
    : null

  // Broker is configured if it's connected
  const brokerConfigured = brokerStatus?.connected === true

  // If on portfolio tab but broker not configured, switch to congress tab
  const displayTab = (tab === 'portfolio' && !brokerConfigured) ? 'congress' : tab

  return (
    <div className="app">
      <Header
        brokerStatus={brokerStatus}
        appSettings={appSettings}
        user={user}
        onOpenProfile={() => setTab('profile')}
        onLogout={handleLogout}
        authBusy={authBusy}
      />

      <nav className="tabs">
        {brokerConfigured && (
          <button className={displayTab === 'portfolio' ? 'active' : ''} onClick={() => setTab('portfolio')}>
            Portfolio
          </button>
        )}
        <button className={displayTab === 'congress' ? 'active' : ''} onClick={() => setTab('congress')}>
          Congress Trades
          {congressTrades.length > 0 && <span className="badge">{congressTrades.length}</span>}
        </button>
        <button className={displayTab === 'company' ? 'active' : ''} onClick={() => setTab('company')}>
          🏢 Company
        </button>
        <button className={displayTab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>
          ⚙️ Jobs
        </button>
        {searchResult && (
          <button className={displayTab === 'search' ? 'active' : ''} onClick={() => setTab('search')}>
            {selectedSymbol}
          </button>
        )}
      </nav>

      <main className="content">
        {error && (
          <div className="error-banner">
            <strong>Error:</strong> {error}
            <button onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {!brokerConfigured && displayTab === 'company' && showBrokerNotice && (
          <div style={{ padding: '1rem', backgroundColor: '#fff3cd', border: '1px solid #ffc107', borderRadius: '4px', marginBottom: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
            <span><strong>⚠️ Broker Not Configured:</strong> Broker setup is optional. You can still use Congress Trades and Company research.</span>
            <button type="button" onClick={() => setShowBrokerNotice(false)}>✕</button>
          </div>
        )}

        {displayTab === 'portfolio' && (
          <>
            {account && <AccountSummary account={account} />}
            {selectedAnalysis && displayTab === 'portfolio' && selectedSymbol && (
              <SymbolDetail
                data={selectedAnalysis}
                onClose={() => setSelectedSymbol(null)}
                onBacktest={sym => { setCompanySymbol(sym); setTab('company'); setSelectedSymbol(null); }}
                onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); setSelectedSymbol(null); }}
              />
            )}
            <AnalysisTable
              analyses={analyses}
              rawPositions={rawPositions}
              pendingOrders={pendingOrders}
              loading={loading}
              emptyMessage={portfolioMessage}
              onSelect={sym => { setSelectedSymbol(sym); }}
              selectedSymbol={selectedSymbol}
              onRefresh={fetchPortfolio}
              onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); }}
            />
          </>
        )}

        {displayTab === 'congress' && (
          <CongressFeed
            trades={congressTrades}
            onSelectSymbol={sym => { setSearchSymbol(sym); handleSearch() }}
            onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); }}
          />
        )}

        {displayTab === 'company' && (
          <CompanyProfile
            symbol={companySymbol}
            onNavigate={sym => setCompanySymbol(sym)}
            riskTolerance={appSettings?.risk_tolerance ?? 5}
            brokerConfigured={brokerConfigured}
          />
        )}

        {displayTab === 'jobs' && <JobsManager />}

        {displayTab === 'profile' && <Profile />}

        {displayTab === 'search' && searchResult && (
          <SymbolDetail
            data={searchResult}
            onClose={() => { setSearchResult(null); setTab('portfolio') }}
            onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); }}
          />
        )}
      </main>

      <StatusBar lastRefresh={lastRefresh} loading={loading} />
    </div>
  )
}
