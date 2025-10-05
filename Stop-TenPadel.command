#!/bin/bash
set -e
PID=$(lsof -ti tcp:5000 || true)
if [ -n "$PID" ]; then
  echo "🧹 Stop Flask (PID $PID)…"
  kill "$PID" || kill -9 "$PID"
else
  echo "ℹ️ Aucun serveur sur le port 5000."
fi
