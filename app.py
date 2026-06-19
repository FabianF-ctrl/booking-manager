from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import json
import os
import re
import shutil
import secrets
import urllib.request
import bcrypt
from datetime import datetime, date, timedelta
from typing import Optional
from pathlib import Path

# ============================================================
# AUTOMATYCZNE DZIENNE BACKUPY
# ============================================================

from backup_scheduler import start_backup_scheduler
start_backup_scheduler()   # startuje w tle, nie blokuje serwera

# ============================================================
# KONFIGURACJA
# ============================================================

app = FastAPI(title="HospesAI API")
security = HTTPBasic()

# Ścieżki
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
INVOICES_DIR        = DATA_DIR / "invoices"
INVOICES_BACKUP_DIR = DATA_DIR / "invoices_backup"   # nieusuwalne kopie
BACKUPS_DIR         = DATA_DIR / "backups"
STATIC_DIR          = BASE_DIR / "static"
BOOKINGS_FILE       = DATA_DIR / "bookings.json"

# Upewnij się że foldery istnieją
for d in [DATA_DIR, INVOICES_DIR, INVOICES_BACKUP_DIR, BACKUPS_DIR, STATIC_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# UŻYTKOWNICY I ROLE
# admin  — pełny dostęp (kasowanie historycznych danych itd.)
# worker — dodawanie i edycja bieżących rezerwacji, brak kasowania
#
# Hasła: bcrypt hash w pliku data/users.json (chmod 600).
# Zarządzanie przez skrypt `manage_users.py` (CLI wrapper: `./users`).
#
# Pierwszy setup (po klonowaniu repo):
#   ./users add admin "twoje-haslo" --role admin
# ============================================================

USERS_FILE = Path(__file__).parent / "data" / "users.json"

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def load_users() -> dict:
    """Wczytaj userów z users.json. Jeśli plik nie istnieje — wypisz instrukcje i zwróć pusty dict."""
    if not USERS_FILE.exists():
        print("=" * 60)
        print(f"[USERS] Brak pliku {USERS_FILE}")
        print("[USERS] Utwórz pierwszego admina komendą:")
        print("[USERS]   ./users add admin \"twoje-haslo\" --role admin")
        print("=" * 60)
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(users: dict):
    """Zapisz users.json z restricted permissions."""
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    try:
        USERS_FILE.chmod(0o600)
    except Exception:
        pass

# Wczytaj userów raz przy starcie (cache w pamięci, reload przy zmianach przez manage_users.py)
_USERS_CACHE = load_users()

def get_current_user(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    # Reload z pliku jeśli mtime się zmienił (żeby manage_users.py zadziałał bez restartu)
    global _USERS_CACHE
    try:
        _USERS_CACHE = load_users()
    except Exception:
        pass  # zostaw stary cache
    user = _USERS_CACHE.get(credentials.username)
    ok = bool(user) and _verify_password(credentials.password, user["hash"])
    if not ok:
        # Nieudane próby logujemy tylko dla /api/me (ekran logowania) — bez spamu
        # z każdego requestu, gdy komuś wygasły zapisane dane. Hasła NIE logujemy.
        if request.url.path == "/api/me":
            audit_log({"username": credentials.username, "ip": _client_ip(request)},
                      "login_failed", "Nieudana próba logowania")
        raise HTTPException(status_code=401, detail="Nieprawidłowy użytkownik lub hasło")
    return {"username": credentials.username, "role": user["role"], "ip": _client_ip(request)}

def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Brak uprawnień — wymagany admin")
    return user

# ── Role ──────────────────────────────────────────────
# admin         — wszystko (w tym Dziennik)
# manager       — edytuje i kasuje wszystko + Dziennik (wiktoria.biuro; Dziennik od v3.80)
# viewer        — widzi wszystko (z Dziennikiem), niczego nie zmienia (szef)
# worker        — noclegi + media/faktury, zmiany max 7 dni wstecz (agata)
# worker_senior — jak worker, ale BEZ limitu 7 dni (dowolna data wstecz) (julia; v3.82)
# worker_basic  — noclegi bez mediów/faktur (ukryte), zmiany max 7 dni wstecz (ihor)

EDIT_BACKLIMIT_DAYS = 7

def _require_edit(user):
    """Viewer = konto tylko do odczytu — blokuje każdą mutację."""
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Konto tylko do odczytu — bez możliwości zmian")

def _backdate_limit_iso() -> str:
    return (date.today() - timedelta(days=EDIT_BACKLIMIT_DAYS)).isoformat()

def require_manager_up(user=Depends(get_current_user)):
    """Operacje 'twarde' (kasowanie, zdjęcia, backup): admin lub manager."""
    if user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Brak uprawnień — wymagany admin lub menadżer")
    return user

def require_audit_access(user=Depends(get_current_user)):
    """Dziennik zdarzeń: admin + manager (wiktoria.biuro, od 17.06) + viewer (szef). Tylko worker/worker_basic bez."""
    if user["role"] not in ("admin", "manager", "viewer"):
        raise HTTPException(status_code=403, detail="Brak uprawnień do dziennika zdarzeń")
    return user

# ============================================================
# DZIENNIK ZDARZEŃ (AUDIT LOG)
# Kto się zalogował, kiedy i co zmienił. Append-only JSONL w
# data/audit/audit-RRRR-MM.jsonl (rotacja miesięczna, poza repo).
# Zapis nigdy nie blokuje właściwej operacji.
# ============================================================

AUDIT_DIR = DATA_DIR / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# Czas polski niezależnie od strefy serwera (Hetzner chodzi na UTC — bez tego
# dziennik pokazywałby godziny przesunięte o 1-2h względem zegara użytkowników).
try:
    from zoneinfo import ZoneInfo
    _AUDIT_TZ = ZoneInfo("Europe/Warsaw")
except Exception:
    _AUDIT_TZ = None

def _audit_now():
    return datetime.now(_AUDIT_TZ) if _AUDIT_TZ else datetime.now()

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""

def audit_log(user, event: str, label: str):
    """user = dict z get_current_user (username + ip) albo string username."""
    try:
        now = _audit_now()
        entry = {
            "ts": now.isoformat(timespec="seconds"),
            "user": user.get("username") if isinstance(user, dict) else str(user),
            "event": event,   # login | login_failed | booking_* | invoice_* | media_update | ...
            "label": label,
        }
        if isinstance(user, dict) and user.get("ip"):
            entry["ip"] = user["ip"]
        fp = AUDIT_DIR / f"audit-{now.strftime('%Y-%m')}.jsonl"
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _booking_label(b: dict) -> str:
    if b.get("outOfService"):
        who = f"wyłączenie pokoju ({b.get('osReason', 'inne')})"
    elif b.get("bookingType") == "company" and b.get("companyName"):
        who = b["companyName"]
    else:
        names = [g.get("name", "") for g in (b.get("guests") or []) if g.get("name")]
        who = ", ".join(names) or "—"
    if b.get("isPermanent"):
        rng = f"od {b.get('permanentStart') or b.get('from', '?')} (stały najemca)"
    else:
        rng = f"{b.get('from', '?')} → {b.get('to', '?')}"
    return f"{who} · obiekt {b.get('locId', '?')}, pokój {b.get('roomId', '?')} · {rng}"

@app.get("/api/audit")
def get_audit(limit: int = 500, user=Depends(require_audit_access)):
    """Dziennik zdarzeń (tylko admin) — najnowsze wpisy z 3 ostatnich miesięcy."""
    entries = []
    for fp in sorted(AUDIT_DIR.glob("audit-*.jsonl"), reverse=True)[:3]:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return entries[:max(1, min(int(limit), 2000))]

# ============================================================
# HELPERS — zapis / odczyt bookings.json
# ============================================================

def load_bookings() -> list:
    if not BOOKINGS_FILE.exists():
        return []
    with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_bookings(bookings: list):
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)

def make_backup():
    """Tworzy kopię zapasową bookings.json z datą i godziną w nazwie."""
    if not BOOKINGS_FILE.exists():
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = BACKUPS_DIR / f"bookings_{ts}.json"
    shutil.copy2(BOOKINGS_FILE, backup_path)
    # Zostawiamy maksymalnie 90 ostatnich backupów zmianowych
    all_backups = sorted(BACKUPS_DIR.glob("bookings_*.json"))
    for old in all_backups[:-90]:
        old.unlink()

# ============================================================
# CORS — pozwala HTML gadać z API (lokalnie i na serwerze)
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # na produkcji zamień na konkretną domenę
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# STATYCZNE PLIKI — serwuje index.html i resztę
# ============================================================

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/invoices", StaticFiles(directory=str(INVOICES_DIR)), name="invoices")

@app.get("/")
def root():
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )

# ============================================================
# API — REZERWACJE
# ============================================================

@app.get("/api/bookings")
def get_bookings(user=Depends(get_current_user)):
    """Zwraca wszystkie rezerwacje."""
    return load_bookings()

@app.post("/api/bookings")
def create_booking(booking: dict, user=Depends(get_current_user)):
    """Dodaje nową rezerwację."""
    _require_edit(user)
    # v3.89 — stały najemca jest wyjęty spod limitu 7 dni (legalne wsteczne ustalenie daty "od kiedy" mieszka).
    if user["role"] in ("worker", "worker_basic") and not booking.get("isPermanent") and (booking.get("from") or "") < _backdate_limit_iso():
        raise HTTPException(status_code=403, detail=f"Pracownik nie może dodawać rezerwacji starszych niż {EDIT_BACKLIMIT_DAYS} dni wstecz")
    # v3.92 — firmówka z przypisaniem pracowników ale bez roomId → wywnioskuj pokój z assignedRoom
    # (naprawia bug roomId=null → calcBookingTotal: if(!room) return 0 → Przychód 0 mimo wpłaty).
    if booking.get("bookingType") == "company" and not booking.get("roomId"):
        ar = next((g.get("assignedRoom") for g in (booking.get("guests") or []) if g.get("assignedRoom")), None)
        if ar:
            booking["roomId"] = ar
    bookings = load_bookings()
    if not booking.get("id"):
        booking["id"] = f"sb{int(datetime.now().timestamp()*1000)}"
    booking["createdBy"] = user["username"]
    booking["createdAt"] = datetime.now().isoformat()
    bookings.append(booking)
    make_backup()
    save_bookings(bookings)
    audit_log(user, "booking_create", f"Nowa rezerwacja: {_booking_label(booking)}")
    return booking

@app.put("/api/bookings/{booking_id}")
def update_booking(booking_id: str, updated: dict, user=Depends(get_current_user)):
    """Edytuje rezerwację. Pracownik nie może edytować rezerwacji z poprzednich miesięcy."""
    bookings = load_bookings()
    idx = next((i for i, b in enumerate(bookings) if b["id"] == booking_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Rezerwacja nie znaleziona")

    booking = bookings[idx]

    _require_edit(user)
    # v3.78 — pracownicy: zmiany max 7 dni wstecz (zastępuje stary limit miesięczny)
    # v3.89 — stały najemca wyjęty spod limitu 7 dni (wsteczne ustalenie/edycja daty "od kiedy").
    is_permanent_booking = bool(booking.get("isPermanent")) or bool(updated.get("isPermanent"))
    if user["role"] in ("worker", "worker_basic") and not is_permanent_booking:
        if booking.get("from", "") < _backdate_limit_iso() or (updated.get("from") or "9999") < _backdate_limit_iso():
            raise HTTPException(
                status_code=403,
                detail=f"Pracownik nie może zmieniać rezerwacji starszych niż {EDIT_BACKLIMIT_DAYS} dni wstecz"
            )

    updated["id"] = booking_id
    updated["updatedBy"] = user["username"]
    updated["updatedAt"] = datetime.now().isoformat()
    bookings[idx] = updated
    make_backup()
    save_bookings(bookings)
    audit_log(user, "booking_update", f"Edycja rezerwacji: {_booking_label(updated)}")
    return updated

@app.delete("/api/bookings/{booking_id}")
def delete_booking(booking_id: str, user=Depends(require_manager_up)):
    """Kasuje rezerwację — admin lub menadżer."""
    bookings = load_bookings()
    removed = next((b for b in bookings if b["id"] == booking_id), None)
    new_bookings = [b for b in bookings if b["id"] != booking_id]
    if len(new_bookings) == len(bookings):
        raise HTTPException(status_code=404, detail="Rezerwacja nie znaleziona")
    make_backup()
    save_bookings(new_bookings)
    audit_log(user, "booking_delete", f"Usunięta rezerwacja: {_booking_label(removed or {})}")
    return {"deleted": booking_id}

# ============================================================
# API — FAKTURY
# ============================================================

INVOICES_META_FILE = DATA_DIR / "invoices_meta.json"

def load_invoices_meta() -> list:
    if not INVOICES_META_FILE.exists():
        return []
    with open(INVOICES_META_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_invoices_meta(invoices: list):
    with open(INVOICES_META_FILE, "w", encoding="utf-8") as f:
        json.dump(invoices, f, ensure_ascii=False, indent=2)

@app.get("/api/invoices")
def get_invoices(user=Depends(get_current_user)):
    if user["role"] == "worker_basic":
        return []   # v3.78 — ihor: faktury ukryte
    return load_invoices_meta()

@app.post("/api/invoices")
async def upload_invoice(
    file: Optional[UploadFile] = File(None),
    loc_id: Optional[str] = Form(None),
    room_id: Optional[str] = Form(None),
    period: Optional[str] = Form(None),
    amount: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    user=Depends(get_current_user)
):
    """Uploaduje fakturę i zapisuje jej metadane."""
    _require_edit(user)
    if user["role"] == "worker_basic":
        raise HTTPException(status_code=403, detail="Brak dostępu do faktur")
    file_url = None
    filename = None

    if file and file.filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean = "".join(c if c.isalnum() or c in ".-_" else "_" for c in file.filename)
        safe_name = f"{ts}_{clean}"
        dest = INVOICES_DIR / safe_name
        with open(dest, "wb") as out:
            content = await file.read()
            out.write(content)
        # Kopia zapasowa — nigdy nie jest usuwana przez endpoint /delete
        shutil.copy2(dest, INVOICES_BACKUP_DIR / safe_name)
        file_url = f"/invoices/{safe_name}"
        filename = file.filename

    invoices = load_invoices_meta()
    inv_id = f"inv{int(datetime.now().timestamp()*1000)}"
    entry = {
        "id": inv_id,
        "filename": filename or f"Faktura {period or ''}",
        "url": file_url,
        "locId": int(loc_id) if loc_id else None,
        "roomId": room_id or None,
        "period": period or "",
        "amount": amount or "",
        "note": note or "",
        "date": date.today().isoformat(),
        "uploadedBy": user["username"],
    }
    invoices.append(entry)
    save_invoices_meta(invoices)
    audit_log(user, "invoice_add",
              f"Faktura dodana: {entry['filename']} · obiekt {loc_id or '—'} · okres {period or '—'}" + (f" · {amount} zł" if amount else ""))
    return entry

@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: str, user=Depends(require_manager_up)):
    """Kasuje fakturę — admin lub menadżer."""
    invoices = load_invoices_meta()
    inv = next((i for i in invoices if i["id"] == invoice_id), None)
    if not inv:
        raise HTTPException(status_code=404, detail="Faktura nie znaleziona")
    if inv.get("url"):
        file_path = BASE_DIR / inv["url"].lstrip("/")
        if file_path.exists():
            file_path.unlink()
    new_invoices = [i for i in invoices if i["id"] != invoice_id]
    save_invoices_meta(new_invoices)
    audit_log(user, "invoice_delete", f"Faktura usunięta: {inv.get('filename', invoice_id)} · okres {inv.get('period') or '—'}")
    return {"deleted": invoice_id}

# ============================================================
# API — CENY POKOI
# ============================================================

PRICES_FILE = DATA_DIR / "prices.json"

def load_prices() -> dict:
    if not PRICES_FILE.exists():
        return {}
    with open(PRICES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_prices(prices: dict):
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(prices, f, ensure_ascii=False, indent=2)

@app.get("/api/prices")
def get_prices(user=Depends(get_current_user)):
    """Zwraca zapisane ceny wszystkich pokoi."""
    return load_prices()

@app.post("/api/prices")
def update_prices(prices: dict, user=Depends(get_current_user)):
    """Zapisuje ceny pokoi. Dostępne dla zalogowanych (oprócz konta podgląd)."""
    _require_edit(user)
    save_prices(prices)
    audit_log(user, "prices_update", f"Cennik zapisany ({len(prices)} pokoi)")
    return {"status": "ok", "rooms": len(prices)}

# ============================================================
# API — MEDIA (koszty prądu, wody, napraw)
# ============================================================

MEDIA_FILE = DATA_DIR / "room_media.json"

def load_media() -> dict:
    if not MEDIA_FILE.exists():
        return {}
    with open(MEDIA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_media(media: dict):
    with open(MEDIA_FILE, "w", encoding="utf-8") as f:
        json.dump(media, f, ensure_ascii=False, indent=2)

@app.get("/api/media")
def get_media(user=Depends(get_current_user)):
    if user["role"] == "worker_basic":
        return {}   # v3.78 — ihor: media ukryte
    return load_media()

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")  # RRRR-MM, miesiąc 01–12

@app.put("/api/media/{room_id}/{period}")
def save_room_media(room_id: str, period: str, data: dict, user=Depends(get_current_user)):
    # v3.41 — walidacja okresu po stronie serwera (drugi bezpiecznik obok frontu).
    # Bez tego dowolny string trafiał jako klucz i psuł filtrowanie w raportach.
    if not _PERIOD_RE.match(period or ""):
        raise HTTPException(status_code=400, detail="Okres musi mieć format RRRR-MM (miesiąc 01–12)")
    _require_edit(user)
    if user["role"] == "worker_basic":
        raise HTTPException(status_code=403, detail="Brak dostępu do mediów")
    if user["role"] == "worker":
        # v3.78 — zmiany max 7 dni wstecz: okres zamknięty >7 dni temu jest zablokowany
        y, m = period.split("-")
        nxt = date(int(y) + (1 if m == "12" else 0), 1 if m == "12" else int(m) + 1, 1)
        period_end = nxt - timedelta(days=1)
        if (date.today() - period_end).days > EDIT_BACKLIMIT_DAYS:
            raise HTTPException(status_code=403, detail=f"Pracownik nie może zmieniać mediów okresów zamkniętych ponad {EDIT_BACKLIMIT_DAYS} dni temu")
    media = load_media()
    key = f"{room_id}__{period}"
    media[key] = data
    save_media(media)
    audit_log(user, "media_update", f"Media zapisane: obiekt/pokój {room_id} · okres {period}")
    return data

# ============================================================
# API — INTEGRACJA: KOSZTY ZAKUPÓW Z MODUŁU ROZLICZENIA
# Token + base_url w data/integrations.json — gitignored, wykluczone z rsync
# (żyje wyłącznie na serwerze, NIGDY w repo). Brak configu / upstream down →
# pusto, raport finansowy działa wtedy bez sekcji kosztów.
# ============================================================

INTEGRATIONS_FILE = DATA_DIR / "integrations.json"

def load_integrations() -> dict:
    if not INTEGRATIONS_FILE.exists():
        return {}
    try:
        with open(INTEGRATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

@app.get("/api/costs")
def get_costs(from_: str = Query(..., alias="from"), to: str = Query(...),
              user=Depends(get_current_user)):
    """Proxy do API kosztów Rozliczeń. Zwraca
    {from, to, items:[{projectId, hospesLocId, name, netto, brutto, count}]}."""
    if not _PERIOD_RE.match(from_ or "") or not _PERIOD_RE.match(to or ""):
        raise HTTPException(status_code=400, detail="from/to muszą mieć format RRRR-MM")
    cfg = load_integrations().get("rozliczenia", {})
    token, base = cfg.get("token"), cfg.get("base_url")
    if not token or not base:
        return {"from": from_, "to": to, "items": [], "error": "not_configured"}
    url = f"{base.rstrip('/')}/api/v1/costs?from={from_}&to={to}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"from": from_, "to": to, "items": [], "error": f"upstream:{type(e).__name__}"}

# ============================================================
# API — ZDJĘCIA OBIEKTÓW
# ============================================================

LOC_IMAGES_DIR = DATA_DIR / "loc_images"
LOC_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/loc_images", StaticFiles(directory=str(LOC_IMAGES_DIR)), name="loc_images")

@app.get("/api/locations/images")
def list_location_images(user=Depends(get_current_user)):
    """Zwraca dict {locId: filename} dla wszystkich obiektów ze zdjęciami."""
    result = {}
    for f in LOC_IMAGES_DIR.iterdir():
        if f.is_file() and f.stem.isdigit():
            result[int(f.stem)] = f.name
    return result

@app.post("/api/locations/{loc_id}/image")
async def upload_location_image(
    loc_id: int,
    file: UploadFile = File(...),
    user=Depends(require_manager_up)
):
    """Uploaduje zdjęcie obiektu — admin lub menadżer.
    Plik zapisywany jako data/loc_images/{loc_id}.{ext}.
    Stare zdjęcie tego obiektu jest nadpisywane (usuwane przed zapisem)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(status_code=400, detail="Niedozwolony format (dozwolone: jpg, png, webp)")
    # Usuń stare zdjęcia tego obiektu (różne rozszerzenia)
    for old in LOC_IMAGES_DIR.glob(f"{loc_id}.*"):
        old.unlink()
    dest = LOC_IMAGES_DIR / f"{loc_id}.{ext}"
    with open(dest, "wb") as out:
        content = await file.read()
        out.write(content)
    audit_log(user, "image_upload", f"Zdjęcie obiektu {loc_id} wgrane ({dest.name})")
    return {"locId": loc_id, "filename": dest.name, "url": f"/loc_images/{dest.name}"}

@app.delete("/api/locations/{loc_id}/image")
def delete_location_image(loc_id: int, user=Depends(require_manager_up)):
    """Kasuje zdjęcie obiektu — admin lub menadżer."""
    deleted = False
    for f in LOC_IMAGES_DIR.glob(f"{loc_id}.*"):
        f.unlink()
        deleted = True
    if deleted:
        audit_log(user, "image_delete", f"Zdjęcie obiektu {loc_id} usunięte")
    return {"deleted": deleted, "locId": loc_id}

# ============================================================
# API — NOTATKI (per-rezerwacja oraz ogólne)
# ============================================================

NOTES_FILE = DATA_DIR / "notes.json"

def load_notes() -> list:
    if not NOTES_FILE.exists():
        return []
    with open(NOTES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_notes(notes: list):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

def backup_notes():
    """Backup pliku notes.json razem z bookings dla bezpieczeństwa."""
    if not NOTES_FILE.exists():
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    shutil.copy2(NOTES_FILE, BACKUPS_DIR / f"notes_{ts}.json")
    all_backups = sorted(BACKUPS_DIR.glob("notes_*.json"))
    for old in all_backups[:-90]:
        old.unlink()

@app.get("/api/notes")
def get_notes(user=Depends(get_current_user)):
    return load_notes()

@app.post("/api/notes")
def create_note(note: dict, user=Depends(get_current_user)):
    """
    Tworzy notatkę. Struktura:
      { type: "booking"|"general", bookingId?, roomId?, locId?, text }
    """
    _require_edit(user)
    notes = load_notes()
    note["id"] = f"nt{int(datetime.now().timestamp()*1000)}"
    note["createdBy"] = user["username"]
    note["createdAt"] = datetime.now().isoformat()
    if note.get("type") not in ("booking", "general"):
        raise HTTPException(status_code=400, detail="Nieprawidłowy typ notatki")
    if not note.get("text", "").strip():
        raise HTTPException(status_code=400, detail="Notatka nie może być pusta")
    notes.append(note)
    backup_notes()
    save_notes(notes)
    audit_log(user, "note_add", f"Notatka dodana: „{(note.get('text') or '')[:60]}{'…' if len(note.get('text') or '') > 60 else ''}”")
    return note

@app.put("/api/notes/{note_id}")
def update_note(note_id: str, updated: dict, user=Depends(get_current_user)):
    _require_edit(user)
    notes = load_notes()
    idx = next((i for i, n in enumerate(notes) if n["id"] == note_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Notatka nie znaleziona")
    notes[idx]["text"] = updated.get("text", notes[idx].get("text", ""))
    notes[idx]["updatedBy"] = user["username"]
    notes[idx]["updatedAt"] = datetime.now().isoformat()
    backup_notes()
    save_notes(notes)
    audit_log(user, "note_update", f"Notatka edytowana: „{(notes[idx].get('text') or '')[:60]}{'…' if len(notes[idx].get('text') or '') > 60 else ''}”")
    return notes[idx]

@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str, user=Depends(require_manager_up)):
    """Kasuje notatkę — admin lub menadżer. Backup robi się przed kasowaniem."""
    notes = load_notes()
    removed_note = next((n for n in notes if n["id"] == note_id), None)
    if not removed_note:
        raise HTTPException(status_code=404, detail="Notatka nie znaleziona")
    backup_notes()
    save_notes([n for n in notes if n["id"] != note_id])
    audit_log(user, "note_delete", f"Notatka usunięta: „{(removed_note.get('text') or '')[:60]}{'…' if len(removed_note.get('text') or '') > 60 else ''}”")
    return {"deleted": note_id}

# ============================================================
# API — INFO O ZALOGOWANYM UŻYTKOWNIKU
# ============================================================

@app.get("/api/me")
def get_me(user=Depends(get_current_user)):
    audit_log(user, "login", "Zalogowano")
    # v3.79 — feature-flagi per instancja: integracja Rozliczeń istnieje tylko tam,
    # gdzie data/integrations.json ją konfiguruje (= nasza instancja ABI Noclegi).
    # Instancje innych firm nie mają configa → zakładka znika, /api/costs i tak puste.
    features = {"rozliczenia": bool(load_integrations().get("rozliczenia", {}).get("token"))}
    return {"username": user["username"], "role": user["role"], "features": features}

# ============================================================
# API — RĘCZNY BACKUP
# ============================================================

@app.post("/api/backup")
def manual_backup(user=Depends(require_manager_up)):
    make_backup()
    audit_log(user, "backup_manual", "Backup ręczny rezerwacji")
    return {"status": "backup created", "time": datetime.now().isoformat()}

# ============================================================
# URUCHOMIENIE
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
