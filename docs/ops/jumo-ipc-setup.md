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
sudo cp -a "$PLIK" /home/jumo/docker-apt-source.list.bak-focal-$(date +%Y%m%d)
sudo sed -i '/download\.docker\.com/ s/ focal / jammy /' "$PLIK"
diff /home/jumo/docker-apt-source.list.bak-focal-* "$PLIK"   # tylko linie z focal -> jammy
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

## Czego ten dokument nie obejmuje

Tworzenie `.env` i startu usług (etap 2, k2), zmiany strefy czasowej lub NTP, `apt upgrade`,
instalacji smartWARE.
