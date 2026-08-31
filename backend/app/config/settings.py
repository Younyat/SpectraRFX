from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import List

from app.config.runtime_settings import apply_runtime_environment, get_runtime_value


apply_runtime_environment()


@dataclass(slots=True, frozen=True)
class AppSettings:
    app_name: str = "Spectrum Lab"
    app_version: str = "0.1.0"
    debug: bool = True


@dataclass(slots=True, frozen=True)
class ApiSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    base_path: str = "/api"
    ws_base_path: str = "/ws"
    cors_allowed_origins: List[str] = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )


@dataclass(slots=True, frozen=True)
class StorageSettings:
    project_root: Path
    workspace_root: Path
    backend_root: Path
    app_root: Path
    infrastructure_root: Path
    persistence_root: Path
    storage_root: Path
    recordings_dir: Path
    sessions_dir: Path
    presets_dir: Path
    temp_dir: Path
    fingerprinting_dir: Path
    mlops_dir: Path
    mlops_scripts_dir: Path
    backend_requirements_path: Path


@dataclass(slots=True, frozen=True)
class DefaultDeviceSettings:
    driver: str = "uhd"
    device_args: str = ""
    antenna: str = "RX2"
    channel_index: int = 0
    sample_rate_hz: float = 2_000_000.0
    center_frequency_hz: float = 89_400_000.0
    span_hz: float = 2_000_000.0
    gain_db: float = 20.0
    agc_enabled: bool = False
    ppm_correction: float = 0.0


@dataclass(slots=True, frozen=True)
class DefaultSpectrumSettings:
    fft_size: int = 4096
    fft_window: str = "hann"
    trace_points: int = 4096
    reference_level_db: float = 10.0
    min_level_db: float = -140.0
    max_level_db: float = 10.0
    averaging_enabled: bool = False
    averaging_factor: float = 0.2
    detector_mode: str = "sample"
    max_hold_enabled: bool = False
    min_hold_enabled: bool = False
    smoothing_enabled: bool = False
    smoothing_factor: float = 0.15
    rbw_hz: float = 10_000.0
    vbw_hz: float = 3_000.0
    noise_floor_offset_db: float = 0.0


@dataclass(slots=True, frozen=True)
class DefaultWaterfallSettings:
    enabled: bool = True
    history_size: int = 400
    min_level_db: float = -140.0
    max_level_db: float = 10.0
    color_map: str = "turbo"


@dataclass(slots=True, frozen=True)
class DefaultRecordingSettings:
    iq_enabled: bool = True
    audio_enabled: bool = False
    iq_format: str = "complex64_fc32_interleaved"
    audio_format: str = "wav_pcm16_mono"
    default_duration_seconds: float = 10.0


@dataclass(slots=True, frozen=True)
class DefaultDemodulationSettings:
    mode: str = "off"
    audio_sample_rate_hz: int = 48_000
    fm_deviation_hz: float = 75_000.0
    am_cutoff_hz: float = 10_000.0
    squelch_enabled: bool = False
    squelch_threshold_db: float = -60.0


@dataclass(slots=True, frozen=True)
class LoggingSettings:
    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


@dataclass(slots=True, frozen=True)
class Settings:
    app: AppSettings
    api: ApiSettings
    storage: StorageSettings
    default_device: DefaultDeviceSettings
    default_spectrum: DefaultSpectrumSettings
    default_waterfall: DefaultWaterfallSettings
    default_recording: DefaultRecordingSettings
    default_demodulation: DefaultDemodulationSettings
    logging: LoggingSettings


def _build_storage_settings() -> StorageSettings:
    app_root = Path(__file__).resolve().parents[1]
    backend_root = app_root.parent
    project_root = backend_root.parent
    workspace_root = project_root.parent
    infrastructure_root = app_root / "infrastructure"
    persistence_root = infrastructure_root / "persistence"
    storage_root = persistence_root / "storage"

    recordings_dir = storage_root / "recordings"
    sessions_dir = storage_root / "sessions"
    presets_dir = storage_root / "presets"
    temp_dir = storage_root / "temp"
    fingerprinting_dir = storage_root / "fingerprinting"
    mlops_dir = storage_root / "mlops"
    mlops_scripts_dir = app_root / "infrastructure" / "scripts"
    backend_requirements_path = backend_root / "requirements.mlops.txt"

    for path in (
        storage_root,
        recordings_dir,
        sessions_dir,
        presets_dir,
        temp_dir,
        fingerprinting_dir,
        mlops_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    return StorageSettings(
        project_root=project_root,
        workspace_root=workspace_root,
        backend_root=backend_root,
        app_root=app_root,
        infrastructure_root=infrastructure_root,
        persistence_root=persistence_root,
        storage_root=storage_root,
        recordings_dir=recordings_dir,
        sessions_dir=sessions_dir,
        presets_dir=presets_dir,
        temp_dir=temp_dir,
        fingerprinting_dir=fingerprinting_dir,
        mlops_dir=mlops_dir,
        mlops_scripts_dir=mlops_scripts_dir,
        backend_requirements_path=backend_requirements_path,
    )


def build_settings() -> Settings:
    return Settings(
        app=AppSettings(),
        api=ApiSettings(),
        storage=_build_storage_settings(),
        default_device=DefaultDeviceSettings(
            center_frequency_hz=float(get_runtime_value("DEFAULT_CENTER_FREQUENCY_HZ", 89_400_000.0)),
            # 4 MSps by default: matches ble-worker-lab's hardcoded
            # INTERNAL_SAMPLE_RATE_HZ requirement (BLE Gate 2A.2 decode
            # fails silently at any other rate -- see
            # real_spectrum_stream.py's SAMPLE_RATE_MISMATCH check) and
            # gives WiFi/Zigbee/other 2.4 GHz protocol work the same
            # acquisition bandwidth without a manual step. span_hz (the
            # displayed/analyzed window) is independent and defaults to the
            # same value only so default visual behavior is unchanged.
            sample_rate_hz=float(get_runtime_value("DEFAULT_SAMPLE_RATE_HZ", 4_000_000.0)),
            span_hz=float(get_runtime_value("DEFAULT_SPAN_HZ", 4_000_000.0)),
            gain_db=float(get_runtime_value("DEFAULT_GAIN_DB", 20.0)),
            antenna=str(get_runtime_value("DEFAULT_ANTENNA", "RX2")),
            device_args=str(get_runtime_value("UHD_DEVICE_ARGS", "")),
        ),
        default_spectrum=DefaultSpectrumSettings(
            rbw_hz=float(get_runtime_value("DEFAULT_RBW_HZ", 10_000.0)),
            vbw_hz=float(get_runtime_value("DEFAULT_VBW_HZ", 3_000.0)),
            reference_level_db=float(get_runtime_value("DEFAULT_REFERENCE_LEVEL_DB", 10.0)),
            averaging_factor=float(get_runtime_value("DEFAULT_AVERAGING_FACTOR", 0.2)),
            smoothing_factor=float(get_runtime_value("DEFAULT_SMOOTHING_FACTOR", 0.15)),
            noise_floor_offset_db=float(get_runtime_value("DEFAULT_NOISE_FLOOR_OFFSET_DB", 0.0)),
        ),
        default_waterfall=DefaultWaterfallSettings(
            history_size=int(get_runtime_value("DEFAULT_WATERFALL_HISTORY_SIZE", 400)),
        ),
        default_recording=DefaultRecordingSettings(
            default_duration_seconds=float(get_runtime_value("DEFAULT_RECORDING_DURATION_SECONDS", 10.0)),
        ),
        default_demodulation=DefaultDemodulationSettings(
            audio_sample_rate_hz=int(get_runtime_value("DEFAULT_AUDIO_SAMPLE_RATE_HZ", 48_000)),
            fm_deviation_hz=float(get_runtime_value("DEFAULT_FM_DEVIATION_HZ", 75_000.0)),
        ),
        logging=LoggingSettings(),
    )


settings = build_settings()
