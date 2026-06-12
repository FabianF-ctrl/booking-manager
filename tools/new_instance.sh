#!/usr/bin/env bash
# ============================================================
# new_instance.sh — stawia NOWĄ, CZYSTĄ instancję HospesAI
# dla kolejnej organizacji (model: osobna instancja per firma).
#
# Uruchamiać NA SERWERZE jako root:
#   bash tools/new_instance.sh <slug> <port> [admin_login]
#   np.: bash tools/new_instance.sh firmaX 8004
#
# Co robi:
#   1. Kopiuje KOD z instancji produkcyjnej (bez danych, bez venv,
#      bez plików prywatnych naszej firmy — patrz EXCLUDES).
#   2. Tworzy świeży venv + instaluje zależności.
#   3. Tworzy puste data/ + konto admina (hasło generowane, podane raz).
#   4. Rejestruje i startuje serwis systemd hospes-<slug> na 127.0.0.1:<port>.
#   5. Wypisuje kroki ręczne: DNS + nginx + certbot (wymagają decyzji o domenie).
#
# Czego NIE robi (świadomie):
#   - NIE kopiuje data/ (rezerwacje, users, dziennik — każda firma ma własne),
#   - NIE kopiuje static/locations.local.js (NASZE prawdziwe obiekty!)
#     → nowa instancja startuje z fikcyjnymi lokalizacjami z index.html,
#       prawdziwe obiekty firmy wgrywa się potem do JEJ locations.local.js,
#   - NIE kopiuje tools/leak_patterns_local.txt (nasze wzorce sekretów),
#   - NIE tworzy data/integrations.json → integracja Rozliczeń wyłączona
#     (feature-flag z v3.79: zakładka znika, /api/costs puste).
# ============================================================
set -euo pipefail

SLUG="${1:-}"
PORT="${2:-}"
ADMIN_USER="${3:-admin}"

if [[ -z "$SLUG" || -z "$PORT" ]]; then
  echo "Użycie: bash tools/new_instance.sh <slug> <port> [admin_login]"; exit 1
fi
if ! [[ "$SLUG" =~ ^[a-z0-9-]+$ ]]; then
  echo "❌ Slug tylko [a-z0-9-] (małe litery, cyfry, myślnik): $SLUG"; exit 1
fi

SRC="/home/booking/booking-app"
DST="/home/booking/hospes-${SLUG}"
SVC="hospes-${SLUG}"

[[ -d "$DST" ]] && { echo "❌ Katalog $DST już istnieje — przerwij albo usuń ręcznie."; exit 1; }
if ss -tlnp | grep -q ":${PORT} "; then
  echo "❌ Port ${PORT} jest zajęty:"; ss -tlnp | grep ":${PORT} "; exit 1
fi

echo "── [1/5] Kopiuję kod ${SRC} → ${DST} (bez danych i plików prywatnych)"
rsync -a \
  --exclude='data' \
  --exclude='venv' --exclude='BM-Venv' --exclude='.venv-preview' \
  --exclude='__pycache__' \
  --exclude='static/locations.local.js' \
  --exclude='tools/leak_patterns_local.txt' \
  --exclude='demo' \
  --exclude='.claude' --exclude='.git' \
  "${SRC}/" "${DST}/"

echo "── [2/5] Świeży venv + zależności (chwilę potrwa)"
python3 -m venv "${DST}/venv"
"${DST}/venv/bin/pip" install --quiet --upgrade pip
"${DST}/venv/bin/pip" install --quiet -r "${DST}/requirements.txt"

echo "── [3/5] Puste data/ + konto admina"
mkdir -p "${DST}/data"
ADMIN_PASS=$("${DST}/venv/bin/python" - << 'PYEOF'
import secrets
words = ['Klucz','Panel','Domek','Pokoj','Lokal','Gosc','Sezon','Kwatera','Meldunek','Nocleg']
w1 = secrets.choice(words); w2 = secrets.choice([w for w in words if w != w1])
print(f"{w1}{w2}{secrets.randbelow(900)+100}{secrets.choice(['#','@','%','?'])}")
PYEOF
)
"${DST}/venv/bin/python" "${DST}/manage_users.py" add "${ADMIN_USER}" "${ADMIN_PASS}" --role admin
chown -R booking:booking "${DST}"

echo "── [4/5] Serwis systemd ${SVC} (127.0.0.1:${PORT})"
cat > "/etc/systemd/system/${SVC}.service" << UNITEOF
[Unit]
Description=HospesAI instance: ${SLUG}
After=network.target

[Service]
User=booking
WorkingDirectory=${DST}
ExecStart=${DST}/venv/bin/uvicorn app:app --host 127.0.0.1 --port ${PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
systemctl enable --now "${SVC}"
sleep 2

echo "── [5/5] Smoke test"
HTTP=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/")
ME=$(curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" "http://127.0.0.1:${PORT}/api/me")
echo "   / → HTTP ${HTTP} (oczek. 200)"
echo "   /api/me → ${ME}"
echo "$ME" | grep -qE '"rozliczenia": ?false' && echo "   ✅ integracja Rozliczeń WYŁĄCZONA (jak ma być)" \
  || echo "   ⚠️ SPRAWDŹ flagę rozliczenia w /api/me!"

# Podpowiedź nginx na później (gdy będzie domena + DNS)
NGINX_HINT="/root/${SVC}.nginx.suggested"
cat > "${NGINX_HINT}" << NGINXEOF
# Sugerowany server block dla ${SVC} — wymaga najpierw rekordu DNS
# (A: <subdomena> → IP tego serwera), potem:
#   1. zapisz ten plik jako /etc/nginx/sites-available/${SVC} (z poprawioną domeną)
#   2. ln -s /etc/nginx/sites-available/${SVC} /etc/nginx/sites-enabled/
#   3. nginx -t && systemctl reload nginx
#   4. certbot --nginx -d <subdomena>   (dopisze HTTPS)
server {
    listen 80;
    server_name PODMIEN.NA.DOMENE;
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        client_max_body_size 25m;
    }
}
NGINXEOF

echo ""
echo "════════════════════════════════════════════════════════"
echo "✅ Instancja ${SLUG} działa na 127.0.0.1:${PORT}"
echo "   Serwis:   systemctl status ${SVC}"
echo "   Katalog:  ${DST}"
echo "   Login:    ${ADMIN_USER} / ${ADMIN_PASS}   ← ZAPISZ, nie pokaże się drugi raz"
echo ""
echo "   DALSZE KROKI (ręczne, gdy znana domena):"
echo "   1. DNS: rekord A <subdomena> → IP serwera"
echo "   2. nginx: szablon w ${NGINX_HINT}"
echo "   3. certbot --nginx -d <subdomena>"
echo "   4. Prawdziwe obiekty firmy → ${DST}/static/locations.local.js"
echo "      (format: patrz static/locations.local.js.example w repo, jeśli jest,"
echo "       albo struktura DATA.locations w static/index.html)"
echo "════════════════════════════════════════════════════════"
