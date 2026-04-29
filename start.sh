#!/usr/bin/env bash
# Pokolysis — start backend + frontend

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV="$SCRIPT_DIR/venv"

if [ ! -f "$VENV/bin/activate" ]; then
  echo "❌  Venv not found. Run: python3 -m venv venv && source venv/bin/activate && pip install -r backend/requirements.txt"
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "❌  node_modules not found. Run: cd frontend && npm install"
  exit 1
fi

echo "▶  Starting backend (port 8002)..."
source "$VENV/bin/activate"
cd "$BACKEND_DIR"
uvicorn main:app --host 0.0.0.0 --port 8002 --reload &
BACKEND_PID=$!

echo "▶  Starting frontend (port 5173)..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo "⏳  Waiting for frontend..."
for i in $(seq 1 30); do
  curl -s http://localhost:5173 > /dev/null 2>&1 && break
  sleep 1
done

echo "🌐  Opening http://localhost:5173 ..."
open http://localhost:5173

trap "echo '🛑  Shutting down...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

echo ""
echo "✅  Backend:  http://localhost:8002"
echo "✅  Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop."
wait
