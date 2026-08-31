// Domain Types
export interface SpectrumData {
  timestamp: number;
  centerFrequency: number;
  span: number;
  frequencyArray: number[];
  powerLevels: number[];
  sampleRateHz?: number;
  fftSize?: number;
  requestedRbwHz?: number;
  effectiveRbwHz?: number;
  powerUnit?: 'dBFS' | 'dBm';
  sourceId?: string;
  deviceSerial?: string;
  calibrationId?: string;
}

export interface WaterfallData {
  timestamp: number;
  centerFrequency: number;
  span: number;
  data: number[][];
}

export interface RFObjectEvidence {
  frequency_band_match: boolean;
  bandwidth_match: boolean;
  temporal_match: boolean;
  channel_grid_match?: string | null;
  notes: string[];
}

export interface RFObjectDetection {
  id: string;
  track_id?: string | null;
  label: string;
  candidate_family: string;
  confidence: number;
  center_frequency_hz: number;
  start_frequency_hz: number;
  stop_frequency_hz: number;
  bandwidth_hz: number;
  occupied_bandwidth_hz: number;
  snr_db: number;
  peak_power_db: number;
  mean_power_db: number;
  noise_floor_db: number;
  temporal_type: 'continuous' | 'bursty' | 'hopping_candidate' | 'unknown';
  persistence: number;
  first_seen_utc?: string | null;
  last_seen_utc?: string | null;
  evidence: RFObjectEvidence;
}

export interface RFSceneAnalysis {
  timestamp_utc?: string | null;
  noise_floor_db?: number | null;
  threshold_db?: number | null;
  detections: RFObjectDetection[];
  summary: {
    total_detections: number;
    families: Record<string, number>;
    classifier_mode: string;
  };
}

export interface Marker {
  id: string;
  label: string;
  frequency: number;
  level: number;
  type: 'normal' | 'delta' | 'noise' | 'peak';
  enabled: boolean;
}

export interface DeviceStatus {
  isConnected: boolean;
  driver: string;
  centerFrequency: number;
  sampleRate: number;
  gain: number;
  antenna?: string;
  lastError?: string | null;
}

export interface AnalyzerSettings {
  centerFrequency: number;
  span: number;
  sampleRate: number;
  rbw: number;
  vbw: number;
  referenceLevel: number;
  noiseFloorOffset: number;
  detectorMode: 'sample' | 'rms' | 'average' | 'peak' | 'min_hold' | 'max_hold' | 'video';
  traceMode: 'clear_write' | 'average' | 'max_hold' | 'min_hold' | 'video_average';
  dbPerDiv: number;
  colorScheme: 'blue' | 'green' | 'amber' | 'magenta';
  averaging: number;
  smoothing: number;
}

export interface Recording {
  id: string;
  sessionId: string;
  timestamp: number;
  duration: number;
  filePath: string;
  size: number;
  type: 'iq' | 'audio';
}

export interface DemodulationResult {
  id: string;
  generated_at_utc?: string;
  timestamp_utc?: string;
  status: string;
  final_status?: string;
  mode: string;
  source?: 'live_sdr' | 'dataset_builder' | string;
  marker_left_hz?: number;
  marker_right_hz?: number;
  pipeline?: string;
  rf_analysis_source?: 'computed_from_live_iq' | 'computed_from_file_iq' | string;
  demodulation_source?: 'computed_from_live_iq' | 'computed_from_file_iq' | string;
  start_frequency_hz?: number;
  stop_frequency_hz?: number;
  center_frequency_hz: number;
  bandwidth_hz?: number;
  duration_seconds?: number;
  sample_rate_hz: number;
  audio_supported?: boolean;
  audio_file?: string | null;
  audio_url?: string | null;
  iq_file?: string;
  metadata_file?: string;
  metadata_url?: string;
  sample_id?: string;
  dataset_id?: string;
  source_dataset?: string;
  input_file?: string;
  signal_type?: string;
  demodulation_pipeline?: string;
  protocol?: string;
  channel?: number;
  packets_decoded?: number;
  packets_crc_valid?: number;
  access_address_detected?: boolean;
  access_address?: string;
  valid_demodulation?: boolean;
  confidence_score?: number | null;
  computed_ble_channel?: number;
  burst_count?: number;
  frames_decoded?: number;
  frames_crc_valid?: number;
  decoded_packets?: Record<string, unknown>;
  decoded_payload?: Record<string, unknown>;
  outputs?: Record<string, string | null>;
  rf_activity?: Record<string, unknown>;
  notes?: string[];
}

export interface ModulatedSignalCapture {
  id: string;
  generated_at_utc: string;
  capture_type: string;
  file_format?: 'cfile' | 'iq';
  source_device: string;
  driver: string;
  label?: string;
  modulation_hint?: string;
  notes?: string;
  dataset_split?: 'train' | 'val' | 'predict';
  session_id?: string;
  transmitter_id?: string;
  transmitter_class?: string;
  operator?: string;
  environment?: string;
  start_frequency_hz: number;
  stop_frequency_hz: number;
  center_frequency_hz: number;
  bandwidth_hz: number;
  duration_seconds: number;
  sample_rate_hz: number;
  sample_count: number;
  gain_db: number;
  antenna: string;
  device_addr: string;
  channel_index: number;
  iq_file: string;
  metadata_file: string;
  iq_format: string;
  file_extension?: string;
  iq_dtype: string;
  byte_order: string;
  file_size_bytes: number;
  sha256: string;
  iq_url?: string;
  metadata_url?: string;
  external_iq_file?: boolean;
  metadata_path_repaired?: boolean;
  replay_parameters?: {
    center_frequency_hz: number;
    sample_rate_hz: number;
    gain_db: number;
    antenna: string;
    iq_format: string;
  };
  ai_dataset_fields?: string[];
  preview_metrics?: {
    live_preview_snr_db?: number;
    live_preview_noise_floor_db?: number;
    live_preview_peak_level_db?: number;
    live_preview_peak_frequency_hz?: number;
  };
  trigger_capture?: {
    mode?: 'immediate' | 'triggered_burst';
    strategy?: string;
    threshold_db?: number;
    pre_trigger_ms?: number;
    post_trigger_ms?: number;
    trigger_max_wait_s?: number;
    trigger_detected?: boolean;
    burst_start_sample?: number;
    burst_end_sample?: number;
    captured_duration_s?: number;
    // Session-level fields (triggered_burst_capture.py)
    event_index?: number;
    session_events_requested?: number;
    session_events_captured?: number;
    session_events_qc_passed?: number;
    snr_db?: number;
    noise_floor_db?: number;
    trigger_energy_db?: number;
    trigger_timestamp_utc?: string;
  };
}

export interface Session {
  id: string;
  name: string;
  createdAt: number;
  recordings: Recording[];
  notes?: string;
}

export interface Preset {
  id: string;
  name: string;
  settings: AnalyzerSettings;
  createdAt: number;
}

export interface FingerprintingDashboardSummary {
  modes: Array<{
    id: string;
    title: string;
    goal: string;
  }>;
  thresholds: Record<string, number>;
  summary: {
    total_captures: number;
    valid_captures: number;
    doubtful_captures: number;
    rejected_captures: number;
  };
  required_metadata: string[];
}

export interface FingerprintingCaptureRecord {
  capture_id: string;
  capture_mode: string;
  session_id: string;
  dataset_split: string;
  created_at_utc: string;
  updated_at_utc?: string;
  capture_config: {
    device_source: string;
    sdr_model: string;
    sdr_serial: string;
    gain_stage?: string;
    antenna_port: string;
    capture_type: string;
    center_frequency_hz: number;
    sample_rate_hz: number;
    effective_bandwidth_hz: number;
    frontend_bandwidth_hz?: number | null;
    gain_mode: string;
    gain_settings: Record<string, unknown>;
    ppm_correction: number;
    lo_offset_hz: number;
    capture_duration_s: number;
    sample_count: number;
    file_format: string;
    sample_dtype: string;
    byte_order: string;
    channel_count: number;
    output_path: string;
    dataset_destination?: string;
  };
  transmitter: {
    transmitter_label: string;
    transmitter_class: string;
    transmitter_id: string;
    family: string;
    signal_type?: string;
    modulation_class?: string;
    protocol_family?: string;
    band_label?: string;
    profile_key?: string | null;
    ground_truth_confidence: string;
  };
  scenario: {
    operator: string;
    environment: string;
    distance_m?: number | null;
    line_of_sight?: boolean | null;
    indoor?: boolean | null;
    notes: string;
    session_number: number;
    timestamp_utc: string;
  };
  signal_family?: 'continuous_fm' | 'burst_rf' | 'packet_rf' | 'unknown';
  qc_profile_id?: string | null;
  iq_file_diagnostics?: {
    num_complex_samples?: number;
    duration_seconds?: number;
    dtype?: string;
    endianness?: string;
    mean_power_db?: number;
    rms_power_db?: number;
    zero_ratio?: number;
    near_zero_ratio?: number;
    nan_ratio?: number;
    inf_ratio?: number;
    spectral_peak_offset_hz?: number | null;
  };
  snr?: {
    temporal_snr_db?: number | null;
    burst_snr_db?: number | null;
    spectral_snr_db?: number | null;
    selected_snr_db?: number | null;
    selected_snr_method?: string | null;
  };
  quality_metrics: {
    estimated_snr_db?: number;
    temporal_snr_db?: number | null;
    burst_snr_db?: number | null;
    spectral_snr_db?: number | null;
    selected_snr_db?: number | null;
    selected_snr_method?: string | null;
    channel_presence_ratio?: number | null;
    noise_floor_db?: number | null;
    peak_power_db?: number | null;
    average_power_db?: number | null;
    occupied_bandwidth_hz?: number | null;
    peak_frequency_hz?: number | null;
    frequency_offset_hz?: number;
    live_offset_hz?: number | null;
    clipping_pct?: number;
    sample_drop_count?: number;
    buffer_overflow_count?: number;
    silence_pct?: number;
    peak_to_average_ratio_db?: number | null;
    kurtosis?: number | null;
    burst_duration_ms?: number;
  };
  burst_detection: {
    method: string;
    energy_threshold_db?: number | null;
    pre_trigger_samples: number;
    post_trigger_samples: number;
    min_burst_duration_ms: number;
    max_burst_duration_ms?: number | null;
    burst_count: number;
    regions_of_interest: string[];
    burst_start_sample?: number | null;
    burst_end_sample?: number | null;
  };
  quality_review: {
    status: 'valid' | 'doubtful' | 'rejected';
    capture_quality?: 'valid' | 'warning' | 'doubtful' | 'invalid';
    label_status?: 'unlabeled' | 'weak_label' | 'strong_label';
    review_status?: 'needs_review' | 'accepted' | 'rejected' | 'manual_override';
    training_readiness?: 'not_ready' | 'candidate' | 'ready_for_training' | 'debug_only';
    qc_policy_profile?: string;
    qc_thresholds?: Record<string, unknown>;
    metadata_check?: Record<string, unknown>;
    band_profile_resolution?: Record<string, any>;
    manual_override_reason?: string;
    reasons: string[];
    quality_flags: string[];
    operator_decision?: 'valid' | 'doubtful' | 'rejected' | null;
    review_notes?: string;
    export_windows?: string[];
    updated_at_utc?: string;
  };
  artifacts: {
    iq_file?: string | null;
    metadata_file?: string | null;
    sha256?: string | null;
    source_capture_id?: string | null;
  };
  preview_metrics?: {
    live_preview_snr_db?: number | null;
    live_preview_noise_floor_db?: number | null;
    live_preview_peak_level_db?: number | null;
    live_preview_peak_frequency_hz?: number | null;
  };
  prediction_ready?: boolean;
  prediction_ready_reason?: string;
}

export interface TrainingDashboard {
  model_dir: string;
  current_model: {
    path: string;
    exists: boolean;
    size_bytes: number;
    modified_at_utc?: string | null;
    train_config?: Record<string, unknown>;
    dataset_manifest?: Record<string, unknown>;
    label_map?: Record<string, unknown>;
    file_inventory?: Array<{
      name: string;
      path: string;
      size_bytes: number;
      modified_at_utc?: string | null;
    }>;
  };
  dataset: {
    records: number;
    devices: number;
    sessions: number;
    device_ids: string[];
  };
  training: {
    epochs: number;
    best_test_acc: number;
    last_test_acc: number;
    last_train_acc: number;
    best_epoch: number | null;
    config: Record<string, unknown>;
    profiles_count: number;
    labeled_devices: number;
    latest_history: Array<Record<string, unknown>>;
  };
  retraining: {
    snapshot_count: number;
    snapshots: Array<Record<string, unknown>>;
  };
  prediction_readiness: {
    has_model_file: boolean;
    has_profiles: boolean;
    has_manifest: boolean;
    has_history: boolean;
    has_validation: boolean;
    latest_validation?: Record<string, unknown> | null;
  };
  validation_reports: Array<Record<string, unknown>>;
  filesystem: {
    model_dir_exists: boolean;
    model_dir_size_bytes: number;
    train_dataset_dir: string;
    train_dataset_size_bytes: number;
    val_dataset_dir: string;
    val_dataset_size_bytes: number;
    predict_dataset_dir: string;
    predict_dataset_size_bytes: number;
  };
}

export interface AsyncJobStatus {
  status: string;
  job_id?: string;
  started_at_utc?: string;
  ended_at_utc?: string | null;
  returncode?: number | null;
  command?: string[];
  cwd?: string | null;
  metadata?: Record<string, unknown>;
  stdout?: string;
  stderr?: string;
  report?: Record<string, unknown>;
}

export interface ModelArtifactSummary {
  version?: string;
  created_at_utc?: string;
  metrics?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RFSignalUnderstandingResult {
  analysis_id: string;
  mode?: string;
  source?: string;
  timestamp_utc?: string;
  input: Record<string, unknown>;
  waterfall: Record<string, unknown>;
  regions: Array<Record<string, any>>;
  summary?: Record<string, unknown>;
  scientific_traceability: Array<Record<string, string>>;
}

export interface RFSignalUnderstandingComparison {
  analysis_id: string;
  legacy_rf_intelligence: Record<string, any>;
  new_rf_signal_understanding: Record<string, any>;
  comparison: Record<string, any>;
  live_result?: RFSignalUnderstandingResult;
}

// API Response Types
export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
}

// Form Types
export interface FrequencyInput {
  value: number;
  unit: 'Hz' | 'kHz' | 'MHz' | 'GHz';
}

export interface GainInput {
  value: number;
  mode: 'auto' | 'manual';
}

// UI State Types
export interface UiState {
  theme: 'light' | 'dark' | 'laboratory';
  sidebarCollapsed: boolean;
  topBarCollapsed: boolean;
  activeTab: 'spectrum' | 'waterfall' | 'recordings' | 'settings';
}

