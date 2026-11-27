# E3-k5 – review planu (architekt)

Data: 2026-11-27. Plan: `e3-k5-plan.md` (`728fb4a`). Review krótkie (dokument 04).

**Werdykt: OK Z UWAGAMI – wykonuj po „ok” Grzegorza.**

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K5-D1 | `--fill-gaps` z odczytem bazy kontem `app_reader` | **Tak**, ale hasło bazy nie trafia do usługi na żywo. Osobna usługa w compose, np. `simulator-tools` z `profiles: [tools]` (nie startuje przy `up -d`), ten sam obraz i wolumen `aip_simulator_data`, zmienne `DB_*` tylko tam; uruchamianie `docker compose run --rm simulator-tools …`. Usługa `simulator` bez zmiennych bazy (test compose). |
| K5-D2 | `--inflight 100`, bez sufitu tempa | **Tak** jako domyślne. Pilotaż (k5 i k7) mierzy wpływ na dane real; jeśli w pilotażu na produkcji dane real mają luki albo `aip-ingest` zbliża się do limitu RAM, w k7 ustawiamy `--rate` z pomiaru. |

## Uwagi

- **K5-U1 – kompletność wszystkich metryk.** `--fill-gaps` ma sprawdzać każdą publikowaną metrykę (liczniki: 6, pompa: 5). Jeśli `energy_1m` nie liczy którejś metryki sim (np. `reactive_power`, `power_factor`), zapytanie dla niej idzie do `measurements` w krótkich zakresach (np. doba), żeby zmieścić się w `statement_timeout` 10 s konta `app_reader`. W teście: usunięte wiersze tylko jednej metryki są wykryte i uzupełnione.
- **K5-U2 – dysk i WAL.** 29 mln wierszy przed kompresją to ok. 5,5 GB (190 B/wiersz) plus WAL. W pilotażu zmierzyć bajty na wiersz i przyrost wolumenu bazy na dobę historii; w procedurze k7 kontrola wolnego miejsca przed pełnym wgraniem (próg: co najmniej 3 × prognoza). Kompresja nowych chunków zrobi się polityką po wgraniu – w raporcie k7 rozmiar przed i po.
- **K5-U3 – pilotaż na `aip-test` w tmpfs.** Wynik to górna granica tempa (zgodnie z planem). Poza tempem podać: RAM i CPU `ingest`, `timescaledb`, `mosquitto`, symulatora; czy kolejka brokera dla ingestu pozostaje bliska zera.
- **K5-U4 – pamięć sum dobowych.** Narzędzie historii korzysta z tego samego pliku `energy-days.json` (wolumen) – liczniki w historii nie liczą dób od nowa; test.

## Dalej

„Ok” Grzegorza → wykonanie k5 → pełne testy → `reviewer` (nowy dostęp do bazy) → raport `e3-k5-report.md` → review.
