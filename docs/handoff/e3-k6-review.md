# E3-k6 – review planu (architekt)

Data: 2026-11-27. Plan: `e3-k6-plan.md` (`8d1ef3c`). Review krótkie (dokument 04).

**Werdykt: OK Z UWAGAMI – wykonuj po „ok” Grzegorza.** Znacznik SYMULACJA z `devices.source` (nie z nazw), trend drgań tylko z minut pracy, bez prognozy (etap 5) – zgodnie z S9, S10, K4-D2. `reviewer` niepotrzebny – zgoda.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K6-D1 | Linie progów drgań | **Nie w k6.** 1,1–7,0 mm/s to zakres modelu, nie próg; strefy ISO wymagają klasy maszyny od Grzegorza (zasada 7) – pytanie w etapie 5. |
| K6-D2 | Minuta pracy w panelach | **Sam `running`** w k6; minimum próbek dla danych na żywo – etap 5. |
| K6-D3 | Skąd zrzuty | **`tests/run-demo.sh` + tunel `ssh -L` do Grafany testowej – tak.** Warunki: Grafana testowa tylko na `127.0.0.1` IPC (tunel z laptopa, bez portu w LAN); `run-demo.sh down` po zrzutach – stos testowy nie zostaje na noc (RAM i harness nie obok produkcji dłużej niż trzeba). Zrzut końcowy z produkcji i tak w k7. |
| K6-D4 | Dane testowe w zwykłym zestawie (+10 min) | **Pompa co 1 min jak produkcja – tak, ale testy paneli z tymi danymi oznaczone `slow`**: uruchamiane w k6, w k8 i przy krokach zmieniających Grafanę lub agregaty; zwykły zestaw bez nich. Dane ładowane raz na sesję (wspólna fixture). |

## Uwagi

- **K6-U1 – czas paneli.** Próg twardy 3 s – zgoda, ale w raporcie czasy wszystkich paneli; z etapu 2 cel ≤ 1 s na roku danych (najwolniejszy był 0,35 s). Panel powyżej 1 s – wyjaśnienie w raporcie.
- **K6-U2 – istniejące dashboardy.** Dopisek SYMULACJA na liście `$device` zmienia 5 dashboardów etapu 2: test, że dla Findera i PLC zapytania i wyniki są bez zmian (tylko etykieta listy).
- **K6-U3 – pamięć Grafany.** Szczyt pamięci w raporcie wobec limitu 512 MiB (OOM w etapie 2 przy masowym teście na produkcji).

## Zrzuty od Grzegorza

Lista 8 zrzutów z planu – OK. Zrzuty do `docs/images/etap3/` (`01-…` poprawny stan), w Wordzie v3. Robię ich przegląd wizualny (jak w etapie 2) przed zamknięciem k6.
