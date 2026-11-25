# E2 – krok 8 (k8, zamknięcie etapu 2): plan

Status: **sam plan, do review architekta.** Nic z poniższego nie zostało jeszcze wykonane poza odczytami tylko-do-odczytu opisanymi w sekcji 4.
Zasady: bez sudo po mojej stronie (polecenia z sudo wykonuje Grzegorz), bez ruszania smartWARE, bez czytania `.env`, PLC tylko odczyt, brak zmian architektury i `docs/modbus-map.md`.
Kolejność wdrożenia przy ewentualnych zmianach kodu/konfiguracji: R-1 (`git pull --ff-only` → `docker compose up -d --build` → `schema_migrations` + `docker logs aip-migrate`).

## 0. Wynik wstępnej diagnozy restartu Grafany (ważne dla review)

Review k4 zakłada „czysty stop, exit 0”. Dane z IPC temu przeczą:

| Źródło | Co pokazuje |
|---|---|
| `docker inspect` | `ExitCode=0`, `OOMKilled=false`, `RestartCount=1` (Docker zapisuje tak przy zabiciu przez jądro procesu, który nie jest PID 1 kontenera, albo gdy init przekazał kod 0 – sam `OOMKilled=false` niczego nie wyklucza) |
| `journalctl -k` (jądro) | **2026-11-25 11:38:14 (czas lokalny) = 10:38:14 UTC: `grafana invoked oom-killer`, `Memory cgroup out of memory: Killed process 1597394 (grafana) anon-rss:381728kB`**, cgroup kontenera `docker-f763f546…` (produkcyjna Grafana), `memory: usage 393216kB, limit 393216kB, failcnt 148` |
| `journalctl -u docker` | 11:38:14.992 `TaskDelete … ignoring event` dla tego samego kontenera, potem start (polityka `unless-stopped`) |
| `docker events` | brak historii (Docker nie przechowuje) |
| log Grafany | brak linii zamknięcia (proces zabity SIGKILL) |

Wniosek roboczy: restart o 10:38:15 UTC to **zabicie przez OOM-killera jądra przy limicie 384 MiB**, nie czysty stop i nie nasze `up -d` (`up -d` nie wygenerowałoby wpisu OOM). To samo zdarzyło się wcześniej: 24.11 23:05:16 i 23:06:22 (czas lokalny; wtedy k7, testy wizualne), w każdym przypadku `anon-rss` ≈ 380 MiB. Pozostałe wpisy OOM z 24.11 17:57 dotyczą kontenera Postgresa z środowiska testowego `aip-test` (k7, tmpfs), nie produkcji.
Dlatego k8 traktuje to jako **ustalenie do rozstrzygnięcia**, nie jako „czysty exit 0” (sekcja 4).

## 1. Test pełny na start

1. Na IPC po `git pull --ff-only`: `tests/run-tests.sh` (środowisko `aip-test`, tmpfs). Oczekiwane ok. 493 testów, 3 testy wydajnościowe pominięte.
2. Wynik (liczba passed/skipped/failed, czas) do raportu. Przy porażce: stop, analiza, osobna notatka; nie przechodzę do pomiarów na ślepo.
3. Po teście `docker compose -p aip-test down -v`, sprawdzenie, że nie zostały kontenery `aip-test-*` ani wolumeny (test z 25.11 11:37 sprzątał poprawnie).
4. Uwaga: test obciąża RAM i dysk IPC. Wykonuję go **przed** pomiarem RAM z sekcji 5, nie w trakcie.

## 2. Kompresja i rozmiar bazy po 26.11 00:00

Powód terminu: `compress_after = 1 day`, więc fragment (chunk) z 24.11 (dziś 147 MB, niekompresowany) i z 25.11 (93 MB do chwili pomiaru) zostaną skompresowane przez zadanie `policy_compression` dopiero po 26.11 00:00 UTC (zadanie działa cyklicznie; sprawdzam `next_start`).

Pomiar (po 26.11, najlepiej gdy chunk z 24.11 i 25.11 jest `is_compressed = t`):

```sql
-- 1) chunki i rozmiary
SELECT c.chunk_name, c.range_start::date, c.is_compressed,
       pg_size_pretty(d.total_bytes) AS size_total
FROM timescaledb_information.chunks c
JOIN chunks_detailed_size('measurements') d USING (chunk_name)
WHERE c.hypertable_name = 'measurements' ORDER BY c.range_start;
-- 2) przed/po kompresji
SELECT * FROM hypertable_compression_stats('measurements');
-- 3) wiersze na dobę (pełna doba 25.11 w stanie v2; 24.11 częściowo v1, osobno)
SELECT time_bucket('1 day', time) AS day, count(*) FROM measurements GROUP BY 1 ORDER BY 1;
-- 4) agregaty
SELECT hypertable_name, pg_size_pretty(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass))
FROM timescaledb_information.hypertables;
SELECT view_name, materialization_hypertable_name FROM timescaledb_information.continuous_aggregates;
```

Wyliczenia do raportu (z metodą, żeby dało się je powtórzyć):
- **B/wiersz po kompresji** = rozmiar skompresowanego chunku (tabela + indeksy + TOAST) / liczba wierszy w chunku; osobno dla doby z pełnym v2 (25.11 po 10:43 UTC jest mieszana: v1 do 10:43, v2 potem – dobę w pełni v2 będzie dopiero 26.11, więc pomiar końcowy na niej).
- **MB/dobę przy 20/s** = 1 728 000 wierszy/dobę × B/wiersz po kompresji (oraz bez kompresji, bo ostatnia doba zawsze jest niekompresowana).
- **Prognoza 90 dni** (retencja): 89 dób skompresowanych + 1–2 niekompresowane; wynik w GB, porównany z dostępnym miejscem (`df -h` na wolumenie Dockera, NVMe 1 TB).
- **Prognoza roku agregatów**: rozmiary `energy_1m` (retencja 1 rok), `energy_1h`, `energy_ext_1m`, `energy_ext_1h` ekstrapolowane z liczby wierszy na dobę i B/wiersz agregatu; w tym porównanie z syntetycznym rokiem z testu wydajnościowego (jeśli `AIP_PERF_KEEP` jest dostępne, opcjonalnie, nie jako zamiennik pomiaru z IPC).
- Zastrzeżenie w raporcie: dane z doby niepełnej / jednej doby to **oszacowanie**; rozkład wartości (stałe zużycie, liczniki rosnące) wpływa na stopień kompresji i prognoza nie obejmuje czujników drgań (symulowanych).

## 3. Pierwszy krok n4: 4800 → 4900 varh

Obserwacja jednorazowa, bez zmian w kodzie (n4 = `reactive_neg_varh` lub `reactive_pos_varh` wg `modbus-map.md` v2; nazwę metryki potwierdzam w `devices.yaml` przed zapytaniem – nie zgaduję).

```sql
SELECT time, value FROM measurements
WHERE metric = '<metryka n4>' AND time > now() - interval '12 hours'
  AND value IN (4800, 4900) ORDER BY time;     -- pierwsze wystąpienie 4900
```

Do raportu: czas przejścia, wartość przed/po, rozdzielczość licznika (krok 100 varh) zgodna z założeniem z k4; sprawdzenie, że `energy_ext_1h` i panel „energia bierna” pokazują przyrost 100 varh w tej godzinie. Jeśli krok jeszcze nie nastąpił do końca k8, pozycja zostaje otwarta w raporcie z gotowym zapytaniem (nie blokuje zamknięcia etapu).

## 4. Przyczyna restartu Grafany

Już zebrane (tabela w sekcji 0). W k8 domykam bez sudo (Jumo czyta `journalctl` jako grupa `adm`):

1. `journalctl -k --since 2026-11-25 --no-pager | grep -E "oom|Killed process"` – pełna lista zdarzeń od rozruchu (wykonane: 3× Grafana, 3× Postgres testowy).
2. `docker inspect aip-grafana -f '{{.RestartCount}} {{.State.StartedAt}} {{.HostConfig.RestartPolicy.Name}}'` oraz `docker compose logs` z okna 10:30–10:40 UTC (logi Grafany działają; uszkodzone `\x00` dotyczą innych kontenerów, sekcja 7).
3. Dopasowanie do aktywności: co robiło Grafanę o 10:38 UTC – żądania w logu (`/api/ds/query`, zakresy czasu), obecność otwartego dashboardu z dużym zakresem, uruchomiony w tym czasie test (`aip-test`, 11:37 lokalnie) – czy to współistniało.
4. **Odtworzenie kontrolowane** (nie na produkcji w godzinach pracy; na `aip-test` lub produkcji po uzgodnieniu): otwarcie 5 dashboardów z zakresem 1 rok i odświeżaniem 5 s, pomiar `docker stats` / `memory.peak` w cgroup (`/sys/fs/cgroup/system.slice/docker-<id>.scope/memory.peak`, `memory.events`) – czy szczyt dociera do 380 MiB i od czego (zapytanie z dużą liczbą punktów, zakres roczny, liczba paneli jednocześnie).
5. **Decyzja (propozycja, do akceptacji architekta):**
   - `mem_limit` Grafany 384 → **512 MiB** (+128 MiB; suma limitów kontenerów 2304 → 2432 MiB z 16 GB, smartWARE ok. 0,4–1 GB, więc budżet nie jest zagrożony),
   - ustawienie `GOMEMLIMIT=400MiB` (miękki limit środowiska uruchomieniowego Go: GC pracuje intensywniej zamiast dopuścić do OOM),
   - ewentualnie zmniejszenie obciążenia: `max_data_points` / minimalny interwał w zapytaniach, ograniczenie zakresu domyślnego w panelach rocznych.
   Wybór po pkt 4; bez pomiaru nie podnoszę limitu „na oko”.
6. Zmiana w `docker-compose.yml` przez R-1; test regresji: `tests/` sprawdzający `mem_limit` wszystkich kontenerów (jeśli taki test istnieje, rozszerzam; jeśli nie, dodaję prosty test konfiguracji).
7. Alarm obserwacyjny (propozycja, nie wdrażam bez zgody): jeśli `RestartCount` rośnie bez naszego działania, to osobny raport (jak w review k4).

## 5. RAM wszystkich `aip-*` po dobie pracy vs `mem_limit`

Termin: po min. 24 h od ostatniego wdrożenia (kontenery wstały 25.11 ~10:5x UTC po `up -d`, więc pomiar 26.11 po południu; jeśli zmiana limitu Grafany z sekcji 4 będzie wdrożona, doba liczy się od niej – ustalamy to w review).

```powershell
ssh jumo@192.168.0.213 "docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'"
ssh jumo@192.168.0.213 "free -m; uptime"
ssh jumo@192.168.0.213 "for c in aip-mosquitto aip-timescaledb aip-ingest aip-collector aip-grafana; do echo $c; cat /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' $c).scope/memory.peak /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' $c).scope/memory.events; done"
```

Raport: tabela kontener | `mem_limit` | użycie bieżące | **szczyt (`memory.peak`)** | % limitu | `oom_kill` z `memory.events`; plus `free -m` całego komputera i procesy smartWARE (tylko odczyt `docker stats`/`ps`, bez ingerencji). Kryterium: szczyt ≤ 80 % limitu; wyjątki opisane z uzasadnieniem. Zmierzone wartości, nie szacunki (reguła 2).

## 6. Test restartu komputera (wykonuje Grzegorz: `sudo reboot`)

Cel (z `plan.md` etap 2 i U4/U8): po restarcie wszystko wstaje samo, bez ręcznego `docker compose up`; ingest/collector czekają z backoffem; `migrate` nie uruchamia się ponownie; czas do zdrowego stosu i do pierwszego nowego punktu na wykresie < 5 min.

**Co mierzę (po stronie Claude, tylko odczyty po SSH, po powrocie IPC):**

| Pomiar | Jak |
|---|---|
| Czas od polecenia reboot do SSH | zapisuje Grzegorz (stoper) lub z `uptime -s` i `last -x` |
| Autostart usług | `systemctl is-active docker containerd`, `docker ps` – wszystkie `aip-*` Up / healthy bez ręcznej interwencji |
| `migrate` nie biegnie ponownie | `docker inspect aip-migrate` (`StartedAt` sprzed rebootu, `restart no`) i `schema_migrations` bez zmian |
| **Czas do pierwszego wiersza** po rozruchu | `SELECT min(time) FROM measurements WHERE time > '<boot UTC>'` minus czas rozruchu (`who -b`, `journalctl --list-boots`) |
| **Luka w danych** | `SELECT lag(time) …` z zapytania okien: ostatni wiersz przed rebootem → pierwszy po; długość luki w sekundach; porównanie z oknem w `data_windows` (dodanie okna `ipc_reboot` – decyzja do zatwierdzenia, tak jak `plc_program_download`) |
| Zachowanie ingest/collector | logi `docker logs aip-ingest`, `aip-collector` od startu: ponowienia z backoffem do czasu gotowości bazy/Mosquitto; brak pętli restartów (`RestartCount`) |
| Zdrowie | `docker inspect -f '{{.State.Health.Status}}'`, Grafana `/api/health`, 5 dashboardów ładuje się |
| smartWARE | kontenery/usługi smartWARE: tylko `docker ps` / `systemctl` przed i po (czy są Up); nie ruszam |
| Czas do „wszystko Healthy” | od `who -b` do ostatniego `healthy` (`docker events` nie ma historii – używam `StartedAt` + `Health.Log[0].Start`) |
| Pierwszy nowy punkt na wykresie | zrzut z Grafany (docs/images/etap2/2x-…) z zaznaczoną luką |

**Polecenia dla Grzegorza (wykonuje sam, na jumo-ipc):**

Przed (zapis stanu):
```powershell
ssh jumo@192.168.0.213 "uptime -s; docker ps --format '{{.Names}} {{.Status}}'; docker exec aip-timescaledb psql -U postgres -d aip -tAc 'select max(time) from measurements'"
```
Reboot (wymaga sudo, hasło wpisuje Grzegorz):
```powershell
ssh -t jumo@192.168.0.213 "sudo reboot"
```
Po (po powrocie SSH – informuje mnie „po restarcie”; stoper od wydania `reboot` do pierwszego udanego `ssh`):
```powershell
ssh jumo@192.168.0.213 "uptime -s; docker ps --format '{{.Names}} {{.Status}}'"
```
Reszta (zapytania, logi, luka) – ja. Warunki: uprzedni test w oknie bez pracy produkcyjnej; PLC niezależny (Modbus nadal odpowiada), więc luka w danych = czas rozruchu IPC + start stosu. Zastrzeżenie: ostatni reboot (utrata zasilania 24.11) miał uszkodzone logi `\x00`; **kolejność: najpierw naprawa logów (sekcja 7), potem reboot**, żeby po teście logi dało się czytać; jeśli Grzegorz woli odwrotnie, uszkodzenie logów po „czystym” `sudo reboot` ma być mniejsze i to też jest pomiar.

## 7. Naprawa uszkodzonych logów Dockera (`\x00`) – procedura z sudo dla Grzegorza

Stan: `docker logs` zawodzi dla `aip-ingest`, `aip-collector`, `aip-mosquitto` (plik JSON-log zawiera bajty `\x00` po nieczystym wyłączeniu 24.11). Naprawiamy **tylko pliki logów tych trzech kontenerów aip-***; bez restartu demona Dockera, bez dotykania smartWARE.

Krok 0 (ja, bez sudo – diagnoza, które pliki są uszkodzone): `docker inspect -f '{{.Name}} {{.LogPath}}'` dla `aip-*`, `docker logs --tail 5 <kontener>` → które kończą błędem.

Procedura (wykonuje Grzegorz; ja podaję gotowy skrypt `docs/ops/fix-docker-logs.sh` w k8 do wglądu przed uruchomieniem):

```powershell
# 1. Lista plików logów (bez sudo)
ssh jumo@192.168.0.213 "for c in aip-ingest aip-collector aip-mosquitto; do docker inspect -f '{{.Name}} {{.LogPath}}' $c; done"
# 2. Zatrzymanie tylko tych kontenerów (dane w bazie nie giną; po stop ingest przestaje zapisywać – luka potrwa do kroku 4)
ssh jumo@192.168.0.213 "cd ai-predykcja && docker compose stop ingest collector mosquitto"
# 3. Kopia zapasowa + wyczyszczenie samych plików logów (sudo, hasło wpisuje Grzegorz)
ssh -t jumo@192.168.0.213 "sudo sh -c 'for f in <ścieżki z kroku 1>; do cp -a $f $f.bak && : > $f; done'"
# 4. Start (kolejność z depends_on: mosquitto, ingest, collector)
ssh jumo@192.168.0.213 "cd ai-predykcja && docker compose start mosquitto ingest collector"
# 5. Weryfikacja (bez sudo)
ssh jumo@192.168.0.213 "docker logs --tail 5 aip-ingest; docker logs --tail 5 aip-collector; docker logs --tail 5 aip-mosquitto"
```

Zasady: kopie `.bak` zostają do akceptacji (usuwa Grzegorz); nie edytujemy `daemon.json` ani nie restartujemy demona (smartWARE korzysta z tego samego Dockera); skasowanie logów skraca historię do czasu naprawy – pożądane, bo uszkodzony fragment i tak nie jest czytelny. Luka w danych z kroku 2–4 (kilkadziesiąt sekund) wchodzi do raportu; collector ma bufor (30 000 próbek ≈ 25 min przy 20/s) i Mosquitto kolejkę, więc zwykle bez utraty, o ile `mosquitto` nie jest zatrzymany dłużej niż to konieczne. Rekomendacja: stop/start w jednym oknie ≤ 1 min.
Prewencja (propozycja do decyzji, bez wdrażania): `logging: driver: local` z `max-size` w `docker-compose.yml` (format binarny, odporny na uszkodzenia), ewentualnie osobna zmiana; wymaga zgody, bo zmienia konfigurację Compose.

## 8. `docs/stages/etap-2.md` – checklista akceptacji

Format jak `docs/stages/etap-1.md`: cel etapu, co powstało, polecenia do samodzielnego wykonania z oczekiwanym wynikiem i miejscem na wpis „OK / uwagi”. Grzegorz wykonuje wszystko sam; ja nie zaznaczam „zaliczone”. Zakres:

1. Stan stosu: `docker compose ps`, `docker stats --no-stream` (mem_limit), `ss -ltn` (porty: 502 tylko po stronie PLC; Grafana 3000, Mosquitto 1883 wg `ops`), brak `.env` w repo (`git ls-files | findstr .env`).
2. Migracje: `schema_migrations` (001–010), `docker logs aip-migrate`.
3. Zgodność z PLC: `mbpoll -c 60` vs ostatni wiersz w bazie (U ±0,5 V, P ±0,2 W, wg U8), mapa v2 (`docs/modbus-map.md`), cos φ z kąta.
4. Liczba wierszy: wzór 13/20/5/1 na sekundę, zapytanie z `status-codes.md` / `data-model.md`, 1200 s kontroli.
5. Grafana: 5 dashboardów (lista, wejście, zrzuty), odświeżanie na żywo, zgodność wartości z `psql` (energia, koszt, cos φ), panele zakresu własnego.
6. Stany błędów (U8, zrzuty 20–29 wg dokumentu 04): przerwanie RS485 (`meter_status ≠ 0`, 5 wierszy/s), PLC offline (1 wiersz/s, zrzut 20), powrót do OK; czas do powrotu danych.
7. **Restart komputera** (sekcja 6): wyniki, kryterium < 5 min do pierwszego nowego punktu.
8. Kompresja/rozmiar (sekcja 2): wartości i prognozy, miejsce na dysku.
9. RAM (sekcja 5): tabela z limitami.
10. Okna `data_windows` (13 + ewentualne `ipc_reboot`), `plc_program_download`.
11. Testy: `tests/run-tests.sh` (wynik z k8), pominięte 3 testy wydajnościowe i dlaczego (`run-perf.sh`).
12. Bezpieczeństwo/zasady twarde: collector tylko czyta (FC04; `grep` kodu pod FC05/06/15/16 → 0 wyników), brak danych urządzeń w kodzie, sekrety tylko `.env`, konto `app_reader` tylko do odczytu (próba INSERT odrzucona).
13. Ograniczenia znane (lista: zasięg zakresu, OOM Grafany jeśli nie rozstrzygnięty, `reactive_1h_calc` wolny, brak czatu/alarmów – etapy 3+).
14. Warunek zamknięcia: Grzegorz akceptuje `etap-2.md`; dopiero potem etap 3 (z wymaganiem z k2: powiększenie `awTcpInputRegs` i nowa wersja mapy – zgłaszam architektowi, nie zmieniam sam).

Dodatkowo na koniec k8: aktualizacja `docs/plan.md` (stan etapów, wpis o zamknięciu 2 po akceptacji), `docs/ops/jumo-ipc-setup.md` (restart, limit Grafany, procedura logów).

## 9. Lista materiałów do dokumentacji Word v2

Raporty: `docs/handoff/` (e2-plc1-diag, e2-k6/k7/k7c/k7d, e2-plc2-k2/k4/k8, review architekta), `docs/stages/etap-1.md`, `etap-2.md`, `docs/plan.md`, `docs/workflow.md`.
Specyfikacje: `docs/modbus-map.md` (v1+v2), `docs/status-codes.md`, `docs/data-model.md`, `docs/grafana.md`, `docs/ops/jumo-ipc-setup.md`, `docs/handoff/e2-k7-zakres.md`.
Zrzuty (`docs/images/etap1`, `etap2`): 01–09 istniejące (v2 w 09), dashboardy ×5 z poprawnymi danymi, zakres własny, kontrola energii, **stany błędów 20–29** (PLC offline, RS485, powrót), okno `plc_program_download`, wynik testu restartu, `docker stats`, rozmiar kompresji. Zrzuty wykonuje Grzegorz tam, gdzie wymaga to przeglądarki użytkownika; ja opisuję nazwy i treść wg dokumentu 04 (nazewnictwo 20–29).
Wydruki konsolowe: `mbpoll -c 60` v1 i v2, `docker compose ps`/`stats`, `psql` (wiersze/s, kompresja, `schema_migrations`), `journalctl -k` (zdarzenie OOM), wynik pytest, `ss -ltn`, test restartu (czas, luka).
**Typowe błędy i ich objawy** (do rozdziału „Rozwiązywanie problemów”): `docker compose up -d` bez `--build` nie stosuje migracji; plik z uprawnieniami po `git pull` (`chmod`); uszkodzone logi `\x00` po utracie zasilania; OOM Grafany (limit 384 MiB); `meter_status ≠ 0` (5 wierszy/s); PLC offline (1 wiersz/s); `reactive_1h_calc` wolny na rocznych zakresach; Mosquitto: zmiana konfiguracji wymaga `restart mosquitto`; zegar/strefa (Europe/Berlin vs UTC vs Warsaw); `energy_1h` bez FILTER (migracja 009); hasła/klucz Grafany w `.env` (`GF_SECURITY_SECRET_KEY`), nigdy w repo.
Liczby do dokumentu: budżet RAM (limity vs zmierzone), rozmiar bazy/dobę i prognozy, bufory (30 000 / 80 000), mapa wierszy/s.

## 10. Ryzyka

| Ryzyko | Postępowanie |
|---|---|
| Naprawa logów wymaga stop mosquitto/ingest/collector → luka w danych | okno ≤ 1 min, bufor collectora; wpis luki w raporcie; wykonanie w spokojnej porze |
| Reboot może znów uszkodzić logi lub nie podnieść stosu | najpierw naprawa logów; kopie `.bak`; w razie kłopotu zbieram `journalctl -b`, nic nie „leczę” na ślepo |
| Pomiar kompresji niemożliwy przed 26.11 00:00 UTC | k8 dzielę: część A (test, restart, logi, OOM, checklista) teraz, część B (kompresja, RAM po dobie) po 26.11 |
| OOM Grafany wraca przed rozstrzygnięciem | restart automatyczny działa (`RestartCount`); zmiana limitu i `GOMEMLIMIT` po pkt 4 |
| Test pełny + pomiar RAM w tym samym czasie zafałszuje pomiar | test przed pomiarem, rozdzielone w czasie |

## 11. Czego potrzebuję od architekta

1. Zgoda na podział k8 na część A i B (z terminami) oraz na kolejność: test → logi → reboot → pomiary po dobie.
2. Decyzja co do restartu Grafany: akceptacja korekty diagnozy („OOM-killer”, nie „czysty exit 0”) oraz zakresu środków (512 MiB + `GOMEMLIMIT`, ewentualnie ograniczenia zapytań) – po pomiarze z pkt 4.4.
3. Zgoda na okno `ipc_reboot` w `data_windows` (oraz ewentualnie okno naprawy logów) – nowa migracja 011, jak 006/010.
4. Zgoda na `logging: driver: local` w `docker-compose.yml` jako prewencję (albo odłożenie).
5. Potwierdzenie, że etap-2.md ma zawierać pozycje 1–14 z sekcji 8 i że kolejność zamknięcia to: akceptacja przez Grzegorza → etap 3.

Stop: czekam na review architekta i „ok” Grzegorza, nie zaczynam wykonywania.
