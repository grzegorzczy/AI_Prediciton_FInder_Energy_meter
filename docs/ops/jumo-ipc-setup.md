# Przygotowanie komputera `jumo-ipc` (jednorazowo)

Instrukcja z kroku e2-k1 (23.11.2026). Polecenia są podane w postaci do uruchomienia **na komputerze**
(bash). Z laptopa przez `ssh jumo@192.168.0.215 "<polecenie>"` wymagają cytowania dla cmd
(patrz „Uruchamianie z laptopa”). Dokument służy też jako baza instalatora (etap 7).

Komputer: Ubuntu 22.04 („jammy”), użytkownik `jumo`, 16 GB RAM, NVMe 1 TB. Na tym samym
komputerze działa JUMO smartWARE (7 kontenerów Dockera, porty 80/443). **Nie ruszamy smartWARE,
demona Dockera, strefy czasowej (Europe/Berlin) ani konfiguracji NTP.**

## Sieć (od 27.11.2026, E3-k7a)

| Element | Wartość |
| --- | --- |
| IPC `jumo-ipc` | **192.168.0.215**, port `enp2s0` (profil NM „Wired connection 2”), MAC `04:2b:58:12:f7:a2`, adres z DHCP |
| PLC | **192.168.0.246** (Modbus TCP 502) |
| Brama | 192.168.0.1 |
| Łącze | **100 Mb/s (znana cecha, zaakceptowana)**: karta jest gigabitowa, kabla i portu switcha nie testujemy; dla 20 wierszy/s i Grafany wystarcza z dużym zapasem |
| Drugi port `enp1s0` | nieużywany (do 27.11 20:49 tam był kabel i adres .213) |

Dostęp z laptopa spoza sieci zakładu: przez Tailscale i komputer w zakładzie udostępniający podsieć 192.168.0.0/24
(nie przez IPC – IPC nie ma Tailscale ani dostępu z internetu). Przerwa po tej drodze **nie oznacza** przerwy sieci IPC:
o stanie IPC świadczą dane real w bazie i monitor poniżej.

**Monitor sieci** (`docs/ops/net-monitor.sh`, K7-D1): cron co minutę, bez `sudo`, ping do bramy i PLC (bez połączeń do Modbus,
K7-D2), stan i prędkość łącza, adres, MAC bramy, zdarzenia „Link is Down/Up”. Log `~/aip-net/net-YYYYMMDD.log` (ok. 0,3 MB/dobę,
14 dni). Instalacja w nagłówku skryptu. Przegląd przerw:

```bash
grep -hv "gw=0/3 .*plc=0/3 .*link_events=0" ~/aip-net/net-*.log | tail
```

**Konflikt adresu** (inne urządzenie na adresie IPC) – bez `sudo` niewykrywalny (brak `arping`, gniazda surowe wymagają roota).
Sprawdzenie ręczne: `sudo python3 docs/ops/arp-probe.py enp2s0 192.168.0.215` (sonda ARP, nic nie zmienia).

## Zasady (obowiązują cały czas)

- Bez `apt upgrade` i bez aktualizacji pakietów Dockera: restart demona zatrzymuje kontenery smartWARE.
- Bez `docker system prune`, bez zatrzymywania cudzych kontenerów, ich wolumenów i sieci.
- Przed każdą zmianą pliku systemowego kopia obok (poza `sources.list.d`).
- Kryteria zatrzymania: `lsb_release -cs` ≠ `jammy`; brak `docker compose`; zajęte porty 1883/3000;
  niezsynchronizowany zegar; błąd `apt update` (nie samo ostrzeżenie); brak `git`.

## 1. Odczyty przed zmianami

```bash
lsb_release -cs; uname -m; hostname
grep -rn "download.docker.com" /etc/apt/sources.list /etc/apt/sources.list.d/
dpkg -l | grep -i -E "docker|containerd"
docker --version; docker compose version; systemctl is-enabled docker; systemctl is-active docker
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker inspect -f '{{.Name}} {{.State.StartedAt}}' $(docker ps -q)   # punkt odniesienia
ss -ltn                       # 80/443 zajęte (smartWARE); 1883 i 3000 wolne
timedatectl                   # synchronizacja: yes; strefa NIE jest zmieniana
free -m; df -h /; nproc
git --version; ssh -V; openssl version
```

## 2. Repozytorium Dockera: `focal` → `jammy`

Stan z 23.11.2026: jeden plik `/etc/apt/sources.list.d/archive_uri-https_download_docker_com_linux_ubuntu-jammy.list`
z wpisem `focal` (klasyczny `.list`, bez `signed-by`). Dostosuj nazwę pliku do wyniku z pkt 1.

```bash
PLIK=/etc/apt/sources.list.d/archive_uri-https_download_docker_com_linux_ubuntu-jammy.list
KOPIA=/home/jumo/docker-apt-source.list.bak-focal-$(date +%Y%m%d)
sudo cp -a "$PLIK" "$KOPIA"
sudo sed -i '/download\.docker\.com/ s/ focal / jammy /' "$PLIK"
diff "$KOPIA" "$PLIK"   # tylko linie z focal -> jammy (zmienna, nie glob: przy drugiej kopii glob dopasuje kilka plików)
sudo apt update 2>&1 | tail -n 15                            # bez błędów; ostrzeżenia zapisać
```

Nie uruchamiamy `apt upgrade` ani `apt install` pakietów Dockera.

## 3. Blokada wersji pakietów Dockera

Tylko pakiety faktycznie zainstalowane (stan 23.11.2026: 6):

```bash
sudo apt-mark hold containerd.io docker-buildx-plugin docker-ce docker-ce-cli docker-ce-rootless-extras docker-compose-plugin
apt-mark showhold
```

### Zdjęcie blokady (tylko na zaplanowane okno serwisowe)

`hold` blokuje także poprawki bezpieczeństwa Dockera. Świadoma aktualizacja:

1. Zaplanuj okno: **restart demona zatrzyma kontenery smartWARE** (i projektu).
2. Zrób kopię jak 15.11.2026 (dokument projektu 10).
3. `sudo apt-mark unhold <lista pakietów z pkt 3>` → `sudo apt update` → `sudo apt install --only-upgrade <lista>`.
4. Po aktualizacji: `docker ps` (smartWARE „healthy”), `docker compose ps` (projekt), ponownie `apt-mark hold`.

### smartWARE a wersja Dockera

Instalator nowej wersji JUMO smartWARE może wymagać nowszego Dockera. Przed aktualizacją
smartWARE sprawdź jego wymagania i zrób kopię; odblokowanie Dockera planuj razem z tą aktualizacją.

### Stary klucz w `trusted.gpg`

`apt update` zgłasza: `Key is stored in legacy trusted.gpg keyring`. W etapie 2 nie naprawiamy.
Docelowo: przeniesienie klucza Dockera do `/etc/apt/keyrings` i `signed-by` we wpisie (etap 7).

## 4. Deploy key tylko do odczytu i klon repo

Klucz prywatny **nigdy** nie jest wypisywany ani kopiowany poza komputer. Klucz bez hasła
(decyzja K1-d: `git pull` bez człowieka; dostęp tylko do odczytu jednego repo, w repo brak sekretów).

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh      # na czystym komputerze katalog może jeszcze nie istnieć
ssh-keygen -t ed25519 -C "jumo-ipc deploy key read-only" -f ~/.ssh/ai_predykcja_deploy -N ""
chmod 600 ~/.ssh/ai_predykcja_deploy
printf '%s\n' '' 'Host github-ai-predykcja' '  HostName github.com' '  User git' \
  '  IdentityFile ~/.ssh/ai_predykcja_deploy' '  IdentitiesOnly yes' >> ~/.ssh/config
chmod 600 ~/.ssh/config
cat ~/.ssh/ai_predykcja_deploy.pub                  # to wklejasz w GitHubie
ssh-keygen -lf ~/.ssh/ai_predykcja_deploy.pub       # odcisk do kontroli
```

W GitHubie: repo → Settings → Deploy keys → Add deploy key, tytuł `jumo-ipc`, wklej klucz publiczny,
**odznacz „Allow write access”**. Klucz dodany jako klucz konta (Settings → SSH keys) byłby pełnym
dostępem do konta; jeśli tam trafi, usuń go.

Pierwsze połączenie bez trybu interaktywnego (bez pytania o `yes`): dodaj klucz serwera GitHub jawnie,
po porównaniu odcisku z oficjalną stroną „GitHub's SSH key fingerprints”:

```bash
ssh-keyscan -t ed25519 github.com > /tmp/gh_key
ssh-keygen -lf /tmp/gh_key        # porównaj SHA256 ze stroną GitHuba; stan 23.11.2026: +DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
cat /tmp/gh_key >> ~/.ssh/known_hosts    # tylko po zgodności
rm -f /tmp/gh_key
```

Test, klon, kontrola, że zapis jest zablokowany:

```bash
ssh -n -o BatchMode=yes -T git@github-ai-predykcja
git clone git@github-ai-predykcja:grzegorzczy/AI_Prediciton_FInder_Energy_meter.git /home/jumo/ai-predykcja
cd /home/jumo/ai-predykcja && git log --oneline -3
git push --dry-run origin main    # oczekiwane: "marked as read only"
```

Aktualizacja repo na komputerze: `git -C /home/jumo/ai-predykcja pull --ff-only`.
Katalog klonu nie jest wolumenem kontenerów; dane kontenerów będą w nazwanych wolumenach Dockera.

## 5. Kontrola po zmianach

```bash
docker inspect -f '{{.Name}} {{.State.StartedAt}}' $(docker ps -q)   # identyczne z punktem odniesienia
systemctl show docker -p ActiveEnterTimestamp                         # bez zmian
ss -ltn                                                              # ten sam stan portów
apt-mark showhold
```

## Uruchamianie z laptopa (cmd lub Git Bash)

- cmd: `ssh jumo@192.168.0.215 "<polecenie>"`; wewnątrz bez podwójnych cudzysłowów
  (`--format 'table {{.Names}}\t…'`); z sudo `ssh -t jumo@192.168.0.215 "sudo …"`.
- PowerShell 5.1 zniekształca cudzysłowy przy przekazaniu do `ssh`; wolisz Git Bash z heredoc:
  `ssh jumo@192.168.0.215 bash -s <<'EOF' … EOF`.
- W skrypcie `bash -s` **nie wywołuj `ssh` bez `-n`**: zagnieżdżony `ssh` czyta resztę skryptu ze
  standardowego wejścia i przerywa wykonanie.

## 6. Plik `.env` (sekrety)

`.env` nie trafia do repo (`.gitignore`). Hasła generuje komputer i nigdzie ich nie wypisujemy:
hex (`openssl rand -hex 24`, 48 znaków alfanumerycznych), bo znaki `+ / =` z base64 psują adresy
połączeń i powłokę. Polecenie nie nadpisze istniejącego `.env`.

`umask 077` jest ustawiony **tylko w podpowłoce** `( … )`: w otwartej konsoli zostałby aktywny, a późniejszy `git pull`
utworzyłby pliki 600/700, nieczytelne dla kontenerów z innym użytkownikiem niż `jumo` (tak było w k2).

```bash
cd /home/jumo/ai-predykcja && git pull --ff-only
(
  umask 077
  if [ -e .env ]; then echo "JUZ ISTNIEJE - nie nadpisuje"; else
    cp .env.example .env
    for v in POSTGRES_PASSWORD APP_WRITER_PASSWORD APP_READER_PASSWORD MQTT_COLLECTOR_PASSWORD MQTT_INGEST_PASSWORD GF_SECURITY_ADMIN_PASSWORD; do
      sed -i "s|^${v}=.*|${v}=$(openssl rand -hex 24)|" .env
    done
    chmod 600 .env
  fi
)
```

Kontrola bez wypisywania wartości (oczekiwane: `600 jumo`, dokładnie 6 zmiennych `*_PASSWORD` po 48 znaków,
wszystkie różne, `CLOUD_LLM_API_KEY` pusty):

```bash
stat -c '%a %U' .env; git check-ignore -v .env
awk -F= '/_PASSWORD=/{printf "%s %d\n",$1,length($2)}' .env
awk -F= '/_PASSWORD=/{print $2}' .env | sort -u | wc -l
```

Zasady:

- **Kopia `.env` w menedżerze haseł.** Nie w repo, nie w czacie. Hasła do Grafany odczytasz sam:
  `grep GF_SECURITY_ADMIN_PASSWORD .env` w swojej konsoli.
- **Nie generuj `.env` od nowa przy istniejącym wolumenie bazy** (`aip_pgdata`). Obraz ustawia hasło
  `postgres` tylko przy pierwszym utworzeniu bazy. Hasła `app_writer` i `app_reader` `migrate` aktualizuje
  przy każdym uruchomieniu, ale `postgres` nie, więc `migrate` zgłosi: `superuser login failed`.
- **Odzyskanie hasła `postgres`** (po zgubieniu lub podmianie `.env`), obraz ma `local trust` w `pg_hba`
  (sprawdzone 23.11.2026), więc gniazdo lokalne kontenera nie pyta o hasło. Najpierw wpisz do `.env`
  nowe `POSTGRES_PASSWORD`, potem:

  ```bash
  set -a; . ./.env; set +a
  docker compose exec -T timescaledb psql -U postgres -d energy -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" <<'SQL'
  ALTER ROLE postgres PASSWORD :'pw';
  SQL
  docker compose up -d --build   # migrate odświeży też hasła app_writer i app_reader
  ```

  Procedura nie była jeszcze wykonana na produkcyjnej bazie (sprawdzone tylko `local trust`).
- **Hasła w `environment` kontenerów** są widoczne dla użytkowników grupy `docker` przez `docker inspect`.
  Dlatego nie wklejamy do raportów wyniku `docker compose config`, `docker inspect` ani `env`;
  walidacja: `docker compose config --quiet`.
- **`git pull` pod `umask 077`:** pliki w klonie dostają prawa 600. Obrazy `migrate` i `collector` zawierają kod z
  ustawionymi prawami odczytu przy budowie, ale `config/devices.yaml` jest montowany `:ro` wprost z klona, więc musi być
  czytelny dla użytkownika kontenera. Dlatego `umask 077` tylko w podpowłoce (jak wyżej), a po każdym `git pull` kontrola
  praw (niżej).

### Kontrola praw po każdym `git pull`

Oczekiwany wynik: oba polecenia `find` bez żadnych wierszy; `.env` ma `600`.

```bash
cd /home/jumo/ai-predykcja
find . -path ./.git -prune -o -type f ! -name .env ! -perm -o=r -print
find . -path ./.git -prune -o -type d ! -perm -o=rx -print
stat -c '%a %U %n' .env config/devices.yaml
```

Naprawa (bez `sudo`, `.env` zostaje 600, `.git` nietknięty; Git śledzi tylko bit wykonywania, więc `git status` pozostaje czysty):

```bash
find . -path ./.git -prune -o -type d -exec chmod 755 {} +
find . -path ./.git -prune -o -type f ! -name .env -exec chmod 644 {} +
chmod 600 .env
git ls-files -s | awk '$1=="100755"{print $4}' | xargs -r chmod 755   # pliki z bitem wykonywania w repo (obecnie brak)
```

Zasada dla asystenta: nie wypisuje zawartości `.env` (`cat`, `type`, `grep` po wartościach), także na komputerze;
`.env` sprawdza tylko po nazwach, długościach i prawach.

## 7. Stos Docker Compose (etap 2)

Projekt `ai-predykcja`, kontenery z prefiksem `aip-` (bez kolizji z smartWARE). Sieć `aip_backend`
`172.31.50.0/24`. Sprawdzone przed wyborem (23.11.2026): zajęte `172.17.0.0/16` (docker0), `172.19.0.0/16`
(`upgrade_pg_default`, pochodzenie nieznane, prawdopodobnie pozostałość aktualizacji smartWARE; nie ruszamy),
`172.20.0.0/16` (`smartware_4527022_default`); LAN `192.168.0.0/24`.

```bash
cd /home/jumo/ai-predykcja
docker compose config --quiet        # walidacja bez wypisywania haseł
docker compose up -d --build         # start; po git pull ten sam komunikat stosuje nowe migracje
docker compose ps -a                 # mosquitto i timescaledb healthy; migrate Exited (0)
docker compose logs --no-log-prefix migrate
```

Usługa `ingest` startuje razem ze stosem (bez profilu), konsumuje MQTT i zapisuje do bazy (rola `app_writer`).
Konfiguracja `config/devices.yaml` jest czytana przy starcie przez ingest i collector: po jej zmianie trzeba je zrestartować
(`docker compose restart ingest`).

Usługa `collector` (od k5, bez profilu) startuje razem ze stosem i czyta PLC wyłącznie funkcją FC04. Wstrzymanie odczytów
bez ruszania reszty stosu: `docker compose stop collector`; wznowienie: `docker compose start collector`. Po zmianie adresu
PLC w `config/devices.yaml`: `docker compose restart collector ingest`.

Zasady: **nigdy `docker compose down -v` bez zgody** (kasuje dane); `docker system prune` zabronione
(dotknęłoby smartWARE); `migrate` nie uruchamia się po restarcie komputera, bo ma `restart: "no"`:
usługi czekają na bazę same. Mosquitto słucha tylko na `127.0.0.1:1883` (testy lokalne, tunel SSH),
baza nie ma portu na hoście. Testy integracyjne: `sh tests/run-tests.sh </dev/null` (izolowany projekt
`aip-test`, sprząta tylko siebie).

W skryptach `bash -s` przekazywanych przez `ssh` dodawaj `</dev/null` do `docker compose run/exec`:
inaczej polecenie czyta resztę skryptu ze standardowego wejścia i przerywa wykonanie.

## Grafana (od k7)

Usługa `grafana` (kontener `aip-grafana`) startuje ze stosem: obraz **`grafana/grafana-oss:13.0.2@sha256:5dad0df181cb644a14e13617b913b261a54f7d4fd4510721dba420929f35bea2`** (wersja 13.0.2, wybrana 24.11.2026 jako
najnowsza stabilna główna; digest sprawdzony po `docker pull` na komputerze), użytkownik 472 (nie-root), `mem_limit` 512 MB (od k8; 384 MB kończyło się OOM-killerem) i `GOMEMLIMIT=400MiB`, port **3000 na wszystkich interfejsach, HTTP bez TLS** (sieć biurowa, świadoma akceptacja dla demo;
TLS i odwrotne proxy w etapie 7). Dashboardy i źródło danych są plikami w repo (`grafana/`), montowanymi tylko do odczytu. Opis dla użytkownika: `docs/grafana.md`.

**Klucz `GF_SECURITY_SECRET_KEY` (G7-g).** Szyfruje sekrety w bazie Grafany (m.in. hasło `app_reader` w źródle danych) i musi być w `.env` **przed pierwszym startem** wolumenu `aip_grafana_data`;
późniejsza zmiana unieważnia zaszyfrowane dane (tak jak `POSTGRES_PASSWORD` i hasło admina). Compose odmawia startu bez niego, także dla innych poleceń (`docker compose ps`, `up`, `restart`…): zmienna jest wymagana w pliku.
Dopisuje go **Grzegorz** w konsoli komputera (Claude Code nie widzi `.env`), potem przenosi tę jedną linię do kopii `.env` na laptopie:

```bash
cd /home/jumo/ai-predykcja && ( umask 077; grep -q '^GF_SECURITY_SECRET_KEY=' .env || printf 'GF_SECURITY_SECRET_KEY=%s
' "$(openssl rand -hex 16)" >> .env ); awk -F= '/^GF_SECURITY_SECRET_KEY=/{print $1, length($2)}' .env; stat -c '%a %U' .env
```

Oczekiwane: `GF_SECURITY_SECRET_KEY 32` i `600 jumo`.

**Hasło admina** (`GF_SECURITY_ADMIN_PASSWORD`) z `.env` obowiązuje tylko przy pierwszym utworzeniu wolumenu Grafany (jak hasło Postgresa). Jeśli kiedyś wolumen powstanie ze starym hasłem, zmiana w `.env` go nie zmieni:
trzeba użyć `grafana cli admin reset-admin-password` w kontenerze.

**Kontrola:** `docker compose ps` (grafana `healthy`), `ss -ltn` (nowy tylko port 3000), `docker stats --no-stream aip-grafana`, `curl -s http://127.0.0.1:3000/api/health`.
Ruch do Grafany jest jawny (HTTP) i hasło admina przechodzi przez sieć biurową bez szyfrowania: nie używaj tego hasła nigdzie indziej.

**Wdrażanie zmian.** Na komputer trafia **wyłącznie to, co jest w `origin/main`** (`git pull --ff-only`, potem kontrola praw plików); nie kopiujemy plików przez `ssh`. Po `git pull` zmiany w `grafana/dashboards/*.json` pojawiają się w Grafanie same
(odświeżanie co 30 s); zmiany w `docker-compose.yml` wymagają `docker compose up -d`. W lokalnym klonie komputera ustawiono `core.fileMode false`, żeby zmiany bitu wykonania po `chmod` nie psuły `git status`.

## Agregaty energii: odświeżanie i kontrola (od k6)

Agregaty `energy_1m` i `energy_1h` odświeżają się same (okna: `energy_1m` 7 dni co minutę, `energy_1h` 30 dni co 15 minut).
Migracja `002` robi pierwsze zmaterializowanie istniejących danych. **Dane starsze niż okno odświeżania polityka nie obejmie**:
po wypełnieniu historii (etap 3) albo po ręcznym wstawieniu starych pomiarów trzeba odświeżyć agregaty ręcznie, najpierw minutowy:

```sql
CALL refresh_continuous_aggregate('energy_1m', NULL, NULL);
CALL refresh_continuous_aggregate('energy_1h', NULL, NULL);
```

Polecenia wykonuje superużytkownik bazy (poza transakcją), np. przez `docker exec -i aip-timescaledb psql` z zalogowaniem z kontenera;
roli `app_writer` i `app_reader` nie wolno zmieniać agregatów. Kontrola stanu:

```sql
SELECT view_name, materialized_only, compression_enabled FROM timescaledb_information.continuous_aggregates;
SELECT proc_name, hypertable_name, schedule_interval, config FROM timescaledb_information.jobs WHERE proc_name LIKE 'policy_%';
SELECT * FROM energy_daily_check ORDER BY day DESC LIMIT 7;
```

Przerwana migracja `002` (np. restart w trakcie) nic nie psuje: runner zapisuje sumę kontrolną dopiero po ostatniej instrukcji,
a wszystkie instrukcje są idempotentne, więc kolejne `docker compose up -d` wykona plik od początku.

## Logi kontenerów (od k8a)

Wszystkie usługi `aip-*` logują sterownikiem `local` (binarny, rotacja `max-size: 10m`, `max-file: 5`), ustawionym w `docker-compose.yml` (bez zmian w `daemon.json`, bez restartu demona; kontenery smartWARE nietknięte).
Powód: po utracie zasilania sterownik `json-file` zostawiał w pliku logu bajty `zerowe (NUL)` i `docker logs` przestawało działać (E2-PLC1). Odtworzenie kontenerów przy wdrożeniu (R-1) usuwa też stare uszkodzone pliki logów.
Czytanie logów bez zmian: `docker logs aip-ingest`. Limit pamięci Grafany: 512 MiB i `GOMEMLIMIT=400MiB` (384 MiB kończyło się zabiciem przez OOM-killera jądra; ślad: `journalctl -k | grep -i oom`).

## Katalog testów `~/ai-predykcja-dev` (od E3-k1)

Produkcja montuje pliki z `~/ai-predykcja` (m.in. `config/devices.yaml`, czytany przez ingest i collector przy starcie), więc
**w tym katalogu nie robimy `git pull` poza wdrożeniem (R-1)**. Testy nowych kroków idą z osobnego katalogu roboczego,
`git worktree` tego samego repozytorium (bez osobnego klucza i bez kopii `.git`):

```bash
git -C ~/ai-predykcja worktree add ~/ai-predykcja-dev origin/main         # jednorazowo (E3-k1, 26.11.2026)
cd ~/ai-predykcja-dev && git fetch -q origin && git checkout -q --detach origin/main   # przed każdym przebiegiem testów
sh tests/run-tests.sh </dev/null                                         # projekt Compose aip-test, jak dotąd
git -C ~/ai-predykcja status --short && git -C ~/ai-predykcja log --oneline -1     # kontrola: produkcja bez zmian
```

Worktree jest w trybie „detached HEAD” (gałąź `main` jest już wybrana w `~/ai-predykcja`). Nic z niego nie jest montowane do
kontenerów produkcyjnych; `tests/run-tests.sh` uruchamia tylko projekt `aip-test` i sprząta tylko siebie. Usunięcie, gdy
niepotrzebny: `git -C ~/ai-predykcja worktree remove ~/ai-predykcja-dev`.

## Kolejność wdrożenia zmian (R-1, k7d)

Zawsze w tej kolejności, na komputerze w `/home/jumo/ai-predykcja`:

1. `git pull --ff-only` (tylko to, co jest w `origin/main`; potem kontrola praw plików, sekcja „Kontrola praw po każdym `git pull`”).
2. `docker compose up -d --build`. **`--build` jest obowiązkowe przy nowej migracji (decyzja D4):** pliki migracji są wbudowane w obraz `migrate`, więc samo `up -d` zostawia stary obraz
   i nic nie stosuje (`done: 0 applied`). Kontenery bez zmian zostają bez restartu; kontener, którego konfiguracja lub obraz się zmieniły (np. Grafana), jest odtwarzany.
3. Sprawdzenie, że migracje poszły: `docker logs aip-migrate | tail -4` (linia `applied NNN_...sql`) i `SELECT version, name FROM schema_migrations ORDER BY 1;`
   (liczba wierszy równa liczbie plików w `db/migrations/`).

Zmiany tylko w `grafana/dashboards/*.json` nie wymagają kroku 2: Grafana wczytuje je sama w ciągu 30 s po `git pull`.

## Utrata danych przy przerwach (bufory)

Dane nie giną w normalnej pracy, ale bufory są ograniczone. Co się dzieje przy przerwie i co traci się przy długiej:

| Przerwa | Co chroni dane | Granica | Co ginie po przekroczeniu |
| --- | --- | --- | --- |
| broker MQTT niedostępny | bufor w pamięci collectora (`COLLECTOR_BUFFER_MAX` = 30 000) | ok. 25 minut przy 20 wiadomościach na sekundę (mapa v2; 38 minut przy 13 na sekundę, mapa v1) | **najstarsze** wiadomości (luka na początku przerwy) |
| ingest lub baza niedostępne | kolejka sesji ingestu w Mosquitto (`max_queued_messages` 80 000, `max_queued_bytes` 20 MB) | ok. 66 minut przy 20 wiadomościach na sekundę (mapa v2; 102 minuty przy 13 na sekundę; wiąże liczba wiadomości) | **najnowsze** wiadomości (luka na końcu przerwy) |
| ingest lub baza niedostępne – **dane symulatora** (od etapu 3, E3-k3) | nic: symulator publikuje z QoS 0, a Mosquitto nie kolejkuje QoS 0 dla rozłączonej sesji (`queue_qos0_messages` domyślnie false, K3-D4) | – | dane sim z czasu przerwy (luka); uzupełnia je historia symulatora (k5), bo wartości są funkcją czasu. Dzięki temu kolejka 80 000 zostaje w całości dla danych prawdziwych: **nadal ok. 66 minut przy 20 wiadomościach na sekundę**, mimo że razem z symulatorem jest ich 49 na sekundę (przy QoS 1 dla sim byłoby ok. 27 minut, test `tests/simulator/test_sim_e2e.py`) |
| broker MQTT niedostępny – **symulator** | bufor w pamięci symulatora (`SIM_BUFFER_MAX` = 36 000) | ok. 20 minut przy 29 wiadomościach na sekundę | **najstarsze** wiadomości symulatora |
| ingest nie łączy się z brokerem dłużej niż 7 dni | `persistent_client_expiration 7d` w `mosquitto.conf` | 7 dni | broker usuwa sesję wraz z kolejką; od tej chwili wiadomości nie są kolejkowane, aż ingest znów się zasubskrybuje |

**Pamięć Mosquitto przy pełnej kolejce:** po opublikowaniu 90 000 wiadomości QoS 1 do rozłączonej sesji trwałej (kolejka ucięta do 80 000) kontener `aip-mosquitto` zajmował
36,8 MiB z limitu 64 MiB, bez OOM (pomiar 25.11.2026 w projekcie `aip-test`, sonda `tests/mqtt/probe_queue_memory.py`; na starcie 1,2 MiB).

Ingest potwierdza wiadomość brokerowi dopiero po zapisie w bazie, więc awaria ingestu lub bazy nie gubi niczego w granicach
kolejki sesji, a ponowne dostarczenie nie tworzy duplikatów (`ON CONFLICT DO NOTHING`). Przy niedostępnej bazie do ingestu
dociera najwyżej 100 niepotwierdzonych wiadomości **QoS 1** (`max_inflight_messages`), reszta czeka w kolejce sesji w brokerze.
Wiadomości QoS 0 limit ten nie obejmuje, dlatego ingest ma **limit danych symulatora** (E3-k4, K4-D1): wiersz urządzenia
`source = sim` dostarczony z QoS 0 jest odrzucany, gdy baza jest niedostępna albo w pamięci czeka już `INGEST_SIM_PENDING_MAX`
(3 000, ok. 100 s) wierszy sim. Ten sam limit obowiązuje w kolejce wejściowej MQTT ingestu: przy wolnej, ale dostępnej bazie
zaległość gromadzi się tam (potok zapisuje paczkami po 100), więc ponad 3 000 wiadomości sim w kolejce jest odrzucanych, a kolejka
(5 000) nie zapełnia się i nie blokuje odbioru danych prawdziwych. Dane real nie są odrzucane nigdy (także z QoS 0); wiersze sim
z QoS 1 (wgrywanie historii) też nie.
W logu jeden WARNING na początku epizodu (z przyczyną) i jeden na końcu (liczba odrzuconych, czas trwania). Dla
demo akceptowalne; przy dłuższych przerwach trzeba liczyć się z luką w danych.

## Symulator (od etapu 3, E3-k3)

Usługa `simulator` (kontener `aip-simulator`) publikuje dane urządzeń sim (`source = sim`) do `zaklad1/linia2` z QoS 0.
Na produkcji startuje dopiero we wdrożeniu k7; do tego czasu `~/ai-predykcja` zostaje na commicie etapu 2.

**Konto MQTT symulatora (K3-D1).** Opcjonalne dla brokera: bez `MQTT_SIM_USER`/`MQTT_SIM_PASSWORD` w `.env` Mosquitto startuje
(WARNING w logu), dane prawdziwe płyną, a symulator ponawia połączenie i loguje błąd autoryzacji raz na epizod. Przed wdrożeniem
k7 **Grzegorz** dopisuje konto (Claude Code nie widzi `.env`):

```bash
cd /home/jumo/ai-predykcja
printf 'MQTT_SIM_USER=simulator\nMQTT_SIM_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> .env
chmod 600 .env
grep -c '^MQTT_SIM_' .env          # 2
```
Tę samą parę linii przenosi do kopii `.env` na laptopie. Zmiana konta wymaga odtworzenia `mosquitto` i `simulator` (R-1).
ACL (K1-D2): collector pisze tylko do `zaklad1/linia1/+/+`, symulator tylko do `zaklad1/linia2/+/+`, ingest czyta wszystko.

**Daty w `config/devices.yaml` (K2R-D1), ustawiane we wdrożeniu k7:**
- `simulator.meter_anchor` = wdrożenie − 14 dni (`history.meter_days`): kotwica liczników energii (stan = `energy_start_wh`),
  **po wdrożeniu nigdy niezmieniana** (zmiana cofnęłaby liczniki, a widoki energii zobaczyłyby reset);
- `bearing_installed_at` pompy = wdrożenie − 84 dni (postęp x = 0,70 „teraz”).
  **Wymiana łożyska** = nowa `bearing_installed_at` (x = 0, drgania ok. 1,1 mm/s) i okno `sim_reset` w `data_windows`;
  liczniki energii nietknięte, historii nie wgrywamy ponownie (K2R-D2).
Bez tych dat symulator kończy się kodem 2 z komunikatem, co ustawić.

**Okna symulatora w `data_windows` (E3-k4).** Każde okno to nowa migracja z `INSERT` (jak 005/006/010/011), granice z bazy:
- `sim_reset` – wymiana łożyska (K2R-D2): start = chwila, od której obowiązuje nowa `bearing_installed_at` we wdrożonym configu
  (pierwszy wiersz `vibration_rms` pompy po odtworzeniu kontenera symulatora), koniec = start + 1 min, `exclude_from_analytics = TRUE`
  (etap 5 dzieli trend drgań na tej granicy);
- `sim_backfill` – wgrywanie historii (k5): od początku do końca wgrywania; `exclude_from_analytics = FALSE` (tylko adnotacja
  o nietypowym obciążeniu komputera, K4-U3), chyba że w tym czasie zginą dane prawdziwe – wtedy osobne okno jak przy przerwach.

```sql
-- 0NN_data_windows_sim_reset.sql (szablon; granice wpisać z bazy)
INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('<start>+00', '<start + 1 min>+00', 'sim_reset', 'Wymiana łożyska pompy symulatora (nowa bearing_installed_at)', TRUE);
-- 0NN_data_windows_sim_backfill.sql
INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('<początek>+00', '<koniec>+00', 'sim_backfill', 'Wgrywanie historii symulatora (obciążenie komputera)', FALSE);
```

**Pamięć sum dobowych (K2R-D3).** Plik `/var/lib/simulator/energy-days.json` w wolumenie `aip_simulator_data` (jedyne miejsce
zapisu, kontener `read_only`): sumy W·s każdej doby od kotwicy dla czterech liczników. Przyspiesza start (bez pliku liczniki
przeliczają wszystkie doby od kotwicy: minuty po kilku miesiącach). Plik można w każdej chwili usunąć – symulator go odtworzy;
przy niezgodności z modelem (klucz z `MODEL_VERSION` i parametrami, kontrola ostatniej doby) jest odrzucany automatycznie.

## Historia symulatora (E3-k5, wykonanie we wdrożeniu k7)

Narzędzie `python -m simulator.backfill` w jednorazowej usłudze `simulator-tools` (profil `tools`, K5-D1): ten sam obraz,
config, konto MQTT i pamięć sum dobowych co `simulator` (wspólny wolumen, K5-U4), plus odczyt bazy kontem **`app_reader`**
(tylko do odczytu, `statement_timeout` 10 s). Usługa na żywo nie ma dostępu do bazy. Publikacja QoS 1, okno w locie 100
(K5-D2), bez sufitu tempa. Każda doba zakresu jest najpierw sprawdzana w bazie; wysyłane są tylko niepełne minuty urządzeń,
więc wgranie, wznowienie i uzupełnianie luk to ten sam przebieg. Ponieważ PUBACK wysyła broker, a nie ingest, narzędzie idzie
**porcjami po 7 200 wiadomości** i przed kolejną porcją czeka, aż ostatnia wysłana minuta jest w bazie kompletna – kolejka
brokera dla ingestu (wspólna z danymi prawdziwymi, limit 80 000) nie przekracza jednej porcji. `--from`/`--to` w pełnych
minutach. Kody wyjścia: 0 – gotowe; 1 – przerwane (broker, baza, brak zapisu przez 10 min) albo zostały luki po
`--fill-gaps`; 2 – błąd argumentów lub configu.

Kolejność w k7 (po ustawieniu dat w `devices.yaml` i starcie symulatora na żywo; `T0` = chwila startu trybu na żywo,
pełna minuta, z logu symulatora; polecenia z `/home/jumo/ai-predykcja`):

1. **Miejsce na dysku:** `df -h /var/lib/docker` – wolne co najmniej 3× prognozy z pilotażu k5 (przyrost bazy na dobę
   liczników × 14 + pompa + WAL; wartość w `docs/handoff/e3-k5-report.md`).
2. **Wstrzymanie kompresji `measurements` na czas wgrywania** (chunki historii są starsze niż 1 doba; bez tego zadanie
   kompresji pakuje je w trakcie, a kolejne wstawki i uzupełnianie luk trafiają do skompresowanych chunków – wolniej):
   ```bash
   docker compose exec -T timescaledb sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT alter_job(job_id, scheduled => false) FROM timescaledb_information.jobs
    WHERE proc_name = 'policy_compression' AND hypertable_name = 'measurements';
   SQL
   ```
3. **Pilotaż 1 doby** (ostatnia doba przed `T0`), w dzień, z obserwacją:
   ```bash
   docker compose run --rm simulator-tools python -m simulator.backfill --from <T0 − 1 d> --to <T0> --devices meters
   docker stats --no-stream aip-ingest aip-timescaledb aip-mosquitto     # kilka razy w trakcie (+ kontener simulator-tools)
   docker compose logs --since 1h ingest | grep -E 'odrzucone_sim|błąd'  # dane sim na żywo odrzucone w czasie wgrywania
   ```
   Kontrola danych prawdziwych w trakcie: ok. 20 wierszy/s `source = 'real'` jak przed startem (zapytanie z k4).
   Przy problemach (opóźnienie danych prawdziwych, ostrzeżenia brokera) dodać `--rate 500`.
4. **Pełne wgranie w nocy, kolejno:** liczniki `--from <meter_anchor> --to <T0 − 1 d> --devices meters`, potem pompa
   `--from <bearing_installed_at> --to <T0> --devices pump`. Przerwane wgranie wznawia się **tym samym poleceniem** (pełne
   minuty są pomijane po sprawdzeniu w bazie).
5. **Uzupełnienie luk** dla całego zakresu: to samo polecenie z `--fill-gaps` (liczniki od `meter_anchor` do `T0`, pompa
   od `bearing_installed_at`). Kod 0 = brakujących minut 0; 1 = zostały luki (lista w logu, powtórzyć).
6. **Włączenie kompresji** (jak w kroku 2, `scheduled => true`).
7. **Odświeżenie agregatów** kontem administratora – narzędzie wypisuje na końcu gotowe polecenia (kolejność: `energy_1m`,
   `energy_ext_1m` → `energy_1h`, `energy_ext_1h` → `pump_1m`):
   ```bash
   docker compose exec -T timescaledb sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   CALL refresh_continuous_aggregate('energy_1m', '<od>', '<do>');   -- … i kolejne z logu narzędzia
   SQL
   ```
8. **Okno `sim_backfill`** (szablon wyżej) z granicami pierwszego i ostatniego uruchomienia z logów narzędzia.

### Strażnik nocnego wgrywania (E3-k7, K7-U1)

`docs/ops/backfill-guard.sh` – w tle na komputerze, bez `sudo`. Co 10 s mierzy i przy przekroczeniu zatrzymuje kontener
wgrywania (`docker stop`), wznawia kompresję `measurements` i zapisuje przyczynę w `~/aip-k7/guard.log`:

| Próg | Pomiar |
| --- | --- |
| dane real < 18 wierszy/s dłużej niż 60 s | wiersze `source = 'real'` w oknie 20 s, 5 s za „teraz” |
| `aip-ingest` > 80 % limitu | pamięć anonimowa z cgroup (`memory.stat anon` / `memory.max`), bez pamięci podręcznej (K7B-D2) |
| wolne miejsce < 3 × pozostała prognoza | `df /`; prognoza = doby od czasu modelu (linia „postęp” narzędzia) do `--to` × 400 MiB + 0,1 GiB (pompa) |
| kolejka brokera dla ingestu > 20 000 w 3 pomiarach z rzędu | **szacunek**: broker nie podaje kolejki klienta (`$SYS` wyłączone), więc opóźnienie danych real w bazie × (tempo narzędzia + 49/s na żywo) – dane real stoją w tej samej kolejce FIFO; normalnie 0,4–2 s, czyli ok. 600–3 100; próg ≈ 12,6 s opóźnienia; liczona tylko, gdy dane real napływają (przerwa PLC/collectora to próg 1) |

Wgrywanie zakończone kodem ≠ 0 też wznawia kompresję (K7-U2); po kodzie 0 kompresja zostaje wstrzymana do rana (pompa,
odświeżenie, `--fill-gaps`, potem ręczne wznowienie). Test wszystkich progów: `sh tests/ops/guard-test.sh` (projekt `aip-test`).

Noc k7 (z `/home/jumo/ai-predykcja`, po `git pull --ff-only`; kompresja wstrzymana wcześniej, krok 2):

```bash
mkdir -p ~/aip-k7 && : > ~/aip-k7/night.log        # pusty log: strażnik nie weźmie EXIT= z poprzedniego przebiegu
(setsid nohup sh -c "docker compose run --rm -T --name aip-backfill-night simulator-tools python -m simulator.backfill --from 2026-11-13T23:00:00Z --to 2026-11-27T12:42:00Z --devices meters > ~/aip-k7/night.log 2>&1; echo EXIT=\$? >> ~/aip-k7/night.log" </dev/null >/dev/null 2>&1 &)
(setsid nohup env GUARD_LOAD_LOG=$HOME/aip-k7/night.log GUARD_FROM=2026-11-13T23:00:00Z GUARD_TO=2026-11-27T12:42:00Z sh docs/ops/backfill-guard.sh </dev/null >>"$HOME/aip-k7/guard.err" 2>&1 &)
tail -3 ~/aip-k7/guard.log ~/aip-k7/night.log      # podgląd
```
Zapytania strażnika mają limit 5 s (baza) i 15 s (proces); błędy skryptu w `~/aip-k7/guard.err`, koniec strażnika zawsze
w `guard.log` („strażnik zakończony (kod N)”). Zatrzymanie: `docker stop -t 10` (narzędzie nie obsługuje SIGTERM, po 10 s SIGKILL;
wiadomości w locie wrócą przy wznowieniu). Po stopie strażnika: usunąć przyczynę, wstrzymać kompresję i uruchomić oba polecenia ponownie (pełne minuty są pomijane).

## Źródła pobierania (przygotowanie instalacji offline, etap 7)

Obrazy (tag i digest są w `docker-compose.yml`, `db/Dockerfile`, `tests/Dockerfile`):
`timescale/timescaledb:2.32.1-pg16`, `eclipse-mosquitto:2.0.23`, `python:3.12.16-slim-trixie`.
Pakiety z PyPI: `psycopg[binary]==3.3.9` (+ `psycopg-binary==3.3.9`, `typing_extensions==4.16.0`) dla `migrate`;
dla testów dodatkowo `paho-mqtt==2.2.0`, `PyYAML==6.0.4`, `pytest==9.2.0` (+ `iniconfig==2.3.1`,
`packaging==26.3`, `pluggy==1.7.0`, `Pygments==2.21.0`); testy collectora dodają `pymodbus==3.16.2`. Obraz `collector`
(`pip freeze`, 23.11.2026): `pymodbus==3.16.2`, `paho-mqtt==2.2.0`, `PyYAML==6.0.4` (bez zależności pośrednich). Obraz `ingest`:
`paho-mqtt==2.2.0`, `psycopg==3.3.9`, `psycopg-binary==3.3.9`, `PyYAML==6.0.4`, `typing_extensions==4.16.0`.
Instalacja offline: `docker save`/`docker load`
obrazów i wheelhouse (`pip download`) tych samych wersji.

## Czego ten dokument nie obejmuje

Zmiany strefy czasowej lub NTP, `apt upgrade`, instalacji smartWARE, uruchamiania collectora, ingestu i Grafany
(kroki k3, k4, k7).
