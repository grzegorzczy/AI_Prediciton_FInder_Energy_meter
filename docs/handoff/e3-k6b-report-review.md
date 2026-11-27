# E3-k6b – review raportu (architekt)

Data: 2026-11-28. Raport: `e3-k6b-report.md` (`7a03da1`; poprawki `0c9fdd1`, `5668bfc`, `781b79c`, `2c38543`; review k6 i zrzuty `da8dd5c`). Review krótkie.

**Werdykt: OK.** V1–V6 wykonane, testy Grafany z `slow` 140/140. Dobrze wyłapana regresja wydajności w V2 (8,5 s / timeout → 0,13 s po wyliczeniu pierwszego odczytu raz na urządzenie).

## Uwagi

- **V1:** ograniczenie przy zakresie bezwzględnym (zaznaczenie myszą) akceptuję – dopisać w opisie panelu (ikona „i”): „Oś 90 dni od teraz; przy zaznaczeniu fragmentu wykresu oś idzie za pulpitem”.
- **V3:** niesprawdzone wzrokowo – kontrola na zrzutach k7 (Flota: „Udział w energii”, „Świeżość danych”). Jeśli dalej ucięte – krótsze etykiety bez „(SYMULACJA)” w tych dwóch panelach (znacznik zostaje w kolorze / legendzie).
- **Push:** 10 commitów lokalnie – wypchnięcie robi Grzegorz w swoim terminalu (logowanie do GitHuba); potem Claude Code wyrównuje worktree na IPC z `origin/main`.

## Przed k7 (blokuje wdrożenie)

**Sieć IPC (E3-NET):** zerwanie 27.11 (nowa dzierżawa .215) i powtarzające się resety ssh 27/28.11. Wgrywanie historii trwa ok. 6 h – niestabilna sieć przerwie je i zatrzyma zbieranie danych real. Plan k7 zaczyna się od kroku diagnostycznego (bez `sudo` tam, gdzie się da; polecenia `sudo` dla Grzegorza): dziennik NetworkManager i jądra (`enp2s0`, link down/up, błędy karty), liczniki błędów interfejsu (`ip -s link`), czy są dwa profile połączenia („Wired connection 1/2”), automatyczne aktualizacje (`/var/log/apt/history.log`, `unattended-upgrades`), luka danych real 27.11 (od–do) → `data_windows`. Po stronie Grzegorza: rezerwacja DHCP (IPC .213, PLC .246), kontrola kabla i portu switcha. Restart IPC (oczekujące aktualizacje) – planowo w k7, z kontrolą wstawania produkcji.
