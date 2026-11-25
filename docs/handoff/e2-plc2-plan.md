# E2-PLC2 – nowe dane z licznika: plan (architekt)

Data: 2026-11-25. Status: **DO AKCEPTACJI GRZEGORZA**. Strona PLC: architekt + Grzegorz (ręcznie w CODESYS).
Strona aplikacji: Claude Code (osobny plan po akceptacji tego).

## Co dodajemy

| Wielkość | Rejestr Findera | Skąd w PLC | Uwagi |
| --- | --- | --- | --- |
| Energia bierna ↑ n2 (mantysa, wykładnik) | 30408–30409, 30402 | **już czytane** (`awFinder1EnergyMant[2..3]`, `awFinder1EnergyExp[1]`) | tylko mapowanie na TCP |
| Energia bierna ↓ n4 | 30412–30413, 30404 | **już czytane** (`[6..7]`, `[3]`) | tylko mapowanie |
| Kąt U1–I1 | 32570–32571 | nowy kanał `chQuality` | REAL, ° |
| THD prądu I1 | 32588–32589 | `chQuality` | REAL, % |
| THD napięcia U1 | 32594–32595 | `chQuality` | REAL, % |
| Temperatura wewnętrzna | 32658–32659 | nowy kanał `chTemp` | REAL, °C |
| Czas pracy | 32480–32481 | nowy kanał `chRunTime` | REAL, s (typ do potwierdzenia na liczniku) |

**Nie w tym kroku:** liczniki o podwyższonej rozdzielczości (30462–30485). Sprzeczność w dokumentacji Findera
i brak miejsca w bloku (24 rejestry) – etap 4, wtedy decyzja o układzie bloku.

## Nowe kanały RTU (wariant B – istniejące kanały bez zmian)

| Kanał | Offset (CODESYS) | Liczba | Cykl | Zakres |
| --- | --- | --- | --- | --- |
| `chQuality` | `16#0A0A` (2570) | 26 | 1000 ms | 32570–32595 |
| `chTemp` | `16#0A62` (2658) | 2 | 10 s | 32658–32659 |
| `chRunTime` | `16#09B0` (2480) | 2 | 10 s | 32480–32481 |

Wszystkie FC04, Keep last value. Wariant A (jeden kanał 2480 × 116) oszczędza transakcje, ale przestawia
istniejące tablice – odrzucony, bo ruszałby działające pomiary. Obciążenie RS485: +1 transakcja/s
(26 rejestrów ≈ 35 ms przy 19200 8N2).

## Mapa Modbus TCP v2 (`MAP_VERSION` = 2)

Rejestry 0–43 bez zmian. Zajmujemy zarezerwowane 44–59 (offsety bloku 34–49) – blok pełny.

| Rejestr | Offset | Nazwa | Typ | Jednostka |
| --- | --- | --- | --- | --- |
| 44–45 | 34 | `reactive_import_mant` | DINT | n2: varh = mant × 10^exp |
| 46 | 36 | `reactive_import_exp` | INT | |
| 47–48 | 37 | `reactive_export_mant` | DINT | n4 |
| 49 | 39 | `reactive_export_exp` | INT | |
| 50–51 | 40 | `thd_voltage` | REAL | % |
| 52–53 | 42 | `thd_current` | REAL | % |
| 54–55 | 44 | `phase_angle` | REAL | ° |
| 56–57 | 46 | `meter_temperature` | REAL | °C |
| 58–59 | 48 | `run_time` | REAL | s |

Zasada ważności bez zmian: `status ≠ 0` → wartości zamrożone, nie zapisujemy.

## Kolejność (żeby nie zgubić danych)

1. **PLC-1 (Grzegorz + architekt):** trzy kanały, tablice w `GVL_Meter`, download. Mapa TCP bez zmian (v1).
   Sprawdzenie online: wartości wiarygodne? Temperatura vs. zdrowy rozsądek, czas pracy rośnie o 1/s,
   THD U kilka %, kąt zgodny z PF 0,37 (|kąt| ok. 68°; znak wg konwencji Findera – do odczytania, nie zakładamy). Zrzut podglądu online.
   Przerwa ok. 18 s → okno `plc_program_download`.
2. **Claude Code:** collector i ingest obsługują mapę v1 **i** v2 (v2 → dodatkowe metryki), `devices.yaml`,
   testy, wdrożenie **przed** PLC-2. Bez tego collector po zmianie PLC zgłosi `link_status 3` (zła mapa).
3. **PLC-2:** `FB_EnergyMeter` (nowe wyjścia), `PRG_ModbusTcpMap` (v2), download, `mbpoll` 0–59.
4. **Claude Code:** sprawdzenie danych w bazie, panele (Jakość energii: THD U/I, kąt; Energia: energia bierna;
   Diagnostyka: temperatura licznika, czas pracy), raport. Architekt aktualizuje `docs/modbus-map.md` do v2.

Przy okazji pracy w CODESYS (E2-PLC1, tylko zbieranie faktów): zdjęcie przewodu RS485 i zacisków A/SC/B,
typ przewodu, co jeszcze jest w pobliżu; czy CODESYS był online w godzinach serii epizodów.

## Ryzyka

- Finder zastrzega, że tabela rejestrów zależy od firmware – dlatego krok 1 sprawdza wartości przed mapowaniem.
- THD prądu przy 80 mA może być niewiarygodne (mały prąd względem zakresu 40 A) – zapisujemy, opisujemy w panelu.
- Czas pracy jako REAL traci rozdzielczość 1 s po ok. 194 dniach (2^24 s) – akceptowalne; jeśli licznik
  ma wersję całkowitą, rozważymy w etapie 4.

## Wyniki PLC-1 (25.11.2026, ok. 09:15 lokalnie; zrzut `docs/images/etap2/08-plc2-codesys-nowe-kanaly.png`)

Grzegorz: kanały dodane, download, Application [run]. Surowe słowa z `GVL_Meter` zdekodowane (REAL, starsze słowo pierwsze):

| Rejestr | Wartość | Ocena |
| --- | --- | --- |
| 32570 kąt U1–I1 | **−50,58°** | wiarygodny, patrz niżej; 32572–32576 to ta sama wartość (kolejne fazy/suma w liczniku jednofazowym) |
| 32584 | 49,98 | nieopisany w dokumencie 01 (wygląda na częstotliwość) – nie używamy |
| 32588 THD I1 | **140,22 %** | wiarygodny dla zasilacza impulsowego (prąd silnie odkształcony); 32590–32592 ta sama wartość |
| 32594 THD U1 | **2,34 %** | wiarygodny |
| 32658 temperatura | **30,2 °C** | wiarygodny |
| 32480 czas pracy | **1 256 171 s** (ok. 14,5 doby) | wiarygodny co do rzędu; przyrost do potwierdzenia (dwa odczyty) |

**Kontrola spójności:** PF = cos φ × 1/√(1 + THD_I²) = cos(50,58°) × 1/√(1 + 1,4022²) = 0,635 × 0,581 = **0,369**,
a licznik podaje PF 0,37. Kąt i THD prądu są więc zgodne z mocami. Znak ujemny kąta = pojemnościowy, zgodny z Q < 0.

**Wniosek dla paneli:** przy THD prądu 140 % współczynnik mocy PF (0,37) to **nie** cos φ (0,64).
Panel „Współczynnik mocy (cos φ)” w Jakości energii ma się nazywać „Współczynnik mocy PF”,
a cos φ = cos(kąt) dochodzi jako osobna seria po mapie v2.

Mapa v2 bez zmian względem planu. Następny krok: Claude Code – obsługa mapy v1 i v2 (krok 2).
