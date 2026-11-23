# e2-k1 results: wyniki rund 1 i 2a (prowadzone przez architekta)

23.11.2026, 16:08–16:20 (czas lokalny). Polecenia wpisywał Grzegorz bezpośrednio w konsoli `jumo@jumo-ipc` (bez `ssh`). Zrzuty wyników są w rozmowie architekta. Poniżej przepisane wyniki, bez sekretów.

## Runda 1: odczyty – żadne kryterium zatrzymania nie zaszło

| # | Polecenie | Wynik |
| --- | --- | --- |
| 1 | `lsb_release -cs; uname -m; hostname` | `jammy`, `x86_64`, `jumo-ipc` |
| 2 | `grep -rn "download.docker.com" /etc/apt/sources.list /etc/apt/sources.list.d/; ls -l /etc/apt/sources.list.d/` | jeden plik `/etc/apt/sources.list.d/archive_uri-https_download_docker_com_linux_ubuntu-jammy.list` (148 B, root, 7 mar 2024), format klasyczny `.list`: l.1 `deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable`, l.2 `# deb-src [arch=amd64] … focal stable`. Brak `signed-by` (klucz w starym `/etc/apt/trusted.gpg`) |
| 3 | `dpkg -l \| grep -i -E "docker\|containerd"` | 6 pakietów z repo Dockera, buildy `~ubuntu.20.04~focal`: `containerd.io` 1.6.28-1, `docker-buildx-plugin` 0.13.0-1, `docker-ce` 5:25.0.4-1, `docker-ce-cli` 5:25.0.4-1, `docker-ce-rootless-extras` 5:25.0.4-1, `docker-compose-plugin` 2.24.7-1. Brak `docker.io`/snap |
| 4 | `docker --version; docker compose version; systemctl is-enabled docker; systemctl is-active docker` | Docker 25.0.4 (build 1a576c5), Compose v2.24.7, `enabled`, `active` |
| 5 | `docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'` | 7 kontenerów smartWARE, „Up 7 hours”: dataview 453.7.0.2.2, datareportengine 7.0.2.2, datareport 7.0.2.2, datastore 454.7.0.2.2, reverse-proxy 2.1.0.18 (te 5 `healthy`), mqtt 2.0.22, postgres-server 17.10.0.0 (bez healthchecka). Zrzut: `docs/images/etap2/02-smartware-docker-ps-before.png` |
| 5b | `docker inspect -f '{{.Name}} {{.State.StartedAt}}' $(docker ps -q)` | **punkt odniesienia**: dataview 2026-11-23T08:00:24.243323062Z, datareportengine …24.612161268Z, datareport …24.475975059Z, datastore …24.20377203Z, reverse-proxy …24.637569125Z, mqtt …24.579055936Z, postgres-server …24.512419613Z |
| 6 | `ss -ltn` | LISTEN: 0.0.0.0/[::] :80, :443 (smartWARE), :22 (SSH); 127.0.0.1/[::1]:631 (CUPS); 127.0.0.53:53 (DNS). **1883 i 3000 wolne** |
| 7 | `timedatectl` | Europe/Berlin (CET, +0100), `System clock synchronized: yes`, NTP active, RTC w UTC |
| 8 | `free -m; df -h /; nproc; docker stats --no-stream` | RAM 15 748 MB, used 1 339, available 13 882; swap 2047 nieużywany. `/` 938G, used 18G, avail 873G (2%). 8 wątków. smartWARE: dataview 92,1 MiB, datareportengine 108,5, datareport 98,8, datastore 144,7, reverse-proxy 9,7, mqtt 6,6, postgres-server 56,6 → **ok. 517 MiB**; CPU ≈ 0%. Kontenery smartWARE **bez limitu pamięci** (limit 15,38 GiB) – nie zmieniamy (cudzy produkt) |
| 9 | `git --version; ssh -V; openssl version` | git 2.34.1, OpenSSH 8.9p1, OpenSSL 3.0.2 |
| 10 | `systemctl is-enabled unattended-upgrades; apt-config dump \| grep …` | `enabled`; Allowed-Origins tylko `${distro_id}:${distro_codename}`, `-security`, ESMApps, ESM-infra – **repo Dockera nie jest w automatycznych aktualizacjach** |

## Runda 2a: repo Dockera (D11) – wykonane

| # | Polecenie | Wynik |
| --- | --- | --- |
| 2a-1 | `sudo cp -a <plik> /home/jumo/docker-apt-source.list.bak-focal-20261123` | kopia 148 B, root, data oryginału. **Kopia poza `sources.list.d`** (tam plik `.bak` dawałby komunikat apt o nieprawidłowym rozszerzeniu) |
| 2a-2 | `sudo sed -i '/download\.docker\.com/ s/ focal / jammy /' <plik>; diff <kopia> <plik>` | `1,2c1,2`: `deb …ubuntu focal stable` → `jammy stable` oraz zakomentowane `# deb-src` → `jammy`. Nic więcej |
| 2a-3 | `sudo apt update 2>&1 \| tail -n 15` | `Get:1 https://download.docker.com/linux/ubuntu jammy InRelease`, `Get:4 … jammy/stable amd64 Packages`; repozytoria Ubuntu Hit; **bez błędów**. „122 packages can be upgraded” (nie aktualizujemy). Pozostałe ostrzeżenie: `W: …docker.com…/jammy/InRelease: Key is stored in legacy trusted.gpg keyring (/etc/apt/trusted.gpg)` – zapisane, **w k1 nie naprawiamy** (osobna sprawa: przeniesienie klucza do `/etc/apt/keyrings` + `signed-by`; kandydat na etap 7) |
| 2a-4 | `sudo apt-mark hold containerd.io docker-buildx-plugin docker-ce docker-ce-cli docker-ce-rootless-extras docker-compose-plugin && apt-mark showhold` | wszystkie 6 „set on hold”; `showhold` zwraca te 6 nazw |

`apt upgrade` nie był uruchamiany. Demon Dockera nie był restartowany. Dowód (2a-5) zbiera Claude Code.

## Zmiana sposobu wykonania (decyzja Grzegorza, 23.11.2026, 16:19)

Od tego miejsca polecenia na komputerze wykonuje **Claude Code** przez `ssh jumo@192.168.0.213 "<polecenie>"` ze swojego terminala na laptopie (klucz, bez hasła), nie Grzegorz ręcznie. Zasady:

1. Tylko polecenia z zatwierdzonego planu kroku (plan → review → „ok”).
2. **Bez `sudo`** (hasło ma tylko Grzegorz). Krok wymagający `sudo` → stop, polecenie dla Grzegorza w raporcie lub pytaniu.
3. Nie restartuje demona Dockera, nie zatrzymuje/usuwa/restartuje kontenerów JUMO smartWARE (dataview, datareportengine, datareport, datastore, reverse-proxy, mqtt, postgres-server) ani ich wolumenów i sieci; żadnego `docker system prune`.
4. Nie pisze do PLC ani do licznika (zasady twarde 1 i 2); z komputera do PLC tylko odczyt FC04.
5. Kryteria zatrzymania z planu kroku obowiązują: stop i pytanie, bez obchodzenia.
6. Każde wykonane polecenie z wynikiem (bez sekretów) trafia do raportu kroku. Testy fizyczne (przewody, zasilanie, restart komputera, jeśli wymaga `sudo`) i zrzuty z GUI robi Grzegorz.

## Do wykonania przez Claude Code (reszta k1)

- **2a-5:** `docker inspect -f '{{.Name}} {{.State.StartedAt}}' $(docker ps -q)` – znaczniki identyczne jak w 5b; `docker ps` jak w 5; `ss -ltn` jak w 6.
- **2b:** deploy key wg planu i review (K1-U3: `ssh-keyscan` + `ssh-keygen -lf`, **porównanie odcisku SHA256 z oficjalną stroną GitHuba robi Grzegorz**, dopiero potem `known_hosts`). Klucz publiczny pokazać Grzegorzowi, który dodaje go w GitHubie **bez** „Allow write access” i robi zrzut → `docs/images/etap2/01-github-deploy-key-readonly.png`. `~/.ssh/config` przez `printf`, prawa 600. Klon do `/home/jumo/ai-predykcja`, kontrola hash (`ff8075a` lub nowszy), `pull --ff-only`, odrzucony `push --dry-run`.
- Raport `e2-k1-report.md` (z tymi wynikami) i `docs/ops/jumo-ipc-setup.md` (z K1-U5: `unhold` i aktualizacja smartWARE; notatka o legacy keyring) → stop.
