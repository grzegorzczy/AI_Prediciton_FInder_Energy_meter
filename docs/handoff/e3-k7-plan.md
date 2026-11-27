# E3-k7 – plan (krótki): diagnoza sieci IPC (E3-NET), potem wdrożenie etapu 3

Data: 2026-11-28. Stan: produkcja `~/ai-predykcja` na `c299eaa` (etap 2), worktree testowy `~/ai-predykcja-dev` na
`64cf4de` (= `origin/main`). Review k6b: `64cf4de`. Bez `sudo` po mojej stronie (polecenia `sudo` podaję gotowe), bez `.env`,
bez smartWARE, nigdy nie piszę do PLC.

## Część A – E3-NET (blokuje wdrożenie)

### Co już wiadomo (odczyt bez `sudo`, 28.11 ok. 00:45)

| Fakt | Źródło |
| --- | --- |
| Dwie karty r8169: `enp1s0` (profil „Wired connection 1”, teraz DOWN) i `enp2s0` („Wired connection 2”, UP, .215) | `ip -br addr`, `nmcli` |
| 27.11 12:00–20:49: **żadnego zdarzenia** jądra ani NetworkManagera na `enp1s0`/`enp2s0` (łącze z punktu widzenia IPC nie padło) | `journalctl -k`, `-u NetworkManager` |
| 27.11 **20:49:22 `enp1s0` Link Down, 20:49:28 `enp2s0` Link Up** → nowy profil, nowa dzierżawa .215. Wygląda na **przełożenie kabla do drugiego portu** | `journalctl -k` |
| `enp2s0` pracuje z **100 Mb/s** (karta gigabitowa) – podejrzany kabel, wtyk albo port switcha | `journalctl -k` |
| Liczniki `enp2s0` od podniesienia łącza: 0 błędów, 0 odrzuconych | `ip -s link` |
| NetworkManager działa od 26.11 06:43; aktualizacje automatyczne włączone, ostatnie 27.11 06:34 (biblioteki), czeka `reboot-required` | `ps`, `apt/history.log`, `systemctl` |

Wniosek roboczy: przerwa 17–20:49 nie była utratą łącza na IPC – przyczyna raczej poza IPC (switch, router, DHCP, adres)
albo w ruchu IP. Resety ssh po 20:49 przy czystych licznikach karty: do sprawdzenia konflikt adresu .215 i router.

### Kroki (ja, bez `sudo`; każdy kończy się wpisem w raporcie)

1. **Dzienniki od 26.11:** NetworkManager i jądro dla obu kart, odnowienia DHCP (czas dzierżawy, czy .213 było odnawiane
   przed 17:00), przyczyna restartu NM 26.11 06:43.
2. **Czy IPC tracił też PLC:** logi collectora i dane real w bazie 27.11 16:00–21:00 (minuty bez wierszy, wpisy
   „PLC offline”). Jeśli dane real szły ciągle – IPC miał LAN do PLC, a przerwa dotyczyła tylko drogi laptop ↔ IPC
   (router/Wi-Fi/adres). Luka (od–do) → wpis w `data_windows` (wzór jak migracja 011).
3. **Monitor 24 h** w `~/aip-monitor` (skrypt `docs/ops/net-monitor.sh` obok instrukcji ops, uruchomiony `nohup`): co 10 s ping bramy i PLC, połączenie
   TCP z PLC:502 (samo połączenie, bez zapytań), adres i stan `enp2s0`, `ip neigh` dla .215 (czy inny MAC); po stronie laptopa
   ping IPC w czasie mojej pracy. Wynik: liczba i czasy przerw po każdej stronie.
4. **Polecenia `sudo` dla Grzegorza** (gotowe w raporcie): `arping -D -I enp2s0 192.168.0.215` (konflikt adresu),
   `ethtool enp2s0` (prędkość, autonegocjacja).

### Po stronie Grzegorza

- Odpowiedź: **czy 27.11 ok. 20:49 ktoś przełożył kabel** z portu 1 do portu 2? Który port zostaje?
- Kontrola kabla i portu switcha (100 Mb/s); rezerwacja DHCP w routerze: **IPC .213** (MAC karty, która zostaje:
  `enp2s0` = `04:2b:58:12:f7:a2`), **PLC .246**. Po rezerwacji: nieużywany profil NM do usunięcia (zmiana systemowa –
  polecenie `sudo nmcli` podam po decyzji).

### Kryterium zakończenia A

Monitor 24 h bez przerw po stronie IPC, adres stały (.213 z rezerwacji), przyczyna nazwana albo zawężona (IPC / sieć),
luka 27.11 w `data_windows`. Dopiero wtedy część B.

## Część B – wdrożenie (po „ok” do A)

Kolejność z planu k0 (§ 7) i uwag z review k5 i k6b; każdy punkt z kontrolą 20 wierszy/s danych real.

1. **Restart IPC** (czekające aktualizacje), przed wdrożeniem, żeby nie przerwał wgrywania: kontrola wstawania
   produkcji (kontenery `Up`, 20 wierszy/s, brak luk poza oknem), wpis w `data_windows`.
2. **Poprawka V1 (review k6b):** opis panelu trendu: „Oś 90 dni od teraz; przy zaznaczeniu fragmentu wykresu oś idzie za
   pulpitem”. Generator + test, commit, push.
3. **Grzegorz:** konto MQTT symulatora w `.env` (polecenie z `docs/ops/jumo-ipc-setup.md`, Claude Code nie czyta `.env`).
4. **R-1:** `git pull --ff-only` → `docker compose up -d --build`: migracja 012, odtworzenie Mosquitto (ACL), ingest,
   nowy `aip-simulator`; krótka przerwa brokera (bufor collectora 30 000). Kontrola: `devices` (5 liczników + pompa,
   `source`), 49 wierszy/s (20 real + 29 sim), `data_windows` dla wdrożenia.
5. **Pilotaż 1 doby historii** w nocy (`simulator-tools`, profil `tools`, K5R-D1): tempo produkcyjne (fsync włączony),
   pomiar **odrzuconych danych sim na żywo** (K5R-D2) → `--fill-gaps` dla okna, cel 0 brakujących minut.
6. **Pełne wgranie** (pompa 84 doby + historia liczników wg planu k5): wolne miejsce ≥ 17 GB (teraz 868 GB);
   **kompresja wstrzymana tylko na tę noc – obowiązkowe wznowienie**, rozmiar bazy i liczba skompresowanych chunków przed
   i po; jeśli prognoza > ok. 10 h – dwie noce przez wznowienie. Proces w tle (`nohup`), odporny na zerwanie ssh.
7. **Odświeżenie** `pump_1m` i agregatów energii dla zakresu historii; liczba wierszy na dobę.
8. **Pomiary:** RAM wszystkich `aip-*` (`docker stats`, `memory.peak`; Grafana wobec 512 MiB), dysk, wiersze/s.
9. **Zrzuty końcowe z produkcji** (8 z planu k6, Grzegorz) – w tym kontrola V3 („Udział w energii”, „Świeżość danych”);
   jeśli dalej ucięte: krótsze etykiety bez „(SYMULACJA)” w tych dwóch panelach.
10. Agent `reviewer` (zmiany wdrożeniowe), raport `e3-k7-report.md`. Checklista `etap-3.md` – k8.

## Ryzyka

| Ryzyko | Postępowanie |
| --- | --- |
| Zerwanie sieci w czasie wgrywania (ok. 6 h) | część A najpierw; wgrywanie w tle, wznawialne (idempotentne, `--fill-gaps`) |
| Wstrzymana kompresja obejmuje dane real | tylko jedna noc, wznowienie i kontrola w tym samym kroku |
| Restart IPC nie podnosi produkcji | restart osobno, przed R-1, z kontrolą i wpisem okna |
| Zmiana adresu IPC po rezerwacji | tunel i polecenia na nowy adres; collector łączy się do PLC, nie odwrotnie |

## Do decyzji

1. Grzegorz: kabel 20:49 i docelowy port; termin rezerwacji DHCP.
2. Architekt: czy monitor sieci (krok A3) zostaje na stałe w `ops` (proponuję tak – tani, pomaga przy każdej przerwie).
3. Noce na pilotaż i pełne wgranie (proponuję: pilotaż noc po „ok” do B, pełne wgranie noc następna).

Plan k7 gotowy do przeglądu.
