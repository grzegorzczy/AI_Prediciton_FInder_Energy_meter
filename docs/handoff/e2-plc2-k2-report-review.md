# E2-PLC2 krok 2 – review raportu (architekt)

Data: 2026-11-25. Raport: `e2-plc2-k2-report.md` (komputer na `4e86c5e`).

**Werdykt: OK – gotowość do PLC-2 przyjęta.** `mbpoll -c 60` na v1 (44–59 = 0), 482/482 testów, 20 min na v1:
13,00 wiersza/s, `link_status` w 1 200 z 1 200 s, 0 metryk v2, 0 błędów; 276 zapytań paneli bez błędu.

## Decyzje w sprawie ustaleń

- **009 – `energy_1h` z `FILTER` w `first()/last()`: TAK, teraz.** Dane mamy od 23.11, `energy_1m` ma retencję
  1 roku, więc odtworzenie `energy_1h` z `energy_1m` nic nie traci. Później (po 90 dniach surowych danych i dłuższej
  historii) byłoby droższe. Wykonaj w kroku 4, po przełączeniu PLC, z testem zgodności przed/po (sumy godzinowe
  identyczne dla 23–25.11) i z `CALL refresh_continuous_aggregate` na pełny zakres.
- **`reactive_1h_calc` ok. 20 s na roku:** akceptuję ostrzeżenie w `docs/data-model.md`; panele go nie używają.
  Przepisanie na funkcję z zakresem – etap 4, razem z `energy_1m_calc` (K6-U4).
- **Drugi licznik w v2:** zapisuję jako warunek etapu 3: tablica `awTcpInputRegs` w PLC i zakres Input Registers
  serwera do powiększenia (np. 0–199), nowa wersja mapy. Do tego czasu jeden licznik.

## Dalej

PLC-2 (Grzegorz + architekt): kod ST w `plc/src/FB_EnergyMeter.st` i `plc/src/PRG_ModbusTcpMap.st` (architekt,
25.11), download. Po sygnale Grzegorza krok 4 Claude Code: `mbpoll -c 60` na v2, kontrola danych v2 wg planu,
okno `plc_program_download` (PLC-2), migracja 009, raport `e2-plc2-k4-report.md`. Kod ST commituje Claude Code
po potwierdzeniu, że PLC działa (`plc: E2-PLC2 step PLC-2 – map v2`).
