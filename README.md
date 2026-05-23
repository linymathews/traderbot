# TraderBot 📈

A web application that connects to your brokerage account, monitors your portfolio, tracks congressional stock trades (Capitol Trades / QuiverQuant), and generates technical buy/sell signals for each position.

---

## Features

| Feature | Description |
|---|---|
| **Multi-broker** | Alpaca (paper & live), Robinhood, E-Trade |
| **Portfolio monitor** | Live positions, P&L, market value |
| **Technical analysis** | RSI, MACD, Bollinger Bands, SMA 50/200, volume |
| **Congressional trades** | Capitol Trades + QuiverQuant (optional) |
| **Combined signals** | Tech score + Congress score → BUY / SELL / HOLD |
| **Ad-hoc search** | Analyze any ticker, even outside your portfolio |
| **Auto-refresh** | Configurable refresh interval |

---

## Quick Start (development)

### 1. Configure `.env`

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set your broker credentials
cp frontend/.env.example frontend/.env
# Edit frontend/.env and set VITE_GOOGLE_CLIENT_ID
```

### 2. Run

```bash
./dev.sh
```

- Frontend → http://localhost:5173  
- API docs → http://localhost:8000/docs

### Google Login

TraderBot now requires login for all `/api/*` endpoints (except `/api/auth/*`).

1. Create an OAuth Client ID in Google Cloud Console (Web application type).
2. Add allowed JavaScript origins:
	- `http://localhost:5173` (dev)
	- `http://localhost:8000` (single-container deploy)
3. Set values:
	- `backend/.env` → `GOOGLE_CLIENT_ID=...`
	- `frontend/.env` → `VITE_GOOGLE_CLIENT_ID=...`

---

## Docker (single container)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up --build
```

- App (frontend + API) → http://localhost:8000
- API docs → http://localhost:8000/docs
- Health check → http://localhost:8000/healthz

### Persistent Data (MongoDB)

The consolidated deployment runs as a single app stack in `docker compose`:

- `app`: frontend + FastAPI backend
- `mongo`: internal database service for persisted backend data (for example auth sessions)

MongoDB data is stored in the named Docker volume `mongo_data`, so data survives container restarts/rebuilds.

User profile settings (broker credentials, toggles, weights, refresh settings) are now stored per authenticated user in MongoDB.

Useful commands:

```bash
docker compose up -d --build
docker compose down
docker volume ls | grep mongo_data
```

If you remove the volume (for a clean reset), persisted data is deleted:

```bash
docker compose down -v
```

---

## Broker Setup

### Alpaca (recommended — free paper trading)
1. Sign up at https://alpaca.markets  
2. Set `ACTIVE_BROKER=alpaca`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`  
3. `ALPACA_PAPER=true` for paper trading

### Robinhood
1. Set `ACTIVE_BROKER=robinhood`, `ROBINHOOD_USERNAME`, `ROBINHOOD_PASSWORD`  
2. For 2FA: set `ROBINHOOD_TOTP_SECRET` (base32 seed from Robinhood 2FA setup)

### E-Trade (OAuth flow)
1. Register a developer app at https://developer.etrade.com  
2. Set `ACTIVE_BROKER=etrade`, `ETRADE_CONSUMER_KEY`, `ETRADE_CONSUMER_SECRET`  
3. On first run visit `GET /api/broker/etrade/auth`, authorize in browser, then `POST /api/broker/etrade/auth {"verifier":"..."}`

---

## Congressional Trades Sources

| Source | Config |
|---|---|
| [Capitol Trades](https://capitoltrades.com) | `CAPITOL_TRADES_ENABLED=true` (no key needed) |
| [QuiverQuant](https://quiverquant.com) | Set `QUIVER_QUANT_API_KEY` |

---

## Signal Methodology

**Technical score** (max ±5): RSI, MACD, Bollinger Bands, SMA 50, SMA 50/200 cross  
**Congress score** (capped ±2 contribution): +2 per Purchase, −2 per Sale

| Combined score | Signal |
|---|---|
| ≥ 4 | STRONG BUY |
| ≥ 2 | BUY |
| −1 to +1 | HOLD |
| ≤ −2 | SELL |
| ≤ −4 | STRONG SELL |

---

> ⚠️ For informational/educational purposes only. Not financial advice.