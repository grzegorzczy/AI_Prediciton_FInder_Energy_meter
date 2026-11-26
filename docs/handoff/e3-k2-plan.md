# E3-k2 – plan kroku: modele symulatora i ich parametry

Data: 2026-11-26. Podstawa: `e3-k0-plan.md` (sekcja 3 i k2), `e3-k0-review.md`, `e3-k1-report-review.md` (K1-U1, K1-U2), parametry zaakceptowane przez Grzegorza (`e3-decyzje-szkic.md`, „Po review planu e3-k0”).
**Sam plan, do review.** W k2 nie ma sieci, MQTT, kontenera ani wdrożenia: tylko czysty Python i testy jednostkowe. Produkcja nie zmienia się (`~/ai-predykcja` na `c299eaa`); testy z `~/ai-predykcja-dev` w `aip-test`.
Plik setupu PLC po PLC-2 zacommitowany w `e61b2fd`, review k1 w `67ef49f`.

## Cel kroku

Biblioteka `services/simulator/src/simulator/`, która dla dowolnej chwili `t` (UTC, pełna sekunda) zwraca wartości wszystkich metryk pięciu urządzeń sim – **deterministycznie**: `f(t, ziarno, config)`, bez stanu między próbkami (zasada z K0). Z tego samego kodu skorzystają tryb na żywo (k3) i historia (k5). Parametry modeli trafiają do sekcji `simulator:` w `config/devices.yaml` i są walidowane przy wczytaniu.

## Uwagi z review k1

- **K1-U1:** nagłówek `config/devices.yaml`, linia 2: „(kontrakt, wersja 1)” → „(kontrakt, wersja 2 od 25.11.2026; collector akceptuje v1 i v2, `plc.map_versions`)”. Tylko komentarz; testy pliku bez zmian.
- **K1-U2:** `t_zero` w configu zostaje opcjonalne (`null` do k7), ale biblioteka **nie podstawia „teraz”**. Loader zwraca `t_zero: datetime | None`; każda funkcja, która potrzebuje postępu degradacji pompy lub kotwicy licznika energii, woła `config.require_t_zero()`, a ta przy `null` zgłasza `ConfigError("simulator.t_zero nie jest ustawione: tryb na żywo i historia nie wystartują; datę ustala wdrożenie (k7)")`. W k3 tryb na żywo zakończy się z tym komunikatem i kodem 2 (jak ingest przy błędzie configu), zamiast liczyć degradację od 0 % po każdym restarcie. Format: ISO 8601 z jawną strefą (np. `2026-12-01T00:00:00Z`); data bez strefy = błąd. Testy: `null` → błąd z tym komunikatem; data bez strefy → błąd; poprawna data → postęp x = 0,70 dokładnie w `t_zero`.

## Parametry w `config/devices.yaml` (sekcja `simulator:`)

Wartości z planu k0 (sekcja 3.2–3.3), zaakceptowane przez Grzegorza; to **parametry symulacji, nie fakty o maszynach**.
```yaml
simulator:
  site: zaklad1
  line: linia2
  poll_interval_s: 1.0
  t_zero: null                    # K1-U2: ustawiane w k7; bez niego live/historia nie startują
  seed: 20261126                  # ziarno szumu; zmiana = inne (ale powtarzalne) dane
  calendar:                       # S2; czas lokalny ze zmianą czasu letniego
    timezone: Europe/Warsaw
    shifts:                       # dni ISO: 1 = poniedziałek … 7 = niedziela
      - { days: [1, 2, 3, 4, 5], start: "06:00", end: "22:00" }
      - { days: [6], start: "06:00", end: "14:00" }
    breaks:                       # przerwy planowe w czasie zmian (bieg jałowy maszyn zmianowych)
      - { start: "10:00", minutes: 15 }
      - { start: "13:30", minutes: 30 }
      - { start: "18:00", minutes: 15 }
    holidays: []                  # daty YYYY-MM-DD bez pracy
  ambient: { mean_c: 20, swing_c: 3, warmest_hour: 15 }     # temperatura otoczenia (chłodnia, łożysko pompy)
  electrical: { voltage_v: 230, voltage_slow_v: 2.0, voltage_noise_v: 0.3 }
  history: { meter_days: 14, pump_step_s: 60 }               # K0-D1 (Grzegorz): liczniki 1 s × 14 dni, pompa 1 min; używa k5
  degradation: { days_total: 120, history_progress: 0.70, shape_k: 3.0 }   # K0-D2: historia pompy 84 dni
  devices:
    - id: sim_pasteryzator  # … pola z k1 (name, kind, source, phases, rated_kw, energy_resolution_wh) bez zmian, plus:
      energy_start_wh: 1250000
      model: { type: thermostat, schedule: shifts, cycle_s: 60, on_fraction: 0.65, p_on_kw: 18, p_idle_kw: 2.5,
               p_off_kw: 0.15, pf_run: 0.98, pf_idle: 0.90, pf_off: 0.90 }
    - id: sim_chlodnia
      energy_start_wh: 2480000
      model: { type: compressor, schedule: always, on_min: 14, off_min: 9, ambient_gain: 0.3, p_on_kw: 9.5,
               p_off_kw: 0.4, pf_run: 0.84, pf_off: 0.60 }
    - id: sim_mieszalnik
      energy_start_wh: 610000
      model: { type: batch, schedule: shifts, batch_min: 8, mix_min: 6, ramp_s: 20, p_mix_kw: 5.8, p_pause_kw: 0.3,
               p_off_kw: 0.05, pf_run: 0.80, pf_idle: 0.45, pf_off: 0.45 }
    - id: sim_pakowaczka
      energy_start_wh: 390000
      model: { type: continuous, schedule: shifts, p_run_kw: 3.2, swing: 0.15, p_idle_kw: 0.9, p_off_kw: 0.12,
               pf_run: 0.78, pf_idle: 0.50, pf_off: 0.50 }
    - id: sim_pump_p101
      model: { type: pump, schedule: shifts, speed_rpm: 2950, flow_m3_h: 40, current_a: 21,
               vibration_good_mm_s: 1.1, vibration_end_mm_s: 7.0, bearing_good_c: 52, bearing_end_c: 78,
               warmup_tau_min: 25, cooldown_tau_min: 40 }
```
- `energy_start_wh`: stan licznika w chwili kotwicy `t_zero − history.meter_days` (dowolny, „licznik nie od zera”). Proponowane wartości są parametrem do akceptacji.
- `current_a: 21` – prąd znamionowy pompy wyliczony z 11 kW przy 400 V, PF ok. 0,86, sprawności ok. 0,9 (≈ 20,5 A); parametr symulacji, nie dane tabliczki.
- Ingest czyta z tych wpisów tylko pola z k1; nowe klucze (`model`, `energy_start_wh`, sekcje kalendarza) ignoruje – sprawdzą to istniejące testy k1 i jeden nowy.

## Modele (czyste funkcje)

| Moduł | Zawartość |
| --- | --- |
| `config.py` | wczytanie i walidacja sekcji `simulator` (typy, zakresy, wymagane pola na typ modelu, `t_zero`, `require_t_zero()`); własny parser jak w ingeście (decyzja K4-a: parsery usług niezależne, zgodność pilnują testy) |
| `calendar.py` | stan w chwili `t`: `off` / `work` / `break` (przerwa planowa) z `zoneinfo` (czas letni), święta; chwila ostatniego startu i zatrzymania pracy (dla nagrzewania pompy) bez stanu |
| `noise.py` | szum jako funkcja skrótu `blake2b(ziarno, urządzenie, metryka, sekunda)` → U(0,1); rozkład normalny (Box–Muller z dwóch takich liczb); wolne wahania = suma trzech sinusoid z fazami z ziarna; **bez wbudowanego `hash()`** (zależy od procesu) |
| `meters.py` | moc czynna z typu modelu i stanu kalendarza: `thermostat` (cykl dwustawny, udział włączenia), `compressor` (cykl 24/7, czas pracy rośnie z temperaturą otoczenia), `batch` (partie z rozbiegiem), `continuous` (praca z wahaniami); w przerwach bieg jałowy, poza zmianami postój; elektryka: U = U_nom + wolne wahania + szum; S = P / PF; Q = √(S² − P²) (Q > 0, odbiorniki indukcyjne); I = S / (3 U) (trójfazowy, U-1) |
| `energy.py` | licznik `energy_import_wh` = `energy_start_wh` + Σ P(s) · 1 s / 3600 od kotwicy, kwantowany w dół do 100 Wh; pamięć sum dobowych w procesie (memo), więc start trybu na żywo po N dniach liczy N dób raz (koszt mierzony w teście) |
| `pump.py` | postęp `x(t)` i krzywa `f(x) = (e^{kx} − 1)/(e^{k} − 1)`; drgania RMS, temperatura łożyska (rośnie z drganiami, nagrzewanie po starcie i stygnięcie po zatrzymaniu z kalendarza, otoczenie dobowe), prąd, przepływ, obroty; poza zmianą: obroty, przepływ, prąd = 0, drgania tła ok. 0,1 mm/s |
| `samples.py` | jedno wejście dla k3/k5: `samples_at(t)` → lista `(device_id, metric, value, unit)` dla 29 metryk (4 × 6 + 5), jednostki: `W`, `var`, `V`, `A`, `""` (PF), `Wh`; `mm/s`, `°C`, `A`, `m³/h`, `obr/min` (nazwy metryk: `vibration_rms`, `bearing_temperature`, `motor_current`, `flow`, `speed`) |

Zakresy wyjść (sprawdzane testem): P ≥ 0, PF w (0, 1], U 220–240 V, brak NaN/Inf, wartości zaokrąglone do sensownej liczby cyfr (P i Q do 1 W/var, U do 0,1 V, I do 0,001 A, PF do 0,001; drgania 0,01 mm/s, temperatura 0,1 °C).

## Testy (`tests/simulator/`, bez sieci; `PYTHONPATH` w `docker-compose.test.yml` dostaje `services/simulator/src`)

1. **Config:** prawdziwy plik wczytuje się; 5 urządzeń z modelami; błędy: nieznany `type`, brak wymaganego parametru typu, wartości ujemne/zerowe/NaN, `on_fraction` poza (0, 1), `mix_min ≥ batch_min`, zła godzina zmiany, dzień spoza 1–7, `t_zero` bez strefy; **K1-U2**: `t_zero: null` → `require_t_zero()` zgłasza błąd z komunikatem, nic nie podstawia „teraz”; ingest nadal wczytuje plik (te same urządzenia i meta co po k1).
2. **Determinizm:** ta sama chwila → identyczne wartości przy innej kolejności wywołań i w nowym procesie (`subprocess`); inne ziarno → inny szum; `samples_at(t)` nie zależy od zegara systemowego.
3. **Kalendarz:** poniedziałek 05:59:59 `off`, 06:00:00 `work`, 21:59:59 `work`, 22:00:00 `off`; sobota 13:59:59 / 14:00:00; niedziela cały dzień `off`; przerwy; święto; **25.10.2026 (doba 25 h) i 28.03.2027 (doba 23 h)** – godziny zmian w czasie lokalnym, poprawne przejścia UTC.
4. **Liczniki:** moc w stanach `off`/`break`/`work` zgodna z parametrami; średni udział włączenia pasteryzatora w zmianie 0,65 ± 0,02; chłodnia pracuje także w niedzielę i dłużej po południu; S ≥ P, Q ≥ 0, PF = P/S, I = S/(3U); **energia dobowa** doby roboczej w przedziałach: pasteryzator 170–210 kWh, chłodnia 120–160, mieszalnik 50–80, pakowaczka 35–55 (wartości z modelu, opisane jako szacunki k0).
5. **Licznik energii:** monotoniczny, krok 100 Wh, przyrost w dobie zgodny z całką mocy w granicach 100 Wh; ciągłość na styku dób; start od `energy_start_wh` w kotwicy.
6. **Pompa:** x(t_zero) = 0,70; wartości kontrolne `f` (0,059 / 0,182 / 0,376 / 0,619 / 1) i drgania 1,45 / 2,18 / 3,32 / 4,75 / 7,00 mm/s (średnia godzinowa w pracy ± szum); średnie dobowe drgań rosną; temperatura w dniu 84 ok. 61,8 °C ± 1,5 po nagrzaniu; poza zmianą obroty/przepływ/prąd = 0; po starcie temperatura rośnie, po zatrzymaniu spada.
7. **Wydajność:** `samples_at` dla jednej doby co 1 s dla 4 liczników (345 600 wywołań) i doby pompy co 1 min – czas w raporcie; start licznika energii po 14 dniach od kotwicy < 30 s (cel; jeśli nie, zmiana `energy.py` przed k3).
8. **Reguła 3:** w kodzie `services/simulator` brak id urządzeń, mocy, nazw linii i zakładów (test jak `test_no_hardcoding` ingestu).

Po k2: pełny zestaw (`tests/run-tests.sh` w worktree), agent `reviewer`, raport `e3-k2-report.md`.

## Lista plików

Nowe: `services/simulator/requirements.txt` (PyYAML, wersja jak w testach), `services/simulator/src/simulator/{__init__,config,calendar,noise,meters,energy,pump,samples}.py`, `tests/simulator/{conftest,test_config,test_determinism,test_calendar,test_meters,test_energy,test_pump,test_perf_k2,test_no_hardcoding}.py`, `docs/handoff/e3-k2-report.md`.
Zmieniane: `config/devices.yaml` (parametry modeli, K1-U1), `docker-compose.test.yml` (tylko `PYTHONPATH` usługi `pytest`), `docs/data-model.md` (nazwy i jednostki metryk sim, krótko), `tests/ingest/test_ingest_config_loader.py` (1 test: nowe klucze nie zmieniają urządzeń ingestu).
Bez zmian: ingest, collector, compose produkcyjny, Mosquitto, baza, Grafana. Dockerfile i usługa w compose – k3.

## Ryzyka

| Ryzyko | Postępowanie |
| --- | --- |
| Czysty Python za wolny dla historii (14 dób × 4 liczniki co 1 s ≈ 4,8 mln wywołań) | pomiar w teście 7; w razie potrzeby uproszczenie szumu (np. jeden skrót na sekundę dla wszystkich metryk urządzenia) przed k5 |
| Start licznika energii długo po `t_zero` (sumowanie wszystkich sekund od kotwicy) | memo dób; jeśli > 30 s – kotwica przesuwana z krokiem dobowym w configu (opis w raporcie) |
| Wartości wyglądają jak dane maszyn | opis „parametr symulacji” w YAML i w `docs/data-model.md`; progi alarmowe tylko w etapie 5 |
| Różnice zmiennoprzecinkowe między maszynami | ta sama wersja Pythona w obrazie; baza i tak przyjmuje pierwszy zapis (`ON CONFLICT DO NOTHING`) |
| Czas letni | testy 25.10.2026 i 28.03.2027 |

## Czego potrzebuję

1. Akceptacja parametrów, które dochodzą w k2 i nie były wprost w K0: godziny przerw (10:00/15 min, 13:30/30 min, 18:00/15 min), otoczenie 20 ± 3 °C, `energy_start_wh`, `current_a: 21`, stałe nagrzewania/stygnięcia pompy (25/40 min).
2. Zgoda na przedziały energii dobowej z testu 4 jako kryterium modelu.

Plan e3-k2 gotowy do przeglądu.
