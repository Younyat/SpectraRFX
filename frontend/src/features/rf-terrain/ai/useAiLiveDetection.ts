import { useEffect, useRef, useState } from 'react';
import { AiResearchPluginApiError, AiResearchPluginClient } from '../../ai-research-plugin/api/aiResearchPluginClient';
import type { InferenceRecord, InputRepresentation, RFModelInputFields, RFModelManifest } from '../../ai-research-plugin/types';
import type { AiLiveDetection } from '../model/rfTerrainTypes';
import type { RFTerrainFrequencyInfo } from '../ui/RFTerrainToolbar';

const client = new AiResearchPluginClient();

// A real floor on how often a new live snapshot+inference round-trip can
// be requested -- protects both the SDR worker and onnxruntime from being
// hammered if a model happens to respond in a few ms, and gives the
// operator an honest, bounded "at most this often" answer to "is this
// real-time". Never fires the NEXT request before the previous one has
// fully resolved (real backpressure, no overlap) -- so the actual
// cadence is max(MIN_POLL_INTERVAL_MS, measured round-trip).
const MIN_POLL_INTERVAL_MS = 800;
const MAX_DETECTION_HISTORY = 30;

export interface FrequencyApplicability {
  applicable: boolean;
  // Empty when applicable and the model does declare a frequency (a real,
  // positive match -- nothing to caveat). Non-empty either as a hard
  // mismatch explanation or an honest "unknown" disclaimer.
  reason: string;
}

const mergeEffectiveInput = (model: RFModelManifest): RFModelInputFields => ({
  ...model.input_discovered,
  ...Object.fromEntries(Object.entries(model.input_overrides).filter(([, value]) => value !== null)),
} as RFModelInputFields);

export function checkFrequencyApplicability(
  model: RFModelManifest | undefined,
  frequencyInfo: RFTerrainFrequencyInfo | null,
): FrequencyApplicability {
  if (!model) return { applicable: false, reason: 'No model selected.' };
  const input = mergeEffectiveInput(model);
  if (input.expected_center_frequency_hz == null) {
    return {
      applicable: true,
      reason: 'This model does not declare an expected frequency -- applicability at the current tuning is unknown, not confirmed. Set it via a model override to enable this check.',
    };
  }
  if (!frequencyInfo) {
    return { applicable: false, reason: 'Live tuning information is not available yet.' };
  }
  const tolerance = input.expected_frequency_tolerance_hz ?? 0;
  const diff = Math.abs(frequencyInfo.centerFrequencyHz - input.expected_center_frequency_hz);
  if (diff <= tolerance) return { applicable: true, reason: '' };
  const expectedMHz = (input.expected_center_frequency_hz / 1e6).toFixed(3);
  const toleranceMHz = (tolerance / 1e6).toFixed(3);
  const currentMHz = (frequencyInfo.centerFrequencyHz / 1e6).toFixed(3);
  return {
    applicable: false,
    reason: `This model isn't applicable here -- it expects ~${expectedMHz} MHz (±${toleranceMHz} MHz), but the receiver is currently tuned to ${currentMHz} MHz. Its effect can't be shown at this frequency.`,
  };
}

const summarizeRecord = (record: InferenceRecord): string => {
  if (record.interpretation.kind === 'classification') {
    const score = record.interpretation.score != null ? record.interpretation.score.toFixed(3) : '?';
    return `${record.interpretation.predicted_class ?? 'unknown class'} (${record.interpretation.score_type ?? 'score'}=${score})`;
  }
  if (record.interpretation.kind === 'embedding') {
    return `embedding, dim=${record.interpretation.dimensionality ?? '?'}`;
  }
  return 'not automatically interpretable';
};

export interface UseAiLiveDetectionOptions {
  frequencyInfo: RFTerrainFrequencyInfo | null;
  onDetection?: (detection: AiLiveDetection) => void;
}

export interface UseAiLiveDetectionResult {
  models: RFModelManifest[];
  refreshModels: () => Promise<void>;
  selectedModelId: string;
  setSelectedModelId: (id: string) => void;
  representation: InputRepresentation;
  setRepresentation: (representation: InputRepresentation) => void;
  liveAvailable: boolean | null;
  continuousEnabled: boolean;
  setContinuousEnabled: (enabled: boolean) => void;
  applicability: FrequencyApplicability | null;
  latestRecord: InferenceRecord | null;
  latestError: string | null;
  detections: AiLiveDetection[];
  pollCount: number;
  busy: boolean;
  runOnce: () => Promise<void>;
}

// Continuous LIVE model application: as soon as a model is selected and
// continuous mode is on, this repeatedly captures a bounded live I/Q
// snapshot and runs inference against it -- the same one-shot
// runInferenceLive() the panel already used, just wrapped in a
// self-scheduling loop with real backpressure (never overlaps requests)
// and a frequency-applicability gate checked before every single tick
// (so retuning away from a model's declared band pauses it automatically,
// and retuning back resumes it, without the operator toggling anything).
export function useAiLiveDetection({ frequencyInfo, onDetection }: UseAiLiveDetectionOptions): UseAiLiveDetectionResult {
  const [models, setModels] = useState<RFModelManifest[]>([]);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [representation, setRepresentation] = useState<InputRepresentation>('iq_tensor');
  const [liveAvailable, setLiveAvailable] = useState<boolean | null>(null);
  const [continuousEnabled, setContinuousEnabled] = useState(false);
  const [applicability, setApplicability] = useState<FrequencyApplicability | null>(null);
  const [latestRecord, setLatestRecord] = useState<InferenceRecord | null>(null);
  const [latestError, setLatestError] = useState<string | null>(null);
  const [detections, setDetections] = useState<AiLiveDetection[]>([]);
  const [pollCount, setPollCount] = useState(0);
  const [busy, setBusy] = useState(false);

  // Refs mirror the latest state for the self-scheduling loop below, so
  // the loop function never closes over a stale value without having to
  // be torn down and recreated every render (same idiom RFTerrainCanvas
  // uses for modeRef/colormapRef/etc.).
  const modelsRef = useRef(models);
  modelsRef.current = models;
  const selectedModelIdRef = useRef(selectedModelId);
  selectedModelIdRef.current = selectedModelId;
  const representationRef = useRef(representation);
  representationRef.current = representation;
  const frequencyInfoRef = useRef(frequencyInfo);
  frequencyInfoRef.current = frequencyInfo;
  const onDetectionRef = useRef(onDetection);
  onDetectionRef.current = onDetection;

  const timeoutRef = useRef<number | null>(null);
  const stoppedRef = useRef(true);

  const refreshModels = async () => {
    try {
      setModels(await client.listModels());
    } catch (e) {
      setLatestError(e instanceof AiResearchPluginApiError ? e.message : String(e));
    }
  };

  useEffect(() => {
    refreshModels();
    client.getStatus().then((s) => setLiveAvailable(s.live_inference_available)).catch(() => setLiveAvailable(null));
  }, []);

  const runOnceInternal = async (): Promise<void> => {
    const modelId = selectedModelIdRef.current;
    const model = modelsRef.current.find((m) => m.model_id === modelId);
    const currentApplicability = checkFrequencyApplicability(model, frequencyInfoRef.current);
    setApplicability(currentApplicability);
    if (!model || !currentApplicability.applicable) return;

    setBusy(true);
    const clientStartedAt = performance.now();
    try {
      const record = await client.runInferenceLive(modelId, representationRef.current);
      const clientRoundTripMs = performance.now() - clientStartedAt;
      setLatestRecord(record);
      setLatestError(null);
      setPollCount((prev) => prev + 1);

      const detection: AiLiveDetection = {
        id: `AI-DETECTION-${record.record_id}`,
        modelId,
        modelName: model.model_name,
        detectedAtUtc: record.inference_timestamp_utc,
        centerFrequencyHz: frequencyInfoRef.current?.centerFrequencyHz ?? 0,
        bandwidthHz: record.compatibility.checks.find((c) => c.field === 'sample_rate_hz')?.capture_value as number ?? frequencyInfoRef.current?.sampleRateHz ?? 0,
        summary: summarizeRecord(record),
        totalLatencyMs: record.total_latency_ms ?? clientRoundTripMs,
      };
      setDetections((prev) => [detection, ...prev].slice(0, MAX_DETECTION_HISTORY));
      onDetectionRef.current?.(detection);
    } catch (e) {
      setLatestError(e instanceof AiResearchPluginApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const scheduleNext = (delayMs: number) => {
    if (stoppedRef.current) return;
    timeoutRef.current = window.setTimeout(async () => {
      const tickStartedAt = performance.now();
      await runOnceInternal();
      if (stoppedRef.current) return;
      const elapsed = performance.now() - tickStartedAt;
      scheduleNext(Math.max(0, MIN_POLL_INTERVAL_MS - elapsed));
    }, delayMs);
  };

  useEffect(() => {
    stoppedRef.current = !continuousEnabled;
    if (continuousEnabled) {
      scheduleNext(0);
    } else if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    return () => {
      stoppedRef.current = true;
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the loop reads everything else via refs on purpose
  }, [continuousEnabled]);

  // Recompute applicability immediately on model/frequency change even
  // while paused, so the "not applicable here" message is honest before
  // the operator ever turns continuous mode on. Deliberately depends on
  // the real PRIMITIVE value (centerFrequencyHz), never the frequencyInfo
  // OBJECT itself: the caller (RFTerrainView) constructs a fresh object
  // on every real spectrum row (~10 Hz) even when the tuned frequency
  // hasn't changed, so depending on object identity here re-fires this
  // effect (and its setState) on every single row -- confirmed via a
  // real OOM crash in this hook's own test suite (an unbounded
  // render->effect->setState->render loop) before this fix.
  useEffect(() => {
    const model = models.find((m) => m.model_id === selectedModelId);
    setApplicability(checkFrequencyApplicability(model, frequencyInfoRef.current));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- frequencyInfoRef.current is read fresh each run; only its centerFrequencyHz should re-trigger this effect
  }, [models, selectedModelId, frequencyInfo?.centerFrequencyHz]);

  return {
    models,
    refreshModels,
    selectedModelId,
    setSelectedModelId,
    representation,
    setRepresentation,
    liveAvailable,
    continuousEnabled,
    setContinuousEnabled,
    applicability,
    latestRecord,
    latestError,
    detections,
    pollCount,
    busy,
    runOnce: runOnceInternal,
  };
}
