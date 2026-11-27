# E3-k3 – review raportu (architekt)

Data: 2026-11-27. Raport: `e3-k3-report.md` (`62cf284`; commity kroku `54c7122`, `11900d8`, `feec7f5`, `d7ffe02`, `835501c`, `ee4aaaa`; review planu `7a2111d`).
Review podane Grzegorzowi w czacie 27.11 rano (laptop był niepodłączony); plik zapisany po przeczytaniu raportu – treść raportu potwierdza tamto podsumowanie.

**Werdykt: OK Z UWAGAMI.** Krok k3 zamknięty.

## Co potwierdza „gotowe”

- K3-D4 (QoS 0): przerwa ingestu 120 s → `linia1` 120/120 w bazie, `linia2` z luką; `queue_qos0_messages` domyślnie false (test); kolejka brokera dla danych prawdziwych nadal ok. 66 min przy 20/s.
- K2R-D3: start liczników z plikiem 3,0 / 2,9 / 3,4 s po 14 / 90 / 365 dniach (bez pliku 43 / 299 / 1 219 s), wynik identyczny; plik 22,8 kB po roku.
- K3-D2: stary i nowy kod collectora i ingestu z oboma plikami – identyczna konfiguracja (`real`).
- Pamięć symulatora ok. 22–29 MiB z 128 MiB; błędny pierwszy pomiar (`ru_maxrss` po `fork`) jawnie opisany i poprawiony.
- Obraz testowy: tzdata 2025b, pusty `TZPATH`, poprawne przesunięcia przy zmianie czasu; bez dat kod 2; obraz usunięty bez `prune`.
- Produkcja: `c299eaa`, bez `aip-simulator`, Mosquitto bez restartu.
- Błąd wykryty przez `reviewer` (QoS 0 sim bez limitu w pamięci ingestu przy niedostępnej bazie → OOM po 1–2 h) – poprawiony przed produkcją.

## Uwagi (wykonane w planie k4)

- **K3R-U1:** pełny zestaw na początku k4 – wykonane: 700 passed, 5 skipped, 0 failed na `62cf284`.
- **K3R-U2:** jawne kryterium odrzucania danych sim w ingeście z limitem liczby wierszy (także przy wolnej bazie) – w planie k4, sekcja 3.
- **K3R-U3:** test brokera bez konta symulatora na żywo – do checklisty k7 (plan k4, sekcja 4).
- Drobne: `start_period` healthchecku 120 s wystarcza przy pliku pamięci sum (start 3 s) i przy pierwszym starcie w k7 (14 dni, ok. 43 s).
