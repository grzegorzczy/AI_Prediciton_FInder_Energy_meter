"""Mosquitto (D3): hasło wymagane, ACL najmniejszych uprawnień, obieg collector -> ingest."""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

HOST = os.environ["MQTT_HOST"]
PORT = int(os.environ.get("MQTT_PORT", "1883"))
REPO = Path(os.environ.get("REPO_DIR", "/repo"))
TOPIC = "zaklad1/linia1/finder_7m24_1/voltage"
WAIT = 5.0


class Probe:
    """Mały klient MQTT v5 do testów: łączy się, subskrybuje, publikuje i zbiera wyniki."""

    def __init__(self, user=None, password=None):
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="t-" + uuid.uuid4().hex[:8], protocol=mqtt.MQTTv5)
        if user is not None:
            self.client.username_pw_set(user, password)
        self.connack = None
        self.suback = None
        self.puback = None
        self.messages: list[tuple[str, bytes]] = []
        self._events = {k: threading.Event() for k in ("connack", "suback", "puback", "message")}
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_publish = self._on_publish
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connack = reason_code
        self._events["connack"].set()

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        self.suback = reason_codes
        self._events["suback"].set()

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        self.puback = reason_code
        self._events["puback"].set()

    def _on_message(self, client, userdata, msg):
        self.messages.append((msg.topic, msg.payload))
        self._events["message"].set()

    def connect(self):
        self.client.connect_async(HOST, PORT)
        self.client.loop_start()
        assert self._events["connack"].wait(WAIT), "brak CONNACK"
        return self.connack

    def subscribe(self, topic):
        self._events["suback"].clear()
        self.client.subscribe(topic, qos=1)
        assert self._events["suback"].wait(WAIT), "brak SUBACK"
        return self.suback[0]

    def publish(self, topic, payload="{}"):
        self._events["puback"].clear()
        self.client.publish(topic, payload, qos=1)
        assert self._events["puback"].wait(WAIT), "brak PUBACK"
        return self.puback

    def wait_message(self):
        return self._events["message"].wait(WAIT)

    def close(self):
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:
            pass


@pytest.fixture
def probes():
    created: list[Probe] = []

    def make(user=None, password=None):
        probe = Probe(user, password)
        created.append(probe)
        return probe

    yield make
    for probe in created:
        probe.close()


@pytest.fixture
def collector(probes):
    probe = probes(os.environ["MQTT_COLLECTOR_USER"], os.environ["MQTT_COLLECTOR_PASSWORD"])
    assert not probe.connect().is_failure
    return probe


@pytest.fixture
def ingest(probes):
    probe = probes(os.environ["MQTT_INGEST_USER"], os.environ["MQTT_INGEST_PASSWORD"])
    assert not probe.connect().is_failure
    return probe


def test_anonymous_connection_is_refused(probes):
    assert probes().connect().is_failure


def test_wrong_password_is_refused(probes):
    assert probes(os.environ["MQTT_COLLECTOR_USER"], "zle-haslo").connect().is_failure


def test_collector_publishes_and_ingest_receives(collector, ingest):
    assert not ingest.subscribe("+/+/+/+").is_failure
    payload = json.dumps({"ts": "2026-11-23T12:00:00.000Z", "value": 240.4, "unit": "V", "source": "real"})
    assert not collector.publish(TOPIC, payload).is_failure
    assert ingest.wait_message(), "ingest nie dostał wiadomości"
    topic, body = ingest.messages[0]
    assert topic == TOPIC
    assert json.loads(body)["value"] == 240.4


def test_collector_never_receives_data(collector, ingest):
    """Wbudowany ACL Mosquitto przyznaje subskrypcję zawsze, a prawo odczytu sprawdza przy dostarczaniu.
    Gwarancja: collector (tylko zapis) nie dostaje żadnej wiadomości, ingest (odczyt) dostaje."""
    collector.subscribe("+/+/+/+")
    collector.subscribe("#")
    ingest.subscribe("+/+/+/+")
    assert not collector.publish(TOPIC, "{}").is_failure
    assert ingest.wait_message(), "ingest powinien dostać wiadomość"
    assert not collector.wait_message(), "collector nie może dostać żadnej wiadomości"


def test_ingest_cannot_publish(ingest):
    assert ingest.publish(TOPIC).is_failure


def test_collector_cannot_publish_outside_four_level_topics(collector):
    assert collector.publish("zaklad1/linia1/finder_7m24_1").is_failure          # 3 poziomy
    assert collector.publish("zaklad1/linia1/finder_7m24_1/voltage/x").is_failure  # 5 poziomów


def test_config_requires_password_and_persistence():
    text = (REPO / "config" / "mosquitto" / "mosquitto.conf").read_text(encoding="utf-8")
    assert "allow_anonymous false" in text
    assert "persistence true" in text
    assert "sys_interval 0" in text      # statystyki $SYS wyłączone; ACL i tak nie daje do nich odczytu


def test_acl_template_grants_only_minimal_rights():
    """K1-D2 (E3-k3): każde konto pisze tylko do swojej linii; ingest czyta wszystko."""
    text = (REPO / "config" / "mosquitto" / "acl.conf").read_text(encoding="utf-8")
    rules = [line.split() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert rules == [
        ["user", "__COLLECTOR_USER__"], ["topic", "write", "zaklad1/linia1/+/+"],
        ["user", "__SIM_USER__"], ["topic", "write", "zaklad1/linia2/+/+"],
        ["user", "__INGEST_USER__"], ["topic", "read", "+/+/+/+"],
    ]


def test_acl_lines_match_devices_yaml():
    """Literały zakładu i linii w ACL są te same co w config/devices.yaml (sprzęt i symulator)."""
    import yaml

    cfg = yaml.safe_load((REPO / "config" / "devices.yaml").read_text(encoding="utf-8"))
    text = (REPO / "config" / "mosquitto" / "acl.conf").read_text(encoding="utf-8")
    assert f"topic write {cfg['site']}/{cfg['line']}/+/+" in text
    assert f"topic write {cfg['simulator']['site']}/{cfg['simulator']['line']}/+/+" in text


SIM_TOPIC = "zaklad1/linia2/sim_pasteryzator/active_power"


@pytest.fixture
def simulator_account(probes):
    probe = probes(os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"])
    assert not probe.connect().is_failure
    return probe


def test_collector_writes_only_its_line(collector):
    assert not collector.publish(TOPIC).is_failure
    assert collector.publish(SIM_TOPIC).is_failure, "collector nie może pisać do linii symulatora"


def test_simulator_writes_only_its_line_and_ingest_receives(simulator_account, ingest):
    assert not ingest.subscribe("+/+/+/+").is_failure
    payload = json.dumps({"ts": "2026-11-30T09:00:00.000Z", "value": 11702.0, "unit": "W", "source": "sim"})
    assert not simulator_account.publish(SIM_TOPIC, payload).is_failure
    assert ingest.wait_message(), "ingest nie dostał wiadomości symulatora"
    assert ingest.messages[0][0] == SIM_TOPIC
    assert simulator_account.publish(TOPIC).is_failure, "symulator nie może pisać do linii sprzętu"
    assert simulator_account.publish("zaklad2/linia2/sim_pasteryzator/active_power").is_failure


def test_simulator_never_receives_data(simulator_account, collector, ingest):
    simulator_account.subscribe("#")
    ingest.subscribe("+/+/+/+")
    assert not collector.publish(TOPIC, "{}").is_failure
    assert ingest.wait_message()
    assert not simulator_account.wait_message(), "symulator nie może niczego czytać"


def test_broker_config_does_not_queue_qos0_for_offline_sessions():
    """K3-D4: dane sim (QoS 0) nie zajmują kolejki sesji ingestu; domyślnie queue_qos0_messages = false."""
    text = (REPO / "config" / "mosquitto" / "mosquitto.conf").read_text(encoding="utf-8")
    assert "queue_qos0_messages true" not in text


def test_entrypoint_makes_the_simulator_account_optional():
    """K3-D1: bez zmiennych konta symulatora broker startuje (WARNING), a blok ACL dostaje nieistniejące konto."""
    text = (REPO / "config" / "mosquitto" / "entrypoint.sh").read_text(encoding="utf-8")
    required = text[text.index("for v in"):text.index("done")]
    assert "MQTT_SIM" not in required
    assert "WARNING: brak konta symulatora" in text and "__brak_konta_symulatora__" in text
