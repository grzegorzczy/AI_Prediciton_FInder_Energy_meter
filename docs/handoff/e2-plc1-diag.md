# e2-plc1 diagnostyka: cykliczny błąd PLC–licznik (U-1, pkt 1)
Status: DO PRZEGLĄDU

Wykonanie 24.11.2026 (czasy w UTC, o ile nie zaznaczono inaczej; logi kontenerów i dziennik systemu są w czasie lokalnym UTC+1) wg sekcji „Następny krok” w `e2-k5-report-review.md`.
Bez zmian kodu, konfiguracji i PLC. Do PLC dotarło wyłącznie `mbpoll -t 3` (odczyt, FC04) oraz collector. `.env` nie był czytany. Raport bez sekretów.

## Streszczenie

1. **`error_code` epizodów to 0x00A2 = 162, nie 161 (RESPONSE_TIMEOUT).** Trzy próbki w trzech osobnych momentach, wszystkie 162. W dokumentacji repo znam tylko 161; **znaczenia 162 w repo nie ma** i go nie zgaduję.
   Według drzewa decyzyjnego z review to gałąź „inny kod” (nie 161).
2. **Częstość bez obciążenia TCP:** collector zatrzymany na 15 min, dwa połączenia `mbpoll`: `error_count` **2 → 9, czyli 7 epizodów w 900,4 s** (14 punktów siatki 64 s w tym przedziale, 7 z epizodem). Zjawisko występuje bez collectora i bez ciągłego odpytywania.
3. **Zmieniły się okoliczności po poprzednim teście:** w nocy była **utrata zasilania** komputera i PLC (patrz niżej). Po ponownym starcie PLC (06:54:09) przez **4 godziny i 7 minut nie było żadnego epizodu**, a o **11:01:42 wróciły** na tej samej siatce 64 s.
4. **Faza siatki 64 s przetrwała zanik zasilania:** 11:01:42 leży 696 okresów po 22:39:18 z dokładnością ±1 s, mimo restartu PLC i komputera.
5. **Przypadkiem sprawdzony autostart po nieczystym wyłączeniu:** cały stos wstał sam (patrz niżej). Wykryty przy tym problem z odczytem logów kontenerów (`docker logs`).

## 0. Odstępstwo od polecenia: collector nie loguje `error_code`

Review zakłada, że collector loguje `error_code` przy zmianie (161 = RESPONSE_TIMEOUT). **Tak nie jest.** Plan k3 zapowiadał „`error_code` tylko do logu przy zmianie”, ale kod tego nie robi: pole `diagnostics.error_code` jest wczytywane z `devices.yaml`
(`config.py`), a ewaluator go nie czyta ani nie publikuje; test tego nie sprawdzał, a raport k3 nie wspomniał o braku. To moje niedociągnięcie z k3. Bez zmian kodu nie mogłem więc odczytać kodu z logu.

**Metoda zastępcza (bez zmian kodu, tylko `-t 3`):** przez 8 minut (10:54:32–11:02:33) odpytywałem z komputera rejestry 10–15 co ok. 1,8 s (267 próbek), przy działającym collectorze, żeby złapać `error_code` w trakcie epizodu. Odpytywanie nie służyło tu do pomiaru częstości
bez obciążenia (to faza 2, osobno, zgodnie z poleceniem).

## 1. Zdarzenie nocne: zanik zasilania komputera i PLC

| Fakt | Źródło |
| --- | --- |
| ostatni wiersz w bazie przed luką: 23.11 23:16:57.132 (`link_status` = 1), pierwszy po luce: 24.11 06:52:43.248 | baza |
| PLC przestał odpowiadać o 23:16:51; komputer przestał zapisywać 6 s później | baza (`link_status` = 1 od 23:16:51) |
| dziennik systemu poprzedniego rozruchu kończy się o 00:16:48 CET wpisem `r8169 … enp1s0: Link is Down`; w `last -x` brak wpisu `shutdown` dla tego rozruchu | `journalctl -b -1`, `last -x` |
| rozruch komputera 07:52:19 CET (06:52:19 UTC); wszystkie kontenery `aip-` (i smartWARE) wystartowały między 06:52:39.55 a 06:52:39.84 UTC, bez żadnej czynności z mojej strony | `uptime -s`, `docker inspect` |
| zegar po rozruchu zsynchronizowany (NTP aktywny), strefa Europe/Berlin bez zmian | `timedatectl` |
| TimescaleDB: `database system was not properly shut down; automatic recovery in progress`, `redo done` po 0,01 s, gotowa po 0,13 s od rozpoczęcia odzyskiwania | log kontenera |
| PLC wrócił do pracy o 06:54:06; collector zgłosił `link_status` = 0 o 06:54:09; **83 wiersze `link_status` = 1 w 84 s (98% sekund)** w czasie oczekiwania na PLC | baza |
| `error_count` w bazie: 62 przed zanikiem, **0 od 06:54:09** (wyzerowany restartem PLC) | baza |
| `ingest` i `collector`: `Up 4 hours (healthy)`, `aip-migrate` nie uruchamia się po rozruchu (`restart: "no"`, zgodnie z projektem U4) | `docker compose ps` |

Zanik trwał ok. 7 h 36 min (23:16:57–06:52:43 UTC). **Przyczyny zaniku nie znam** (wyłączenie szafy, awaria zasilania). To nie był zaplanowany test.

**Skutki dla k8 (restart komputera):**
- Autostart całego stosu po nieczystym wyłączeniu zadziałał bez ingerencji, a baza odzyskała się sama; dane po powrocie płyną.
- **Uszkodzone pliki logów kontenerów:** po zaniku zasilania `docker logs` dla `ingest`, `collector` i `mosquitto` zwraca `Error grabbing logs: invalid character '\x00'`. Odczyt z `--since` i pełny odczyt zawodzą (linia z zerami w środku pliku), działa tylko `--tail` z małym zakresem
  (dla `ingest` i `collector` pokazuje nowe wpisy, dla większych zakresów dochodzi do błędu). Z tego powodu **nie mogłem odczytać logów z samego rozruchu** (czy ingest czekał na bazę). To realny problem operacyjny po każdej awarii zasilania (diagnostyka po awarii). Do rozważenia w k8
  (np. kopia logów aplikacji poza `json-file` albo procedura naprawy; naprawa pliku wymaga uprawnień roota, których nie mam).

## 2. Wyniki faz

### Faza 1: `error_code` (collector działał, odpytywanie `mbpoll -t 3` rejestrów 10–15 co ok. 1,8 s przez 8 min)

267 próbek (10:54:32–11:02:31). `error_code`: 265 × 0x0000 (status OK), **2 × 0x00A2**; `error_count`: 239 × 0x0000, 28 × 0x0001 (po epizodzie). Próbki ze statusem ≠ 0:

```text
11:01:43.257 status=0x0001 error_code=0x00A2 error_count=0x0001 data_age=1000 ms
11:01:45.074 status=0x0001 error_code=0x00A2 error_count=0x0001 data_age=2799 ms
```

W 8 minutach: **jeden epizod** (11:01:42–46), tj. 1 z 7–8 punktów siatki. Dodatkowo odczyt początkowy fazy 2 trafił w kolejny epizod (11:03:50): `status` = 1, `error_code` = 0x00A2, `error_count` = 2, `data_age` = 3601 ms. **Łącznie 3 próbki w 2 epizodach: wszystkie `error_code` = 0x00A2 (162).**
Przy teście przerwy RS485 w k5 (odłączony przewód) znany z etapu 1 kod to 161 (timeout); tu inny.

### Faza 2: 15 minut bez collectora (collector zatrzymany 11:03:53.4–11:18:55.3, tylko dwa połączenia `mbpoll`)

```text
READ_START 2026-11-24T11:03:53.446Z hb=0x000124E2 map=0x0001 status=0x0001 error_code=0x00A2 error_count=0x0002 data_age=3601 ms
READ_END   2026-11-24T11:18:53.852Z hb=0x00013678 map=0x0001 status=0x0000 error_code=0x0000 error_count=0x0009 data_age=0
```

| Pomiar | Wynik |
| --- | --- |
| odstęp między odczytami | 900,406 s |
| **przyrost `error_count`** | **7** (2 → 9), czyli ok. 0,47 epizodu na minutę |
| punkty siatki 64 s w przedziale | 14 (11:04:54 … 11:18:46); epizodów 7, czyli 50% punktów |
| heartbeat | 74 978 → 79 480: **4502 w 900,4 s = 5,00/s** (PLC pracuje równo, `map_version` 1) |
| obciążenie TCP | 2 połączenia w całym oknie (collector zatrzymany) |

Po wznowieniu collectora (11:18:57): `meter_error_count` = 9 w pierwszym wierszu, następny epizod 11:19:50 (na siatce: 11:18:46 + 64 s).

### Tło z bazy: epizody od rozruchu PLC (06:54:10) do 11:20

| start (UTC) | czas [s] | uwagi |
| --- | --- | --- |
| 11:01:43 | 4 | pierwszy epizod po 4 h 7 min ciszy (06:54:10–11:01:42: **0 epizodów**, ok. 232 punkty siatki) |
| 11:03:51 | 3 (obcięte przez zatrzymanie collectora) | |
| 11:04–11:18 | 7 epizodów | widziane tylko przez przyrost `error_count` (2 → 9), bez momentów |
| 11:19:50 | 4 | |

Od 11:01:42 do 11:20: 10 epizodów w ok. 18 punktach siatki.

## 3. Siatka 64 s i jej faza

Wszystkie początki epizodów od wczoraj do dziś pasują do siatki co 64 s zakotwiczonej w 22:39:18 z dokładnością ±1 s (±1 s wynika z przesunięcia fazy próbkowania collectora względem sekundy po jego restarcie, bo pierwszy wiersz ze statusem 1 wypada o ułamek sekundy inaczej):

| Moment | Sekundy po 22:39:18 | Okresy po 64 s |
| --- | --- | --- |
| 23.11 22:54:14 (`mbpoll`, collector zatrzymany) | 896 | 14,000 |
| 23.11 23:01:42 | 1344 | 21,000 |
| 24.11 11:01:42/43 (po zaniku zasilania i restarcie PLC i komputera) | 44 544–44 545 | 696,000–696,016 |

`epoch(22:39:18Z)` = 1795473558, `mod 64` = 22. **Faza nie zależy więc od chwili uruchomienia ani PLC, ani komputera**: siatka jest przywiązana do czasu bezwzględnego. To fakt z danych; źródła okresowości nie znam.

Wcześniejsza częstość (wczoraj): w oknie referencyjnym 22:41–22:51 było 7 epizodów w 9 punktach siatki; 23:13:26, 23:14:30, 23:15:34, 23:16:38 to cztery kolejne punkty tuż przed zanikiem; wcześniej od 23:08:00 do 23:13:26 w bazie nie było żadnego epizodu. Zjawisko występuje w seriach, nie równomiernie.

## 4. Interpretacja względem drzewa decyzyjnego z review

| Gałąź z review | Wynik |
| --- | --- |
| kod 161: Response timeout 200 → 1000 ms | **nie dotyczy**: kod to 162 |
| inny kod: przegląd okablowania RS485 (skrętka, ekran SC, terminacja) | **ta gałąź**, ale znaczenia 162 nie znam: warto sprawdzić w dokumentacji biblioteki `IoDrvModbus` (`MB_ErrorCodes`, 16#A2) przed decyzją |

Czego dane **nie** rozstrzygają: czy 162 oznacza zakłócenie, kolizję na magistrali, niepoprawną ramkę czy coś innego; kto lub co jest źródłem okresowości 64 s; dlaczego epizody zniknęły na 4 h i wróciły o 11:01:42.

## 5. Hipotezy do sprawdzenia (nie fakty)

- **Czy CODESYS jest zalogowany online w chwilach epizodów?** Brak epizodów od rozruchu do 11:01 (nikt nie pracował z PLC) i ich obecność wczoraj podczas całej sesji z IDE oraz od 11:01 mogłaby to sugerować; **nie mam danych o sesjach online**, więc to pytanie do Grzegorza.
  Test (bez zmian w PLC): zapis w czacie, kiedy CODESYS jest online, i zestawienie z godzinami epizodów.
- **Źródło okresowe niezależne od stanu PLC i komputera** (siatka przetrwała restart obu): inne urządzenie na magistrali RS485, urządzenie w sieci odpytujące PLC albo mechanizm oparty na czasie bezwzględnym. Do ustalenia przez przegląd magistrali i listy urządzeń; poza zakresem collectora.
- Stała siatka 64 s = 2^16 tyknięć po 1/1024 s; to wyłącznie spostrzeżenie o liczbie, bez dowodu związku.

## 6. Okna do wyłączenia z analityki (UTC)

| start | koniec | rodzaj | uwagi |
| --- | --- | --- | --- |
| 2026-11-23T23:16:51Z | 2026-11-24T06:54:09Z | `plc_power_loss` | zanik zasilania PLC (od 23:16:51) i komputera (23:16:57–06:52:43); `link_status` = 1 w 83 wierszach po rozruchu |
| 2026-11-24T10:54:32Z | 2026-11-24T11:02:33Z | `plc1_phase1_sampling` | dodatkowe odpytywanie `mbpoll -t 3` co ok. 1,8 s przy działającym collectorze |
| 2026-11-24T11:03:53Z | 2026-11-24T11:18:57Z | `collector_stopped` | faza 2: collector zatrzymany, w bazie luka 904 s |

## 7. Propozycje (bez wdrażania)

- **Logowanie `error_code` w collectorze:** w k5b dopisać wpis przy `OK -> COMM_ERROR` z kodem z rejestru 11 (i ewentualnie metrykę `meter_error_code`, niezależną od `meter_status`), żeby następne epizody były opisane w bazie, a nie tylko przez `mbpoll`. Decyzja architekta (to zmiana kodu i konfiguracji).
- **k8:** rozwiązanie problemu z logami kontenerów po nieczystym wyłączeniu (procedura, kopia, `docker logs --tail`), udokumentowanie zachowania autostartu po zaniku zasilania (zadziałał), pomiar rozmiaru i kompresji po dobie.
- **Uwagi uboczne:** log Mosquitto zaczyna się ostrzeżeniem `Note: It is recommended to replace message_size_limit with max_packet_size` (zmiana jednej linii w `config/mosquitto/mosquitto.conf`); healthcheck `nc -z` zapisuje po dwie linie do logu brokera co 10 s (`New connection` i `closed`), co zaśmieca log (do rozważenia przy wyciszeniu `log_type`). Zużycie pamięci po kilku godzinach:
  `aip-ingest` 45,5 MiB (było 27,8 MiB po 30 min), `aip-timescaledb` 114,5 MiB (było 54,5 MiB), `aip-mosquitto` 7,3 MiB (było 2,1 MiB), collector 24,3 MiB; to najprawdopodobniej rozgrzewanie pamięci podręcznej i 4 godziny danych, ale wzrost ingestu warto obserwować w k8 (dobowy pomiar).

## 8. Stan końcowy

Collector wznowiony o 11:18:55, `healthy`, dane płyną; `ingest`, `mosquitto`, `timescaledb` `healthy`; smartWARE `healthy`. Baza: 220 706 wierszy, 41 MB (ok. 195 bajtów na wiersz). Kontrola praw w klonie czysta, `.env` 600, `git status` bez moich zmian poza tym dokumentem.
W katalogu roboczym laptopa są dwie zmiany nie moje i niezacommitowane: zmodyfikowany `plc/setup/10.2.1.1-new_1.431.432` (plik projektu PLC) i plik tymczasowy Worda `~$_Predykcja_dokumentacja.docx`; nie dotykałem ich.
