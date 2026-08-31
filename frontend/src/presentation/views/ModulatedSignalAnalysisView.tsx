import React, { useEffect, useMemo, useState } from 'react';
import { Bluetooth, Database, Download, Play, RotateCcw, ShieldCheck, Trash2, Wifi } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ApiService } from '../../app/services/ApiService';
import { useAnalyzerSettings, useAppActions, useMarkers, useSpectrumData } from '../../app/store/AppStore';
import { MODULATION_HINTS } from '../../shared/constants';
import { ModulatedSignalCapture } from '../../shared/types';
import { buildRfCaptureDiagnostic, estimateBandQuality, formatFrequency, formatPowerLevel } from '../../shared/utils';
import { cn } from '../../shared/utils';

const apiService = new ApiService();

const splitHelp = {
  train: 'Entrena el modelo. No reutilizar luego para validacion ni prediccion.',
  val: 'Se reserva solo para validacion externa. No mezclar con train.',
  predict: 'Se usa para inferencia sobre muestras nuevas. No contaminar train ni val.',
} as const;

const CAPTURE_LAB_MAX_BANDWIDTH_HZ = 10_000_000;
const CAPTURE_LAB_MAX_DURATION_S = 120;
const BLE_ANALYZER_ENABLED = import.meta.env.VITE_BLE_ANALYZER_V1 !== 'false';
const BLE_DSP_UNAVAILABLE_REASON = 'IQ-based BLE analysis is unavailable because the DSP recovery gate has not been completed. Validated bitstream replay is available for platform-integration testing.';

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

const formatBytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

const formatMHz = (hz: number) => (hz / 1e6).toFixed(6);

export const ModulatedSignalAnalysisView: React.FC = () => {
  const markers = useMarkers();
  const analyzerSettings = useAnalyzerSettings();
  const spectrumData = useSpectrumData();
  const { setGlobalActivity, clearGlobalActivity } = useAppActions();
  const [durationSeconds, setDurationSeconds] = useState('5');
  const [fileFormat, setFileFormat] = useState<'cfile' | 'iq'>('cfile');
  const [captureBandMode, setCaptureBandMode] = useState<'markers' | 'custom'>('markers');
  const [bandSourcePinned, setBandSourcePinned] = useState(false);
  const [customStartMHz, setCustomStartMHz] = useState('');
  const [customStopMHz, setCustomStopMHz] = useState('');
  const [customCenterMHz, setCustomCenterMHz] = useState('');
  const [customBandwidthMHz, setCustomBandwidthMHz] = useState('');
  const [datasetSplit, setDatasetSplit] = useState<'train' | 'val' | 'predict'>('train');
  const [label, setLabel] = useState('band_profile_pending');
  const [transmitterId, setTransmitterId] = useState('weak_profile_pending');
  const [transmitterClass, setTransmitterClass] = useState('profile_pending');
  const [bandProfileSuggestion, setBandProfileSuggestion] = useState<Record<string, any> | null>(null);
  const [autoApplyBandProfile, setAutoApplyBandProfile] = useState(true);
  const [sessionId, setSessionId] = useState('session_001');
  const [operator, setOperator] = useState('operator_a');
  const [environment, setEnvironment] = useState('indoor_lab_los');
  const [modulationHint, setModulationHint] = useState('unknown');
  const [notes, setNotes] = useState('');
  const [autoImport, setAutoImport] = useState(true);
  const [captureMode, setCaptureMode] = useState<'immediate' | 'triggered_burst'>('immediate');
  const [triggerStrategy, setTriggerStrategy] = useState<'adaptive_energy_trigger' | 'smart_burst_trigger'>('adaptive_energy_trigger');
  const [triggerThresholdDb, setTriggerThresholdDb] = useState('6');
  const [preTriggerMs, setPreTriggerMs] = useState('50');
  const [postTriggerMs, setPostTriggerMs] = useState('100');
  const [minEventDurationMs, setMinEventDurationMs] = useState('10');
  const [maxEventDurationMs, setMaxEventDurationMs] = useState('2000');
  const [cooldownMs, setCooldownMs] = useState('500');
  const [triggerMaxWaitSeconds, setTriggerMaxWaitSeconds] = useState('10');
  const [captureRepetitions, setCaptureRepetitions] = useState('1');
  const [minValidEvents, setMinValidEvents] = useState('1');
  const [smartPersistenceMs, setSmartPersistenceMs] = useState('10');
  const [autoQcEnabled, setAutoQcEnabled] = useState(true);
  const [targetTask, setTargetTask] = useState<'device_fingerprinting' | 'signal_recognition'>('device_fingerprinting');
  const [signalType, setSignalType] = useState('');
  const [isCapturing, setIsCapturing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [captures, setCaptures] = useState<ModulatedSignalCapture[]>([]);
  const [deletingCaptureId, setDeletingCaptureId] = useState<string | null>(null);

  const selectedBand = useMemo(() => {
    if (markers.length < 2) return null;
    const [first, second] = markers;
    const start = Math.min(first.frequency, second.frequency);
    const stop = Math.max(first.frequency, second.frequency);
    return {
      start,
      stop,
      center: start + (stop - start) / 2,
      bandwidth: stop - start,
      first,
      second,
    };
  }, [markers]);

  const customBand = useMemo(() => {
    const start = Number(customStartMHz) * 1e6;
    const stop = Number(customStopMHz) * 1e6;
    if (!Number.isFinite(start) || !Number.isFinite(stop) || start <= 0 || stop <= start) {
      return null;
    }
    return {
      start,
      stop,
      center: start + (stop - start) / 2,
      bandwidth: stop - start,
    };
  }, [customStartMHz, customStopMHz]);

  const activeBand = captureBandMode === 'markers' ? selectedBand : customBand;
  const activeBandSourceLabel = captureBandMode === 'markers' ? 'Markers M1-M2' : 'Custom Frequencies';
  const liveBandQuality = useMemo(() => {
    if (!activeBand || !spectrumData) return null;
    return estimateBandQuality(
      spectrumData.frequencyArray,
      spectrumData.powerLevels,
      activeBand.start,
      activeBand.stop,
    );
  }, [activeBand, spectrumData]);
  const preCaptureDiagnostic = useMemo(() => {
    if (!activeBand || !liveBandQuality) return null;
    return buildRfCaptureDiagnostic({
      source: 'live',
      centerFrequencyHz: activeBand.center,
      bandwidthHz: activeBand.bandwidth,
      peakFrequencyHz: liveBandQuality.peakFrequencyHz,
      snrDb: liveBandQuality.snrDb,
      canonicalizationEnabled: true,
    });
  }, [activeBand, liveBandQuality]);

  const requestedDuration = Number(durationSeconds);
  const requestedTriggerThresholdDb = Number(triggerThresholdDb);
  const requestedPreTriggerMs = Number(preTriggerMs);
  const requestedPostTriggerMs = Number(postTriggerMs);
  const requestedMinEventDurationMs = Number(minEventDurationMs);
  const requestedMaxEventDurationMs = Number(maxEventDurationMs);
  const requestedCooldownMs = Number(cooldownMs);
  const requestedTriggerMaxWaitSeconds = Number(triggerMaxWaitSeconds);
  const requestedCaptureRepetitions = Number(captureRepetitions);
  const requestedMinValidEvents = Number(minValidEvents);
  const requestedSmartPersistenceMs = Number(smartPersistenceMs);

  const captureValidationMessage = useMemo(() => {
    if (!activeBand) {
      return captureBandMode === 'markers'
        ? 'Create at least two markers to define the capture band.'
        : 'Enter a valid frequency window. Start must be lower than stop and both must be positive.';
    }
    if (activeBand.bandwidth > CAPTURE_LAB_MAX_BANDWIDTH_HZ) {
      return `Capture Lab supports up to ${(CAPTURE_LAB_MAX_BANDWIDTH_HZ / 1e6).toFixed(1)} MHz of bandwidth in this workflow. Reduce the requested window.`;
    }
    if (captureMode === 'immediate') {
      if (!Number.isFinite(requestedDuration) || requestedDuration <= 0 || requestedDuration > CAPTURE_LAB_MAX_DURATION_S) {
        return `Duration must be between 0 and ${CAPTURE_LAB_MAX_DURATION_S} seconds.`;
      }
    }
    if (captureMode === 'triggered_burst') {
      if (!Number.isFinite(requestedTriggerThresholdDb) || requestedTriggerThresholdDb <= 0 || requestedTriggerThresholdDb > 40) {
        return 'Trigger threshold must be between 0 and 40 dB above the estimated noise floor.';
      }
      if (!Number.isFinite(requestedPreTriggerMs) || requestedPreTriggerMs < 0 || requestedPreTriggerMs > 5000) {
        return 'Pre-trigger must be between 0 and 5000 ms.';
      }
      if (!Number.isFinite(requestedPostTriggerMs) || requestedPostTriggerMs < 0 || requestedPostTriggerMs > 5000) {
        return 'Post-trigger must be between 0 and 5000 ms.';
      }
      if (!Number.isFinite(requestedMinEventDurationMs) || requestedMinEventDurationMs < 1 || requestedMinEventDurationMs > 5000) {
        return 'Min event duration must be between 1 and 5000 ms.';
      }
      if (!Number.isFinite(requestedMaxEventDurationMs) || requestedMaxEventDurationMs < requestedMinEventDurationMs) {
        return 'Max event duration must be ≥ min event duration.';
      }
      if (!Number.isFinite(requestedTriggerMaxWaitSeconds) || requestedTriggerMaxWaitSeconds <= 0 || requestedTriggerMaxWaitSeconds > 120) {
        return 'Max wait per event must be between 0 and 120 seconds.';
      }
      if (!Number.isFinite(requestedCaptureRepetitions) || requestedCaptureRepetitions < 1 || requestedCaptureRepetitions > 20) {
        return 'Capture repetitions must be between 1 and 20.';
      }
      if (!Number.isFinite(requestedMinValidEvents) || requestedMinValidEvents < 1 || requestedMinValidEvents > requestedCaptureRepetitions) {
        return 'Min valid events must be between 1 and capture repetitions.';
      }
      if (triggerStrategy === 'smart_burst_trigger') {
        if (!Number.isFinite(requestedSmartPersistenceMs) || requestedSmartPersistenceMs < 0 || requestedSmartPersistenceMs > 1000) {
          return 'Smart burst persistence must be between 0 and 1000 ms.';
        }
      }
    }
    return null;
  }, [
    activeBand,
    captureBandMode,
    requestedDuration,
    captureMode,
    triggerStrategy,
    requestedTriggerThresholdDb,
    requestedPreTriggerMs,
    requestedPostTriggerMs,
    requestedMinEventDurationMs,
    requestedMaxEventDurationMs,
    requestedCooldownMs,
    requestedTriggerMaxWaitSeconds,
    requestedCaptureRepetitions,
    requestedMinValidEvents,
    requestedSmartPersistenceMs,
  ]);

  const loadCaptures = async () => {
    const data = await apiService.getModulatedSignalCaptures();
    setCaptures(data);
  };

  useEffect(() => {
    loadCaptures().catch(() => undefined);
  }, []);

  useEffect(() => {
    const start = (analyzerSettings.centerFrequency - analyzerSettings.span / 2) / 1e6;
    const stop = (analyzerSettings.centerFrequency + analyzerSettings.span / 2) / 1e6;
    setCustomStartMHz(start.toFixed(6));
    setCustomStopMHz(stop.toFixed(6));
    setCustomCenterMHz(formatMHz(analyzerSettings.centerFrequency));
    setCustomBandwidthMHz(formatMHz(analyzerSettings.span));
  }, [analyzerSettings.centerFrequency, analyzerSettings.span]);

  useEffect(() => {
    if (!bandSourcePinned && selectedBand) {
      setCaptureBandMode('markers');
    }
  }, [selectedBand, bandSourcePinned]);

  useEffect(() => {
    if (!activeBand) return;
    let cancelled = false;
    apiService.resolveRFIntelligenceBandProfile({
      start_frequency_hz: activeBand.start,
      stop_frequency_hz: activeBand.stop,
      center_frequency_hz: activeBand.center,
      bandwidth_hz: activeBand.bandwidth,
    })
      .then((response) => {
        const resolved = response.data ?? response;
        if (cancelled) return;
        setBandProfileSuggestion(resolved);
        const defaults = resolved.defaults;
        if (autoApplyBandProfile && defaults) {
          setLabel(defaults.transmitter_label || label);
          setTransmitterClass(defaults.transmitter_class || transmitterClass);
          setTransmitterId(defaults.transmitter_id || transmitterId);
          setModulationHint(defaults.modulation_class || defaults.transmitter_class || modulationHint);
          if (!notes) {
            setNotes(`Weak band-profile label from ${defaults.profile_key || 'band_profiles.json'}. Confirm manually before scientific training.`);
          }
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [activeBand?.start, activeBand?.stop, autoApplyBandProfile]);

  const useAnalyzerWindow = () => {
    const startHz = analyzerSettings.centerFrequency - analyzerSettings.span / 2;
    const stopHz = analyzerSettings.centerFrequency + analyzerSettings.span / 2;
    setCustomStartMHz(formatMHz(startHz));
    setCustomStopMHz(formatMHz(stopHz));
    setCustomCenterMHz(formatMHz(analyzerSettings.centerFrequency));
    setCustomBandwidthMHz(formatMHz(analyzerSettings.span));
    setCaptureBandMode('custom');
    setBandSourcePinned(true);
  };

  const centerOnLivePeak = () => {
    if (!activeBand || !liveBandQuality) {
      return;
    }
    const bandwidthHz = activeBand.bandwidth;
    const centerHz = liveBandQuality.peakFrequencyHz;
    const startHz = centerHz - bandwidthHz / 2;
    const stopHz = centerHz + bandwidthHz / 2;
    if (startHz <= 0 || stopHz <= startHz) {
      return;
    }
    setCustomCenterMHz(formatMHz(centerHz));
    setCustomBandwidthMHz(formatMHz(bandwidthHz));
    setCustomStartMHz(formatMHz(startHz));
    setCustomStopMHz(formatMHz(stopHz));
    setCaptureBandMode('custom');
    setBandSourcePinned(true);
  };

  const useCurrentMarkersNow = () => {
    if (!selectedBand) {
      setError('Create at least two markers in Live Monitor before using marker-driven capture.');
      return;
    }
    setError(null);
    setCaptureBandMode('markers');
    setBandSourcePinned(false);
  };

  const updateFromStartStop = (startMHzValue: string, stopMHzValue: string) => {
    setCustomStartMHz(startMHzValue);
    setCustomStopMHz(stopMHzValue);
    const startHz = Number(startMHzValue) * 1e6;
    const stopHz = Number(stopMHzValue) * 1e6;
    if (!Number.isFinite(startHz) || !Number.isFinite(stopHz) || startHz <= 0 || stopHz <= startHz) {
      return;
    }
    const centerHz = startHz + (stopHz - startHz) / 2;
    const bandwidthHz = stopHz - startHz;
    setCustomCenterMHz(formatMHz(centerHz));
    setCustomBandwidthMHz(formatMHz(bandwidthHz));
  };

  const updateFromCenterBandwidth = (centerMHzValue: string, bandwidthMHzValue: string) => {
    setCustomCenterMHz(centerMHzValue);
    setCustomBandwidthMHz(bandwidthMHzValue);
    const centerHz = Number(centerMHzValue) * 1e6;
    const bandwidthHz = Number(bandwidthMHzValue) * 1e6;
    if (!Number.isFinite(centerHz) || !Number.isFinite(bandwidthHz) || centerHz <= 0 || bandwidthHz <= 0) {
      return;
    }
    const startHz = centerHz - bandwidthHz / 2;
    const stopHz = centerHz + bandwidthHz / 2;
    if (startHz <= 0 || stopHz <= startHz) {
      return;
    }
    setCustomStartMHz(formatMHz(startHz));
    setCustomStopMHz(formatMHz(stopHz));
  };

  const deleteCapture = async (capture: ModulatedSignalCapture) => {
    const confirmed = window.confirm(
      `Delete Capture Lab dataset ${capture.label || capture.id}? This removes the raw IQ file, metadata JSON, and any linked fingerprinting registry record.`,
    );
    if (!confirmed) return;
    setError(null);
    setSuccess(null);
    setDeletingCaptureId(capture.id);
    try {
      const result = await apiService.deleteModulatedSignalCapture(capture.id);
      const registryInfo = result.deleted_registry_records.length
        ? ` Removed ${result.deleted_registry_records.length} linked fingerprinting record(s).`
        : '';
      const skippedInfo = result.skipped_external_files?.length
        ? ` Skipped ${result.skipped_external_files.length} external file(s) outside this project.`
        : '';
      setSuccess(`Capture ${result.capture_id} deleted. Removed ${result.deleted_files.length} local file(s).${registryInfo}${skippedInfo}`);
      await loadCaptures();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setDeletingCaptureId(null);
    }
  };

  const captureSignal = async () => {
    if (!activeBand) {
      setError(
        captureBandMode === 'markers'
          ? 'Create at least two markers first. M1 and M2 define the capture band.'
          : 'Set valid custom start and stop frequencies before capturing.',
      );
      return;
    }

    const duration = Number(durationSeconds);
    if (captureValidationMessage) {
      setError(captureValidationMessage);
      return;
    }

    setError(null);
    setSuccess(null);
    setIsCapturing(true);
    const activityDetail = captureMode === 'triggered_burst'
      ? `${formatFrequency(activeBand.start)} – ${formatFrequency(activeBand.stop)} · ${requestedCaptureRepetitions} event(s) · strategy: ${triggerStrategy.replace('_trigger', '')} · Navigation remains available.`
      : `${formatFrequency(activeBand.start)} to ${formatFrequency(activeBand.stop)} · ${duration}s · Navigation remains available.`;
    setGlobalActivity({
      visible: true,
      kind: 'capturing',
      title: captureMode === 'triggered_burst'
        ? `Triggered capture – waiting for signal (${datasetSplit.toUpperCase()})`
        : `Capturing ${datasetSplit.toUpperCase()} dataset segment`,
      detail: activityDetail,
    });
    try {
      const capture = await apiService.captureModulatedSignal({
        startFrequencyHz: activeBand.start,
        stopFrequencyHz: activeBand.stop,
        durationSeconds: duration,
        label,
        modulationHint,
        notes,
        datasetSplit,
        sessionId,
        transmitterId,
        transmitterClass,
        operator,
        environment,
        fileFormat,
        livePreviewSnrDb: liveBandQuality?.snrDb,
        livePreviewNoiseFloorDb: liveBandQuality?.noiseFloorDb,
        livePreviewPeakLevelDb: liveBandQuality?.peakLevelDb,
        livePreviewPeakFrequencyHz: liveBandQuality?.peakFrequencyHz,
        captureMode,
        triggerStrategy,
        triggerThresholdDb: requestedTriggerThresholdDb,
        preTriggerMs: requestedPreTriggerMs,
        postTriggerMs: requestedPostTriggerMs,
        minEventDurationMs: requestedMinEventDurationMs,
        maxEventDurationMs: requestedMaxEventDurationMs,
        cooldownMs: requestedCooldownMs,
        triggerMaxWaitSeconds: requestedTriggerMaxWaitSeconds,
        captureRepetitions: requestedCaptureRepetitions,
        minValidEvents: requestedMinValidEvents,
        smartPersistenceMs: requestedSmartPersistenceMs,
        autoQcEnabled,
        targetTask,
        signalType,
      });

      if (autoImport) {
        await apiService.importModulatedCaptureToFingerprinting(capture.id, {
          session_id: sessionId,
          dataset_split: datasetSplit,
          transmitter_label: label,
          transmitter_class: transmitterClass,
          transmitter_id: transmitterId,
          operator,
          environment,
          notes,
          ground_truth_confidence: autoApplyBandProfile ? 'weak_from_band_profile' : 'confirmed',
          family: bandProfileSuggestion?.defaults?.family || transmitterClass,
          signal_family: bandProfileSuggestion?.defaults?.family || transmitterClass,
          signal_type: bandProfileSuggestion?.defaults?.signal_type || transmitterClass,
          modulation_class: bandProfileSuggestion?.defaults?.modulation_class || modulationHint,
          protocol_family: bandProfileSuggestion?.defaults?.protocol_family || transmitterClass,
          band_label: bandProfileSuggestion?.defaults?.band_label || label,
          profile_key: bandProfileSuggestion?.defaults?.profile_key || null,
          label_status: autoApplyBandProfile ? 'weak_label' : 'strong_label',
        });
      }

      setCaptures((current) => [capture, ...current.filter((item) => item.id !== capture.id)]);
      const sessionInfo = capture.trigger_capture
        ? ` (${capture.trigger_capture.session_events_captured ?? 1} event(s) captured, ${capture.trigger_capture.session_events_qc_passed ?? 1} QC-passed)`
        : '';
      setSuccess(
        autoImport
          ? `Capture ${capture.id} stored and imported as ${datasetSplit}.${sessionInfo}`
          : `Capture ${capture.id} stored as raw IQ metadata with split ${datasetSplit}.${sessionInfo}`,
      );
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsCapturing(false);
      clearGlobalActivity();
    }
  };

  return (
    <div className="h-full overflow-auto bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-7xl space-y-5 p-6">
        <section className="rounded-md border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Capture Lab</h2>
              <p className="text-sm text-slate-400">
                Esta es ahora la pantalla principal de captura. Captura IQ real entre M1 y M2, define si la muestra es
                para `train`, `val` o `predict`, y la deja lista para que entrenamiento, validación o inferencia la detecten automáticamente.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {BLE_ANALYZER_ENABLED && <Link to="/ble-lab" className="inline-flex h-9 items-center rounded-md bg-cyan-700 px-3 text-sm font-semibold hover:bg-cyan-600"><Bluetooth className="mr-2 h-4 w-4" />Open BLE Lab</Link>}
              <button onClick={() => loadCaptures()} className="inline-flex h-9 items-center rounded-md bg-slate-700 px-3 text-sm hover:bg-slate-600"><RotateCcw className="mr-2 h-4 w-4" />Refresh</button>
            </div>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_420px]">
          <div className="space-y-4 rounded-md border border-slate-800 bg-slate-900 p-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Info label="M1" value={selectedBand ? formatFrequency(selectedBand.first.frequency) : 'Not set'} />
              <Info label="M2" value={selectedBand ? formatFrequency(selectedBand.second.frequency) : 'Not set'} />
              <Info label="Center" value={activeBand ? formatFrequency(activeBand.center) : 'Not set'} />
              <Info label="Bandwidth" value={activeBand ? formatFrequency(activeBand.bandwidth) : 'Not set'} />
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4 text-sm text-slate-300">
              <div className="text-xs uppercase text-slate-500">Current Capture Source</div>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-cyan-700/60 bg-cyan-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100">
                  {activeBandSourceLabel}
                </span>
                <span className="text-xs text-slate-400">
                  {captureBandMode === 'markers'
                    ? 'La captura usará exactamente M1 y M2.'
                    : 'La captura usará la ventana custom actual, aunque existan markers visibles.'}
                </span>
              </div>
            </div>

            <div className="rounded-md border border-teal-800 bg-teal-950/30 p-4 text-sm text-teal-50">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-xs uppercase text-teal-300">Automatic label from band_profiles.json</div>
                  <div className="mt-2 font-semibold">{bandProfileSuggestion?.defaults?.transmitter_label ?? 'No resolved profile yet'}</div>
                  <div className="mt-1 text-xs text-teal-100/80">
                    {bandProfileSuggestion?.profile_key ?? 'none'} · {bandProfileSuggestion?.defaults?.transmitter_class ?? 'unresolved'} · score {Number(bandProfileSuggestion?.score ?? 0).toFixed(3)}
                  </div>
                </div>
                <label className="flex items-center gap-2 rounded-full border border-teal-700 bg-black/20 px-3 py-2 text-xs">
                  <input type="checkbox" checked={autoApplyBandProfile} onChange={(event) => setAutoApplyBandProfile(event.target.checked)} />
                  Auto-apply weak label
                </label>
              </div>
              <div className="mt-2 text-xs text-teal-100/75">
                Esta etiqueta evita capturas sin clase, pero queda como weak_label hasta que el usuario la confirme para entrenamiento cientifico.
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <Info label="Live peak" value={liveBandQuality ? formatPowerLevel(liveBandQuality.peakLevelDb) : 'Not available'} />
              <Info label="Noise floor" value={liveBandQuality ? formatPowerLevel(liveBandQuality.noiseFloorDb) : 'Not available'} />
              <Info label="Live SNR" value={liveBandQuality ? `${liveBandQuality.snrDb.toFixed(1)} dB` : 'Not available'} />
              <Info label="Peak freq" value={liveBandQuality ? formatFrequency(liveBandQuality.peakFrequencyHz) : 'Not available'} />
            </div>

            {preCaptureDiagnostic && (
              <RfDiagnosticCard diagnostic={preCaptureDiagnostic} titlePrefix="Pre-capture intelligence" />
            )}

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs uppercase text-slate-500">Capture Frequency Source</div>
                  <div className="mt-1 text-sm text-slate-300">
                    Elige si quieres capturar entre los dos primeros markers o con frecuencias personalizadas.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={useCurrentMarkersNow}
                    disabled={!selectedBand}
                    className={cn(
                      'rounded-full border px-4 py-2 text-xs font-semibold',
                      !selectedBand
                        ? 'cursor-not-allowed border-slate-800 text-slate-600'
                        : 'border-cyan-700 text-cyan-100 hover:bg-cyan-950/40',
                    )}
                  >
                    Use Current M1-M2 Now
                  </button>
                  <button
                    type="button"
                    onClick={centerOnLivePeak}
                    disabled={!activeBand || !liveBandQuality}
                    className={cn(
                      'rounded-full border px-4 py-2 text-xs font-semibold',
                      !activeBand || !liveBandQuality
                        ? 'cursor-not-allowed border-slate-800 text-slate-600'
                        : 'border-emerald-700 text-emerald-100 hover:bg-emerald-950/40',
                    )}
                  >
                    Center on Live Peak
                  </button>
                  <button
                    type="button"
                    onClick={useAnalyzerWindow}
                    className="rounded-full border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Use Live Monitor Window
                  </button>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => {
                    setCaptureBandMode('markers');
                    setBandSourcePinned(false);
                  }}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureBandMode === 'markers'
                      ? 'border-cyan-500 bg-cyan-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Markers M1-M2</div>
                  <div className="mt-2 text-xs text-slate-400">Captura exactamente la banda delimitada por los dos primeros markers.</div>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCaptureBandMode('custom');
                    setBandSourcePinned(true);
                  }}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureBandMode === 'custom'
                      ? 'border-cyan-500 bg-cyan-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Custom Frequencies</div>
                  <div className="mt-2 text-xs text-slate-400">Define center y bandwidth o start y stop. El otro par se recalcula automáticamente.</div>
                </button>
              </div>

              {captureBandMode === 'custom' && (
                <div className="mt-4 space-y-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Center MHz
                      <input value={customCenterMHz} onChange={(event) => updateFromCenterBandwidth(event.target.value, customBandwidthMHz)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Bandwidth MHz
                      <input value={customBandwidthMHz} onChange={(event) => updateFromCenterBandwidth(customCenterMHz, event.target.value)} className={inputClass} />
                    </label>
                    <Info label="Derived start" value={customBand ? formatFrequency(customBand.start) : 'Invalid'} />
                    <Info label="Derived stop" value={customBand ? formatFrequency(customBand.stop) : 'Invalid'} />
                  </div>

                  <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Start MHz
                    <input value={customStartMHz} onChange={(event) => updateFromStartStop(event.target.value, customStopMHz)} className={inputClass} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Stop MHz
                    <input value={customStopMHz} onChange={(event) => updateFromStartStop(customStartMHz, event.target.value)} className={inputClass} />
                  </label>
                  <Info label="Derived center" value={customBand ? formatFrequency(customBand.center) : 'Invalid'} />
                  <Info label="Derived bandwidth" value={customBand ? formatFrequency(customBand.bandwidth) : 'Invalid'} />
                </div>
                </div>
              )}

              {captureValidationMessage && (
                <div className="mt-4 rounded-2xl border border-amber-400/40 bg-amber-500/10 p-4 text-sm text-amber-100">
                  {captureValidationMessage}
                </div>
              )}
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <div className="text-xs uppercase text-slate-500">Capture Mode</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setCaptureMode('immediate')}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureMode === 'immediate'
                      ? 'border-emerald-500 bg-emerald-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Manual Capture</div>
                  <div className="mt-2 text-xs text-slate-400">Graba inmediatamente toda la ventana temporal pedida. Sin espera de señal.</div>
                </button>
                <button
                  type="button"
                  onClick={() => setCaptureMode('triggered_burst')}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureMode === 'triggered_burst'
                      ? 'border-blue-500 bg-blue-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Triggered Capture</div>
                  <div className="mt-2 text-xs text-slate-400">Buffer circular continuo de IQ. Dispara al detectar actividad. El inicio del burst nunca se pierde.</div>
                </button>
              </div>

              {captureMode === 'triggered_burst' && (
                <div className="mt-4 space-y-4">
                  {/* Trigger strategy */}
                  <div>
                    <div className="mb-2 text-xs uppercase text-slate-500">Trigger Strategy</div>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      <button
                        type="button"
                        onClick={() => setTriggerStrategy('adaptive_energy_trigger')}
                        className={cn(
                          'rounded-md border p-3 text-left text-sm transition',
                          triggerStrategy === 'adaptive_energy_trigger'
                            ? 'border-blue-400 bg-blue-500/10 text-white'
                            : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                        )}
                      >
                        <div className="font-semibold">Adaptive Energy</div>
                        <div className="mt-1 text-xs text-slate-400">Estimación dinámica del ruido por percentil. Dispara cuando la energía supera el umbral.</div>
                      </button>
                      <button
                        type="button"
                        onClick={() => setTriggerStrategy('smart_burst_trigger')}
                        className={cn(
                          'rounded-md border p-3 text-left text-sm transition',
                          triggerStrategy === 'smart_burst_trigger'
                            ? 'border-blue-400 bg-blue-500/10 text-white'
                            : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                        )}
                      >
                        <div className="font-semibold">Smart Burst</div>
                        <div className="mt-1 text-xs text-slate-400">Adds persistence check and saturation rejection to reduce false positives.</div>
                      </button>
                    </div>
                  </div>

                  {/* Core trigger timing */}
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Threshold dB
                      <input value={triggerThresholdDb} onChange={(e) => setTriggerThresholdDb(e.target.value)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Pre-trigger ms
                      <input value={preTriggerMs} onChange={(e) => setPreTriggerMs(e.target.value)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Post-trigger ms
                      <input value={postTriggerMs} onChange={(e) => setPostTriggerMs(e.target.value)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Max wait s
                      <input value={triggerMaxWaitSeconds} onChange={(e) => setTriggerMaxWaitSeconds(e.target.value)} className={inputClass} />
                    </label>
                  </div>

                  {/* Event duration + session */}
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Min event ms
                      <input value={minEventDurationMs} onChange={(e) => setMinEventDurationMs(e.target.value)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Max event ms
                      <input value={maxEventDurationMs} onChange={(e) => setMaxEventDurationMs(e.target.value)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Repetitions
                      <input value={captureRepetitions} onChange={(e) => setCaptureRepetitions(e.target.value)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Cooldown ms
                      <input value={cooldownMs} onChange={(e) => setCooldownMs(e.target.value)} className={inputClass} />
                    </label>
                  </div>

                  {/* Min valid + smart persistence (conditional) */}
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Min valid events
                      <input value={minValidEvents} onChange={(e) => setMinValidEvents(e.target.value)} className={inputClass} />
                    </label>
                    {triggerStrategy === 'smart_burst_trigger' && (
                      <label className="flex flex-col gap-1 text-xs text-slate-400">
                        Persistence ms
                        <input value={smartPersistenceMs} onChange={(e) => setSmartPersistenceMs(e.target.value)} className={inputClass} />
                      </label>
                    )}
                  </div>

                  {/* Target task */}
                  <div>
                    <div className="mb-2 text-xs uppercase text-slate-500">Target Task</div>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      <button
                        type="button"
                        onClick={() => setTargetTask('device_fingerprinting')}
                        className={cn(
                          'rounded-md border p-3 text-left text-sm transition',
                          targetTask === 'device_fingerprinting'
                            ? 'border-violet-500 bg-violet-500/10 text-white'
                            : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                        )}
                      >
                        <div className="font-semibold">Device Fingerprinting</div>
                        <div className="mt-1 text-xs text-slate-400">Label = Transmitter ID. Identifica el dispositivo emisor.</div>
                      </button>
                      <button
                        type="button"
                        onClick={() => setTargetTask('signal_recognition')}
                        className={cn(
                          'rounded-md border p-3 text-left text-sm transition',
                          targetTask === 'signal_recognition'
                            ? 'border-violet-500 bg-violet-500/10 text-white'
                            : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                        )}
                      >
                        <div className="font-semibold">Signal Recognition</div>
                        <div className="mt-1 text-xs text-slate-400">Label = Signal Type. Clasifica el tipo de señal (WiFi, BLE, LoRa…).</div>
                      </button>
                    </div>
                    {targetTask === 'signal_recognition' && (
                      <label className="mt-3 flex flex-col gap-1 text-xs text-slate-400">
                        Signal Type
                        <input
                          value={signalType}
                          onChange={(e) => setSignalType(e.target.value)}
                          placeholder="e.g. WiFi_2.4GHz, BLE, LoRa_868"
                          className={inputClass}
                        />
                      </label>
                    )}
                  </div>

                  {/* Auto QC */}
                  <label className="flex items-center gap-2 text-xs text-slate-300">
                    <input
                      type="checkbox"
                      checked={autoQcEnabled}
                      onChange={(e) => setAutoQcEnabled(e.target.checked)}
                    />
                    Auto QC – reject events with low SNR, saturation or clipping
                  </label>
                </div>
              )}
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <div className="text-xs uppercase text-slate-500">Capture Purpose</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                {(['train', 'val', 'predict'] as const).map((split) => (
                  <button
                    key={split}
                    type="button"
                    onClick={() => setDatasetSplit(split)}
                    className={cn(
                      'rounded-md border p-3 text-left text-sm transition',
                      datasetSplit === split
                        ? 'border-emerald-500 bg-emerald-500/10 text-white'
                        : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                    )}
                  >
                    <div className="font-semibold uppercase">{split}</div>
                    <div className="mt-2 text-xs text-slate-400">{splitHelp[split]}</div>
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Label
                <input value={label} onChange={(event) => { setAutoApplyBandProfile(false); setLabel(event.target.value); }} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Transmitter ID
                <input value={transmitterId} onChange={(event) => { setAutoApplyBandProfile(false); setTransmitterId(event.target.value); }} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Transmitter class
                <input value={transmitterClass} onChange={(event) => { setAutoApplyBandProfile(false); setTransmitterClass(event.target.value); }} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Session ID
                <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Operator
                <input value={operator} onChange={(event) => setOperator(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Environment
                <input value={environment} onChange={(event) => setEnvironment(event.target.value)} className={inputClass} />
              </label>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Modulation hint
                <select value={modulationHint} onChange={(event) => { setAutoApplyBandProfile(false); setModulationHint(event.target.value); }} className={inputClass}>
                  {MODULATION_HINTS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Duration s
                <input value={durationSeconds} onChange={(event) => setDurationSeconds(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                File format
                <select value={fileFormat} onChange={(event) => setFileFormat(event.target.value as 'cfile' | 'iq')} className={inputClass}>
                  <option value="cfile">CFILE</option>
                  <option value="iq">IQ</option>
                </select>
              </label>
              <label className="flex items-end gap-2 text-xs text-slate-400">
                <input type="checkbox" checked={autoImport} onChange={(event) => setAutoImport(event.target.checked)} />
                Auto-import to fingerprinting
              </label>
              <button
                onClick={captureSignal}
                disabled={isCapturing || !activeBand}
                className={cn(
                  'inline-flex h-9 items-center justify-center self-end rounded-md px-4 text-sm font-semibold',
                  isCapturing || !activeBand || Boolean(captureValidationMessage)
                    ? 'cursor-not-allowed bg-slate-700 text-slate-400'
                    : 'bg-emerald-600 text-white hover:bg-emerald-500',
                )}
              >
                <Play className="mr-2 h-4 w-4" />
                {isCapturing
                  ? (captureMode === 'triggered_burst' ? 'Waiting for trigger...' : 'Capturing...')
                  : (captureMode === 'triggered_burst' ? `Trigger ${fileFormat.toUpperCase()}` : `Capture ${fileFormat.toUpperCase()}`)}
              </button>
            </div>

            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Notes
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                rows={3}
                placeholder="Device state, distance, scenario, antenna setup, or dataset notes"
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
              />
            </label>

            {error && <div className="text-sm text-red-300">{error}</div>}
            {success && <div className="text-sm text-emerald-300">{success}</div>}
          </div>

          <div className="rounded-md border border-slate-800 bg-slate-900 p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4" />
              What this capture now does
            </h3>
            <div className="space-y-2 text-sm text-slate-300">
              <p>1. Captura IQ real del USRP entre M1 y M2 o con frecuencias personalizadas.</p>
              <p>2. Guarda metadata con split experimental: train, val o predict.</p>
              <p>3. Si activas auto-import, registra la captura en el flujo de fingerprinting.</p>
              <p>4. Ese registro luego aparece en `Dataset Builder` y se detecta automáticamente en `Training`, `Validation`, `Inference` o `Retraining` según el split.</p>
              <p>5. El banner central informa de conexión o captura sin bloquear la navegación entre pestañas.</p>
              <p>6. Esta pantalla avisa antes de lanzar configuraciones demasiado anchas para el flujo de captura científica.</p>
              <p>7. La estimación SNR en vivo del marker-band se guarda también en la metadata de la captura para trazabilidad operativa.</p>
            </div>
          </div>
        </section>

        <section className="overflow-hidden rounded-md border border-slate-800 bg-slate-900">
          <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
            <Database className="h-4 w-4" />
            <h3 className="text-sm font-semibold">Generated RF Captures</h3>
          </div>
          <div className="divide-y divide-slate-800">
            {captures.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No RF captures found.</div>
            ) : captures.map((capture) => (
              <CaptureRow
                key={capture.id}
                capture={capture}
                onDelete={deleteCapture}
                isDeleting={deletingCaptureId === capture.id}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

const inputClass =
  'h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400';

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function RfDiagnosticCard({
  diagnostic,
  titlePrefix,
  compact = false,
}: {
  diagnostic: ReturnType<typeof buildRfCaptureDiagnostic>;
  titlePrefix: string;
  compact?: boolean;
}) {
  const palette =
    diagnostic.status === 'valid'
      ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
      : diagnostic.status === 'doubtful'
        ? 'border-amber-400/40 bg-amber-500/10 text-amber-100'
        : 'border-rose-400/40 bg-rose-500/10 text-rose-100';
  return (
    <div className={cn('rounded-2xl border p-4 text-sm', palette)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold uppercase tracking-[0.18em]">{titlePrefix}: {diagnostic.title}</div>
        <span className="rounded-full border border-current/30 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em]">
          {diagnostic.status}
        </span>
      </div>
      <div className="mt-2 text-xs leading-5 opacity-90">{diagnostic.summary}</div>
      {!compact && diagnostic.facts.length > 0 && (
        <div className="mt-3 grid gap-1 text-xs opacity-90 md:grid-cols-2">
          {diagnostic.facts.map((fact) => <div key={fact}>{fact}</div>)}
        </div>
      )}
      <div className="mt-3 space-y-1 text-xs leading-5 opacity-95">
        {diagnostic.recommendations.slice(0, compact ? 2 : 4).map((item) => (
          <div key={item}>- {item}</div>
        ))}
      </div>
    </div>
  );
}

const WIFI_JOB_POLL_INTERVAL_MS = 1500;

type WifiJobState = {
  status: 'idle' | 'running' | 'done' | 'error';
  message?: string;
  reportUrl?: string;
  eventsUrl?: string;
};

function CaptureRow({
  capture,
  onDelete,
  isDeleting,
}: {
  capture: ModulatedSignalCapture;
  onDelete: (capture: ModulatedSignalCapture) => void;
  isDeleting: boolean;
}) {
  const [wifiJob, setWifiJob] = useState<WifiJobState>({ status: 'idle' });
  const iqUrl = apiService.getModulatedSignalIqUrl(capture.id);
  const metadataUrl = apiService.getModulatedSignalMetadataUrl(capture.id);
  const fileFormat = (capture.file_format || (capture.iq_file?.toLowerCase().endsWith('.iq') ? 'iq' : 'cfile')).toUpperCase();
  const shaPreview = capture.sha256 ? `${capture.sha256.slice(0, 16)}...` : 'n/a';
  const gainLabel = Number.isFinite(capture.gain_db) ? `${capture.gain_db.toFixed(1)} dB` : 'n/a';
  const capturedDurationLabel = Number.isFinite(capture.trigger_capture?.captured_duration_s)
    ? `${capture.trigger_capture?.captured_duration_s?.toFixed(3)} s`
    : Number.isFinite(capture.duration_seconds)
      ? `${capture.duration_seconds.toFixed(3)} s`
      : 'n/a';
  const postCaptureDiagnostic = buildRfCaptureDiagnostic({
    source: 'live',
    centerFrequencyHz: capture.center_frequency_hz,
    bandwidthHz: capture.bandwidth_hz,
    peakFrequencyHz: capture.preview_metrics?.live_preview_peak_frequency_hz,
    snrDb: capture.preview_metrics?.live_preview_snr_db,
    canonicalizationEnabled: true,
  });

  const demodulateWifi = async () => {
    setWifiJob({ status: 'running', message: 'Starting worker...' });
    try {
      const { job_id: jobId } = await apiService.startWifiDemodulationJob({
        sample_id: capture.id,
        file_path: capture.iq_file,
        file_format: capture.file_format,
        // Capture Lab always writes complex64 (interleaved float32 I/Q) on disk
        // regardless of file_format/iq_dtype label -- the wifi_80211 worker uses
        // its own datatype vocabulary (cf32_le/ci16_le/cu8), so translate here.
        datatype: 'cf32_le',
        sample_rate_hz: capture.sample_rate_hz,
        center_frequency_hz: capture.center_frequency_hz,
        hardware_center_frequency_hz: capture.center_frequency_hz,
        channel_center_frequency_hz: capture.center_frequency_hz,
        bandwidth_hz: capture.bandwidth_hz,
        channel_width_hz: capture.bandwidth_hz,
        capture_duration: capture.duration_seconds,
        source_dataset: 'capture_lab',
        pipeline: 'wifi_80211',
        temporal_order_known: true,
      });

      const poll = async () => {
        try {
          const job = await apiService.getWifiDemodulationJobStatus(jobId);
          if (job.status === 'done') {
            const report = job.result || {};
            const framesConfirmed = report.frames_decoded ?? 0;
            setWifiJob({
              status: 'done',
              message: `${framesConfirmed} frame(s) confirmed (partial recovery -- not every transmitted frame is recovered).`,
              reportUrl: report.outputs?.report ? apiService.getDemodulationOutputUrl(report.id || capture.id, 'demodulation_report.json') : undefined,
              eventsUrl: report.outputs?.receiver_internal_events
                ? apiService.getDemodulationOutputUrl(report.id || capture.id, 'receiver_internal_events.jsonl')
                : undefined,
            });
            return;
          }
          if (job.status === 'error') {
            setWifiJob({ status: 'error', message: job.message || job.error || 'Demodulation job failed.' });
            return;
          }
          setWifiJob({ status: 'running', message: job.message || 'Running worker...' });
          setTimeout(poll, WIFI_JOB_POLL_INTERVAL_MS);
        } catch (err) {
          setWifiJob({ status: 'error', message: getErrorMessage(err) });
        }
      };
      setTimeout(poll, WIFI_JOB_POLL_INTERVAL_MS);
    } catch (err) {
      setWifiJob({ status: 'error', message: getErrorMessage(err) });
    }
  };

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">
            {capture.label || capture.id} | {fileFormat} | {formatFrequency(capture.center_frequency_hz)} | BW {formatFrequency(capture.bandwidth_hz)}
          </div>
          <div className="text-xs text-slate-400">
            {(capture.dataset_split || 'train')} | {capture.session_id || 'no_session'} | {capture.modulation_hint || 'unknown'} | {capture.duration_seconds}s | {formatFrequency(capture.sample_rate_hz)}/s | {formatBytes(capture.file_size_bytes)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={iqUrl} className="inline-flex h-9 items-center rounded-md bg-blue-600 px-3 text-sm font-medium hover:bg-blue-500">
            <Download className="mr-2 h-4 w-4" />
            {fileFormat}
          </a>
          <a href={metadataUrl} className="inline-flex h-9 items-center rounded-md bg-slate-700 px-3 text-sm font-medium hover:bg-slate-600">
            <Download className="mr-2 h-4 w-4" />
            JSON
          </a>
          {BLE_ANALYZER_ENABLED && (
            <button type="button" disabled title={BLE_DSP_UNAVAILABLE_REASON} aria-label={`Analyze in BLE Lab. ${BLE_DSP_UNAVAILABLE_REASON}`} className="inline-flex h-9 cursor-not-allowed items-center rounded-md border border-cyan-700 bg-cyan-950/40 px-3 text-sm font-medium text-cyan-200 opacity-60">
              <Bluetooth className="mr-2 h-4 w-4" />Analyze in BLE Lab
            </button>
          )}
          <button
            type="button"
            onClick={demodulateWifi}
            disabled={wifiJob.status === 'running'}
            className="inline-flex h-9 items-center rounded-md bg-indigo-600 px-3 text-sm font-medium hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Wifi className="mr-2 h-4 w-4" />
            {wifiJob.status === 'running' ? 'Demodulating...' : 'Demodulate Wi-Fi'}
          </button>
          <button
            type="button"
            onClick={() => onDelete(capture)}
            disabled={isDeleting}
            className="inline-flex h-9 items-center rounded-md border border-red-500/40 bg-red-950/60 px-3 text-sm font-medium text-red-100 hover:bg-red-900/70 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            {isDeleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 text-xs text-slate-400 md:grid-cols-3">
        <div>Start: {formatFrequency(capture.start_frequency_hz)}</div>
        <div>Stop: {formatFrequency(capture.stop_frequency_hz)}</div>
        <div>Gain: {gainLabel}</div>
        <div>Antenna: {capture.antenna || 'unknown'}</div>
        <div>Artifact scope: {capture.external_iq_file ? 'external/stale IQ path' : 'local project storage'}</div>
        <div>Tx ID: {capture.transmitter_id || 'unknown'}</div>
        <div>Class: {capture.transmitter_class || 'unknown'}</div>
        <div>Operator: {capture.operator || 'unknown'}</div>
        <div>Environment: {capture.environment || 'unknown'}</div>
        <div>SHA256: {shaPreview}</div>
        <div>Live preview SNR: {capture.preview_metrics?.live_preview_snr_db?.toFixed(1) ?? 'n/a'} dB</div>
        <div>Live preview noise: {capture.preview_metrics?.live_preview_noise_floor_db !== undefined ? formatPowerLevel(capture.preview_metrics.live_preview_noise_floor_db) : 'n/a'}</div>
        <div>Live preview peak: {capture.preview_metrics?.live_preview_peak_level_db !== undefined ? formatPowerLevel(capture.preview_metrics.live_preview_peak_level_db) : 'n/a'}</div>
        <div>Capture mode: {capture.trigger_capture?.mode || 'immediate'}</div>
        {capture.trigger_capture?.strategy && (
          <div>Strategy: {capture.trigger_capture.strategy.replace('_trigger', '').replace('_', ' ')}</div>
        )}
        <div>Trigger detected: {capture.trigger_capture?.trigger_detected === undefined ? 'n/a' : String(capture.trigger_capture.trigger_detected)}</div>
        <div>Captured duration: {capturedDurationLabel}</div>
        {capture.trigger_capture?.snr_db !== undefined && (
          <div>Trigger SNR: {capture.trigger_capture.snr_db.toFixed(1)} dB</div>
        )}
        {capture.trigger_capture?.session_events_captured !== undefined && (
          <div>Session events: {capture.trigger_capture.session_events_captured} captured / {capture.trigger_capture.session_events_qc_passed ?? '?'} QC-passed</div>
        )}
      </div>

      <RfDiagnosticCard diagnostic={postCaptureDiagnostic} titlePrefix="Post-capture intelligence" compact />

      {wifiJob.status !== 'idle' && (
        <div
          className={cn(
            'rounded-md border p-2 text-xs',
            wifiJob.status === 'error'
              ? 'border-rose-500/40 bg-rose-950/40 text-rose-100'
              : wifiJob.status === 'done'
                ? 'border-emerald-500/40 bg-emerald-950/40 text-emerald-100'
                : 'border-slate-600/40 bg-slate-800/40 text-slate-200',
          )}
        >
          <div>{wifiJob.message}</div>
          {wifiJob.status === 'done' && (
            <div className="mt-1 flex gap-3">
              {wifiJob.reportUrl && (
                <a href={wifiJob.reportUrl} className="underline hover:text-white">
                  Demodulation report
                </a>
              )}
              {wifiJob.eventsUrl && (
                <a href={wifiJob.eventsUrl} className="underline hover:text-white">
                  Receiver diagnostics (receiver_internal_events.jsonl)
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {capture.external_iq_file && (
        <div className="rounded-md border border-amber-500/30 bg-amber-950/40 p-2 text-xs text-amber-100">
          This metadata record points to an IQ file outside the current project storage. Delete removes the local metadata/registry entry and will not touch that external file.
        </div>
      )}
      {capture.notes && <div className="text-sm text-slate-300">{capture.notes}</div>}
    </div>
  );
}
