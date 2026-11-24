# e2-plc1 diag review: cykliczny błąd PLC–licznik

Recenzent: architekt, 24.11.2026. Podstawa: `docs/handoff/e2-plc1-diag.md` (commit `20f2b0d`), `e2-k5-report-review.md` (U-1), dokumentacja CODESYS `MB_ErrorCodes` (helpme-codesys.com, IoDrvModbus).

## Werdykt: diagnoza OK – gałąź „inny kod”

- `error_code` epizodów = 16#A2 = **`RESPONSE_CRC_FAIL`**: odpowiedź licznika dotarła, ale suma kontrolna się nie zgadza. To **nie** jest timeout, więc zmiana Response timeout 200 → 1000 ms (gałąź „kod 161”) **odpada**. Źródło: dokumentacja biblioteki CODESYS `MB_ErrorCodes` (A1 = RESPONSE_TIMEOUT, A2 = RESPONSE_CRC_FAIL, A3 = RESPONSE_WRONG_SLAVE).
- Zjawisko nie zależy od collectora ani od obciążenia Modbus TCP (7 epizodów w 900 s przy dwóch połączeniach `mbpoll`).
- Faza siatki 64 s przetrwała zanik zasilania PLC, licznika i komputera (±1 s), a po powrocie zasilania przez ok. 4 h nie było epizodów. Źródło okresowości nie jest związane z chwilą startu żadnego z tych urządzeń. Przyczyny nie zgadujemy; typowe przyczyny błędów CRC w RS485 to okablowanie (brak skrętki, brak przewodu odniesienia/ekranu, terminacja i polaryzacja), zakłócenia z innych urządzeń i parametry ramki.

## Następne kroki E2-PLC1 (architekt + Grzegorz)

1. Fakty od Grzegorza (bez zgadywania):
   - czy CODESYS był zalogowany online w okresach epizodów (23.11 22:38–23:16 UTC, 24.11 od 11:01 UTC);
   - zdjęcie okablowania RS485 przy liczniku i przy PLC, rodzaj przewodu (skrętka? długość?), czy zacisk SC licznika jest podłączony;
   - co jeszcze jest zasilane z tej samej listwy lub stoi obok (zasilacze impulsowe, urządzenia z cyklem pracy).
2. Dalsze działania ustali architekt po tych faktach (np. skrętka z przewodem odniesienia, sprawdzenie zacisków COM variTRONa w dokumentacji JUMO). Do PLC i licznika z komputera nadal tylko odczyt.
3. Filtr 3 s w `FB_EnergyMeter` – bez zmian do czasu usunięcia przyczyny.

## Dla Claude Code

- Brak logowania `error_code` w collectorze (zapowiedziane w k3, niezaimplementowane, nieprzetestowane) – **dodać w k5b**: log przy zmianie kodu oraz metryka `meter_error_code` (publikowana przy `meter_status ≠ 0`, w `devices.yaml`), z testem.
- Uszkodzone logi Dockera po zaniku zasilania (`\x00`) – do k8 (wymaga `sudo`; polecenie dla Grzegorza w planie k8).
- Autostart po zaniku zasilania zadziałał (kontenery w 300 ms, odzysk bazy 0,13 s) – odnotować w k8 jako pierwszy, nieplanowany dowód; test planowy w k8 zostaje.
- `plc/setup/10.2.1.1-new_1.431.432` zmieniony – to zapis projektu przez Grzegorza po poprawce `FB_EnergyMeter` (zaplanowany w etapie 1). Commit po potwierdzeniu Grzegorza. `~$_Predykcja_dokumentacja.docx` to plik blokady otwartego Worda: nie commitować, dodać `~$*` do `.gitignore`.
- Po „ok” Grzegorza: `e2-k5b-plan.md` (U-2 luki `link_status`, U-3 opis kodów, U-4 wyciszenie pymodbus, `error_code` jak wyżej) → stop.
