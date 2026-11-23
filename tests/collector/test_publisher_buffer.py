"""Bufor MQTT: ograniczony, odrzuca najstarsze, loguje raz na epizod, opróżnia po kolei z oryginalnymi ts."""
from __future__ import annotations

import logging

from collector.publisher import DRAIN_PER_CALL, Publisher
from collector.statelog import StateLogger


class FakeTransport:
    def __init__(self, connected=False):
        self.connected = connected
        self.accept = True
        self.sent: list[tuple[str, bytes]] = []

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload):
        if not self.accept:
            return False
        self.sent.append((topic, payload))
        return True

    def start(self):
        pass

    def stop(self):
        pass


def msg(i):
    return (f"zaklad1/linia1/dev/m{i}", f'{{"ts":"2026-11-23T12:00:{i:02d}.000Z","value":{i}}}'.encode())


def test_connected_publishes_immediately_and_buffer_stays_empty():
    transport = FakeTransport(connected=True)
    publisher = Publisher(transport, buffer_max=10)
    publisher.publish_batch([msg(1), msg(2)])
    assert transport.sent == [msg(1), msg(2)] and publisher.buffered == 0


def test_overflow_drops_the_oldest_and_logs_once_per_episode(caplog):
    transport = FakeTransport(connected=False)
    publisher = Publisher(transport, buffer_max=5)
    with caplog.at_level(logging.INFO, logger="collector.mqtt"):
        publisher.publish_batch([msg(i) for i in range(8)])
        publisher.publish_batch([msg(8), msg(9)])
    assert publisher.buffered == 5 and publisher.dropped_total == 5
    full_warnings = [r for r in caplog.records if "bufor MQTT pełny" in r.getMessage()]
    assert len(full_warnings) == 1                                  # jeden log na epizod, nie na każdą stratę


def test_after_reconnect_buffer_drains_in_order_with_original_payloads(caplog):
    transport = FakeTransport(connected=False)
    publisher = Publisher(transport, buffer_max=5)
    publisher.publish_batch([msg(i) for i in range(8)])             # zostają m3..m7 (najstarsze odrzucone)
    transport.connected = True
    with caplog.at_level(logging.INFO, logger="collector.mqtt"):
        publisher.drain()
    assert transport.sent == [msg(i) for i in range(3, 8)]          # kolejność i niezmienione ładunki (ts)
    assert publisher.buffered == 0
    assert sum("opróżniony" in r.getMessage() for r in caplog.records) == 1
    publisher.publish_batch([msg(20)])
    assert transport.sent[-1] == msg(20)


def test_drain_is_rate_limited():
    transport = FakeTransport(connected=False)
    publisher = Publisher(transport, buffer_max=5000)
    publisher.publish_batch([msg(i) for i in range(1200)])
    transport.connected = True
    assert publisher.drain() == DRAIN_PER_CALL
    assert publisher.buffered == 1200 - DRAIN_PER_CALL


def test_rejected_publish_stays_in_buffer_and_is_retried():
    transport = FakeTransport(connected=True)
    transport.accept = False
    publisher = Publisher(transport, buffer_max=10)
    publisher.publish_batch([msg(1), msg(2)])
    assert publisher.buffered == 2 and transport.sent == []
    transport.accept = True
    publisher.drain()
    assert transport.sent == [msg(1), msg(2)]


def test_state_logger_logs_changes_and_reminders_only(caplog, clock):
    states = StateLogger(clock, remind_s=60)
    with caplog.at_level(logging.INFO, logger="collector.state"):
        for _ in range(120):                                       # 120 cykli co 1 s w stanie PLC_OFFLINE
            states.update({"plc": "PLC_OFFLINE"})
            clock.advance(1)
        states.update({"plc": "OK"})
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) <= 4, messages                            # start, 1-2 przypomnienia, powrót
    assert any("PLC_OFFLINE" in m for m in messages) and messages[-1].endswith("OK")
