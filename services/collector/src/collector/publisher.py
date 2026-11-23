"""Publikacja do MQTT z buforem w pamięci.

Gdy broker jest niedostępny, wiadomości trafiają do ograniczonego bufora (deque). Po przepełnieniu odrzucane są
NAJSTARSZE wiadomości, a odrzucenia są logowane raz na epizod. Po powrocie brokera bufor jest opróżniany po
kolei, z oryginalnymi znacznikami `ts`, z ograniczeniem tempa. Mosquitto po swojej stronie odrzuca NAJNOWSZE
wiadomości po zapełnieniu kolejki sesji ingestu: te dwie asymetrie są opisane w raporcie k3 i k4.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Protocol

import paho.mqtt.client as mqtt

LOG = logging.getLogger("collector.mqtt")

DRAIN_PER_CALL = 500   # górny limit wiadomości wysyłanych w jednym wywołaniu (tempo nadrabiania po awarii)


class Transport(Protocol):
    def is_connected(self) -> bool: ...
    def publish(self, topic: str, payload: bytes) -> bool:
        """True, jeśli wiadomość przyjęto do wysłania; False, jeśli trzeba spróbować później."""
        ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


class PahoTransport:
    """paho-mqtt 2.x, MQTT v5 (odmowa ACL jest widoczna w PUBACK), QoS 1, automatyczne ponowne łączenie."""

    def __init__(self, host: str, port: int, user: str, password: str, client_id: str = "aip-collector") -> None:
        self._host, self._port = host, port
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        self._client.username_pw_set(user, password)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.max_queued_messages_set(2000)     # wewnętrzna kolejka paho nie rośnie bez limitu
        self._client.max_inflight_messages_set(100)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish
        self._denied_logged = False

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            LOG.warning("MQTT: połączenie odrzucone: %s", reason_code)
        else:
            LOG.info("MQTT: połączono z %s:%s", self._host, self._port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        LOG.warning("MQTT: rozłączono (%s); wiadomości trafiają do bufora", reason_code)

    def _on_publish(self, client, userdata, mid, reason_code, properties) -> None:
        if reason_code.is_failure and not self._denied_logged:
            self._denied_logged = True
            LOG.error("MQTT: broker odrzucił publikację (%s); sprawdź konto i ACL", reason_code)

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
        info = self._client.publish(topic, payload, qos=1)
        return info.rc == mqtt.MQTT_ERR_SUCCESS


class Publisher:
    def __init__(self, transport: Transport, buffer_max: int) -> None:
        self._transport = transport
        self._buffer: deque[tuple[str, bytes]] = deque()
        self._max = buffer_max
        self._episode_dropped = 0
        self._dropped_total = 0

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    @property
    def dropped_total(self) -> int:
        return self._dropped_total

    def start(self) -> None:
        self._transport.start()

    def stop(self) -> None:
        self.drain()
        self._transport.stop()

    def enqueue(self, messages: list[tuple[str, bytes]]) -> None:
        for message in messages:
            if len(self._buffer) >= self._max:
                self._buffer.popleft()                 # odrzucamy najstarszą
                self._dropped_total += 1
                if self._episode_dropped == 0:
                    LOG.warning("bufor MQTT pełny (%d): odrzucam najstarsze wiadomości", self._max)
                self._episode_dropped += 1
            self._buffer.append(message)

    def drain(self) -> int:
        sent = 0
        while self._buffer and sent < DRAIN_PER_CALL and self._transport.is_connected():
            topic, payload = self._buffer[0]
            if not self._transport.publish(topic, payload):
                break
            self._buffer.popleft()
            sent += 1
        if not self._buffer and self._episode_dropped:
            LOG.warning("bufor MQTT opróżniony; w tym epizodzie odrzucono %d wiadomości", self._episode_dropped)
            self._episode_dropped = 0
        return sent

    def publish_batch(self, messages: list[tuple[str, bytes]]) -> None:
        self.enqueue(messages)
        self.drain()
