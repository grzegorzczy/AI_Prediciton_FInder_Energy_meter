# e2-k3 review: collector (Modbus TCP → MQTT)

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k3-plan.md` (commit `271bb92`), `docs/modbus-map.md` (po poprawce filtra 3 s), `config/devices.yaml`, `e2-k0-review.md`, `e2-k2-report-review.md`, dokumenty projektu 00, 11, 12.

## Werdykt: OK

Plan jest zgodny z kontraktem PLC, zasadami twardymi i decyzjami D2, D10 oraz uwagami U2, U4, R2-U1…U3. Zasadę 1 (do PLC nie piszemy) zabezpieczają trzy warstwy, z czego dwie ostatnie sprawdzają testy:
1. `ReadOnlyModbusClient` wystawia wyłącznie odczyt;
2. w źródłach nie ma nazw metod zapisu;
3. atrapa PLC rejestruje kody funkcji, a test wymaga, by docierał tylko `{4}`.

Dobrze przemyślane:
- ocena `status` przed `serial`, żeby uniknąć fałszywego SERIAL_MISMATCH przy NO_DATA;
- wstrzymanie publikacji pomiarów do pierwszej zmiany heartbeatu, żeby po połączeniu nie zapisać zamrożonych rejestrów zatrzymanego PLC;
- brak drugiego filtru (filtr 3 s jest w PLC);
- `retries=0` w pymodbus, żeby awaria PLC nie blokowała cyklu na kilkanaście sekund;
- logi tylko przy zmianie stanu;
- healthcheck „pętla żyje”, a nie „PLC działa”;
- utwardzenie kontenera;
- profil `live` do k5.

Uwagi K3-U1…U4 są drobne i nie wymagają nowego planu.

## Decyzje K3-a…K3-k – wszystkie zatwierdzone

| Id | Rozstrzygnięcie |
| --- | --- |
| K3-a | Diagnostyka `meter_error_count`, `meter_data_age_ms` w MQTT – **zatwierdzone**; nowa liczba: **13 wiadomości/s = 780 wierszy/min** (zastępuje 660 z U7) |
| K3-b | `status` przed `serial`; nieznany `status` publikowany surowo + ostrzeżenie – zatwierdzone (zgodne z kontraktem, dokumentacja mapy bez zmian) |
| K3-c | nie-root, `read_only`, `cap_drop: ALL`, `no-new-privileges` – zatwierdzone |
| K3-d | Statusy w każdym cyklu – zatwierdzone |
| K3-e | Bufor 20 000, odrzucane najstarsze, log raz na epizod – zatwierdzone; asymetria z Mosquitto (odrzuca najnowsze) opisana w raporcie |
| K3-f | Profil `live` do k5 – zatwierdzone |
| K3-g | `timeout_s` 2 s, ponawianie 1 → 10 s w `devices.yaml` – zatwierdzone |
| K3-h | Pomiary dopiero po pierwszej zmianie heartbeatu; po 5 s bez zmiany `link_status = 2` – zatwierdzone |
| K3-i | Zły config przy starcie → kod ≠ 0 – zatwierdzone |
| K3-j | Atrapa PLC i collector w procesie pytest, prawdziwy broker – zatwierdzone |
| K3-k | Jeden `ts` na odczyt – zatwierdzone (D2) |
| R2-U1 | Kolejność poleceń `chmod` i kontrola `find`/`stat` – zatwierdzone; `.git` nieruszany |
| R2-U3 | `deny Grep` + weryfikacja na atrapie `docs/decoy/.env` (ignorowana `*.env`), atrapa usunięta – zatwierdzone |

## Uwagi

### K3-U1 – `source` z konfiguracji, nie stała w kodzie

Plan pisze o ładunku z `source: "real"`. Wartość ma pochodzić z pola `source` urządzenia w `devices.yaml`, a dla `plc-01` z konfiguracji PLC (domyślnie `real`), nie ze stałej w kodzie (reguła 3). Dzięki temu ten sam collector obsłuży w przyszłości np. PLC testowe jako `sim`. Test w `test_payload.py`: urządzenie z `source: sim` w konfiguracji testowej daje `"source": "sim"`.

### K3-U2 – liczba wierszy i dysk

780 wierszy na minutę to ok. 1,12 mln wierszy na dobę i ok. 101 mln w 90 dniach. Szacunek dysku z k0 (rząd kilku GB po kompresji) nadal obowiązuje; pomiar po dobie w k8. Checklista k5 podaje wzór (7 + 2 + 3 diagnostyka/status licznika + 1 `link_status` = 13/s), nie samą liczbę.

### K3-U3 – zadanie dla k7 (Grafana)

Przy `link_status ≠ 0` collector nie publikuje `meter_status`, więc ostatnia wartość w bazie może być nieaktualna („0” sprzed awarii PLC). Kafelek stanu licznika w Grafanie ma uwzględniać `link_status` (np. „brak danych z PLC”, gdy `link_status ≠ 0` albo ostatni `meter_status` starszy niż kilka sekund). Zapisać jako zadanie k7, obok K2-U5.

### K3-U4 – drobne

- Raport k3 podaje zmierzony czas jednego cyklu odczytu na atrapie oraz czas wykrycia „offline” przy wyłączonym serwerze (oczekiwane ≤ `timeout_s` + 1 s).
- `docs/status-codes.md`: wpisać też zachowanie czasowe – NO_DATA do ok. 10 s po starcie PLC, brak pomiarów ok. 3 s po przerwie RS485 (filtr PLC), ok. 1 s po połączeniu (K3-h). Te opisy trafią do dokumentacji Word.
- Przy usuwaniu profilu `live` w k5 sprawdzić, że `docker compose up -d` startuje collector razem ze stosem bez `--profile`.

## Kontrola reszty planu

- Kontrakt `docs/modbus-map.md`: FC04, Unit ID 1, 0–43 jednym zapytaniem, starsze słowo pierwsze, reguły ważności 1–5 (kolejność licznika uzasadniona), pola 10–15 wg filtra 3 s – ✔. Mapa nie jest zmieniana – ✔.
- Reguła 3: adres, rejestry, nazwy metryk, limity czasu w `devices.yaml`; test przeszukujący źródła – ✔.
- RAM: +128 MB → 1728 MB stale dla `aip-` – ✔.
- Bezpieczeństwo:
  - collector bez portów na hoście;
  - hasło MQTT tylko w środowisku i nigdy w logu;
  - konto `collector` może tylko publikować;
  - `.env` nie jest wypisywany – ✔.
- „Gotowe, gdy” k3 sprawdzalne bez sprzętu (pytest, budowa, `config --quiet`, nie-root, prawa plików, `deny`) – ✔. Test na prawdziwym PLC to k5 – zgodnie z listą kroków.

## Checklista Grzegorza po k3

Brak czynności – k3 nie dotyka sprzętu ani GUI. (Okno konsoli z `umask 077` – zamknięte po k2.)

## Następny krok

Po „ok” Grzegorza: Claude Code wykonuje k3 (najpierw R2-U1 i R2-U3), z uwagami K3-U1…U4 → `e2-k3-report.md` → stop.
