"""Odporność: start przed bazą i schematem (U4), przerwa bazy, awaria między odbiorem a zapisem, sesja trwała (K4-U2)."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import pytest

from dbtools import admin_connect
from ingest import health

from ingest_support import (HAS_BROKER, IngestHarness, count_rows, make_payload, make_store, topic_for, unique_ts,
                            until)

pytestmark = pytest.mark.skipif(not HAS_BROKER, reason="wymaga brokera Mosquitto i bazy (projekt aip-test)")


def distinct_rows(pg, dbname) -> int:
    with admin_connect(pg, dbname) as conn:
        return conn.execute(
            "SELECT count(*) FROM (SELECT DISTINCT device_id, metric, time FROM measurements) t").fetchone()[0]


def publish_n(pub, n, start=0, metric="voltage"):
    base = datetime.now(timezone.utc)
    for i in range(start, start + n):
        pub.publish(topic_for(metric=metric), make_payload(value=float(i), ts=unique_ts(i, base)), wait=False)
    pub.flush()


def test_ingest_started_before_database_and_schema_waits_then_works(pg, fresh_db, role_passwords, run_migrate, config,
                                                                    pub):
    """U4: pusta baza bez schematu (a nawet bez roli). Ingest się nie kończy, żyje, a po migrate zaczyna zapisywać."""
    store = make_store(pg, fresh_db, role_passwords["app_writer"])
    harness = IngestHarness(config, store, client_id="t-ingest-" + uuid.uuid4().hex[:8]).start()
    try:
        time.sleep(2.5)
        assert harness.thread.is_alive(), f"ingest zakończył się: {harness.error!r}"
        assert not harness.source.connected                          # MQTT startuje dopiero po bazie i synchronizacji
        assert health.is_fresh(harness.health_file, max_age_s=2.0)    # pętla żyje mimo braku bazy
        result = run_migrate(fresh_db)
        assert result.returncode == 0, result.stderr
        harness.wait_connected(timeout=20)
        for i in range(3):
            pub.publish(topic_for(), make_payload(value=float(i), ts=unique_ts(i)))
        until(lambda: count_rows(pg, fresh_db) == 3)
        assert admin_rows(pg, fresh_db, "SELECT count(*) FROM devices") == 7          # plc-01, licznik i 5 urządzeń sim (E3-k1)
    finally:
        harness.stop(forget=True)
        store.close()


def admin_rows(pg, dbname, query):
    with admin_connect(pg, dbname) as conn:
        return conn.execute(query).fetchone()[0]


def test_database_outage_holds_at_most_100_in_flight_and_loses_nothing(pg, migrated_db, role_passwords, config, pub):
    """K4-U2: przy niedostępnej bazie do ingestu dociera najwyżej 100 niepotwierdzonych, reszta czeka w kolejce sesji;
    po powrocie bazy liczba wierszy = liczba wysłanych (bez strat i duplikatów)."""
    store = make_store(pg, migrated_db, role_passwords["app_writer"], flaky=True)
    harness = IngestHarness(config, store, client_id="t-ingest-" + uuid.uuid4().hex[:8]).start()
    try:
        harness.wait_connected()
        store.down = True
        total = 250
        publish_n(pub, total)
        time.sleep(3.0)
        in_flight = harness.source.received_total
        print(f"\n[pomiar] przy niedostępnej bazie do ingestu dotarło {in_flight} z {total} wiadomości "
              f"(oczekujących w potoku: {harness.pipeline.pending})")
        assert in_flight == 100
        assert count_rows(pg, migrated_db) == 0 and harness.pipeline.db_down
        assert health.is_fresh(harness.health_file, max_age_s=2.0)    # pętla żyje także przy niedostępnej bazie
        store.down = False
        until(lambda: count_rows(pg, migrated_db) == total, timeout=60)
        assert distinct_rows(pg, migrated_db) == total == count_rows(pg, migrated_db)
    finally:
        harness.stop(forget=True)
        store.close()


def test_failure_between_receive_and_ack_is_redelivered_without_duplicates(pg, migrated_db, role_passwords, config,
                                                                            pub):
    """Awaria ingestu po odebraniu, przed zapisem (nic nie potwierdzone): broker dostarcza ponownie, jeden wiersz na wiadomość."""
    client_id = "t-ingest-" + uuid.uuid4().hex[:8]
    flaky = make_store(pg, migrated_db, role_passwords["app_writer"], flaky=True)
    first = IngestHarness(config, flaky, client_id).start()
    try:
        first.wait_connected()
        flaky.down = True
        publish_n(pub, 30)
        until(lambda: first.source.received_total == 30)
        assert count_rows(pg, migrated_db) == 0
    finally:
        first.stop()                                                 # zatrzymanie przy niedostępnej bazie: bez potwierdzeń
        flaky.close()
    assert count_rows(pg, migrated_db) == 0

    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    second = IngestHarness(config, store, client_id).start()
    try:
        until(lambda: count_rows(pg, migrated_db) == 30, timeout=30)
        time.sleep(1.0)
        assert distinct_rows(pg, migrated_db) == 30 == count_rows(pg, migrated_db)
    finally:
        second.stop(forget=True)
        store.close()


def test_messages_published_while_ingest_is_down_are_delivered_after_restart(pg, migrated_db, role_passwords, config,
                                                                              pub):
    """Sesja trwała: wiadomości z czasu przerwy ingestu czekają w Mosquitto."""
    client_id = "t-ingest-" + uuid.uuid4().hex[:8]
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    first = IngestHarness(config, store, client_id).start()
    first.wait_connected()
    first.stop()                                                     # ingest zatrzymany po poprawnym nawiązaniu sesji
    publish_n(pub, 40)
    assert count_rows(pg, migrated_db) == 0
    second = IngestHarness(config, store, client_id).start()
    try:
        until(lambda: count_rows(pg, migrated_db) == 40, timeout=30)
        assert distinct_rows(pg, migrated_db) == 40
    finally:
        second.stop(forget=True)
        store.close()


def test_rejections_do_not_flood_the_log_end_to_end(pg, migrated_db, role_passwords, config, pub, caplog):
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    harness = IngestHarness(config, store, client_id="t-ingest-" + uuid.uuid4().hex[:8]).start()
    try:
        harness.wait_connected()
        with caplog.at_level(logging.INFO, logger="ingest"):
            for i in range(1000):
                pub.publish(topic_for(), make_payload(value="zly", ts=unique_ts(i)), wait=False)
            pub.flush()
            until(lambda: harness.pipeline.total.rejected["value"] == 1000, timeout=60)
        warnings = [r for r in caplog.records if r.name.startswith("ingest") and r.levelno >= logging.WARNING]
        print(f"\n[pomiar] 1000 wadliwych wiadomości: {len(warnings)} wpisów WARNING w logu ingestu")
        assert len(warnings) <= 3
        assert count_rows(pg, migrated_db) == 0
    finally:
        harness.stop(forget=True)
        store.close()


def test_health_marker_is_refreshed_and_loop_never_exits_when_database_is_down(pg, migrated_db, role_passwords,
                                                                                config):
    store = make_store(pg, migrated_db, role_passwords["app_writer"], flaky=True)
    store.down = True                                                # baza niedostępna już przy starcie
    harness = IngestHarness(config, store, client_id="t-ingest-" + uuid.uuid4().hex[:8]).start()
    try:
        time.sleep(2.0)
        assert harness.thread.is_alive() and health.is_fresh(harness.health_file, max_age_s=1.5)
        store.down = False
        harness.wait_connected(timeout=20)
    finally:
        harness.stop(forget=True)
        store.close()
