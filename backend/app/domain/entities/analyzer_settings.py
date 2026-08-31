from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


DetectorMode = Literal["sample", "rms", "average", "peak", "min", "min_hold", "max_hold", "video"]
DemodulationMode = Literal["off", "am", "fm", "wfm", "usb", "lsb", "cw"]
WindowType = Literal["rectangular", "hann", "hamming", "blackman"]
TraceMode = Literal["clear_write", "average", "max_hold", "min_hold"]


@dataclass(slots=True)
class FrequencySettings:
    center_frequency_hz: float
    span_hz: float
    sample_rate_hz: float
    start_frequency_hz: float = 0.0
    stop_frequency_hz: float = 0.0

    def __post_init__(self) -> None:
        self._validate()
        self.recalculate_edges()

    def _validate(self) -> None:
        if self.center_frequency_hz <= 0:
            raise ValueError("center_frequency_hz must be > 0")
        if self.span_hz <= 0:
            raise ValueError("span_hz must be > 0")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")

    def recalculate_edges(self) -> None:
        half_span = self.span_hz / 2.0
        self.start_frequency_hz = self.center_frequency_hz - half_span
        self.stop_frequency_hz = self.center_frequency_hz + half_span

    def set_center_frequency(self, value_hz: float) -> None:
        if value_hz <= 0:
            raise ValueError("center frequency must be > 0")
        self.center_frequency_hz = value_hz
        self.recalculate_edges()

    def set_span(self, value_hz: float) -> None:
        if value_hz <= 0:
            raise ValueError("span must be > 0")
        self.span_hz = value_hz
        self.recalculate_edges()

    def set_sample_rate(self, value_hz: float) -> None:
        if value_hz <= 0:
            raise ValueError("sample rate must be > 0")
        self.sample_rate_hz = value_hz


@dataclass(slots=True)
class GainSettings:
    gain_db: float
    agc_enabled: bool = False
    attenuation_db: float = 0.0
    preamp_enabled: bool = False

    def set_gain(self, value_db: float) -> None:
        self.gain_db = value_db

    def enable_agc(self) -> None:
        self.agc_enabled = True

    def disable_agc(self) -> None:
        self.agc_enabled = False


@dataclass(slots=True)
class TraceSettings:
    detector_mode: DetectorMode = "sample"
    trace_mode: TraceMode = "clear_write"
    averaging_enabled: bool = False
    averaging_factor: float = 0.2
    smoothing_enabled: bool = False
    smoothing_factor: float = 0.15
    max_hold_enabled: bool = False
    min_hold_enabled: bool = False

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not 0.0 < self.averaging_factor <= 1.0:
            raise ValueError("averaging_factor must be in (0, 1]")
        if not 0.0 < self.smoothing_factor <= 1.0:
            raise ValueError("smoothing_factor must be in (0, 1]")


@dataclass(slots=True)
class ResolutionSettings:
    fft_size: int = 4096
    fft_window: WindowType = "hann"
    rbw_hz: float = 10_000.0
    vbw_hz: float = 3_000.0

    def __post_init__(self) -> None:
        if self.fft_size <= 0:
            raise ValueError("fft_size must be > 0")
        if self.rbw_hz <= 0:
            raise ValueError("rbw_hz must be > 0")
        if self.vbw_hz <= 0:
            raise ValueError("vbw_hz must be > 0")


@dataclass(slots=True)
class DisplaySettings:
    reference_level_db: float = 10.0
    min_level_db: float = -140.0
    max_level_db: float = 10.0
    noise_floor_offset_db: float = 0.0
    waterfall_enabled: bool = True
    waterfall_history_size: int = 400
    color_map: str = "turbo"

    def __post_init__(self) -> None:
        if self.min_level_db >= self.max_level_db:
            raise ValueError("min_level_db must be lower than max_level_db")
        if self.waterfall_history_size <= 0:
            raise ValueError("waterfall_history_size must be > 0")


@dataclass(slots=True)
class FilterSettings:
    low_pass_enabled: bool = False
    low_pass_cutoff_hz: Optional[float] = None
    band_pass_enabled: bool = False
    band_pass_low_hz: Optional[float] = None
    band_pass_high_hz: Optional[float] = None
    notch_enabled: bool = False
    notch_center_hz: Optional[float] = None
    notch_width_hz: Optional[float] = None

    def validate(self) -> None:
        if self.low_pass_enabled and (self.low_pass_cutoff_hz is None or self.low_pass_cutoff_hz <= 0):
            raise ValueError("low_pass_cutoff_hz must be > 0 when low pass is enabled")

        if self.band_pass_enabled:
            if self.band_pass_low_hz is None or self.band_pass_high_hz is None:
                raise ValueError("band pass limits must be defined when band pass is enabled")
            if self.band_pass_low_hz >= self.band_pass_high_hz:
                raise ValueError("band_pass_low_hz must be lower than band_pass_high_hz")

        if self.notch_enabled:
            if self.notch_center_hz is None or self.notch_width_hz is None:
                raise ValueError("notch parameters must be defined when notch is enabled")
            if self.notch_width_hz <= 0:
                raise ValueError("notch_width_hz must be > 0")


@dataclass(slots=True)
class DemodulationSettings:
    mode: DemodulationMode = "off"
    audio_sample_rate_hz: int = 48_000
    squelch_enabled: bool = False
    squelch_threshold_db: float = -60.0

    def __post_init__(self) -> None:
        if self.audio_sample_rate_hz <= 0:
            raise ValueError("audio_sample_rate_hz must be > 0")


@dataclass(slots=True)
class AnalyzerSettings:
    frequency: FrequencySettings
    gain: GainSettings
    trace: TraceSettings = field(default_factory=TraceSettings)
    resolution: ResolutionSettings = field(default_factory=ResolutionSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    filters: FilterSettings = field(default_factory=FilterSettings)
    demodulation: DemodulationSettings = field(default_factory=DemodulationSettings)

    def set_center_frequency(self, value_hz: float) -> None:
        self.frequency.set_center_frequency(value_hz)

    def set_span(self, value_hz: float) -> None:
        self.frequency.set_span(value_hz)

    def set_sample_rate(self, value_hz: float) -> None:
        self.frequency.set_sample_rate(value_hz)

    def set_gain(self, value_db: float) -> None:
        self.gain.set_gain(value_db)

    def set_rbw(self, value_hz: float) -> None:
        if value_hz <= 0:
            raise ValueError("rbw must be > 0")
        self.resolution.rbw_hz = value_hz

    def set_vbw(self, value_hz: float) -> None:
        if value_hz <= 0:
            raise ValueError("vbw must be > 0")
        self.resolution.vbw_hz = value_hz

    def set_reference_level(self, value_db: float) -> None:
        self.display.reference_level_db = value_db

    def set_noise_floor_offset(self, value_db: float) -> None:
        self.display.noise_floor_offset_db = value_db

    def set_detector_mode(self, mode: DetectorMode) -> None:
        self.trace.detector_mode = mode

    def set_trace_mode(self, mode: TraceMode) -> None:
        self.trace.trace_mode = mode

    def set_demodulation_mode(self, mode: DemodulationMode) -> None:
        self.demodulation.mode = mode

    def validate(self) -> None:
        self.filters.validate()
