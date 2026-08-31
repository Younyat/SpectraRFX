# BLE Dataset Studio Pilot v1 (superseded)

**Superseded.** This document describes a frozen, early baseline that
predates the BLE-RFFI End-to-End Studio module. It does **not** describe the
current state of BLE work in this repository -- for that, see the root
[`README.md`](../../README.md)'s BLE-RFFI Studio section and
[`SCIENTIFIC_STATUS.md`](SCIENTIFIC_STATUS.md). This page is kept only as a
historical record of what this pilot once measured.

## Terminology used only in this pilot

`BLE Dataset Studio Pilot v1` used its own campaign-status vocabulary --
**a separate, older scale from the RF Experiment Lab E0-E10/S1/S2/S4 codes
documented in the root README's Terminology section.** The two share digits
but not meaning, and must never be conflated.

- **Evidence-level ladder** (`E1`-`E4`, cumulative, each level implying the
  ones below it -- source:
  `backend/app/infrastructure/ble/dataset_studio_manager.py`): `E1` = BLE
  activity detected at all; `E2` = at least one CRC-valid decoded packet;
  `E3` = the native Windows Bluetooth scan and the B200 decode corroborate
  the same event; `E4` = the corroborated packet's address matches the
  declared target device (logical device identification / RF-fingerprint-
  ready evidence).
- **Positive E4 campaign**: a session run with the target device present
  that reached evidence level `E4`.
- **Exploratory E2 campaign**: a session run to search for a target that
  reached at least evidence level `E2`.
- **Declared negative control**: a session where the operator declared the
  target absent, with no false positive attribution.
- **Reinforced negative control**: a declared negative control run
  *alongside* an active positive reference, so "no detection" is shown to
  mean "correctly absent," not "receiver was not working."
- **Clean capture**: a session with zero recorded RF overflows or
  discontinuities.

## Last-measured state

A historical record, not re-verified against live data -- see the
reproducibility note below for why.

- Historical campaigns: 3.
- Generated examples: 338.
- Included examples: 0.
- Quarantined examples: 338.
- Positive E4 campaign: `PASSED_SINGLE_RUN`.
- Exploratory E2 campaign: `PASSED`.
- Declared negative control: `PASSED_SINGLE_RUN`.
- Reinforced negative control: `PENDING`.
- Clean captures: `PENDING`.
- Training: `NOT_READY`.
- Fingerprinting: `NOT_VALIDATED`.

The frozen 30-second protocol and its hashes below belong only to this BLE
Dataset Studio pilot. They were never the definitive scientific protocol for
the whole SpectraRFˣ platform.

## Reproducibility note (checked directly against disk, 2026-08-07)

**This pilot's underlying artifacts are no longer present, and the hashes
below cannot currently be re-verified.**

- Frozen pilot protocol SHA-256
  (`752bb3b437ccf6500376366774a330ea626cd06bc5b4429632b311997c3511f1`): no
  file with this hash exists anywhere in the repository or local storage
  today; the string is recorded only here.
- `BLE-IQ-ce737e9e9711` (claimed data SHA-256
  `9e24df1820de5d569578faa61a8dbe4a2fe59ee9bdcfbf1bdc88ec4f5181d2bf`): the
  original raw capture no longer exists at its expected path. One derived
  fragment (`burst-000013.cf32`, a single extracted burst, not the whole
  capture) survives under an unrelated dataset export directory
  (`ble_lab/datasets/BLE-EVIDENCE-DS01/1.0.0/exports/e4-c7b5c35d/iq_segments/`),
  which is not what this hash was computed against.
- `BLE-IQ-e5615d8d54cc` (claimed data SHA-256
  `1361b16462b05938c90fc37ae8353bee01d056156bec0145a6b4c94f96efda64`): not
  found anywhere in local storage.
- `BLE-IQ-cf8a55ff592f` (claimed data SHA-256
  `dd8c8daaa6eee968361abb9ee7aa52c10830f58f288affbe5d5f6006474914e9`): not
  found anywhere in local storage.

These captures were most likely removed by a later, unrelated storage
cleanup; nothing indicates the hashes themselves were ever wrong, only that
the files they describe are gone now. Do not cite this pilot's specific hash
values as independently reproducible evidence going forward -- cite the
current, on-disk, re-verifiable BLE-RFFI Studio and Guided BLE Scientific
Validation evidence documented in the root README and
[`SCIENTIFIC_STATUS.md`](SCIENTIFIC_STATUS.md) instead.
