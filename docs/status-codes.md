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
lub zamrożone). Stan jest publikowany w **każdym cyklu** (co 1 s) także podczas awarii, w której odczyt się zawiesza (odczyt PLC działa w tle),
więc „ostatnia wartość” jest zawsze świeża. Wyjątek: cykle rozgrzewki (niżej) i wolna odpowiedź krótsza niż `timeout_s`.

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

## `meter_error_code` (urządzenie licznika): kod błędu komunikacji PLC-licznik

Kod z rejestru `error_code` bloku licznika (offset 1; opis w `docs/modbus-map.md`). Collector go **interpretuje tylko wtedy,
gdy `meter_status` ≠ 0**: publikuje wtedy metrykę `meter_error_code` (liczba, jednostka pusta) i zapisuje w logu kod
z nazwą, **raz przy każdej zmianie kodu**. Przy `meter_status` = 0 kod jest nieważny (PLC może trzymać stary), więc nie jest
ani publikowany, ani logowany. Przy `SERIAL_MISMATCH` (status 0) kodu też nie ma.

Nazwy znanych kodów pochodzą z dokumentacji CODESYS `MB_ErrorCodes` (biblioteka IoDrvModbus, helpme-codesys.com);
źródło zweryfikowane przez architekta 24.11.2026. Kod spoza tablicy jest podawany tylko liczbowo (dziesiętnie i szesnastkowo).

| Kod | Szesnastkowo | Nazwa | Znaczenie |
| --- | --- | --- | --- |
| 161 | `0xA1` | `RESPONSE_TIMEOUT` | licznik nie odpowiedział w czasie |
| 162 | `0xA2` | `RESPONSE_CRC_FAIL` | odpowiedź z błędną sumą CRC |
| 163 | `0xA3` | `RESPONSE_WRONG_SLAVE` | odpowiedź od innego adresu niż zapytany |

Przykład wpisu w logu collectora: `meter:finder_7m24_1: OK -> COMM_ERROR (error_code=162, 0xA2, RESPONSE_CRC_FAIL)`.
Test `tests/collector/test_status_doc.py` sprawdza, że ta tabela zgadza się z `ERROR_CODE_NAMES` w kodzie.

## Liczba wierszy na sekundę (model do planowania pojemności)

| Stan | Wiersze na sekundę | Skład |
| --- | --- | --- |
| Wszystko sprawne, mapa v1 | **13** | `link_status` + 12 wierszy licznika (`meter_status`, `meter_error_count`, `meter_data_age_ms`, 7 pomiarów, 2 liczniki energii) |
| Wszystko sprawne, mapa v2 | **20** | jak wyżej + 7 wierszy mapy v2: `reactive_pos_varh`, `reactive_neg_varh`, `thd_voltage`, `thd_current`, `phase_angle`, `meter_temperature`, `run_time` (wszystkie co 1 s) |
| `meter_status` ≠ 0 (v1 i v2) | **5** | `link_status` + `meter_status`, `meter_error_count`, `meter_data_age_ms` (jeśli ≠ `FFFFFFFF`), `meter_error_code` |
| PLC niedostępny (`link_status` ≠ 0) | **1** | tylko `link_status` |

Przy `meter_data_age_ms` = `FFFFFFFF` (`NO_DATA`) wierszy jest o jeden mniej. Nowe wartości mapy v2 są publikowane **tylko przy `meter_status` = 0**
(te same reguły ważności co pomiary v1; zamrożone wartości nie są zapisywane). Przy 13 wierszach na sekundę dzienny przyrost to ok. 1,1 mln wierszy, przy 20 na sekundę
ok. 1,7 mln (1 728 000); zmierzone rozmiary są w `docs/data-model.md`. Wartość mapy v2 spoza zakresu `valid_range` z `config/devices.yaml` (filtr wiarygodności,
nie dane katalogowe) nie jest publikowana, a collector zapisuje WARNING raz na zmianę stanu.

## Zachowanie w czasie (do dokumentacji i do interpretacji wykresów)

| Zdarzenie | Czas | Skutek na wykresach |
| --- | --- | --- |
| Start PLC: licznik jeszcze nie odpowiedział (`NO_DATA`) | do ok. 10 s po starcie PLC | `meter_status` = 2, brak pomiarów licznika |
| Przerwa RS485 (odłączony przewód) | od pierwszego błędu | `meter_status` = 1, `meter_data_age_ms` rośnie, `meter_error_count` +1 na przerwę |
| Koniec przerwy RS485 | PLC wraca do statusu 0 dopiero po **3 s** bez błędu (filtr w PLC) | pomiarów brak jeszcze ok. 3 s po podłączeniu przewodu |
| Połączenie collectora z PLC (start lub powrót po awarii) | ok. 1 s (collector czeka na pierwszą zmianę heartbeatu) | pierwsze pomiary z opóźnieniem ok. 1 s; chroni przed zapisaniem zamrożonych rejestrów zatrzymanego PLC |
| PLC wyłączony lub odłączony od sieci (także „czarna dziura”: połączenie TCP, które nie odpowiada) | wykrycie po `timeout_s` (2 s) + najwyżej jeden okres | `link_status` = 1 w każdym cyklu, bez pomiarów; odczyt w tle jest porzucany po 3 x `timeout_s`, a po powrocie PLC collector wraca do OK bez restartu |
| Pojedyncza wolna odpowiedź sprawnego PLC (dłuższa niż okres, krótsza niż `timeout_s`) | do `timeout_s` | cykl bez publikacji, bez `link_status` = 1 i bez rozgrzewki |
| PLC zatrzymany, ale serwer Modbus nadal odpowiada | 5 s bez zmiany heartbeatu | `link_status` = 2 |

W cyklu rozgrzewki (ok. 1 s po połączeniu collectora z PLC, do pierwszej zmiany heartbeatu) collector nie publikuje niczego,
także `link_status`: „0” byłoby deklaracją sprawności bez zweryfikowanych danych, a „2” fałszywym alarmem. Przez ten czas panel
pokazuje poprzedni stan (zwykle `link_status` = 1 z poprzedniej awarii). Jeśli heartbeat nie zmieni się przez 5 s, pojawia się
`link_status` = 2.

Heartbeat rośnie ok. 6 razy na sekundę, więc próg 5 s jest z dużym zapasem. `meter_error_count` jest licznikiem 16-bitowym
(po 65535 wraca do 0), a `meter_data_age_ms` przy `NO_DATA` (wartość `FFFFFFFF`) nie jest publikowane.
