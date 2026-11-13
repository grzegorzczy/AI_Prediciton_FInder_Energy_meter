# Licznik Finder 7M.24.8.230.0210 – Modbus RTU

Stan na 13.11.2026. Źródło: oficjalny dokument Findera „Modbus communication protocol 7M24 – 7M38" (v2, 30.06.2021):
https://cdn.findernet.com/app/uploads/2021/09/20090052/Modbus-7M24-7M38_v2_30062021.pdf
Instrukcja licznika: https://cdn.findernet.com/app/uploads/IB7M24IT.pdf
Przykład Findera (OPTA w CODESYS jako brama RTU → TCP, ten sam licznik): https://opta.findernet.com/en/tutorial/serie7m-modbus-rtu

Finder zastrzega, że tabela rejestrów może się zmienić z wersją firmware. Wszystko poniżej potwierdzamy na żywym liczniku w etapie 1.

## Urządzenie

- Typ: 7M.24.8.230.0210, jednofazowy, 5(40) A, 230 V, MID, RS485 Modbus RTU + NFC
- Nr seryjny z tabliczki: F0183363
- Zaciski komunikacji: A, SC, B

## Parametry transmisji

| Parametr | Fabrycznie wg Findera | U nas (podane przez Grzegorza) |
| --- | --- | --- |
| Prędkość | 19200 bit/s (zakres 1200–115200) | 19200 |
| Ramka | 8 bitów danych, bez parzystości, **2 bity stopu** (8N2) | bez parzystości; bity stopu DO POTWIERDZENIA |
| Adres slave | **33** (0x21) | DO POTWIERDZENIA |
| Port w PLC | – | COM 2 w variTRON 300 |

Uwaga: jeśli w CODESYS port jest ustawiony na 8N1, a licznik ma fabryczne 8N2, komunikacja może działać niestabilnie albo wcale. Ustaw 2 bity stopu w PLC albo zmień ustawienie licznika.

## Konwencja adresowania

- Pomiary: rejestry wejściowe, funkcja 04. Ustawienia: rejestry holding, funkcje 03 / 06 / 16.
- Offset w ramce = numer rejestru − 30000 (wejściowe) lub − 40000 (holding). Przykład: 30107 → offset 107 (0x6B).
- Wartości 32-bitowe zajmują 2 rejestry; w przykładach z dokumentu starsze słowo jest pierwsze (big-endian). Dokument nie mówi tego wprost → sprawdzić na liczniku.
- Odświeżanie: pomiary 30105–30190 co 1 s, liczniki energii 30406–30441 co 40 ms.

## Zalecany zestaw odczytu: blok IEEE 754 (T_float, gotowe REAL)

| Wielkość | Rejestry | Offset (dec) | Jednostka |
| --- | --- | --- | --- |
| Moc czynna Pt | 32490–32491 | 2490 | W |
| Moc bierna Qt | 32492–32493 | 2492 | var |
| Moc pozorna St | 32494–32495 | 2494 | VA |
| Współczynnik mocy PFt | 32496–32497 | 2496 | – |
| Częstotliwość | 32498–32499 | 2498 | Hz |
| Napięcie U1 | 32500–32501 | 2500 | V |
| Prąd I1 | 32516–32517 | 2516 | A |
| Kąt U1–I1 | 32570–32571 | 2570 | ° |
| THD prądu I1 | 32588–32589 | 2588 | % |
| THD napięcia U1 | 32594–32595 | 2594 | % |
| Temperatura wewnętrzna | 32658–32659 | 2658 | °C |
| Czas pracy | 32480–32481 | 2480 | s |

Propozycja kanałów w PLC: (1) FC04, offset 2490, 12 rejestrów → Pt, Qt, St, PFt, f, U1 w jednym zapytaniu; (2) FC04, offset 2516, 2 rejestry → I1; (3) energia jak niżej.

## Energia

Dokładny odczyt (zalecany dla kWh): wartość = mantysa × 10^wykładnik.

| Licznik | Mantysa (T3, int32) | Wykładnik (T2, int16) | Jednostka |
| --- | --- | --- | --- |
| n1 | 30406–30407 | 30401 | Wh |
| n2 | 30408–30409 | 30402 | varh |
| n3 | 30410–30411 | 30403 | Wh |
| n4 | 30412–30413 | 30404 | varh |

To samo jako float: n1–n4 w 32752–32759 (oraz 32638–32645). Float traci rozdzielczość przy dużych stanach licznika, dlatego do rozliczeń bierzemy mantysę i wykładnik.

DO POTWIERDZENIA na liczniku: który z liczników n1 / n3 to energia pobrana, a który oddana (licznik jest dwukierunkowy; konfiguracja liczników siedzi w rejestrach holding od 40421).

## Te same pomiary w kodowaniu Findera (zapas, gdyby blok float nie odpowiadał)

| Wielkość | Rejestry | Typ |
| --- | --- | --- |
| Częstotliwość | 30105–30106 | T5 |
| U1 | 30107–30108 | T5 |
| I1 | 30126–30127 | T5 |
| Pt | 30140–30141 | T6 |
| Qt | 30148–30149 | T6 |
| St | 30156–30157 | T5 |
| PFt | 30164–30165 | T7 |
| Flagi ważności fazy | 30101 | T1 (bit 0 = faza 1 nieważna) |

Typy: T1 uint16; T2 int16; T3 int32; T5 – najstarszy bajt to wykładnik dziesiętny ze znakiem, młodsze 24 bity to mantysa bez znaku; T6 – jak T5, mantysa ze znakiem; T7 – bajt 1 import/eksport (00/FF), bajt 2 ind./poj. (00/FF), młodsze 16 bitów to wartość z 4 miejscami po przecinku; T16 uint16 ÷ 100; T17 int16 ÷ 100.

## Identyfikacja (dobry pierwszy test łączności)

| Pozycja | Rejestry | Typ |
| --- | --- | --- |
| Model | 30001–30008 | tekst ASCII, 2 znaki na rejestr |
| Numer seryjny | 30009–30012 | tekst ASCII |
| Grupa urządzeń | 39000 | T1, wartość 5 = seria 7M |

## Ustawienia portu RS485 (holding) – tylko do odczytu kontrolnego, nie zapisujemy z aplikacji

| Ustawienie | Rejestr | Wartości |
| --- | --- | --- |
| Adres Modbus | 40202 | 1–247 |
| Prędkość | 40203 | 0=1200, 1=2400, 2=4800, 3=9600, 4=19200, 5=38400, 6=57600, 7=115200 |
| Bity stopu | 40204 | 0 = 1 bit, 1 = 2 bity |
| Parzystość | 40205 | 0 = brak, 1 = nieparzysta, 2 = parzysta |

## Znane nieścisłości w dokumencie Findera

- Przykład odczytu napięcia w dokumencie podaje 229,34 V, a bajty z przykładu dają 229,00 V.
- Wstęp umieszcza liczniki o podwyższonej rozdzielczości w 30426–30441, tabela 7M.24 w 30462–30485.
- Dokument nie podaje maksymalnej liczby rejestrów w jednym zapytaniu (jest tylko rejestr 30099 z tą informacją) → odczytać 30099 w etapie 1.
