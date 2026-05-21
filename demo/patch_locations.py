#!/usr/bin/env python3
"""
patch_locations.py — podmienia nazwy obiektów/miast w static/index.html
na fikcyjne, do screenshotów portfolio.

Nie hardkoduje prawdziwych nazw — wyciąga je z istniejącego pliku runtime
i podmienia w kolejności na fikcyjne (DEMO_NAMES poniżej).

Użycie:
    python3 demo/patch_locations.py patch    # prawdziwe → demo
    python3 demo/patch_locations.py restore  # przywróć

Backup oryginału trzymany w demo/.index.html.real podczas trybu demo.
"""

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"
BACKUP = ROOT / "demo" / ".index.html.real"

# Fikcyjne nazwy w kolejności pojawiania się lokalizacji w index.html.
# Każda para nadpisuje (name, city) i-tej lokalizacji.
DEMO_NAMES = [
    ("Apartamenty Centralne",  "Warszawa"),
    ("Hostel Stary Browar",    "Kraków"),
    ("Kwatery Polna",          "Wrocław"),
    ("Apartamenty Słoneczne",  "Wrocław"),
    ("Hostel Brama Miejska",   "Gdańsk"),
    ("Hostel Park",            "Kraków"),
    ("Apartamenty Riverside",  "Kraków"),
    ("Mini-Apartamenty Centrum", "Kraków"),
    ("Pensjonat Górski",       "Zakopane"),
]

# Wyłapuje: name: "...", city: "..."  (z opcjonalnym whitespace)
LOC_RE = re.compile(r'name:\s*"([^"]*)",\s*city:\s*"([^"]*)"')


def patch():
    if BACKUP.exists():
        print(f"⚠️  Backup już istnieje ({BACKUP}). Najpierw zrób `restore`.")
        sys.exit(1)
    text = INDEX.read_text(encoding="utf-8")
    BACKUP.write_text(text, encoding="utf-8")

    matches = LOC_RE.findall(text)
    if len(matches) > len(DEMO_NAMES):
        print(f"⚠️  Znaleziono {len(matches)} lokalizacji, mam {len(DEMO_NAMES)} fikcyjnych nazw. Dodaj więcej do DEMO_NAMES.")
        sys.exit(1)

    counter = [0]
    def sub(_match):
        idx = counter[0]
        counter[0] += 1
        if idx < len(DEMO_NAMES):
            demo_name, demo_city = DEMO_NAMES[idx]
            return f'name: "{demo_name}", city: "{demo_city}"'
        return _match.group(0)

    new_text = LOC_RE.sub(sub, text)
    INDEX.write_text(new_text, encoding="utf-8")
    print(f"✅ Podmieniono {counter[0]} lokalizacji na fikcyjne. Backup: {BACKUP}")


def restore():
    if not BACKUP.exists():
        print(f"❌ Brak backupu ({BACKUP}). Nie ma co przywracać.")
        sys.exit(1)
    INDEX.write_text(BACKUP.read_text(encoding="utf-8"), encoding="utf-8")
    BACKUP.unlink()
    print(f"✅ Przywrócono oryginalne nazwy w {INDEX} (backup usunięty)")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("patch", "restore"):
        print(__doc__)
        sys.exit(1)
    {"patch": patch, "restore": restore}[sys.argv[1]]()
