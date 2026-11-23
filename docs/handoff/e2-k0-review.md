# e2-k0 review: plan etapu 2 (kręgosłup danych)

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k0-plan.md`, `CLAUDE.md`, `docs/modbus-map.md` (stan 23.11.2026, po poprawce pkt 5 etapu 1), dokumenty projektu 00, 04, 10, 11.

## Werdykt: OK Z UWAGAMI

Plan jest zgodny z architekturą i zasadami twardymi. Kroki k1–k8 kończą się czymś sprawdzalnym, collector tylko czyta (FC04, klasa bez metod zapisu, test „żaden kod zapisu nie dotarł”), suma `mem_limit` mieści się w budżecie, sekrety są w `.env`. Uwagi U1–U8 trzeba uwzględnić w planach kroków, których dotyczą (bez ponownego planu e2-k0). Po „ok” Grzegorza: start od **e2-k1-plan**.

## Zmiana po stronie PLC (informacja, kontrakt bez zmiany wersji)

Test 5 etapu 1 wykazał, że `status` licznika chwilami pokazywał 0 w trakcie przerwy RS485. `FB_EnergyMeter` ma teraz filtr 3 s. `docs/modbus-map.md` doprecyzowuje pola 10–15:

- `status` = 1 od pierwszego błędu, powrót do 0 dopiero po 3 s bez błędu;
- `error_count` = liczba przerw (jedna przerwa = +1);
- `data_age_ms` rośnie równo przez całą przerwę.

`MAP_VERSION` = 1, układ rejestrów bez zmian. Do commitu razem z tym review: `plc/src/FB_EnergyMeter.st`, `docs/modbus-map.md`, `docs/stages/etap-1.md`, `docs/images/etap1/12-rtu-break-status.png`, `13-plc-restart-mbpoll.png`, `24-err-mbpoll-boot-connection-failed.png` oraz `plc/setup/10.2.1.1-new_1.431.432` po zapisie przez Grzegorza.

Heartbeat rośnie ok. 6 na sekundę (86 → 92 w odczytach co 1 s). Reguła „> 5 s bez zmiany” bez zmian.

## Decyzje Grzegorza (23.11.2026)

| Id | Decyzja |
| --- | --- |
| D1 | Temat MQTT: `zaklad1/linia1/{device_id}/{metric}`, czyli `site: zaklad1`, `line: linia1` w `config/devices.yaml` |
| D2 | `ts` z zegara komputera, UTC, ms – **zatwierdzone** |
| D3 | Dwa konta MQTT `collector` (tylko publikacja) i `ingest` (tylko subskrypcja), ACL, zmienne `MQTT_COLLECTOR_*`, `MQTT_INGEST_*` – **zatwierdzone** |
| D4 | Jednorazowy kontener `migrate` + `schema_migrations` – **zatwierdzone**, z uwagą U5 (role też w `migrate`) |
| D5 | Repo na komputer: **deploy key tylko do odczytu** (osobny klucz ed25519 komputera `jumo-ipc`, dodany w GitHub → repo → Settings → Deploy keys, bez „Allow write access”), `git clone` przez SSH, aktualizacja `git pull`. Klucz prywatny zostaje na komputerze (`~/.ssh/`, prawa 600), nie trafia do repo |
| D6 | Przyrosty energii: widoki z `LAG`, bez `timescaledb_toolkit` – **zatwierdzone** |
| D7 | **Energia przy rozdzielczości 100 Wh: całka mocy + stan licznika.** Zużycie w krótkich oknach (minuta, godzina) z całki mocy czynnej, a stan licznika (mantysa × 10^wykładnik) jako wartość wzorcowa i kontrola na dłuższych oknach. Rejestry o podwyższonej rozdzielczości (30462–30485) sprawdzamy w etapie 4, przed decyzją o źródle kosztów. W etapie 2 bez zmian w PLC i mapie |
| D8 | Tabele spoza etapu 2 nie powstają – **zatwierdzone** |
| D9 | Przypięte wersje obrazów i bibliotek, wpisane do raportów – **zatwierdzone** |
| D10 | `link_status` i `meter_status` jako metryki MQTT – **zatwierdzone**, z uwagami U1 i U2 |
| D11 | **Repozytorium Dockera (k1): `focal` → `jammy` + blokada wersji.** Kopia pliku źródła przed zmianą, zamiana tylko we wpisie Dockera, `sudo apt update` bez ostrzeżeń, potem `sudo apt-mark hold docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin` (tylko pakiety faktycznie zainstalowane – sprawdzić `dpkg -l | grep -i docker`). **W etapie 2 żadnego `apt upgrade` pakietów Dockera**: aktualizacja restartuje demona, a z nim kontenery JUMO smartWARE. Wynik `apt-mark showhold` do raportu k1 |

## Uwagi (do uwzględnienia w planach kroków)

### U1 (k2, k4) – PLC jako urządzenie w `devices`

`plc-01/link_status` ma `device_id = plc-01`, którego nie ma w `devices`, więc ingest odrzuciłby go jako nieznane urządzenie. PLC musi być synchronizowany z `devices.yaml` do tabeli `devices` (np. `kind: plc`, `source: real`). Test ingestu: `link_status` od PLC trafia do bazy.

### U2 (k3) – błąd numeru seryjnego na poziomie licznika

Niezgodny `serial` dotyczy jednego bloku licznika, nie całego PLC. Przy dwóch licznikach pomyłka w jednym nie może blokować drugiego. Propozycja:

- `link_status`: 0 OK, 1 PLC offline, 2 PLC zatrzymany, 3 zła `map_version`;
- `meter_status`: 0–2 wprost z rejestru 10, a 10 = SERIAL_MISMATCH (wyliczany przez collector).

Kody opisane w `config/devices.yaml` albo w `docs/` i w jednym miejscu w kodzie (enum), z tłumaczeniem na polski w Grafanie. Reguła 5 kontraktu (serial) blokuje wtedy tylko pomiary tego licznika.

### U3 (k2) – porty na hoście

- **Mosquitto:** w etapie 2 nie wystawiamy 1883 w LAN. Collector, ingest (a później symulator) są w sieci Compose. Albo bez `ports`, albo `127.0.0.1:1883:1883` do testów `mosquitto_pub/sub`. Wystawienie w LAN dopiero, gdy pojawi się zewnętrzny wydawca, z osobnym kontem.
- **Grafana 3000 w LAN** – akceptowane (demo z laptopa), pod warunkami: hasło admina z `.env` (`GF_SECURITY_ADMIN_PASSWORD`), `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`, brak domyślnego `admin/admin`.
- **Baza:** bez portu na hoście – zgodnie z planem.
- Raport k2 zawiera `ss -ltn` po starcie (oczekiwane: 3000 w LAN, 1883 najwyżej na 127.0.0.1; 80/443 nadal smartWARE).

### U4 (k3, k4, k8) – start po restarcie komputera

`depends_on` z `condition` stosuje tylko `docker compose up`. Po restarcie komputera demon Dockera uruchamia kontenery z `restart: unless-stopped` bez kolejności, a `migrate` się nie uruchomi (`restart: "no"`). Wymagania:

- collector i ingest same czekają z ponawianiem na MQTT i bazę (cofanie wykładnicze, logi bez zalewania), żadna usługa nie kończy się błędem z braku zależności;
- ingest nie zakłada, że `migrate` przebiegło w tym uruchomieniu; przy braku tabel czeka i loguje;
- test k8 obejmuje restart komputera **bez** ręcznego `docker compose up`.

### U5 (k2) – role bazy w `migrate`, nie tylko w `initdb`

`db/init/00-roles.sh` działa tylko przy pierwszym utworzeniu wolumenu. Role i hasła tworzy / aktualizuje `migrate` przy każdym uruchomieniu (idempotentnie: `CREATE ROLE … IF NOT EXISTS` przez blok `DO`, `ALTER ROLE … PASSWORD` z `.env`). Dla `app_reader`:

- `GRANT SELECT` na tabele, widoki i agregaty ciągłe;
- `ALTER DEFAULT PRIVILEGES` dla obiektów tworzonych w kolejnych migracjach;
- `ALTER ROLE app_reader SET statement_timeout` (wartość w raporcie);
- brak `CREATE` na schemacie.

Test: `app_reader` nie może INSERT ani CREATE, a zapytanie dłuższe niż limit zostaje przerwane.

### U6 (k2) – pamięć TimescaleDB

Obraz `timescale/timescaledb` przy pierwszym starcie uruchamia `timescaledb-tune`. Bez ustawienia może przyjąć pamięć całego komputera (16 GB) zamiast limitu kontenera. Ustawić jawnie `TS_TUNE_MEMORY` zgodne z `mem_limit` (1536 MB) albo `NO_TS_TUNE=true` i parametry w konfiguracji (`shared_buffers` ok. 384 MB, `effective_cache_size`, `work_mem`, `max_connections` 30). Raport k2: wynik `SHOW shared_buffers; SHOW max_connections; SHOW work_mem;`.

### U7 (k5, k6, checklista) – liczby i czas

- Metryki na sekundę: 7 pomiarów + 2 stany liczników energii + `link_status` + `meter_status` = 11 → **ok. 660 wierszy na minutę** (nie 540–600). Checklista podaje wzór, nie tylko liczbę.
- Strefa czasowa komputera to **Europe/Berlin** (dokument 10) i jej nie zmieniamy (smartWARE). k1 sprawdza tylko synchronizację NTP. Baza w UTC (`timestamptz`), Grafana wyświetla Europe/Warsaw.
- Całka mocy (D7): `energy_integral_wh = sum(active_power) × poll_interval_s / 3600` z faktycznej liczby próbek (`sample_count`); luki nie są dopełniane. Widok porównujący całkę z przyrostem licznika na dobie (odchyłka w %) – do k6, z testem.
- Bufor Mosquitto dla sesji ingestu: przy 11 wiadomościach na sekundę 60 min to ok. 40 tys. wiadomości. Ustawić `max_queued_messages` i `max_queued_bytes` z zapasem w limicie 64 MB, opisać w raporcie k4.

### U8 (k5, k7, k8) – checklista i zrzuty

Dodać do checklisty etapu 2:

1. **Przerwa RS485** (jak pkt 5 etapu 1): na dashboardzie „licznik: błąd komunikacji”, w bazie brak pomiarów licznika w tym czasie, potem powrót bez ingerencji.
2. **PLC offline** – już jest; zrzut stanu błędu jako `docs/images/etap2/20-…`.
3. **Zgodność wartości:** Grafana vs `mbpoll` w tej samej chwili – napięcie ±0,5 V, moc ±0,2 W.
4. **Restart:** zmierzony czas od włączenia do stanu `healthy` i pierwszego nowego punktu na wykresie; cel < 5 min.

Zrzuty dodatkowe: po k2 (`docker compose ps` healthy, odmowa `mosquitto_sub` bez hasła), po k5 i k8 stany błędów (20–29). Nazewnictwo wg dokumentu 04.

## Drobne

- `README.md`: poprawić sprzęt na 16 GB / 1 TB, jeśli nadal podaje 8 GB / 128 GB (dowolny krok, osobny commit).
- `.env`: prawa 600, w `.gitignore` (sprawdzić), hasła generowane np. `openssl rand -base64 24`. Hasła wpisuje Grzegorz.
- `config/devices.yaml` montowany do kontenerów tylko do odczytu (`:ro`).
- Opcjonalnie collector publikuje też `meter_error_count` i `meter_data_age_ms` (rej. 12, 14–15) – przydatne do alarmów w etapie 5; decyzja Claude Code w k3, bez zmiany kontraktu.

## Budżet RAM (sprawdzone)

Limity etapu 2: 2240 MB (+64 MB chwilowo `migrate`). Razem z systemem (ok. 1 GB), smartWARE (0,4–1 GB), rezerwą na Ollamę (ok. 3 GB) i późniejszymi usługami (ok. 1,5 GB) to ok. 9–9,5 GB z 15 GiB widocznych. Akceptowane; raport k8 podaje zużycie zmierzone (`docker stats --no-stream`, `free -m`), w tym smartWARE.

## Następny krok

Claude Code: commit plików etapu 1 i tego review, potem `docs/handoff/e2-k1-plan.md` (k1 z decyzjami D5 i D11, uwaga U7 o strefie czasowej) → stop.
