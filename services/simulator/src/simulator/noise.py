"""Szum deterministyczny: funkcja skrótu (ziarno, urządzenie, sekunda), a nie generator z pamięcią.

Wbudowany `hash()` zależy od procesu (PYTHONHASHSEED), dlatego blake2b z hashlib. Jedno wywołanie skrótu daje cztery
liczby U(0,1) dla urządzenia w danej sekundzie (szybciej niż osobny skrót na każdą metrykę).
"""
from __future__ import annotations

import math
from functools import lru_cache
from hashlib import blake2b

_SCALE = 1.0 / 4294967296.0          # 2**32
_PERIOD_RATIOS = (1.0, 0.41, 0.17)    # trzy sinusoidy o niewspółmiernych okresach: wolne wahania bez widocznej powtarzalności


def uniforms(seed: int, key: str, t: int) -> tuple[float, float, float, float]:
    """Cztery liczby z przedziału [0, 1) dla klucza (urządzenia) w sekundzie `t`; ta sama trójka wejść = te same liczby."""
    digest = blake2b(f"{seed}|{key}|{t}".encode(), digest_size=16).digest()
    return (int.from_bytes(digest[0:4], "big") * _SCALE, int.from_bytes(digest[4:8], "big") * _SCALE,
            int.from_bytes(digest[8:12], "big") * _SCALE, int.from_bytes(digest[12:16], "big") * _SCALE)


def normal_pair(u1: float, u2: float) -> tuple[float, float]:
    """Dwie liczby N(0, 1) z dwóch U(0, 1) (Box–Muller); 1 - u1 > 0, więc logarytm jest skończony."""
    radius = math.sqrt(-2.0 * math.log(1.0 - u1))
    angle = 2.0 * math.pi * u2
    return radius * math.cos(angle), radius * math.sin(angle)


@lru_cache(maxsize=1024)
def _phases(seed: int, key: str) -> tuple[float, float, float]:
    u = uniforms(seed, key + "|phase", 0)
    return (2.0 * math.pi * u[0], 2.0 * math.pi * u[1], 2.0 * math.pi * u[2])


def slow(seed: int, key: str, t: float, period_s: float) -> float:
    """Wolne wahanie w [-1, 1]: średnia trzech sinusoid o okresach period_s × (1; 0,41; 0,17) i fazach z ziarna."""
    phases = _phases(seed, key)
    total = 0.0
    for ratio, phase in zip(_PERIOD_RATIOS, phases):
        total += math.sin(2.0 * math.pi * t / (period_s * ratio) + phase)
    return total / 3.0


@lru_cache(maxsize=1024)
def offset(seed: int, key: str, span: int) -> int:
    """Stałe przesunięcie fazy cyklu urządzenia w [0, span) – urządzenia nie startują cykli w tej samej sekundzie."""
    return int(uniforms(seed, key + "|offset", 0)[0] * span)
