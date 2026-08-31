import importlib.util
import sys
import types
import tempfile
from pathlib import Path


def load_fingerprinting_service_class() -> type:
    rf_intelligence_pkg = types.ModuleType("app.modules.rf_intelligence")
    rf_intelligence_pkg.__path__ = []
    knowledge_base = types.ModuleType("app.modules.rf_intelligence.knowledge_base")
    knowledge_base.resolve_band_profile = lambda **_: {"defaults": {}}
    sys.modules["app.modules.rf_intelligence"] = rf_intelligence_pkg
    sys.modules["app.modules.rf_intelligence.knowledge_base"] = knowledge_base
    service_path = Path(__file__).resolve().parents[2] / "modules" / "fingerprinting" / "service.py"
    spec = importlib.util.spec_from_file_location("fingerprinting_service_module", service_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FingerprintingService


def test_burst_rf_v1_spectral_peak_detection_uses_warnings_not_doubtful() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 17.06,
        "estimated_snr_db": 17.06,
        "clipping_pct": 0.0,
        "silence_pct": 0.0,
        "burst_duration_ms": 10.0,
        "occupied_bandwidth_hz": 329_346.0,
        "effective_bandwidth_hz": 332_329.0,
        "capture_band_edge_margin_hz": 54_039.0,
        "frequency_offset_ratio_of_capture_band": 0.675,
        "signal_within_capture_band": True,
        "method": "spectral_peak_detection",
    }

    result = service._evaluate_quality(
        metrics,
        operator_decision=None,
        label_status="strong_label",
        metadata_check={"valid": True, "missing": []},
    )

    assert result["status"] == "valid"
    assert result["reasons"] == []
    assert "occupied_bandwidth_near_capture_limit" in result["flags"]
    assert "peak_not_ideally_centered" in result["flags"]


def test_pre_post_qc_mismatch_is_warning_not_reason() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 18.0,
        "estimated_snr_db": 18.0,
        "clipping_pct": 0.0,
        "silence_pct": 0.0,
        "burst_duration_ms": 10.0,
        "occupied_bandwidth_hz": 330_000.0,
        "effective_bandwidth_hz": 332_000.0,
        "capture_band_edge_margin_hz": 80_000.0,
        "frequency_offset_ratio_of_capture_band": 0.5,
        "signal_within_capture_band": True,
        "method": "spectral_peak_detection",
        "live_offset_hz": 100_000.0,
        "frequency_offset_hz": 50_000.0,
    }

    result = service._evaluate_quality(
        metrics,
        operator_decision=None,
        label_status="strong_label",
        metadata_check={"valid": True, "missing": []},
    )

    assert result["status"] == "valid"
    assert "pre_post_qc_mismatch" in result["flags"]
    assert "pre_post_qc_mismatch" not in result["reasons"]


def test_high_margin_burst_rf_capture_with_occupied_bandwidth_warning_is_valid() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 16.5,
        "estimated_snr_db": 16.5,
        "clipping_pct": 0.0,
        "silence_pct": 0.0,
        "burst_duration_ms": 10.0,
        "occupied_bandwidth_hz": 370_840.0,
        "effective_bandwidth_hz": 374_584.0,
        "capture_band_edge_margin_hz": 97_970.0,
        "frequency_offset_ratio_of_capture_band": 0.239,
        "signal_within_capture_band": True,
        "method": "spectral_peak_detection",
        "live_offset_hz": 0.0,
        "frequency_offset_hz": 0.0,
    }

    result = service._evaluate_quality(
        metrics,
        operator_decision=None,
        label_status="strong_label",
        metadata_check={"valid": True, "missing": []},
    )

    assert result["status"] == "valid"
    assert result["reasons"] == []
    assert "occupied_bandwidth_near_capture_limit" in result["flags"]


def test_marker_confined_lora_offset_warning_stays_training_ready() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 28.2,
        "estimated_snr_db": 28.2,
        "clipping_pct": 0.0,
        "silence_pct": 63.8,
        "burst_duration_ms": 134.9,
        "occupied_bandwidth_hz": 163_220.0,
        "effective_bandwidth_hz": 699_935.0,
        "capture_band_edge_margin_hz": 273_832.0,
        "frequency_offset_ratio_of_capture_band": 0.218,
        "frequency_offset_hz": -76_136.0,
        "live_offset_hz": 157_226.0,
        "signal_within_capture_band": True,
        "method": "auto_energy_burst",
    }

    result = service._evaluate_quality(
        metrics,
        operator_decision=None,
        label_status="strong_label",
        metadata_check={"valid": True, "missing": []},
    )

    assert result["status"] == "valid"
    assert result["capture_quality"] == "valid"
    assert result["review_status"] == "accepted"
    assert result["training_readiness"] == "ready_for_training"
    assert "profile_frequency_offset_warning" in result["flags"]
    assert "pre_post_qc_mismatch" in result["flags"]
    assert "profile_frequency_offset_limit_exceeded" not in result["reasons"]


def test_marker_confined_ble_near_full_bandwidth_stays_training_ready() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 19.5,
        "estimated_snr_db": 19.5,
        "clipping_pct": 0.0,
        "silence_pct": 52.3,
        "burst_duration_ms": 500.0,
        "occupied_bandwidth_hz": 1_965_824.0,
        "effective_bandwidth_hz": 2_000_000.0,
        "capture_band_edge_margin_hz": 774_624.0,
        "frequency_offset_ratio_of_capture_band": 0.225,
        "frequency_offset_hz": 225_376.0,
        "live_offset_hz": 0.0,
        "signal_within_capture_band": True,
        "method": "auto_energy_burst",
    }

    result = service._evaluate_quality(
        metrics,
        operator_decision=None,
        label_status="strong_label",
        metadata_check={"valid": True, "missing": []},
    )

    assert result["status"] == "valid"
    assert result["capture_quality"] == "valid"
    assert result["review_status"] == "accepted"
    assert result["training_readiness"] == "ready_for_training"
    assert "occupied_bandwidth_near_capture_limit" in result["flags"]
    assert "profile_frequency_offset_warning" in result["flags"]
    assert "profile_frequency_offset_limit_exceeded" not in result["reasons"]

