# E3-k2 – raport: modele symulatora i ich parametry

Data: 2026-11-26. Plan: `e3-k2-plan.md`, review: `e3-k2-review.md` (OK Z UWAGAMI; parametry K2-D1 przyjęte przez Grzegorza, K2-D2 tak). Produkcja **nie zmieniona** (`~/ai-predykcja` na `c299eaa`, katalog czysty po każdym przebiegu); testy z worktree `~/ai-predykcja-dev` w `aip-test`.
Plik setupu PLC po PLC-2: **`e61b2fd`**. Commity k2: `ed23758` (review), `85f95a2` (biblioteka, parametry, testy, dokumentacja), `b53fb59` (poprawki po przeglądzie `reviewer`), `1b03239` (porządek), ten raport.

## Co powstało

- **`services/simulator/src/simulator/`** (czysty Python, bez sieci): `config` (wczytanie i walidacja sekcji `simulator`, `require_t_zero()`), `calendar` (zmiany, przerwy, święta, czas letni, temperatura otoczenia), `noise` (szum z `blake2b`, jeden skrót na urządzenie i sekundę), `meters` (termostat, sprężarka, partie, praca ciągła; elektryka trójfazowa), `energy` (licznik `energy_import_wh`), `pump` (degradacja łożyska i wielkości procesowe), `samples` (`samples_at(t)` → 29 metryk: 4 × 6 + 5). Każda wartość jest funkcją `f(chwila, ziarno, config)`.
- **`config/devices.yaml`:** pełne parametry modeli w sekcji `simulator` (kalendarz S2, przerwy, otoczenie, elektryka, historia, degradacja, `energy_start_wh`, `model:` każdego urządzenia; wartości z K0 i K2-D1). Nagłówek pliku: mapa Modbus **wersja 2** (K1-U1).
- **`services/simulator/requirements.txt`:** `PyYAML==6.0.4`, **`tzdata==2025.2`** (K2-U2); `tzdata` także w `tests/requirements.txt`, `PYTHONPATH` testów rozszerzony o `services/simulator/src`.
- **`docs/data-model.md`:** metryki i jednostki urządzeń sim, licznik jako całka modelu (K2-U3), termostat (K2-U6), pompa w przerwach, znacznik pracy dla `pump_1m`, prąd +5 % (K2-U4), koniec krzywej (K2-U1).
- Bez zmian: ingest, collector, compose produkcyjny, Mosquitto, baza, Grafana. Kontener symulatora – k3.

## Uwagi z review

| Uwaga | Jak zrobione |
| --- | --- |
| K1-U1 | komentarz nagłówka `devices.yaml`: wersja 2 od 25.11.2026, collector akceptuje v1 i v2 |
| K1-U2 | `t_zero: null` → `require_t_zero()` zgłasza `ConfigError` z komunikatem o k7; `Simulator`, `EnergyCounter` i `PumpModel` nie wystartują; data bez strefy i niepełna minuta = błąd; nic nie podstawia „teraz” (testy) |
| K2-U1 | x > 1 obcinane do 1, wartości jak dla x = 1, WARNING raz na model pompy w procesie (test: x = 1,2 ≡ x = 1, jedno ostrzeżenie) |
| K2-U2 | `tzdata==2025.2` przypięte; testy czasu letniego przechodzą w kontenerze testowym: **Python 3.12.16, tzdata 2025.2** (ta sama wersja Pythona co obraz bazowy dla k3). Uwaga z przeglądu: `zoneinfo` najpierw szuka bazy systemowej (`/usr/share/zoneinfo`), `tzdata` jest zapasem – żeby wersja bazy była ściśle ta z `tzdata`, w obrazie k3 ustawię `PYTHONTZPATH=""` |
| K2-U3 | koszt zmierzony (tabela niżej); **90 dni > 60 s** – rozwiązanie do wyboru w k3; opis „licznik rośnie także bez publikacji” w `docs/data-model.md` |
| K2-U4 | pompa pracuje przez całą zmianę, także w przerwach (`shift_at`, nie `state`), stoi poza zmianami; **wariant prądu: +5 % przy x = 1** (test 1,05 ± 0,003); znacznik pracy dla `pump_1m` (k4) opisany |
| K2-U5 | jednostka `rpm` |
| K2-U6 | faza wyłączonej grzałki = `p_idle_kw` (YAML, kod, `data-model.md`); sobota 13:30–13:59:59 `break`, 14:00:00 `off` (test) |

## Wyniki (na IPC, w kontenerze testowym)

**Energia doby roboczej** (poniedziałek 30.11.2026: 15 h pracy, 1 h przerw, 8 h postoju), K2-D2:

| Urządzenie | Zmierzona | Przedział |
| --- | --- | --- |
| pasteryzator | **192,3 kWh** | 170–210 |
| agregat chłodniczy | **142,0 kWh** | 120–160 |
| mieszalnik | **65,2 kWh** | 50–80 |
| pakowaczka | **49,9 kWh** | 35–55 |
| razem | 449,4 kWh | (k0: 0,40–0,45 MWh) |

**Pompa – wartości kontrolne krzywej** (k = 3; średnia godziny pracy 08:00–09:00 przy danym x, te same chwile = ten sam szum):

| x | f(x) (model) | Drgania zmierzone | Kontrolne (k0) |
| --- | --- | --- | --- |
| 0,25 | 0,059 | 1,47 mm/s | 1,45 |
| 0,50 | 0,182 | 2,21 | 2,18 |
| 0,70 (`t_zero`) | 0,376 | 3,37 | 3,32 |
| 0,85 | 0,619 | 4,82 | 4,75 |
| 1,00 | 1,000 | 7,10 | 7,00 |

Średnie godzinowe są o 1–1,5 % powyżej wartości kontrolnych przez wolne wahanie (±3 %, okres 6 h) w tej godzinie; tolerancja testu 4 %. Temperatura łożyska w dniu `t_zero` po nagrzaniu, bez odchylenia otoczenia: **61,8 °C** (model 61,85, test ± 0,1; średnia 10 min z szumem ± 1,5).

**Koszt liczenia (K2-U3)** – pomiar z testu w kontenerze na IPC:

| Wielkość | Wynik |
| --- | --- |
| jedna doba jednego licznika (86 400 próbek mocy) | 0,79 s |
| start licznika 14 dni po kotwicy (1 licznik, zimny) | 10,8 s |
| jedna sekunda wszystkich 29 metryk (po rozgrzaniu) | 0,18 ms |
| prognoza startu 4 liczników: 14 / 30 / 90 / 365 dni po kotwicy | **44 s / 94 s / 283 s / 1 148 s** |
| historia 14 dni co 1 s (sam rachunek, bez MQTT) | ok. 0,1 h |

**90 dni przekracza 60 s** (to samo zmierzył agent `reviewer`: 101–283 s zależnie od obciążenia maszyny). Zgodnie z K2-U3 rozwiązanie wybieramy w k3; moja propozycja: pamięć sum dobowych (W·s, liczby całkowite) w pliku w wolumenie symulatora, z kluczem (urządzenie, doba od kotwicy, skrót parametrów modelu i ziarna) – plik da się w każdej chwili odtworzyć, więc nie łamie zasady „bez stanu”; dzięki sumowaniu na liczbach całkowitych wynik z pliku i z rachunku jest identyczny.

## Testy

| Przebieg (worktree, `aip-test`) | Commit | Wynik |
| --- | --- | --- |
| testy symulatora lokalnie (venv na laptopie, do szybkiej iteracji) | przed `85f95a2` | 2 porażki w moich testach (tolerancja prądu przy zaokrągleniach, `caplog` łapał ostrzeżenie innego modelu) – poprawione; potem zielone |
| pełny | `85f95a2` | **642 passed, 3 skipped, 0 failed** (1 281 s) |
| pełny, końcowy | `1b03239` | **653 passed, 3 skipped, 0 failed** (1 330 s, 26.11 10:52–11:15 UTC); produkcja `c299eaa`, czysto |

Testy symulatora (101 nowych w pełnym zestawie: 653 − 552 z k1, w 7 plikach): config i walidacja (37 przypadków błędnego configu, w tym nowe z przeglądu), `t_zero` (K1-U2), kalendarz (18 chwil, święto, doby 25 h i 23 h, kolejność wywołań), determinizm (kolejność, nowa instancja, **nowy proces z innym `PYTHONHASHSEED`**, inne ziarno, zegar systemowy), liczniki (stany, cykle, partie, sprężarka, elektryka przez dobę, energia dobowa), licznik energii (kotwica, monotoniczność, kwant 100 Wh, zgodność z całką, ścieżki „po kolei” i „dobowa” identyczne co do W·s), pompa (x(t_zero) = 0,70, wartości kontrolne, wzrost, koniec krzywej, praca w przerwach, prąd +5 %, temperatura), koszt, reguła 3. Ingest czyta plik jak po k1 (te same urządzenia i meta – test).
Czas pełnego zestawu wzrósł z ok. 12 do ok. 22 min (testy symulatora liczą doby próbek co 1 s); po rozwiązaniu K2-U3 w k3 spadnie.

## Przegląd agentem `reviewer`

Werdykt agenta: krok poprawny, uwagi K2-U1…U6 i K1-U2 spełnione; agent niezależnie zmierzył te same energie i drgania. Ustalenia i co z nimi zrobiłem:

| # | Ustalenie | Stan |
| --- | --- | --- |
| 1 | koszt startu licznika: 90 dni > 60 s | **do k3** (wyżej, z propozycją) |
| 2 | **jedno `t_zero` steruje degradacją pompy i kotwicą liczników**: „wymiana łożyska” przez nowe `t_zero` cofnęłaby liczniki energii (przykład agenta: pasteryzator 17 054 000 → 3 457 600 Wh, widoki energii zobaczą `import_reset`), a nowa historia nałożyłaby się na stare dane | **do decyzji architekta przed k7**; propozycja: osobne pola `meter_anchor` (stała data kotwicy liczników) i `pump.t_zero` (degradacja), przy wdrożeniu oba ustawiane razem, później zmieniane niezależnie |
| 3 | ścieżka przyrostowa i dobowa licznika różniły się w ostatnich bitach (możliwy jednosekundowy spadek o 100 Wh przy trafieniu w granicę kwantu) | **poprawione**: całka w liczbach całkowitych W·s, test identyczności |
| 4 | luki walidacji: święto jako znacznik czasu, nieznane klucze (literówki), nakładające się przerwy, liczby jako tekst, ułamkowe `cycle_s`/`batch_min`, za duże wahania napięcia, linia sim = linia sprzętu (sprawdzał tylko ingest) | **poprawione** + testy (10 nowych przypadków); relacji mocy (`p_idle` > `p_on`) nie sprawdzam |
| 5 | słabsze miejsca testów (zegar tylko `time.time`, mało punktów styku dób, doby 23/25 h bez energii) | częściowo: test identyczności całki na 6 000 kolejnych sekund przez styk dób; reszta – zapis do k3/k5 |
| 6 | `samples_at` dla chwili sprzed kotwicy liczników zgłasza `ValueError` (historia pompy 84 dni, liczników 14) | **do k5**: historia pompy przez `samples_at(t, devices={pompa})` – opis w planie k5 |
| 7 | `tzdata` to zapas `zoneinfo`, nie pierwsze źródło | **do k3**: `PYTHONTZPATH=""` w obrazie |
| 8 | stałe modelu w kodzie (+5 % prądu, −5 % przepływu, tło drgań 0,1 mm/s, poziomy szumu) | parametry modelu, nie dane urządzeń (reguła 3 spełniona); przy kolejnym typie pompy – do YAML |

Pamięć biblioteki (pomiar agenta, `tracemalloc`): ok. 4,4 MB na godzinę pracy całego symulatora; pamięci podręczne ograniczone (plan doby i suma dobowa: 1 wpis na dobę).

## Zasoby

k2 nie dodaje kontenera ani nie zmienia produkcji. Obraz testowy urósł o pakiet `tzdata` (ok. 0,5 MB).

## Do decyzji

1. Ustalenie 2: rozdzielenie kotwicy liczników od `t_zero` pompy (przed k7).
2. K2-U3: pamięć sum dobowych w pliku (k3) – propozycja wyżej.

Raport e3-k2 gotowy. Stop.
