# Plan etapów 0–7

Źródło: dokument projektu `02-plan-i-prompty.md` (13.11.2026). Jeden etap naraz.
Etap jest skończony dopiero, gdy spełnione jest kryterium „gotowe, gdy” i Grzegorz
przeszedł checklistę `docs/stages/etap-N.md` na sprzęcie.

| Etap | Co powstaje | Gotowe, gdy | Gdzie |
| --- | --- | --- | --- |
| 0. Przygotowanie | Repo, Docker na Ubuntu, stałe IP, SSH | `docker run hello-world` działa, komputer pinguje PLC | Czat + Claude Code |
| 1. PLC | Odczyt licznika po RTU, serwer Modbus TCP, mapa rejestrów TCP | `mbpoll` z komputera pokazuje ok. 230 V | Czat (MCP CODESYS) |
| 2. Kręgosłup danych | Mosquitto, TimescaleDB, Grafana, collector, ingest, dashboard na żywo | Wykresy odświeżają się na żywo; po restarcie wszystko wstaje samo | Claude Code |
| 3. Symulator | 4 wirtualne liczniki, pompa P-101 z degradacją łożyska | Flota 5 urządzeń ze źródłem real/sim; rosnące wibracje pompy | Claude Code |
| 4. Analityka energii | Stany off/idle/run, koszty, zmiany, pobór poza pracą | Koszt jednego dnia zgadza się z ręcznym wyliczeniem | Czat (decyzje) + Claude Code |
| 5. Anomalie i alarmy | Progi, Isolation Forest, trend do progu, alarmy | Alarm pojawia się przed czerwonym progiem na danych symulatora | Czat (decyzje) + Claude Code |
| 6. Czat AI | Ollama, narzędzia, zabezpieczony SQL, CSV, przełącznik chmury | Co najmniej 17 z 20 pytań testowych poprawnie lokalnie | Czat (pytania) + Claude Code |
| 7. Produkt | Logowanie, kopie, instalator, wiele zakładów, prawdziwe czujniki | Czysta instalacja na drugim komputerze w mniej niż godzinę | Oba |

## Zależności między etapami

- Etap 2 potrzebuje `docs/modbus-map.md` z etapu 1. Do tego czasu collector testujemy
  na lokalnym serwerze Modbus z pymodbus.
- Etapy 4 i 5 potrzebują `docs/decisions.md` (taryfa, zmiany, progi) z czatu
  „Decyzje – analityka i progi”.
- Etap 6 potrzebuje `tests/chat_questions.yaml` z czatu „Pytania testowe do czatu AI”.

## Stan

| Etap | Stan |
| --- | --- |
| 0 | W toku: repozytorium gotowe; przygotowanie Ubuntu zaplanowane |
| 1–7 | Nie rozpoczęte |
