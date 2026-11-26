"""K2R-U4: energia dób lokalnych 25 h i 23 h (zmiana czasu) oraz poniedziałków po zmianie czasu."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from sim_support import epoch, with_dates

WAW = ZoneInfo("Europe/Warsaw")


def local(*args):
    return epoch(*args, tz=WAW)


def sim_anchored(make_sim, sim_config, anchor_utc):
    return make_sim(with_dates(sim_config, meter_anchor=datetime.fromtimestamp(anchor_utc, timezone.utc)))


@pytest.mark.parametrize("day, seconds", [((2026, 10, 25), 90000), ((2027, 3, 28), 82800)])
def test_local_day_energy_is_the_sum_of_its_seconds(make_sim, sim_config, day, seconds):
    start, end = local(*day), local(*day[:2], day[2] + 1)
    assert end - start == seconds
    sim = sim_anchored(make_sim, sim_config, start - 3600)
    for dev, (meter, counter) in sim.meters.items():
        summed = sum(int(meter.power(t)[0]) for t in range(start, end))
        assert counter.integral_ws(end) - counter.integral_ws(start) == summed, dev
        delta_wh = counter.value_wh(end) - counter.value_wh(start)
        assert abs(delta_wh - summed / 3600.0) < 100.0, dev
    # niedziela: maszyny zmianowe stoją (tylko moc postoju), chłodnia pracuje proporcjonalnie do długości doby
    chiller = sim.meters["sim_chlodnia"][0]
    per_hour = sum(chiller.power(t)[0] for t in range(start, end)) / 3600.0 / (seconds / 3600) / 1000.0
    assert 4.5 < per_hour < 7.5
    packer = sim.meters["sim_pakowaczka"][0]
    assert {packer.model_power(t)[0] for t in range(start, end, 600)} == {120.0}


@pytest.mark.parametrize("monday, normal_monday, shift_start_utc", [
    ((2026, 10, 26), (2026, 10, 19), (2026, 10, 26, 5)),          # po zmianie na czas zimowy: 06:00 = 05:00 UTC
    ((2027, 3, 29), (2027, 3, 22), (2027, 3, 29, 4)),             # po zmianie na czas letni: 06:00 = 04:00 UTC
])
def test_monday_after_dst_change_has_the_usual_energy(make_sim, sim_config, monday, normal_monday, shift_start_utc):
    sim = sim_anchored(make_sim, sim_config, local(*normal_monday) - 3600)
    assert sim.calendar.state(epoch(*shift_start_utc) - 1) == "off" and sim.calendar.state(epoch(*shift_start_utc)) == "work"
    for dev in ("sim_mieszalnik", "sim_pakowaczka"):
        meter = sim.meters[dev][0]
        energy = lambda d: sum(meter.power(t)[0] for t in range(local(*d), local(*d[:2], d[2] + 1))) / 3600.0  # noqa: E731
        assert energy(monday) == pytest.approx(energy(normal_monday), rel=0.03), dev
