# E3-k6 – raport (krótki): dashboardy „Flota” i „Pompa”

Data: 2026-11-27. Commity: `234fb55`, `c8f108d`, `21cfa18`, raport (review planu w `8228332`). Produkcja bez zmian (c299eaa do k7).
**Uwaga: commity od `c8f108d` nie są w GitHubie** – push z laptopa odrzucony (403, uwierzytelnienie jako inne konto);
testy na IPC szły z tych commitów nałożonych łatkami na worktree `~/ai-predykcja-dev`.

## Wyniki

- **Dashboardy** z generatora (`grafana/generate.py`): `aip-flota` (tabela 5 liczników ze źródłem, stanem świeżości, mocą
  teraz i energią od północy; moc czynna; energia na godzinę skumulowana; udział w energii zakresu; oś świeżości danych)
  i `aip-pompa` (kafelki: drgania z ostatnich 60 minut pracy, temperatura łożyska i obroty teraz, minuty pracy dziś; trend
  dobowy drgań tylko z minut pracy, własny zakres 90 dni; drgania minutowe z minut pracy, obroty, temperatura, prąd, przepływ,
  udział minut pracy). Bez progów (K6-D1), sam `running` (K6-D2), bez prognozy (etap 5).
- **SYMULACJA (S10):** dopisek wyliczany w SQL z `devices.source` (stała `SIM_LABEL`); w generatorze nie ma żadnych nazw ani
  identyfikatorów urządzeń (test). Stały panel z objaśnieniem na górze obu dashboardów.
- **K6-U2:** w 5 dashboardach etapu 2 zmienia się tylko etykieta listy `$device` i linki nawigacji – test porównuje odcisk
  paneli, pozostałych zmiennych i adnotacji ze stanem `8228332` (identyczny); wartość zmiennej nadal `device_id`, Finder bez
  dopisku (test na danych).
- **Testy `slow` paneli (K6-D4):** `AIP_SLOW_PANELS=1`, fixture sesji ładuje przez MQTT i prawdziwy ingest 777 600 wiadomości
  (liczniki sim 2 h + pompa 84 doby) w ok. 620 s (1 600–1 640/s). Sprawdzenia: każdy panel w zakresach 15 min – 90 dni bez
  błędu i z danymi; tabela floty (4 × SYMULACJA, prawdziwe na górze, brak danych = puste, nie zero); trend drgań rośnie
  (ostatnie 6 dób pracy > 1,3 × pierwsze), 65–74 doby (bez niedziel), ≤ 16 h pracy na dobę; drgania puste w postoju; oś
  świeżości: „Brak danych” przed historią, „Dane” w niej.
- **Pełny zestaw z `slow`:** **756 passed, 6 skipped** (37 min).

| K6-U1: czasy paneli (maks. ze wszystkich zakresów) | s |
|---|---|
| Pompa – trend drgań (90 dni) | 0,25 |
| Pompa – udział minut pracy / drgania / obroty / przepływ / prąd / temperatura | 0,15–0,18 |
| Flota – świeżość danych / tabela / moc | 0,09–0,14 |
| pozostałe | ≤ 0,05 |

Wszystkie 16 paneli ≤ 0,25 s; żaden > 1 s (cel z etapu 2: ≤ 1 s).

| K6-U3: szczyt kontenerów w pełnym zestawie (`docker stats` co 15 s) | RAM / limit | CPU maks. |
|---|---|---|
| Grafana | **178 MiB / 512 MiB** (35 %) | 9 % (w przebiegu samych testów Grafany 87 %, 177 MiB) |
| baza testowa (tmpfs) | 808 MiB / 896 MiB | 92 % |
| pytest (ingest + narzędzie) | 87 MiB / 256 MiB | 99 % |

## Odstępstwa od planu

1. **Tytuł i lista „Pompa” zamiast „Pompa P-101”:** nazwa urządzenia nie może być w kodzie (zasada 3); dashboard nazywa się
   „Pompa”, a „Pompa P-101 (SYMULACJA)” pokazuje lista `$pump` z bazy.
2. Moc floty z `energy_1m` we wszystkich zakresach (bez gałęzi z `measurements` ≤ 6 h) – jedno zapytanie, 0,09 s.
3. Stos demonstracyjny w osobnym projekcie `aip-demo` (nie `aip-test`), żeby testy mogły działać obok; baza na dysku
   (`docker-compose.perf.yml`), Grafana tylko `127.0.0.1:3300` (K6-D3), ingest i symulator na żywo po historii, Finder
   bez danych na żywo (w stosie testowym nie ma PLC – w tabeli floty „Brak danych”).

## Do decyzji / ryzyka

1. **Baza testowa w tmpfs: 808 z 896 MiB** przy pełnym zestawie z danymi historii (dane Findera 30 dni + historia sim).
   Zapas 10 %; przy kolejnych danych w testach podniosę limit bazy testowej albo przeniosę testy `slow` na bazę dyskową
   (`docker-compose.perf.yml`). Proponuję drugie, gdy zapas spadnie poniżej 5 %.
2. **Push do GitHuba:** Grzegorz – sprawdź konto Git na laptopie (Menedżer poświadczeń Windows, `git:https://github.com`);
   po naprawie wypycham `main` i wyrównuję worktree na IPC do `origin/main`.

## Zrzuty

Stos `aip-demo` uruchomiony (`sh tests/run-demo.sh up`); instrukcja w odpowiedzi czatu. Zrzuty do `docs/images/etap3/`
(`01-…`), lista 8 z planu. Po zrzutach: `sh tests/run-demo.sh down`.

Raport e3-k6 gotowy do przeglądu.
