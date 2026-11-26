# E3-k2 – review planu (architekt)

Data: 2026-11-26. Plan: `e3-k2-plan.md` (`9bf8407`). Commity przed k2: `.432` po PLC-2 `e61b2fd`, review k1 `67ef49f`.

**Werdykt: OK Z UWAGAMI.** Wykonanie po „ok” Grzegorza (dotyczy też parametrów z K2-D1). Uwagi K2-U1…U6 wchodzą do wykonania k2.

## Sprawdzone

- Model `f(t, ziarno, config)` bez stanu, szum z `blake2b` zamiast `hash()` – zgodne z K0; determinizm sprawdzany także w nowym procesie.
- K1-U1 i K1-U2 rozwiązane poprawnie. Przy `t_zero: null` jest błąd konfiguracji i kod 2, a data bez strefy też jest błędem.
- Krok nie wyprzedza etapu: bez sieci, MQTT, kontenera i produkcji. Ingest ignoruje nowe klucze, co sprawdza test.
- Przeliczyłem wartości kontrolne pompy (k = 3): f(0,25 / 0,5 / 0,7 / 0,85 / 1) = 0,059 / 0,182 / 0,376 / 0,619 / 1. Drgania: 1,45 / 2,18 / 3,32 / 4,75 / 7,00 mm/s. Temperatura łożyska w dniu 84: 61,8 °C. Wszystko zgodne z planem.
- Prąd pompy: 11 kW / (√3 · 400 V · 0,86 · 0,9) = 20,5 A, czyli wartość 21 A jest spójna.
- Energia dobowa w dzień roboczy (15 h pracy, 1 h przerw, 8 h postoju), liczona z parametrów planu:
  - pasteryzator ok. 180–192 kWh (zależnie od mocy w fazie „wyłączonej” cyklu, patrz K2-U6);
  - chłodnia ok. 143 kWh (14/9 min, przed wpływem otoczenia);
  - mieszalnik ok. 67 kWh;
  - pakowaczka ok. 50 kWh.

  Każda wartość mieści się w przedziale z testu 4.
- 29 metryk (4 × 6 + 5), zgodne z S3. Na żywo ok. 29 wierszy/s, razem z prawdziwym sprzętem ok. 49/s – zgodne z S4.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K2-D1 | Parametry spoza K0: przerwy 10:00/15, 13:30/30, 18:00/15 min; otoczenie 20 ± 3 °C; `energy_start_wh`; `current_a: 21`; stałe nagrzewania/stygnięcia 25/40 min | **Rekomenduję przyjęcie**. To parametry symulacji, nie fakty o sprzęcie. Wiążące po „ok” Grzegorza; jeśli zna inne przerwy z zakładów klientów, zmiana to jedna linia w YAML. |
| K2-D2 | Przedziały energii dobowej jako kryterium testu modelu | **Tak.** To test spójności parametrów (moce × czasy), nie odwzorowanie prawdziwej maszyny. W raporcie podać zmierzoną energię każdej maszyny obok przedziału. |

## Uwagi do wykonania

- **K2-U1 – pompa po końcu krzywej (x > 1).** 120 dni degradacji to 36 dni na żywo po `t_zero`; plan nie mówi, co potem. Decyzja: x obcinamy do 1,0, a drgania zostają na 7,0 mm/s z szumem. Przy pierwszym przekroczeniu w procesie pojawia się WARNING w logu. „Wymiana łożyska” = nowe `t_zero` (procedura wdrożenia z k7) plus okno `data_windows` (`sim_reset`). Test: x = 1,2 daje wartości jak x = 1.
- **K2-U2 – strefa czasowa w obrazie.** `zoneinfo` potrzebuje bazy stref. Dodać przypięty pakiet `tzdata` do `services/simulator/requirements.txt`, żeby wynik nie zależał od tego, czy obraz `slim` ma `/usr/share/zoneinfo`. Testy czasu letniego mają przechodzić w kontenerze testowym z tą samą wersją Pythona, której użyje obraz z k3.
- **K2-U3 – koszt startu licznika energii.** Cel < 30 s dla 14 dni to za mało, bo symulator będzie restartowany miesiącami po kotwicy. W raporcie: zmierzony koszt jednej doby i prognoza dla 30 / 90 / 365 dni. Jeśli 90 dni przekracza 60 s, rozwiązanie wybieramy w k3 (np. pamięć podręczna sum dobowych w pliku – da się ją odtworzyć, więc nie łamie zasady „bez stanu”). Ręczne przesuwanie kotwicy w configu odrzucam. Opisać też w `docs/data-model.md`: licznik to całka modelu, więc rośnie także wtedy, gdy próbki nie były publikowane (jak prawdziwy licznik przy przerwie komunikacji).
- **K2-U4 – pompa w przerwach i prąd silnika.** Doprecyzować: pompa pracuje przez całą zmianę, także w przerwach (cyrkulacja procesowa), a stoi poza zmianami. Mniej postojów oznacza czystszy trend dla etapu 5. Prąd silnika rośnie z degradacją lekko (do +5 % przy x = 1) albo wcale – zapisać, który wariant przyjęto. Uwaga na k4 (`pump_1m`): agregat musi mieć znacznik pracy (np. udział próbek z `speed > 0`). Wtedy analityka liczy trend drgań tylko w stanie pracy, a nie z tła 0,1 mm/s poza zmianą.
- **K2-U5 – jednostka obrotów.** `rpm` zamiast `obr/min` (kod i dane po angielsku). Polski opis da Grafana w k6.
- **K2-U6 – faza „wyłączona” termostatu w czasie pracy.** Zapisać w YAML i `docs/data-model.md`, jaka moc obowiązuje w 35 % cyklu pasteryzatora: `p_idle_kw` (wtedy ok. 192 kWh/dobę) czy `p_off_kw` (ok. 180). Rekomenduję `p_idle_kw`, bo grzałka wyłączona, ale pompy obiegowe i sterowanie pracują. Do testu: sobota 13:30–14:00 to przerwa kończąca się z końcem zmiany, a 14:00:00 = `off`.

## Zrzuty

k2 nie zmienia GUI, więc zrzuty nie są potrzebne. Do dokumentacji Word v3 trafią jako wydruki tekstowe: tabela energii dobowej (zmierzona vs przedział) i wartości kontrolne krzywej pompy.

## Dalej

„Ok” Grzegorza → wykonanie k2 w worktree → pełne testy → `reviewer` → `e3-k2-report.md` (z hashem `e61b2fd` pliku `.432`) → review.
