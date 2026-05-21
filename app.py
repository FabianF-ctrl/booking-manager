from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import json
import os
import shutil
import secrets
import bcrypt
from datetime import datetime, date
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

def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    # Reload z pliku jeśli mtime się zmienił (żeby manage_users.py zadziałał bez restartu)
    global _USERS_CACHE
    try:
        _USERS_CACHE = load_users()
    except Exception:
        pass  # zostaw stary cache
    user = _USERS_CACHE.get(credentials.username)
    if not user:
        raise HTTPException(status_code=401, detail="Nieprawidłowy użytkownik")
    if not _verify_password(credentials.password, user["hash"]):
        raise HTTPException(status_code=401, detail="Nieprawidłowe hasło")
    return {"username": credentials.username, "role": user["role"]}

def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Brak uprawnień — wymagany admin")
    return user

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
    bookings = load_bookings()
    if not booking.get("id"):
        booking["id"] = f"sb{int(datetime.now().timestamp()*1000)}"
    booking["createdBy"] = user["username"]
    booking["createdAt"] = datetime.now().isoformat()
    bookings.append(booking)
    make_backup()
    save_bookings(bookings)
    return booking

@app.put("/api/bookings/{booking_id}")
def update_booking(booking_id: str, updated: dict, user=Depends(get_current_user)):
    """Edytuje rezerwację. Pracownik nie może edytować rezerwacji z poprzednich miesięcy."""
    bookings = load_bookings()
    idx = next((i for i, b in enumerate(bookings) if b["id"] == booking_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Rezerwacja nie znaleziona")

    booking = bookings[idx]

    if user["role"] == "worker":
        booking_month = booking.get("from", "")[:7]
        current_month = date.today().strftime("%Y-%m")
        if booking_month < current_month:
            raise HTTPException(
                status_code=403,
                detail="Brak uprawnień — pracownik nie może edytować rezerwacji z poprzednich miesięcy"
            )

    updated["id"] = booking_id
    updated["updatedBy"] = user["username"]
    updated["updatedAt"] = datetime.now().isoformat()
    bookings[idx] = updated
    make_backup()
    save_bookings(bookings)
    return updated

@app.delete("/api/bookings/{booking_id}")
def delete_booking(booking_id: str, user=Depends(require_admin)):
    """Kasuje rezerwację — tylko admin."""
    bookings = load_bookings()
    new_bookings = [b for b in bookings if b["id"] != booking_id]
    if len(new_bookings) == len(bookings):
        raise HTTPException(status_code=404, detail="Rezerwacja nie znaleziona")
    make_backup()
    save_bookings(new_bookings)
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
    return entry

@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: str, user=Depends(require_admin)):
    """Kasuje fakturę — tylko admin."""
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
    """Zapisuje ceny pokoi. Dostępne dla wszystkich zalogowanych."""
    save_prices(prices)
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
    return load_media()

@app.put("/api/media/{room_id}/{period}")
def save_room_media(room_id: str, period: str, data: dict, user=Depends(get_current_user)):
    media = load_media()
    key = f"{room_id}__{period}"
    media[key] = data
    save_media(media)
    return data

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
    user=Depends(require_admin)
):
    """Uploaduje zdjęcie obiektu — tylko admin.
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
    return {"locId": loc_id, "filename": dest.name, "url": f"/loc_images/{dest.name}"}

@app.delete("/api/locations/{loc_id}/image")
def delete_location_image(loc_id: int, user=Depends(require_admin)):
    """Kasuje zdjęcie obiektu — tylko admin."""
    deleted = False
    for f in LOC_IMAGES_DIR.glob(f"{loc_id}.*"):
        f.unlink()
        deleted = True
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
    return note

@app.put("/api/notes/{note_id}")
def update_note(note_id: str, updated: dict, user=Depends(get_current_user)):
    notes = load_notes()
    idx = next((i for i, n in enumerate(notes) if n["id"] == note_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Notatka nie znaleziona")
    notes[idx]["text"] = updated.get("text", notes[idx].get("text", ""))
    notes[idx]["updatedBy"] = user["username"]
    notes[idx]["updatedAt"] = datetime.now().isoformat()
    backup_notes()
    save_notes(notes)
    return notes[idx]

@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str, user=Depends(require_admin)):
    """Kasuje notatkę — tylko admin. Backup robi się przed kasowaniem."""
    notes = load_notes()
    if not any(n["id"] == note_id for n in notes):
        raise HTTPException(status_code=404, detail="Notatka nie znaleziona")
    backup_notes()
    save_notes([n for n in notes if n["id"] != note_id])
    return {"deleted": note_id}

# ============================================================
# API — INFO O ZALOGOWANYM UŻYTKOWNIKU
# ============================================================

@app.get("/api/me")
def get_me(user=Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"]}

# ============================================================
# API — RĘCZNY BACKUP
# ============================================================

@app.post("/api/backup")
def manual_backup(user=Depends(require_admin)):
    make_backup()
    return {"status": "backup created", "time": datetime.now().isoformat()}

# ============================================================
# URUCHOMIENIE
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
