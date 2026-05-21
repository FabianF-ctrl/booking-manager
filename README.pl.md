# HospesAI

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

### Tryb demo (bez setupu)
```bash
./demo/start.sh
# → http://localhost:8003  (admin / demo123)
# Ctrl+C przywraca prawdziwe dane
```
Ładuje fikcyjne obiekty, ~12 przykładowych rezerwacji (indywidualne / firmowe / stały najemca / seria cykliczna / mieszane tryby rozliczenia / customPrice override), notatki, media i ceny. Produkcyjne `data/` jest odsuwane na bok i przywracane przy wyjściu. Zobacz [`demo/README.md`](demo/README.md).

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
├── demo/                   # Fikcyjny dataset + runner do screenshotów
│   ├── data/               # Fake rezerwacje, userzy, ceny itd.
│   ├── patch_locations.py  # Podmienia prawdziwe nazwy obiektów na fikcyjne
│   └── start.sh            # Orkiestrator: swap in → run → restore przy wyjściu
└── data/                   # gitignored — rezerwacje, faktury, users.json, backupy
```

---

## Lessons learned

Co zrobiłbym inaczej z perspektywy czasu (lub co zajęło mi chwilę żeby zrozumieć):

- **Wybierz nudną warstwę storage na końcu, nie na początku.** Z przyzwyczajenia prawie sięgnąłem po SQLite + SQLAlchemy w dniu pierwszym. Dla jednoosobowego datasetu 2MB podejście JSON-on-disk okazało się szybsze do zbudowania, łatwiejsze do backupowania (`cp -r`) i trywialne do inspekcji przy debuggowaniu. Schema "migracje" stają się skryptem `python3 -c "for b in bookings: b.setdefault(...)"`. Koszt: brak współbieżnych zapisów (jeden worker FastAPI), brak joinów, brak indeksów. Przy tej skali — koszty zerowe.

- **State + render() wygrały z moimi próbami bycia sprytnym.** Wczesne commity miały handlery per komponent i bezpośrednią manipulację DOM. Stało się to niezarządzalne koło 2000 linii. Przejście na `state = {...}; render()` (jedna funkcja zwracająca świeży string HTML wstawiany jako `innerHTML`) zrobiło frontend dramatycznie łatwiejszym do zrozumienia. "Performance hit" pełnego re-renderowania jest niewidoczny przy 126 pokojach.

- **Backupy muszą być out-of-band.** Pierwszy design backupów to był cron na tym samym VPS — kompletnie bezużyteczny jeśli VPS pada. Dodanie launchd na Macu, który pulluje produkcję i staging via rsync, zajęło 30 minut i jest najważniejszą funkcją niezawodności w projekcie. (Dodatkowy ból: macOS TCC blokuje launchd przed dostępem do `~/Documents/`. Spędziłem wieczór na tym zanim przeniosłem skrypt do `~/Library/Scripts/`.)

- **Plaintext hasła w źródłach to był błąd.** Pierwsza wersja miała hardcoded dict `_LEGACY_USERS` dla wygody w early devie. Zanim zauważyłem ile to tworzy powierzchni ataku, musiałem migrować na bcrypt hashes w osobnym pliku chmod 600. Teraz jest CLI (`./users add admin "haslo" --role admin`), a kod aplikacji nie ma pojęcia o żadnym haśle.

- **Dostępność per łóżko powinna być od pierwszego dnia.** Najpierw shippnałem dostępność per pokój ("pokój jest zajęty lub nie"), wszedłem na produkcję, potem odkryłem że biznes faktycznie potrzebuje wsadzić dwóch niezwiązanych gości do tego samego pokoju 4-osobowego. Doszywanie księgowania łóżek przez `bedsUsedByBooking` / `getFreeBeds` / `getRoomOccupants` było bolesne bo każdy ekran rezerwacji wymagał updateu. Lekcja: zapytać "co jest granularność zasobu?" zanim się projektuje model.

- **Migracja ikon była warta zachodu.** Zamiana każdej emoji na Lucide-style inline SVG wyglądała jak busywork. Efekt: spójne renderowanie na różnych OS/browserach, świadomość light/dark mode (`currentColor`), per-call sizing, brak font dependencies. Obiekt `ICONS` to teraz ~50 małych funkcji; total koszt ~2KB gzip.

---

## Trade-offs

Świadome decyzje techniczne i co każda kosztowała:

| Decyzja | Zysk | Koszt |
|---|---|---|
| JSON zamiast SQL DB | Trywialne backupy, atomic writes (tempfile+rename), zero zarządzania schematem, dataset czytelny w każdym edytorze | Brak współbieżnych zapisów, brak joinów ani indeksów, twardy limit (~10MB zanim I/O zacznie boleć) |
| Single-page bez frameworka | Zero build step, instant load, łatwy deploy (jeden static), brak rotacji zależności | Brak type-checkingu (vanilla JS), brak biblioteki komponentów, ręczna reactivity, długi pojedynczy plik |
| HTTP Basic + bcrypt | Stateless (brak sesji do zarządzania), działa za każdym reverse proxy, browser obsługuje UI logowania | Brak "zapamiętaj mnie", brak password reset flow, brak MFA, gorszy UX niż custom form |
| FastAPI single worker | Najprostszy możliwy deploy (jeden serwis systemd), brak koordynacji stanu między workerami | Brak skalowania horizontal; jeden wolny request blokuje następny. OK przy tej skali |
| Polskie UI + mieszane komentarze PL/EN | Userzy produkcji dostają natywny język; komentarze oddają terminologię dziedzinową ("stały najemca" nie ma czystego ekwiwalentu po angielsku) | Mniej dostępne dla zagranicznych contributorów. (W tym projekcie to nie jest realny problem.) |
| Hardcoded dane lokalizacji w `index.html` | Frontend renderuje zero-latency na pierwszym paint, brak dodatkowego API calla po graf pokoi | Zmiana pokoi wymaga edycji kodu + deployu. Akceptowalne bo portfolio nieruchomości zmienia się może dwa razy na rok. |
| Manualny `render()` zamiast frameworka | Przewidywalny, debugowalny przez `console.log(state)`, brak update'ów biblioteki łamiących aplikację | Musiałem napisać helpery (debounced events, sticky scroll restore, focus management) które React/Vue dają z pudełka |

---

## Roadmap

**W kolejce:**
- **Moduł SMS** — potwierdzenia rezerwacji dla gości via Twilio/SMSAPI, z szablonami per typ rezerwacji
- **Generowanie PDF faktur** — obecnie faktury są uploadowane; auto-generacja z danych rezerwacji

**Rozważone i odrzucone (na razie):**
- **Wersja multi-tenant SaaS** — wymagałoby wyrwania storage JSON i dodania pełnego auth/billing/izolacji per tenant. Niewart kosztu przepisywania gdy jest jeden user.
- **Przepisanie na React/Vue** — kupiłoby ergonomię ale kosztowało własność "zero build step" która sprawia że deploy jest trywialny. Może przy 10k+ liniach, jeszcze nie teraz.
- **Aplikacja mobilna** — responsive web działa na telefonach wystarczająco dobrze. Natywna apka to miesiące pracy dla marginalnego UX.
- **Real-time multi-user collaboration** — obecny model to "jeden operator na raz" i tak właśnie firma faktycznie pracuje. Live updates przez WebSocket byłyby fajną funkcją ale rozwiązywałyby problem którego nikt nie ma.

---

## Status

Używane produkcyjnie przez biznes obsługujący 9 obiektów / 126 pokoi od 2025.

---

## Licencja

MIT — patrz [LICENSE](LICENSE).
