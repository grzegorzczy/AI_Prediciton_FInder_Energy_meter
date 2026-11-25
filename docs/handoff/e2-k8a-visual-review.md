# E2-k8a – review wizualny v4 (architekt)

Data: 2026-11-25, ok. 13:30 lokalnie (zakres „Ostatnia godzina”, po teście restartu komputera).
Zrzuty: `docs/images/etap2/03, 04, 04b, 04c, 05, 05b, 07b` oraz `11-grafana-diagnostyka-blad-brak-danych.png`.

**Werdykt: DO POPRAWY (jedna ważna usterka) – krok k8c przed częścią B.**

## Potwierdzone

- Licznik na żywo: nowe kafelki THD U 2,39 %, THD I 139,7 %, kąt −50,47°, temp. 30,3 °C; tabela z nowymi wielkościami.
- Jakość energii: PF 0,37 i cos φ 0,63 jako osobne serie; THD U, THD I, kąt z min/średnią/maks.
- Diagnostyka: temperatura i czas pracy licznika (14,72 d, rośnie liniowo); „Sekundy bez pomiaru mocy” w godzinie 13:00 = 37 s – zgodnie z luką po restarcie; adnotacja `ipc_reboot` na wszystkich wykresach.

## K8-V1 (ważna) – oś stanów pokazuje „Brak danych”, choć dane płyną

Na `11-grafana-diagnostyka-blad-brak-danych.png` panele „Łącze z PLC (link_status)” i „Stan licznika (meter_status)”
pokazują „Brak danych” od ok. 13:00 do końca zakresu (13:31), mimo że w tym czasie jest 20 wierszy/s, a „Kod błędu”
pokazuje „Brak błędu”. Luka po restarcie trwała 37 s (12:03:47–12:04:24 UTC).
Hipoteza (do sprawdzenia, nie wniosek): zapytanie wstawia znacznik „Brak danych” na początku luki i nie wstawia
powrotu do stanu po luce, gdy wartość stanu się nie zmieniła (0 → 0). To ten sam typ błędu co W-2 (brak wiersza
zamykającego). Poprawka + test na danych z luką bez zmiany stanu.

## K8-V2 – pełne nazwy w kafelkach (prośba Grzegorza)

Licznik na żywo: tytuły kafelków z pełną nazwą i symbolem, np. „Napięcie U”, „Prąd I”, „Moc czynna P”,
„Moc bierna Q”, „Moc pozorna S”, „Współczynnik mocy PF”, „Częstotliwość f”, „THD napięcia”, „THD prądu”,
„Kąt U–I”, „Temperatura licznika”. Bez obcinania tytułów (test jak w k7c).

## K8-V3 – „Wartości w oknie” znowu przewija się

Po dodaniu wielkości v2 tabela ma 11 wierszy i pasek przewijania (regresja W-8). Wysokość panelu dopasować
do liczby wierszy.

## K8-V4 – sprawdzić „Epizody błędu licznika dziś” = 36

O 06:10 kafelek pokazywał 14. Sprawdź zapytaniem liczbę przejść `meter_status` 0 → ≠ 0 od północy lokalnej
i godziny epizodów (nowe serie? E2-PLC1). Wynik do raportu – tylko opis.

## Dalej

k8c (bez osobnego planu): K8-V1…V4, testy, wdrożenie R-1, raport `e2-k8c-report.md`. Potem Grzegorz robi
zrzut 07 (Diagnostyka) i zrzuty Energii i profilu (06, 06b, 06c, energia bierna).

## Dopisek 13:40 – Energia i profil (zrzuty 06, 06b, 06c, zakres „Ostatnia godzina”)

Potwierdzone: profil godzinowy niebieski, puste godziny zaniku przezroczyste; porównania mocy z 2 miejscami
po przecinku; „Zużycie na dobę” jako słupki z etykietą „DD.MM (xx%)”; tabela kontrolna bez przewijania;
energia bierna z całki Q (godzina 13:00 ok. 5 varh przy Q ≈ −8,5 var – zgodne); spadki „Zużycia na minutę”
o 12:58 (wdrożenie) i 13:04 (restart) z widocznym spadkiem pokrycia – poprawne zachowanie.

**K8-V5 – „Energia bierna na dobę: całka i licznik”: zepsute etykiety osi.** Kategorie pokazują się jako
„23.1 varh”, „24.1 varh”, „25.1 varh” zamiast „23.11”, „24.11”, „25.11” – etykieta doby jest traktowana jak liczba
i dostaje jednostkę. Etykieta jako tekst (jak w „Zużyciu na dobę”), jednostka tylko na osi wartości.
Seria licznika (n2/n4) jest pusta, bo dane v2 są od 25.11 10:43 i n4 jeszcze nie zrobiło kroku – opisać to w panelu.

**K8-V6 – „Moc bazowa (5. percentyl nocą)” pokazuje „Brak danych” przy krótkich zakresach.** Przy zakresie
1 h nie ma nocy, więc panel jest pusty. Własny zakres liczony w SQL (jak w k7d), np. ostatnie 14 nocy, niezależnie
od zakresu pulpitu; w tytule „(ostatnie 14 nocy)”.

**K8-V7 – „Profil: godzina × dzień tygodnia”: poziomy pasek przewijania, kolumna „Niedz” ucięta.**
Wszystkie 7 dni ma się mieścić bez przewijania w poziomie (szerokości kolumn albo szerszy panel kosztem kafelka
„Moc maks. profilu”).

Drobne, bez zmian: „Zużycie na godzinę” przy zakresie 1 h pokazuje praktycznie jeden słupek – to wynika z zakresu.
