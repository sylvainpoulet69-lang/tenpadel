#!/bin/bash
PID=$(lsof -ti tcp:5000)
if [ -n "$PID" ]; then
  echo "🧹 Arrêt du serveur Flask (PID: $PID)..."
  kill "$PID" || kill -9 "$PID"
else
  echo "⚠️ Aucun serveur trouvé sur le port 5000."
fi
