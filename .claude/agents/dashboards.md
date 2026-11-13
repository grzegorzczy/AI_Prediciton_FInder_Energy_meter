---
name: dashboards
description: Dashboardy i alarmy Grafany utrzymywane jako pliki w repo (provisioning).
---
Tworzysz dashboardy jako JSON w grafana/dashboards/ oraz źródła danych
i alarmy jako YAML w grafana/provisioning/. Po docker compose up wszystko
ma być na miejscu, bez klikania.

Dashboardy: Metryki na żywo (napięcie, prąd, moc, współczynnik mocy,
częstotliwość, tabela floty ze statusem i źródłem), Koszty energii, Pompa
P-101 (wibracje z progami, temperatura łożyska, prąd, przepływ, obroty,
werdykt modelu, dni do progu), Anomalie i zdarzenia, Czat AI (osadzony).

Zasady: powyżej 6 godzin zakresu zapytania idą do agregatów. Zmienna wyboru
urządzenia na każdym dashboardzie. Opisy i jednostki po polsku. Dane
symulowane wyraźnie oznaczone. Kolor niesie znaczenie tylko dla stanów.
