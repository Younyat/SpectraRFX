# Scientific contribution and prior art

RF fingerprinting of wireless transmitters is an established research area.
This page states plainly what SpectraRFˣ does and does not claim to
contribute, so the root README's summary is not read as a novelty claim it
cannot back.

## What is established prior art, not a contribution of this project

- RF fingerprinting itself, as a research direction, is established prior
  art.
- Raw-I/Q CNN fingerprinting, STFT/CNN2D fingerprinting, and classical
  engineered-feature classifiers (PSD/spectral statistics + SVM/random
  forest/logistic regression) are all established techniques with existing
  literature, independently of this repository.
- BLE-specific RF fingerprinting, receiver/channel-sensitivity studies of RF
  fingerprints, and power-cycle/temporal-drift sensitivity of RF fingerprints
  all have prior art elsewhere.

SpectraRFˣ does not claim to have originated any of the individual
techniques above.

## What this project's BLE-RFFI Studio workflow actually integrates

The more defensible contribution is the **controlled integration**, in one
real, working BLE source-comparison pipeline over genuine USRP B200
acquisitions, of:

- Explicit **acquisition-dependence measurement** (RQ1: related capture vs.
  independent capture vs. a protected future period), instead of reporting
  one TEST score without checking whether it depended on incidental
  acquisition context.
- A **protected, single-use future evaluation** mechanism (TRAIN →
  VALIDATION → FREEZE → FUTURE TEST), with a real, hash-chained holdout
  access log and non-confirmatory bundles explicitly and permanently marked
  as such — not just a train/test split by convention.
- **Transmitter-state intervention** (RQ3: RESET vs. CONTINUOUS/CONTROL
  arms), with receiver-epoch-aware pairing that invalidates a PRE/POST pair
  when the qualified receiver state changed between the two captures.
- **BLE packet-content controls** (RQ4: FULL_BURST / ADVA_EXCLUDED /
  PRE_PDU), testing whether a classifier is using genuine RF characteristics
  rather than easily-copied packet content, with a reproducible field-to-
  sample mapping derived from the actually-decoded PDU rather than assumed.
- **Evidence lineage** from raw I/Q through to a final decision (capture →
  candidate → packet → example → dataset → split → preprocessing →
  model bundle → decision → inference manifest), auditable end to end.

None of these four elements is claimed to be individually novel in the
research literature. The claim is narrower: this repository integrates them
together, with real code and real tests, into one working BLE-RFFI pipeline,
rather than treating any one of them as a solved side detail.

## Terms this project deliberately avoids making as unqualified claims

`first`, `receiver-invariant`, `channel-invariant`, `validated forensic
attribution`, `validated real-time identification`. Where any of these ideas
is discussed anywhere in this repository's documentation, it is stated as an
open question or an explicit non-claim, never as an achieved result — see
the root README's Current scientific status table and
[`docs/ble/SCIENTIFIC_STATUS.md`](../ble/SCIENTIFIC_STATUS.md) for the exact,
current, evidence-backed state of every capability.

## Detailed prior-art / novelty audit

A field-by-field comparison against specific prior work is a substantially
larger undertaking than this page attempts, and does not currently exist as
a completed document in this repository. This page states the intended
positioning; it is not itself the literature review.
