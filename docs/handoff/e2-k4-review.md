# e2-k4 review: ingest (MQTT → walidacja → paczki → baza)

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k4-plan.md` (commit `63b3210`), `e2-k3-report-review.md`, `e2-k0-review.md` (U1, U4, U7), `e2-k2-report-review.md` (R2-U2), `config/mosquitto/mosquitto.conf`, `db/migrations/001_core.sql`.

## Werdykt: OK

Plan realizuje wszystkie wymagania z „Następnego kroku” review k3:
- `plc-01` trafia do `devices` (U1);
- ingest czeka na bazę i schemat i nie kończy się przy ich braku (U4);
- synchronizacja z `enabled = false` dla usuniętych wpisów;
- walidacja (`source` zgodne z urządzeniem, `ts` nie z przyszłości);
- `ON CONFLICT DO NOTHING`;
- wprost opisana utrata danych przy długiej przerwie (R2-U2).

Najmocniejszy element to **potwierdzenie wiadomości dopiero po zapisie w bazie** (ręczny `ack`, sesja trwała, stały `client_id`). Awaria ingestu lub bazy nie gubi danych w granicach bufora brokera, a ponowne dostarczenie nie tworzy duplikatów. Dobrze uzasadniony jest limit paczki 100 = `max_inflight_messages` brokera. Dymek w prawdziwym stosie bez zapisu do `measurements` zostawia czystą tabelę do liczenia wierszy w k5.

## Decyzje K4-a…K4-j – wszystkie zatwierdzone

| Id | Rozstrzygnięcie |
| --- | --- |
| K4-a | Własny minimalny parser `devices.yaml` w ingeście – zatwierdzone (zgodność obu parserów pilnują testy) |
| K4-b | Ręczne `ack` po zapisie, MQTT v3.1.1, sesja trwała, `client_id` `aip-ingest`, paczka 100 / 1 s – zatwierdzone |
| K4-c | Okno `ts`: +5 min / −400 dni, w zmiennych środowiskowych – zatwierdzone (wiersze starsze niż 90 dni usunie retencja – akceptowane dla wypełniania historii symulatora) |
| K4-d | Nieznane metryki znanych urządzeń akceptowane, nowa para logowana raz – zatwierdzone |
| K4-e | Odrzucenia potwierdzane od razu, liczniki wg powodu, podsumowanie co 60 s – zatwierdzone |
| K4-f | Przeładowanie configu tylko przez restart – zatwierdzone (do rozważenia w etapie 7) |
| K4-g | Ingest startuje ze stosem, dymek bez zapisu do `measurements` – zatwierdzone |
| K4-h | 128 MB, nie-root uid 10003, `read_only`, `cap_drop: ALL`, `no-new-privileges` – zatwierdzone; suma `aip-` 1856 MB |
| K4-i | Zdrowie „pętla żyje” – zatwierdzone (spójne z collectorem i U4) |
| K4-j | Jedno połączenie, `statement_timeout` 30 s dla ingestu – zatwierdzone |

## Uwagi (drobne, bez nowego planu)

### K4-U1 – wygaśnięcie sesji trwałej

`persistent_client_expiration 7d` w `mosquitto.conf`: jeśli ingest nie połączy się z brokerem przez ponad 7 dni, broker usunie jego sesję wraz z kolejką. Od tej chwili wiadomości nie są kolejkowane, aż ingest znów się zasubskrybuje. Dla demo akceptowalne. Dopisać jedno zdanie w raporcie k4 i w `docs/ops` (sekcja „utrata danych”), obok R2-U2.

### K4-U2 – potwierdzić założenia brokera liczbami

W `test_resilience.py` / raporcie:
- przy niedostępnej bazie liczba wiadomości w locie do ingestu zatrzymuje się na 100 (założenie `max_inflight_messages`), a reszta czeka w kolejce sesji;
- po powrocie bazy wszystkie wiadomości trafiają do bazy, liczba wierszy = liczba wysłanych (bez strat i duplikatów);
- zmierzona przepustowość ingestu (wiadomości/s) jako punkt odniesienia dla etapu 3 (ok. 65/s plus wypełnianie historii).

Jeśli zachowanie `manual_ack` w paho 2.2.0 okaże się inne niż zakładane, zatrzymać się i zgłosić (zgodnie z planem).

### K4-U3 – dymek w prawdziwym stosie

Oprócz odrzucenia nieznanego urządzenia sprawdzić w logu ingestu:
- brak hasła i treści zapytań SQL;
- obecność jednego wpisu synchronizacji `devices` i potwierdzenia subskrypcji;
- że `meta` urządzeń nie zawiera adresu IP (zapytanie `SELECT device_id, kind, source, enabled, meta FROM devices`).

### K4-U4 – przygotowanie k5

Checklista k5 przyjmie z k4:
- oczekiwana liczba wierszy: 13/s = 780/min przy sprawnym PLC i liczniku (tolerancja ±2%, bo cykle mogą być pominięte);
- ingest bez odrzuceń (`rejected = 0` w podsumowaniu) przy prawdziwych danych.

## Kontrola reszty planu

- Zasady twarde: brak kontaktu z PLC; dane urządzeń tylko z `devices.yaml` (test `test_no_hardcoding.py`); sekret tylko `APP_WRITER_PASSWORD`, nigdy w logu; brak `DELETE/DROP/TRUNCATE`; `mem_limit` – ✔.
- Bezpieczeństwo: konto MQTT `ingest` tylko do odczytu, rola `app_writer` bez DDL, kontener bez portów i utwardzony; adres IP PLC nie trafia do bazy – ✔.
- U4: test ingestu wystartowanego przed bazą i przed `migrate` – ✔ (to sedno testu k8).
- „Gotowe, gdy” k4 sprawdzalne bez sprzętu (pytest, `ps`, `devices` = 2 wiersze, `measurements` = 0) – ✔.

## Checklista Grzegorza po k4

Brak czynności.

## Następny krok

Po „ok” Grzegorza: Claude Code wykonuje k4 wg planu z uwagami K4-U1…U4 → `e2-k4-report.md` → stop.
