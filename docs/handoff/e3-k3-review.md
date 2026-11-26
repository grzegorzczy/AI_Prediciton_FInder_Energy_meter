# E3-k3 – review planu (architekt)

Data: 2026-11-26. Plan: `e3-k3-plan.md` (`6ee628e`); review k2 zacommitowane w `f98279a`.

**Werdykt: OK Z UWAGAMI – wykonuj po „ok” Grzegorza.** Kotwice, pamięć sum dobowych, ACL i reguła „sekcja główna tylko `real`” zgodne z K1-D1, K1-D2, K2R-D1…D3. Jedna rzecz zmienia plan: QoS symulatora (K3-D4) – chroni kolejkę danych prawdziwych w brokerze.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K3-D1 | Konto symulatora w Mosquitto opcjonalne czy wymagane | **Opcjonalne** – zgoda z rekomendacją. Broker z repo nowszym niż `.env` ma wstać, a dane prawdziwe płynąć. Warunki: WARNING w logu brokera przy braku zmiennych; blok ACL `simulator` w `acl.conf` może zostać (reguła dla nieistniejącego konta jest bez skutku – test); symulator bez konta łączy się ponownie z cofaniem i loguje błąd autoryzacji raz na epizod. W k7: Grzegorz generuje hasło na IPC (`openssl rand -hex 24`), dopisuje do `.env` (prawa 600, bez `sudo`) i do kopii `.env` na laptopie, potem R-1. |
| K3-D2 | Reguła „sekcja główna tylko `real`” w collectorze | **Tak, w ingeście i w collectorze.** Warunek z k1: test starego kodu collectora i ingestu z nowym plikiem oraz nowego kodu z obecnym plikiem produkcyjnym – w raporcie. |
| K3-D3 | `SIM_BUFFER_MAX` | **36 000 – tak**, z pomiarem: szczytowy RSS kontenera przy pełnym buforze (test w `aip-test`, jak pomiar kolejki Mosquitto w etapie 2) – musi zostać zapas do 128 MiB. |
| K3-D4 | **QoS publikacji symulatora (nowe)** | **QoS 0 dla danych sim** (zamiast QoS 1). Powód: ingest ma trwałą sesję, a Mosquitto kolejkuje dla niego do 80 000 wiadomości. Dziś przy 20 wierszach/s to ok. 67 min danych prawdziwych przy przerwie ingestu; z symulatorem na QoS 1 (49/s) – **ok. 27 min**, potem broker odrzuca najnowsze, także prawdziwe. Wiadomości QoS 0 nie są kolejkowane dla rozłączonego klienta (`queue_qos0_messages false` – sprawdzić w `mosquitto.conf` i testem), więc kolejka zostaje dla danych prawdziwych. Danych sim nie trzeba przechowywać: są funkcją czasu i luki uzupełnia historia (k5, idempotentnie). Własny bufor symulatora (K3-D3) zostaje na krótkie przerwy brokera. Do sprawdzenia testem: ingest poprawnie zapisuje wiadomości QoS 0 (ręczne potwierdzenia nie mogą rzucać wyjątku dla QoS 0) i nie gubi przy tym wiadomości QoS 1 z `linia1`. Test: ingest zatrzymany 2 min przy działającym symulatorze i collectorze testowym → po powrocie wszystkie wiadomości `linia1` w bazie, `linia2` z luką. Przeliczyć i opisać w `docs/ops` czasy utraty danych przy przerwach (tabela z etapu 2) dla 20 + 29 wiadomości/s. |

## Uwagi

- **K3-U1 – `MODEL_VERSION` pilnowany wartościami wzorcowymi.** Sama obecność stałej w kluczu nie wykryje zmiany kodu modelu bez podbicia wersji. Dodać test z wzorcowymi sumami W·s jednej doby każdego licznika (i kilkoma wartościami pompy) zapisanymi w teście razem z `MODEL_VERSION`. Zmiana wyniku przy tej samej wersji = test czerwony z komunikatem „podbij `MODEL_VERSION` i zaktualizuj wzorce”.
- **K3-U2 – obraz testowy na IPC.** `docker build -t aip-simulator:test`, `docker run --rm`, potem `docker image rm aip-simulator:test` – tylko ten tag; bez `prune`, bez ruszania obrazów i kontenerów smartWARE (dokument 04, zasada 3). Wydruk `tzdata.IANA_VERSION`, `zoneinfo.TZPATH` i przesunięć UTC do raportu.
- **K3-U3 – zegar ścienny.** Przeskok przy spóźnieniu > 5 s – tak. Dodatkowo: skok zegara wstecz (korekta NTP) nie może publikować drugi raz tej samej sekundy z inną wartością – i tak nie może, bo wartość = f(t), a baza ma `ON CONFLICT DO NOTHING`; wystarczy test, że pętla nie zawiesza się przy cofnięciu zegara.
- **K3-U4 – pamięć sum przy 365 dniach.** Pomiar w `run-perf.sh` na `aip-test` – tak; w raporcie także rozmiar pliku `energy-days.json` po 365 dobach (4 liczniki).
- **K3-U5 – `docker-compose.yml` w repo zmienia się w k3**, ale produkcja zostaje na `c299eaa` (nie ma `git pull` w `~/ai-predykcja`). W raporcie: `git -C ~/ai-predykcja log -1` i `status` przed i po, `docker ps` bez `aip-simulator` na produkcji.
- **K3-U6 – budżet RAM.** Suma limitów 2560 MiB po dodaniu symulatora – zgodne z U-5 z K0; w raporcie zmierzone zużycie `aip-simulator` w teście (spoczynek i pełny bufor).

## Zrzuty

k3 bez GUI – zrzutów nie potrzeba. Pierwsze zrzuty w etapie 3: k6 (dashboardy „Flota” i „Pompa P-101”) i k7 (produkcja z danymi sim).

## Dalej

„Ok” Grzegorza → wykonanie k3 w worktree → pełne testy → `reviewer` → `e3-k3-report.md` → review.
