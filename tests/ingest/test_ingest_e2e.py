"""Tor MQTT -> ingest -> baza na prawdziwym Mosquitto i prawdziwej bazie (projekt aip-test)."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

import pytest

from dbtools import admin_connect

from ingest_support import (HAS_BROKER, IngestHarness, count_rows, make_payload, make_store, topic_for, unique_ts,
                            until)

pytestmark = pytest.mark.skipif(not HAS_BROKER, reason="wymaga brokera Mosquitto i bazy (projekt aip-test)")


@pytest.fixture
def harness(pg, migrated_db, role_passwords, config):
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    h = IngestHarness(config, store, client_id="t-ingest-" + uuid.uuid4().hex[:8]).start()
    h.wait_connected()
    yield h
    h.stop(forget=True)
    store.close()


def rows(pg, dbname, where="TRUE"):
    with admin_connect(pg, dbname) as conn:
        return conn.execute(
            "SELECT time, device_id, metric, value, unit, source FROM measurements "
            f"WHERE {where} ORDER BY time, metric").fetchall()


def test_valid_messages_land_in_measurements_with_correct_fields(pg, migrated_db, harness, pub):
    pub.publish(topic_for(metric="voltage"), make_payload(value=240.4, unit="V", ts=unique_ts()))
    pub.publish(topic_for(metric="energy_import_wh"), make_payload(value=3500, unit="Wh", ts=unique_ts(1)))
    until(lambda: count_rows(pg, migrated_db) == 2)
    by_metric = {r[2]: r for r in rows(pg, migrated_db)}
    assert by_metric["voltage"][1:6] == ("finder_7m24_1", "voltage", 240.4, "V", "real")
    assert by_metric["energy_import_wh"][3:6] == (3500.0, "Wh", "real")


def test_milliseconds_of_ts_are_preserved(pg, migrated_db, harness, pub):
    pub.publish(topic_for(), make_payload(ts="2026-11-23T11:59:59.123Z"))
    until(lambda: count_rows(pg, migrated_db) == 1)
    moment = rows(pg, migrated_db)[0][0]
    assert moment == datetime(2026, 11, 23, 11, 59, 59, 123000, tzinfo=timezone.utc)


def test_link_status_from_plc_reaches_the_database(pg, migrated_db, harness, pub):
    """U1: plc-01 jest w devices, więc jego link_status trafia do bazy (a nie jest odrzucony jako nieznany)."""
    pub.publish(topic_for("plc-01", "link_status"), make_payload(value=0, unit="", ts=unique_ts()))
    until(lambda: count_rows(pg, migrated_db, "device_id = 'plc-01' AND metric = 'link_status'") == 1)
    row = rows(pg, migrated_db, "device_id = 'plc-01'")[0]
    assert row[3] == 0.0 and row[4] == "" and row[5] == "real"


def test_duplicate_message_gives_a_single_row(pg, migrated_db, harness, pub):
    payload = make_payload(ts=unique_ts())
    pub.publish(topic_for(), payload)
    pub.publish(topic_for(), payload)
    until(lambda: harness.pipeline.total.written + harness.pipeline.total.duplicates >= 2)
    assert count_rows(pg, migrated_db) == 1
    assert harness.pipeline.total.duplicates == 1


def test_invalid_messages_are_not_stored_and_do_not_block_the_stream(pg, migrated_db, harness, pub):
    pub.publish(topic_for("nieznane_urzadzenie"), make_payload(ts=unique_ts()))                     # nieznane urządzenie
    pub.publish(topic_for(), make_payload(source="sim", ts=unique_ts(1)))                           # źródło niezgodne
    pub.publish(topic_for(), b"to nie jest json")                                                    # zły ładunek
    pub.publish(topic_for(), make_payload(ts="2026-11-23T11:59:59.123"))                            # ts bez strefy
    pub.publish(topic_for(), make_payload(value="240.4", ts=unique_ts(2)))                          # wartość tekstowa
    pub.publish(topic_for(), make_payload(ts=unique_ts(3)))                                          # poprawna na końcu
    until(lambda: count_rows(pg, migrated_db) == 1)
    until(lambda: sum(harness.pipeline.total.rejected.values()) == 5)
    assert dict(harness.pipeline.total.rejected) == {
        "unknown_device": 1, "source": 1, "payload": 1, "ts": 1, "value": 1}


def test_ingest_uses_the_writer_role_and_marks_the_connection(pg, migrated_db, harness, pub):
    pub.publish(topic_for(), make_payload(ts=unique_ts()))
    until(lambda: count_rows(pg, migrated_db) == 1)
    with admin_connect(pg, migrated_db) as conn:
        users = {r[0] for r in conn.execute(
            "SELECT usename FROM pg_stat_activity WHERE application_name = 'aip-ingest'").fetchall()}
    assert users == {"app_writer"}


def test_burst_throughput_and_exact_row_count(pg, migrated_db, harness, pub):
    """Seria 5000 wiadomości: wszystkie w bazie dokładnie raz; przepustowość do raportu (punkt odniesienia dla etapu 3)."""
    metrics = ["active_power", "reactive_power", "apparent_power", "power_factor", "frequency", "voltage", "current",
               "energy_import_wh", "energy_export_wh", "meter_status", "meter_error_count", "meter_data_age_ms"]
    base = datetime.now(timezone.utc)
    total = 5000
    started = time.perf_counter()
    for i in range(total):
        pub.publish(topic_for(metric=metrics[i % len(metrics)]), make_payload(value=float(i), ts=unique_ts(i, base)),
                    wait=False)
    pub.flush()
    until(lambda: count_rows(pg, migrated_db) == total, timeout=120)
    elapsed = time.perf_counter() - started
    rate = total / elapsed
    print(f"\n[pomiar] seria {total} wiadomości QoS 1: {elapsed:.1f} s, {rate:.0f} wiadomości/s "
          f"(paczki: średnio {harness.pipeline.total.batch_ms_total / max(harness.pipeline.total.batches, 1):.1f} ms, "
          f"maks. {harness.pipeline.total.batch_ms_max:.1f} ms, liczba paczek {harness.pipeline.total.batches})")
    assert rate >= 100                                                    # wymagane: 13/s teraz, ok. 65/s w etapie 3
    with admin_connect(pg, migrated_db) as conn:
        distinct = conn.execute("SELECT count(*) FROM (SELECT DISTINCT device_id, metric, time FROM measurements) t"
                                ).fetchone()[0]
    assert distinct == total == count_rows(pg, migrated_db)



def test_real_and_simulated_messages_land_together_with_their_sources(pg, migrated_db, harness, pub):
    """E3-k1, regresja ścieżki prawdziwej: wiadomości Findera i PLC z linia1 zapisują się jak dotąd, równolegle z danymi
    urządzenia sim z linia2 (od E3-k3 z konta symulatora, QoS 0; collector nie może pisać do linia2 – ACL K1-D2);
    wiadomość sim w linii sprzętu nie trafia do bazy (odrzuca ją ACL brokera, a gdyby dotarła – ingest)."""
    import paho.mqtt.client as mqtt

    sim = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t-sim-" + uuid.uuid4().hex[:6], protocol=mqtt.MQTTv5)
    sim.username_pw_set(os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"])
    sim.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
    sim.loop_start()
    try:
        pub.publish(topic_for(metric="voltage"), make_payload(value=240.4, unit="V", ts=unique_ts()))
        pub.publish("zaklad1/linia1/plc-01/link_status", make_payload(value=0, unit="", ts=unique_ts(1)))
        sim.publish("zaklad1/linia2/sim_pasteryzator/active_power",
                    make_payload(value=11700.0, unit="W", source="sim", ts=unique_ts(2)), qos=0).wait_for_publish(10)
        sim.publish("zaklad1/linia1/sim_pasteryzator/active_power",
                    make_payload(value=1.0, unit="W", source="sim", ts=unique_ts(3)), qos=0).wait_for_publish(10)
    finally:
        sim.loop_stop()
        sim.disconnect()
    until(lambda: count_rows(pg, migrated_db) == 3)
    time.sleep(1.5)                                                     # odrzucona wiadomość nie dociera później
    got = {(r[1], r[2]): r[3:6] for r in rows(pg, migrated_db)}
    assert got == {("finder_7m24_1", "voltage"): (240.4, "V", "real"), ("plc-01", "link_status"): (0.0, "", "real"),
                   ("sim_pasteryzator", "active_power"): (11700.0, "W", "sim")}
