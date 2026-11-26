# E3-k1 – plan kroku: konfiguracja symulatora i ingest (urządzenia sim, site/line na urządzenie)

Data: 2026-11-26. Etap 2 zaakceptowany przez Grzegorza; etap 3 w toku. Podstawa: `e3-k0-plan.md` (k1), `e3-k0-review.md` (K0-D3, U-1, U-2, U-6), `e3-decyzje-szkic.md` (decyzje Grzegorza i „Po review planu e3-k0”).
**Sam plan, do review.** W k1 nie zmieniam produkcji (compose, baza, Grafana, działające kontenery, konfiguracja montowana przez kontenery produkcyjne).

## Cel kroku

Ingest przyjmuje dane urządzeń symulowanych z `zaklad1/linia2`, a ścieżka danych prawdziwych (`zaklad1/linia1`, PLC i Finder) działa bez zmian. Konfiguracja urządzeń sim istnieje w `config/devices.yaml`. Kodu symulatora, konta MQTT i ACL jeszcze nie ma (k3).

## Co wynika z kodu (stan dziś)

- Ingest ma jedno `site`/`line` na cały config: `validate.py` porównuje temat z `config.site`/`config.line`, a `store.sync_devices` zapisuje te same wartości do każdego wiersza `devices`.
- Collector traktuje **każdy** wpis `devices:` jako urządzenie Modbus (wymaga `profile`, `block_base`) i czyta tylko klucze `plc`, `profiles`, `devices`. Nowa sekcja najwyższego poziomu `simulator:` jest dla niego niewidoczna – sprawdzę to testem, nie założeniem.
- Produkcyjne kontenery czytają `./config/devices.yaml` montowane z katalogu repo `~/ai-predykcja` na IPC (dziś na `c299eaa`). **`git pull` w tym katalogu zmieniłby plik, który czyta produkcja** (ingest i collector wczytują go przy starcie, np. po restarcie komputera).

## Zakres zmian

### 1. `config/devices.yaml` – nowa sekcja `simulator:`
```yaml
simulator:
  site: zaklad1
  line: linia2                    # K0-D3: dane sim tylko w linia2 (ACL konta symulatora w k3)
  poll_interval_s: 1.0            # wspólne dla urządzeń sim; trafia do devices.meta (widoki energii)
  t_zero: null                    # U-2: data „teraz” dla degradacji, ustalana w k7 przy wdrożeniu
  devices:
    - { id: sim_pasteryzator, name: "Pasteryzator", kind: energy_meter, source: sim, phases: 3, rated_kw: 18,  energy_resolution_wh: 100 }
    - { id: sim_chlodnia,     name: "Agregat chłodniczy", kind: energy_meter, source: sim, phases: 3, rated_kw: 11, energy_resolution_wh: 100 }
    - { id: sim_mieszalnik,   name: "Mieszalnik", kind: energy_meter, source: sim, phases: 3, rated_kw: 7.5, energy_resolution_wh: 100 }
    - { id: sim_pakowaczka,   name: "Pakowaczka", kind: energy_meter, source: sim, phases: 3, rated_kw: 4,   energy_resolution_wh: 100 }
    - { id: sim_pump_p101,    name: "Pompa P-101", kind: pump, source: sim, rated_kw: 11 }
```
- **Tylko tożsamość i metadane potrzebne ingestowi i widokom** (id, nazwa po polsku, rodzaj, źródło, linia, `poll_interval_s`, `energy_resolution_wh`, `phases`, `rated_kw`). Parametry modeli (kalendarz, profile pracy, PF, degradacja pompy, ziarno) dochodzą w k2 razem z kodem, który je czyta, i z jego walidacją – żeby nie trzymać w configu nieużywanych i niesprawdzanych wartości. Do potwierdzenia (alternatywa: wszystko w k1).
- **U-1:** `phases: 3` i komentarz w YAML: „licznik wirtualny trójfazowy; `voltage` = napięcie fazowe, `current` = prąd fazy przy obciążeniu symetrycznym; Finder jest jednofazowy”. Ten sam opis w `docs/data-model.md`. Metadanych prawdziwego Findera w k1 nie zmieniam (bez `phases: 1`, żeby nie ruszać wiersza prawdziwego urządzenia); dopisanie – decyzja architekta.
- Nazwy bez znacznika „SYMULACJA”: znacznik dokłada Grafana z kolumny `source` (S10, k6), dane zostają czyste. Do potwierdzenia.
- `sim_pump_demo` (K0-D5) **nie** w k1: dojdzie razem z trybem przyspieszonym (k5), żeby ingest nie rejestrował urządzenia, które nic nie publikuje.

### 2. Ingest
- `config.py`: `DeviceSpec` dostaje `site` i `line`; urządzenia z `devices:` i PLC – z `site`/`line` najwyższego poziomu (bez zmian), urządzenia z `simulator.devices` – z `simulator.site`/`simulator.line`. Walidacja: urządzenie w `simulator.devices` musi mieć `source: sim`; `kind` tylko `energy_meter` lub `pump`; id unikalne w obu sekcjach; segmenty tematu ASCII; brak sekcji `simulator` = zachowanie jak dziś. Metadane sim: `poll_interval_s`, `energy_resolution_wh` (liczniki), `phases`, `rated_kw`.
- `validate.py`: kontrola `site_line` wobec `site`/`line` **urządzenia** (ten sam kod powodu `site_line`, te same komunikaty).
- `store.py`: `sync_devices` zapisuje `site`/`line` z urządzenia; logika wyłączania urządzeń spoza configu bez zmian.
- `main.py`: log startowy wypisuje zbiór par zakład/linia zamiast jednej.
- **Bez zmian:** schemat bazy (kolumny `site`, `line` już są w `devices`), potok, zapis, potwierdzenia MQTT, collector.

### 3. Testy (w tym regresja ścieżki danych prawdziwych)
| Obszar | Testy |
| --- | --- |
| Konfiguracja (`tests/config/test_devices_yaml.py`) | sekcja `simulator`: id z prefiksem `sim_`, `source: sim`, linia `linia2` ≠ linia prawdziwego sprzętu, `phases: 3` dla liczników, rozdzielczość 100 Wh, nazwy po polsku, segmenty tematu bezpieczne, id unikalne w obu sekcjach |
| Loader ingestu (`test_ingest_config_loader.py`) | prawdziwy plik: PLC + Finder z `linia1` (meta Findera identyczne jak dziś – porównanie z wartościami sprzed zmiany), 5 urządzeń sim z `linia2` i oczekiwanymi meta; błędy: sim z `source: real`, nieznany `kind`, powtórzone id między sekcjami, zła linia; config bez sekcji `simulator` daje dokładnie to samo co dziś |
| Walidacja (`test_validate.py`) | macierz: Finder w `linia1` – przyjęty; Finder w `linia2` – `site_line`; sim w `linia2` – przyjęty; sim w `linia1` – `site_line`; `source` niezgodny w obie strony – `source`; inny zakład – `site_line` |
| Synchronizacja urządzeń (`test_devices_sync.py`, baza `aip-test`) | wiersze `devices` z linią na urządzenie; wiersze PLC i Findera bez zmian (wszystkie kolumny); usunięcie urządzenia sim z configu = `enabled = FALSE`, prawdziwe nietknięte |
| **Regresja ścieżki prawdziwej** (`test_ingest_e2e.py`) | pełny przebieg MQTT → ingest → baza dla tematów `zaklad1/linia1/finder_7m24_1/*` i `plc-01/link_status` z configiem zawierającym sekcję sim: te same wiersze (czas, wartość, jednostka, `source = real`) co bez niej; wiadomość sim w `linia2` zapisana równolegle z `source = sim`; wszystkie dotychczasowe testy ingestu bez zmian |
| Collector (`tests/collector/test_config_loader.py`) | prawdziwy plik z sekcją `simulator`: collector widzi dokładnie 1 urządzenie Modbus (Finder), te same kontrole rejestrów; urządzenie `sim_*` nigdy nie jest odpytywane |
| Brak danych urządzeń w kodzie (`test_no_hardcoding.py`) | rozszerzenie: żadnych id `sim_*`, mocy ani nazw linii w źródłach ingestu (reguła 3) |

Po k1: pełny zestaw `tests/run-tests.sh` (oczekiwane 507 + nowe, 3 pominięte), potem agent `reviewer` na diff k1.

## Gdzie uruchamiam testy na IPC (proszę o zgodę)

Żeby nie zmienić pliku czytanego przez produkcję, **nie robię `git pull` w `~/ai-predykcja`**. Proponuję osobny katalog roboczy na IPC: `git -C ~/ai-predykcja worktree add ~/ai-predykcja-dev main` (ten sam `.git`, osobne pliki; produkcja zostaje na `c299eaa` do wdrożenia w k7), a w nim `git pull --ff-only` i `sh tests/run-tests.sh` (projekt Compose `aip-test` jak dotąd, sprząta tylko siebie). Bez sudo, bez `.env` (testy generują własne hasła). Alternatywa: drugi `git clone` z kluczem tylko do odczytu. Od k7 wdrożenie normalnie przez R-1 w `~/ai-predykcja`.

## Lista plików

Zmieniane: `config/devices.yaml`, `services/ingest/src/ingest/{config,validate,store,main}.py`, `tests/config/test_devices_yaml.py`, `tests/ingest/{test_ingest_config_loader,test_validate,test_devices_sync,test_ingest_e2e,test_no_hardcoding}.py`, `tests/collector/test_config_loader.py`, `docs/data-model.md` (linia na urządzenie, `phases`, urządzenia sim), `docs/status-codes.md` (jeśli opis `site_line` wymaga doprecyzowania).
Nowe: `docs/handoff/e3-k1-report.md`.
Bez zmian: collector (kod), `docker-compose*.yml`, Mosquitto (konto i ACL w k3), migracje, Grafana, `docs/modbus-map.md`.

## Ryzyka

| Ryzyko | Postępowanie |
| --- | --- |
| Zmiana walidacji ingestu dotyka danych prawdziwych | macierz testów walidacji + e2e regresji z porównaniem wierszy; wdrożenie dopiero w k7 z kontrolą 20 wierszy/s |
| `git pull` w katalogu produkcji podmienia `devices.yaml` | osobny katalog roboczy na IPC (wyżej) |
| Produkcyjny ingest po restarcie wczytałby nową sekcję | nie dotyczy do k7 (stary obraz i stary plik); obecny ingest i tak ignoruje nieznane klucze – sprawdzę testem na kodzie sprzed zmiany |
| Urządzenia sim pojawią się w `$device` dashboardów bez danych | dopiero po wdrożeniu (k7), gdy symulator już publikuje; opis w k6 |

## Czego potrzebuję

1. Zgoda na osobny katalog roboczy `~/ai-predykcja-dev` (worktree) na IPC do testów.
2. Potwierdzenie: parametry modeli w k2, a w k1 tylko tożsamość i metadane; nazwy bez „SYMULACJA”; Finder bez `phases: 1` w k1.

Plan e3-k1 gotowy do przeglądu.
