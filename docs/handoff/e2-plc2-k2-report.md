# E2-PLC2, krok 2: raport (collector v1+v2, agregaty, panele); zgłoszenie gotowości do PLC-2
Status: DO PRZEGLĄDU. **Zgłaszam gotowość do przełączenia PLC na v2 (PLC-2).**

Wykonanie 25.11.2026 wg `e2-plc2-k2-plan.md` i `e2-plc2-k2-review.md` (czasy w UTC; logi kontenerów w czasie lokalnym UTC+1). Bez `sudo`, bez ruszania smartWARE i `.env`; do PLC dotarł wyłącznie FC04 (`mbpoll -t 3` i collector). **PLC nie był przełączany.**
Na komputer trafiało tylko to, co jest w `origin/main` (`git pull --ff-only`). Stan komputera: `261213c` (kod wdrożony), potem tylko dokumenty.

## Wynik: gotowość

| Kryterium z planu | Wynik |
| --- | --- |
| Krok 1: `mbpoll -t 3 -r 0 -c 60` na PLC v1 | **60 rejestrów odczytanych**, rejestry 44–59 = 0, `map_version` = 1, status licznika 0, serial `F0183363` (23.11 i dziś bez zmian); serwer nie zgłasza wyjątku, więc zapas P2-a (dwa zapytania) nie był potrzebny |
| Wdrożenie z `--build` | `docker compose up -d --build` 10:04:04–10:04:16; migracje **006, 007, 008** zastosowane (`schema_migrations` = 8 wierszy; 007 z pierwszym odświeżeniem trwała ok. 6 s na 1,3 mln wierszy); kolejność wg R-1 (pull → build → sprawdzenie `schema_migrations`) |
| Kontrola v1 przez 20 min (10:05:00–10:25:00) | **13,00 wiersza/s** (15 600 wierszy, 1 200 z 1 200 sekund miało komplet 13 wierszy), `link_status` w każdej sekundzie (1 200 wierszy, 0 brakujących sekund, 0 wierszy ≠ 0), **0 wierszy metryk v2**, 0 epizodów błędu licznika w oknie, **0 wpisów WARNING i ERROR w logach collectora i ingestu**, 0 restartów, wszystkie kontenery `healthy` |
| Log collectora | `collector start: PLC 192.168.0.246:502 (FC04, rejestry 0-59)` i `mapa rejestrów PLC: wersja 1` |
| Panele na produkcji (harness, przez `docker exec`) | **276 zapytań, 0 błędów**, 0 wpisów `level=error` w logu Grafany; panele v2 (THD, kąt, temperatura, czas pracy) zwracają 0 wierszy i pokażą „Brak danych (mapa v1)”, nie zero; panele energii biernej (całka Q) i PF mają dane |
| Izolacja | w `ss -ltn` bez nowych portów (3000 z k7), `StartedAt` smartWARE bez zmian (06:52:39 UTC 24.11) |
| Pamięć | collector 23,7 MiB / 128, ingest 26,9 MiB / 128, Grafana 134 MiB / 384, baza 325 MiB / 1,5 GiB, Mosquitto 1,2 MiB / 64 (po restarcie) |
| Okno wdrożenia | jedyna przerwa w `link_status` to **4 s** (10:04:06–10:04:10, odtworzenie collectora i rozgrzewka); restart Mosquitto 10:04:24–10:04:35 (nowy limit kolejki) bez luki: wiadomości czekały w buforze collectora, sesja ingestu wznowiona |

**Czego to nie dowodzi:** ścieżka v2 jest sprawdzona na atrapie PLC (testy) i na syntetycznej bazie, **nie na prawdziwym PLC v2**; weryfikacja na prawdziwych danych to krok 4 po przełączeniu.

## Co zrobiono

Commity (kolejność): `d5ed660` kod PLC z PLC-1 razem z `docs/modbus-map.md` v2 (osobny commit wg U-2; kodu ST nie zmieniałem), `693c535` review planu, `869dc13` collector, `9c2ddbf`/`6c635d1` migracje i testy bazy, `dfa7d39`/`41e743b` panele i testy, `123048b`/`d95d8c0` bufory, dokumenty i sonda pamięci, `261213c` poprawka paneli energii biernej.

**Collector (`config/devices.yaml`, `config.py`, `evaluator.py`, `codec.py`, `main.py`):**
- jedno zapytanie FC04 0–59 dla obu wersji; `plc.map_versions: [1, 2]`; pola v2 z `since: 2`; wersja spoza listy → `link_status` 3 (bez rozgrzewki, tylko status);
- **wszystko co 1 s (P2-c zmienione w review): 20 wierszy/s** w stanie OK (13 + 7), 5 wierszy/s przy `meter_status` ≠ 0, 1 przy awarii PLC; nowe wartości tylko przy `meter_status` = 0 i zgodnym numerze seryjnym;
- nazwy **`reactive_pos_varh` (n2, Q > 0) i `reactive_neg_varh` (n4, Q < 0)**, jednostki `varh`, `%`, `°`, `°C`, `s`; energia bierna jak czynna (mantysa × 10^wykładnik, rozdzielczość 100 varh w `devices.yaml` i w `devices.meta` jako `reactive_resolution_varh`);
- `valid_range` jako **filtr śmieci** z komentarzem „filtr wiarygodności, nie dane katalogowe”: THD U 0…100, THD I 0…1000, kąt −180…180, temperatura −50…150, czas pracy 0…4,3×10^9; wartość spoza zakresu lub NaN nie jest publikowana, WARNING **raz na zmianę stanu** (wcześniej NaN logowano w każdym cyklu), INFO przy powrocie; log okresowy z licznikiem pominiętych: collector nie ma dziś logu okresowego, więc nie dodawałem (zgodnie z „jeśli już taki jest”);
- przełączanie wersji w locie: INFO `zmiana wersji mapy rejestrów PLC: 1 -> 2` i nowa rozgrzewka (P2-h);
- bufor collectora `COLLECTOR_BUFFER_MAX` 30 000; Mosquitto `max_queued_messages` 80 000 (przeliczone dla 20 wierszy/s: ok. 25 i 66 minut). **Pamięć Mosquitto przy pełnej kolejce zmierzona: 36,8 MiB z 64 MiB**, bez OOM (po 90 000 wiadomości QoS 1 do rozłączonej sesji, projekt `aip-test`; sonda `tests/mqtt/probe_queue_memory.py`). Nowy limit wymaga restartu Mosquitto (wykonany);
- **ingest bez zmian w logice walidacji** (nazwy, jednostki do 16 znaków, w tym `°C`, przechodzą; test); tylko `devices.meta`: `map_versions: [1, 2]` i `reactive_resolution_varh`.

**Baza (migracje):**
- **006**: okno `plc_program_download` z PLC-1: 08:16:10,574–08:16:18,577 UTC (granice z bazy: pierwszy i ostatni wiersz `link_status` ≠ 0, 10 wierszy);
- **007**: `energy_ext_1m` i `energy_ext_1h` (THD, kąt, `phase_cos_sum` = suma cos kąta, temperatura, czas pracy, stany liczników `counter_pos/neg`, **całka mocy biernej `reactive_pos_sum`/`reactive_neg_sum` od początku zapisu `reactive_power`**, także sprzed v2: agregat objął Q z wcześniejszych dób, 1 674 minut z Q, 0 z THD); polityki jak dla energii czynnej; idempotentna (test przerwania w pięciu punktach);
- **008**: widok `reactive_1h_calc` (przyrost n2 i n4, reset, `pos_gap_before`/`neg_gap_before`, całka w varh, `coverage`).

**Panele (po polsku):** Jakość energii: „THD napięcia (THD U)”, „THD prądu (THD I)”, „Kąt U–I”, „**Współczynnik mocy PF**” (przemianowany; seria PF i **cos φ = cos(kąt)** jako druga seria; opis z PF = cos φ / √(1 + THD_I²) i liczbami 0,37 i 0,64); Energia i profil: „Energia bierna z mocy (całka Q, godziny)” i „Energia bierna na dobę: całka i licznik (ostatnie 14d)”; Stan i diagnostyka: kafelek i wykres temperatury, kafelek i wykres czasu pracy (w dobach), opis „Wiersze na minutę” z 13/20 wierszami na sekundę; Licznik na żywo: kafelki THD U, THD I, kąt, temperatura, wykresy THD i kąta, tabela rozszerzona. Przed v2: zapytania bez `COALESCE`, `noValue` „Brak danych (mapa v1)”, kafelki z podzapytaniem dają NULL, nie 0. Opisy kąta: **„u nas kąt ujemny przy Q < 0 (zmierzone 25.11.2026), konwencja Findera niepotwierdzona”** (U-1), THD I z uwagą o małym prądzie bez progów (U-5), temperatura bez progów (U-6).

## Testy

- Pełny zestaw na komputerze: **482 z 482** (przed i po ostatniej zmianie paneli energii biernej; 10 min 25 s); testy Grafany po tej zmianie **106 z 106**; pomiar wydajności na roku danych **3 z 3**.
- Nowe: `tests/collector/test_map_v2.py` (dekodowanie v2 ze znanych słów: −50,58°, 140,22%, 2,34%, 30,2 °C, 1 256 171 s, n4 = 4 500 varh; v1 z „śmieciami” w 44–59 nie publikuje v2; wersje 0, 3, 4, 255, 65535 → `link_status` 3; ważność przy `status` ≠ 0, 2 i nieznanym numerze seryjnym; `valid_range` z granicami włączonymi; NaN; przełączanie v1 → v2 → v1 w locie i cykl „download”: zerwanie, rozgrzewka, powrót z v2; konfiguracja: `map_versions`, `since` poza listą, `valid_range`, nakładanie v1/v2, konfiguracja samej v1), test pętli (INFO o wersji i WARNING raz na zmianę), test e2e z prawdziwym sterownikiem i brokerem (v1 → v2 w locie, 60 rejestrów, **tylko FC04**), `tests/db/test_energy_ext.py` (18 testów: agregaty równe przeliczeniu z surowych danych na losowych danych z lukami, hierarchia, `phase_cos_sum`, brak zer przed v2, całka z podziałem znaku, przyrost, reset, luka, NULL bez `meta`, polityki, uprawnienia, przerwanie migracji 007), testy paneli v2 (brak wierszy dla licznika bez v2, wartości THD i kąta z danych, cos φ zgodny z kątem, NULL w kafelkach), testy dokumentów (model wierszy 13/20/5/1).
- **Wydajność na roku danych** (8,2 mln wierszy surowych, 1,9 GB, pierwsze odświeżenie czterech agregatów 489 s): wszystkie zapytania paneli < 1 s, **najwolniejsze 379 ms**; nowe panele: THD, kąt, PF ≤ 321 ms, energia bierna 42 ms (godziny, rok) i 5–9 ms (doby).

## Odstępstwa od planu i ustalenia

1. **Panele energii biernej nie czytają widoku `reactive_1h_calc`:** na roku danych widok trwał **20 s** (limit `app_reader` 10 s), a pierwotnie zaplanowane panele przekraczały 1 s (doby 1,5 s). Przyczyny nie ustaliłem: plan pokazuje 20 s na odczycie pierwszego kawałka materializacji, choć zwykłe zapytanie do `energy_ext_1h` trwa 6 ms (analogiczny widok `energy_1h_calc` był szybki). Panele czytają `energy_ext_1h` wprost (całka) i liczą przyrost z zapasem 3 dni jak w k7 (doby): 42 ms i 9 ms. Widok zostaje dla analityki z ostrzeżeniem, żeby nie używać go na długich zakresach (dopisane w `docs/data-model.md`); do wyjaśnienia przed użyciem w etapie 4.
2. **Wada w migracji 002 (energy_1h), nie w ext:** `first(import_first, bucket)` i `last(...)` w agregacie hierarchicznym biorą wartość najwcześniejszego wiersza **także gdy jest NULL**, więc godzina, w której pierwsza lub ostatnia minuta nie ma energii (np. cała minuta błędu licznika), dostałaby `import_first/last` = NULL, a przyrost dla tej godziny byłby NULL (następna godzina liczy się poprawnie, bo `LAG` pomija takie wiersze). Wykryły to testy `energy_ext_1h` (tam naprawione `FILTER (WHERE ... IS NOT NULL)` przed wdrożeniem). **W produkcji `energy_1h` dziś nie ma takich godzin** (0 z 29 godzin, 0 z 1 582 minut bez energii), więc nic nie jest zepsute, ale to błąd utajony. Propozycja do decyzji architekta: migracja 009 odtwarzająca `energy_1h` (z `FILTER`) razem z zależnymi widokami; nie robiłem tego bez decyzji.
3. **Drugi licznik w v2 nie mieści się w zakresie 0–99:** blok licznika v2 jest pełny (offsety 0–49), a kolejny licznik miałby bazę 60, czyli rejestry 60–109, poza „Input Registers 0–99” z `docs/modbus-map.md`. Przy dodaniu drugiego licznika (etap 3) trzeba zwiększyć `awTcpInputRegs` w PLC i zakres zapytania (110 < limit 125). Atrapa PLC ma od teraz 120 rejestrów; test dwóch liczników zmieniony (zapytanie 110).
4. **Stan kompresji nie zmierzony:** w planie obiecałem pomiar po kompresji doby 24.11. Kawałek z 24.11 kompresuje się dopiero po 26.11 00:00 (kompresja po 1 dniu od końca kawałka), więc dziś jest tylko stary pomiar (kawałek z 23.11: 25 razy, ale to 25 tys. wierszy). Pomiar zrobię w kroku 4 i wpiszę do raportu. Przy 20 wierszach/s: 1 728 000 wierszy na dobę (+54% względem 13/s), nieskompresowane ok. 190 B/wiersz, czyli ok. 330 MB/dobę; po kompresji szacunek 5–10 B/wiersz, 9–17 MB/dobę (do weryfikacji).
5. **Wiersz-wartownik i nazwy** bez zmian względem k7; `reactive_1h_calc.gap_before` z planu to w rzeczywistości dwie flagi `pos_gap_before` i `neg_gap_before` (licznik n2 i n4 mogą mieć różne luki).
6. **Restart Mosquitto** wykonałem osobno po wdrożeniu (zmiana limitu kolejki wymaga restartu, sam `up -d` go nie robi); zapisane w `docs/ops` przy tabeli buforów.
7. **Pierwszy krok n4 o 100 varh (potwierdzenie znaku):** w tym kroku nieobserwowalne (n4 jest czytany dopiero w mapie v2; przy Q ≈ −9 var krok następuje co ok. 11 h). Zapiszę w raporcie kroku 4, czy nastąpił.
8. W katalogu roboczym laptopa były niezatwierdzone zmiany `plc/src/*` i `docs/modbus-map.md`: zacommitowane osobnym commitem `d5ed660` wg U-2.

## Co dalej (PLC-2) i co sprawdzę po przełączeniu

**Gotowość:** collector na komputerze czyta 0–59 i obsługuje v1 i v2; każda inna wersja daje `link_status` 3. PLC można przełączać po uzgodnieniu terminu z Grzegorzem i architektem. Zachowanie przy przełączeniu: download zerwie połączenie na kilka do kilkunastu sekund (8–18 s przy poprzednich), potem collector wróci sam, bez restartu; zmieni się `map_version` i `meter_error_count` się wyzeruje (dodam kolejne okno `plc_program_download` migracją po fakcie, granice z bazy).

Po przełączeniu sprawdzę (krok 4 planu architekta): 20 wierszy/s w stanie OK, wartości nowych metryk zgodne z podglądem online (THD I ok. 140%, kąt ok. −50,6°, temperatura ok. 30 °C, czas pracy rosnący, energie bierne: n2 = 0, n4 ≈ 4 500 varh), cos φ z kąta ≈ 0,64 przy PF 0,37, brak pominiętych poprawnych wartości, agregaty `energy_ext_*` równe surowym, harness paneli i panele z danymi v2, pomiar kompresji i rozmiaru, okno `plc_program_download`, raport `e2-plc2-k2-step4`.
Jeśli po przełączeniu cokolwiek pójdzie nie tak, awaryjnie wystarczy wgrać do PLC wersję v1 (collector obsługuje obie).

## Prośby i pytania do architekta

1. **Decyzja:** migracja 009 odtwarzająca `energy_1h` z `FILTER` (ustalenie 2), teraz czy w etapie 4?
2. **Pytanie:** czy `reactive_1h_calc` ma zostać (widok dla analityki z ostrzeżeniem), czy przepisać na funkcję z zakresem (jak `energy_1m_calc` w decyzji z k6)?
3. Zakres rejestrów dla drugiego licznika (ustalenie 3) do planu etapu 3.

## Stan testów

Końcowy pełny przebieg na komputerze po ostatnim commicie kodu (`261213c`): **482 z 482** (3 testy wydajnościowe pomijane w zwykłym przebiegu, 10 min 25 s), bez resztek `aip-test`; ten sam kod jest wdrożony i działa na produkcji.
