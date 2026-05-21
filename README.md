# Booking Manager

A self-hosted booking management web app for short-term rental businesses — built for managing **9 properties / 126 rooms** across multiple Polish cities, with per-bed availability, per-employee billing, permanent tenant tracking, invoicing, charts and an automated nightly backup pipeline.

[🇵🇱 Polski README](README.pl.md)

---

## Why this project

I built this for a family-run hostel business that was managing all 126 rooms in an Excel sheet. The goals were:

- **Make double-bookings impossible** — per-bed availability, not just per-room
- **Support mixed billing modes** — some companies pay per room, others per employee, with custom rates per worker
- **Handle "permanent tenants"** — open-ended bookings that bill to end-of-month automatically
- **Replace receipts in a shoebox** — invoice attachments + media bills (electricity, water, gas, internet) per room per period
- **Daily insights** — KPI dashboard with net profit, occupancy rate, revenue trends
- **Run on cheap hardware** — single FastAPI process on a small VPS, JSON file storage, no DB server

---

## Stack

- **Backend**: FastAPI (Python 3.11), Uvicorn, Pydantic
- **Auth**: HTTP Basic + bcrypt-hashed passwords (separate `data/users.json`, chmod 600), role-based (admin/worker)
- **Storage**: JSON files (intentional — small dataset, atomic writes, trivial backups)
- **Frontend**: Single-page vanilla JS/HTML/CSS (~5800 lines, zero build step), Lucide-style inline SVG icons
- **Deployment**: systemd services on Hetzner, HTTPS via Caddy, staging on port 8001
- **Backups**: 90 daily rolling backups (server cron + Mac launchd off-site copy)

No frameworks, no bundler, no DB server. The whole stack is designed to be readable and boring on purpose.

---

## Features

### Reservations
- Per-bed availability — multiple guests can occupy a multi-bed room independently
- Multi-room company bookings (one company, many rooms, expandable group in reports)
- Recurring series (weekly/monthly patterns with mass-cancel)
- Buffer days for cleaning between stays
- "Actual stay" calendar — distinguishes booked dates from actual occupancy days

### Billing
- **Per-room mode** — flat nightly rate from the room's pricelist
- **Per-employee mode** — each worker has their own daily rate
- **Mixed mode per booking** — some workers per-room, others per-employee
- **Per-worker price override** — manual `dailyRate` field beats the default
- **Permanent tenant model** — open-ended bookings auto-bill to end of current month (or `permanentEnd` date)

### Reports
- Hero KPI: net profit with month-over-month delta
- Drill-down: revenue → costs (media bills + cleaning) → net
- Media billing per room per period (electricity, water, gas, internet, other)
- Multi-room company grouping
- CSV export

### Other
- Notes system: booking-scoped or general, with edit history
- Location photo upload (JPG/PNG, served from `data/loc_images/`)
- Charts: revenue trend, location split (pie), occupancy heatmap
- Light/dark mode with adaptive favicon
- Polish UI (commercial product); codebase comments mixed PL/EN

---

## Architecture decisions worth noting

- **JSON over SQL** — the entire dataset fits in ~2MB. SQL would add operational burden (migrations, backups, schema versioning) for zero practical gain at this scale. Writes are atomic via tempfile + rename.
- **Single-page, no framework** — fewer moving parts, instant page loads, no build pipeline to break. The HTML file is ~330KB gzipped and renders the entire app.
- **State-based render()** — one global `state` object, one `render()` function that returns a fresh HTML string per change. No virtual DOM, no reactivity library — just template literals and `innerHTML`. Predictable, easy to debug.
- **bcrypt + separate file (chmod 600)** — migrated away from plaintext passwords in source. The file is excluded from backups-to-public-locations.
- **Inline SVG icon set** — Lucide-style icons defined as a single `ICONS` object in JS. No icon font, no separate sprite — each icon is a 5–10 line function. Color and size are passed at the call site.
- **Two-tier backups** — server-side daily cron (90 rotating copies on the VPS) plus an off-site Mac launchd job that pulls both production and staging. Solves the "single point of failure" problem cheaply.

---

## Setup

### Requirements
- Python 3.11+
- `pip install -r requirements.txt`

### First run
```bash
git clone https://github.com/<your-user>/booking-manager.git
cd booking-manager
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create the first admin user (creates data/users.json with bcrypt hash, chmod 600)
./users add admin "your-password" --role admin

# Start the server
./start.sh
# → http://localhost:8000
```

### Adding more users
```bash
./users list                                 # show all users
./users add worker1 "password" --role worker # add worker
./users passwd admin "new-password"          # change password
./users role worker1 admin                   # promote
./users delete worker2                       # remove
```

### Backups
Daily backups are made by `backup_scheduler.py` (started as a background thread by `app.py`). They go to `data/backups/daily/YYYY-MM-DD/` and keep the last 90 days. To trigger a manual backup: `python3 backup_scheduler.py`.

---

## Repo structure

```
.
├── app.py                  # FastAPI backend (~600 lines): auth, CRUD, file uploads
├── manage_users.py         # bcrypt user CLI
├── backup_scheduler.py     # nightly backup daemon
├── users                   # bash wrapper for manage_users.py
├── start.sh / start.bat    # platform launchers
├── requirements.txt
├── static/
│   ├── index.html          # The entire frontend (~5800 lines)
│   └── favicon.svg
└── data/                   # gitignored — bookings, invoices, users.json, backups
```

---

## Status

Used in production by a real business across 9 properties / 126 rooms since 2025. Active development continues — current roadmap includes an SMS module for booking confirmations.

---

## License

MIT — see [LICENSE](LICENSE).
