# E3-k3 – raport: usługa symulatora na żywo, konto MQTT i ACL, kotwice, pamięć sum dobowych

Data: 2026-11-26. Plan: `e3-k3-plan.md`, review: `e3-k3-review.md` (OK Z UWAGAMI; K3-D1…D4, K3-U1…U6). Review zacommitowane w `7a2111d`.
Commity kroku: `54c7122` (usługa, ACL, kotwice, pamięć sum, „tylko real”, testy, dokumentacja), `11900d8` (poprawki po przeglądzie `reviewer`, w tym błąd w ingeście), `feec7f5`, `d7ffe02`, `835501c`, `ee4aaaa` (poprawki testów), ten raport.
**Produkcja nie zmieniona (K3-U5):** `~/ai-predykcja` przed, w trakcie i po każdym przebiegu: `c299eaa`, katalog czysty; `docker ps` na produkcji: `aip-collector aip-grafana aip-ingest aip-mosquitto aip-timescaledb` – **bez `aip-simulator`**, Mosquitto bez restartu.

## Co powstało

1. **Usługa `aip-simulator`** (`services/simulator`): `main` (start, kody wyjścia), `live` (pętla co pełną sekundę), `publisher` (paho 2.2.0, MQTT v5, **QoS 0** – K3-D4, bufor `SIM_BUFFER_MAX` 36 000 – K3-D3), `health` („pętla żyje”), `daycache` (pamięć sum dobowych). `Dockerfile`: obraz bazowy jak collector, `PYTHONTZPATH=""` (K2R-U1), użytkownik uid 10003. Usługa `simulator` w `docker-compose.yml` (`read_only`, `tmpfs /tmp`, `cap_drop ALL`, `no-new-privileges`, `mem_limit`/`memswap_limit` 128m, wolumen `aip_simulator_data:/var/lib/simulator`, config `:ro`, bez portów); suma limitów `aip-*` 2560 MiB (U-5, K3-U6).
2. **Kotwice (K2R-D1, K2R-D2):** `t_zero` i `history_progress` usunięte; `simulator.meter_anchor` (stała kotwica liczników) i `bearing_installed_at` pompy (x = 0 w montażu). Oba `null` w repo do k7; `Simulator` przy `null` kończy się `ConfigError` (kod 2). Stare pola w configu = błąd „nieznane klucze”. Wymiana łożyska = nowa data montażu, liczniki nietknięte (test). Opis w `docs/ops` i `docs/data-model.md`.
3. **Pamięć sum dobowych (K2R-D3):** plik `/var/lib/simulator/energy-days.json`; klucz = sha256 z `MODEL_VERSION`, ziarna, kotwicy, kalendarza, otoczenia, elektryki i parametrów liczników; doba = blok 86 400 s od kotwicy (UTC); kontrola ostatniej doby każdego licznika przy starcie; zapis atomowy; brak/uszkodzenie/brak praw = przeliczenie i WARNING. W trybie na żywo suma doby powstaje z dwóch kolejnych granic dób (bez ponownego liczenia 86 400 s).
4. **Konto MQTT i ACL (K1-D2, K3-D1):** `acl.conf`: collector `write zaklad1/linia1/+/+`, symulator `write zaklad1/linia2/+/+`, ingest `read +/+/+/+`. `entrypoint.sh`: konto symulatora **opcjonalne** (bez zmiennych broker startuje z WARNING, blok ACL dostaje nieistniejące konto). `.env.example`, compose testowy, `run-tests.sh`/`run-perf.sh` (losowe hasło testowe).
5. **Sekcja główna tylko `real` (K1-D1, K3-D2):** walidacja w ingeście i w collectorze (tylko przy wczytaniu); testy z `source: sim` w sekcji głównej przepisane na sekcję `simulator`.
6. **Ingest i QoS 0 (poprawka po przeglądzie, ustalenie 1):** przy niedostępnej bazie ingest **odrzuca wiadomości QoS 0** (dane sim) zamiast trzymać je w pamięci – szczegóły niżej.
7. **Dokumentacja:** `docs/ops/jumo-ipc-setup.md` (sekcja „Symulator”: konto i polecenia dla Grzegorza do k7, kotwice przy wdrożeniu, pamięć sum; tabela utraty danych przeliczona dla 20 + 29 wiadomości/s; zachowanie ingestu przy niedostępnej bazie), `docs/data-model.md` (kotwice, wymiana łożyska).

## Wyniki pomiarów

**K3-D2 – stary i nowy kod z oboma plikami** (laptop, kod z `c299eaa` i z `54c7122`):
```
STARY ingest: plik prod ['finder_7m24_1', 'plc-01'] | NOWY plik ['finder_7m24_1', 'plc-01'] | identyczne: True
STARY collector: identyczne: True ['finder_7m24_1']
NOWY ingest + plik prod: ['finder_7m24_1', 'plc-01'] {'plc-01': 'real', 'finder_7m24_1': 'real'}
NOWY collector + plik prod: ['finder_7m24_1'] real == stary: True
```
(Agent `reviewer` powtórzył to niezależnie z tym samym wynikiem.)

**K3-D4 – przerwa ingestu przy działającym symulatorze (QoS 0) i collectorze testowym (QoS 1)**, test `test_ingest_outage_keeps_the_broker_queue_for_real_data` w `aip-test`:
```
PRZERWA INGESTU 120 s: linia1 120/120 w bazie, linia2 sekundy w bazie: [0, 121]
```
Wszystkie wiadomości prawdziwe z czasu przerwy dotarły po powrocie ingestu; dane sim z przerwy nie były kolejkowane (luka, którą uzupełni historia k5). `queue_qos0_messages` nie jest ustawione w `mosquitto.conf` (domyślnie false; test). Ręczne potwierdzenia ingestu dla QoS 0 nie zgłaszają wyjątku (paho `ack(mid, 0)` to nic nie robiące SUCCESS; wątek ingestu bez błędów w obu testach e2e). Tabela w `docs/ops`: kolejka 80 000 zostaje dla danych prawdziwych – **nadal ok. 66 min przy 20/s** (przy QoS 1 dla sim byłoby ok. 27 min).

**K3-D3 / K3-U6 – pamięć:**

| Pomiar | Wynik |
| --- | --- |
| kontener `aip-simulator:test` po starcie (bez brokera, `--memory 128m`), `docker stats` | 22,1 MiB; po kolejnych 2 min 22,8 MiB |
| `memory.peak` tego kontenera (cgroup) | 25 006 080 B (23,8 MiB) |
| pełny bufor 36 000 wiadomości (osobny proces w kontenerze testowym, VmRSS) | 26,1 → 32,2 MiB (**+6,1 MiB**) |
| szacunek kontenera z pełnym buforem | ok. 29 MiB z 128 MiB |

Uwaga: pierwsza wersja testu bufora mierzyła `ru_maxrss`, które po `fork` dziedziczy szczyt procesu pytest (wynik „+0 MiB” był błędny, commit `835501c` miał w opisie VmRSS, ale zmiana się nie zastosowała); poprawione w `ee4aaaa`.

**K3-U1 / K3-U2 – obraz testowy na IPC** (`docker build -t aip-simulator:test`, `docker run --rm`, potem `docker image rm aip-simulator:test`; bez `prune`, bez ruszania innych obrazów i kontenerów):
```
tzdata 2025.2 IANA 2025b TZPATH ()
2026-10-25T00:30:00+00:00 2026-10-25T02:30:00+02:00
2026-10-25T01:30:00+00:00 2026-10-25T02:30:00+01:00
2027-03-28T00:30:00+00:00 2027-03-28T01:30:00+01:00
2027-03-28T01:30:00+00:00 2027-03-28T03:30:00+02:00
```
Kontener z configiem z repo (daty `null`): `ERROR simulator błąd konfiguracji: simulator.meter_anchor nie jest ustawione …`, **kod 2**. Z datami testowymi (kotwica 17.11, montaż 08.09): `start: model 2026-11-26.1, 4 liczników i 1 pomp w zaklad1/linia2 …, pamięć sum: brak pliku, start liczników 32,2 s`, `pompa sim_pump_p101: … postęp x = 0.663`; po `docker restart`: `pamięć sum: plik, start liczników 5,0 s`. Kontener, wolumen testowy i obraz usunięte.

**K2R-D3 / K3-U4 – start liczników z plikiem i bez:**

| Dni od kotwicy | Bez pliku | Z plikiem | Rozmiar pliku | Zgodne |
| --- | --- | --- | --- | --- |
| 14 (test zwykły) | 43,0 s | 3,0 s (z kontrolą ostatniej doby) | 903 B | tak |
| 90 (`run-perf.sh`) | 299 s | 2,9 s | 5 468 B | tak |
| 365 (`run-perf.sh`) | 1 219 s | 3,4 s | **22 833 B** | tak |

Koszt jednego ticku 29 metryk po rozgrzaniu: 0,19 ms.

## Uwagi z review

| Uwaga | Jak zrobione |
| --- | --- |
| K3-U1 | `test_sim_model_version.py`: wzorcowe sumy W·s doby 13 każdego licznika i 3 próbki pompy razem z `MODEL_VERSION = "2026-11-26.1"`; zmiana wyniku przy tej samej wersji = czerwony test z poleceniem „podbij MODEL_VERSION i zaktualizuj wzorce”; test, że wersja wchodzi do klucza |
| K3-U2 | wyżej (tylko tag testowy, potem `image rm`) |
| K3-U3 | przeskok przy opóźnieniu > 5 s (jeden log); cofnięcie zegara ≤ 5 s = czekanie bez ponownego wysłania, większe = start od bieżącej sekundy; test, że `run()` się nie zawiesza; dodatkowo (przegląd) zegar przed kotwicą liczników = jeden ERROR, pętla żyje |
| K3-U4 | wyżej (z plikiem 2,9 / 3,4 s, plik 22,8 kB po 365 dobach) |
| K3-U5 | wyżej (produkcja `c299eaa`, bez `aip-simulator`) |
| K3-U6 | wyżej (ok. 22–29 MiB z 128) |
| K2R-U4 | `test_sim_dst_energy.py`: energia dób lokalnych 25.10.2026 (90 000 s) i 28.03.2027 (82 800 s) = suma ich sekund co do W·s; chłodnia proporcjonalna do długości doby; pakowaczka w niedzielę = moc postoju; poniedziałki 26.10.2026 i 29.03.2027: zmiana startuje 05:00 / 04:00 UTC, energia mieszalnika i pakowaczki jak w zwykły poniedziałek (± 3 %) |
| K2R-U5 | pełny zestaw: **24 min 49 s** (z 22 min w k2, przy 47 nowych testach, w tym 2-minutowym teście przerwy ingestu i 4 kontenerach testowych); bez pamięci sum byłby dłuższy (testy symulatora same z siebie: ok. 5 min zamiast ok. 10) |

## Testy

| Przebieg (worktree `~/ai-predykcja-dev`, `aip-test`) | Commit | Wynik |
| --- | --- | --- |
| pełny | `54c7122` | 691 passed, 5 skipped, **1 failed**: `test_ingest_e2e.py::test_real_and_simulated…` (k1) publikował dane sim z konta collectora do `linia2` – po K1-D2 ACL słusznie to odrzuca; test przepisany na konto symulatora (`feec7f5`) |
| `run-perf.sh` (pamięć sum 90 i 365 dni) | `54c7122` | 2 passed (25 min) |
| **pełny, końcowy** | `feec7f5` | **700 passed, 5 skipped, 0 failed** (1 489 s); produkcja `c299eaa` czysta |
| pliki z wydrukami (pamięć sum, pętla, e2e, koszt), osobno | `d7ffe02` | 23 passed (po poprawce ścieżki importu: `test_sim_e2e` uruchomiony osobno nie widział helperów ingestu) |
| `test_sim_live.py` (pomiar bufora VmRSS) | `ee4aaaa` | 6 passed |

Po `feec7f5` zmieniały się tylko pliki testów (ścieżka importu, pomiar bufora); te pliki przeszły osobno, pełnego zestawu po nich nie powtarzałem. Pominięte (5): 3 testy wydajności etapu 2 i 2 nowe (`run-perf.sh`).

## Przegląd agentem `reviewer`

Werdykt agenta przed poprawkami: **nie do akceptacji** z powodu ustalenia 1; po poprawkach – wszystkie ustalenia o wadze „błąd” i „ryzyko” obsłużone poniżej.

| # | Ustalenie | Stan |
| --- | --- | --- |
| 1 (błąd) | QoS 0 omija limit 100 wiadomości w locie: przy niedostępnej bazie dane sim rosną w pamięci ingestu (ok. 43 MiB/h, OOM po 1–2 h), a po powrocie jedna wielka paczka; dokumentacja („najwyżej 100”) nieaktualna | **poprawione** (`11900d8`): `Incoming.qos`; przy `db_down` wiadomości QoS 0 są odrzucane (WARNING na początku i na końcu przerwy z liczbą, pole w podsumowaniu); QoS 1 bez zmian. Test: 20 000 wiadomości QoS 0 przy niedostępnej bazie → w pamięci tylko 50 wiadomości QoS 1, po powrocie bazy wszystkie zapisane. `docs/ops` poprawione. **Dotyka ingestu (ścieżki produkcyjnej) – na produkcji dopiero w k7** |
| 2 | nieudany zapis pamięci sum ponawiany co sekundę z WARNING | **poprawione**: kolejna próba dopiero przy nowej pełnej dobie (test: 100 ticków = 1 WARNING) |
| 3 | bez konta MQTT symulator kończył się kodem 2 (pętla restartów), niezgodnie z K3-D1 | **poprawione**: proces działa, jeden ERROR „brak konta MQTT symulatora”, transport ponawia (test) |
| 4 | duży skok zegara liczył przerwę dwa razy | **poprawione** (test: skok o 3 doby = tylko brakujące doby) |
| 5 | zegar cofnięty przed kotwicę kończył proces | **poprawione**: jeden ERROR, pętla żyje (test) |
| 6 | kontrola pliku sprawdza tylko ostatnią dobę | zostawione (ryzyko niskie; wzorce K3-U1 pilnują modelu) |
| 7 | luki testów | dodane testy `main` (kod 2, brak konta), `health`; **brak testu na żywym brokerze bez konta symulatora** (compose testowy zawsze podaje konto; jest test tekstowy `entrypoint.sh`) – do k7: na produkcji pierwszy start brokera i tak będzie z kontem (kolejność `.env` → R-1) |
| drobne | `start_period` 120 s bez pliku pamięci może być za krótki po miesiącach (chwilowo unhealthy); plan wymieniał `test_sim_anchors.py` i `status-codes.md` – testy kotwic są w `test_sim_config.py`/`test_sim_pump.py`, kod 2 opisany w `docs/ops` | zapis tutaj |

## Do k7 (wdrożenie)

- Grzegorz: konto symulatora w `.env` (polecenie w `docs/ops`, sekcja „Symulator”) **przed** R-1; potem odtworzenie `mosquitto` (nowy ACL: collector tylko `linia1`), `ingest` (QoS 0 przy braku bazy, linia na urządzenie, „tylko real”), `collector` (walidacja), start `simulator`; kontrola 20 wierszy/s danych prawdziwych po restarcie brokera.
- Ustawienie `meter_anchor` (wdrożenie − 14 dni) i `bearing_installed_at` (wdrożenie − 84 dni) w `config/devices.yaml`.

Raport e3-k3 gotowy. Stop.
