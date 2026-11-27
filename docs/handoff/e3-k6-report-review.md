# E3-k6 – review raportu i przegląd wizualny (architekt)

Data: 2026-11-27. Raport: `e3-k6-report.md` (commity `c8f108d`, `21cfa18`, `1964103` – do wypchnięcia po naprawie poświadczeń GitHub). Zrzuty Grzegorza z `aip-test` (tunel, 27.11 ok. 21:00): Flota 24 h, Flota 7 dni, Pompa 24 h (2×), Pompa 90 dni, Pompa 6 h.

**Werdykt: OK Z UWAGAMI.** Testy 756/0, panele ≤ 0,25 s, Grafana 178/512 MiB – zgodnie z K6-U1…U3. Dashboardy pokazują to, co miały: znacznik SYMULACJA w tabeli, legendach i nazwach; rosnący trend drgań 1,1 → ok. 3,3 mm/s w 90 dniach z rytmem tygodniowym (ok. 900 minut pracy w dni robocze, mniej w soboty, 0 w niedziele); drgania z przerwą w postoju; nagrzewanie i stygnięcie łożyska; 901 minut pracy dziś (06:00–21:00). Poprawki V1–V6 – mały krok **k6b** (tylko generator Grafany), bez nowego demo: zrzuty końcowe z produkcji w k7.

## Uwagi wizualne (do k6b)

| Id | Gdzie | Problem | Poprawka |
| --- | --- | --- | --- |
| V1 | Pompa: „Trend drgań z minut pracy (ostatnie 90 dni)” | **Własny zakres 90 dni nie działa**: przy 24 h panel pokazuje jeden punkt i jeden słupek, przy 6 h „Dane poza zakresem czasu”. Poprawnie tylko przy zakresie pulpitu 90 dni | panel zawsze 90 dni od „teraz” niezależnie od zakresu pulpitu (jak k7d etapu 2: zakres w SQL + `timeFrom`/nadpisanie osi tak, by oś też była 90 dni); test harnessu przy 6 h, 24 h, 7 d i zakresie bezwzględnym |
| V2 | Flota: „Świeżość danych w czasie” (7 dni) | urządzenia sim **przed pierwszymi danymi** świecą na czerwono „Brak danych” – wygląda jak awaria | przed pierwszym odczytem urządzenia (albo przed `meter_anchor`) – brak stanu (przezroczyste), czerwień tylko po pierwszych danych |
| V3 | Flota: „Udział w energii zakresu” i „Świeżość danych w czasie” | ucięta pierwsza litera etykiety: „gregat chłodniczy (SYMULACJA)” | szerokość etykiet osi / `axisWidth` albo krótsza nazwa w legendzie, bez ucinania |
| V4 | Flota i Pompa: panel „Dane symulowane” na górze | tekst ucięty (panel za niski, widać pół linii i pasek przewijania) | wyższy panel albo krótszy tekst w 1–2 zdaniach, bez przewijania |
| V5 | Pompa: kafelek „Obroty teraz” i oś „Obroty” | „3K rd/m” – skrót tysięcy i nieczytelna jednostka | pełna liczba bez skrótu (np. „2 950”), jednostka opisowa „obr/min” (jednostka danych zostaje `rpm`, zmienia się tylko wyświetlanie) |
| V6 | Flota: tabela „Liczniki floty”, kolumna „Energia od północy” | Finder w Wh, liczniki sim w kWh – trudno porównać w jednej kolumnie | jedna jednostka w kolumnie (kWh, 2–3 miejsca po przecinku) |

## Uwagi do k7

- W demo Finder ma „Brak danych”, bo stos testowy nie ma prawdziwego collectora – stan Findera ocenimy na produkcji.
- Zrzuty końcowe (8 z planu, po k6b) robimy z produkcji w k7, nie z demo.

## Zdarzenie 27.11 (do wyjaśnienia, nie blokuje)

IPC stracił sieć ok. 17–20:49 (dziennik: NetworkManager podniósł „Wired connection 2” o 20:49:31, nowa dzierżawa DHCP **192.168.0.215** zamiast .213); kontenery produkcji „Up 2 days” (bez restartu), uśpienia nie było (`journalctl`). Grzegorz zablokował usypianie (`systemctl mask sleep/suspend/hibernate/hybrid-sleep`). Do zrobienia: przyczyna utraty sieci (NetworkManager, aktualizacje automatyczne – „System restart required”), luka w danych real (okno w `data_windows`), rezerwacja DHCP adresu IPC w routerze.
