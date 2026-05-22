# HospesAI

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

# Activate git hooks (prevents accidental commits with personal data)
./tools/setup-hooks.sh

# Create the first admin user (creates data/users.json with bcrypt hash, chmod 600)
./users add admin "your-password" --role admin

# Start the server
./start.sh
# → http://localhost:8000
```

### Git hooks (preventative leak protection)

This repo uses `.githooks/` (committed) instead of default `.git/hooks/`. After running `./tools/setup-hooks.sh`:

- **commit-msg** — scans commit message body; blocks commit if it detects
  location names, company names from `data/bookings.json`, the production server IP, or
  historical plaintext passwords
- **pre-commit** — runs `demo/patch_locations.py check` + scans the staged diff

Patterns are sourced from gitignored `static/locations.local.js` and `data/bookings.json` —
ZERO configuration if you already have prod data. Fresh clone without these files = hooks
fall back to a hardcoded list (IP, passwords).

Bypass at your own risk: `git commit --no-verify`.

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

### Demo mode (try without setup)
```bash
./demo/start.sh
# → http://localhost:8003  (admin / demo123)
# Ctrl+C restores your real data
```
Loads fictional locations, ~12 sample bookings (individual / company / permanent tenant / recurring series / mixed billing modes / custom price overrides), notes, media bills and prices. Production `data/` is moved aside and restored on exit. See [`demo/README.md`](demo/README.md).

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
├── demo/                   # Fictional dataset + screenshot runner
│   ├── data/               # Fake bookings, users, prices, etc.
│   ├── patch_locations.py  # Swaps real building names for fictional ones
│   └── start.sh            # Orchestrator: swap in → run → restore on exit
└── data/                   # gitignored — bookings, invoices, users.json, backups
```

---

## Lessons learned

Things I'd do differently with hindsight (or that took me a while to figure out):

- **Pick the boring storage layer last, not first.** I almost reached for SQLite + SQLAlchemy on day 1 out of habit. For a single-tenant 2MB dataset, the JSON-on-disk approach turned out to be faster to build, easier to back up (just `cp -r`), and trivial to inspect during debugging. Schema "migrations" become a `python3 -c "for b in bookings: b.setdefault(...)"` script. The cost: no concurrent writes (single FastAPI worker), no joins, no indexes. At this scale, those costs are zero.

- **State + render() beat me trying to be clever.** Early commits had per-component event handlers and direct DOM manipulation. It became unmaintainable around the 2000-line mark. Switching to `state = {...}; render()` (single function returning a fresh HTML string, set as `innerHTML`) made the whole frontend dramatically easier to reason about. The "performance hit" of full re-rendering is invisible on a 126-room dataset.

- **Backups need to be out-of-band.** The first backup design was a cron job inside the same VPS — perfectly worthless if the VPS dies. Adding a launchd job on my Mac that pulls both production and staging via rsync took 30 minutes and is the single most important reliability feature in the project. (Bonus pain point: macOS TCC blocks launchd from accessing `~/Documents/`. Spent an evening on this before moving the script to `~/Library/Scripts/`.)

- **Plaintext passwords in source were a mistake.** Original version had a hardcoded `_LEGACY_USERS` dict for convenience during early dev. By the time I noticed how much surface area that created, I had to migrate to bcrypt hashes in a separate chmod-600 file. Now there's a CLI (`./users add admin "pw" --role admin`) and the application code has no idea what any password is.

- **Per-bed availability should have been there from day one.** I shipped per-room availability first ("the room is booked or it isn't"), got bookings into prod, then discovered the business actually needs to put two unrelated guests in the same 4-bed room. Retrofitting the bed accounting through `bedsUsedByBooking` / `getFreeBeds` / `getRoomOccupants` was painful because every booking screen needed updating. Lesson: ask "what's the granularity of the resource?" before designing the model.

- **The icon migration was worth it.** Replacing every emoji with a Lucide-style inline SVG felt like busywork. The result: consistent rendering across OS/browser, light/dark mode aware (`currentColor`), per-call sizing, no font dependencies. The `ICONS` object is now ~50 small functions; total cost ~2KB gzipped.

---

## Trade-offs

The conscious technical decisions and what each one cost:

| Decision | Got | Gave up |
|---|---|---|
| JSON files vs SQL DB | Trivial backups, atomic writes (tempfile+rename), zero schema management, dataset readable in any editor | No concurrent writes, no joins or indexes, hard upper bound (~10MB before noticeable I/O cost) |
| Single-page no-framework JS | Zero build step, instant page loads, easy to deploy (one static file), no dependency churn | No type checking (it's vanilla JS), no component library, manual reactivity, long single file |
| HTTP Basic + bcrypt | Stateless (no sessions to manage), works behind any reverse proxy, browser handles the login UI | No "remember me", no password reset flow, no MFA, slightly worse UX than custom form |
| FastAPI single worker | Simplest possible deploy (one systemd service), no inter-worker state coordination needed | Can't scale horizontally; one slow request blocks the next. Fine at this dataset size |
| Polish UI + mixed PL/EN comments | Production users get native language; comments capture domain terminology accurately ("stały najemca" has no clean English equivalent) | Less approachable for international contributors. (For this project, that's not a real concern.) |
| Hardcoded location data in `index.html` | Frontend renders zero-latency on first paint, no extra API call to fetch the room graph | Changing rooms requires a code edit + deploy. Acceptable since the property portfolio changes maybe twice a year. |
| Manual `render()` instead of a framework | Predictable, debuggable with `console.log(state)`, no library updates breaking the app | I had to write helpers (debounced events, sticky scroll restore, focus management) that React/Vue give for free |

---

## Roadmap

**Next up:**
- **SMS module** — booking confirmations to guests via Twilio/SMSAPI, with templates per booking type
- **Invoice PDF generation** — currently invoices are uploaded; auto-generate from booking data

**Considered and rejected (for now):**
- **Multi-tenant SaaS version** — would require ripping out the JSON storage and adding proper auth/billing/per-tenant isolation. Not worth the rewrite cost when there's one user.
- **React/Vue rewrite** — would buy ergonomics but cost the zero-build-step property that makes deployment trivial. Maybe at 10k+ lines, not yet.
- **Mobile app** — the responsive web works on phones well enough. Native app is months of work for marginal UX gain.
- **Real-time multi-user collaboration** — current model is "one operator at a time" and that matches how the business actually runs. WebSocket-based live updates would be a fun feature but solve a problem nobody has.

---

## Status

Used in production by a real business across 9 properties / 126 rooms since 2025.

---

## License

MIT — see [LICENSE](LICENSE).
