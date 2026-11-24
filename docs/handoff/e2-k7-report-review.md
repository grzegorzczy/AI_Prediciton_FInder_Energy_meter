# e2-k7 report review: Grafana, pięć dashboardów

Recenzent: architekt (czat projektu), 24.11.2026. Podstawa: `docs/handoff/e2-k7-report.md` (commit `85d0c7a`), `e2-k7-review.md`, `e2-k7-zakres.md`.

## Werdykt: OK – technicznie zaliczony; ocena wizualna po zrzutach Grzegorza

| Kryterium | Dowód | Ocena |
| --- | --- | --- |
| Grafana | 13.0.2 z digestem, `healthy`, uid 472, 384 MB, anonim 401, rejestracja wyłączona, klucz i hasło tylko z `.env` | ✔ |
| Źródło danych | `app_reader`, 5/2 połączenia, 6 rodzajów zapisu odrzuconych | ✔ |
| Panele na prawdziwej bazie | 200 zapytań (5 × 4 zakresy), 0 błędów, maks. 0,33 s | ✔ |
| Wydajność na roku | panele ≤ 339 ms; „Na żywo” na dobie ≤ 202 ms | ✔ |
| K3-U3, `$device`, adnotacje | 12 przypadków kafelka; dwa liczniki bez mieszania; 10 okien w `data_windows` | ✔ |
| Pamięć | Grafana 175 MiB maks. przy otwartym „Na żywo”; suma `aip-` w użyciu ok. 380 MiB | ✔ |
| Testy, izolacja | 407/407; nowy tylko port 3000; smartWARE bez zmian; tylko `git pull` | ✔ |
| `meter_error_code` na żywo | 18 epizodów w ok. 1 h 45 min; w każdym 161 w pierwszej sekundzie, potem 162; dokładnie 5 wierszy/s błędu | ✔ (zamyka punkt z k6) |

Odstępstwa 1–9 akceptowane. W szczególności:
- pivot SQL dla mapy cieplnej (zapas z review);
- panele bez widoku `energy_1m_calc`;
- zapas 3 dni w `LAG`;
- większa baza testowa;
- poprawka wyścigu w pomocniku testowym.

## Decyzje

1. **`energy_1m_calc` (17 s na roku):** przepisanie w **pierwszym kroku etapu 4**, przed analityką. Kierunek: funkcja SQL z zakresem czasu (`STABLE`, `SECURITY INVOKER`, `SELECT` dla `app_reader`) z wyszukaniem poprzedniego wiaderka z ograniczeniem, zgodnie z receptą z testu. Widoku do tego czasu nikt nie używa; w `docs/data-model.md` dopisać ostrzeżenie „nie używać na długich zakresach – patrz K6-U4”.
2. **Konto Grafany dla Claude Code do oceny wizualnej:** **nie zakładamy**. Mniej kont to mniejsza powierzchnia ataku przy jawnym HTTP. Ocena wizualna: zrzuty Grzegorza, przegląda je architekt; poprawki wyglądu wracają do Claude Code jako lista.
3. **Port 3000 z laptopa:** sprawdzi Grzegorz przy logowaniu. Jeśli się nie otworzy, Claude Code ustali stan zapory poleceniem bez `sudo` (np. `ufw status` wymaga `sudo` – wtedy polecenie dla Grzegorza).
4. **Epizody 161 → 162:** odnotowane do E2-PLC1 (przekroczenie czasu w pierwszej sekundzie, potem przekłamane odpowiedzi przez ok. 3 s). Diagnoza nadal odłożona.

## Następne kroki

1. Grzegorz: logowanie i zrzuty pięciu dashboardów (zakres 24 h) do `docs/images/etap2/` (nazwy `03-grafana-przeglad.png`, `04-grafana-na-zywo.png`, `05-grafana-jakosc.png`, `06-grafana-energia.png`, `07-grafana-diagnostyka.png`). Kopia `GF_SECURITY_SECRET_KEY` w `.env` na laptopie.
2. Architekt: przegląd zrzutów → lista poprawek wyglądu (jeśli będą) dla Claude Code.
3. Potem decyzja Grzegorza: **E2-PLC2** (nowe dane z licznika) czy **k8** (restart komputera, dysk po dobie, naprawa logów Dockera, dokumentacja Word v2).

## Checklista Grzegorza po k7

Jak w raporcie, pkt 1–4.
