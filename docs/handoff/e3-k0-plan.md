# E3-k0 – plan etapu 3 (Symulator: 4 wirtualne liczniki i pompa P-101)

Data: 2026-11-25. **Sam plan, do review architekta; niczego nie zaimplementowano.** Powstał wyłącznie na laptopie: żadnego kodu symulatora, testów ani obciążeń na IPC, żadnych zmian w compose, bazie i Grafanie na produkcji (zakazy do zamknięcia etapu 2). Etap 3 startuje dopiero po akceptacji `docs/stages/etap-2.md` przez Grzegorza.
Źródła: `docs/handoff/e3-decyzje-szkic.md`, `docs/plan.md`, `CLAUDE.md`, `.claude/agents/data-platform.md`, a także kod, który symulator dotyka (ingest, collector, migracje 002/003, `devices.yaml`, ACL Mosquitto, generator Grafany).

## 0. Czego nie znalazłem i jak to traktuję

Polecenie mówi o sekcji „Decyzje Grzegorza” w `e3-decyzje-szkic.md`. **W pliku na dysku (zapisany 14:32, ten sam co w repo) takiej sekcji nie ma**: są decyzje S1–S11 jako propozycje architekta i cztery pytania otwarte do Grzegorza bez odpowiedzi. Zgodnie z regułą 7 nie zgaduję: w całym planie **S1, S2, S4, S7, S8 i pytania 1–4 traktuję jako propozycje architekta do potwierdzenia** i oznaczam je „[do potwierdzenia]”. Jeśli decyzje Grzegorza istnieją w innym pliku, podaj ścieżkę – poprawię plan.
Dwie rzeczy w samych propozycjach są ze sobą sprzeczne albo niezgodne z kodem. Rozwinąłem je w sekcji 2 jako **K0-D1 (rozdzielczość historii a widoki energii)** i **K0-D2 (S5 a S6)**; bez rozstrzygnięcia nie da się poprawnie zaplanować kroków historii.

## 1. Założenia i co wynika z kodu (fakty z repo, nie zgadywanie)

1. **Ingest** odrzuca wiadomość, gdy `source` w ładunku ≠ `source` urządzenia z configu, gdy `site/line` z tematu ≠ globalne `site/line` configu (jedna para na cały zakład: `validate.py`, `config.py`), gdy `ts` jest starszy niż 400 dni lub ponad 300 s w przyszłość. Urządzenia spoza configu są logowane, nie zapisywane; urządzenia, których nie ma w configu, ingest oznacza jako wyłączone przy synchronizacji.
2. **Collector** czyta wszystkie wpisy `devices:` jako urządzenia Modbus (wymaga `profile` i `block_base` dla każdego). **Wirtualnych liczników nie można dopisać do `devices:`** bez zmiany collectora: zaplanowałem osobną sekcję `simulator:` w `config/devices.yaml` (collector jej nie czyta), a ingest ją doczytuje.
3. **Mosquitto**: konto `collector` może pisać `+/+/+/+`, konto `ingest` tylko czytać; ACL generuje `entrypoint.sh` z `.env`. Symulator potrzebuje własnego konta (nowe zmienne w `.env` dopisuje Grzegorz) i restartu brokera. Kolejka sesji ingestu: `max_queued_messages` 80 000, `max_queued_bytes` 20 MB; **przy przepełnieniu broker gubi najnowsze wiadomości bez błędu po stronie nadawcy**.
4. **Widoki energii** (migracja 002/003) działają dla każdego `device_id`, który ma metryki `active_power`, `energy_import_wh` itd., ale czas próbkowania biorą z `devices.meta.poll_interval_s`: energia = suma mocy × `poll_interval_s` / 3600, pokrycie = liczba próbek × `poll_interval_s` / 60. **Zakładają jednakowy odstęp próbek.**
5. **Zmienna `$device`** we wszystkich pięciu dashboardach to `SELECT … FROM devices WHERE kind = 'energy_meter' AND enabled`: wirtualne liczniki pojawią się w niej automatycznie (S9 tego chce), ale paneli diagnostycznych (`meter_status`, `link_status`) dla nich nie będzie.
6. Agregat `pump_1m` jest w `docs/data-model.md` oznaczony „planowany w etapie 4”, a w `CLAUDE.md` i w szkicu etapu 3 wśród tego, co powstaje; rozstrzygam to jako **K0-D4**.
7. Zmierzone wartości, na których liczę wpływ: PLC daje 20 wierszy/s; ingest w teście 1 363 wiadomości/s (wartość optymistyczna: tmpfs, `fsync=off`); niekompresowany wiersz ok. 180 B z indeksami (25.11: 240 MB na 1,31 mln wierszy); kompresję i rozmiar po kompresji zmierzy część B k8; kontenery: collector 38,8 MiB, ingest 39 MiB (zmierzone).

## 2. Decyzje, bez których nie zacznę kodować (do architekta i Grzegorza)

### K0-D1 (najważniejsza) – historia 1 min przez MQTT psuje energię i pokrycie

S7 proponuje historię z rozdzielczością 1 minuty. Widoki energii (pkt 4 wyżej) liczą energię jako suma mocy × `poll_interval_s` / 3600. Przy jednej próbce na minutę i `poll_interval_s = 1` energia wyjdzie **60 razy za mała, a pokrycie 1,7 % zamiast 100 %**; ustawienie `poll_interval_s = 60` psuje dane na żywo (1 s) tego samego urządzenia. Etap 4 (koszt doby, zmiany, pobór poza pracą) opiera się na tych widokach. Opcje:

| Opcja | Co | Wiersze historii | Czas wgrania (500 / 1000 msg/s) | Skutek |
| --- | --- | --- | --- | --- |
| **A (rekomenduję)** | liczniki: historia **co 1 s przez K dni** (domyślnie K = 7, parametr w configu); pompa: historia **co 1 min przez całe 84 dni** (jej agregat `pump_1m` nie zależy od odstępu próbek) | liczniki 7 × 86 400 × 24 = 14 515 200; pompa 84 × 1 440 × 5 = 604 800; razem ok. 15,1 mln | 8,4 h / 4,2 h | energia i pokrycie poprawne dla ostatnich K dni; dla starszych dni liczniki bez danych (pokrycie 0, nie błąd) |
| B | całość co 1 min, widoki energii uczone odstępu (np. `poll_interval_s` zależne od czasu) | ok. 5,0 mln (29 metryk × 172 800 min) | 2,8 h / 1,4 h | **zmiana migracji 002/003 i dashboardów**: duży zakres poza etapem 3, ryzyko dla danych prawdziwych |
| C | całość co 1 s | ok. 500 mln (29 × 120 d × 86 400) | 11,6 doby / 5,8 doby | nierealne |

Liczba 7 mln z szkicu przy S3 (6 metryk licznika + 5 pompy = 29 metryk) wynosi dla historii 1 min 5,0 mln (7 mln wymagałoby 40 metryk). Decyzja: A (z jakim K: 7, 14?) / B / inna.

### K0-D2 – S5 i S6 są w szkicu niespójne

S5: „120 dni od stanu dobrego do przekroczenia progu”. S6: „historia 120 dni kończy się teraz na ok. 70 % drogi do alarmu”. Jedno i drugie naraz oznacza drogę 170 dni. Alternatywa z S8 („historia tylko 85 dni”) rozwiązuje wszystko naraz. **Rekomenduję:** cała degradacja trwa D = **120 dni**; historia = 70 % z tego = **84 dni**; na żywo zostaje 36 dni do końca modelu. Skutki: historia (84 dni) mieści się w retencji 90 dni, więc **S8 przestaje być konfliktem** (surowe dane nie są kasowane do czasu, aż „teraz” przesunie się o 6 dni; potem surowe dane pompy starzeją się normalnie, a pełna krzywa żyje w `pump_1m` z retencją roku). Do potwierdzenia.

### K0-D3 – wirtualne liczniki w osobnej linii (pytanie 4)

Rekomenduję `zaklad1/linia2` dla symulatora: wtedy ACL Mosquitto może ograniczyć konto symulatora do `zaklad1/linia2/+/+` (symulator nie zapisze nic w temacie prawdziwego licznika ani PLC), a dane sim są odróżnialne po linii i po `source`. Cena: ingest musi znać `site/line` **na urządzenie** (dziś globalne): mała zmiana `config.py` i `validate.py` z testami. W tej samej linii (`linia1`) ACL nie da się zawęzić (wildcard `+` obejmuje cały poziom), a obronę zostawiamy tylko warunkowi `source` ingestu.

### K0-D4 – kiedy powstaje `pump_1m`

Rekomenduję **w etapie 3** (migracja 012, jak `energy_1m`): bez niego dashboard „Pompa P-101” liczyłby na surowych danych, a krzywa 84 dni na 1-minutowych punktach z agregatu jest tym, czego potrzebuje etap 5. Wymaga to aktualizacji `docs/data-model.md` (dziś: etap 4).

### Pozostałe do potwierdzenia (mniejsze)

- **K0-D5 – tryb przyspieszony.** Znaczniki czasu nie mogą wyjść poza `now + 300 s` (ingest je odrzuci), więc „przyspieszony” może przyspieszać tylko **stan fizyczny** (postęp degradacji x rośnie K razy szybciej niż zegar), a nie czas. To zaburza ciągłość serii, dlatego proponuję go **tylko dla osobnego urządzenia demo** (np. `sim_pump_demo`, domyślnie wyłączonego), nie dla P-101. Zgoda?
- **K0-D6 – `meter_status` dla wirtualnych liczników.** S3 (zestaw skrócony) go pomija; konsekwencja: osie „Stan licznika” i „Łącze z PLC” w „Stan i diagnostyka” dla urządzeń sim będą puste. Rekomenduję zostawić tak, z jednym zdaniem w opisie dashboardu (nie dokładam 4 wierszy/s).
- **K0-D7 – znaczenie „Flota 5 urządzeń” i „stan” w S9.** Interpretuję: „Flota” = 5 liczników energii (1 prawdziwy Finder + 4 wirtualne) ze źródłem real/sim; pompa ma osobny dashboard. „Stan” we „Flocie” to świeżość danych (aktualne / brak danych), **nie** off/idle/run (te klasyfikuje etap 4). Zgoda?
- **K0-D8 – rozdzielczość licznika wirtualnego.** Proponuję jak Finder: 100 Wh (`energy_resolution_wh: 100`, stan kwantowany w dół do 100 Wh), żeby widoki zgodności działały tak samo. Alternatywa: 1 Wh.
- **K0-D9 – pompa a energia.** Pompa nie publikuje mocy (zgodnie z listą z planu: wibracje RMS, temperatura łożyska, prąd silnika, przepływ, obroty), więc nie wchodzi do rachunku energii etapu 4. Czy silnik pompy ma być też liczony jako odbiornik (dodatkowa metryka `active_power`)?

## 3. Model symulatora (jedna zasada projektowa)

**Każda wartość jest czystą, deterministyczną funkcją `f(czas, ziarno, konfiguracja)`, bez stanu między próbkami.** Tryb na żywo i historia używają tego samego kodu; ponowne uruchomienie symulatora, przerwa lub drugi przebieg historii daje identyczne wartości (a ponieważ baza ma `UNIQUE (device_id, metric, time)` i ingest `ON CONFLICT DO NOTHING`, powtórka uzupełnia tylko luki, nie tworzy duplikatów). Szum to funkcja skrótu (ziarno, urządzenie, metryka, sekunda), nie generator z pamięcią. Sprzężenia „z opóźnieniem” (nagrzewanie łożyska) realizuję krzywą od momentu startu pracy wynikającego z kalendarza, nie filtrem ze stanem.
Znaczniki czasu na pełnych sekundach UTC (ms = 000), ładunek `{ts, value, unit, source: "sim"}`, temat `zaklad1/linia2/<id>/<metryka>` [K0-D3].

### 3.1 Kalendarz (S2) [do potwierdzenia]
Czas lokalny `Europe/Warsaw` (`zoneinfo`, uwzględnia czas letni): dwie zmiany pon–pt 6:00–22:00, sobota 6:00–14:00, niedziela postój, chłodzenie 24/7; lista świąt w configu (domyślnie pusta); przerwy w pracy pakowaczki (dwie po 15 min na zmianę, parametr). Historia 84 dni od przełomu listopada obejmuje **zmianę czasu 25.10.2026 (doba 25-godzinna)**: osobny test.

### 3.2 Cztery wirtualne liczniki (S1, S3) – propozycje parametrów [do potwierdzenia przez Grzegorza]
To parametry symulacji (nie fakty sprzętowe); wszystkie w `config/devices.yaml`. Metryki: `active_power` (W), `reactive_power` (var), `voltage` (V), `current` (A), `power_factor`, `energy_import_wh` (Wh) = 6 wierszy/s na licznik. Napięcie fazowe ok. 230 V ± wolne wahania i szum (jak Finder: U1), prąd I1 = S / (3 U) przy obciążeniu symetrycznym, Q = P·tan(arccos PF) (Q > 0 dla odbiorników indukcyjnych), energia = całka mocy od `energy.start` w configu, kwantowana do 100 Wh.

| Id (propozycja) | Maszyna | Moc znamionowa | Profil pracy | P praca / jałowy / postój | PF praca / jałowy |
| --- | --- | --- | --- | --- | --- |
| `sim_pasteryzator` | piec / pasteryzator | 18 kW | regulacja dwustawna w cyklu 60 s (udział włączenia ok. 0,65) w czasie zmian; w przerwach podtrzymanie | ok. 11,7 kW średnio / 2,5 kW / 0,15 kW | 0,98 / 0,90 |
| `sim_chlodnia` | agregat chłodniczy | 11 kW | załącz/wyłącz 24/7: sprężarka 14 min, przerwa 9 min, długość cyklu zależna od temperatury otoczenia (dobowa sinusoida) | 9,5 kW w cyklu / – / 0,4 kW (wentylatory, sterownik) | 0,84 / 0,60 |
| `sim_mieszalnik` | mieszalnik | 7,5 kW | partie 8 min: 6 min mieszania z rozbiegiem, 2 min przerwy, tylko w czasie zmian | 5,8 kW w mieszaniu / 0,3 kW w przerwie partii / 0,05 kW | 0,80 / 0,45 |
| `sim_pakowaczka` | pakowaczka | 4 kW | w czasie zmian praca z wahaniami ±15 %, przerwy zmianowe jako bieg jałowy | 3,2 kW średnio / 0,9 kW / 0,12 kW | 0,78 / 0,50 |

Dobowa energia całego zakładu sim (doba robocza): rzędu 0,4–0,45 MWh (piec ok. 190 kWh, chłodnia ok. 140 kWh, reszta ok. 120 kWh) – wystarczy etapowi 4 do kosztu doby i poboru poza pracą. Stan „off/idle/run” **nie jest** zapisywany: klasyfikuje go etap 4 z mocy.

### 3.3 Pompa P-101 i degradacja łożyska (S5, S6)
Metryki (5 wierszy/s): `vibration_rms` (mm/s), `bearing_temperature` (°C), `motor_current` (A), `flow` (m³/h), `speed` (obr/min). Pompa pracuje w czasie zmian (kalendarz jak wyżej), poza nim stoi: obroty i przepływ 0, prąd 0, drgania tła ok. 0,1 mm/s, temperatura łożyska stygnie wykładniczo do temperatury otoczenia.
**Postęp degradacji** `x(t) = clamp((t − t_start) / (D · 86 400 s), 0, 1)`, gdzie `t_start = t_zero − 0,70 · D` dni, a `t_zero` („teraz” dla wdrożenia, data absolutna w configu, żeby zachować determinizm). Krzywa przyspieszająca: `f(x) = (e^{k x} − 1) / (e^{k} − 1)`, domyślnie k = 3.
Drgania w pracy: `vibration_rms = v_dobry + (v_koniec − v_dobry) · f(x)`, z szumem względnym ±5 %, wolnym składnikiem ±3 % i słabą zależnością od obciążenia. **`v_koniec` to koniec zakresu modelu, a nie próg alarmowy** (progi: etap 5, `docs/decisions.md`).
Temperatura łożyska rośnie razem z drganiami: `T = T_dobra + (T_koniec − T_dobra) · f(x) + ΔT_otoczenia(doba) − ΔT_nagrzewania · exp(−(t − t_start_pracy)/τ)`.
Prąd: `I_nom · (0,55 + 0,35 · obciążenie)` z dodatkiem do +3 % przy x = 1 (większe tarcie). Przepływ: `Q_nom · (n / n_nom) · (1 − 0,05 x)`. Obroty: `n_nom` z poślizgiem i szumem ±0,3 %.

| Parametr (w configu, propozycje) | Wartość | Uwaga |
| --- | --- | --- |
| `degradation.days_total` (D) | 120 | S5 |
| `degradation.history_progress` | 0,70 | S6; historia = 0,70 · 120 = 84 dni |
| `degradation.shape_k` | 3 | przyspieszanie pod koniec |
| `vibration.good_mm_s` / `end_mm_s` | 1,1 / 7,0 | koniec zakresu modelu, nie próg alarmu |
| `bearing_temp.good_c` / `end_c` | 52 / 78 | zmienia się razem z drganiami |
| `motor.rated_kw`, `motor.current_a` | 11 kW, ok. 21 A | prąd znamionowy do potwierdzenia |
| `flow_nominal_m3_h`, `speed_nominal_rpm` | 40, 2950 | parametry symulacji |

Wartości kontrolne dla `D = 120`, `k = 3`: `f(0,25) = 0,059`, `f(0,5) = 0,182`, `f(0,7) = 0,376`, `f(0,85) = 0,619`, `f(1) = 1`. Drgania: 1,10 → 1,45 → 2,18 → **3,32 (dziś, dzień 84)** → 4,75 → 7,00 mm/s. Nachylenie: ok. 0,063 mm/s na dobę w dniu 84, ok. 0,155 mm/s na dobę w dniu 120 (krzywizna widoczna dla trendu etapu 5). Temperatura łożyska w dniu 84: ok. 61,8 °C. Wartości te są **zmierzone na modelu, nie na maszynie**, i opisane tak w dokumentacji.

### 3.4 Tryby pracy
1. **Na żywo**: tick co 1 s zsynchronizowany z zegarem ściennym (sleep do granicy sekundy, bez narastającego dryfu), 29 wiadomości na tick (24 liczniki + 5 pompa), QoS 1, ponawianie połączenia z cofaniem wykładniczym, healthcheck „pętla żyje”.
2. **Historia (jednorazowe wypełnienie)**: polecenie `backfill --from --to --step` w tym samym obrazie (osobny `docker compose run --rm`), kolejność chronologiczna, **ograniczenie tempa** (domyślnie 500 wiadomości/s, parametr) i okresowe czekanie na potwierdzenia, żeby nie przepełnić kolejki brokera (utrata najnowszych wiadomości bez śladu); postęp w logu co minutę; wznawianie przez ponowne uruchomienie z innym `--from` (idempotentne). Weryfikacja liczbą wierszy w bazie na dobę (oczekiwana: dni × 86 400 × liczba metryk).
3. **Przyspieszony** [K0-D5]: tylko dla urządzenia demo, tylko postęp x przyspieszony, jawnie włączany.

## 4. Kroki etapu (każdy kończy się czymś sprawdzalnym; po każdym raport i stop)

| Krok | Zawartość | Kończy się |
| --- | --- | --- |
| **k1** | Konfiguracja: sekcja `simulator:` w `devices.yaml` (urządzenia, kalendarz, modele, degradacja, ziarno, historia); ingest doczytuje urządzenia sim i `site/line` na urządzenie [K0-D3]; testy konfiguracji i regresja (collector ignoruje sekcję, reguła 3: brak danych urządzeń w kodzie) | testy zielone, commit |
| **k2** | Modele czysto-funkcyjne w `services/simulator/src/simulator/` (kalendarz, liczniki, pompa, szum, całka energii) bez sieci | testy jednostkowe (determinizm, kalendarz z DST, energia, krzywa degradacji), commit |
| **k3** | Usługa na żywo: publisher MQTT (konto sim), pętla 1 s, health, Dockerfile, usługa w Compose (`mem_limit: 128m`, `read_only`, `cap_drop: [ALL]`), ACL i `entrypoint.sh` Mosquitto, `.env.example`, testy e2e (broker + ingest + baza w `aip-test`): 29 wierszy/s ze źródłem `sim` | testy zielone, commit; **bez wdrożenia na IPC** |
| **k4** | Migracja 012 `pump_1m` [K0-D4] z politykami (odświeżanie, kompresja po 14 dniach, retencja roku jak `energy_1m`), uprawnienia `app_reader`, testy jak dla `energy_1m` (w tym odświeżenie ręczne starej historii) | testy zielone, commit |
| **k5** | Tryb historii: `backfill`, ograniczenie tempa, idempotencja; pomiar przepustowości w `aip-test` i przepustowości brokera (próg utraty wiadomości) | testy + liczby w raporcie |
| **k6** | Grafana: „Flota”, „Pompa P-101”, etykieta SYMULACJA w zmiennej `$device` i tytułach (S10), opisy; testy generatora i harnessu; `docs/grafana.md` | testy zielone, dashboardy wygenerowane, commit |
| **k7** | Wdrożenie na IPC (dopiero po akceptacji etap-2 i planu): R-1 z `--build`, `.env` (Grzegorz), restart Mosquitto, start symulatora na żywo, historia, odświeżenie `pump_1m` i agregatów, kontrola zasobów; zrzuty | pomiary na IPC, raport |
| **k8** | `docs/stages/etap-3.md` (checklista dla Grzegorza), aktualizacja `plan.md`, `data-model.md`, `ops`; przegląd agentem `reviewer` | checklista do wykonania |

Każdy krok: plan krótki (lub wspólny plan+wykonanie, jeśli Grzegorz zdecyduje), testy `pytest` w `aip-test`, `reviewer` po k3, k5, k7.

## 5. Lista plików (nowe i zmieniane)

**Nowe:** `services/simulator/Dockerfile`, `requirements.txt`, `src/simulator/{__init__,config,calendar,noise,meter,pump,publisher,live,backfill,main,health}.py`; `tests/simulator/*` (unit, e2e, config, compose, perf); `db/migrations/012_pump_1m.sql`; `grafana/dashboards/{flota,pompa}.json`; `docs/stages/etap-3.md`; `docs/handoff/e3-kN-*.md`.
**Zmieniane:** `config/devices.yaml` (sekcja `simulator:`); `services/ingest/src/ingest/{config,validate}.py` (urządzenia sim, `site/line` na urządzenie) i `tests/ingest/*`; `config/mosquitto/{acl.conf,entrypoint.sh}` i `tests/mqtt/test_broker_acl.py`; `docker-compose.yml`, `docker-compose.test.yml`, `tests/config/test_compose_limits.py` (suma limitów 2432 + 128 = 2560 MiB, na granicy dozwolonego `≤ 2560`: kolejne usługi wymagają przeglądu limitów); `.env.example`; `grafana/generate.py` (zmienna `$device`, dwa dashboardy, nawigacja) i testy Grafany; `docs/{plan,data-model,grafana}.md`, `docs/ops/jumo-ipc-setup.md`, `docs/status-codes.md` (nowe metryki sim).
**Nie zmieniam:** collectora, `docs/modbus-map.md`, migracji 001–011, architektury.

## 6. Wpływ na wiersze/s, dysk, RAM

| Wielkość | Dziś | Po etapie 3 (live) | Uwagi |
| --- | --- | --- | --- |
| wiersze/s | 20 (PLC) | **49** (20 + 24 liczniki + 5 pompa) | 2,45 ×; ingest ma zapas (test 1 363/s, na produkcji niezmierzone) |
| wiersze/dobę | 1,73 mln | **4,23 mln** | 381 mln w oknie retencji 90 dni |
| dysk, surowe (ostatnia doba, niekompresowane) | ok. 0,3 GB | ok. **0,76 GB/dobę** (180 B/wiersz) | polityka kompresji po 1 dobie |
| dysk po kompresji | do zmierzenia (część B k8) | wg współczynnika z pomiaru; prognoza 90 dni zostanie przeliczona | wolne 869 GB: nie jest ograniczeniem |
| historia (opcja A) | – | 15,1 mln wierszy, ok. 2,7 GB przed kompresją | tymczasowo; kompresja policy po dobie |
| `pump_1m` | – | 1 440 wierszy/dobę na metrykę | retencja 1 rok, kompresja 14 dni |
| RAM symulatora | – | **szacunek 40–60 MiB**, `mem_limit` 128m (zasada 2: podam `docker stats` po wdrożeniu) | kolektor 38,8, ingest 39 MiB mierzone |
| RAM Mosquitto | 7 MiB, limit 64 | przy pełnej kolejce 80 000 wiadomości 36,8 MiB (zmierzone 25.11 w `aip-test`) | limit bez zmian |
| suma `mem_limit` kontenerów aip-* | 2432 MiB | **2560 MiB** | smartWARE ok. 0,4–1 GB, razem w 16 GB z zapasem |
| Grafana (512 MiB) | szczyt 392,7 MiB od 13:11 UTC | dwa nowe dashboardy | po przebiegu dobowym (część B) ocena limitu |

## 7. Kolejność wdrożenia (k7, po akceptacji; R-1 + elementy z udziałem Grzegorza)

1. Pull + testy w `aip-test` na IPC (dopiero po akceptacji etapu 2).
2. **Grzegorz** dopisuje do `.env` konto MQTT symulatora (polecenie dam gotowe; Claude Code nie czyta `.env`).
3. R-1: `git pull --ff-only` → `docker compose up -d --build`: nowy obraz `aip-simulator`, migracja 012, odtworzenie Mosquitto (zmieniony `entrypoint.sh`/ACL) i ingestu (nowy config). **Krótka przerwa brokera (kilka sekund): collector ma bufor 30 000, kolejka ingestu 80 000.**
4. Ingest synchronizuje urządzenia sim; kontrola `devices`.
5. Start symulatora na żywo; kontrola 49 wierszy/s i `source = 'sim'`.
6. Historia (`backfill`) z ograniczeniem tempa, w oknie bez pracy użytkowników; nadzór zasobów i kolejki; po zakończeniu liczenie wierszy na dobę.
7. Ręczne odświeżenie `pump_1m` (i `energy_1m/1h` dla zakresu historii liczników) – zakres starszy niż okna polityk odświeżania.
8. Pomiary: RAM wszystkich `aip-*` (`docker stats` + `memory.peak`), dysk, wiersze/s; okna w `data_windows` dla backfillu (jeśli architekt zdecyduje, jak dla wdrożeń).

## 8. Testy

- **Jednostkowe (bez sieci):** determinizm (ta sama chwila daje tę samą wartość niezależnie od kolejności wywołań), kalendarz (granice zmian, sobota, niedziela, święta, **DST 25.10.2026 i 28.03.2027**), energia (monotoniczna, kwantowana do 100 Wh, całka zgodna z mocą), krzywa degradacji (monotoniczna, wartości kontrolne z pkt 3.3, postęp przy `t_zero`), pompa stoi poza zmianami, brak NaN/Inf, wartości w zakresach fizycznych.
- **Konfiguracja:** `devices.yaml` poprawny; brak adresów, mocy i parametrów maszyn w kodzie (reguła 3: test skanujący źródła jak `test_no_write`); `collector` ignoruje sekcję `simulator`; ingest wczytuje sim; `source` sim dla wszystkich.
- **Integracyjne (aip-test):** e2e symulator → Mosquitto → ingest → baza (29 wierszy/s, `source = 'sim'`, jednostki, metryki); ACL: konto sim nie pisze poza `zaklad1/linia2/+/+` i nie czyta; ingest odrzuca wiadomość z `source: real` dla urządzenia sim i odwrotnie; zamiana `site/line`.
- **Historia:** godzina danych co 1 s i dzień co 1 min: liczba wierszy, **idempotencja** (drugi przebieg: 0 nowych), ciągłość licznika energii na styku historia/żywo, ochrona kolejki (tempo poniżej progu: brak utraty).
- **Agregaty:** `pump_1m` (sumy, liczności, min/max, odświeżanie, zakres starszy niż polityka) jak testy `energy_1m`; widoki energii dla urządzeń sim (poprawna energia i pokrycie przy 1 s).
- **Grafana:** generator (nowe dashboardy, etykieta SYMULACJA, zmienna `$device`), harness zapytań (bez błędów, dane dla urządzeń sim i pompy, krzywa rosnąca), regresja pięciu istniejących dashboardów.
- **Compose:** `mem_limit: 128m`, `read_only`, `cap_drop`, suma limitów, konto MQTT z `.env`.
- **Wydajność (opt-in, `run-perf.sh`):** przepustowość historii i próg przepełnienia kolejki Mosquitto.
- **Kryterium etapu:** flota 5 liczników ze źródłem real/sim, rosnące wibracje pompy (zapytanie i panel z `pump_1m` na 84 dniach); wszystko do sprawdzenia przez Grzegorza w `etap-3.md`.

## 9. Ryzyka

| Ryzyko | Postępowanie |
| --- | --- |
| **Historia 1 min zaniża energię 60 ×** (K0-D1) | opcja A albo B; decyzja przed k1 |
| Niespójność S5/S6 (K0-D2) | wariant 120/84 (rekomendacja) |
| Przepełnienie kolejki brokera przy historii: ciche gubienie najnowszych wiadomości | ograniczenie tempa, weryfikacja liczbą wierszy, powtórka idempotentna |
| Wstawianie wstecz do chunków skompresowanych (polityka po 1 dobie) jest wolniejsze | kolejność chronologiczna, test w `aip-test`; kompresję doganiają zadania w tle |
| Przepustowość ingestu na produkcji nieznana (1 363/s to test na tmpfs) | pomiar w k5 i pilotaż 1 doby historii przed pełnym wgraniem |
| Zmiana `ingest/validate.py` (linia na urządzenie) dotyka ścieżki danych prawdziwych | testy regresji ingestu, wdrożenie przez R-1 z kontrolą 20 wierszy/s PLC |
| Dashboardy istniejące pokażą liczniki sim w `$device` bez diagnostyki | opis w dashboardzie, K0-D6; etykieta SYMULACJA |
| Parametry modelu wyglądają jak fakty o maszynach | opisane jako parametry symulacji; progi alarmowe tylko w etapie 5 |
| Suma limitów 2560 MiB na granicy testu budżetu | świadoma zmiana testu przy kolejnym kontenerze |
| Tryb przyspieszony zaburzy ciągłość serii P-101 | tylko urządzenie demo, domyślnie wyłączone (K0-D5) |
| Zmiana czasu letniego w historii (doba 25 h) | test kalendarza |
| Restart symulatora = luka w danych na żywo | bez stanu: `backfill` uzupełnia lukę idempotentnie; opcja `catch_up` |

## 10. Czego potrzebuję

1. Decyzje: **K0-D1** (A/B, wartość K), **K0-D2** (120/84), **K0-D3** (linia2), **K0-D4** (`pump_1m` w etapie 3), D5–D9.
2. Od Grzegorza: S1 (zestaw maszyn i moce znamionowe z pkt 3.2 lub własne), S2 (kalendarz), parametry pompy (pkt 3.3), nazwy urządzeń (id i opisy po polsku).
3. Wskazanie pliku z „Decyzjami Grzegorza”, jeśli istnieje (pkt 0).
4. Potwierdzenie, że po akceptacji etapu 2 testy w `aip-test` na IPC wracają (zakaz dotyczy zamknięcia etapu 2).

Plan e3-k0 gotowy do przeglądu. Niczego nie wdrażam i nie implementuję do czasu review.
