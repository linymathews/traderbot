import { useEffect, useRef, useState } from 'react'

function loadGoogleScript() {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) {
      resolve()
      return
    }

    const existing = document.querySelector('script[data-google-gsi="1"]')
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Failed to load Google script')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.dataset.googleGsi = '1'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Google script'))
    document.head.appendChild(script)
  })
}

export default function LoginGate({ onCredential, onLocalLogin, disabled, error, googleEnabled = false, localLoginEnabled = true }) {
  const buttonRef = useRef(null)
  const initializedRef = useRef(false)
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')

  useEffect(() => {
    // Only render Google button if both clientId exists in env AND server has Google enabled
    if (!clientId || !googleEnabled || initializedRef.current || !buttonRef.current) return

    let cancelled = false

    loadGoogleScript()
      .then(() => {
        if (cancelled || !window.google?.accounts?.id) return
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: response => {
            if (response?.credential) {
              onCredential(response.credential)
            }
          },
        })
        buttonRef.current.innerHTML = ''
        window.google.accounts.id.renderButton(buttonRef.current, {
          type: 'standard',
          theme: 'outline',
          text: 'continue_with',
          size: 'large',
          width: 280,
          shape: 'pill',
        })
        initializedRef.current = true
      })
      .catch(err => {
        console.error(err)
      })

    return () => {
      cancelled = true
    }
  }, [clientId, googleEnabled, onCredential])

  const submitLocalLogin = e => {
    e.preventDefault()
    if (!onLocalLogin || disabled) return
    onLocalLogin({ name, email })
  }

  // Determine which auth methods are available
  const hasGoogle = clientId && googleEnabled
  const hasLocal = localLoginEnabled
  const showDivider = hasGoogle && hasLocal

  return (
    <div className="login-shell">
      <div className="login-card">
        <h1>TraderBot</h1>
        <p className="login-sub">Sign in to access your portfolio, analyses, and company research workspace.</p>

        {hasGoogle && <div className={`google-btn-wrap ${disabled ? 'disabled' : ''}`} ref={buttonRef} />}

        {showDivider && <div className="login-divider"><span>or</span></div>}

        {hasLocal && (
          <form className="login-form" onSubmit={submitLocalLogin}>
            <input
              type="text"
              className="login-input"
              placeholder="Name (optional)"
              value={name}
              onChange={e => setName(e.target.value)}
              disabled={disabled}
            />
            <input
              type="email"
              className="login-input"
              placeholder="Email (optional)"
              value={email}
              onChange={e => setEmail(e.target.value)}
              disabled={disabled}
            />
            <button type="submit" className="btn" disabled={disabled}>
              {disabled ? 'Signing in...' : 'Continue'}
            </button>
          </form>
        )}

        {error && <div className="login-error">{error}</div>}
      </div>
    </div>
  )
}
