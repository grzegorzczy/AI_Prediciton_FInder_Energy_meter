"""Wejście MQTT: paho-mqtt 2.x, MQTT v3.1.1, sesja trwała, QoS 1, RĘCZNE potwierdzanie.

Stały client_id i clean_session=False sprawiają, że wiadomości z czasu przerwy ingestu czekają w Mosquitto.
Potwierdzenie (ack) wysyła potok dopiero po zapisie w bazie. Broker nie wyśle więcej niż max_inflight_messages
(100) niepotwierdzonych wiadomości, więc przy niedostępnej bazie reszta czeka w kolejce sesji brokera.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

from .pipeline import Incoming

LOG = logging.getLogger("ingest.mqtt")

TOPIC_FILTER = "+/+/+/+"


class MqttInput:
    def __init__(self, host: str, port: int, user: str, password: str, client_id: str = "aip-ingest",
                 droppable: Callable[[str, int], bool] | None = None, droppable_max: int = 3000) -> None:
        self._host, self._port = host, port
        self._queue: queue.Queue[Incoming] = queue.Queue(maxsize=5000)
        # E3-k4 (przegląd): limit danych sim także w kolejce wejściowej. Przy wolnej bazie zaległość gromadzi się tutaj, a nie
        # w potoku; bez limitu wiadomości QoS 0 symulatora zapełniłyby kolejkę (5000) i zablokowały wątek sieciowy paho
        # (put), czyli także dane prawdziwe. `droppable(topic, qos)` = wiadomość urządzenia sim z QoS 0 (z configu).
        if droppable_max < 1:
            raise ValueError("droppable_max musi być >= 1")
        self._droppable = droppable or (lambda topic, qos: False)
        self._droppable_max = droppable_max
        self._droppable_in_queue = 0
        self._lock = threading.Lock()
        self.sim_dropped_total = 0
        self._sim_drop_episode = 0
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
        droppable = self._droppable(message.topic, message.qos)
        if droppable:
            with self._lock:
                if self._droppable_in_queue >= self._droppable_max:
                    self.sim_dropped_total += 1
                    if self._sim_drop_episode == 0:
                        LOG.warning("kolejka wejściowa: %d wiadomości symulatora (QoS 0) czeka na zapis – odrzucam kolejne "
                                    "(limit INGEST_SIM_PENDING_MAX); dane prawdziwe bez zmian", self._droppable_in_queue)
                    self._sim_drop_episode += 1
                    return                                  # QoS 0: nie ma czego potwierdzać
                self._droppable_in_queue += 1
                if self._sim_drop_episode:
                    LOG.warning("kolejka wejściowa: koniec odrzucania danych symulatora, odrzucono %d", self._sim_drop_episode)
                    self._sim_drop_episode = 0
        self._queue.put(Incoming(message.topic, bytes(message.payload), (message.mid, message.qos), message.qos, droppable))

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
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item.droppable:
            with self._lock:
                self._droppable_in_queue -= 1
        return item

    def ack(self, token) -> None:
        mid, qos = token
        self._client.ack(mid, qos)
