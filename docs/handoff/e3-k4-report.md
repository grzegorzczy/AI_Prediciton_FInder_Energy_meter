# E3-k4 – raport (krótki)

Data: 2026-11-27. Plan `e3-k4-plan.md`, review `e3-k4-review.md` (K4-D1…D3, K4-U1…U5); reviews k3/k4 zacommitowane w `212e498`. Produkcja bez zmian (`~/ai-predykcja` na `c299eaa`, czysto).
Commity: `5a47752` (migracja 012, limit sim w ingeście, okna, dokumentacja), `1314cfd`…`94575b3` (testy, poprawki po `reviewer`, `1ca6ddf`: limit w kolejce wejściowej).

## Wyniki

| Pozycja | Wynik |
| --- | --- |
| Pełny zestaw na `1ca6ddf` | 721 passed, 5 skipped, **1 failed**: `test_energy_aggregates.py::test_real_time_mode…` – lista agregatów w teście bez `pump_1m` (deterministyczne; poprawione w `94575b3`) |
| `tests/db` na `94575b3` (po poprawce) | **118 passed, 3 skipped, 0 failed** |
| `tests/ingest` (lokalnie, bez brokera) | 150 passed; testy z brokerem przeszły w pełnym zestawie |
| **K4-U2** (TimescaleDB 2.32.1) | (a) ręczne odświeżenie zakresu, w którym chunk `pump_1m` jest **skompresowany** – **działa**; (b) wstawienie surowych wierszy pompy do **skompresowanego** chunku `measurements` – **działa**; dane po odświeżeniu poprawne (test `test_refresh_and_insert_into_compressed_chunks`). Kolejność w k5 nie musi omijać kompresji |
| Model → `pump_1m` | średnie drgań z `samples_at` równe `vibration_avg`; minuta w zmianie `running = true`, nocą `false` |

## Odstępstwa od planu

1. **Limit danych sim także w kolejce wejściowej MQTT** (ustalenie 1 `reviewer`): przy wolnej, ale dostępnej bazie potok zapisuje paczkami po 100, więc limit w potoku (3 000) się nie włączał; zaległość rosła w kolejce `MqttInput` (5 000), a jej zapełnienie blokowałoby wątek sieciowy paho – także dla danych real. Teraz ta sama wartość `INGEST_SIM_PENDING_MAX` ogranicza wiadomości sim (QoS 0, urządzenia `source = sim` z configu) czekające w kolejce; ponad limit są odrzucane, log raz na początek i koniec epizodu. Dane real i sim z QoS 1 nigdy (testy). Łącznie w pamięci najwyżej 2 × 3 000 wierszy sim (kolejka + paczka).
2. Test „dane symulatora → `pump_1m`” bez MQTT (wiersze z `samples_at` wstawione bezpośrednio); ścieżkę MQTT → ingest sprawdza `test_sim_e2e`.
3. `pump_1m_calc` ma dodatkowo `vibration_n` (migracja nie była nigdzie zastosowana, więc zmieniona w miejscu).
4. `INGEST_SIM_PENDING_MAX < 1` = błąd startu ingestu (kod 2).

## Przegląd `reviewer` – co zostało

- Ustalenia 1, 2, 4, 5, 6 – poprawione (limit w kolejce, test końca epizodu przy limicie, kontrola wartości, ścisła asercja kompresji, ack danych real przy odrzucaniu sim).
- Ustalenie 3 (wiersze sim z QoS 1 liczą się do limitu potoku, więc wgrywanie historii może wywołać odrzucanie danych sim na żywo) – **do planu k5**.
- Migracja 012 i ścieżka danych real w ingeście – bez zastrzeżeń agenta.

## Decyzje do podjęcia

1. Limit 2 × `INGEST_SIM_PENDING_MAX` (kolejka + paczka) zamiast jednego wspólnego – akceptacja?
2. k5: wybór QoS wgrywania historii (K4-U1) z uwzględnieniem ustalenia 3.

Do checklisty k7: test brokera bez konta sim (K3R-U3). Raport e3-k4 gotowy. Stop.
