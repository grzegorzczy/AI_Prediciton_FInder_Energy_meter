# e2-k1 raport: przygotowanie komputera `jumo-ipc`
Status: DO PRZEGLĄDU

Wykonanie 23.11.2026. Runda 1 i 2a: architekt z Grzegorzem (surowe wyniki w
`e2-k1-results.md`). Punkt 2a-5 i cała 2b: Claude Code przez `ssh jumo@192.168.0.213`,
bez `sudo`, według zasad z sekcji „Zmiana sposobu wykonania” w `e2-k1-results.md`.
Do repo nie trafiły żadne sekrety (klucz prywatny nie był nigdzie wypisywany).

## Co zrobiono

| Pozycja planu | Stan |
| --- | --- |
| Runda 1: 10 odczytów | wykonana, żadne kryterium zatrzymania nie zaszło (`e2-k1-results.md`) |
| 2a: `focal` → `jammy` w jednym pliku źródeł, kopia, `diff`, `apt update` bez błędów | wykonane |
| 2a: `apt-mark hold` na 6 zainstalowanych pakietach Dockera | wykonane |
| 2a-5: dowód, że demon nie był restartowany | wykonany (niżej) |
| 2b: deploy key tylko do odczytu, `known_hosts` po porównaniu odcisku, klon | wykonane |
| 2c: `.env` | nie tworzony (przesunięty do k2, zatwierdzone w review) |

Pliki w repo w tym kroku: `docs/handoff/e2-k1-results.md`, ten raport,
`docs/ops/jumo-ipc-setup.md`, `docs/images/etap2/02-smartware-docker-ps-before.png`.
Zrzut `01-github-deploy-key-readonly.png` (dostarczył Grzegorz po wypchnięciu raportu): lista
Deploy keys z wpisem `jumo-ipc`, „Read-only”, odcisk `SHA256:YFDrLXfeh4vBCBaM2JqQQrMEAHKNgm2cbL4Xjws0KcI`
zgodny z odciskiem klucza na komputerze. GitHub pokazuje przy kluczu „Never used”, mimo że
klon i `pull` przez niego przeszły; prawdopodobnie opóźnienie wskaźnika po stronie GitHuba (nie sprawdzałem); uwierzytelnienie
potwierdza komunikat „Hi grzegorzczy/…” i udany klon.

## Wyniki poleceń z mojej części

### 2a-5: demon Dockera nie był restartowany

`docker inspect -f '{{.Name}} {{.State.StartedAt}}' $(docker ps -q)` po wszystkich zmianach:
wszystkie 7 znaczników **identyczne** z punktem odniesienia z rundy 1 (np. `/dataview
2026-11-23T08:00:24.243323062Z`, `/postgres-server …24.512419613Z`). Demon:
`systemctl show docker -p ActiveEnterTimestamp` = `Mon 2026-11-23 09:00:24 CET`
(= 08:00:24 UTC, ten sam moment co start kontenerów), `MainPID=1283`. `docker ps`: te same
7 kontenerów, „Up 7 hours”, pięć `healthy`. `apt-mark showhold`: `containerd.io`,
`docker-buildx-plugin`, `docker-ce`, `docker-ce-cli`, `docker-ce-rootless-extras`,
`docker-compose-plugin`.

### `ss -ltn` po zmianach

Ten sam stan co w rundzie 1: `:80`, `:443` (smartWARE), `:22`, `127.0.0.1/[::1]:631`,
`127.0.0.53:53`. `1883` i `3000` wolne.

### 2b: deploy key

- Klucz `~/.ssh/ai_predykcja_deploy` (ed25519, bez hasła, K1-d) wygenerowany na komputerze;
  poprzednio w `~/.ssh` nie było ani klucza, ani `config`. Prawa: `.ssh` 700, `config` 600,
  klucz prywatny 600, publiczny 644.
- `~/.ssh/config`, dopisane przez `printf`: `Host github-ai-predykcja`, `HostName github.com`,
  `User git`, `IdentityFile ~/.ssh/ai_predykcja_deploy`, `IdentitiesOnly yes`.
- Odcisk klucza serwera GitHub pobrany z komputera (`ssh-keyscan -t ed25519`, `ssh-keygen -lf`):
  `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` (ED25519). **Porównał go Grzegorz
  ze stroną „GitHub's SSH key fingerprints”: zgodny.** Dopiero potem dopisany do `known_hosts`.
  Ślad porównania: odcisk z komputera (powyżej) i odcisk ze strony GitHuba (Grzegorz potwierdził
  zgodność w czacie; strona nie jest pobierana przeze mnie).
- Odcisk klucza deploy: `SHA256:YFDrLXfeh4vBCBaM2JqQQrMEAHKNgm2cbL4Xjws0KcI`.
  Klucz publiczny dodał Grzegorz w GitHub → repo → Settings → Deploy keys, tytuł `jumo-ipc`,
  bez „Allow write access”.
- Pierwsza próba autoryzacji dała `Permission denied (publickey)`: klucz nie był jeszcze dodany
  (strona Deploy keys była pusta, mimo wcześniejszego potwierdzenia). Po dodaniu:
  `Hi grzegorzczy/AI_Prediciton_FInder_Energy_meter! You've successfully authenticated, but GitHub
  does not provide shell access.`
- Klon do `/home/jumo/ai-predykcja` (K1-a), 103 MB (historia zawiera kilka wersji pliku `.432`).
  `git log`: `ff8075a docs: e2-k1 review (OK with remarks)`, czyli nowszy niż wymagany `b58dc04`.
  `git pull --ff-only`: „Already up to date.”
- `git push --dry-run origin main` odrzucony: `ERROR: The key you are authenticating with has been
  marked as read only.` Kod wyjścia 128. Klucz nie pozwala na zapis.

## Odstępstwa od planu i dlaczego

1. **Pierwsze wykonanie 2a-5 przez PowerShell nie udało się** (cudzysłowy zniekształcone przez
   PowerShell 5.1); powtórzone przez Git Bash i heredoc. Odczyt tylko do odczytu, bez skutków.
2. **Pierwszy skrypt klonowania przerwał się po teście autoryzacji:** zagnieżdżony `ssh` czytał
   resztę skryptu ze standardowego wejścia. Nic nie zostało sklonowane; powtórzone bez zagnieżdżonego
   `ssh`. Lekcja do `jumo-ipc-setup.md`: przy `bash -s` nie wywoływać `ssh` bez `-n`.
3. **Plik źródeł Dockera ma nazwę z `jammy`, a wpis wskazywał `focal`** (runda 1). Zmieniono tylko
   wpis; kopia leży poza `sources.list.d` (`/home/jumo/docker-apt-source.list.bak-focal-20261123`).
4. **Ostrzeżenie `Key is stored in legacy trusted.gpg keyring`** nie jest naprawiane w k1
   (osobna sprawa, kandydat na etap 7).

## Zmierzone zasoby

Stan bazowy z rundy 1 (nic nie uruchomiono w k1): RAM 15 748 MB, used 1 339 MB, available
13 882 MB; po k1 `free -m`: used 1 359 MB, available 13 860 MB (różnica to szum: SSH, klon).
Dysk `/`: 938 GB, zajęte 18 GB. smartWARE razem ok. 517 MiB (kontenery bez limitu pamięci, nie
zmieniamy). Klon repo: 103 MB.

## Checklista dla Grzegorza (do zaliczenia k1)

Polecenia z laptopa w cmd; w razie wątpliwości do cytowania patrz `docs/ops/jumo-ipc-setup.md`.

1. Strona Deploy keys repo pokazuje wpis `jumo-ipc` bez „write”. Zrzut:
   `docs/images/etap2/01-github-deploy-key-readonly.png`.
2. `ssh jumo@192.168.0.213 "apt-mark showhold"`: 6 nazw pakietów Dockera.
3. `ssh jumo@192.168.0.213 "docker ps"`: 7 kontenerów smartWARE „Up”, bez „Up … minutes”.
4. `ssh jumo@192.168.0.213 "git -C ~/ai-predykcja log --oneline -1"`: commit `ff8075a` lub nowszy.
5. `ssh jumo@192.168.0.213 "git -C ~/ai-predykcja push --dry-run origin main"`: odmowa
   „marked as read only”.

## Otwarte kwestie

- Zrzut `01-github-deploy-key-readonly.png` dostarczony i dodany (patrz wyżej).
- Klucz Dockera w starym `trusted.gpg` (ostrzeżenie `apt`); do etapu 7.
- `hold` blokuje poprawki Dockera; procedura odblokowania i ostrzeżenie o smartWARE w
  `docs/ops/jumo-ipc-setup.md`.
- Plik `e2-k1-report.md` kończy k1; k2 zaczyna się od `docs/handoff/e2-k2-plan.md` dopiero po
  review tego raportu i „ok” Grzegorza.
