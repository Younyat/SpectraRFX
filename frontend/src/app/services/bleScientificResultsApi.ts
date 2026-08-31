import axios from 'axios';

// Fase 1 (frozen protocol, chained holdout access log, paper runs,
// two-tier scientific preflight) + Fase 2 (canonical records, campaign
// accounting, descriptive quality summaries, figures). RQ1-4/S1-S2/power-
// simulation/LaTeX/export types and methods are added in later phases,
// once the backend endpoints behind them exist -- this file intentionally
// does not declare types for capabilities that are not implemented yet.

export type GitDirtyState = 'CLEAN' | 'DIRTY';

export interface AnalysisContract {
  schema_version: string;
  protocol_id: string;
  protocol_version: number;
  creation_timestamp_utc: string;
  git_commit: string;
  git_dirty_state: GitDirtyState;
  software_environment_digest: string;
  hardware_profile_id: string;
  receiver_profile_hash: string;
  device_population: Record<string, unknown>;
  device_ids: string[];
  firmware_hashes: Record<string, string>;
  channels: number[];
  campaign_schedule: Record<string, unknown>;
  intervention_schedule: Record<string, unknown>;
  content_variants: string[];
  association_policy_hash: string;
  quality_policy_hash: string;
  dataset_policy_hash: string;
  split_manifest_hash: string;
  model_branch_definitions: Record<string, unknown>[];
  feature_policy: Record<string, unknown>;
  signal_region_policy: Record<string, unknown>;
  phase_compensation_policy: Record<string, unknown>;
  hyperparameter_search_space: Record<string, unknown>;
  model_selection_rule: string;
  random_seeds: number[];
  number_of_restarts: number;
  threshold_selection_rule: string;
  abstention_rule: string;
  calibration_rule: string;
  multiplicity_family: Record<string, unknown>;
  statistical_tests: string[];
  effect_thresholds: Record<string, unknown>;
  non_inferiority_margins: Record<string, unknown>;
  minimum_independent_blocks: Record<string, unknown>;
  interpretation_matrix_hash: string;
}

export interface FreezeProtocolRequest {
  protocol_id?: string;
  project_id?: string;
  protocol_name?: string;
  hardware_profile_id: string;
  receiver_profile_hash: string;
  interpretation_matrix_hash: string;
  device_population?: Record<string, unknown>;
  device_ids?: string[];
  channels?: number[];
  split_manifest_hash?: string;
}

export interface HoldoutAccessLogEntry {
  sequence_number: number;
  previous_entry_hash: string | null;
  entry_hash: string;
  analysis_contract_hash: string | null;
  paper_run_id: string | null;
  actor: string;
  process: string;
  access_type: string;
  access_path: string;
  resource_id: string;
  resource_hash: string | null;
  timestamp_utc: string;
  reason: string;
}

export interface HoldoutGroupAssignment {
  assignment_id: string;
  dataset_id: string;
  dataset_version: string;
  group: string;
  physical_unit_ids: string[];
  day_ids: string[];
  session_ids: string[];
  frozen_at: string;
  group_manifest_sha256: string;
}

export type HoldoutChainStatus = 'VALID' | 'BROKEN' | 'EMPTY';
export interface HoldoutChainVerificationResult {
  status: HoldoutChainStatus;
  entry_count: number;
  broken_at_sequence: number | null;
  findings: string[];
}

export interface PaperRunRecord {
  paper_run_id: string;
  campaign_id: string;
  protocol_id: string;
  protocol_version: number;
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
  dataset_fingerprint: string | null;
  split_fingerprint: string | null;
  model_set_fingerprint: string | null;
  analysis_code_commit: string;
  analysis_environment_hash: string;
  storage_path: string;
  created_at: string;
}

export interface CreateRunRequest {
  protocol_id: string;
  protocol_version?: number;
  campaign_id: string;
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
}

export type PreflightCategoryStatus = 'PASSED' | 'BLOCKED';
export interface PreflightCategoryResult {
  status: PreflightCategoryStatus;
  findings: string[];
  [key: string]: unknown;
}

// Two-tier: a dataset can be internally coherent without the whole PAPER
// campaign satisfying everything the frozen protocol declares -- never a
// single generic "passed" step. DATASET_STRUCTURAL_PREFLIGHT_PASSED must
// never be presented as "ready for the paper".
export type PreflightStatus = 'DATASET_STRUCTURAL_PREFLIGHT_PASSED' | 'PAPER_CAMPAIGN_PREFLIGHT_PASSED' | 'PREFLIGHT_BLOCKED';

export interface ScientificPreflightReport {
  paper_run_id: string;
  protocol_id: string;
  protocol_version: number;
  generated_at: string;
  integrity: PreflightCategoryResult;
  leakage: PreflightCategoryResult;
  population_separation: PreflightCategoryResult & { population_counts: Record<string, number> };
  quality: PreflightCategoryResult;
  design_completeness: PreflightCategoryResult;
  paper_campaign_completeness: PreflightCategoryResult & { checked_requirements: string[] };
  overall_status: PreflightStatus;
}

export interface ReadinessResponse {
  paper_run_id: string;
  overall_status: PreflightStatus | null;
  message?: string;
  [key: string]: unknown;
}

export interface ScientificResultsJob {
  job_id: string;
  job_type: string;
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  overall_status?: PreflightStatus;
  error?: string;
  started_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------
// Fase 2: canonical records, campaign accounting, quality, figures
// ---------------------------------------------------------------------

export interface RecordBuildResult {
  paper_run_id: string;
  generated_at: string;
  capture_record_count: number;
  burst_record_count: number;
  decision_window_record_count: number;
  campaign_deviation_count: number;
  captures_without_replay: string[];
}

export interface RecordsStatusResponse {
  paper_run_id: string;
  built: boolean;
  [key: string]: unknown;
}

export type BurstClass = 'RF_ACTIVITY' | 'BLE_SYNC_CANDIDATE' | 'CRC_VALID_PACKET' | 'TARGET_ASSOCIATED_PACKET';

export interface ScientificCaptureRecord extends Record<string, unknown> {
  capture_id: string;
  physical_unit_id: string | null;
  channel: number | null;
  capture_quality: string | null;
  label_status: string | null;
  experimental_role: string | null;
  split: string | null;
  eligible: boolean | null;
  exclusion_reason_codes: string[];
  not_documented_fields: string[];
}

export interface ScientificBurstRecord extends Record<string, unknown> {
  burst_id: string;
  capture_id: string;
  burst_class: BurstClass;
  decision_window_id: string;
  crc_status: string | null;
  association_status: string | null;
  eligible: boolean | null;
  exclusion_reason_codes: string[];
  not_documented_fields: string[];
}

export interface ScientificDecisionWindowRecord extends Record<string, unknown> {
  decision_window_id: string;
  capture_id: string;
  active: boolean;
  eligible_burst_count: number;
  decision_eligible: boolean;
  ineligibility_reason_codes: string[];
}

export interface ScientificCampaignDeviationRecord extends Record<string, unknown> {
  deviation_id: string;
  affected_object_type: string;
  affected_object_id: string;
  deviation_type: string;
  description: string;
  severity: string;
  blocking: boolean;
  action: string;
  scientific_impact: string;
  source_artifact_ids: string[];
}

export interface CampaignAccountingResponse {
  counters: Record<string, number | boolean>;
  balance: Record<string, Record<string, Record<string, number>>>;
  exclusion_reason_row_count: number;
  missingness_row_count: number;
}

export interface QualitySummaryResponse {
  capture_field_summary: Record<string, unknown>[];
  window_field_summary: Record<string, unknown>[];
  unit_day_summary: Record<string, unknown>[];
  association_summary: Record<string, unknown>[];
}

export interface RunArtifactsResponse {
  paper_run_id: string;
  files: string[];
}

// ---------------------------------------------------------------------
// Guided BLE Scientific Validation -- one orchestrator job spanning every
// enrolled device's existing dataset. Mirrors guided_validation/contracts.py
// exactly; the frontend never computes any of these numbers itself.
// ---------------------------------------------------------------------

export type GuidedValidationStageStatus =
  | 'NOT_STARTED' | 'RUNNING' | 'PASSED' | 'PARTIALLY_SUPPORTED' | 'BLOCKED' | 'REQUIRES_PHYSICAL_ACTION' | 'COMPLETED';

export interface GuidedValidationStage {
  stage_id: string;
  label: string;
  status: GuidedValidationStageStatus;
  plain_explanation: string;
  technical_details: Record<string, unknown>;
  evidence_artifacts: string[];
  next_action: string | null;
}

export interface CapabilityFlag {
  capability: string;
  supported: boolean;
  plain_explanation: string;
}

export interface GuidedValidationSummary {
  run_id: string;
  generated_at: string;
  overall_status: string;
  stages: GuidedValidationStage[];
  capability_flags: CapabilityFlag[];
  device_summary: Record<string, {
    capture_count: number;
    calibration_eligible_or_better_captures: number;
    native_event_count: number;
    crc_valid_packet_count: number;
    strong_association_count: number;
    active_windows: number;
    eligible_windows: number;
  }>;
  capture_totals: {
    total_captures: number;
    association_calibration_eligible: number;
    qualification_pilot_eligible: number;
    diagnostic_only: number;
  };
  association_summary: {
    total_calibration_events: number;
    by_status: Record<string, number>;
    by_status_percent: Record<string, number>;
    matched_target_count: number;
  };
  target_absence_summary: {
    candidates_checked: number;
    valid_reinforced_controls: Record<string, unknown>[];
    has_valid_control: boolean;
    invalid_reasons_by_capture: Record<string, string>;
  };
  association_policy_summary: Record<string, unknown> | null;
  simplified_conclusion: string;
  next_required_action: string;
  artifact_index: Record<string, unknown>;
}

export interface GuidedValidationJob {
  job_id: string;
  job_type: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: GuidedValidationSummary;
  started_at: string;
  updated_at: string;
}

export interface TimingDiagnosticResult {
  action_id: string;
  physical_unit_id: string;
  capture_id: string;
  session_id: string;
  native_scanner_running_time_s: number;
  native_event_count: number;
  target_native_event_count: number;
  sdr_candidate_count: number;
  crc_valid_packet_count: number;
  target_address_packet_count: number;
  candidate_pair_count: number;
  narrow_window_valid_count: number;
  narrow_window_ambiguous_count: number;
  best_residual_ms_median: number | null;
  best_residual_ms_p95: number | null;
  diagnosis_code: string;
  diagnosis_explanation: string;
  diagnosis_next_action: string;
}

export interface TargetAbsenceControlResult {
  action_id: string;
  status: string;
  capture_id: string;
  session_id: string;
  native_event_count: number;
  devices_detected: string[];
  false_strong_associations_by_threshold_ms: Record<string, number>;
  false_strong_associations_total: number;
}

export interface GuidedValidationActionJob {
  job_id: string;
  job_type: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: TimingDiagnosticResult | TargetAbsenceControlResult;
  started_at: string;
  updated_at: string;
}

export interface CapturableDevice {
  physical_unit_id: string;
  has_bound_address: boolean;
  has_dataset: boolean;
  existing_capture_count: number;
}

export interface NewCaptureSessionResponse {
  run_id: string;
}

export interface CleanupRunEntry {
  run_id: string;
  kind: 'FULL_RUN' | 'CAPTURE_ONLY' | 'UNKNOWN';
  generated_at: string | null;
  overall_status: string | null;
  paper_run_count: number;
  size_bytes: number;
}

export interface DeleteCleanupRunResponse {
  deleted: boolean;
  run_id: string;
  deleted_paper_runs: string[];
}

export interface StartTimingDiagnosticRequest {
  physical_unit_id: string;
  capture_duration_s: number;
  channel: number;
  receiver_profile?: string;
  operator_id?: string;
}

export interface StartTargetAbsenceControlRequest {
  confirmed_devices_off: Record<string, boolean>;
  capture_duration_s: number;
  channel: number;
  operator_id?: string;
}

// Paper progress dashboard (2026-08-10) -- pure reporting types. Every
// shape below mirrors a real backend dict exactly (get_study_status,
// get_paper_readiness, paper_export.py's manifest); `NoDataResponse` is
// what every "no real artifact yet" endpoint returns instead of an empty
// object or a zeroed one.

export interface NoDataResponse {
  status: 'NO_DATA';
}

export interface StudyStatusResponse {
  git_sha: string;
  git_dirty_state: GitDirtyState;
  protocol_id: string | null;
  all_protocol_ids: string[];
  protocol_version: number | null;
  contract_status: 'NO_DATA' | 'INCOMPLETE' | 'COMPLETE' | 'FROZEN';
  contract_sha256: string | null;
  missing_confirmatory_readiness_fields: string[];
  association_policy_status: 'NONE' | 'FROZEN';
  protected_future_test_status: 'UNTOUCHED' | 'OPENED';
  protocol_freeze_status: 'NOT_STARTED' | 'COMPLETE';
  real_capture_count: number;
  current_phase: string;
  generated_at: string;
}

export interface PaperReadinessRow {
  manuscript_element: string;
  scientific_mechanism: string;
  evidence_maturity: 'QUALIFICATION' | 'DEVELOPMENT' | 'VALIDATION' | 'CONFIRMATORY' | 'ENGINEERING' | null;
  canonical_artifact: string;
  available: boolean;
  confirmatory: boolean;
  statistics_ready: boolean;
  table_ready: boolean;
  figure_ready: boolean;
  paper_evidence_status: 'DATA_PENDING' | 'PRELIMINARY' | 'COMPLETE';
}

export interface ProtocolFreezeStatusResponse {
  status: 'NOT_STARTED' | 'COMPLETE';
  entries: { protocol_id: string; protocol_version: number; contract_sha256: string; frozen_at: string; new_version_reason: string | null; is_new_version_of: number | null }[];
}

export interface AssociationPolicyStatusResponse {
  status: 'NONE' | 'FROZEN';
  policy?: Record<string, unknown>;
}

export interface PaperExportManifestEntry {
  file: string;
  status: 'GENERATED' | 'SKIPPED_NO_DATA';
  detail?: string;
  would_be_derived_from?: string;
}

export interface PaperExportManifest {
  schema_version: string;
  generated_at: string;
  generated_count: number;
  skipped_count: number;
  entries: PaperExportManifestEntry[];
}

// Source-association calibration summary (2026-08-17) -- the real
// per-threshold sweep from the most recent real calibration attempt of ANY
// outcome, structured (never only inside a stringified `detail`). Status
// stays real even when nothing was ever frozen -- this IS the honest
// current state, shown on Results Dashboard regardless.
export interface AssociationCalibrationSummary {
  status: 'FROZEN' | 'FROZEN_STRATIFIED' | 'NO_THRESHOLD_SATISFIES_CRITERIA';
  policy_scope: string | null;
  evaluated_at?: string;
  detail?: string;
  policy?: Record<string, unknown>;
  policies_by_family?: Record<string, unknown>;
  threshold_grid?: number[];
  minimum_coverage?: number;
  acceptance_criterion?: string;
  coverage_by_threshold_ms?: Record<string, number>;
  false_strong_by_threshold_ms?: Record<string, number>;
  ambiguous_by_threshold_ms?: Record<string, number>;
  n_calibration_events?: number;
  n_target_absence_events?: number;
}

// Provenance reconstruction + S1/S2 engineering reports (2026-08-11) --
// read-only, mirroring provenance.py / engineering_reports.py exactly.

export interface InferenceRunSummary {
  inference_run_id: string;
  bundle_id: string;
  prediction_count: number;
  created_at: string;
  example_ids: string[];
}

export type ProvenanceStatus = 'COMPLETE' | 'INCOMPLETE' | 'FAIL';

export interface DecisionProvenance {
  inference_run_id: string;
  example_id: string;
  provenance_status: ProvenanceStatus;
  missing_link: string[];
  hash_mismatch: string[];
  bundle_id?: string;
  bundle_sha256?: string;
  representation_profile_id?: string;
  base_preprocessing_profile_id?: string;
  decision?: { predicted_class: string | null; final_decision: string | null; class_probability: number | null };
  capture_id?: string;
  sample_start?: number;
  sample_end?: number;
  candidate_id?: string;
  packet_id?: string;
  example_source_iq_sha256?: string;
  capture_iq_sha256?: string;
  recovered_pdu_evidence?: { pdu_type: string | null; packet_sha256: string | null; advertiser_address_canonical: string | null; association_strength: string | null };
  dataset_id?: string;
  dataset_version?: string;
  dataset_manifest_sha256?: string;
  scientific_task?: string;
  split_manifest_sha256?: string;
  [key: string]: unknown;
}

export interface ChannelTransportChannelResult {
  channel: number;
  center_frequency_hz: number | null;
  frozen_bundle_id: string;
  windows: number;
  balanced_accuracy: number | null;
  macro_f1: number | null;
  coverage: number | null;
  confusion_matrix: Record<string, Record<string, number>> | null;
  per_unit_recall: Record<string, number> | null;
}

// Coverage canonical producer (2026-08-12, Scientific Closure pass) --
// mirrors coverage_analysis.py exactly.

export interface CoverageBucket {
  eligible_windows: number;
  decided_windows: number;
  abstained_windows: number;
  coverage: number;
  errors_among_decided: number | null;
  risk_among_decided: number | null;
}

// Closed-set decision-window BA/confusion/risk-coverage (2026-08-17) --
// real Evaluator.evaluate_split() output fed real 10-second decision-window
// predictions, kept separate per branch (never pooled across branches like
// by_evaluation_domain is). evidence_maturity is always CURRENT_TEST here --
// this block only ever covers TRAIN/VALIDATION/TEST, never protected FUTURE.
// n_decided/n_abstained (2026-08-17): exact integer counts derived from the
// same coverage ratio (coverage = n_decided/n_comparable) -- `risk` here IS
// the selective_error (El-Yaniv & Wiener, 2010), same field, not renamed.
export interface WindowLevelRiskCoveragePoint {
  coverage: number;
  risk: number;
  threshold: number;
  n_decided: number;
  n_abstained: number;
}

export interface WindowLevelDomainEvaluation {
  evidence_maturity: 'CURRENT_TEST';
  balanced_accuracy: number | null;
  macro_f1: number | null;
  confusion_matrix: Record<string, Record<string, number>>;
  n_comparable: number;
  distinct_physical_units: string[];
  risk_coverage: WindowLevelRiskCoveragePoint[] | null;
  // PAPER_READY gate (2026-08-17): false whenever n_comparable<10 or the
  // domain's real decision windows all belong to a single physical unit --
  // the curve above is kept as real, functional evidence regardless, just
  // never presented as citable without this being true.
  paper_ready: boolean;
  paper_ready_reason: string | null;
}

// Real per-window record (2026-08-17) -- one row per real 10-second decision
// window (decided AND abstained), read verbatim from run_decision_windows().
export interface DecisionWindowRecord {
  branch: string;
  evaluation_domain: string | null;
  decision_window_id: string | null;
  capture_id: string | null;
  window_duration_s: number | null;
  burst_count: number | null;
  true_physical_unit_id: string | null;
  predicted_class: string | null;
  class_probability: number | null;
  final_decision: string | null;
  abstention_reason: string | null;
}

export interface WindowLevelBranchEvaluation {
  by_evaluation_domain: Record<string, WindowLevelDomainEvaluation>;
  decision_windows: DecisionWindowRecord[];
  // Two DIFFERENT real thresholds, unambiguously named (2026-08-17):
  // classifier_acceptance_threshold is this bundle's own real,
  // VALIDATION-only UNKNOWN-rejection threshold (Evaluator.
  // calibrate_unknown_threshold). association_time_threshold_ms is the
  // SEPARATE native<->SDR AssociationPolicy.threshold_ms -- real null while
  // association calibration stays fail-closed (never loosened to force a
  // value).
  classifier_acceptance_threshold: number | null;
  classifier_acceptance_threshold_calibrated_on: string | null;
  association_time_threshold_ms: number | null;
}

// Domain-resolution diagnostic (2026-08-17 investigation): why a real
// decision window's evaluation_domain came back unresolved.
export interface DomainResolutionDiagnostic {
  total_windows: number;
  assigned_train: number;
  assigned_validation: number;
  assigned_test: number;
  unresolved: number;
  unresolved_by_reason: Record<string, number>;
}

export interface CoverageAnalysisReport {
  schema_version: string;
  generated_at: string;
  paper_run_id: string;
  bundle_ids: Record<string, string>;
  window_duration_s: number;
  minimum_eligible_bursts: number;
  overall: CoverageBucket | null;
  by_evaluation_domain: Record<string, CoverageBucket>;
  by_branch: Record<string, CoverageBucket>;
  by_physical_unit: Record<string, CoverageBucket>;
  abstention_reason_counts: Record<string, number> | 'NOT_AVAILABLE';
  window_level_evaluation?: Record<string, WindowLevelBranchEvaluation>;
  domain_resolution_diagnostic?: DomainResolutionDiagnostic;
}

export interface StartCoverageAnalysisRequest {
  paper_run_id: string;
  evaluate_window_level?: boolean;
  bundle_ids?: Record<string, string>;
}

export interface CoverageAnalysisJob {
  job_id: string;
  job_type: 'COVERAGE_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: CoverageAnalysisReport;
  started_at: string;
  updated_at: string;
}

// Sensitivity canonical producer (2026-08-12, Scientific Closure pass) --
// mirrors sensitivity_analysis.py / run_sensitivity_analysis exactly.

export interface LodoRow {
  omitted_physical_unit: string;
  estimate: number | null;
  accuracy: number | null;
  n_comparable: number;
  coverage: number | null;
  delta_vs_full_set: number | null;
}

export interface OffsetRetainingResult {
  analysis_role: 'OFFSET_RETAINING_SENSITIVITY';
  training_run_id: string;
  base_run_training_run_id: string;
  base_preprocessing_profile_id: string;
  estimate: number | null;
  coverage: number | null;
  delta_vs_primary: number | null;
}

export interface SensitivityReport {
  schema_version: string;
  generated_at: string;
  paper_run_id: string;
  primary: { analysis_role: 'PRIMARY'; branch: string | null; training_run_id: string; balanced_accuracy: number | null };
  leave_one_device_out: { analysis_role: 'SENSITIVITY'; full_set_balanced_accuracy: number | null; rows: LodoRow[] };
  offset_retaining: OffsetRetainingResult;
  seed_variability: { analysis_role: 'SENSITIVITY'; rows: SeedVariabilityPoint[] } | null;
}

export interface SensitivityAnalysisJob {
  job_id: string;
  job_type: 'SENSITIVITY_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: SensitivityReport;
  started_at: string;
  updated_at: string;
}

export interface ChannelTransportReport {
  schema_version: string;
  per_channel: ChannelTransportChannelResult[];
  interpretation_note: string;
}

export type OfflineNearlivePairingStatus = 'NO_DATA' | 'COMPUTED_FROM_EXACT_EVIDENCE_INTERVAL_MATCH';

export interface OfflineNearliveReport {
  schema_version: string;
  pairing_status: OfflineNearlivePairingStatus;
  pairing_note: string;
  matched_pair_count: number;
  unpaired_offline_count: number;
  unpaired_nearlive_count: number;
  analytical_agreement: Record<string, number | null> | null;
  computational_behavior: Record<string, number | string> | null;
}

// RQ2 canonical representation comparison (2026-08-11) -- real per-branch
// persistence, mirroring persist_rq1_acquisition_dependence_report exactly.

export type Rq2AnalysisRole = 'PRIMARY' | 'SENSITIVITY' | 'UNSELECTED';

export interface Rq2BranchResult {
  branch: string;
  analysis_role: Rq2AnalysisRole;
  evaluation_domain: string;
  balanced_accuracy?: number | null;
  balanced_accuracy_ci?: { ci_low: number; ci_high: number } | null;
  macro_f1?: number | null;
  coverage?: number | null;
  classwise_recall?: Record<string, number> | null;
  serialized_model_size_bytes?: number | null;
  inference_latency_ms?: number | null;
  seed_variability?: SeedVariabilityPoint[];
  model_bundle_id?: string | null;
  model_bundle_sha256?: string | null;
}

// Study Control Center, Phase 1 (2026-08-11) -- the 17-phase workflow
// aggregator and the RUN REAL HARDWARE QUALIFICATION job. Both compute no
// new science: the status endpoint only reads already-real getters, and
// the job only drives real hardware/decode/preprocessing functions into
// the untouched run_campaign_qualification_preflight() classifier.

export type StudyControlCenterPhaseState = 'NOT_STARTED' | 'READY' | 'IN_PROGRESS' | 'PRELIMINARY' | 'BLOCKED' | 'COMPLETE' | 'INVALIDATED' | 'NOT_APPLICABLE';

// Normalized 2026-08-11: three independent states, never conflated into
// one blended READY. mechanism/launcher are static facts about what code
// exists; execution is the only one computed from real runtime artifacts.
export type StudyControlCenterMechanismState = 'READY' | 'PARTIAL' | 'NOT_STARTED';
export type StudyControlCenterLauncherState = 'READY' | 'PARTIAL' | 'NOT_STARTED';
export type StudyControlCenterExecutionState = 'NOT_RUN' | 'IN_PROGRESS' | 'COMPLETE' | 'BLOCKED' | 'PRELIMINARY';

export interface StudyControlCenterPhase {
  phase_id: string;
  label: string;
  state: StudyControlCenterPhaseState;
  mechanism_state: StudyControlCenterMechanismState;
  launcher_state: StudyControlCenterLauncherState;
  execution_state: StudyControlCenterExecutionState;
  prerequisites: string[];
  blocking_reasons: string[];
  real_data_available: boolean;
  run_id: string | null;
  git_sha: string;
  protocol_version: number | null;
  artifacts: string[];
  paper_section: string;
  next_allowed_operation: string | null;
}

export interface StudyControlCenterStatus {
  schema_version: string;
  generated_at: string;
  phases: StudyControlCenterPhase[];
  phases_with_mechanism_and_launcher_ready: number;
  phases_total: number;
}

export interface HardwareQualificationJob {
  job_id: string;
  job_type: 'HARDWARE_QUALIFICATION';
  physical_unit_id: string;
  channel: number;
  duration_seconds: number;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: {
    capture_id: string | null;
    session_id: string | null;
    acquisition_error?: string;
    preflight_report: Record<string, unknown>;
  };
  started_at: string;
  updated_at: string;
}

export interface StartHardwareQualificationRequest {
  physical_unit_id: string;
  channel?: number;
  duration_seconds?: number;
}

// Study Control Center, phase 08 (2026-08-11) -- RUN RQ2 VALIDATION
// BENCHMARK. Drives the same real train_selected_models() orchestration;
// computes no new science, only maps its real result onto the 4 RQ2
// branches.

export interface Rq2BenchmarkJob {
  job_id: string;
  job_type: 'RQ2_BENCHMARK';
  paper_run_id: string;
  dataset_id: string;
  dataset_version: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: {
    stopped_at: string | null;
    stopped_reason: string | null;
    rq2_report: Rq2RepresentationComparisonReport | null;
    skipped_models?: { model_type: string; reason: string }[];
  };
  started_at: string;
  updated_at: string;
}

// Study Control Center, phase 05 (2026-08-11) -- Study Sizing. Wraps the
// real, previously-unwired statistics/power_simulation.py; the decision
// endpoint never auto-selects a design.

export interface HierarchicalDesignInput {
  n_units: number;
  n_days: number;
  n_captures_per_unit_day: number;
  icc_unit: number;
  icc_day: number;
}

export type StudySizingVerdict = 'INSUFFICIENT' | 'SUFFICIENT' | 'OVERPROVISIONED';

export interface StudySizingDesignEvaluation {
  design: HierarchicalDesignInput & { total_captures: number; design_effect: number; effective_captures: number };
  power: number;
  verdict: StudySizingVerdict;
}

export interface StudySizingEvaluationResult {
  p1: number;
  p2: number;
  alpha: number;
  target_power: number;
  evaluations: StudySizingDesignEvaluation[];
  minimum_sufficient_design: StudySizingDesignEvaluation | null;
}

export interface StudySizingDecision extends StudySizingDesignEvaluation {
  schema_version: string;
  p1: number;
  p2: number;
  alpha: number;
  target_power: number;
  rationale: string;
  decided_by: string | null;
  decided_at: string;
}

// Study Control Center, phase 09 (2026-08-11) -- Analysis Contract
// Readiness. Never a generic JSON editor: every field declares whether it
// is DERIVED (a real, already-frozen artifact/constant) or a genuine
// SCIENTIST_DECISION, and status is restricted to
// COMPLETE/INCOMPLETE/SCIENTIST_DECISION_REQUIRED.

export type AnalysisContractFieldKind = 'DERIVED' | 'SCIENTIST_DECISION';
export type AnalysisContractFieldStatus = 'COMPLETE' | 'INCOMPLETE' | 'SCIENTIST_DECISION_REQUIRED';

export interface AnalysisContractFieldReadiness {
  field_id: string;
  label: string;
  kind: AnalysisContractFieldKind;
  value: unknown;
  source: string | null;
  evidence_maturity: string | null;
  status: AnalysisContractFieldStatus;
  rationale: string | null;
}

export interface AnalysisContractReadinessGate {
  gate_id: string;
  label: string;
  status: 'COMPLETE' | 'INCOMPLETE';
}

export interface ProtocolFreezeReadiness {
  status: 'READY' | 'BLOCKED';
  missing: string[];
}

export interface AnalysisContractReadiness {
  schema_version: string;
  generated_at: string;
  fields: AnalysisContractFieldReadiness[];
  readiness_gates: AnalysisContractReadinessGate[];
  protocol_freeze_readiness: ProtocolFreezeReadiness;
}

export interface ScientistDecisionRecord {
  schema_version: string;
  field_id: string;
  selected_value: unknown;
  rationale: string;
  evidence_used: string;
  decided_by: string | null;
  protocol_version_candidate: number | null;
  decided_at: string;
}

export interface RecordScientistDecisionRequest {
  field_id: string;
  selected_value: unknown;
  rationale: string;
  evidence_used?: string;
  decided_by?: string;
  protocol_version_candidate?: number;
}

export interface StartRq2BenchmarkRequest {
  paper_run_id: string;
  dataset_id: string;
  dataset_version: string;
  scientific_task?: string;
  model_types?: string[];
}

// Scientific Dashboard closure, Level A/B (2026-08-11) -- real cross-
// references over already-real getters/canonical tables. Mirrors
// get_experiment_health_summary()/get_evidence_quality_summary() exactly.

export interface ExperimentHealthBlockCounts {
  scheduled_blocks: number;
  completed_blocks: number;
  rejected_attempt_count: number;
}

export interface ExperimentHealthCampaign {
  schedule_id: string;
  schedule_version: number;
  protocol_id: string;
  evidence_maturity: 'QUALIFICATION' | 'DEVELOPMENT';
  scheduled_blocks: number;
  completed_blocks: number;
  incomplete_blocks: number;
  rejected_attempt_count: number;
  physical_units: string[];
  blocks_by_physical_unit: Record<string, ExperimentHealthBlockCounts>;
  receiver_session_id: string | null;
  frozen_at: string | null;
  paper_run_ids: string[];
}

export interface ExperimentHealthSummary {
  schema_version: string;
  generated_at: string;
  git_sha: string;
  association_policy_status: 'NONE' | 'FROZEN';
  protocol_freeze_status: 'NOT_STARTED' | 'COMPLETE';
  protected_future_test_status: 'UNTOUCHED' | 'OPENED';
  campaigns: ExperimentHealthCampaign[];
  deviation_type_distribution: Record<string, number>;
}

export interface EvidenceQualitySummary {
  schema_version: string;
  generated_at: string;
  paper_run_id: string;
  capture_count: number;
  burst_count: number;
  window_count: number;
  captures_per_physical_unit: Record<string, number>;
  captures_per_day: Record<string, number>;
  captures_per_experimental_role: Record<string, number>;
  candidate_bursts_per_capture: Record<string, number>;
  crc_valid_per_capture: Record<string, number>;
  admitted_per_capture: Record<string, number>;
  exclusion_reason_counts: Record<string, number>;
  eligible_bursts_per_window: Record<string, number>;
  usable_windows: number;
  insufficient_evidence_abstention_windows: number;
  captures_with_discontinuities: number;
  deviation_count: number;
  physical_unit_by_capture_id: Record<string, string>;
}

export interface BootstrapCiResult {
  point_estimate: number;
  ci_low: number;
  ci_high: number;
  n_resamples: number;
  confidence_level: number;
}

export interface Rq3Pair {
  physical_unit_id: string;
  day_id: string;
  intervention_arm: string;
  pre_capture_id: string;
  post_capture_id: string;
  pre_receiver_epoch: string | null;
  post_receiver_epoch: string | null;
  pre_receiver_session_id: string | null;
  post_receiver_session_id: string | null;
  valid: boolean;
  invalidation_reason: string | null;
  // Real FRR pre/post/D (2026-08-11) -- from OfflineInferenceService's
  // frozen decision-window pipeline, never a fabricated per-capture score.
  n_pre_windows: number | null;
  n_post_windows: number | null;
  pre_frr: number | null;
  post_frr: number | null;
  d: number | null;
}

export interface Rq3PerUnitMeanD {
  reset: Record<string, number>;
  control: Record<string, number>;
}

export interface StartRq3FrrAnalysisRequest {
  paper_run_id: string;
  bundle_id?: string;
}

export interface Rq3FrrAnalysisJob {
  job_id: string;
  job_type: 'RQ3_FRR_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: Record<string, unknown>;
  started_at: string;
  updated_at: string;
}

export interface StartRq4RegionAnalysisRequest {
  paper_run_id: string;
  full_burst_bundle_id?: string;
}

export interface Rq4RegionAnalysisJob {
  job_id: string;
  job_type: 'RQ4_REGION_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: Record<string, unknown>;
  started_at: string;
  updated_at: string;
}

export interface ConfirmatoryFutureAnalysisJob {
  job_id: string;
  job_type: 'CONFIRMATORY_FUTURE_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: Record<string, unknown>;
  started_at: string;
  updated_at: string;
}

export interface ChannelTransportAnalysisJob {
  job_id: string;
  job_type: 'CHANNEL_TRANSPORT_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: Record<string, unknown>;
  started_at: string;
  updated_at: string;
}

export interface OfflineNearliveAnalysisJob {
  job_id: string;
  job_type: 'OFFLINE_NEARLIVE_ANALYSIS';
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: Record<string, unknown>;
  started_at: string;
  updated_at: string;
}

export interface Rq4RegionResult {
  analytical_region: string;
  eligible_windows: number;
  decided_windows: number | null;
  abstained_windows: number | null;
  coverage: number | null;
  recall: number | null;
}

export interface Rq4MatchedRegionBlock {
  matched_region_block_id: string;
  physical_unit_id: string | null;
  day_id: string | null;
  packet_condition: string | null;
  capture_ids: string[];
  regions: Record<string, Rq4RegionResult | null>;
}

export interface Rq4RegionReport {
  schema_version: string;
  matched_region_blocks: Rq4MatchedRegionBlock[];
  bundle_ids: Record<string, string | null>;
  primary_contrast: { a_region: string; b_region: string; n_matched_blocks: number };
  primary_contrast_scores_a: number[];
  primary_contrast_scores_b: number[];
  secondary_contrast: { a_region: string; b_region: string; n_matched_blocks: number };
  secondary_contrast_scores_a: number[];
  secondary_contrast_scores_b: number[];
}

export interface SeedVariabilityPoint {
  seed: number;
  training_run_id: string;
  validation_accuracy: number | null;
  validation_balanced_accuracy: number | null;
}

export interface Rq2RepresentationComparisonReport extends Record<string, unknown> {
  schema_version: string;
  protocol_id: string;
  protocol_version: number;
  contract_sha256: string;
  git_sha: string;
  dataset_id: string;
  dataset_version: string;
  split_manifest_id: string;
  split_manifest_sha256: string;
  branches: Rq2BranchResult[];
  // PRIMARY is selected on this domain ONLY -- FUTURE (when it exists) is
  // evaluation, never a re-selection input. Real, persisted, never a
  // frontend-inferred label.
  selection_rule?: string | null;
  selection_domain?: string | null;
  generated_at: string;
}

// Real, in-platform paper-support dashboard (2026-08-16) -- every field here
// is a pass-through of an already-persisted artifact (get_evidence_dashboard_
// summary() computes no new science); see backend/.../get_evidence_dashboard_
// summary docstring for the exact provenance of each section.
export interface Rq1AcquisitionDependenceReport extends Record<string, unknown> {
  schema_version: string;
  protocol_id?: string | null;
  protocol_version?: number | null;
  contract_sha256?: string | null;
  git_sha?: string | null;
  model_bundle_id?: string | null;
  ba_window: number | null;
  ba_window_n_comparable?: number | null;
  ba_capture: number | null;
  ba_capture_n_comparable?: number | null;
  ba_future: number | null;
  ba_future_status: string;
  delta_dependence: number | null;
  confusion_matrix_capture: Record<string, Record<string, number>> | null;
  // RQ1 uncertainty completion (2026-08-17): ba_window now also gets its own
  // real CI (a deliberately leakage-optimistic diagnostic still has real,
  // reportable resampling uncertainty). delta_dependence_ci comes from a
  // JOINT/paired resample over both populations, never from subtracting the
  // two marginal CIs' bounds.
  uncertainty_ci?: {
    ba_capture_ci?: BootstrapCiResult | null;
    ba_window_ci?: BootstrapCiResult | null;
    delta_dependence_ci?: (BootstrapCiResult & { method: string }) | null;
  } | null;
  // Investigation finding (2026-08-17): RQ1's real evaluation unit is the
  // ExampleRecord (per-burst classification) -- "window" in BA_window is
  // RQ1's own pre-existing acquisition-provenance term, unrelated to the
  // 10-second decision-window aggregation coverage_analysis.py uses.
  evaluation_unit?: string;
  decision_window_cross_reference?: {
    source_artifact: string;
    window_duration_s: number | null;
    note: string;
    by_evaluation_domain: Record<string, { n_decision_windows: number | null }>;
  } | null;
  generated_at: string;
}

export interface EvidenceDashboardTestEvaluation {
  accuracy?: number | null;
  balanced_accuracy?: number | null;
  macro_f1?: number | null;
  recall_per_class?: Record<string, number> | null;
  precision_per_class?: Record<string, number> | null;
  f1_per_class?: Record<string, number> | null;
  confusion_matrix?: Record<string, Record<string, number>> | null;
  n_examples?: number | null;
  n_comparable_to_known_classes?: number | null;
  evaluation_validity?: string | null;
  // El-Yaniv & Wiener (2010) selective-prediction curve -- same shape
  // Evaluator._risk_coverage() already produces server-side, one point per
  // achievable confidence threshold on this same TEST split.
  risk_coverage?: { coverage: number; risk: number; threshold: number }[] | null;
}

export interface EvidenceDashboardClosedSet {
  paper_run_id: string;
  dataset_id: string;
  dataset_version: string;
  rq1: Rq1AcquisitionDependenceReport | null;
  rq2: Rq2RepresentationComparisonReport | null;
  primary_branch: string | null;
  primary_training_run_id: string | null;
  primary_test: EvidenceDashboardTestEvaluation | null;
}

export interface EvidenceDashboardPerUnitRun {
  paper_run_id: string;
  dataset_id: string;
  dataset_version: string;
  rq1: Rq1AcquisitionDependenceReport | null;
  rq2: Rq2RepresentationComparisonReport | null;
}

export interface EvidenceDashboardScientistDecision {
  field_id: string;
  selected_value: Record<string, unknown>;
  rationale: string;
  evidence_used: string;
  decided_by: string | null;
  decided_at: string;
}

export interface EvidenceDashboardRq3Progress {
  total_captures: number;
  captures_with_rq3_metadata: number;
  declared_by_unit: Record<string, { RESET: number; CONTROL: number }>;
}

export interface EvidenceDashboardRq4Unit {
  physical_unit_id: string;
  rq4_eligibility: 'ELIGIBLE' | 'NOT_ELIGIBLE';
  rq4_eligibility_reason: string | null;
}

export interface EvidenceDashboardSummary {
  schema_version: string;
  generated_at: string;
  git_sha: string | null;
  protocol_id: string | null;
  protocol_version: number | null;
  contract_sha256: string | null;
  closed_set: EvidenceDashboardClosedSet | null;
  per_unit_auxiliary: EvidenceDashboardPerUnitRun[];
  rq3: { sample_size_decision: EvidenceDashboardScientistDecision | null; campaign_progress: EvidenceDashboardRq3Progress };
  rq4: { physical_units: EvidenceDashboardRq4Unit[]; status: 'DATA_NOT_AVAILABLE' | 'ELIGIBLE_UNITS_PRESENT' };
}

export interface EvidenceFigureRegenerationResult {
  started_at: string;
  finished_at: string;
  png_files: string[];
  notebook_written: boolean;
  note: string;
}

// Paper-representation pass (2026-08-17) -- new supporting tables + the
// scientific completeness report. Every field here mirrors the real backend
// dict exactly (build_tx_composition_table / build_partition_composition_table /
// build_receiver_epoch_table / get_scientific_completeness_report); no field
// is computed client-side.

export interface TxCompositionRow {
  physical_unit_id: string;
  device_family: string | null;
  manufacturer: string | null;
  model: string | null;
  project_id: string | null;
  status: string | null;
  rq4_eligibility: string | null;
  real_capture_count: number;
  channels: number[];
  day_range: { first: string; last: string } | null;
}

// n_examples (renamed 2026-08-17, was n_windows): real ExampleRecord
// (burst/packet-level) count from SplitManifest.assignments -- NOT a
// 10-second decision-window count. See CoverageAnalysisReport.
// domain_resolution_diagnostic for the real decision-window count.
export interface PartitionDomainCounts {
  n_examples: number;
  n_captures: number;
  n_sessions: number;
}

export interface PartitionCompositionTable {
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
  split_status: string;
  leakage_check_status: string;
  domains: { TRAIN: PartitionDomainCounts; VALIDATION: PartitionDomainCounts; TEST: PartitionDomainCounts };
}

export interface ReceiverEpochRow {
  receiver_epoch: string;
  boundary_reason: string | null;
  n_captures: number;
  day_ids: string[];
  channels: number[];
  physical_units: string[];
}

export type ScientificCompletenessStatus = 'AVAILABLE' | 'PENDING_REAL_ACQUISITION' | 'BLOCKED' | 'NOT_ELIGIBLE' | 'PROTECTED';

export interface ScientificCompletenessItem {
  item: string;
  status: ScientificCompletenessStatus;
  reason: string;
  missing_evidence: string[];
}

export interface ScientificCompletenessReport {
  schema_version: string;
  generated_at: string;
  git_sha: string | null;
  items: ScientificCompletenessItem[];
}

export class BleScientificResultsApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  private get root() { return `${this.baseURL}/api/ble-scientific-results`; }

  async freezeProtocol(body: FreezeProtocolRequest) { return (await axios.post<AnalysisContract>(`${this.root}/protocols`, body)).data; }
  async getProtocol(protocolId: string, version?: number) {
    return (await axios.get<AnalysisContract>(`${this.root}/protocols/${encodeURIComponent(protocolId)}`, { params: version ? { version } : {} })).data;
  }
  async listProtocolVersions(protocolId: string) {
    return (await axios.get<AnalysisContract[]>(`${this.root}/protocols/${encodeURIComponent(protocolId)}/versions`)).data;
  }

  async holdoutAccessLog() { return (await axios.get<HoldoutAccessLogEntry[]>(`${this.root}/holdout-access-log`)).data; }
  async verifyHoldoutAccessChain() { return (await axios.get<HoldoutChainVerificationResult>(`${this.root}/holdout-access-log/verify`)).data; }

  // Holdout groups (2026-08-12, fast-closure pass, Phase 12): the ONLY
  // FUTURE-specific step -- declares which real physical_unit_ids/day_ids/
  // session_ids belong to group=FUTURE_TEST. Metadata-only, never acquires
  // data (real acquisition reuses the same generic campaign mechanism
  // every other phase already uses).
  async freezeHoldoutGroups(body: { dataset_id: string; dataset_version: string; group: string; physical_unit_ids?: string[]; day_ids?: string[]; session_ids?: string[] }) {
    return (await axios.post<HoldoutGroupAssignment>(`${this.root}/holdout-groups`, body)).data;
  }
  async listHoldoutGroups(datasetId: string, datasetVersion: string) {
    return (await axios.get<HoldoutGroupAssignment[]>(`${this.root}/holdout-groups/${encodeURIComponent(datasetId)}/${encodeURIComponent(datasetVersion)}`)).data;
  }

  async createRun(body: CreateRunRequest) { return (await axios.post<PaperRunRecord>(`${this.root}/runs`, body)).data; }
  async listRuns() { return (await axios.get<PaperRunRecord[]>(`${this.root}/runs`)).data; }
  async getRun(paperRunId: string) { return (await axios.get<PaperRunRecord>(`${this.root}/runs/${encodeURIComponent(paperRunId)}`)).data; }

  async startPreflight(paperRunId: string) { return (await axios.post<ScientificResultsJob>(`${this.root}/preflight`, { paper_run_id: paperRunId })).data; }
  async getJob(jobId: string) { return (await axios.get<ScientificResultsJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data; }
  async cancelJob(jobId: string) { return (await axios.post<ScientificResultsJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}/cancel`)).data; }
  async readiness(paperRunId: string) { return (await axios.get<ReadinessResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/readiness`)).data; }

  async startBuildRecords(paperRunId: string) { return (await axios.post<ScientificResultsJob>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/build-records`)).data; }
  async recordsStatus(paperRunId: string) { return (await axios.get<RecordsStatusResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/records/status`)).data; }
  async campaignAccounting(paperRunId: string) { return (await axios.get<CampaignAccountingResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/campaign-accounting`)).data; }
  async deviations(paperRunId: string, limit = 200, offset = 0) {
    return (await axios.get<ScientificCampaignDeviationRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/deviations`, { params: { limit, offset } })).data;
  }
  async qualitySummary(paperRunId: string) { return (await axios.get<QualitySummaryResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/quality-summary`)).data; }
  async captures(paperRunId: string, limit = 100, offset = 0) {
    return (await axios.get<ScientificCaptureRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/captures`, { params: { limit, offset } })).data;
  }
  async captureDetail(paperRunId: string, captureId: string) {
    return (await axios.get<ScientificCaptureRecord>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/captures/${encodeURIComponent(captureId)}`)).data;
  }
  async bursts(paperRunId: string, limit = 100, offset = 0, captureId?: string) {
    return (await axios.get<ScientificBurstRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/bursts`, { params: { limit, offset, capture_id: captureId } })).data;
  }
  async windows(paperRunId: string, limit = 100, offset = 0, captureId?: string) {
    return (await axios.get<ScientificDecisionWindowRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/windows`, { params: { limit, offset, capture_id: captureId } })).data;
  }
  async artifacts(paperRunId: string) { return (await axios.get<RunArtifactsResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/artifacts`)).data; }

  async startGuidedValidation() { return (await axios.post<GuidedValidationJob>(`${this.root}/guided-validation`)).data; }
  async getGuidedValidationJob(jobId: string) { return (await axios.get<GuidedValidationJob>(`${this.root}/guided-validation/${encodeURIComponent(jobId)}`)).data; }

  async listCapturableDevices() { return (await axios.get<CapturableDevice[]>(`${this.root}/guided-validation/capturable-devices`)).data; }
  async newCaptureSession() { return (await axios.post<NewCaptureSessionResponse>(`${this.root}/guided-validation/new-capture-session`)).data; }

  async listCleanupRuns() { return (await axios.get<CleanupRunEntry[]>(`${this.root}/guided-validation/cleanup/runs`)).data; }
  async deleteCleanupRun(runId: string) {
    return (await axios.delete<DeleteCleanupRunResponse>(`${this.root}/guided-validation/cleanup/runs/${encodeURIComponent(runId)}`)).data;
  }

  async startTimingDiagnostic(runId: string, body: StartTimingDiagnosticRequest) {
    return (await axios.post<GuidedValidationActionJob>(`${this.root}/guided-validation/${encodeURIComponent(runId)}/timing-diagnostic`, body)).data;
  }
  async startTargetAbsenceControl(runId: string, body: StartTargetAbsenceControlRequest) {
    return (await axios.post<GuidedValidationActionJob>(`${this.root}/guided-validation/${encodeURIComponent(runId)}/target-absence-control`, body)).data;
  }
  async getGuidedValidationAction(runId: string, actionJobId: string) {
    return (await axios.get<GuidedValidationActionJob>(`${this.root}/guided-validation/${encodeURIComponent(runId)}/actions/${encodeURIComponent(actionJobId)}`)).data;
  }

  // Paper progress dashboard (2026-08-10) -- read-only. `runPaperExport()`
  // is the one method here that writes files server-side; it never mutates
  // the protocol/science, only generates the export manifest.
  async studyStatus(protocolId?: string) {
    return (await axios.get<StudyStatusResponse>(`${this.root}/study-status`, { params: protocolId ? { protocol_id: protocolId } : {} })).data;
  }
  async paperReadiness() { return (await axios.get<PaperReadinessRow[]>(`${this.root}/paper-readiness`)).data; }
  async campaignQualificationPreflightLatest() {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/campaign-qualification-preflight/latest`)).data;
  }
  async associationPolicyStatus() { return (await axios.get<AssociationPolicyStatusResponse>(`${this.root}/association-policy-status`)).data; }
  // Paper-representation pass (2026-08-17) -- the real per-threshold sweep
  // from the latest calibration attempt, regardless of outcome.
  async associationCalibrationSummary() {
    return (await axios.get<AssociationCalibrationSummary | NoDataResponse>(`${this.root}/association-calibration-summary`)).data;
  }
  async protocolFreezeStatus(protocolId?: string) {
    return (await axios.get<ProtocolFreezeStatusResponse>(`${this.root}/protocol-freeze-status`, { params: protocolId ? { protocol_id: protocolId } : {} })).data;
  }
  async confirmatoryStatisticalPlan(paperRunId: string) {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/confirmatory-statistical-plan`)).data;
  }
  async confirmatoryFutureAnalysis(paperRunId: string) {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/confirmatory-future-analysis`)).data;
  }
  // Phase 13 launcher (2026-08-12, fast-closure pass): the single real
  // trigger for the untouched CONFIRMATORY_FUTURE engine -- no
  // recalibration, no model re-selection, no threshold/NI/hypothesis edits.
  async startConfirmatoryFutureAnalysis(body: { paper_run_id: string; protocol_id: string; dataset_id: string; dataset_version: string; bundle_id: string; declared_contract_sha256?: string }) {
    return (await axios.post<ConfirmatoryFutureAnalysisJob>(`${this.root}/confirmatory-future-analysis`, body)).data;
  }
  async getConfirmatoryFutureAnalysisJob(jobId: string) {
    return (await axios.get<ConfirmatoryFutureAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }
  async rq1AcquisitionDependence(paperRunId: string) {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/rq1-acquisition-dependence`)).data;
  }
  async rq2RepresentationComparison(paperRunId: string) {
    return (await axios.get<Rq2RepresentationComparisonReport | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/rq2-representation-comparison`)).data;
  }
  async evidenceDashboardSummary() {
    return (await axios.get<EvidenceDashboardSummary>(`${this.root}/evidence-dashboard`)).data;
  }
  // UI-triggered equivalent of running docs/ble/generate_evidence_figures.py
  // + docs/ble/build_evidence_notebook.py from a terminal -- same real code,
  // writes real PNG/ipynb files into the repo working tree. Never runs git.
  async regenerateEvidenceFigures() {
    return (await axios.post<EvidenceFigureRegenerationResult>(`${this.root}/evidence-dashboard/regenerate-figures`)).data;
  }
  async runPaperExport() { return (await axios.post<PaperExportManifest>(`${this.root}/paper-exports`)).data; }
  async getPaperExportManifest() { return (await axios.get<PaperExportManifest | NoDataResponse>(`${this.root}/paper-exports`)).data; }

  // Provenance reconstruction (2026-08-11) -- strictly read-only.
  async listInferenceRuns() { return (await axios.get<InferenceRunSummary[]>(`${this.root}/inference-runs`)).data; }
  async getDecisionProvenance(inferenceRunId: string, exampleId: string) {
    return (await axios.get<DecisionProvenance>(`${this.root}/provenance/${encodeURIComponent(inferenceRunId)}/${encodeURIComponent(exampleId)}`)).data;
  }

  // S1 channel transport, S2 offline/near-live (2026-08-11) -- read-only.
  async getChannelTransport(paperRunId: string) {
    return (await axios.get<ChannelTransportReport | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/channel-transport`)).data;
  }
  async getOfflineNearlive(paperRunId: string) {
    return (await axios.get<OfflineNearliveReport | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/offline-nearlive`)).data;
  }

  // Study Control Center, Phase 1 (2026-08-11).
  async getStudyControlCenterStatus() {
    return (await axios.get<StudyControlCenterStatus>(`${this.root}/study-control-center`)).data;
  }
  async startHardwareQualification(body: StartHardwareQualificationRequest) {
    return (await axios.post<HardwareQualificationJob>(`${this.root}/hardware-qualification`, body)).data;
  }
  async getHardwareQualificationJob(jobId: string) {
    return (await axios.get<HardwareQualificationJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }
  async cancelHardwareQualificationJob(jobId: string) {
    return (await axios.post<HardwareQualificationJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}/cancel`)).data;
  }
  async startRq2Benchmark(body: StartRq2BenchmarkRequest) {
    return (await axios.post<Rq2BenchmarkJob>(`${this.root}/rq2-benchmark`, body)).data;
  }
  async getRq2BenchmarkJob(jobId: string) {
    return (await axios.get<Rq2BenchmarkJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }

  async evaluateStudySizing(body: { candidate_designs: HierarchicalDesignInput[]; p1: number; p2: number; alpha?: number; target_power?: number }) {
    return (await axios.post<StudySizingEvaluationResult>(`${this.root}/study-sizing/evaluate`, body)).data;
  }
  async recordStudySizingDecision(body: { chosen_design: HierarchicalDesignInput; p1: number; p2: number; alpha?: number; target_power?: number; rationale: string; decided_by?: string }) {
    return (await axios.post<StudySizingDecision>(`${this.root}/study-sizing/decision`, body)).data;
  }
  async getStudySizingDecision() {
    return (await axios.get<StudySizingDecision | NoDataResponse>(`${this.root}/study-sizing/decision`)).data;
  }

  // Study Control Center, phase 09 (2026-08-11) -- Analysis Contract Readiness.
  async getAnalysisContractReadiness() {
    return (await axios.get<AnalysisContractReadiness>(`${this.root}/analysis-contract-readiness`)).data;
  }
  async recordScientistDecision(body: RecordScientistDecisionRequest) {
    return (await axios.post<ScientistDecisionRecord>(`${this.root}/scientist-decisions`, body)).data;
  }
  async listScientistDecisions(fieldId?: string) {
    return (await axios.get<ScientistDecisionRecord[]>(`${this.root}/scientist-decisions`, { params: fieldId ? { field_id: fieldId } : {} })).data;
  }

  // RQ3 real FRR pre/post analysis (2026-08-11).
  async startRq3FrrAnalysis(body: StartRq3FrrAnalysisRequest) {
    return (await axios.post<Rq3FrrAnalysisJob>(`${this.root}/rq3-frr-analysis`, body)).data;
  }
  async getRq3FrrAnalysisJob(jobId: string) {
    return (await axios.get<Rq3FrrAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }

  // Coverage canonical producer (2026-08-12, Scientific Closure pass).
  async startCoverageAnalysis(body: StartCoverageAnalysisRequest) {
    return (await axios.post<CoverageAnalysisJob>(`${this.root}/coverage-analysis`, body)).data;
  }
  async getCoverageAnalysisJob(jobId: string) {
    return (await axios.get<CoverageAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }
  async getCoverageAnalysis(paperRunId: string) {
    return (await axios.get<CoverageAnalysisReport | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/coverage-analysis`)).data;
  }

  // Sensitivity canonical producer (2026-08-12, Scientific Closure pass).
  async startSensitivityAnalysis(paperRunId: string) {
    return (await axios.post<SensitivityAnalysisJob>(`${this.root}/sensitivity-analysis`, { paper_run_id: paperRunId })).data;
  }
  async getSensitivityAnalysisJob(jobId: string) {
    return (await axios.get<SensitivityAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }
  async getSensitivityAnalysis(paperRunId: string) {
    return (await axios.get<SensitivityReport | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/sensitivity-analysis`)).data;
  }

  // RQ4 region-specific fitting closure (2026-08-12): rq4_primary_analysis=
  // REGION_SPECIFIC_FITTING_AND_EVALUATION. Persists into the SAME
  // confirmatory_statistical_plan_report.json RQ3 writes to (rq4_region_report) --
  // read via confirmatoryStatisticalPlan(), no separate GET route.
  async startRq4RegionAnalysis(body: StartRq4RegionAnalysisRequest) {
    return (await axios.post<Rq4RegionAnalysisJob>(`${this.root}/rq4-region-analysis`, body)).data;
  }
  async getRq4RegionAnalysisJob(jobId: string) {
    return (await axios.get<Rq4RegionAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }

  // Fast-closure pass (2026-08-12), Phase 14 (S1) / Phase 15 (S2) launchers.
  async startChannelTransportAnalysis(paperRunId: string, bundleId?: string) {
    return (await axios.post<ChannelTransportAnalysisJob>(`${this.root}/channel-transport-analysis`, { paper_run_id: paperRunId, bundle_id: bundleId || undefined })).data;
  }
  async getChannelTransportAnalysisJob(jobId: string) {
    return (await axios.get<ChannelTransportAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }
  async startOfflineNearliveAnalysis(paperRunId: string) {
    return (await axios.post<OfflineNearliveAnalysisJob>(`${this.root}/offline-nearlive-analysis`, { paper_run_id: paperRunId })).data;
  }
  async getOfflineNearliveAnalysisJob(jobId: string) {
    return (await axios.get<OfflineNearliveAnalysisJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data;
  }

  // Scientific Dashboard closure, Level A/B (2026-08-11).
  async getExperimentHealth() {
    return (await axios.get<ExperimentHealthSummary>(`${this.root}/experiment-health`)).data;
  }
  async getEvidenceQualitySummary(paperRunId: string) {
    return (await axios.get<EvidenceQualitySummary | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/evidence-quality-summary`)).data;
  }

  // Paper-representation pass (2026-08-17) -- supporting tables + the
  // scientific completeness report. Zero new science: real cross-references
  // over already-real registry/capture/split/readiness artifacts.
  async txComposition() { return (await axios.get<TxCompositionRow[]>(`${this.root}/tx-composition`)).data; }
  async partitionComposition(datasetId: string, datasetVersion: string, scientificTask: string) {
    return (await axios.get<PartitionCompositionTable>(`${this.root}/partition-composition`, {
      params: { dataset_id: datasetId, dataset_version: datasetVersion, scientific_task: scientificTask },
    })).data;
  }
  async receiverEpochs() { return (await axios.get<ReceiverEpochRow[]>(`${this.root}/receiver-epochs`)).data; }
  async scientificCompleteness() { return (await axios.get<ScientificCompletenessReport>(`${this.root}/scientific-completeness`)).data; }
}
