# E3-k1 – raport: konfiguracja symulatora i ingest (urządzenia sim, zakład/linia na urządzenie)

Data: 2026-11-26. Plan: `e3-k1-plan.md`, review: `e3-k1-review.md` (OK, decyzje 1–4). Produkcja **nie zmieniona**: `~/ai-predykcja` na IPC zostaje na `c299eaa`, kontenery bez restartu, testy tylko z worktree `~/ai-predykcja-dev` w projekcie `aip-test`.
Commity: `0cded00` (kod, config, testy), `eaf7f94` (test odporności: liczba urządzeń), `aff8665` (poprawki po przeglądzie `reviewer`, dokumentacja), `2076c7a` (wyścig w teście collectora), ten raport.

## Co zrobiono

1. **`config/devices.yaml`:** nowa sekcja `simulator:` (`zaklad1/linia2`, `poll_interval_s: 1.0`, `t_zero: null` – U-2, ustalane w k7) z pięcioma urządzeniami: `sim_pasteryzator` (18 kW), `sim_chlodnia` (11 kW), `sim_mieszalnik` (7,5 kW), `sim_pakowaczka` (4 kW) – `energy_meter`, `phases: 3`, `energy_resolution_wh: 100` – oraz `sim_pump_p101` (`pump`, `rated_kw: 11` = moc silnika). Nazwy po polsku bez „SYMULACJA” (decyzja 3). Komentarz w YAML: liczniki sim trójfazowe (`voltage` fazowe, `current` jednej fazy), Finder jednofazowy (U-1). **Finder dostał `phases: 1`** (decyzja 4). Parametry modeli – w k2 (decyzja 2).
2. **Ingest:** `DeviceSpec` ma `site` i `line`; PLC i urządzenia z `devices:` – z sekcji głównej, urządzenia sim – z `simulator`. `validate.py` porównuje temat z zakładem/linią **urządzenia** (ten sam kod `site_line`); `store.sync_devices` zapisuje zakład/linię z urządzenia; log startowy wypisuje wszystkie pary (`zaklad1/linia1, zaklad1/linia2`). Walidacja sekcji `simulator`: `source` musi być `sim`, `kind` tylko `energy_meter`/`pump`, id unikalne w obu sekcjach, **linia sim musi być inna niż linia sprzętu**, liczby dodatnie i skończone (`poll_interval_s`, `rated_kw`, `energy_resolution_wh`), `phases` tylko liczba całkowita 1 lub 3, liczniki muszą mieć `phases` i `energy_resolution_wh`, pompa nie może ich mieć. Brak sekcji = zachowanie sprzed etapu 3.
3. **Dokumentacja:** `docs/data-model.md` (zakład/linia na urządzenie, tabela kluczy `meta`: `phases` 1/3 z opisem dla etapu 4, `rated_kw` pompy to moc silnika, nie moc pobierana – uwaga z review), `docs/ops/jumo-ipc-setup.md` (sekcja „Katalog testów `~/ai-predykcja-dev`”: zakładanie, aktualizacja, kontrola produkcji, usuwanie).
4. **Bez zmian:** kod collectora, compose, Mosquitto, migracje, Grafana.

## Testy

| Przebieg (worktree `~/ai-predykcja-dev`, `aip-test`) | Commit | Wynik |
| --- | --- | --- |
| podzbiór config + ingest + loader collectora | `0cded00` | 181 passed, 1 failed: `test_resilience` liczył 2 urządzenia w `devices` (teraz 7) – poprawione w `eaf7f94` |
| pełny | `eaf7f94` | **538 passed, 3 skipped, 0 failed** (707 s) |
| pełny po poprawkach z przeglądu | `aff8665` | 551 passed, 3 skipped, **1 failed**: `tests/collector/test_e2e.py::test_v1_then_v2_in_flight…` – wyścig w moim teście z E2-PLC2 (czekał tylko na `thd_current`, a `meter_temperature` z tego samego cyklu była jeszcze w drodze); kod collectora bez zmian. Poprawka `2076c7a`: czekanie na każdy temat v2; plik `test_e2e.py` 5 × 9 passed |
| pełny, końcowy | `2076c7a` | **552 passed, 3 skipped (wydajnościowe), 0 failed** (706,8 s, 26.11 08:56–09:08 UTC); produkcja po przebiegu: `c299eaa`, katalog czysty |

Nowe i zmienione testy (wszystkie w powyższych przebiegach):
- **Loader ingestu:** prawdziwy plik (PLC + Finder w `linia1`, 5 urządzeń sim w `linia2` z oczekiwanymi meta); **metadane Findera różnią się od stanu sprzed k1 wyłącznie kluczem `phases: 1`** (`test_finder_meta_differs_from_before_k1_only_by_phases`); config bez sekcji `simulator` = dokładnie urządzenia sprzed etapu 3; 22 przypadki błędnego configu (m.in. linia sim = linia sprzętu, `source: real` w sekcji sim, `kind: plc`, powtórzone id między sekcjami, złe typy i zakresy, `phases: true/3.0/2`, brak `phases`/rozdzielczości licznika, `phases` dla pompy); zgodność z loaderem collectora tylko dla urządzeń linii sprzętu.
- **Walidacja:** macierz 10 przypadków urządzenie prawdziwe/sim × `linia1`/`linia2`/inny zakład × zgodny/niezgodny `source`; **wiersz z wiadomości Findera i PLC jest identyczny z configiem z sekcją `simulator` i bez niej**.
- **Synchronizacja `devices` (baza):** 7 urządzeń, sim z `linia2`; **wiersze PLC i Findera identyczne we wszystkich kolumnach z sekcją sim i bez niej**; usunięcie jednego urządzenia sim i całej sekcji `simulator` wyłącza tylko urządzenia sim.
- **E2E (broker + ingest + baza):** wiadomości Findera i PLC z `linia1` zapisują się jak dotąd (`source = real`) równolegle z danymi `sim_pasteryzator` z `linia2` (`source = sim`); wiadomość urządzenia sim w `linia1` nie trafia do bazy.
- **Collector:** z sekcją `simulator` i kluczem `phases` jego konfiguracja jest **identyczna** jak bez nich (jedno urządzenie Modbus, Finder); urządzenia `sim_*` nie są odpytywane.
- **Reguła 3:** w kodzie ingestu nie ma id urządzeń sim, `linia2` ani nazw maszyn.

## Stary kod produkcyjny z nowym plikiem (uwaga z review)

Kod z `c299eaa` (taki jak w obrazach produkcyjnych), wczytujący nowy `config/devices.yaml` z worktree, na IPC (`python3`, PyYAML 5.4.1):
```
stary ingest, stary plik: ['finder_7m24_1', 'plc-01'] zaklad1 linia1
stary ingest, NOWY plik : ['finder_7m24_1', 'plc-01'] zaklad1 linia1
urzadzenia identyczne: True
stary collector, stary/NOWY plik identyczne: True ['finder_7m24_1']
```
Przypadkowy restart produkcji z nowym plikiem nic by nie zmienił (stary ingest nie czyta `phases` ani sekcji `simulator`). Agent `reviewer` sprawdził to niezależnie z tym samym wynikiem.

## Produkcja przed i po (decyzja 1 z review)

`git -C ~/ai-predykcja log --oneline -1` i `status --short` przed utworzeniem worktree, po nim i po każdym przebiegu testów: **`c299eaa`, katalog czysty**; kontenery `aip-*` „Up 21 hours (healthy)” (bez restartu). Worktree: `~/ai-predykcja-dev` (detached HEAD, aktualizowany `git checkout --detach origin/main`), nic z niego nie jest montowane do produkcji.

## Przegląd agentem `reviewer`

Werdykt agenta: ścieżka danych prawdziwych zachowuje się jak przed zmianą (poza zamierzonym `phases: 1`), wprowadzenie danych `real` do linii sim jest zablokowane. Ustalenia i co z nimi zrobiłem:

| # | Ustalenie | Stan |
| --- | --- | --- |
| 1 | loader nie wymuszał, by linia sim była inna niż linia sprzętu (pilnował tylko test pliku) | **poprawione** w kodzie + test |
| 2 | sekcja główna dalej przyjmuje `source: sim` (PLC, `devices:`) – urządzenie sim mogłoby być w `linia1` | **do decyzji architekta**: istniejący test `test_simulated_device_accepts_sim_and_rejects_real` korzysta z tej możliwości; propozycja: w sekcji głównej tylko `real` (osobny drobny krok albo w k3) |
| 3 | ACL Mosquitto: konto collectora może pisać do każdego tematu (`+/+/+/+`), więc mogłoby opublikować dane sim | **do k3** (plan): przy dodaniu konta symulatora zawęzić zapis collectora do `zaklad1/linia1/+/+` |
| 4 | złe typy w configu dawały `ValueError` zamiast `ConfigError`; brak kontroli zakresu (`rated_kw` ujemne/NaN, `poll_interval_s: 0`) | **poprawione** dla sekcji sim (sekcja główna ma ten sam wzorzec od etapu 2 – nie ruszałem, propozycja na później) |
| 5 | `phases: true` / `3.0` przechodziło | **poprawione** (`type(...) is int`) |
| 6 | `phases`/rozdzielczość liczników sim niewymagane, `phases` dopuszczalne dla pompy | **poprawione** |
| 7 | braki w testach: przypadek z pkt 1, wyłączenie całej sekcji sim, mylący opis testu, martwy token w `test_no_hardcoding` | **poprawione**; licznika powodu `site_line` w e2e nie sprawdzam (pokrywa go macierz walidacji) |
| 8 | dokumentacja niezacommitowana w chwili przeglądu | **zacommitowana** w `aff8665` |

## Zasoby

k1 nie zmienia obrazów, compose ani pracy kontenerów: RAM i dysk produkcji bez zmian. Testy obciążają tylko projekt `aip-test` (cron `~/aip-monitor` zapisuje go osobno jako `aip-test-*`).

## Dalej

Do decyzji: ustalenie 2 (tylko `real` w sekcji głównej) i zakres ACL collectora w k3 (ustalenie 3). Następny krok: k2 (modele symulatora i ich parametry w `simulator:`), po review i „ok”.
Raport e3-k1 gotowy. Stop.
