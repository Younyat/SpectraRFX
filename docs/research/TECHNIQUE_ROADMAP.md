# Technique roadmap (RF Experiment Lab)

This page lists techniques registered in `rf_experiment_lab`'s
`experiment_registry.py` that are **not implemented as executable
capabilities**, plus techniques implemented there but not part of any BLE-RFFI
Studio workflow. It exists so these ideas stay documented without being
presented, anywhere in the root README, as capabilities a visitor can
actually run today.

**These codes belong to `rf_experiment_lab`, a general RF-technique registry
evaluated on whatever RF captures are on hand — not all of them BLE, not all
of them device-fingerprinting.** BLE-RFFI Studio (the platform's BLE
device-identification workflow) uses none of these codes; its own vocabulary
is `ScientificTask`/RQ1–RQ4, documented in the root README and
[`docs/ble/SCIENTIFIC_STATUS.md`](../ble/SCIENTIFIC_STATUS.md).

States used here: `PLANNED` (designed, not started), `EXPLORATORY` (partial
code exists, not a reliable executable path), `NOT_IMPLEMENTED` (registry
entry only). None of these states is "implemented" or "validated" — see the
root README's Current scientific status table for what those two words
require.

| Code | Technique | State | Note |
|---|---|---|---|
| S1 | PSD/energy detection | NOT_IMPLEMENTED | Registry entry only, `experiment_registry.py` |
| S2 | SCD/CSP cyclostationary alpha-profile classification | NOT_IMPLEMENTED | Registry entry only |
| S4 | Unknown dynamic RF classification | NOT_IMPLEMENTED | Registry entry only |
| E2 | Edge IQ Transformer (lightweight CNN1D / transformer encoder) | NOT_IMPLEMENTED | Registry entry only |
| E8 | Bispectrum and cyclostationary statistics (SVM / MLP / RF) | NOT_IMPLEMENTED | Registry entry only |
| E9 | Metric-learning open-set fingerprinting (siamese / triplet / prototypical / ArcFace-like) | NOT_IMPLEMENTED | Registry entry only |
| E10 | Quantized edge inference (TFLite / quantized CNN / transformer) | NOT_IMPLEMENTED | Registry entry only |

For reference, the techniques in this same registry that **are** implemented
(E0, E1, E3, E5) are documented as real, executable RF Experiment Lab
capabilities in the root README's Platform section and in
[`docs/ble/SCIENTIFIC_STATUS.md`](../ble/SCIENTIFIC_STATUS.md) §1.1 — they are
not repeated here because this page is specifically the not-yet-implemented
list. There is no code named `E4` or `E6` in this registry; `E6` is a
structurally separate module (`e6_oracle_style`), and a legacy, unconnected
use of "E4" exists only in the superseded
[BLE Dataset Studio Pilot v1 record](../ble/PILOT_V1_LEGACY.md).

Adding a technique here to the executable platform requires: a real
implementation, wiring into the relevant module's workflow, and a real test
suite — the same bar every other implemented capability in this repository
already meets. A roadmap entry is never promoted to "implemented" in the root
README without that work actually landing.
