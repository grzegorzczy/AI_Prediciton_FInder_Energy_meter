# E2-k7c – review wizualny v3 (architekt)

Data: 2026-11-25, 08:48. Zrzuty Grzegorza (zakres 24.11 18:48 – 25.11 06:48), zapisane jako
`docs/images/etap2/05-grafana-jakosc.png`, `06-grafana-energia.png`, `07-grafana-diagnostyka.png`.

**Werdykt: OK Z UWAGAMI** – jedna regresja (K7C-V1) do poprawki w k7d.

## Potwierdzone

- **W-9:** obie granice pasma (napięcie i częstotliwość) są czerwone i widoczne. Hipoteza z przycinaniem linii na brzegu wykresu się potwierdziła.
- **W-1:** mapa cieplna niebieska, puste komórki przezroczyste, liczby czytelne.
- **W-2:** oś kodu błędu zielona „Brak błędu”, epizody 00:35–01:00 jako wąskie paski w kolorach 161/162; po 01:00 nic się nie ciągnie.
- **W-3/W-4:** brak spadku na końcu minuty; legenda „Pokrycie upłynionej części (w toku)”.
- **W-7:** „Poza pasmem U [min]”, „Z danymi U [min]” (720 min = 12 h), „Moc maks. profilu” – bez obcinania.
- Spójność liczb: „Sekundy bez pomiaru mocy” w godzinie 00:00 ≈ 55 s = 14 epizodów × ok. 4 s.

## K7C-V1 (ważna, regresja) – panele z własnym zakresem czasu go zgubiły

Na zrzucie 06:
- „Zużycie na dobę (ostatnie 14d)” ma oś 19:00–06:00 (zakres dashboardu), a nie 14 dni;
  brak niebieskiego znacznika „Last 14 days”, który był na zrzucie v2;
- „Profil: godzina × dzień tygodnia (ostatnie 28d)” pokazuje tylko wtorek 19–21 i środę 0–6,
  czyli godziny z zakresu dashboardu; we v2 były m.in. wtorek 0 i 7–9. Brak znacznika „Last 28 days”;
- „Moc maks. profilu” – też bez znacznika 28 d.

Prawdopodobnie `timeFrom` (lub `relativeTime` w Grafanie 13) zniknął przy regeneracji w `generate.py`.
Poprawka: przywrócić własne zakresy wszystkim panelom, które je miały w k7b (14 d, 28 d, a także
„Kontrola całki… 14d” i ewentualne inne), i dodać test, który dla każdego takiego panelu sprawdza
obecność zakresu w wygenerowanym JSON. W raporcie wypisać listę paneli z własnym zakresem.

## Drobne (bez poprawki)

- Na wykresie „Zużycie na minutę” seria epizodów 00:35–01:00 daje ząbki w linii energii i pokrycia – to prawdziwe dane, nie błąd.

## Dalej

k7d = K7C-V1 (mały krok, bez planu), raport `e2-k7d-report.md`. Po nim Grzegorz robi zrzuty 06, 06b, 06c.
Równolegle rusza E2-PLC2 (decyzja Grzegorza 25.11) – najpierw plan architekta dla strony PLC.
