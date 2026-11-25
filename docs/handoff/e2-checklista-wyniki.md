# E2 – checklista etapu 2: surowe wyniki poleceń

Data wykonania: 2026-11-25, 13:46–13:47 UTC (14:46–14:47 czasu lokalnego). Polecenia wykonał Claude Code na decyzję Grzegorza (tylko odczyty, bez sudo, bez zmian w systemie, bez harnessu na produkcji, bez czytania `.env`). Pod każdym numerem punktu z `docs/stages/etap-2.md` jest **surowy, pełny wydruk polecenia (bez skracania)**, a pod nim krótkie podsumowanie faktów. Podsumowania nie oceniają stanu punktu: oceniają Grzegorz i architekt.

Nie wykonane dziś (zgodnie z poleceniem): punkty 2, 12, 13, 15, 16 (wejdą do części B: pamięć po dobie, pełne testy, kompresja). Punkty 8 i 14 są już zaliczone (zrzuty, test restartu).

Komputer: `jumo-ipc`, katalog repo `~/ai-predykcja`. Zapytania SQL: `docker exec aip-timescaledb psql -U postgres -d energy`.

## Punkt 1

`cd ~/ai-predykcja && docker compose ps` (na komputerze `jumo-ipc`)

```text
date -u: 2026-11-25T13:46:50Z
$ cd ~/ai-predykcja && docker compose ps
NAME              IMAGE                                                                                                       COMMAND                  SERVICE       CREATED       STATUS                 PORTS
aip-collector     aip-collector:local                                                                                         "python -m collector…"   collector     2 hours ago   Up 2 hours (healthy)   
aip-grafana       grafana/grafana-oss:13.0.2@sha256:5dad0df181cb644a14e13617b913b261a54f7d4fd4510721dba420929f35bea2          "/run.sh"                grafana       2 hours ago   Up 2 hours (healthy)   0.0.0.0:3000->3000/tcp, :::3000->3000/tcp
aip-ingest        aip-ingest:local                                                                                            "python -m ingest.ma…"   ingest        2 hours ago   Up 2 hours (healthy)   
aip-mosquitto     eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9            "/bin/sh /mosquitto/…"   mosquitto     2 hours ago   Up 2 hours (healthy)   127.0.0.1:1883->1883/tcp
aip-timescaledb   timescale/timescaledb:2.32.1-pg16@sha256:5d7a2f9d9d593315368338aa6054fda37d7707b4a12a912e30dcb7523385e2b4   "docker-entrypoint.s…"   timescaledb   2 hours ago   Up 2 hours (healthy)   5432/tcp
```

**Podsumowanie (bez oceny):** Pięć kontenerów `aip-*` w stanie Up (healthy), każdy utworzony „2 hours ago”. Nie ma wiersza `aip-migrate` (kontener jednorazowy, `restart: no`, zakończony; `docker compose ps` bez `-a` pokazuje tylko działające). Porty opublikowane: Grafana 3000 (wszystkie interfejsy), Mosquitto 127.0.0.1:1883; baza bez opublikowanego portu.

## Punkt 3

`ss -ltn` (na komputerze `jumo-ipc`)

```text
date -u: 2026-11-25T13:46:50Z
$ ss -ltn
State  Recv-Q Send-Q Local Address:Port Peer Address:PortProcess
LISTEN 0      128        127.0.0.1:631       0.0.0.0:*          
LISTEN 0      4096       127.0.0.1:1883      0.0.0.0:*          
LISTEN 0      4096   127.0.0.53%lo:53        0.0.0.0:*          
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*          
LISTEN 0      4096         0.0.0.0:80        0.0.0.0:*          
LISTEN 0      4096         0.0.0.0:443       0.0.0.0:*          
LISTEN 0      4096         0.0.0.0:3000      0.0.0.0:*          
LISTEN 0      128            [::1]:631          [::]:*          
LISTEN 0      128             [::]:22           [::]:*          
LISTEN 0      4096            [::]:80           [::]:*          
LISTEN 0      4096            [::]:443          [::]:*          
LISTEN 0      4096            [::]:3000         [::]:*          
```

**Podsumowanie (bez oceny):** Nasłuch TCP: 22 (SSH), 80 i 443 (smartWARE), 631 (127.0.0.1 i ::1), 53 (127.0.0.53), 1883 tylko na 127.0.0.1 oraz 3000 na wszystkich interfejsach. Port bazy (5432) nie nasłuchuje na hoście. Z portów aip-* nowe są tylko 1883 (lokalnie) i 3000.

## Punkt 4

`docker exec aip-timescaledb psql -U postgres -d energy -c "SELECT version, name FROM schema_migrations ORDER BY 1"`

```text
date -u: 2026-11-25T13:46:50Z
$ docker exec aip-timescaledb psql -U postgres -d energy -c "SELECT version, name FROM schema_migrations ORDER BY 1"
 version |                   name                    
---------+-------------------------------------------
       1 | 001_core.sql
       2 | 002_energy_aggregates.sql
       3 | 003_energy_views.sql
       4 | 004_data_windows.sql
       5 | 005_data_windows_plc_program_download.sql
       6 | 006_data_windows_plc1_download.sql
       7 | 007_energy_ext_aggregates.sql
       8 | 008_energy_ext_views.sql
       9 | 009_energy_1h_first_last_filter.sql
      10 | 010_data_windows_plc2_download.sql
      11 | 011_data_windows_ipc_reboot.sql
(11 rows)
```

**Podsumowanie (bez oceny):** 11 wierszy, wersje 1–11, od `001_core.sql` do `011_data_windows_ipc_reboot.sql`.

## Punkt 5

na laptopie: `git ls-files | findstr /i ".env"`

```text
2026-11-25T13:47:05Z
> git ls-files | findstr /i ".env"
.env.example
exit=0
```

**Podsumowanie (bez oceny):** Jedyny plik śledzony przez git, którego nazwa zawiera „.env”: `.env.example`. Plik `.env` nie jest w repo.

## Punkt 6

`mbpoll -m tcp -a 1 -t 3:float -B -0 -r 16 -c 9 -1 192.168.0.246` i od razu potem zapytanie do bazy

```text
date -u: 2026-11-25T13:46:50Z
$ mbpoll -m tcp -a 1 -t 3:float -B -0 -r 16 -c 9 -1 192.168.0.246
mbpoll 1.0-0 - FieldTalk(tm) Modbus(R) Master Simulator
Copyright © 2015-2019 Pascal JEAN, https://github.com/epsilonrt/mbpoll
This program comes with ABSOLUTELY NO WARRANTY.
This is free software, and you are welcome to redistribute it
under certain conditions; type 'mbpoll -w' for details.

Protocol configuration: Modbus TCP
Slave configuration...: address = [1]
                        start reference = 16, count = 9
Communication.........: 192.168.0.246, port 502, t/o 1.00 s, poll rate 1000 ms
Data type.............: 32-bit float (big endian), input register table

-- Polling slave 1...
[16]: 	7
[18]: 	-8.7
[20]: 	19.2
[22]: 	0.364
[24]: 	50
[26]: 	238.7
[28]: 	0.08
[30]: 	3.8
[32]: 	0

date -u: 2026-11-25T13:46:50Z
$ SELECT metric, value, time FROM measurements WHERE time > now() - interval '3 s' AND metric IN ('voltage','active_power') ORDER BY time DESC LIMIT 4
    metric    | value |            time            
--------------+-------+----------------------------
 active_power |   7.1 | 2026-11-25 13:46:49.158+00
 voltage      | 238.9 | 2026-11-25 13:46:49.158+00
 active_power |   7.1 | 2026-11-25 13:46:48.16+00
 voltage      | 238.9 | 2026-11-25 13:46:48.16+00
(4 rows)
```

**Podsumowanie (bez oceny):** Odczyt mbpoll (rejestry 16–33, float, nazwy wg `docs/modbus-map.md`): P = 7 W, Q = −8,7 var, S = 19,2 VA, PF = 0,364, f = 50 Hz, U = 238,7 V, I = 0,08 A, energia czynna importowana n1 = 3,8 kWh, eksportowana n3 = 0 kWh. W bazie próbka z 13:46:49,158 UTC (poprzednia sekunda względem wywołania mbpoll): U = 238,9 V, P = 7,1 W. Różnice: U o 0,2 V, P o 0,1 W. mbpoll to drugi klient Modbus TCP obok collectora, tylko odczyt FC04, nic nie zapisuje do PLC.

## Punkt 7

rozkład wierszy na sekundę z ostatnich 10 minut (zapytanie z `etap-2.md`)

```text
date -u: 2026-11-25T13:46:51Z
$ SELECT n, count(*) FROM (SELECT time_bucket('1 s', time) s, count(*) n FROM measurements WHERE time > now() - interval '10 minutes' AND time < now() - interval '10 s' GROUP BY 1) t GROUP BY n ORDER BY 2 DESC
 n  | count 
----+-------
 20 |   590
(1 row)
```

**Podsumowanie (bez oceny):** W 590 z 590 pełnych sekund okna (13:36:51–13:46:41 UTC) po 20 wierszy; żadnej sekundy z inną liczbą.

## Punkt 9

`SELECT * FROM energy_daily_check ORDER BY 1 DESC LIMIT 3` (z przełącznikiem `psql -x`, patrz uwaga pod wydrukiem)

```text
date -u: 2026-11-25T13:46:51Z
$ SELECT * FROM energy_daily_check ORDER BY 1 DESC LIMIT 3
-[ RECORD 1 ]------------+---------------------
device_id                | finder_7m24_1
day                      | 2026-11-25
integral_wh              | 103.98177777777781
coverage                 | 0.6133101851851852
counter_delta_wh         | 100
integral_extrapolated_wh | 169.5419060200038
diff_wh                  | 69.54190602000381
resolution_wh            | 100
within_resolution        | t
deviation_pct            | 
day_complete             | f
gap_before_count         | 0
reset_count              | 0
-[ RECORD 2 ]------------+---------------------
device_id                | finder_7m24_1
day                      | 2026-11-23
integral_wh              | 2.0133333333333336
coverage                 | 0.011828703703703704
counter_delta_wh         | 0
integral_extrapolated_wh | 
diff_wh                  | 
resolution_wh            | 100
within_resolution        | 
deviation_pct            | 
day_complete             | t
gap_before_count         | 0
reset_count              | 0
-[ RECORD 3 ]------------+---------------------
device_id                | finder_7m24_1
day                      | 2026-11-24
integral_wh              | 112.8286388888889
coverage                 | 0.6681481481481482
counter_delta_wh         | 100
integral_extrapolated_wh | 168.8676967849224
diff_wh                  | 68.8676967849224
resolution_wh            | 100
within_resolution        | t
deviation_pct            | 
day_complete             | t
gap_before_count         | 1
reset_count              | 0
```

**Podsumowanie (bez oceny):** Trzy ostatnie rekordy z widoku (dla jedynego licznika z danymi `finder_7m24_1`): doby 25.11, 23.11 i 24.11. Zgodnie z poleceniem sortowanie jest po kolumnie 1 (`device_id`), a nie po dobie, więc kolejność dób nie jest chronologiczna (widok ma 3 doby danych, więc `LIMIT 3` zwrócił wszystkie). 25.11: całka 103,98 Wh, pokrycie 0,613, przyrost licznika 100 Wh, ekstrapolacja 169,54 Wh, `within_resolution = t`, doba niezakończona. 24.11: całka 112,83 Wh, pokrycie 0,668, przyrost licznika 100 Wh, ekstrapolacja 168,87 Wh, `within_resolution = t`, doba zakończona, `gap_before_count = 1`. 23.11: pokrycie 0,0118 doby (ok. 17 minut danych), brak ekstrapolacji. `reset_count = 0` we wszystkich. `deviation_pct` puste (przyrost poniżej 5 kroków licznika).

## Punkt 10

`SELECT kind, start_time, end_time FROM data_windows ORDER BY start_time`

```text
date -u: 2026-11-25T13:46:51Z
$ SELECT kind, start_time, end_time FROM data_windows ORDER BY start_time
         kind         |         start_time         |          end_time          
----------------------+----------------------------+----------------------------
 collector_start      | 2026-11-23 22:38:25+00     | 2026-11-23 22:38:26+00
 calm_window          | 2026-11-23 22:41:00+00     | 2026-11-23 22:51:00+00
 mqtt_broker_restart  | 2026-11-23 22:52:14+00     | 2026-11-23 22:52:26+00
 collector_stopped    | 2026-11-23 22:53:44+00     | 2026-11-23 22:55:37+00
 rs485_break          | 2026-11-23 22:56:35+00     | 2026-11-23 22:57:27+00
 plc_lan1_unplugged   | 2026-11-23 22:58:59+00     | 2026-11-23 23:00:33+00
 plc_program_stop     | 2026-11-23 23:03:39+00     | 2026-11-23 23:05:25+00
 power_outage         | 2026-11-23 23:16:57.132+00 | 2026-11-24 06:52:43.248+00
 collector_stopped    | 2026-11-24 11:03:53.043+00 | 2026-11-24 11:18:57.442+00
 plc_program_download | 2026-11-24 14:25:03.39+00  | 2026-11-24 14:25:20.392+00
 deploy               | 2026-11-24 14:33:59+00     | 2026-11-24 14:34:30+00
 plc_program_download | 2026-11-25 08:16:10.574+00 | 2026-11-25 08:16:18.577+00
 plc_program_download | 2026-11-25 10:43:01.518+00 | 2026-11-25 10:43:09.521+00
 ipc_reboot           | 2026-11-25 12:03:47.557+00 | 2026-11-25 12:04:24.705+00
(14 rows)
```

**Podsumowanie (bez oceny):** 14 okien: rodzaje `collector_start`, `calm_window`, `mqtt_broker_restart`, `collector_stopped` ×2, `rs485_break`, `plc_lan1_unplugged`, `plc_program_stop`, `power_outage`, `plc_program_download` ×3, `deploy` i `ipc_reboot`. Trzy okna `plc_program_download`: 24.11 14:25:03–14:25:20, 25.11 08:16:10–08:16:18 oraz 25.11 10:43:01–10:43:09 (UTC).

## Punkt 11

adnotacje z API Grafany dla zakresu 24.11.2026 14:15–14:35 UTC (tylko GET)

```text
date -u: 2026-11-25T13:46:51Z
$ GET /api/annotations?from=<2026-11-24T14:15:00Z>&to=<2026-11-24T14:35:00Z>  (przez docker exec aip-grafana, uwierzytelnienie wewnatrz kontenera)
HTTP 200 from_ms 1795529700000 to_ms 1795530900000
[]
--- GET /api/dashboards/uid/aip-jakosc: sekcja annotations (definicja adnotacji dashboardu)
HTTP 200
{
  "list": [
    {
      "datasource": {
        "type": "grafana-postgresql-datasource",
        "uid": "aip-timescaledb"
      },
      "enable": true,
      "iconColor": "rgba(255, 152, 48, 0.6)",
      "name": "Okna testów i przerw",
      "target": {
        "datasource": {
          "type": "grafana-postgresql-datasource",
          "uid": "aip-timescaledb"
        },
        "editorMode": "code",
        "format": "table",
        "rawQuery": true,
        "rawSql": "SELECT start_time AS time, end_time AS \"timeEnd\", kind AS tags, description AS text FROM data_windows WHERE start_time <= $__timeTo() AND end_time >= $__timeFrom() ORDER BY start_time",
        "refId": "Anno"
      }
    }
  ]
}
--- odpowiednik w bazie (to samo zapytanie, ktore dashboard wykonuje jako adnotacje; odczyt SELECT)
$ SELECT start_time AS time, end_time AS "timeEnd", kind AS tags, description AS text FROM data_windows WHERE start_time <= '2026-11-24 14:35:00+00' AND end_time >= '2026-11-24 14:15:00+00' ORDER BY start_time
           time            |          timeEnd           |         tags         |                              text                              
---------------------------+----------------------------+----------------------+----------------------------------------------------------------
 2026-11-24 14:25:03.39+00 | 2026-11-24 14:25:20.392+00 | plc_program_download | Download programu PLC (Grzegorz), reset liczników FB
 2026-11-24 14:33:59+00    | 2026-11-24 14:34:30+00     | deploy               | Wdrożenie k6: restart collectora i ingestu, migracje 002 i 003
(2 rows)
```

**Podsumowanie (bez oceny):** `GET /api/annotations` dla zakresu zwrócił `[]` (HTTP 200): adnotacje dashboardów w tym projekcie nie są zapisane w magazynie adnotacji Grafany, tylko pochodzą z zapytania SQL do źródła danych (definicja w sekcji `annotations` dashboardu, pokazana wyżej z `GET /api/dashboards/uid/aip-jakosc`: „Okna testów i przerw”, zapytanie do `data_windows`). Dlatego dołączyłem to samo zapytanie wykonane w bazie dla tego zakresu (odczyt `SELECT`): zwraca `plc_program_download` (24.11 14:25:03,39–14:25:20,392 UTC, „Download programu PLC (Grzegorz), reset liczników FB”) i `deploy` (14:33:59–14:34:30). Nie wykonywałem `POST /api/ds/query` (nie jest GET), więc wynik zapytania przez Grafanę nie jest tu pokazany; widać go na zrzutach dashboardów.

## Uwagi o wykonaniu

- Punkt 9: polecenie uruchomione z dodatkowym przełącznikiem `psql -x` (wydruk rozszerzony, bo widok ma 13 kolumn); zapytanie bez zmian.
- Punkt 11: `GET /api/annotations` wywołane przez `docker exec aip-grafana` (uwierzytelnienie wewnątrz kontenera, hasło nie opuszcza kontenera, nie występuje w wydruku). Dodatkowo `GET /api/dashboards/uid/aip-jakosc` (tylko sekcja `annotations`) i odpowiednik SQL w bazie.
- Punkt 6: `mbpoll` to odczyt rejestrów wejściowych (FC04), jak collector; nic nie zapisuje do PLC.
- Znaczniki `date -u` w wydrukach to czas UTC polecenia (wszystkie punkty w ciągu 15 sekund).
