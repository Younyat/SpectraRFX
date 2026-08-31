import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { SpectrumData } from '../../shared/types';
import type { SpectrumAnnotation, SpectrumLineSeries, SpectrumRasterLayer, SpectrumToolConfig, SpectrumToolInstance, SpectrumToolKind } from './model/spectrumToolTypes';
import { holdsContainLive, spectrumGeometryKey, updateDensityMatrix, updatePowerAverageDb, updateRmsPowerDb } from './engine/spectrumMath';
import { SPECTRUM_SERIES_IDS } from './engine/seriesIdentity';

export type SpectrumToolsState = Record<SpectrumToolKind, SpectrumToolInstance>;
const PREFERENCES_KEY = 'spectrum-tools-v2-preferences';
const kinds: SpectrumToolKind[] = ['max_hold', 'min_hold', 'power_average', 'rms_power', 'ewma', 'percentiles', 'trace_history', 'density', 'spectrum_mask', 'gated_spectrum', 'zero_span', 'occupancy'];
const colors: Record<SpectrumToolKind, string> = { max_hold: '#fbbf24', min_hold: '#22d3ee', power_average: '#34d399', rms_power: '#a78bfa', ewma: '#fb923c', percentiles: '#e879f9', trace_history: '#60a5fa', density: '#38bdf8', spectrum_mask: '#ef4444', gated_spectrum: '#2dd4bf', zero_span: '#facc15', occupancy: '#10b981' };
const unavailable = new Set<SpectrumToolKind>(['gated_spectrum', 'zero_span']);

const createInitialState = (): SpectrumToolsState => Object.fromEntries(kinds.map((kind) => [kind, {
  active: false, visible: true, status: 'inactive', sampleCount: 0, color: colors[kind], config: kind === 'ewma' ? { ewmaTauSeconds: 1 } : kind === 'percentiles' ? { percentileWindow: 60 } : kind === 'trace_history' ? { historyFrames: 20 } : kind === 'spectrum_mask' ? { maskUpperDb: -40 } : kind === 'occupancy' ? { thresholdDb: -70 } : {},
}])) as SpectrumToolsState;

const finite = (value: number, fallback: number) => Number.isFinite(value) ? value : fallback;
const percentile = (values: number[], q: number) => { const sorted = values.filter(Number.isFinite).sort((a, b) => a - b); if (!sorted.length) return Number.NaN; const p = (sorted.length - 1) * q; const lo = Math.floor(p); const hi = Math.ceil(p); return sorted[lo] + (sorted[hi] - sorted[lo]) * (p - lo); };

interface Buffers { lines: Partial<Record<SpectrumToolKind, number[]>>; counts: Partial<Record<SpectrumToolKind, number[]>>; frames: number[][]; history: number[][]; density: number[]; occupancyActive: number[]; occupancyTotal: number; lastTimestamp?: number; geometry?: string; }
const emptyBuffers = (): Buffers => ({ lines: {}, counts: {}, frames: [], history: [], density: [], occupancyActive: [], occupancyTotal: 0 });

export const useSpectrumTools = (frame: SpectrumData | null, paused: boolean, enabled = true) => {
  const [tools, setTools] = useState<SpectrumToolsState>(createInitialState);
  const [revision, setRevision] = useState(0);
  const buffers = useRef<Buffers>(emptyBuffers());

  useEffect(() => {
    if (!enabled) return;
    try {
      const parsed = JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? 'null') as { version?: number; tools?: Partial<Record<SpectrumToolKind, Partial<SpectrumToolInstance>>> } | null;
      if (parsed?.version !== 2 || !parsed.tools) return;
      setTools((current) => Object.fromEntries(kinds.map((kind) => { const saved = parsed.tools?.[kind]; return [kind, { ...current[kind], active: Boolean(saved?.active) && !unavailable.has(kind), visible: saved?.visible !== false, color: typeof saved?.color === 'string' ? saved.color : current[kind].color, config: { ...current[kind].config, ...(saved?.config ?? {}) } }]; })) as SpectrumToolsState);
    } catch { /* Invalid preferences never block the spectrum. */ }
  }, [enabled]);

  const preferencePayload = useMemo(() => JSON.stringify({ version: 2, tools: Object.fromEntries(kinds.map((kind) => [kind, { active: tools[kind].active, visible: tools[kind].visible, color: tools[kind].color, config: tools[kind].config }])) }), [tools]);
  useEffect(() => {
    if (!enabled) return;
    try { localStorage.setItem(PREFERENCES_KEY, preferencePayload); } catch { /* Storage is optional. */ }
  }, [enabled, preferencePayload]);

  const reset = useCallback((kind: SpectrumToolKind) => {
    delete buffers.current.lines[kind];
    if (kind === 'power_average' || kind === 'rms_power') delete buffers.current.counts[kind];
    if (kind === 'percentiles') buffers.current.frames = [];
    if (kind === 'trace_history') buffers.current.history = [];
    if (kind === 'density') buffers.current.density = [];
    if (kind === 'occupancy') { buffers.current.occupancyActive = []; buffers.current.occupancyTotal = 0; }
    setTools((current) => ({ ...current, [kind]: { ...current[kind], sampleCount: 0, status: current[kind].active ? 'collecting' : 'inactive' } }));
    setRevision((value) => value + 1);
  }, []);
  const setActive = useCallback((kind: SpectrumToolKind, active: boolean) => {
    if (active && unavailable.has(kind)) { setTools((current) => ({ ...current, [kind]: { ...current[kind], active: true, visible: false, status: 'unavailable', message: `${kind === 'zero_span' ? 'Zero Span' : 'Gated Spectrum'} unavailable — IQ timing source required` } })); return; }
    if (!active) reset(kind);
    setTools((current) => ({ ...current, [kind]: { ...current[kind], active, visible: active, status: active ? 'collecting' : 'inactive', message: undefined } }));
  }, [reset]);
  const setVisible = useCallback((kind: SpectrumToolKind, visible: boolean) => setTools((current) => ({ ...current, [kind]: { ...current[kind], visible } })), []);
  const setConfig = useCallback((kind: SpectrumToolKind, config: SpectrumToolConfig) => setTools((current) => ({ ...current, [kind]: { ...current[kind], config: { ...current[kind].config, ...config } } })), []);
  const resetAll = useCallback(() => kinds.forEach(reset), [reset]);
  const disableAll = useCallback(() => kinds.forEach((kind) => setActive(kind, false)), [setActive]);

  useEffect(() => {
    if (!enabled || !frame || paused) return;
    const frequencies = frame.frequencyArray;
    const geometry = spectrumGeometryKey({
      centerFrequencyHz: frame.centerFrequency, spanHz: frame.span,
      sampleRateHz: frame.sampleRateHz, fftSize: frame.fftSize,
      binCount: frequencies.length, firstFrequencyHz: frequencies[0] ?? 0,
      lastFrequencyHz: frequencies[frequencies.length - 1] ?? 0,
      binSpacingHz: frequencies.length > 1 ? frequencies[1] - frequencies[0] : 0,
      effectiveRbwHz: frame.effectiveRbwHz, sourceId: frame.sourceId,
      deviceSerial: frame.deviceSerial, calibrationId: frame.calibrationId,
    });
    const b = buffers.current; const x = frame.powerLevels;
    const geometryChanged = Boolean(b.geometry && b.geometry !== geometry);
    if (geometryChanged) buffers.current = emptyBuffers();
    const state = buffers.current; state.geometry = geometry;
    const timestamp = Number.isFinite(frame.timestamp) ? frame.timestamp : Date.now(); const dt = Math.max(0.001, Math.min(10, (timestamp - (state.lastTimestamp ?? timestamp - 100)) / 1000)); state.lastTimestamp = timestamp;
    const active = kinds.filter((kind) => tools[kind].active && !unavailable.has(kind));
    if (!active.length) return;
    if (tools.max_hold.active) state.lines.max_hold = !state.lines.max_hold ? [...x] : x.map((v, i) => Number.isFinite(v) ? Math.max(finite(state.lines.max_hold?.[i] ?? v, v), v) : state.lines.max_hold?.[i] ?? v);
    if (tools.min_hold.active) state.lines.min_hold = !state.lines.min_hold ? [...x] : x.map((v, i) => Number.isFinite(v) ? Math.min(finite(state.lines.min_hold?.[i] ?? v, v), v) : state.lines.min_hold?.[i] ?? v);
    if (tools[SPECTRUM_SERIES_IDS.powerAverage.processor].active) { const previous = state.lines[SPECTRUM_SERIES_IDS.powerAverage.buffer]; const counts = state.counts[SPECTRUM_SERIES_IDS.powerAverage.buffer] ?? x.map(() => 1); state.lines[SPECTRUM_SERIES_IDS.powerAverage.buffer] = !previous ? [...x] : x.map((v, i) => { if (!Number.isFinite(v)) return previous[i]; const result = updatePowerAverageDb(previous[i], v, counts[i] ?? 1); counts[i] = (counts[i] ?? 1) + 1; return result; }); state.counts[SPECTRUM_SERIES_IDS.powerAverage.buffer] = counts; }
    if (tools[SPECTRUM_SERIES_IDS.rmsPower.processor].active) { const previous = state.lines[SPECTRUM_SERIES_IDS.rmsPower.buffer]; const counts = state.counts[SPECTRUM_SERIES_IDS.rmsPower.buffer] ?? x.map(() => 1); state.lines[SPECTRUM_SERIES_IDS.rmsPower.buffer] = !previous ? [...x] : x.map((v, i) => { if (!Number.isFinite(v)) return previous[i]; const result = updateRmsPowerDb(previous[i], v, counts[i] ?? 1); counts[i] = (counts[i] ?? 1) + 1; return result; }); state.counts[SPECTRUM_SERIES_IDS.rmsPower.buffer] = counts; }
    if (tools.ewma.active) { const previous = state.lines.ewma; const alpha = 1 - Math.exp(-dt / Math.max(0.05, tools.ewma.config.ewmaTauSeconds ?? 1)); state.lines.ewma = !previous ? [...x] : x.map((v, i) => { if (!Number.isFinite(v)) return previous[i]; const p = 10 ** (previous[i] / 10) * (1 - alpha) + 10 ** (v / 10) * alpha; return 10 * Math.log10(p); }); }
    if (tools.percentiles.active) { state.frames.push([...x]); state.frames.splice(0, Math.max(0, state.frames.length - Math.min(600, Math.max(5, tools.percentiles.config.percentileWindow ?? 60)))); }
    if (tools.trace_history.active) { state.history.push([...x]); state.history.splice(0, Math.max(0, state.history.length - Math.min(1200, Math.max(2, tools.trace_history.config.historyFrames ?? 20)))); }
    if (tools.density.active) { const width = Math.min(512, x.length); const height = 128; state.density = updateDensityMatrix(state.density, width, height, x); }
    if (tools.min_hold.active && tools.max_hold.active && state.lines.min_hold && state.lines.max_hold && !holdsContainLive(state.lines.min_hold, x, state.lines.max_hold)) {
      console.error('Spectrum Tools invariant failed: expected Min Hold <= Live <= Max Hold for the same frame and geometry.');
    }
    if (tools.occupancy.active) { if (state.occupancyActive.length !== x.length) state.occupancyActive = x.map(() => 0); const threshold = tools.occupancy.config.thresholdDb ?? -70; x.forEach((v, i) => { if (v > threshold) state.occupancyActive[i] += dt; }); state.occupancyTotal += dt; }
    setTools((current) => Object.fromEntries(kinds.map((kind) => [kind, current[kind].active && !unavailable.has(kind) ? { ...current[kind], status: 'ready', sampleCount: geometryChanged ? 1 : current[kind].sampleCount + 1 } : current[kind]])) as SpectrumToolsState);
    setRevision((value) => value + 1);
  // Tool state changes take effect on the next immutable input frame. Keeping the
  // frame as the clock source prevents status updates from recursively processing it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, frame, paused]);

  useEffect(() => { if (!paused) return; setTools((current) => Object.fromEntries(kinds.map((kind) => [kind, current[kind].active && !unavailable.has(kind) ? { ...current[kind], status: 'paused' } : current[kind]])) as SpectrumToolsState); }, [paused]);

  const outputs = useMemo(() => {
    if (!frame) return { lineSeries: [] as SpectrumLineSeries[], rasterLayers: [] as SpectrumRasterLayer[], annotations: [] as SpectrumAnnotation[] };
    const b = buffers.current; const lineSeries: SpectrumLineSeries[] = []; const add = (kind: SpectrumToolKind, label: string, dash: number[], z: number, data = b.lines[kind], color = tools[kind].color, graphicId = `${kind}-${label}`) => { if (tools[kind].active && data) lineSeries.push({ id: graphicId, toolId: kind, label, frequenciesHz: frame.frequencyArray, powerLevelsDb: data, color, opacity: .9, lineWidth: 1.8, lineDash: dash, visible: tools[kind].visible, zIndex: z }); };
    add(SPECTRUM_SERIES_IDS.powerAverage.result, 'Power Average', [8, 3, 2, 3], 20, b.lines[SPECTRUM_SERIES_IDS.powerAverage.buffer], tools.power_average.color, SPECTRUM_SERIES_IDS.powerAverage.graphic); add(SPECTRUM_SERIES_IDS.rmsPower.result, 'RMS Power over FFT frames', [2, 3], 21, b.lines[SPECTRUM_SERIES_IDS.rmsPower.buffer], tools.rms_power.color, SPECTRUM_SERIES_IDS.rmsPower.graphic); add('ewma', 'EWMA', [10, 4], 22); add('min_hold', 'Min Hold', [6, 4], 29); add('max_hold', 'Max Hold', [], 30);
    if (tools.percentiles.active && b.frames.length) { const palette = ['#e2e8f0', '#f472b6', '#e879f9', '#f43f5e']; [0.5, .9, .95, .99].forEach((q, qi) => add('percentiles', `P${q * 100}`, qi === 0 ? [] : [4 + qi * 2, 3], 23 + qi, frame.powerLevels.map((_, i) => percentile(b.frames.map((row) => row[i]), q)), palette[qi])); }
    if (tools.trace_history.active) b.history.forEach((row, i) => lineSeries.push({ id: `history-${i}`, toolId: 'trace_history', label: 'History', frequenciesHz: frame.frequencyArray, powerLevelsDb: row, color: tools.trace_history.color, opacity: .05 + .35 * (i + 1) / b.history.length, lineWidth: 1, lineDash: [], visible: tools.trace_history.visible, zIndex: 10 }));
    const rasterLayers: SpectrumRasterLayer[] = [];
    if (tools.density.active && b.density.length) rasterLayers.push({ id: 'density', toolId: 'density', kind: 'density', width: Math.min(512, frame.powerLevels.length), height: 128, values: b.density, opacity: .35, visible: tools.density.visible, zIndex: 1 });
    if (tools.occupancy.active && b.occupancyTotal > 0) rasterLayers.push({ id: 'occupancy', toolId: 'occupancy', kind: 'occupancy', width: frame.powerLevels.length, height: 1, values: b.occupancyActive.map((v) => v / b.occupancyTotal), opacity: .8, visible: tools.occupancy.visible, zIndex: 2 });
    const annotations: SpectrumAnnotation[] = tools.spectrum_mask.active ? [{ id: 'mask-upper', toolId: 'spectrum_mask', type: 'mask_upper', coordinates: frame.frequencyArray.map(() => tools.spectrum_mask.config.maskUpperDb ?? -40), label: 'Spectrum Mask', color: tools.spectrum_mask.color, visible: tools.spectrum_mask.visible }] : [];
    return { lineSeries, rasterLayers, annotations };
  }, [frame, revision, tools]);
  return { tools, ...outputs, setActive, setVisible, setConfig, reset, resetAll, disableAll };
};
