# e2-k7 review: Grafana, pięć dashboardów

Recenzent: architekt (czat projektu), 24.11.2026. Podstawa: `docs/handoff/e2-k7-plan.md`, `e2-k7-zakres.md`, `e2-k6-report-review.md`, dokument projektu 12.

## Werdykt: OK

Plan realizuje rozszerzony zakres w całości:
- pomiar K6-U4 przed Grafaną, z jasną regułą decyzji;
- provisioning jako kod;
- `app_reader` z limitami połączeń;
- 5 dashboardów ze zmienną `$device`;
- adnotacje;
- harness zapytań przez API dla każdego panelu, na danych testowych i prawdziwych;
- kafelek K3-U3 z testem przypadków;
- izolacja i brak sekretów w raportach.

Dobre są też:
- brak wtyczek (komputer bez internetu);
- jednokrotny wybór `$device` – świadome ograniczenie harnessu;
- „brak danych ≠ zero”.

## Decyzje G7-a…G7-j – wszystkie zatwierdzone

| Id | Rozstrzygnięcie |
| --- | --- |
| G7-a | Najnowsza stabilna wersja główna, tag + digest po `docker pull`, w raporcie i `docs/ops` – zatwierdzone. Healthcheck: sprawdzić, czy obraz ma `wget`/`curl`; inaczej healthcheck przez wbudowane narzędzie lub test portu |
| G7-b | `generate.py` + JSON w repo + test braku dryfu – zatwierdzone |
| G7-c | Mapa cieplna: „Grouping to matrix” + tabela z kolorowaniem, zapas: pivot w SQL przez `FILTER` – zatwierdzone; wygląd ocenimy na zrzucie Grzegorza |
| G7-d | Tabela `data_windows` przez migrację 004, tylko odczyt dla `app_reader` – zatwierdzone |
| G7-e | Harness w `aip-test` + ten sam przebieg na prawdziwej bazie przez `docker exec` – zatwierdzone |
| G7-f | Progi jako zmienne dashboardu, domyślne z generatora – zatwierdzone |
| G7-g | `GF_SECURITY_SECRET_KEY` – **zatwierdzone, z kolejnością i podziałem ról niżej** |
| G7-h | HTTP na porcie 3000 w LAN bez TLS – zatwierdzone dla demo (sieć biurkowa); TLS i odwrotne proxy w etapie 7; opis ryzyka w `docs/ops` |
| G7-i | `Europe/Warsaw`, `pl-PL`, jeśli dostępne – zatwierdzone |
| G7-j | Wyłączenia sieciowe – zatwierdzone |

### G7-g – jak dopisać klucz

Klucz szyfruje sekrety w bazie Grafany (m.in. hasło `app_reader` w źródle danych). Musi być w `.env` **przed pierwszym startem** wolumenu `aip_grafana_data`. Późniejsza zmiana unieważnia zaszyfrowane dane, tak jak hasło admina i `POSTGRES_PASSWORD`. Claude Code nie widzi `.env`, a Grzegorz trzyma kopię na laptopie, więc klucz dopisuje **Grzegorz** w konsoli `jumo@jumo-ipc`, po wypchnięciu nowego `.env.example`. Polecenie poda Claude Code (wzór):

```bash
cd /home/jumo/ai-predykcja && ( umask 077; grep -q '^GF_SECURITY_SECRET_KEY=' .env || printf 'GF_SECURITY_SECRET_KEY=%s\n' "$(openssl rand -hex 16)" >> .env ); awk -F= '/^GF_SECURITY_SECRET_KEY=/{print $1, length($2)}' .env; stat -c '%a %U' .env
```

Oczekiwane: `GF_SECURITY_SECRET_KEY 32` i `600 jumo`. Potem Grzegorz przenosi tę jedną linię do kopii `.env` na laptopie (`cat`/`grep` na komputerze, wklejenie w Notatniku). Plik `.env` na laptopie jest ignorowany przez git. Kolejność w kroku 2: `.env.example` → klucz od Grzegorza → pierwszy start Grafany.

## Odpowiedzi na pytania

**1. Okna z dokumentu projektu 12.** Poza siedmioma oknami z raportu k5 w dokumencie 12 są:
- `power_outage`: 2026-11-23T23:16:57Z – ok. 2026-11-24T06:52Z (zanik zasilania PLC, licznika i komputera). Dokładny koniec wyznaczyć z danych, zgodnie z planem;
- `collector_stopped`: okno diagnostyki E2-PLC1 z 24.11 (15 min bez collectora) – dokładne czasy są w `docs/handoff/e2-plc1-diag.md`;
- `deploy`: wdrożenie k6, ok. 14:33:59–14:34:30Z (restart collectora i ingestu).

Okno `calm_window` (22:41–22:51Z, 23.11) to okno referencyjne, nie przerwa. W tabeli może zostać jako adnotacja informacyjna, ale analityka ma go nie wyłączać – dodać kolumnę lub `kind` pozwalający to odróżnić (np. `exclude_from_analytics BOOLEAN`).

**2. Zużycie dziś / wczoraj.** Zgoda z propozycją:
- wartość główna: energia z obecnych próbek (dolna granica) z pokryciem obok;
- wartość pomocnicza: ekstrapolacja do pełnej doby (całka / pokrycie) tylko przy pokryciu ≥ 0,5, z opisem panelu;
- przyrost licznika wzorcowego jako trzecia, informacyjna liczba (kwantyzacja 100 Wh).

## Drobne

- `docs/grafana.md`: krótka ściąga dla Grzegorza – jak zalogować się z laptopa, gdzie jest który dashboard, co znaczą kolory stanu i pokrycie, jak zmienić progi (zmienne dashboardu) i że zmiany w GUI nie są trwałe.
- Raport: zrzut ekranu nie jest potrzebny od Claude Code. Jeśli panel przeglądarki ma dostęp do `192.168.0.213:3000`, wystarczy krótka ocena wizualna (np. mapa cieplna, luki na wykresach).
- Pamięć Grafany po 10 minutach z otwartym dashboardem „Licznik na żywo” (odświeżanie 5 s), nie tylko w spoczynku.

## Checklista Grzegorza w k7

1. Na prośbę Claude Code: polecenie dopisujące `GF_SECURITY_SECRET_KEY` (wyżej) i przeniesienie linii do kopii `.env` na laptopie.
2. Po wdrożeniu: logowanie z laptopa (`http://192.168.0.213:3000`, `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` z `.env`).
3. Zrzuty pięciu dashboardów (zakres ostatnie 24 h) do `docs/images/etap2/`.

## Następny krok

Po „ok” Grzegorza: Claude Code wykonuje k7 wg planu i tego review → `e2-k7-report.md` → stop.
