#!/usr/bin/env python3
"""
patch_locations.py — sanity check / leak detector.

Od refactoru (2026-05-21) prawdziwe nazwy obiektów żyją tylko w
`static/locations.local.js` (gitignored). Ten skrypt:

  python3 demo/patch_locations.py check

…wyciąga listę prawdziwych nazw z `static/locations.local.js` i sprawdza
czy któraś z nich nie wyciekła do plików które będą commitowane.

Jeśli nie masz `static/locations.local.js` (np. świeży clone z GitHuba),
check zwraca OK z informacją, że nie ma czego sprawdzać.
"""

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "static" / "locations.local.js"

EXCLUDE_PREFIXES = (
    ".git",
    "data",
    ".venv-preview",
    "BM-Venv",
    "venv",
    "__pycache__",
    "static/locations.local.js",
    "data.real-backup",
)

SCAN_SUFFIXES = {".html", ".py", ".js", ".md", ".sh", ".txt", ".json"}


def extract_real_names():
    """Wyciągnij listę prawdziwych nazw obiektów + miast z locations.local.js."""
    if not LOCAL.exists():
        return None
    text = LOCAL.read_text(encoding="utf-8")
    # Pattern: name: "...", city: "..."
    pairs = re.findall(r'name:\s*"([^"]+)",\s*city:\s*"([^"]+)"', text)
    names = set()
    for name, city in pairs:
        # Próg >=4 znaki: pomija placeholdery/słowa generyczne (np. 3-literowe), które
        # łapałyby masę false-positives (krótkie słowo trafia w kod) a nic nie ujawniają.
        # Spójne z progiem w tools/check_leak.py.
        if len(name) >= 4:
            names.add(name)
        if len(city) >= 4:
            names.add(city)
    return names


def check():
    real_names = extract_real_names()
    if real_names is None:
        print(f"ℹ️  Brak {LOCAL.relative_to(ROOT)} — nie ma czego sprawdzać.")
        print("    (To OK jeśli pracujesz na świeżym clone z GitHuba.)")
        return

    print(f"Skanuję {len(real_names)} prawdziwych nazw w plikach committed-friendly…")

    leaks = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        rel_str = str(rel)
        if any(rel_str == ex or rel_str.startswith(ex + "/") for ex in EXCLUDE_PREFIXES):
            continue
        if path.suffix not in SCAN_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name in real_names:
            if name in content:
                leaks.append((str(rel), name))

    if leaks:
        print(f"❌ Znaleziono {len(leaks)} wyciek(ów):")
        for path, name in sorted(set(leaks)):
            print(f"   {path}  →  '{name}'")
        sys.exit(1)
    else:
        print("✅ Brak wycieków — pliki committed są czyste.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "check":
        print(__doc__)
        sys.exit(1)
    check()
