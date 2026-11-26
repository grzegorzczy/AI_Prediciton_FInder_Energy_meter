"""Symulator etapu 3: wirtualne liczniki energii i pompa z degradacją łożyska.

Każda wartość jest czystą, deterministyczną funkcją f(chwila, ziarno, config) – bez stanu między próbkami. Ten sam kod
liczy dane na żywo (k3) i historię (k5); powtórka daje identyczne wartości. Parametry modeli są w config/devices.yaml
(sekcja `simulator`); w kodzie nie ma danych urządzeń (reguła 3).
"""
