# e2-k4 raport: ingest (MQTT → walidacja → paczki → baza)
Status: DO PRZEGLĄDU

Wykonanie 23.11.2026 wg `e2-k4-plan.md` i uwag K4-U1…U4 z `e2-k4-review.md`. Polecenia na `jumo-ipc` wykonywałem przez
`ssh jumo@192.168.0.213` (Git Bash, `bash -s`, `</dev/null`), bez `sudo`, bez ruszania smartWARE, demona Dockera ani `docker system prune`.
**Nic nie łączyło się z PLC ani z licznikiem.** `.env` nie był czytany ani wypisywany. Raport nie zawiera sekretów.

## Co zrobiono

| Hash | Zawartość |
| --- | --- |
| `dd286b7` | review k4 |
| `e3f7f73` | ingest, testy, usługa w Compose, zdanie o rozgrzewce w `docs/status-codes.md` |

Pliki: `services/ingest/` (`Dockerfile`, `requirements.txt`, `src/ingest/`: `main`, `config`, `validate`, `store`, `pipeline`, `mqtt_in`, `health`),
`docker-compose.yml` (usługa `ingest`), `docker-compose.test.yml`, `tests/ingest/` (9 plików), `docs/status-codes.md`, `docs/ops/jumo-ipc-setup.md`.
Raport i zmiany `docs/ops` idą w commicie po tym raporcie.

## Wyniki testów

Polecenie na komputerze: `sh tests/run-tests.sh -s </dev/null` (projekt `aip-test`, dane w tmpfs, prawdziwy Mosquitto i prawdziwa baza).

**`257 passed in 157.65s`** za pierwszym uruchomieniem na komputerze (k3: 136; nowe: 121). Rozkład nowych testów ingestu: walidacja 59, potok 18,
parser configu 11, usługa w Compose 8, e2e 7, synchronizacja `devices` 6, odporność 6, brak danych w kodzie 6. Po testach nie zostały zasoby `aip-test`.
Lokalnie na laptopie przed wypchnięciem: 193 przeszło, 27 pominiętych (testy wymagające bazy i brokera).

### Błąd znaleziony przez testy (poprawiony przed pierwszym uruchomieniem na komputerze)

Test jednostkowy potoku wykazał, że po zapisie „po jednym wierszu” (izolacja przy naruszeniu ograniczenia lub braku wiersza w `devices`) każda wiadomość była
potwierdzana brokerowi **dwa razy**: raz w izolacji, drugi raz we wspólnej ścieżce końcowej. Skutek byłby niegroźny (drugi `PUBACK` dla nieznanego identyfikatora
broker ignoruje), ale to zbędny ruch i niejasny stan. Po poprawce izolacja czyści listę oczekujących po przetworzeniu wszystkich wierszy. Testy `test_row_isolation_…`
i `test_persistent_foreign_key_violation_…` pilnują pojedynczego potwierdzenia.

### K4-U2: założenia brokera potwierdzone liczbami

| Pomiar | Wynik |
| --- | --- |
| Baza niedostępna, opublikowano 250 wiadomości: ile dotarło do ingestu | **dokładnie 100** (reszta czeka w kolejce sesji brokera; założenie `max_inflight_messages` = 100 potwierdzone, `manual_ack` w paho 2.2.0 zachowuje się jak założono) |
| Po powrocie bazy | wszystkie 250 w bazie, **250 różnych wierszy, bez duplikatów** |
| Awaria między odbiorem a zapisem (zatrzymanie przy niedostępnej bazie, bez potwierdzeń; ponowny start z tym samym `client_id`) | 30 z 30 wiadomości dostarczone ponownie, dokładnie 30 wierszy |
| Wiadomości opublikowane, gdy ingest był wyłączony (sesja trwała) | 40 z 40 w bazie po ponownym starcie |
| Przepustowość: seria 5000 wiadomości QoS 1 | **3,7 s, 1363 wiadomości/s**; 51 paczek (ok. 98 na paczkę), zapis paczki średnio 15,2 ms, maks. 30,5 ms; wszystkie 5000 wierszy, 5000 różnych |
| Wymagana przepustowość | 13/s teraz, ok. 65/s w etapie 3 |

**Zastrzeżenie do przepustowości:** test działa na bazie w tmpfs z `fsync=off` i z ingestem w procesie testu, więc 1363/s jest wartością optymistyczną. Na
produkcyjnej bazie na NVMe z domyślnym `fsync` oczekuję niższej, ale nie mierzyłem. Margines względem 65/s jest duży (ok. 20 razy).

**Uwaga do etapu 3 (wypełnianie historii):** przy ok. 65 wiadomościach/s w czasie rzeczywistym historia 120 dni z próbkowaniem 1 Hz to ok. 674 mln wiadomości,
czyli przy ok. 1,4 tys./s ponad 5 dni pracy. Wypełnianie historii przez MQTT ma więc sens tylko z rzadszym próbkowaniem (np. 1 próbka na minutę: ok. 11 mln wiadomości,
rząd godzin) albo innym torem (bezpośredni zapis do bazy). Decyzja należy do etapu 3; tu tylko liczby.

### Pokrycie planu

Walidacja: wszystkie dziewięć powodów (`topic`, `unknown_device`, `site_line`, `metric`, `payload`, `ts`, `value`, `unit`, `source`), granice okna (+4 min dozwolone, +6 min odrzucone,
399 dni dozwolone, 401 odrzucone, znacznik zerowy), brak strefy czasowej, `NaN`, `Infinity`, `1e400`, ogromna liczba całkowita, wartość logiczna i tekstowa, `source` zgodne i
niezgodne z urządzeniem (w tym urządzenie `sim`), ładunek za duży, dodatkowe klucze ignorowane, milisekundy i przesunięcie strefy. Potok: paczka po 100 lub 1 s, **ack dopiero po zapisie**,
brak ack przy błędzie bazy, ponawianie z cofaniem (próby w 1, 2, 4, 8, 16 i 26 s od początku awarii, czyli przerwy 1, 2, 4, 8, 10 s), duplikaty liczone i potwierdzane, wadliwe potwierdzane od razu, izolacja wierszy, ponowna synchronizacja przy FK,
awaria bazy w trakcie izolacji (pozostałe wiersze czekają), zatrzymanie z niedostępną bazą (nic nie potwierdzone), log odrzuceń. E2E: pola wiersza, milisekundy, **`link_status` od `plc-01`
trafia do bazy (U1)**, duplikat daje jeden wiersz, wadliwe nie blokują strumienia (pięć powodów odrzucenia i poprawna wiadomość na końcu), rola `app_writer`. **Ingest przed bazą i przed `migrate`
(U4):** pusta baza bez schematu i bez roli, ingest żyje (znacznik świeży), MQTT jeszcze nie startuje, po `migrate` łączy się i zapisuje, `devices` zawiera 2 wiersze.

Log odrzuceń: 1000 wadliwych wiadomości dało **1 wpis WARNING** (próg testu: ≤ 3), wszystkie 1000 policzone.

## Prawdziwy stos na komputerze (kroki 4–6)

`docker compose up -d --build` zbudował obraz `aip-ingest:local` (136,4 MB) i uruchomił `ingest`; collector zostaje za profilem `live`.

```text
NAME              STATUS                      PORTS
aip-ingest        Up 12 seconds (healthy)     
aip-migrate       Exited (0) 10 seconds ago   
aip-mosquitto     Up 2 hours (healthy)        127.0.0.1:1883->1883/tcp
aip-timescaledb   Up 2 hours (healthy)        5432/tcp
```

Log startu ingestu (cały, 4 wpisy):

```text
INFO ingest start: temat zaklad1/linia1/<urządzenie>/<metryka>, urządzeń w configu: 2, paczka 100 lub 1.0 s
INFO ingest devices zsynchronizowane z configiem: 2 wpisów, wyłączono 0
INFO ingest.mqtt MQTT: połączono z mosquitto:1883, sesja trwała nowa
INFO ingest.mqtt MQTT: subskrypcja +/+/+/+ potwierdzona (QoS 1)
```

### `devices` (K4-U3)

```text
   device_id   |     kind     | source | enabled |                                meta
 finder_7m24_1 | energy_meter | real   | t       | {"serial": "F0183363", "profile": "finder_7m24", "block_base": 10}
 plc-01        | plc          | real   | t       | {"map_version": 1}
```

**Adres IP nie występuje w bazie** (zapytanie na `meta` i `name`: 0 wierszy z `192.168`). `measurements`: **0 wierszy** przed i po dymku.

### Dymek bez zapisu do `measurements` (K4-U3)

Wiadomość na nieznane urządzenie (`zaklad1/linia1/nieznane_urzadzenie/voltage`, konto `collector` z kontenera Mosquitto, hasło ze zmiennej środowiskowej, nie wypisywane)
została odrzucona; log pierwszego wystąpienia i podsumowanie po 60 s:

```text
WARNING ingest odrzucono (unknown_device): nieznane urządzenie 'nieznane_urzadzenie'; temat=zaklad1/linia1/nieznane_urzadzenie/voltage ładunek=b'{"ts":"2026-11-23T19:10:00.000Z",...}'
INFO ingest podsumowanie: odebrane=1 zapisane=0 duplikaty=0 rejected=1 (unknown_device=1) paczki=0 zapis_ms_sr=0.0 zapis_ms_maks=0.0 oczekujące=0 baza=OK
```

Skan logu ingestu (6 linii): słowo „password”: **0**, słowa kluczowe SQL (`INSERT`, `SELECT`, `UPDATE`): **0**; po jednym wpisie synchronizacji `devices` i potwierdzenia subskrypcji.
Połączenie z bazą: `app_writer`, `application_name = aip-ingest`. Kontener: uid **10003**, system plików tylko do odczytu (zapis w `/app` odrzucony), znacznik żywotności w `/tmp`,
`healthy`, `failing_streak = 0`. Obraz (`pip freeze`): `paho-mqtt==2.2.0`, `psycopg==3.3.9`, `psycopg-binary==3.3.9`, `PyYAML==6.0.4`, `typing_extensions==4.16.0`.

### Pozostały stan

`ss -ltn`: bez zmian (nowy tylko `127.0.0.1:1883` z k2; ingest bez portów); `StartedAt` wszystkich 7 kontenerów smartWARE bez zmian; kontener collectora nie istnieje; kontrola praw po `git pull`:
bez wyników, `.env` 600; `git status` czysty. `aip-migrate` uruchamia się przy każdym `docker compose up` (`restart: "no"`), więc przy `up --build` ingest wystartował równolegle z kolejnym biegiem `migrate`;
schemat już istniał, więc nic nie przeszkadzało, a świeża instalacja jest pokryta testem „ingest przed bazą i przed `migrate`”.

## Zasoby

| Kontener | Zużycie (spoczynek) | Limit |
| --- | --- | --- |
| `aip-ingest` | 26,3 MiB | 128 MB |
| `aip-timescaledb` | 49,5 MiB | 1,5 GiB |
| `aip-mosquitto` | 1,5 MiB | 64 MB |

CPU ingestu w spoczynku **ok. 0,1%** (skumulowany czas procesu: 1 tyknięcie zegara w 10 s). Pojedyncze próbki `docker stats` pokazywały ok. 25%: to uruchomienie healthchecka
(`python -m ingest.health` co 10 s) liczone do kontenera, nie pętla główna. `free -m` w trakcie testów: used 1518 MB, available 13 566 MB, swap 0; po starcie ingestu: used 1471 MB,
available 13 715 MB. smartWARE bez zmian (ok. 517 MiB razem). **Zużycie pod obciążeniem prawdziwymi danymi zmierzę w k5/k8.** Suma limitów `aip-` działających teraz: 1600 + 128 = **1728 MB**;
po uruchomieniu collectora (k5): 1856 MB.

## Odstępstwa od planu i dlaczego

1. **Nazwy plików testów:** `test_ingest_e2e.py`, `test_ingest_config_loader.py`, `test_ingest_compose_service.py` zamiast `test_e2e.py` i `test_compose_service.py` z planu, bo pytest wymaga
   unikalnych nazw modułów w całym repo (te nazwy istnieją w testach collectora). Dodatkowy plik `test_ingest_config_loader.py` (w planie nie był wymieniony): sprawdza zgodność parserów ingestu i collectora na
   jednym pliku (K4-a).
2. **Helpery w `tests/ingest/ingest_support.py`, nie w `conftest.py`:** ten sam powód co `tests/dbtools.py` w k3 (kilka plików `conftest.py`).
3. **Sprzątanie trwałych sesji MQTT w testach** (`forget_session`): test, który zatrzymuje ingest, usuwa jego sesję z brokera (ponowne połączenie z `clean_session=True`), żeby sesje testowe
   nie zbierały wiadomości z kolejnych testów.
4. **Zdanie w `docs/status-codes.md`** o rozgrzewce collectora dodane jako krok 1 (uwaga z review k3).
5. **Klucz `rejected` w podsumowaniu jest po angielsku**, reszta po polsku: celowo, żeby zgadzał się z kryterium K4-U4 (`rejected = 0`) i dało się go łatwo przeszukać.
6. **Czego plan wymieniał, a nie testowałem osobno:** flaga `retain` nie jest przekazywana do walidacji, więc jest ignorowana z konstrukcji (brak osobnego testu); **restart brokera** w trakcie pracy ingestu
   (paho łączy się ponownie z cofaniem 1–30 s) nie jest testowany, bo test nie może zatrzymać kontenera Mosquitto; sprawdzi to test restartu komputera w k8.

## Uwagi K4-U1…U4 i zadania na kolejne kroki

- **K4-U1:** sesja trwała wygasa po 7 dniach bez połączenia ingestu (`persistent_client_expiration 7d`): broker usuwa sesję z kolejką, wiadomości nie są kolejkowane, aż ingest znów się zasubskrybuje.
  Dopisane w `docs/ops` (sekcja „Utrata danych przy przerwach”) obok R2-U2.
- **R2-U2 (powtórzone wprost):** przy zapełnieniu kolejki sesji ingestu Mosquitto (50 000 wiadomości lub 20 MB; ok. 64 minuty przy 13 na sekundę, wiąże liczba wiadomości) odrzuca **najnowsze**, więc luka w danych
  pojawia się **na końcu przerwy**. Collector przy przepełnieniu własnego bufora (20 000, ok. 25 minut) odrzuca **najstarsze**, ale działa on tylko przy niedostępnym brokerze.
- **K4-U2:** liczby wyżej (100 w locie, bez strat i duplikatów po powrocie bazy, przepustowość).
- **K4-U3:** log bez haseł i bez treści SQL, jeden wpis synchronizacji i potwierdzenie subskrypcji, `meta` bez adresu IP.
- **K4-U4 (checklista k5):** oczekiwana liczba wierszy przy sprawnym PLC i liczniku: **13/s = 780 na minutę, tolerancja ±2% (ok. 764 do 796)**; ingest bez odrzuceń: w podsumowaniu `rejected=0`.
  Przy `meter_status` ≠ 0 wierszy jest mniej, przy `link_status` ≠ 0 tylko 1 na sekundę.
- **Zadania k7 (bez zmian):** K2-U5 (`maxOpenConns` ok. 5, `maxIdleConns` ok. 2), K3-U3 (kafelek stanu licznika uwzględnia `link_status`).

## Checklista dla Grzegorza

Brak czynności (zgodnie z review k4): krok nie dotyka sprzętu ani GUI.

## Otwarte kwestie

- **Przepustowość na prawdziwej bazie** (NVMe, `fsync` włączony) nie była mierzona; wartość 1363/s pochodzi z testu na bazie w tmpfs (patrz zastrzeżenie).
- **Restart brokera w trakcie pracy** i **restart komputera** (autostart całego stosu, w tym ingest czekający na bazę): k8.
- **Wypełnianie historii w etapie 3:** liczby wyżej wskazują, że 1 Hz przez 120 dni nie nadaje się do toru MQTT.
- **Zmiana `devices.yaml`** wymaga restartu ingestu i collectora (K4-f); opisane w `docs/ops`.
- **Start collectora (k5):** usunięcie profilu `live` i sprawdzenie, że `docker compose up -d` startuje oba bez `--profile`; wtedy `measurements` zacznie rosnąć, a `devices` już jest zsynchronizowane.
