# BLE-RFFI Studio: preprocessing specification

Full derivation and code references for the preprocessing profiles the root
README only summarizes. Source: `backend/app/modules/ble_rffi_studio/preprocessing/`
(registry: `base_preprocessing_registry.py`).

**Profile actually used for every real result** (RQ1, RQ2, the decision-window
check, and the RQ4 exploratory FULL_BURST/PRE_PDU control — see
[`docs/ble/TECHNICAL_EVIDENCE_AUDIT.md`](TECHNICAL_EVIDENCE_AUDIT.md)) is
**`base-v1`** — identity preprocessing, no signal-altering step. Neither
`paper-eq6-7-v1` below nor its heuristic predecessor produced any currently
reported number.

## `paper-eq6-7-v1` — paper-compliant affine phase/frequency compensation

**Status: IMPLEMENTED AND TESTED. Not used to produce any current result** —
no real closed-set training run has ever used this profile; every real
bundle behind RQ1/RQ2/RQ4 was trained under `base-v1` (identity). This
section documents what the implementation does when enabled, for its
intended future methodological role — not what produced today's numbers.

Implementation: `preprocessing/paper_compliant_cfo.py`.

1. **`q[n]`** — a frozen BLE reference: the ideal GFSK-modulated
   preamble + access-address waveform (LE 1M PHY, Gaussian pulse BT=0.5,
   modulation index h=0.5), built once from fixed, known bits. The
   advertising-channel access address is fixed at `0x8E89BED6` for every real
   advertising packet (Bluetooth Core Spec Vol 6 Part B 1.4.1); the preamble
   byte (`0xAA`/`0x55`) is deterministically implied by the access address's
   first-transmitted bit (Vol 6 Part B 2.1.2). `q[n]` is therefore the same
   waveform for every burst at a given sample rate — never fit to the
   observed signal.
2. **`z_b[n] = x_b[n] · q*[n]`** — the observed burst multiplied by the
   conjugated reference, evaluated only over the frozen index set below.
3. **`ψ_b[n] = unwrap(angle(z_b[n]))`** — the unwrapped phase of `z_b`.
4. **`I_b`** — the frozen fitting interval: the burst's own `PRE_PDU` sample
   range (`packet_content/field_mapping.py`'s `PRE_PDU_BITS = 40`,
   preamble + access address) — the only span of a real advertising burst
   whose bit content is known and fixed, so it is the only span a known
   reference can be correlated against.
5. **Joint least-squares estimation** of `(φ_b0, f_b)` such that
   `ψ_b[n] ≈ φ_b0 + 2π·f_b·n/Fs` over `I_b`, via `np.linalg.lstsq` — a real
   joint regression, not a mean-slope or single-sample approximation.
6. **Affine compensation**, applied to the *whole* burst window (not just
   `I_b`):
   `x̃_b[n] = x_b[n] · exp(-j(φ_b0 + 2π·f_b·n/Fs))`.

**Per-burst provenance** (persisted, never discarded): `profile_id`,
`reference_waveform_version`, `reference_waveform_hash` (SHA-256 of `q[n]`),
`index_set` (`I_b`, as absolute sample bounds), `phi_b0`, `f_b_hz`,
`sample_rate_sps`, `compensation_status` (`APPLIED` or
`SKIPPED_WINDOW_SHORTER_THAN_I_B`, never a fabricated value for a window too
short to fit). Training writes one row per example to
`training_runs/<run>/preprocessing_provenance.jsonl`; offline inference
attaches the same structure to each scored decision. TRAIN and inference
call the exact same function
(`apply_base_preprocessing_with_provenance`) — never two implementations.

## `offset-retaining-v1` — sensitivity-analysis counterpart, not currently informative

Identity preprocessing (no step enabled) under its own, intentionally
distinct `profile_id` — the deliberate "what if we don't correct the
offset" comparison, *intended* to be run against `paper-eq6-7-v1`.

**Real finding (2026-08-22 audit):** `offset-retaining-v1` and `base-v1`
both resolve to the exact same flags in the registry (every flag `False`).
Because the real PRIMARY run itself already uses `base-v1`, the
`offset-retaining-v1` sensitivity run is **behaviorally identical** to
PRIMARY at the signal-processing level — the two are not distinguishable,
and any equality between their reported balanced accuracies
(`delta_vs_primary = 0.0` in `sensitivity_report.json`) is a trivial
consequence of that equivalence, not a validated finding that affine phase
compensation leaves the result unchanged. A real ablation of
`paper-eq6-7-v1` against `base-v1` remains a valid and useful future
comparison; it has not been run.

## `cfo-compensated-v1` — heuristic/legacy compensation, not Eq.(6)-(7)

An older, simpler correction (mean phase-step CFO over the whole window +
first-sample phase zeroing) kept only for historical/ablation utility. It
has **no** reference waveform, **no** frozen index set, **no** joint
regression, and **no** per-burst persisted parameters. It must never be
described as an implementation of Eq.(6)-(7) — see
`scientific_basis/preprocessing_evidence.json`'s own justification note for
this profile, which states the distinction explicitly.

## `cfo_estimate_hz` (engineered feature) — not the same estimator as `paper-eq6-7-v1`

One of the ten `engineered_rf` descriptors (`representation_profiles.py`,
`FEATURE_NAMES`), computed by `base_preprocessing.py::estimate_cfo_hz()`.
Despite the name, it is **not** an implementation of Eq.(6)-(7) above and
must not be read as a validated transmitter-CFO measurement: it is the mean
sample-to-sample unwrapped phase increment over the **whole** burst — no
reference correlation, no restriction to the known-bit `I_b` span, no
least-squares fit. Best described as an *apparent mean phase rate /
frequency-offset estimate*. Computed on the unprocessed (`base-v1`) burst
for every real run to date, so it can mix GFSK modulation phase structure,
true transmitter frequency offset, and the B200 receiver's own
local-oscillator offset — none of which it separates. To defensibly call a
value here "transmitter CFO" would require reference correlation over `I_b`
(as `paper-eq6-7-v1` does), an independently calibrated receiver LO offset
to subtract, and stability validation across repeated captures — none of
which is done here.

## Justification gate

No preprocessing step that alters the signal runs unless
`scientific_basis/preprocessing_evidence.json` records a real
`justified_by_technique_id` for it, checked in code
(`BasePreprocessingProfile.validate_justifications`) — a step cannot be
silently enabled without an on-file justification, and a fabricated
citation is explicitly forbidden by the same file's own policy note.
