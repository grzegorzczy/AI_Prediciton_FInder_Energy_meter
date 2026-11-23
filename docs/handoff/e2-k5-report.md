# e2-k5 raport: pierwsze prawdziwe dane (PLC → collector → MQTT → ingest → baza)
Status: DO PRZEGLĄDU

Wykonanie 23.11.2026 (czasy w UTC, o ile nie zaznaczono inaczej; logi kontenerów są w czasie lokalnym UTC+1) wg `e2-k5-plan.md` i uwag K5-U1…U5 z `e2-k5-review.md`,
w kolejności z K5-U4. Polecenia na `jumo-ipc` wykonywałem przez `ssh jumo@192.168.0.213`, **bez `sudo`**, bez ruszania smartWARE, demona Dockera i `docker system prune`.
Do PLC dotarło wyłącznie FC04: collector oraz `mbpoll -t 3`; żadnych zapisów do PLC ani do licznika nie było. `.env` nie był czytany ani wypisywany. Raport bez sekretów.

## Podsumowanie

Cały tor działa na prawdziwym PLC i liczniku, a potok (collector → MQTT → ingest → baza) jest poprawny: w 10-minutowym oknie 600 s pokrytych bez luk, 0 duplikatów, `rejected=0`,
liczba wierszy w każdej minucie zgadza się **dokładnie** z modelem. **Kryterium „780 wierszy na minutę ±2%” w planie nie jest jednak spełnione dosłownie**, bo licznik w systemie zgłasza
cykliczny błąd komunikacji z PLC (co 64 s, patrz „Ustalenia”). Test PLC offline i test Stop programu wykazały dwie rzeczy, których plan nie zakładał (luki w `link_status` w awarii, `link_status` = 1 zamiast 2 po Stop).

## Co zrobiono

| Hash | Zawartość |
| --- | --- |
| `5b9c1a3` | review k5 |
| `f80f555` | usunięcie profilu `live` (collector startuje ze stosem), test Compose i `docs/ops` zaktualizowane |

Raport i pozostałe zmiany idą w commicie po tym raporcie. Testy po zmianie profilu: **257 z 257** (160 s), bez resztek `aip-test`.

## Wyniki względem kryteriów zaliczenia

| Kryterium | Wymóg | Wynik |
| --- | --- | --- |
| Start | `healthy` ze stosem bez `--profile`; pierwszy odczyt przez NAT; zero odmów MQTT | ✔ collector `healthy` po 15 s; sam TCP z kontenera 55 ms; `plc: OK` i `meter: OK` po 1,0 s od startu; brak odmów MQTT |
| Zgodność wartości | U ±0,5 V, P ±0,2 W, energia równa, serial | ✔ 5 par: U ±0,1 V, P ±0,1 W, energia identyczna, serial `F0183363` |
| Liczba wierszy | 780/min ±2%, brak duplikatów, `rejected=0` | ✘ dosłownie (744–780 przez błędy licznika); ✔ model 13/4 wierszy na sekundę zgodny w 100% minut; 0 duplikatów; `rejected=0` |
| Heartbeat | ok. 6/s (obserwacja, nie wymóg; K5-U5) | zmierzone **ok. 5,0/s** (4,93–5,01); kontrakt (zmiana w ciągu 5 s) spełniony z dużym zapasem |
| Przerwa RS485 | `meter_status` = 1, `error_count` +1, `data_age` rośnie, brak pomiarów, powrót | ✔ patrz niżej |
| PLC offline (LAN1) | `link_status` = 1, 1 wiersz/s i nic więcej, powrót bez ingerencji | częściowo: ✔ tylko `link_status` = 1, ✔ powrót bez ingerencji, ✘ nie 1 wiersz/s (luki 3 s co ok. 12 s) |
| Restart brokera | brak luki > restart, brak duplikatów, oba `healthy` | ✔ 0 sekund bez danych, 0 duplikatów w bazie, oba `healthy` |
| Stop programu (opcjonalny, za zgodą) | wynik jako fakt | ✔ wykonany za zgodą Grzegorza: serwer Modbus przestaje odpowiadać → `link_status` = 1 (nie 2) |
| Zasoby | `docker stats`, `zapis_ms`, jitter | ✔ patrz „Zasoby” |
| Zasada 1 | tylko FC04 | ✔ collector (konstrukcja i testy z k3) i `mbpoll -t 3` |
| Izolacja | smartWARE bez zmian, brak nowych portów | ✔ `StartedAt` 7 kontenerów bez zmian, `ss -ltn` bez zmian, kontrola praw czysta, `.env` 600 |

## Ustalenia wymagające decyzji architekta

### U-1. Cykliczny błąd komunikacji PLC z licznikiem co 64 s

Licznik zgłasza `meter_status` = 1 w regularnych epizodach: **1 s błędu plus 3 s przytrzymania w PLC = 4 s bez pomiarów**, każdy epizod zwiększa `meter_error_count` o 1.

Lista epizodów od startu collectora (start, czas trwania, odstęp od poprzedniego; tylko okna bez celowych testów):

| Start | Sek. | Odstęp [s] | Start | Sek. | Odstęp [s] |
| --- | --- | --- | --- | --- | --- |
| 22:39:18 | 4 | | 22:48:54 | 4 | 64 |
| 22:40:22 | 4 | 64 | 22:49:58 | 4 | 64 |
| 22:42:30 | 4 | 128 | 22:53:10 | 4 | 192 |
| 22:43:34 | 4 | 64 | 22:56:22 | 4 | 192 |
| 22:44:38 | 4 | 64 | (22:56:35–22:57:26: celowa przerwa RS485) | 52 | 13 |
| 22:45:42 | 4 | 64 | 23:01:42 | 4 | 320 |
| 22:47:50 | 4 | 128 | | | |

Fakty:
- Wszystkie początki leżą na **siatce co 64 s** (np. 23:01:42 jest 21 kroków po 22:39:18). Epizod nie występuje w każdym punkcie siatki: w oknie 22:41–22:51 (10 pełnych minut) było **7 epizodów** (7 × 4 s = 28 s), w kolejnych 17 minutach poza testami 3 w bazie (22:53:10, 22:56:22, 23:01:42) i 2 widziane przez `mbpoll` przy zatrzymanym collectorze (22:54:14, 22:55:18). Od startu programu po Stopie (23:05:25) do 23:07:46 nie było żadnego (dwa punkty siatki: 23:05:58 i 23:07:02), co jest zbyt krótką próbą, by cokolwiek wnioskować o zmianie częstości.
- **Niezależne od collectora i ingestu:** po zatrzymaniu collectora (`docker compose stop collector`, 22:53:44–22:55:35) `mbpoll -t 3` co 10 s widział ten sam wzorzec: `status` = 1 i `error_count` 53 → 54 (22:54:14) i 54 → 55 (22:55:18), czyli dokładnie na siatce 64 s.
- **Zaczęły się przed collectorem:** punkt odniesienia z `mbpoll` o ok. 22:38:10 pokazał `error_count` = 42 (0x2A), a pierwszy epizod w bazie (22:39:18) i `error_count` 45 o 22:41:00 wymagają jednego epizodu między nimi (ok. 22:38:14), zanim collector wystartował (22:38:25). Wcześniejszych etapów nie umiem odtworzyć.
- Skutek: w oknie 10 minut **28 z 600 sekund (4,7%)** bez pomiarów licznika.
- **Przyczyny nie znam** i jej nie zgaduję. Poza zakresem collectora i ingestu; PLC i mapa należą do architekta i Grzegorza. Do rozważenia po stronie PLC/okablowania: odporność filtra (3 s przytrzymania powiększa 1-sekundowy błąd do 4 s braku danych), ustawienia kanału RTU (odpowiedź 200 ms, 6 kanałów), okablowanie i terminacja RS485, sam licznik.

### U-2. `link_status` w awarii ma luki: nie 1 wiersz/s

W teście LAN1: 74 wiersze `link_status` = 1 w ok. 92 s, czyli **80,6% sekund**. Co ok. 12 s jest **3,00-sekundowa luka** (po wierszach 22:58:56.162, 22:58:58.993, 22:59:03.002, 22:59:09.007,
22:59:19.012, 22:59:31.019, … 23:00:19.041). Przyczyna to konstrukcja `ModbusPlcDriver`: próba ponownego połączenia (do `timeout_s` + 1 s = 3 s) blokuje pętlę, więc w tym cyklu nie
ma publikacji. Dane są poprawne, ale ciągłość wykresu stanu w awarii jest gorsza niż w planie. **Propozycja (nie wprowadzona w k5, bo K5-a: bez zmian w kodzie):** publikować stan niezależnie od
blokującej próby połączenia (osobne zadanie lub krótszy limit czasu połączenia). Decyzja architekta.

### U-3. Stop programu: serwer Modbus przestaje odpowiadać

Po Stop programu w CODESYS serwer Modbus TCP **nie odpowiada** (timeout zarówno u collectora, jak i u niezależnego `mbpoll`): `link_status` = **1**, nie 2. Scenariusz „zamrożony heartbeat przy
odpowiadającym serwerze” (`link_status` = 2) nie wystąpił na prawdziwym PLC; reguła kontraktu zostaje sprawdzona tylko na atrapie (k3). Do `docs/status-codes.md` warto dopisać, że Stop programu
objawia się jako kod 1. Stop/Start jest „gorący”: heartbeat nie został wyzerowany (`0x67A6` przed Stop, `0x6935` po Start), `error_count` nie zerował się (58), a `meter_status` = 0 od pierwszego
cyklu po powrocie (bez `NO_DATA`).

### U-4. Szum w logu collectora od pymodbus

Przy awariach w logu pojawiają się linie pymodbus mimo ustawienia poziomu `ERROR`: przy LAN1 jeden wpis `ERROR pymodbus.logging No response received…` plus **20 surowych linii z ramkami** (`>>>>> send:`/`recv:`,
dane pomiarowe, nie sekrety); przy Stop **12 wpisów ERROR** (jeden na każdą próbę z timeoutem, co 10–12 s). To niewielki wolumen (kilkadziesiąt linii na awarię), ale to szum. Propozycja: wyciszyć logger `pymodbus`
poniżej `CRITICAL` (zmiana jednej linii w `main.py`); do decyzji, bo K5-a zabrania zmian kodu w k5.

## Szczegóły testów

### 1. Start i NAT

- `docker compose up -d` bez `--profile`. Sam TCP z kontenera w `aip_backend` do 192.168.0.246:502 (bez żądania Modbus): 55,3 ms. Punkt odniesienia z `mbpoll -t 3` (rejestry 0–43) przed startem: `map_version` 1,
  `status` 0, `error_count` 42, napięcie 239,6 V, moc 7,2 W, energia 3600 Wh, serial `F0183363` (`4630 3138 3333 3633`). Ping do PLC: 1,39 ms średnio.
- Start collectora ok. 22:38:25; log: `start: PLC 192.168.0.246:502 (FC04, rejestry 0-43)`, `MQTT: połączono`, po 1,0 s `plc: (start) -> OK` i `meter:finder_7m24_1: (start) -> OK` (rozgrzewka jednego cyklu). Pierwszy
  start z `read_only`, `cap_drop: ALL`, `tmpfs: /tmp` i healthcheckiem `python -m collector.health` przeszedł bez problemów (K3 „Do k5” 1).

### 3. Zgodność wartości (K5-d)

PLC **przyjął drugiego klienta Modbus** przy działającym collectorze, więc plan awaryjny z zatrzymaniem collectora nie był potrzebny. Pięć par `mbpoll` (jeden odczyt rejestrów 0–43) i najbliższy wiersz w bazie (odstęp 0,02–1,4 s):

| Wielkość | Największa różnica | Tolerancja |
| --- | --- | --- |
| napięcie | 0,1 V | ±0,5 V ✔ |
| moc czynna | 0,1 W | ±0,2 W ✔ |
| energia pobrana / oddana | 0 (3600 / 0 Wh) | równa ✔ |
| moc pozorna | 0,2 VA | bez progu |
| częstotliwość / prąd / współczynnik mocy / moc bierna | 0,01 Hz / 0 / 0,0029 / 0 | bez progu |

Różnice wynikają z przesunięcia próbkowania (PLC odświeża wartości co 1 s). `meter_status` = 0 w każdej parze, serial `F0183363`, `map_version` 1.
Czas jednego wywołania `mbpoll` (start procesu, połączenie, odczyt 44 rejestrów): 355–401 ms, mediana 361 ms (przeważa start procesu).

### 4. Okno 10 pełnych minut: 22:41:00–22:51:00 (K5-e, K5-U4)

Okno nie nachodziło na żaden test ani na start collectora (start 22:38:25, ostatni `mbpoll` ok. 22:39:10).

| Pomiar | Wynik |
| --- | --- |
| Wiersze w oknie | 7548; 600 różnych sekund; **0 sekund bez danych**; **0 duplikatów** |
| Rozkład wierszy na sekundę | 572 s po 13 wierszy, 28 s po 4 wiersze |
| Model | 572 × 13 + 28 × 4 = **7548: zgodny dokładnie** |
| Odstępy między kolejnymi `link_status` | mediana 1,000 s, p99 1,002 s, min 0,984 s, maks. 1,016 s |
| Opóźnienie `now() - max(time)` | 0,1 s |
| Ingest | `rejected=0` we wszystkich podsumowaniach, `duplikaty=0`; `zapis_ms_sr` 15,5–17,2 ms, `zapis_ms_maks` 18,7–21,4 ms |

Wiersze na minutę (model: 13 × s_ok + 4 × s_błąd): 22:41 → 780 (0 s błędu), 22:42 → 744 (4), 22:43 → 744 (4), 22:44 → 744 (4), 22:45 → 744 (4), 22:46 → 780 (0), 22:47 → 744 (4),
22:48 → 744 (4), 22:49 → 762 (2), 22:50 → 762 (2). W każdej minucie liczba wierszy równa modelowi. Przy `meter_status` = 0 w całej minucie jest dokładnie 780 wierszy (13 na sekundę).

### 9. Restart brokera (K5-U4 punkt 3; kontener `aip-mosquitto`)

Restart 22:52:14.2, polecenie trwało 0,88 s, broker `healthy` po ok. 11 s (22:52:25.6). Collector i ingest cały czas pokazywały `healthy`.
- **0 sekund bez `link_status`** w oknie 22:52:00–22:53:10; największy odstęp 1,001 s; **0 duplikatów w bazie**.
- Collector: `MQTT: rozłączono (Unspecified error); wiadomości trafiają do bufora` o 22:52:14.5, `MQTT: połączono` o 22:52:15.5 (1,0 s).
- Ingest: `MQTT: rozłączono`, po 1,0 s `połączono, sesja trwała wznowiona`, subskrypcja potwierdzona; w podsumowaniu `duplikaty=13` (jeden cykl dostarczony ponownie i pominięty przez `ON CONFLICT`), `rejected=0`.

### 6. Test przerwy RS485 (Grzegorz odłączył jeden przewód przy złączu „COM” PLC)

| Kryterium | Wynik |
| --- | --- |
| `meter_status` = 1 przez całą przerwę | tak: od 22:56:35.163 do 22:57:26.162 (**52 s**; przerwa dłuższa niż planowane 10 s, bo czas wyznaczają dane) |
| `meter_error_count` +1 | tak: 56 → 57 |
| `meter_data_age_ms` rośnie | tak, równo: przyrosty 999–1001 ms na sekundę, do 51 400 ms |
| brak pomiarów licznika | tak: **0 wierszy** pomiarowych w przerwie; w przerwie dokładnie 4 wiersze na sekundę (50 s) |
| `link_status` | cały czas 0 (65 wierszy w 65 s) |
| powrót | `meter_status` = 0 i pomiary (napięcie 239,7 V) wracają w tym samym cyklu, 22:57:27.161; ostatni pomiar przed przerwą 22:56:34.162 (239,1 V) |
| K5-U5: pojedynczy „stary” pomiar na początku przerwy | nie wystąpił: ostatni pomiar (34.162), pierwszy status 1 (35.163) |

Chwilę fizycznego podłączenia przewodu znam tylko przybliżenie (ok. 22:57:23, wynika z 3-sekundowego przytrzymania w PLC: ostatni status 1 o 22:57:26), więc „powrót ok. 3 s po podłączeniu” nie jest zmierzony wprost.
Logi: dwa wpisy zmiany stanu (`OK -> COMM_ERROR` o 23:56:35 lokalnie, `COMM_ERROR -> OK` o 23:57:27), bez zalewania.

### 7. Test PLC offline (kabel LAN1 do switcha odłączony przez Grzegorza)

| Pomiar | Wynik |
| --- | --- |
| Wykrycie | ostatni poprawny wiersz 22:58:56.162, pierwszy `link_status` = 1 o 22:58:58.993: **2,8 s** (wymóg ≤ `timeout_s` + 1 s ✔) |
| W trakcie awarii | **tylko** `link_status` = 1 (74 wiersze, żadnej innej metryki) ✔ |
| Gęstość | 80,6% sekund z wierszem; luki po 3,00 s co ok. 12 s (U-2) |
| Powrót | bez ingerencji: ostatni wiersz awarii 23:00:31.047, pierwszy `link_status` = 0 o 23:00:33.161 (rozgrzewka jednego cyklu), pierwszy cykl z pełnymi 13 wierszami |
| Adres z DHCP | bez zmian (192.168.0.246), ping 0,5–1,4 ms po powrocie |
| Czas awarii | 94 s (22:58:59–23:00:33), dłuższy niż planowane 30 s |

Log: `plc: OK -> PLC_OFFLINE`, przypomnienie `nadal PLC_OFFLINE` po 60 s, `PLC_OFFLINE -> OK`. Surowe linie pymodbus: U-4. smartWARE: `StartedAt` bez zmian; nie sprawdzałem, czy korzysta z PLC po sieci.

### 8. Stop programu w CODESYS (za zgodą Grzegorza, K5-U2)

Grzegorz użył **Stop** (nie Reset ani „Login with download”), a po ok. 100 s **Start**; PLC wrócił do RUN. Wynik jako fakt: patrz U-3.

| Pomiar | Wynik |
| --- | --- |
| Pierwszy `link_status` = 1 | 23:03:39.049 (ostatni poprawny wiersz 23:03:36.161: 2,9 s) |
| `mbpoll -t 3` w czasie Stop | `Connection timed out` (dwa odczyty) |
| Powrót po Start | `link_status` = 0 o 23:05:25.162, pełne 13 wierszy od pierwszego cyklu; `meter_status` = 0, `error_count` 58, `data_age` 0 |
| Heartbeat | `0x67A6` (23:02:54, przed) → `0x6935` (23:05:5x, po): nie wyzerowany, przyrost zgodny z pracą programu tylko poza czasem Stop |

### Diagnostyka: collector zatrzymany (22:53:44–22:55:35)

Wynik w U-1. Skrypt w tle (`setsid`) odczytywał co 10 s rejestry 10–15 przez `mbpoll -t 3` i zakończyłem go wcześniej po drugim epizodzie, uruchamiając collector (`healthy` o 22:55:37, `OK` po 1,2 s).

## Okna testów w formie do maszynowego użycia (K5-U3)

Czasy UTC. Okna to przedziały od pierwszej zmiany stanu do powrotu. Epizody cyklicznego błędu licznika (U-1, 4 s każdy) są **prawdziwymi danymi** i leżą poza tymi oknami; ich lista jest w U-1.

| start | koniec | rodzaj | uwagi |
| --- | --- | --- | --- |
| 2026-11-23T22:38:25Z | 2026-11-23T22:38:26Z | `collector_start` | start collectora, rozgrzewka jednego cyklu |
| 2026-11-23T22:41:00Z | 2026-11-23T22:51:00Z | `calm_window` | okno referencyjne 10 min, bez testów (epizody co 64 s w środku) |
| 2026-11-23T22:52:14Z | 2026-11-23T22:52:26Z | `mqtt_broker_restart` | `docker compose restart mosquitto`; 0 s luki, 0 duplikatów |
| 2026-11-23T22:53:44Z | 2026-11-23T22:55:37Z | `collector_stopped` | diagnostyka: collector zatrzymany, brak danych z tego okna |
| 2026-11-23T22:56:35Z | 2026-11-23T22:57:27Z | `rs485_break` | `meter_status` = 1 przez 52 s |
| 2026-11-23T22:58:59Z | 2026-11-23T23:00:33Z | `plc_lan1_unplugged` | `link_status` = 1 przez 94 s; luki 3 s co ok. 12 s |
| 2026-11-23T23:03:39Z | 2026-11-23T23:05:25Z | `plc_program_stop` | Stop programu w CODESYS; `link_status` = 1; serwer Modbus nie odpowiadał |

## Zasoby

| Kontener | Zużycie | Limit | CPU (stan ustalony) |
| --- | --- | --- | --- |
| `aip-collector` | 24,07 MiB | 128 MB | ok. 0,9–1,1% |
| `aip-ingest` | 27,75 MiB | 128 MB | ok. 1% (skoki do 16–27%: healthcheck `python -m …health` co 10 s) |
| `aip-timescaledb` | 54,5 MiB | 1,5 GiB | 0,5% |
| `aip-mosquitto` | 2,06 MiB | 64 MB | 1,7% |

`free -m`: used 1457 MB, available 13 724 MB, swap 0; `df -h /`: 20 GB zajęte (3%), wolne 871 GB. smartWARE bez zmian (ok. 515 MiB razem). Suma limitów `aip-`: 1856 MB (w użyciu ok. 110 MiB).
Zapis paczki ingestu na prawdziwej bazie (NVMe, `fsync` włączony): średnio **12,5–17,6 ms**, maks. **25,5 ms** w stanie ustalonym (74,8 ms w pierwszej minucie), ok. 40 paczek na minutę. Czas cyklu collectora wyznaczony pośrednio: odstępy
`link_status` 1,000 s (0,984–1,016); collector nie loguje własnego czasu cyklu (K5-a).

Dane: 18 656 wierszy, hypertable 3632 kB (1 kawałek, z indeksami, bez kompresji): **ok. 199 bajtów na wiersz**. Przy 13 wierszach na sekundę to ok. 1,12 mln wierszy (ok. 224 MB) na dobę przed kompresją. Kompresja po 1 dniu
i rozmiar po dobie: pomiar w k8 (nie mierzone).

## Tak wygląda poprawny stan (do dokumentacji)

`docker compose ps -a`:

```text
NAME              STATUS                      PORTS
aip-collector     Up 12 minutes (healthy)     
aip-ingest        Up 5 hours (healthy)        
aip-migrate       Exited (0) 29 minutes ago   
aip-mosquitto     Up 15 minutes (healthy)     127.0.0.1:1883->1883/tcp
aip-timescaledb   Up 7 hours (healthy)        5432/tcp
```

Jedna pełna sekunda w bazie (13 wierszy, `source` = `real`):

```text
 czas         | metryka                         | value      | unit
 23:08:12.161 | plc-01/link_status              | 0          |
 23:08:12.161 | finder_7m24_1/meter_status      | 0          |
 23:08:12.161 | finder_7m24_1/meter_error_count | 58         |
 23:08:12.161 | finder_7m24_1/meter_data_age_ms | 0          | ms
 23:08:12.161 | finder_7m24_1/voltage           | 238.7      | V
 23:08:12.161 | finder_7m24_1/active_power      | 7.1        | W
 23:08:12.161 | finder_7m24_1/reactive_power    | -8.7       | var
 23:08:12.161 | finder_7m24_1/apparent_power    | 19.1       | VA
 23:08:12.161 | finder_7m24_1/power_factor      | 0.3724     |
 23:08:12.161 | finder_7m24_1/frequency         | 49.99      | Hz
 23:08:12.161 | finder_7m24_1/current           | 0.08000001 | A
 23:08:12.161 | finder_7m24_1/energy_import_wh  | 3600       | Wh
 23:08:12.161 | finder_7m24_1/energy_export_wh  | 0          | Wh
```

Log collectora w stanie ustalonym (trzy wpisy startu): `start: PLC 192.168.0.246:502 (FC04, rejestry 0-43), temat zaklad1/linia1/<urządzenie>/<metryka>`, `MQTT: połączono z mosquitto:1883`, `plc: (start) -> OK`
i `meter:finder_7m24_1: (start) -> OK`; potem wpisy tylko przy zmianie stanu licznika (epizody co 64 s: `OK -> COMM_ERROR`, 4 s później `COMM_ERROR -> OK`). Podsumowanie ingestu co 60 s, np.
`odebrane=780 zapisane=781 duplikaty=0 rejected=0 paczki=40 zapis_ms_sr=16.6 zapis_ms_maks=20.8 oczekujące=0 baza=OK`. Wartość `current` 0,08000001 pochodzi z konwersji float32 i jest zapisana wiernie (7 cyfr znaczących).
Łącznie w bazie po k5: 13 różnych metryk, 0 duplikatów.

## Odstępstwa od planu i dlaczego

1. **Kryterium liczby wierszy** zinterpretowane przez model 13/4 wierszy na sekundę (zgodny w 100% minut), bo cykliczny błąd licznika (U-1) uniemożliwia 780 w każdej minucie. Wynik literalny zapisałem w tabeli kryteriów jako niespełniony.
2. **Czasy testów fizycznych dłuższe niż w planie** (RS485 52 s zamiast 10 s, LAN1 94 s zamiast 30 s): ludzkie opóźnienie między „TERAZ” a potwierdzeniem. Czasy wyznaczyłem z danych (K5-b).
3. **Dodatkowa diagnostyka** (collector zatrzymany 22:53:44–22:55:35), której nie było w planie: wynikała z ustalenia U-1 i miała rozstrzygnąć, czy błąd nie pochodzi od collectora. Okno zapisane w tabeli (K5-U3, rodzaj `collector_stopped`).
4. **Kolejność** (K5-U4): start, 10 minut spokoju, restart brokera, RS485, LAN1, Stop. Dodatkowo między restartem brokera a RS485 wstawiłem diagnostykę z zatrzymanym collectorem (odstępstwo 3), żeby wiedzieć, czy błąd licznika
   nie pochodzi od collectora, zanim zawołałem Grzegorza. Odstępy stabilnej pracy między testami (wymóg: co najmniej 1 minuta): restart brokera → diagnostyka 1,5 min, diagnostyka → RS485 1,0 min (collector wrócił 22:55:37, RS485 od 22:56:35),
   RS485 (koniec 22:57:27) → LAN1 (początek 22:58:59) 1,5 min, LAN1 (koniec 23:00:33) → Stop (początek 23:03:39) 3 min.
5. **Trzy zerwania sesji SSH** (laptop → komputer, „Connection reset by peer”): polecenia powtórzone, dane nieuszkodzone; skrypty w tle uruchamiane przez `setsid` nie ucierpiały. Komputer nie restartował się (uptime 14 h w momencie pierwszego zerwania).
6. **Zdjęcia opcjonalne** (`docs/images/etap2/30-…`) nie zostały dostarczone.

## Uwagi K5-U1…U5

- **K5-U1:** w komunikatach „TERAZ” podawałem wprost **LAN1 (do switcha), nie LAN2**; odłączony był LAN1 (zmierzone `ping` bez odpowiedzi, powrót po podłączeniu).
- **K5-U2:** Stop wykonany za zgodą; użyty tylko Stop i Start; PLC wrócił do RUN; bez downloadu ani resetu.
- **K5-U3:** tabela okien wyżej (UTC).
- **K5-U4:** kolejność z drobną zmianą (odstępstwo 4).
- **K5-U5:** heartbeat ok. 5,0/s zapisany jako fakt; pojedynczy „stary” pomiar na początku przerwy RS485 nie wystąpił.

## Checklista dla Grzegorza

Wykonane trzy czynności fizyczne (RS485, LAN1, Stop i Start). Brak dalszych czynności. Zdjęcia (opcjonalne) nie były wymagane.

## Otwarte kwestie i propozycje

- **U-1 (priorytet):** cykliczny błąd PLC–licznik co 64 s (4 s bez pomiarów, ok. 4,7% czasu w oknie referencyjnym). Przyczyna po stronie PLC, okablowania lub licznika; do diagnozy przez architekta i Grzegorza.
  Wpływa na wszystkie późniejsze etapy (koszty energii, anomalie), więc warto rozstrzygnąć przed etapem 4.
- **U-2:** luki w `link_status` podczas awarii (poprawka kodu collectora do decyzji).
- **U-3:** dopisać do `docs/status-codes.md`, że Stop programu objawia się kodem 1; kod 2 pozostaje tylko dla zamrożonego heartbeatu przy odpowiadającym serwerze (niewidziany na prawdziwym PLC).
- **U-4:** wyciszenie loggera `pymodbus` (poprawka kodu do decyzji).
- **Do k6/k7/k8:** rozmiar po dobie i kompresja (k8); restart komputera i autostart całego stosu, w tym collector i ingest (k8); agregaty i widoki energii (k6), w których epizody licznika trzeba uwzględnić w całce mocy
  (luki 4 s); Grafana (k7) z kafelkiem stanu licznika uwzględniającym `link_status` (K3-U3) i `maxOpenConns` ok. 5 (K2-U5).
- Wiersze z testów fizycznych i diagnostyki zostają w bazie (K5-g); okna do wyłączenia z analityki w tabeli wyżej.
