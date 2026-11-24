# e2-k7 zakres rozszerzony: Grafana (zastępuje „Zakres k7” z `e2-k6-report-review.md`)

Architekt, 24.11.2026. **Decyzja Grzegorza:** w k7 rozbudowana Grafana z danych, które już zbieramy (5 dashboardów). Nowe dane z licznika (THD, temperatura, kąt, czas pracy, energia bierna) – osobny krok **E2-PLC2** po k7 (zmiana programu PLC i mapy v2, potem collector). Pozostałe punkty `e2-k6-report-review.md` (pomiar K6-U4, Grafana w Compose, provisioning jako kod, testy, czynności Grzegorza) obowiązują bez zmian.

## Zasady wspólne

- Dashboardy jako JSON w repo (`grafana/dashboards/`), provisioning; folder „AI Predykcja”; zmienne `$device` (z tabeli `devices`, `kind = energy_meter`), aby kolejne liczniki (etap 3) działały bez kopiowania paneli.
- Strefa wyświetlania `Europe/Warsaw`; polskie tytuły, jednostki SI, opisy paneli (`description`) z definicją wielkości.
- Źródło: wyłącznie `app_reader`. Zapytania z filtrem czasu Grafany (`$__timeFilter`, `$__timeGroupAlias`); długie zakresy z `energy_1m` / `energy_1h`, nie z `measurements`.
- Progi i stałe jakości energii (230 V, ±10%, 50 Hz, ±0,2 Hz itp.) jako **zmienne dashboardu** lub stałe w jednym miejscu, opisane w `docs/grafana.md`. Tabela `tariffs` i koszty w zł – dopiero etap 4.
- Zasada 8: żadnego „przewidywania awarii” w nazwach.
- **Adnotacje:** okna testów i przerw z dokumentu projektu 12 (tabela „Okna testów…”) jako plik w repo (`config/annotations.yaml` albo migracja z tabelą `data_windows` – do wyboru w planie; jeśli tabela, to tylko odczyt dla `app_reader`, zapis przez `migrate`), widoczne na wykresach czasowych.
- Panel „brak danych” ≠ „zero”: wykresy nie łączą punktów przez luki dłuższe niż kilka okresów (`connect null values` wyłączone lub próg).

## Dashboardy

1. **Przegląd** (strona startowa): moc czynna teraz, zużycie dziś i wczoraj (całka mocy, z pokryciem), maksymalna moc dziś (z godziną), średni cos φ dziś, stan PLC i stan licznika (K3-U3: „brak danych z PLC”, gdy `link_status ≠ 0` lub dane starsze niż kilka sekund), pokrycie danych dziś, wiek ostatniego odczytu, liczba epizodów błędu licznika dziś.
2. **Licznik na żywo** (odświeżanie 5 s, domyślnie ostatnie 15 min): U, I, P, Q, S, PF, f – wykresy i kafelki ostatniej wartości z min/max/średnią w oknie.
3. **Jakość energii:** napięcie z pasmem 230 V ±10% (strefy kolorów), min/max/średnia z `energy_1m`; odchyłka częstotliwości od 50 Hz; cos φ i stosunek Q/P; histogram napięcia (rozkład w zakresie czasu); liczba minut z napięciem poza pasmem. Opis panelu: pasmo ±10% to wartość orientacyjna, nie ocena zgodności z normą.
4. **Energia i profil:** zużycie na minutę / godzinę / dobę (całka mocy) z pokryciem; **mapa cieplna godzina × dzień tygodnia** (średnia moc lub zużycie z `energy_1h`); porównanie dziś vs wczoraj i bieżący tydzień vs poprzedni (przesunięcie czasu); moc bazowa (np. minimum lub 5. percentyl mocy w godzinach nocnych 0–5 – definicja w opisie); tabela `energy_daily_check` (całka, licznik, `within_resolution`, pokrycie, `day_complete`).
5. **Stan i diagnostyka:** oś stanów `link_status` i `meter_status` (kolory i nazwy kodów z `docs/status-codes.md`); `meter_error_code` z nazwą (161/162/163); `meter_error_count`, `meter_data_age_ms`; liczba sekund bez danych na godzinę; adnotacje okien testów i zaników zasilania. Opcjonalnie: wiersze na minutę z `measurements` (pokazuje model 13/5/1).

## Testy (dodatkowo do `e2-k6-report-review.md`)

- Każdy panel każdego dashboardu wykonuje zapytanie przez API Grafany na prawdziwej bazie bez błędu i zwraca dane (lub świadomie „brak danych” dla pustego zakresu).
- Zapytania paneli „Energia i profil” i „Jakość energii” na syntetycznym roku (pomiar K6-U4) < 1 s każde.
- Zmienna `$device` działa przy dwóch licznikach (dane syntetyczne w `aip-test`).
- Adnotacje: okna z dokumentu 12 widoczne (zapytanie adnotacji zwraca oczekiwane przedziały).

## Czynności Grzegorza (bez zmian)

Logowanie z laptopa (`http://192.168.0.213:3000`) i **zrzuty pięciu dashboardów** do `docs/images/etap2/` (pierwsze zrzuty GUI do dokumentacji Word v2).

## Po k7

- **E2-PLC2:** nowe kanały w PLC (THD U/I, kąt U–I, temperatura wewnętrzna, czas pracy z bloku 32480–32658; energia bierna n2/n4), mapa Modbus TCP v2 (`MAP_VERSION` = 2), collector i panele (Jakość energii: THD; Diagnostyka: temperatura licznika, czas pracy). Prowadzi architekt z Grzegorzem (kod ST ręcznie), potem plan Claude Code.
- k8 (restart, dysk, dokumentacja Word v2) – po E2-PLC2 albo przed, decyzja Grzegorza.
