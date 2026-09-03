import axios from 'axios';

export type StudioDeviceSource = 'ISOLATION_DECLARED' | 'ADDRESS_MATCH' | 'MULTIPLE_ADDRESS_MATCHES' | 'ENVIRONMENT_NO_MATCH' | 'NOT_ANALYZED' | 'DECLARED_NOT_CONFIRMED';
// Four genuinely different experimental intents -- never one generic
// "background" bucket (see the backend contracts/capture.py module docstring
// for the full rationale: a BACKGROUND_TARGET_OFF capture's expected,
// correct outcome is fundamentally different from BACKGROUND_GENERAL's "no
// target at all" and from UNKNOWN_DEVICE_COLLECTION's "other transmitters
// entirely, never counted as background evidence").
export type StudioCapturePurpose = 'TARGET_DEVICE_ON' | 'BACKGROUND_TARGET_OFF' | 'BACKGROUND_GENERAL' | 'UNKNOWN_DEVICE_COLLECTION';
export type StudioBackgroundKind = 'TARGET_DECLARED_OFF_OR_REMOVED' | 'GENERAL_AMBIENT';
export type StudioTargetPresenceStatus = 'DETECTED' | 'NOT_DETECTED' | 'INCONCLUSIVE' | 'NOT_APPLICABLE';
export type StudioTargetState = 'POWERED_ON' | 'OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED';
export type StudioDatasetRole = 'POSITIVE_CANDIDATE' | 'NEGATIVE_CANDIDATE' | 'UNKNOWN_CANDIDATE' | 'CONTROL_ONLY';
// QUARANTINED and QUARANTINED_AMBIGUOUS are deliberately different: QUARANTINED
// is only the one real, provable declared-purpose contradiction (a
// BACKGROUND_TARGET_OFF capture whose declared-off target was actually
// detected). QUARANTINED_AMBIGUOUS is everything else that lands in the same
// evidence-layer CONFLICT bucket -- overwhelmingly native-scan correlation
// ambiguity (MULTIPLE_NATIVE_CALLBACKS), unrelated to anything the operator
// declared, and NOT fixed by reapplying analysis on the same capture.
export type StudioCaptureDecision = 'ELIGIBLE_AS_POSITIVE' | 'ELIGIBLE_AS_BACKGROUND' | 'ELIGIBLE_AS_UNKNOWN' | 'CONTROL_ONLY' | 'REPETITION_NEEDED' | 'QUARANTINED' | 'QUARANTINED_AMBIGUOUS' | 'NOT_ANALYZED_YET';
export interface StudioRepairGuidanceItem { code: string; message: string }
export interface StudioLiveSelectableBundle {
  bundle_id: string;
  physical_units: string[];
  task: string | null;
  task_display: string | null;
  model_type: string | null;
  label_classes: string[];
  acquisition_reference: {
    center_frequency_hz?: number | null;
    ble_channel?: number | null;
    sample_rate_sps?: number | null;
    bandwidth_hz?: number | null;
    sample_dtype?: string | null;
    error?: string;
  };
  /** Real TEST-split false-positive rate for TARGET_VS_BACKGROUND bundles
   * (null for other scientific tasks, where "false alarm" has no single
   * meaning). Surfaced so an operator can see a model's real reliability in
   * the picker instead of discovering it live -- see backend
   * StudioRepository._bundle_reliability_summary(). */
  reliability: { false_positive_rate_on_background: number; target_device_precision: number } | null;
}
// Unlike StudioLiveSelectableBundle (which silently drops anything not
// APPROVED_FOR_LIVE_PILOT -- by design, it's an activation picker), this is
// every bundle ever exported, real full TEST-split evaluation attached, so
// "does my model really detect what it claims" can be answered for the bad
// ones too, not just the ones already cleared for live use.
export interface StudioModelReliabilityEntry {
  bundle_id: string;
  training_run_id: string;
  approval_status: StudioBundleManifest['approval_status'];
  created_at: string;
  physical_units: string[];
  task: string | null;
  task_display: string | null;
  model_type: string | null;
  label_classes: string[];
  /** null when this bundle has no TEST evaluation yet (DRAFT, or a
   * non-recommended candidate never opted into evaluateOnTestOptIn). */
  test_evaluation: StudioSplitEvaluationReport | null;
}
export interface StudioLiveCheckResult {
  predicted_class?: string | null;
  identified_device?: string | null;
  class_probability?: number | null;
  acceptance_threshold?: number | null;
  /** 'NO_BLE_PACKET_DECODED' (new): the energy burst could not be decoded
   * into a real BLE packet (e.g. non-BLE 2.4 GHz activity) -- classification
   * was correctly skipped rather than run on an out-of-distribution window.
   * Existing UI code that only special-cases 'IDENTIFIED' already treats
   * this the same as 'UNKNOWN' with no changes needed. */
  final_decision?: string | null;
  peak_power_dbfs?: number | null;
  timestamp_utc?: string | null;
  error?: string | null;
  /** BLE address decoded from the live burst, if live decode is enabled and
   * succeeded -- best-effort, purely informational. */
  decoded_address?: string | null;
}
export interface StudioQuickPresenceCheck {
  applicable: boolean;
  reason?: string;
  target_addresses?: string[];
  target_observed?: boolean;
  target_observation_count?: number;
  other_addresses_observed_count?: number;
  total_native_observations?: number;
  human_summary?: string;
}
export interface StudioLegacyCapture extends Record<string, unknown> {
  capture_id: string;
  /** The project_id this capture was actually recorded under -- "Aplicar
   * analisis" must send THIS back, never the current Step 1 project field,
   * since a session that mixes project_id spellings across captures would
   * otherwise silently break AddressBinding lookups for the mismatched ones. */
  project_id?: string | null;
  execution_id?: string | null;
  campaign_id?: string | null;
  condition_id?: string | null;
  created_at_utc?: string | null;
  duration_seconds?: number | null;
  ble_channel?: number;
  center_frequency_hz?: number;
  sample_rate_sps?: number;
  target_address?: string | null;
  acquisition_quality?: string;
  replay?: Record<string, unknown> | null;
  /** One-glance "whose recording is this" -- never leave the operator
   * guessing between a real device's session and pure environmental noise
   * from an opaque capture_id alone. */
  device_label?: string;
  device_source?: StudioDeviceSource;
  /** Human-facing "Tipo de captura" (Dispositivo encendido / Entorno --
   * dispositivo apagado / Entorno general / Sin clasificar / Sintetica de
   * pruebas) -- what the operator declared this capture was FOR, distinct
   * from device_label (which device it turned out to be). */
  capture_type_label?: string;
  capture_decision?: StudioCaptureDecision;
  target_presence_status?: StudioTargetPresenceStatus;
  /** Only present when capture_decision needs "corregir y repetir" guidance
   * (REPETITION_NEEDED / CONTROL_ONLY / QUARANTINED) -- concrete, named
   * causes, never a vague "capture failed". */
  repair_guidance?: StudioRepairGuidanceItem[];
}
export interface StudioLegacyCaptureListing {
  captures: StudioLegacyCapture[];
  classification: Record<string, string | null>;
}

export interface StudioPhysicalUnit extends Record<string, unknown> {
  physical_unit_id: string;
  project_id: string;
  device_family: string;
  manufacturer?: string | null;
  model?: string | null;
  status: string;
  first_registered_at: string;
  same_model_confirmation: 'CONFIRMED' | 'NOT_CONFIRMED';
  same_model_confirmation_basis: string | null;
  rq4_eligibility: 'ELIGIBLE' | 'NOT_ELIGIBLE';
  rq4_eligibility_reason: string | null;
}
export interface StudioAddressBinding extends Record<string, unknown> {
  binding_id: string;
  project_id: string;
  address: string;
  address_type: string;
  bound_physical_unit_id?: string | null;
  binding_status: string;
  first_seen: string;
  last_seen: string;
}

export interface StudioCaptureRecord extends Record<string, unknown> {
  capture_id: string;
  project_id: string;
  campaign_id: string;
  session_id: string;
  execution_id: string;
  physical_unit_id?: string | null;
  capture_purpose?: StudioCapturePurpose | null;
  target_state?: StudioTargetState | null;
  background_kind?: StudioBackgroundKind | null;
  target_reference_id?: string | null;
  dataset_role?: StudioDatasetRole | null;
  target_presence_status?: StudioTargetPresenceStatus | null;
  sample_rate_sps: number;
  center_frequency_hz: number;
  sample_count: number;
  iq_sha256: string;
  acquisition_quality: string;
  replay_status: string;
  created_at: string;
}

export interface StudioExample extends Record<string, unknown> {
  example_id: string;
  capture_id: string;
  physical_unit_id?: string | null;
  association_status: string;
  quality_status: string;
  dataset_eligibility: string;
}

export type StudioJobState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export interface StudioJob extends Record<string, unknown> {
  job_id: string;
  job_type: 'EVIDENCE_BUILD' | 'TRAINING_RUN' | 'PREPARE_AND_TRAIN' | 'CAMPAIGN_SESSION' | 'GUIDED_CAPTURE' | 'DEVICE_SCRUB' | 'TRAIN_SELECTED_MODELS' | 'CAMPAIGN_SCHEDULE_EXECUTE';
  state: StudioJobState;
  phase?: string | null;
  overall_progress?: number;
  message?: string | null;
  result_summary?: Record<string, unknown>;
  training_run_id?: string;
  error?: string;
}

// Paper campaign schedule (Study Control Center, phases 04/06/07,
// 2026-08-11) -- the SAME real mechanism serves the Qualification Pilot
// (qualification_only=true) and DEVELOPMENT/VALIDATION campaigns
// (qualification_only=false).
export interface StudioPaperCampaignScheduleEntry extends Record<string, unknown> {
  planned_capture_id: string;
  protocol_id: string;
  day_id: string;
  campaign_period: string | null;
  physical_unit_id: string;
  capture_order: number;
  pre_or_post: 'PRE' | 'POST' | 'NOT_APPLICABLE';
  intervention_arm: 'RESET' | 'CONTROL' | 'NOT_APPLICABLE';
  packet_condition: string;
  channel: number;
  receiver_epoch: string;
  receiver_session_id: string;
  capture_purpose: StudioCapturePurpose;
  executed: boolean;
  executed_capture_id: string | null;
}
export interface StudioPaperCampaignSchedule extends Record<string, unknown> {
  schedule_id: string;
  schedule_version: number;
  protocol_id: string;
  entries: StudioPaperCampaignScheduleEntry[];
  qualification_only: boolean;
  receiver_session_id: string;
  frozen_at: string;
}
export interface StudioPaperCampaignRejection extends Record<string, unknown> {
  schedule_id: string;
  protocol_id: string;
  planned_capture_id: string | null;
  reason: string;
  attempted: Record<string, unknown>;
  operator_id: string | null;
  rejected_at: string;
}

export type StudioDataOrigin = 'REAL_B200' | 'SYNTHETIC_TEST_ONLY';
export type StudioOperationalUse = 'ALLOWED' | 'FORBIDDEN';

export interface StudioDatasetManifest extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  data_origin: StudioDataOrigin;
  frozen: boolean;
  physical_units: string[];
  captures: string[];
  sessions: string[];
  example_ids: string[];
  class_distribution: Record<string, number>;
  dataset_manifest_sha256?: string | null;
}
export interface StudioDatasetBuildResult {
  dataset: StudioDatasetManifest;
  n_selected: number;
  n_excluded: number;
  excluded_reasons: Record<string, string>;
}

export interface StudioQualityReport extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  exact_duplicates: { status: string; duplicate_groups: string[][] };
  sample_overlap: { status: string; overlapping_pairs: string[][] };
  near_duplicates: { status: string; flagged_pairs: string[][]; note?: string };
  gate_decision: 'ACCEPTED_FOR_TRAINING' | 'ACCEPTED_WITH_LIMITATIONS' | 'NOT_ACCEPTED_FOR_TRAINING';
  gate_reasons: string[];
}

export interface StudioSplitManifest extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
  split_status: 'READY' | 'NOT_FEASIBLE';
  infeasibility_reason?: string | null;
  assignments: { example_id: string; physical_unit_id?: string | null; session_id: string; split: string }[];
  leakage_check: { status: string; overlapping_keys: Record<string, string[]> };
  split_manifest_sha256?: string | null;
}

export interface StudioTrainingRun extends Record<string, unknown> {
  training_run_id: string;
  status: string;
  model_type: string;
  scientific_task: string;
  campaign_id?: string;
  dataset_id: string;
  dataset_version: string;
  data_origin: StudioDataOrigin;
  operational_use: StudioOperationalUse;
  metrics?: Record<string, { accuracy: number | null; n_examples: number }> | null;
  label_classes?: string[] | null;
  error?: Record<string, unknown> | null;
  started_at?: string | null;
  completed_at?: string | null;
}

// "Pantalla de revision antes de entrenar": TRAIN/VALIDATION/TEST classes,
// sessions per class, examples per class and capture_ids actually used --
// computed backend-side strictly from the frozen DatasetManifest and the
// already-built SplitManifest, so it can never drift from what training
// itself will consume (the original bug: interface showed 0 eligible
// examples while training used hundreds).
export interface StudioSplitPreviewData { classes: string[]; sessions_by_class: Record<string, string[]>; examples_by_class: Record<string, number>; capture_ids: string[] }
// Full detail for one FAILED sample_overlap pair -- never just a count. Two
// examples, their exact sample ranges, how much of the smaller window they
// share, which split each landed in (splits are session-disjoint, so
// cross_partition should always be false -- shown explicitly rather than
// assumed), and a concrete, evidence-based reason (never a guess) the
// extractor produced two overlapping-but-not-identical examples.
export interface StudioSampleOverlapPairDetail extends Record<string, unknown> {
  example_id_a: string; example_id_b: string;
  capture_id_a: string; capture_id_b: string;
  iq_start_sample_a: number; iq_end_sample_a: number;
  iq_start_sample_b: number; iq_end_sample_b: number;
  overlap_samples: number; overlap_fraction_of_smaller_window: number;
  reason: string;
  split_a: string | null; split_b: string | null; cross_partition: boolean;
}
export interface StudioTrainingPreview extends Record<string, unknown> {
  dataset_id: string; dataset_version: string; scientific_task: string;
  split_status: 'READY' | 'NOT_FEASIBLE'; infeasibility_reason?: string | null; ready_to_train: boolean;
  // Checked fresh over the frozen dataset's own examples, the same set
  // build_quality_report/training will see -- ready_to_train is false
  // whenever this is false too, so the review can never say "ready" while
  // the real quality gate would reject the same data (exact-duplicate/
  // sample-overlap groups, e.g. from a capture_id repeated in the source list).
  quality_gate_ok: boolean; quality_gate_reasons: string[];
  sample_overlap_pairs: StudioSampleOverlapPairDetail[];
  splits: { TRAIN: StudioSplitPreviewData; VALIDATION: StudioSplitPreviewData; TEST: StudioSplitPreviewData };
  eligible_examples_total: number; excluded_examples_total: number; excluded_reasons: Record<string, string>;
  quarantined_capture_ids: string[];
}

export interface StudioSplitEvaluationReport {
  split: string;
  n_examples: number;
  n_comparable_to_known_classes: number;
  accuracy: number | null;
  precision_per_class: Record<string, number>;
  recall_per_class: Record<string, number>;
  f1_per_class: Record<string, number>;
  confusion_matrix: Record<string, Record<string, number>>;
  /** "INVALID_SINGLE_CLASS_EVALUATION" when this split saw fewer than 2
   * known classes -- accuracy/f1 are trivially perfect in that case (a
   * model that always guesses the one class present is always "right"),
   * never real evidence of discrimination. See the single-class TRAIN gate. */
  evaluation_validity?: string;
  /** Average per-class F1/recall -- unlike raw accuracy, these can't hide a
   * model that only ever predicts the majority class behind a high number. */
  macro_f1?: number | null;
  balanced_accuracy?: number | null;
}
export interface StudioLabelProvenanceReport extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  total_examples: number;
  counts: Record<string, number>;
  fractions: Record<string, number>;
  strong_fraction: number;
}
export interface StudioDatasetCompositionReport extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  total_examples: number;
  channel_counts: Record<string, number>;
  session_count: number;
  day_counts: Record<string, number>;
  physical_unit_counts: Record<string, number>;
}
// NOT_EVALUATED: no TEST evaluation exists for this training_run_id yet
// (the common case for a non-recommended candidate). SINGLE_SELECTION_
// GUARANTEE: prepare_and_train() itself TEST-evaluated exactly this one
// model, chosen from VALIDATION -- the scientifically clean case.
// OPT_IN_MULTI_CANDIDATE_COMPARISON: an operator explicitly asked to
// TEST-evaluate this NON-recommended candidate anyway (evaluateOnTestOptIn),
// to compare exported models live -- a real, permanent caveat, never to be
// confused with the single-selection guarantee.
export type StudioTestEvaluationProvenance = 'NOT_EVALUATED' | 'SINGLE_SELECTION_GUARANTEE' | 'OPT_IN_MULTI_CANDIDATE_COMPARISON';
export interface StudioEvaluationResult {
  evaluation_report: Record<string, StudioSplitEvaluationReport>;
  calibration: { acceptance_threshold: number | null; calibrated_on: string; min_identified_precision: number };
  test_evaluation_provenance?: StudioTestEvaluationProvenance;
}

export interface StudioBundleManifest extends Record<string, unknown> {
  bundle_id: string;
  training_run_id: string;
  data_origin: StudioDataOrigin;
  operational_use: StudioOperationalUse;
  artifact_hashes: Record<string, string>;
  bundle_sha256?: string | null;
  // TEST_NOT_EXECUTED != REJECTED: every other acceptance gate passed and
  // the only open item is that this training_run_id has no TEST evaluation
  // yet (the normal state for a non-recommended candidate -- TEST stays
  // reserved for the one model prepare_and_train() actually selected).
  // REJECTED means a gate was checked and genuinely failed.
  approval_status: 'DRAFT' | 'EVALUATED' | 'SYNTHETIC_PIPELINE_VERIFIED' | 'APPROVED_FOR_LIVE_PILOT' | 'REJECTED' | 'TEST_NOT_EXECUTED';
  test_evaluation_provenance: StudioTestEvaluationProvenance;
}
export interface StudioExportResult {
  bundle: StudioBundleManifest;
  gate_reasons: string[];
}
export interface StudioInferenceDecision {
  example_id: string;
  distance: number | null;
  class_probability: number | null;
  acceptance_threshold: number | null;
  predicted_class: string | null;
  final_decision: 'IDENTIFIED' | 'UNKNOWN' | 'INSUFFICIENT_EVIDENCE';
}

export class BleRffiStudioApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  // A getter, not a field initializer: a `= ${this.baseURL}/...` class field
  // initializer runs before TypeScript assigns constructor parameter
  // properties, so `this.baseURL` reads as undefined at that point -- every
  // request silently became a same-origin relative "undefined/api/..." URL.
  private get root() { return `${this.baseURL}/api/ble-rffi-studio`; }

  async legacyCaptures() { return (await axios.get<StudioLegacyCaptureListing>(`${this.root}/legacy-captures`)).data; }
  /** Deletes a raw B200 capture -- real, irreversible IQ removal (mainly
   * meant for the RF-overflow retry artifacts the campaign retry loop
   * leaves behind). Also removes this module's CaptureRecord/evidence for
   * it, if any were built. */
  async deleteLegacyCapture(captureId: string) {
    return (await axios.delete<{ deleted: boolean; capture_id: string }>(`${this.root}/legacy-captures/${encodeURIComponent(captureId)}`)).data;
  }

  async physicalUnits() { return (await axios.get<StudioPhysicalUnit[]>(`${this.root}/physical-units`)).data; }
  async createPhysicalUnit(body: { physical_unit_id: string; project_id: string; device_family: string; manufacturer?: string; model?: string; operator_declaration_id: string }) {
    return (await axios.post<StudioPhysicalUnit>(`${this.root}/physical-units`, body)).data;
  }
  // Study Control Center, phase 02 (2026-08-11) -- explicit operator
  // decisions, never inferred from device_family/model.
  async confirmSameModel(physicalUnitId: string, basis: string) {
    return (await axios.post<StudioPhysicalUnit>(`${this.root}/physical-units/${encodeURIComponent(physicalUnitId)}/confirm-same-model`, { basis })).data;
  }
  async setRq4Eligibility(physicalUnitId: string, eligible: boolean, reason: string) {
    return (await axios.post<StudioPhysicalUnit>(`${this.root}/physical-units/${encodeURIComponent(physicalUnitId)}/rq4-eligibility`, { eligible, reason })).data;
  }
  async addressBindings() { return (await axios.get<StudioAddressBinding[]>(`${this.root}/address-bindings`)).data; }
  async createAddressBinding(body: { project_id: string; address: string; address_type?: string; physical_unit_id: string; reason?: string; decision_artifact_id?: string }) {
    return (await axios.post<StudioAddressBinding>(`${this.root}/address-bindings`, body)).data;
  }

  async captures() { return (await axios.get<StudioCaptureRecord[]>(`${this.root}/captures`)).data; }
  async createCapture(body: {
    capture_id: string; project_id: string; campaign_id: string; execution_id?: string; session_id?: string;
    isolation_declared_physical_unit_id?: string | null;
    capture_purpose?: StudioCapturePurpose; target_state?: StudioTargetState; background_kind?: StudioBackgroundKind;
    target_reference_id?: string; dataset_role?: StudioDatasetRole;
  }) {
    return (await axios.post<StudioCaptureRecord>(`${this.root}/captures`, body)).data;
  }
  async getCapture(captureId: string) { return (await axios.get<StudioCaptureRecord>(`${this.root}/captures/${encodeURIComponent(captureId)}`)).data; }
  async captureRepairGuidance(captureId: string) { return (await axios.get<StudioRepairGuidanceItem[]>(`${this.root}/captures/${encodeURIComponent(captureId)}/repair-guidance`)).data; }
  /** Fast (~1s, no IQ decode) triage: was the declared target seen at all by
   * the native Windows BLE scan during this capture? See README's "Quick
   * native-scan presence check" section. */
  async quickPresenceCheck(captureId: string) { return (await axios.get<StudioQuickPresenceCheck>(`${this.root}/captures/${encodeURIComponent(captureId)}/quick-presence-check`)).data; }

  async startEvidenceJob(captureId: string, body: { project_id: string; ble_channel: number; replay_run_id?: string }) {
    return (await axios.post<StudioJob>(`${this.root}/captures/${encodeURIComponent(captureId)}/evidence-jobs`, body)).data;
  }
  /** Runs the resumable OFFLINE_REPLAY (decode, the slow part -- can take
   * many minutes) + Evidence Stage for a CaptureRecord that already exists.
   * Idempotent by default: a capture that already has evidence is reported
   * `skipped: true` rather than silently re-decoded; pass force to redo it
   * anyway. This is the deliberately separable counterpart to
   * startCampaignSession({ capture_only: true }). */
  async startReplayAndEvidenceJob(captureId: string, body: { project_id: string; ble_channel: number; force?: boolean }) {
    return (await axios.post<StudioJob>(`${this.root}/captures/${encodeURIComponent(captureId)}/replay-and-evidence-jobs`, body)).data;
  }
  async examples(captureId: string) { return (await axios.get<StudioExample[]>(`${this.root}/captures/${encodeURIComponent(captureId)}/examples`)).data; }
  async job(jobId: string) { return (await axios.get<StudioJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data; }

  async datasets() { return (await axios.get<StudioDatasetManifest[]>(`${this.root}/datasets`)).data; }
  async createDataset(body: { dataset_id: string; dataset_version: string; project_id: string; campaign_id: string; capture_ids: string[] }) {
    return (await axios.post<StudioDatasetBuildResult>(`${this.root}/datasets`, body)).data;
  }
  /** Deletes a frozen dataset manifest and every split built from it.
   * Never touches the underlying captures/evidence -- only the frozen
   * selection over them. Existing training runs/bundles that already
   * reference this dataset keep their own copy of the manifest hash and
   * stay valid as a historical record. */
  async deleteDataset(datasetId: string, datasetVersion: string) {
    return (await axios.delete<{ deleted: boolean; dataset_id: string; dataset_version: string; deleted_splits: string[] }>(
      `${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(datasetVersion)}`,
    )).data;
  }
  async buildQualityReport(datasetId: string, version: string, runNearDuplicates = false) {
    return (await axios.post<StudioQualityReport>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/quality-report`, { run_near_duplicates: runNearDuplicates })).data;
  }
  async getQualityReport(datasetId: string, version: string) {
    return (await axios.get<StudioQualityReport>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/quality-report`)).data;
  }
  /** What fraction of this dataset's examples rest on STRONG (independently
   * corroborated) association versus PHYSICAL_ISOLATION_DECLARED/AMBIGUOUS/
   * CONFLICT/NONE -- for the benchmark panel, so a high accuracy backed
   * mostly by declared isolation is never shown as equivalent to one backed
   * by strong evidence. */
  async labelProvenance(datasetId: string, version: string) {
    return (await axios.get<StudioLabelProvenanceReport>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/label-provenance`)).data;
  }
  /** Purely informational, never a gate: how the dataset's examples are
   * distributed across BLE channel, real capture day, session, and physical
   * unit -- a lopsided capture protocol is invisible in an aggregate
   * accuracy number alone. */
  async datasetComposition(datasetId: string, version: string) {
    return (await axios.get<StudioDatasetCompositionReport>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/composition-report`)).data;
  }

  async buildSplit(datasetId: string, version: string, scientificTask: string) {
    return (await axios.post<StudioSplitManifest>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/splits/${encodeURIComponent(scientificTask)}`)).data;
  }
  async getSplit(datasetId: string, version: string, scientificTask: string) {
    return (await axios.get<StudioSplitManifest>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/splits/${encodeURIComponent(scientificTask)}`)).data;
  }
  async trainingPreview(datasetId: string, version: string, scientificTask: string) {
    return (await axios.get<StudioTrainingPreview>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/splits/${encodeURIComponent(scientificTask)}/training-preview`)).data;
  }
  /** UI-reachable fix for a quality gate blocked on exact duplicates or
   * sample overlap: quarantines exactly the redundant/overlapping examples
   * (deterministic resolution, never a guess at which decode is "better")
   * directly on each capture's evidence. Re-run "Revisar datos" afterwards --
   * it rebuilds its preview dataset fresh from that now-fixed evidence. */
  async resolveDatasetDuplicates(captureIds: string[]) {
    return (await axios.post<{ quarantined_example_ids: string[]; details: Record<string, string>; captures_updated: string[] }>(
      `${this.root}/datasets/resolve-duplicates`, { capture_ids: captureIds },
    )).data;
  }

  async startTraining(body: {
    training_run_id: string; project_id: string; campaign_id: string; dataset_id: string; dataset_version: string;
    dataset_manifest_sha256: string; split_manifest_sha256: string; scientific_task: string; model_type: string;
    representation_profile_id: string; base_preprocessing_profile_id?: string; random_seed?: number;
  }) {
    return (await axios.post<StudioJob>(`${this.root}/training-runs`, body)).data;
  }
  async trainingRuns() { return (await axios.get<StudioTrainingRun[]>(`${this.root}/training-runs`)).data; }
  async getTrainingRun(id: string) { return (await axios.get<StudioTrainingRun>(`${this.root}/training-runs/${encodeURIComponent(id)}`)).data; }
  /** Deletes a TrainingRun's fitted artifact + evaluation history. Any bundle
   * already exported from it keeps its own copy of every artifact and stays
   * fully usable -- only re-deriving a NEW bundle from this exact run stops
   * being possible. */
  async deleteTrainingRun(id: string) {
    return (await axios.delete<{ deleted: boolean; training_run_id: string }>(`${this.root}/training-runs/${encodeURIComponent(id)}`)).data;
  }

  async evaluate(trainingRunId: string, minIdentifiedPrecision = 0.9) {
    return (await axios.post<StudioEvaluationResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/evaluation`, { min_identified_precision: minIdentifiedPrecision })).data;
  }
  async getEvaluation(trainingRunId: string) {
    return (await axios.get<StudioEvaluationResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/evaluation`)).data;
  }
  /** Explicit, audited opt-in: TEST-evaluate a NON-recommended candidate
   * anyway, so it can be exported+approved and compared live in Live Monitor
   * alongside the officially recommended model. Breaks the "TEST evaluated
   * exactly once" guarantee on purpose -- acknowledge_multiple_comparison_risk
   * must be true or the backend rejects the call (400). */
  async evaluateOnTestOptIn(trainingRunId: string) {
    return (await axios.post<StudioEvaluationResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/evaluate-on-test-opt-in`, { acknowledge_multiple_comparison_risk: true })).data;
  }

  async exportBundle(trainingRunId: string, body: { bundle_id: string; acceptance_criteria?: Record<string, number>; model_card_text?: string }) {
    return (await axios.post<StudioExportResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/export`, body)).data;
  }
  async bundles() { return (await axios.get<StudioBundleManifest[]>(`${this.root}/bundles`)).data; }
  /** Every bundle ever exported, real full TEST-split evaluation attached --
   * for a "review all my models" surface, not the live-activation picker
   * (liveSelectableModels(), which silently drops anything not
   * APPROVED_FOR_LIVE_PILOT). */
  async modelReliabilityOverview() { return (await axios.get<StudioModelReliabilityEntry[]>(`${this.root}/models/reliability-overview`)).data; }
  async getBundle(id: string) { return (await axios.get<StudioBundleManifest>(`${this.root}/bundles/${encodeURIComponent(id)}`)).data; }
  async approveBundle(id: string) { return (await axios.post<StudioBundleManifest>(`${this.root}/bundles/${encodeURIComponent(id)}/approve`)).data; }
  /** Deletes an exported model bundle -- the deployable artifact Live
   * Monitor's model selector lists. Never touches the TrainingRun/dataset it
   * came from. */
  async deleteBundle(id: string) {
    return (await axios.delete<{ deleted: boolean; bundle_id: string }>(`${this.root}/bundles/${encodeURIComponent(id)}`)).data;
  }

  async runInference(bundleId: string, captureId: string) {
    return (await axios.post<StudioInferenceDecision[]>(`${this.root}/bundles/${encodeURIComponent(bundleId)}/inference`, { capture_id: captureId })).data;
  }

  async scientificTasks() { return (await axios.get<Record<string, string>>(`${this.root}/scientific-tasks`)).data; }
  async feasibility(datasetId: string, version: string, scientificTask: string) {
    return (await axios.get<StudioFeasibility>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/feasibility`, { params: { scientific_task: scientificTask } })).data;
  }
  async taskRecommendation(datasetId: string, version: string) {
    return (await axios.get<StudioTaskRecommendation>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/task-recommendation`)).data;
  }
  async prepareAndTrain(body: {
    capture_ids: string[]; project_id: string; campaign_id: string; scientific_task: string;
    ble_channel?: number; dataset_id?: string; dataset_version?: string; speed_profile?: 'quick_pilot' | 'normal';
  }) {
    return (await axios.post<StudioJob>(`${this.root}/prepare-and-train`, body)).data;
  }
  async seedSyntheticDemo() { return (await axios.post<StudioSyntheticDemoSeed>(`${this.root}/synthetic-demo/seed`)).data; }

  /** One-call automation over prepare-and-train: per registered device, how
   * many of its own target sessions and how many project-shared background
   * sessions are already captured -- `ready` mirrors TARGET_VS_BACKGROUND's
   * own feasibility gate (>=3 independent sessions each), so the UI can show
   * which devices can be trained right now without fetching capture lists. */
  async autoTrainCandidates() {
    return (await axios.get<Array<{
      physical_unit_id: string; project_id: string; target_captures: number; target_sessions: number;
      background_captures: number; background_sessions: number; ready: boolean;
    }>>(`${this.root}/auto-train/candidates`)).data;
  }
  /** Resolves this device's own TARGET_DEVICE_ON captures + every
   * project-shared BACKGROUND_* capture automatically (the same selection an
   * operator would otherwise curate by hand) and launches the same
   * PREPARE_AND_TRAIN job prepareAndTrain() does. */
  async autoTrain(physicalUnitId: string) {
    return (await axios.post<StudioJob>(`${this.root}/auto-train/${encodeURIComponent(physicalUnitId)}`, {})).data;
  }

  /** For an "always-on" device (see backend/README.md): every background
   * capture in its project that still shows real evidence of it (either an
   * uncontested address match on a BACKGROUND_GENERAL capture, or the
   * declared-off contradiction EvidenceStage already flags). Purely
   * informational -- launching the scrub itself re-detects this same list. */
  async scrubBackgroundCandidates(physicalUnitId: string) {
    return (await axios.get<StudioCaptureRecord[]>(`${this.root}/scrub-background/${encodeURIComponent(physicalUnitId)}/candidates`)).data;
  }
  /** One click: scrub+verify every contaminated background capture for this
   * device, then train and export both an ORIGINAL-background and a
   * SCRUBBED-background model set for direct TEST-metric comparison. */
  async scrubBackground(physicalUnitId: string) {
    return (await axios.post<StudioJob>(`${this.root}/scrub-background/${encodeURIComponent(physicalUnitId)}`, {})).data;
  }

  /** Training Service: trains an operator-chosen subset of model_type
   * candidates against 1+ ALREADY-frozen, already-labeled dataset(s) (never
   * builds a dataset from raw captures). One dataset -> a normal
   * TARGET_VS_BACKGROUND detector. 2+ datasets -> combined into ONE
   * multi-class SAME_MODEL_UNIT_IDENTIFICATION model that says WHICH device
   * is present (never a binary "any of these" family -- see backend
   * StudioRepository.combine_datasets_for_identification()). The run's name
   * (date + time + the dataset's own device(s)) is generated internally by
   * the backend, not supplied here. */
  /** backgroundDataset (optional, only meaningful with 2+ datasetKeys): use
   * ONE dataset's background-only examples as the SOLE "environment absent"
   * evidence for every device, instead of pooling whatever (often much
   * thinner) background each per-device dataset happens to carry. Each
   * device dataset then contributes ONLY its own target examples. */
  async trainSelectedModels(
    datasetKeys: Array<{ dataset_id: string; dataset_version: string }>, modelTypes: string[],
    backgroundDataset?: { dataset_id: string; dataset_version: string } | null,
  ) {
    return (await axios.post<StudioJob>(`${this.root}/training-service/run`, {
      dataset_keys: datasetKeys, model_types: modelTypes, background_dataset: backgroundDataset || null,
    })).data;
  }
  /** Explicit, operator-visible export -- export already happens
   * automatically right after training, but this gives a real button
   * instead of only a silent background step (and is safe to click again:
   * export/approve are themselves idempotent). */
  async trainingServiceExport(
    runName: string, trainedModels: Array<{ training_run_id: string; model_type: string }>, recommendedTrainingRunId?: string | null,
  ) {
    return (await axios.post<Array<{ bundle_id: string; model_type: string; training_run_id: string; approval_status: string | null; error?: string }>>(
      `${this.root}/training-service/export`,
      { run_name: runName, trained_models: trainedModels, recommended_training_run_id: recommendedTrainingRunId || null },
    )).data;
  }

  async campaignDeviceStatus() { return (await axios.get<StudioCampaignDeviceStatus>(`${this.root}/campaign/device-status`)).data; }

  // Live Monitor "model check" -- reuses Live Monitor's own B200 session
  // (see real_spectrum_stream.py); never opens a second SDR session.
  async liveSelectableModels() { return (await axios.get<StudioLiveSelectableBundle[]>(`${this.root}/live-monitor/models`)).data; }
  async enableLiveMonitorCheck(bundleId: string) { return (await axios.post<{ status: string; bundle_id: string }>(`${this.root}/live-monitor/enable/${encodeURIComponent(bundleId)}`)).data; }
  /** bundleId given: stop watching just that one (always prefer this --
   * never disturbs any other bundle currently watched, whether from the
   * single-select health check or the multi-device watch list). Omitted:
   * full teardown, reserved for the panel's own unmount cleanup. */
  async disableLiveMonitorCheck(bundleId?: string) {
    const url = bundleId ? `${this.root}/live-monitor/disable/${encodeURIComponent(bundleId)}` : `${this.root}/live-monitor/disable`;
    return (await axios.post<{ status: string; bundle_id?: string }>(url)).data;
  }
  /** Keyed by bundle_id -- every currently-watched bundle's latest result. */
  async liveMonitorResult() { return (await axios.get<Record<string, StudioLiveCheckResult>>(`${this.root}/live-monitor/result`)).data; }
  async retrainReference(bundleId: string) {
    return (await axios.get<{ project_id: string; campaign_id: string; scientific_task: string; ble_channel: number; capture_ids: string[] }>(
      `${this.root}/bundles/${encodeURIComponent(bundleId)}/retrain-reference`,
    )).data;
  }
  /** Same idea, but for the Benchmark panel's "Reentrenar (mismas capturas)"
   * action -- works for a candidate training_run_id that was never exported
   * to a bundle at all. */
  async retrainReferenceFromTrainingRun(trainingRunId: string) {
    return (await axios.get<{ project_id: string; campaign_id: string; scientific_task: string; ble_channel: number; capture_ids: string[] }>(
      `${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/retrain-reference`,
    )).data;
  }
  async startCampaignSession(body: {
    ble_channel?: number; duration_seconds?: number; gain_db?: number; condition_label: string;
    physical_unit_id?: string | null; project_id: string; campaign_id: string; session_index?: number; device_id?: string;
    isolation_declared?: boolean;
    /** "Que quieres capturar?" -- defaults to TARGET_DEVICE_ON server-side.
     * BACKGROUND_TARGET_OFF requires operator_confirmed_target_absent. */
    capture_purpose?: StudioCapturePurpose;
    operator_confirmed_target_absent?: boolean;
    /** Stops right after the real B200 acquisition (CaptureRecord built,
     * B200 released) -- OFFLINE_REPLAY/evidence (the slow part) are applied
     * later via startReplayAndEvidenceJob, for any number of captures,
     * whenever there's time for the decode. Lets an operator capture
     * several devices in a hurry without waiting between each one. */
    capture_only?: boolean;
  }) {
    return (await axios.post<StudioJob>(`${this.root}/campaign/sessions`, body)).data;
  }

  // Paper campaign schedule (Study Control Center, phases 04/06/07, 2026-08-11).
  async freezeCampaignSchedule(body: { schedule_id: string; protocol_id: string; entries: Record<string, unknown>[]; qualification_only?: boolean; receiver_session_id?: string }) {
    return (await axios.post<StudioPaperCampaignSchedule>(`${this.root}/campaign/schedule`, body)).data;
  }
  async getCampaignSchedule(scheduleId: string) {
    return (await axios.get<StudioPaperCampaignSchedule>(`${this.root}/campaign/schedule/${encodeURIComponent(scheduleId)}`)).data;
  }
  async getCampaignScheduleRejections(scheduleId: string) {
    return (await axios.get<StudioPaperCampaignRejection[]>(`${this.root}/campaign/schedule/${encodeURIComponent(scheduleId)}/rejections`)).data;
  }
  async executeNextCampaignScheduleCapture(scheduleId: string, body: { duration_seconds?: number; gain_db?: number; operator_id?: string; operator_confirmed_target_absent?: boolean }) {
    return (await axios.post<StudioJob>(`${this.root}/campaign/schedule/${encodeURIComponent(scheduleId)}/execute-next`, body)).data;
  }

  /** Probes with short, throwaway B200 captures for a real signal
   * (TARGET_DEVICE_ON: waits for the device to actually be detected before
   * recording) or a clean environment (BACKGROUND_*: waits until nothing
   * dangerously strong is present) BEFORE launching the real, saved capture.
   * Always stops after the real B200 acquisition (capture_only semantics) --
   * OFFLINE_REPLAY/evidence are applied later, same as startCampaignSession. */
  async startGuidedCapture(body: {
    ble_channel?: number; duration_seconds?: number; gain_db?: number; condition_label: string;
    physical_unit_id?: string | null; project_id: string; campaign_id: string; session_index?: number; device_id?: string;
    isolation_declared?: boolean;
    capture_purpose?: StudioCapturePurpose;
    operator_confirmed_target_absent?: boolean;
    probe_duration_seconds?: number;
    probe_timeout_seconds?: number;
  }) {
    return (await axios.post<StudioJob>(`${this.root}/campaign/guided-sessions`, body)).data;
  }
}

export interface StudioCampaignDeviceStatus {
  device_id: string;
  status: 'AVAILABLE' | 'ACQUIRED' | string;
  owner?: string | null;
  operation_id?: string | null;
  acquired_at?: string | null;
  lease_expires_at?: string | null;
}
export interface StudioCampaignSessionResult extends Record<string, unknown> {
  session_id: string;
  capture_id: string;
  /** Absent when the session was launched with capture_only: true -- no
   * replay/evidence has run yet for this capture. */
  replay_run_id?: string;
  condition_label: string;
  physical_unit_id?: string | null;
  capture_purpose?: StudioCapturePurpose;
  target_state?: StudioTargetState;
  dataset_role?: StudioDatasetRole;
  evidence_summary?: Record<string, unknown>;
}
export interface StudioReplayAndEvidenceResult extends Record<string, unknown> {
  skipped: boolean;
  reason?: 'ALREADY_HAS_EVIDENCE';
  capture_id: string;
  replay_run_id?: string;
  evidence_summary?: Record<string, unknown>;
}

export interface StudioFeasibility {
  scientific_task: string;
  scientific_task_display: string;
  feasible: boolean;
  have: Record<string, number>;
  need: Record<string, number>;
  human_summary: string;
  /** Concrete "do this next" sentences (e.g. "Anade 2 sesion(es) mas del
   * dispositivo objetivo") -- empty once feasible is true. Never leave the
   * operator to infer an action from the have/need numbers alone. */
  next_steps: string[];
  /** 0..1, how close this task is to feasible -- used to rank candidates. */
  progress: number;
}
export interface StudioTaskRecommendation {
  recommended_task: string;
  recommended_task_display: string;
  reason: string;
  candidates: StudioFeasibility[];
}
export interface StudioSyntheticDemoSeed {
  project_id: string;
  campaign_id: string;
  capture_ids: string[];
  physical_unit_ids: string[];
}
export interface StudioPrepareAndTrainSummary {
  stopped_at: string | null;
  stopped_reason: string | null;
  dataset_id: string | null;
  dataset_version: string | null;
  data_origin: StudioDataOrigin | null;
  split_status: string | null;
  feasibility: StudioFeasibility | null;
  trained_models: { training_run_id: string; model_type: string; composite_score: number }[];
  skipped_models: { model_type: string; reason: string }[];
  recommended_training_run_id: string | null;
  recommended_reason: string | null;
  /** Evaluated exactly once, only for recommended_training_run_id, only
   * after model+hyperparameters+preprocessing+UNKNOWN threshold were frozen
   * via VALIDATION-only selection. Null when NO_MODEL_ACCEPTED or no model
   * was recommended -- TEST is never touched in that case either. */
  final_test_evaluation: Record<string, unknown> | null;
}

/** Never show a raw AxiosError to an operator: always resolve to a
 * plain-language sentence naming the endpoint and what happened. */
export function describeApiError(error: unknown): string {
  const withResponse = error as { response?: { status?: number; data?: { detail?: string } }; config?: { url?: string; method?: string }; message?: string };
  const status = withResponse?.response?.status;
  const url = withResponse?.config?.url;
  const detail = withResponse?.response?.data?.detail;
  if (status === 404) {
    return `No se pudo acceder al servicio BLE-RFFI Studio. Ruta solicitada: ${url ?? '(desconocida)'}. Codigo: 404.`;
  }
  if (status) {
    return `El servicio respondio con un error (codigo ${status}) en ${url ?? '(ruta desconocida)'}${detail ? `: ${detail}` : '.'}`;
  }
  if (withResponse?.message?.toLowerCase().includes('network')) {
    return 'No se pudo contactar con el backend de BLE-RFFI Studio. Verifica que el servidor este en ejecucion en el puerto 8000.';
  }
  return withResponse?.message || 'Ocurrio un error inesperado al comunicarse con el backend.';
}

/** A campaign session job's raw `error` string is an internal exception
 * chain (CampaignSessionError -> HYBRID_SESSION_FAILED -> RuntimeError ->
 * CAPTURE_FAILED, etc.) -- never show that chain verbatim to an operator.
 * Translates the known cases; falls back to the raw text (still better
 * than nothing) only for a case not yet mapped here. */
export function describeCampaignSessionError(rawError: string | undefined | null): string {
  const text = rawError || '';
  if (text.includes('CAPTURE_FAILED') || text.includes('CAPTURE_WORKER_FAILED')) {
    return 'La captura de radio fallo por una interrupcion real de la adquisicion (overflow o discontinuidad de muestras) -- el USRP B200 no pudo mantener el ritmo de escritura durante toda la ventana de captura. No es un error de software; es una variacion normal del hardware en este entorno (ocurre en una fraccion significativa de las capturas reales). Puedes simplemente reintentar.';
  }
  if (text.includes('B200_BUSY')) {
    return 'El USRP B200 esta siendo usado por otra operacion en este momento (otra captura o el monitor en vivo). Espera a que termine y reintenta.';
  }
  if (text.includes('HYBRID_SESSION_FAILED')) {
    return 'La sesion de captura (escaneo nativo + B200) no se completo correctamente. Revisa que el dispositivo SDR siga conectado y reintenta.';
  }
  if (text.includes('OFFLINE_REPLAY_DID_NOT_REACH_FULLY_PROCESSED')) {
    return 'El analisis de la captura no termino de procesarse dentro del limite de reintentos automaticos. La captura real fue exitosa, pero el analisis completo requiere mas tiempo del disponible.';
  }
  if (text.includes('OFFLINE_REPLAY_FAILED')) {
    return 'El analisis (decodificacion) de la captura fallo despues de una adquisicion exitosa. Puede requerir revisión tecnica.';
  }
  if (text.includes('REAL_CAMPAIGN_NOT_AVAILABLE')) {
    return 'El modulo de captura real (BLE Lab / B200) no esta activo en el backend en este momento.';
  }
  return text || 'La sesion fallo por una razon no reconocida.';
}

export interface NativeBleDevice extends Record<string, unknown> {
  address: string;
  local_name?: string | null;
  rssi_dbm?: number | null;
  last_seen_utc?: string | null;
}

/** Thin client for the existing native Windows BLE scan (a different
 * module, /api/ble/native/*) -- used only to detect which registered
 * physical units are broadcasting right now, so the operator never has to
 * guess or manually re-type a MAC address for a device already on. */
export class BleNativeScanApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  private get root() { return `${this.baseURL}/api/ble/native`; }

  async start() { return (await axios.post<{ state: string; scan_session_id?: string }>(`${this.root}/scan/start`, {})).data; }
  async stop() { return (await axios.post<{ state: string }>(`${this.root}/scan/stop`)).data; }
  async devices() { return (await axios.get<{ devices: NativeBleDevice[] }>(`${this.root}/devices`)).data.devices; }
}

/** A device counts as "active now" if seen within this many seconds --
 * matches one native-scan detection cycle, not a stale historical entry
 * from a previous, unrelated capture session. */
export const NATIVE_DEVICE_FRESHNESS_SECONDS = 45;

export function isDeviceActiveNow(device: NativeBleDevice): boolean {
  if (!device.last_seen_utc) return false;
  const seenAt = new Date(device.last_seen_utc).getTime();
  if (Number.isNaN(seenAt)) return false;
  return (Date.now() - seenAt) / 1000 < NATIVE_DEVICE_FRESHNESS_SECONDS;
}
