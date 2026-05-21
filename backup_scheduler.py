"""
backup_scheduler.py — automatyczne dzienne backupy
===================================================
Uruchamiaj RAZEM z app.py:

    Windows:  start_all.bat
    Mac/Linux: ./start_all.sh

Robi backup co noc o 3:00, niezależnie od aktywności w apce.
Trzyma maksymalnie 90 kopii (ok. 3 miesiące codziennych backupów).
"""

import shutil
import time
import threading
from datetime import datetime, date
from pathlib import Path

# ============================================================
# KONFIGURACJA
# ============================================================

BASE_DIR     = Path(__file__).parent
DATA_DIR     = BASE_DIR / "data"
BACKUPS_DIR  = DATA_DIR / "backups"
BOOKINGS_FILE     = DATA_DIR / "bookings.json"
INVOICES_META     = DATA_DIR / "invoices_meta.json"
ROOM_MEDIA        = DATA_DIR / "room_media.json"
PRICES_FILE       = DATA_DIR / "prices.json"
NOTES_FILE        = DATA_DIR / "notes.json"
USERS_FILE        = DATA_DIR / "users.json"
INVOICES_DIR      = DATA_DIR / "invoices"
LOC_IMAGES_DIR    = DATA_DIR / "loc_images"

MAX_BACKUPS  = 90   # ile codziennych kopii trzymać (ok. 3 miesiące)
BACKUP_HOUR  = 3    # godzina nocna (24h)
BACKUP_MIN   = 0

# ============================================================
# LOGIKA BACKUPU
# ============================================================

def make_daily_backup():
    """
    Tworzy pełny backup folderu data/ do backups/daily/YYYY-MM-DD/
    Kopiuje:
      - bookings.json
      - invoices_meta.json
      - room_media.json
      - prices.json
      - folder invoices/ (pliki PDF/zdjęcia)
    """
    today = date.today().strftime("%Y-%m-%d")
    backup_dir = BACKUPS_DIR / "daily" / today
    backup_dir.mkdir(parents=True, exist_ok=True)

    copied = []

    # Kopiuj pliki JSON
    for src in [BOOKINGS_FILE, INVOICES_META, ROOM_MEDIA, PRICES_FILE, NOTES_FILE, USERS_FILE]:
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)
            copied.append(src.name)

    # Kopiuj folder z fakturami (pliki PDF/img)
    if INVOICES_DIR.exists():
        dest_inv = backup_dir / "invoices"
        if dest_inv.exists():
            shutil.rmtree(dest_inv)
        shutil.copytree(INVOICES_DIR, dest_inv)
        copied.append(f"invoices/ ({len(list(INVOICES_DIR.iterdir()))} plików)")

    # Kopiuj folder ze zdjęciami obiektów
    if LOC_IMAGES_DIR.exists():
        dest_img = backup_dir / "loc_images"
        if dest_img.exists():
            shutil.rmtree(dest_img)
        shutil.copytree(LOC_IMAGES_DIR, dest_img)
        copied.append(f"loc_images/ ({len(list(LOC_IMAGES_DIR.iterdir()))} plików)")

    # Usuń stare backupy ponad limit
    daily_dir = BACKUPS_DIR / "daily"
    all_backups = sorted(daily_dir.glob("????-??-??"))  # sortuje chronologicznie
    for old in all_backups[:-MAX_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BACKUP] {ts} — dzienny backup gotowy: {backup_dir}")
    print(f"[BACKUP] Skopiowano: {', '.join(copied)}")
    print(f"[BACKUP] Łącznie przechowywanych kopii: {min(len(all_backups), MAX_BACKUPS)}")


def seconds_until_next_backup():
    """Ile sekund do następnego uruchomienia o BACKUP_HOUR:BACKUP_MIN."""
    now = datetime.now()
    target = now.replace(hour=BACKUP_HOUR, minute=BACKUP_MIN, second=0, microsecond=0)
    if now >= target:
        # Już minęła godzina dziś — czekamy do jutra
        from datetime import timedelta
        target += timedelta(days=1)
    return (target - now).total_seconds()


def scheduler_loop():
    """Pętla działająca w tle — czeka do 3:00 i odpala backup."""
    print(f"[BACKUP] Scheduler uruchomiony. Backup codziennie o {BACKUP_HOUR:02d}:{BACKUP_MIN:02d}.")
    while True:
        wait = seconds_until_next_backup()
        h, m = int(wait // 3600), int((wait % 3600) // 60)
        print(f"[BACKUP] Następny backup za {h}h {m}min.")
        time.sleep(wait)
        try:
            make_daily_backup()
        except Exception as e:
            print(f"[BACKUP] BŁĄD podczas backupu: {e}")
        # Poczekaj chwilę żeby nie odpalone dwa razy w tej samej minucie
        time.sleep(61)


def start_backup_scheduler():
    """
    Uruchom scheduler w wątku demona.
    Wywołaj tę funkcję z app.py lub start_all.sh.
    Wątek demon kończy się automatycznie gdy główny proces się kończy.
    """
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    return t


# ============================================================
# URUCHOMIENIE SAMODZIELNE (python backup_scheduler.py)
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  Backup Scheduler — tryb testowy")
    print("=" * 50)
    print("\nRobię natychmiastowy backup testowy...")
    make_daily_backup()
    print("\nScheduler uruchomiony. Ctrl+C żeby zatrzymać.")
    try:
        scheduler_loop()
    except KeyboardInterrupt:
        print("\n[BACKUP] Zatrzymano.")
