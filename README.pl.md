# Booking Manager

Aplikacja webowa do zarządzania rezerwacjami krótkoterminowymi — zbudowana dla biznesu obsługującego **9 obiektów / 126 pokoi** w polskich miastach. Obsługuje dostępność per łóżko, rozliczenie per pracownik, stałych najemców, faktury, wykresy i automatyczne nocne backupy.

[🇬🇧 English README](README.md)

---

## Po co to powstało

Projekt powstał dla rodzinnego biznesu, który zarządzał 126 pokojami w Excelu. Cele:

- **Zero podwójnych rezerwacji** — dostępność per łóżko, nie per pokój
- **Mieszane tryby rozliczania** — niektóre firmy płacą za pokój, inne za pracownika, z indywidualnymi stawkami
- **Stali najemcy** — otwarte rezerwacje rozliczane automatycznie do końca miesiąca
- **Koniec z teczką paragonów** — załączniki faktur + media (prąd, woda, gaz, internet) per pokój per okres
- **Codzienny ogląd biznesu** — KPI z zyskiem netto, obłożeniem, trendami
- **Działa na taniej infrastrukturze** — pojedynczy proces FastAPI na małym VPS, JSON jako storage, bez serwera bazy

---

## Stack

- **Backend**: FastAPI (Python 3.11), Uvicorn, Pydantic
- **Auth**: HTTP Basic + hashowane hasła bcrypt (oddzielny `data/users.json`, chmod 600), role admin/worker
- **Storage**: pliki JSON (świadomy wybór — mały dataset, atomic writes, trywialne backupy)
- **Frontend**: Single-page vanilla JS/HTML/CSS (~5800 linii, zero build), ikony Lucide-style inline SVG
- **Deployment**: systemd na Hetzner, HTTPS via Caddy, staging na porcie 8001
- **Backupy**: 90 dziennych kopii rotacyjnych (cron na serwerze + launchd na Macu jako off-site)

Bez frameworków, bez bundlera, bez serwera DB. Cały stack jest celowo nudny i czytelny.

---

## Funkcje

### Rezerwacje
- Dostępność per łóżko — wielu gości może niezależnie zająć pokój wielołóżkowy
- Wieloosobowe rezerwacje firmowe (jedna firma, wiele pokoi, grupa rozwijalna w raportach)
- Serie cykliczne (tygodniowe/miesięczne z masowym anulowaniem)
- Dni buforowe na sprzątanie pomiędzy pobytami
- Kalendarz "faktycznego pobytu" — oddziela dni rezerwacji od dni faktycznej obecności

### Rozliczenia
- **Tryb per pokój** — stawka z cennika pokoju
- **Tryb per pracownik** — każdy pracownik ma swoją stawkę dzienną
- **Tryb mieszany** — w jednej rezerwacji część pracowników rozliczana per pokój, część per pracownik
- **Indywidualna stawka** — pole `dailyRate` nadpisuje domyślną stawkę
- **Stały najemca** — rezerwacja otwarta, automatycznie naliczana do końca miesiąca (lub do `permanentEnd`)

### Raporty
- Hero KPI: zysk netto z deltą miesiąc-do-miesiąca
- Drill-down: przychód → koszty (media + sprzątanie) → netto
- Rozliczenie mediów per pokój per okres (prąd, woda, gaz, internet, inne)
- Grupowanie multi-room dla rezerwacji firmowych
- Eksport CSV

### Inne
- System notatek: per rezerwacja lub ogólne, z historią edycji
- Upload zdjęć obiektów (JPG/PNG, serwowane z `data/loc_images/`)
- Wykresy: trend przychodów, podział wg obiektu (pie), heatmap obłożenia
- Tryb jasny/ciemny z adaptywną favicon
- Polskie UI; komentarze w kodzie mieszane PL/EN

---

## Decyzje architektoniczne warte odnotowania

- **JSON zamiast SQL** — cały dataset to ~2MB. SQL dodałby koszt operacyjny (migracje, backupy, wersjonowanie schematu) bez praktycznego zysku w tej skali. Zapis atomowy przez tempfile + rename.
- **Single-page bez frameworka** — mniej ruchomych części, instant load, brak pipeline'u który by się psuł. Cały HTML to ~330KB gzip i renderuje całą aplikację.
- **render() oparty o stan** — jeden globalny obiekt `state`, jedna funkcja `render()` zwracająca świeży string HTML przy każdej zmianie. Bez virtual DOM, bez biblioteki reactivity — template literale i `innerHTML`. Przewidywalne, łatwe do debugowania.
- **bcrypt + osobny plik (chmod 600)** — migracja z plaintext w źródłach. Plik wykluczony z backupów-do-miejsc-publicznych.
- **Inline SVG icon set** — ikony Lucide-style zdefiniowane w jednym obiekcie `ICONS` w JS. Bez font-icon, bez sprite — każda ikona to funkcja 5-10 linii. Kolor i rozmiar przekazywane w wywołaniu.
- **Dwupoziomowe backupy** — codzienny cron na serwerze (90 rotujących kopii na VPS) + off-site na Macu via launchd, który pulluje zarówno produkcję jak i staging. Tanio rozwiązuje problem single point of failure.

---

## Setup

### Wymagania
- Python 3.11+
- `pip install -r requirements.txt`

### Pierwsze uruchomienie
```bash
git clone https://github.com/<twoj-user>/booking-manager.git
cd booking-manager
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Utwórz pierwszego admina (tworzy data/users.json z bcrypt hashem, chmod 600)
./users add admin "twoje-haslo" --role admin

# Uruchom serwer
./start.sh
# → http://localhost:8000
```

### Dodawanie kolejnych userów
```bash
./users list                                  # lista userów
./users add worker1 "haslo" --role worker     # dodaj workera
./users passwd admin "nowe-haslo"             # zmień hasło
./users role worker1 admin                    # promuj
./users delete worker2                        # usuń
```

### Backupy
Codzienne backupy robi `backup_scheduler.py` (uruchamiany jako background thread przez `app.py`). Lecą do `data/backups/daily/YYYY-MM-DD/` i trzymają ostatnie 90 dni. Ręczny backup: `python3 backup_scheduler.py`.

---

## Struktura repo

```
.
├── app.py                  # Backend FastAPI (~600 linii): auth, CRUD, uploady
├── manage_users.py         # CLI userów bcrypt
├── backup_scheduler.py     # daemon nocnych backupów
├── users                   # wrapper bash dla manage_users.py
├── start.sh / start.bat    # launchery
├── requirements.txt
├── static/
│   ├── index.html          # Cały frontend (~5800 linii)
│   └── favicon.svg
└── data/                   # gitignored — rezerwacje, faktury, users.json, backupy
```

---

## Status

Używane produkcyjnie przez biznes obsługujący 9 obiektów / 126 pokoi od 2025. Aktywny rozwój — w roadmapie moduł SMS do potwierdzeń rezerwacji.

---

## Licencja

MIT — patrz [LICENSE](LICENSE).
