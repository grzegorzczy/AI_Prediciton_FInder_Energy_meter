# E3-k7b – raport (krótki): restart IPC, R-1, pilotaż 1 doby historii

Data: 2026-11-28. Review części A: `2471dcf`. Wdrożony commit: `f767048` (produkcja `~/ai-predykcja`, wcześniej `c299eaa`).
Bez `sudo` po mojej stronie, `.env` nieczytany (konto symulatora dopisał Grzegorz: `grep -c` = 2). smartWARE nietknięty.
Czasy w UTC (lokalnie +1 h).

## Przed restartem: testy i poprawka

- Pierwszy przebieg testów (`648a496`) **zawiesił się** na `test_main_without_dates_exits_with_code_2`: test brał
  `config/devices.yaml` z repo jako „bez dat”, a od `54e6043` plik ma daty k7, więc `main()` wchodził w pętlę na żywo.
  Poprawka `f767048`: test sam ustawia daty null. Reviewer tego nie wyłapał.
- Pętla czekania bez limitu czekała 1 h 55 min – zasada limitu (≤ 2× spodziewany czas, przerwanie przy błędzie ssh)
  dopisana do `docs/workflow.md`. Limit 20 min dla testów był za mały (432 testy, nie 262) – przedłużony o 15 min.
- Przebieg przerwany restartem IPC powtórzony: `tests/config tests/simulator tests/db tests/grafana`
  → **406 passed, 26 skipped, 0 failed** (23 min 47 s; slow paneli bez `AIP_SLOW_PANELS`).

## Restart IPC (K7-D3)

| Pomiar | Wynik |
| --- | --- |
| Wyłączenie / start systemu | 12:13:42 / 12:13:56 |
| Pierwszy wiersz real po starcie | 12:14:13.195 (17 s po starcie systemu) – **< 5 min** |
| Luka danych real | **12:13:31.156 → 12:14:13.195 (42 s)**, jedyna |
| Tempo real po restarcie | 20,0 wierszy/s |

## R-1 (12:40:51)

`git pull --ff-only` (`c299eaa` → `f767048`), kontrola praw bez uwag (`.env` 600), `docker compose up -d --build` → EXIT 0.

| Kontrola | Wynik |
| --- | --- |
| Migracje | `applied 012_pump_aggregates.sql`, `applied 013_data_windows_cable_move.sql`; `schema_migrations` 13 = 13 plików |
| `devices` | 2 real (`plc-01`, `finder_7m24_1`) + 5 sim (4 liczniki + `sim_pump_p101`) |
| Symulator | start 12:42:02, kotwica 2026-11-13T23:00Z, łożysko 2026-09-04T22:00Z, x = 0,705, MQTT QoS 0 połączony |
| Tempo | **20 real + 29 sim = 49 wierszy/s** |
| Luka real przy odtworzeniu collectora | **12:41:00.159 → 12:41:16.358 (16 s)**; od 12:41:16 żadnej luki > 3 s |
| `T0` | **2026-11-28T12:42:00Z** (pierwsza pełna minuta po starcie na żywo) |

## Pilotaż 1 doby liczników (K5R-D1, K5R-D2)

`backfill --from 2026-11-27T12:42:00Z --to 2026-11-28T12:42:00Z --devices meters`, w tle (`nohup`), monitor co 20 s
(`~/aip-k7/pilot-mon.sh`, tylko odczyt). Kompresja **niewstrzymana** (K7-U2: tylko noc wgrywania; okno pilotażu < 1 doby).

| Pomiar | Wynik |
| --- | --- |
| Przebieg | 12:43:32 – 13:06:02, EXIT 0 |
| Wiadomości / czas / tempo | 2 073 600 / 1 350 s / **1 536 wiad./s** (k5 na testach: 1 340/s), 288 porcji, czekanie na bazę 826 s |
| Dane real w trakcie (59 próbek) | **20 wierszy/s w każdej próbce** (min 400 / 20 s) |
| Dane sim na żywo w trakcie | **29 wierszy/s w każdej próbce**; w logu ingestu brak `odrzucone_sim` i błędów |
| `--fill-gaps` (12:42 – 12:43 dnia T0 włącznie) | brakujących minut przed **4** (minuta 12:42 – start na żywo o :02), wysłano 1 440, po **0** |
| Wiersze sim w oknie | 2 075 040 (= 2 073 600 + 1 440); `energy_1h` 104 = 4 liczniki × 26 h po odświeżeniu |
| Baza | 531 → 937 MB (**≈ 400 MB/dobę liczników**, z danymi na żywo); chunki `measurements` 4/6 skompresowane (bez zmian) |
| Dysk | wolne 868 GB |
| CPU maks. (`docker stats`) | ingest 113 %, baza 131 %, narzędzie 115 %, broker 16 % rdzenia |
| RAM `docker stats` maks. / `memory.peak` | ingest 35 / 37 MiB (128), broker 3 / 6 (64), narzędzie 27 (128), symulator – / 32 (128), collector – / 33 (128), Grafana 350 / 365 (512), baza 506 / **1 536 (limit)** |

**Baza na limicie `memory.peak`:** to pamięć plików (`file` 1 456 MiB, `anon` 26 MiB) – cgroup odzyskuje cache przy limicie
(`memory.events max` 359), `oom_kill` 0, restartów 0. Nie blokuje; do decyzji architekta, czy to akceptowalne w nocy.
**Grafana:** 141 MiB przed restartem → 350 MiB (64 % limitu) po R-1 i pilotażu; obserwuję w nocy (krok 8 planu).

## Prognoza nocy (K5R checklista)

- Liczniki `--from 2026-11-13T23:00Z --to 2026-11-27T12:42Z` = 13,57 doby × 1 350 s ≈ **5,1 h**; pompa
  `--from 2026-09-04T22:00Z --to T0` (krok 60 s) – minuty. **Razem ok. 5,5 h < 10 h → jedna noc.**
- Dysk: 13,57 × 400 MB ≈ **5,4 GB** + pompa ≈ 0,1 GB; wolne 868 GB ≫ 3× (17 GB).

## Monitor sieci (K7A-D2: wynik dobowy w raporcie B)

28.11 00:53 – 13:43: 770 próbek, brama i PLC 0/3 strat w każdej, adres .215, MAC bramy i prędkość 100 bez zmian,
zdarzenia łącza tylko przy restarcie (13:15: 3). Doba pomiaru kończy się 29.11 ok. 01:00 – pełny wynik w raporcie k7.

## Okna `data_windows` (K7-U4) – do jednej migracji w raporcie k7

`ipc_reboot` 12:13:31.156–12:14:13.195; `deploy` 12:41:00.159–12:41:16.358; `sim_backfill` pilotażu 12:43:32–13:06:43
(z nocnym wgrywaniem); ewentualne luki nocy.

## Przed nocnym wgrywaniem (stop)

1. Strażnik K7-U1 (real < 18/s > 60 s, ingest > 80 % RAM, dysk < 3× reszty, kolejka brokera > 20 000) – do zbudowania
   i przetestowania na `aip-test` przed nocą; potrzebny sposób pomiaru kolejki brokera (np. `$SYS` lub zaległość z bazy).
2. Kompresja: wstrzymanie tylko na noc i obowiązkowe wznowienie (K7-U2). Najbliższe uruchomienie zadania: **18:53 UTC dziś**
   (skompresuje starsze chunki przed nocą – dobrze).
3. Godzina startu nocy i dostęp przez `desktop-buej0av` – decyzja Grzegorza.

Raport e3-k7b-pilot gotowy do przeglądu.
