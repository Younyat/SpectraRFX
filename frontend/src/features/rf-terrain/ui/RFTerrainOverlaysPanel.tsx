import React from 'react';
import { Layers } from 'lucide-react';
import type { RFTerrainMode } from '../model/rfTerrainTypes';
import type { TerrainColormap } from '../render/TerrainColors';
import type { RFTerrainColorSource, RFTerrainOverlayToggles, RFTerrainTraceSource, RFTerrainTraceScope } from './RFTerrainCanvas';
import { HudFrame } from './hud/HudFrame';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND, hudLabelClass } from './hud/hudTheme';

interface RFTerrainOverlaysPanelProps {
  open: boolean;
  onToggleOpen: () => void;
  mode: RFTerrainMode;
  onModeChange: (mode: RFTerrainMode) => void;
  colormapName: TerrainColormap;
  onColormapChange: (colormap: TerrainColormap) => void;
  colorSource: RFTerrainColorSource;
  onColorSourceChange: (source: RFTerrainColorSource) => void;
  traceSource: RFTerrainTraceSource;
  onTraceSourceChange: (source: RFTerrainTraceSource) => void;
  traceScope: RFTerrainTraceScope;
  onTraceScopeChange: (scope: RFTerrainTraceScope) => void;
  overlays: RFTerrainOverlayToggles;
  onOverlaysChange: (overlays: RFTerrainOverlayToggles) => void;
  objectsEnabled: boolean;
  onObjectsEnabledChange: (enabled: boolean) => void;
  maskThresholdDb: number | null;
  onMaskThresholdChange: (value: number | null) => void;
}

const TRACE_SOURCE_LABEL: Record<RFTerrainTraceSource, string> = {
  live: 'LIVE',
  maxHold: 'MAX HOLD',
  minHold: 'MIN HOLD',
  average: 'AVERAGE / RMS',
  ewma: 'EWMA',
  p50: 'P50',
  p90: 'P90',
  p95: 'P95',
  p99: 'P99',
};

const HEIGHT_LABEL: Record<RFTerrainMode, string> = {
  raw: 'height = raw power',
  adaptive: 'height = excess over noise floor',
  occupancy: 'height = excess over noise floor',
  density: 'height = excess over noise floor, smoothed across frequency (continuous surface, not a calibrated PSD)',
};

const COLOR_LABEL: Record<RFTerrainColorSource, string> = {
  magnitude: 'color = same magnitude as height (heat map)',
  persistence: 'color = persistence',
  occupancy: 'color = occupancy',
};

const Toggle: React.FC<{ label: string; checked: boolean; onChange: (checked: boolean) => void; swatch?: string }> = ({ label, checked, onChange, swatch }) => (
  <label className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-xs hover:bg-white/5">
    <span className="flex items-center gap-2">
      {swatch && <span className="h-2 w-2 rounded-full" style={{ background: swatch }} />}
      {label}
    </span>
    <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
  </label>
);

const Unavailable: React.FC<{ label: string; reason: string }> = ({ label, reason }) => (
  <div className="rounded-md px-2 py-1 text-xs opacity-50">
    <div className="flex items-center justify-between">
      <span>{label}</span>
      <input type="checkbox" disabled />
    </div>
    <p className="mt-0.5 text-[10px] italic">{reason}</p>
  </div>
);

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className={`mb-1 mt-3 first:mt-0 ${hudLabelClass}`} style={{ color: HUD_ACCENT_BRIGHT }}>{children}</div>
);

// Floating, transparent, collapsible "what is being shown" panel, adapted
// from Live Monitor's Spectrum Tools tray (Live Trace / Max Hold / Min
// Hold / Power Average / RMS / EWMA / Percentiles / Trace History /
// Density-Persistence / Spectrum Mask / Gated Spectrum / Zero Span /
// Observed-frame Occupancy) into 3D-native equivalents -- never a literal
// re-paint of the 2D panel. Every entry here either does something real or
// says explicitly why it doesn't yet.
export const RFTerrainOverlaysPanel: React.FC<RFTerrainOverlaysPanelProps> = ({
  open, onToggleOpen, mode, onModeChange, colormapName, onColormapChange,
  colorSource, onColorSourceChange,
  traceSource, onTraceSourceChange, traceScope, onTraceScopeChange,
  overlays, onOverlaysChange, objectsEnabled, onObjectsEnabledChange,
  maskThresholdDb, onMaskThresholdChange,
}) => (
  // top-14, not top-3: sits directly below the always-visible Menu button
  // (top-3) instead of overlapping it once Menu reveals this trigger.
  <div className="pointer-events-none absolute left-3 top-14 z-20 flex flex-col items-start gap-2">
    <button
      onClick={onToggleOpen}
      className="pointer-events-auto flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
      style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
    >
      <Layers className="h-3.5 w-3.5" />
      Layers
    </button>

    {open && (
      <HudFrame className="pointer-events-auto max-h-[80vh] w-72 overflow-y-auto rounded-sm p-3 text-slate-100 shadow-2xl">
        <div className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Now showing</div>
        <div className="mb-2 mt-1 rounded-sm border p-2 text-[11px]" style={{ borderColor: HUD_BORDER_COLOR }}>
          {mode.toUpperCase()} -- {HEIGHT_LABEL[mode]}, {COLOR_LABEL[colorSource]}
        </div>

        <SectionTitle>Mode</SectionTitle>
        <div className="mb-2 flex flex-wrap gap-1">
          {(['raw', 'adaptive', 'occupancy', 'density'] as const).map((value) => (
            <button
              key={value}
              onClick={() => onModeChange(value)}
              className={`rounded-sm border px-2 py-1 text-[11px] ${mode === value ? 'text-slate-950' : 'text-cyan-100/80'}`}
              style={{ borderColor: HUD_BORDER_COLOR, background: mode === value ? HUD_ACCENT_BRIGHT : 'transparent' }}
            >
              {value.toUpperCase()}
            </button>
          ))}
        </div>
        {mode === 'density' && (
          <p className="mb-2 px-2 text-[10px] leading-snug app-muted-text">
            DENSITY smooths the terrain surface across frequency so it reads as one continuous curve instead of independent per-bin spikes -- a visual reconstruction, not a calibrated power spectral density. The inspector and reference ribbons keep showing the real, unsmoothed value.
          </p>
        )}

        <SectionTitle>Colormap</SectionTitle>
        <select
          value={colormapName}
          onChange={(event) => onColormapChange(event.target.value as TerrainColormap)}
          className="w-full rounded-md border bg-transparent px-2 py-1 text-xs"
          style={{ borderColor: 'var(--app-border)' }}
        >
          <option value="turbo">Turbo</option>
          <option value="viridis">Viridis</option>
          <option value="grayscale">Grayscale</option>
        </select>

        <SectionTitle>What color encodes</SectionTitle>
        <select
          value={colorSource}
          onChange={(event) => onColorSourceChange(event.target.value as typeof colorSource)}
          className="w-full rounded-md border bg-transparent px-2 py-1 text-xs"
          style={{ borderColor: 'var(--app-border)' }}
        >
          <option value="magnitude">Power/Height (heat map -- same value, same color)</option>
          <option value="persistence">Persistence (independent of height)</option>
          <option value="occupancy">Occupancy (independent of height)</option>
        </select>

        <SectionTitle>Terrain trace source</SectionTitle>
        <p className="mb-1 px-2 text-[10px] leading-snug app-muted-text">
          What the WHOLE terrain surface itself shows -- not a thin reference line, the mountain itself. Every option here is a real, already-computed per-bin value (the same ones behind the ribbons below), never a new statistic.
        </p>
        <div className="mb-2 flex flex-wrap gap-1 px-2">
          {(['live', 'maxHold', 'minHold', 'average', 'ewma', 'p50', 'p90', 'p95', 'p99'] as const).map((value) => (
            <button
              key={value}
              onClick={() => onTraceSourceChange(value)}
              className={`rounded-sm border px-2 py-1 text-[10px] ${traceSource === value ? 'text-slate-950' : 'text-cyan-100/80'}`}
              style={{ borderColor: HUD_BORDER_COLOR, background: traceSource === value ? HUD_ACCENT_BRIGHT : 'transparent' }}
            >
              {TRACE_SOURCE_LABEL[value]}
            </button>
          ))}
        </div>
        <div className="mb-1 flex gap-1 px-2">
          {([
            ['liveEdgeOnly', 'Live edge only'],
            ['entireHistory', 'Entire history'],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              onClick={() => onTraceScopeChange(value)}
              className={`flex-1 rounded-sm border px-2 py-1 text-[10px] ${traceScope === value ? 'text-slate-950' : 'text-cyan-100/80'}`}
              style={{ borderColor: HUD_BORDER_COLOR, background: traceScope === value ? HUD_ACCENT_BRIGHT : 'transparent' }}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="mb-2 px-2 text-[10px] leading-snug app-muted-text">
          {traceScope === 'liveEdgeOnly'
            ? 'Only rows arriving from now on use the selected source -- rows already on screen keep whatever they were captured with (today\'s default behavior).'
            : 'Every row currently visible is repainted from its own real cached value under the selected source -- never a fabricated history, only what was actually measured for that row.'}
        </p>
        <Toggle
          label="Power Density (smoothed surface, see DENSITY mode)"
          checked={mode === 'density'}
          onChange={(checked) => onModeChange(checked ? 'density' : 'adaptive')}
        />

        <SectionTitle>Reference ribbons (Live Monitor -&gt; 3D)</SectionTitle>
        <p className="mb-1 px-2 text-[10px] leading-snug app-muted-text">
          Thin front-edge lines drawn ON TOP of the terrain -- independent of the trace source above, and always following the live edge.
        </p>
        <div className="rounded-md px-2 py-1 text-xs opacity-70">Live Trace -- the terrain itself, always on</div>
        <Toggle label="Max Hold" checked={overlays.maxHold} swatch="#38bdf8" onChange={(checked) => onOverlaysChange({ ...overlays, maxHold: checked })} />
        <Toggle label="Min Hold" checked={overlays.minHold} swatch="#4ade80" onChange={(checked) => onOverlaysChange({ ...overlays, minHold: checked })} />
        <Toggle label="Power Average / RMS" checked={overlays.average} swatch="#fbbf24" onChange={(checked) => onOverlaysChange({ ...overlays, average: checked })} />
        <Toggle label="EWMA" checked={overlays.ewma} swatch="#f472b6" onChange={(checked) => onOverlaysChange({ ...overlays, ewma: checked })} />
        <Toggle label="P50" checked={overlays.p50} swatch="#a3a3a3" onChange={(checked) => onOverlaysChange({ ...overlays, p50: checked })} />
        <Toggle label="P90" checked={overlays.p90} swatch="#fb923c" onChange={(checked) => onOverlaysChange({ ...overlays, p90: checked })} />
        <Toggle label="P95" checked={overlays.p95} swatch="#ef4444" onChange={(checked) => onOverlaysChange({ ...overlays, p95: checked })} />
        <Toggle label="P99" checked={overlays.p99} swatch="#7f1d1d" onChange={(checked) => onOverlaysChange({ ...overlays, p99: checked })} />

        <SectionTitle>History and density</SectionTitle>
        <Toggle label="Trace History (historical mesh)" checked={overlays.historyWireframe} onChange={(checked) => onOverlaysChange({ ...overlays, historyWireframe: checked })} />
        <div className="rounded-md px-2 py-1 text-xs opacity-70">Persistence Density -- drives color in ADAPTIVE mode</div>
        <div className="rounded-md px-2 py-1 text-xs opacity-70">Observed-frame Occupancy -- drives color in OCCUPANCY mode (real Δt, not frame count)</div>

        <SectionTitle>References</SectionTitle>
        <Toggle label="Frequency marker" checked={overlays.frequencyMarker} onChange={(checked) => onOverlaysChange({ ...overlays, frequencyMarker: checked })} />
        <Toggle label="Terrain objects" checked={objectsEnabled} onChange={onObjectsEnabledChange} />

        <SectionTitle>Spectrum Mask</SectionTitle>
        <div className="flex items-center gap-2 px-2">
          <input type="checkbox" checked={maskThresholdDb !== null} onChange={(event) => onMaskThresholdChange(event.target.checked ? 20 : null)} />
          <input
            type="number"
            disabled={maskThresholdDb === null}
            value={maskThresholdDb ?? 20}
            onChange={(event) => onMaskThresholdChange(Number(event.target.value))}
            className="w-full rounded-md border bg-transparent px-2 py-1 text-xs disabled:opacity-40"
            style={{ borderColor: 'var(--app-border)' }}
          />
          <span className="text-[10px] app-muted-text">dB</span>
        </div>
        <p className="px-2 text-[10px] app-muted-text">Threshold in the active mode's own height units (raw in RAW, excess in ADAPTIVE/OCCUPANCY).</p>

        <SectionTitle>Not available yet</SectionTitle>
        <Unavailable label="Gated Spectrum" reason="No gated-acquisition mode exists in the current backend -- nothing real to switch on." />
        <Unavailable label="Zero Span" reason="Requesting span=0 from the device would break RF Terrain's own frame validator (requires span &gt; 0); needs a dedicated data path." />

        <p className="mt-3 px-2 text-[10px] leading-snug app-muted-text">
          RMS matches Power Average (same linear-domain formula; with no I/Q there is no distinct RMS to compute).
        </p>
      </HudFrame>
    )}
  </div>
);
