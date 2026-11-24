# e2-k5 report review: pierwsze prawdziwe dane

Recenzent: architekt (czat projektu), 24.11.2026. Podstawa: `docs/handoff/e2-k5-report.md`, `e2-k5-review.md`, `docs/modbus-map.md`, zrzuty konfiguracji Modbus RTU z etapu 1 (`docs/images/etap1/01-rtu-channels.png`, `03-modbus-client-settings.png`), dokumenty projektu 00, 01, 12.

## Werdykt: OK Z UWAGAMI – k5 zaliczony dla toru danych; ustalenie U-1 (licznik) idzie do osobnej diagnozy PLC przed etapem 4

Tor danych PLC → collector → MQTT → ingest → baza działa na prawdziwym sprzęcie i spełnia założenia:
- zgodność z niezależnym `mbpoll` (U ±0,1 V, P ±0,1 W, energia identyczna, serial);
- 600/600 s pokrytych w oknie referencyjnym, 0 duplikatów, `rejected=0`;
- restart brokera bez luki i bez duplikatów w bazie (13 duplikatów pominiętych przez `ON CONFLICT`);
- test przerwy RS485 zgodny z kontraktem: `meter_status = 1` przez całą przerwę, `error_count` +1, `data_age` równo, 0 pomiarów w przerwie, `link_status` cały czas 0;
- powrót po LAN1 i po Stop bez ingerencji, adres DHCP bez zmian;
- zasoby: collector 24 MiB, ingest 28 MiB, zapis paczki 12,5–17,6 ms na NVMe;
- zasada 1: tylko FC04.

**Kryterium liczby wierszy** przyjmuję w postaci modelu 13/4 wierszy na sekundę (100% minut zgodnych). Odchyłka od 780/min nie jest błędem toru, tylko prawdziwym stanem licznika (U-1). Wynik dosłowny zostaje w raporcie jako niespełniony – dobrze, że tak zapisany.

Odstępstwa 1–6 akceptowane. Diagnostyka z zatrzymanym collectorem (odstępstwo 3) była trafna: wykluczyła collector jako źródło U-1, zanim wołano Grzegorza.

## Ustalenia – decyzje

### U-1. Cykliczny błąd PLC–licznik co 64 s → osobne zadanie PLC „E2-PLC1”, przed etapem 4

**Fakty z raportu:**
- epizody na siatce 64 s;
- 1 s błędu + 3 s filtra = 4 s bez pomiarów;
- 7 epizodów w 10 min;
- występują też przy zatrzymanym collectorze (widziane przez `mbpoll`);
- licznik `error_count` = 42 o 22:38, a PLC działał od restartu ok. 14:17 UTC (pkt 6 etapu 1). To ok. 8 h i średnio ok. 1 epizod na 12 min, przy 7 na 10 min w oknie k5.

Częstość wyraźnie wzrosła w czasie k5, ale nie jest to dowód przyczyny. Sam `error_count` nie mówi, kiedy dokładnie były wcześniejsze epizody.

**Konfiguracja PLC (zrzuty z etapu 1):**
- `Modbus_Client_COM_Port`: **Response timeout 200 ms**, Time between frames 10 ms;
- 6 kanałów FC04: 4 co 1000 ms (12, 2, 4 i 8 rejestrów) i 2 co 10 s (12 i 1 rejestr).

200 ms przy 19200 bit/s zostawia mało zapasu, jeśli licznik czasem odpowiada wolniej. Stała siatka 64 s sugeruje zjawisko okresowe po stronie licznika albo sterownika. To hipoteza, nie fakt.

**Decyzja (zasada 7 – nie zgadujemy, sprawdzamy po kolei):**
1. Claude Code (bez zmian kodu): z logu collectora odczytać **`error_code` epizodów**. Collector loguje go przy zmianie: 161 = RESPONSE_TIMEOUT, inne kody (np. CRC) wskazywałyby na okablowanie lub zakłócenia. Do tego **pomiar częstości bez obciążenia TCP**: collector zatrzymany na 15 min, `mbpoll -t 3` rejestru 12 tylko na początku i na końcu (2 połączenia), różnica `error_count`. Potem collector z powrotem.
2. Architekt z Grzegorzem (tryb ręczny PLC), w zależności od wyniku:
   - **kod 161**: Response timeout 200 → **1000 ms** w `Modbus_Client_COM_Port` (bez zmiany ST), download, pomiar 15 min częstości epizodów (cel: 0 w 15 min). Ewentualnie połączenie kanałów `chPower` + `chCurrent` w jeden odczyt (2490, 28 rejestrów) – mniej transakcji. To zmiana mapowania w `GVL_Meter`, więc tylko jeśli sam timeout nie wystarczy;
   - **inny kod**: przegląd okablowania RS485 (skrętka, ekran SC, terminacja) ze zdjęciem.
3. Wynik trafia do dokumentu projektu 01 (licznik) i 12. Filtr 3 s w `FB_EnergyMeter` zostaje bez zmian. Krótszy filtr skróciłby lukę, ale osłabiłby gwarancję „po błędzie dane wracają dopiero, gdy są pewne”.

Etap 2 może iść dalej (k6, k7) równolegle: agregaty i Grafana muszą i tak obsługiwać luki w pomiarach. Patrz zadanie dla k6 niżej.

### U-2. Luki w `link_status` w czasie awarii → poprawka przed k6

Zatwierdzam poprawkę kodu collectora jako krok **k5b**: mała zmiana, testy, wdrożenie, bez czynności Grzegorza. Wymagania:
- w czasie awarii PLC `link_status = 1` publikowany w **każdym** cyklu (≥ 95% sekund z wierszem w teście LAN1 na atrapie z „czarną dziurą” – serwer, który nie odpowiada na SYN). Próba ponownego połączenia nie może blokować cyklu dłużej niż okres. Sposób wybiera Claude Code (krótki limit połączenia, osobny wątek, nieblokujące łączenie); uzasadnienie w raporcie;
- bez zmian w regułach ważności i bez zapisu do PLC (testy k3 nadal zielone);
- wykrycie offline nadal ≤ `timeout_s` + 1 s.

### U-3. Stop programu = kod 1

Przyjmuję jako fakt sprzętowy. Do `docs/status-codes.md` (k5b): „Stop programu w CODESYS: serwer Modbus TCP nie odpowiada → `link_status = 1`. Kod 2 dotyczy sytuacji, w której serwer odpowiada, a heartbeat stoi (np. zawieszony MainTask); na variTRON 300 nie zaobserwowano”. Dopisać też: Stop/Start jest „gorący” – heartbeat i `error_count` nie są zerowane, a `NO_DATA` po Start nie występuje. Kod 2 zostaje w kontrakcie bez zmian.

### U-4. Szum pymodbus w logu → poprawka w k5b

Zatwierdzam wyciszenie loggera `pymodbus` (poziom `CRITICAL`). Zdarzenia stanu i tak loguje `StateLogger`. Surowe ramki nie mogą trafiać do logu (rosną logi przy dłuższej awarii).

## Zadania przenoszone

- **k6 (agregaty, przyrosty, całka mocy):** luki w pomiarach (epizody U-1, testy, awarie) są normalnym stanem danych.
  - Całka mocy liczy energię tylko z obecnych próbek (`sample_count`), bez interpolacji przez luki dłuższe niż kilka sekund.
  - Agregat podaje **pokrycie** (`coverage` = liczba sekund z pomiarem / długość okna), żeby koszty w etapie 4 mogły ocenić wiarygodność.
  - Porównanie całki z przyrostem licznika wzorcowego na dobie – jak w U7.
- **k7 (Grafana):** K2-U5, K3-U3; dodatkowo w panelu stanu licznika widoczne epizody `meter_status ≠ 0` (np. pasek stanu w czasie).
- **k8:** rozmiar po dobie i kompresja (ok. 199 B na wiersz przed kompresją, ok. 224 MB/dobę), restart komputera.
- **Etap 4/5:** okna testów z tabeli K5-U3 przenoszę do dokumentu projektu 12; później jako wpisy w tabeli `events`.

## Checklista Grzegorza po k5

1. Czynności fizyczne – wykonane (RS485, LAN1, Stop/Start).
2. E2-PLC1 (osobno, w czacie architekta, po wyniku z pkt 1 U-1): zmiana Response timeout w CODESYS i download – dopiero na polecenie architekta.

## Następny krok

Claude Code:
1. Commit tego review.
2. Diagnostyka U-1 pkt 1 (`error_code` z logu, 15 min bez collectora, różnica `error_count`) – wyniki do `docs/handoff/e2-plc1-diag.md` → stop.
3. Po „ok”: plan `e2-k5b-plan.md` (U-2, U-3, U-4) → stop.
