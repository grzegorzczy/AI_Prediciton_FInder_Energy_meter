# e2-k1 review: przygotowanie komputera `jumo-ipc`

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k1-plan.md` (commit `b58dc04`), `e2-k0-review.md`, dokumenty projektu 00, 04, 10, 12.

## Werdykt: OK Z UWAGAMI

Plan jest zgodny z decyzjami D5 i D11 oraz uwagą U7. Dobre:
- runda tylko z odczytami przed zmianami;
- kryteria zatrzymania;
- kopia pliku przed zmianą;
- dowód „demon nie był restartowany” przez porównanie `docker ps` przed i po;
- weryfikacja odcisku klucza GitHuba;
- test, że klucz nie pozwala na zapis;
- `docs/ops/jumo-ipc-setup.md` na etap 7.

Uwagi K1-U1…K1-U5 są drobne i nie wymagają nowego planu.

## Decyzje do planu

| Id | Rozstrzygnięcie |
| --- | --- |
| K1-a | `/home/jumo/ai-predykcja` – **zatwierdzone** |
| K1-b | Brak `git` → stop i pytanie – **zatwierdzone** |
| K1-c | Brak `docker compose` → stop i pytanie – **zatwierdzone** |
| K1-d | Klucz deploy bez hasła – **zatwierdzone** (tylko odczyt jednego repo, w repo brak sekretów, prawa 600) |
| `.env` przesunięty do k2 | **zatwierdzone** – zmienne zmieniają się w k2 (D3) |
| Hasła `openssl rand -hex 24` zamiast base64 | **zatwierdzone** – poprawka słuszna (znaki `+ / =` w URL połączenia i powłoce) |

## Uwagi

### K1-U1 – kto prowadzi polecenia

Zgodnie z dokumentem 00 polecenia dla komputera prowadzi architekt z Grzegorzem w czacie projektu: jedno polecenie naraz, wklejony wynik, następne polecenie. Wyniki rund 1 i 2 (surowe wyjścia, bez sekretów) architekt zapisuje do `docs/handoff/e2-k1-results.md`. Claude Code na tej podstawie pisze `e2-k1-report.md` i `docs/ops/jumo-ipc-setup.md`. Polecenia rundy 2 architekt układa z wyników rundy 1, tak jak przewiduje plan.

### K1-U2 – cytowanie poleceń w cmd

Polecenia idą jako `ssh jumo@192.168.0.213 "<polecenie>"` z cmd na Windows. W cmd nie da się bezpiecznie zagnieździć cudzysłowów podwójnych. Dlatego `docker ps --format "table {{.Names}}…"` trzeba zapisać z apostrofami wewnątrz (`--format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'`). Wpis do `~/.ssh/config` dopisujemy przez `printf` z apostrofami, a nie heredoc. `docs/ops/jumo-ipc-setup.md` podaje polecenia w postaci do uruchomienia **na komputerze** (bash); wariant cmd jest w raporcie.

### K1-U3 – pierwsze połączenie z GitHubem bez trybu interaktywnego

`ssh jumo@… "ssh -T git@github-ai-predykcja"` bez terminala nie pokaże pytania o odcisk i się nie powiedzie. Zamiast akceptować klucz przez `yes` (i `ssh -t`) dodajemy go jawnie:
1. `ssh-keyscan -t ed25519 github.com > /tmp/gh_key`
2. `ssh-keygen -lf /tmp/gh_key` – porównanie odcisku SHA256 z oficjalną stroną GitHuba (docs.github.com, „GitHub's SSH key fingerprints”); porównuje Grzegorz.
3. Dopiero po zgodności: `cat /tmp/gh_key >> ~/.ssh/known_hosts`.

Ślad porównania (oba odciski) trafia do raportu.

### K1-U4 – `sudo` przez SSH

Polecenia z `sudo` (`cp -a`, `sed -i`, `apt update`, `apt-mark hold`) idą przez `ssh -t jumo@192.168.0.213 "sudo …"`, po jednym. Hasło wpisuje Grzegorz.

### K1-U5 – `hold` a przyszłe aktualizacje smartWARE

Do `docs/ops/jumo-ipc-setup.md` dopisać:
- procedurę zdjęcia blokady (`apt-mark unhold …`) na okno serwisowe;
- informację, że instalator nowej wersji JUMO smartWARE może wymagać nowszego Dockera. Przed aktualizacją smartWARE sprawdzamy jego wymagania i robimy kopię jak 15.11.2026 (dokument 10).

## Kontrola reszty planu

- Kryterium „gotowe, gdy” jest sprawdzalne: `apt-mark showhold`, porównanie `docker ps`, `git pull --ff-only`, odrzucony `push`.
- Bezpieczeństwo:
  - klucz prywatny nigdy nie jest wypisywany;
  - deploy key bez zapisu;
  - brak `apt upgrade`;
  - porty tylko odczytywane;
  - strefa czasowa bez zmian.
- Budżet RAM: k1 nic nie uruchamia; pomiar bazowy (`free -m`, `docker stats`) dobrze, że jest.
- Mapa D1–D11 i U1–U8 na kroki k2–k8 jest kompletna.
- Hash kontrolny klonu: „`b58dc04` lub nowszy” (zamiast `af997a3`).
- Zrzut ekranu do dokumentacji: lista Deploy keys w GitHubie (bez „write”) → `docs/images/etap2/01-github-deploy-key-readonly.png`; `docker ps` przed i po → `02-…`. Zrzuty podaje Grzegorz.

## Następny krok

Po „ok” Grzegorza architekt prowadzi rundę 1 w czacie projektu. Claude Code czeka na `e2-k1-results.md`, potem pisze `e2-k1-report.md` i `docs/ops/jumo-ipc-setup.md` → stop.
