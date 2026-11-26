# E3-k1 – review raportu (architekt)

Data: 2026-11-26. Raport: `e3-k1-report.md` (`b7a164e`; commity kroku `0cded00`, `eaf7f94`, `aff8665`, `2076c7a`).

**Werdykt: OK.** Krok k1 zamknięty. Wszystkie 4 decyzje z `e3-k1-review.md` wykonane i sprawdzone testami. Produkcja nietknięta (`c299eaa`, katalog czysty, kontenery bez restartu).

## Co potwierdza „gotowe” dla k1

- Ścieżka danych prawdziwych bez zmian, pokazane na 4 poziomach: walidacja (wiersz Findera/PLC identyczny z sekcją sim i bez niej), synchronizacja `devices` (PLC i Finder identyczne we wszystkich kolumnach), e2e MQTT → baza (`source = real` jak dotąd) i collector (konfiguracja identyczna, `sim_*` nieodpytywane).
- Finder: w metadanych różni się tylko nowy klucz `phases: 1` – zgodnie z decyzją 4.
- Stary kod produkcyjny z nowym plikiem daje te same urządzenia. Przypadkowy restart produkcji przed k7 jest bezpieczny. Wynik zostaje w raporcie – dobrze.
- Pełne testy: 552 passed, 3 skipped, 0 failed.
- Sprawdziłem `config/devices.yaml` na dysku laptopa: sekcja `simulator` i `phases: 1` u Findera zgadzają się z raportem i z parametrami zaakceptowanymi w K0 (18 / 11 / 7,5 / 4 kW, pompa 11 kW).
- Poprawka testu `test_v1_then_v2_in_flight` (wyścig w teście, kod collectora bez zmian) – OK. Dobrze, że 5 × przebieg pliku.

## Decyzje w sprawach otwartych

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K1-D1 | Ustalenie 2: sekcja główna przyjmuje `source: sim` | **Tak, w sekcji głównej tylko `real`** – w k3 razem z ACL (ten sam temat: rozdzielenie real/sim). Test `test_simulated_device_accepts_sim_and_rejects_real` przepisać na urządzenie z sekcji `simulator`. Każde urządzenie sim tylko w `simulator:`. |
| K1-D2 | Ustalenie 3: collector może publikować do każdego tematu | **Tak, w k3:** zapis collectora tylko `zaklad1/linia1/+/+`, symulator tylko `zaklad1/linia2/+/+`, ingest bez zmian (tylko subskrypcja). Test ACL: collector → `linia2` odrzucony, symulator → `linia1` odrzucony. Restart Mosquitto na produkcji dopiero w k7 (w k5 etapu 2 restart brokera = 0 s luki – kontrola 20 wierszy/s po restarcie). |
| K1-D3 | Ustalenie 4: sekcja główna bez kontroli typów/zakresów (`ValueError` zamiast `ConfigError`) | **Odkładamy** – zapis w otwartych kwestiach etapu 3 (E3-O1). Sekcja główna to ścieżka produkcyjna; zmiana z regresją na początku etapu 4 albo w k8 etapu 3 – decyzja przy planie k8. |

## Uwagi (drobne, do zrobienia przy okazji k2)

- **K1-U1:** nagłówek `config/devices.yaml`, linia 2: „docs/modbus-map.md (kontrakt, wersja 1)” – od 25.11 obowiązuje **wersja 2**. Poprawić komentarz.
- **K1-U2:** `t_zero: null` – w k2 kod symulatora musi odróżniać „brak `t_zero`” od daty; przy `null` tryb na żywo nie startuje (błąd konfiguracji z jasnym komunikatem), nie przyjmuje po cichu „teraz”. Inaczej degradacja zaczęłaby się od 0 % przy każdym restarcie.

## Zrzuty

k1 nie zmienia nic w GUI (Grafana, CODESYS) – zrzutów nie potrzeba; wyniki konsolowe są w raporcie. Do dokumentacji Word v3: tabela testów i blok „stary kod + nowy plik” jako wydruk.

## Plik setupu PLC `.432` (polecenie Grzegorza, 26.11)

Grzegorz zapisał projekt CODESYS po zmianach PLC-2 (mapa v2). Plik na dysku: `plc/setup/10.2.1.1-new_1.431.432`, 24 856 282 B, zmiana 25.11.2026 15:20 (czas lokalny) – po wgraniu PLC-2 (11:43). **Claude Code:** `git status`, potem commit tylko tego pliku bez `checkout`/`restore`, komunikat np. `plc: setup file after PLC-2 (Modbus TCP map v2)`, push. Hash commita w raporcie k2.

## Dalej

Plan k2 (modele symulatora i ich parametry w `simulator:` – kalendarz S2, profile pracy, PF, degradacja pompy, ziarno) → review → „ok”. Commit tego review razem z `.432`.
