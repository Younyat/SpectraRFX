import axios from 'axios';
import {
  SpectrumData,
  WaterfallData,
  Marker,
  DeviceStatus,
  AnalyzerSettings,
  Recording,
  Session,
  Preset,
  DemodulationResult,
  ModulatedSignalCapture,
  FingerprintingDashboardSummary,
  FingerprintingCaptureRecord,
  TrainingDashboard,
  AsyncJobStatus,
  ModelArtifactSummary,
  RFSceneAnalysis,
  RFSignalUnderstandingComparison,
  RFSignalUnderstandingResult,
} from '../../shared/types';
import { API_ENDPOINTS } from '../../shared/constants';

const toDeviceStatus = (data: any): DeviceStatus => ({
  isConnected: Boolean(data.isConnected ?? data.is_connected ?? data.is_streaming ?? data.status === 'streaming'),
  driver: data.driver ?? 'uhd_gnuradio',
  centerFrequency: data.centerFrequency ?? data.center_frequency_hz ?? data.frequency_hz ?? 0,
  sampleRate: data.sampleRate ?? data.sample_rate_hz ?? 0,
  gain: data.gain ?? data.gain_db ?? 0,
  antenna: data.antenna,
  lastError: data.lastError ?? data.last_error ?? null,
});

const toSpectrumData = (data: any): SpectrumData => ({
  timestamp: data.timestamp ?? (data.timestamp_utc ? Date.parse(data.timestamp_utc) : Date.now()),
  centerFrequency: data.centerFrequency ?? data.center_frequency_hz ?? 0,
  span: data.span ?? data.span_hz ?? 0,
  frequencyArray: data.source === 'real_sdr_error' ? [] : (data.frequencyArray ?? data.frequencies_hz ?? []),
  powerLevels: data.source === 'real_sdr_error' ? [] : (data.powerLevels ?? data.levels_db ?? []),
  sampleRateHz: data.sampleRateHz ?? data.sample_rate_hz,
  fftSize: data.fftSize ?? data.fft_size ?? data.points,
  requestedRbwHz: data.requestedRbwHz ?? data.requested_rbw_hz,
  effectiveRbwHz: data.effectiveRbwHz ?? data.effective_rbw_hz,
  powerUnit: data.powerUnit ?? data.power_unit ?? 'dBFS',
  sourceId: data.sourceId ?? data.source,
  deviceSerial: data.deviceSerial ?? data.device_serial,
  calibrationId: data.calibrationId ?? data.calibration_id,
});

const toWaterfallData = (data: any): WaterfallData => {
  const levels = data.source === 'real_sdr_error' ? [] : (data.levels_db ?? data.powerLevels ?? []);
  const rows = data.data && data.data.length > 0 ? data.data : (levels.length > 0 ? [levels] : []);

  return {
    timestamp: data.timestamp ?? (data.timestamp_utc ? Date.parse(data.timestamp_utc) : Date.now()),
    centerFrequency: data.centerFrequency ?? data.center_frequency_hz ?? 0,
    span: data.span ?? data.span_hz ?? 0,
    data: rows,
  };
};

const toMarker = (data: any): Marker => ({
  id: data.id ?? data.marker_id ?? '',
  label: data.label ?? 'Marker',
  frequency: data.frequency ?? data.frequency_hz ?? 0,
  level: data.level ?? data.level_db ?? 0,
  type: data.type ?? data.marker_type ?? 'normal',
  enabled: data.enabled ?? true,
});

const toRecording = (data: any): Recording => ({
  id: data.id ?? data.recording_id ?? data.capture_id ?? '',
  sessionId: data.sessionId ?? data.session_id ?? '',
  timestamp: data.timestamp ?? (data.timestamp_utc ? Date.parse(data.timestamp_utc) : Date.now()),
  duration: data.duration ?? data.duration_seconds ?? 0,
  filePath: data.filePath ?? data.file_path ?? data.filename ?? '',
  size: data.size ?? data.file_size_bytes ?? 0,
  type: data.type ?? data.format ?? 'iq',
});

const toSession = (data: any): Session => ({
  id: data.id ?? data.session_id ?? '',
  name: data.name ?? 'Session',
  createdAt: data.createdAt ?? (data.created_utc ? Date.parse(data.created_utc) : Date.now()),
  recordings: data.recordings ?? [],
  notes: data.notes ?? data.description,
});

const toPreset = (data: any): Preset => ({
  id: data.id ?? data.preset_id ?? '',
  name: data.name ?? 'Preset',
  settings: data.settings ?? data.config ?? {
    centerFrequency: 100000000,
    span: 2000000,
    sampleRate: 4000000,
    rbw: 10000,
    vbw: 3000,
    referenceLevel: 10,
    noiseFloorOffset: 0,
    detectorMode: 'sample',
    traceMode: 'clear_write',
    dbPerDiv: 10,
    colorScheme: 'blue',
    averaging: 1,
    smoothing: 0,
  },
  createdAt: data.createdAt ?? Date.now(),
});

export class ApiService {
  private baseURL = 'http://localhost:8000';

  constructor(baseURL?: string) {
    if (baseURL) {
      this.baseURL = baseURL;
    }
  }

  // Device endpoints
  async getDeviceStatus(): Promise<DeviceStatus> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEVICE_STATUS}`);
    return toDeviceStatus(response.data);
  }

  async connectDevice(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_CONNECT}`);
    return toDeviceStatus(response.data);
  }

  async disconnectDevice(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_DISCONNECT}`);
    return toDeviceStatus(response.data);
  }

  async openWfmReceiver(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_OPEN_RECEIVER}`);
    return toDeviceStatus(response.data);
  }

  async closeWfmReceiver(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_CLOSE_RECEIVER}`);
    return toDeviceStatus(response.data);
  }

  async startDeviceStream(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_START_STREAM}`);
  }

  async stopDeviceStream(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_STOP_STREAM}`);
  }

  async getRuntimeSettings(): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RUNTIME_SETTINGS}`);
    return response.data;
  }

  async saveRuntimeSettings(values: Record<string, unknown>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RUNTIME_SETTINGS}`, { values });
    return response.data;
  }

  async setDeviceFrequency(frequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_SET_FREQUENCY}`, { frequency_hz: frequency });
  }

  async setDeviceGain(gain: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_SET_GAIN}`, { gain_db: gain });
  }

  async setDeviceSampleRate(sampleRate: number): Promise<{ sample_rate_hz: number; span_hz?: number }> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_SET_SAMPLE_RATE}`, { sample_rate_hz: sampleRate });
    return response.data;
  }

  // Spectrum endpoints
  async getLiveSpectrum(signal?: AbortSignal): Promise<SpectrumData> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_LIVE}`, { signal });
    return toSpectrumData(response.data);
  }

  async setSpectrumCenterFrequency(frequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_CENTER}`, { center_frequency_hz: frequency });
  }

  async setSpectrumSpan(span: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_SPAN}`, { span_hz: span });
  }

  async setSpectrumStartStop(startFrequency: number, stopFrequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_START_STOP}`, {
      start_frequency_hz: startFrequency,
      stop_frequency_hz: stopFrequency,
    });
  }

  async setSpectrumRbw(rbw: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_RBW}`, { rbw_hz: rbw });
  }

  async setSpectrumVbw(vbw: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_VBW}`, { vbw_hz: vbw });
  }

  async setSpectrumReferenceLevel(level: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_REFERENCE_LEVEL}`, { reference_level_db: level });
  }

  async setSpectrumNoiseFloorOffset(offset: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_NOISE_FLOOR}`, { offset_db: offset });
  }

  async setSpectrumDetectorMode(mode: string): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_DETECTOR}`, { mode });
  }

  async setSpectrumAveraging(count: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_AVERAGING}`, { count });
  }

  // Waterfall endpoints
  async getLiveWaterfall(): Promise<WaterfallData> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.WATERFALL_LIVE}`);
    return toWaterfallData(response.data);
  }

  async getLiveRFScene(params?: {
    thresholdOffsetDb?: number;
    minSnrDb?: number;
    minBins?: number;
    mergeGapBins?: number;
  }): Promise<RFSceneAnalysis> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_INTELLIGENCE_LIVE}`, {
      params: {
        threshold_offset_db: params?.thresholdOffsetDb,
        min_snr_db: params?.minSnrDb,
        min_bins: params?.minBins,
        merge_gap_bins: params?.mergeGapBins,
      },
    });
    return response.data;
  }

  async analyzeRFScene(frame: SpectrumData, params?: {
    thresholdOffsetDb?: number;
    minSnrDb?: number;
    minBins?: number;
    mergeGapBins?: number;
  }): Promise<RFSceneAnalysis> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_INTELLIGENCE_ANALYZE}`, {
      frame: {
        timestamp_utc: new Date(frame.timestamp).toISOString(),
        center_frequency_hz: frame.centerFrequency,
        span_hz: frame.span,
        start_frequency_hz: frame.centerFrequency - frame.span / 2,
        stop_frequency_hz: frame.centerFrequency + frame.span / 2,
        sample_rate_hz: frame.span,
        frequencies_hz: frame.frequencyArray,
        levels_db: frame.powerLevels,
      },
      settings: {
        threshold_offset_db: params?.thresholdOffsetDb ?? 10,
        min_snr_db: params?.minSnrDb ?? 6,
        min_bins: params?.minBins ?? 2,
        merge_gap_bins: params?.mergeGapBins ?? 2,
      },
    });
    return response.data;
  }

  async resolveRFIntelligenceBandProfile(payload: {
    start_frequency_hz?: number;
    stop_frequency_hz?: number;
    center_frequency_hz?: number;
    bandwidth_hz?: number;
    occupied_bandwidth_hz?: number;
  }): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_INTELLIGENCE_BAND_PROFILE_RESOLVE}`, payload);
    return response.data;
  }

  async analyzeRFSignalUnderstanding(payload: {
    file_path: string;
    sample_rate_hz: number;
    center_frequency_hz: number;
    format?: string;
    n_fft?: number;
    hop_length?: number;
    window?: string;
  }): Promise<RFSignalUnderstandingResult> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_ANALYZE}`, payload);
    return response.data;
  }

  async getLiveRFSignalUnderstanding(params?: { start_frequency_hz?: number; stop_frequency_hz?: number; decision_mode?: 'hybrid' | 'ai_only' }): Promise<RFSignalUnderstandingResult> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_LIVE}`, { params });
    return response.data;
  }

  async analyzeRFSignalUnderstandingFrame(frame: SpectrumData, params?: { decision_mode?: 'hybrid' | 'ai_only' }): Promise<RFSignalUnderstandingResult> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_ANALYZE_FRAME}`, {
      frame: {
        timestamp_utc: new Date(frame.timestamp).toISOString(),
        center_frequency_hz: frame.centerFrequency,
        span_hz: frame.span,
        start_frequency_hz: frame.centerFrequency - frame.span / 2,
        stop_frequency_hz: frame.centerFrequency + frame.span / 2,
        sample_rate_hz: frame.span,
        frequencies_hz: frame.frequencyArray,
        levels_db: frame.powerLevels,
      },
    }, { params });
    return response.data;
  }

  async compareLiveRFSignalUnderstanding(params?: { start_frequency_hz?: number; stop_frequency_hz?: number; decision_mode?: 'hybrid' | 'ai_only' }): Promise<RFSignalUnderstandingComparison> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_COMPARE_LIVE}`, null, { params });
    return response.data;
  }

  async compareRFSignalUnderstanding(payload: {
    file_path: string;
    sample_rate_hz: number;
    center_frequency_hz: number;
    format?: string;
    n_fft?: number;
    hop_length?: number;
    window?: string;
    legacy_frame?: Record<string, unknown>;
  }): Promise<RFSignalUnderstandingComparison> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_COMPARE}`, payload);
    return response.data;
  }

  async getRFSignalUnderstandingReferences(): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_REFERENCES}`);
    return response.data;
  }

  async getRFSignalUnderstandingModels(): Promise<Array<Record<string, any>>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_MODELS}`);
    return Array.isArray(response.data) ? response.data : response.data.models ?? [];
  }

  async reviewRFSignalRegion(payload: {
    analysis_id: string;
    bbox_id: string;
    label: string;
    review_status: string;
    reviewer?: string;
    notes?: string;
    send_to_training_buffer?: boolean;
    legacy_label?: string | null;
  }): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_REVIEW_REGION}`, payload);
    return response.data;
  }

  async pseudoLabelRFSignalRegion(payload: {
    analysis_id: string;
    bbox_id: string;
    legacy_label: string;
    legacy_family?: string | null;
    legacy_confidence: number;
    training_weight?: number;
    center_frequency_hz?: number;
    occupied_bandwidth_hz?: number;
    snr_db?: number;
  }): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_PSEUDO_LABEL}`, payload);
    return response.data;
  }

  async captureRFSignalForTraining(payload: {
    start_frequency_hz: number;
    stop_frequency_hz: number;
    duration_seconds: number;
    label_hint?: string;
    session_id?: string;
    file_format?: 'iq' | 'cfile';
    gain_db?: number;
    profile_key?: string;
    profile?: Record<string, unknown>;
    apply_bandpass_filter?: boolean;
    filter_stopband_attenuation_db?: number;
    filter_transition_width_hz?: number | null;
    live_preview_snr_db?: number | null;
    live_preview_noise_floor_db?: number | null;
    live_preview_peak_level_db?: number | null;
    live_preview_peak_frequency_hz?: number | null;
    transmitter_id?: string;
    transmitter_class?: string;
    operator?: string;
    environment?: string;
  }): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_CAPTURE_FOR_TRAINING}`, payload);
    return response.data;
  }

  async getRFSignalCaptureRegistry(): Promise<{ captures: Array<Record<string, any>> }> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_CAPTURE_REGISTRY}`);
    return response.data;
  }

  async registerRFSignalUnderstandingCapture(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_REGISTER_CAPTURE}`, payload);
    return response.data;
  }

  async analyzeRegisteredRFSignalCapture(id: string): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_ANALYZE_REGISTERED_CAPTURE(id)}`);
    return response.data;
  }

  async deleteRegisteredRFSignalCapture(id: string): Promise<Record<string, any>> {
    const response = await axios.delete(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_DELETE_REGISTERED_CAPTURE(id)}`);
    return response.data;
  }

  async getRFSignalTrainingQueue(): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_TRAINING_QUEUE}`);
    return response.data;
  }

  async trainRFSignalClassifierIncremental(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_SIGNAL_UNDERSTANDING_TRAIN_INCREMENTAL}`, payload);
    return response.data;
  }

  async getRFExperimentLabHealth(): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_HEALTH}`);
    return response.data;
  }

  async getRFExperimentCaptures(): Promise<Array<Record<string, any>>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_DATASET_CAPTURES}`);
    return response.data?.data ?? response.data?.captures ?? [];
  }

  async getRFExperimentDatasetSources(): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_DATASET_SOURCES}`);
    return response.data?.data ?? response.data;
  }

  async getRFExperimentInternalSamples(): Promise<Array<Record<string, any>>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_INTERNAL_SAMPLES}`);
    return response.data?.data ?? [];
  }

  async createRFExperimentInternalSample(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_INTERNAL_SAMPLES}`, payload);
    return response.data;
  }

  async reviewRFExperimentInternalSample(sampleId: string, payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_INTERNAL_SAMPLE_REVIEW(sampleId)}`, payload);
    return response.data;
  }

  async previewRFExperimentDatasetV1(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_DATASET_V1_PREVIEW}`, payload);
    return response.data;
  }

  async exportRFExperimentDatasetV1(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_DATASET_V1_EXPORT}`, payload);
    return response.data;
  }

  async previewExternalRFExperimentDataset(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_EXTERNAL_DATASET_PREVIEW}`, payload);
    return response.data;
  }

  async importExternalRFExperimentDataset(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_EXTERNAL_DATASET_IMPORT}`, payload);
    return response.data;
  }

  async listRFExperimentRuns(): Promise<Array<Record<string, any>>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_EXPERIMENTS}`);
    return response.data?.data ?? [];
  }

  async getModelRegistry(): Promise<Array<Record<string, any>>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_MODEL_REGISTRY}`);
    return response.data?.data ?? [];
  }

  async runLiveInference(body: {
    model_id: string;
    experiment_type?: string;
    live_context: {
      frequency_array_hz: number[];
      power_levels_db: number[];
      center_frequency_hz: number;
      marker_start_hz?: number;
      marker_stop_hz?: number;
    };
  }): Promise<Record<string, any> | null> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_LIVE_INFERENCE}`, body);
    return response.data?.data ?? null;
  }

  async getE6LiveReadyModels(): Promise<Array<Record<string, any>>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.E6_MODELS_LIVE_READY}`);
    if (response.data?.status === 'error') {
      throw new Error(response.data?.message || 'E6 live-ready model list failed');
    }
    return response.data?.data ?? [];
  }

  async predictE6LiveSpectrum(body: {
    model_id: string;
    frequency_array_hz: number[];
    power_levels_db: number[];
    marker_start_hz?: number;
    marker_stop_hz?: number;
    top_k?: number;
  }): Promise<Record<string, any> | null> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.E6_PREDICT_LIVE_SPECTRUM}`, body);
    if (response.data?.status === 'error') {
      throw new Error(response.data?.message || 'E6 live spectrum prediction failed');
    }
    return response.data?.data ?? null;
  }

  async getRFExperimentRun(experimentId: string): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_EXPERIMENTS}/${encodeURIComponent(experimentId)}`);
    return response.data?.data ?? response.data;
  }

  async previewRFExperiment(kind: 'e5' | 'e1' | 'e3', payload: Record<string, any>): Promise<Record<string, any>> {
    const endpoint =
      kind === 'e5'
        ? API_ENDPOINTS.RF_EXPERIMENT_E5_PREVIEW
        : kind === 'e1'
          ? API_ENDPOINTS.RF_EXPERIMENT_E1_PREVIEW
          : API_ENDPOINTS.RF_EXPERIMENT_E3_PREVIEW;
    const response = await axios.post(`${this.baseURL}${endpoint}`, payload);
    return response.data;
  }

  async runRFExperiment(kind: 'e5' | 'e1' | 'e3', payload: Record<string, any>): Promise<Record<string, any>> {
    const endpoint =
      kind === 'e5'
        ? API_ENDPOINTS.RF_EXPERIMENT_E5_RUN
        : kind === 'e1'
          ? API_ENDPOINTS.RF_EXPERIMENT_E1_RUN
          : API_ENDPOINTS.RF_EXPERIMENT_E3_RUN;
    const response = await axios.post(`${this.baseURL}${endpoint}`, payload);
    return response.data;
  }

  async createRFExperimentBenchmark(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_BENCHMARK_REPORT}`, payload);
    return response.data;
  }

  async predictRFExperiment(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_INFERENCE_PREDICT}`, payload);
    return response.data;
  }

  async compareRFExperimentRegion(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_INFERENCE_COMPARE_REGION}`, payload);
    return response.data;
  }

  async previewRFExperimentSigMF(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_SIGMF_PREVIEW}`, payload);
    return response.data;
  }

  async exportRFExperimentSigMF(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_SIGMF_EXPORT}`, payload);
    return response.data;
  }

  async previewRFExperimentHDF5Manifest(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_HDF5_MANIFEST_PREVIEW}`, payload);
    return response.data;
  }

  async exportRFExperimentHDF5Manifest(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_HDF5_MANIFEST_EXPORT}`, payload);
    return response.data;
  }

  async exportRFExperimentRepresentation(kind: 'raw-iq' | 'fft-psd' | 'spectrogram' | 'waterfall', payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_REPRESENTATION_EXPORT(kind)}`, payload);
    return response.data;
  }

  async exportRFExperimentRepresentationManifest(payload: Record<string, any>): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RF_EXPERIMENT_REPRESENTATION_MANIFEST_EXPORT}`, payload);
    return response.data;
  }

  // Marker endpoints
  async getMarkers(): Promise<Marker[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.MARKERS_LIST}`);
    const markers = Array.isArray(response.data) ? response.data : response.data.markers ?? [];
    return markers.map(toMarker);
  }

  async createMarker(marker: Omit<Marker, 'id'>): Promise<Marker> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.MARKERS_CREATE}`, marker);
    return toMarker(response.data);
  }

  async deleteMarker(id: string): Promise<void> {
    await axios.delete(`${this.baseURL}${API_ENDPOINTS.MARKERS_DELETE(id)}`);
  }

  // Recording endpoints
  async getRecordings(): Promise<Recording[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RECORDINGS_LIST}`);
    return (Array.isArray(response.data) ? response.data : response.data.recordings ?? []).map(toRecording);
  }

  async startRecording(type: 'iq' | 'audio', duration?: number): Promise<Recording> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RECORDINGS_START}`, {
      type,
      duration_seconds: duration,
    });
    return toRecording(response.data);
  }

  async stopRecording(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.RECORDINGS_STOP}`);
  }

  // Demodulation endpoints
  async startDemodulation(mode: string, frequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_START}`, {
      mode,
      frequency_hz: frequency,
    });
  }

  async stopDemodulation(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_STOP}`);
  }

  async getDemodulationAudioStatus(): Promise<{ is_active: boolean; mode: string }> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_AUDIO_STATUS}`);
    return response.data;
  }

  async demodulateMarkerBand(request: {
    startFrequencyHz: number;
    stopFrequencyHz: number;
    mode: string;
    durationSeconds: number;
    applyBandpassFilter?: boolean;
    filterStopbandAttenuationDb?: number;
    filterTransitionWidthHz?: number | null;
  }): Promise<DemodulationResult> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_MARKER_BAND}`, {
      start_frequency_hz: request.startFrequencyHz,
      stop_frequency_hz: request.stopFrequencyHz,
      mode: request.mode,
      duration_seconds: request.durationSeconds,
      apply_bandpass_filter: request.applyBandpassFilter,
      filter_stopband_attenuation_db: request.filterStopbandAttenuationDb,
      filter_transition_width_hz: request.filterTransitionWidthHz,
    });
    return response.data;
  }

  async getDemodulationPipelines(): Promise<Record<string, any>[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_PIPELINES}`);
    return Array.isArray(response.data) ? response.data : response.data.pipelines ?? [];
  }

  async getWifi80211Channels(): Promise<{
    channels_24ghz: { channel: number; frequency_hz: number }[];
    channels_5ghz: { channel: number; frequency_hz: number }[];
  }> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_WIFI_CHANNELS}`);
    return response.data;
  }

  async testBleAdvertisingChannels(payload: {
    durationSeconds: number;
    sampleRateHz?: number;
    bandwidthHz?: number;
  }): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_BLE_TEST_CHANNELS}`, {
      duration_seconds: payload.durationSeconds,
      sample_rate_hz: payload.sampleRateHz,
      bandwidth_hz: payload.bandwidthHz,
    });
    return response.data;
  }

  async testWifi5GhzChannels(payload: {
    durationSeconds: number;
    bandwidthHz?: number;
  }): Promise<Record<string, any>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_WIFI_5GHZ_TEST_CHANNELS}`, {
      duration_seconds: payload.durationSeconds,
      bandwidth_hz: payload.bandwidthHz,
    });
    return response.data;
  }

  async demodulateDatasetCapture(payload: Record<string, unknown>): Promise<DemodulationResult> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_DATASET_CAPTURE}`, payload);
    return response.data;
  }

  async startWifiDemodulationJob(payload: Record<string, unknown>): Promise<{ job_id: string }> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_WIFI_JOB_START}`, payload);
    return response.data;
  }

  async getWifiDemodulationJobStatus(jobId: string): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_WIFI_JOB_STATUS(jobId)}`);
    return response.data;
  }

  async getDemodulationResults(): Promise<DemodulationResult[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_RESULTS}`);
    return Array.isArray(response.data) ? response.data : response.data.results ?? [];
  }

  async deleteDemodulationResult(id: string): Promise<Record<string, any>> {
    const response = await axios.delete(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_RESULT(id)}`);
    return response.data;
  }

  getDemodulationAudioUrl(id: string): string {
    return `${this.baseURL}${API_ENDPOINTS.DEMODULATION_AUDIO(id)}`;
  }

  getDemodulationOutputUrl(id: string, filename: string): string {
    return `${this.baseURL}${API_ENDPOINTS.DEMODULATION_OUTPUT(id, filename)}`;
  }

  async getDemodulationOutputJson(id: string, filename: string): Promise<Record<string, any>> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_OUTPUT(id, filename)}`);
    return response.data;
  }

  // Modulated signal analysis capture endpoints
  async captureModulatedSignal(request: {
    startFrequencyHz: number;
    stopFrequencyHz: number;
    durationSeconds: number;
    label: string;
    modulationHint: string;
    notes: string;
    datasetSplit: 'train' | 'val' | 'predict';
    sessionId: string;
    transmitterId: string;
    transmitterClass: string;
    operator: string;
    environment: string;
    fileFormat: 'cfile' | 'iq';
    livePreviewSnrDb?: number;
    livePreviewNoiseFloorDb?: number;
    livePreviewPeakLevelDb?: number;
    livePreviewPeakFrequencyHz?: number;
    captureMode: 'immediate' | 'triggered_burst';
    // Triggered capture params
    triggerStrategy?: 'adaptive_energy_trigger' | 'smart_burst_trigger';
    triggerThresholdDb?: number;
    preTriggerMs?: number;
    postTriggerMs?: number;
    minEventDurationMs?: number;
    maxEventDurationMs?: number;
    cooldownMs?: number;
    triggerMaxWaitSeconds?: number;
    captureRepetitions?: number;
    minValidEvents?: number;
    smartPersistenceMs?: number;
    autoQcEnabled?: boolean;
    targetTask?: 'device_fingerprinting' | 'signal_recognition';
    signalType?: string;
  }): Promise<ModulatedSignalCapture> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_CAPTURES}`, {
      start_frequency_hz: request.startFrequencyHz,
      stop_frequency_hz: request.stopFrequencyHz,
      duration_seconds: request.durationSeconds,
      label: request.label,
      modulation_hint: request.modulationHint,
      notes: request.notes,
      dataset_split: request.datasetSplit,
      session_id: request.sessionId,
      transmitter_id: request.transmitterId,
      transmitter_class: request.transmitterClass,
      operator: request.operator,
      environment: request.environment,
      file_format: request.fileFormat,
      live_preview_snr_db: request.livePreviewSnrDb,
      live_preview_noise_floor_db: request.livePreviewNoiseFloorDb,
      live_preview_peak_level_db: request.livePreviewPeakLevelDb,
      live_preview_peak_frequency_hz: request.livePreviewPeakFrequencyHz,
      capture_mode: request.captureMode,
      trigger_strategy: request.triggerStrategy,
      trigger_threshold_db: request.triggerThresholdDb,
      pre_trigger_ms: request.preTriggerMs,
      post_trigger_ms: request.postTriggerMs,
      min_event_duration_ms: request.minEventDurationMs,
      max_event_duration_ms: request.maxEventDurationMs,
      cooldown_ms: request.cooldownMs,
      trigger_max_wait_s: request.triggerMaxWaitSeconds,
      capture_repetitions: request.captureRepetitions,
      min_valid_events: request.minValidEvents,
      smart_persistence_ms: request.smartPersistenceMs,
      auto_qc_enabled: request.autoQcEnabled,
      target_task: request.targetTask,
      signal_type: request.signalType,
    });
    return response.data;
  }

  async getModulatedSignalCaptures(): Promise<ModulatedSignalCapture[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_CAPTURES}`);
    return Array.isArray(response.data) ? response.data : response.data.captures ?? [];
  }

  async deleteModulatedSignalCapture(
    id: string,
  ): Promise<{
    capture_id: string;
    deleted: boolean;
    deleted_files: string[];
    skipped_external_files?: string[];
    deleted_registry_records: string[];
  }> {
    const response = await axios.delete(`${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_CAPTURE(id)}`);
    return response.data;
  }

  getModulatedSignalIqUrl(id: string): string {
    return `${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_IQ(id)}`;
  }

  getModulatedSignalMetadataUrl(id: string): string {
    return `${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_METADATA(id)}`;
  }

  async getFingerprintingDashboard(): Promise<FingerprintingDashboardSummary> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_DASHBOARD}`);
    return response.data;
  }

  async getFingerprintingCaptures(datasetSplit?: 'train' | 'val' | 'predict'): Promise<FingerprintingCaptureRecord[]> {
    const suffix = datasetSplit ? `?dataset_split=${encodeURIComponent(datasetSplit)}` : '';
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURES}${suffix}`);
    return Array.isArray(response.data) ? response.data : response.data.captures ?? [];
  }

  async getFingerprintingCapture(captureId: string): Promise<FingerprintingCaptureRecord> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURE(captureId)}`);
    return response.data;
  }

  async createFingerprintingCapture(payload: unknown): Promise<FingerprintingCaptureRecord> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURES}`, payload);
    return response.data;
  }

  async reviewFingerprintingCapture(
    captureId: string,
    payload: { operator_decision?: string | null; review_notes?: string; export_windows?: string[] },
  ): Promise<FingerprintingCaptureRecord> {
    const response = await axios.post(
      `${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURE_REVIEW(captureId)}`,
      payload,
    );
    return response.data;
  }

  async recomputeFingerprintingCaptureQc(captureId: string): Promise<FingerprintingCaptureRecord> {
    const response = await axios.post(
      `${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURE_RECOMPUTE_QC(captureId)}`,
    );
    return response.data;
  }

  async applyBandProfileToFingerprintingCapture(
    captureId: string,
    payload: { confirm_as_strong_label?: boolean; overwrite_existing?: boolean } = {},
  ): Promise<FingerprintingCaptureRecord> {
    const response = await axios.post(
      `${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURE_APPLY_BAND_PROFILE(captureId)}`,
      payload,
    );
    return response.data;
  }

  async deleteFingerprintingCapture(
    captureId: string,
    payload: { delete_artifacts?: boolean } = {},
  ): Promise<{ capture_id: string; deleted: boolean; deleted_artifacts: string[] }> {
    const response = await axios.delete(
      `${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_CAPTURE_DELETE(captureId)}`,
      { data: payload },
    );
    return response.data;
  }

  async importModulatedCaptureToFingerprinting(
    captureId: string,
    payload: {
      session_id: string;
      dataset_split: string;
      transmitter_label: string;
      transmitter_class: string;
      transmitter_id: string;
      operator: string;
      environment: string;
      notes: string;
      ground_truth_confidence: string;
      family?: string;
      signal_family?: string;
      signal_type?: string;
      modulation_class?: string;
      protocol_family?: string;
      band_label?: string;
      profile_key?: string | null;
      label_status?: string | null;
    },
  ): Promise<FingerprintingCaptureRecord> {
    const response = await axios.post(
      `${this.baseURL}${API_ENDPOINTS.FINGERPRINTING_IMPORT_MODULATED(captureId)}`,
      payload,
    );
    return response.data;
  }

  async getTrainingDashboard(): Promise<TrainingDashboard> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.TRAINING_DASHBOARD}`);
    return response.data;
  }

  async getTrainingModels(): Promise<ModelArtifactSummary[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.TRAINING_MODELS}`);
    return response.data;
  }

  async startTraining(payload: unknown): Promise<AsyncJobStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.TRAINING_START}`, payload);
    return response.data;
  }

  async retrainModel(payload: unknown): Promise<AsyncJobStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.TRAINING_RETRAIN}`, payload);
    return response.data;
  }

  async getTrainingStatus(jobId?: string): Promise<AsyncJobStatus> {
    const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.TRAINING_STATUS}${suffix}`);
    return response.data;
  }

  async runValidation(payload: unknown): Promise<any> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.VALIDATION_RUN}`, payload);
    return response.data;
  }

  async startValidation(payload: unknown): Promise<AsyncJobStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.VALIDATION_START}`, payload);
    return response.data;
  }

  async getValidationStatus(jobId?: string): Promise<AsyncJobStatus> {
    const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.VALIDATION_STATUS}${suffix}`);
    return response.data;
  }

  async getValidationReports(): Promise<Record<string, unknown>[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.VALIDATION_REPORTS}`);
    return response.data;
  }

  async classifyInference(payload: { cfile_path: string }): Promise<Record<string, unknown>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.INFERENCE_CLASSIFY}`, payload);
    return response.data;
  }

  async verifyInference(payload: { cfile_path: string }): Promise<Record<string, unknown>> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.INFERENCE_VERIFY}`, payload);
    return response.data;
  }

  async getPredictionCaptures(): Promise<FingerprintingCaptureRecord[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.INFERENCE_PREDICT_CAPTURES}`);
    return Array.isArray(response.data) ? response.data : response.data.captures ?? [];
  }

  async startPrediction(payload: unknown): Promise<AsyncJobStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.INFERENCE_PREDICT_START}`, payload);
    return response.data;
  }

  async getPredictionStatus(jobId?: string): Promise<AsyncJobStatus> {
    const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.INFERENCE_PREDICT_STATUS}${suffix}`);
    return response.data;
  }

  async getModelOverview(): Promise<TrainingDashboard> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.MODELS_OVERVIEW}`);
    return response.data;
  }

  async getCurrentModel(): Promise<ModelArtifactSummary | null> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.MODELS_CURRENT}`);
    if (response.data?.available === false) return null;
    return response.data;
  }

  // Preset endpoints
  async getPresets(): Promise<Preset[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.PRESETS_LIST}`);
    return (Array.isArray(response.data) ? response.data : response.data.presets ?? []).map(toPreset);
  }

  async createPreset(name: string, settings: AnalyzerSettings): Promise<Preset> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.PRESETS_CREATE}`, {
      name,
      settings,
    });
    return toPreset(response.data);
  }

  async loadPreset(id: string): Promise<Preset> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.PRESETS_LOAD(id)}`);
    return toPreset(response.data);
  }

  async deletePreset(id: string): Promise<void> {
    await axios.delete(`${this.baseURL}${API_ENDPOINTS.PRESETS_DELETE(id)}`);
  }

  // Session endpoints
  async getSessions(): Promise<Session[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.SESSIONS_LIST}`);
    return (Array.isArray(response.data) ? response.data : response.data.sessions ?? []).map(toSession);
  }

  async createSession(name: string): Promise<Session> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.SESSIONS_CREATE}`, { name });
    return toSession(response.data);
  }
}
