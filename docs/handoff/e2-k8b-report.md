# E2-k8b – raport (część B zamknięcia etapu 2)

Data: 2026-11-26, pomiary 07:17–07:40 UTC. Plan: `e2-k8-plan.md`, review: `e2-k8-review.md`. Zasady: tylko odczyty na produkcji, bez harnessu na produkcji, bez sudo, bez czytania `.env`, bez zmian w działającym systemie. Pełne testy w projekcie `aip-test` (izolowany).

## 1. Pełne testy na start

`tests/run-tests.sh` na IPC (kod `c299eaa`, taki sam jak wdrożony), 26.11 07:17:20–07:29:05 UTC: **507 passed, 3 skipped (testy wydajnościowe, uruchamiane osobno `tests/run-perf.sh`), 0 failed, 0 errors, 689,7 s**, kod wyjścia 0.
Baza testowa nie padła (awaria z pierwszego przebiegu k8c 25.11 się nie powtórzyła), więc nie było potrzeby zbierać `docker logs` kontenera testowego ani `journalctl -k`. Test 009 po poprawce porównania (9 cyfr znaczących) zaliczony.

## 2. Kompresja i rozmiar bazy

### 2.1 Stan chunków `measurements` (07:17 UTC)

| Chunk | Doba (UTC) | Wiersze | Skompresowany | Rozmiar teraz | Przed kompresją | Po kompresji | Współczynnik | B/wiersz przed | **B/wiersz po** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `_hyper_1_1_chunk` | 23.11 | 24 941 | tak | 216 kB | 4 923 392 B | 196 608 B | 25,0 | 197,4 | 7,88 |
| `_hyper_1_2_chunk` | 24.11 | 786 541 | tak | 3 504 kB | 154 468 352 B | 3 563 520 B | **43,3** | 196,4 | **4,53** |
| `_hyper_1_5_chunk` | 25.11 | 1 452 376 | **nie** | 274 MB | – | – | – | 198 (z rozmiaru) | – |
| `_hyper_1_9_chunk` | 26.11 (w toku) | 525 180 | nie | 100 MB | – | – | – | – | – |

Przed kompresją (24.11): tabela 65,1 MB, indeksy 89,3 MB; po: tabela 0,29 MB, indeksy 0,07 MB, TOAST 3,19 MB (dane kolumnowe).
**Chunk z 25.11 nie jest jeszcze skompresowany i to jest zgodne z polityką**: `compress_after = 1 day` liczy się od **końca** chunku (26.11 00:00), więc chunk kwalifikuje się po 27.11 00:00 UTC. Zadanie kompresji `measurements` (job 1000) uruchamia się co 12 h: ostatni przebieg 26.11 06:52:41 UTC, **Success**, 4,4 s; następny 26.11 18:52:46 (jeszcze za wcześnie dla 25.11); 25.11 skompresuje przebieg 27.11 ok. 06:53 UTC. Historia zadania: 6 przebiegów, 0 błędów. Zadania kompresji agregatów (1004 `energy_1m`, 1009/1010 `energy_ext_*`, 1013 `energy_1h`): po 2–4 przebiegi, 0 błędów; nic jeszcze nie kompresują (`compress_after` 14 i 60 dni).

**Zastrzeżenie:** jedyna pełna doba po kompresji (24.11) to **mapa v1** (13 wierszy/s w stanie OK, przerwa zaniku zasilania do 06:52 UTC). Dane v2 (THD, kąt, temperatura, czas pracy, liczniki energii biernej) mogą kompresować się inaczej. Pierwsza doba w pełni v2 (26.11) zostanie skompresowana 28.11 ok. 06:53 UTC; wtedy podam B/wiersz dla v2 (dopisek do raportu, jeśli architekt chce).

### 2.2 Rozmiar całości (07:17 UTC)

| Obiekt | Rozmiar |
| --- | --- |
| baza `energy` | 390 MB (409 394 199 B) |
| `measurements` | 377 MB (z tego 274 + 100 MB to dwa nieskompresowane chunki) |
| `energy_1m` | 1 280 kB (2 926 wierszy, ok. 448 B/wiersz z indeksami) |
| `energy_ext_1m` | 936 kB (2 926 wierszy, ok. 328 B/wiersz) |
| `energy_1h`, `energy_ext_1h` | po 104 kB (52 wiersze; rozmiar to narzut stron, nie do ekstrapolacji) |
| dysk `/` | 938 GB, zajęte 22 GB, wolne 869 GB; wolumeny Dockera 472 MB |

Agregaty mają po jednym chunku (zakres 10 dni) i żaden nie jest jeszcze skompresowany.

### 2.3 Prognoza

Podstawa: 196 B/wiersz przed kompresją (24.11 i 25.11 zgodnie: 196,4 i ok. 198), **4,53 B/wiersz po kompresji (mapa v1; v2 do potwierdzenia)**. Nieskompresowane są zawsze ok. 2–2,5 doby (bieżąca, poprzednia i do 12 h opóźnienia zadania).

| Wariant | Wiersze/dobę | Surowe nieskompresowane | Po kompresji | 90 dni surowych (88 dób skompr. + ok. 2,5 doby nieskompr.) |
| --- | --- | --- | --- | --- |
| **20 wierszy/s (dziś)** | 1 728 000 | 339 MB/dobę | **7,8 MB/dobę** | ok. 0,69 GB + 0,85 GB ≈ **1,5 GB** |
| 20/s, jeśli v2 kompresuje się 2× gorzej (9 B/wiersz) | 1 728 000 | 339 MB/dobę | 15,6 MB/dobę | ok. 1,4 GB + 0,85 GB ≈ 2,2 GB |
| **49 wierszy/s (po etapie 3, orientacyjnie)** | 4 233 600 | 831 MB/dobę | 19,2 MB/dobę | ok. 1,7 GB + 2,1 GB ≈ **3,8 GB** |

**Agregaty, rok (na jeden licznik, górna granica bez kompresji):** `energy_1m` 525 600 wierszy × 448 B ≈ 235 MB, `energy_ext_1m` × 328 B ≈ 172 MB, godzinne po ok. 8 760 wierszy (rząd kilku MB) – razem ok. **0,4 GB/licznik/rok**; po kompresji (po 14 dniach) znacznie mniej, współczynnik zmierzę, gdy powstanie pierwszy skompresowany chunk agregatu (ok. 7.12). Po etapie 3 (5 liczników + `pump_1m`) górna granica rzędu 2–2,5 GB/rok.
Wniosek: przy 869 GB wolnego dysk nie jest ograniczeniem ani dziś, ani po etapie 3. Pamięć bazy (cache nieskompresowanych chunków) rośnie razem z wierszami/s – patrz sekcja 4.

## 3. Krok n4 i całka mocy biernej

| Zdarzenie | Czas (UTC) | Wartość n4 (`reactive_neg_varh`) |
| --- | --- | --- |
| początek mapy v2 | 25.11 10:43:11.557 | 4 800 |
| **krok 4 800 → 4 900** | **25.11 16:04:09.162** (17:04 czasu lokalnego) | 4 900 |
| krok 4 900 → 5 000 | 26.11 03:21:15.155 (04:21 lokalnie) | 5 000 |
| ostatni odczyt | 26.11 07:18:13 | 5 000 |

`reactive_pos_varh` (n2) = 0 przez cały czas, `reactive_power` w każdej próbce < 0 (0 próbek ≥ 0), średnio −8,69 var.
Całka |Q| (Q < 0) z surowych próbek (Q × 1 s / 3600):

| Odcinek | Całka | Licznik | Ocena |
| --- | --- | --- | --- |
| 10:43:11 → pierwszy krok | 45,12 varh | 4 800 → 4 900 | spójne: stan licznika w chwili startu v2 był ok. 54,9 varh ponad 4 800 (każda całka 0–100 varh jest tu zgodna) |
| **między krokami** (16:04:09 → 03:21:15, 40 626 s) | **98,68 varh** z 40 534 próbek | **+100 varh** | brakuje 92 s próbek (epizody błędu licznika, ok. 0,22 varh): po uzupełnieniu ok. **98,9 varh, różnica ok. 1,1 varh (1,1 %)**, w granicach 100 varh |
| drugi krok → 07:18 | 34,50 varh | 5 000 | następny krok przy tym obciążeniu za ok. 7–8 h |

Agregat `energy_ext_1h` (to, co pokazuje dashboard) od 25.11 10:00 UTC: 184,36 varh, czyli o 6,09 varh więcej niż surowe dane od 10:43:11 – to dokładnie ok. 43 minuty mapy v1 przed 10:43 przy ok. 8,5 var, więc agregat i surowe dane są zgodne.
Wniosek: rozdzielczość licznika 100 varh i znak („n4 przy Q < 0”) potwierdzone; całka mocy biernej zgadza się z licznikiem z dokładnością ok. 1 %.

### 3.1 Nowy fakt E2-PLC1 (korekta mojego wczorajszego zdania)
Wczoraj (do ok. 13:47 UTC) pod mapą v2 nie było epizodów błędu licznika. **Później się pojawiły**: od 25.11 10:43 UTC do teraz 57 epizodów `meter_status` 0 → ≠ 0: 14:00–15:00 UTC 11, 15:00–16:00 23, 16:00–17:00 6, 22:00–23:00 8, 23:00–24:00 9; każdy ok. 5 s (luki w `reactive_power` po ok. 5 s), odstępy wielokrotnością 64 s. Zdanie w `docs/stages/etap-2.md` („pod mapą v2 zero”) jest nieaktualne; pliku nie zmieniam (kolumnę i treść prowadzi architekt) – do poprawy przez architekta albo na polecenie.

## 4. Pamięć z crona (`~/aip-monitor`)

Okno analizy: **25.11 13:29:32 – 26.11 07:16:01 UTC (17 h 47 min, 1 068 próbek na kontener)**; przerwane przed startem pełnych testów (07:17), żeby kontenery `aip-test-*` nie zakłócały przebiegu (cron zapisuje je też, ale analiza je pomija). Bez harnessu na produkcji w tym oknie.

| Kontener | min | średnia | maks. | limit | maks. % | Chwila maks. (UTC) | `memory.peak` (od utworzenia) | % limitu | `oom` / `oom_kill` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aip-collector | 38,8 | 39,9 | 48,9 MiB | 128 | 38,2 % | 26.11 04:11 | 54,3 MiB | 42,5 % | 0 / 0 |
| aip-ingest | 39,3 | 40,4 | 49,3 MiB | 128 | 38,5 % | 25.11 17:02 | 54,2 MiB | 42,4 % | 0 / 0 |
| aip-mosquitto | 7,2 | 7,5 | 8,8 MiB | 64 | 13,8 % | 25.11 23:55 | 11,5 MiB | 17,9 % | 0 / 0 |
| aip-timescaledb | 307,5 | 412,4 | 464,4 MiB | 1536 | 30,2 % | 26.11 06:29 | 1 074,0 MiB | 69,9 % | 0 / 0 |
| **aip-grafana** | 138,7 | 141,3 | **320,4 MiB** | 512 | 62,6 % | **25.11 22:01** | **392,7 MiB** | **76,7 %** | **0 / 0** |

(min/średnia/maks. z `docker stats`, które pomija pamięć podręczną plików; `memory.peak` z cgroup liczy wszystko, także cache.)

**Kryterium (0 OOM, szczyt ≤ 80 % limitu): spełnione w oknie** – wszystkie `oom_kill` = 0, najwyższy szczyt Grafany 76,7 %.

### 4.1 Grafana: szczyty a zdarzenia

| Zdarzenie | Czas (UTC) | Pamięć Grafany |
| --- | --- | --- |
| utworzenie kontenera przy wdrożeniu k8c | 25.11 13:11 | – |
| **harness paneli na produkcji** (`prod_panels.py`, 207 zapytań) + sprawdzenie API | 25.11 ok. 13:12–13:14 | **szczyt `memory.peak` 392,7 MiB powstał w tym oknie** (13:11–13:29; cron ruszył 13:29:32 i od tej chwili `memory.peak` się nie zmienił) |
| harness na produkcji (k4) | 25.11 ok. 11:10 | poprzedni kontener (odtworzony o 13:11), poza oknem pomiaru |
| restart komputera, wdrożenie 011 | 25.11 12:04, 12:07 | poprzednie kontenery, poza oknem |
| **przeglądarka z laptopa (192.168.0.214) otwiera „Stan i diagnostyka”** po odnowieniu sesji (log Grafany: `GET /d/aip-diagnostyka`, rotacja tokenu, `/api/live/ws`) | **25.11 22:00:15** | **320,4 MiB o 22:01–22:02**, 217 MiB o 22:03–22:04, 147–151 MiB od 22:05; `memory.peak` bez zmian |
| reszta doby | – | 139–151 MiB, maks. godzinowe 139,5–150,4 MiB |

Wniosek: **największy szczyt zwykłej pracy (320 MiB, 62,6 %) dało otwarcie dashboardu „Stan i diagnostyka” (domyślnie 24 h, osie stanów) w przeglądarce**, nie harness. Szczyt absolutny kontenera (392,7 MiB, 76,7 %) pochodzi z okna z harnessem 13:12 i startem kontenera. `GOMEMLIMIT=400MiB` działa zgodnie z zamiarem: po 2–3 minutach pamięć wraca do ok. 150 MiB. Limitu nie proponuję zmieniać; po przyjściu kolejnych dashboardów (etap 3: „Flota”, „Pompa”) ponowić pomiar.

### 4.2 TimescaleDB
`docker stats` 307–464 MiB (30 %), ale `memory.peak` rośnie stale (617 → 1 074 MiB w 18 h, ok. 25 MiB/h; skok +82 MiB o 06:53 UTC = przebieg zadania kompresji): to pamięć podręczna plików nieskompresowanych chunków (274 + 100 MB) i `shared_buffers` (384 MB), którą jądro odzyskuje przed OOM. Po kompresji chunku 25.11 (27.11) wzrost powinien się zatrzymać; przy 49 wierszach/s (etap 3) nieskompresowane chunki będą ok. 2,5× większe – do obserwacji w etapie 3, `oom_kill` = 0.

### 4.3 Pamięć po pełnej dobie (do uzupełnienia po 13:00 UTC)

_Do uzupełnienia: przebieg 25.11 13:29 – 26.11 13:29 UTC (bez okresu testów 07:17–07:30), `memory.peak` i `memory.events` po pełnej dobie._

## 5. Podsumowanie i dalej

| Punkt | Wynik |
| --- | --- |
| Pełne testy | 507 passed, 3 skipped, 0 failed (689,7 s) |
| Kompresja | 24.11: 43,3×, 4,53 B/wiersz (v1); 25.11 skompresuje się 27.11 ok. 06:53 UTC (zgodnie z polityką), v2 do potwierdzenia 28.11 |
| Prognoza 90 dni | ok. 1,5 GB przy 20/s (do 2,2 GB, jeśli v2 kompresuje się 2× gorzej); ok. 3,8 GB przy 49/s |
| n4 | 4 800 → 4 900 o 25.11 16:04:09 UTC; całka między krokami 98,9 varh wobec 100 varh (1,1 %) |
| Pamięć (17 h 47 min) | 0 OOM; szczyt Grafany 76,7 % (okno harnessu 13:12), w zwykłej pracy 62,6 % (otwarcie dashboardu 22:00 UTC) |
| Nowe | epizody E2-PLC1 także pod mapą v2 (57 od 25.11 14:41 UTC) |

Do decyzji architekta: (1) czy dopisać B/wiersz dla v2 po 28.11; (2) korekta zdania o E2-PLC1 w `etap-2.md`; (3) uzupełnienie sekcji 4.3 po 13:00 UTC.
Stop.
