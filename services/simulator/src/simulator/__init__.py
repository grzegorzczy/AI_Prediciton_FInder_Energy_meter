"""Symulator etapu 3: wirtualne liczniki energii i pompa z degradacją łożyska.

Każda wartość jest czystą, deterministyczną funkcją f(chwila, ziarno, config) – bez stanu między próbkami. Ten sam kod
liczy dane na żywo (k3) i historię (k5); powtórka daje identyczne wartości. Parametry modeli są w config/devices.yaml
(sekcja `simulator`); w kodzie nie ma danych urządzeń (reguła 3).
"""

# Wersja modelu (K2R-D3, K3-U1): podbić przy KAŻDEJ zmianie kodu, która zmienia wartości (moce, szum, kalendarz, pompa).
# Wchodzi do klucza pamięci sum dobowych; test wzorców (tests/simulator/test_sim_model_version.py) jest czerwony, gdy wynik
# modelu zmieni się bez podbicia tej stałej.
MODEL_VERSION = "2026-11-26.1"
