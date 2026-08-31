import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { SpectrumToolKind } from '../model/spectrumToolTypes';
import type { SpectrumToolConfig } from '../model/spectrumToolTypes';
import type { SpectrumToolsState } from '../useSpectrumTools';

const labels: Record<SpectrumToolKind, string> = {
  max_hold: 'Max Hold',
  min_hold: 'Min Hold',
  power_average: 'Power Average',
  rms_power: 'RMS Power over FFT frames', ewma: 'EWMA', percentiles: 'Percentiles P50/P90/P95/P99', trace_history: 'Trace History', density: 'Density / Persistence', spectrum_mask: 'Spectrum Mask', gated_spectrum: 'Gated Spectrum', zero_span: 'Zero Span', occupancy: 'Observed-frame Occupancy',
};

const colors: Record<SpectrumToolKind, string> = {
  max_hold: '#fbbf24',
  min_hold: '#22d3ee',
  power_average: '#34d399',
  rms_power: '#a78bfa', ewma: '#fb923c', percentiles: '#e879f9', trace_history: '#60a5fa', density: '#38bdf8', spectrum_mask: '#ef4444', gated_spectrum: '#2dd4bf', zero_span: '#facc15', occupancy: '#10b981',
};

interface ToolHelp {
  shows: string;
  useful: string;
  limitation: string;
  output: string;
  requires: string;
  impact: string;
  parameter?: string;
}

const help: Record<SpectrumToolKind, ToolHelp> = {
  max_hold: { shows: 'The highest level observed at each frequency.', useful: 'Short bursts, frequency hopping, spurious emissions, and intermittent signals.', limitation: 'It does not preserve when the maximum occurred or how long it lasted.', output: 'Power-versus-frequency trace.', requires: 'Live FFT/PSD frames.', impact: 'Visual only; it does not automatically change the analysis source.' },
  min_hold: { shows: 'The lowest level observed at each frequency.', useful: 'Estimating the noise floor and identifying continuously occupied channels.', limitation: 'A low outlier can remain until the tool is reset.', output: 'Dashed power-versus-frequency trace.', requires: 'Live FFT/PSD frames.', impact: 'Visual and cumulative only.' },
  power_average: { shows: 'Average power at each frequency, calculated in the linear-power domain.', useful: 'Stabilizing noise and observing persistent signals.', limitation: 'It can smooth or hide very short events.', output: 'Average power-versus-frequency trace.', requires: 'Multiple FFT/PSD frames.', impact: 'Adds a small amount of processing per frame.' },
  rms_power: { shows: 'Accumulated RMS power at each frequency.', useful: 'Measuring the effective energy of varying signals.', limitation: 'With PSD-only input it may look similar to Power Average.', output: 'RMS power-versus-frequency trace.', requires: 'PSD; exact time-domain RMS requires IQ samples.', impact: 'Cumulative visual processing.' },
  ewma: { shows: 'An exponential average that gives more weight to recent frames.', useful: 'Smoothing the trace while retaining a response to changes.', limitation: 'A large time constant can hide fast events.', output: 'Smoothed power-versus-frequency trace.', requires: 'Frames with timestamps.', impact: 'Adapts to the real interval between frames.', parameter: 'Time constant in seconds: increasing it produces a steadier trace with a slower response; decreasing it follows fast changes more closely but shows more noise. A practical starting value is 1 second.' },
  percentiles: { shows: 'P50, P90, P95, and P99 for each bin over a bounded window.', useful: 'Separating typical behavior from infrequent peaks.', limitation: 'It must accumulate samples and uses more memory and processing.', output: 'Four power-versus-frequency traces.', requires: 'Several compatible frames.', impact: 'The window is limited to 600 frames.' },
  trace_history: { shows: 'Previous traces with gradually decreasing opacity.', useful: 'Viewing movement, drift, and intermittent activity.', limitation: 'Many traces can make the graph visually dense.', output: 'A family of historical traces.', requires: 'Consecutive FFT/PSD frames.', impact: 'The buffer is bounded and never grows indefinitely.' },
  density: { shows: 'How frequently each power level appears in each frequency bin.', useful: 'Identifying persistence, noise, and multiple signal states.', limitation: 'This is observed-frame density, not a regulatory measurement.', output: 'Two-dimensional color layer.', requires: 'Many frames before it becomes stable.', impact: 'Higher rendering cost than a simple line.' },
  spectrum_mask: { shows: 'An upper power limit across the spectrum.', useful: 'Visually identifying emissions that exceed an allowed level.', limitation: 'At this stage it is a visual mask and does not trigger an IQ capture.', output: 'Dashed mask line.', requires: 'A configured limit in dB.', impact: 'It does not modify the spectrum or legacy detection.', parameter: 'Mask level in dB: increasing it causes fewer crossings and only strong signals will exceed it; decreasing it increases sensitivity but also raises the chance of noise-related false alarms.' },
  gated_spectrum: { shows: 'A spectrum calculated inside a specific time gate.', useful: 'Analyzing a selected part of a burst or pulse.', limitation: 'It cannot be calculated honestly from PSD frames or waterfall images.', output: 'An additional spectrum trace when synchronized IQ is available.', requires: 'Real IQ samples with accurate timing.', impact: 'Currently unavailable because the Live stream provides PSD only.' },
  zero_span: { shows: 'Power versus time at a selected frequency.', useful: 'Pulses, temporal modulation, duty cycle, and rise-time analysis.', limitation: 'It is not a power-versus-frequency trace or a slow history of one FFT bin.', output: 'A separate time-domain panel.', requires: 'Continuous IQ, a selected frequency, and real time resolution.', impact: 'Currently unavailable because the Live stream does not provide timed IQ.' },
  occupancy: { shows: 'The percentage of observed time that each bin exceeds a threshold.', useful: 'Comparing which parts of the span are most active during the session.', limitation: 'It represents received frames only and is not absolute or regulatory occupancy.', output: 'Color strip below the spectrum.', requires: 'A threshold and timestamped frames.', impact: 'Time accumulation is bounded to the current session.', parameter: 'Threshold in dB: increasing it counts only stronger signals and reduces reported occupancy; decreasing it includes weaker signals and noise, increasing apparent occupancy. Set it a few dB above the noise floor.' },
};

interface Props {
  tools: SpectrumToolsState;
  paused: boolean;
  onActiveChange: (kind: SpectrumToolKind, active: boolean) => void;
  onVisibleChange: (kind: SpectrumToolKind, visible: boolean) => void;
  onReset: (kind: SpectrumToolKind) => void;
  onConfigChange: (kind: SpectrumToolKind, config: SpectrumToolConfig) => void;
  onResetAll: () => void;
  onDisableAll: () => void;
  liveTraceVisible: boolean;
  onLiveTraceVisibleChange: (visible: boolean) => void;
}

export const SpectrumToolsPanel: React.FC<Props> = ({ tools, paused, onActiveChange, onVisibleChange, onReset, onConfigChange, onResetAll, onDisableAll, liveTraceVisible, onLiveTraceVisibleChange }) => {
  const [open, setOpen] = useState(false);
  const [tooltip, setTooltip] = useState<{ kind: SpectrumToolKind; left: number; top: number } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const tooltipTimerRef = useRef<number | null>(null);
  const kinds = Object.keys(tools) as SpectrumToolKind[];
  const activeKinds = kinds.filter((kind) => tools[kind].active);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, []);

  const hideTooltip = () => {
    if (tooltipTimerRef.current !== null) window.clearTimeout(tooltipTimerRef.current);
    tooltipTimerRef.current = null;
    setTooltip(null);
  };

  const scheduleTooltip = (kind: SpectrumToolKind, element: HTMLElement) => {
    hideTooltip();
    const rect = element.getBoundingClientRect();
    tooltipTimerRef.current = window.setTimeout(() => {
      const width = 320;
      setTooltip({
        kind,
        left: Math.max(8, rect.left - width - 12),
        top: Math.max(8, Math.min(window.innerHeight - 390, rect.top)),
      });
    }, 350);
  };

  useEffect(() => () => {
    if (tooltipTimerRef.current !== null) window.clearTimeout(tooltipTimerRef.current);
  }, []);

  return (
    <div ref={rootRef} className="absolute left-auto right-2 top-2 z-20 pointer-events-auto" onClick={(event) => event.stopPropagation()} onMouseDown={(event) => event.stopPropagation()}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="rounded-md border border-slate-600 bg-slate-950/90 px-3 py-2 text-xs font-semibold text-slate-100 shadow-lg backdrop-blur">
        Spectrum Tools{activeKinds.length ? ` · ${activeKinds.length}` : ''} ▾
      </button>
      {open && (
        <div className="mt-2 max-h-[70vh] w-72 overflow-y-auto rounded-lg border border-slate-700 bg-slate-950/95 p-3 shadow-2xl backdrop-blur">
          <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-400">Traces</div>
          <label className="mb-1 flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-slate-800" title="Show or hide only the original Live trace. Acquisition, analysis, markers, waterfall, and Spectrum Tools continue running unchanged.">
            <span className="h-2.5 w-2.5 rounded-full bg-blue-500" />
            <span className="flex-1 text-sm text-slate-100">Live Trace</span>
            <input type="checkbox" checked={liveTraceVisible} onChange={(event) => onLiveTraceVisibleChange(event.target.checked)} />
          </label>
          {kinds.map((kind) => (
            <div
              key={kind}
              className="rounded-md px-2 py-2 hover:bg-slate-800 focus-within:bg-slate-800"
              onMouseEnter={(event) => scheduleTooltip(kind, event.currentTarget)}
              onMouseLeave={hideTooltip}
              onFocusCapture={(event) => scheduleTooltip(kind, event.currentTarget)}
              onBlurCapture={hideTooltip}
            >
              <label className="flex cursor-pointer items-center gap-3">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors[kind] }} />
                <span className="flex-1 text-sm text-slate-100">{labels[kind]}</span>
                <input type="checkbox" checked={tools[kind].active} onChange={(event) => onActiveChange(kind, event.target.checked)} />
              </label>
              {tools[kind].message && <div className="mt-1 text-[10px] text-amber-300">{tools[kind].message}</div>}
              {tools[kind].active && kind === 'ewma' && <input aria-label="EWMA time constant seconds" type="number" min="0.05" max="60" step="0.05" value={tools[kind].config.ewmaTauSeconds} onChange={(e) => onConfigChange(kind, { ewmaTauSeconds: Number(e.target.value) })} className="mt-1 w-full rounded bg-slate-900 px-2 py-1 text-xs" />}
              {tools[kind].active && kind === 'occupancy' && <input aria-label="Occupancy threshold dB" type="number" min="-160" max="20" value={tools[kind].config.thresholdDb} onChange={(e) => onConfigChange(kind, { thresholdDb: Number(e.target.value) })} className="mt-1 w-full rounded bg-slate-900 px-2 py-1 text-xs" />}
              {tools[kind].active && kind === 'spectrum_mask' && <input aria-label="Mask upper level dB" type="number" min="-160" max="20" value={tools[kind].config.maskUpperDb} onChange={(e) => onConfigChange(kind, { maskUpperDb: Number(e.target.value) })} className="mt-1 w-full rounded bg-slate-900 px-2 py-1 text-xs" />}
            </div>
          ))}
          <button type="button" onClick={onResetAll} className="mt-3 w-full rounded-md bg-slate-800 px-2 py-2 text-xs text-slate-200 hover:bg-slate-700">Reset all histories</button>
          <button type="button" onClick={onDisableAll} className="mt-2 w-full rounded-md bg-slate-800 px-2 py-2 text-xs text-slate-200 hover:bg-slate-700">Disable all tools</button>
        </div>
      )}
      {(activeKinds.length > 0 || !liveTraceVisible) && (
        <div className="mt-2 flex max-w-[760px] flex-wrap gap-1.5 pointer-events-auto">
          <div className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-950/80 px-2 py-1 text-[11px] text-slate-100 shadow backdrop-blur">
            <span className="inline-block w-5 border-t-2 border-blue-500" />
            <span>Live Trace · {liveTraceVisible ? 'visible' : 'hidden'}</span>
            <button type="button" aria-label={`${liveTraceVisible ? 'Hide' : 'Show'} Live Trace`} onClick={() => onLiveTraceVisibleChange(!liveTraceVisible)} className="rounded px-1 hover:bg-slate-700">{liveTraceVisible ? '◉' : '○'}</button>
          </div>
          {activeKinds.map((kind) => (
            <div key={kind} className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-950/80 px-2 py-1 text-[11px] text-slate-100 shadow backdrop-blur">
              <span className="inline-block w-5 border-t-2" style={{ borderColor: colors[kind], borderStyle: kind === 'max_hold' ? 'solid' : 'dashed' }} />
              <span>{labels[kind]} · {paused ? 'paused' : tools[kind].status}{tools[kind].sampleCount ? ` ${tools[kind].sampleCount}` : ''}</span>
              <button type="button" aria-label={`${tools[kind].visible ? 'Hide' : 'Show'} ${labels[kind]}`} onClick={() => onVisibleChange(kind, !tools[kind].visible)} className="rounded px-1 hover:bg-slate-700">{tools[kind].visible ? '◉' : '○'}</button>
              <button type="button" aria-label={`Reset ${labels[kind]}`} onClick={() => onReset(kind)} className="rounded px-1 hover:bg-slate-700">↻</button>
              <button type="button" aria-label={`Disable ${labels[kind]}`} onClick={() => onActiveChange(kind, false)} className="rounded px-1 hover:bg-slate-700">×</button>
            </div>
          ))}
        </div>
      )}
      {tooltip && createPortal(
        <div
          role="tooltip"
          className="pointer-events-none fixed z-[100] w-80 rounded-xl border border-slate-500/40 bg-slate-950/75 p-4 text-left text-xs text-slate-100 shadow-2xl backdrop-blur-sm"
          style={{ left: tooltip.left, top: tooltip.top }}
        >
          <div className="mb-3 text-sm font-bold uppercase tracking-wide" style={{ color: colors[tooltip.kind] }}>{labels[tooltip.kind]}</div>
          <div className="space-y-2 leading-relaxed">
            <div><span className="font-semibold text-slate-300">Shows: </span>{help[tooltip.kind].shows}</div>
            <div><span className="font-semibold text-slate-300">Useful for: </span>{help[tooltip.kind].useful}</div>
            <div><span className="font-semibold text-slate-300">Limitation: </span>{help[tooltip.kind].limitation}</div>
            <div><span className="font-semibold text-slate-300">Output: </span>{help[tooltip.kind].output}</div>
            <div><span className="font-semibold text-slate-300">Requires: </span>{help[tooltip.kind].requires}</div>
            <div><span className="font-semibold text-slate-300">Impact: </span>{help[tooltip.kind].impact}</div>
            {help[tooltip.kind].parameter && <div className="mt-3 rounded-lg border border-cyan-300/20 bg-cyan-950/25 p-2 text-cyan-50"><span className="font-semibold">How to adjust the value: </span>{help[tooltip.kind].parameter}</div>}
            {tools[tooltip.kind].message && <div className="mt-3 rounded-lg border border-amber-300/25 bg-amber-950/25 p-2 text-amber-100">{tools[tooltip.kind].message}</div>}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};
