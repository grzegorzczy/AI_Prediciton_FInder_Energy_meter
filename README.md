# Lokalna platforma monitoringu energii i wykrywania anomalii

Platforma brzegowa (edge) dla zakładów produkcyjnych: zbiera dane z PLC, pokazuje
dashboardy na żywo, liczy koszty energii i bieg jałowy, wykrywa anomalie, szacuje
liczbę dni do przekroczenia progu, odpowiada na pytania w czacie AI po polsku.
Działa w całości lokalnie, bez internetu. Model w chmurze to opcja, domyślnie wyłączona.

Najpierw demo na biurku, potem produkt.

## Sprzęt demo

- Komputer przemysłowy C4350Z-HD: i5-10210U, 16 GB RAM (2x8 GB DDR4), dysk NVMe 1 TB, Ubuntu, bez GPU
- PLC JUMO variTRON 300 (CODESYS V3.5) – master Modbus RTU i serwer Modbus TCP
- Licznik energii Finder 7M.24.8.230.0210 (RS485, Modbus RTU), podłączony do PLC
- Czujniki drgań i temperatury łożysk: na razie symulowane

## Architektura

```
Finder 7M.24 --RTU/RS485--> variTRON 300 --Modbus TCP:502--> collector
                                                               |
symulator (4 liczniki + pompa P-101) ---------------------> MQTT (Mosquitto)
                                                               |
                                                            ingest
                                                               |
                                                          TimescaleDB
                                                               |
                                Grafana / analytics / czat AI / raporty
```

Komputer nigdy nie zapisuje niczego do PLC ani do licznika – tylko czyta.

## Struktura repozytorium

| Katalog | Zawartość |
| --- | --- |
| `plc/` | eksport kodu ST z CODESYS (`src/`), dokumentacja licznika (`docs/`) |
| `services/` | usługi w Pythonie 3.12: collector, ingest, simulator, analytics, chat |
| `grafana/` | dashboardy i provisioning jako pliki |
| `db/migrations/` | migracje SQL TimescaleDB |
| `config/` | `devices.yaml` – jedyne miejsce z danymi urządzeń (powstanie w etapie 2) |
| `docs/` | plan etapów, model danych, mapa Modbus, decyzje, checklisty etapów |
| `tests/` | testy pytest (bez sprzętu) i pytania testowe czatu |
| `.claude/agents/` | agenci Claude Code: data-platform, analytics, ai-chat, dashboards, reviewer |

## Dokumenty

- [`CLAUDE.md`](CLAUDE.md) – zasady pracy i zasady twarde
- [`docs/plan.md`](docs/plan.md) – etapy 0–7 z kryteriami „gotowe, gdy”
- [`docs/data-model.md`](docs/data-model.md) – schemat bazy (projekt wstępny)
- [`docs/modbus-map.md`](docs/modbus-map.md) – kontrakt PLC ↔ collector (etap 1)
- [`plc/docs/finder-7M24-modbus.md`](plc/docs/finder-7M24-modbus.md) – rejestry licznika
- `docs/decisions.md` – taryfa, zmiany, progi (powstanie przed etapem 4)
- `docs/stages/etap-N.md` – checklisty akceptacji po każdym etapie

## Stan

Etap 0: szkielet repozytorium gotowy. Kodu usług jeszcze nie ma – zaczyna się w etapie 2.

## Uruchomienie

Opis pojawi się w etapie 2 (`docker compose up -d` na komputerze z Ubuntu,
po skopiowaniu `.env.example` do `.env`).
