"""Publikacja danych symulatora do MQTT: QoS 0 (K3-D4) i ograniczony bufor na krótkie przerwy brokera (K3-D3).

QoS 0, bo dane sim są funkcją czasu (luki uzupełnia historia, idempotentnie), a Mosquitto nie kolejkuje wiadomości QoS 0
dla rozłączonego ingestu (`queue_qos0_messages` domyślnie false): kolejka sesji ingestu (80 000) zostaje dla danych
prawdziwych z linii sprzętu. Bufor symulatora działa tylko przy braku połączenia z brokerem: po przepełnieniu odrzuca
NAJSTARSZE wiadomości (log raz na epizod), po powrocie wysyła je po kolei z ograniczeniem tempa.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Protocol

import paho.mqtt.client as mqtt

LOG = logging.getLogger("simulator.mqtt")
DRAIN_PER_CALL = 500
QOS = 0


class Transport(Protocol):
    def is_connected(self) -> bool: ...
    def publish(self, topic: str, payload: bytes) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


class PahoTransport:
    """paho-mqtt 2.x, MQTT v5, QoS 0, ponowne łączenie z cofaniem; błąd autoryzacji logowany raz na epizod (K3-D1)."""

    def __init__(self, host: str, port: int, user: str, password: str, client_id: str = "aip-simulator") -> None:
        self._host, self._port = host, port
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        self._client.username_pw_set(user, password)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.max_queued_messages_set(2000)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._refused_logged = False

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            if not self._refused_logged:
                self._refused_logged = True
                LOG.error("MQTT: połączenie odrzucone (%s): sprawdź konto symulatora w .env (MQTT_SIM_USER/PASSWORD); "
                          "ponawiam z cofaniem", reason_code)
            return
        self._refused_logged = False
        LOG.info("MQTT: połączono z %s:%s (QoS 0)", self._host, self._port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if not self._refused_logged:
            LOG.warning("MQTT: rozłączono (%s); wiadomości trafiają do bufora", reason_code)

    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=30)
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def is_connected(self) -> bool:
        return self._client.is_connected()

    def publish(self, topic: str, payload: bytes) -> bool:
        return self._client.publish(topic, payload, qos=QOS).rc == mqtt.MQTT_ERR_SUCCESS


class Publisher:
    def __init__(self, transport: Transport, buffer_max: int) -> None:
        self._transport = transport
        self._buffer: deque[tuple[str, bytes]] = deque()
        self._max = buffer_max
        self._episode_dropped = 0
        self.dropped_total = 0
        self.sent_total = 0

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def start(self) -> None:
        self._transport.start()

    def stop(self) -> None:
        self.drain()
        self._transport.stop()

    def enqueue(self, messages: list[tuple[str, bytes]]) -> None:
        for message in messages:
            if len(self._buffer) >= self._max:
                self._buffer.popleft()
                self.dropped_total += 1
                if self._episode_dropped == 0:
                    LOG.warning("bufor MQTT symulatora pełny (%d): odrzucam najstarsze wiadomości", self._max)
                self._episode_dropped += 1
            self._buffer.append(message)

    def drain(self, limit: int = DRAIN_PER_CALL) -> int:
        sent = 0
        while self._buffer and sent < limit and self._transport.is_connected():
            topic, payload = self._buffer[0]
            if not self._transport.publish(topic, payload):
                break
            self._buffer.popleft()
            sent += 1
        self.sent_total += sent
        if not self._buffer and self._episode_dropped:
            LOG.warning("bufor MQTT symulatora opróżniony; w tym epizodzie odrzucono %d wiadomości", self._episode_dropped)
            self._episode_dropped = 0
        return sent

    def publish_batch(self, messages: list[tuple[str, bytes]]) -> None:
        self.enqueue(messages)
        self.drain(limit=max(DRAIN_PER_CALL, len(messages)))
