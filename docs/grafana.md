# Grafana: ściąga dla użytkownika i opis dashboardów

Grafana pokazuje dane, które zbieramy z PLC i licznika Finder 7M.24. Działa lokalnie (bez internetu), w sieci biurowej pod adresem
**`http://192.168.0.213:3000`** (HTTP, bez szyfrowania: ruch i hasło idą jawnie po sieci lokalnej; szyfrowanie dojdzie w etapie 7).

## Jak się zalogować

1. Otwórz `http://192.168.0.213:3000` w przeglądarce na laptopie (ta sama sieć co komputer przemysłowy).
2. Użytkownik i hasło administratora to `GF_SECURITY_ADMIN_USER` i `GF_SECURITY_ADMIN_PASSWORD` z pliku `.env` (kopia na laptopie; plik nie trafia do repozytorium).
3. **Hasła nie zmieniamy w interfejsie**: źródłem jest `.env`, a wartość z `.env` działa tylko przy pierwszym utworzeniu bazy Grafany.
4. Brak dostępu anonimowego i rejestracji. Strona startowa to „Przegląd”.

## Gdzie co jest (folder „AI Predykcja”)

| Dashboard | Do czego służy | Odświeżanie |
| --- | --- | --- |
| **Przegląd** | stan PLC i licznika, moc teraz, zużycie dziś i wczoraj, moc maksymalna dziś, cos φ, pokrycie danych, wiek ostatniego odczytu, epizody błędu licznika | 30 s |
| **Licznik na żywo** | U, I, P, Q, S, PF i f jako wykresy i kafelki, z wartościami min/maks./średnia w oknie | 5 s, domyślnie ostatnie 15 min |
| **Jakość energii** | napięcie z pasmem orientacyjnym, minuty poza pasmem, histogram napięcia, odchyłka częstotliwości, cos φ i stosunek Q/P | ręczne |
| **Energia i profil** | zużycie na minutę, godzinę i dobę z pokryciem, profil godzina × dzień tygodnia, porównania (doba i tydzień wcześniej), moc bazowa, kontrola z licznikiem wzorcowym | ręczne |
| **Stan i diagnostyka** | oś stanów łącza z PLC i licznika, kody błędów komunikacji, liczniki błędów, wiek danych, sekundy bez pomiaru, wiersze na minutę | ręczne |

U góry każdego dashboardu: wybór licznika (**Licznik**; kolejne liczniki z etapu 3 pojawią się tam same), linki do pozostałych dashboardów (zachowują czas i licznik)
oraz zakres czasu. Pionowe oznaczenia na wykresach to **okna testów i przerw** (restart, zanik zasilania, testy, wdrożenia); najechanie kursorem pokazuje opis.

## Co znaczą kolory i stany

| Kolor | Stan |
| --- | --- |
| zielony | OK: PLC działa / licznik działa |
| czerwony | błąd: PLC offline, błąd komunikacji z licznikiem, **„Brak danych z PLC”** |
| pomarańczowy | licznik nie ma danych po starcie PLC lub nie ma świeżego statusu |
| fioletowy | błąd konfiguracji: zła wersja mapy rejestrów lub inny licznik niż w `config/devices.yaml` |
| szary „Brak danych” | luka w danych: collector zatrzymany, zanik zasilania, awaria zapisu |

Pełna lista kodów i komunikatów: `docs/status-codes.md` (dashboardy biorą je z tego pliku). **„Brak danych z PLC”** pokazuje kafelek stanu licznika, gdy łącze z PLC
nie działa (`link_status` inne niż 0) albo ostatni wpis o łączu jest starszy niż 10 sekund; wtedy stan licznika jest nieznany, a nie „dobry”.

**Pokrycie** to część czasu, w której mamy pomiar mocy (liczba próbek × okres próbkowania / długość okna). 100% = bez luk. Przy pokryciu poniżej 100% energia z pomiarów
jest **dolną granicą** (luk nie wypełniamy): dlatego obok jest „szacunek pełnej doby” (energia / pokrycie, tylko gdy pokrycie ≥ 50%) oraz przyrost licznika wzorcowego.
Licznik zmienia stan co 100 Wh, więc przy obciążeniu rzędu kilku watów przyrost dobowy to 1–2 kroki i porównanie procentowe nie ma sensu: główną miarą zgodności jest kolumna
„W granicach rozdzielczości” (różnica nie większa niż jeden krok licznika), a odchyłka procentowa pojawia się dopiero przy przyroście co najmniej 5 kroków.
Bieżąca minuta, godzina i doba mają pokrycie poniżej 100% z natury (jeszcze trwają).

Wykresy nie łączą punktów przez luki: przerwa w linii oznacza brak danych, a nie zero.

## Progi i stałe (zmienne dashboardu)

Progi są zmiennymi u góry dashboardów, więc zmieniasz je bez edycji zapytań (wpisz wartość w polu i naciśnij Enter). Domyślne wartości są w jednym miejscu: `grafana/generate.py` (słownik `DEFAULTS`).

| Zmienna | Domyślnie | Gdzie | Znaczenie |
| --- | --- | --- | --- |
| Napięcie znamionowe [V] | 230 | Jakość energii | środek pasma napięcia |
| Pasmo napięcia [± %] | 10 | Jakość energii | **orientacyjne** (230 V ±10% to 207–253 V); to nie jest ocena zgodności z normą |
| Częstotliwość znamionowa [Hz] | 50 | Jakość energii | punkt odniesienia odchyłki |
| Pasmo częstotliwości [± Hz] | 0,2 | Jakość energii | orientacyjne pasmo odchyłki |
| Dane uznane za stare po [s] | 10 | Przegląd, Stan i diagnostyka | próg kafelka „Brak danych”, luk na osi stanów |

**Zmiany w interfejsie nie są trwałe.** Dashboardy są plikami w repozytorium (`grafana/dashboards/*.json`, generowane przez `grafana/generate.py`). Edycja w interfejsie jest dozwolona do prób,
ale po restarcie Grafany lub zmianie pliku wraca wersja z repozytorium. Trwałą zmianę wprowadza się w `grafana/generate.py`, uruchamia `python grafana/generate.py` i commituje oba pliki.

## Wielkości (definicje)

- **Moc czynna P [W]**: faktycznie pobierana moc; z niej liczymy energię. **Moc bierna Q [var]** i **pozorna S [VA] = U × I**. **cos φ / PF = P / S**.
- **Energia z całki mocy [Wh]** = suma mocy czynnej z obecnych próbek × okres próbkowania (1 s) / 3600.
- **Moc bazowa [W]**: 5. percentyl średniej minutowej mocy czynnej w godzinach lokalnych 00:00–05:00 w danej dobie (obciążenie tła).
- **Minuty poza pasmem**: liczba minut, w których minimum lub maksimum napięcia wyszło poza pasmo orientacyjne.
- **Epizod błędu licznika**: przejście `meter_status` z 0 na wartość inną niż 0. Brak danych z powodu awarii PLC nie jest błędem licznika.
- Doba w tabelach to doba lokalna (`Europe/Warsaw`; przy zmianie czasu ma 23 lub 25 godzin).

## Dla administratora

- Źródło danych: PostgreSQL/TimescaleDB jako rola **`app_reader`** (tylko odczyt, limit czasu zapytania 10 s, pula 5 + 2 połączenia). Zapis przez Grafanę jest niemożliwy (testowane).
- Zapytania dla długich zakresów czytają agregaty (`energy_1m`, `energy_1h`) i widoki, nie surową tabelę. Przyrost licznika w panelach minutowych liczą zapytania sami (widok `energy_1m_calc` na roku danych trwa kilkanaście sekund, patrz `docs/handoff/e2-k7-report.md`).
- Okna testów i przerw: tabela `data_windows` (migracja `004`); nowe okno dopisuje się nową migracją.
- Kopie zapasowe i odtwarzanie: etap 7. Wersja obrazu i operacje: `docs/ops/jumo-ipc-setup.md`.
