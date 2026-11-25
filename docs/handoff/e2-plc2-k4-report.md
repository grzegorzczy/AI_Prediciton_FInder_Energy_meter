# E2-PLC2, krok 4: raport (kontrola danych v2, okno PLC-2, migracja 009)
Status: DO PRZEGLĄDU

Wykonanie 25.11.2026 wg `e2-plc2-k2-report-review.md` i polecenia Grzegorza (czasy w UTC; logi kontenerów w czasie lokalnym UTC+1). Bez `sudo`, bez ruszania smartWARE i `.env`; do PLC dotarł wyłącznie FC04 (`mbpoll -t 3`, collector). Na komputer trafiało tylko to, co jest w `origin/main`.

## Wynik

**Mapa v2 działa na prawdziwym PLC i na prawdziwych danych; wszystkie kryteria z planu są spełnione.**

| Kryterium | Wynik |
| --- | --- |
| `mbpoll -c 60` na v2 | 60 rejestrów odczytanych: `map_version` = 2 (rejestr 2), status licznika 0, serial `F0183363`; rejestry 44–59: n2 mantysa 0 i wykładnik 2 (46), n4 mantysa **48** (`0x0030`) i wykładnik 2 (47–49), THD U `0x4019999A` = 2,4%, THD I `0x4309C7AE` = 137,8%, kąt `0xC24B6666` = −50,85°, temperatura `0x41EA6666` = 29,3 °C, czas pracy `0x499A6CE0`; zgodne z bazą |
| Przełączenie w collectorze | 10:43:01,518 odczyt przekroczył timeout (PLC wgrywa program) → `link_status` 1 przez 8,003 s (10 wierszy), 10:43:10,757 INFO `zmiana wersji mapy rejestrów PLC: 1 -> 2`, 10:43:11,564 `PLC_OFFLINE -> OK`; **bez restartu collectora i bez zmiany konfiguracji** |
| **20 wierszy na sekundę** (okno 10:44:00–11:04:00) | **24 000 wierszy w 1 200 s = 20,000/s**, **1 200 z 1 200 sekund miało dokładnie 20 wierszy**, `link_status` w każdej sekundzie (0 brakujących, 0 wierszy ≠ 0), każda z 20 metryk po 1 200 wierszy; w oknie 0 epizodów błędu licznika |
| 0 pominiętych | 0 wpisów „pomijam metryki” (żadna wartość nie wyszła poza `valid_range`); w logach collectora tylko 2 oczekiwane WARNING z momentu przełączenia (timeout i `OK -> PLC_OFFLINE`), **ingest 0 WARNING i ERROR**, 0 restartów collectora i ingestu, wszystkie kontenery `healthy` |
| Wartości zgodne z PLC-1 | patrz tabela niżej |
| cos φ z kąta ≈ 0,64 przy PF 0,37 | **cos φ z kąta = 0,6286, PF = 0,3699**; predykcja `cos(kąt) / √(1 + THD_I²)` = **0,3704** (zgodna z PF w granicach 0,0005) |
| Izolacja i zasoby | bez nowych portów, `StartedAt` smartWARE bez zmian; pamięć: collector 23,7 MiB, ingest 26,9 MiB, Grafana 132,8 MiB, baza 344,6 MiB (z limitu 1,5 GiB) |

**Wartości v2 w oknie (1 200 próbek każda) a pomiar z PLC-1:**

| Metryka | Jednostka | Min | Średnia | Maks | PLC-1 (25.11, 09:15 lokalnie) |
| --- | --- | --- | --- | --- | --- |
| `thd_voltage` | % | 2,31 | 2,43 | 2,54 | 2,34 |
| `thd_current` | % | 131,74 | 137,10 | 142,28 | 140,22 |
| `phase_angle` | ° | −52,42 | −51,05 | −49,53 | −50,58 |
| `meter_temperature` | °C | 29,3 | 29,35 | 29,4 | 30,2 |
| `run_time` | s | 1 264 983 | 1 265 580 | 1 266 177 | 1 256 171 (o 2,5 h wcześniej) |
| `reactive_pos_varh` (n2) | varh | 0 | 0 | 0 | 0 |
| `reactive_neg_varh` (n4) | varh | 4 800 | 4 800 | 4 800 | 4 500 (23.11) |
| `reactive_power` (Q, v1) | var | −8,9 | −8,68 | −8,5 | −8,7 |

- **Czas pracy rośnie zgodnie z zegarem:** przyrost 1 194 s w 1 199 s (PLC odświeża wartość co 10 s, więc w oknie wychodzi o jeden skok mniej niż czas).
- **Energia bierna:** n2 = 0 i n4 = 4 800 varh (stałe w oknie). Zapis znaku z review (n4 przy Q < 0) jest spójny z danymi: Q stale ujemne (−8,7 var), n2 = 0, n4 > 0. **Pierwszy krok n4 o 100 varh w moich danych jeszcze nie nastąpił** (od przełączenia całka |Q| to 8,5 varh/h; krok oczekiwany co ok. 11–12 h); wcześniejszy przyrost 45 → 48 (4 500 → 4 800 varh) potwierdziłeś w podglądzie online, a baza widzi już 4 800. W kolejnym raporcie dopiszę, kiedy w bazie pojawi się krok 4 800 → 4 900.
- **Kolejny dowód spójności:** całka mocy biernej z agregatu (`reactive_1h_calc`, godzina 10:00): |Q| przy Q < 0 = 8,52 varh przy pokryciu 99,6%, a pozytywna 0; przyrost licznika 0 (przy 8,5 varh/h to oczekiwane).

## Kontrola agregatów v2

- `energy_ext_1m` równe przeliczeniu z surowych danych w 20 minutach okna: liczności, suma THD I, suma cos kąta (`phase_cos_sum`), ostatni czas pracy i stan n4, całka Q przy Q < 0: **wszystkie różnice 0, 0 niezgodności liczności i stanów**.
- `energy_ext_1h`, godzina 10:00: THD I średnio 137,56% (1 009 próbek z 1 009 sekund po przełączeniu), cos φ 0,6292, n4 4 800, czas pracy 1 265 945 s; godzina 11:00 (w toku): THD I 136,3%, cos φ 0,6296. Pierwsza minuta z danymi v2 w agregacie: 10:43:00 (agregat `energy_ext_*` objął wcześniej tylko Q; brak zer dla okresu sprzed v2).

## Okno `plc_program_download` (PLC-2) i migracje

- **Migracja 010** (`010_data_windows_plc2_download.sql`): okno **2026-11-25 10:43:01,518 – 10:43:09,521 UTC** (pierwszy i ostatni wiersz `link_status` ≠ 0 z bazy, 10 wierszy, 8,003 s), opis „Download programu PLC (PLC-2: mapa Modbus v2, nowy FB_EnergyMeter), reset liczników FB”, `exclude_from_analytics` = TRUE; pierwszy wiersz OK po oknie 10:43:11,557. Uwaga: wg Twojej wiadomości download miał być ok. 11:41–11:42 czasu lokalnego, a baza pokazuje utratę łączności 11:43:01 lokalnie: okno (do którego collector faktycznie stracił PLC) zaczyna się więc kilkadziesiąt sekund po tym czasie; granice wziąłem z bazy zgodnie z poleceniem. W `data_windows` są teraz **trzy** okna `plc_program_download` (24.11 14:25, 25.11 08:16, 25.11 10:43), 13 okien łącznie.
- **Migracja 009** (`009_energy_1h_first_last_filter.sql`): odtworzenie `energy_1h` z `FILTER (WHERE … IS NOT NULL)` w `first()`/`last()` (import i export), z odtworzeniem zależnych widoków `energy_1h_calc` i `energy_daily_check` (definicje wygenerowane z 003, identyczne), politykami (odświeżanie 30 dni/15 min, kompresja po 60 dniach, bez retencji) i pełnym odświeżeniem z `energy_1m` (trwa poniżej sekundy na obecnych danych); idempotentna i odporna na przerwanie (jak K6-U3).
  - **Test zgodności przed/po (baza testowa):** na losowych danych z lukami (3 h, reset licznika) wszystkie kolumny `energy_1h`, `energy_1h_calc` i `energy_daily_check` są **identyczne** przed i po, definicje widoków identyczne (`pg_get_viewdef`); dla godziny z pustymi brzegowymi minutami przed poprawką `import_first/last` = NULL i przyrost NULL, po poprawce wartości z minut, które je mają (`first` = 1000, `last` = 1100, przyrost 100); polityki, uprawnienia i brak zmian przy ponownym `migrate`; przerwanie w siedmiu punktach daje ten sam katalog co czysta baza.
  - **Zgodność na produkcji:** zrzut przed (sumy kontrolne md5 i wartości dobowe) i po. **Sumy md5 wierszy godzinowych nie są identyczne** (przed `26b0a65d…`, po `d12f1cdb…` dla 30 godzin przed 10:00): nie mam surowych wierszy sprzed migracji (zapisałem tylko sumy), więc nie mogę wskazać różnic kolumna po kolumnie. Co sprawdziłem po fakcie: **nowy `energy_1h` równa się niezależnemu przeliczeniu z `energy_1m` dla wszystkich 31 godzin** (liczności i stany liczników identyczne, wszystkie sumy statusów zgodne, różnice sum zmiennoprzecinkowych do 3,5·10⁻¹⁰ przy sumach rzędu 10⁵, czyli poziom błędu zaokrągleń), liczba godzin w `energy_1h` równa liczbie godzin w `energy_1m` (31), `import_first/last` bez NULL; **wartości dobowe po migracji identyczne z przed (23.11: 2,013 Wh i przyrost licznika 0; 24.11: 112,829 Wh i 100 Wh)**; definicje widoków identyczne (ta sama suma md5). Różnicę sum md5 przypisuję kolejności sumowania liczb zmiennoprzecinkowych (stary agregat budowany przyrostowo przez kolejne odświeżenia, nowy jednym przebiegiem), ale **tego nie dowiodłem na danych sprzed migracji**; test na bazie testowej, gdzie dane przechodzą przez te same ścieżki, pokazuje identyczne wiersze.
  - Wdrożenie: `up -d --build` 11:09:38–11:09:44, `applied 009…`, `applied 010…` (10 migracji w `schema_migrations`); Grafana działa (0 `level=error`), harness paneli na produkcji **276 zapytań, 0 błędów**.

## Panele po przełączeniu (produkcja, harness przez `docker exec`)

Wszystkie panele v2 zwracają dane: „THD napięcia (THD U)”, „THD prądu (THD I)”, „Kąt U–I”, „Współczynnik mocy PF” (z serią cos φ), „Temperatura licznika” (kafelek i wykres), „Czas pracy licznika” (kafelek i wykres), kafelki „THD U”, „THD I”, „Kąt U–I” na żywo, „Energia bierna z mocy (całka Q, godziny)” i „Energia bierna na dobę: całka i licznik”; zakresy 15 min, 6 h, 24 h i 7 dni bez błędu (przed przełączeniem te panele pokazywały „Brak danych (mapa v1)”; tak ma być do końca zakresu sprzed 10:43).

## Commit kodu PLC

`dd175eb` `plc: E2-PLC2 step PLC-2 - map v2`: `plc/src/FB_EnergyMeter.st`, `plc/src/PRG_ModbusTcpMap.st`, `docs/modbus-map.md` i zrzut `09-plc2-codesys-mapa-v2.png`; treść kodu ST bez zmian (wykonany dopiero po potwierdzeniu danymi, że PLC działa na v2). Review k2 zacommitowane osobno.

## Obserwacje i odstępstwa

1. **Grafana zrestartowała się raz o 10:38:15 UTC** (kod wyjścia 0, bez OOM, bez błędu w logu; polityka `unless-stopped` uruchomiła ją ponownie, `RestartCount` = 1) w czasie, gdy ktoś oglądał dashboardy (kanały „live” zainicjowane 10:37:30–10:37:54). Przyczyny nie ustaliłem; nie wpłynęło to na dane (Grafana ich nie zapisuje). Będę obserwował `RestartCount`.
2. **Zakres okna kontroli:** zgodnie z moim planem miała to być kontrola 20 min na v2; zmierzyłem okno 10:44:00–11:04:00 (po rozgrzewce collectora), przed migracją 009 i wdrożeniem, żeby obciążenie testów i migracji nie zakłócało pomiaru.
3. **Kompresja nowych wierszy:** nadal nie zmierzona (kawałek z 24.11 kompresuje się po 26.11 00:00); zrobię to przy najbliższym kroku (jedna zmiana: 20 wierszy/s dają 1 728 000 wierszy na dobę).
4. **Epizody błędu licznika (E2-PLC1):** w oknach kontroli v1 (20 min) i v2 (20 min) nie było żadnego epizodu; wcześniej pojawiały się seriami (patrz `e2-k7c-report.md`). Mapa v2 niczego tu nie zmieniła.
5. `reactive_1h_calc` zostaje z ostrzeżeniem (decyzja architekta), przepisanie w etapie 4 razem z `energy_1m_calc`.

## Stan testów

Końcowy pełny przebieg na komputerze: uzupełniony poniżej po jego zakończeniu.
