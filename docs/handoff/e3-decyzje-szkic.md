# Etap 3 – Symulator: decyzje do podjęcia (szkic architekta)

Data: 2026-11-25. Status: **SZKIC – przygotowanie, etap 3 nie jest rozpoczęty.** Claude Code dostaje ten dokument
dopiero po akceptacji `etap-2.md` przez Grzegorza; wtedy pisze plan `e3-k0-plan.md`.

## Co mówi plan (docs/plan.md, dokument projektu 03)

- **Co powstaje:** 4 wirtualne liczniki z cyklem praca / bieg jałowy / postój według zmian oraz pompa P-101
  (wibracje RMS, temperatura łożyska, prąd silnika, przepływ, obroty) ze 120-dniową degradacją łożyska.
- **Tryby:** na żywo, przyspieszony, jednorazowe wypełnienie historii. Ziarno losowe w konfiguracji.
- **Gotowe, gdy:** flota 5 urządzeń ze źródłem real/sim; rosnące wibracje pompy.
- **Architektura:** symulator publikuje do tego samego MQTT (`source = "sim"`), osobny kontener z `mem_limit`,
  urządzenia w `config/devices.yaml`; agregat `pump_1m`.

## Sprostowanie

Zapis „drugi licznik w etapie 3 wymaga nowej mapy Modbus” jest nieaktualny: wirtualne liczniki publikują prosto
do MQTT, z pominięciem PLC. Powiększenie `awTcpInputRegs` i nowa wersja mapy są potrzebne dopiero przy drugim
**prawdziwym** liczniku (etap 7 lub wcześniej, jeśli Grzegorz podłączy drugi Finder).

## Decyzje

| Id | Pytanie | Propozycja architekta | Dlaczego |
| --- | --- | --- | --- |
| S1 | Jakie maszyny udają 4 wirtualne liczniki? | Zakład spożywczy: **piec / pasteryzator**, **agregat chłodniczy**, **mieszalnik**, **pakowaczka** (moce znamionowe do ustalenia, rząd kilku–kilkunastu kW) | Bliskie klientom Grzegorza; różne profile: praca ciągła z regulacją (piec), cykle załącz/wyłącz całą dobę (chłodzenie), krótkie cykle (mieszalnik), praca zmianowa z biegiem jałowym (pakowaczka) |
| S2 | Kalendarz pracy | 2 zmiany pon–pt 6:00–22:00, sobota 6:00–14:00, niedziela postój; chłodzenie 24/7 | Daje pobór poza pracą i bieg jałowy do etapu 4 |
| S3 | Jakie metryki mają wirtualne liczniki? | **Zestaw skrócony:** P, Q, U, I, PF, energia (licznik rosnący); bez THD, kąta, temperatury | Mniej wierszy; etap 4 potrzebuje mocy i energii, nie jakości |
| S4 | Częstotliwość danych na żywo | **co 1 s** jak licznik prawdziwy | Te same panele i agregaty; ok. 30 wierszy/s więcej (łącznie ok. 50/s) – w zasięgu bazy (test ok. 1 360/s) |
| S5 | Model degradacji pompy | 120 dni od stanu „dobrego” do przekroczenia progu alarmowego wibracji; przebieg wolny na początku, przyspieszający pod koniec; temperatura łożyska rośnie razem z wibracjami; wartości progów – w `docs/decisions.md` (etap 5) | Klasyczny obraz zużycia łożyska; daje trend do progu dla etapu 5 |
| S6 | Gdzie na osi 120 dni zaczynamy „na żywo”? | Historia 120 dni kończy się „teraz” na ok. 70 % drogi do alarmu; dalsza degradacja na żywo; tryb przyspieszony do pokazów | Na demo od razu widać trend i szacowaną liczbę dni do progu |
| S7 | Jak wgrać historię? | **Przez MQTT, z rozdzielczością 1 min** (nie 1 s): ok. 120 × 1 440 × ok. 40 metryk ≈ 7 mln wiadomości, kilka godzin; dane na żywo co 1 s | Zostajemy w architekturze (wszystko przez MQTT). Historia 1 s to ok. 670 mln wiadomości – ponad 5 dni |
| S8 | Konflikt: historia 120 dni a retencja surowych danych 90 dni | Surowe dane starsze niż 90 dni zostaną skasowane, ale agregaty (`energy_1m`, `pump_1m`, `energy_1h`) trzymają rok – **po wgraniu historii ręczne odświeżenie agregatów przed zadziałaniem retencji**. Alternatywa: historia tylko 85 dni | Analityka (etap 5) potrzebuje całej krzywej degradacji; agregaty wystarczą |
| S9 | Grafana | Nowy dashboard „Flota” (5 urządzeń: moc, energia, stan, źródło real/sim) i „Pompa P-101” (wibracje, temperatura łożyska, prąd, przepływ, obroty); przełącznik `$device` obejmuje urządzenia sim | Kryterium etapu: flota 5 urządzeń, rosnące wibracje |
| S10 | Oznaczenie danych symulowanych | `source = "sim"` w każdym wierszu, w Grafanie wyraźny znacznik „SYMULACJA” przy urządzeniach sim | Na demo nikt nie pomyli danych prawdziwych z symulowanymi |
| S11 | Zasoby | kontener `aip-simulator`, `mem_limit` 128 MiB, ziarno losowe w `devices.yaml`, testy deterministyczne | Zasada twarda 3 i 4 |

## Pytania otwarte do Grzegorza

1. S1: czy taki zestaw maszyn Ci pasuje, czy wolisz inne (np. z konkretnego zakładu, który znasz)? Jakie moce znamionowe?
2. S2: kalendarz zmian.
3. S6/S7/S8: zgoda na historię 1 min przez MQTT i odświeżenie agregatów.
4. Czy wirtualne liczniki mają być „w tej samej linii” (`zaklad1/linia1`), czy w osobnej linii (`zaklad1/linia2`)?
