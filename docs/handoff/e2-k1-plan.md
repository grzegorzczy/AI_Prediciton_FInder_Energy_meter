# e2-k1 plan: przygotowanie komputera `jumo-ipc`
Status: DO PRZEGLĄDU

Podstawa: `docs/handoff/e2-k0-plan.md`, `docs/handoff/e2-k0-review.md` (OK Z UWAGAMI;
decyzje D1–D11, uwagi U1–U8), `CLAUDE.md`. Krok nie zawiera kodu usług. Powstają polecenia
do wykonania na komputerze, ich wyniki i jeden dokument operacyjny.

## Cel kroku

Po k1 komputer 192.168.0.213 ma: poprawne repozytorium APT Dockera (`jammy`) z zablokowaną
wersją pakietów Dockera, sklonowane repo przez **deploy key tylko do odczytu**, potwierdzone
porty, czas, miejsce i bazowe zużycie zasobów. Kontenery JUMO smartWARE działają
**bez zmian**: nie restartujemy demona Dockera i nie aktualizujemy jego pakietów.

**Sprawdzalny wynik:** komplet wyników poleceń z sekcji „Jak sprawdzę” w `e2-k1-report.md`,
w tym `apt-mark showhold`, `docker ps` sprzed i po zmianach (te same kontenery, ten sam czas
działania) oraz `git pull` działający na komputerze, a `git push` z komputera odrzucony.

## Co powstaje / zmienia się

Na komputerze (nie w repo, wszystko wykonuje Grzegorz):

- zmiana wpisu Dockera w źródłach APT (`focal` → `jammy`), kopia pliku obok;
- blokada wersji pakietów Dockera (`apt-mark hold`);
- klucz `~/.ssh/ai_predykcja_deploy` (ed25519), wpis w `~/.ssh/config`;
- sklonowane repo w `/home/jumo/ai-predykcja` (nazwa katalogu do potwierdzenia, K1-a).

W repo:

- `docs/handoff/e2-k1-report.md` (raport kroku, po wykonaniu);
- `docs/ops/jumo-ipc-setup.md`: jednorazowa instrukcja przygotowania komputera (te same
  polecenia, kolejność, kryteria zatrzymania). Przyda się w etapie 7 (instalacja na drugim
  komputerze); w k1 jest to jedyny nowy plik poza raportem.

Nie zmieniam: `docker-compose.yml` (jeszcze nie istnieje), `.env.example`, `docs/modbus-map.md`.

## Zasady wykonania

- Polecenia z laptopa w cmd: `ssh jumo@192.168.0.213 "<polecenie>"`; z sudo `ssh -t …`.
  Hasło sudo wpisuje Grzegorz; ja go nie widzę.
- **Dwie rundy.** Runda 1: tylko odczyty (nic nie zmienia stanu). Na podstawie wyników
  przygotowuję dokładne polecenia rundy 2 (zmiany); nie zgaduję nazwy pliku źródeł Dockera
  ani listy zainstalowanych pakietów.
- Kopia przed każdą zmianą pliku systemowego. Po każdej zmianie wynik do raportu.
- **Kryteria zatrzymania** (przerywam i pytam, bez próby obejścia): `lsb_release -cs` ≠
  `jammy`; brak `docker compose`; porty 1883 lub 3000 zajęte; zegar niezsynchronizowany;
  `apt update` zgłasza błąd (nie samo ostrzeżenie o focal, tylko błąd, np. `NO_PUBKEY`);
  `git` nie jest zainstalowany; cokolwiek, co wymagałoby `apt upgrade` lub restartu demona Dockera.

## Runda 1: odczyty

Wyniki wklejamy do raportu w całości (bez haseł, których tu nie ma).

1. System: `lsb_release -cs`, `uname -m`, `hostname`.
2. Źródła Dockera: `grep -rn "download.docker.com" /etc/apt/sources.list /etc/apt/sources.list.d/`
   oraz `ls -l /etc/apt/sources.list.d/`. Wynik pokaże plik i format (klasyczny `.list` albo `.sources`).
3. Pakiety Dockera: `dpkg -l | grep -i -E "docker|containerd"`.
4. Docker: `docker --version`, `docker compose version`, `systemctl is-enabled docker`,
   `systemctl is-active docker`.
5. Stan smartWARE **przed** zmianami: `docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"`
   (zapisujemy nazwy i czas działania; po zmianach ma się zgadzać).
6. Porty: `ss -ltn`. Oczekiwane: 80 i 443 zajęte (smartWARE), 1883 i 3000 wolne.
7. Czas: `timedatectl`. Oczekiwane: `System clock synchronized: yes`, strefa Europe/Berlin.
   **Strefy nie zmieniamy** (U7: dotyczy smartWARE); baza używa UTC, Grafana pokazuje Europe/Warsaw.
8. Zasoby bazowe: `free -m`, `df -h /`, `nproc`, `docker stats --no-stream` (smartWARE w liczbach).
9. Narzędzia: `git --version`, `ssh -V`, `openssl version`.
10. Aktualizacje automatyczne: `systemctl is-enabled unattended-upgrades` oraz
    `apt-config dump | grep -i Unattended-Upgrade::Package-Blacklist` (czy bez blokady mogłyby
    zaktualizować Dockera; blokada `hold` chroni też przed nimi).

## Runda 2: zmiany

### 2a. Repozytorium Dockera, `focal` → `jammy`, blokada wersji (D11)

Zakładam, że wynik rundy 1 potwierdza `jammy`; jeśli nie, zatrzymuję się (patrz kryteria).

1. Kopia pliku źródeł: `sudo cp -a <PLIK> <PLIK>.bak-focal` (nazwa pliku z rundy 1).
2. Zamiana `focal` na `jammy` **tylko we wpisie Dockera**. Polecenie zależne od formatu:
   dla klasycznego `.list` `sed` na linii z `download.docker.com`, dla deb822 (`.sources`)
   na linii `Suites:`. Wynik porównujemy: `diff <PLIK>.bak-focal <PLIK>` (jedna zmieniona
   linia).
3. `sudo apt update`: bez ostrzeżeń o repozytorium Dockera. Ostrzeżenia dotyczące innych
   repozytoriów zapisuję w raporcie, nie naprawiam.
4. **Bez `apt upgrade` i bez `apt install` pakietów Dockera.** Aktualizacja restartuje demona,
   a z nim kontenery smartWARE.
5. Blokada wersji tylko dla pakietów faktycznie zainstalowanych (z rundy 1, pkt 3), spośród:
   `docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin`:
   `sudo apt-mark hold <lista>`; potem `apt-mark showhold` do raportu.
6. Powtórka `docker ps` (jak w rundzie 1, pkt 5): te same kontenery, czas działania bez
   resetu (potwierdza, że demon nie został zrestartowany).

Notatka na przyszłość (do `docs/ops/jumo-ipc-setup.md`): `hold` blokuje też poprawki
bezpieczeństwa Dockera. Świadoma aktualizacja wymaga okna serwisowego, bo restart demona
zatrzyma kontenery smartWARE; w etapie 2 jej nie robimy.

### 2b. Deploy key tylko do odczytu i klon repo (D5)

1. Klucz na komputerze, bez hasła (potrzebne do `git pull` bez udziału człowieka; ryzyko
   ograniczone: klucz daje tylko odczyt tego jednego repo, w którym nie ma sekretów; prawa 600):
   `ssh-keygen -t ed25519 -C "jumo-ipc deploy key read-only" -f ~/.ssh/ai_predykcja_deploy -N ""`.
2. Klucz publiczny wypisujemy: `cat ~/.ssh/ai_predykcja_deploy.pub`. **Klucz prywatny
   nigdy nie jest wypisywany ani wklejany do czatu ani repo.**
3. Grzegorz dodaje go w GitHub → repo → Settings → Deploy keys → Add deploy key, tytuł
   `jumo-ipc`, **bez zaznaczenia „Allow write access”**.
4. Wpis w `~/.ssh/config` (prawa 600, `IdentitiesOnly yes`) z aliasem `github-ai-predykcja`,
   żeby ten klucz był używany wyłącznie do tego repo.
5. Pierwsze połączenie z GitHubem: porównujemy odcisk klucza serwera z listą opublikowaną
   przez GitHub (strona „GitHub's SSH key fingerprints”) **zanim** wpiszemy `yes`. Ja nie
   podaję odcisku z pamięci; podam adres strony w poleceniach.
6. Test: `ssh -T git@github-ai-predykcja` (oczekiwane: potwierdzenie uwierzytelnienia i
   informacja, że GitHub nie daje powłoki).
7. Klon: `git clone git@github-ai-predykcja:grzegorzczy/AI_Prediciton_FInder_Energy_meter.git ~/ai-predykcja`.
   Repo zawiera plik projektu PLC (ok. 25 MB, kilka wersji w historii), więc klon trwa
   dłużej; to normalne.
8. Kontrola `main` zgodny z GitHubem: `git -C ~/ai-predykcja log --oneline -3`
   (hash ostatniego commitu zgodny z `af997a3` lub nowszym).
9. Kontrola, że klucz jest tylko do odczytu: `git -C ~/ai-predykcja push --dry-run origin main`
   powinien zostać odrzucony. Jeśli `--dry-run` nie dotknie uprawnień zapisu i przejdzie,
   raportuję to wprost, a o braku zapisu świadczy odznaczone pole w GitHubie (zrzut ekranu
   listy Deploy keys bez słowa „write”).
10. Aktualizacja w przyszłości: `git -C ~/ai-predykcja pull --ff-only`.

### 2c. Przygotowanie pod k2 (bez zmian systemu)

- **`.env`:** w k1 **go nie tworzymy**. Zmienne zmienią się w k2 (D3: `MQTT_COLLECTOR_*` i
  `MQTT_INGEST_*` zamiast `MQTT_USER/MQTT_PASSWORD`), więc plik powstanie razem z nowym
  `.env.example`. Odstępstwo od k0: tam k1 miał obejmować `.env`. W k1 sprawdziłem tylko, że
  `.gitignore` ignoruje `.env` i przepuszcza `.env.example` (potwierdzone).
- Zasady na k2: `chmod 600 .env`; hasła **hex**, nie base64 (`openssl rand -hex 24`).
  Odstępstwo od propozycji w review (`-base64`): base64 daje znaki `+ / =`, które psują
  adresy połączeń z bazą i polecenia powłoki; hex jest alfanumeryczny, 192 bity entropii.
  Hasła wpisuje Grzegorz; ja ich nie widzę.
- Katalog klonu nie jest wolumenem kontenerów; dane kontenerów będą w nazwanych wolumenach
  Dockera, więc `git pull` nie ruszy danych.

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| K1-a | Katalog klonu | `/home/jumo/ai-predykcja` | Krótka nazwa bez wielkich liter; nie koliduje z niczym; w `docs/ops` zapisana jako stała |
| K1-b | `git` na komputerze | Jeśli go brakuje: zatrzymuję się i pytam przed `apt install git` | Instalacja nie dotyka pakietów Dockera, ale każda zmiana pakietów na komputerze z smartWARE wymaga Twojej zgody |
| K1-c | `docker compose` brak | Jeśli brakuje wtyczki: zatrzymuję się i pytam | Instalacja `docker-compose-plugin` to zmiana pakietów Dockera pod `hold`; nie robię jej samowolnie |
| K1-d | Klucz bez hasła | Tak | `git pull` ma działać bez człowieka; uzasadnienie wyżej |

## Przekazanie decyzji D1–D11 i uwag U1–U8 do planów kolejnych kroków

Nie zmieniam e2-k0-plan (review: „bez ponownego planu e2-k0”). Każdy plan kroku, który ich
dotyczy, uwzględni je jawnie w sekcji „Decyzje”; mapa:

| Krok | Uwzględnia |
| --- | --- |
| k1 (ten plan) | D5, D11, U7 (strefa Europe/Berlin, tylko kontrola NTP), U3 (stan portów przed startem), drobne: `.gitignore`, prawa `.env`, hex zamiast base64 |
| k2 | D1 (`site: zaklad1`, `line: linia1`), D3 (konta MQTT i ACL, nowe zmienne), D4 + U5 (role i hasła w `migrate`, `GRANT`, `DEFAULT PRIVILEGES`, `statement_timeout`, brak `CREATE`), D9 (przypięte wersje), U1 (schemat `devices` z `plc-01`, `kind: plc`), U3 (Mosquitto bez portu w LAN lub `127.0.0.1:1883`, Grafana z hasłem i wyłączonym anonimowym dostępem; `ss -ltn` w raporcie), U6 (`TS_TUNE_MEMORY` lub `NO_TS_TUNE`, wynik `SHOW shared_buffers/max_connections/work_mem`), `devices.yaml` montowany `:ro`; zrzuty po k2 (`docker compose ps`, odmowa `mosquitto_sub` bez hasła) |
| k3 | D2, D10 + U2 (`link_status` 0–3: 3 = zła `map_version`; `meter_status` 0–2 z rejestru 10, 10 = `SERIAL_MISMATCH` liczony przez collector; kody w jednym miejscu, enum), nowy filtr 3 s w PLC (mapa: `status` 1 od pierwszego błędu, `error_count` = liczba przerw, `data_age_ms` rośnie równo), opcjonalne `meter_error_count` i `meter_data_age_ms`, U4 (ponawianie bez zalewania logów) |
| k4 | U1 (test: `link_status` od `plc-01` trafia do bazy), U4 (ingest czeka na tabele i bazę, nie zakłada, że `migrate` przebiegło), U7 (bufor Mosquitto: 11 wiadomości na sekundę, 60 min ≈ 40 tys., `max_queued_messages` i `max_queued_bytes` w limicie 64 MB) |
| k5 | U7 (ok. 660 wierszy na minutę: 7 + 2 + 2 = 11 metryk na sekundę; w checklistę wzór, nie sama liczba), U8 (zgodność Grafana vs `mbpoll`: ±0,5 V, ±0,2 W; test przerwy RS485; PLC offline; zrzuty `docs/images/etap2/20-…`) |
| k6 | D6 (widoki z `LAG`), D7 (całka mocy `sum(active_power) × poll_interval_s / 3600` z `sample_count` plus stan licznika; widok porównujący całkę z przyrostem na dobie w %, z testem; rejestry 30462–30485 dopiero w etapie 4) |
| k7 | U3 (Grafana: `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`, hasło z `.env`), U2 (kody statusów po polsku w Grafanie), U8 (zrzuty stanów błędu) |
| k8 | U4 (restart komputera bez ręcznego `docker compose up`), U8 (czas do `healthy` i pierwszego nowego punktu na wykresie, cel < 5 min), budżet RAM z pomiarem także smartWARE, zrzuty 20–29 |

Nazewnictwo zrzutów wg dokumentu projektu 04 (po stronie architekta; w razie wątpliwości pytam w k5).

## Ryzyka i założenia (bez potwierdzenia)

- Wpis Dockera wskazuje `focal`; wynik rundy 1 to potwierdzi lub nie.
- Docker w repozytorium `jammy` ma pakiety w tych samych nazwach; `hold` dotyczy tylko tych
  zainstalowanych. Jeśli zainstalowano Dockera inną drogą (np. `docker.io`, snap), zatrzymuję się:
  plan D11 zakłada pakiety z repozytorium Dockera.
- `apt update` może zgłaszać ostrzeżenia z innych powodów; nie naprawiam ich w tym kroku.
- `hold` uniemożliwia też automatyczne poprawki bezpieczeństwa Dockera: świadomy kompromis
  z review (ochrona smartWARE), do przeglądu przed etapem 7.
- Pierwsze połączenie SSH z GitHubem zadaje pytanie o odcisk klucza: bez porównania z oficjalną
  stroną nie akceptujemy go.
- GitHub pozwala użyć danego klucza jako deploy key tylko w jednym repo; ten klucz służy
  wyłącznie temu repo.
- Zakładam, że repo jest prywatne (D5 wprowadza deploy key); gdyby było publiczne, klon HTTPS
  też by działał, ale decyzja D5 jest wiążąca.

## Jak sprawdzę, że działa

1. Runda 1 kompletna w raporcie (pkt 1–10).
2. `diff` źródeł pokazuje jedną zmienioną linię; `sudo apt update` bez ostrzeżeń Dockera.
3. `apt-mark showhold` zawiera zainstalowane pakiety Dockera.
4. `docker ps` przed i po: te same kontenery, czas działania bez resetu.
5. `ssh -T git@github-ai-predykcja` uwierzytelnia; klon istnieje; `git pull --ff-only` mówi
   „Already up to date”.
6. Odrzucenie zapisu z komputera (lub zrzut Deploy keys bez „write”).
7. `ss -ltn` po wszystkich zmianach: ten sam stan portów co w rundzie 1.

## Poza zakresem

Instalacja czegokolwiek poza ewentualnym `git` (za zgodą), tworzenie `.env`, `docker-compose.yml`,
jakikolwiek kontener projektu, zmiana strefy czasowej lub konfiguracji NTP, `apt upgrade`,
zmiany w PLC, zmiana `docs/modbus-map.md`.
