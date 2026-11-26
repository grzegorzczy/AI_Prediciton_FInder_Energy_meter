"""Kalendarz pracy (S2) w czasie lokalnym Europe/Warsaw, z przerwami, świętami i zmianą czasu (K2-U2)."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from sim_support import epoch
from simulator.calendar import BREAK, OFF, WORK, CalendarModel
from simulator.config import load_config_dict

WAW = ZoneInfo("Europe/Warsaw")


@pytest.fixture
def cal(sim_config):
    return CalendarModel(sim_config.calendar, sim_config.ambient)


def local(*args):
    return epoch(*args, tz=WAW)


@pytest.mark.parametrize("moment, expected", [
    ((2026, 11, 30, 5, 59, 59), OFF),        # poniedziałek przed zmianą
    ((2026, 11, 30, 6, 0, 0), WORK),
    ((2026, 11, 30, 9, 59, 59), WORK),
    ((2026, 11, 30, 10, 0, 0), BREAK),       # przerwa 10:00, 15 min
    ((2026, 11, 30, 10, 14, 59), BREAK),
    ((2026, 11, 30, 10, 15, 0), WORK),
    ((2026, 11, 30, 13, 30, 0), BREAK),      # przerwa 13:30, 30 min
    ((2026, 11, 30, 18, 0, 0), BREAK),
    ((2026, 11, 30, 21, 59, 59), WORK),
    ((2026, 11, 30, 22, 0, 0), OFF),
    ((2026, 12, 5, 5, 59, 59), OFF),         # sobota 06:00-14:00
    ((2026, 12, 5, 6, 0, 0), WORK),
    ((2026, 12, 5, 13, 29, 59), WORK),
    ((2026, 12, 5, 13, 30, 0), BREAK),       # K2-U6: przerwa kończąca się z końcem zmiany
    ((2026, 12, 5, 13, 59, 59), BREAK),
    ((2026, 12, 5, 14, 0, 0), OFF),          # 14:00:00 = off
    ((2026, 12, 5, 18, 0, 0), OFF),          # przerwa 18:00 poza sobotnią zmianą nie istnieje
    ((2026, 12, 6, 12, 0, 0), OFF),          # niedziela
])
def test_states_of_weekday_saturday_and_sunday(cal, moment, expected):
    assert cal.state(local(*moment)) == expected


def test_holiday_is_off(make_raw):
    config = load_config_dict(make_raw(lambda r: r["simulator"]["calendar"].update(holidays=["2026-12-24"])))
    cal = CalendarModel(config.calendar, config.ambient)
    assert cal.state(local(2026, 12, 24, 12, 0, 0)) == OFF
    assert cal.state(local(2026, 12, 23, 12, 0, 0)) == WORK


def test_daylight_saving_days_have_25_and_23_hours_and_shifts_follow_local_time(cal):
    """25.10.2026 (doba 25 h) i 28.03.2027 (doba 23 h) to niedziele: zmiany w sobotę i poniedziałek obok przesuwają się
    w UTC o godzinę, a 06:00 czasu lokalnego zostaje 06:00."""
    autumn = cal.plan(local(2026, 10, 25, 12, 0, 0))
    spring = cal.plan(local(2027, 3, 28, 12, 0, 0))
    assert autumn.end - autumn.start == 25 * 3600 and autumn.shift is None
    assert spring.end - spring.start == 23 * 3600 and spring.shift is None
    assert cal.plan(epoch(2026, 10, 24, 12)).shift[0] == epoch(2026, 10, 24, 4)      # sobota, UTC+2
    assert cal.plan(epoch(2026, 10, 26, 12)).shift[0] == epoch(2026, 10, 26, 5)      # poniedziałek, UTC+1
    assert cal.plan(epoch(2027, 3, 27, 12)).shift[0] == epoch(2027, 3, 27, 5)        # sobota, UTC+1
    assert cal.plan(epoch(2027, 3, 29, 12)).shift[0] == epoch(2027, 3, 29, 4)        # poniedziałek, UTC+2
    assert cal.state(epoch(2026, 10, 26, 4, 59, 59)) == OFF and cal.state(epoch(2026, 10, 26, 5)) == WORK


def test_state_does_not_depend_on_call_order(sim_config):
    moments = [local(2026, 11, 30, h, m, 0) for h in range(0, 24) for m in (0, 17, 44)]
    first = CalendarModel(sim_config.calendar, sim_config.ambient)
    second = CalendarModel(sim_config.calendar, sim_config.ambient)
    assert [first.state(t) for t in moments] == [second.state(t) for t in reversed(moments)][::-1]


def test_last_shift_before_and_shift_at(cal):
    monday_evening = local(2026, 11, 30, 23, 0, 0)
    assert cal.shift_at(monday_evening) is None
    assert cal.last_shift_before(monday_evening) == (local(2026, 11, 30, 6, 0, 0), local(2026, 11, 30, 22, 0, 0))
    sunday = local(2026, 12, 6, 12, 0, 0)
    assert cal.last_shift_before(sunday) == (local(2026, 12, 5, 6, 0, 0), local(2026, 12, 5, 14, 0, 0))


def test_ambient_is_warmest_at_the_configured_hour(cal):
    assert cal.ambient_c(local(2026, 11, 30, 15, 0, 0)) == pytest.approx(23.0)
    assert cal.ambient_c(local(2026, 11, 30, 3, 0, 0)) == pytest.approx(17.0)
    assert cal.ambient_anomaly(local(2026, 11, 30, 9, 0, 0)) == pytest.approx(0.0, abs=1e-9)
