#!/bin/bash
# demo/start.sh — uruchamia booking-manager w trybie demo (do screenshotów)
#
# Co robi:
#   1. Backup prawdziwego data/ → data.real-backup/
#   2. Kopiuje demo/data/* → data/
#   3. Chowa static/locations.local.js → .demo-backup (żeby fallback fictional names zadziałał)
#   4. Odpala serwer na http://localhost:8003
#   5. Na Ctrl+C — przywraca prawdziwe data/ + locations.local.js
#
# Po zatrzymaniu masz pewność że nic nie zostało zmienione w produkcyjnych danych
# ani w static/.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REAL_DATA_BACKUP="data.real-backup"
DEMO_DATA="demo/data"
LOCATIONS_OVERRIDE_FILE="static/locations.local.js"
LOCATIONS_BACKUP="static/locations.local.js.demo-backup"
PORT="${DEMO_PORT:-8003}"

# Wybierz venv
if [ -x ".venv-preview/bin/python" ]; then
    PYTHON=".venv-preview/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif [ -x "BM-Venv/bin/python" ]; then
    PYTHON="BM-Venv/bin/python"
else
    echo "❌ Brak venv. Najpierw: python3 -m venv .venv-preview && .venv-preview/bin/pip install -r requirements.txt"
    exit 1
fi

UVICORN_PID=""

cleanup() {
    # Idempotentny — guard przed dwukrotnym uruchomieniem (EXIT+INT mogą oba odpalić)
    [ -n "$CLEANUP_DONE" ] && return
    CLEANUP_DONE=1

    # Zabij uvicorn jeśli jeszcze żyje
    if [ -n "$UVICORN_PID" ] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        kill -TERM "$UVICORN_PID" 2>/dev/null
        wait "$UVICORN_PID" 2>/dev/null
    fi

    echo ""
    echo "[DEMO] Sprzątam — przywracam prawdziwe dane…"

    # Restore locations.local.js
    if [ -f "$LOCATIONS_BACKUP" ]; then
        mv "$LOCATIONS_BACKUP" "$LOCATIONS_OVERRIDE_FILE"
        echo "[DEMO] ✅ Przywrócono $LOCATIONS_OVERRIDE_FILE"
    fi

    # Restore data/
    if [ -d "$REAL_DATA_BACKUP" ]; then
        rm -rf data
        mv "$REAL_DATA_BACKUP" data
        echo "[DEMO] ✅ Przywrócono prawdziwe data/"
    fi
    echo "[DEMO] Tryb demo zakończony."
}

# Trap on INT/TERM przekieruje sygnał na cleanup, EXIT łapie wszystkie ścieżki wyjścia.
trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

# Sanity check: czy nie jesteśmy już w trybie demo?
if [ -d "$REAL_DATA_BACKUP" ] || [ -f "$LOCATIONS_BACKUP" ]; then
    echo "❌ Backup z poprzedniej sesji demo istnieje — być może coś poszło źle wcześniej."
    [ -d "$REAL_DATA_BACKUP" ] && echo "   $REAL_DATA_BACKUP/ istnieje"
    [ -f "$LOCATIONS_BACKUP" ] && echo "   $LOCATIONS_BACKUP istnieje"
    echo "   Sprawdź ręcznie i przywróć właściwe pliki, potem usuń backupy."
    exit 1
fi

echo "========================================================"
echo "  Booking Manager — TRYB DEMO"
echo "  http://localhost:$PORT"
echo "  Login: admin / demo123"
echo "  Ctrl+C zatrzymuje i przywraca prawdziwe dane"
echo "========================================================"

# 1. Backup prawdziwego data/
if [ -d "data" ]; then
    mv data "$REAL_DATA_BACKUP"
    echo "[DEMO] Backup data/ → $REAL_DATA_BACKUP/"
fi

# 2. Skopiuj demo data
mkdir -p data
cp -r "$DEMO_DATA"/* data/
chmod 600 data/users.json 2>/dev/null || true
echo "[DEMO] Skopiowano demo/data/ → data/"

# 3. Schowaj locations.local.js — bez niego app fallback'uje do fictional names z index.html
if [ -f "$LOCATIONS_OVERRIDE_FILE" ]; then
    mv "$LOCATIONS_OVERRIDE_FILE" "$LOCATIONS_BACKUP"
    echo "[DEMO] Schowano $LOCATIONS_OVERRIDE_FILE → $LOCATIONS_BACKUP"
fi

# 4. Start serwer w tle, `wait` w foreground — kluczowe dla działania trapów.
# Gdy bash dostaje SIGINT/SIGTERM, `wait` jest przerywany i odpala się trap.
# Z `exec` lub bez `&` shell blokowałby się w foreground command i trap nie zadziałał.
$PYTHON -m uvicorn app:app --host 127.0.0.1 --port "$PORT" &
UVICORN_PID=$!
wait "$UVICORN_PID"
