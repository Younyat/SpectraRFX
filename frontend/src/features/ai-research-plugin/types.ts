// Mirrors backend/app/modules/ai_research_plugin/contracts.py exactly --
// field names are snake_case because that is genuinely what the FastAPI/
// Pydantic JSON response contains (no alias layer exists on the backend),
// not a stylistic choice made independently on this side.

export type ModelFramework = 'onnx' | 'torchscript' | 'tensorflow';

export type RFTask =
  | 'modulation_classification' | 'signal_classification' | 'fingerprinting'
  | 'anomaly_detection' | 'emitter_identification' | 'other';

export type InputRepresentation = 'raw_iq' | 'iq_tensor' | 'spectrogram' | 'psd' | 'features' | 'flat_iq' | 'unknown';

export type OutputType = 'class_logits' | 'class_probabilities' | 'embedding' | 'reconstruction' | 'detector' | 'unknown';

export interface RFModelInputFields {
  representation: InputRepresentation | null;
  tensor_shape: (number | null)[] | null;
  dtype: string | null;
  input_name: string | null;
  sample_rate_hz: number | null;
  bandwidth_hz: number | null;
  center_frequency_dependency: boolean | null;
  window_samples: number | null;
  overlap: number | null;
  // Operator-asserted only -- never discovered from the ONNX graph itself
  // (see backend contracts.py). null = "unknown, not confirmed applicable
  // at any particular frequency", never "applies everywhere".
  expected_center_frequency_hz: number | null;
  expected_frequency_tolerance_hz: number | null;
  // The signal's real typical OCCUPIED bandwidth (e.g. ~2 MHz for BLE) --
  // a different concept from `bandwidth_hz` above (that one is the
  // capture/analysis bandwidth fed INTO the model). Used only to size the
  // LIVE detection's 3D highlight; never discovered.
  expected_signal_bandwidth_hz: number | null;
}

export interface RFModelPreprocessing {
  normalization: string | null;
  fft_size: number | null;
  stft_window: string | null;
  stft_hop: number | null;
  scaling: string | null;
}

export interface RFModelOutputFields {
  output_type: OutputType | null;
  tensor_shape: (number | null)[] | null;
  output_name: string | null;
  classes: string[] | null;
  // Operator-typed-once explanation per class name (e.g. "BPSK" -> "Binary
  // Phase Shift Keying"). Never discovered -- an ONNX graph carries no
  // semantic meaning for a class name/index.
  class_descriptions: Record<string, string> | null;
}

export interface RFModelProvenance {
  paper: string | null;
  authors: string | null;
  repository: string | null;
  dataset: string | null;
  model_version: string | null;
  notes: string | null;
}

export interface RFModelManifest {
  model_id: string;
  model_name: string;
  framework: ModelFramework;
  model_file: string;
  model_sha256: string;
  imported_at_utc: string;
  // The real, absolute path this .onnx was found at on the operator's own
  // machine -- set only when imported via importFromFolder() (a bulk local
  // directory scan), null for a model imported one at a time through the
  // file picker. See backend RFModelManifest's own field docstring.
  local_source_path: string | null;
  task: RFTask;
  input_discovered: RFModelInputFields;
  input_overrides: RFModelInputFields;
  preprocessing: RFModelPreprocessing;
  output_discovered: RFModelOutputFields;
  output_overrides: RFModelOutputFields;
  provenance: RFModelProvenance;
}

export interface FolderImportFailure {
  filename: string;
  error: string;
}

// Real outcome of scanning one local directory for .onnx files -- every
// file found is accounted for in exactly one of the three lists, never
// silently dropped. See backend contracts.FolderImportResult.
export interface FolderImportResult {
  folder_path: string;
  imported: RFModelManifest[];
  skipped_duplicate: string[];
  failed: FolderImportFailure[];
}

export type CompatibilityVerdict = 'COMPATIBLE' | 'PARTIALLY_COMPATIBLE' | 'INCOMPATIBLE' | 'UNKNOWN';

export interface CompatibilityCheck {
  field: string;
  capture_value: unknown;
  model_value: unknown;
  matched: boolean | null;
  note: string;
}

export interface CompatibilityResult {
  verdict: CompatibilityVerdict;
  checks: CompatibilityCheck[];
}

export interface InferenceRecord {
  record_id: string;
  model_id: string;
  model_sha256: string;
  model_manifest_snapshot: RFModelManifest;
  capture_id: string;
  capture_data_sha256: string;
  selected_time_seconds: [number, number];
  selected_frequency_hz: [number, number] | null;
  input_transformation: InputRepresentation;
  input_tensor_shape: number[];
  input_dtype: string;
  normalization_applied: string;
  inference_timestamp_utc: string;
  software_backend: string;
  raw_output: number[];
  raw_output_shape: number[];
  interpretation: {
    kind: 'classification' | 'embedding' | 'not_automatically_interpretable';
    predicted_class?: string;
    score?: number;
    score_type?: 'logit' | 'probability';
    class_scores?: Record<string, number>;
    known_classes?: string[];
    dimensionality?: number;
    l2_norm?: number;
    warning?: string;
  };
  compatibility: CompatibilityResult;

  // Real, measured wall-clock durations -- see backend contracts.py.
  // capture_latency_ms is null for an OFFLINE run (no live-snapshot wait).
  capture_latency_ms: number | null;
  inference_latency_ms: number | null;
  total_latency_ms: number | null;
}

// Real fields from ble_capture_job_manager.list_captures() -- the
// same manifest shape RF Terrain's Offline Reconstruction already reads.
export interface AiPluginCaptureSummary {
  capture_id: string;
  data_sha256?: string;
  sample_rate_sps?: number;
  center_frequency_hz?: number;
  bandwidth_hz?: number;
  sample_format?: string;
  actual_samples?: number;
  device_serial?: string;
  created_at_utc?: string;
}
