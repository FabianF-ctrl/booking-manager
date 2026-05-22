#!/usr/bin/env python3
"""
Leak detector dla commit messages / staged file content.

Wzorce leaków zaciągane z:
1. static/locations.local.js — prawdziwe nazwy obiektów (gitignored)
2. data/bookings.json — companyName z prawdziwych rezerwacji (gitignored)
3. tools/leak_patterns_extra.txt — opcjonalna lista dodatkowych wzorców (jedno per linia)
4. Hardcoded sensitive: stary IP, plaintext hasła historyczne

Jeśli źródła nie istnieją (świeży clone), skrypt WARN-uje ale nie blokuje
— pierwsze locations.local.js wpadnie po setupie, dopiero wtedy realnie chroni.

Użycie:
  python3 tools/check_leak.py <plik>           # skanuj plik tekstowy
  python3 tools/check_leak.py --stdin          # skanuj stdin
  python3 tools/check_leak.py --staged         # skanuj `git diff --cached`

Exit codes:
  0  — czysto
  1  — wykryto leak (commit zablokowany)
  2  — błąd użycia
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# UWAGA: hardcoded patterns CELOWO usunięte stąd — ironicznie leak detector
# wyciekałby swoje własne sekrety na GitHuba. Wszystkie wzorce z osobnych plików:
#
#   tools/leak_patterns_local.txt — gitignored, prawdziwe dane (IP, hasła historyczne, domena)
#   tools/leak_patterns_local.example.txt — committed template z placeholderami
#
# Setup po klonie:
#   cp tools/leak_patterns_local.example.txt tools/leak_patterns_local.txt
#   # → edytuj wpisując prawdziwe wartości
HARDCODED_PATTERNS = []

# Lista typowych imion polskich do ignorowania jako patterns (false positives)
# Jeśli twój real tenant ma takie imię, dodaj do leak_patterns_extra.txt manually.
COMMON_NAMES_BLACKLIST = {
    "jan", "anna", "maria", "adam", "piotr", "tomasz", "krzysztof", "andrzej",
    "marek", "paweł", "michał", "łukasz", "jakub", "katarzyna", "agnieszka",
    "magdalena", "joanna", "barbara", "ewa", "elżbieta", "alicja",
    "test", "guest", "gość", "demo", "pracownik", "klient", "user",
    "mama", "tata", "dziecko",  # generic family terms
}


def load_locations():
    """Wyciąga TOP-LEVEL nazwy obiektów (nie pokoi) z locations.local.js (gitignored).

    Format: { id: N, name: "...", city: "...", icon: ... } — patrzymy tylko na te,
    nie na nested room.name które są często generyczne ("2 parter", "13 piętro").
    """
    f = ROOT / "static" / "locations.local.js"
    if not f.exists():
        return []
    text = f.read_text(encoding="utf-8", errors="replace")
    # Match: id: N, name: "...", city: "..."  (top-level location, NIE pokój)
    loc_matches = re.findall(r'id:\s*\d+\s*,\s*name:\s*"([^"]+)"\s*,\s*city:\s*"([^"]+)"', text)
    names = set()
    for loc_name, city in loc_matches:
        if len(loc_name) >= 4:
            names.add(loc_name)
        if len(city) >= 4:
            names.add(city)
    return list(names)


def load_company_names():
    """Wyciąga companyName z bookings (firmy mają unikalne nazwy)."""
    f = ROOT / "data" / "bookings.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = set()
    for b in data:
        cn = (b.get("companyName") or "").strip()
        if not cn:
            continue
        # Strip legal suffixes ("sp. z o.o.", "S.A.", "sp.j.")
        clean = re.sub(r'\s+(sp\.?\s*z\s*o\.?o\.?|S\.A\.|sp\.j\.|spółka.*)$', '', cn, flags=re.I).strip()
        if len(clean) >= 4 and clean.lower() not in COMMON_NAMES_BLACKLIST:
            out.add(clean)
    return list(out)


def load_individual_first_names():
    """Wyciąga imiona stałych najemców indywidualnych z bookings (mniej oczywiste niż firmy)."""
    f = ROOT / "data" / "bookings.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = set()
    for b in data:
        if b.get("bookingType") != "individual":
            continue
        # Tylko stali najemcy (perm) — krótsze rezerwacje turystów bywają z fake/test names
        if not b.get("isPermanent"):
            continue
        for g in (b.get("guests") or []):
            name = (g.get("name") or "").strip()
            if not name:
                continue
            first = name.split()[0]
            if len(first) >= 5 and first.lower() not in COMMON_NAMES_BLACKLIST:
                out.add(first)
    return list(out)


def load_local_patterns():
    """Lokalny gitignored plik z hardcoded sensitive (IP, hasła, domena org).

    Format: jeden pattern per linia, # comments OK. Skrypt warn-uje jeśli brak.
    """
    f = ROOT / "tools" / "leak_patterns_local.txt"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_extra_patterns():
    """Manualnie maintainowana lista dodatkowa (jedna pattern per linia, # comments OK).

    Komitowane do repo (NIE gitignored) — używaj tylko dla generycznych wzorców
    bez wartości wrażliwej (np. "TODO:", "DEBUG:" jeśli chcesz blokować takie pozostawione).
    """
    f = ROOT / "tools" / "leak_patterns_extra.txt"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def get_all_patterns():
    pats = (
        HARDCODED_PATTERNS  # zostaje puste — tylko jako dokumentacja
        + load_local_patterns()  # gitignored sensitive (IP, hasła, domena)
        + load_locations()
        + load_company_names()
        + load_individual_first_names()
        + load_extra_patterns()  # committed extras
    )
    # Deduplicate, preserve order
    seen = set()
    out = []
    for p in pats:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def scan(text, patterns):
    """Return list of (pattern, count, sample_context) for matches."""
    text_l = text.lower()
    hits = []
    for pat in patterns:
        pat_l = pat.lower()
        count = text_l.count(pat_l)
        if count == 0:
            continue
        # Context for first hit
        idx = text_l.find(pat_l)
        line_start = text.rfind("\n", 0, idx) + 1
        line_end = text.find("\n", idx)
        if line_end == -1:
            line_end = len(text)
        ctx = text[line_start:line_end].strip()
        if len(ctx) > 100:
            # Trim around the hit
            local_idx = idx - line_start
            start = max(0, local_idx - 30)
            end = min(len(ctx), local_idx + len(pat) + 30)
            ctx = ("…" if start > 0 else "") + ctx[start:end] + ("…" if end < line_end - line_start else "")
        hits.append((pat, count, ctx))
    return hits


def scan_staged_diff():
    """Wyciąga z `git diff --cached` (sam diff, nie pełne pliki).

    Wyklucza pliki samego leak-detection systemu (zawierają patterns
    jako dane — false positive na samym sobie).
    """
    # Pliki które ZAWIERAJĄ patterns jako dane — pomijamy w skanie staged.
    # (Nadal są w repo, więc audyt całej historii złapie cokolwiek nowego,
    # ale w trakcie commitowania zmian DO TYCH PLIKÓW nie blokujemy.)
    EXCLUDED = {
        "tools/check_leak.py",
        "tools/leak_patterns_extra.txt",
    }
    try:
        # Use --diff-filter=ACM to skip deletions, and pass excludes
        cmd = ["git", "diff", "--cached"] + [f":(exclude){p}" for p in EXCLUDED]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, cwd=str(ROOT)
        )
        return result.stdout
    except Exception as e:
        print(f"⚠️  Nie udało się odczytać staged diff: {e}", file=sys.stderr)
        return ""


def strip_git_comments(text):
    """Usuwa linie # commentów z commit message (git auto-dodaje takie)."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    mode = sys.argv[1]
    if mode == "--stdin":
        text = sys.stdin.read()
        label = "stdin"
    elif mode == "--staged":
        text = scan_staged_diff()
        label = "staged diff"
    else:
        path = Path(mode)
        if not path.exists():
            print(f"❌ Plik nie istnieje: {mode}", file=sys.stderr)
            sys.exit(2)
        text = path.read_text(encoding="utf-8", errors="replace")
        label = str(path)

    # Strip git comment lines (relevant tylko dla commit message file)
    text = strip_git_comments(text)

    patterns = get_all_patterns()
    if not patterns:
        print("⚠️  check_leak: brak źródeł patterns (brak locations.local.js i data/bookings.json) — SKIP", file=sys.stderr)
        sys.exit(0)

    hits = scan(text, patterns)
    if not hits:
        sys.exit(0)

    # Bug detected — print report and fail
    print("", file=sys.stderr)
    print(f"❌ LEAK detected in {label}:", file=sys.stderr)
    print("", file=sys.stderr)
    for pat, count, ctx in hits:
        print(f"     • '{pat}' × {count}", file=sys.stderr)
        print(f"       w: {ctx}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Commit zablokowany. Usuń dane osobowe/poufne i spróbuj jeszcze raz.", file=sys.stderr)
    print(f"Aby ominąć (NIE zalecane): git commit --no-verify", file=sys.stderr)
    print("", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
