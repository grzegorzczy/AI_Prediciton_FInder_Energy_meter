# Model danych (projekt wstępny)

**Status: propozycja do zatwierdzenia na początku etapu 2.** Nazwy tabel, kompresja
i retencja pochodzą z ustaleń projektu. Kolumny i typy to propozycja: mogą się
zmienić, gdy powstanie `docs/modbus-map.md` i `docs/decisions.md`.

## Zasady

- Jedna wąska tabela pomiarów: wiersz = jedna wartość jednej metryki w chwili.
  Nowa metryka nie wymaga zmiany schematu.
- Czas zawsze `TIMESTAMPTZ` w UTC; strefa Europe/Warsaw tylko w prezentacji.
- Źródło każdej wartości: `real` (PLC) albo `sim` (symulator).
- Urządzenia definiuje `config/devices.yaml`; tabela `devices` jest jego odbiciem
  synchronizowanym przy starcie, a nie miejscem ręcznej edycji.
- Dwie role w bazie: `app_writer` (ingest, analytics) i `app_reader`
  (Grafana, czat; tylko SELECT, `statement_timeout`).

## Zgodność z MQTT

Temat `zaklad/linia/urzadzenie/metryka` → `device_id` = `urzadzenie`,
`metric` = `metryka`; `zaklad` i `linia` są atrybutami urządzenia w `devices`.
Ładunek `{ts, value, unit, source}` → kolumny `time, value, unit, source`.

## Tabele

### `devices`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| device_id | TEXT PK | np. `meter-01`, `p-101` |
| name | TEXT | nazwa po polsku |
| site | TEXT | zakład |
| line | TEXT | linia |
| kind | TEXT | `energy_meter`, `pump`, … |
| source | TEXT | `real` / `sim` |
| enabled | BOOLEAN | |
| meta | JSONB | dodatkowe atrybuty z configu |

Zakład i linia są **na urządzenie** (E3-k1): prawdziwy sprzęt (PLC `plc-01`, Finder) ma `zaklad1/linia1` z sekcji głównej
`config/devices.yaml`, urządzenia symulatora (`sim_*`, `source = sim`) – `zaklad1/linia2` z sekcji `simulator`. Ingest przyjmuje
wiadomość tylko wtedy, gdy zakład i linia z tematu są zakładem i linią tego urządzenia, a `source` w ładunku jest źródłem
urządzenia; dane sim nie trafią więc pod prawdziwe urządzenie ani odwrotnie.

Klucze `meta` (wpisuje ingest z configu; brak wartości = brak klucza):

| Klucz | Urządzenia | Znaczenie |
| --- | --- | --- |
| `poll_interval_s` | liczniki, pompa | okres próbek [s]; widoki energii liczą z niego energię i pokrycie |
| `energy_resolution_wh`, `reactive_resolution_varh` | liczniki | rozdzielczość stanu licznika energii [Wh], [varh] |
| `phases` | liczniki | **1 – Finder (jednofazowy: U1, I1); 3 – liczniki symulatora (trójfazowe)**. U liczników trójfazowych `voltage` to napięcie fazowe, `current` prąd jednej fazy przy obciążeniu symetrycznym, a moce i energia są sumą trzech faz. Etap 4 nie może tych dwóch rodzajów mieszać (np. liczyć mocy z U × I bez uwzględnienia `phases`). |
| `rated_kw` | urządzenia sim | parametr symulacji: moc znamionowa maszyny (liczniki) albo moc silnika pompy; **dla pompy to nie jest moc pobierana** – pompa nie publikuje `active_power` (K0-D9) |
| `profile`, `block_base`, `serial` | Finder | profil rejestrów i numer seryjny z PLC |
| `map_versions` | PLC | akceptowane wersje mapy Modbus |

### Metryki urządzeń symulatora (E3-k2)

Wartości liczy biblioteka `services/simulator` jako deterministyczną funkcję chwili, ziarna i configu (`config/devices.yaml`,
sekcja `simulator`); to **dane modelu, nie pomiary**. Na żywo co 1 s (k3), historia w k5.

| Urządzenia | Metryka | Jednostka | Uwagi |
| --- | --- | --- | --- |
| liczniki sim (`energy_meter`, trójfazowe) | `active_power`, `reactive_power`, `voltage`, `current`, `power_factor`, `energy_import_wh` | `W`, `var`, `V`, `A`, –, `Wh` | `voltage` fazowe, `current` jednej fazy (I = S / 3U); Q > 0 (odbiorniki indukcyjne) |
| pompa (`pump`) | `vibration_rms`, `bearing_temperature`, `motor_current`, `flow`, `speed` | `mm/s`, `°C`, `A`, `m³/h`, `rpm` | bez `active_power` (K0-D9) |

- **Licznik `energy_import_wh` to całka modelu** od kotwicy (`t_zero` − `history.meter_days`) i `energy_start_wh`, kwantowana do
  100 Wh: rośnie także wtedy, gdy próbek nie publikowano (jak prawdziwy licznik przy przerwie komunikacji), więc po przerwie
  przyrost licznika może być większy niż całka z zapisanych próbek.
- **Termostat (pasteryzator):** w fazie wyłączonej grzałki w czasie pracy obowiązuje `p_idle_kw` (pompy obiegowe i sterowanie
  pracują, K2-U6); doba robocza ok. 192 kWh.
- **Pompa:** pracuje przez całą zmianę, także w przerwach (cyrkulacja procesowa), stoi poza zmianami: wtedy `speed`, `flow`,
  `motor_current` = 0, a `vibration_rms` to tło ok. 0,1 mm/s – analityka trendu drgań ma brać tylko próbki z `speed > 0`
  (znacznik pracy w `pump_1m`, k4). Prąd silnika rośnie z degradacją o 5 % przy końcu krzywej (K2-U4).
- **Degradacja pompy:** postęp x = 0,70 w `t_zero`, koniec krzywej po 120 dniach; po nim (x > 1) wartości zostają jak dla x = 1
  (WARNING raz w logu), „wymiana łożyska” = nowe `t_zero` przy wdrożeniu i okno `sim_reset` w `data_windows` (K2-U1).
  `vibration_end_mm_s` to koniec zakresu modelu, **nie próg alarmowy** (progi: etap 5).

### `measurements` (hypertable)

| Kolumna | Typ | Opis |
| --- | --- | --- |
| time | TIMESTAMPTZ | znacznik czasu z ładunku |
| device_id | TEXT FK → devices | |
| metric | TEXT | np. `voltage`, `active_power`, `energy_import` |
| value | DOUBLE PRECISION | |
| unit | TEXT | `V`, `W`, `Wh`, `mm/s`, … |
| source | TEXT | `real` / `sim` |

- Klucz unikalny: `(device_id, metric, time)` – chroni przed duplikatami po ponowieniu.
- Hypertable po `time`, kawałki 1 dzień.
- Kompresja po 1 dniu, `segmentby = device_id, metric`.
- Retencja 90 dni (surowe dane). Agregaty trzymane dłużej: `energy_1m` 1 rok, `energy_1h` bez limitu (tabela wyżej).

### Agregaty ciągłe energii (migracja `002_energy_aggregates.sql`, krok k6)

Agregaty przechowują **wyłącznie wartości addytywne lub odtwarzalne** (liczności, sumy, minima, maksima, pierwsza i ostatnia
wartość), bo tylko takie można poprawnie złożyć w agregat godzinny. Wartości pochodne liczą widoki (niżej).

| Agregat | Okno | Źródło | Zawartość |
| --- | --- | --- | --- |
| `energy_1m` | 1 min | `measurements` | dla każdej metryki: liczność `*_n` (sekundy z pomiarem) i suma `*_sum`; dla mocy czynnej, napięcia i prądu także `*_min`, `*_max`; stan liczników energii `import_first/last/min/max` i `export_first/last/min/max` (Wh); `meter_error_seconds` (sekundy z `meter_status` ≠ 0) i `meter_status_n` |
| `energy_1h` | 1 h | `energy_1m` (agregat hierarchiczny) | te same kolumny, złożone z minutowych (sumy sum, minima z minimów, `first`/`last` z wiaderek) |
| `pump_1m` | 1 min | `measurements` | planowany w etapie 4 |

- `plc-01` (tylko `link_status`) nie tworzy wierszy; agregaty obejmują metryki licznika wymienione w migracji.
- **Luki są normalnym stanem danych** (epizody, awarie, zaniki zasilania): nie ma interpolacji, a brak próbek widać w `*_n` i `coverage`.
- Tryb czasu rzeczywistego (`materialized_only = false`): zapytania widzą też bieżące, jeszcze niezmaterializowane wiaderko.
- Wiaderka są w UTC; tylko widok dobowy używa doby lokalnej `Europe/Warsaw` (stała do etapu 4).

| Obiekt | Odświeżanie (okno / opóźnienie końca / okres) | Kompresja | Retencja |
| --- | --- | --- | --- |
| `measurements` | n/d | po 1 dobie | 90 dni |
| `energy_1m` | 7 dni / 1 min / 1 min | po 14 dniach (`segmentby = device_id`) | 1 rok |
| `energy_1h` | 30 dni / 1 h / 15 min | po 60 dniach (`segmentby = device_id`) | bez limitu |

Okna odświeżania są krótsze niż retencja surowych danych (90 dni), więc usunięcie starych surowych kawałków nie kasuje
zmaterializowanych wiaderek; kompresja następuje po oknie odświeżania. Dane wpisane z odległej przeszłości (starsze niż okno)
polityka nie odświeży: po wypełnieniu historii (etap 3) trzeba ręcznie wywołać `CALL refresh_continuous_aggregate('energy_1m', NULL, NULL)`,
a potem to samo dla `energy_1h` (opis w `docs/ops/jumo-ipc-setup.md`).

### Agregaty jakości i energii biernej (migracja `007_energy_ext_aggregates.sql`, E2-PLC2)

Osobne agregaty obok `energy_1m` i `energy_1h` (te bez zmian), żeby nie usuwać i nie odtwarzać istniejących: agregatu ciągłego nie da się rozszerzyć o kolumny.

| Agregat | Okno | Zawartość |
| --- | --- | --- |
| `energy_ext_1m` | 1 min | z `measurements`: dla `thd_voltage`, `thd_current`, `phase_angle`, `meter_temperature` liczność `*_n`, suma `*_sum`, `*_min`, `*_max`; `phase_cos_sum` (suma cos kąta, daje dokładną średnią cos φ); `run_time_first/_last/_min/_max`; stany liczników energii biernej `counter_pos_*` (n2, Q > 0) i `counter_neg_*` (n4, Q < 0); **całka mocy biernej** `reactive_power_n`, `reactive_pos_sum`, `reactive_neg_sum` (suma Q z podziałem na znak, od początku zapisu `reactive_power`, także sprzed mapy v2) |
| `energy_ext_1h` | 1 h | te same kolumny, złożone z minutowych (hierarchia); `first`/`last` z `FILTER` po kolumnie nie-NULL, bo `first()` bierze najwcześniejszy wiersz także wtedy, gdy ma NULL |

Polityki jak dla `energy_1m`/`energy_1h` (odświeżanie 7 dni/1 min i 30 dni/15 min, kompresja po 14 i 60 dniach, retencja 1 rok i bez limitu, czas rzeczywisty).
**`energy_1h` odtworzony migracją 009 (25.11.2026):** `first(import_first, bucket)` i `last(...)` (oraz dla `export_*`) mają teraz `FILTER (WHERE kolumna IS NOT NULL)`; w migracji 002 godzina, w której pierwsza lub ostatnia minuta nie miała energii (np. cała minuta błędu licznika), dostawała `import_first/last` = NULL. Widoki `energy_1h_calc` i `energy_daily_check` odtworzone z identycznymi definicjami.
Dla okresu sprzed mapy v2 kolumny metryk v2 to NULL (liczności 0): **brak danych, nie zero**. Widok `reactive_1h_calc` (migracja `008`): przyrost liczników n2 i n4 względem poprzedniego
wiaderka z odczytem (`LAG`, reset, `pos_gap_before` i `neg_gap_before`), całka mocy biernej w varh (`reactive_pos_integral_varh`, `reactive_neg_integral_varh` jako moduł),
`coverage`, `bucket_complete`, rozdzielczość `resolution_varh` (100 varh) i okres próbkowania z `devices.meta`. Nazwy n2 i n4 wg znaku mocy biernej, nie kierunku przepływu (`docs/modbus-map.md`).
**Ostrzeżenie:** na roku danych `reactive_1h_calc` trwa ok. 20 s (limit `app_reader` 10 s; przyczyny nie ustalono), więc **nie używać go na długich zakresach**: panele Grafany czytają `energy_ext_1h` wprost i liczą przyrost z zapasem 3 dni (jak K6-U4). Widok zostaje dla analityki po wyjaśnieniu.

### Widoki pochodne energii (migracja `003_energy_views.sql`)

`energy_1m_calc` i `energy_1h_calc` (urządzenie x wiaderko), `energy_daily_check` (urządzenie x doba lokalna).
Okres próbkowania i rozdzielczość licznika **nie są stałymi w SQL**: pochodzą z `devices.meta` (`poll_interval_s`, `energy_resolution_wh`;
ingest synchronizuje je z `config/devices.yaml`). Brak wartości daje NULL, a nie domysł.

| Kolumna | Znaczenie |
| --- | --- |
| `*_avg` | suma / liczność (NULL przy zerowej liczności) |
| `energy_integral_wh` | `active_power_sum x poll_interval_s / 3600`: energia z obecnych próbek, bez interpolacji przez luki |
| `coverage` | `LEAST(1, active_power_n x poll_interval_s / długość_okna_s)`: jaka część okna ma pomiar mocy |
| `bucket_complete` | okno już się zakończyło (`bucket + okno <= now()`); **bieżące wiaderko ma `coverage` < 1 z natury**, więc ta kolumna odróżnia „trwa” od „brak danych” |
| `energy_import_delta_wh`, `energy_export_delta_wh` | przyrost licznika względem poprzedniego wiaderka **z odczytem licznika** (`LAG`, bez toolkitu); przy resecie (`*_last` mniejsze od poprzedniego) przyrost = `*_last` i flaga `import_reset` / `export_reset`; pierwsze wiaderko: `last - first` |
| `gap_before` | odstęp od poprzedniego wiaderka z odczytem licznika większy niż okno: przyrost obejmuje czas, którego całka nie widzi |
| `meter_error_seconds`, `meter_error_share` | sekundy ze `meter_status` ≠ 0 i ich udział w sekundach ze statusem |

**Brak pokrycia nie jest błędem licznika.** `meter_error_seconds` liczy tylko sekundy, w których licznik **opublikował** status ≠ 0.
Gdy PLC jest niedostępny (`link_status` ≠ 0), licznik nie publikuje statusu, więc te sekundy nie są błędem licznika, tylko spadkiem `coverage`.
Awarię łącza z PLC widać w metryce `link_status` urządzenia `plc-01`.

`energy_daily_check`: porównanie całki mocy z przyrostem licznika wzorcowego w dobie lokalnej `Europe/Warsaw`
(`integral_wh`, `coverage` z uwzględnieniem długości doby przy zmianie czasu: 23 lub 25 godzin, `counter_delta_wh`,
`integral_extrapolated_wh` = całka / pokrycie, NULL przy pokryciu poniżej 0,5, `diff_wh`, `day_complete`, `gap_before_count`).
Licznik zmienia stan co `resolution_wh` (100 Wh), a obciążenie ok. 7 W to ok. 170 Wh na dobę, więc przyrost dobowy to 1-2 kroki:
pierwszą miarą zgodności jest **`within_resolution`** (|`diff_wh`| nie większa niż jeden krok licznika), a **`deviation_pct`**
jest podawana tylko gdy przyrost ma co najmniej 5 kroków licznika (inaczej NULL). Rejestry o większej rozdzielczości (30462-30485)
zostają na etap 4, przed wyborem źródła kosztów.

Wydajność widoków (`LAG` nad całym agregatem): wynik `EXPLAIN ANALYZE` na prawdziwych danych jest w raporcie `docs/handoff/e2-k6-report.md`.

### `data_windows` (migracja `004_data_windows.sql`, k7)

Okna testów i przerw w danych: adnotacje na wykresach Grafany i wykluczenia w analityce.

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | BIGSERIAL PK | |
| start_time, end_time | TIMESTAMPTZ | granice okna (`end_time >= start_time`) |
| kind | TEXT | rodzaj, małe litery, cyfry i `_` (np. `power_outage`, `rs485_break`, `deploy`, `calm_window`) |
| description | TEXT | opis po polsku |
| exclude_from_analytics | BOOLEAN | `TRUE` dla przerw i zakłóceń; `FALSE` tylko dla okna referencyjnego (`calm_window`), które nie jest przerwą |

Tabela jest tylko do odczytu dla aplikacji (`app_reader` ma `SELECT`, `app_writer` nic); wpisy dodaje wyłącznie `migrate`: każde nowe okno to nowa migracja z `INSERT`.

### `machine_states`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| device_id | TEXT | |
| state | TEXT | `off` / `idle` / `run` |
| start_time | TIMESTAMPTZ | |
| end_time | TIMESTAMPTZ NULL | NULL = stan trwa |
| threshold_w | DOUBLE PRECISION | próg użyty do klasyfikacji |

### `anomaly_scores`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| time | TIMESTAMPTZ | koniec okna 10-minutowego |
| device_id | TEXT | |
| model_version | TEXT | |
| score | DOUBLE PRECISION | wynik Isolation Forest |
| is_anomaly | BOOLEAN | |
| features | JSONB | cechy okna (do objaśnień) |

### `events`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | BIGSERIAL PK | |
| time | TIMESTAMPTZ | |
| device_id | TEXT | |
| kind | TEXT | `threshold`, `anomaly`, `trend`, `comm_loss`, … |
| severity | TEXT | `info` / `warning` / `alarm` |
| message | TEXT | po polsku |
| details | JSONB | np. szacowane dni do progu z przedziałem |
| acknowledged_at | TIMESTAMPTZ NULL | |

### `tariffs`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | SERIAL PK | |
| name | TEXT | |
| valid_from | DATE | |
| valid_to | DATE NULL | |
| schedule | JSONB | strefy godzinowe i ceny zł/kWh |

### `chat_log`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | BIGSERIAL PK | |
| time | TIMESTAMPTZ | |
| question | TEXT | |
| provider | TEXT | `ollama` / nazwa dostawcy chmurowego |
| model | TEXT | |
| path | TEXT | `tool` / `sql` |
| tool_or_sql | TEXT | użyte narzędzie z parametrami albo SQL |
| answer | TEXT | |
| confidence | TEXT | `high` / `medium` |
| sent_to_cloud | BOOLEAN | wymagane przez zasadę twardą nr 5 |
| latency_ms | INTEGER | |

## Ustalenia z etapu 2

- Energia jest zapisywana jako stan licznika (Wh, mantysa x 10^wykładnik); przyrosty liczą widoki (`LAG`), a nie collector.
- Retencja agregatów: `energy_1h` bez limitu, `energy_1m` 1 rok (migracja 002).
- Zmierzony rozmiar po dobie pracy i rozmiary agregatów: raport `docs/handoff/e2-k6-report.md`.
