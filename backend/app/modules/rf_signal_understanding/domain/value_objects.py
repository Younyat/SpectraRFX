from __future__ import annotations

from typing import Literal


SignalLabel = Literal[
    "fm_broadcast_like",
    "ook_like",
    "fsk_like",
    "psk_like",
    "ofdm_like",
    "frequency_hopping_like",
    "spread_spectrum_like",
    "narrowband_iot_like",
    "wideband_noise_like",
    "wifi_like",
    "bluetooth_like",
    "zigbee_like",
    "lte_like",
    "unknown",
    "ambiguous",
]

DecisionStatus = Literal["accepted", "ambiguous", "unknown", "rejected"]

VALIDATION_TASKS = {
    "region_detection": ["iou", "map", "precision", "recall", "false_positive_rate", "false_negative_rate"],
    "signal_type_classification": ["accuracy", "macro_f1", "confusion_matrix", "top_k_accuracy", "unknown_detection_rate"],
    "robustness": [
        "accuracy_by_snr",
        "accuracy_by_gain",
        "accuracy_by_session",
        "accuracy_by_day",
        "accuracy_by_center_frequency",
        "accuracy_by_environment",
    ],
    "transmitter_identification": [
        "closed_set_accuracy",
        "open_set_auroc",
        "eer",
        "false_accept_rate",
        "false_reject_rate",
    ],
}
