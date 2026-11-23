"""Wejście MQTT: paho-mqtt 2.x, MQTT v3.1.1, sesja trwała, QoS 1, RĘCZNE potwierdzanie.

Stały client_id i clean_session=False sprawiają, że wiadomości z czasu przerwy ingestu czekają w Mosquitto.
Potwierdzenie (ack) wysyła potok dopiero po zapisie w bazie. Broker nie wyśle więcej niż max_inflight_messages
(100) niepotwierdzonych wiadomości, więc przy niedostępnej bazie reszta czeka w kolejce sesji brokera.
"""
from __future__ import annotations

import logging
import queue
import time

import paho.mqtt.client as mqtt

from .pipeline import Incoming

LOG = logging.getLogger("ingest.mqtt")

TOPIC_FILTER = "+/+/+/+"


class MqttInput:
    def __init__(self, host: str, port: int, user: str, password: str, client_id: str = "aip-ingest") -> None:
        self._host, self._port = host, port
        self._queue: queue.Queue[Incoming] = queue.Queue(maxsize=5000)
        self.received_total = 0
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False,
            protocol=mqtt.MQTTv311, manual_ack=True,
        )
        self._client.username_pw_set(user, password)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message
        self.connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            LOG.warning("MQTT: połączenie odrzucone: %s (sprawdź konto ingest)", reason_code)
            return
        self.connected = True
        LOG.info("MQTT: połączono z %s:%s, sesja trwała %s", self._host, self._port,
                 "wznowiona" if flags.session_present else "nowa")
        client.subscribe(TOPIC_FILTER, qos=1)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties) -> None:
        if any(code.is_failure for code in reason_codes):
            LOG.error("MQTT: subskrypcja %s odrzucona: %s", TOPIC_FILTER, reason_codes)
        else:
            LOG.info("MQTT: subskrypcja %s potwierdzona (QoS 1)", TOPIC_FILTER)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self.connected = False
        LOG.warning("MQTT: rozłączono (%s); połączę ponownie, niepotwierdzone wiadomości wrócą z brokera", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        self.received_total += 1
        self._queue.put(Incoming(message.topic, bytes(message.payload), (message.mid, message.qos)))

    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=30)
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def get(self, timeout: float) -> Incoming | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def ack(self, token) -> None:
        mid, qos = token
        self._client.ack(mid, qos)
