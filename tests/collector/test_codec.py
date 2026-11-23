"""Dekodowanie rejestrów wg docs/modbus-map.md (starsze słowo pierwsze, mantysa x 10^wykładnik)."""
from __future__ import annotations

import pytest

from collector.codec import Registers, RegisterError, round_real32
from fakes.modbus_plc import SAMPLE_METER, build_image


def regs(*words: int) -> Registers:
    return Registers(0, words)


def test_u32_has_older_word_first():
    assert regs(0x0001, 0x0002).u32(0) == 0x00010002 == 65538


def test_i32_is_signed():
    assert regs(0xFFFF, 0xFFFE).i32(0) == -2
    assert regs(0x0000, 0x0023).i32(0) == 35


def test_i16_is_signed():
    assert regs(0xFFFE).i16(0) == -2
    assert regs(0x0002).i16(0) == 2


def test_real32_from_two_words():
    # 240.4 V jako float32 = 0x43706666, starsze słowo pierwsze (wartość z mapy: U 240,4 V)
    assert round_real32(regs(0x4370, 0x6666).real32(0)) == 240.4


def test_real32_negative():
    assert round_real32(regs(0xC10B, 0x3333).real32(0)) == pytest.approx(-8.7, abs=1e-6)


def test_serial_ascii_from_map_example():
    # Z mapy: rejestry 40-43 = 4630 3138 3333 3633 -> "F0183363" (2 znaki na rejestr, starszy bajt pierwszy)
    assert regs(0x4630, 0x3138, 0x3333, 0x3633).ascii(0, 4) == "F0183363"


def test_ascii_strips_trailing_nul_and_spaces():
    assert regs(0x4142, 0x4300, 0x0000).ascii(0, 3) == "ABC"
    assert regs(0x4142, 0x2020).ascii(0, 2) == "AB"


def test_energy_is_mantissa_times_power_of_ten():
    # mapa: energia pobrana 3,5 kWh = mantysa 35, wykładnik 2 -> 3500 Wh
    assert regs(0x0000, 0x0023, 0x0002).energy_wh(0, 2) == 3500.0


def test_energy_with_negative_exponent():
    assert regs(0x0000, 0x0023, 0xFFFF).energy_wh(0, 2) == 3.5     # 35 x 10^-1


def test_address_outside_read_window_is_an_error():
    with pytest.raises(RegisterError):
        regs(1, 2).u16(2)
    with pytest.raises(RegisterError):
        regs(1, 2).u32(1)


def test_non_word_value_is_an_error():
    with pytest.raises(RegisterError):
        regs(70000).u16(0)


def test_offsets_respect_window_start():
    window = Registers(10, [7, 8, 9])
    assert window.u16(11) == 8


def test_documented_sample_decodes_from_whole_image():
    """Obraz rejestrów zbudowany niezależnym koderem z próbki 23.11.2026 dekoduje się do tych samych wartości."""
    image = Registers(0, build_image()[:44])
    assert image.u16(2) == 1                                    # map_version
    assert image.u16(10) == 0                                   # status
    assert round_real32(image.real32(16)) == SAMPLE_METER["active_power"]
    assert round_real32(image.real32(26)) == 240.4              # napięcie
    assert round_real32(image.real32(24)) == 50.02              # częstotliwość
    assert round_real32(image.real32(28)) == 0.08               # prąd
    assert round_real32(image.real32(22)) == 0.365              # współczynnik mocy
    assert image.energy_wh(34, 36) == 3500.0                    # pobrana
    assert image.energy_wh(37, 39) == 0.0                       # oddana
    assert image.ascii(40, 4) == "F0183363"
