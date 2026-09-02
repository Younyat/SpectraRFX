import { useEffect, useRef, useState } from 'react';
import { AiResearchPluginApiError, AiResearchPluginClient } from '../../ai-research-plugin/api/aiResearchPluginClient';
import type { InferenceRecord, InputRepresentation, RFModelInputFields, RFModelManifest, RFModelOutputFields } from '../../ai-research-plugin/types';
import type { AiLiveDetection } from '../model/rfTerrainTypes';
import type { RFTerrainFrequencyInfo } from '../ui/RFTerrainToolbar';
import { lookupKnownRfTerm } from './knownRfTerms';

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
// A guaranteed-to-fail request (e.g. a real tensor-rank mismatch) never
// becomes less guaranteed-to-fail by retrying -- stop hammering the
// backend/onnxruntime after this many CONSECUTIVE failures instead of
// looping forever on the same error every MIN_POLL_INTERVAL_MS. Reset to
// 0 on any success, so one transient SDR hiccup never trips it.
const MAX_CONSECUTIVE_ERRORS = 3;

export interface FrequencyApplicability {
  applicable: boolean;
  // Empty when applicable and the model does declare a frequency (a real,
  // positive match -- nothing to caveat). Non-empty either as a hard
  // mismatch explanation or an honest "unknown" disclaimer.
  reason: string;
}

// Real, known SHAPE TEMPLATE each adapter (adapters.py) produces, given
// the model's own declared last dimension (N samples, or 2N for FLAT_IQ's
// interleaved vector -- _infer_required_sample_count derives the LIVE
// snapshot's real sample count from exactly this number, so the produced
// last dim always equals it by construction). `null` entries are axes
// this plugin genuinely cannot predict without a model-specific parameter
// it doesn't expose (spectrogram/psd's FFT window size) -- never guessed.
// Non-null entries (batch, channel counts) are architecturally FIXED by
// the adapter and checked exactly: this is what catches a mismatch rank
// alone would miss -- e.g. a real model declaring a fixed batch of 8
// ([8,3,224,224]) against spectrogram's real batch=1, channel=1 output
// ([1,1,F,T]) -- same rank (4), but onnxruntime still rejects it (a real
// failure this exact check reproduced and now catches before ever
// touching the backend).
const SHAPE_TEMPLATES: Partial<Record<InputRepresentation, (declaredLastDim: number) => (number | null)[]>> = {
  iq_tensor: (n) => [1, 2, n],
  raw_iq: (n) => [1, 2, n],
  flat_iq: (n) => [1, n],
  spectrogram: () => [1, 1, null, null],
  psd: () => [1, null],
};

const shapesCompatible = (declared: (number | null)[], produced: (number | null)[]): boolean =>
  declared.length === produced.length
  && declared.every((expected, i) => expected === null || produced[i] === null || expected === produced[i]);

export interface RepresentationApplicability {
  compatible: boolean;
  reason: string;
}

// A real, PRE-FLIGHT shape check (no network call) -- catches the exact
// classes of failure real models produced during testing, before ever
// hitting the backend with a request guaranteed to fail. A model with no
// declared shape can't be ruled out this way -- stays "compatible"
// (unknown, not confirmed) rather than blocked.
export function checkRepresentationCompatibility(
  model: RFModelManifest | undefined,
  representation: InputRepresentation,
): RepresentationApplicability {
  if (!model) return { compatible: false, reason: 'No model selected.' };
  const input = mergeEffectiveInput(model);
  const declaredShape = input.tensor_shape;
  if (declaredShape === null || declaredShape === undefined) return { compatible: true, reason: '' };

  const templateFn = SHAPE_TEMPLATES[representation];
  if (!templateFn) {
    return {
      compatible: false,
      reason: `The "${representation}" representation has no adapter implemented in this plugin yet.`,
    };
  }
  const declaredLastDim = declaredShape[declaredShape.length - 1];
  const producedShape = templateFn(declaredLastDim ?? 0);
  if (shapesCompatible(declaredShape, producedShape)) return { compatible: true, reason: '' };

  const shapeText = `[${declaredShape.map((d) => (d === null ? '?' : d)).join(', ')}]`;
  const producedText = `[${producedShape.map((d) => (d === null ? '?' : d)).join(', ')}]`;
  return {
    compatible: false,
    reason: `This model declares input ${shapeText}, but "${representation}" produces ${producedText} -- onnxruntime will reject every attempt. None of iq_tensor/flat_iq/spectrogram/psd may be the representation this model actually needs (raw declared shape shown above); check its real preprocessing requirements before running.`,
  };
}

const mergeEffectiveInput = (model: RFModelManifest): RFModelInputFields => ({
  ...model.input_discovered,
  ...Object.fromEntries(Object.entries(model.input_overrides).filter(([, value]) => value !== null)),
} as RFModelInputFields);

const mergeEffectiveOutput = (model: RFModelManifest): RFModelOutputFields => ({
  ...model.output_discovered,
  ...Object.fromEntries(Object.entries(model.output_overrides).filter(([, value]) => value !== null)),
} as RFModelOutputFields);

// A whole-snippet classifier has no per-detection frequency localization
// -- it says "this analyzed window looks like class X", not "the signal
// occupies exactly this many Hz". Rather than pretend otherwise (the real
// bug this replaces: using the CAPTURE's sample rate, which can span the
// entire visible terrain), the 3D highlight uses a real, operator-
// declared signal bandwidth when the model provides one, and otherwise a
// small, honestly-disclosed marker scaled to a modest fraction of the
// current visible span -- never the full analysis bandwidth.
const FALLBACK_MARKER_SPAN_FRACTION = 0.02;
const FALLBACK_MARKER_MIN_HZ = 50_000;

function resolveDetectionBandwidth(
  model: RFModelManifest,
  frequencyInfo: RFTerrainFrequencyInfo | null,
): { bandwidthHz: number; bandwidthIsKnown: boolean } {
  const declared = mergeEffectiveInput(model).expected_signal_bandwidth_hz;
  if (declared != null && declared > 0) {
    return { bandwidthHz: declared, bandwidthIsKnown: true };
  }
  const spanHz = frequencyInfo?.spanHz ?? 0;
  return {
    bandwidthHz: Math.max(FALLBACK_MARKER_MIN_HZ, spanHz * FALLBACK_MARKER_SPAN_FRACTION),
    bandwidthIsKnown: false,
  };
}

function resolveClassDescription(
  model: RFModelManifest,
  predictedClass: string | null,
): AiLiveDetection['classDescription'] {
  if (!predictedClass) return null;
  const modelDescription = mergeEffectiveOutput(model).class_descriptions?.[predictedClass];
  if (modelDescription) return { text: modelDescription, source: 'MODEL_OVERRIDE' };
  const knownTerm = lookupKnownRfTerm(predictedClass);
  if (knownTerm) return { text: knownTerm, source: 'KNOWN_TERM' };
  return null;
}

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

const extractPredictedClass = (record: InferenceRecord): string | null =>
  record.interpretation.kind === 'classification' ? record.interpretation.predicted_class ?? null : null;

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
  representationApplicability: RepresentationApplicability | null;
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
  const [representationApplicability, setRepresentationApplicability] = useState<RepresentationApplicability | null>(null);
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
  const consecutiveErrorsRef = useRef(0);

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
    const currentRepresentationApplicability = checkRepresentationCompatibility(model, representationRef.current);
    setRepresentationApplicability(currentRepresentationApplicability);
    if (!model || !currentApplicability.applicable) return;
    if (!currentRepresentationApplicability.compatible) {
      // A guaranteed-to-fail shape mismatch -- never even attempted, and
      // continuous mode stops outright rather than re-checking (and
      // re-displaying the same refusal) every MIN_POLL_INTERVAL_MS forever.
      setLatestError(currentRepresentationApplicability.reason);
      stoppedRef.current = true;
      setContinuousEnabled(false);
      return;
    }

    setBusy(true);
    const clientStartedAt = performance.now();
    try {
      const record = await client.runInferenceLive(modelId, representationRef.current);
      const clientRoundTripMs = performance.now() - clientStartedAt;
      consecutiveErrorsRef.current = 0;
      setLatestRecord(record);
      setLatestError(null);
      setPollCount((prev) => prev + 1);

      const { bandwidthHz, bandwidthIsKnown } = resolveDetectionBandwidth(model, frequencyInfoRef.current);
      const predictedClass = extractPredictedClass(record);
      const detection: AiLiveDetection = {
        id: `AI-DETECTION-${record.record_id}`,
        modelId,
        modelName: model.model_name,
        detectedAtUtc: record.inference_timestamp_utc,
        centerFrequencyHz: frequencyInfoRef.current?.centerFrequencyHz ?? 0,
        bandwidthHz,
        bandwidthIsKnown,
        summary: summarizeRecord(record),
        predictedClass,
        classDescription: resolveClassDescription(model, predictedClass),
        totalLatencyMs: record.total_latency_ms ?? clientRoundTripMs,
      };
      setDetections((prev) => [detection, ...prev].slice(0, MAX_DETECTION_HISTORY));
      onDetectionRef.current?.(detection);
    } catch (e) {
      const message = e instanceof AiResearchPluginApiError ? e.message : String(e);
      consecutiveErrorsRef.current += 1;
      if (consecutiveErrorsRef.current >= MAX_CONSECUTIVE_ERRORS) {
        setLatestError(`Stopped after ${consecutiveErrorsRef.current} consecutive failures: ${message}`);
        stoppedRef.current = true;
        setContinuousEnabled(false);
      } else {
        setLatestError(message);
      }
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
      // A deliberate "Start continuous" click always gets a fresh
      // MAX_CONSECUTIVE_ERRORS budget -- otherwise a manual retry right
      // after an auto-stop inherits the old streak and can report e.g.
      // "Stopped after 4" on its very first new attempt.
      consecutiveErrorsRef.current = 0;
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

  // Same immediacy as the frequency check above, for the shape/rank
  // pre-flight -- the operator sees "this won't work" the moment they pick
  // an incompatible representation, not only after Start Continuous fires
  // a doomed first request.
  useEffect(() => {
    const model = models.find((m) => m.model_id === selectedModelId);
    setRepresentationApplicability(checkRepresentationCompatibility(model, representation));
  }, [models, selectedModelId, representation]);

  // Real bug this fixes: switching to a different (or newly-incompatible)
  // model/representation left the PREVIOUS model's error and "Latest
  // detection" summary visible underneath the new applicability warning --
  // reading as if the new model had produced them. A model/representation
  // change always starts a clean slate for these two, and for the
  // consecutive-failure counter (a fresh model deserves a fresh chance,
  // not to inherit a previous model's failure streak). `detections` (the
  // running history list) is deliberately left alone -- that is a log,
  // not a "current status" readout.
  useEffect(() => {
    setLatestError(null);
    setLatestRecord(null);
    consecutiveErrorsRef.current = 0;
  }, [selectedModelId, representation]);

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
    representationApplicability,
    latestRecord,
    latestError,
    detections,
    pollCount,
    busy,
    runOnce: runOnceInternal,
  };
}
