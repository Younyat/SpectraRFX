from __future__ import annotations

from typing import Any


REGION_DETECTORS = [
    {
        "id": "morphological_heuristic",
        "aliases": ["baseline_visual_region_detector", "morphological"],
        "name": "Morphological heuristic",
        "trainable": False,
        "default": True,
        "status": "available",
        "paper_reference": "Current RF-Fingerprint-Lab-v6 morphological heuristic detector",
        "role": "Permanent baseline and operational fallback",
    },
    {"id": "energy_based", "name": "Energy based", "trainable": False, "status": "planned_optional"},
    {"id": "ssd_waterfall", "name": "SSD waterfall", "trainable": True, "status": "not_implemented"},
    {"id": "faster_rcnn_waterfall", "name": "Faster R-CNN waterfall", "trainable": True, "status": "not_implemented"},
    {"id": "yolo_waterfall", "name": "YOLO waterfall", "trainable": True, "status": "not_implemented"},
]

REPRESENTATIONS = [
    "raw_iq",
    "amplitude_phase",
    "fft_psd",
    "spectrogram",
    "waterfall",
    "mfcc_lfcc",
    "physical_impairments",
    "bispectrum",
    "csp_scd",
    "ewt_subbands",
]

STAGE_1_CLASSES = [
    "noise_only",
    "unknown",
    "fm_broadcast",
    "am",
    "fsk",
    "gfsk",
    "psk_like",
    "qam_like",
    "ofdm_like",
    "wifi",
    "bluetooth",
    "lora",
    "zigbee",
    "subghz_narrowband",
    "satellite_telemetry",
    "cochannel_anomaly",
    "jammer_or_replay_like",
]

TECHNIQUES = [
    {
        "id": "E0",
        "family": "stage1_signal_recognition",
        "technique_name": "Current morphological heuristic detector",
        "paper_reference": "Current RF-Fingerprint-Lab-v6 implementation",
        "input_representation": "waterfall",
        "model_types": ["morphological_heuristic"],
        "implementation_status": "implemented",
        "objective": "Baseline visual region detection without training",
    },
    {
        "id": "S1",
        "family": "stage1_signal_recognition",
        "technique_name": "PSD and energy detection",
        "paper_reference": "O'Shea, Clancy and Ebeid",
        "input_representation": "fft_psd",
        "model_types": ["energy_detector", "thresholds"],
        "implementation_status": "not_implemented",
        "objective": "Practical occupancy and active-region detection",
    },
    {
        "id": "S2",
        "family": "stage1_signal_recognition",
        "technique_name": "SCD/CSP alpha-profile classification",
        "paper_reference": "O'Shea, Clancy and Ebeid",
        "input_representation": "csp_scd",
        "model_types": ["svm", "random_forest", "mlp"],
        "implementation_status": "not_implemented",
    },
    {
        "id": "S4",
        "family": "stage1_signal_recognition",
        "technique_name": "Unknown dynamic RF classification",
        "paper_reference": "Shi et al.",
        "input_representation": "spectrogram",
        "model_types": ["cnn2d", "autoencoder", "metric_learning"],
        "implementation_status": "not_implemented",
    },
    {
        "id": "E1",
        "family": "stage2_device_fingerprinting",
        "technique_name": "Raw IQ CNN fingerprinting",
        "paper_reference": "Riyaz et al.; Jian et al.",
        "input_representation": "raw_iq",
        "model_types": ["cnn1d", "resnet1d"],
        "implementation_status": "implemented_cnn1d_baseline",
    },
    {
        "id": "E2",
        "family": "stage2_device_fingerprinting",
        "technique_name": "Edge IQ Transformer",
        "paper_reference": "Hussain et al.",
        "input_representation": "raw_iq",
        "model_types": ["lightweight_cnn1d", "transformer_encoder"],
        "implementation_status": "not_implemented",
    },
    {
        "id": "E3",
        "family": "stage2_device_fingerprinting",
        "technique_name": "Spectrogram/waterfall CNN",
        "paper_reference": "Shen et al.; Lin et al.; Liu et al.; Bremnes et al.",
        "input_representation": "spectrogram",
        "model_types": ["simple_cnn2d", "resnet18", "vgg11"],
        "implementation_status": "implemented_simple_cnn2d_with_optional_torchvision_models",
    },
    {
        "id": "E5",
        "family": "stage2_device_fingerprinting",
        "technique_name": "PSD/MFCC/LFCC classical ML",
        "paper_reference": "Kilic et al.",
        "input_representation": "mfcc_lfcc",
        "model_types": ["svm", "random_forest", "knn"],
        "implementation_status": "partially_implemented_psd_basic",
    },
    {
        "id": "E8",
        "family": "stage2_device_fingerprinting",
        "technique_name": "Bispectrum and cyclostationary statistics",
        "paper_reference": "O'Shea et al.; Mehta et al.; Sivolenko et al.",
        "input_representation": "bispectrum",
        "model_types": ["svm", "mlp", "random_forest"],
        "implementation_status": "not_implemented",
    },
    {
        "id": "E9",
        "family": "open_set_spoofing",
        "technique_name": "Metric learning open-set fingerprinting",
        "paper_reference": "Shi et al.; Jian et al.",
        "input_representation": "raw_iq",
        "model_types": ["siamese", "triplet", "prototypical", "arcface_like"],
        "implementation_status": "not_implemented",
    },
    {
        "id": "E10",
        "family": "edge_inference",
        "technique_name": "Quantized edge inference",
        "paper_reference": "Hussain et al.",
        "input_representation": "raw_iq",
        "model_types": ["tflite", "quantized_cnn", "quantized_transformer"],
        "implementation_status": "not_implemented",
    },
]


class ExperimentRegistry:
    def overview(self) -> dict[str, Any]:
        return {
            "architecture_rule": "Current operational core remains stable; RF Experiment Lab is optional and removable.",
            "default_region_detector": "morphological_heuristic",
            "detector_modes": ["morphological_heuristic", "learned_detector", "hybrid"],
            "region_detectors": REGION_DETECTORS,
            "representations": REPRESENTATIONS,
            "stage_1_classes": STAGE_1_CLASSES,
            "techniques": TECHNIQUES,
            "scientific_boundaries": {
                "stage_1": "Signal family, modulation and protocol recognition only.",
                "stage_2": "Technology-specific physical transmitter fingerprinting only.",
                "forbidden_primary_split": "random_window_split",
            },
        }

    def list_techniques(self) -> list[dict[str, Any]]:
        return TECHNIQUES

    def list_region_detectors(self) -> list[dict[str, Any]]:
        return REGION_DETECTORS
