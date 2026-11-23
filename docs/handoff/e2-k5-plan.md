# e2-k5 plan: pierwsze prawdziwe dane (PLC → collector → MQTT → ingest → baza)
Status: DO PRZEGLĄDU

Podstawa: `e2-k4-report-review.md` (sekcja „Zakres k5” i uwagi 1–3), `e2-k3-report-review.md` (punkty „Do k5”), `docs/modbus-map.md`,
`docs/status-codes.md`, `docs/stages/etap-1.md` (test przerwy RS485, okablowanie), `config/devices.yaml`, `CLAUDE.md`.
To pierwszy krok, w którym collector łączy się z prawdziwym PLC. Zasada 1 obowiązuje bez zmian: **z komputera do PLC tylko odczyt FC04**
(collector oraz `mbpoll -t 3`; nigdy `-t 4` z wartościami, nigdy zapisy).

## Cel kroku

Po usunięciu profilu `live` collector startuje razem ze stosem i dane z prawdziwego licznika Finder 7M.24 płyną do `measurements`.
Weryfikujemy: łączność kontenera z PLC (NAT), zgodność wartości z niezależnym odczytem, liczbę wierszy, zachowanie przy przerwie RS485, przy
odłączonym PLC i przy restarcie brokera oraz zużycie zasobów na prawdziwej sieci.

**Sprawdzalny wynik:** wszystkie kryteria z tabeli „Kryteria zaliczenia” poniżej, z tekstowymi wydrukami w `e2-k5-report.md`; collector i ingest
`healthy` po `docker compose up -d` bez `--profile`; `docker compose ps` pokazuje cztery usługi `aip-` (collector, ingest, mosquitto, timescaledb) i zakończony `migrate`.

## Tryb wykonania i podział ról

Polecenia na `jumo-ipc` wykonuję przez `ssh jumo@192.168.0.213` (Git Bash, `bash -s`, `</dev/null`), **bez `sudo`**, bez ruszania smartWARE, demona Dockera i
`docker system prune`; `docker compose down -v` tylko za zgodą. Nie wypisuję `.env` (kontrola tylko nazw, długości i praw); raport bez sekretów. Po każdym
`git pull` kontrola praw wg `docs/ops`.

| Kto | Co |
| --- | --- |
| Claude Code | wszystkie polecenia na komputerze, zapytania do bazy, `mbpoll -t 3` (tylko odczyt), analiza danych, raport |
| Grzegorz | **trzy czynności fizyczne**: odłączenie przewodu RS485 (ok. 10 s), odłączenie kabla LAN1 PLC (ok. 30 s) i opcjonalnie Stop programu w CODESYS (ok. 15 s); każda na wyraźne „TERAZ odłącz” i potwierdzenie „gotowe”; opcjonalnie 1–2 zdjęcia |

Kolejność: najpierw części autonomiczne (kroki 1–5 i 9), potem czynności fizyczne (6–8) z Grzegorzem w sesji, na końcu analiza i raport. Cały krok zajmie
rzędu 1,5 godziny, z czego Grzegorz jest potrzebny w trzech krótkich momentach.

## Plan wykonania

### 1. Usunięcie profilu `live` i przygotowanie

- `docker-compose.yml`: usunięcie `profiles: ["live"]` z usługi `collector` i komentarza o profilu; test `test_compose_service.py` (collector) zmieniony z „profil = `live`” na
  „brak profilu”; `docs/ops` zaktualizowane (collector startuje ze stosem). Commit na `main`, `git pull --ff-only` na komputerze, kontrola praw, pełny `sh tests/run-tests.sh`
  (nic poza tym testem nie powinno się zmienić: oczekiwane 257 zielonych).
- **Kontrola przed startem (tylko odczyt):** `measurements` = 0, `devices` = 2 wiersze, stos zdrowy, `StartedAt` smartWARE jako punkt odniesienia, `ping` do 192.168.0.246.
- **Punkt odniesienia z PLC niezależnie od collectora:** `mbpoll -m tcp -a 1 -t 3:hex -0 -r 0 -c 44 -1 192.168.0.246` (jak w etapie 1): `map_version` = 1, status 0, serial `F0183363`
  (rejestry 40–43 = `4630 3138 3333 3633`). Jeśli wynik jest inny, **zatrzymuję się i pytam** (np. adres PLC zmieniony przez DHCP lub włączona Serial Gateway).

### 2. NAT i pierwszy start (punkty 1–2 z „Zakresu k5”)

- Najpierw sama łączność TCP z kontenera w sieci `aip_backend`, bez żadnego żądania Modbus: jednorazowy kontener z obrazu `aip-collector:local` (nie-root, `cap-drop ALL`,
  `read-only`) próbuje otworzyć gniazdo do 192.168.0.246:502 i zamyka je. Brak połączenia = stop i pytanie (NAT/routing; `network_mode: host` tylko za zgodą).
- `docker compose up -d` (bez `--profile`): collector startuje razem ze stosem. Obserwuję log, czekam na `healthy`. Oczekiwane wpisy: start z adresem PLC i zakresem 0–43; zmiana
  stanu `plc: (start) -> OK` i `meter:finder_7m24_1: (start) -> OK`; brak ostrzeżeń o odmowie MQTT. Pierwszy start z `read_only`, `cap_drop: ALL`, `tmpfs: /tmp` oraz healthcheckiem
  `python -m collector.health` jest tym, co k3 zostawiło do sprawdzenia.
- Po minucie: pierwsze wiersze w `measurements`; `rejected=0` w pierwszym podsumowaniu ingestu.
- **Wycofanie:** `docker compose stop collector` zatrzymuje odczyty z PLC natychmiast i nie dotyka niczego innego; stosuję je przy każdym nieoczekiwanym zachowaniu.

### 3. Zgodność wartości (punkt 3)

Pięć par pomiarów: `mbpoll -t 3` (tylko odczyt, z komputera) i w tej samej sekundzie najbliższy wiersz w bazie, z zapisaną chwilą odczytu (`date` z milisekundami). Porównuję:

| Wielkość | Źródło `mbpoll` | Źródło w bazie | Tolerancja |
| --- | --- | --- | --- |
| napięcie `voltage` | rejestry 26–27 (REAL, starsze słowo pierwsze, `-t 3:float -B`) | `voltage` | ±0,5 V |
| moc czynna `active_power` | rejestry 16–17 | `active_power` | ±0,2 W |
| energia pobrana `energy_import_wh` | rejestry 34–36 (mantysa × 10^wykładnik) | `energy_import_wh` | równa (zmienia się co 100 Wh) |
| serial | rejestry 40–43 (ASCII) | `devices.meta` i `meter_status = 0` (collector zaakceptował) | `F0183363` |
| pozostałe (częstotliwość, prąd, współczynnik mocy) | odpowiednie rejestry | odpowiednie metryki | do wiadomości, bez progu |

Założenie do potwierdzenia: serwer Modbus CODESYS przyjmuje drugie połączenie klienta, gdy collector już jest połączony. Jeśli `mbpoll` dostanie odmowę lub timeout, zatrzymuję
collector (`docker compose stop collector`) na czas porównania, wykonuję odczyt `mbpoll`, porównuję z ostatnimi wierszami sprzed zatrzymania i uruchamiam collector ponownie
(odnotowuję to w raporcie jako ograniczenie PLC).

### 4. Liczba wierszy, heartbeat, ciągłość (punkt 4 oraz uwaga 1 z review k4)

- Okno **10 pełnych minut** (bez pierwszej i ostatniej, niepełnej): liczba wierszy na minutę, oczekiwane **780 ± 2% (764–796)**; liczba wierszy na metrykę (ok. 60 na minutę każda, a diagnostyka i statusy też);
  brak duplikatów (liczba wierszy = liczba różnych `(device_id, metric, time)`); opóźnienie `now() - max(time)` poniżej 3 s; rozkład odstępów między kolejnymi wierszami `link_status` (mediana, p99, maks.) jako
  pośredni pomiar jitteru cyklu collectora na prawdziwej sieci.
- Ingest: kilka kolejnych podsumowań z logu: `rejected=0`, `zapis_ms_sr` i `zapis_ms_maks` na prawdziwej bazie (uwaga 1 z review k4: przy 13/s paczki są małe, czas zapisu wystarcza jako wskaźnik).
- **Heartbeat ok. 6/s:** pięć odczytów `mbpoll -t 3` rejestrów 0–1 w odstępach ok. 1 s; przyrost / czas = ok. 6 (ze zmierzonym odstępem z `date`).
- Czas jednego odczytu na prawdziwej sieci: `time mbpoll -1` jako przybliżenie (łączenie plus odczyt) i `ping` (RTT).

### 5. Zasoby (punkt 9)

`docker stats --no-stream` collectora, ingestu, bazy i brokera: próbki co ok. 1 minutę przez 10 minut (pod obciążeniem prawdziwych 13 wiadomości na sekundę), `free -m`, `df -h /`, rozmiar `measurements`
(`pg_total_relation_size`) po 10 minutach. Collector nie loguje własnego czasu cyklu (K5-a), więc używam pomiarów pośrednich z kroku 4.

### 6. Test przerwy RS485 (punkt 5) — Grzegorz

Ten sam test co w etapie 1 (test 5): **jeden przewód RS485 między licznikiem a złączem „COM” PLC** (okablowanie: `docs/images/etap1/30-wiring-varitron-com.jpg`), odłączony na ok. 10 s.
Przed testem zapisuję chwilę początkową z bazy. Protokół:

1. Ja: „TERAZ odłącz przewód RS485”. Grzegorz odłącza i odpisuje „odłączony”.
2. Odczekanie ok. 10 s (Grzegorz liczy sam; dokładny czas wyznaczą dane, nie jego zegarek).
3. Ja: „TERAZ podłącz”. Grzegorz podłącza i odpisuje „podłączony”.
4. Ja czekam ok. 15 s i analizuję bazę w oknie czasu testu.

Oczekiwane (kryteria zaliczenia): `meter_status = 1` w każdym cyklu przerwy; `meter_error_count` wzrasta o **1** (jedna przerwa = +1); `meter_data_age_ms` rośnie równo; **brak** wierszy z pomiarami licznika
(`voltage` itd.) od pierwszego `meter_status = 1` do powrotu; `link_status` nadal 0; po podłączeniu `meter_status` wraca do 0 po ok. 3 s (filtr PLC) i dopiero wtedy wracają pomiary.
Z danych wyznaczam faktyczny czas przerwy, czas od podłączenia do pierwszego pomiaru oraz brak innych luk.

### 7. Test PLC offline (punkt 6) — Grzegorz

**Kabel LAN1 PLC odłączony na ok. 30 s.** Protokół jak wyżej („TERAZ odłącz kabel LAN1 PLC” → „odłączony”; po ok. 30 s „TERAZ podłącz” → „podłączony”; ja analizuję po ok. 30 s).
Oczekiwane: w czasie przerwy tylko `link_status = 1`, jeden wiersz na sekundę, żadnych innych wierszy; po podłączeniu powrót bez ingerencji: `link_status` przechodzi w 0 po rozgrzewce ok. 1 s od odzyskania połączenia, a
pomiary wracają. Z danych wyznaczam czas wykrycia (czas od odłączenia do pierwszego `link_status = 1`) i czas powrotu.

**Ryzyko DHCP:** adres 192.168.0.246 jest przydzielany przez DHCP. Po odłączeniu kabla na 30 s PLC powinien odzyskać ten sam adres, ale nie mam tej gwarancji. Jeśli po podłączeniu `link_status` pozostaje 1
dłużej niż ok. 60 s, sprawdzam `ping` i odczyt `mbpoll` pod 192.168.0.246; jeśli adres się zmienił, **zatrzymuję się i pytam** (zmiana adresu to edycja `config/devices.yaml` w jednej linii i restart collectora;
rezerwacja adresu w routerze załatwiłaby to na stałe, ale to sprawa sieci Grzegorza).

### 8. Opcjonalnie: Stop programu w CODESYS (punkt 7) — Grzegorz, tylko za wyraźną zgodą

**Nie wykonuję bez wyraźnego „tak” Grzegorza w chwili testu**, bo Stop programu wpływa na działający sterownik. Stop na ok. 15 s w środowisku CODESYS (połączenie online), potem Start; download programu nie jest potrzebny.
Zapisuję wynik **jako fakt**: albo `link_status = 2` (serwer Modbus nadal odpowiada ze zamrożonym heartbeatem; kontrakt przewiduje 2 po 5 s), albo `link_status = 1` (serwer przestaje odpowiadać). Po Start: powrót do 0
po rozgrzewce. Jeśli Grzegorz nie wyrazi zgody, test pomijam i zaznaczam to w raporcie (reguła „zamrożony heartbeat” pozostaje sprawdzona wyłącznie na atrapie).

### 9. Restart brokera w trakcie pracy (punkt 8; własny kontener)

`docker compose restart mosquitto` (kontener `aip-mosquitto`, nie smartWARE) przy działających collectorze i ingeście. Oczekiwane: collector buforuje wiadomości na czas niedostępności brokera i wysyła je po
powrocie (z oryginalnymi `ts`); ingest łączy się ponownie z tą samą sesją; **w bazie brak luki dłuższej niż czas restartu i brak duplikatów** (`UNIQUE`); oba kontenery pozostają `healthy`. Pomiary: czas
restartu, lista sekund bez `link_status` w oknie (`generate_series`), liczba duplikatów policzonych przez ingest (`duplikaty=` w podsumowaniu), logi collectora i ingestu z momentu restartu.

### 10. Raport

`e2-k5-report.md`: wydruki tekstowe (bez zrzutów GUI; Grafana dopiero w k7), tabele wyników względem kryteriów, krótki opis „tak wygląda poprawny stan” do dokumentacji (stan `docker compose ps`, przykładowe
ostatnie wiersze, log collectora i ingestu w stanie ustalonym), osie czasu trzech testów fizycznych z dokładnymi chwilami (do wyłączenia tych okien z późniejszej analityki). Zdjęcia Grzegorza (opcjonalne)
jako `docs/images/etap2/30-…`.

## Kryteria zaliczenia

| Kryterium | Wymóg |
| --- | --- |
| Start | collector i ingest `healthy` po `docker compose up -d` bez `--profile`; pierwszy odczyt z kontenera przez NAT; zero ostrzeżeń o odmowie MQTT |
| Zgodność wartości | napięcie ±0,5 V, moc ±0,2 W, energia równa, serial `F0183363`; 5 par |
| Liczba wierszy | 780 ± 2% na minutę (764–796) przez 10 pełnych minut, brak duplikatów, `rejected=0` |
| Heartbeat | ok. 6/s (zmierzony) |
| Przerwa RS485 | `meter_status = 1`, `meter_error_count` +1, `meter_data_age_ms` rośnie, brak pomiarów licznika, powrót ok. 3 s po podłączeniu |
| PLC offline | `link_status = 1`, 1 wiersz/s i nic więcej; powrót bez ingerencji z rozgrzewką ok. 1 s |
| Restart brokera | brak luki dłuższej niż restart, brak duplikatów w bazie, oba kontenery `healthy` |
| Zasoby | `docker stats` collectora i ingestu pod obciążeniem, `zapis_ms` na prawdziwej bazie, jitter cyklu z `ts` |
| Zasada 1 | do PLC dotarło wyłącznie FC04; `mbpoll` tylko `-t 3` |
| Izolacja | `StartedAt` smartWARE bez zmian, `ss -ltn` bez nowych portów, kontrola praw po `pull` czysta |

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| K5-a | Zmiany w kodzie collectora | brak; czas cyklu mierzę pośrednio (jitter odstępów `ts`, `time mbpoll`, `ping`) | k5 ma sprawdzać gotowy kod, nie go zmieniać; ewentualne logowanie czasu cyklu można dodać później |
| K5-b | Czas przerw | RS485 ok. 10 s, LAN1 PLC ok. 30 s | Zgodnie z review k4 i etapem 1; dokładny czas wyznaczają dane, nie zegarek |
| K5-c | Test Stop programu w CODESYS | opcjonalny, tylko za wyraźną zgodą w chwili testu | Wpływa na działający sterownik; bez zgody zamrożony heartbeat zostaje sprawdzony tylko na atrapie |
| K5-d | Porównanie wartości | 5 par `mbpoll` i najbliższy wiersz z bazy; plan awaryjny z zatrzymaniem collectora, jeśli PLC odrzuci drugiego klienta | Pierwsze rozwiązanie nie przerywa ciągłości danych; drugie zachowuje test przy ograniczeniu PLC |
| K5-e | Okno liczenia wierszy | 10 pełnych minut | Przy tolerancji ±2% jedna minuta byłaby zbyt wrażliwa na pominięty cykl; 10 minut daje wiarygodną średnią i rozkład |
| K5-f | Ryzyko DHCP | wykrywanie po `link_status` > 60 s po podłączeniu, stop i pytanie | Zmiana adresu to decyzja Grzegorza (edycja configu lub rezerwacja w routerze) |
| K5-g | Dane z testów fizycznych | zostają w bazie, a ich okna czasu zapisane w raporcie | Wpisy z przerw są prawdziwymi danymi systemu; okna trzeba będzie wyłączyć z analityki (etap 4) |

## Przekazanie uwag z review k3 i k4

| Pozycja | Gdzie w planie |
| --- | --- |
| K3 „Do k5” 1: pierwsze uruchomienie z `read_only`, `cap_drop: ALL`, `tmpfs`, healthcheck | krok 2 |
| K3 „Do k5” 2: NAT 172.31.50.0/24 → 192.168.0.246:502 | krok 2 (najpierw samo gniazdo TCP) |
| K3 „Do k5” 3: zgodność z `mbpoll`, RS485, offline, Stop (opcjonalnie), heartbeat 6/s | kroki 3, 4, 6, 7, 8 |
| K3 „Do k5” 4: pamięć collectora i czas cyklu na prawdziwej sieci | kroki 4–5 |
| K3 „Do k5” 5: usunięcie profilu `live` i `compose up -d` bez `--profile` | krok 1 i 2 |
| K3 „Do k5” 6 i K4-U4: 13/s = 780/min ±2%, `rejected=0` | krok 4 |
| K4 uwaga 1: `zapis_ms_sr` i `zapis_ms_maks` na prawdziwej bazie | krok 4 |
| K4 uwaga 3: restart brokera (własny kontener) | krok 9 |
| K4 uwaga 2: wypełnianie historii (etap 3) | poza k5 (decyzja etapu 3) |

## Ryzyka i założenia (bez potwierdzenia)

- Adres PLC 192.168.0.246 może się zmienić po odłączeniu kabla (DHCP); opisane w kroku 7.
- Serwer CODESYS może odrzucać drugie połączenie klienta; plan awaryjny w kroku 3.
- Czy po Stop programu serwer Modbus nadal odpowiada, nie wiadomo: wynik zapiszę jako fakt (krok 8).
- NAT sieci Compose do PLC nie był jeszcze sprawdzany; krok 2 sprawdza go najpierw samym gniazdem.
- Zasada 1: ryzyko przypadkowego zapisu zamyka konstrukcja collectora (tylko FC04, testy w k3) oraz moja zasada używania wyłącznie `mbpoll -t 3` z flagami odczytu.
- Serial Gateway PLC musi pozostać wyłączona (`docs/modbus-map.md`); z komputera nie mogę tego odczytać, więc opieram się na stanie z etapu 1 i na sensownych wartościach z pierwszego odczytu.
- Wiersze z przerw (RS485, LAN1, ewentualnie Stop) są prawdziwymi danymi; do analityki trzeba je wyłączyć (K5-g).
- Jeśli smartWARE również łączy się z PLC po Modbus TCP (nie sprawdzano), liczba połączeń do serwera może być większa niż zakładam.
- Dysk: ok. 1,12 mln wierszy na dobę (780/min) po uruchomieniu collectora; zmierzę rozmiar `measurements` po 10 minutach, a pomiar po dobie zostaje na k8.

## Poza zakresem

Agregaty ciągłe i widoki energii (k6), Grafana (k7), restart komputera i autostart całego stosu (k8), zmiany w kodzie collectora i ingestu, zmiany w PLC i `docs/modbus-map.md`, drugi licznik,
symulator (etap 3), przełączenie PLC na stały adres.
