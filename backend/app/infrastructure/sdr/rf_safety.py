from __future__ import annotations

from dataclasses import dataclass
import math
import os

from app.config.runtime_settings import get_runtime_value


class RFSafetyError(ValueError):
    """Raised when a requested RF setting is outside configured safety limits."""


@dataclass(frozen=True)
class RFSafetyLimits:
    device_name: str
    min_center_frequency_hz: float
    max_center_frequency_hz: float
    min_sample_rate_hz: float
    max_sample_rate_hz: float
    max_span_hz: float
    min_gain_db: float
    max_gain_db: float
    min_rbw_hz: float
    max_rbw_hz: float
    min_vbw_hz: float
    max_vbw_hz: float


def _env_float(name: str, default: float) -> float:
    value = get_runtime_value(name, os.environ.get(name, default))
    if value is None or value == "":
        return default
    return float(value)


# Software guardrails for the currently configured device (RF_SAFETY_DEVICE_NAME
# etc., see runtime_settings.DEVICE_PROFILES) -- a FUNCTION, deliberately not a
# module-level constant. It used to be computed once at import time, which is
# why switching device profiles (e.g. B200 -> NI USRP-2932) required a full
# backend restart before a request would stop being validated against the OLD
# device's range: "center_frequency_hz must be between 380000000 and
# 4420000000 Hz for NI USRP-2932..." kept citing the NEW device's limits (that
# part read runtime_settings.json live) while validating against values still
# frozen from the OLD one, or vice versa, depending on restart timing -- a
# real, confusing bug. Calling this fresh on every validation (matching how
# get_runtime_value()/merged_runtime_values() are already called fresh
# everywhere else in this module) means a profile switch takes effect on the
# very next request, no restart required.
def current_limits() -> RFSafetyLimits:
    return RFSafetyLimits(
        device_name=str(get_runtime_value("RF_SAFETY_DEVICE_NAME", os.environ.get("RF_SAFETY_DEVICE_NAME", "USRP-B200 from Ettus Research"))),
        min_center_frequency_hz=_env_float("RF_MIN_CENTER_FREQUENCY_HZ", 70_000_000.0),
        max_center_frequency_hz=_env_float("RF_MAX_CENTER_FREQUENCY_HZ", 6_000_000_000.0),
        min_sample_rate_hz=_env_float("RF_MIN_SAMPLE_RATE_HZ", 200_000.0),
        max_sample_rate_hz=_env_float("RF_MAX_SAMPLE_RATE_HZ", 61_440_000.0),
        max_span_hz=_env_float("RF_MAX_SPAN_HZ", 61_440_000.0),
        min_gain_db=_env_float("RF_MIN_GAIN_DB", 0.0),
        max_gain_db=_env_float("RF_MAX_GAIN_DB", 60.0),
        min_rbw_hz=_env_float("RF_MIN_RBW_HZ", 1.0),
        max_rbw_hz=_env_float("RF_MAX_RBW_HZ", 1_000_000.0),
        min_vbw_hz=_env_float("RF_MIN_VBW_HZ", 1.0),
        max_vbw_hz=_env_float("RF_MAX_VBW_HZ", 1_000_000.0),
    )


# Live device-selection helpers, matching current_limits()'s "call it fresh,
# no restart needed" discipline -- every real subprocess launcher in the
# backend (Live Monitor, RF Terrain, Capture Lab, Demodulation, RF Recording)
# reads through these instead of the frozen app_settings.default_device
# snapshot, so switching device profiles (Settings -> Device profiles) takes
# effect for all of them on the next real action, not just the ones that
# happened to be touched when this fix was written. Fallbacks match
# DefaultDeviceSettings' own literal defaults (device_args="", antenna="RX2")
# without importing app.config.settings, to avoid a needless cross-module
# dependency here.
def active_device_args() -> str:
    return str(get_runtime_value("UHD_DEVICE_ARGS", ""))


def active_antenna() -> str:
    return str(get_runtime_value("DEFAULT_ANTENNA", "RX2"))


def assert_finite(name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise RFSafetyError(f"{name} must be finite")


def validate_center_frequency(frequency_hz: float, limits: RFSafetyLimits | None = None) -> None:
    limits = limits or current_limits()
    assert_finite("center_frequency_hz", frequency_hz)
    if not limits.min_center_frequency_hz <= frequency_hz <= limits.max_center_frequency_hz:
        raise RFSafetyError(
            "center_frequency_hz must be between "
            f"{limits.min_center_frequency_hz:.0f} and {limits.max_center_frequency_hz:.0f} Hz "
            f"for {limits.device_name}"
        )


def validate_sample_rate(sample_rate_hz: float, limits: RFSafetyLimits | None = None) -> None:
    limits = limits or current_limits()
    assert_finite("sample_rate_hz", sample_rate_hz)
    if not limits.min_sample_rate_hz <= sample_rate_hz <= limits.max_sample_rate_hz:
        raise RFSafetyError(
            "sample_rate_hz must be between "
            f"{limits.min_sample_rate_hz:.0f} and {limits.max_sample_rate_hz:.0f} Hz"
        )


def validate_span(span_hz: float, limits: RFSafetyLimits | None = None) -> None:
    limits = limits or current_limits()
    assert_finite("span_hz", span_hz)
    if span_hz <= 0:
        raise RFSafetyError("span_hz must be > 0")
    if span_hz > limits.max_span_hz:
        raise RFSafetyError(f"span_hz must be <= {limits.max_span_hz:.0f} Hz")
    validate_sample_rate(span_hz, limits)


def validate_gain(gain_db: float, limits: RFSafetyLimits | None = None) -> None:
    limits = limits or current_limits()
    assert_finite("gain_db", gain_db)
    if not limits.min_gain_db <= gain_db <= limits.max_gain_db:
        raise RFSafetyError(
            f"gain_db must be between {limits.min_gain_db:.1f} and {limits.max_gain_db:.1f} dB"
        )


def validate_rbw(rbw_hz: float, limits: RFSafetyLimits | None = None) -> None:
    limits = limits or current_limits()
    assert_finite("rbw_hz", rbw_hz)
    if not limits.min_rbw_hz <= rbw_hz <= limits.max_rbw_hz:
        raise RFSafetyError(f"rbw_hz must be between {limits.min_rbw_hz:.0f} and {limits.max_rbw_hz:.0f} Hz")


def validate_vbw(vbw_hz: float, limits: RFSafetyLimits | None = None) -> None:
    limits = limits or current_limits()
    assert_finite("vbw_hz", vbw_hz)
    if not limits.min_vbw_hz <= vbw_hz <= limits.max_vbw_hz:
        raise RFSafetyError(f"vbw_hz must be between {limits.min_vbw_hz:.0f} and {limits.max_vbw_hz:.0f} Hz")


def validate_frequency_window(
    center_frequency_hz: float,
    span_hz: float,
    limits: RFSafetyLimits | None = None,
) -> None:
    limits = limits or current_limits()
    validate_center_frequency(center_frequency_hz, limits)
    validate_span(span_hz, limits)
    start_frequency_hz = center_frequency_hz - span_hz / 2.0
    stop_frequency_hz = center_frequency_hz + span_hz / 2.0
    if start_frequency_hz < limits.min_center_frequency_hz:
        raise RFSafetyError(
            f"start_frequency_hz must stay >= {limits.min_center_frequency_hz:.0f} Hz"
        )
    if stop_frequency_hz > limits.max_center_frequency_hz:
        raise RFSafetyError(
            f"stop_frequency_hz must stay <= {limits.max_center_frequency_hz:.0f} Hz"
        )


def validate_start_stop(
    start_frequency_hz: float,
    stop_frequency_hz: float,
    limits: RFSafetyLimits | None = None,
) -> tuple[float, float]:
    limits = limits or current_limits()
    assert_finite("start_frequency_hz", start_frequency_hz)
    assert_finite("stop_frequency_hz", stop_frequency_hz)
    if stop_frequency_hz <= start_frequency_hz:
        raise RFSafetyError("stop_frequency_hz must be greater than start_frequency_hz")
    span_hz = stop_frequency_hz - start_frequency_hz
    center_frequency_hz = start_frequency_hz + span_hz / 2.0
    validate_frequency_window(center_frequency_hz, span_hz, limits)
    return center_frequency_hz, span_hz


def safety_status(limits: RFSafetyLimits | None = None) -> dict:
    limits = limits or current_limits()
    return {
        "device_name": limits.device_name,
        "min_center_frequency_hz": limits.min_center_frequency_hz,
        "max_center_frequency_hz": limits.max_center_frequency_hz,
        "min_sample_rate_hz": limits.min_sample_rate_hz,
        "max_sample_rate_hz": limits.max_sample_rate_hz,
        "max_span_hz": limits.max_span_hz,
        "min_gain_db": limits.min_gain_db,
        "max_gain_db": limits.max_gain_db,
        "min_rbw_hz": limits.min_rbw_hz,
        "max_rbw_hz": limits.max_rbw_hz,
        "min_vbw_hz": limits.min_vbw_hz,
        "max_vbw_hz": limits.max_vbw_hz,
    }
