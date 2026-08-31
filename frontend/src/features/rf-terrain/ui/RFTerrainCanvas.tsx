import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { RFTerrainRenderer } from '../render/RFTerrainRenderer';
import { colormapFor } from '../render/TerrainColors';
import type { TerrainOverlayId } from '../render/TerrainOverlays';
import {
  RF_TERRAIN_DEFAULT_FREQUENCY_BINS,
  RF_TERRAIN_DEFAULT_HISTORY_ROWS,
  RF_TERRAIN_EXTENDED_HISTORY_ROWS,
  RF_TERRAIN_HEIGHT_VISUAL_SCALE,
  RF_TERRAIN_MAX_EXCESS_DB,
  RF_TERRAIN_RAW_DISPLAY_MAX_DB,
  RF_TERRAIN_RAW_DISPLAY_MIN_DB,
  RF_TERRAIN_SEGMENTATION_GROW_THRESHOLD_DB,
  RF_TERRAIN_DENSITY_SMOOTHING_RADIUS,
} from '../model/rfTerrainConstants';
import type { RFTerrainCameraPreset, RFTerrainMode, TerrainInspectorSelection, TerrainObject, TerrainProcessedRow } from '../model/rfTerrainTypes';
import { findObjectAtPoint } from '../engine/objectSelection';
import { buildSpectralObjectEnvelope, EnvelopeSourceRow } from '../engine/spectralObjectEnvelope';
import { smoothAcrossFrequency } from '../engine/frequencySmoothing';
import { pickTraceValues, RFTerrainTraceSource } from '../engine/traceSource';
import { HUD_BORDER_COLOR, HUD_PANEL_BACKGROUND } from './hud/hudTheme';

export type { RFTerrainTraceSource } from '../engine/traceSource';
// Whether switching trace source/mode/colormap only affects newly-arriving
// rows going forward ('liveEdgeOnly', the historical default -- matches
// how mode/colormap changes have always behaved here) or retroactively
// repaints every currently-visible row from its own real cached values
// ('entireHistory') -- spec-adjacent "apply it only to the latest live
// samples, or to everything visible in the 3D view" request.
export type RFTerrainTraceScope = 'liveEdgeOnly' | 'entireHistory';

export interface RFTerrainCanvasHandle {
  applyRow: (row: TerrainProcessedRow) => void;
  clear: () => void;
  setCameraPreset: (preset: RFTerrainCameraPreset) => void;
  setViewOffset: (offsetRows: number) => void;
  exportPng: () => string | null;
  exportCsv: () => string | null;
  unpinSelection: () => void;
}

// What COLOR encodes, independent of what HEIGHT encodes (mode). Defaults
// to 'magnitude' -- a classic heat-map where equal power/excess gets equal
// color and tall peaks read hot, matching how spectrum-analyzer waterfalls
// are conventionally read. 'persistence'/'occupancy' remain selectable for
// the original spec-intent reading where color carries independent
// information from height.
export type RFTerrainColorSource = 'magnitude' | 'persistence' | 'occupancy';

export interface RFTerrainOverlayToggles {
  maxHold: boolean;
  minHold: boolean;
  average: boolean;
  ewma: boolean;
  p50: boolean;
  p90: boolean;
  p95: boolean;
  p99: boolean;
  historyWireframe: boolean;
  frequencyMarker: boolean;
}

const RIBBON_FIELDS: Record<'maxHold' | 'minHold' | 'average' | 'ewma' | 'p50' | 'p90' | 'p95' | 'p99', keyof TerrainProcessedRow> = {
  maxHold: 'maxHoldDb',
  minHold: 'minHoldDb',
  average: 'averageDb',
  ewma: 'ewmaDb',
  p50: 'p50Db',
  p90: 'p90Db',
  p95: 'p95Db',
  p99: 'p99Db',
};

interface RFTerrainCanvasProps {
  mode: RFTerrainMode;
  colormapName: 'turbo' | 'viridis' | 'grayscale';
  colorSource: RFTerrainColorSource;
  traceSource: RFTerrainTraceSource;
  traceScope: RFTerrainTraceScope;
  objects: TerrainObject[];
  overlays: RFTerrainOverlayToggles;
  maskThresholdDb: number | null;
  onSelect: (selection: TerrainInspectorSelection | null) => void;
  onFpsUpdate: (fps: number) => void;
  onContextLost: () => void;
  onContextRestored: () => void;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

// Per-bin display height for a given mode (spec §64's height/color table):
// RAW normalizes raw power into the fixed display band; Adaptive/Occupancy
// both plot noise-referenced excess as height (they only differ in what
// color encodes). Reused for the terrain itself and for the Max/Min/
// Average reference ribbons so a ribbon and the terrain underneath it are
// always on the same visual scale.
const toDisplayHeight = (rawDb: number, noiseFloorDb: number, mode: RFTerrainMode): number => {
  if (mode === 'raw') {
    return clamp01((rawDb - RF_TERRAIN_RAW_DISPLAY_MIN_DB) / (RF_TERRAIN_RAW_DISPLAY_MAX_DB - RF_TERRAIN_RAW_DISPLAY_MIN_DB)) * RF_TERRAIN_MAX_EXCESS_DB;
  }
  return Math.min(RF_TERRAIN_MAX_EXCESS_DB, Math.max(0, rawDb - noiseFloorDb));
};

// DENSITY mode's terrain SURFACE (only the surface -- ribbons, markers,
// and the Inspector all keep reading the real unsmoothed per-bin value,
// exactly like every other mode, spec §9.3's raycaster-to-source-data
// discipline) reads as a smoothed reconstruction of the same
// noise-referenced excess ADAPTIVE/OCCUPANCY already compute: real
// per-bin values, blended across neighboring bins into one coherent
// curve instead of many independent spikes. Never claimed as a
// calibrated Power Spectral Density (the technical report explicitly
// refuses to fabricate PSD from uncalibrated dBFS) -- purely a
// readability smoothing of the same real excess quantity.
const computeDensitySurfaceHeights = (row: TerrainProcessedRow, traceSource: RFTerrainTraceSource): Float32Array => {
  const values = pickTraceValues(row, traceSource);
  const bins = values.length;
  const rawExcess = new Float32Array(bins);
  for (let i = 0; i < bins; i += 1) {
    rawExcess[i] = Math.min(RF_TERRAIN_MAX_EXCESS_DB, Math.max(0, values[i] - row.noiseFloorDb[i]));
  }
  return smoothAcrossFrequency(rawExcess, RF_TERRAIN_DENSITY_SMOOTHING_RADIUS);
};

const computeTerrainRow = (
  row: TerrainProcessedRow,
  mode: RFTerrainMode,
  colormapName: 'turbo' | 'viridis' | 'grayscale',
  colorSource: RFTerrainColorSource,
  traceSource: RFTerrainTraceSource,
) => {
  // Which per-bin quantity feeds the terrain (spec-adjacent "apply Max
  // Hold/Average/etc. to the whole 3D view"): real, already-computed
  // values (engine/traceSource.ts), 'live' by default -- never a second,
  // approximated statistic.
  const traceValues = pickTraceValues(row, traceSource);
  const bins = traceValues.length;
  const heights = new Float32Array(bins);
  const colors = new Float32Array(bins * 3);
  const colormap = colormapFor(colormapName);
  const densitySurface = mode === 'density' ? computeDensitySurfaceHeights(row, traceSource) : null;

  for (let i = 0; i < bins; i += 1) {
    const heightRaw = densitySurface ? densitySurface[i] : toDisplayHeight(traceValues[i], row.noiseFloorDb[i], mode);
    let colorValue: number;
    if (colorSource === 'occupancy') {
      colorValue = row.occupancy[i];
    } else if (colorSource === 'persistence') {
      colorValue = row.persistence[i];
    } else {
      // 'magnitude' (default heat-map): the SAME value driving height also
      // drives color, so equal power/excess always reads as the same
      // color and tall mountains read hot -- never a different-looking
      // color for an equal-height point.
      colorValue = clamp01(heightRaw / RF_TERRAIN_MAX_EXCESS_DB);
    }
    heights[i] = heightRaw * RF_TERRAIN_HEIGHT_VISUAL_SCALE;
    const [r, g, b] = colormap(colorValue);
    colors[i * 3] = r; colors[i * 3 + 1] = g; colors[i * 3 + 2] = b;
  }
  return { heights, colors };
};

// Owns the Three.js renderer instance and the row-level history cache used
// to answer raycaster hits with real measured values (spec §70/§96 -- the
// GPU is never the source of truth). Receives rows imperatively via
// applyRow() rather than through React state/props so a new frame never
// triggers a React re-render of this subtree. Also keeps a bounded,
// extended history (spec-adjacent "rewind" feature, deliberately capped --
// see rfTerrainConstants.ts) independent from the live render window.
export const RFTerrainCanvas = forwardRef<RFTerrainCanvasHandle, RFTerrainCanvasProps>(({ mode, colormapName, colorSource, traceSource, traceScope, objects, overlays, maskThresholdDb, onSelect, onFpsUpdate, onContextLost, onContextRestored }, ref) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<RFTerrainRenderer | null>(null);
  const historyRef = useRef<(TerrainProcessedRow | null)[]>(new Array(RF_TERRAIN_EXTENDED_HISTORY_ROWS).fill(null));
  const viewOffsetRef = useRef(0);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const colormapRef = useRef(colormapName);
  colormapRef.current = colormapName;
  const colorSourceRef = useRef(colorSource);
  colorSourceRef.current = colorSource;
  const traceSourceRef = useRef(traceSource);
  traceSourceRef.current = traceSource;
  const objectsRef = useRef(objects);
  objectsRef.current = objects;
  const overlaysRef = useRef(overlays);
  overlaysRef.current = overlays;
  // Ruler labels (frequency ticks + power/height ticks, spec-adjacent
  // "regla" request): plain DOM nodes updated imperatively at the ~10Hz
  // row rate (not React state, and not per-RAF-frame -- text labels don't
  // need 60fps precision, and this keeps the hot render loop untouched).
  const freqLabelRefs = useRef<(HTMLDivElement | null)[]>([null, null, null]);
  const powerLabelRefs = useRef<(HTMLDivElement | null)[]>([null, null, null]);
  // FSEI selection bookkeeping (spec-adjacent click=select / second
  // click=pin / hover=cyan preview): kept as refs, not React state, since
  // updating them must never trigger a re-render of this canvas subtree --
  // the Inspector's copy of the selection lives in the parent via onSelect.
  const currentSelectionRef = useRef<TerrainInspectorSelection | null>(null);
  const lastClickKeyRef = useRef<string | null>(null);
  const hoverThrottleRef = useRef(0);

  const updateRulerLabels = (row: TerrainProcessedRow) => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    const bins = row.frame.frequencyArray;
    const binCount = bins.length;

    const freqTicks: Array<[number, number]> = [
      [0, bins[0]],
      [Math.floor(binCount / 2), bins[Math.floor(binCount / 2)]],
      [binCount - 1, bins[binCount - 1]],
    ];
    freqTicks.forEach(([binIndex, freqHz], i) => {
      const el = freqLabelRefs.current[i];
      if (!el) return;
      const { xRatio, yRatio, visible } = renderer.projectToScreenRatio(binIndex - binCount / 2, 2, 0);
      el.style.display = visible ? 'block' : 'none';
      el.style.left = `${xRatio * 100}%`;
      el.style.top = `${yRatio * 100}%`;
      el.textContent = `${(freqHz / 1e6).toFixed(3)} MHz`;
    });

    const powerTicks = [0, RF_TERRAIN_MAX_EXCESS_DB / 2, RF_TERRAIN_MAX_EXCESS_DB];
    powerTicks.forEach((dbValue, i) => {
      const el = powerLabelRefs.current[i];
      if (!el) return;
      const { xRatio, yRatio, visible } = renderer.projectToScreenRatio(-binCount / 2 - 3, dbValue * RF_TERRAIN_HEIGHT_VISUAL_SCALE, 0);
      el.style.display = visible ? 'block' : 'none';
      el.style.left = `${xRatio * 100}%`;
      el.style.top = `${yRatio * 100}%`;
      el.textContent = modeRef.current === 'raw' ? `${dbValue.toFixed(0)} dB` : `+${dbValue.toFixed(0)} dB`;
    });
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) {
      return;
    }

    const renderer = new RFTerrainRenderer(canvas, RF_TERRAIN_DEFAULT_HISTORY_ROWS, RF_TERRAIN_DEFAULT_FREQUENCY_BINS, {
      onContextLost,
      onContextRestored,
      onFpsUpdate,
      // A pinned selection survives OUT OF VIEW as a flagged, stale entry
      // (the Inspector shows it honestly rather than silently vanishing);
      // an unpinned one is simply cleared -- it was never meant to persist.
      onSelectionOutOfView: () => {
        const current = currentSelectionRef.current;
        if (!current) return;
        if (current.pinned) {
          const updated = { ...current, outOfView: true };
          currentSelectionRef.current = updated;
          onSelect(updated);
        } else {
          currentSelectionRef.current = null;
          renderer.hideSelectedObjectEnvelope();
          onSelect(null);
        }
      },
    });
    rendererRef.current = renderer;
    renderer.resize(container.clientWidth, container.clientHeight);
    renderer.start();

    const resizeObserver = new ResizeObserver(() => {
      renderer.resize(container.clientWidth, container.clientHeight);
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      renderer.dispose();
      rendererRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reflect overlay toggle changes onto the renderer without waiting for
  // the next row.
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    (Object.keys(RIBBON_FIELDS) as TerrainOverlayId[]).forEach((id) => renderer.setOverlayVisible(id, overlays[id as keyof typeof RIBBON_FIELDS]));
    renderer.setHistoryWireframe(overlays.historyWireframe);
  }, [overlays]);

  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    renderer.setMaskPlane(maskThresholdDb === null ? null : maskThresholdDb * RF_TERRAIN_HEIGHT_VISUAL_SCALE);
  }, [maskThresholdDb]);

  // "Apply to everything visible" (traceScope='entireHistory'): retroactively
  // repaints every currently-cached, currently-visible row from ITS OWN real
  // per-row values under the new mode/trace source -- never fabricates a
  // history that wasn't measured (unlike the removed seedFill duplication
  // trick, every row here is a real, previously-captured TerrainProcessedRow
  // from historyRef). The default scope ('liveEdgeOnly') leaves this a
  // no-op, matching the historical behavior where a mode/trace change only
  // ever affected rows arriving from that point on.
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer || traceScope !== 'entireHistory' || viewOffsetRef.current !== 0) return;

    const rowsWindow: Array<{ heights: Float32Array; colorsFlat: Float32Array }> = [];
    for (let i = 0; i < RF_TERRAIN_DEFAULT_HISTORY_ROWS; i += 1) {
      const row = historyRef.current[i];
      if (!row) {
        rowsWindow.push({ heights: new Float32Array(RF_TERRAIN_DEFAULT_FREQUENCY_BINS), colorsFlat: new Float32Array(RF_TERRAIN_DEFAULT_FREQUENCY_BINS * 3) });
        continue;
      }
      const { heights, colors } = computeTerrainRow(row, mode, colormapName, colorSource, traceSource);
      rowsWindow.push({ heights, colorsFlat: colors });
    }
    renderer.renderStaticWindow(rowsWindow);
    // Not a rewind -- stay live immediately after repainting.
    renderer.setLive(true);
  }, [mode, colormapName, colorSource, traceSource, traceScope]);

  useImperativeHandle(ref, () => ({
    applyRow(row: TerrainProcessedRow) {
      const renderer = rendererRef.current;
      if (!renderer) return;

      historyRef.current.unshift(row);
      if (historyRef.current.length > RF_TERRAIN_EXTENDED_HISTORY_ROWS) {
        historyRef.current.pop();
      }

      // While rewound, live rows keep accumulating into history (so the
      // window is ready the instant the user returns to LIVE) but must not
      // repaint the terrain the user is currently scrubbing through.
      if (viewOffsetRef.current !== 0) {
        return;
      }

      const { heights, colors } = computeTerrainRow(row, modeRef.current, colormapRef.current, colorSourceRef.current, traceSourceRef.current);
      renderer.pushRow(heights, colors);

      const activeOverlays = overlaysRef.current;
      (Object.keys(RIBBON_FIELDS) as Array<keyof typeof RIBBON_FIELDS>).forEach((id) => {
        if (!activeOverlays[id]) return;
        const values = row[RIBBON_FIELDS[id]] as number[];
        renderer.updateOverlay(id, Float32Array.from(values.map((v, i) => toDisplayHeight(v, row.noiseFloorDb[i], modeRef.current) * RF_TERRAIN_HEIGHT_VISUAL_SCALE)));
      });

      if (activeOverlays.frequencyMarker) {
        const bins = row.frame.frequencyArray;
        let nearestIndex = 0;
        let nearestDistance = Infinity;
        for (let i = 0; i < bins.length; i += 1) {
          const distance = Math.abs(bins[i] - row.frame.centerFrequency);
          if (distance < nearestDistance) { nearestDistance = distance; nearestIndex = i; }
        }
        renderer.setFrequencyMarker(nearestIndex - bins.length / 2);
      } else {
        renderer.setFrequencyMarker(null);
      }

      updateRulerLabels(row);
    },
    clear() {
      rendererRef.current?.clear();
      historyRef.current = new Array(RF_TERRAIN_EXTENDED_HISTORY_ROWS).fill(null);
      viewOffsetRef.current = 0;
      currentSelectionRef.current = null;
      lastClickKeyRef.current = null;
      onSelect(null);
    },
    setCameraPreset(preset: RFTerrainCameraPreset) {
      rendererRef.current?.setCameraPreset(preset);
    },
    setViewOffset(offsetRows: number) {
      const renderer = rendererRef.current;
      if (!renderer) return;
      viewOffsetRef.current = offsetRows;
      // A rewind repaints every row slot from scratch (renderStaticWindow),
      // so any marker/envelope placed against the previous row layout is
      // now pointing at the wrong content -- hide it rather than mislead.
      renderer.hideSelectedMarker();
      renderer.hideHoverMarker();
      renderer.hideSelectedObjectEnvelope();

      if (offsetRows === 0) {
        renderer.setLive(true);
        return;
      }

      const rowsWindow: Array<{ heights: Float32Array; colorsFlat: Float32Array }> = [];
      for (let i = 0; i < RF_TERRAIN_DEFAULT_HISTORY_ROWS; i += 1) {
        const row = historyRef.current[offsetRows + i];
        if (!row) {
          rowsWindow.push({ heights: new Float32Array(RF_TERRAIN_DEFAULT_FREQUENCY_BINS), colorsFlat: new Float32Array(RF_TERRAIN_DEFAULT_FREQUENCY_BINS * 3) });
          continue;
        }
        const { heights, colors } = computeTerrainRow(row, modeRef.current, colormapRef.current, colorSourceRef.current, traceSourceRef.current);
        rowsWindow.push({ heights, colorsFlat: colors });
      }
      renderer.renderStaticWindow(rowsWindow);
    },
    exportPng() {
      return canvasRef.current?.toDataURL('image/png') ?? null;
    },
    exportCsv() {
      const latest = historyRef.current[viewOffsetRef.current];
      if (!latest) return null;
      const header = 'frequency_hz,power_db,noise_floor_db,excess_db,persistence,occupancy\n';
      const lines = latest.frame.frequencyArray.map((freq, i) =>
        [freq, latest.frame.powerLevels[i], latest.noiseFloorDb[i], latest.excessDb[i], latest.persistence[i], latest.occupancy[i]].join(','));
      return header + lines.join('\n');
    },
    unpinSelection() {
      const current = currentSelectionRef.current;
      if (!current) return;
      // An out-of-view selection was only being kept around because it was
      // pinned -- unpinning it has nothing left to hold onto, so it clears
      // outright rather than lingering as an unpinned-but-stale entry.
      if (current.outOfView) {
        currentSelectionRef.current = null;
        lastClickKeyRef.current = null;
        rendererRef.current?.hideSelectedMarker();
        rendererRef.current?.hideSelectedObjectEnvelope();
        onSelect(null);
        return;
      }
      const updated = { ...current, pinned: false };
      currentSelectionRef.current = updated;
      onSelect(updated);
    },
  }), [onSelect]);

  // Same local mesh-space convention TerrainMesh itself uses (x = col -
  // cols/2, z = -row) -- never a separately-derived position for the
  // gold/cyan reticles.
  const localMarkerPosition = (row: TerrainProcessedRow, col: number, meshRow: number): [number, number, number] => {
    const heightRaw = toDisplayHeight(row.frame.powerLevels[col], row.noiseFloorDb[col], modeRef.current);
    return [col - RF_TERRAIN_DEFAULT_FREQUENCY_BINS / 2, heightRaw * RF_TERRAIN_HEIGHT_VISUAL_SCALE, -meshRow];
  };

  // Gathers the real, already-cached rows spanning a terrain object's own
  // measured time range, each tagged with its CURRENT mesh-row position --
  // the same historyRef the raycaster/Inspector already treat as the
  // source of truth (spec §9.3), never a second independent data source.
  // Only searches the LIVE render depth (not the extended rewind cache):
  // the envelope is a live-selection feature, consistent with markers
  // being hidden during a rewind (see setViewOffset above).
  const gatherEnvelopeSourceRows = (object: TerrainObject): EnvelopeSourceRow[] => {
    const rows: EnvelopeSourceRow[] = [];
    for (let meshRow = 0; meshRow < RF_TERRAIN_DEFAULT_HISTORY_ROWS; meshRow += 1) {
      const candidate = historyRef.current[viewOffsetRef.current + meshRow];
      if (!candidate) continue;
      const timeSeconds = candidate.frame.timestamp / 1000;
      if (timeSeconds < object.startTimeSeconds || timeSeconds > object.endTimeSeconds) continue;
      rows.push({ meshRow, excessDb: candidate.excessDb, frequencyHz: candidate.frame.frequencyArray });
    }
    return rows;
  };

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const renderer = rendererRef.current;
    if (!canvas || !renderer) return;

    const rect = canvas.getBoundingClientRect();
    const ndcX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    const ndcY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const hit = renderer.pickGridCell(ndcX, ndcY);
    if (!hit) {
      return;
    }
    const row = historyRef.current[viewOffsetRef.current + hit.row];
    if (!row) {
      return;
    }
    const frequencyHz = row.frame.frequencyArray[hit.col];
    const timestamp = row.frame.timestamp;
    const timeSeconds = timestamp / 1000;
    const matchedObject = findObjectAtPoint(objectsRef.current, frequencyHz, timeSeconds);

    // Second click on the SAME target (object id, or the same frequency
    // bin for a plain point) pins it; a click on anything else always
    // starts a fresh, unpinned selection (spec-adjacent click=select /
    // second-click=pin).
    const key = matchedObject ? `obj:${matchedObject.id}` : `col:${hit.col}`;
    const pinned = key === lastClickKeyRef.current ? !(currentSelectionRef.current?.pinned ?? false) : false;
    lastClickKeyRef.current = key;

    const selection: TerrainInspectorSelection = {
      kind: matchedObject ? 'TERRAIN_OBJECT' : 'POINT',
      generation: row.frame.generation,
      frequencyHz,
      timestamp,
      rawPowerDb: row.frame.powerLevels[hit.col],
      noiseFloorDb: row.noiseFloorDb[hit.col],
      excessDb: row.excessDb[hit.col],
      persistence: row.persistence[hit.col],
      occupancy: row.occupancy[hit.col],
      maxHoldDb: row.maxHoldDb[hit.col],
      minHoldDb: row.minHoldDb[hit.col],
      averageDb: row.averageDb[hit.col],
      ewmaDb: row.ewmaDb[hit.col],
      powerUnit: row.frame.powerUnit ?? 'dBFS',
      calibrationId: row.frame.calibrationId,
      objectId: matchedObject?.id ?? null,
      pinned,
      outOfView: false,
    };
    currentSelectionRef.current = selection;
    onSelect(selection);

    const [x, y, z] = localMarkerPosition(row, hit.col, hit.row);
    renderer.setSelectedMarker(x, y, z);

    if (matchedObject) {
      const sourceRows = gatherEnvelopeSourceRows(matchedObject);
      const envelope = buildSpectralObjectEnvelope(
        sourceRows, matchedObject.startFrequencyHz, matchedObject.stopFrequencyHz, RF_TERRAIN_SEGMENTATION_GROW_THRESHOLD_DB,
      );
      if (envelope) {
        renderer.setSelectedObjectEnvelope(envelope, RF_TERRAIN_DEFAULT_FREQUENCY_BINS);
      } else {
        renderer.hideSelectedObjectEnvelope();
      }
    } else {
      renderer.hideSelectedObjectEnvelope();
    }
  };

  const handleMouseMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const now = performance.now();
    if (now - hoverThrottleRef.current < 60) return;
    hoverThrottleRef.current = now;

    const canvas = canvasRef.current;
    const renderer = rendererRef.current;
    if (!canvas || !renderer) return;

    const rect = canvas.getBoundingClientRect();
    const ndcX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    const ndcY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const hit = renderer.pickGridCell(ndcX, ndcY);
    if (!hit) {
      renderer.hideHoverMarker();
      return;
    }
    const row = historyRef.current[viewOffsetRef.current + hit.row];
    if (!row) {
      renderer.hideHoverMarker();
      return;
    }
    const [x, y, z] = localMarkerPosition(row, hit.col, hit.row);
    renderer.setHoverMarker(x, y, z);
  };

  const handleMouseLeave = () => {
    rendererRef.current?.hideHoverMarker();
  };

  const rulerLabelClass = 'pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-sm px-1.5 py-0.5 text-[10px] font-mono tabular-nums text-cyan-50 backdrop-blur-sm';
  const rulerLabelStyle: React.CSSProperties = { border: `1px solid ${HUD_BORDER_COLOR}`, background: HUD_PANEL_BACKGROUND };

  return (
    <div ref={containerRef} className="relative h-full w-full min-h-0">
      <canvas ref={canvasRef} className="h-full w-full" onClick={handleClick} onMouseMove={handleMouseMove} onMouseLeave={handleMouseLeave} />
      {/* Frequency ruler (start/center/stop of the visible span) */}
      {[0, 1, 2].map((i) => (
        <div key={`freq-${i}`} ref={(el) => { freqLabelRefs.current[i] = el; }} className={rulerLabelClass} style={{ ...rulerLabelStyle, display: 'none', borderBottom: '2px solid #67e8f9' }} />
      ))}
      {/* Power/height ruler (0 / mid / max of the current display range) */}
      {[0, 1, 2].map((i) => (
        <div key={`power-${i}`} ref={(el) => { powerLabelRefs.current[i] = el; }} className={rulerLabelClass} style={{ ...rulerLabelStyle, display: 'none', borderBottom: '2px solid #fbbf24' }} />
      ))}
    </div>
  );
});
RFTerrainCanvas.displayName = 'RFTerrainCanvas';
