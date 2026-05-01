#!/usr/bin/env bash
# dev.sh — start backend and frontend in development mode
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Copy .env if it doesn't exist
if [ ! -f "$ROOT/backend/.env" ]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "⚠  Created backend/.env from .env.example — please fill in your credentials."
fi

echo "=== Installing Python dependencies ==="
cd "$ROOT/backend"
pip install -q -r requirements.txt

echo ""
echo "=== Starting FastAPI backend on http://localhost:8000 ==="
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo ""
echo "=== Installing Node dependencies ==="
cd "$ROOT/frontend"
npm install --silent

echo ""
echo "=== Starting Vite frontend on http://localhost:5173 ==="
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅  TraderBot running:"
echo "   Frontend → http://localhost:5173"
echo "   API docs → http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
