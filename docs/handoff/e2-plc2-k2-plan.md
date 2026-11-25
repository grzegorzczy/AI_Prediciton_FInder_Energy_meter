# E2-PLC2, krok 2: strona aplikacji (collector, ingest, baza, panele): plan
Status: DO PRZEGLĄDU (tylko plan, nic nie wykonane)

Podstawa: `e2-plc2-plan.md` w całości, w tym „Mapa Modbus TCP v2” i „Wyniki PLC-1” (25.11.2026), `docs/modbus-map.md` (v1), `docs/status-codes.md`, `config/devices.yaml`, `CLAUDE.md`; kod: `services/collector/src/collector/{config,evaluator,codec,main}.py`, `services/ingest/src/ingest/{config,validate}.py`, `grafana/generate.py`, `db/migrations/002–005`.
Zasady twarde bez zmian: collector tylko czyta FC04 (do PLC nie piszemy), dane urządzeń tylko w `config/devices.yaml` (reguła 3), `mem_limit` kontenerów, bez `sudo`, bez ruszania smartWARE, bez czytania `.env`; interfejs Grafany po polsku, kod i nazwy po angielsku, brak „przewidywania awarii” w nazwach.
**Nie ruszam `docs/modbus-map.md`** (zmienia architekt): czego potrzebuję, jest w sekcji „Czego potrzebuję od architekta”.

## Cel kroku

1. Collector obsługuje mapę **v1 i v2 jednocześnie**: `map_version` 1 jak dziś, 2 dodatkowo rejestry 44–59, każda inna wersja → `link_status` 3. Przełączenie PLC z v1 na v2 (i z powrotem) nie wymaga zmiany konfiguracji ani restartu collectora.
2. Nowe metryki w `config/devices.yaml` (nazwy, jednostki, rozdzielczość, zakresy wiarygodności), ingest przyjmuje je bez zmian w logice walidacji.
3. Baza: dwa nowe agregaty ciągłe (jakość i energia bierna) i widok przyrostu energii biernej; migracja z oknem `plc_program_download` z 25.11.
4. Panele (po polsku) w czterech dashboardach; dla danych sprzed v2 brak wartości = brak danych, nigdy zero.
5. Wdrożenie collectora v1+v2 **przed** przełączeniem PLC na v2, z dowodem, że na v1 nic się nie zmieniło.

**Sprawdzalny wynik:** pytest zielony na komputerze (dekodowanie v2, przełączanie v1↔v2 w locie, zakresy, kadencja wolnych metryk, agregaty, panele); po wdrożeniu collectora na v1: 13 wierszy/s, `link_status` bez luk, 0 błędów, żadnych nowych metryk w bazie; po przełączeniu PLC na v2 (krok 3 architekta i Grzegorza): 18,2 wiersza/s, nowe metryki w bazie z wiarygodnymi wartościami, panele pokazują dane.

## Stan wyjściowy (zmierzone 25.11.2026)

| Pozycja | Wartość |
| --- | --- |
| Collector dziś | jedno zapytanie FC04 0–43 (44 rejestry), `map_version` = 1 wymagana, 13 wierszy/s w stanie OK |
| `docs/modbus-map.md` | „Zakres: Input Registers 0–99”, rejestry 44–59 „zarezerwowane (0)”, maks. jedno zapytanie „0–43” (to ograniczenie dotyczy użytej wersji, nie limitu protokołu: FC04 pozwala na 125 rejestrów) |
| Baza | 1,21 mln wierszy `measurements`, 222 MB (wszystkie kawałki, razem z indeksami), **ok. 190 B/wiersz nieskompresowany**; skompresowany jest na razie tylko kawałek 23.11 (4 808 kB → 192 kB, 25 razy, ale to tylko 25 tys. wierszy: za mało na wniosek o stopniu kompresji) |
| Dysk | 869 GB wolne z 938 GB |
| Okno programu z 25.11 | `link_status` ≠ 0 od 08:16:10,574 do 08:16:18,577 UTC (10 wierszy, 8,0 s), pierwszy wiersz OK 08:16:20,611; `meter_error_count` wyzerowany (54 → 0), czyli 09:16 czasu lokalnego |

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| P2-a | Zakres odczytu FC04 | **jedno zapytanie 0–59 (60 rejestrów) dla obu wersji**, zawsze | Mieści się w jednym zapytaniu (limit 125); nie trzeba znać wersji przed odczytem; przełączenie v1↔v2 nie zmienia konfiguracji. Na v1 rejestry 44–59 powinny dać 0 (zakres 0–99 w mapie), **ale tego nie sprawdziłem na PLC**: pierwszy krok wykonania to `mbpoll -t 3 -r 0 -c 60` (tylko odczyt FC04, jak w k5) na obecnym PLC v1. Jeśli serwer odrzuci (wyjątek „illegal data address”), zapas: czytam 0–43, a przy `map_version` = 2 drugie zapytanie 44–59 w tym samym cyklu (wtedy dwa zapytania na cykl tylko dla v2) |
| P2-b | Konfiguracja wersji map | `plc.map_versions: [1, 2]` zamiast `plc.map_version: 1`; pola v2 w profilu oznaczone `since: 2` | Reguła 3: wersje i pola w configu; kontrola nakładania rejestrów i zakresu zapytania obejmuje wszystkie pola (także v2). Test konfiguracji i metadane PLC w `devices.meta` (`map_versions`) do aktualizacji |
| P2-c | Kadencja temperatury i czasu pracy | **co 10 s (`publish_every_s: 10`)**, pozostałe nowe kanały co 1 s | PLC odświeża je co 10 s, więc zapis co 1 s to 9 z 10 powielonych wierszy; różnica w bazie ok. 9% wierszy (18,2 zamiast 20 na sekundę). Liczy to zegar collectora (`now − ostatnia publikacja ≥ okres − połowa okresu odczytu`), pierwsza wartość po `meter_status` = 0 idzie od razu. Alternatywa (co 1 s) jest prostsza i nie wymaga stanu w ewaluatorze, kosztuje 1,8 wiersza/s |
| P2-d | Agregaty nowych metryk | **osobne agregaty ciągłe `energy_ext_1m` i `energy_ext_1h`** (hierarchiczny), bez zmiany `energy_1m` i `energy_1h` | Agregatu ciągłego nie da się rozszerzyć o kolumny bez usunięcia i utworzenia od nowa, a to groziłoby utratą starszych wiaderek niż 90 dni surowych danych (`energy_1m` ma retencję 1 rok). Nowe agregaty startują od danych v2 |
| P2-e | Energia bierna w panelach | przyrost licznika n2/n4 z agregatu godzinnego (widok `reactive_1h_calc`, `LAG`, reset i luka jak w `energy_1h_calc`), rozdzielczość 100 varh z `devices.meta`; **opcjonalnie** druga miara: całka mocy biernej z podziałem na znak (`reactive_pos_sum`, `reactive_neg_sum` w agregacie), bo licznik zmienia stan co 100 varh, a przy Q ≈ −9 var to jeden krok na ok. 11 godzin | Przyrost licznika jest wzorcem, ale przy obecnym obciążeniu będzie prawie zawsze 0 (jak w kontroli energii czynnej, K6-e). Całka mocy daje bieżący obraz. Do decyzji, czy robić całkę (kosztuje dwie kolumny i jeden panel) |
| P2-f | Zakresy wiarygodności | `valid_range: [min, max]` przy metrykach w `devices.yaml`, sprawdzane **w collectorze**; wartość spoza zakresu nie jest publikowana (jak NaN dziś: pomijana, WARNING raz na zmianę, nie w każdym cyklu); ingest bez zmian | Ingest nie zna fizyki urządzeń (reguła 3), a odrzucenie w ingeście traci wartość bez śladu przy urządzeniu. Wartości zakresów w tabeli niżej to **propozycje**, nie fakty o liczniku (reguła 7): proszę architekta o potwierdzenie z karty katalogowej Findera |
| P2-g | Bufory przy większej liczbie wierszy | `COLLECTOR_BUFFER_MAX` 20 000 → 30 000; w Mosquitto `max_queued_messages` 50 000 → 75 000 (limit bajtów 20 MB wystarcza) | Przy 18,2 wiersza/s dotychczasowe limity dawałyby ok. 18 min (collector) i ok. 46 min (ingest) zamiast 25 i 64 min; zmiana zachowuje te czasy. Pamięć: 30 000 komunikatów po ok. 200 B to ok. 6 MB, w limicie 128 MB |
| P2-h | Przełączenie wersji w locie | zmiana `map_version` między kolejnymi cyklami zapisuje INFO i **zeruje rozgrzewkę i zegary wolnych metryk**; link do PLC nie jest przerywany | Po downloadzie PLC i tak zrywa połączenie (rozgrzewka z mocy obecnych reguł), ale chcę mieć pewność dla zmiany bez zerwania połączenia; test w locie jest w liście testów |

## 1. Collector (v1 i v2)

**Konfiguracja (`config/devices.yaml` i `collector/config.py`):**
- `plc.read: {start: 0, count: 60}` (P2-a), `plc.map_versions: [1, 2]`; `PlcConfig.map_versions` zamiast `map_version`; błąd konfiguracji, gdy lista pusta lub powtórki.
- Pola v2 w profilu `finder_7m24` z atrybutem `since: 2` (domyślnie 1): wszystkie istniejące pola bez zmian. Walidacja `_spans` i nakładania sprawdza wszystkie pola (v1 i v2) względem zapytania 0–59 i bloku (offsety 34–49 w bloku 50).
- Opcjonalne atrybuty pola: `publish_every_s` (P2-c) i `valid_range` (P2-f).

**Ewaluator (`evaluator.py`):**
- `map_version` z rejestru 2: nie należy do `map_versions` → `LinkStatus.MAP_VERSION_MISMATCH` (jak dziś, bez rozgrzewki).
- Dla wersji należącej do listy: publikowane są pola z `since <= wersja`. Reguły ważności bez zmian: nowe wartości **tylko przy `meter_status` = 0** i zgodnym numerze seryjnym (te same gałęzie co dla pomiarów v1); przy `status` ≠ 0 zamrożone wartości nie są publikowane. Model 5 wierszy na sekundę błędu zostaje.
- Energia bierna jak czynna: `regs.energy_wh(mantysa, wykładnik)` (mantysa × 10^wykładnik, arytmetyka całkowita), nazwa metody ogólna (`energy_scaled`), jednostka `varh`. Ujemny kąt jest poprawną wartością (nie jest odrzucany ani zaokrąglany do zera).
- Kadencja `publish_every_s` (P2-c): słownik ostatnich publikacji (urządzenie, metryka) → czas z wstrzykiwanego zegara; zerowany po błędzie odczytu, po zmianie `map_version` i przy wyjściu licznika ze stanu OK (po powrocie do OK pierwsza wartość idzie od razu).
- Pomijanie wartości niewiarygodnych: nieskończone, NaN (jak dziś) oraz spoza `valid_range`; WARNING raz na zmianę stanu „pomijam”, a nie w każdym cyklu (dziś `skipped` loguje się w każdym cyklu).
- Log INFO przy zmianie wersji mapy: `map_version 1 -> 2`.

**Sterownik (`drivers/modbus_plc.py`):** bez zmian w logice, czyta `read_count` z konfiguracji (60); dalej wyłącznie FC04. Testy `test_no_write` i atrapa PLC pilnują braku zapisu.

**Dekoder (`codec.py`):** typy istniejące wystarczą (`real32`, `int32`, `int16`); dochodzi tylko ogólna nazwa `energy_scaled`. Czas pracy jako REAL (`real32`, s) zgodnie z `e2-plc2-plan.md`; jeśli licznik ma wersję całkowitą, zmiana typu w configu (offset i typ już w configu).

## 2. Nowe metryki (`config/devices.yaml`), ingest

| Metryka (temat MQTT) | Rejestr / offset w bloku | Typ | Jednostka w ładunku | Kadencja | `valid_range` (propozycja, P2-f) |
| --- | --- | --- | --- | --- | --- |
| `reactive_import_varh` | 44–45, 46 (mantysa, wykładnik; offset 34, 36) | DINT, INT | `varh` | 1 s | bez zakresu (licznik rosnący; reset wykrywają widoki) |
| `reactive_export_varh` | 47–48, 49 (offset 37, 39) | DINT, INT | `varh` | 1 s | jw. |
| `thd_voltage` | 50–51 (40) | REAL | `%` | 1 s | 0 … 100 |
| `thd_current` | 52–53 (42) | REAL | `%` | 1 s | 0 … 1000 (zmierzone 140,22% przy zasilaczu impulsowym) |
| `phase_angle` | 54–55 (44) | REAL | `°` | 1 s | −180 … 180 (zmierzone −50,58°; ujemny = pojemnościowy, zgodnie z Q < 0) |
| `meter_temperature` | 56–57 (46) | REAL | `°C` | 10 s | −40 … 125 (propozycja do potwierdzenia z kartą Findera) |
| `run_time` | 58–59 (48) | REAL | `s` | 10 s | 0 … 4,0 × 10^9 |

- Nazwy: małe litery i `_` (zgodnie z ograniczeniem `^[a-z0-9_]+$` w bazie i ingeście), kolizji z istniejącymi nie ma. Jednostki `°` i `°C` to znaki spoza ASCII; ładunek JSON i kolumna `unit` (TEXT, limit 16 znaków w ingeście) je przyjmują, test to pilnuje (JSON przez `ensure_ascii` nie psuje wartości).
- **Ingest:** walidacja jest ogólna (nazwa wg wzorca, `value` skończona liczba, `unit` tekst do 16 znaków, `source` zgodne z urządzeniem), więc nowe metryki przejdą bez zmiany logiki; potwierdzam to testem. Zmiany w ingeście: tylko `devices.meta` licznika (`reactive_resolution_varh` obok `energy_resolution_wh`; z `resolution_varh: 100` przy energiach biernych w profilu) i `devices.meta` PLC (`map_versions: [1, 2]`); testy `test_devices_sync.py` i `test_ingest_config_loader.py` do zmiany oczekiwań.
- Zakresy wiarygodności nie trafiają do bazy ani ingestu: są wyłącznie w `devices.yaml` i używa ich collector (P2-f).

## 3. Model wierszy na sekundę po v2

| Stan | Dziś (v1) | Po v2 (P2-c: temperatura i czas pracy co 10 s) | Po v2 (gdyby wszystko co 1 s) |
| --- | --- | --- | --- |
| Sprawny licznik (OK) | **13** (`link_status` + 12 licznika) | **18,2 średnio**: 18 wierszy w 9 z 10 s, 20 wierszy w 1 z 10 s (`link_status` 1 + 12 + 2 energie bierne + THD U, THD I, kąt + temperatura i czas pracy raz na 10 s) | 20 |
| `meter_status` ≠ 0 | 5 | 5 (nowych wartości nie publikujemy) | 5 |
| PLC niedostępny | 1 | 1 | 1 |

Wynik końcowy do `docs/status-codes.md` (sekcja o modelu wierszy) i do `docs/ops` (bufory); test dokumentu sprawdza liczby.

## 4. Wpływ na dysk i bufory

- Wiersze na dobę: 13/s = 1 123 200; 18,2/s = **1 572 480 (+40%)**; (20/s = 1 728 000, +54%). Surowe dane przy retencji 90 dni: 101 mln wierszy dziś, **141 mln po v2**.
- Rozmiar: zmierzone **ok. 190 B/wiersz nieskompresowany** (z indeksami), więc 213 MB/dobę dziś i **299 MB/dobę po v2** (+86 MB), a w nieskompresowanych kawałkach (do 2 dób przed kompresją po 1 dniu) ok. 0,6 GB. Po kompresji **nie mam wiarygodnego pomiaru** (jedyny skompresowany kawałek ma 25 tys. wierszy i dał 25 razy, czyli ok. 8 B/wiersz); prawdziwy współczynnik zmierzę po kompresji doby 24.11 i wpiszę do raportu. Szacunek ostrożny 5–10 B/wiersz: **8–16 MB/dobę** po v2, 0,7–1,4 GB na 90 dni. Dysk: 869 GB wolne.
- Pamięć bazy: bez zmian w konfiguracji (limit 1,5 GB, mierzone 150–180 MiB).
- Bufory: patrz P2-g; tabela „Utrata danych przy przerwach” w `docs/ops` do aktualizacji liczb.

## 5. Baza: migracje

| Migracja | Zawartość |
| --- | --- |
| `006_data_windows_plc1_download.sql` | okno `plc_program_download` dla dzisiejszego wgrania programu (PLC-1): **2026-11-25 08:16:10,574 – 08:16:18,577 UTC** (pierwszy i ostatni wiersz `link_status` ≠ 0, 10 wierszy; granice z bazy), opis „Download programu PLC (PLC-1: kanały jakości, temperatury i czasu pracy), reset liczników FB”, `exclude_from_analytics` = TRUE. W treści migracji: pierwszy wiersz OK po oknie 08:16:20,611 |
| `007_energy_ext_aggregates.sql` (bez transakcji, instrukcje idempotentne jak 002) | `energy_ext_1m` z `measurements` (`WHERE metric IN (...)`): `thd_voltage_n/_sum/_min/_max`, `thd_current_n/_sum/_min/_max`, `phase_angle_n/_sum/_min/_max`, `phase_cos_sum` (suma `cos(radians(kąt))`, addytywna: daje dokładną średnią cos φ), `temperature_n/_sum/_min/_max`, `run_time_first/_last/_min/_max`, `reactive_import_first/_last/_min/_max`, `reactive_export_first/_last/_min/_max` (+ `reactive_pos_sum`, `reactive_neg_sum` jeśli P2-e z całką). `energy_ext_1h` hierarchiczny z `energy_ext_1m`. Polityki jak w 002: odświeżanie 7 dni/1 min i 30 dni/15 min, kompresja 14 i 60 dni, retencja 1 rok i bez limitu, czas rzeczywisty |
| `008_energy_ext_views.sql` | `reactive_1h_calc`: przyrost n2 i n4 względem poprzedniego wiaderka z odczytem (`LAG` po wierszach z licznikiem), reset, `gap_before`, `bucket_complete`, `resolution_varh` z `devices.meta` (NULL gdy brak, nie domysł), `GRANT SELECT` dla `app_reader` |

Wiaderka powstają tylko dla godzin z danymi v2 (filtr po metrykach), więc dla okresu sprzed v2 nie ma wierszy: panele pokażą „Brak danych”, a nie zero. Wdrożenie migracji wchodzi w krok „collector na komputerze, PLC jeszcze na v1”: agregaty będą puste do czasu przełączenia, co nie przeszkadza niczemu.

## 6. Panele (`grafana/generate.py`, po polsku)

| Dashboard | Zmiana |
| --- | --- |
| **Jakość energii** | nowy panel „**THD napięcia (THD U)**” [%] i osobny „**THD prądu (THD I)**” [%] (różne skale: THD U kilka %, THD I ok. 140%; średnia i maksimum z `energy_ext_1m`); „**Kąt U–I**” [°] (min, średnia, maks.; opis: ujemny kąt = obciążenie pojemnościowe, zgodnie z Q < 0); panel „Współczynnik mocy (cos φ)” **przemianowany na „Współczynnik mocy PF”** z dwiema seriami: PF (z `energy_1m`) i **cos φ = cos(kąt)** (średnia `phase_cos_sum / phase_angle_n`), z opisem: PF = cos φ / √(1 + THD_I²), więc przy THD I ≈ 140% PF 0,37 ≠ cos φ 0,64 (zmierzone w PLC-1: kąt −50,58°, THD I 140,22%). Opis THD I: przy małym prądzie względem zakresu licznika (80 mA wobec 40 A) wartość może być niepewna |
| **Energia i profil** | „**Energia bierna: przyrost licznika**” (godzinowo i dobowo, n2 i n4 jako dwie serie) z `reactive_1h_calc`; opis: rozdzielczość 100 varh, przy obecnym obciążeniu (Q ≈ −9 var) licznik zmienia stan raz na ok. 11 godzin, więc słupek 0 oznacza „brak kroku licznika”, a nie „brak energii biernej”. Wartości pomocnicze: całka mocy biernej (jeśli P2-e) |
| **Stan i diagnostyka** | kafelek „**Temperatura licznika**” [°C] (ostatnia wartość, bez progów: nie znam granic z karty katalogowej), wykres temperatury, kafelek „**Czas pracy licznika**” w dobach (`run_time / 86400`, jednostka własny sufiks „ d”) i wykres z widocznymi zerowaniami (restart licznika); opis „Wiersze na minutę” z nowym modelem (1 080 przy 18 wierszach na sekundę, itd.) |
| **Licznik na żywo** | druga linijka kafelków: „THD U”, „THD I”, „Kąt U–I”, „Temp.”; wykresy THD U, THD I i kąta; tabela „Wartości w oknie” rozszerzona o te wielkości (i wyższa, by nie było przewijania; K7-W-8) |
| Wszystkie | dla okresu sprzed v2: zapytania nie używają `COALESCE(…, 0)`, kafelki mają `noValue` „Brak danych (mapa v1)”; układ rzędów nadal zajmuje 24 kolumny (test); generator nadal jedynym źródłem JSON |

Wszystkie nowe zapytania czytają agregaty (`energy_ext_1m/_1h`, `reactive_1h_calc`) dla zakresów dłuższych niż doba; panele „na żywo” czytają `measurements` w zakresach do kilku godzin, tak jak dziś. Własne zakresy paneli (jak w k7d) tylko tam, gdzie potrzebne, liczone w SQL.

## 7. Okno adnotacji `plc_program_download` (25.11)

Migracja 006 (wyżej). Granice z bazy, nie z pamięci: `link_status` ≠ 0 od 2026-11-25 08:16:10,574 do 08:16:18,577 UTC; pierwszy wiersz OK 08:16:20,611; `meter_error_count` 54 → 0 w tym oknie. **Kolejne okno**, przy przełączeniu PLC na v2 (PLC-2), architekt i Grzegorz robią download, a ja dopisuję je trzecią migracją po fakcie (granice znów z bazy).

## 8. Kolejność wdrożenia i kontroli

1. **Odczyt próbny (tylko FC04, bez wdrożenia):** na komputerze `mbpoll -m tcp -a 1 -t 3 -0 -r 0 -c 60 -1 192.168.0.246` na obecnym PLC v1 (P2-a): czy 60 rejestrów jest odczytywalnych, 44–59 = 0, `map_version` = 1.
2. Kod i testy na laptopie (kroki: collector, config i test configu; ewaluator i atrapa v2; ingest meta; migracje; generator i panele), pytest na komputerze, każdy krok jako mały commit, `git pull --ff-only` na komputerze (tylko to, co w `origin/main`).
3. **Wdrożenie:** `docker compose up -d --build` (R-1; migracje 006–008, Grafana wczytuje JSON), sprawdzenie `schema_migrations` (8 wierszy).
4. **Kontrola „na v1 nic się nie zmieniło”** przez ok. 20 minut: 13 wierszy/s (`SELECT` po metrykach), 0 sekund bez `link_status`, `rejected = 0` w ingeście, brak metryk v2 w bazie, zużycie pamięci collectora i ingestu, 0 błędów w logach, harness paneli na produkcji (0 błędów; panele v2 puste z komunikatem „Brak danych (mapa v1)”). Dopiero po tym zgłaszam gotowość do PLC-2.
5. **PLC-2 (architekt + Grzegorz):** `FB_EnergyMeter`, `PRG_ModbusTcpMap` v2, download, `mbpoll` 0–59. Collector zrywa połączenie na kilka sekund (jak 24.11 i 25.11), potem wraca z `map_version` 2 bez restartu.
6. **Moja kontrola danych v2 (krok 4 planu architekta):** 18,2 wiersza/s, wartości nowych metryk zgodne z podglądem online (THD I 140%, kąt −50,6°, temperatura ok. 30 °C, czas pracy rosnący o 10 s co 10 s, energie bierne), cos φ z kąta ≈ 0,64 przy PF 0,37, zakresy wiarygodności nie odrzucają poprawnych danych (0 pominiętych), agregaty `energy_ext_*` zgodne z surowymi, harness paneli, pomiar rozmiaru po kompresji, nowe okno `plc_program_download`, raport `e2-plc2-k2-report.md`.

## 9. Testy (pytest, bez sprzętu)

| Obszar | Co sprawdza |
| --- | --- |
| Dekodowanie v2 (`test_evaluator.py`, atrapa PLC rozszerzona o blok 34–49) | wartości REAL i DINT/INT z mantysy i wykładnika dla znanych słów (kąt −50,58°, THD I 140,22%, THD U 2,34%, temperatura 30,2 °C, czas pracy 1 256 171 s, energie bierne), starsze słowo pierwsze; **kąt ujemny publikowany bez zmiany znaku**; atrapa koduje niezależnie od collectora |
| Wersje | v1: żadnych metryk v2 mimo niezerowych rejestrów 44–59 w obrazie; v2: komplet; każda inna wersja (0, 3, 65535): `link_status` 3 i tylko status, bez rozgrzewki; zapytanie 60 rejestrów do atrapy v1 z zerami 44–59 działa |
| Przełączanie w locie | v1 → v2 → v1 między cyklami bez zerwania połączenia: metryki v2 pojawiają się i znikają, INFO o zmianie, zegary wolnych metryk zerowane; po „downloadzie” (zerwanie, rozgrzewka, powrót z inną wersją) bez luk poza oczekiwaną rozgrzewką |
| Ważność | `status` ≠ 0 lub inny numer seryjny: ani jednej metryki v2; model 5 wierszy na sekundę błędu bez zmian; powrót do OK publikuje temperaturę i czas pracy od razu |
| Kadencja | temperatura i czas pracy raz na 10 s przy okresie 1 s (dokładnie 2 z 20 wierszy co 10 cykli), z jitterem okresu; pozostałe nowe metryki w każdym cyklu; średnia 18,2 wiersza/s w teście 100 cykli |
| Zakresy | wartość spoza `valid_range` i NaN nie są publikowane, WARNING raz na zmianę, nie co cykl |
| Konfiguracja | `map_versions`, `since`, nakładanie rejestrów v2, zapytanie 0–59, kontrola nakładania z nagłówkiem; stare asercje (`read_count == 44`, `map_version == 1`) zmienione świadomie; `test_devices_yaml.py` i test spójności kodu z `docs/status-codes.md` |
| Ingest | nowe nazwy, jednostki `°`, `°C`, `%`, `varh`, `s` przechodzą; jednostka dłuższa niż 16 znaków nadal odrzucona; `devices.meta` (`reactive_resolution_varh`, `map_versions`) |
| Bezpieczeństwo (zasada 1) | `test_no_write` bez zmian: do atrapy dociera wyłącznie FC04 także dla zapytania 60 rejestrów |
| Baza | `energy_ext_1m/_1h` równe przeliczeniu z surowych danych (losowe dane z lukami, `phase_cos_sum`), hierarchia, czas rzeczywisty, polityki, idempotencja i przerwanie migracji 007 (jak K6-U3), `reactive_1h_calc`: zwykły przyrost, reset, luka, NULL bez rozdzielczości w `meta`; okno 006 z dokładnymi granicami |
| Panele | harness przez API Grafany dla nowych paneli (dane syntetyczne z v2 dla jednego licznika i bez v2 dla drugiego: brak wierszy, nie zera), układ 24 kolumn, tytuły bez obcinania, panel „Współczynnik mocy PF” z cos φ, opisy po polsku, brak fraz z zasady 8; wydajność na roku danych (zapytania < 1 s; dane v2 w zbiorze perf) |
| Dokumenty | liczby modelu wierszy w `docs/status-codes.md`, bufory w `docs/ops` |

## 10. Pliki

```
config/devices.yaml                                   map_versions, pola v2 (since, publish_every_s, valid_range), resolution_varh
services/collector/src/collector/config.py            map_versions, since/publish_every_s/valid_range, walidacja nakładania
services/collector/src/collector/evaluator.py         wersje map, pola v2, kadencja, zakresy, log zmiany wersji
services/collector/src/collector/codec.py             energy_scaled (nazwa ogólna)
services/collector/src/collector/main.py              ostrzeżenia o pominiętych metrykach raz na zmianę
services/ingest/src/ingest/config.py                  meta: reactive_resolution_varh, map_versions
db/migrations/006_…, 007_energy_ext_aggregates.sql, 008_energy_ext_views.sql
grafana/generate.py, grafana/dashboards/*.json        panele z sekcji 6
docker-compose.yml, config/mosquitto/*                bufory (P2-g)
tests/fakes/modbus_plc.py                             blok 34–49 v2, map_version v2
tests/collector/*, tests/ingest/*, tests/config/*     wg sekcji 9
tests/db/test_energy_ext_*.py, tests/dbtools.py       agregaty, widok, dane v2 do paneli i perf
tests/grafana/*                                       nowe panele, dane v2
docs/status-codes.md, docs/data-model.md, docs/grafana.md, docs/ops/jumo-ipc-setup.md
docs/handoff/e2-plc2-k2-report.md
```
**Poza moją ręką:** `docs/modbus-map.md` (architekt) i `plc/src/*` (Grzegorz): w katalogu roboczym na laptopie `plc/src/GVL_Meter.st` i `plc/src/PRG_ModbusTcpMap.st` mają niezatwierdzone zmiany (PLC-1) oraz nowy zrzut `08-plc2-codesys-nowe-kanaly.png`; **nie commituję kodu PLC bez polecenia** (zrzut i review już są w repozytorium).

## Czego potrzebuję od architekta

1. **`docs/modbus-map.md` do v2** (zgodnie z `e2-plc2-plan.md`): nowa tabela offsetów 34–49, zdanie „maks. jedno zapytanie 0–59 (60 rejestrów)” zamiast „0–43”, `MAP_VERSION` = 2 i opis zachowania collectora przy v1 i v2 (jednoczesna obsługa). Do czasu przełączenia PLC dokument może zostać w v1 z adnotacją.
2. **Potwierdzenie, że rejestry 44–59 są odczytywalne na PLC v1** (wynik mojego `mbpoll -c 60` w kroku 1 wykonania rozstrzygnie, ale potrzebuję wiedzieć, czy architekt zna powód, dla którego miałoby być inaczej, np. rozmiar tablicy `awTcpInputRegs`).
3. **Zakresy wiarygodności** z karty katalogowej Findera dla temperatury, THD i czasu pracy (moje wartości to propozycje, nie fakty o liczniku).
4. **Znaczenie n2 i n4 (energia bierna):** nazwy `reactive_import` i `reactive_export` są z planu; proszę o potwierdzenie, który kierunek (indukcyjna/pojemnościowa) jest który, żeby opisy paneli nie sugerowały odwrotnego znaku.
5. **Decyzje P2-a…P2-h** (szczególnie P2-c kadencja, P2-d osobne agregaty, P2-e całka mocy biernej, P2-g bufory).

## Ryzyka i założenia (bez potwierdzenia)

- **Zapytanie o 60 rejestrów na PLC v1** nie jest sprawdzone; jeśli serwer zgłosi wyjątek, collector zobaczyłby błąd odczytu i `link_status` = 1 w całym czasie. Dlatego krok 1 wykonania (odczyt próbny) i zapas P2-a, a wdrożenie collectora dopiero po jego wyniku.
- **Zakresy wiarygodności** są moimi propozycjami: zbyt wąskie zakresy odrzucałyby prawdziwe dane (np. THD prądu 140%); dlatego ich liczba odrzuconych wartości jest w kontroli po przełączeniu.
- **THD prądu** przy 80 mA może być niewiarygodne (ryzyko z planu architekta); zapisujemy, opisujemy w panelu, nie oceniamy.
- **Czas pracy jako REAL** traci rozdzielczość 1 s po ok. 194 dniach (2^24 s); obecne 1 256 171 s ma jeszcze zapas, ale panel dni nie jest sprawdzalny co do sekundy.
- **Przełączanie PLC z v1 na v2** zrywa połączenie na kilka do kilkunastu sekund (jak 24.11 i 25.11: 18 s i 8 s) i zeruje `meter_error_count`: kolejne okno `plc_program_download` w danych, plus rozgrzewka collectora.
- **Kompresja** nowych wierszy nie jest zmierzona (jedyny skompresowany kawałek jest za mały); szacunki dysku są rzędu wielkości.
- **Znak i konwencja kąta** wg Findera: w PLC-1 zmierzone −50,58° przy Q < 0; opisy paneli mówią „ujemny = pojemnościowy” tylko dlatego, że zgadza się to ze znakiem Q w tym jednym pomiarze.
- **Nowe agregaty** startują od danych v2, więc „rok historii” dla THD i energii biernej zacznie się od dnia przełączenia.
- Agregaty ciągłe i `LAG` w widoku godzinowym: przy roku danych godzinowych wystarczająco szybkie (K7: ok. 100 ms), ale pomiar na roku danych v2 wchodzi do testu wydajności.
- Poprawki, które ujawnią się dopiero po przełączeniu na prawdziwy PLC (np. NaN w którymś kanale), będą w raporcie i w osobnej poprawce, nie w tym kroku.

## Kryteria zaliczenia

| Kryterium | Wymóg |
| --- | --- |
| Zasada 1 | do PLC wyłącznie FC04 (test), `mbpoll` tylko `-t 3` |
| v1 po wdrożeniu | 13 wierszy/s, `link_status` bez luk, 0 błędów, 0 nowych metryk, `rejected` = 0 przez ok. 20 min |
| v2 po przełączeniu | 18,2 wiersza/s (18/20 na przemian), nowe wartości zgodne z podglądem online i z kontrolą spójności z PLC-1 (cos φ z kąta ≈ 0,64 przy PF 0,37), 0 pominiętych poprawnych wartości |
| Wersje | v1 i v2 jednocześnie; każda inna wersja daje `link_status` 3; przełączenie w locie przetestowane |
| Ważność | nowe wartości tylko przy `meter_status` = 0 i zgodnym numerze seryjnym; brak wartości = brak danych w panelach (nie zero) |
| Baza | `energy_ext_*` równe przeliczeniu z surowych danych; migracje idempotentne; okno 25.11 z granicami z bazy |
| Panele | nowe panele zwracają dane na prawdziwej bazie po v2 i „Brak danych (mapa v1)” przed; zapytania < 1 s na roku danych; „Współczynnik mocy PF” z cos φ; polskie opisy |
| Izolacja | `StartedAt` smartWARE bez zmian, brak nowych portów, tylko `git pull --ff-only`, `git status` czysty po `pull` |

## Poza zakresem

Zmiany w PLC i `docs/modbus-map.md` (architekt i Grzegorz), liczniki o podwyższonej rozdzielczości (30462–30485, etap 4), koszty i taryfy (etap 4), anomalie i alarmy (etapy 4–5), diagnoza E2-PLC1 (przyczyna błędów komunikacji), testy fizyczne, restart komputera (k8).
