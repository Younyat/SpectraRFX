// Mirrors backend/app/modules/ai_research_plugin/catalog/contracts.py
// exactly. Deliberately separate from ../types.ts (RFModelManifest etc.):
// those describe a model already IMPORTED into this plugin; these describe
// a model being DISCOVERED from the outside world, which may not even be
// a model (a dataset or a framework/toolkit) and is never used to gate
// inference.

export type CatalogTask =
  | 'MODULATION_CLASSIFICATION' | 'WIRELESS_TECHNOLOGY_CLASSIFICATION' | 'RADIO_SYSTEM_IDENTIFICATION'
  | 'PROTOCOL_IDENTIFICATION' | 'SIGNAL_DETECTION' | 'WIDEBAND_SIGNAL_DETECTION' | 'RF_FINGERPRINTING'
  | 'EMITTER_IDENTIFICATION' | 'INTERFERENCE_CLASSIFICATION' | 'RADAR_WAVEFORM_CLASSIFICATION'
  | 'UAV_RF_CLASSIFICATION' | 'SPECTRUM_SENSING' | 'SPECTRUM_ANOMALY_DETECTION' | 'FOUNDATION_MODEL'
  | 'REPRESENTATION_MODEL' | 'UNKNOWN';

export type CatalogInputRepresentation =
  | 'RAW_IQ' | 'COMPLEX_IQ' | 'IQ_FEATURES' | 'SPECTROGRAM' | 'WATERFALL_IMAGE' | 'PSD' | 'FFT'
  | 'CONSTELLATION' | 'MEL_SPECTROGRAM' | 'PREAMBLE_IQ' | 'TRANSIENT_IQ' | 'FEATURE_VECTOR'
  | 'CSI' | 'CIR' | 'OTHER' | 'UNKNOWN';

export type CatalogEntryKind = 'MODEL' | 'FRAMEWORK_TOOLKIT' | 'DATASET';

export type CatalogStatus =
  | 'READY' | 'CONVERTIBLE' | 'CONVERSION_REQUIRED' | 'PLATFORM_ADAPTER_REQUIRED' | 'FOUNDATION_FINE_TUNING_REQUIRED'
  | 'RESEARCH_MODEL' | 'DATASET_ONLY' | 'UNSUPPORTED';

export type CatalogOriginalFormat =
  | 'onnx' | 'safetensors' | 'pt' | 'pth' | 'ckpt' | 'bin' | 'torchscript' | 'h5' | 'keras'
  | 'tensorflow_savedmodel' | 'tflite' | 'engine' | 'none' | 'unknown';

export type CatalogSourceKind = 'CURATED' | 'HUGGINGFACE_LIVE';

export interface RFModelCatalogEntry {
  id: string;
  name: string;
  kind: CatalogEntryKind;
  provider: string;
  source_url: string;
  paper_url: string | null;
  download_url: string | null;

  task: CatalogTask;
  signal_domain: string | null;
  classes: string[] | null;

  input_representation: CatalogInputRepresentation;
  expected_sample_rate_hz: number | null;
  input_length: number | null;
  input_shape: (number | null)[] | null;
  normalization: string | null;
  preprocessing: string | null;

  framework: string | null;
  original_format: CatalogOriginalFormat;
  onnx_available: boolean;
  conversion_status: CatalogStatus;
  opset: number | null;
  output_shape: (number | null)[] | null;
  output_labels: string[] | null;

  license: string | null;
  dataset: string | null;
  reported_metrics: Record<string, unknown> | null;
  validation_status: string;
  independently_verified: boolean;

  priority: string | null;
  notes: string | null;
  source_kind: CatalogSourceKind;
}

export interface CatalogListResponse {
  entries: RFModelCatalogEntry[];
  total: number;
}

export interface CatalogFilters {
  task?: CatalogTask;
  input_representation?: CatalogInputRepresentation;
  kind?: CatalogEntryKind;
  onnx_available?: boolean;
  conversion_status?: CatalogStatus;
  source_kind?: CatalogSourceKind;
}
