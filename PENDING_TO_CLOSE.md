# SpectraRFˣ — What's left to fully close the platform and the paper

Generated 2026-08-16, from the platform's own real, live state (`GET
/analysis-contract-readiness`, `GET /study-status`, `GET /paper-readiness`,
`GET /association-policy-status`, `GET /scientist-decisions`) — every claim
below was verified against a real endpoint response before being written
here, not recalled from memory.

**Update 2026-08-17 (paper-representation pass)**: no item below closed as a
result of this pass — it was a representation/traceability pass, not a data
acquisition one. What changed: (a) `rq2_representation_comparison_report.json`
now persists `selection_rule`/`selection_domain` and per-branch
`balanced_accuracy_ci`, and `rq1_acquisition_dependence_report.json` now
persists a real cluster-bootstrap `uncertainty_ci.ba_capture_ci` and the
correct `model_bundle_sha256` (previously silently held a dataset hash) —
these populate on the **next** RQ1/RQ2 run, not retroactively on the
already-persisted reports; (b) the RQ3/RQ4 paired-figure "generators" the
overhaul asked for were confirmed **already implemented and correct**
(`_emit_confirmatory_derived_exports` in `paper_export.py`), so §3/§5 below
are unchanged in substance, just now also visible as a normalized confusion
matrix, per-transmitter table, campaign-timeline figure, and forensic-lineage
diagram, all regenerable via `run_paper_export()`/the Evidence Dashboard's
existing "Generar imagenes nuevas" button; (c) a new `GET
/scientific-completeness` endpoint (Scientific Completeness tab) mirrors this
very file's own state machine in-platform, in the vocabulary AVAILABLE /
PENDING_REAL_ACQUISITION / BLOCKED / NOT_ELIGIBLE / PROTECTED — useful as a
live cross-check against this document, not a replacement for it.

**Update 2026-08-17, second pass (same day) -- "exploit what already exists,
no new captures"**: implemented 6 scoped improvements over already-real
mechanisms, no new science, no new hardware:

- RQ1 figure (`evidence_rq1_domains.png` + `rq1_acquisition_dependence.pdf`)
  now plots the real cluster-bootstrap CI on `BA_capture` and a real
  n-per-domain caption; the third bar stays explicitly "Held-out TEST",
  never mislabeled FUTURE; a fourth "protected FUTURE" bar renders
  automatically once `ba_future` is real.
- Per-transmitter table (`closed_set_per_transmitter.csv`) now includes a
  real `n` per unit (derived from the same confusion matrix already
  exported, never a second count). Per-unit CI intentionally NOT added --
  no per-unit bootstrap exists yet.
- **Source-association calibration is now a real, structured artifact.**
  Previously the real per-threshold sweep (`coverage_by_threshold`,
  `false_strong_by_threshold`, `ambiguous_by_threshold`) was computed
  internally by `select_association_threshold` but only ever survived as a
  stringified blob inside an exception message -- now
  `NoThresholdSatisfiesCriteriaError` carries it as real attributes,
  `guided_validation/service.py::_attempt_policy` persists it structurally
  into `association_policy.json` (still `NO_THRESHOLD_SATISFIES_CRITERIA`,
  same real status as before -- 0 STRONG associations remains 0), and it is
  now visible via `GET /association-calibration-summary` and the
  Association tab's new sweep table, even with no accepted threshold.
- **Closed-set 10-second decision-window BA/confusion/risk-coverage now
  exists as real evidence** (`run_coverage_analysis(...,
  evaluate_window_level=True)`, reusing `Evaluator.evaluate_split()`
  unchanged, fed real decision-window predictions instead of per-example
  ones). Ran it for real against the closed-set PRIMARY branch (after
  exporting its previously-never-exported bundle,
  `CLOSED-SET-4DEVICES-random_forest-bundle` -- no new capture, just
  packaging an already-trained/already-evaluated run). **Real, honest
  finding, worth flagging explicitly**: at 10-second-window granularity the
  closed-set collapses to only 2/5/5 real windows in TRAIN/VALIDATION/TEST
  (vs. thousands of per-packet examples), and the PRIMARY model predicts
  `keyfobdemo 01` for every one of them (BA=0.25, chance level for 4
  classes) -- window-level aggregation empties out almost all real evidence
  because the underlying sessions are short. This is real CURRENT_TEST
  evidence, not a bug; it argues for either longer real capture sessions or
  a shorter window duration before this becomes a citable paper figure.
  Labeled `CURRENT_TEST` everywhere (never `PROTECTED_FUTURE`) in the new
  `window_level_evaluation` block of `coverage_analysis_report.json` /
  Coverage tab.
- **Window-level risk-coverage**: same real block above also carries a
  window-level risk-coverage curve per domain (reuses
  `Evaluator._risk_coverage()`, no second implementation). The "operating
  point" badge is computed from the branch's OWN real, VALIDATION-only
  `acceptance_threshold` (`Evaluator.calibrate_unknown_threshold`, 0.66 for
  the closed-set PRIMARY bundle) -- **this already exists and is frozen**,
  a genuinely different mechanism from the still-blocked native<->SDR
  `AssociationPolicy.threshold_ms` (§4 below); no threshold was selected
  using TEST anywhere in this pipeline.
- Computational-cost figure now captions its real methodology (mean of 10
  repeats, single-sample wall-clock `predict_proba`) and explicitly notes
  the measurement host was never captured historically (real gap, not
  fabricated).
- **Real, pre-existing bug found and fixed, unrelated to any of the above**:
  `scientific_results_job_manager.py` imported `OfflineInferenceService` via
  `from ..inference.offline_inference import ...` in 4 places (RQ3, RQ4,
  Coverage, one more) -- `..` resolves inside `ble_scientific_results`,
  which has no `inference` subpackage; the real one lives under
  `ble_rffi_studio`. Every one of those 4 background jobs has been failing
  immediately with `ModuleNotFoundError` whenever triggered over HTTP. Fixed
  to an absolute import. Whatever real RQ3/RQ4 data already exists in this
  document predates this exact code path or was produced differently; going
  forward, the "Run" buttons for RQ3/RQ4/Coverage now actually work.
- **RQ4 answer, investigated on request, no code touched**: checked
  `docs/ble/physical_device_inventory.json` for all 7 enrolled units --
  `configurable_payload`/`configurable_address` are `NOT_DOCUMENTED` for
  every single one (0 real captures anywhere declaring
  `packet_condition=CONTROLLED_VARIANT`). No current firmware/hardware
  capability exists on any enrolled unit to produce the FULL_BURST /
  ADVA_EXCLUDED / PRE_PDU packet-content variants RQ4 needs -- would require
  either a flashable/documented-firmware device or a verified third-party
  tool to alter advertising payload/address, neither of which exists in the
  current inventory.

**One-paragraph summary**: the closed-set RQ1/RQ2 result (the paper's
headline finding) is real and done. RQ4 is real and closed as an honest
negative result. Everything else — RQ3's actual campaign, the *confirmatory*
readiness ceremony, and therefore the protected FUTURE evaluation itself —
is not done, and FUTURE cannot open until the confirmatory ceremony is
satisfied. That ceremony needs ~16 real scientist decisions that only the
project owner can make (not something that should be auto-decided). This
file is the punch list.

---

## 1. Already closed — do not repeat

- **SOURCE ADMISSION V2** — closed, 8,191 admitted PDUs, session-level
  native corroboration.
- **Closed-set RQ1/RQ2** (4-unit `MULTI_DEVICE_CLASSIFICATION`) — real,
  `delta_dependence = +0.2182`, PRIMARY = `engineered_rf`, TEST
  BA = 0.7666. This is the paper's headline result.
- **4 per-unit auxiliary `TARGET_VS_BACKGROUND` runs** — real, kept as
  auxiliary, never substituted for the closed-set result.
- **RQ4 eligibility** — real, `DATA_NOT_AVAILABLE: CONTROLLED_VARIANT_NOT_AVAILABLE`,
  0/4 units eligible, per-unit reasons recorded. This is a real, final,
  reportable negative result — nothing left to do here unless a unit's
  hardware/firmware situation genuinely changes.
- **RQ3 sample size** — frozen as a real scientist decision (`rq3_sample_size`,
  80 pairs / 160 captures, `PROSPECTIVE_BALANCED_WITHIN_DEVICE_CROSSOVER`).
  The *decision* is closed; the *campaign* is not (§3).
- **Evidence Dashboard** — live in-platform tab, real data, refresh +
  regenerate-figures buttons, real PNG figures + notebook committed.

---

## 2. The real blocker: confirmatory readiness is BLOCKED

`GET /analysis-contract-readiness` reports `protocol_freeze_readiness.status
= BLOCKED`. `GET /study-status` reports `contract_status = INCOMPLETE`,
`protocol_freeze_status = NOT_STARTED`. This is the single gate everything
else (S2 aside) is waiting behind — no protected FUTURE evaluation is
reachable until it clears.

**16 real missing fields**, from the live `missing_confirmatory_readiness_fields`:

| Field | Kind | What it needs |
|---|---|---|
| `rq2_primary_branch` | SCIENTIST_DECISION | Formally record `engineered_rf` via `record_scientist_decision()`, citing the real automatic VALIDATION-based selection as evidence — the automatic selection during `/rq2-benchmark` is **not** automatically recorded as this decision; it has to be logged explicitly. |
| `rq2_branch_selection_rule` | SCIENTIST_DECISION | State the rule in writing (`select_primary_rq2_branch_from_validation`, VALIDATION-only, highest composite score) as a frozen decision, not just as code. |
| `rq3_primary_analysis` | SCIENTIST_DECISION | What RQ3's primary confirmatory analysis actually is (the crossover `delta_cycle` estimand + `stratified_crossover_permutation_test`, already implemented in `rq3_frr_analysis.py` — needs to be *declared*, not re-invented). |
| `rq3_reset_control_definition` | SCIENTIST_DECISION | The operational definition of RESET vs. CONTROL (already described in the README/paper text) needs to be recorded as a frozen decision, not only prose. |
| `rq4_representation_definitions` | SCIENTIST_DECISION/DERIVED | `rq4_primary_analysis` is already recorded (`REGION_SPECIFIC_FITTING_AND_EVALUATION`); this sibling field (representation-per-region mapping) is still missing. |
| `sensitivity_analyses` | SCIENTIST_DECISION | Which sensitivity analyses count for the confirmatory report (seed variability, offset-retaining preprocessing, LODO — all three mechanisms already exist and were used ad hoc this session; needs a frozen enumeration). |
| `preprocessing_profile` | SCIENTIST_DECISION | Confirm `paper-eq6-7-v1` as the frozen primary preprocessing profile (vs. `offset-retaining-v1`, kept as sensitivity only) — a one-line decision, but a required one. |
| `threshold_selection_procedure` / `operating_threshold_ms` | DERIVED, currently null | Both resolve from `AssociationPolicy.selection_rule`/`.threshold_ms` — **blocked by §4** (no frozen association policy exists yet). |
| `non_inferiority_margin` | SCIENTIST_DECISION | Real number, e.g. for RQ4's FULL_BURST vs. PRE_PDU non-inferiority test. Needs a stated, defensible margin. |
| `non_inferiority_direction` | SCIENTIST_DECISION | One-sided direction of that test. |
| `alpha` | SCIENTIST_DECISION | Significance level for every confirmatory test (0.05 is used throughout the power-simulation tooling as a default, but has never been *frozen* as the real decision). |
| `confirmatory_hypotheses` | SCIENTIST_DECISION | The exact enumerated hypothesis family entering the Holm correction (H1 dependence/future, H2 RESET/CONTROL, H3a/H3b content — the paper's own §RQ1-4 defines them; needs to be transcribed as a frozen list). |
| `holm_family` | SCIENTIST_DECISION | Which of the above hypotheses share one Holm-adjusted family vs. are reported separately. |
| `decision_rule` | SCIENTIST_DECISION | The final accept/reject logic combining coverage + non-inferiority + significance into one stated confirmatory verdict rule. |
| `future_test_access_policy_ref` | SCIENTIST_DECISION | A named reference to *this exact document/procedure* governing who may trigger FUTURE access and how — currently nothing is cited. |

**Readiness gates**, also currently `INCOMPLETE` (separate from the fields
above — these are formal phase-completion markers, real work may already
exist behind some of them without the marker having been set):

- `qualification_state` (Phase 01 — hardware qualification)
- `association_policy_state` (Phase 03 — see §4)
- `development_completion` (Phase 06)
- `validation_completion` (Phase 07)
- `rq2_primary_selection` (flips once the `rq2_primary_branch` decision above is recorded)

**A real, separate wrinkle found while checking this**: `GET /study-status`'s
single `protocol_id` field does not point at the deliberate paper freeze
(`protocol-56ec3f1285fb45fa0fe3fa99df39dc3a`) — it currently resolves to an
auto-generated, minimal contract (`ble-rffi-studio-TRAIN-...`) that
`evaluate_training_run(include_test=True)` silently freezes every time ANY
training run's TEST set is opened, purely to log holdout access. There are
**96 real protocol IDs** on disk from this platform's whole lifetime, most
of them these minimal auto-freezes, not deliberate paper freezes. Before
attempting the real confirmatory freeze, whoever does this needs to confirm
which protocol_id resolution path `freeze_protocol()`/the readiness checks
actually target, so the real paper decisions land on the real paper
protocol and not on an incidental auto-freeze artifact.

---

## 3. RQ3 — the physical campaign itself

Mechanism-complete, zero real data. In order:

1. **Smoke test** (`QUALIFICATION_ONLY`, excluded from confirmatory): 1 RESET
   pair + 1 CONTROL pair on one unit (CC2650-UNIT-01 was already selected).
   Requires live coordination — I trigger each B200 capture, the operator
   physically power-cycles (or waits, for CONTROL) the target device on cue.
   **This was set up and never actually run** — got sidetracked into
   dashboard work. Verifies: PRE/POST metadata correctness, same
   `receiver_epoch`/`receiver_session_id`, valid pairing via
   `build_pre_post_pairs()`, frozen PRIMARY model can score both windows.
2. **If it passes** — the full confirmatory campaign: 10 RESET + 10 CONTROL
   pairs × 4 units = 80 pairs / 160 real captures, using the already-computed
   balanced crossover order (`build_balanced_crossover_assignment`). This is
   a large amount of real, hands-on operator time (80 physical
   power-cycle/wait actions).
3. **After real captures exist** — run the real analysis:
   `ScientificResultsRepository.run_rq3_frr_analysis` (already implemented,
   drives `OfflineInferenceService.run_decision_windows()` against the
   frozen PRIMARY bundle) to get real `FRR_pre`/`FRR_post`/`D` per pair, then
   `stratified_crossover_permutation_test` (real function, not the
   `simulate_h2_power_cycle` proxy) for the confirmatory `delta_cycle`
   verdict.

---

## 4. Association calibration — likely a permanent, honestly-reported limitation

`GET /association-policy-status` → `{"status":"NONE"}`, still. 0 STRONG
associations in the whole real corpus (156 real captures on disk today).
SOURCE ADMISSION V2 (session-level corroboration) is the *primary* dataset
admission gate now and does not depend on this — but `threshold_selection_procedure`/
`operating_threshold_ms` in §2's table stay `null` until/unless a real
calibration campaign produces an accepted policy. This may simply remain a
real, stated negative result for the paper's Discussion/Limitations section
(same posture the README already takes) rather than something to force —
worth a deliberate decision either way, not silent inaction.

**Update 2026-08-17**: the real per-threshold sweep behind this negative
result (`coverage_by_threshold_ms`/`false_strong_by_threshold_ms`/
`ambiguous_by_threshold_ms` for every grid value) is now a real, structured,
inspectable artifact — `GET /association-calibration-summary`, Association
tab. Still `NO_THRESHOLD_SATISFIES_CRITERIA`; nothing about the underlying
0-STRONG-association finding changed, only its visibility. Do not confuse
this with the model's own per-bundle `acceptance_threshold` (UNKNOWN-
rejection calibration, `Evaluator.calibrate_unknown_threshold`) — that one
IS real and VALIDATION-frozen already (0.66 for the closed-set PRIMARY
bundle) and has nothing to do with this native&lt;-&gt;SDR association gate.

---

## 5. Protected FUTURE evaluation

Blocked on §2 clearing, plus:

1. A genuinely **new acquisition period**, temporally after DEVELOPMENT/
   VALIDATION, for the 4 enrolled units — real B200 captures the model has
   never seen in any form, at any stage.
2. `run_confirmatory_future_analysis` (already implemented, never triggered
   for real data) — verifies the frozen protocol/contract-hash/partition/
   model-configuration are mutually consistent before touching FUTURE, then
   evaluates once.
3. The real, non-proxy confirmatory statistical plan across H1/H2/H3 (uses
   `exact_randomization_test`/`stratified_crossover_permutation_test`
   directly, Holm-corrected per §2's `holm_family` decision) — this is what
   turns RQ1/RQ2's current `PRELIMINARY` paper-readiness status into
   `CONFIRMATORY`.

**Until this happens**: `BA_future`/`delta_future` stay `NOT_YET_AVAILABLE`
everywhere, correctly, and RQ1/RQ2 remain reportable only as `PRELIMINARY`
findings in the paper, not confirmatory ones.

---

## 6. S1 — channel transport (37 → 38/39)

Mechanism real (`compute_channel_transport_report`, real per-unit recall
join). Paper readiness = `DATA_PENDING`, maturity `ENGINEERING`. Needs real
B200 captures on channels 38 and 39 for the 4 enrolled units (only captured
after model development is frozen, per the paper's own stated protocol) —
none exist yet.

## 7. S2 — online/offline equivalence

Paper readiness = `DATA_PENDING`, maturity `ENGINEERING`, and honestly
`BOUNDED_WITH_NOT_MEASURED` per the platform's own prior audit: **no real
near-live inference source exists at all** — this is not a data-collection
gap like S1, it's a missing real-time inference pipeline that would need to
be built before it could be exercised. Lowest priority of everything in
this document unless the paper's own scope requires it.

## 8. Coverage / Sensitivity

Mechanisms real and already used ad hoc this session (seed variability for
RQ2's PRIMARY branch, real risk-coverage curves). Paper-readiness still
`DATA_PENDING` because a canonical run over the confirmatory (not
diagnostic) domain hasn't been produced and persisted as the citable
artifact — mostly falls out for free once §5 runs.

---

## 9. Known, non-blocking bugs (documented, not fixed, by explicit prior instruction)

- `freeze_protocol()` accepts `primary_population`/`primary_unit_ids`/
  `secondary_same_model_subset`/`configurable_content_subset`/
  `device_specific_packet_profiles`/`crossover_intervention_schedule`/
  `population_claim_boundary` in its payload but never forwards them into
  the persisted `AnalysisContract` — only `device_ids` is actually wired.
  Real, findable in `scientific_results_repository.py`'s `freeze_protocol`.
  Should be fixed **before** the real confirmatory freeze in §2, since that
  freeze is exactly when these fields would matter for the first time.

---

## 10. The paper document itself (not the platform)

Explicitly deferred earlier, still open, now worth listing:

- Population: 5 enrolled units → 4 (Shelly excluded as a class per Source
  Admission V2) — Abstract, inventory table, any equation/text assuming `U=5`.
- Insert the closed-set as the **primary** reported RQ1/RQ2 result (not the
  per-unit binaries) — Results section, using the real numbers/figures
  already in `README.md`/`readme_img/evidence_*.png`.
- RQ3/RQ4/S1/S2/Coverage results sections stay `DATA_PENDING` placeholders
  until §3/§5/§6/§7/§8 produce real numbers.
- Discussion/Limitations: the real 0-STRONG-association finding (§4) and
  RQ4's real `DATA_NOT_AVAILABLE` (§1) belong here as honestly-reported
  constraints, not failures — the README already models this tone.
- Optional secondary same-family stress test: every enrolled unit's
  `same_model_confirmation` is still `NOT_CONFIRMED` — only relevant if the
  paper wants that secondary analysis; not required for primary closure.

---

## 11. Suggested order of operations

1. Fix the §9 bug (small, and blocks trusting §2's freeze once it happens).
2. Resolve the §2 protocol-id wrinkle, then record the ~13 real
   `record_scientist_decision()` entries in §2's table (these need the
   project owner's real judgment calls — not something to auto-fill).
3. Run the RQ3 smoke test (§3.1) — needs a live session with the operator.
4. If it passes: run the full 80-pair RQ3 campaign (§3.2) — needs many live
   sessions.
5. Real RQ3 analysis (§3.3).
6. §4 decision: pursue association calibration for real, or formally close
   it as a stated limitation.
7. Freeze the real confirmatory protocol (§2 clears) → capture the FUTURE
   period (§5.1) → run confirmatory analysis (§5.2/§5.3).
8. S1 channel-38/39 captures (§6) — can happen any time after model
   development is frozen, does not block §5.
9. Coverage/Sensitivity canonical run (§8) — falls out of §5.
10. Paper text updates (§10), once the numbers above exist.
11. S2 (§7) — only if in scope; largest remaining engineering lift.

Regenerate `readme_img/evidence_*.png` + `docs/ble/evidence_figures.ipynb`
(button in the Evidence Dashboard tab, or the two scripts in `docs/ble/`)
after every step above that changes a real number.
