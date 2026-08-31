# Bluetooth Low Energy (BLE) — technical README

Audience: a programmer with **no prior context** who needs to understand,
reproduce, extend, or debug BLE work in this platform.

Status honesty, up front, and more important here than anywhere else in this
repo: **there are two separate BLE efforts, at very different maturity
levels, and they must not be conflated.**

1. A **frozen Gate 1B validated-bitstream-replay pipeline** is fully
   integrated into spectrum-lab today (`/ble-lab`). It replays a fixed,
   known-good set of test vectors through the real BLE bit-conversion / CRC /
   PDU-parsing code, and exercises the full job → artifact → visualization →
   PCAPNG-export pipeline end to end. **It does not touch RF or IQ at all.**
   It exists to prove the platform-integration plumbing works, using inputs
   whose correct answer is already known.
2. A **separate, active, NOT-frozen DSP/IQ-recovery development effort**
   (fractional timing synchronization, Gate 2A.2) is in progress in an
   external, isolated repository (`C:\Users\Usuario\ble-worker-lab`, and a
   distinct frozen snapshot `C:\Users\Usuario\ble-worker-gate1b-frozen` used
   by effort #1 above). This is real over-the-air BLE demodulation work.
   **An experimental, off-by-default "analyze an existing IQ file" bridge
   into this effort is now integrated** (§2.10) — but SDR capture and
   combined capture+decode remain **explicitly not allowed**:
   `iq_capture` and `capture_and_decode` must stay disabled,
   `iq_recovery_validated` and `ota_validated` must stay `false`, until a
   receiver candidate is frozen and passes an independent holdout evaluation
   it has never seen.

If you're asked to "add BLE capture" or "make BLE demodulate real IQ from a
live SDR," that is **not** what §2.10 does (it only analyzes an
already-existing file, offline) and it is **not ready** — read §3 before
doing anything that would look like enabling live capture.

---

## 1. Effort #1: Gate 1B validated bitstream replay (integrated today)

### 1.1 What it actually proves

`ble-worker-gate1b-frozen` (commit `7b685f7fb0d161be6577d862711456532dcb3528`,
pinned) contains real, tested BLE Link Layer bit-conversion, CRC-24, and
Advertising PDU semantic-parsing code. The replay worker
(`backend/tools/ble_gate1b_replay_worker.py`) loads two frozen JSON test
vector files from that repo (`test_vectors/independent/
gate1b_semantic_vectors.json` and `test_vectors/official/
gate1b_semantic_vectors.json`), feeds each vector's known PDU bytes through
the real `ble_worker.bit_conversions`/`ble_worker.crc`/
`ble_worker.legacy_pdu_parser` code, and produces the same artifact shape a
real receiver job would: confirmed packets, parsed semantic records,
advertisements, advertiser addresses, a rejection/diagnostics summary, and a
proper `capture.pcapng` (LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR, openable in
Wireshark). Gates already passed at this stage:

```text
bit_true_gate               = passed
link_layer_bitstream_gate   = passed
semantic_advertising_gate   = passed
platform_integration_gate   = in_progress
dsp_gate                    = not_started
iq_recovery_validated       = false
ota_validated                = false
```

This proves the bit-conversion/CRC/PDU-parsing/artifact/visualization chain
is correct against known inputs. It says nothing about whether real IQ can
be turned into those bits — that's effort #2.

### 1.2 Architecture

```
BleLabView.tsx (frontend, /ble-lab)
  "Analyze replay frames" button
        │  POST /api/ble/jobs  { input_mode: "validated_bitstream_replay", ... }
        ▼
build_ble_router() (backend/app/modules/ble_lab/routes.py)
        │
        ▼
BleJobManager.create()  (backend/app/infrastructure/ble/ble_job_manager.py)
  - rejects anything but input_mode="validated_bitstream_replay"
    (IqRecoveryNotAvailable)
  - event-sourced state machine: created → queued → validating_input →
    starting_worker → running → validating_artifacts → completed
  - every transition appended to job_events.jsonl (sequence, timestamp,
    previous/new state, reason) -- full audit trail, nothing overwritten
        │ spawns subprocess
        ▼
BleWorkerAdapter.run()  (ble_worker_adapter.py)
  - verifies the worker repo's git HEAD matches the pinned WORKER_COMMIT
    before running anything (WorkerVersionMismatch if not)
  - runs backend/tools/ble_gate1b_replay_worker.py as a subprocess
    (separate process, same interpreter unless BLE_WORKER_PYTHON overridden)
        │ writes job directory
        ▼
BleArtifactValidator.validate()  (ble_artifact_validator.py)
  - artifacts_manifest.json hash-checks every declared file
  - rejects any undeclared file in the job directory
  - rejects duplicate packet_id, rejects any confirmed packet with
    crc_valid != True, cross-checks published advertisements/parsed
    packets only reference packet_ids that exist in confirmed_packets
        │
        ▼
GET /api/ble/jobs/{id}/{packets|advertisements|advertisers|channels|
    diagnostics|artifacts|events|bundle}
        │
        ▼
BleLabView.tsx renders: capability/gate table, job progress, job summary
metrics, 40-channel map (37/38/39 highlighted), packet table + full detail
view, advertisement table, advertiser table, receiver pipeline (state
transitions), diagnostics, known-limitations panel, reproducible-bundle
download (zip of the whole job directory).
```

### 1.3 Why the artifact validation is this strict

Every rule in `BleArtifactValidator` exists to make it structurally
impossible for the dashboard to ever show a non-CRC-valid packet as
"confirmed," or to show artifacts that don't match what the pinned worker
commit actually produced:

- `artifacts_manifest.json`'s `worker_commit` must equal the pinned
  `WORKER_COMMIT` constant (`ble_contracts.py`) — a stale or swapped worker
  build is rejected, not silently accepted.
- Every file listed in the manifest is SHA-256-verified against what's
  actually on disk; any file present on disk but *not* declared in the
  manifest is rejected too (`UndeclaredArtifact`) — nothing can sneak in
  after the fact.
- Every record in `confirmed_packets.jsonl` must have `crc_valid: True` —
  the validator itself would reject the job if that were ever violated, not
  just the worker's own logic.
- `packet_id`s must be unique; anything published in
  `parsed_packets.jsonl`/`advertisements.jsonl` must reference a
  `packet_id` that exists in `confirmed_packets.jsonl` — no orphaned or
  duplicated publications.

### 1.4 Deliberately disabled in the UI

`BleJobLauncher`'s "Start BLE Capture" button (channel/duration picker for a
*live* capture) is rendered `disabled`, with `title={BLE_DSP_UNAVAILABLE_REASON}`
and inline copy: *"Unavailable — DSP recovery gate has not passed. No IQ job
will be started."* This is not a placeholder to be casually re-enabled — see
§5.

### 1.5 Turning the integrated replay pipeline on

Two independent flags, easy to confuse:

| Flag | Effect | Default |
|---|---|---|
| `VITE_BLE_ANALYZER_V1` (frontend build env) | Whether "BLE Lab" appears in the sidebar nav at all | shown unless explicitly `'false'` |
| `BLE_ANALYZER_V1` (backend process env) | Whether `BleJobManager.enabled` is `True` | **disabled** unless explicitly `true`/`1`/`yes`/`on` |

So by default the nav item is visible but every `/api/ble/*` route 404s
with `"ble_analyzer_disabled"` until the backend is started with
`BLE_ANALYZER_V1=true`. Also configurable (all optional, sensible defaults
in `backend/app/modules/ble_lab/module.py`):

```text
BLE_WORKER_REPOSITORY     default: C:\Users\Usuario\ble-worker-gate1b-frozen
BLE_WORKER_PYTHON         default: this backend's own sys.executable
BLE_WORKER_ENTRY_POINT    default: backend/tools/ble_gate1b_replay_worker.py
BLE_WORKER_TIMEOUT_SECONDS default: 60
```

Unlike Wi-Fi's `default_worker_command()`, there is currently no
"auto-detect and default to enabled" behavior for BLE — this is a
deliberate difference, matching BLE's own methodology of not treating any
capability as on-by-default until it's explicitly earned.

---

## 2. Effort #2: DSP/IQ recovery development (Gate 2A.2, not integrated)

This section is a condensed, structured summary of the full handoff
document this was derived from. **Read the original in full before touching
any receiver code** — this summary exists for orientation, not as a
replacement.

### 2.1 Methodology (must not be violated)

Three strictly separated evidence pools:

- **Development corpus** — used to build/debug/select the receiver.
- **Regression corpus** — known cases (including ones derived from prior
  failures) that must keep passing.
- **Holdout corpus** — used *only* for independent evaluation *after* a
  receiver version is frozen.

Rules that must never be broken:

- a case inspected during development can never become eligible for a
  future holdout;
- a holdout can never be used to tune the receiver;
- the selection policy can never change after seeing a holdout result;
- Holdout B cannot be created before Candidate B is frozen;
- results from different policies can never be combined to claim an
  approved campaign;
- no per-case manual policy selection.

### 2.2 Gate status (as of the last handoff)

```text
Gate 2A.1                 = passed
Gate 2A.2                 = in_progress
dsp_gate                  = in_progress
iq_recovery_validated     = false
ota_validated             = false
Receiver Candidate B      = not frozen
Holdout B                 = not created
iq_capture                = disabled
capture_and_decode        = disabled
```

### 2.3 History: Candidate A, Holdout A

Candidate A only evaluated integer sample positions (no fractional timing
recovery). Holdout A revealed a case needing a timing phase of `0.5` input
samples, at an input sample step of `0.25 Ts`, i.e. `0.125 Ts = 2/16 Ts` —
a position Candidate A structurally could not evaluate. Two coordinate
systems must stay distinct: `phase_input_samples` (fraction of one input
sample) vs. `phase_ts` (fraction of the symbol period `Ts`).

The original Holdout A evaluation is `failed` and stays `failed` — it is
**not** reinterpreted as passed. It was, however, correctly preserved and
copied into the regression corpus with
`{"eligible_for_future_holdout": false, "purpose":
"development_regression_only"}` — it can prevent regressions but can never
again serve as independent holdout evidence.

### 2.4 Fractional timing interpolator (implemented)

```text
type               = linear_frequency_metric
phase_count        = 16
phase_step         = 1/16 Ts
input_sample_step  = 0.25 Ts
```

Interpolates the frequency metric (not the raw IQ, not post-bit-decision)
across a 16-point phase grid (`0/16 Ts` … `15/16 Ts`) *before* the binary
decision — interpolating after the bit decision would not recover the
information lost by deciding at the wrong phase in the first place, so
that ordering is load-bearing, not incidental. Generates explicit,
individually-identified hypotheses per phase, keeps the losing ones (not
just the winner), is deterministic, and has explicit non-finite (`NaN`,
`±Inf`) and boundary handling. 466 tests pass for this infrastructure and
for the Holdout-A-derived regression case specifically — this proves the
*interpolator* works, not that the *selection policy* is correct across the
whole development domain.

### 2.5 Development timing sweep — reconciled results

384-case development sweep, three deterministic selection policies:

| Policy | Result |
|---|---|
| `sync → energy → phase` | **381/384** (best) |
| `sync → lower phase` | 370/384 |
| `sync → span → energy → phase` | 380/384 |

Requirement is strict `384/384`; `381/384` is a `development candidate`
only, not approved, not frozen. **3 residual failures remain
unclassified** as of the last handoff.

The discrepancy is resolved experimentally: `381/384` belongs to
`sync -> energy -> phase` and is both the active policy and best development
result. `380/384` belongs to `sync -> span -> energy -> phase` and is
preserved separately. Neither result satisfies the acceptance criterion.

### Backend regression baseline

The BLE-targeted backend suite passes completely. The complete backend suite
is not globally green: `83 passed`, `2 skipped`, and `17 failed`. A controlled
run on clean commit `12e3ac193123e128a555ea6cc24b1b765c08f4cb` reproduces
the same 17 non-BLE failures with matching exception types and primary error
lines. The BLE working tree adds fourteen passing tests and introduces no new
backend test failure. This is a relative regression statement, not a claim
that the repository-wide suite passes.

The structured comparison is stored in
`docs/technical-readmes/ble/backend_test_failure_reconciliation.json`.

### Real IQ capture and visualization

BLE Lab now has a separate experimental acquisition path:

```text
SoapySDR receiver -> preserved SigMF IQ recording -> visualization
```

It is controlled by `BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED`, defaults to on
(set the variable to `false` to disable it explicitly), and never starts
Gate 2A.2 automatically. The backend records raw IQ directly
to disk while the browser receives only reduced FFT and I/Q preview frames.
Completed recordings include relative paths, hashes, acquisition parameters,
overflow/discontinuity counters and explicit exclusion from scientific and
holdout corpora. `Capture and Decode BLE` remains hardcoded disabled.

The target and only physical SDR for this integration is the USRP B200;
HackRF is out of scope. With an explicitly isolated RadioConda runtime,
SoapySDR/UHD detects and probes the B200 successfully. The capture profile is
derived from the enumerated device capabilities (RX formats, sample rates,
bandwidth, antennas, gains, clock sources and time sources), not from a
HackRF-specific assumption. The controlled CH37 campaign is recorded in
`physical_capture_acceptance_usrp_b200.json`: capture A (controlled
transmitter off) and capture B (controlled transmitter active) each preserved
12,000,000 CF32 samples at 4 MS/s. A recorded seven overflows/discontinuities;
B recorded zero. Both SigMF recordings and their visualization artifacts have
verified hashes and reopen through the catalog. This accepts real-IQ capture
and visualization as experimental infrastructure only. The flag remains
disabled by default; Gate 2A.2 was not run, BLE packets were not decoded, and
no IQ-recovery or OTA validation claim has been made.

### Native BLE sensor values

Operational sensor values use the conventional Windows BLE adapter through
Bleak/WinRT, independently of the USRP and Gate 2A.2. The API exposes adapter
status, manual scanning, raw advertising observations, explicit GATT
connection/service discovery, property-checked read/notify operations, and
measurements with parser/raw-byte provenance. Unknown manufacturer and service
payloads remain `UNKNOWN_FORMAT`; no engineering value is inferred from RF
power, spectrum, waterfall, or undocumented byte offsets.

The first controlled 30-second inventory is preserved in
`observed_sensor_inventory.json`. It detected 70 ambient BLE identities, ten
with a local name, but no device yet has an accepted sensor parser. A concrete
sensor must therefore be identified by the operator before GATT inspection or
vendor-parser validation. This does not alter Gate 2A.2, Candidate B, IQ
recovery, OTA status, or the disabled Capture-and-Decode capability.

### 2.6 Reference checkpoint

```text
b61aa1a5c18c79d836fb2e6336d8b00289ac736a
```

Treat as a development checkpoint only — never as Candidate B, never as a
frozen baseline, never as grounds to create Holdout B. Before changing
anything, diff this commit in full
(`git show b61aa1a5c18c79d836fb2e6336d8b00289ac736a`) against
`artifacts/gate2a_2/receiver_tuning_history.json`,
`src/ble_worker/dsp_models.py`, `src/ble_worker/dsp_receiver.py`, and
the other files reported by Git. The authoritative checkpoint contains
exactly eleven changed files; the former figure of seven is superseded.

### 2.7 What's required before the 3 residual failures can be closed

In order, without skipping steps:

1. **Reproduce only the 3 failures** under full instrumentation, with the
   current best policy (`sync → energy → phase`) unchanged. Each must
   reproduce individually, deterministically, repeatedly, independent of
   the other cases' execution order.
2. **Preserve all 16 hypotheses per case** (winners and losers), each
   recording at minimum: `hypothesis_id`, `phase_index`, `phase_ts`,
   `phase_input_samples`, `sync_metric`, `energy_metric`,
   `frequency_metric_span`, `decision_start_index`, `decoded_pdu_hex`,
   `decoded_length`, `crc_ok`, `byte_exact`, `selected`, `rejection_stage`
   — plus each metric's optimization direction, tolerance, normalization,
   original index, final rank, and exact rejection reason.
3. **Oracle applied only after the run**, never during hypothesis
   generation/interpolation/metric computation/ranking/tie-break/
   selection/bit decision. Record
   `{"oracle_used_for_runtime_selection": false,
   "oracle_used_for_post_run_diagnostics": true}` and, per case,
   `{"byte_exact_hypothesis_exists", "byte_exact_hypothesis_selected",
   "first_ranking_stage_that_rejects_correct_hypothesis"}`.
4. **Classify each failure to exactly one primary cause**:
   `INTERPOLATION_COVERAGE_FAILURE`, `INTERPOLATED_METRIC_FAILURE`,
   `BIT_DECISION_FAILURE`, `SYNC_RANKING_FAILURE`, `ENERGY_RANKING_FAILURE`,
   `SPAN_RANKING_FAILURE`, `NUMERIC_TIE_FAILURE`,
   `BOUNDARY_HANDLING_FAILURE`, `NON_TIMING_RECEIVER_FAILURE`, or
   `UNRESOLVED` — derived from artifacts, never from visual impression
   alone, always naming which hypothesis was correct and at which stage it
   was lost.
5. **Do not add a new ranking metric before completing 1–4.** If *no*
   phase produces the correct PDU, the bug is in coverage/interpolation/
   decision/sync, not in ranking — adding another ranking tier would not
   fix that. If a byte-exact hypothesis exists but loses on a specific
   metric, investigate *why* that metric disfavors the correct hypothesis
   before ever just flipping a comparison direction.
6. **No overfitting**: no rule keyed to a specific `phase_index`/length/
   seed/identifier, no lookup table of known cases, no per-case tuned
   parameters, no runtime access to the expected PDU. Any new policy needs
   a general justification tied to the signal model or receiver behavior.
7. **Determinism**: final selection must never depend on dict/set
   iteration order, thread count, OS scheduling, parallel completion
   order, or CPU architecture. A stable final tie-break
   (`phase_index` or `hypothesis_id`) must be documented and tested; repeat
   each residual case multiple times and confirm identical
   `selected_hypothesis_id`, decoded PDU, metric values, and ranking order
   every time.

### 2.8 Candidate B freeze criteria (all required, none optional)

```text
development timing sweep         = 384/384
Holdout A-derived regression      = passed
all unit tests                    = passed
all prior receiver regressions    = passed
deterministic repeated execution  = passed
non-finite handling               = passed
boundary handling                 = passed
phase conversion                  = verified
runtime ground-truth access       = absent
selection policy                  = documented
selection tolerances              = documented
losing hypotheses                 = preserved in diagnostic mode
clean campaign artifacts          = generated
```

Even once frozen, `iq_recovery_validated` does **not** automatically become
`true` — freezing Candidate B only unlocks the next, independent
evaluation (Holdout B), it is not validation by itself.

### 2.9 Holdout B (does not exist yet)

Must stay separate from Holdout A, the Holdout-A-derived regression case,
all 384 development cases/seeds, and anything already inspected. Before it
can be materialized: Candidate B's freeze commit, a frozen receiver
manifest, a generator manifest, a seed-partition manifest, immutable
success/failure criteria, and confirmation none of it was used in
development. Once started: the receiver, policy, and tolerances are frozen
for the duration; it cannot be re-run selectively until it passes; a
failure cannot be used to patch the same Candidate B — it goes back to
development and the next candidate needs its own, still-independent
holdout.

### 2.10 Integration into spectrum-lab: experimental offline IQ analysis (NEW)

Unlike everything else in §2 (which lives entirely in the external
`ble-worker-lab` repo), this is now wired into spectrum-lab itself — off by
default, isolated from Gate 1B, and real (not simulated): it calls
`ble-worker-lab`'s own `iq_contract.validate_iq_job()` +
`dsp_receiver.run_offline_receiver()`, which hands recovered candidates to
the **same frozen Gate 1A decoder + Gate 1B semantic parser** effort #1
trusts — so a `confirmed_packets` entry here really did pass a real CRC
check, even though the DSP front end that produced its bits is unvalidated.

- **`backend/app/infrastructure/ble/ble_gate2a2_status.py`** — reads Gate
  2A.2's status **live** from `ble-worker-lab/artifacts/gate2a_2/*.json`
  (path overridable via `BLE_GATE2A2_REPOSITORY`) rather than a hand-copied
  snapshot, so it can never silently drift out of sync with the real repo.
  Returns `{"available": false, ...}` honestly if the repository isn't
  present on a machine. It reads the versioned reconciliation artifact and
  distinguishes the best development result, latest recorded execution,
  active policy, authoritative gate status, and frozen candidate. It does
  not infer scientific state from file modification time.
- **`backend/tools/ble_gate2a2_offline_worker.py`** — the subprocess worker
  (mirrors `ble_gate1b_replay_worker.py`'s boundary pattern). Deliberately
  does **not** hard-pin and fail on a specific git commit the way the Gate 1B
  worker does — Gate 2A.2 is explicitly not frozen, so there is no single
  "the" commit to demand; the actual commit used is recorded as provenance
  in every output instead. Verified standalone against a real, synthetically
  generated (but validly GFSK-modulated) `cf32_le` fixture: produced a real
  `ADV_NONCONN_IND` packet, `crc_valid: true`, with the winning timing
  hypothesis ID and the 15 losing hypothesis IDs preserved.
  **Known limitation:** `dsp_receiver.run_offline_receiver()`'s public
  return value only exposes hypothesis *IDs* (winner + losers) and a count,
  not each hypothesis's individual sync/energy/phase metric values — those
  are computed internally and discarded before the function returns. Getting
  full per-hypothesis metrics would require duplicating
  `dsp_receiver()`'s internal burst-processing loop in this platform's own
  code, which was deliberately avoided (it would risk silently drifting out
  of sync with the real receiver's actual behavior as `ble-worker-lab`
  evolves) — so today's hypothesis table shows IDs/counts/winner, not full
  metric-by-metric detail.
- **`backend/app/infrastructure/ble/ble_gate2a2_job_manager.py`** — a
  **separate** class from `BleJobManager`, not a subclass or a branch inside
  it. Reuses `BleRepository` (already generic over job-id prefix,
  `BLE-G2A2-JOB-*` vs. Gate 1B's `BLE-JOB-*`) but has its own, simpler
  event-sourced state machine — no artifact-manifest/hash validation step,
  since the worker script itself is what invokes the trusted CRC check.
- **`backend/app/modules/ble_lab/gate2a2_routes.py`** — `GET
  /api/ble/gate2a2/status`, `POST/GET/cancel /api/ble/gate2a2/jobs(/{id})`,
  per-job `candidates`/`confirmed-packets`/`semantic-packets`/`events`/
  `rejections`/`known-limitations`/`result-summary`/`bundle`. Entirely
  separate router from Gate 1B's `routes.py`, combined into one
  `APIRouter` in `ble_lab/module.py`.
- **Feature flags**, four independent, none reused: `BLE_ANALYZER_V1`
  (unchanged, Gate 1B only), `BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED` (env var,
  default off, gates §2.10's job routes only), `BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED`
  (env var, **default on** — real IQ capture via the SoapySDR/USRP B200 worker
  is implemented; set to `false` to disable it explicitly), and
  `BLE_CAPTURE_AND_DECODE_ENABLED` (still a **hardcoded `False` constant** in
  `ble_lab/module.py`, not an env var — combined capture+decode is not
  implemented, so making it togglable would create a flag with no real
  behavior behind it).
- **Frontend** (`frontend/src/presentation/views/ble/BleLabView.tsx`): the
  page is now explicitly split into a "Validated bitstream replay — Gate 1B"
  section (completely unchanged) and an "Experimental IQ recovery — Gate
  2A.2" section below it (`Gate2a2StatusPanel`, `AnalyzeIqFilePanel`,
  `Gate2a2CandidateTable`, `Gate2a2ConfirmedPacketsPanel`). "Capture Real IQ"
  is a real, functioning capability (enabled by default, gated only on SDR
  detection) — not a disabled stub. "Capture and Decode BLE" remains
  permanently disabled and shows a specific reason via `title`/inline text,
  not a generic "not available".
- **Verified end to end**: `pytest test_ble_platform_integration.py` passes
  unchanged (zero Gate 1B regressions); `GET /api/ble/gate2a2/status`
  reflects the live repo; a full job (`POST` → poll → `candidates`/
  `confirmed-packets`/`bundle`) against the synthetic fixture completed and
  returned a real CRC-valid packet; `npx tsc --noEmit` clean.

---

## 3. What must remain disabled, and why

```text
iq_capture              = disabled   (no SDR capture code path exists at all -- not built)
capture_and_decode      = disabled   (Candidate B is not frozen, OTA not validated)
iq_recovery_validated   = false      (do not set true until Holdout B passes)
ota_validated           = false      (synthetic/controlled-corpus success is not OTA validation)
dsp_gate                = in_progress
```

§2.10's *offline analysis of an already-existing IQ file* is the one exception
that is now real and integrated — off by default
(`BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED`), clearly labeled experimental on every
screen and every artifact, and structurally incapable of touching live
hardware (it only ever reads a file path you already have). It does not
change anything above: it is not SDR capture, not combined capture-and-decode,
and completing an offline analysis run never sets `iq_recovery_validated` or
`ota_validated` to `true`.

The only thing that may look similar and *is* real and enabled is effort
#1's frozen bitstream replay (§1) — it never touches RF/IQ, and its own
`known_limitations.json` says so explicitly on every job:
*"No IQ demodulation or RF recovery was performed."*

---

## 4. Reproducing / verifying what's integrated today

1. Start the backend with `BLE_ANALYZER_V1=true` (see §1.5).
2. `GET /api/ble/capabilities` — confirm `enabled: true` and the gate table
   matches §1.1.
3. `POST /api/ble/jobs` with `input_mode: "validated_bitstream_replay"` (the
   frontend's "Analyze replay frames" button does exactly this), poll
   `GET /api/ble/jobs/{id}` until a terminal state, then check
   `confirmed_packets` all have `crc_valid: true` and
   `GET /api/ble/jobs/{id}/bundle` returns a zip.
4. `pytest backend/app/tests/unit/test_ble_platform_integration.py`.
5. Do **not** attempt to point this at real IQ or enable a capture button —
   there is currently no code path for that, by design (§2, §3).

For effort #2 (the actual DSP work), reproduction steps are the ones in
§2.6–2.7 above and, in full detail, in the original handoff document this
README was derived from (kept alongside project history — ask for it if
it isn't already in this repo's own notes).

### 4.1 Reproducing/verifying §2.10's offline IQ analysis integration

1. Start the backend with `BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED=true` (in
   addition to whatever `BLE_ANALYZER_V1` setting you want — independent).
2. `GET /api/ble/gate2a2/status` — confirm `available: true` and that the
   numbers match whatever `ble-worker-lab/artifacts/gate2a_2/*.json`
   currently say (they will drift as that campaign continues; that's
   expected and correct).
3. `POST /api/ble/gate2a2/jobs` with `{"iq_file_path": "<path>",
   "channel_index": 37|38|39}` pointing at a real `cf32_le`, 4 MS/s IQ file,
   poll `GET /api/ble/gate2a2/jobs/{id}` to a terminal state, then check
   `GET .../candidates` and `GET .../confirmed-packets`.
4. Standalone (bypasses the platform, fastest sanity check): run
   `ble_gate2a2_offline_worker.py --worker-repository
   C:\Users\Usuario\ble-worker-lab --request <request.json> --output-dir
   <dir>` directly and inspect `result_summary.json`.

---

## 5. File map

```
Effort #1 (integrated, frozen Gate 1B replay):
  backend/tools/ble_gate1b_replay_worker.py                (subprocess worker, runs under ble-worker-gate1b-frozen)
  backend/app/infrastructure/ble/ble_contracts.py           (CONTRACT_VERSION, WORKER_COMMIT, CAPABILITIES)
  backend/app/infrastructure/ble/ble_job_manager.py         (event-sourced job state machine)
  backend/app/infrastructure/ble/ble_worker_adapter.py      (subprocess boundary + commit-pin verification)
  backend/app/infrastructure/ble/ble_repository.py          (job directory / event log persistence)
  backend/app/infrastructure/ble/ble_artifact_validator.py  (manifest hash + CRC/publication integrity checks)
  backend/app/infrastructure/ble/ble_errors.py              (typed error codes)
  backend/app/modules/ble_lab/module.py                     (wiring, env var defaults)
  backend/app/modules/ble_lab/routes.py                     (GET/POST /api/ble/*)
  backend/app/tests/unit/test_ble_platform_integration.py
  frontend/src/presentation/views/ble/BleLabView.tsx        (dashboard: gates, launcher, packets, advertisements,
                                                              advertiser addresses, pipeline, diagnostics, bundle download)
  frontend/src/app/services/bleApi.ts                       (typed API client)
  frontend/src/app/modules/ble-lab/module.tsx                (route registration, /ble-lab)

Effort #2 (§2.1-2.9 external/not integrated; §2.10 experimental integration):
  C:\Users\Usuario\ble-worker-lab                            (active development repo, Gate 2A.2, not frozen)
  C:\Users\Usuario\ble-worker-gate1b-frozen                  (the earlier, frozen snapshot effort #1 actually uses)
  backend/app/infrastructure/ble/ble_gate2a2_status.py        (live status reader, §2.10)
  backend/app/infrastructure/ble/ble_gate2a2_job_manager.py   (separate job manager + worker adapter, §2.10)
  backend/tools/ble_gate2a2_offline_worker.py                 (subprocess worker, real DSP call, §2.10)
  backend/app/modules/ble_lab/gate2a2_routes.py               (GET/POST /api/ble/gate2a2/*)
  frontend/src/presentation/views/ble/BleLabView.tsx          (also contains the "Experimental IQ recovery — Gate 2A.2"
                                                                section: Gate2a2StatusPanel, AnalyzeIqFilePanel,
                                                                Gate2a2CandidateTable, Gate2a2ConfirmedPacketsPanel,
                                                                Gate2a2DisabledCaptureButtons)
  frontend/src/app/services/bleApi.ts                         (also contains gate2a2Status/createGate2a2Job/etc.)
```
