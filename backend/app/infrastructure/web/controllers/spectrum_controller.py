from __future__ import annotations

import re

from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import (
    RFSafetyError,
    safety_status,
    validate_center_frequency,
    validate_frequency_window,
    validate_gain,
    validate_rbw,
    validate_sample_rate,
    validate_span,
    validate_start_stop,
    validate_vbw,
)


class SpectrumController:
    def __init__(
        self,
        get_live_spectrum_use_case,
        get_live_waterfall_use_case,
        set_span_use_case,
        set_rbw_use_case,
        set_vbw_use_case,
        set_noise_floor_offset_use_case,
        set_reference_level_use_case,
        set_detector_mode_use_case,
        set_averaging_use_case,
        settings,
    ):
        self._get_live_spectrum_use_case = get_live_spectrum_use_case
        self._get_live_waterfall_use_case = get_live_waterfall_use_case
        self._set_span_use_case = set_span_use_case
        self._set_rbw_use_case = set_rbw_use_case
        self._set_vbw_use_case = set_vbw_use_case
        self._set_noise_floor_offset_use_case = set_noise_floor_offset_use_case
        self._set_reference_level_use_case = set_reference_level_use_case
        self._set_detector_mode_use_case = set_detector_mode_use_case
        self._set_averaging_use_case = set_averaging_use_case
        self._settings = settings

    def get_spectrum(self, settings=None) -> dict:
        active_settings = settings or self._settings
        return real_spectrum_stream.get_latest(active_settings)

    def get_live_waterfall(self) -> dict:
        frame = real_spectrum_stream.get_latest(self._settings)
        levels_db = frame.get("levels_db") or []
        center_frequency_hz = frame.get("center_frequency_hz", self._settings.frequency.center_frequency_hz)
        span_hz = frame.get("span_hz", self._settings.frequency.sample_rate_hz)
        start_frequency_hz = center_frequency_hz - span_hz / 2
        stop_frequency_hz = center_frequency_hz + span_hz / 2

        return {
            "timestamp_utc": frame.get("timestamp_utc"),
            "center_frequency_hz": center_frequency_hz,
            "span_hz": span_hz,
            "start_frequency_hz": frame.get("start_frequency_hz", start_frequency_hz),
            "stop_frequency_hz": frame.get("stop_frequency_hz", stop_frequency_hz),
            "sample_rate_hz": frame.get("sample_rate_hz", self._settings.frequency.sample_rate_hz),
            "frequencies_hz": frame.get("frequencies_hz") or [],
            "levels_db": levels_db,
            "data": [levels_db] if levels_db else [],
            "points": len(levels_db),
            "source": frame.get("source", "real_sdr"),
            "error": frame.get("error"),
        }

    def get_safety_limits(self) -> dict:
        return safety_status()

    def set_span(self, span_hz: float) -> dict:
        # span_hz is only how much of the already-acquired bandwidth is
        # displayed/analyzed -- independent of sample_rate_hz (the real
        # ADC/USRP acquisition rate a downstream decoder like BLE's Gate
        # 2A.2 depends on). Never touches sample_rate_hz; use
        # set_sample_rate() for that.
        validate_span(span_hz)
        if span_hz > self._settings.frequency.sample_rate_hz:
            raise RFSafetyError(
                f"span_hz ({span_hz:.0f}) cannot exceed the current sample_rate_hz "
                f"({self._settings.frequency.sample_rate_hz:.0f}); raise the sample rate first."
            )
        validate_frequency_window(self._settings.frequency.center_frequency_hz, span_hz)
        self._settings.set_span(span_hz)
        if real_spectrum_stream.is_running():
            real_spectrum_stream.apply_settings(self._settings)
        return {"status": "ok", "span_hz": span_hz}

    def set_sample_rate(self, sample_rate_hz: float) -> dict:
        # The real ADC/USRP acquisition rate -- independent of span_hz (the
        # display window). Raising this always succeeds; lowering it below
        # the current span_hz auto-narrows the span to match, since a view
        # can never be wider than what's actually sampled.
        validate_sample_rate(sample_rate_hz)
        self._settings.set_sample_rate(sample_rate_hz)
        if sample_rate_hz < self._settings.frequency.span_hz:
            self._settings.set_span(sample_rate_hz)
        if real_spectrum_stream.is_running():
            real_spectrum_stream.apply_settings(self._settings)
        return {
            "status": "ok",
            "sample_rate_hz": sample_rate_hz,
            "span_hz": self._settings.frequency.span_hz,
        }

    def set_center_frequency(self, frequency_hz: float) -> dict:
        validate_center_frequency(frequency_hz)
        validate_frequency_window(frequency_hz, self._settings.frequency.span_hz)
        self._settings.set_center_frequency(frequency_hz)
        if real_spectrum_stream.is_running():
            real_spectrum_stream.apply_settings(self._settings)
        return {
            "status": "ok",
            "center_frequency_hz": self._settings.frequency.center_frequency_hz,
            "start_frequency_hz": self._settings.frequency.start_frequency_hz,
            "stop_frequency_hz": self._settings.frequency.stop_frequency_hz,
        }

    def set_start_stop(self, start_frequency_hz: float, stop_frequency_hz: float) -> dict:
        center_frequency_hz, span_hz = validate_start_stop(start_frequency_hz, stop_frequency_hz)
        if span_hz > self._settings.frequency.sample_rate_hz:
            raise RFSafetyError(
                f"span_hz ({span_hz:.0f}) cannot exceed the current sample_rate_hz "
                f"({self._settings.frequency.sample_rate_hz:.0f}); raise the sample rate first."
            )
        self._settings.set_center_frequency(center_frequency_hz)
        self._settings.set_span(span_hz)
        if real_spectrum_stream.is_running():
            real_spectrum_stream.apply_settings(self._settings)
        return {
            "status": "ok",
            "center_frequency_hz": center_frequency_hz,
            "span_hz": span_hz,
            "start_frequency_hz": start_frequency_hz,
            "stop_frequency_hz": stop_frequency_hz,
        }

    def set_rbw(self, rbw_hz: float) -> dict:
        validate_rbw(rbw_hz)
        self._settings.set_rbw(rbw_hz)
        if real_spectrum_stream.is_running():
            real_spectrum_stream.apply_settings(self._settings)
        return {"status": "ok", "rbw_hz": rbw_hz}

    def set_vbw(self, vbw_hz: float) -> dict:
        validate_vbw(vbw_hz)
        self._settings.set_vbw(vbw_hz)
        if real_spectrum_stream.is_running():
            real_spectrum_stream.apply_settings(self._settings)
        return {"status": "ok", "vbw_hz": vbw_hz}

    def set_noise_floor_offset(self, noise_floor_offset_db: float) -> dict:
        self._settings.set_noise_floor_offset(noise_floor_offset_db)
        return {"status": "ok", "noise_floor_offset_db": noise_floor_offset_db}

    def set_reference_level(self, reference_level_db: float) -> dict:
        self._settings.set_reference_level(reference_level_db)
        return {"status": "ok", "reference_level_db": reference_level_db}

    def set_detector_mode(self, detector_mode: str) -> dict:
        allowed_modes = {"sample", "rms", "average", "peak", "min", "min_hold", "max_hold", "video"}
        if detector_mode not in allowed_modes:
            raise ValueError(f"detector_mode must be one of {sorted(allowed_modes)}")
        self._settings.set_detector_mode(detector_mode)
        return {"status": "ok", "detector_mode": detector_mode}

    def set_averaging(self, enabled: bool, averaging_factor: float | None = None) -> dict:
        self._settings.trace.averaging_enabled = enabled
        if averaging_factor is not None:
            if averaging_factor <= 0:
                raise ValueError("averaging_factor must be > 0")
            self._settings.trace.averaging_factor = averaging_factor
        return {"status": "ok", "averaging_enabled": enabled, "averaging_factor": averaging_factor}

    def validate_gain(self, gain_db: float) -> None:
        validate_gain(gain_db)

    def validate_sample_rate(self, sample_rate_hz: float) -> None:
        validate_span(sample_rate_hz)

    def execute_scpi(self, command: str) -> dict:
        normalized = command.strip().upper()
        match = re.fullmatch(r"SENS:FREQ:CENT\s+([0-9.]+)\s*(HZ|KHZ|MHZ|GHZ)?", normalized)
        if match:
            return self.set_center_frequency(self._scpi_number_to_hz(match.group(1), match.group(2)))

        match = re.fullmatch(r"SENS:FREQ:SPAN\s+([0-9.]+)\s*(HZ|KHZ|MHZ|GHZ)?", normalized)
        if match:
            return self.set_span(self._scpi_number_to_hz(match.group(1), match.group(2)))

        match = re.fullmatch(r"DISP:TRAC:Y:RLEV\s+([-0-9.]+)\s*(DB|DBM)?", normalized)
        if match:
            return self.set_reference_level(float(match.group(1)))

        match = re.fullmatch(r"DISP:TRAC:Y:SCAL:PDIV\s+([0-9.]+)\s*(DB)?", normalized)
        if match:
            value = float(match.group(1))
            if value <= 0:
                raise ValueError("dB per division must be > 0")
            return {"status": "ok", "db_per_div": value}

        raise ValueError(f"Unsupported SCPI command: {command}")

    def _scpi_number_to_hz(self, value: str, unit: str | None) -> float:
        multiplier = {
            None: 1.0,
            "HZ": 1.0,
            "KHZ": 1e3,
            "MHZ": 1e6,
            "GHZ": 1e9,
        }[unit]
        return float(value) * multiplier
