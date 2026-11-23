# Kody statusów: `link_status` i `meter_status`

Collector publikuje dwie metryki stanu jako liczby (jednostka pusta). Źródłem prawdy w kodzie są enumy w
`services/collector/src/collector/status.py`; test sprawdza, że ten dokument opisuje te same kody. Kolumna „Komunikat”
to polskie tłumaczenie dla Grafany (krok k7).

## `link_status` (urządzenie `plc-01`): stan łącza z PLC

| Kod | Nazwa (enum) | Kiedy | Komunikat |
| --- | --- | --- | --- |
| 0 | `OK` | odczyt udany, `map_version` zgodna, heartbeat się zmienia | PLC działa |
| 1 | `PLC_OFFLINE` | brak połączenia TCP, timeout, błąd Modbus, krótka odpowiedź | PLC offline |
| 2 | `PLC_STOPPED` | heartbeat bez zmiany dłużej niż `heartbeat_timeout_s` (5 s) | PLC zatrzymany |
| 3 | `MAP_VERSION_MISMATCH` | rejestr `map_version` inny niż oczekiwany w `devices.yaml` | Błąd konfiguracji: zła wersja mapy rejestrów |

Przy `link_status` ≠ 0 collector nie publikuje żadnych pomiarów ani `meter_status` (rejestry licznika są wtedy nieważne
lub zamrożone). Stan jest publikowany w **każdym cyklu** (co 1 s), więc „ostatnia wartość” jest zawsze świeża.

## `meter_status` (urządzenie licznika, np. `finder_7m24_1`): stan licznika

Publikowany tylko przy `link_status` = 0. Kody 0–2 są kopiowane z rejestru PLC, kod 10 liczy collector.

| Kod | Nazwa (enum) | Kiedy | Komunikat |
| --- | --- | --- | --- |
| 0 | `OK` | status licznika w PLC = 0 i numer seryjny zgodny z `devices.yaml` | Licznik działa |
| 1 | `COMM_ERROR` | PLC zgłasza błąd komunikacji z licznikiem (RS485) | Licznik: błąd komunikacji |
| 2 | `NO_DATA` | licznik nie odpowiedział od startu PLC | Licznik: brak danych (start PLC) |
| 10 | `SERIAL_MISMATCH` | status = 0, ale numer seryjny pod blokiem inny niż w `devices.yaml` | Błąd konfiguracji: inny licznik niż w konfiguracji |

Inna wartość rejestru statusu niż 0–2 jest publikowana surowo (widoczna w bazie), a collector zapisuje ostrzeżenie w logu;
pomiary nie są wtedy publikowane. Pomyłka w jednym liczniku (kod 10) nie blokuje pozostałych liczników.

Status licznika jest oceniany **przed** numerem seryjnym: przy `NO_DATA` rejestry numeru seryjnego są puste, więc odwrotna
kolejność zgłaszałaby fałszywy kod 10.

## Zachowanie w czasie (do dokumentacji i do interpretacji wykresów)

| Zdarzenie | Czas | Skutek na wykresach |
| --- | --- | --- |
| Start PLC: licznik jeszcze nie odpowiedział (`NO_DATA`) | do ok. 10 s po starcie PLC | `meter_status` = 2, brak pomiarów licznika |
| Przerwa RS485 (odłączony przewód) | od pierwszego błędu | `meter_status` = 1, `meter_data_age_ms` rośnie, `meter_error_count` +1 na przerwę |
| Koniec przerwy RS485 | PLC wraca do statusu 0 dopiero po **3 s** bez błędu (filtr w PLC) | pomiarów brak jeszcze ok. 3 s po podłączeniu przewodu |
| Połączenie collectora z PLC (start lub powrót po awarii) | ok. 1 s (collector czeka na pierwszą zmianę heartbeatu) | pierwsze pomiary z opóźnieniem ok. 1 s; chroni przed zapisaniem zamrożonych rejestrów zatrzymanego PLC |
| PLC wyłączony lub odłączony od sieci | wykrycie w czasie krótszym niż `timeout_s` + 1 s | `link_status` = 1 w każdym cyklu, bez pomiarów |
| PLC zatrzymany, ale serwer Modbus nadal odpowiada | 5 s bez zmiany heartbeatu | `link_status` = 2 |

W cyklu rozgrzewki (ok. 1 s po połączeniu collectora z PLC, do pierwszej zmiany heartbeatu) collector nie publikuje niczego,
także `link_status`: „0” byłoby deklaracją sprawności bez zweryfikowanych danych, a „2” fałszywym alarmem. Przez ten czas panel
pokazuje poprzedni stan (zwykle `link_status` = 1 z poprzedniej awarii). Jeśli heartbeat nie zmieni się przez 5 s, pojawia się
`link_status` = 2.

Heartbeat rośnie ok. 6 razy na sekundę, więc próg 5 s jest z dużym zapasem. `meter_error_count` jest licznikiem 16-bitowym
(po 65535 wraca do 0), a `meter_data_age_ms` przy `NO_DATA` (wartość `FFFFFFFF`) nie jest publikowane.
