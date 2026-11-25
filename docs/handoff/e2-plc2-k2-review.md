# E2-PLC2 krok 2 – review planu (architekt) + review raportu k7d

Data: 2026-11-25. Plan: `e2-plc2-k2-plan.md`. Raport: `e2-k7d-report.md`.

## k7d – werdykt: OK

Wyjaśnienie (nadpisanie `timeFrom` nie działa przy bezwzględnym zakresie pulpitu) jest zgodne z obrazem:
na zrzucie 06c z k7b (zakres bezwzględny) też nie było znacznika „Last 14 days”. Zakres liczony w SQL od „teraz”
jest lepszy, bo nie zależy od zachowania Grafany. Test wykonawczy dla trzech zakresów – dobry pomysł.
Wygląd słupków „Zużycie na dobę” z etykietą „DD.MM (xx%)” – ocenią zrzuty 06, 06b, 06c (Grzegorz, w tym jeden
przy zakresie bezwzględnym).

## Plan E2-PLC2 k2 – werdykt: OK Z UWAGAMI

Plan jest kompletny: kolejność „collector v1+v2 przed PLC”, kontrola v1 przez 20 min, testy przełączania w locie,
brak zer dla danych sprzed v2. Wykonuj po uwzględnieniu poniższego.

### Odpowiedzi na „Czego potrzebuję od architekta”

1. **`docs/modbus-map.md` v2** – zapisane (architekt, 25.11). Zapytanie 0–59, pola 44–59, `map_version` 1 lub 2.
2. **Rejestry 44–59 na PLC v1:** `GVL_Meter.awTcpInputRegs : ARRAY[0..99] OF WORD` jest zmapowane na Input Registers
   serwera, a PLC v1 zapisuje tylko 0–43, więc 44–59 powinny dać 0. Nie znam powodu, by było inaczej, ale
   rozstrzyga Twój `mbpoll -c 60` (krok 1) – zostaje jako warunek wdrożenia.
3. **Zakresy wiarygodności:** nie mam wartości z karty Findera i ich nie zgaduję. `valid_range` traktujemy jako
   **filtr śmieci (np. 1e38, wartości niemożliwe fizycznie), a nie granice z karty** – szerokie zakresy:
   THD U 0…100 %, THD I 0…1000 %, kąt −180…180°, temperatura −50…150 °C, czas pracy 0…4,3×10^9 s.
   W `devices.yaml` komentarz „filtr wiarygodności, nie dane katalogowe”.
4. **n2/n4 – zmiana nazw.** „import/export” sugeruje kierunek przepływu, a tego nie wiemy. Nazwy wg znaku Q:
   - n2 → `reactive_pos_varh` (Q > 0),
   - n4 → `reactive_neg_varh` (Q < 0).
   Podstawa: 23.11 n2 = 0, n4 = 4,5 kvarh przy stale Q < 0 (dokument 01). Opis w panelu: „przy Q > 0 (indukcyjna,
   konwencja odbiornika)” / „przy Q < 0 (pojemnościowa)”. Potwierdzenie: pierwszy krok n4 o 100 varh przy Q ≈ −9 var
   (ok. 11 h) – zapisz w raporcie, czy nastąpił.

### Decyzje P2-a…P2-h

| Id | Decyzja |
| --- | --- |
| P2-a | **OK** – jedno zapytanie 0–59; najpierw `mbpoll -t 3 -r 0 -c 60`, zapas jak w planie |
| P2-b | **OK** |
| P2-c | **Zmiana: wszystko co 1 s** (bez `publish_every_s`). Powtórzone wartości kompresują się prawie do zera (kompresja po 1 dniu), a 1,8 wiersza/s nie jest warte stanu w ewaluatorze i dodatkowych testów kadencji. Model: **20 wierszy/s** w stanie OK (1 200/min). Mechanizm `publish_every_s` – nie teraz |
| P2-d | **OK** – osobne `energy_ext_1m/_1h`; nie ruszamy `energy_1m/_1h` |
| P2-e | **OK z całką** – `reactive_pos_sum`, `reactive_neg_sum` (całka mocy biernej z podziałem na znak, jak D7 dla energii czynnej); przyrost licznika jako wzorzec. Uwaga: Q jest już w `measurements` od v1, więc całkę da się policzyć także wstecz – agregat może objąć `reactive_power` od początku danych (decyzja Twoja, opisz w raporcie) |
| P2-f | **OK** – w collectorze, WARNING raz na zmianę stanu; dodatkowo licznik pominiętych wartości w logu okresowym (jeśli już taki jest) |
| P2-g | **OK, przelicz dla 20 wierszy/s**: collector 25 min → ok. 30 000; Mosquitto 64 min → ok. 77 000 (zaokrąglij do 80 000); sprawdź limit bajtów |
| P2-h | **OK** |

### Pozostałe uwagi

- **U-1 Kąt w opisie panelu:** nie pisz ogólnie „ujemny = pojemnościowy” jako cechy licznika. Napisz:
  „u nas kąt ujemny przy Q < 0 (zmierzone 25.11)”. Konwencja Findera nie jest potwierdzona w dokumentacji.
- **U-2 Kod PLC:** zmiany w `plc/src/GVL_Meter.st` i `plc/src/PRG_ModbusTcpMap.st` to stan PLC po kroku PLC-1
  (wgrany 25.11 09:16). **Zacommituj je** osobnym commitem `plc: E2-PLC2 step PLC-1 – new RTU channels (map v1)`
  razem z `docs/modbus-map.md` v2. Kodu ST nie zmieniaj.
- **U-3 Okno 006:** granice 08:16:10,574–08:16:18,577 UTC – OK.
- **U-4 Wiersze na minutę:** opis panelu i `docs/status-codes.md` na 20/s (1 200/min), 5/s, 1/s.
- **U-5 THD I:** opis „wartość może być niepewna przy małym prądzie” – OK, bez progów.
- **U-6 Temperatura:** kafelek bez progów (nie znamy granic) – OK.

## Dalej

Claude Code: wykonanie k2 wg planu z uwagami (krok 1: `mbpoll -c 60`; wdrożenie; 20 min kontroli v1; zgłoszenie
gotowości do PLC-2). Architekt przygotowuje kod ST dla PLC-2 (`FB_EnergyMeter`, `PRG_ModbusTcpMap` v2,
`MAP_VERSION` = 2, usunięcie zmiennych `rChk…`). Przełączenie PLC – dopiero po zgłoszeniu gotowości.
