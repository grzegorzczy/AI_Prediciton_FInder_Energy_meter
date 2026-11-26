# E3-k1 – review planu (architekt)

Data: 2026-11-26. Plan: `e3-k1-plan.md` (`c42dd0a`).

**Werdykt: OK – wykonuj.**

## Decyzje

1. **Katalog roboczy `~/ai-predykcja-dev` jako `git worktree`: TAK.** Dobre wychwycenie, że `git pull` w `~/ai-predykcja`
   podmieniłby `devices.yaml` czytany przez produkcję przy najbliższym restarcie. Zasady: testy tylko z worktree
   (projekt Compose `aip-test`), produkcja zostaje na `c299eaa` do k7; worktree nie montuje niczego do kontenerów
   produkcyjnych; w raporcie `git -C ~/ai-predykcja status` przed i po (czysto, ten sam commit). Opisać w `docs/ops`.
2. **Parametry modeli w k2, w k1 tylko tożsamość i metadane: TAK.**
3. **Nazwy bez „SYMULACJA”: TAK** – znacznik z `source` w Grafanie (k6).
4. **Finder `phases: 1`: TAK, w k1** – jedno źródło prawdy dla etapu 4 (liczniki trójfazowe sim vs jednofazowy
   Finder). Test regresji: w metadanych Findera różni się wyłącznie nowy klucz `phases`, wszystko inne identyczne;
   ścieżka zapisu pomiarów bez zmian. Trafi na produkcję dopiero w k7.

## Uwagi

- Test „obecny ingest ignoruje nieznane klucze” (kod sprzed zmiany + nowy config) – ważny, bo chroni produkcję
  przy przypadkowym restarcie z nowym plikiem; zostaw go w raporcie z wynikiem.
- `rated_kw` dla pompy to parametr symulacji (moc silnika), nie moc pobierana – opis w `docs/data-model.md`
  (pompa nie publikuje `active_power`, K0-D9).

## Dalej

Wykonanie k1 → pełne testy w worktree → `reviewer` → raport `e3-k1-report.md` → review.
