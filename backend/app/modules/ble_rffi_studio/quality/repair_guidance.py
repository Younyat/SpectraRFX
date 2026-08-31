"""'Corregir y repetir': when a capture doesn't reach an ELIGIBLE_AS_*
verdict, an operator with no RF background cannot be expected to guess why
from raw counters alone. This gives a short list of concrete, named causes
(matched against the same CaptureRecord/ExampleRecord facts
StudioRepository._capture_decision already computes) plus what to change
before repeating -- never a vague "capture failed".

Deliberately does NOT attempt to detect RF saturation or measure SNR
directly: those require sample-level power/amplitude statistics this module
never has (Evidence Stage only ever sees already-decoded packets, not raw
IQ power). `ble/capture/ble_rf_diagnostics.py` already computes exactly that
(clipping ratio, noise floor, PSD) from a capture's raw IQ file as a
separate, manual qualification tool -- LOW_SNR here is a proxy (CRC-invalid
packet ratio) precisely because that direct measurement isn't wired into
this automatic pipeline yet.
"""
from __future__ import annotations

from typing import Any

from ..contracts import CaptureRecord, ExampleRecord

_INSUFFICIENT_ACTIVITY_MIN_EXAMPLES = 3
_LOW_ELIGIBLE_RATE_THRESHOLD = 0.3
_LOW_SNR_FAILED_RATIO_THRESHOLD = 0.5


def repair_guidance(capture: CaptureRecord, examples: list[ExampleRecord], target_presence_status: str | None, decision_code: str | None = None) -> list[dict[str, str]]:
    """target_presence_status/decision_code are passed in (freshly computed
    by the caller, e.g. StudioRepository._capture_decision) rather than read
    off capture.target_presence_status -- that field is only a cached
    convenience copy written once by build_evidence(), and could be stale/
    never-set if evidence was written by any other path. Recomputing them
    here would require duplicating _capture_decision's own logic, so the
    caller supplies both."""
    guidance: list[dict[str, str]] = []

    if capture.discontinuities > 0:
        guidance.append({
            "code": "RF_DISCONTINUITIES",
            "message": f"Se detectaron {capture.discontinuities} discontinuidad(es) en la adquisicion RF (USB/B200). Revisa la conexion y repite.",
        })

    total = len(examples)
    if total < _INSUFFICIENT_ACTIVITY_MIN_EXAMPLES:
        guidance.append({
            "code": "INSUFFICIENT_BLE_ACTIVITY",
            "message": "Muy poca actividad BLE recuperada en esta captura. Aumenta la duracion maxima y repite.",
        })
    else:
        eligible = [e for e in examples if e.quality_status == "PASSED" and e.dataset_eligibility in ("PENDING_ANALYSIS", "ELIGIBLE")]
        if len(eligible) / total < _LOW_ELIGIBLE_RATE_THRESHOLD:
            guidance.append({
                "code": "LOW_ELIGIBLE_EXAMPLE_RATE",
                "message": "Baja proporcion de ejemplos elegibles frente al total capturado. Continua capturando o aumenta la duracion.",
            })
        failed_ratio = sum(1 for e in examples if e.quality_status == "FAILED") / total
        if failed_ratio > _LOW_SNR_FAILED_RATIO_THRESHOLD:
            guidance.append({
                "code": "LOW_SNR",
                "message": "Alta proporcion de paquetes con CRC invalido (posible SNR bajo). Revisa distancia, antena o ganancia.",
            })

    if capture.capture_purpose == "TARGET_DEVICE_ON" and target_presence_status == "NOT_DETECTED":
        guidance.append({
            "code": "TARGET_NOT_DETECTED",
            "message": "El dispositivo objetivo no aparecio en esta captura. Revisa alimentacion, canal, direccion registrada o aislamiento fisico.",
        })
    if capture.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL") and target_presence_status == "DETECTED":
        guidance.append({
            "code": "TARGET_DETECTED_DURING_BACKGROUND",
            "message": "El dispositivo declarado apagado/retirado fue detectado durante esta captura de entorno. Apaga o retira el dispositivo realmente y repite.",
        })
    if decision_code == "QUARANTINED_AMBIGUOUS":
        guidance.append({
            "code": "NATIVE_CORRELATION_AMBIGUOUS",
            "message": (
                "Mas de una observacion nativa de Windows coincidio en el mismo instante que un paquete B200 -- el sistema no "
                "puede saber con certeza cual corresponde (entorno con varios dispositivos BLE cercanos). Esto no se corrige "
                "repitiendo el analisis sobre la misma captura: declara aislamiento fisico si el dispositivo no tiene direccion "
                "estable, o repite la captura con menos dispositivos BLE activos cerca."
            ),
        })

    return guidance
