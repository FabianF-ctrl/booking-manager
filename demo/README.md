# Demo data fixture

Fake dataset for screenshots and portfolio demos. **None of this is real production data** — locations, guests, companies and prices are all fictional.

## What's here

```
demo/
├── data/                  # Fake JSON fixtures (drop-in replacement for data/)
│   ├── bookings.json      # ~12 sample bookings exercising all features
│   ├── users.json         # admin / demo123 (bcrypt hashed)
│   ├── prices.json        # Realistic price list
│   ├── room_media.json    # Sample electricity/gas/water bills
│   ├── notes.json         # Booking-scoped and general notes
│   └── invoices_meta.json # (empty)
├── patch_locations.py     # Swaps real building names with fictional ones in static/index.html
├── start.sh               # One-shot orchestrator (backup → swap → run → restore on exit)
└── README.md              # This file
```

## What the bookings exercise

- **B01** — current individual booking with partial `actualDays`
- **B02** — current company multi-employee, billed per-worker
- **B03** — future individual booking, cash prepaid
- **B04** — past individual booking, completed
- **B05** — open-ended **permanent tenant**
- **B06 (×4)** — **recurring weekly series** (4 bookings, shared group ID)
- **B07** — booking with **custom price** override
- **B08** — company booking with **mixed billing modes** (per-room + per-employee + custom rates)
- **B09** — future company booking

## How to use

```bash
./demo/start.sh
# → http://localhost:8003  (login: admin / demo123)
# Ctrl+C to stop and restore real data
```

The script:
1. Moves your real `data/` aside to `data.real-backup/`
2. Copies `demo/data/*` into `data/`
3. Patches building names in `static/index.html` (backup in `demo/.index.html.real`)
4. Starts uvicorn on port 8003
5. On `Ctrl+C` — restores everything

If something goes wrong mid-flight, the cleanup trap still fires on EXIT, so your real data is safe.

## Manual patching (without start.sh)

```bash
# Patch index.html with fictional building names
python3 demo/patch_locations.py patch

# Restore real names
python3 demo/patch_locations.py restore
```
