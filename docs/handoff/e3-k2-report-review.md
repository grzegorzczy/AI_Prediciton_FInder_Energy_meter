# E3-k2 – review raportu (architekt)

Data: 2026-11-26. Raport: `e3-k2-report.md` (`71ca722`; commity kroku `85f95a2`, `b53fb59`, `1b03239`; review planu `ed23758`).

**Werdykt: OK.** Krok k2 zamknięty. Biblioteka symulatora zgodna z planem, wszystkie uwagi K1-U1, K1-U2 i K2-U1…U6 wykonane i sprawdzone testami. Produkcja nietknięta (`c299eaa`).

## Co potwierdza „gotowe” dla k2

- Energia doby roboczej zgodna z moim przeliczeniem z parametrów (192 / 143 / 67 / 50 kWh): zmierzone 192,3 / 142,0 / 65,2 / 49,9 kWh, wszystkie w przedziałach K2-D2. Razem 449 kWh/dobę.
- Krzywa pompy: zmierzone średnie godzinowe są o 1–1,5 % powyżej wartości kontrolnych. Wyjaśnienie jest wiarygodne: wolne wahanie ±3 % z okresem 6 h w tej konkretnej godzinie, ta sama chwila dla każdego x, więc przesunięcie wszędzie ma ten sam znak. Temperatura łożyska w `t_zero` 61,8 °C – zgodna.
- Determinizm sprawdzony także w nowym procesie z innym `PYTHONHASHSEED` – to był główny warunek K0.
- Całka licznika na liczbach całkowitych W·s (ustalenie 3 `reviewer`) – bardzo dobra poprawka: bez niej licznik mógł na sekundę spaść o 100 Wh, a widoki energii z etapu 2 oznaczyłyby to jako reset.
- `devices.yaml` na dysku laptopa sprawdzony: parametry zgodne z K0 i K2-D1, nagłówek „wersja 2”, `p_idle_kw` w fazie wyłączonej grzałki (K2-U6), pompa przez całą zmianę (K2-U4).
- 653 passed, 0 failed.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K2R-D1 | Ustalenie 2: jedno `t_zero` dla pompy i liczników | **Rozdzielić – w k3, nie dopiero przed k7** (zmiana configu i modelu jest tania teraz, później zależy od niej k5 i wdrożenie). Dwa pola o fizycznym znaczeniu: `meter_anchor` – stała data kotwicy liczników energii (`energy_start_wh` w tej chwili), nigdy niezmieniana po wdrożeniu; `pump.bearing_installed_at` – data montażu łożyska, **x = 0 w tej chwili**, x = (t − montaż) / 120 dni. Pole `t_zero` i `degradation.history_progress` znikają z konfiguracji. Przy wdrożeniu (k7): `meter_anchor` = wdrożenie − 14 dni, `bearing_installed_at` = wdrożenie − 84 dni (stąd x = 0,70 „teraz”, jak w K0-D2). Oba wymagane: `null` = błąd konfiguracji, nic nie podstawia „teraz” (K1-U2 bez zmian w sensie). |
| K2R-D2 | **Korekta mojej uwagi K2-U1** | W review planu napisałem „wymiana łożyska = nowe `t_zero`”. To był błąd: przy x(t_zero) = 0,70 nowa data dawałaby łożysko zużyte w 70 %, a nie nowe – i cofałaby liczniki (ustalenie 2). Poprawnie: **wymiana łożyska = nowa `bearing_installed_at`** (x = 0, drgania ok. 1,1 mm/s) + okno `data_windows` `sim_reset`. Liczniki energii nietknięte. Historii po wymianie nie wgrywamy ponownie – wgranie historii (k5) jest jednorazowe przy wdrożeniu. Obcinanie x > 1 i ostrzeżenie zostają. |
| K2R-D3 | K2-U3: start licznika 283 s przy 90 dniach | **Tak – pamięć sum dobowych w pliku w wolumenie symulatora (k3)**, z warunkami: (1) klucz = urządzenie, numer doby od `meter_anchor`, skrót parametrów modelu, ziarna, `meter_anchor` **i stałej `MODEL_VERSION` w kodzie** (zmiana kodu modelu unieważnia pamięć – bez tego stary plik po zmianie modelu dawałby zły licznik); (2) doba = blok 86 400 s od kotwicy (UTC), nie doba lokalna – czas letni nie zmienia klucza; (3) przy starcie kontrola: ostatnia zapisana doba każdego licznika przeliczona i porównana co do W·s – niezgodność = WARNING, odrzucenie pliku, pełne przeliczenie; (4) zapis atomowy (plik tymczasowy + `rename`); brak lub uszkodzenie pliku = przeliczenie, nie błąd; (5) kontener zostaje `read_only`, zapisywalny tylko wolumen. W raporcie k3: start po 14 / 90 / 365 dniach z plikiem i bez. |

## Uwagi do k3 / k5

- **K2R-U1:** `PYTHONTZPATH=""` w obrazie – tak (k3); test w obrazie: `zoneinfo` bierze bazę z `tzdata` (np. `tzdata.IANA_VERSION` = 2025b obok wyniku dla 25.10.2026).
- **K2R-U2:** historia pompy przez `samples_at(t, devices={pompa})` (ustalenie 6) – tak, w planie k5.
- **K2R-U3:** stałe modelu w kodzie (+5 % prądu, −5 % przepływu, tło 0,1 mm/s, szum) – akceptuję jako parametry modelu; przenieść do YAML przy drugim typie pompy.
- **K2R-U4:** ustalenie 5 – brakujący test energii doby 23 h i 25 h (czas letni): dopisać w k3 razem z pamięcią dobową (energia doby lokalnej 29.03.2027 i 25.10.2026 = suma jej sekund; na mieszalniku/pakowaczce przesunięcie zmian w UTC).
- **K2R-U5:** czas pełnego zestawu 22 min – akceptowalny; po K2R-D3 ma spaść (podać w raporcie k3).

## Zrzuty

k2 bez zmian w GUI – zrzutów nie potrzeba. Do Word v3 jako wydruki: tabela energii dobowej i tabela krzywej pompy z tego raportu.

## Dalej

Plan k3 (kontener `aip-simulator`, tryb na żywo, konto MQTT i ACL z K1-D1/K1-D2, `PYTHONTZPATH`, K2R-D1, K2R-D3) → review → „ok”.
