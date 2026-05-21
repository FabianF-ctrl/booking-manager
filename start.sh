#!/bin/bash
# start.sh — uruchamia HospesAI na Mac/Linux
# Użycie: ./start.sh

cd "$(dirname "$0")"

# Aktywuj środowisko
source BM-Venv/bin/activate

echo "============================================"
echo "  HospesAI"
echo "  http://localhost:8000"
echo "  Ctrl+C żeby zatrzymać"
echo "============================================"

uvicorn app:app --host 0.0.0.0 --port 8000 --reload
