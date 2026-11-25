# E2-k8a – raport (część A zamknięcia etapu 2)

Data: 2026-11-25. Plan: `e2-k8-plan.md`, review: `e2-k8-review.md`. Stan: **wykonane wszystko poza krokami z sudo – te wykonuje Grzegorz (sekcja 6).** Część B po 26.11.
Commity: `06517c7` (compose, harness, test), `3bc75c4` (poprawka, szkice), ostatni z tego raportu (dokumentacja). Bez sudo po mojej stronie, bez ruszania smartWARE, bez czytania `.env`.

## 1. Pełne testy (start k8a)

Na IPC, `tests/run-tests.sh`, 11:45–11:57 UTC, 690 s:
**481 passed, 3 skipped (testy wydajnościowe), 16 failed.**
Wszystkie 16 porażek miały jedną przyczynę, **mój błąd**: w komentarzu w `docker-compose.yml` znalazł się bajt NUL (skrypt edycji zinterpretował `\x00` jako znak), więc plik był nieczytelny dla YAML (`unacceptable character #x0000`) – to 5 testów `test_compose_service.py`, 7 `test_ingest_compose_service.py` i 4 nowe `test_compose_limits.py`. Testy zatrzymały błąd **przed wdrożeniem**. Po poprawce (`3bc75c4`): `tests/config`, `test_compose_service.py`, `test_ingest_compose_service.py` – **27 passed**, `docker compose config --quiet` OK.
Pełnego zestawu nie powtarzałem po poprawce: zmiana dotyczy tylko `docker-compose.yml`, a pozostałe 481 testów go nie czyta (testy używają `docker-compose.test.yml`). Jeśli architekt woli pełne powtórzenie, zrobię je w części B. Ten sam błąd NUL wyłapałem też w `docs/ops/jumo-ipc-setup.md` (naprawiony); skan pozostałych zmienionych plików: 0 bajtów NUL.
Zasoby podczas testu: RAM całego komputera ok. 1,6 GB zajęte, 13 GB dostępne; test sprzątnął kontenery `aip-test-*` (sprawdzone po zakończeniu). Obniżanie równoległości nie było potrzebne: baza testowa ma `mem_limit` 896m z `max_wal_size=192MB` (poprawka z k7), OOM Postgresa z 24.11 17:57 nie powtórzył się.

## 2. OOM Grafany a harness paneli

| Zdarzenie (czas lokalny) | Co ustaliłem |
| --- | --- |
| 25.11 11:38:14 | Ofiarą był kontener produkcyjny (cgroup `docker-f763f546…` = `aip-grafana`). W oknie 11:25–11:38 na IPC nie ma śladu harnessu przeciw produkcji: pliki `/tmp` z tego czasu to wdrożenie/obserwacje PLC-2 (`plc2_*`), a `prod_panels.py` został uruchomiony dopiero o 12:10 (`k4_panels.sh`). O 11:26:34–11:37:12 szedł pełny test w projekcie `aip-test` (**własna** Grafana testowa, inny cgroup; 276 zapytań harnessu testowego idzie tam, nie do produkcji). Zbieżność z harnessem produkcyjnym: **nie potwierdzona**. Co obciążyło produkcyjną Grafanę o 11:38, nie wiadomo (log Grafany na poziomie INFO nie zapisuje żądań; możliwe otwarte dashboardy z odświeżaniem 5 s lub inne zapytania) |
| 24.11 23:05:16 i 23:06:22 | W oknie sesja SSH z laptopa (23:03–23:38), trwała k7b (testy paneli, pliki `k7b_*` z 23:18–23:37). Logi uruchomień harnessu z 23:05 nie zachowały się (najwcześniejszy `k7b_g.log` 23:18), więc zbieżność jest **prawdopodobna, ale nie udowodniona** |

W obu wypadkach `anon-rss` ≈ 380 MiB tuż przy limicie 384 MiB (`memory: usage 393216kB, limit 393216kB, failcnt 148`).
**Ograniczenia harnessu** (`tests/grafana/prod_panels.py`): zapytania i tak szły pojedynczo (brak współbieżności – sprawdzone w kodzie); dodane: odmowa zakresów dłuższych niż 7 dni na produkcji (kod wyjścia 2, komunikat „użyj aip-test”) oraz przerwa 0,2 s między zapytaniami (`PROD_PANELS_PAUSE_S`). Zakresy roczne zostają tylko w testach `aip-test`.
Wniosek: główna przyczyna OOM (szczyt zużycia przy limicie 384 MiB) usunięta zmianą limitów (sekcja 3); kryterium sprawdzające – część B (`memory.peak`, `oom_kill = 0`).

## 3. Compose: logowanie i Grafana (R-1)

Zmiany w `docker-compose.yml`: `logging` dla wszystkich usług `driver: local`, `max-size: 10m`, `max-file: 5` (bez zmian w `daemon.json`, bez restartu demona); Grafana `mem_limit`/`memswap_limit` **512m**, `GOMEMLIMIT=400MiB`. Suma limitów aip-*: 2432 MiB (test `test_memory_limits_sum_fits_the_budget` pilnuje ≤ 2560).
Wdrożenie R-1: `git pull --ff-only`, kontrola praw (puste), `docker compose up -d --build` (11:57:59–11:58:15 UTC). Weryfikacja:

| Sprawdzenie | Wynik |
| --- | --- |
| kontenery | wszystkie 5 `healthy`, `aip-migrate` Exited (0), `RestartCount` = 0 |
| sterownik logów | `local`, `max-file:5 max-size:10m` na wszystkich 5 |
| pamięć w `HostConfig` | Grafana 536870912 B (512 MiB), `GOMEMLIMIT=400MiB` w środowisku |
| migracje | `done: 0 applied, 10 already applied`, `schema_migrations` = 10 wierszy (max 10) |
| `docker logs` | działa dla wszystkich 5 kontenerów |
| wiersze/s | po wdrożeniu 20 wierszy na sekundę w każdej z 45 sprawdzonych pełnych sekund |
| Grafana | `/api/health` database ok, wersja 13.0.2; pamięć po starcie 148,7 MiB / 512 |
| smartWARE | 7 kontenerów (`dataview`, `datareportengine`, `datareport`, `datastore`, `reverse-proxy`, `mqtt`, `postgres-server`) bez zmian, Up 29 h |

**Luka w danych przy wdrożeniu:** ostatni wiersz `link_status` 11:57:59.557, następny 11:58:15.557 UTC – **16 s** (odtworzenie wszystkich kontenerów, w tym collectora; bufor collectora nie chroni przy jego własnym restarcie). Nie dodaję okna do `data_windows` (poniżej progu istotności); do raportu i ewentualnej decyzji architekta.

## 4. Naprawa logów – stan i polecenia

Nie ma już czego naprawiać z sudo: **stare uszkodzone pliki `json-file` należały do kontenerów, które odtworzyło wdrożenie z pkt 3** (usuwanie kontenera usuwa jego plik logu), a nowe kontenery logują sterownikiem `local`. `docker logs` działa dla wszystkich 5. Polecenie `cp -a` + `: > plik` z review okazało się zbędne, więc **nie wymagam od Grzegorza żadnego kroku z sudo dla logów**. Jedyne, co zostaje: po teście restartu sprawdzić, że `docker logs` nadal działa (sekcja 6, krok „Po”). Jeśli kiedyś plik logu znów będzie uszkodzony (nie powinien przy `local`), procedura awaryjna (sudo, tylko ścieżka z `docker inspect -f '{{.LogPath}}' <kontener>`) jest w `e2-k8-plan.md` sekcja 7.

## 5. Migracja 011 (`ipc_reboot`) – szkic

~~`docs/handoff/e2-k8a-011-draft.sql`~~ (szkic zastąpiony migracją, patrz sekcja 10; poza `db/migrations/`, żeby nie wdrożyła się przedwcześnie). Rodzaj `ipc_reboot` nie wymaga zmiany ograniczenia (wzorzec `^[a-z0-9_]+$`). Granice weźmiemy z bazy po teście: ostatni wiersz przed restartem i pierwszy po nim; `exclude_from_analytics = TRUE`. Po dodaniu: poprawić `tests/db/test_data_windows.py` (lista rodzajów, liczba 13 → 14) – opisane w szkicu.

## 6. Szkic `docs/stages/etap-2.md`

Zrobiony wg poprawek review: bez kosztów, stany błędów przez odwołanie do k5 (z opcją powtórzenia), znane ograniczenia (E2-PLC1 serie CRC, drugi licznik wymaga nowej mapy, `energy_1m_calc`/`reactive_1h_calc` wolne – etap 4), reguła „do PLC nie piszemy” przez `tests/collector/test_no_write.py` zamiast `grep`. Pozycje 14 (restart) i 15 (kompresja) czekają na wyniki; stan wszystkich pozycji pusty do wypełnienia przez Grzegorza.

## 7. Test restartu – polecenia dla Grzegorza (sam wykonujesz, w wybranej porze)

Uwaga: **restart komputera restartuje też smartWARE** (jego kontenery mają `unless-stopped`, Docker i containerd są `enabled`). Wybierz porę, gdy to nie przeszkadza. W trakcie testu nie uruchamiaj ręcznie `docker compose up`.
Stan „przed”, który zapisałem teraz: `uptime -s` = 2026-11-24 07:52:19; wszystkie 5 aip-* i 7 kontenerów smartWARE Up; dysk `/` 938 GB, zajęte 22 GB; ostatni wiersz w bazie 11:59:17 UTC.

1. Zapisz czas (stoper) i uruchom w cmd:
```
ssh jumo@192.168.0.213 "uptime -s; date -u; docker ps --format '{{.Names}} {{.Status}}'; docker exec aip-timescaledb psql -U postgres -d energy -tAc 'select max(time) from measurements'"
```
2. Restart (hasło sudo wpisujesz Ty):
```
ssh -t jumo@192.168.0.213 "sudo reboot"
```
3. Odczekaj i powtarzaj do skutku (to jest „czas do SSH”, zapisz go stoperem):
```
ssh jumo@192.168.0.213 "uptime -s; docker ps --format '{{.Names}} {{.Status}}'"
```
4. Napisz mi „po restarcie” i podaj czas stopera od wydania `reboot` do pierwszego udanego `ssh`. Resztę (czas do pierwszego wiersza, długość luki, brak ponownego `migrate`, zachowanie ingest/collector, `docker logs`, powrót smartWARE, Grafana) zmierzę ja odczytami bez sudo; potem przygotuję migrację 011 z granicami z bazy i zrzut z luką w Grafanie wykonasz Ty.

## 8. Zasoby i limity (stan po wdrożeniu, 1 minuta po starcie)

Grafana 148,7 MiB / 512; ingest 26,0 / 128; collector 23,7 / 128; timescaledb 41,6 / 1536 (świeży start); mosquitto 1,3 / 64. To NIE jest pomiar po dobie – ten w części B (od 25.11 11:58 UTC, więc najwcześniej 26.11 po 12:00 UTC).

## 9. Otwarte i do decyzji architekta

1. Pełny test po poprawce NUL nie powtórzony (uzasadnienie w pkt 1) – powtórzyć w B?
2. Przyczyna obciążenia Grafany o 11:38 nieustalona; czy w części B dodać do Grafany log żądań (`GF_SERVER_ROUTER_LOGGING=true`) na czas obserwacji doby?
3. Luka 16 s przy wdrożeniu bez okna w `data_windows` – akceptujesz?
4. Test restartu czeka na Grzegorza; po nim migracja 011 i część B (kompresja, RAM po dobie, krok n4 – nazwa metryki `reactive_neg_varh`).



## 10. Wynik testu restartu (25.11.2026, wykonał Grzegorz: `sudo reboot`)

Czyste zamknięcie (nie utrata zasilania). Czasy UTC, z dziennika systemu, `docker inspect` i bazy:

| Zdarzenie | Czas UTC |
| --- | --- |
| ostatni wiersz w bazie przed przerwą | 12:03:47.557 |
| zatrzymanie collectora / bazy / ingestu przez systemd | 12:03:48.000 / 12:03:48.028 / 12:03:49 |
| koniec poprzedniego rozruchu w dzienniku | 12:03:54 |
| start jądra (nowy rozruch) | 12:04:08 |
| start Dockera (`Started Docker Application Container Engine`) | 12:04:19 |
| start kontenerów aip-* i smartWARE | 12:04:21–12:04:22 |
| start collectora, `plc: (start) -> OK` | 12:04:23.674, 12:04:24.708 |
| **pierwszy wiersz w bazie po restarcie** | **12:04:24.705** |

- **Luka w danych: 37,148 s** (ostatni wiersz → pierwszy po). Od startu jądra do pierwszego wiersza 16,7 s; od polecenia `reboot` ok. 37 s. Kryterium „< 5 min” spełnione z dużym zapasem. Po luce w każdej sekundzie dokładnie 20 wierszy (zapytanie o sekundy z n ≠ 20: 0 wierszy).
- **Autostart:** wszystkie 5 aip-* wstało samo (`restart: unless-stopped`, Docker `enabled`), bez `docker compose up`; przy pierwszym sprawdzeniu (kilkanaście sekund po starcie kontenerów) 4 `healthy`, Grafana `health: starting`, po minucie wszystkie `healthy`. `RestartCount` = 0 dla wszystkich.
- **`aip-migrate`:** nie uruchomił się ponownie (`StartedAt` 11:58:13, bez zmian), `schema_migrations` bez zmian.
- **Zachowanie usług:** collector i ingest zalogowały czyste zatrzymanie i start; ingest przy zatrzymaniu bazy zapisał „baza niedostępna … oczekujących: 14” (14 wiadomości bez potwierdzenia wróciło z brokera po wznowieniu sesji trwałej, bez duplikatów, `ON CONFLICT DO NOTHING`; sekunda 12:03:47 ma komplet 20 wierszy). Logi `docker logs` czytelne przed i po restarcie (sterownik `local`). Pętli ponowień z backoffem nie było potrzeba: Mosquitto i baza wstały przed collectorem i ingestem.
- **smartWARE** (tylko odczyt `docker ps`): wszystkie 7 kontenerów wstało 12:04:21–22 i po minucie `healthy` (`mqtt` i `postgres-server` bez healthchecka, Up). Ich logi nadal `json-file` (nie ruszane).
- **Grafana po rozruchu:** `/api/health` ok; pamięć 353 MiB / 512 po minucie, `memory.peak` 418 050 048 B (398,7 MiB = 77,9 % limitu), `oom_kill` = 0. To wyraźnie więcej niż 148,7 MiB po wcześniejszym wdrożeniu (start pod obciążeniem po rozruchu, gdy wstają też kontenery smartWARE); poniżej 80 %, ale blisko – do obserwacji w części B.
- **Czas SSH:** pierwsza próba Grzegorza po restarcie (timeout), druga udana ok. 12:04:33 UTC (kontenery „Up 11 seconds”), czyli ok. 45 s od polecenia (stoper od Grzegorza: do uzupełnienia, jeśli go zmierzył).

### Migracja 011 (okno `ipc_reboot`)

`db/migrations/011_data_windows_ipc_reboot.sql` z granicami 12:03:47.557 – 12:04:24.705 UTC (`exclude_from_analytics = TRUE`), test `test_ipc_reboot_window_matches_the_measured_gap`, liczba okien 13 → 14. Testy `tests/db` (data_windows, migrations, roles): 26 passed. Wdrożona przez R-1 (12:07:40 UTC): `applied 011`, `schema_migrations` 11 wierszy; odtworzona tylko Grafana i `migrate` (zależność od `migrate`), collector/ingest/baza/Mosquitto bez restartu, dane dalej 20 wierszy/s (1100 w 55 s). Jednocześnie `docs/stages/etap-2.md` zaktualizowany (11 migracji, 14 okien, pozycja 14 – wynik).

## 11. Stan części A i dalej

Część A zakończona. Do Grzegorza: zrzut z Grafany (np. dashboard „Jakość”, zakres 12:00–12:10 UTC) z adnotacją `ipc_reboot` i luką do dokumentacji (docs/images/etap2, nazwa wg dokumentu 04), oraz ewentualny czas ze stopera.
Część B (po 26.11 00:00 UTC; RAM po dobie od 25.11 11:58 UTC, więc najwcześniej 26.11 po 12:00 UTC): kompresja i rozmiar, RAM vs `mem_limit` z `memory.peak` i `oom_kill`, krok n4 (`reactive_neg_varh` 4800 → 4900), uzupełnienie `etap-2.md`.

Stop: czekam na review architekta części A.
