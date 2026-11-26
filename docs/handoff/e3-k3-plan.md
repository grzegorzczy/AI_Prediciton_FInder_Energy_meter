# E3-k3 – plan kroku: usługa symulatora na żywo, konto MQTT i ACL, rozdzielenie real/sim, kotwice, pamięć sum dobowych

Data: 2026-11-26. Podstawa: `e3-k0-plan.md` (k3), `e3-k1-report-review.md` (K1-D1, K1-D2), `e3-k2-report-review.md` (K2R-D1, K2R-D2, K2R-D3, K2R-U1, K2R-U4, K2R-U5). Review k2 zacommitowane w `f98279a`.
**Sam plan, do review.** W k3 produkcja się nie zmienia: `~/ai-predykcja` zostaje na `c299eaa`, Mosquitto bez restartu, kontener `aip-simulator` nie startuje na produkcji (to k7). Testy z worktree `~/ai-predykcja-dev` w `aip-test`; obraz symulatora budowany na IPC tylko pod tagiem testowym.

## Cel kroku

Kontener `aip-simulator` publikuje co 1 s 29 wiadomości `{ts, value, unit, source: "sim"}` do `zaklad1/linia2/<urządzenie>/<metryka>`; ingest je zapisuje. Broker pozwala każdemu kontu pisać tylko do jego linii. Konfiguracja symulatora ma dwie niezależne daty (liczniki, łożysko), a start licznika energii po miesiącach od kotwicy trwa sekundy dzięki pamięci sum dobowych w pliku.

## 1. Kotwice (K2R-D1, K2R-D2)

- W `config/devices.yaml`, sekcja `simulator`: **usuwam `t_zero` i `degradation.history_progress`**; dochodzą:
  - `meter_anchor: null` – stała data kotwicy liczników energii (w tej chwili licznik = `energy_start_wh`); po wdrożeniu nigdy niezmieniana;
  - w urządzeniu pompy `bearing_installed_at: null` – data montażu łożyska; **x = 0 w tej chwili**, x = (t − montaż) / `degradation.days_total`.
- Oba pola: data ISO 8601 ze strefą, pełna minuta. `null` jest dozwolony **w pliku** (do k7), ale `Simulator` przy starcie woła `require_meter_anchor()` i `require_bearing_installed_at()` i przy `null` kończy się `ConfigError` (kod 2) z komunikatem, co ustawić i kiedy (k7). Nic nie podstawia „teraz” (sens K1-U2 bez zmian).
- Wdrożenie (k7): `meter_anchor` = wdrożenie − 14 dni (`history.meter_days`), `bearing_installed_at` = wdrożenie − 84 dni (x = 0,70 „teraz”, K0-D2). Opis w `docs/ops`.
- **Wymiana łożyska = nowa `bearing_installed_at`** (x = 0, drgania ok. 1,1 mm/s) + okno `data_windows` `sim_reset`; liczniki energii nietknięte; historii nie wgrywamy ponownie (K2R-D2). Poprawiam opis w `pump.py` i `docs/data-model.md` (dziś „nowe t_zero”).
- Biblioteka: `EnergyCounter.anchor = meter_anchor`; `PumpModel` liczy x od `bearing_installed_at`; obcinanie x > 1 i ostrzeżenie zostają. Testy k2 przechodzą na nowe pola (wartości kontrolne krzywej: montaż + x · 120 dni; x = 0,70 w dniu 84 po montażu).

## 2. Pamięć sum dobowych w pliku (K2R-D3)

- Plik `/var/lib/simulator/energy-days.json` w wolumenie `aip_simulator_data` (jedyne miejsce zapisu; kontener `read_only`).
- Zawartość: `{"format": 1, "key": "<sha256>", "devices": {"sim_…": {"<doba>": <W·s>, …}}}`; doba = numer bloku 86 400 s od `meter_anchor` (UTC; czas letni nie zmienia klucza), wartość = suma W·s (liczba całkowita, jak w k2).
- **Klucz** = sha256 z: stałej `MODEL_VERSION` w kodzie, `seed`, `meter_anchor`, kalendarza, otoczenia i parametrów modelu każdego licznika (kanoniczny JSON). Zmiana kodu modelu wymaga podbicia `MODEL_VERSION` (test pilnuje, że stała istnieje i wchodzi do klucza); inny klucz = plik ignorowany (INFO) i przeliczenie.
- **Kontrola przy starcie:** ostatnia zapisana doba każdego licznika przeliczana od zera i porównywana co do W·s; niezgodność = WARNING, odrzucenie całego pliku, pełne przeliczenie.
- **Zapis atomowy** (plik tymczasowy w tym samym katalogu + `os.replace`) po każdej nowej pełnej dobie i po przeliczeniu startowym. Brak, uszkodzony JSON albo brak praw zapisu = przeliczenie i WARNING, nie błąd (symulator działa dalej, tylko wolniej przy starcie).
- Pamięć jest wyłącznie przyspieszeniem: wynik z pliku i z rachunku identyczny co do W·s (test), plik można w każdej chwili usunąć.
- **Pomiar do raportu:** start po 14 / 90 / 365 dniach od kotwicy **z plikiem i bez**. 14 dni – zmierzone w teście; 90 dni – jednorazowy pomiar w `run-perf.sh` (przeliczenie bez pliku ok. 4–5 min, potem start z plikiem); 365 dni – start z plikiem zmierzony na pliku z 365 dobami (sumy dób przeliczone raz w teście wydajności, ok. 20 min; jeśli za długo, prognoza z 90 dni z opisem metody).

## 3. Usługa na żywo `aip-simulator`

- `simulator.main`: wczytanie configu (`DEVICES_CONFIG`), `require_*` (pkt 1), pamięć sum (pkt 2), połączenie MQTT, pętla 1 s.
- **Pętla:** tick na pełnej sekundzie zegara ściennego (UTC; jedyne użycie zegara – wartości nadal są funkcją chwili); dla chwili t: `samples_at(t)` → 29 wiadomości, `ts` = ISO 8601 UTC z ms (`…:00.000Z`), QoS 1. Gdy pętla spóźni się o więcej niż 5 s (np. zatrzymany proces), przeskakuje do „teraz” i loguje lukę raz (luki uzupełnia historia w k5, idempotentnie).
- **Publikacja:** paho-mqtt 2.2.0, MQTT v5, konto `MQTT_SIM_USER`/`MQTT_SIM_PASSWORD` z `.env`, `client_id` `aip-simulator`, ponowne łączenie z cofaniem; przy niedostępnym brokerze ograniczony bufor (`SIM_BUFFER_MAX`, propozycja 36 000 wiadomości ≈ 20 min przy 29/s; najstarsze odrzucane, log raz na epizod) – ten sam wzorzec co publisher collectora (kod własny symulatora, bez importu z collectora; usługi niezależne).
- `simulator.health`: „pętla żyje” (plik w `/tmp` odświeżany przez pętlę, jak collector), nie „broker działa”.
- Logi: start (urządzenia, linia, kotwice, x pompy, źródło pamięci sum: plik / przeliczenie i czas), zmiana stanu połączenia, luki, raz na proces koniec krzywej pompy.

### Obraz i Compose
- `services/simulator/Dockerfile`: ten sam obraz bazowy co collector (`python:3.12.16-slim-trixie@sha256:…`), `PYTHONTZPATH=""` (**K2R-U1**: `zoneinfo` bierze bazę wyłącznie z pakietu `tzdata`), użytkownik bez uprawnień (uid 10003), `requirements.txt`: `PyYAML`, `tzdata==2025.2`, `paho-mqtt==2.2.0`.
- `docker-compose.yml`, usługa `simulator`: `container_name: aip-simulator`, `restart: unless-stopped`, `depends_on: mosquitto (healthy)`, `read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit`/`memswap_limit: 128m`, healthcheck `python -m simulator.health`, `logging: *default-logging`, wolumeny: `./config/devices.yaml:/config/devices.yaml:ro` i `aip_simulator_data:/var/lib/simulator`. Suma limitów `aip-*`: 2560 MiB (test budżetu na granicy, U-5).
- **Test obrazu (K2R-U1)** na IPC, tag `aip-simulator:test` (nie produkcyjny): `docker build` i `docker run --rm` z wydrukiem `tzdata.IANA_VERSION` (oczekiwane 2025b), `zoneinfo.TZPATH` (pusty) i przesunięcia UTC 25.10.2026 01:30/03:30 UTC (+2/+1 h). Wynik do raportu; obraz usunięty po teście.

## 4. Konto MQTT i ACL (K1-D2)

- `config/mosquitto/acl.conf`: collector `topic write zaklad1/linia1/+/+` (dziś `+/+/+/+`), symulator `topic write zaklad1/linia2/+/+`, ingest bez zmian (`topic read +/+/+/+`). Literały zakładu i linii są w pliku konfiguracyjnym (nie w kodzie); test pilnuje zgodności z `site/line` i `simulator.site/line` w `devices.yaml`.
- `config/mosquitto/entrypoint.sh`: trzecie konto z `MQTT_SIM_USER`/`MQTT_SIM_PASSWORD` (te same kontrole znaków, inne niż collector i ingest).
- **Do decyzji:** konto symulatora **opcjonalne** w `entrypoint.sh` (brak zmiennych = brak konta i bloku ACL symulatora, WARNING w logu brokera) – rekomenduję, bo restart brokera na produkcji z repo nowszym niż `.env` nie zatrzyma wtedy danych prawdziwych; alternatywa: wymagane (broker nie wstanie bez zmiennych). Kolejność w k7 w obu wariantach: najpierw Grzegorz dopisuje zmienne do `.env`, potem R-1.
- `.env.example` (nazwy bez wartości), `docker-compose.test.yml` (konto `simulator` w Mosquitto i w `pytest`), `tests/run-tests.sh` (losowe `TEST_MQTT_SIM_PASSWORD`).
- **Testy ACL** (`tests/mqtt/test_broker_acl.py`, MQTT v5, kod powodu w PUBACK): collector → `linia1` przyjęty, collector → `linia2` **odrzucony**; symulator → `linia2` przyjęty i dociera do ingestu, symulator → `linia1` **odrzucony**, symulator nie może subskrybować; ingest czyta obie linie.
- Restart Mosquitto na produkcji dopiero w k7, z kontrolą 20 wierszy/s po restarcie (w k5 etapu 2 restart brokera dał 0 s luki).

## 5. Sekcja główna configu tylko `real` (K1-D1)

- Ingest (`config.py`): `plc.source` i `devices[].source` muszą być `real`; urządzenie sim tylko w sekcji `simulator:` (komunikat wskazuje sekcję).
- **Collector** (`config.py`): ta sama reguła, bo czyta tę samą sekcję – zmiana tylko walidacji (bez zmian w odczycie i publikacji). Do potwierdzenia: alternatywa to reguła tylko w ingeście.
- Testy przepisane: `test_validate.py::test_simulated_device_accepts_sim_and_rejects_real` → na urządzeniu z sekcji `simulator`; `test_devices_sync.py::test_changed_name_and_source_are_updated` → zmiana nazwy (zmiana źródła w sekcji głównej = błąd configu); collector `test_evaluator.py` (K3-U1) i `test_payload.py` → `source` z configu przechodzi do ładunku dla `real`, `sim` w sekcji głównej odrzucone przy wczytaniu.

## 6. Testy czasu letniego dla energii (K2R-U4)

Kotwica testowa tuż przed datą (mały koszt): energia doby lokalnej 25.10.2026 (90 000 s) i 28.03.2027 (82 800 s) = przyrost całki licznika między lokalnymi północami = suma jej sekund (co do W·s); chłodnia (24/7) ma energię proporcjonalną do długości doby (± szum cyklu); poniedziałki po zmianie czasu (26.10.2026, 29.03.2027): mieszalnik i pakowaczka zaczynają pracę o 05:00 / 04:00 UTC, a energia ich doby lokalnej równa jest energii zwykłego poniedziałku (± 3 %).

## 7. Testy (razem)

| Obszar | Testy |
| --- | --- |
| Kotwice | nowe pola w configu, `null` → błąd przy starcie z komunikatem, x = 0 w montażu i 0,70 po 84 dniach, wymiana łożyska nie zmienia liczników |
| Pamięć sum | zapis i odczyt identyczne z rachunkiem; inny klucz (zmiana parametru, ziarna, kotwicy, `MODEL_VERSION`) → przeliczenie; podrobiona ostatnia doba → WARNING i przeliczenie; uszkodzony JSON / brak katalogu / brak praw → przeliczenie; zapis atomowy (przerwany zapis nie psuje pliku); czas startu z plikiem |
| Pętla na żywo | atrapa zegara: kolejne ticki publikują 29 wiadomości z poprawnymi tematami, ładunkiem i `ts`; spóźnienie > 5 s = przeskok i jeden log; bufor przy braku brokera (limit, odrzucanie najstarszych, opróżnianie po powrocie) |
| E2E (`aip-test`) | symulator (w procesie testu, konto `simulator`) → Mosquitto → ingest → baza: 29 wierszy na sekundę z `source = sim` w `linia2`, wartości równe `samples_at(t)`; dane prawdziwe z `linia1` równolegle bez zmian |
| ACL | pkt 4 |
| Real/sim | pkt 5 |
| Czas letni | pkt 6 |
| Compose | usługa `simulator`: `read_only`, `cap_drop`, `no-new-privileges`, `mem_limit` 128m, wolumen tylko `/var/lib/simulator`, config `:ro`, brak portów, konto MQTT z `.env`; suma limitów |
| Obraz | pkt 3 (ręcznie na IPC, tag testowy) |

Testy symulatora używają pamięci sum we wspólnym katalogu tymczasowym sesji, więc nowe instancje nie liczą dób od zera – **K2R-U5**: czas pełnego zestawu podam w raporcie (cel: wyraźnie poniżej 22 min). Po k3: pełny zestaw w worktree, agent `reviewer`, raport `e3-k3-report.md`.

## 8. Lista plików

Nowe: `services/simulator/Dockerfile`, `services/simulator/src/simulator/{main,live,publisher,health,daycache}.py`, `tests/simulator/{test_sim_anchors,test_sim_daycache,test_sim_live,test_sim_e2e,test_sim_dst_energy,test_sim_compose}.py`, `docs/handoff/e3-k3-report.md`.
Zmieniane: `services/simulator/src/simulator/{config,energy,pump,samples}.py`, `services/simulator/requirements.txt` (+ `paho-mqtt`), `config/devices.yaml` (kotwice), `config/mosquitto/{acl.conf,entrypoint.sh}`, `docker-compose.yml` (usługa i wolumen), `docker-compose.test.yml`, `tests/run-tests.sh`, `.env.example`, `services/ingest/src/ingest/config.py`, `services/collector/src/collector/config.py` (tylko walidacja `source`), testy ingestu, collectora, MQTT, configu i compose, `tests/simulator/*` (kotwice), `docs/{data-model,status-codes}.md`, `docs/ops/jumo-ipc-setup.md` (konto MQTT symulatora, kotwice przy wdrożeniu, wolumen, plik pamięci).
Bez zmian: schemat bazy, Grafana, produkcja.

## 9. Ryzyka

| Ryzyko | Postępowanie |
| --- | --- |
| Zmiana ACL collectora dotyka ścieżki danych prawdziwych | test: collector pisze do `linia1` jak dotąd; na produkcji dopiero w k7 z kontrolą 20 wierszy/s; łatwy powrót (jeden plik) |
| Broker nie wstanie po wdrożeniu bez zmiennych sim w `.env` | konto opcjonalne (rekomendacja) i kolejność k7: `.env` → R-1 |
| Plik pamięci sum niezgodny z modelem | klucz z `MODEL_VERSION` i parametrów, kontrola ostatniej doby, przeliczenie zamiast błędu |
| Walidacja `source` w collectorze (produkcyjny kod) | tylko kontrola przy wczytaniu; prawdziwy config ma `real`; test starego i nowego kodu na nowym pliku jak w k1 |
| Długi test wydajności 90/365 dni | tylko w `run-perf.sh`, nie w zwykłym zestawie |

## 10. Do decyzji

1. Konto symulatora w Mosquitto opcjonalne (rekomendacja) czy wymagane.
2. Reguła „sekcja główna tylko `real`” także w collectorze (rekomendacja) czy tylko w ingeście.
3. `SIM_BUFFER_MAX` = 36 000 (ok. 20 min przy 29/s).

Plan e3-k3 gotowy do przeglądu.
