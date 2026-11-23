# e2-k1 report review: przygotowanie komputera `jumo-ipc`

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k1-report.md`, `docs/handoff/e2-k1-results.md`, `docs/ops/jumo-ipc-setup.md`, zrzut `docs/images/etap2/01-github-deploy-key-readonly.png`.

## Werdykt: OK – krok k1 zakończony

Wszystkie punkty „Jak sprawdzę” z planu e2-k1 są potwierdzone wynikami:

| Kryterium | Dowód w raporcie | Ocena |
| --- | --- | --- |
| Repo Dockera `jammy`, `apt update` bez błędów | results 2a-2, 2a-3 | ✔ |
| `apt-mark showhold` = 6 pakietów Dockera | results 2a-4, raport 2a-5 | ✔ |
| Demon nie był restartowany | 7 × `StartedAt` identyczne z punktem odniesienia, `ActiveEnterTimestamp` 09:00:24 CET = start kontenerów | ✔ |
| Porty bez zmian, 1883/3000 wolne | `ss -ltn` po zmianach | ✔ |
| Odcisk klucza GitHuba sprawdzony przed `known_hosts` | `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` (ED25519) – zgodny z opublikowanym odciskiem ED25519 GitHuba; porównanie potwierdził Grzegorz | ✔ |
| Deploy key tylko do odczytu | zrzut: `jumo-ipc`, „Read-only”, odcisk `SHA256:YFDrLX…0KcI` = klucz na komputerze; `push --dry-run` → „marked as read only”, kod 128 | ✔ |
| Klon i aktualizacja | `/home/jumo/ai-predykcja`, `ff8075a` (≥ `b58dc04`), `pull --ff-only` „Already up to date” | ✔ |
| Bez sekretów w repo, bez `sudo` po stronie Claude Code | raport | ✔ |

Odstępstwa (PowerShell i cytowanie, zagnieżdżony `ssh` czytający stdin, pierwsze `Permission denied` przed dodaniem klucza) są opisane i nie miały skutków. Lekcja o `ssh -n` w `bash -s` jest w `docs/ops` – dobrze. „Never used” przy kluczu w GitHubie to opóźnienie wskaźnika; uwierzytelnienie potwierdzają komunikat „Hi grzegorzczy/…” i udany klon.

## Checklista Grzegorza

Punkt 1 (zrzut Deploy keys) – **zaliczony** (zrzut w repo). Punkty 2–5 to odczyty konsolowe, które Claude Code już wykonał i zapisał w raporcie (tryb pracy z dokumentu 04). Architekt przyjmuje je na podstawie raportu; Grzegorz **nie musi** ich powtarzać. Na przyszłość: checklista Grzegorza w raportach obejmuje tylko to, czego Claude Code nie może sprawdzić sam (GUI, testy fizyczne, `sudo`, decyzje).

## Drobne do `docs/ops/jumo-ipc-setup.md` (przy okazji k2, bez osobnego kroku)

1. Pkt 2: `diff /home/jumo/docker-apt-source.list.bak-focal-* …` – przy drugiej kopii glob dopasuje kilka plików; użyć zmiennej z nazwą kopii (`KOPIA=…$(date +%Y%m%d)`).
2. Pkt 4: przed `printf >> ~/.ssh/config` dodać `mkdir -p ~/.ssh && chmod 700 ~/.ssh` (na czystym komputerze katalog może nie istnieć, gdy `ssh-keygen` nie był wcześniej użyty z domyślną ścieżką).

## Stan po k1 (punkt startowy k2)

- Docker 25.0.4 / Compose 2.24.7, `enabled`, pakiety na `hold`, repo `jammy`.
- smartWARE: 7 kontenerów, ok. 517 MiB, bez zmian od 08:00:24Z.
- RAM dostępne ok. 13,9 GB; dysk wolny 873 GB; porty 1883 i 3000 wolne.
- Repo na komputerze: `/home/jumo/ai-predykcja`, aktualizacja `git pull --ff-only`.

## Następny krok

Claude Code: `docs/handoff/e2-k2-plan.md` (Compose, Mosquitto, TimescaleDB, role, migracje) z decyzjami D1, D3, D4, D9 i uwagami U1, U3, U5, U6 z `e2-k0-review.md`; polecenia na komputerze w trybie z dokumentu 04 (bez `sudo`, bez ruszania smartWARE). `.env` tworzy Grzegorz (hasła `openssl rand -hex 24`) – plan ma podać dokładne polecenie i listę zmiennych, a Claude Code nie widzi wartości haseł → stop.
