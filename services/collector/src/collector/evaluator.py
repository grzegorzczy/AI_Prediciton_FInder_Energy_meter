"""Reguły ważności danych (kontrakt docs/modbus-map.md). Czysta logika: zegar jest wstrzykiwany.

Kolejność oceny w każdym cyklu:
  1. odczyt się nie udał                       -> link_status = PLC_OFFLINE, tylko status
  2. map_version różny od oczekiwanego         -> link_status = MAP_VERSION_MISMATCH, tylko status
  3. heartbeat bez zmiany > heartbeat_timeout  -> link_status = PLC_STOPPED, tylko status
  4. po (ponownym) połączeniu jeszcze nie widziano zmiany heartbeatu -> nic nie publikujemy (rozgrzewka)
  5. link_status = OK; dla każdego licznika osobno:
       status != 0                             -> meter_status = wartość z rejestru, bez pomiarów
       status == 0 i serial niezgodny          -> meter_status = SERIAL_MISMATCH, bez pomiarów
       w przeciwnym razie                      -> meter_status = OK i komplet pomiarów

Status licznika oceniamy PRZED numerem seryjnym: przy NO_DATA (do ok. 10 s po starcie PLC) rejestry
numeru seryjnego są puste i odwrotna kolejność zgłaszałaby fałszywy SERIAL_MISMATCH.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .codec import Registers, round_real32
from .config import Config, MeterConfig
from .status import LinkStatus, MeterStatus, describe_error_code


@dataclass(frozen=True)
class Reading:
    device_id: str
    metric: str
    value: float
    unit: str
    source: str


@dataclass
class Evaluation:
    """Wynik jednego cyklu: co opublikować i w jakich stanach są obiekty (do logowania zmian)."""

    link_status: LinkStatus | None          # None = rozgrzewka, nic nie publikujemy
    readings: list[Reading] = field(default_factory=list)
    states: dict[str, str] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)   # szczegół stanu do logu (np. kod błędu licznika)
    skipped: list[str] = field(default_factory=list)   # metryki pominięte (wartość nie jest liczbą skończoną)


class Evaluator:
    def __init__(self, config: Config, clock: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._clock = clock
        self._reset_heartbeat()

    def _reset_heartbeat(self) -> None:
        self._hb_last: int | None = None
        self._hb_changed_at = 0.0
        self._hb_seen_change = False

    def on_read_failed(self) -> Evaluation:
        # Po utracie połączenia pierwszy odczyt nie może uchodzić za świeży: wymagamy nowej zmiany heartbeatu.
        self._reset_heartbeat()
        return self._link_only(LinkStatus.PLC_OFFLINE)

    def _link_only(self, status: LinkStatus) -> Evaluation:
        plc = self._cfg.plc
        return Evaluation(
            link_status=status,
            readings=[Reading(plc.device_id, plc.link_metric, float(status), "", plc.source)],
            states={"plc": status.name},
        )

    def evaluate(self, regs: Registers) -> Evaluation:
        plc = self._cfg.plc

        if regs.u16(plc.map_version_offset) != plc.map_version:
            self._reset_heartbeat()
            return self._link_only(LinkStatus.MAP_VERSION_MISMATCH)

        now = self._clock()
        heartbeat = regs.u32(plc.heartbeat_offset)
        if self._hb_last is None:
            self._hb_last, self._hb_changed_at, self._hb_seen_change = heartbeat, now, False
        elif heartbeat != self._hb_last:
            self._hb_last, self._hb_changed_at, self._hb_seen_change = heartbeat, now, True

        if now - self._hb_changed_at > plc.heartbeat_timeout_s:
            return self._link_only(LinkStatus.PLC_STOPPED)
        if not self._hb_seen_change:
            return Evaluation(link_status=None)

        result = self._link_only(LinkStatus.OK)
        for meter in self._cfg.meters:
            self._evaluate_meter(meter, regs, result)
        return result

    def _evaluate_meter(self, meter: MeterConfig, regs: Registers, out: Evaluation) -> None:
        profile, base, source = meter.profile, meter.block_base, meter.source

        def add(metric: str, value: float, unit: str) -> None:
            if not math.isfinite(value):
                out.skipped.append(f"{meter.device_id}.{metric}")
                return
            out.readings.append(Reading(meter.device_id, metric, float(value), unit, source))

        raw_status = regs.u16(base + profile.status.offset)

        # Diagnostyka jest ważna także przy błędzie komunikacji (data_age_ms rośnie przez całą przerwę).
        if profile.error_count is not None and profile.error_count.metric:
            add(profile.error_count.metric, regs.read(profile.error_count.type, base + profile.error_count.offset),
                profile.error_count.unit)
        if profile.data_age is not None and profile.data_age.metric:
            age = regs.read(profile.data_age.type, base + profile.data_age.offset)
            if age != profile.data_age.omit_value:
                add(profile.data_age.metric, age, profile.data_age.unit)

        status_metric = profile.status.metric
        key = f"meter:{meter.device_id}"
        if raw_status != MeterStatus.OK:
            add(status_metric, raw_status, "")
            known = raw_status in (MeterStatus.COMM_ERROR, MeterStatus.NO_DATA)
            out.states[key] = MeterStatus(raw_status).name if known else f"UNKNOWN_STATUS_{raw_status}"
            # Kod błędu komunikacji (rejestr 11) jest ważny tylko przy statusie != 0; przy OK nie jest publikowany.
            if profile.error_code is not None:
                code = int(regs.read(profile.error_code.type, base + profile.error_code.offset))
                if profile.error_code.metric:
                    add(profile.error_code.metric, code, profile.error_code.unit)
                out.details[key] = describe_error_code(code)
            return

        serial = regs.ascii(base + profile.serial_offset, profile.serial_registers)
        if serial != meter.serial:
            add(status_metric, MeterStatus.SERIAL_MISMATCH, "")
            out.states[key] = MeterStatus.SERIAL_MISMATCH.name
            return

        add(status_metric, MeterStatus.OK, "")
        out.states[key] = MeterStatus.OK.name
        for metric, spec in profile.metrics.items():
            value = regs.read(spec.type, base + spec.offset)
            add(metric, round_real32(value) if spec.type == "real32" else value, spec.unit)
        for metric, spec in profile.energy.items():
            add(metric, regs.energy_wh(base + spec.mantissa, base + spec.exponent), spec.unit)
