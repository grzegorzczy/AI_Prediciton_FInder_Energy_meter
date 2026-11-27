# E3-k6 – plan kroku (krótki): dashboardy „Flota” i „Pompa P-101”

Data: 2026-11-27. Podstawa: S9, S10, K0-D7 („Flota” = 5 liczników, 1 real + 4 sim, stan = świeżość danych), K4-D2
(`running`), K4-U4 (liczność minut historii), K5R. Review k5 zacommitowane w `1ada2f8`. Produkcja bez zmian do k7.

## Zasady wspólne

Dashboardy generowane w `grafana/generate.py` (jak dotąd, `--check` w testach), źródło danych tylko `app_reader`,
długie zakresy z agregatów, brak danych ≠ zero, adnotacje z `data_windows` (w tym `sim_backfill`, `sim_reset`), brak słów
„przewidywanie awarii” (zasada 8). **Znacznik SYMULACJA (S10):** nazwa każdego urządzenia sim w seriach, wierszach tabel
i liście `$device` = `name || ' (SYMULACJA)'` – z `devices.source`, nie z kodu (zasada 3); urządzenie real bez dopisku.
Na górze obu dashboardów stały panel tekstowy: „Urządzenia oznaczone SYMULACJA to dane symulowane (`source = sim`)”.
Linki nawigacji wszystkich dashboardów dostają dwie nowe pozycje. Lista `$device` istniejących dashboardów obejmuje liczniki
sim (S9) i też dostaje dopisek.

## „Flota” (`aip-flota`, domyślnie 24 h)

1. **Tabela floty** (5 wierszy z `devices`, `kind = 'energy_meter' AND enabled`): nazwa, źródło (real / SYMULACJA, kolor),
   stan = świeżość (Aktualne / Brak danych > `$stale_s`, K0-D7), wiek ostatniej próbki, moc czynna teraz, energia od
   północy [kWh] (`energy_1h_calc` + bieżąca godzina z `energy_1m_calc`, jak w „Przeglądzie”).
2. **Moc czynna – 5 liczników** (seria na urządzenie): ≤ 6 h z `measurements`, dłużej `energy_1m_calc`/`energy_1h_calc`
   (próg jak w istniejących panelach).
3. **Energia na godzinę** (słupki skumulowane na urządzenie, `energy_1h_calc`) i **udział w energii zakresu** (słupek
   poziomy).
4. **Świeżość danych w czasie** (oś stanów na urządzenie: dane / brak danych, minutowo z `energy_1m`).

## „Pompa P-101” (`aip-pompa`, domyślnie 7 dni; zmienna `$pump` z `kind = 'pump'`)

Wszystko z `pump_1m_calc`.
1. **Trend drgań – tylko minuty pracy** (`WHERE running`, K4-D2): średnia dobowa i godzinowa `vibration_avg` z minut pracy
   (zakresy > 7 dni dobowo), panel z własnym zakresem 90 dni (znacznik „własny zakres” jak w „Energii”). Postoje i minuty
   częściowe nie wchodzą do trendu; liczba minut pracy w kubełku jako druga oś (pokrycie).
2. **Drgania minutowe** (minuty pracy jako punkty, pozostałe minuty puste – luka, nie zero) i **obroty** (wszystkie minuty,
   żeby było widać postoje).
3. **Temperatura łożyska, prąd silnika, przepływ** (średnie minutowe; dłuższe zakresy godzinowo).
4. **Udział minut pracy** na godzinę (`run_share`) i **stat**: drgania średnio z ostatniej godziny pracy, temperatura teraz.
Bez prognozy i bez „dni do progu” – to etap 5.

## Testy (tylko `aip-test`)

- **Generator:** nowe UID-y i linki, każdy panel z SQL tylko na widokach/tabelach dostępnych dla `app_reader`, dopisek
  SYMULACJA wyliczany z `source` (żadnych nazw urządzeń w generatorze), zakaz słów z zasady 8, `--check` czysty.
- **Panele przez API Grafany** (harness z E2-k7) na danych **z narzędzia historii**: nowa fixtura sesji ładuje do bazy
  `energy` przez MQTT i ingest (`simulator.backfill`, QoS 1, sterowanie przepływem) liczniki sim **2 h** i pompę **84 doby**
  (ok. 0,17 + 0,6 mln wiadomości, ok. 10 min przy tempie z pilotażu), daty w configu testu liczone od „teraz” (ingest odrzuca przyszłość),
  obok dotychczasowych danych Findera (`build_panel_data`). Sprawdzenia: każdy cel każdego panelu w zakresach 15 m … 90 d
  bez błędu i < 3 s; tabela floty = 5 wierszy, 4 z SYMULACJA, Finder bez; trend drgań rośnie (ostatni tydzień > pierwszy,
  zgodnie z modelem 1,1 → x = 0,70); trend nie zawiera minut z `running = false` (minuty postoju z modelu poza wynikiem);
  luka w danych pompy = brak punktu, nie zero.
- **Pamięć Grafany** (uwaga z E2-k8b): szczyt kontenera `aip-test` w czasie harnessu z nowymi dashboardami; pomiar
  produkcyjny w k7.

## Pliki

Zmieniane: `grafana/generate.py`, `grafana/dashboards/*.json` (wynik generatora: 2 nowe, 5 z nowymi linkami i `$device`),
`tests/grafana/test_grafana_generator.py`, `test_grafana_panels.py`, `conftest.py`/`grafana_support.py` (fixtura historii),
`docs/data-model.md` lub `docs/ops` (krótko: dashboardy etapu 3). `reviewer` – nie (brak zmian ingestu, brokera, migracji).

## Zrzuty do zrobienia przez Grzegorza

Ze stosu `aip-test` z danymi z narzędzia historii (produkcja dopiero w k7), w przeglądarce na laptopie:
1. Flota, 24 h, cały ekran – 5 liczników, SYMULACJA przy czterech, Finder bez.
2. Flota, 7 dni – energia na godzinę i udział w energii.
3. Flota – podpowiedź (tooltip) na serii licznika sim z dopiskiem SYMULACJA.
4. Pompa P-101, 90 dni – rosnący trend drgań z minut pracy, adnotacja `sim_backfill`, jeśli jest.
5. Pompa P-101, 24 h – drgania minutowe z lukami w postojach i obroty pokazujące postoje.
6. Pompa P-101, 6 h – temperatura łożyska, prąd, przepływ.
7. „Licznik na żywo” – rozwinięta lista `$device` z dopiskami SYMULACJA.
8. Dowolny dashboard na wąskim oknie (telefon) – czytelność tabeli floty.

## Do decyzji

1. **Progi drgań na wykresie:** proponuję w k6 **bez linii progów** (zakres modelu 1,1–7,0 mm/s to nie próg; zasada 7 –
   strefy ISO 10816/20816 wymagają klasy maszyny i wartości od Grzegorza). Linie progów razem z etapem 5 albo teraz – po
   podaniu wartości.
2. **Minimum liczności minuty pracy (K4-U4):** proponuję w k6 sam `running` (historia ma 1 próbkę/min); minimum `speed_n`
   dla danych na żywo decyduje etap 5.
3. **Jak pokazać `aip-test` do zrzutów:** proponuję skrypt `tests/run-demo.sh` (stos `aip-test` z danymi, zostaje do
   sprzątnięcia) i tunel `ssh -L` z laptopa do Grafany testowej (port tylko na `127.0.0.1` komputera). Alternatywa: zrzuty
   dopiero z produkcji w k7.
4. **Dane testowe w zwykłym zestawie** (2 h liczników + 84 doby pompy, ok. 10 min, zestaw z 27 do ok. 37 min) – proponuję tak; alternatywa: pompa co 5 min w fixturze (2 min), ale wtedy nie są to dane jak z produkcyjnej historii. Dłuższe dane liczników
   tylko w pomiarze `perf`.

Plan e3-k6 gotowy do przeglądu.
