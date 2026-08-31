import React, { useEffect, useMemo, useState } from 'react';
import { Beaker, BrainCircuit, FileInput, GitCompare, Microscope, Network, RadioTower, RefreshCw, Save, ScanSearch, Waves } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { useAnalyzerSettings, useDeviceStatus, useMarkers } from '../../app/store/AppStore';
import { RUNTIME_CONFIG } from '../../shared/config/runtime';
import { RF_PROFILE_STORAGE_KEY, RF_PROFILES, type AppliedRFProfile } from '../../shared/rfProfiles';
import type { RFSignalUnderstandingComparison, RFSignalUnderstandingResult } from '../../shared/types';
import { formatFrequency } from '../../shared/utils';

const apiService = new ApiService();

const getErrorMessage = (error: unknown): string => {
  const data = (error as { response?: { data?: { detail?: unknown } } })?.response?.data;
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item) => item?.msg ?? String(item)).join(', ');
  return error instanceof Error ? error.message : 'Request failed';
};

const techniqueRows = [
  ['STFT waterfall generation', 'A Radio Frequency Signal Recognition Method Based on Spectrogram'],
  ['SSD waterfall detection', 'RF Fingerprint Recognition Based on Spectrum Waterfall Diagram'],
  ['MLP over spectrogram rows', 'Simple Detection and Classification of Spectrogram RF Signals Using a Four-Layer Perceptron'],
  ['Bispectrum-waterfall fusion', 'Bispectrum-Based Signal Processing Using Waterfall Features'],
];
const markerBandpassStorageKey = 'spectrum-view-marker-bandpass-settings';

const loadSelectedRFProfile = (): AppliedRFProfile | null => {
  try {
    const raw = window.localStorage.getItem(RF_PROFILE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AppliedRFProfile;
    if (parsed?.selected_profile_key && RF_PROFILES[parsed.selected_profile_key]) return parsed;
  } catch {
    // Ignore invalid persisted profile state.
  }
  return null;
};

const loadMarkerBandpassSettings = () => {
  try {
    const raw = window.localStorage.getItem(markerBandpassStorageKey);
    if (!raw) return { enabled: false, attenuationDb: 60 };
    const parsed = JSON.parse(raw) as { enabled?: boolean; attenuation_db?: number };
    return {
      enabled: Boolean(parsed.enabled),
      attenuationDb: Number.isFinite(parsed.attenuation_db) ? Number(parsed.attenuation_db) : 60,
    };
  } catch {
    return { enabled: false, attenuationDb: 60 };
  }
};

const isTrainableLabel = (label: string) => label !== 'ambiguous' && label !== 'rejected' && label.trim().length > 0;

const suggestTrainingLabel = (region: Record<string, any> | null, labelHint = '') => {
  const hint = labelHint.trim();
  if (hint) return hint;
  const centerHz = region ? (Number(region.freq_start_hz ?? 0) + Number(region.freq_end_hz ?? 0)) / 2 : 0;
  if (centerHz >= 87_500_000 && centerHz <= 108_000_000) return 'fm_broadcast_like';
  const visual = String(region?.classification?.visual_label ?? '');
  if (isTrainableLabel(visual) && visual !== 'unknown') return visual;
  const mlp = String(region?.classification?.mlp_label ?? '');
  if (isTrainableLabel(mlp) && mlp !== 'unknown') return mlp;
  const fused = String(region?.final_decision?.label ?? '');
  if (isTrainableLabel(fused)) return fused;
  return 'unknown';
};

const pickTrainingRegion = (regions: Array<Record<string, any>> = []) => {
  const candidates = regions.filter((region) => region?.bbox_id);
  if (candidates.length === 0) return null;
  return [...candidates].sort((left, right) => {
    const leftLabel = suggestTrainingLabel(left);
    const rightLabel = suggestTrainingLabel(right);
    const leftScore = (isTrainableLabel(leftLabel) ? 1 : 0) + Number(left.final_decision?.confidence ?? left.detector?.confidence ?? 0);
    const rightScore = (isTrainableLabel(rightLabel) ? 1 : 0) + Number(right.final_decision?.confidence ?? right.detector?.confidence ?? 0);
    return rightScore - leftScore;
  })[0];
};

export const RFSignalUnderstandingView: React.FC = () => {
  const [filePath, setFilePath] = useState('');
  const [sampleRateHz, setSampleRateHz] = useState(2_000_000);
  const [centerFrequencyHz, setCenterFrequencyHz] = useState(433_920_000);
  const [result, setResult] = useState<RFSignalUnderstandingResult | null>(null);
  const [comparison, setComparison] = useState<RFSignalUnderstandingComparison | null>(null);
  const [references, setReferences] = useState<Record<string, any> | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [reviewLabel, setReviewLabel] = useState('unknown');
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);
  const [captureDuration, setCaptureDuration] = useState(5);
  const [captureLabelHint, setCaptureLabelHint] = useState('');
  const [selectedRFProfile, setSelectedRFProfile] = useState<AppliedRFProfile | null>(() => loadSelectedRFProfile());
  const [markerBandpass, setMarkerBandpass] = useState(() => loadMarkerBandpassSettings());
  const [captureRegistry, setCaptureRegistry] = useState<Array<Record<string, any>>>([]);
  const [selectedCaptures, setSelectedCaptures] = useState<Set<string>>(new Set());
  const [trainingQueue, setTrainingQueue] = useState<Record<string, any> | null>(null);
  const [trainingResult, setTrainingResult] = useState<Record<string, any> | null>(null);
  const [trainingTarget, setTrainingTarget] = useState<'local' | 'remote'>('local');
  const [remoteTraining, setRemoteTraining] = useState({
    remote_user: RUNTIME_CONFIG.remoteUser,
    remote_host: RUNTIME_CONFIG.remoteHost,
    remote_venv_activate: RUNTIME_CONFIG.remoteVenvActivate,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const settings = useAnalyzerSettings();
  const deviceStatus = useDeviceStatus();
  const markers = useMarkers();

  const firstRegion = result?.regions?.[0] ?? null;
  const selectedTrainingRegion = pickTrainingRegion((result?.regions ?? []) as Array<Record<string, any>>);
  const suggestedTrainingLabel = suggestTrainingLabel((selectedTrainingRegion ?? firstRegion) as Record<string, any> | null, captureLabelHint);
  const finalDecision = firstRegion?.final_decision ?? null;
  const spectral = firstRegion?.features?.spectral ?? {};
  const bispectral = firstRegion?.features?.bispectral ?? {};
  const canTrainSignalType = Boolean(trainingQueue?.ready_for_training_config);
  const trainingNotReadyReason = (trainingQueue?.not_ready_for_training_config_reasons ?? trainingQueue?.not_ready_reasons ?? []).join(' ');
  const bootstrapTraining = Number(trainingQueue?.trainable_iq_samples ?? 0) === 0;
  const effectiveMinSamplesPerClass = 1;
  const markerBand = useMemo(() => {
    if (markers.length < 2) return null;
    const first = markers[0];
    const second = markers[1];
    const start = Math.min(first.frequency, second.frequency);
    const stop = Math.max(first.frequency, second.frequency);
    const bandwidth = stop - start;
    if (!Number.isFinite(start) || !Number.isFinite(stop) || bandwidth <= 0) return null;
    return {
      start,
      stop,
      bandwidth,
      center: start + bandwidth / 2,
      firstLabel: first.label || 'M1',
      secondLabel: second.label || 'M2',
    };
  }, [markers]);
  const activeCenterHz = markerBand?.center ?? settings.centerFrequency;
  const activeSpanHz = markerBand?.bandwidth ?? settings.span;
  const activeSampleRateHz = markerBand?.bandwidth ?? (deviceStatus.sampleRate || settings.span);
  const activeConfigSource = markerBand ? 'Marker 1-2' : 'Spectrum span';
  const liveMarkerParams = markerBand ? { start_frequency_hz: markerBand.start, stop_frequency_hz: markerBand.stop } : undefined;
  const liveInput = (result?.input ?? {}) as Record<string, any>;

  const payload = useMemo(() => ({
    file_path: filePath,
    sample_rate_hz: sampleRateHz,
    center_frequency_hz: centerFrequencyHz,
    format: 'complex64',
    n_fft: 1024,
    hop_length: 256,
    window: 'hann',
  }), [filePath, sampleRateHz, centerFrequencyHz]);

  useEffect(() => {
    setCenterFrequencyHz(Math.round(activeCenterHz));
    setSampleRateHz(Math.round(activeSampleRateHz));
  }, [activeCenterHz, activeSampleRateHz]);

  useEffect(() => {
    const syncProfile = () => {
      const profile = loadSelectedRFProfile();
      setSelectedRFProfile(profile);
      setMarkerBandpass(loadMarkerBandpassSettings());
      if (profile) {
        setCaptureDuration(profile.capture_duration_seconds);
        setCaptureLabelHint((current) => current || profile.signal_type);
      }
    };
    syncProfile();
    window.addEventListener('focus', syncProfile);
    window.addEventListener('storage', syncProfile);
    return () => {
      window.removeEventListener('focus', syncProfile);
      window.removeEventListener('storage', syncProfile);
    };
  }, []);

  useEffect(() => {
    apiService.getRFSignalUnderstandingReferences().then(setReferences).catch(() => setReferences(null));
    refreshLearningLoop();
  }, []);

  const refreshLearningLoop = async () => {
    const [registry, queue] = await Promise.all([
      apiService.getRFSignalCaptureRegistry().catch(() => ({ captures: [] })),
      apiService.getRFSignalTrainingQueue().catch(() => null),
    ]);
    setCaptureRegistry(registry.captures ?? []);
    setTrainingQueue(queue);
  };

  const refreshLive = async () => {
    try {
      setLoading(true);
      setError(null);
      const next = await apiService.getLiveRFSignalUnderstanding(liveMarkerParams);
      setResult(next);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshLive();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(refreshLive, 1500);
    return () => window.clearInterval(timer);
  }, [autoRefresh, liveMarkerParams?.start_frequency_hz, liveMarkerParams?.stop_frequency_hz]);

  const runAnalyze = async () => {
    try {
      setLoading(true);
      setError(null);
      setAutoRefresh(false);
      const next = await apiService.analyzeRFSignalUnderstanding(payload);
      setResult(next);
      setComparison(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const runCompare = async () => {
    try {
      setLoading(true);
      setError(null);
      const next = filePath ? await apiService.compareRFSignalUnderstanding(payload) : await apiService.compareLiveRFSignalUnderstanding(liveMarkerParams);
      setComparison(next);
      if (next.live_result) {
        setResult(next.live_result as RFSignalUnderstandingResult);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setReviewLabel(suggestedTrainingLabel);
  }, [suggestedTrainingLabel]);

  const reviewRegion = async (status: 'confirmed' | 'corrected' | 'unknown' | 'ambiguous') => {
    if (!result?.analysis_id || !firstRegion?.bbox_id) {
      setError('No region is selected for review');
      return;
    }
    const label = status === 'unknown' ? 'unknown' : status === 'ambiguous' ? 'ambiguous' : reviewLabel;
    try {
      setLoading(true);
      const response = await apiService.reviewRFSignalRegion({
        analysis_id: result.analysis_id,
        bbox_id: String(firstRegion.bbox_id),
        label,
        review_status: status,
        reviewer: 'operator',
        notes: 'Reviewed from RF Signal Understanding panel',
        send_to_training_buffer: true,
        legacy_label: comparison?.legacy_rf_intelligence?.label ?? null,
      });
      const sample = response.learning_buffer_sample;
      setReviewStatus(
        sample?.sample_id
          ? `Saved ${sample.sample_id}${sample.iq_path ? ' · trainable I/Q' : ' · live metadata only'}`
          : 'Review saved',
      );
      await refreshLearningLoop();
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const pseudoLabelRegion = async () => {
    if (!result?.analysis_id || !firstRegion?.bbox_id || !comparison?.legacy_rf_intelligence?.label) {
      setError('Run legacy comparison before creating a pseudo-label');
      return;
    }
    try {
      setLoading(true);
      const response = await apiService.pseudoLabelRFSignalRegion({
        analysis_id: result.analysis_id,
        bbox_id: String(firstRegion.bbox_id),
        legacy_label: String(comparison.legacy_rf_intelligence.label),
        legacy_family: comparison.legacy_rf_intelligence.family ?? null,
        legacy_confidence: Number(comparison.legacy_rf_intelligence.confidence ?? 0),
        training_weight: 0.4,
        center_frequency_hz: (Number(firstRegion.freq_start_hz) + Number(firstRegion.freq_end_hz)) / 2,
        occupied_bandwidth_hz: Number(firstRegion.freq_end_hz) - Number(firstRegion.freq_start_hz),
        snr_db: Number(spectral.snr_db ?? 0),
      });
      setReviewStatus(`Pseudo-label ${response.sample?.sample_id ?? 'saved'}`);
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const captureForTraining = async () => {
    try {
      setLoading(true);
      setAutoRefresh(false);
      const startFrequencyHz = markerBand?.start ?? centerFrequencyHz - sampleRateHz / 2;
      const stopFrequencyHz = markerBand?.stop ?? centerFrequencyHz + sampleRateHz / 2;
      const response = await apiService.captureRFSignalForTraining({
        start_frequency_hz: startFrequencyHz,
        stop_frequency_hz: stopFrequencyHz,
        duration_seconds: captureDuration,
        label_hint: captureLabelHint,
        session_id: `session_${new Date().toISOString().slice(0, 10)}`,
        file_format: 'iq',
        gain_db: selectedRFProfile?.recommended_gain_db,
        profile_key: selectedRFProfile?.selected_profile_key,
        profile: selectedRFProfile ?? undefined,
        apply_bandpass_filter: markerBandpass.enabled,
        filter_stopband_attenuation_db: markerBandpass.attenuationDb,
      });
      setResult(response.analysis as RFSignalUnderstandingResult);
      await refreshLearningLoop();
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const captureAndAddTrainingSample = async () => {
    try {
      setLoading(true);
      setAutoRefresh(false);
      setError(null);
      setReviewStatus('Capturing I/Q and preparing a trainable sample...');
      const startFrequencyHz = markerBand?.start ?? centerFrequencyHz - sampleRateHz / 2;
      const stopFrequencyHz = markerBand?.stop ?? centerFrequencyHz + sampleRateHz / 2;
      const captured = await apiService.captureRFSignalForTraining({
        start_frequency_hz: startFrequencyHz,
        stop_frequency_hz: stopFrequencyHz,
        duration_seconds: captureDuration,
        label_hint: captureLabelHint,
        session_id: `session_${new Date().toISOString().slice(0, 10)}`,
        file_format: 'iq',
        gain_db: selectedRFProfile?.recommended_gain_db,
        profile_key: selectedRFProfile?.selected_profile_key,
        profile: selectedRFProfile ?? undefined,
        apply_bandpass_filter: markerBandpass.enabled,
        filter_stopband_attenuation_db: markerBandpass.attenuationDb,
      });
      const analysis = captured.analysis as RFSignalUnderstandingResult;
      const region = pickTrainingRegion((analysis.regions ?? []) as Array<Record<string, any>>);
      if (!region?.bbox_id) {
        setResult(analysis);
        await refreshLearningLoop();
        setReviewStatus('Capture analyzed, but no region was found to add to training.');
        setError('No detected region was available in this capture. Move the markers tighter around the signal and capture again.');
        return;
      }
      const label = suggestTrainingLabel(region, captureLabelHint);
      const review = await apiService.reviewRFSignalRegion({
        analysis_id: analysis.analysis_id,
        bbox_id: String(region.bbox_id),
        label,
        review_status: label === 'unknown' ? 'unknown' : 'confirmed',
        reviewer: 'operator',
        notes: 'Auto-added from simplified RF Signal Understanding flow',
        send_to_training_buffer: true,
        legacy_label: null,
      });
      setResult(analysis);
      setReviewLabel(label);
      setReviewStatus(
        review.learning_buffer_sample?.iq_path
          ? `Ready: ${review.learning_buffer_sample.sample_id} · ${label} · trainable I/Q`
          : `Saved ${review.learning_buffer_sample?.sample_id ?? 'sample'} · ${label} · not trainable`,
      );
      await refreshLearningLoop();
    } catch (err) {
      setError(getErrorMessage(err));
      setReviewStatus('Capture + add failed');
    } finally {
      setLoading(false);
    }
  };

  const analyzeRegistered = async (captureId: string) => {
    try {
      setLoading(true);
      setAutoRefresh(false);
      const response = await apiService.analyzeRegisteredRFSignalCapture(captureId);
      setResult(response.analysis as RFSignalUnderstandingResult);
      await refreshLearningLoop();
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const deleteRegistered = async (captureId: string) => {
    if (!confirm(`Are you sure you want to delete capture ${captureId}?`)) return;
    try {
      setLoading(true);
      await apiService.deleteRegisteredRFSignalCapture(captureId);
      await refreshLearningLoop();
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const toggleCaptureSelection = (captureId: string) => {
    setSelectedCaptures(prev => {
      const newSet = new Set(prev);
      if (newSet.has(captureId)) {
        newSet.delete(captureId);
      } else {
        newSet.add(captureId);
      }
      return newSet;
    });
  };

  const toggleSelectAll = () => {
    if (selectedCaptures.size === captureRegistry.length) {
      setSelectedCaptures(new Set());
    } else {
      setSelectedCaptures(new Set(captureRegistry.map(c => c.capture_id)));
    }
  };

  const deleteSelected = async () => {
    if (selectedCaptures.size === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedCaptures.size} selected captures?`)) return;
    try {
      setLoading(true);
      await Promise.all(Array.from(selectedCaptures).map(id => apiService.deleteRegisteredRFSignalCapture(id)));
      setSelectedCaptures(new Set());
      await refreshLearningLoop();
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const trainSignalTypeClassifier = async () => {
    if (!canTrainSignalType) {
      setTrainingResult({
        status: 'not_ready',
        reason: trainingNotReadyReason || 'Training queue is not ready.',
      });
      setError(trainingNotReadyReason || 'Training queue is not ready.');
      return;
    }
    try {
      setLoading(true);
      setTrainingResult({ status: 'training_started', message: 'Training request sent to backend.' });
      const response = await apiService.trainRFSignalClassifierIncremental({
        dataset_name: 'learning_buffer',
        base_model_id: null,
        new_model_id: `signal_type_softmax_v${Date.now()}`,
        execution_target: trainingTarget,
        remote_user: remoteTraining.remote_user,
        remote_host: remoteTraining.remote_host,
        remote_venv_activate: remoteTraining.remote_venv_activate,
        include_weak_labels: true,
        weak_label_weight: 0.4,
        min_samples_per_class: effectiveMinSamplesPerClass,
        split_strategy: 'session_id',
        model_type: 'mlp_spectral_classifier',
        epochs: 250,
        learning_rate: 0.05,
        test_split: 0.25,
        feature_bins: 128,
      });
      setTrainingResult(response);
      await refreshLearningLoop();
      setError(null);
    } catch (err) {
      const message = getErrorMessage(err);
      setTrainingResult({ status: 'failed', reason: message });
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-full bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-500">
            <ScanSearch className="h-4 w-4" />
            Waterfall Evidence Pipeline
          </div>
          <h1 className="text-2xl font-semibold">RF Signal Understanding</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setAutoRefresh((value) => !value)} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)', background: autoRefresh ? 'var(--app-accent)' : 'var(--app-surface-strong)', color: autoRefresh ? 'var(--app-accent-foreground)' : 'var(--app-text)' }}>
            <RefreshCw className={`h-4 w-4 ${loading && autoRefresh ? 'animate-spin' : ''}`} />
            {autoRefresh ? 'Live on' : 'Live off'}
          </button>
          <button type="button" onClick={refreshLive} disabled={loading} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface-strong)' }}>
            <RadioTower className="h-4 w-4" />
            Refresh live
          </button>
          <button type="button" onClick={runAnalyze} disabled={loading || !filePath} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface-strong)' }}>
            <Microscope className="h-4 w-4" />
            Analyze file
          </button>
          <button type="button" onClick={runCompare} disabled={loading} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' }}>
            <GitCompare className="h-4 w-4" />
            Compare legacy
          </button>
        </div>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-500">{error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Simple learning flow" icon={<BrainCircuit className="h-4 w-4" />}>
          <Metric label="Band" value={markerBand ? `${formatFrequency(markerBand.start)} - ${formatFrequency(markerBand.stop)}` : 'Use Spectrum span'} />
          <Metric label="Suggested label" value={suggestedTrainingLabel} />
          <Metric label="Need" value="5 I/Q samples per class" />
          <label className="block">
            <span className="text-xs uppercase text-[var(--app-text-muted)]">Label to teach</span>
            <input value={captureLabelHint} onChange={(event) => setCaptureLabelHint(event.target.value)} className="mt-2 w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} placeholder="example: fm_broadcast_like" />
          </label>
          <button type="button" onClick={captureAndAddTrainingSample} disabled={loading} className="w-full rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' }}>
            Teach this signal
          </button>
          <div className="text-xs text-[var(--app-text-muted)]">
            Marca la region en Spectrum, escribe que es, y pulsa este boton. El sistema captura I/Q, analiza y guarda una muestra para que el modelo lo aprenda.
          </div>
        </Panel>

        <Panel title="Capture for training" icon={<Save className="h-4 w-4" />}>
          <Metric label="RF profile" value={selectedRFProfile?.selected_profile_key ?? 'manual'} />
          <Metric label="I/Q FIR filter" value={markerBandpass.enabled ? `ON, ${markerBandpass.attenuationDb} dB stopband` : 'off'} />
          <Metric label="Band source" value={activeConfigSource} />
          <Metric label="Capture start" value={formatFrequency(markerBand?.start ?? centerFrequencyHz - sampleRateHz / 2)} />
          <Metric label="Capture stop" value={formatFrequency(markerBand?.stop ?? centerFrequencyHz + sampleRateHz / 2)} />
          <NumberInput label="Duration s" value={captureDuration} onChange={setCaptureDuration} />
          <input value={captureLabelHint} onChange={(event) => setCaptureLabelHint(event.target.value)} className="w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} placeholder="label to teach optional" />
          <button type="button" onClick={captureForTraining} disabled={loading} className="w-full rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' }}>
            Capture I/Q for training
          </button>
          {selectedRFProfile && (
            <div className="text-xs text-[var(--app-text-muted)]">
              Profile metadata will be stored with the capture for homogeneous fingerprinting experiments.
            </div>
          )}
        </Panel>

        <Panel title="Live input" icon={<FileInput className="h-4 w-4" />}>
          <Metric label="Mode" value={(result?.mode as string) ?? 'live'} />
          <Metric label="Source" value={(result?.source as string) ?? 'real_sdr'} />
          <Metric label="Config source" value={activeConfigSource} />
          <Metric label="Spectrum center" value={formatFrequency(settings.centerFrequency)} />
          <Metric label="Spectrum span" value={formatFrequency(settings.span)} />
          {markerBand && (
            <>
              <Metric label={`${markerBand.firstLabel}-${markerBand.secondLabel}`} value={`${formatFrequency(markerBand.start)} - ${formatFrequency(markerBand.stop)}`} />
              <Metric label="Marker BW" value={formatFrequency(markerBand.bandwidth)} />
            </>
          )}
          <label className="mt-3 block text-xs uppercase text-[var(--app-text-muted)]">Optional I/Q or cfile path</label>
          <input value={filePath} onChange={(event) => setFilePath(event.target.value)} className="mt-2 w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} placeholder="C:\captures\capture_001.iq" />
          <div className="mt-3 grid grid-cols-2 gap-3">
            <NumberInput label="Sample rate Hz" value={sampleRateHz} onChange={setSampleRateHz} />
            <NumberInput label="Center Hz" value={centerFrequencyHz} onChange={setCenterFrequencyHz} />
          </div>
        </Panel>

        <Panel title="Live waterfall from SDR" icon={<Waves className="h-4 w-4" />}>
          <Metric label="Analysis" value={result?.analysis_id ?? 'not run'} />
          <Metric label="Backend center" value={formatFrequency(Number(liveInput.center_frequency_hz ?? activeCenterHz))} />
          <Metric label="Backend span" value={formatFrequency(Number(liveInput.span_hz ?? activeSpanHz))} />
          <Metric label="Backend rate" value={`${formatFrequency(Number(liveInput.sample_rate_hz ?? activeSampleRateHz))}/s`} />
          <Metric label="Rows" value={`${result?.waterfall.rows ?? result?.waterfall.n_fft ?? 0}`} />
          <Metric label="Bins" value={`${result?.waterfall.freq_bins ?? result?.waterfall.hop_length ?? 0}`} />
        </Panel>

        <Panel title="Detected time-frequency regions" icon={<Network className="h-4 w-4" />}>
          <Metric label="Regions" value={`${result?.regions?.length ?? 0}`} />
          <Metric label="First center" value={firstRegion ? formatFrequency(Number(firstRegion.freq_start_hz + firstRegion.freq_end_hz) / 2) : 'n/a'} />
          <Metric label="Detector" value={firstRegion?.detector?.type ?? 'morphological'} />
        </Panel>

        <Panel title="Region classification" icon={<BrainCircuit className="h-4 w-4" />}>
          <Metric label="Visual" value={firstRegion?.classification?.visual_label ?? 'unknown'} />
          <Metric label="MLP" value={firstRegion?.classification?.mlp_label ?? 'unknown'} />
          <Metric label="Policy" value="protocol-like only" />
        </Panel>

        <Panel title="Spectral features" icon={<RadioTower className="h-4 w-4" />}>
          <Metric label="Occupied BW" value={`${Number(spectral.occupied_bandwidth_hz ?? 0).toFixed(0)} Hz`} />
          <Metric label="SNR" value={`${Number(spectral.snr_db ?? 0).toFixed(1)} dB`} />
          <Metric label="Entropy" value={Number(spectral.spectral_entropy ?? 0).toFixed(3)} />
        </Panel>

        <Panel title="Bispectral verification" icon={<Beaker className="h-4 w-4" />}>
          <Metric label="Peak energy" value={Number(bispectral.bispectral_peak_energy ?? 0).toFixed(3)} />
          <Metric label="Phase coupling" value={Number(bispectral.phase_coupling_score ?? 0).toFixed(3)} />
          <Metric label="Nonlinear ratio" value={Number(bispectral.nonlinear_energy_ratio ?? 0).toFixed(3)} />
        </Panel>

        <Panel title="Final fused decision" icon={<ScanSearch className="h-4 w-4" />}>
          <Metric label="Label" value={finalDecision?.label ?? 'unknown'} />
          <Metric label="Confidence" value={`${(Number(finalDecision?.confidence ?? 0) * 100).toFixed(0)}%`} />
          <Metric label="Status" value={finalDecision?.status ?? 'unknown'} />
        </Panel>

        <Panel title="Legacy vs new comparison" icon={<GitCompare className="h-4 w-4" />}>
          <Metric label="Legacy" value={comparison?.legacy_rf_intelligence?.label ?? 'not compared'} />
          <Metric label="New" value={comparison?.new_rf_signal_understanding?.label ?? finalDecision?.label ?? 'unknown'} />
          <Metric label="Agreement" value={comparison?.comparison?.agreement_level ?? 'n/a'} />
        </Panel>

        <Panel title="Active learning review" icon={<Save className="h-4 w-4" />}>
          <Metric label="Region" value={firstRegion?.bbox_id ?? 'none'} />
          <input value={reviewLabel} onChange={(event) => setReviewLabel(event.target.value)} className="w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} />
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={() => reviewRegion('confirmed')} disabled={!firstRegion || loading} className="rounded-md border px-2 py-2 text-xs disabled:opacity-50" style={{ borderColor: 'var(--app-border)' }}>Confirm</button>
            <button type="button" onClick={() => reviewRegion('corrected')} disabled={!firstRegion || loading} className="rounded-md border px-2 py-2 text-xs disabled:opacity-50" style={{ borderColor: 'var(--app-border)' }}>Correct</button>
            <button type="button" onClick={() => reviewRegion('unknown')} disabled={!firstRegion || loading} className="rounded-md border px-2 py-2 text-xs disabled:opacity-50" style={{ borderColor: 'var(--app-border)' }}>Unknown</button>
            <button type="button" onClick={() => reviewRegion('ambiguous')} disabled={!firstRegion || loading} className="rounded-md border px-2 py-2 text-xs disabled:opacity-50" style={{ borderColor: 'var(--app-border)' }}>Ambiguous</button>
          </div>
          <button type="button" onClick={pseudoLabelRegion} disabled={!firstRegion || !comparison || loading} className="w-full rounded-md border px-2 py-2 text-xs disabled:opacity-50" style={{ borderColor: 'var(--app-border)' }}>
            Send weak legacy label
          </button>
          <Metric label="Buffer" value={reviewStatus ?? 'not saved'} />
        </Panel>
      </div>

      <section className="mt-4 rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold">Captured RF files</div>
          <div className="flex gap-2">
            <button type="button" onClick={toggleSelectAll} className="rounded-md border px-2 py-1 text-xs" style={{ borderColor: 'var(--app-border)' }}>
              {selectedCaptures.size === captureRegistry.length ? 'Deselect All' : 'Select All'}
            </button>
            <button type="button" onClick={deleteSelected} disabled={selectedCaptures.size === 0 || loading} className="rounded-md border px-2 py-1 text-xs bg-red-500 text-white disabled:opacity-50" style={{ borderColor: 'var(--app-border)' }}>
              Delete Selected ({selectedCaptures.size})
            </button>
            <button type="button" onClick={refreshLearningLoop} className="rounded-md border px-2 py-1 text-xs" style={{ borderColor: 'var(--app-border)' }}>Refresh</button>
          </div>
        </div>
        <div className="overflow-x-auto overflow-y-auto max-h-96">
          <table className="w-full min-w-[820px] text-left text-sm">
            <thead className="text-xs uppercase text-[var(--app-text-muted)]">
              <tr>
                <th className="px-2 py-2">
                  <input
                    type="checkbox"
                    checked={selectedCaptures.size === captureRegistry.length && captureRegistry.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded"
                  />
                </th>
                <th className="px-2 py-2">Capture ID</th>
                <th className="px-2 py-2">Frequency</th>
                <th className="px-2 py-2">Sample rate</th>
                <th className="px-2 py-2">Duration</th>
                <th className="px-2 py-2">Status</th>
                <th className="px-2 py-2">Labels</th>
                <th className="px-2 py-2">Used</th>
                <th className="px-2 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {captureRegistry.map((capture) => (
                <tr key={capture.capture_id} className="border-t" style={{ borderColor: 'var(--app-border)' }}>
                  <td className="px-2 py-2">
                    <input
                      type="checkbox"
                      checked={selectedCaptures.has(capture.capture_id)}
                      onChange={() => toggleCaptureSelection(capture.capture_id)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-2 py-2">{capture.capture_id}</td>
                  <td className="px-2 py-2">{formatFrequency(Number(capture.center_frequency_hz ?? 0))}</td>
                  <td className="px-2 py-2">{formatFrequency(Number(capture.sample_rate_hz ?? 0))}/s</td>
                  <td className="px-2 py-2">{Number(capture.duration_s ?? 0).toFixed(1)} s</td>
                  <td className="px-2 py-2">{capture.analysis_status ?? 'pending'}</td>
                  <td className="px-2 py-2">{(capture.labels ?? []).join(', ') || 'none'}</td>
                  <td className="px-2 py-2">{capture.used_for_training ? 'yes' : 'no'}</td>
                  <td className="px-2 py-2">
                    <button type="button" onClick={() => analyzeRegistered(String(capture.capture_id))} className="rounded-md border px-2 py-1 text-xs mr-2" style={{ borderColor: 'var(--app-border)' }}>Analyze</button>
                    <button type="button" onClick={() => deleteRegistered(String(capture.capture_id))} className="rounded-md border px-2 py-1 text-xs bg-red-500 text-white" style={{ borderColor: 'var(--app-border)' }}>Delete</button>
                  </td>
                </tr>
              ))}
              {captureRegistry.length === 0 && (
                <tr><td colSpan={9} className="px-2 py-6 text-center text-[var(--app-text-muted)]">No registered captures yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Training Queue" icon={<BrainCircuit className="h-4 w-4" />}>
          <Metric label="Total" value={`${trainingQueue?.total_samples ?? 0}`} />
          <Metric label="Trainable I/Q" value={`${trainingQueue?.trainable_iq_samples ?? 0}`} />
          <Metric label="Live only" value={`${trainingQueue?.non_trainable_live_samples ?? 0}`} />
          <Metric label="Strong" value={`${trainingQueue?.strong_labels ?? 0}`} />
          <Metric label="Weak" value={`${trainingQueue?.weak_labels ?? 0}`} />
          <Metric label="Unknown" value={`${trainingQueue?.unknown_samples ?? 0}`} />
          <Metric label="Ready button" value={canTrainSignalType ? 'yes' : 'no'} />
          {!canTrainSignalType && (
            <div className="rounded-md border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">
              {trainingNotReadyReason || 'The training queue is not ready yet.'}
            </div>
          )}
          <pre className="max-h-40 overflow-auto rounded-md bg-black/10 p-2 text-xs">{JSON.stringify(trainingQueue?.samples_per_class ?? {}, null, 2)}</pre>
        </Panel>
        <Panel title="Train model" icon={<Microscope className="h-4 w-4" />}>
          <Metric label="Model" value="signal-type softmax" />
          <Metric label="Weak weight" value="0.4" />
          <Metric label="Mode" value={bootstrapTraining ? 'bootstrap metadata' : 'I/Q spectral'} />
          <Metric label="Min samples/class" value={`${effectiveMinSamplesPerClass}`} />
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={() => setTrainingTarget('local')} className="rounded-md border px-2 py-2 text-xs" style={{ borderColor: 'var(--app-border)', background: trainingTarget === 'local' ? 'var(--app-accent)' : 'transparent', color: trainingTarget === 'local' ? 'var(--app-accent-foreground)' : 'var(--app-text)' }}>
              Local
            </button>
            <button type="button" onClick={() => setTrainingTarget('remote')} className="rounded-md border px-2 py-2 text-xs" style={{ borderColor: 'var(--app-border)', background: trainingTarget === 'remote' ? 'var(--app-accent)' : 'transparent', color: trainingTarget === 'remote' ? 'var(--app-accent-foreground)' : 'var(--app-text)' }}>
              Remote
            </button>
          </div>
          {trainingTarget === 'remote' && (
            <div className="space-y-2 rounded-md border p-2" style={{ borderColor: 'var(--app-border)' }}>
              {(['remote_user', 'remote_host', 'remote_venv_activate'] as const).map((field) => (
                <label key={field} className="block">
                  <span className="text-[10px] uppercase text-[var(--app-text-muted)]">{field}</span>
                  <input
                    value={remoteTraining[field]}
                    onChange={(event) => setRemoteTraining((current) => ({ ...current, [field]: event.target.value }))}
                    className="mt-1 w-full rounded-md border bg-transparent px-2 py-1.5 text-xs"
                    style={{ borderColor: 'var(--app-border)' }}
                  />
                </label>
              ))}
              <div className="text-xs text-[var(--app-text-muted)]">
                Remote target: {remoteTraining.remote_user || 'unset'}@{remoteTraining.remote_host || 'unset'}
              </div>
            </div>
          )}
          <button type="button" onClick={trainSignalTypeClassifier} disabled={loading || !canTrainSignalType} title={!canTrainSignalType ? trainingNotReadyReason : undefined} className="w-full rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' }}>
            Train signal-type classifier
          </button>
          {!canTrainSignalType && (
            <div className="text-xs text-[var(--app-text-muted)]">
              Puedes entrenar un modelo inicial con metadatos si hay al menos 5 muestras en 2 clases. Con I/Q real el modelo sera mas fiable.
            </div>
          )}
          {trainingResult && <pre className="max-h-48 overflow-auto rounded-md bg-black/10 p-2 text-xs">{JSON.stringify(trainingResult, null, 2)}</pre>}
        </Panel>
      </section>

      <section className="mt-4 rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
        <div className="mb-3 text-sm font-semibold">Scientific traceability</div>
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {techniqueRows.map(([technique, paper]) => (
            <div key={technique} className="rounded-md bg-black/5 px-3 py-2 text-sm">
              <div className="font-medium">Technique: {technique}</div>
              <div className="mt-1 text-[var(--app-text-muted)]">Supported by: {paper}</div>
            </div>
          ))}
        </div>
        {references && <div className="mt-3 text-xs text-[var(--app-text-muted)]">Reference groups loaded: {Object.keys(references).join(', ')}</div>}
      </section>
    </div>
  );
};

const Panel = ({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) => (
  <section className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
    <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
      {icon}
      {title}
    </div>
    <div className="space-y-2">{children}</div>
  </section>
);

const Metric = ({ label, value }: { label: string; value: string }) => (
  <div className="flex items-center justify-between gap-3 rounded-md bg-black/5 px-3 py-2 text-sm">
    <span className="text-[var(--app-text-muted)]">{label}</span>
    <span className="max-w-[14rem] truncate text-right font-medium">{value}</span>
  </div>
);

const NumberInput = ({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) => (
  <label className="block">
    <span className="text-xs uppercase text-[var(--app-text-muted)]">{label}</span>
    <input value={value} onChange={(event) => onChange(Number(event.target.value))} type="number" className="mt-2 w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} />
  </label>
);
