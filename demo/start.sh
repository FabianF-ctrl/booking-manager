#!/bin/bash
# demo/start.sh — uruchamia booking-manager w trybie demo (do screenshotów)
#
# Co robi:
#   1. Robi backup prawdziwego data/ → data.real-backup/
#   2. Kopiuje demo/data/* → data/
#   3. Patchuje nazwy obiektów w static/index.html (backup w demo/.index.html.real)
#   4. Odpala serwer na http://localhost:8003
#   5. Na Ctrl+C — przywraca prawdziwe data/ i prawdziwy index.html
#
# Po zatrzymaniu masz pewność że nic nie zostało zmienione w produkcyjnych danych.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REAL_DATA_BACKUP="data.real-backup"
DEMO_DATA="demo/data"
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

cleanup() {
    echo ""
    echo "[DEMO] Sprzątam — przywracam prawdziwe dane…"
    # Restore index.html
    $PYTHON demo/patch_locations.py restore 2>/dev/null || true
    # Restore data/
    if [ -d "$REAL_DATA_BACKUP" ]; then
        rm -rf data
        mv "$REAL_DATA_BACKUP" data
        echo "[DEMO] ✅ Przywrócono prawdziwe data/"
    fi
    echo "[DEMO] Tryb demo zakończony."
}
trap cleanup EXIT INT TERM

# Sanity check: czy nie jesteśmy już w trybie demo?
if [ -d "$REAL_DATA_BACKUP" ]; then
    echo "❌ Folder $REAL_DATA_BACKUP już istnieje — być może coś poszło źle wcześniej."
    echo "   Sprawdź ręcznie czy data/ to prawdziwe dane, czy demo, i usuń backup."
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

# 3. Patch index.html
$PYTHON demo/patch_locations.py patch
echo "[DEMO] Spatchowano nazwy obiektów w static/index.html"

# 4. Start serwer (foreground, Ctrl+C → cleanup)
exec $PYTHON -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
