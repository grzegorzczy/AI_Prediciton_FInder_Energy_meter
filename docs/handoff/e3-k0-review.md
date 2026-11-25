# E3-k0 – review planu etapu 3 (architekt)

Data: 2026-11-25. Plan: `e3-k0-plan.md` (`409f857`).

**Werdykt: OK Z UWAGAMI.** Plan dobry: model czysto funkcyjny f(czas, ziarno, config) daje determinizm i idempotentne
uzupełnianie luk; trafnie wykryte dwa błędy w moim szkicu (K0-D1, K0-D2). **Wykonanie dopiero po akceptacji
`etap-2.md` przez Grzegorza** – do tego czasu zakazy z polecenia obowiązują.

## Sprawa „Decyzji Grzegorza”

Sekcja istniała w moim pliku, ale wersja na dysku została nadpisana starszą (ten sam problem co rano z
`e2-k8a-visual-review.md`). Plik zapisałem ponownie (`docs/handoff/e3-decyzje-szkic.md`, sekcja na końcu).
Decyzje Grzegorza (25.11): S1 zakład spożywczy, S2 dwie zmiany + sobota, historia przez MQTT, osobna `linia2`.
Kopia także w dokumencie projektu 13. **Przy commicie plików architekta: najpierw `git status`, plik z dysku
commitować bez `checkout`/`restore`.**

## Decyzje

| Id | Decyzja |
| --- | --- |
| K0-D1 | **Opcja A, K = 14 dni** (decyzja Grzegorza 25.11, zamiast historii 1 min dla liczników): liczniki co 1 s × 14 dni, pompa co 1 min × 84 dni, wszystko przez MQTT. Uzasadnienie K = 14: etap 4 liczy próg biegu jałowego z rozkładu mocy z 14 dni. Ok. 29 mln + 0,6 mln wiadomości. **Tempo wgrywania ustala pomiar w k5**; przed pełnym wgraniem pilotaż 1 doby na produkcji z kontrolą 20 wierszy/s PLC i kolejki brokera; pełne wgranie w nocy. |
| K0-D2 | **120 / 84** – akceptuję. Mój szkic był niespójny. Historia pompy 84 dni mieści się w retencji 90 dni. |
| K0-D3 | **`zaklad1/linia2`** (decyzja Grzegorza) z ACL konta symulatora `zaklad1/linia2/+/+`; zmiana ingestu (site/line na urządzenie) z testami regresji ścieżki danych prawdziwych. |
| K0-D4 | **`pump_1m` w etapie 3** (migracja 012); `docs/data-model.md` do aktualizacji. |
| K0-D5 | Tryb przyspieszony tylko dla osobnego `sim_pump_demo`, domyślnie wyłączonego – OK. |
| K0-D6 | Bez `meter_status` dla urządzeń sim, opis w dashboardzie – OK. |
| K0-D7 | „Flota” = 5 liczników (1 real + 4 sim), stan = świeżość danych; pompa w osobnym dashboardzie – OK. |
| K0-D8 | Rozdzielczość 100 Wh jak Finder – OK (te same widoki zgodności). |
| K0-D9 | **Pompa bez `active_power` w etapie 3** – pozostaje obiektem diagnostyki stanu; ewentualnie w etapie 4. |

**Parametry maszyn i pompy z pkt 3.2–3.3: zaakceptowane przez Grzegorza** (pasteryzator 18 kW, agregat chłodniczy
11 kW, mieszalnik 7,5 kW, pakowaczka 4 kW; pompa 11 kW, 2950 obr/min, 40 m³/h; drgania 1,1 → 7,0 mm/s jako koniec
zakresu modelu, nie próg). Identyfikatory `sim_*` z planu – OK; opisy po polsku w configu.

## Uwagi

- **U-1:** liczniki wirtualne liczą I = S/(3U) – to liczniki trójfazowe, a Finder jest jednofazowy. Opisać w
  `devices.yaml` i dokumentacji (`phases: 3` dla sim, `voltage` = napięcie fazowe), żeby etap 4 nie mieszał.
- **U-2:** `t_zero` (data „teraz” dla degradacji) ustalana w k7 przy wdrożeniu; zapisać w raporcie i w `devices.yaml`.
- **U-3:** wgrywanie historii do chunków już skompresowanych (dane realne od 23.11) – zmierzyć w k5 na `aip-test`
  z danymi w skompresowanych chunkach, nie tylko na pustej bazie.
- **U-4:** okno `data_windows` dla wgrywania historii (`sim_backfill`) – tak, jak dla wdrożeń, żeby analityka
  wiedziała, że w tym czasie obciążenie było nietypowe.
- **U-5:** suma `mem_limit` 2560 MiB – OK; test budżetu zostaje na granicy, kolejny kontener (etap 5/6, Ollama!)
  wymaga przeglądu limitów – zapisać w ryzykach etapu 6.
- **U-6:** po akceptacji etapu 2 testy w `aip-test` na IPC wracają – tak.

## Dalej

Po akceptacji `etap-2.md`: k1 (konfiguracja i ingest) – plan krótki + wykonanie, raport, review.
