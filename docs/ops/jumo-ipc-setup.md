# Przygotowanie komputera `jumo-ipc` (jednorazowo)

Instrukcja z kroku e2-k1 (23.11.2026). Polecenia są podane w postaci do uruchomienia **na komputerze**
(bash). Z laptopa przez `ssh jumo@192.168.0.213 "<polecenie>"` wymagają cytowania dla cmd
(patrz „Uruchamianie z laptopa”). Dokument służy też jako baza instalatora (etap 7).

Komputer: Ubuntu 22.04 („jammy”), użytkownik `jumo`, 16 GB RAM, NVMe 1 TB. Na tym samym
komputerze działa JUMO smartWARE (7 kontenerów Dockera, porty 80/443). **Nie ruszamy smartWARE,
demona Dockera, strefy czasowej (Europe/Berlin) ani konfiguracji NTP.**

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

- cmd: `ssh jumo@192.168.0.213 "<polecenie>"`; wewnątrz bez podwójnych cudzysłowów
  (`--format 'table {{.Names}}\t…'`); z sudo `ssh -t jumo@192.168.0.213 "sudo …"`.
- PowerShell 5.1 zniekształca cudzysłowy przy przekazaniu do `ssh`; wolisz Git Bash z heredoc:
  `ssh jumo@192.168.0.213 bash -s <<'EOF' … EOF`.
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

Usługa `collector` ma w Compose profil `live` (zdefiniowana i zbudowana w k3, uruchomienie na sprzęcie w k5):
`docker compose up -d` bez profilu jej nie startuje. Budowa bez startu: `docker compose build collector`.

Zasady: **nigdy `docker compose down -v` bez zgody** (kasuje dane); `docker system prune` zabronione
(dotknęłoby smartWARE); `migrate` nie uruchamia się po restarcie komputera, bo ma `restart: "no"`:
usługi czekają na bazę same. Mosquitto słucha tylko na `127.0.0.1:1883` (testy lokalne, tunel SSH),
baza nie ma portu na hoście. Testy integracyjne: `sh tests/run-tests.sh </dev/null` (izolowany projekt
`aip-test`, sprząta tylko siebie).

W skryptach `bash -s` przekazywanych przez `ssh` dodawaj `</dev/null` do `docker compose run/exec`:
inaczej polecenie czyta resztę skryptu ze standardowego wejścia i przerywa wykonanie.

## Źródła pobierania (przygotowanie instalacji offline, etap 7)

Obrazy (tag i digest są w `docker-compose.yml`, `db/Dockerfile`, `tests/Dockerfile`):
`timescale/timescaledb:2.32.1-pg16`, `eclipse-mosquitto:2.0.23`, `python:3.12.16-slim-trixie`.
Pakiety z PyPI: `psycopg[binary]==3.3.9` (+ `psycopg-binary==3.3.9`, `typing_extensions==4.16.0`) dla `migrate`;
dla testów dodatkowo `paho-mqtt==2.2.0`, `PyYAML==6.0.4`, `pytest==9.2.0` (+ `iniconfig==2.3.1`,
`packaging==26.3`, `pluggy==1.7.0`, `Pygments==2.21.0`). Instalacja offline: `docker save`/`docker load`
obrazów i wheelhouse (`pip download`) tych samych wersji.

## Czego ten dokument nie obejmuje

Zmiany strefy czasowej lub NTP, `apt upgrade`, instalacji smartWARE, uruchamiania collectora, ingestu i Grafany
(kroki k3, k4, k7).
