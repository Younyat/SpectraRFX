"""Pure, hardware-free classification logic for the two Guided Validation
hardware actions (Live Timing Diagnostic, Reinforced Target-Absence
Control). Kept separate from service.py's real hardware orchestration so
every branch of the diagnosis can be exercised with synthetic numbers,
never a real capture, in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

TIMING_DIAGNOSTIC_CODES = (
    "NATIVE_SCANNER_NOT_RUNNING",
    "NATIVE_SCANNER_COVERAGE_INSUFFICIENT",
    "TIMESTAMP_DOMAINS_INCOMPATIBLE",
    "TIME_GATE_TOO_NARROW",
    "DECODED_FIELDS_DO_NOT_MATCH",
    "MULTIPLE_COMPETING_CANDIDATES",
    "ASSOCIATION_CALIBRATION_POSSIBLE",
)

# Tight-cluster tolerance for detecting a systematic (constant) offset
# between the native and SDR timestamp domains, vs. genuinely scattered
# (no real timing relationship) residuals. Documented, not tuned against
# any real data -- there is none yet with a matched target address at
# this residual range.
_TIGHT_CLUSTER_IQR_MS = 100.0
_NARROW_GATE_EXTENSION_MS = 500.0  # a residual median below this, tightly clustered, reads as "gate too narrow"; above it, as a real offset.


@dataclass(frozen=True)
class TimingDiagnosisResult:
    code: str
    explanation: str
    next_action: str


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    index = q * (len(sorted_values) - 1)
    lower, upper = int(index), min(int(index) + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def classify_timing_diagnostic(
    *, native_event_count: int, target_native_event_count: int, target_address_packet_count: int,
    narrow_window_valid_count: int, narrow_window_ambiguous_count: int, wide_window_residuals_ms: Sequence[float],
    narrow_window_threshold_ms: float = 250.0,
) -> TimingDiagnosisResult:
    """Classifies ONE real (or synthetic, for tests) capture's timing
    relationship between native BLE observations and SDR-decoded packets.
    `wide_window_residuals_ms` are residuals for target-address-matched
    pairs computed WITHOUT the narrow_window_threshold_ms cap (a much wider
    search, e.g. the whole capture duration) -- only used once coverage and
    decode are already confirmed present. Never widens the real association
    threshold itself; this is diagnosis only."""
    if native_event_count == 0:
        return TimingDiagnosisResult(
            "NATIVE_SCANNER_NOT_RUNNING",
            "The native BLE scanner recorded zero events during the capture window.",
            "Verify the native adapter is connected and the scanner process starts correctly, then repeat the diagnostic.",
        )
    if target_native_event_count == 0:
        return TimingDiagnosisResult(
            "NATIVE_SCANNER_COVERAGE_INSUFFICIENT",
            "The native scanner was active and observed ambient traffic, but never observed the declared target device's own address.",
            "Confirm the device is powered, advertising, and within range of the native adapter, then repeat the diagnostic.",
        )
    if target_address_packet_count == 0:
        return TimingDiagnosisResult(
            "DECODED_FIELDS_DO_NOT_MATCH",
            "The SDR decoded packets during the capture, but none carried the declared target's own address.",
            "Verify the declared physical_unit_id and its bound address are correct, and that channel/receiver settings match the target's real advertising configuration.",
        )
    if narrow_window_valid_count > 0:
        if narrow_window_ambiguous_count > 0:
            return TimingDiagnosisResult(
                "MULTIPLE_COMPETING_CANDIDATES",
                "Some native-SDR pairs fall inside the accepted timing gate, but more than one candidate competes for the same native event.",
                "Investigate callback batching/duplicate policy before attempting to freeze an association policy from this capture alone.",
            )
        return TimingDiagnosisResult(
            "ASSOCIATION_CALIBRATION_POSSIBLE",
            "Native and SDR observations of the declared target were matched, uniquely, inside the accepted timing gate.",
            "This capture can contribute real calibration events toward Association Policy selection.",
        )

    # No pair falls inside the narrow gate -- decide between a systematic
    # offset (TIMESTAMP_DOMAINS_INCOMPATIBLE), a merely-too-strict gate
    # (TIME_GATE_TOO_NARROW), or genuinely poor coverage, using how tightly
    # the wide-window residuals cluster.
    residuals = sorted(wide_window_residuals_ms)
    if not residuals:
        return TimingDiagnosisResult(
            "NATIVE_SCANNER_COVERAGE_INSUFFICIENT",
            "Target-address packets and target native events both exist, but no pairing was found even in a wide search window.",
            "Check for a large clock discrepancy or a capture-duration mismatch between the native scanner and the SDR.",
        )
    median = _quantile(residuals, 0.5)
    iqr = _quantile(residuals, 0.75) - _quantile(residuals, 0.25)
    if iqr <= _TIGHT_CLUSTER_IQR_MS:
        if median <= _NARROW_GATE_EXTENSION_MS:
            return TimingDiagnosisResult(
                "TIME_GATE_TOO_NARROW",
                f"Native-SDR residuals cluster tightly around {median:.0f} ms, just outside the current {narrow_window_threshold_ms:.0f} ms gate.",
                "Association-policy selection remains blocked at the current threshold grid; consider whether the grid needs a value in this range -- never widen the running policy automatically.",
            )
        return TimingDiagnosisResult(
            "TIMESTAMP_DOMAINS_INCOMPATIBLE",
            f"Native-SDR residuals cluster tightly around a large, consistent offset (~{median:.0f} ms), suggesting a systematic timestamp misalignment rather than random delay.",
            "Association-policy selection remains blocked until the timestamp offset is corrected or explicitly modeled -- do not compensate by enlarging the threshold grid.",
        )
    return TimingDiagnosisResult(
        "NATIVE_SCANNER_COVERAGE_INSUFFICIENT",
        "Native-SDR residuals for the declared target are widely scattered even in a wide search window -- no reliable timing relationship was found.",
        "Investigate scanner coverage gaps or capture conditions before repeating the diagnostic.",
    )
