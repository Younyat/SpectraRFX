// UI Constants
export const THEME = {
  COLORS: {
    primary: '#3b82f6',
    secondary: '#64748b',
    success: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444',
    background: '#ffffff',
    surface: '#f8fafc',
    text: '#1e293b',
    textSecondary: '#64748b',
  },
  SPACING: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
    xxl: '3rem',
  },
  BORDER_RADIUS: {
    sm: '0.25rem',
    md: '0.375rem',
    lg: '0.5rem',
    xl: '0.75rem',
  },
} as const;

// Frequency Units
export const FREQUENCY_UNITS = {
  Hz: 1,
  kHz: 1000,
  MHz: 1000000,
  GHz: 1000000000,
} as const;

// Detector Modes
export const DETECTOR_MODES = [
  { value: 'sample', label: 'Sample' },
  { value: 'rms', label: 'RMS' },
  { value: 'average', label: 'Average' },
  { value: 'peak', label: 'Peak' },
  { value: 'max_hold', label: 'Max Hold' },
  { value: 'min_hold', label: 'Min Hold' },
  { value: 'video', label: 'Video' },
] as const;

export const TRACE_MODES = [
  { value: 'clear_write', label: 'Clear/Write' },
  { value: 'average', label: 'Average' },
  { value: 'max_hold', label: 'Max Hold' },
  { value: 'min_hold', label: 'Min Hold' },
  { value: 'video_average', label: 'Video Avg' },
] as const;

export const SPECTRUM_COLOR_SCHEMES = [
  { value: 'blue', label: 'Blue' },
  { value: 'green', label: 'Green' },
  { value: 'amber', label: 'Amber' },
  { value: 'magenta', label: 'Magenta' },
] as const;

// Window Functions
export const WINDOW_FUNCTIONS = [
  { value: 'hann', label: 'Hann' },
  { value: 'hamming', label: 'Hamming' },
  { value: 'blackman', label: 'Blackman' },
  { value: 'bartlett', label: 'Bartlett' },
  { value: 'rectangular', label: 'Rectangular' },
] as const;

// Demodulation Modes
export const DEMODULATION_MODES = [
  { value: 'am', label: 'AM' },
  { value: 'fm', label: 'FM' },
  { value: 'nfm', label: 'NFM' },
  { value: 'wfm', label: 'WFM' },
  { value: 'ask', label: 'ASK' },
  { value: 'fsk', label: 'FSK' },
  { value: 'psk', label: 'PSK' },
  { value: 'ook', label: 'OOK' },
] as const;

export const MODULATION_HINTS = [
  { value: 'unknown', label: 'Unknown' },
  { value: 'am', label: 'AM' },
  { value: 'fm', label: 'FM' },
  { value: 'nfm', label: 'NFM' },
  { value: 'wfm', label: 'WFM' },
  { value: 'ask', label: 'ASK' },
  { value: 'fsk', label: 'FSK' },
  { value: 'psk', label: 'PSK' },
  { value: 'ook', label: 'OOK' },
  { value: 'ofdm', label: 'OFDM' },
  { value: 'lora', label: 'LoRa' },
] as const;

// Recording Formats
export const RECORDING_FORMATS = [
  { value: 'iq', label: 'IQ Data' },
  { value: 'audio', label: 'Audio WAV' },
] as const;

// Colormaps
export const COLORMAPS = [
  { value: 'turbo', label: 'Turbo' },
  { value: 'viridis', label: 'Viridis' },
  { value: 'plasma', label: 'Plasma' },
  { value: 'inferno', label: 'Inferno' },
  { value: 'magma', label: 'Magma' },
] as const;

// Default Settings
export const DEFAULT_SETTINGS = {
  centerFrequency: 89400000, // 89.4 MHz
  span: 2000000, // 2 MHz
  sampleRate: 4000000, // 4 MSps -- real acquisition rate, independent of span
  rbw: 10000, // 10 kHz
  vbw: 10000, // 10 kHz
  referenceLevel: 0, // 0 dBm
  noiseFloorOffset: 0,
  detectorMode: 'sample' as const,
  traceMode: 'clear_write' as const,
  dbPerDiv: 10,
  colorScheme: 'blue' as const,
  averaging: 1,
  smoothing: 0,
} as const;

// API Endpoints
export const API_ENDPOINTS = {
  // Device
  DEVICE_STATUS: '/api/device/status',
  DEVICE_CONNECT: '/api/device/connect',
  DEVICE_DISCONNECT: '/api/device/disconnect',
  DEVICE_OPEN_RECEIVER: '/api/device/receiver/open',
  DEVICE_CLOSE_RECEIVER: '/api/device/receiver/close',
  DEVICE_START_STREAM: '/api/device/stream/start',
  DEVICE_STOP_STREAM: '/api/device/stream/stop',
  DEVICE_SET_FREQUENCY: '/api/device/frequency',
  DEVICE_SET_GAIN: '/api/device/gain',
  DEVICE_SET_SAMPLE_RATE: '/api/device/sample-rate',

  // Runtime settings
  RUNTIME_SETTINGS: '/api/runtime-settings',

  // Spectrum
  SPECTRUM_LIVE: '/api/spectrum/live',
  SPECTRUM_SET_CENTER: '/api/spectrum/center-frequency',
  SPECTRUM_SET_SPAN: '/api/spectrum/span',
  SPECTRUM_SET_START_STOP: '/api/spectrum/start-stop',
  SPECTRUM_SET_RBW: '/api/spectrum/rbw',
  SPECTRUM_SET_VBW: '/api/spectrum/vbw',
  SPECTRUM_SET_REFERENCE_LEVEL: '/api/spectrum/reference-level',
  SPECTRUM_SET_NOISE_FLOOR: '/api/spectrum/noise-floor-offset',
  SPECTRUM_SET_DETECTOR: '/api/spectrum/detector-mode',
  SPECTRUM_SET_AVERAGING: '/api/spectrum/averaging',

  // Waterfall
  WATERFALL_LIVE: '/api/waterfall/live',

  // RF Intelligence
  RF_INTELLIGENCE_LIVE: '/api/rf-intelligence/live',
  RF_INTELLIGENCE_ANALYZE: '/api/rf-intelligence/analyze',
  RF_INTELLIGENCE_BAND_PROFILE_RESOLVE: '/api/rf-intelligence/band-profile/resolve',

  // RF Signal Understanding
  RF_SIGNAL_UNDERSTANDING_LIVE: '/api/rf-signal-understanding/live',
  RF_SIGNAL_UNDERSTANDING_ANALYZE_FRAME: '/api/rf-signal-understanding/analyze-frame',
  RF_SIGNAL_UNDERSTANDING_ANALYZE: '/api/rf-signal-understanding/analyze',
  RF_SIGNAL_UNDERSTANDING_COMPARE: '/api/rf-signal-understanding/compare-with-rf-intelligence',
  RF_SIGNAL_UNDERSTANDING_COMPARE_LIVE: '/api/rf-signal-understanding/compare-live-with-rf-intelligence',
  RF_SIGNAL_UNDERSTANDING_RESULTS: (id: string) => `/api/rf-signal-understanding/results/${id}`,
  RF_SIGNAL_UNDERSTANDING_MODELS: '/api/rf-signal-understanding/models',
  RF_SIGNAL_UNDERSTANDING_REFERENCES: '/api/rf-signal-understanding/references',
  RF_SIGNAL_UNDERSTANDING_REVIEW_REGION: '/api/rf-signal-understanding/regions/review',
  RF_SIGNAL_UNDERSTANDING_PSEUDO_LABEL: '/api/rf-signal-understanding/regions/pseudo-label',
  RF_SIGNAL_UNDERSTANDING_TRAIN_INCREMENTAL: '/api/rf-signal-understanding/train-classifier-incremental',
  RF_SIGNAL_UNDERSTANDING_COMPARE_MODELS: '/api/rf-signal-understanding/compare-models',
  RF_SIGNAL_UNDERSTANDING_CAPTURE_FOR_TRAINING: '/api/rf-signal-understanding/capture-for-training',
  RF_SIGNAL_UNDERSTANDING_CAPTURE_REGISTRY: '/api/rf-signal-understanding/capture-registry',
  RF_SIGNAL_UNDERSTANDING_REGISTER_CAPTURE: '/api/rf-signal-understanding/capture-registry/register',
  RF_SIGNAL_UNDERSTANDING_ANALYZE_REGISTERED_CAPTURE: (id: string) => `/api/rf-signal-understanding/capture-registry/${id}/analyze`,
  RF_SIGNAL_UNDERSTANDING_DELETE_REGISTERED_CAPTURE: (id: string) => `/api/rf-signal-understanding/capture-registry/${id}`,
  RF_SIGNAL_UNDERSTANDING_TRAINING_QUEUE: '/api/rf-signal-understanding/training-queue',

  // RF Experiment Lab
  RF_EXPERIMENT_HEALTH: '/api/rf-experiment-lab/health',
  RF_EXPERIMENT_DATASET_CAPTURES: '/api/rf-experiment-lab/dataset/captures',
  RF_EXPERIMENT_DATASET_SOURCES: '/api/rf-experiment-lab/dataset/sources',
  RF_EXPERIMENT_INTERNAL_SAMPLES: '/api/rf-experiment-lab/dataset/internal-samples',
  RF_EXPERIMENT_INTERNAL_SAMPLE_REVIEW: (id: string) => `/api/rf-experiment-lab/dataset/internal-samples/${id}/review`,
  RF_EXPERIMENT_DATASET_V1_PREVIEW: '/api/rf-experiment-lab/datasets/rf-experiment-dataset-v1/preview',
  RF_EXPERIMENT_DATASET_V1_EXPORT: '/api/rf-experiment-lab/datasets/rf-experiment-dataset-v1/export',
  RF_EXPERIMENT_EXTERNAL_DATASET_PREVIEW: '/api/rf-experiment-lab/datasets/external/preview',
  RF_EXPERIMENT_EXTERNAL_DATASET_IMPORT: '/api/rf-experiment-lab/datasets/external/import',
  RF_EXPERIMENT_EXPERIMENTS: '/api/rf-experiment-lab/experiments',
  RF_EXPERIMENT_COMPARE: '/api/rf-experiment-lab/experiments/compare',
  RF_EXPERIMENT_BENCHMARK_REPORT: '/api/rf-experiment-lab/benchmark/report',
  RF_EXPERIMENT_E5_PREVIEW: '/api/rf-experiment-lab/experiments/e5-spectral-baseline/preview',
  RF_EXPERIMENT_E5_RUN: '/api/rf-experiment-lab/experiments/e5-spectral-baseline/run',
  RF_EXPERIMENT_E1_PREVIEW: '/api/rf-experiment-lab/experiments/e1-raw-iq-cnn1d/preview',
  RF_EXPERIMENT_E1_RUN: '/api/rf-experiment-lab/experiments/e1-raw-iq-cnn1d/run',
  RF_EXPERIMENT_E3_PREVIEW: '/api/rf-experiment-lab/experiments/e3-spectrogram-cnn2d/preview',
  RF_EXPERIMENT_E3_RUN: '/api/rf-experiment-lab/experiments/e3-spectrogram-cnn2d/run',
  RF_EXPERIMENT_INFERENCE_PREDICT: '/api/rf-experiment-lab/inference/predict',
  RF_EXPERIMENT_INFERENCE_COMPARE_REGION: '/api/rf-experiment-lab/inference/compare-region',
  RF_EXPERIMENT_MODEL_REGISTRY: '/api/rf-experiment-lab/models/registry',
  RF_EXPERIMENT_LIVE_INFERENCE: '/api/rf-experiment-lab/models/live-inference',
  RF_EXPERIMENT_SIGMF_PREVIEW: '/api/rf-experiment-lab/sigmf/preview',
  RF_EXPERIMENT_SIGMF_EXPORT: '/api/rf-experiment-lab/sigmf/export',
  RF_EXPERIMENT_HDF5_MANIFEST_PREVIEW: '/api/rf-experiment-lab/hdf5-manifest/preview',
  RF_EXPERIMENT_HDF5_MANIFEST_EXPORT: '/api/rf-experiment-lab/hdf5-manifest/export',
  RF_EXPERIMENT_REPRESENTATION_EXPORT: (kind: string) => `/api/rf-experiment-lab/representations/${kind}/export`,
  RF_EXPERIMENT_REPRESENTATION_MANIFEST_EXPORT: '/api/rf-experiment-lab/representations/manifest/export',

  // E6 Oracle-style classical RF fingerprinting
  E6_MODELS: '/api/e6/models',
  E6_MODELS_LIVE_READY: '/api/e6/models/live-ready',
  E6_PREDICT_LIVE_SPECTRUM: '/api/e6/predict-live-spectrum',

  // Markers
  MARKERS_LIST: '/api/markers/',
  MARKERS_CREATE: '/api/markers/',
  MARKERS_DELETE: (id: string) => `/api/markers/${id}`,

  // Recording
  RECORDINGS_LIST: '/api/recordings/',
  RECORDINGS_START: '/api/recordings/start',
  RECORDINGS_STOP: '/api/recordings/stop',

  // Demodulation
  DEMODULATION_START: '/api/demodulation/start',
  DEMODULATION_STOP: '/api/demodulation/stop',
  DEMODULATION_AUDIO_STATUS: '/api/demodulation/audio/status',
  DEMODULATION_MARKER_BAND: '/api/demodulation/marker-band',
  DEMODULATION_DATASET_CAPTURE: '/api/demodulation/dataset-capture',
  DEMODULATION_WIFI_JOB_START: '/api/demodulation/dataset-capture/wifi-job',
  DEMODULATION_WIFI_JOB_STATUS: (jobId: string) => `/api/demodulation/dataset-capture/wifi-job/${jobId}`,
  DEMODULATION_PIPELINES: '/api/demodulation/pipelines',
  DEMODULATION_WIFI_CHANNELS: '/api/demodulation/wifi-80211/channels',
  DEMODULATION_BLE_TEST_CHANNELS: '/api/demodulation/ble-advertising/test-channels',
  DEMODULATION_WIFI_5GHZ_TEST_CHANNELS: '/api/demodulation/wifi-80211/5ghz/test-channels',
  DEMODULATION_RESULTS: '/api/demodulation/results',
  DEMODULATION_RESULT: (id: string) => `/api/demodulation/results/${id}`,
  DEMODULATION_AUDIO: (id: string) => `/api/demodulation/audio/${id}`,
  DEMODULATION_OUTPUT: (id: string, filename: string) => `/api/demodulation/outputs/${id}/${filename}`,

  // Modulated signal analysis captures
  MODULATED_SIGNAL_CAPTURES: '/api/modulated-signals/captures',
  MODULATED_SIGNAL_CAPTURE: (id: string) => `/api/modulated-signals/captures/${id}`,
  MODULATED_SIGNAL_IQ: (id: string) => `/api/modulated-signals/captures/${id}/iq`,
  MODULATED_SIGNAL_METADATA: (id: string) => `/api/modulated-signals/captures/${id}/metadata`,

  // Fingerprinting
  FINGERPRINTING_DASHBOARD: '/api/fingerprinting/dashboard',
  FINGERPRINTING_CAPTURES: '/api/fingerprinting/captures',
  FINGERPRINTING_CAPTURE: (id: string) => `/api/fingerprinting/captures/${id}`,
  FINGERPRINTING_CAPTURE_DELETE: (id: string) => `/api/fingerprinting/captures/${id}`,
  FINGERPRINTING_CAPTURE_REVIEW: (id: string) => `/api/fingerprinting/captures/${id}/review`,
  FINGERPRINTING_CAPTURE_RECOMPUTE_QC: (id: string) => `/api/fingerprinting/captures/${id}/recompute-qc`,
  FINGERPRINTING_CAPTURE_APPLY_BAND_PROFILE: (id: string) => `/api/fingerprinting/captures/${id}/apply-band-profile`,
  FINGERPRINTING_IMPORT_MODULATED: (id: string) => `/api/fingerprinting/imports/modulated-signals/${id}`,

  // MLOps
  TRAINING_DASHBOARD: '/api/training/dashboard',
  TRAINING_MODELS: '/api/training/models',
  TRAINING_START: '/api/training/start',
  TRAINING_RETRAIN: '/api/training/retrain',
  TRAINING_STATUS: '/api/training/status',
  VALIDATION_RUN: '/api/validation/run',
  VALIDATION_START: '/api/validation/start',
  VALIDATION_STATUS: '/api/validation/status',
  VALIDATION_REPORTS: '/api/validation/reports',
  INFERENCE_CLASSIFY: '/api/inference/classify',
  INFERENCE_VERIFY: '/api/inference/verify',
  INFERENCE_PREDICT_CAPTURES: '/api/inference/predict/captures',
  INFERENCE_PREDICT_START: '/api/inference/predict/start',
  INFERENCE_PREDICT_STATUS: '/api/inference/predict/status',
  MODELS_OVERVIEW: '/api/models/overview',
  MODELS_CURRENT: '/api/models/current',
  MODELS_BY_VERSION: (version: string) => `/api/models/${version}`,

  // Presets
  PRESETS_LIST: '/api/presets/',
  PRESETS_CREATE: '/api/presets/',
  PRESETS_LOAD: (id: string) => `/api/presets/${id}`,
  PRESETS_DELETE: (id: string) => `/api/presets/${id}`,

  // Sessions
  SESSIONS_LIST: '/api/sessions/',
  SESSIONS_CREATE: '/api/sessions/',
} as const;

