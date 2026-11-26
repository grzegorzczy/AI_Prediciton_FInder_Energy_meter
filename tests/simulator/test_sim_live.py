"""Pętla na żywo (atrapa zegara i transportu): ticki, opóźnienia, cofnięcie zegara (K3-U3), bufor (K3-D3)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading

import pytest

from sim_support import epoch
from simulator.live import LiveLoop, iso_ms, messages_for
from simulator.publisher import Publisher

START = epoch(2026, 11, 30, 9, 0, 0)


class FakeTransport:
    def __init__(self, connected=True):
        self.connected = connected
        self.sent: list[tuple[str, bytes]] = []

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload):
        if not self.connected:
            return False
        self.sent.append((topic, payload))
        return True

    def start(self):
        pass

    def stop(self):
        pass


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


def loop_for(simulator, clock, transport=None, buffer_max=36000):
    transport = transport or FakeTransport()
    publisher = Publisher(transport, buffer_max)
    return LiveLoop(simulator, publisher, clock=clock, sleep=lambda s: None), transport, publisher


def test_one_tick_publishes_29_messages_with_topics_and_payload(simulator):
    clock = Clock(START + 0.4)
    loop, transport, _ = loop_for(simulator, clock)
    assert loop.step() == 1
    assert len(transport.sent) == 29
    topics = [t for t, _ in transport.sent]
    assert all(t.startswith("zaklad1/linia2/sim_") for t in topics)
    assert "zaklad1/linia2/sim_pump_p101/speed" in topics and "zaklad1/linia2/sim_chlodnia/energy_import_wh" in topics
    payload = json.loads(transport.sent[0][1])
    assert set(payload) == {"ts", "value", "unit", "source"} and payload["source"] == "sim"
    assert payload["ts"] == iso_ms(START) == "2026-11-30T09:00:00.000Z"
    assert [m for m in messages_for(simulator, "zaklad1", "linia2", START)] == transport.sent


def test_same_second_twice_publishes_nothing_and_small_lag_is_caught_up(simulator):
    clock = Clock(START)
    loop, transport, _ = loop_for(simulator, clock)
    loop.step()
    clock.t = START + 0.9
    assert loop.step() == 0
    clock.t = START + 3.2                                                # 3 s opóźnienia: nadrabia 3 sekundy po kolei
    assert loop.step() == 3 and len(transport.sent) == 4 * 29
    stamps = sorted({json.loads(p)["ts"] for _, p in transport.sent})
    assert stamps == [iso_ms(START + i) for i in range(4)]


def test_big_lag_skips_to_now_and_logs_once(simulator, caplog):
    clock = Clock(START)
    loop, transport, _ = loop_for(simulator, clock)
    loop.step()
    clock.t = START + 60
    with caplog.at_level(logging.WARNING, logger="simulator.live"):
        assert loop.step() == 1
    assert loop.last == START + 60 and loop.skipped_total == 59
    assert sum("przeskakuję" in r.getMessage() for r in caplog.records) == 1


def test_clock_going_back_does_not_hang_or_resend(simulator, caplog):
    """K3-U3: małe cofnięcie = czekanie (nic nie wychodzi dwa razy), duże = start od bieżącej sekundy; pętla żyje."""
    clock = Clock(START + 10)
    loop, transport, _ = loop_for(simulator, clock)
    loop.step()
    clock.t = START + 8                                                  # NTP cofa o 2 s
    assert loop.step() == 0
    clock.t = START + 11
    assert loop.step() == 1 and loop.last == START + 11
    clock.t = START - 3600                                               # cofnięcie o godzinę
    with caplog.at_level(logging.WARNING, logger="simulator.live"):
        assert loop.step() == 1
    assert loop.last == START - 3600 and any("cofnięty" in r.getMessage() for r in caplog.records)
    stop = threading.Event()
    steps = []
    loop.sleep = lambda s: (steps.append(s), setattr(clock, "t", clock.t + 1), stop.set() if len(steps) >= 3 else None)
    loop.run(stop)
    assert len(steps) == 3 and loop.last == START - 3600 + 2


def test_buffer_keeps_messages_while_the_broker_is_away_and_drops_the_oldest(simulator, caplog):
    clock = Clock(START)
    transport = FakeTransport(connected=False)
    loop, _, publisher = loop_for(simulator, clock, transport, buffer_max=29 * 3)
    with caplog.at_level(logging.WARNING, logger="simulator.mqtt"):
        for i in range(5):
            clock.t = START + i
            loop.step()
    assert publisher.buffered == 29 * 3 and publisher.dropped_total == 29 * 2
    assert sum("pełny" in r.getMessage() for r in caplog.records) == 1
    transport.connected = True
    publisher.drain()                                                    # po powrocie brokera: najpierw bufor
    clock.t = START + 5
    loop.step()
    stamps = [json.loads(p)["ts"] for _, p in transport.sent]
    assert stamps[0] == iso_ms(START + 2) and stamps[-1] == iso_ms(START + 5)          # najstarsze odrzucone


@pytest.mark.skipif(sys.platform == "win32", reason="moduł resource tylko w Linuksie (kontener testowy)")
def test_full_buffer_memory(sim_config):
    """K3-D3: pełny bufor 36 000 wiadomości (ok. 20 min przy 29/s) w osobnym procesie – szczytowy RSS do raportu."""
    code = (
        "import resource, sys\n"
        "from simulator.publisher import Publisher\n"
        "class Down:\n"
        "    def is_connected(self): return False\n"
        "    def publish(self, t, p): return False\n"
        "    def start(self): pass\n"
        "    def stop(self): pass\n"
        "base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "pub = Publisher(Down(), 36000)\n"
        "payload = b'{\"ts\": \"2026-11-30T09:00:00.000Z\", \"value\": 11702.0, \"unit\": \"W\", \"source\": \"sim\"}'\n"
        "for i in range(40000):\n"
        "    pub.enqueue([('zaklad1/linia2/sim_pasteryzator/active_power', payload + str(i).encode())])\n"
        "peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "print(pub.buffered, base, peak)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120,
                         env={**os.environ}).stdout.split()
    buffered, base_kb, peak_kb = map(int, out)
    print(f"\nBUFOR 36000: RSS procesu (VmRSS) {base_kb / 1024:.1f} -> {peak_kb / 1024:.1f} MiB (wzrost {(peak_kb - base_kb) / 1024:.1f} MiB)")
    assert buffered == 36000 and peak_kb / 1024 < 100
