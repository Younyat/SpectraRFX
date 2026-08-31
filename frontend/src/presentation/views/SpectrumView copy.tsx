import React, { useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, BrainCircuit, ChevronLeft, ChevronRight, Download, Eye, EyeOff, FlaskConical, Image, Move, Play, Square, RotateCcw, ScanSearch, Target, Usb, Unplug, Radio, Trash2, SlidersHorizontal, X } from 'lucide-react';
import { useSpectrum } from '../hooks/useSpectrum';
import { useWaterfall } from '../hooks/useWaterfall';
import { useSpectrumController } from '../controllers/SpectrumController';
import { getLevelAtFrequency, useMarkerController } from '../controllers/MarkerController';
import { useAnalyzerSettings, useAppActions, useDeviceStatus, useMarkers, useSpectrumData, useWaterfallData } from '../../app/store/AppStore';
import { ApiService } from '../../app/services/ApiService';
import { estimateBandQuality, formatFrequency, formatPowerLevel } from '../../shared/utils';
import { cn } from '../../shared/utils';
import { DETECTOR_MODES, SPECTRUM_COLOR_SCHEMES, TRACE_MODES } from '../../shared/constants';
import { RF_PROFILE_LIST, RF_PROFILE_STORAGE_KEY, RF_PROFILES, applyRFProfile } from '../../shared/rfProfiles';
import type { AnalyzerSettings, RFObjectDetection, RFSceneAnalysis, RFSignalUnderstandingResult, SpectrumData, WaterfallData } from '../../shared/types';

const hzToMhz = (hz: number) => Number.isFinite(hz) ? hz / 1e6 : 0;
const mhzToHz = (mhz: string) => Number(mhz) * 1e6;
const khzToHz = (khz: string) => Number(khz) * 1e3;
const spectrumOverlayStorageKey = 'spectrum-view-overlay-preferences';
const apiService = new ApiService();
const AUTO_FREEZE_TRIGGER_SNR_DB = 15;
const AUTO_FREEZE_MIN_ABOVE_NOISE_DB = 6;
const AUTO_FREEZE_MIN_REGION_BINS = 3;
const AUTO_FREEZE_MIN_RELATIVE_BW = 0.3;
const AUTO_FREEZE_MAX_RELATIVE_BW = 0.7;
const AUTO_FREEZE_FRAME_BUFFER_SIZE = 12;
const MARKER_BANDPASS_ATTENUATION_DB = 60;
const markerBandpassStorageKey = 'spectrum-view-marker-bandpass-settings';

const RF_EXPERIMENT_TYPE_LABELS = {
  best: 'Best validated model',
  e5: 'E5 Spectral Feature',
  e1: 'E1 Raw IQ CNN 1D',
  e3: 'E3 Spectrogram CNN 2D',
} as const;

const RF_EXPERIMENT_TYPE_NAMES = {
  e5: 'e5_spectral_feature_baseline',
  e1: 'e1_raw_iq_cnn1d',
  e3: 'e3_spectrogram_cnn2d',
} as const;

const formatInput = (value: number, digits = 6) => {
  if (!Number.isFinite(value)) return '';
  return Number(value.toFixed(digits)).toString();
};

const computeStats = (levels: number[]) => {
  const finite = levels.filter(Number.isFinite);
  if (finite.length === 0) {
    return { min: Number.NaN, max: Number.NaN, mean: Number.NaN, std: Number.NaN };
  }
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const mean = finite.reduce((sum, value) => sum + value, 0) / finite.length;
  const variance = finite.reduce((sum, value) => sum + (value - mean) ** 2, 0) / finite.length;
  return { min, max, mean, std: Math.sqrt(variance) };
};

const findLocalPeaks = (frequencies: number[], levels: number[], count = 3) => {
  const peaks: Array<{ frequency: number; level: number }> = [];
  for (let index = 1; index < levels.length - 1; index += 1) {
    const level = levels[index];
    if (Number.isFinite(level) && level >= levels[index - 1] && level >= levels[index + 1]) {
      peaks.push({ frequency: frequencies[index], level });
    }
  }
  return peaks.sort((a, b) => b.level - a.level).slice(0, count);
};

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

const findStrongestPeak = (frequencies: number[], levels: number[]) => {
  if (frequencies.length === 0 || levels.length === 0 || frequencies.length !== levels.length) {
    return null;
  }
  let peakIndex = 0;
  let peakLevel = -Infinity;
  for (let index = 0; index < levels.length; index += 1) {
    const level = levels[index];
    if (Number.isFinite(level) && level > peakLevel) {
      peakLevel = level;
      peakIndex = index;
    }
  }
  const peakFrequency = frequencies[peakIndex];
  if (!Number.isFinite(peakFrequency) || !Number.isFinite(peakLevel)) {
    return null;
  }
  return {
    frequency: peakFrequency,
    level: peakLevel,
  };
};

const formatBandwidth = (hz: number) => {
  if (!Number.isFinite(hz)) return 'n/a';
  if (Math.abs(hz) >= 1e6) return `${(hz / 1e6).toFixed(2)} MHz`;
  if (Math.abs(hz) >= 1e3) return `${(hz / 1e3).toFixed(1)} kHz`;
  return `${hz.toFixed(0)} Hz`;
};

const cloneSpectrumFrame = (frame: SpectrumData): SpectrumData => ({
  ...frame,
  frequencyArray: [...frame.frequencyArray],
  powerLevels: [...frame.powerLevels],
});

const applyMarkerBandpassMask = (
  frame: SpectrumData,
  band: { start: number; stop: number; span: number } | null,
  attenuationDb = MARKER_BANDPASS_ATTENUATION_DB,
): SpectrumData => {
  if (!band || band.span <= 0) return frame;
  const frameStart = frame.centerFrequency - frame.span / 2;
  const frameStop = frame.centerFrequency + frame.span / 2;
  if (band.start < frameStart || band.stop > frameStop) return frame;

  return {
    ...frame,
    powerLevels: frame.powerLevels.map((level, index) => {
      const frequency = frame.frequencyArray[index];
      if (!Number.isFinite(frequency) || frequency < band.start || frequency > band.stop) {
        return Number.isFinite(level) ? level - attenuationDb : level;
      }
      return level;
    }),
  };
};

interface AutoFreezeCandidate {
  peakFrequencyHz: number;
  peakLevelDb: number;
  noiseFloorDb: number;
  snrDb: number;
  bandwidthHz: number;
  startFrequencyHz: number;
  stopFrequencyHz: number;
  bins: number;
}

interface AutoFreezeCaptureTarget {
  candidate: AutoFreezeCandidate;
  frozenFrame: SpectrumData;
  viewRange: { centerFrequency: number; span: number };
}

interface CaptureProgressDetails {
  startFrequencyHz: number;
  stopFrequencyHz: number;
  gainDb: number;
  antenna: string;
  artifactScope: string;
  txId: string;
  class: string;
  operator: string;
  environment: string;
  sha256: string;
  livePreviewSnrDb: number | null;
  livePreviewNoiseDb: number | null;
  livePreviewPeakDb: number | null;
  captureMode: string;
  triggerDetected: boolean;
}

const findAutoFreezeCandidate = (
  frame: SpectrumData,
  band: { start: number; stop: number; span: number },
): AutoFreezeCandidate | null => {
  const quality = estimateBandQuality(frame.frequencyArray, frame.powerLevels, band.start, band.stop);
  if (!quality || quality.snrDb < AUTO_FREEZE_TRIGGER_SNR_DB) return null;

  const thresholdDb = quality.noiseFloorDb + AUTO_FREEZE_MIN_ABOVE_NOISE_DB;
  const minBandwidthHz = Math.max(1_000, band.span * AUTO_FREEZE_MIN_RELATIVE_BW);
  const maxBandwidthHz = band.span * AUTO_FREEZE_MAX_RELATIVE_BW;
  let best: AutoFreezeCandidate | null = null;
  let current: Array<{ frequency: number; level: number }> = [];

  const finishRun = () => {
    if (current.length < AUTO_FREEZE_MIN_REGION_BINS) {
      current = [];
      return;
    }
    let peak = current[0];
    current.forEach((point) => {
      if (point.level > peak.level) peak = point;
    });
    const startFrequencyHz = current[0].frequency;
    const stopFrequencyHz = current[current.length - 1].frequency;
    const bandwidthHz = Math.max(0, stopFrequencyHz - startFrequencyHz);
    if (bandwidthHz < minBandwidthHz || bandwidthHz > maxBandwidthHz) {
      current = [];
      return;
    }
    const candidate = {
      peakFrequencyHz: peak.frequency,
      peakLevelDb: peak.level,
      noiseFloorDb: quality.noiseFloorDb,
      snrDb: peak.level - quality.noiseFloorDb,
      bandwidthHz,
      startFrequencyHz,
      stopFrequencyHz,
      bins: current.length,
    };
    if (!best || candidate.snrDb > best.snrDb) best = candidate;
    current = [];
  };

  for (let index = 0; index < frame.frequencyArray.length; index += 1) {
    const frequency = frame.frequencyArray[index];
    const level = frame.powerLevels[index];
    const active = (
      Number.isFinite(frequency) &&
      Number.isFinite(level) &&
      frequency >= band.start &&
      frequency <= band.stop &&
      level >= thresholdDb
    );
    if (active) {
      current.push({ frequency, level });
    } else {
      finishRun();
    }
  }
  finishRun();
  return best;
};

const rfFamilyStyle = (family: string) => {
  if (family.includes('wifi')) return { border: 'rgba(56,189,248,0.82)', fill: 'rgba(14,165,233,0.13)', text: 'text-sky-100', badge: 'bg-sky-400/20 border-sky-300/40' };
  if (family.includes('fm') || family.includes('broadcast')) return { border: 'rgba(52,211,153,0.82)', fill: 'rgba(16,185,129,0.13)', text: 'text-emerald-100', badge: 'bg-emerald-400/20 border-emerald-300/40' };
  if (family.includes('bluetooth')) return { border: 'rgba(129,140,248,0.82)', fill: 'rgba(99,102,241,0.13)', text: 'text-indigo-100', badge: 'bg-indigo-400/20 border-indigo-300/40' };
  if (family.includes('zigbee')) return { border: 'rgba(250,204,21,0.86)', fill: 'rgba(234,179,8,0.13)', text: 'text-yellow-100', badge: 'bg-yellow-400/20 border-yellow-300/40' };
  if (family.includes('lte') || family.includes('nr')) return { border: 'rgba(244,114,182,0.84)', fill: 'rgba(236,72,153,0.13)', text: 'text-pink-100', badge: 'bg-pink-400/20 border-pink-300/40' };
  if (family.includes('ism')) return { border: 'rgba(251,146,60,0.84)', fill: 'rgba(249,115,22,0.13)', text: 'text-orange-100', badge: 'bg-orange-400/20 border-orange-300/40' };
  return { border: 'rgba(203,213,225,0.72)', fill: 'rgba(148,163,184,0.10)', text: 'text-slate-100', badge: 'bg-slate-400/15 border-slate-300/30' };
};

export const SpectrumView: React.FC = () => {
  const liveSpectrumData = useSpectrumData();
  const liveWaterfallData = useWaterfallData();
  const [viewMode, setViewMode] = useState<'live' | 'frozen'>('live');
  const [frozenSpectrumData, setFrozenSpectrumData] = useState<SpectrumData | null>(null);
  const [frozenWaterfallData, setFrozenWaterfallData] = useState<WaterfallData[]>([]);
  const [frozenViewRange, setFrozenViewRange] = useState<{ centerFrequency: number; span: number } | null>(null);
  const isFrozen = viewMode === 'frozen';
  const spectrumData = isFrozen ? frozenSpectrumData : liveSpectrumData;
  const deviceStatus = useDeviceStatus();
  const settings = useAnalyzerSettings();
  const markers = useMarkers();
  const displaySettings = isFrozen && frozenViewRange ? { ...settings, ...frozenViewRange } : settings;
  const [peakHoldEnabled, setPeakHoldEnabled] = useState(false);
  const [peakHoldMode, setPeakHoldMode] = useState<'permanent' | 'decay'>('permanent');
  const [peakHoldDecayDbPerSecond, setPeakHoldDecayDbPerSecond] = useState(3);
  const [usePeakTraceForDetection, setUsePeakTraceForDetection] = useState(false);
  const [peakHoldData, setPeakHoldData] = useState<SpectrumData | null>(null);
  const [selectedProfileKey, setSelectedProfileKey] = useState('');
  const [markerBandpassEnabled, setMarkerBandpassEnabled] = useState(false);
  const [markerBandpassAttenuationDb, setMarkerBandpassAttenuationDb] = useState(MARKER_BANDPASS_ATTENUATION_DB);
  const markerBand = useMemo(() => {
    if (markers.length < 2) return null;
    const first = markers[0];
    const second = markers[1];
    const start = Math.min(first.frequency, second.frequency);
    const stop = Math.max(first.frequency, second.frequency);
    const span = stop - start;
    if (!Number.isFinite(start) || !Number.isFinite(stop) || span <= 0) return null;
    return {
      start,
      stop,
      span,
      center: start + span / 2,
      firstLabel: first.label || 'M1',
      secondLabel: second.label || 'M2',
    };
  }, [markers]);
  const analysisSourceSpectrumData = usePeakTraceForDetection && peakHoldEnabled && peakHoldData ? peakHoldData : spectrumData;
  const markerBandpassIsValid = useMemo(() => {
    if (!analysisSourceSpectrumData || !markerBand) return false;
    const sourceStart = analysisSourceSpectrumData.centerFrequency - analysisSourceSpectrumData.span / 2;
    const sourceStop = analysisSourceSpectrumData.centerFrequency + analysisSourceSpectrumData.span / 2;
    return markerBand.start >= sourceStart && markerBand.stop <= sourceStop;
  }, [analysisSourceSpectrumData, markerBand]);
  const analysisSpectrumData = useMemo(() => {
    if (!analysisSourceSpectrumData) return null;
    if (!markerBandpassEnabled || !markerBandpassIsValid) return analysisSourceSpectrumData;
    return applyMarkerBandpassMask(analysisSourceSpectrumData, markerBand, markerBandpassAttenuationDb);
  }, [analysisSourceSpectrumData, markerBand, markerBandpassAttenuationDb, markerBandpassEnabled, markerBandpassIsValid]);
  const displayedSpectrumData = markerBandpassEnabled && markerBandpassIsValid ? analysisSpectrumData : spectrumData;
  const peakHoldOverlayData = peakHoldEnabled && peakHoldData
    ? (markerBandpassEnabled && markerBandpassIsValid ? applyMarkerBandpassMask(peakHoldData, markerBand, markerBandpassAttenuationDb) : peakHoldData)
    : null;
  const { canvasRef } = useSpectrum({
    enabled: !isFrozen,
    displayData: displayedSpectrumData,
    displaySettings,
    overlayData: peakHoldOverlayData,
    overlayLabel: peakHoldMode === 'decay' ? `Peak Hold Decay ${peakHoldDecayDbPerSecond} dB/s` : 'Max Hold',
  });
  const [showWaterfallSplit, setShowWaterfallSplit] = useState(false);
  const { canvasRef: waterfallCanvasRef, error: waterfallError } = useWaterfall(showWaterfallSplit && !isFrozen, isFrozen ? frozenWaterfallData : null, displaySettings);
  const { setGlobalActivity, clearGlobalActivity } = useAppActions();
  const spectrumController = useSpectrumController();
  const markerController = useMarkerController();

  const [isStreaming, setIsStreaming] = useState(false);
  const [centerMHz, setCenterMHz] = useState(formatInput(hzToMhz(settings.centerFrequency)));
  const [spanMHz, setSpanMHz] = useState(formatInput(hzToMhz(settings.span), 3));
  const [panStepMHz, setPanStepMHz] = useState(formatInput(hzToMhz(settings.span) / 10, 3));
  const [startMHz, setStartMHz] = useState(formatInput(hzToMhz(settings.centerFrequency - settings.span / 2)));
  const [stopMHz, setStopMHz] = useState(formatInput(hzToMhz(settings.centerFrequency + settings.span / 2)));
  const [rbwKHz, setRbwKHz] = useState(formatInput(settings.rbw / 1e3, 2));
  const [vbwKHz, setVbwKHz] = useState(formatInput(settings.vbw / 1e3, 2));
  const [refLevel, setRefLevel] = useState(formatInput(settings.referenceLevel, 1));
  const [noiseOffset, setNoiseOffset] = useState(formatInput(settings.noiseFloorOffset, 1));
  const [detectorMode, setDetectorMode] = useState<AnalyzerSettings['detectorMode']>(settings.detectorMode);
  const [traceMode, setTraceMode] = useState<AnalyzerSettings['traceMode']>(settings.traceMode);
  const [dbPerDiv, setDbPerDiv] = useState(formatInput(settings.dbPerDiv, 1));
  const [colorScheme, setColorScheme] = useState<AnalyzerSettings['colorScheme']>(settings.colorScheme);
  const [averaging, setAveraging] = useState(formatInput(settings.averaging, 0));
  const [gainDb, setGainDb] = useState(formatInput(deviceStatus.gain, 1));
  const [controlError, setControlError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<{ frequency: number; level: number } | null>(null);
  const [draggingMarkerId, setDraggingMarkerId] = useState<string | null>(null);
  const [showPanOverlay, setShowPanOverlay] = useState(true);
  const [showMarkerBadges, setShowMarkerBadges] = useState(true);
  const [showCursorBadge, setShowCursorBadge] = useState(true);
  const [showRfIntelligenceOverlay, setShowRfIntelligenceOverlay] = useState(true);
  const [showRsuOverlay, setShowRsuOverlay] = useState(false);
  const [showRfExperimentOverlay, setShowRfExperimentOverlay] = useState(false);
  const [selectedRfExperimentType, setSelectedRfExperimentType] = useState<'best' | 'e5' | 'e1' | 'e3' | null>('best');
  const [rsuOverlayMode, setRsuOverlayMode] = useState<'hybrid' | 'ai_only'>('hybrid');
  const [autoFreezeArmed, setAutoFreezeArmed] = useState(false);
  const [autoFreezeCaptureTarget, setAutoFreezeCaptureTarget] = useState<AutoFreezeCaptureTarget | null>(null);
  const [autoFreezeCaptureProcessing, setAutoFreezeCaptureProcessing] = useState(false);
  const [autoFreezeCaptureStatus, setAutoFreezeCaptureStatus] = useState<string | null>(null);
  const [captureProgressDetails, setCaptureProgressDetails] = useState<CaptureProgressDetails | null>(null);
  const [showCaptureProgressOverlay, setShowCaptureProgressOverlay] = useState(false);
  const [rfScene, setRfScene] = useState<RFSceneAnalysis | null>(null);
  const [rfOverlayError, setRfOverlayError] = useState<string | null>(null);
  const [rsuLive, setRsuLive] = useState<RFSignalUnderstandingResult | null>(null);
  const [rsuOverlayError, setRsuOverlayError] = useState<string | null>(null);
  const [rfExperimentOverlay, setRfExperimentOverlay] = useState<Record<string, any> | null>(null);
  const [rfExperimentOverlayError, setRfExperimentOverlayError] = useState<string | null>(null);
  const [liveInferenceResult, setLiveInferenceResult] = useState<Record<string, any> | null>(null);
  const [panOverlayPosition, setPanOverlayPosition] = useState({ x: 16, y: 16 });

  const selectedRfExperimentRun = useMemo(() => {
    if (!rfExperimentOverlay || !selectedRfExperimentType) return null;
    if (selectedRfExperimentType === 'best') return rfExperimentOverlay.best ?? null;
    const typeName = RF_EXPERIMENT_TYPE_NAMES[selectedRfExperimentType];
    const candidates = (rfExperimentOverlay.models ?? []).filter((m: Record<string, any>) => String(m.experiment_type) === typeName);
    return candidates
      .sort((left: Record<string, any>, right: Record<string, any>) =>
        Number(right.metrics_summary?.macro_f1 ?? -1) - Number(left.metrics_summary?.macro_f1 ?? -1),
      )[0] ?? null;
  }, [rfExperimentOverlay, selectedRfExperimentType]);

  useEffect(() => {
    if (!showRfExperimentOverlay) {
      setSelectedRfExperimentType(null);
      setLiveInferenceResult(null);
    }
  }, [showRfExperimentOverlay]);

  const dragStateRef = useRef<{ type: 'pan' | null; offsetX: number; offsetY: number }>({ type: null, offsetX: 0, offsetY: 0 });
  const spectrumDataRef = useRef<typeof spectrumData>(spectrumData);
  const markerBandRef = useRef<typeof markerBand>(markerBand);
  const selectedRfExperimentTypeRef = useRef<typeof selectedRfExperimentType>(selectedRfExperimentType);
  const suppressNextClickRef = useRef(false);
  const autoFreezeTriggeringRef = useRef(false);
  const autoFreezeFrameBufferRef = useRef<SpectrumData[]>([]);
  const peakHoldTimestampRef = useRef<number | null>(null);
  const selectedProfile = selectedProfileKey ? RF_PROFILES[selectedProfileKey] : null;

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(spectrumOverlayStorageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        showPanOverlay?: boolean;
        showMarkerBadges?: boolean;
        showCursorBadge?: boolean;
        showRfIntelligenceOverlay?: boolean;
        showRsuOverlay?: boolean;
        showRfExperimentOverlay?: boolean;
        rsuOverlayMode?: 'hybrid' | 'ai_only';
        panOverlayPosition?: { x?: number; y?: number };
      };
      if (typeof parsed.showPanOverlay === 'boolean') setShowPanOverlay(parsed.showPanOverlay);
      if (typeof parsed.showMarkerBadges === 'boolean') setShowMarkerBadges(parsed.showMarkerBadges);
      if (typeof parsed.showCursorBadge === 'boolean') setShowCursorBadge(parsed.showCursorBadge);
      if (typeof parsed.showRfIntelligenceOverlay === 'boolean') setShowRfIntelligenceOverlay(parsed.showRfIntelligenceOverlay);
      if (typeof parsed.showRsuOverlay === 'boolean') setShowRsuOverlay(parsed.showRsuOverlay);
      if (typeof parsed.showRfExperimentOverlay === 'boolean') setShowRfExperimentOverlay(parsed.showRfExperimentOverlay);
      if (parsed.rsuOverlayMode === 'hybrid' || parsed.rsuOverlayMode === 'ai_only') setRsuOverlayMode(parsed.rsuOverlayMode);
      if (
        parsed.panOverlayPosition &&
        Number.isFinite(parsed.panOverlayPosition.x) &&
        Number.isFinite(parsed.panOverlayPosition.y)
      ) {
        setPanOverlayPosition({
          x: Number(parsed.panOverlayPosition.x),
          y: Number(parsed.panOverlayPosition.y),
        });
      }
    } catch {
      // Ignore invalid persisted UI state.
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        spectrumOverlayStorageKey,
        JSON.stringify({
          showPanOverlay,
          showMarkerBadges,
          showCursorBadge,
          showRfIntelligenceOverlay,
          showRsuOverlay,
          showRfExperimentOverlay,
          rsuOverlayMode,
          panOverlayPosition,
        }),
      );
    } catch {
      // Ignore storage failures.
    }
  }, [showPanOverlay, showMarkerBadges, showCursorBadge, showRfIntelligenceOverlay, showRsuOverlay, showRfExperimentOverlay, rsuOverlayMode, panOverlayPosition]);

  useEffect(() => { spectrumDataRef.current = spectrumData; }, [spectrumData]);
  useEffect(() => { markerBandRef.current = markerBand; }, [markerBand]);
  useEffect(() => { selectedRfExperimentTypeRef.current = selectedRfExperimentType; }, [selectedRfExperimentType]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(RF_PROFILE_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as { selected_profile_key?: string };
      if (parsed.selected_profile_key && RF_PROFILES[parsed.selected_profile_key]) {
        setSelectedProfileKey(parsed.selected_profile_key);
      }
    } catch {
      // Ignore invalid persisted profile state.
    }
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(markerBandpassStorageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw) as { enabled?: boolean; attenuation_db?: number };
      if (typeof parsed.enabled === 'boolean') setMarkerBandpassEnabled(parsed.enabled);
      if (Number.isFinite(parsed.attenuation_db)) {
        setMarkerBandpassAttenuationDb(Math.max(1, Math.min(60, Number(parsed.attenuation_db))));
      }
    } catch {
      // Ignore invalid persisted filter state.
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        markerBandpassStorageKey,
        JSON.stringify({
          enabled: markerBandpassEnabled,
          attenuation_db: markerBandpassAttenuationDb,
          filter_mode: 'fft_soft_mask_preview_and_iq_fir_on_capture',
        }),
      );
    } catch {
      // Ignore storage failures.
    }
  }, [markerBandpassAttenuationDb, markerBandpassEnabled]);

  useEffect(() => {
    if (isFrozen) return;
    setCenterMHz(formatInput(hzToMhz(settings.centerFrequency)));
    setSpanMHz(formatInput(hzToMhz(settings.span), 3));
    setStartMHz(formatInput(hzToMhz(settings.centerFrequency - settings.span / 2)));
    setStopMHz(formatInput(hzToMhz(settings.centerFrequency + settings.span / 2)));
    setRbwKHz(formatInput(settings.rbw / 1e3, 2));
    setVbwKHz(formatInput(settings.vbw / 1e3, 2));
    setRefLevel(formatInput(settings.referenceLevel, 1));
    setNoiseOffset(formatInput(settings.noiseFloorOffset, 1));
    setDetectorMode(settings.detectorMode);
    setTraceMode(settings.traceMode);
    setDbPerDiv(formatInput(settings.dbPerDiv, 1));
    setColorScheme(settings.colorScheme);
    setAveraging(formatInput(settings.averaging, 0));
  }, [
    isFrozen,
    settings.centerFrequency,
    settings.span,
    settings.rbw,
    settings.vbw,
    settings.referenceLevel,
    settings.noiseFloorOffset,
    settings.detectorMode,
    settings.traceMode,
    settings.dbPerDiv,
    settings.colorScheme,
    settings.averaging,
  ]);

  useEffect(() => {
    if (!isFrozen) return;
    setCenterMHz(formatInput(hzToMhz(displaySettings.centerFrequency)));
    setSpanMHz(formatInput(hzToMhz(displaySettings.span), 3));
    setStartMHz(formatInput(hzToMhz(displaySettings.centerFrequency - displaySettings.span / 2)));
    setStopMHz(formatInput(hzToMhz(displaySettings.centerFrequency + displaySettings.span / 2)));
  }, [displaySettings.centerFrequency, displaySettings.span, isFrozen]);

  useEffect(() => {
    setPanStepMHz(formatInput(hzToMhz(displaySettings.span) / 10, 3));
  }, [displaySettings.span]);

  useEffect(() => {
    setGainDb(formatInput(deviceStatus.gain, 1));
  }, [deviceStatus.gain]);

  useEffect(() => {
    if (isFrozen || !peakHoldEnabled || !liveSpectrumData) return;
    setPeakHoldData((previous) => {
      const current = cloneSpectrumFrame(liveSpectrumData);
      const sameShape = (
        previous &&
        previous.powerLevels.length === current.powerLevels.length &&
        previous.frequencyArray.length === current.frequencyArray.length &&
        previous.centerFrequency === current.centerFrequency &&
        previous.span === current.span
      );
      const now = Number.isFinite(current.timestamp) ? current.timestamp : Date.now();
      const previousTimestamp = peakHoldTimestampRef.current ?? now;
      const deltaSeconds = Math.max(0, (now - previousTimestamp) / 1000);
      peakHoldTimestampRef.current = now;

      if (!sameShape) return current;

      return {
        ...current,
        powerLevels: current.powerLevels.map((level, index) => {
          const held = previous.powerLevels[index] ?? level;
          if (peakHoldMode === 'decay') {
            return Math.max(level, held - peakHoldDecayDbPerSecond * deltaSeconds);
          }
          return Math.max(held, level);
        }),
      };
    });
  }, [isFrozen, liveSpectrumData, peakHoldDecayDbPerSecond, peakHoldEnabled, peakHoldMode]);

  useEffect(() => {
    if (isFrozen || !liveSpectrumData) return;
    const buffer = autoFreezeFrameBufferRef.current;
    buffer.push(cloneSpectrumFrame(liveSpectrumData));
    if (buffer.length > AUTO_FREEZE_FRAME_BUFFER_SIZE) {
      buffer.splice(0, buffer.length - AUTO_FREEZE_FRAME_BUFFER_SIZE);
    }
  }, [isFrozen, liveSpectrumData]);

  useEffect(() => {
    if (isFrozen || !showRfIntelligenceOverlay || !deviceStatus.isConnected) {
      return;
    }

    let cancelled = false;
    const refreshRfScene = async () => {
      try {
        const scene = analysisSpectrumData && (usePeakTraceForDetection || markerBandpassEnabled)
          ? await apiService.analyzeRFScene(analysisSpectrumData, { thresholdOffsetDb: 10, minSnrDb: 6 })
          : await apiService.getLiveRFScene({ thresholdOffsetDb: 10, minSnrDb: 6 });
        if (!cancelled) {
          setRfScene(scene);
          setRfOverlayError(null);
        }
      } catch (error) {
        if (!cancelled) {
          setRfOverlayError(getErrorMessage(error));
        }
      }
    };

    refreshRfScene();
    const interval = window.setInterval(refreshRfScene, 1200);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [analysisSpectrumData, deviceStatus.isConnected, isFrozen, markerBandpassEnabled, showRfIntelligenceOverlay, usePeakTraceForDetection]);

  useEffect(() => {
    if (isFrozen || !showRsuOverlay || !deviceStatus.isConnected) {
      return;
    }

    let cancelled = false;
    const refreshRsuLive = async () => {
      try {
        const live = analysisSpectrumData && (usePeakTraceForDetection || markerBandpassEnabled)
          ? await apiService.analyzeRFSignalUnderstandingFrame(analysisSpectrumData, { decision_mode: rsuOverlayMode })
          : await apiService.getLiveRFSignalUnderstanding({ decision_mode: rsuOverlayMode });
        if (!cancelled) {
          setRsuLive(live);
          setRsuOverlayError(null);
        }
      } catch (error) {
        if (!cancelled) {
          setRsuOverlayError(getErrorMessage(error));
        }
      }
    };

    refreshRsuLive();
    const interval = window.setInterval(refreshRsuLive, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [analysisSpectrumData, deviceStatus.isConnected, isFrozen, markerBandpassEnabled, showRsuOverlay, rsuOverlayMode, usePeakTraceForDetection]);

  useEffect(() => {
    if (!showRfExperimentOverlay) {
      return;
    }

    let cancelled = false;
    const refreshExperimentOverlay = async () => {
      try {
        const [healthResponse, models] = await Promise.all([
          apiService.getRFExperimentLabHealth(),
          apiService.getModelRegistry(),
        ]);
        if (cancelled) return;
        const health = healthResponse?.data ?? healthResponse;
        const candidates = models.filter((m) =>
          ['e5_spectral_feature_baseline', 'e1_raw_iq_cnn1d', 'e3_spectrogram_cnn2d'].includes(String(m.experiment_type)),
        );
        const readyCandidates = candidates.filter((m) => m.ready_for_live_inference);
        const best =
          [...readyCandidates].sort(
            (a, b) => Number(b.metrics_summary?.macro_f1 ?? -1) - Number(a.metrics_summary?.macro_f1 ?? -1),
          )[0] ?? null;

        setRfExperimentOverlay({ health, models: candidates, best });
        setRfExperimentOverlayError(null);

        // Determine which model to use for live inference based on current selection.
        const currentType = selectedRfExperimentTypeRef.current;
        let inferenceModel: Record<string, any> | null = null;
        if (currentType === 'best') {
          inferenceModel = best;
        } else if (currentType && currentType in RF_EXPERIMENT_TYPE_NAMES) {
          const typeName = RF_EXPERIMENT_TYPE_NAMES[currentType as keyof typeof RF_EXPERIMENT_TYPE_NAMES];
          inferenceModel =
            [...readyCandidates]
              .filter((m) => m.experiment_type === typeName && m.live_compatible)
              .sort((a, b) => Number(b.metrics_summary?.macro_f1 ?? -1) - Number(a.metrics_summary?.macro_f1 ?? -1))[0] ?? null;
        }

        const currentSpectrum = spectrumDataRef.current;
        const currentMarker = markerBandRef.current;

        if (inferenceModel?.live_compatible && currentSpectrum && currentSpectrum.frequencyArray.length >= 4) {
          try {
            const inferenceResult = await apiService.runLiveInference({
              model_id: String(inferenceModel.model_id),
              experiment_type: String(inferenceModel.experiment_type),
              live_context: {
                frequency_array_hz: currentSpectrum.frequencyArray,
                power_levels_db: currentSpectrum.powerLevels,
                center_frequency_hz: currentSpectrum.centerFrequency,
                ...(currentMarker ? { marker_start_hz: currentMarker.start, marker_stop_hz: currentMarker.stop } : {}),
              },
            });
            if (!cancelled) {
              setLiveInferenceResult(
                inferenceResult
                  ? { ...inferenceResult, task: inferenceModel.task, label_field: inferenceModel.label_field }
                  : null,
              );
            }
          } catch {
            if (!cancelled) setLiveInferenceResult(null);
          }
        } else if (!cancelled) {
          setLiveInferenceResult(null);
        }
      } catch (error) {
        if (!cancelled) {
          setRfExperimentOverlayError(getErrorMessage(error));
        }
      }
    };

    refreshExperimentOverlay();
    const interval = window.setInterval(refreshExperimentOverlay, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [showRfExperimentOverlay]);

  const markerRows = useMemo(() => {
    return markers.map((marker) => {
      const liveLevel = analysisSpectrumData
        ? getLevelAtFrequency(marker.frequency, analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels)
        : marker.level;
      return {
        ...marker,
        level: Number.isFinite(liveLevel) ? liveLevel : marker.level,
      };
    });
  }, [analysisSpectrumData, markers]);

  const traceStats = useMemo(() => computeStats(analysisSpectrumData?.powerLevels ?? []), [analysisSpectrumData]);

  const deltaMarker = useMemo(() => {
    if (markerRows.length < 2) return null;
    const first = markerRows[0];
    const second = markerRows[1];
    return {
      frequencyDelta: second.frequency - first.frequency,
      levelDelta: second.level - first.level,
    };
  }, [markerRows]);

  const liveMarkerBandQuality = useMemo(() => {
    if (!analysisSpectrumData || !markerBand) return null;
    return estimateBandQuality(analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels, markerBand.start, markerBand.stop);
  }, [analysisSpectrumData, markerBand]);

  const markerBandIsVisible = useMemo(() => {
    if (!markerBand) return false;
    const visibleStart = displaySettings.centerFrequency - displaySettings.span / 2;
    const visibleStop = displaySettings.centerFrequency + displaySettings.span / 2;
    return markerBand.start >= visibleStart && markerBand.stop <= visibleStop;
  }, [displaySettings.centerFrequency, displaySettings.span, markerBand]);

  const canArmAutoFreeze = Boolean(markerBand && markerBandIsVisible && !isFrozen && deviceStatus.isConnected);

  const visibleRfDetections = useMemo(() => {
    if (!showRfIntelligenceOverlay || !rfScene) return [];
    const start = displaySettings.centerFrequency - displaySettings.span / 2;
    const stop = displaySettings.centerFrequency + displaySettings.span / 2;
    return rfScene.detections
      .filter((detection) => detection.stop_frequency_hz >= start && detection.start_frequency_hz <= stop)
      .sort((left, right) => right.confidence - left.confidence)
      .slice(0, 8);
  }, [rfScene, displaySettings.centerFrequency, displaySettings.span, showRfIntelligenceOverlay]);

  const visibleRsuRegions = useMemo(() => {
    if (!showRsuOverlay || !rsuLive) return [];
    const start = displaySettings.centerFrequency - displaySettings.span / 2;
    const stop = displaySettings.centerFrequency + displaySettings.span / 2;
    return (rsuLive.regions ?? [])
      .filter((region) => rsuOverlayMode === 'hybrid' || Boolean(region.classification?.trained))
      .filter((region) => Number(region.freq_end_hz) >= start && Number(region.freq_start_hz) <= stop)
      .sort((left, right) => Number(right.final_decision?.confidence ?? 0) - Number(left.final_decision?.confidence ?? 0))
      .slice(0, 8);
  }, [rsuLive, displaySettings.centerFrequency, displaySettings.span, showRsuOverlay, rsuOverlayMode]);

  const freezeView = async (
    sourceFrame: SpectrumData | null = liveSpectrumData,
    viewRange?: { centerFrequency: number; span: number },
  ) => {
    if (!sourceFrame) {
      setControlError('No live spectrum frame is available to freeze.');
      return;
    }
    const frozenSpectrum = cloneSpectrumFrame(sourceFrame);
    setFrozenSpectrumData(frozenSpectrum);
    setFrozenWaterfallData(liveWaterfallData.map((row) => ({ ...row, data: row.data.map((values) => [...values]) })));
    setFrozenViewRange(viewRange ?? { centerFrequency: displaySettings.centerFrequency, span: displaySettings.span });
    setViewMode('frozen');
    setControlError(null);
    if (showRfIntelligenceOverlay) {
      try {
        const scene = await apiService.analyzeRFScene(frozenSpectrum, { thresholdOffsetDb: 10, minSnrDb: 6 });
        setRfScene(scene);
        setRfOverlayError(null);
      } catch (error) {
        setRfOverlayError(getErrorMessage(error));
      }
    }
    if (showRsuOverlay) {
      try {
        const analysis = await apiService.analyzeRFSignalUnderstandingFrame(frozenSpectrum, { decision_mode: rsuOverlayMode });
        setRsuLive(analysis);
        setRsuOverlayError(null);
      } catch (error) {
        setRsuOverlayError(getErrorMessage(error));
      }
    }
  };

  const captureAutoFreezeSignal = async (fileFormat: 'iq' | 'cfile') => {
    const target = autoFreezeCaptureTarget;
    if (!target) return;

    // Calcular detalles en vivo usando la ventana de la señal detectada, no solo el marker band.
    const bandQuality = estimateBandQuality(
      target.frozenFrame.frequencyArray,
      target.frozenFrame.powerLevels,
      target.candidate.startFrequencyHz,
      target.candidate.stopFrequencyHz,
    );

    const details: CaptureProgressDetails = {
      startFrequencyHz: target.candidate.startFrequencyHz,
      stopFrequencyHz: target.candidate.stopFrequencyHz,
      gainDb: deviceStatus.gain,
      antenna: 'RX2',
      artifactScope: 'local project storage',
      txId: selectedProfile?.key ?? 'auto_freeze',
      class: selectedProfile?.signal_type ?? selectedProfile?.label ?? 'auto_freeze',
      operator: 'auto',
      environment: 'lab',
      sha256: 'calculating...',
      livePreviewSnrDb: bandQuality?.snrDb ?? target.candidate.snrDb ?? null,
      livePreviewNoiseDb: bandQuality?.noiseFloorDb ?? null,
      livePreviewPeakDb: bandQuality?.peakLevelDb ?? target.candidate.peakLevelDb ?? null,
      captureMode: 'immediate',
      triggerDetected: true,
    };

    setCaptureProgressDetails(details);
    setShowCaptureProgressOverlay(true);

    const profileDuration = selectedProfile?.capture_duration_seconds ?? 10;
    const labelHint = selectedProfile?.label
      ? `Auto Freeze capture: ${selectedProfile.label}`
      : `Auto Freeze signal ${formatFrequency(target.candidate.peakFrequencyHz)}`;

    try {
      setAutoFreezeCaptureProcessing(true);
      setAutoFreezeCaptureStatus(`Saving ${fileFormat.toUpperCase()} capture...`);
      setControlError(null);
      const response = await apiService.captureRFSignalForTraining({
        start_frequency_hz: target.candidate.startFrequencyHz,
        stop_frequency_hz: target.candidate.stopFrequencyHz,
        duration_seconds: profileDuration,
        label_hint: labelHint,
        session_id: `autofreeze_${new Date().toISOString()}`,
        file_format: fileFormat,
        gain_db: selectedProfile?.recommended_gain_db,
        profile_key: selectedProfile?.key,
        profile: selectedProfile ?? undefined,
        apply_bandpass_filter: markerBandpassEnabled,
        filter_stopband_attenuation_db: markerBandpassAttenuationDb,
        live_preview_snr_db: details.livePreviewSnrDb,
        live_preview_noise_floor_db: details.livePreviewNoiseDb,
        live_preview_peak_level_db: details.livePreviewPeakDb,
        live_preview_peak_frequency_hz: target.candidate.peakFrequencyHz,
        transmitter_id: details.txId,
        transmitter_class: details.class,
        operator: details.operator,
        environment: details.environment,
      });

      // Actualizar SHA256 si disponible
      if (response?.sha256) {
        setCaptureProgressDetails(prev => prev ? { ...prev, sha256: response.sha256 } : null);
      }

      setAutoFreezeCaptureStatus(
        `Auto Freeze saved as ${fileFormat.toUpperCase()}.` +
        (response?.capture_id ? ` ID=${response.capture_id}` : ''),
      );
      setControlError(`Auto Freeze capture saved as ${fileFormat.toUpperCase()}.`);
    } catch (error) {
      const message = getErrorMessage(error);
      setAutoFreezeCaptureStatus(`Capture failed: ${message}`);
      setControlError(message);
    } finally {
      setAutoFreezeCaptureProcessing(false);
      setAutoFreezeCaptureTarget(null);
      // Mantener overlay visible por un tiempo para ver el resultado
      setTimeout(() => {
        setShowCaptureProgressOverlay(false);
        setCaptureProgressDetails(null);
      }, 3000);
    }
  };

  const dismissAutoFreezeCapturePrompt = () => {
    setAutoFreezeCaptureTarget(null);
    setAutoFreezeCaptureStatus(null);
  };

  const resumeLive = () => {
    setFrozenSpectrumData(null);
    setFrozenWaterfallData([]);
    setFrozenViewRange(null);
    setViewMode('live');
    setAutoFreezeArmed(false);
    autoFreezeTriggeringRef.current = false;
    setControlError(null);
  };

  useEffect(() => {
    if (!markerBand || !markerBandIsVisible || isFrozen) {
      setAutoFreezeArmed(false);
      autoFreezeTriggeringRef.current = false;
    }
  }, [isFrozen, markerBand, markerBandIsVisible]);

  useEffect(() => {
    if (!markerBand) setMarkerBandpassEnabled(false);
  }, [markerBand]);

  useEffect(() => {
    if (!autoFreezeArmed || isFrozen || !markerBand || !liveSpectrumData || autoFreezeTriggeringRef.current) {
      return;
    }
    let triggerFrame: SpectrumData | null = null;
    let triggerCandidate: AutoFreezeCandidate | null = null;
    const recentFrames = [...autoFreezeFrameBufferRef.current, liveSpectrumData].slice(-AUTO_FREEZE_FRAME_BUFFER_SIZE);
    for (let index = recentFrames.length - 1; index >= 0; index -= 1) {
      const frame = recentFrames[index];
      const candidateFrame = markerBandpassEnabled ? applyMarkerBandpassMask(frame, markerBand, markerBandpassAttenuationDb) : frame;
      const candidate = findAutoFreezeCandidate(candidateFrame, markerBand);
      if (candidate && (!triggerCandidate || candidate.snrDb > triggerCandidate.snrDb)) {
        triggerFrame = frame;
        triggerCandidate = candidate;
      }
    }
    if (!triggerFrame || !triggerCandidate) {
      return;
    }

    autoFreezeTriggeringRef.current = true;
    setAutoFreezeArmed(false);
    const triggerSpan = Math.max(triggerCandidate.bandwidthHz * 2.5, markerBand.span * 0.15, 5_000);
    const viewRange = {
      centerFrequency: triggerCandidate.peakFrequencyHz,
      span: Math.min(markerBand.span, triggerSpan),
    };
    void freezeView(triggerFrame, viewRange).then(() => {
      setControlError(
        `Auto Freeze captured ${formatFrequency(triggerCandidate.peakFrequencyHz)} inside M1-M2: ` +
        `${triggerCandidate.snrDb.toFixed(1)} dB SNR, ${formatBandwidth(triggerCandidate.bandwidthHz)} BW.`,
      );
      setAutoFreezeCaptureTarget({
        candidate: triggerCandidate,
        frozenFrame: triggerFrame,
        viewRange,
      });
      setAutoFreezeCaptureStatus('Seleccione si desea guardar esta señal como .cfile o .iq para entrenamiento.');
      autoFreezeTriggeringRef.current = false;
    });
  }, [autoFreezeArmed, isFrozen, liveSpectrumData, markerBand, markerBandpassAttenuationDb, markerBandpassEnabled]);

  useEffect(() => {
    if (!isFrozen || !showRsuOverlay || !frozenSpectrumData) return;
    let cancelled = false;
    apiService.analyzeRFSignalUnderstandingFrame(frozenSpectrumData, { decision_mode: rsuOverlayMode })
      .then((analysis) => {
        if (!cancelled) {
          setRsuLive(analysis);
          setRsuOverlayError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) setRsuOverlayError(getErrorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [frozenSpectrumData, isFrozen, rsuOverlayMode, showRsuOverlay]);

  const applyCenterSpan = async () => {
    const center = mhzToHz(centerMHz);
    const span = mhzToHz(spanMHz);
    if (!Number.isFinite(center) || center <= 0 || !Number.isFinite(span) || span <= 0) {
      setControlError('Center and span must be positive numeric values.');
      return;
    }
    setControlError(null);
    if (isFrozen) {
      setFrozenViewRange({ centerFrequency: center, span });
      return;
    }
    try {
      await spectrumController.setCenterFrequency(center);
      await spectrumController.setSpan(span);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applyStartStop = async () => {
    const start = mhzToHz(startMHz);
    const stop = mhzToHz(stopMHz);
    if (!Number.isFinite(start) || !Number.isFinite(stop) || start <= 0 || stop <= start) {
      setControlError('Start must be positive and lower than stop.');
      return;
    }
    setControlError(null);
    if (isFrozen) {
      const span = stop - start;
      setFrozenViewRange({ centerFrequency: start + span / 2, span });
      return;
    }
    try {
      await spectrumController.setStartStop(start, stop);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const panFrequencyWindow = async (direction: -1 | 1) => {
    const step = mhzToHz(panStepMHz);
    if (!Number.isFinite(step) || step <= 0) {
      setControlError('Step must be a positive numeric value.');
      return;
    }

    const nextCenter = displaySettings.centerFrequency + direction * step;
    if (!Number.isFinite(nextCenter) || nextCenter <= 0) {
      setControlError('Center frequency must stay above 0 Hz.');
      return;
    }

    setControlError(null);
    if (isFrozen) {
      setFrozenViewRange({ centerFrequency: nextCenter, span: displaySettings.span });
      return;
    }
    try {
      await spectrumController.setCenterFrequency(nextCenter);
      await spectrumController.refreshSpectrum();
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applyResolution = async () => {
    const rbw = khzToHz(rbwKHz);
    const vbw = khzToHz(vbwKHz);
    const ref = Number(refLevel);
    const offset = Number(noiseOffset);
    const avg = Number(averaging);
    const div = Number(dbPerDiv);
    if (
      !Number.isFinite(rbw) || rbw <= 0 ||
      !Number.isFinite(vbw) || vbw <= 0 ||
      !Number.isFinite(ref) ||
      !Number.isFinite(offset) ||
      !Number.isFinite(avg) || avg < 1 ||
      !Number.isFinite(div) || div <= 0
    ) {
      setControlError('RBW, VBW, dB/div and averaging must be positive. Ref and offset must be numeric.');
      return;
    }
    setControlError(null);
    try {
      await spectrumController.setRbw(rbw);
      await spectrumController.setVbw(vbw);
      await spectrumController.setReferenceLevel(ref);
      await spectrumController.setNoiseFloorOffset(offset);
      await spectrumController.setDetectorMode(detectorMode);
      await spectrumController.setAveraging(avg);
      spectrumController.setTraceDisplay({ traceMode, dbPerDiv: div, colorScheme });
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applyGain = async () => {
    const gain = Number(gainDb);
    if (!Number.isFinite(gain)) {
      setControlError('Gain must be numeric.');
      return;
    }
    setControlError(null);
    try {
      await spectrumController.setGain(gain);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applySelectedRFProfile = async (profileKey: string) => {
    if (!profileKey) {
      setSelectedProfileKey('');
      window.localStorage.removeItem(RF_PROFILE_STORAGE_KEY);
      return;
    }
    const profile = RF_PROFILES[profileKey];
    if (!profile) return;
    if (isFrozen) {
      setControlError('Resume Live before applying an RF profile.');
      return;
    }

    const applied = applyRFProfile(profile);
    setSelectedProfileKey(profile.key);
    setCenterMHz(formatInput(hzToMhz(applied.center_frequency_hz)));
    setSpanMHz(formatInput(hzToMhz(applied.span_hz), 3));
    setStartMHz(formatInput(hzToMhz(applied.start_frequency_hz)));
    setStopMHz(formatInput(hzToMhz(applied.stop_frequency_hz)));
    setGainDb(formatInput(applied.recommended_gain_db, 1));

    try {
      setControlError(null);
      await spectrumController.setStartStop(applied.start_frequency_hz, applied.stop_frequency_hz);
      await spectrumController.setGain(applied.recommended_gain_db);

      for (const marker of markerRows) {
        await markerController.deleteMarker(marker.id);
      }
      await markerController.createMarker(applied.marker_left_hz, 'M1 Profile Left');
      await markerController.createMarker(applied.marker_right_hz, 'M2 Profile Right');
      await markerController.createMarker(applied.center_frequency_hz, 'Profile Center');

      window.localStorage.setItem(RF_PROFILE_STORAGE_KEY, JSON.stringify(applied));
      await spectrumController.refreshSpectrum();
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const handleStartStop = async () => {
    if (isStreaming) {
      try {
        await spectrumController.stopDeviceStream();
        setIsStreaming(false);
      } catch (error) {
        setControlError(getErrorMessage(error));
      }
      return;
    }
    try {
      await spectrumController.startDeviceStream();
      setIsStreaming(true);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const handleConnectDisconnect = async () => {
    if (deviceStatus.isConnected) {
      try {
        setGlobalActivity({
          visible: true,
          kind: 'processing',
          title: 'Disconnecting SDR',
          detail: 'Closing the active SDR session.',
        });
        await spectrumController.disconnectDevice();
        setIsStreaming(false);
      } catch (error) {
        setControlError(getErrorMessage(error));
      } finally {
        clearGlobalActivity();
      }
      return;
    }
    try {
      setGlobalActivity({
        visible: true,
        kind: 'connecting',
        title: 'Connecting to SDR',
        detail: 'The radio frontend may take a few seconds to initialize. You can keep navigating.',
      });
      await spectrumController.connectDevice();
    } catch (error) {
      setControlError(getErrorMessage(error));
    } finally {
      clearGlobalActivity();
    }
  };

  const addMarkerAtCanvas = async (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false;
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const relativeX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const start = displaySettings.centerFrequency - displaySettings.span / 2;
    const frequency = start + relativeX * displaySettings.span;
    const level = analysisSpectrumData
      ? getLevelAtFrequency(frequency, analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels)
      : Number.NaN;
    await markerController.createMarker(frequency, undefined, level);
  };

  const frequencyFromPointer = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const relativeX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const start = displaySettings.centerFrequency - displaySettings.span / 2;
    return start + relativeX * displaySettings.span;
  };

  const updateCursor = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const frequency = frequencyFromPointer(event);
    if (frequency === null) return;
    const level = analysisSpectrumData
      ? getLevelAtFrequency(frequency, analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels)
      : Number.NaN;
    setCursor({ frequency, level });
    if (draggingMarkerId) {
      markerController.updateMarker(draggingMarkerId, { frequency, level: Number.isFinite(level) ? level : 0 });
    }
  };

  const startOverlayDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    const container = event.currentTarget.parentElement;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    dragStateRef.current = {
      type: 'pan',
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
  };

  const stopOverlayDrag = () => {
    dragStateRef.current = { type: null, offsetX: 0, offsetY: 0 };
  };

  const dragOverlay = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragStateRef.current.type !== 'pan') return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const nextX = Math.max(8, Math.min(rect.width - 260, event.clientX - rect.left - dragStateRef.current.offsetX));
    const nextY = Math.max(8, Math.min(rect.height - 80, event.clientY - rect.top - dragStateRef.current.offsetY));
    setPanOverlayPosition({ x: nextX, y: nextY });
  };

  const startMarkerDrag = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const frequency = frequencyFromPointer(event);
    if (frequency === null) return;
    const toleranceHz = displaySettings.span * 0.01;
    const marker = markerRows.find((item) => Math.abs(item.frequency - frequency) <= toleranceHz);
    if (marker) {
      suppressNextClickRef.current = true;
      setDraggingMarkerId(marker.id);
    }
  };

  const zoomFromWheel = async (event: React.WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const zoomFactor = event.deltaY < 0 ? 0.8 : 1.25;
    const nextSpan = Math.max(displaySettings.span * zoomFactor, 1_000);
    if (isFrozen) {
      setFrozenViewRange({ centerFrequency: displaySettings.centerFrequency, span: nextSpan });
      return;
    }
    try {
      await spectrumController.setSpan(nextSpan);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const createAutoPeaks = async () => {
    if (!analysisSpectrumData) return;
    const peaks = findLocalPeaks(analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels, 3);
    for (const [index, peak] of peaks.entries()) {
      await markerController.createMarker(peak.frequency, `P${index + 1}`, peak.level);
    }
  };

  const centerOnLivePeak = async () => {
    if (!analysisSpectrumData) {
      setControlError('No live spectrum data available to recenter.');
      return;
    }
    const strongestPeak = findStrongestPeak(analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels);
    if (!strongestPeak) {
      setControlError('No valid spectral peak available to recenter.');
      return;
    }

    setControlError(null);
    if (isFrozen) {
      if (markerRows.length >= 2) {
        const first = markerRows[0];
        const second = markerRows[1];
        const markerBandwidth = Math.abs(second.frequency - first.frequency);
        setFrozenViewRange({ centerFrequency: strongestPeak.frequency, span: Math.max(markerBandwidth, 1_000) });
      } else {
        setFrozenViewRange({ centerFrequency: strongestPeak.frequency, span: displaySettings.span });
      }
      return;
    }
    try {
      if (markerRows.length >= 2) {
        const first = markerRows[0];
        const second = markerRows[1];
        const markerBandwidth = Math.abs(second.frequency - first.frequency);
        const nextStart = strongestPeak.frequency - markerBandwidth / 2;
        const nextStop = strongestPeak.frequency + markerBandwidth / 2;
        if (!Number.isFinite(nextStart) || !Number.isFinite(nextStop) || nextStart <= 0 || nextStop <= nextStart) {
          setControlError('Unable to derive a valid marker-centered frequency window.');
          return;
        }

        await spectrumController.setStartStop(nextStart, nextStop);
        markerController.updateMarker(first.id, {
          frequency: nextStart,
          level: getLevelAtFrequency(nextStart, analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels),
        });
        markerController.updateMarker(second.id, {
          frequency: nextStop,
          level: getLevelAtFrequency(nextStop, analysisSpectrumData.frequencyArray, analysisSpectrumData.powerLevels),
        });
        await spectrumController.refreshSpectrum();
        return;
      }

      await spectrumController.setCenterFrequency(strongestPeak.frequency);
      await spectrumController.refreshSpectrum();
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const removeLastMarker = async () => {
    if (markerRows.length === 0) return;
    const lastMarker = markerRows[markerRows.length - 1];
    await markerController.deleteMarker(lastMarker.id);
  };

  const exportCsv = () => {
    if (!analysisSpectrumData) return;
    const rows = ['frequency_hz,level_db'];
    analysisSpectrumData.frequencyArray.forEach((frequency, index) => {
      rows.push(`${frequency},${analysisSpectrumData.powerLevels[index] ?? ''}`);
    });
    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `spectraease_${Math.round(settings.centerFrequency)}Hz.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportPng = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `spectraease_${Math.round(settings.centerFrequency)}Hz.png`;
    link.click();
  };

  return (
    <div className="h-full flex flex-col bg-slate-950 text-slate-100">
      <div className="border-b border-slate-800 bg-slate-900 px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <button
            onClick={handleConnectDisconnect}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              deviceStatus.isConnected ? 'bg-slate-700 hover:bg-slate-600' : 'bg-emerald-600 hover:bg-emerald-500'
            )}
          >
            {deviceStatus.isConnected ? <Unplug className="w-4 h-4 mr-2" /> : <Usb className="w-4 h-4 mr-2" />}
            {deviceStatus.isConnected ? 'Disconnect' : 'Connect USB'}
          </button>

          <button
            onClick={handleStartStop}
            disabled={!deviceStatus.isConnected}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              !deviceStatus.isConnected ? 'bg-slate-700 text-slate-400 cursor-not-allowed' :
              isStreaming ? 'bg-red-600 hover:bg-red-500' : 'bg-green-600 hover:bg-green-500'
            )}
          >
            {isStreaming ? <Square className="w-4 h-4 mr-2" /> : <Play className="w-4 h-4 mr-2" />}
            {isStreaming ? 'Stop' : 'Start'}
          </button>

          <button
            onClick={() => spectrumController.openWfmReceiver()}
            className="h-9 flex items-center px-3 rounded-md bg-indigo-600 hover:bg-indigo-500 text-sm font-medium"
          >
            <Radio className="w-4 h-4 mr-2" />
            WFM Receiver
          </button>

          <button
            onClick={() => spectrumController.refreshSpectrum()}
            disabled={isFrozen}
            className="h-9 flex items-center px-3 rounded-md bg-blue-600 hover:bg-blue-500 text-sm font-medium"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Refresh
          </button>

          {isFrozen ? (
            <button
              onClick={resumeLive}
              className="h-9 flex items-center px-3 rounded-md bg-emerald-400 text-slate-950 hover:bg-emerald-300 text-sm font-medium"
              title="Resume live spectrum and waterfall updates"
            >
              <Play className="w-4 h-4 mr-2" />
              Resume Live
            </button>
          ) : (
            <button
              onClick={() => freezeView()}
              disabled={!spectrumData}
              className="h-9 flex items-center px-3 rounded-md bg-violet-300 text-slate-950 hover:bg-violet-200 text-sm font-medium disabled:opacity-50"
              title="Freeze the current spectrum and waterfall in memory"
            >
              <Square className="w-4 h-4 mr-2" />
              Freeze View
            </button>
          )}

          <button
            onClick={() => {
              autoFreezeTriggeringRef.current = false;
              setAutoFreezeArmed((current) => !current);
              setControlError(null);
            }}
            disabled={!canArmAutoFreeze}
            aria-pressed={autoFreezeArmed}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium disabled:opacity-50',
              autoFreezeArmed
                ? 'bg-amber-300 text-slate-950 hover:bg-amber-200'
                : 'bg-slate-700 hover:bg-slate-600',
            )}
            title={
              canArmAutoFreeze && markerBand
                ? `Auto Freeze listens only between M1 and M2, centered at ${formatFrequency(markerBand.center)}. Trigger: contiguous region, SNR >= ${AUTO_FREEZE_TRIGGER_SNR_DB} dB, BW ${Math.round(AUTO_FREEZE_MIN_RELATIVE_BW * 100)}-${Math.round(AUTO_FREEZE_MAX_RELATIVE_BW * 100)}% of M1-M2.`
                : 'Place Marker 1 and Marker 2 inside the visible spectrum before enabling Auto Freeze'
            }
          >
            <Target className="w-4 h-4 mr-2" />
            {autoFreezeArmed
              ? `Armed ${markerBand ? formatFrequency(markerBand.center) : 'M1-M2'}`
              : `Auto Freeze ${markerBand ? formatFrequency(markerBand.center) : 'M1-M2'}`}
          </button>

          {autoFreezeCaptureTarget && (
            <div className="rounded-md border border-amber-500 bg-amber-950/40 p-3 text-sm text-amber-100">
              <div className="mb-2 font-semibold text-amber-200">Auto Freeze captured a signal.</div>
              <div className="mb-2">
                {autoFreezeCaptureStatus ?? 'Seleccione un formato para guardar esta captura en la librería de entrenamiento.'}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => captureAutoFreezeSignal('cfile')}
                  disabled={autoFreezeCaptureProcessing}
                  className="rounded-md border border-amber-400 bg-amber-500 px-3 py-2 text-xs font-medium text-slate-950 hover:bg-amber-400 disabled:opacity-50"
                >
                  Guardar como .cfile
                </button>
                <button
                  type="button"
                  onClick={() => captureAutoFreezeSignal('iq')}
                  disabled={autoFreezeCaptureProcessing}
                  className="rounded-md border border-slate-700 bg-slate-700 px-3 py-2 text-xs font-medium text-slate-100 hover:bg-slate-600 disabled:opacity-50"
                >
                  Guardar como .iq
                </button>
                <button
                  type="button"
                  onClick={dismissAutoFreezeCapturePrompt}
                  disabled={autoFreezeCaptureProcessing}
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-100 hover:bg-slate-800 disabled:opacity-50"
                >
                  No capturar
                </button>
              </div>
            </div>
          )}
          <button
            onClick={() => {
              setMarkerBandpassEnabled((current) => !current);
            }}
            disabled={!markerBand}
            aria-pressed={markerBandpassEnabled}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium disabled:opacity-50',
              markerBandpassEnabled ? 'bg-lime-300 text-slate-950 hover:bg-lime-200' : 'bg-slate-700 hover:bg-slate-600',
            )}
            title={
              markerBand
                ? `FFT preview mask for live spectrum and real FIR filter for I/Q captures. Outside-band attenuation: ${markerBandpassAttenuationDb} dB.`
                : 'Place Marker 1 and Marker 2 before enabling marker band-pass filtering'
            }
          >
            <SlidersHorizontal className="w-4 h-4 mr-2" />
            Band-Pass {markerBandpassEnabled ? 'On' : 'Off'}
          </button>
          {markerBandpassEnabled && (
            <label className="flex flex-col gap-1 text-[11px] text-slate-400">
              Stopband
              <select
                value={markerBandpassAttenuationDb}
                onChange={(event) => setMarkerBandpassAttenuationDb(Number(event.target.value))}
                className="h-9 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
              >
                <option value={1}>1 dB</option>
                <option value={3}>3 dB</option>
                <option value={6}>6 dB</option>
                <option value={10}>10 dB</option>
                <option value={20}>20 dB</option>
                <option value={40}>40 dB</option>
                <option value={60}>60 dB</option>
              </select>
            </label>
          )}

          <button
            onClick={() => {
              setPeakHoldEnabled((current) => !current);
              peakHoldTimestampRef.current = null;
            }}
            aria-pressed={peakHoldEnabled}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              peakHoldEnabled ? 'bg-yellow-300 text-slate-950 hover:bg-yellow-200' : 'bg-slate-700 hover:bg-slate-600',
            )}
            title="Visual-only Max Hold / Peak Hold overlay. Does not capture or save I/Q."
          >
            <BarChart3 className="w-4 h-4 mr-2" />
            {peakHoldEnabled ? 'Peak Hold On' : 'Peak Hold Off'}
          </button>

          {peakHoldEnabled && (
            <>
              <label className="flex flex-col gap-1 text-[11px] text-slate-400">
                Peak Mode
                <select
                  value={peakHoldMode}
                  onChange={(event) => {
                    setPeakHoldMode(event.target.value as 'permanent' | 'decay');
                    peakHoldTimestampRef.current = null;
                  }}
                  className="h-9 w-28 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  <option value="permanent">Permanent</option>
                  <option value="decay">Decay</option>
                </select>
              </label>
              {peakHoldMode === 'decay' && (
                <label className="flex flex-col gap-1 text-[11px] text-slate-400">
                  Decay
                  <select
                    value={peakHoldDecayDbPerSecond}
                    onChange={(event) => setPeakHoldDecayDbPerSecond(Number(event.target.value))}
                    className="h-9 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                  >
                    <option value={1}>1 dB/s</option>
                    <option value={3}>3 dB/s</option>
                    <option value={6}>6 dB/s</option>
                  </select>
                </label>
              )}
              <button
                onClick={() => {
                  setPeakHoldData(null);
                  peakHoldTimestampRef.current = null;
                }}
                className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
                title="Clear the current peak trace"
              >
                Reset Peaks
              </button>
              <button
                onClick={() => setUsePeakTraceForDetection((current) => !current)}
                aria-pressed={usePeakTraceForDetection}
                className={cn(
                  'h-9 flex items-center px-3 rounded-md text-sm',
                  usePeakTraceForDetection ? 'bg-orange-300 text-slate-950 hover:bg-orange-200' : 'bg-slate-700 hover:bg-slate-600',
                )}
                title="Use the Peak Hold trace for markers, measurements, local detection and overlay prediction requests"
              >
                Use Peak For Detection
              </button>
            </>
          )}

          <button
            onClick={() => setShowWaterfallSplit((current) => !current)}
            aria-pressed={showWaterfallSplit}
            title={showWaterfallSplit ? 'Volver a solo espectro' : 'Dividir vista con waterfall'}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              showWaterfallSplit ? 'bg-cyan-500 text-slate-950 hover:bg-cyan-400' : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <BarChart3 className="w-4 h-4 mr-2" />
            {showWaterfallSplit ? 'Spectrum Only' : 'Spectrum + Waterfall'}
          </button>

          <button
            onClick={() => setShowPanOverlay((current) => !current)}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            {showPanOverlay ? <EyeOff className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
            Pan Overlay
          </button>

          <button
            onClick={() => setShowMarkerBadges((current) => !current)}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            {showMarkerBadges ? <EyeOff className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
            Marker Badges
          </button>

          <button
            onClick={() => setShowCursorBadge((current) => !current)}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            {showCursorBadge ? <EyeOff className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
            Cursor Badge
          </button>

          <button
            onClick={() => setShowRfIntelligenceOverlay((current) => !current)}
            aria-pressed={showRfIntelligenceOverlay}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              showRfIntelligenceOverlay ? 'bg-amber-400 text-slate-950 hover:bg-amber-300' : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <BrainCircuit className="w-4 h-4 mr-2" />
            RF Overlay
          </button>

          <button
            onClick={() => setShowRsuOverlay((current) => !current)}
            aria-pressed={showRsuOverlay}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              showRsuOverlay ? 'bg-cyan-300 text-slate-950 hover:bg-cyan-200' : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <ScanSearch className="w-4 h-4 mr-2" />
            Understanding Overlay
          </button>

          {showRsuOverlay && (
            <button
              onClick={() => setRsuOverlayMode((current) => current === 'hybrid' ? 'ai_only' : 'hybrid')}
              aria-pressed={rsuOverlayMode === 'ai_only'}
              title={rsuOverlayMode === 'ai_only' ? 'Solo muestra regiones clasificadas por el modelo entrenado' : 'Mezcla detector/reglas con modelo entrenado'}
              className={cn(
                'h-9 flex items-center px-3 rounded-md text-sm font-medium',
                rsuOverlayMode === 'ai_only' ? 'bg-fuchsia-300 text-slate-950 hover:bg-fuchsia-200' : 'bg-slate-700 hover:bg-slate-600'
              )}
            >
              <BrainCircuit className="w-4 h-4 mr-2" />
              {rsuOverlayMode === 'ai_only' ? 'AI Only' : 'Hybrid'}
            </button>
          )}

          <button
            onClick={() => setShowRfExperimentOverlay((current) => !current)}
            aria-pressed={showRfExperimentOverlay}
            title="Muestra estado de modelos experimentales E1/E3/E5. No inventa inferencia live si no hay pipeline validado."
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              showRfExperimentOverlay ? 'bg-emerald-300 text-slate-950 hover:bg-emerald-200' : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <FlaskConical className="w-4 h-4 mr-2" />
            Experiment Overlay{selectedRfExperimentType ? ` (${selectedRfExperimentType === 'best' ? 'Best' : selectedRfExperimentType.toUpperCase()})` : ''}
          </button>

          <div className="flex items-center gap-1">
            {(['best', 'e5', 'e1', 'e3'] as const).map((type) => (
              <button
                key={type}
                type="button"
                disabled={!showRfExperimentOverlay}
                onClick={() => setSelectedRfExperimentType(type)}
                className={cn(
                  'h-9 rounded-md px-3 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed',
                  selectedRfExperimentType === type
                    ? 'bg-slate-200 text-slate-950 border border-slate-300'
                    : 'bg-slate-700 hover:bg-slate-600 text-slate-100',
                )}
                title={showRfExperimentOverlay ? `Select ${RF_EXPERIMENT_TYPE_LABELS[type]}` : 'Enable Experiment Overlay first'}
              >
                {type === 'best' ? 'Best' : type.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="h-9 w-px bg-slate-700 mx-1" />

          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            RF Profile
            <select
              value={selectedProfileKey}
              onChange={(event) => applySelectedRFProfile(event.target.value)}
              disabled={isFrozen}
              className="h-9 w-64 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400 disabled:opacity-50"
              title="Applies stable RF observation settings and M1-M2 profile markers"
            >
              <option value="">Manual / no profile</option>
              {RF_PROFILE_LIST.map((profile) => (
                <option key={profile.key} value={profile.key}>{profile.label}</option>
              ))}
            </select>
          </label>

          <LabeledInput label="Center MHz" value={centerMHz} onChange={setCenterMHz} onEnter={applyCenterSpan} />
          <LabeledInput label="Span MHz" value={spanMHz} onChange={setSpanMHz} onEnter={applyCenterSpan} />
          <button onClick={applyCenterSpan} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">Apply</button>
          <LabeledInput label="Step MHz" value={panStepMHz} onChange={setPanStepMHz} onEnter={() => undefined} compact />
          <button
            onClick={() => panFrequencyWindow(-1)}
            title="Desplazar espectro hacia la izquierda"
            className="h-9 inline-flex items-center gap-1.5 rounded-md bg-cyan-700 px-3 text-sm font-semibold text-white hover:bg-cyan-600"
          >
            <ChevronLeft className="w-5 h-5" />
            Spectrum Left
          </button>
          <button
            onClick={() => panFrequencyWindow(1)}
            title="Desplazar espectro hacia la derecha"
            className="h-9 inline-flex items-center gap-1.5 rounded-md bg-cyan-700 px-3 text-sm font-semibold text-white hover:bg-cyan-600"
          >
            Spectrum Right
            <ChevronRight className="w-5 h-5" />
          </button>

          <LabeledInput label="Start MHz" value={startMHz} onChange={setStartMHz} onEnter={applyStartStop} />
          <LabeledInput label="Stop MHz" value={stopMHz} onChange={setStopMHz} onEnter={applyStartStop} />
          <button onClick={applyStartStop} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">Set Edges</button>

          <LabeledInput label="RBW kHz" value={rbwKHz} onChange={setRbwKHz} onEnter={applyResolution} compact />
          <LabeledInput label="VBW kHz" value={vbwKHz} onChange={setVbwKHz} onEnter={applyResolution} compact />
          <LabeledInput label="Ref dB" value={refLevel} onChange={setRefLevel} onEnter={applyResolution} compact />
          <LabeledInput label="Offset dB" value={noiseOffset} onChange={setNoiseOffset} onEnter={applyResolution} compact />
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Detector
            <select
              value={detectorMode}
              onChange={(event) => setDetectorMode(event.target.value as AnalyzerSettings['detectorMode'])}
              className="h-9 w-28 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
            >
              {DETECTOR_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Trace
            <select
              value={traceMode}
              onChange={(event) => setTraceMode(event.target.value as AnalyzerSettings['traceMode'])}
              className="h-9 w-28 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
            >
              {TRACE_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </label>
          <LabeledInput label="dB/div" value={dbPerDiv} onChange={setDbPerDiv} onEnter={applyResolution} compact />
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Color
            <select
              value={colorScheme}
              onChange={(event) => setColorScheme(event.target.value as AnalyzerSettings['colorScheme'])}
              className="h-9 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
            >
              {SPECTRUM_COLOR_SCHEMES.map((scheme) => (
                <option key={scheme.value} value={scheme.value}>{scheme.label}</option>
              ))}
            </select>
          </label>
          <LabeledInput label="Avg" value={averaging} onChange={setAveraging} onEnter={applyResolution} compact />
          <button onClick={applyResolution} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">
            <SlidersHorizontal className="w-4 h-4 mr-2 inline-block" />
            Apply Trace
          </button>

          <LabeledInput label="Gain dB" value={gainDb} onChange={setGainDb} onEnter={applyGain} compact />
          <button onClick={applyGain} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">Gain</button>

          <button
            onClick={() => markerController.createPeakMarker()}
            className="h-9 flex items-center px-3 rounded-md bg-purple-600 hover:bg-purple-500 text-sm font-medium"
          >
            <Target className="w-4 h-4 mr-2" />
            Peak
          </button>
          <button
            onClick={centerOnLivePeak}
            disabled={!analysisSpectrumData || analysisSpectrumData.frequencyArray.length === 0}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              !analysisSpectrumData || analysisSpectrumData.frequencyArray.length === 0
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-emerald-700 hover:bg-emerald-600 text-white'
            )}
          >
            <Target className="w-4 h-4 mr-2" />
            Center On Peak
          </button>
          <button
            onClick={createAutoPeaks}
            className="h-9 flex items-center px-3 rounded-md bg-purple-700 hover:bg-purple-600 text-sm font-medium"
          >
            Auto Peaks
          </button>
          <button
            onClick={() => removeLastMarker()}
            disabled={markerRows.length === 0}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm',
              markerRows.length === 0
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Remove One
          </button>
          <button
            onClick={() => markerController.clearAllMarkers()}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Clear
          </button>
          <button onClick={exportCsv} className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">
            <Download className="w-4 h-4 mr-2" />
            CSV
          </button>
          <button onClick={exportPng} className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">
            <Image className="w-4 h-4 mr-2" />
            PNG
          </button>
        </div>
        {controlError && <div className="mt-2 text-sm text-red-300">{controlError}</div>}
        {deviceStatus.lastError && <div className="mt-2 text-sm text-red-300">{deviceStatus.lastError}</div>}
        {showWaterfallSplit && waterfallError && <div className="mt-2 text-sm text-red-300">{waterfallError}</div>}
        {showRfIntelligenceOverlay && rfOverlayError && <div className="mt-2 text-sm text-amber-200">RF Intelligence overlay: {rfOverlayError}</div>}
        {showRsuOverlay && rsuOverlayError && <div className="mt-2 text-sm text-cyan-200">RF Signal Understanding overlay: {rsuOverlayError}</div>}
        {showRfExperimentOverlay && rfExperimentOverlayError && <div className="mt-2 text-sm text-emerald-200">RF Experiment overlay: {rfExperimentOverlayError}</div>}
      </div>

      <div className="flex-1 grid grid-cols-[minmax(0,1fr)_320px] min-h-0">
        <div className="flex min-h-0 flex-col">
          <div className={cn('relative min-h-0', showWaterfallSplit ? 'flex-[3_1_0%]' : 'flex-1')}>
            {showPanOverlay && (
              <div
                className="absolute z-10 rounded-xl border border-slate-700/80 bg-slate-950/60 px-2 py-2 shadow-lg backdrop-blur-md"
                style={{ left: `${panOverlayPosition.x}px`, top: `${panOverlayPosition.y}px` }}
              >
                <div
                  className="mb-2 flex cursor-move items-center justify-between gap-2 rounded-lg bg-slate-900/70 px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-300"
                  onMouseDown={startOverlayDrag}
                >
                  <div className="flex items-center gap-1">
                    <Move className="w-3 h-3" />
                    Pan
                  </div>
                  <button
                    onClick={() => setShowPanOverlay(false)}
                    className="rounded-md p-1 text-slate-300 hover:bg-slate-800"
                    title="Ocultar panel"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => panFrequencyWindow(-1)}
                    title="Desplazar espectro hacia la izquierda"
                    className="h-8 inline-flex items-center gap-1 rounded-md bg-cyan-700/85 px-2 text-xs font-semibold text-white hover:bg-cyan-600"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Left
                  </button>
                  <LabeledInput label="Step MHz" value={panStepMHz} onChange={setPanStepMHz} onEnter={() => undefined} compact />
                  <button
                    onClick={() => panFrequencyWindow(1)}
                    title="Desplazar espectro hacia la derecha"
                    className="h-8 inline-flex items-center gap-1 rounded-md bg-cyan-700/85 px-2 text-xs font-semibold text-white hover:bg-cyan-600"
                  >
                    Right
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
            <canvas
              ref={canvasRef}
              width={1400}
              height={720}
              className="w-full h-full cursor-crosshair bg-slate-950"
              onClick={addMarkerAtCanvas}
              onMouseDown={startMarkerDrag}
              onMouseMove={(event) => {
                dragOverlay(event);
                updateCursor(event);
              }}
              onMouseUp={() => {
                setDraggingMarkerId(null);
                stopOverlayDrag();
              }}
              onMouseLeave={() => {
                setCursor(null);
                setDraggingMarkerId(null);
                stopOverlayDrag();
              }}
              onWheel={zoomFromWheel}
            />
            {showRfIntelligenceOverlay && (
              <div className="pointer-events-none absolute inset-0 z-[8]">
                {visibleRfDetections.map((detection, index) => (
                  <RfDetectionBand
                    key={`${detection.track_id ?? detection.id}-${detection.start_frequency_hz}-${detection.stop_frequency_hz}`}
                    detection={detection}
                    centerFrequency={displaySettings.centerFrequency}
                    span={displaySettings.span}
                    row={index}
                  />
                ))}
                <div className="absolute left-12 top-12 rounded-md border border-amber-300/30 bg-slate-950/35 px-2 py-1 text-[10px] uppercase tracking-[0.16em] text-amber-100 shadow-lg backdrop-blur-sm">
                  RF intelligence {isFrozen ? 'frozen' : 'live'}
                </div>
              </div>
            )}
            {showRsuOverlay && (
              <div className="pointer-events-none absolute inset-0 z-[9]">
                {visibleRsuRegions.map((region, index) => (
                  <RsuDetectionBand
                    key={`${region.bbox_id}-${region.freq_start_hz}-${region.freq_end_hz}`}
                    region={region}
                    centerFrequency={displaySettings.centerFrequency}
                    span={displaySettings.span}
                    row={index}
                  />
                ))}
                <div className="absolute left-12 top-24 rounded-md border border-cyan-200/35 bg-slate-950/30 px-2 py-1 text-[10px] uppercase tracking-[0.16em] text-cyan-100 shadow-lg backdrop-blur-sm">
                  RF signal understanding {isFrozen ? 'frozen' : 'live'}
                </div>
              </div>
            )}
            {showRfExperimentOverlay && (
              <div className="pointer-events-none absolute inset-0 z-[10]">
                {/* Status card */}
                <div className="absolute left-12 top-36 max-w-xs rounded-md border border-emerald-200/35 bg-slate-950/80 px-3 py-2 text-[10px] text-emerald-100 shadow-lg backdrop-blur-sm">
                  <div className="flex items-center justify-between">
                    <span className="uppercase tracking-[0.16em]">RF Experiment Lab</span>
                    {selectedRfExperimentRun?.ready_for_live_inference && (
                      <span className="ml-2 rounded-full bg-emerald-500/20 px-1.5 py-0.5 text-[9px] text-emerald-300">LIVE</span>
                    )}
                  </div>
                  <div className="mt-1 text-[10px] text-slate-400">
                    {selectedRfExperimentType ? RF_EXPERIMENT_TYPE_LABELS[selectedRfExperimentType] : 'no type selected'}
                    {selectedRfExperimentRun ? ` · ${String(selectedRfExperimentRun.model_id ?? selectedRfExperimentRun.experiment_id ?? '').split(':')[1]?.slice(0, 16) ?? ''}` : ''}
                  </div>
                  {liveInferenceResult?.status === 'ok' ? (
                    <>
                      <div className="mt-2 text-[15px] font-bold leading-tight text-emerald-200">{String(liveInferenceResult.predicted_label)}</div>
                      <div className="mt-0.5 text-[11px] text-slate-200">
                        {liveInferenceResult.confidence != null
                          ? `${(Number(liveInferenceResult.confidence) * 100).toFixed(1)}% confidence`
                          : 'confidence n/a'}
                      </div>
                      <div className="mt-1 text-[10px] text-slate-400">
                        Task: {String(liveInferenceResult.task ?? 'unknown')}
                        {liveInferenceResult.latency_ms != null ? ` · ${Number(liveInferenceResult.latency_ms).toFixed(1)} ms` : ''}
                        {liveInferenceResult.marker_filtered ? ' · marker band' : ' · full span'}
                      </div>
                    </>
                  ) : liveInferenceResult?.status === 'incompatible' ? (
                    <div className="mt-1.5 text-[10px] text-amber-300/90">
                      {String((liveInferenceResult.rejection_reasons as string[])?.[0] ?? 'Incompatible with live stream')}
                    </div>
                  ) : liveInferenceResult?.status === 'not_ready' ? (
                    <div className="mt-1.5 text-[10px] text-slate-400">
                      Not ready: {String((liveInferenceResult.rejection_reasons as string[])?.[0] ?? 'model did not pass readiness gate')}
                    </div>
                  ) : selectedRfExperimentRun ? (
                    <>
                      <div className="mt-1.5 text-[11px] text-slate-300">
                        Macro F1: {String(selectedRfExperimentRun.metrics_summary?.macro_f1 ?? 'n/a')} | Acc: {String(selectedRfExperimentRun.metrics_summary?.accuracy ?? 'n/a')}
                      </div>
                      <div className="mt-0.5 text-[10px] text-slate-500">
                        {selectedRfExperimentRun.live_compatible
                          ? 'Waiting for spectrum data…'
                          : 'Batch-only — capture IQ for inference.'}
                      </div>
                    </>
                  ) : (
                    <div className="mt-1.5 text-[10px] text-slate-500">No validated model available.</div>
                  )}
                </div>
                {/* Band annotation when live inference is successful and marker band is set */}
                {liveInferenceResult?.status === 'ok' && markerBand && (() => {
                  const specStart = displaySettings.centerFrequency - displaySettings.span / 2;
                  const leftPct = ((markerBand.start - specStart) / displaySettings.span) * 100;
                  const widthPct = (markerBand.span / displaySettings.span) * 100;
                  if (leftPct < -5 || leftPct + widthPct > 105 || widthPct < 0.1) return null;
                  const clampedLeft = Math.max(0, leftPct);
                  const clampedWidth = Math.min(100 - clampedLeft, widthPct);
                  return (
                    <div
                      className="absolute top-0 bottom-0 border-l border-r border-emerald-400/50 bg-emerald-400/[0.07]"
                      style={{ left: `${clampedLeft}%`, width: `${clampedWidth}%` }}
                    >
                      <div className="absolute top-2 left-1/2 -translate-x-1/2 rounded-md border border-emerald-300/40 bg-emerald-950/85 px-2 py-0.5 text-[10px] text-emerald-100 whitespace-nowrap backdrop-blur-sm shadow">
                        {String(liveInferenceResult.predicted_label)}
                        {liveInferenceResult.confidence != null
                          ? ` · ${(Number(liveInferenceResult.confidence) * 100).toFixed(0)}%`
                          : ''}
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
            {cursor && showCursorBadge && (
              <div className="absolute right-4 top-4 z-10 rounded-lg border border-slate-700/80 bg-slate-950/55 px-2 py-1 text-[11px] text-slate-100 shadow-lg backdrop-blur-md">
                {formatFrequency(cursor.frequency)} | {formatPowerLevel(cursor.level)}
              </div>
            )}
            {showMarkerBadges && markerRows.map((marker) => {
              const start = displaySettings.centerFrequency - displaySettings.span / 2;
              const position = ((marker.frequency - start) / displaySettings.span) * 100;
              if (position < 0 || position > 100) return null;
              return (
                <div
                  key={marker.id}
                  className="absolute top-0 bottom-0 border-l border-amber-300/70 pointer-events-none"
                  style={{ left: `${position}%` }}
                >
                  <div className="ml-1 mt-1 rounded-md border border-amber-300/40 bg-amber-300/18 px-1.5 py-0.5 text-[10px] whitespace-nowrap text-amber-100 backdrop-blur-sm">
                    {marker.label} {formatFrequency(marker.frequency)}
                  </div>
                </div>
              );
            })}
          </div>

          {showWaterfallSplit && (
            <div className="relative min-h-[180px] flex-[2_1_0%] border-t border-slate-700 bg-black">
              <div className="absolute left-4 top-3 z-10 rounded-md border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs text-slate-100 shadow-lg">
                Waterfall | {formatFrequency(displaySettings.centerFrequency - displaySettings.span / 2)} - {formatFrequency(displaySettings.centerFrequency + displaySettings.span / 2)}
              </div>
              <canvas
                ref={waterfallCanvasRef}
                width={1400}
                height={420}
                className="h-full w-full bg-black"
              />
              <div className="absolute bottom-2 left-10 right-10 flex justify-between text-xs text-slate-300">
                <span>{formatFrequency(displaySettings.centerFrequency - displaySettings.span / 2)}</span>
                <span>{formatFrequency(displaySettings.centerFrequency)}</span>
                <span>{formatFrequency(displaySettings.centerFrequency + displaySettings.span / 2)}</span>
              </div>
              <div className="absolute right-4 top-3 bottom-8 w-4 rounded-sm bg-gradient-to-b from-red-600 via-yellow-400 via-green-500 to-blue-900" />
            </div>
          )}
        </div>

        <aside className="border-l border-slate-800 bg-slate-900 p-3 overflow-auto">
          <div className="text-xs uppercase text-slate-400 mb-2">Device Status</div>
          <StatusRow label="View" value={isFrozen ? 'Frozen View' : 'Live View'} tone={isFrozen ? undefined : 'ok'} />
          <StatusRow label="Status" value={deviceStatus.isConnected ? 'Connected' : 'Disconnected'} tone={deviceStatus.isConnected ? 'ok' : 'bad'} />
          <StatusRow label="Driver" value={deviceStatus.driver} />
          <StatusRow label="RF Profile" value={selectedProfile?.label ?? 'manual'} tone={selectedProfile ? 'ok' : undefined} />
          <StatusRow
            label="Experiment Model"
            value={selectedRfExperimentType ? RF_EXPERIMENT_TYPE_LABELS[selectedRfExperimentType] : 'none'}
            tone={selectedRfExperimentType ? 'ok' : undefined}
          />
          <StatusRow label="Center" value={formatFrequency(displaySettings.centerFrequency)} />
          <StatusRow label="Span" value={formatFrequency(displaySettings.span)} />
          <StatusRow label="Start" value={formatFrequency(displaySettings.centerFrequency - displaySettings.span / 2)} />
          <StatusRow label="Stop" value={formatFrequency(displaySettings.centerFrequency + displaySettings.span / 2)} />
          <StatusRow label="Sample Rate" value={formatFrequency(deviceStatus.sampleRate || settings.span) + '/s'} />
          <StatusRow label="RBW" value={formatFrequency(settings.rbw)} />
          <StatusRow label="VBW" value={formatFrequency(settings.vbw)} />
          <StatusRow label="Ref" value={formatPowerLevel(settings.referenceLevel)} />
          <StatusRow label="Offset" value={formatPowerLevel(settings.noiseFloorOffset)} />
          <StatusRow label="Detector" value={settings.detectorMode} />
          <StatusRow label="Trace" value={settings.traceMode} />
          <StatusRow
            label="Peak Hold"
            value={peakHoldEnabled ? (peakHoldMode === 'decay' ? `decay ${peakHoldDecayDbPerSecond} dB/s` : 'permanent') : 'off'}
            tone={peakHoldEnabled ? 'ok' : undefined}
          />
          <StatusRow label="Peak Source" value={usePeakTraceForDetection && peakHoldEnabled ? 'measure/detect' : 'visual only'} />
          <StatusRow label="Marker BPF" value={markerBandpassEnabled ? 'ON' : 'OFF'} tone={markerBandpassEnabled ? 'ok' : undefined} />
          {markerBand && (
            <>
              <StatusRow label="Filter source" value={`${markerBand.firstLabel} - ${markerBand.secondLabel}`} />
              <StatusRow label="Band start" value={formatFrequency(markerBand.start)} />
              <StatusRow label="Band stop" value={formatFrequency(markerBand.stop)} />
              <StatusRow label="Filter BW" value={formatFrequency(markerBand.span)} />
              <StatusRow label="Attenuation" value={`${markerBandpassAttenuationDb} dB`} />
              <StatusRow label="Filter mode" value="FFT mask preview / FIR on I/Q capture" />
              <StatusRow label="Filter valid" value={markerBandpassIsValid ? 'yes' : 'outside span'} tone={markerBandpassIsValid ? 'ok' : 'bad'} />
            </>
          )}
          <StatusRow label="Scale" value={`${settings.dbPerDiv} dB/div`} />
          <StatusRow label="Averaging" value={`${settings.averaging}x`} />
          <StatusRow label="Gain" value={formatPowerLevel(deviceStatus.gain)} />

          {selectedProfile && (
            <>
              <div className="mt-5 text-xs uppercase text-slate-400 mb-2">RF Profile Metadata</div>
              <StatusRow label="Profile key" value={selectedProfile.key} />
              <StatusRow label="Signal type" value={selectedProfile.signal_type} />
              <StatusRow label="Family" value={selectedProfile.family} />
              <StatusRow label="Modulation" value={selectedProfile.modulation.join(', ')} />
              <StatusRow label="Temporal" value={selectedProfile.temporal_pattern} />
              <StatusRow label="Expected BW" value={selectedProfile.expected_bandwidth_hz.map(formatBandwidth).join(', ')} />
              <StatusRow label="Capture" value={`${selectedProfile.capture_duration_seconds}s @ ${formatFrequency(selectedProfile.sample_rate_hz)}/s`} />
              <div className="mt-2 rounded-md border border-slate-800 bg-slate-950/50 px-2 py-2 text-xs text-slate-300">
                {selectedProfile.training_note}
              </div>
            </>
          )}

          <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Trace Stats</div>
          <StatusRow label="Mean" value={formatPowerLevel(traceStats.mean)} />
          <StatusRow label="Max" value={formatPowerLevel(traceStats.max)} />
          <StatusRow label="Min" value={formatPowerLevel(traceStats.min)} />
          <StatusRow label="Std Dev" value={formatPowerLevel(traceStats.std)} />

          {showRfIntelligenceOverlay && (
            <>
              <div className="mt-5 flex items-center justify-between gap-2">
                <div className="text-xs uppercase text-slate-400">RF Intelligence</div>
                <div className="rounded-full border border-amber-300/30 bg-amber-300/10 px-2 py-0.5 text-[10px] text-amber-100">
                  {visibleRfDetections.length} live
                </div>
              </div>
              <div className="mt-2 space-y-2">
                {visibleRfDetections.length === 0 ? (
                  <div className="rounded-md border border-slate-800 bg-slate-950/50 px-2 py-2 text-xs text-slate-400">
                    No RF objects above threshold in this span.
                  </div>
                ) : visibleRfDetections.slice(0, 5).map((detection) => {
                  const style = rfFamilyStyle(detection.candidate_family);
                  return (
                    <div key={detection.track_id ?? detection.id} className={cn('rounded-md border px-2 py-2 text-xs', style.badge)}>
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-semibold text-slate-100">{detection.label}</span>
                        <span className="text-amber-100">{Math.round(detection.confidence * 100)}%</span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-slate-300">
                        <span>{formatFrequency(detection.center_frequency_hz)}</span>
                        <span className="text-right">{formatBandwidth(Math.max(detection.bandwidth_hz, detection.occupied_bandwidth_hz))}</span>
                        <span>SNR {detection.snr_db.toFixed(1)} dB</span>
                        <span className="text-right">{detection.temporal_type.replace('_', ' ')}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {showRsuOverlay && (
            <>
              <div className="mt-5 flex items-center justify-between gap-2">
                <div className="text-xs uppercase text-slate-400">Signal Understanding</div>
                <div className="rounded-full border border-cyan-200/30 bg-cyan-300/10 px-2 py-0.5 text-[10px] text-cyan-100">
                  {visibleRsuRegions.length} live · {rsuOverlayMode === 'ai_only' ? 'AI only' : 'hybrid'}
                </div>
              </div>
              <div className="mt-2 space-y-2">
                {visibleRsuRegions.length === 0 ? (
                  <div className="rounded-md border border-slate-800 bg-slate-950/50 px-2 py-2 text-xs text-slate-400">
                    No time-frequency regions above the understanding threshold.
                  </div>
                ) : visibleRsuRegions.slice(0, 5).map((region) => {
                  const decision = region.final_decision ?? {};
                  const spectral = region.features?.spectral ?? {};
                  const trained = region.classification?.trained;
                  return (
                    <div key={region.bbox_id} className="rounded-md border border-cyan-200/35 bg-cyan-300/10 px-2 py-2 text-xs">
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-semibold text-cyan-50">{decision.label ?? 'unknown'}</span>
                        <span className="text-cyan-100">{Math.round(Number(decision.confidence ?? 0) * 100)}%</span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-slate-300">
                        <span>{formatFrequency((Number(region.freq_start_hz) + Number(region.freq_end_hz)) / 2)}</span>
                        <span className="text-right">{formatBandwidth(Number(region.freq_end_hz) - Number(region.freq_start_hz))}</span>
                        <span>SNR {Number(spectral.snr_db ?? 0).toFixed(1)} dB</span>
                        <span className="text-right">{trained ? 'AI' : decision.status ?? 'unknown'}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {showRfExperimentOverlay && (
            <>
              <div className="mt-5 flex items-center justify-between gap-2">
                <div className="text-xs uppercase text-slate-400">Experiment Lab</div>
                <div className="rounded-full border border-emerald-200/30 bg-emerald-300/10 px-2 py-0.5 text-[10px] text-emerald-100">
                  {(rfExperimentOverlay?.models ?? []).length} models
                </div>
              </div>
              <div className="mt-2 space-y-2">
                {liveInferenceResult?.status === 'ok' ? (
                  <div className="rounded-md border border-emerald-500/30 bg-emerald-950/50 px-2 py-2 text-xs">
                    <div className="font-semibold text-emerald-200">Live Inference Result</div>
                    <div className="mt-1 text-[13px] font-bold text-emerald-100">{String(liveInferenceResult.predicted_label)}</div>
                    <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-slate-300">
                      <span>Confidence</span>
                      <span className="text-right">
                        {liveInferenceResult.confidence != null ? `${(Number(liveInferenceResult.confidence) * 100).toFixed(1)}%` : 'n/a'}
                      </span>
                      <span>Task</span>
                      <span className="text-right">{String(liveInferenceResult.task ?? 'unknown')}</span>
                      <span>Latency</span>
                      <span className="text-right">
                        {liveInferenceResult.latency_ms != null ? `${Number(liveInferenceResult.latency_ms).toFixed(1)} ms` : 'n/a'}
                      </span>
                      <span>Source</span>
                      <span className="text-right">{liveInferenceResult.marker_filtered ? 'marker band' : 'full span'}</span>
                    </div>
                    {Array.isArray(liveInferenceResult.top_k) && liveInferenceResult.top_k.length > 1 && (
                      <div className="mt-2">
                        <div className="text-[10px] text-slate-400 mb-1">Top candidates</div>
                        {(liveInferenceResult.top_k as Array<{ label: string; score: number }>).slice(0, 3).map((item) => (
                          <div key={item.label} className="flex items-center gap-1 text-[10px]">
                            <span className="flex-1 text-slate-300 truncate">{item.label}</span>
                            <span className="text-slate-400">{(item.score * 100).toFixed(0)}%</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : rfExperimentOverlay?.best ? (
                  <div className="rounded-md border border-slate-800 bg-slate-950/50 px-2 py-2 text-xs">
                    <div className="font-semibold text-slate-100">{String(rfExperimentOverlay.best.experiment_type)}</div>
                    <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-slate-300">
                      <span>Macro F1</span>
                      <span className="text-right">{String(rfExperimentOverlay.best.metrics_summary?.macro_f1 ?? 'n/a')}</span>
                      <span>Accuracy</span>
                      <span className="text-right">{String(rfExperimentOverlay.best.metrics_summary?.accuracy ?? 'n/a')}</span>
                      <span>Task</span>
                      <span className="text-right">{String(rfExperimentOverlay.best.task ?? 'unknown')}</span>
                    </div>
                    {liveInferenceResult?.status === 'incompatible' && (
                      <div className="mt-1.5 text-[10px] text-amber-300/80">
                        {String((liveInferenceResult.rejection_reasons as string[])?.[0] ?? 'Incompatible')}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-md border border-slate-800 bg-slate-950/50 px-2 py-2 text-xs text-slate-400">
                    No E1/E3/E5 experiment results have been validated yet.
                  </div>
                )}
              </div>
            </>
          )}

          {deltaMarker && (
            <>
              <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Delta M2-M1</div>
              <StatusRow label="Delta F" value={formatFrequency(deltaMarker.frequencyDelta)} />
              <StatusRow label="Delta L" value={formatPowerLevel(deltaMarker.levelDelta)} />
            </>
          )}

          {liveMarkerBandQuality && (
            <>
              <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Marker-Band QC</div>
              <StatusRow label="Auto Freeze" value={autoFreezeArmed ? `armed >= ${AUTO_FREEZE_TRIGGER_SNR_DB} dB` : 'off'} />
              {markerBand && <StatusRow label="Listen center" value={formatFrequency(markerBand.center)} />}
              {markerBand && (
                <StatusRow
                  label="Signal BW gate"
                  value={`${formatBandwidth(markerBand.span * AUTO_FREEZE_MIN_RELATIVE_BW)} - ${formatBandwidth(markerBand.span * AUTO_FREEZE_MAX_RELATIVE_BW)}`}
                />
              )}
              <StatusRow label="Peak" value={formatPowerLevel(liveMarkerBandQuality.peakLevelDb)} />
              <StatusRow label="Noise" value={formatPowerLevel(liveMarkerBandQuality.noiseFloorDb)} />
              <StatusRow label="SNR" value={`${liveMarkerBandQuality.snrDb.toFixed(1)} dB`} />
              <StatusRow label="Peak Freq" value={formatFrequency(liveMarkerBandQuality.peakFrequencyHz)} />
            </>
          )}

          <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Markers</div>
          <div className="overflow-hidden rounded-md border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-800 text-slate-300">
                <tr>
                  <th className="text-left px-2 py-1">ID</th>
                  <th className="text-right px-2 py-1">Frequency</th>
                  <th className="text-right px-2 py-1">Level</th>
                </tr>
              </thead>
              <tbody>
                {markerRows.length === 0 ? (
                  <tr><td colSpan={3} className="px-2 py-3 text-slate-500">Click trace to add marker</td></tr>
                ) : markerRows.map((marker) => (
                  <tr key={marker.id} className="border-t border-slate-800">
                    <td className="px-2 py-1 text-amber-300">{marker.label}</td>
                    <td className="px-2 py-1 text-right">{formatFrequency(marker.frequency)}</td>
                    <td className="px-2 py-1 text-right">{formatPowerLevel(marker.level)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      </div>

      {/* Capture Progress Overlay */}
      {showCaptureProgressOverlay && captureProgressDetails && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="rounded-lg border border-slate-700 bg-slate-900/95 p-6 shadow-xl max-w-md w-full mx-4">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-100">Captura en Progreso</h3>
              {autoFreezeCaptureProcessing && (
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-400 border-t-transparent"></div>
                  Procesando...
                </div>
              )}
            </div>
            <div className="space-y-2 text-sm">
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Start:</span>
                <span className="text-slate-100">{formatFrequency(captureProgressDetails.startFrequencyHz)}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Stop:</span>
                <span className="text-slate-100">{formatFrequency(captureProgressDetails.stopFrequencyHz)}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Gain:</span>
                <span className="text-slate-100">{captureProgressDetails.gainDb.toFixed(1)} dB</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Antenna:</span>
                <span className="text-slate-100">{captureProgressDetails.antenna}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Artifact scope:</span>
                <span className="text-slate-100">{captureProgressDetails.artifactScope}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Tx ID:</span>
                <span className="text-slate-100">{captureProgressDetails.txId}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Class:</span>
                <span className="text-slate-100">{captureProgressDetails.class}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Operator:</span>
                <span className="text-slate-100">{captureProgressDetails.operator}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Environment:</span>
                <span className="text-slate-100">{captureProgressDetails.environment}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">SHA256:</span>
                <span className="text-slate-100 font-mono text-xs">{captureProgressDetails.sha256}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Live preview SNR:</span>
                <span className="text-slate-100">{captureProgressDetails.livePreviewSnrDb ? `${captureProgressDetails.livePreviewSnrDb.toFixed(1)} dB` : 'n/a'}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Live preview noise:</span>
                <span className="text-slate-100">{captureProgressDetails.livePreviewNoiseDb ? `${captureProgressDetails.livePreviewNoiseDb.toFixed(1)} dB` : 'n/a'}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Live preview peak:</span>
                <span className="text-slate-100">{captureProgressDetails.livePreviewPeakDb ? `${captureProgressDetails.livePreviewPeakDb.toFixed(1)} dB` : 'n/a'}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Capture mode:</span>
                <span className="text-slate-100">{captureProgressDetails.captureMode}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <span className="text-slate-400">Trigger detected:</span>
                <span className="text-slate-100">{captureProgressDetails.triggerDetected ? 'true' : 'false'}</span>
              </div>
            </div>
            {!autoFreezeCaptureProcessing && (
              <div className="mt-4 flex justify-end">
                <button
                  onClick={() => setShowCaptureProgressOverlay(false)}
                  className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-100 hover:bg-slate-700"
                >
                  Cerrar
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

function LabeledInput({
  label,
  value,
  onChange,
  onEnter,
  compact = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onEnter: () => void;
  compact?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-slate-400">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onEnter();
        }}
        className={cn(
          'h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400',
          compact ? 'w-20' : 'w-28'
        )}
      />
    </label>
  );
}

function RfDetectionBand({
  detection,
  centerFrequency,
  span,
  row,
}: {
  detection: RFObjectDetection;
  centerFrequency: number;
  span: number;
  row: number;
}) {
  const graphWidth = 1400;
  const graphHeight = 720;
  const padding = 40;
  const plotWidth = graphWidth - padding * 2;
  const start = centerFrequency - span / 2;
  const stop = centerFrequency + span / 2;
  const clippedStart = Math.max(detection.start_frequency_hz, start);
  const clippedStop = Math.min(detection.stop_frequency_hz, stop);
  const leftPx = padding + ((clippedStart - start) / span) * plotWidth;
  const rightPx = padding + ((clippedStop - start) / span) * plotWidth;
  const leftPct = (leftPx / graphWidth) * 100;
  const widthPct = Math.max(0.35, ((rightPx - leftPx) / graphWidth) * 100);
  const topPct = (padding / graphHeight) * 100;
  const bottomPct = (padding / graphHeight) * 100;
  const style = rfFamilyStyle(detection.candidate_family);
  const labelTop = 58 + row * 34;

  return (
    <div
      className="absolute"
      style={{
        left: `${leftPct}%`,
        width: `${widthPct}%`,
        top: `${topPct}%`,
        bottom: `${bottomPct}%`,
      }}
    >
      <div
        className="absolute inset-y-0 left-0 right-0 rounded-sm border-x-2 border-t border-b shadow-[0_0_22px_rgba(255,255,255,0.08)]"
        style={{ borderColor: style.border, background: style.fill }}
      />
      <div className="absolute inset-y-0 left-1/2 border-l border-white/25" />
      <div
        className={cn(
          'absolute min-w-[13rem] max-w-[24rem] rounded-md border px-2 py-1 text-[11px] shadow-xl backdrop-blur-md',
          style.text,
          style.badge,
        )}
        style={{ top: `${labelTop}px`, left: 0 }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-semibold">{detection.label}</span>
          <span className="shrink-0 text-amber-100">{Math.round(detection.confidence * 100)}%</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-slate-200/95">
          <span>{formatFrequency(detection.center_frequency_hz)}</span>
          <span>{formatBandwidth(Math.max(detection.bandwidth_hz, detection.occupied_bandwidth_hz))}</span>
          <span>SNR {detection.snr_db.toFixed(1)} dB</span>
        </div>
      </div>
    </div>
  );
}

function RsuDetectionBand({
  region,
  centerFrequency,
  span,
  row,
}: {
  region: Record<string, any>;
  centerFrequency: number;
  span: number;
  row: number;
}) {
  const graphWidth = 1400;
  const graphHeight = 720;
  const padding = 40;
  const plotWidth = graphWidth - padding * 2;
  const start = centerFrequency - span / 2;
  const stop = centerFrequency + span / 2;
  const regionStart = Number(region.freq_start_hz);
  const regionStop = Number(region.freq_end_hz);
  const clippedStart = Math.max(regionStart, start);
  const clippedStop = Math.min(regionStop, stop);
  const leftPx = padding + ((clippedStart - start) / span) * plotWidth;
  const rightPx = padding + ((clippedStop - start) / span) * plotWidth;
  const leftPct = (leftPx / graphWidth) * 100;
  const widthPct = Math.max(0.35, ((rightPx - leftPx) / graphWidth) * 100);
  const topPct = (padding / graphHeight) * 100;
  const bottomPct = (padding / graphHeight) * 100;
  const decision = region.final_decision ?? {};
  const classification = region.classification ?? {};
  const labelTop = 112 + row * 34;
  const confidence = Number(decision.confidence ?? 0);

  return (
    <div
      className="absolute"
      style={{
        left: `${leftPct}%`,
        width: `${widthPct}%`,
        top: `${topPct}%`,
        bottom: `${bottomPct}%`,
      }}
    >
      <div
        className="absolute inset-y-0 left-0 right-0 rounded-sm border-x-2 border-t border-b shadow-[0_0_24px_rgba(34,211,238,0.12)]"
        style={{ borderColor: 'rgba(103,232,249,0.88)', background: 'rgba(8,145,178,0.12)' }}
      />
      <div className="absolute inset-y-0 left-1/2 border-l border-cyan-100/35" />
      <div
        className="absolute min-w-[13rem] max-w-[24rem] rounded-md border border-cyan-200/40 bg-cyan-300/15 px-2 py-1 text-[11px] text-cyan-50 shadow-xl backdrop-blur-md"
        style={{ top: `${labelTop}px`, left: 0 }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-semibold">{decision.label ?? 'unknown'}</span>
          <span className="shrink-0 text-cyan-100">{Math.round(confidence * 100)}%</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-slate-100/95">
          <span>{formatFrequency((regionStart + regionStop) / 2)}</span>
          <span>{formatBandwidth(regionStop - regionStart)}</span>
          <span>{classification.visual_label ?? 'visual unknown'}</span>
        </div>
      </div>
    </div>
  );
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'bad' }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-800 py-1.5 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className={cn('text-right font-medium', tone === 'ok' && 'text-green-300', tone === 'bad' && 'text-red-300')}>
        {value}
      </span>
    </div>
  );
}
