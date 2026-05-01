import { useState, useEffect, useCallback } from 'react'
import Header from './components/Header'
import AccountSummary from './components/AccountSummary'
import AnalysisTable from './components/AnalysisTable'
import SymbolDetail from './components/SymbolDetail'
import CongressFeed from './components/CongressFeed'
import Backtest from './components/Backtest'
import Profile from './components/Profile'
import CompanyProfile from './components/CompanyProfile'
import StatusBar from './components/StatusBar'
import './App.css'

const API = '/api'

export default function App() {
  const [tab, setTab] = useState('portfolio')  // portfolio | congress | backtest | search | company
  const [companySymbol, setCompanySymbol] = useState('')
  const [account, setAccount] = useState(null)
  const [analyses, setAnalyses] = useState([])
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
  const [backtestSymbol, setBacktestSymbol] = useState('')

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
      setLastRefresh(new Date())
    } catch (e) {
      setError(e.message)
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
    fetchStatus()
    fetchPortfolio()
    fetchCongressTrades()
  }, [fetchStatus, fetchPortfolio, fetchCongressTrades])

  // Auto-refresh
  useEffect(() => {
    if (!appSettings?.refresh_interval_minutes) return
    const interval = setInterval(() => {
      fetchPortfolio()
      fetchCongressTrades()
    }, appSettings.refresh_interval_minutes * 60 * 1000)
    return () => clearInterval(interval)
  }, [appSettings, fetchPortfolio, fetchCongressTrades])

  const selectedAnalysis = selectedSymbol
    ? (analyses.find(a => a.symbol === selectedSymbol) || searchResult)
    : null

  return (
    <div className="app">
      <Header
        brokerStatus={brokerStatus}
        appSettings={appSettings}
        searchSymbol={searchSymbol}
        setSearchSymbol={setSearchSymbol}
        onSearch={handleSearch}
        searchLoading={searchLoading}
      />

      <nav className="tabs">
        <button className={tab === 'portfolio' ? 'active' : ''} onClick={() => setTab('portfolio')}>
          Portfolio
        </button>
        <button className={tab === 'congress' ? 'active' : ''} onClick={() => setTab('congress')}>
          Congress Trades
          {congressTrades.length > 0 && <span className="badge">{congressTrades.length}</span>}
        </button>
        <button className={tab === 'backtest' ? 'active' : ''} onClick={() => setTab('backtest')}>
          Back-Test
        </button>
        <button className={tab === 'company' ? 'active' : ''} onClick={() => setTab('company')}>
          🏢 Company
        </button>
        <button className={tab === 'profile' ? 'active' : ''} onClick={() => setTab('profile')} style={{marginLeft:'auto'}}>
          ⚙ Settings
        </button>
        {searchResult && (
          <button className={tab === 'search' ? 'active' : ''} onClick={() => setTab('search')}>
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

        {tab === 'portfolio' && (
          <>
            {account && <AccountSummary account={account} />}
            {selectedAnalysis && tab === 'portfolio' && selectedSymbol && (
              <SymbolDetail
                data={selectedAnalysis}
                onClose={() => setSelectedSymbol(null)}
                onBacktest={sym => { setBacktestSymbol(sym); setTab('backtest'); setSelectedSymbol(null); }}
                onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); setSelectedSymbol(null); }}
              />
            )}
            <AnalysisTable
              analyses={analyses}
              loading={loading}
              onSelect={sym => { setSelectedSymbol(sym); }}
              selectedSymbol={selectedSymbol}
              onRefresh={fetchPortfolio}
              onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); }}
            />
          </>
        )}

        {tab === 'congress' && (
          <CongressFeed
            trades={congressTrades}
            onSelectSymbol={sym => { setSearchSymbol(sym); handleSearch() }}
            onViewCompany={sym => { setCompanySymbol(sym); setTab('company'); }}
          />
        )}

        {tab === 'backtest' && <Backtest initialSymbol={backtestSymbol} />}

        {tab === 'company' && (
          <CompanyProfile
            symbol={companySymbol}
            onNavigate={sym => setCompanySymbol(sym)}
          />
        )}

        {tab === 'profile' && <Profile />}

        {tab === 'search' && searchResult && (
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
