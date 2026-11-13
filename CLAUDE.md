# Projekt: lokalna platforma monitoringu energii i wykrywania anomalii (edge)

## Cel
Demo, które ma dać się rozwinąć w produkt dla zakładów produkcyjnych:
zbieranie danych z PLC, dashboardy, koszty energii, wykrywanie anomalii,
szacowanie czasu do przekroczenia progu, czat AI po polsku, alarmy, raporty.
Wszystko działa lokalnie, bez internetu. Chmura jest opcją, domyślnie wyłączoną.

## Sprzęt
- Komputer przemysłowy: i5-10210U, 8 GB RAM, 128 GB dysku, Ubuntu, bez GPU.
- PLC: JUMO variTRON 300 (CODESYS), serwer Modbus TCP na porcie 502.
- Licznik Finder 7M.24.8.230.0210, Modbus RTU po RS485, podpięty do PLC.
  Komputer nie rozmawia z licznikiem bezpośrednio.
- Czujniki drgań i temperatury: na razie symulowane.

## Architektura (nie zmieniaj bez mojej zgody)
PLC (Modbus TCP) -> collector -> MQTT (Mosquitto) -> ingest -> TimescaleDB
-> Grafana / analytics / chat / raporty. Symulator publikuje do tego samego
MQTT. Temat: zaklad/linia/urzadzenie/metryka, ładunek JSON
{ts, value, unit, source}; source to "real" albo "sim".
Usługi: Python 3.12, każda w osobnym kontenerze, Docker Compose.
Baza: measurements (hypertable, kompresja po 1 dniu, retencja 90 dni),
agregaty ciągłe energy_1m, energy_1h, pump_1m; tabele devices,
machine_states, anomaly_scores, events, tariffs, chat_log.
Model lokalny: Ollama. Model w chmurze: za wspólnym interfejsem LLMProvider.
Kontrakt z PLC: docs/modbus-map.md. Nie zmieniaj go, zgłoś potrzebę zmiany.

## Zasady twarde
1. Do PLC nigdy nie piszemy. Collector tylko czyta rejestry.
2. Budżet 8 GB RAM: każdy kontener ma mem_limit; podawaj zmierzone zużycie.
3. Żadnych danych urządzeń w kodzie: wszystko w config/devices.yaml.
4. Czat łączy się z bazą kontem tylko do odczytu, z limitem czasu zapytania.
5. Tryb chmurowy wysyła wyłącznie pytanie, schemat i wynik zapytania;
   każde użycie chmury trafia do chat_log.
6. Sekrety tylko w .env, którego nie ma w repo.
7. Nie zgaduj faktów sprzętowych. Gdy czegoś brakuje, zatrzymaj się i zapytaj.
8. Nie nazywaj wykrywania anomalii "przewidywaniem awarii". Prognozę podajemy
   jako "szacowana liczba dni do przekroczenia progu" z przedziałem niepewności.

## Sposób pracy
- Etapy 0-7 z docs/plan.md, jeden naraz. Każdy etap dzielisz na kroki;
  krok kończy się czymś sprawdzalnym (test, commit).
- Współpraca z architektem (czat projektu claude.ai) wg docs/workflow.md:
  plan i raport każdego kroku zapisujesz w docs/handoff/, zatrzymujesz się
  i czekasz na review architekta oraz moje "ok". Nie zaczynasz kolejnego
  kroku sam.
- Przed kodem: krótki plan etapu i lista plików. Czekasz na moje "ok".
- Po kodzie: testy pytest, potem agent reviewer, potem checklista akceptacji
  w docs/stages/etap-N.md z poleceniami, które sam wykonam.
- Tłumacz mi decyzje: chcę rozumieć, co i dlaczego powstaje.
- Interfejs i odpowiedzi czatu po polsku. Kod, nazwy i commity po angielsku.

## Struktura repo
plc/ (eksport ST, dokumentacja licznika)   services/collector, ingest,
simulator, analytics, chat   grafana/ (provisioning)   db/ (migracje SQL)
config/   docs/   tests/   docker-compose.yml
