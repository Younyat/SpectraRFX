import React, { useState } from 'react';
import { Radio } from 'lucide-react';
import { useSpectrumController } from '../../../presentation/controllers/SpectrumController';
import { useAnalyzerSettings, useDeviceStatus } from '../../../app/store/AppStore';
import { HudFrame } from './hud/HudFrame';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND, hudLabelClass } from './hud/hudTheme';

const hzToMHz = (hz: number) => hz / 1e6;
const mhzToHz = (mhz: number) => mhz * 1e6;
const hzToKHz = (hz: number) => hz / 1e3;
const khzToHz = (khz: number) => khz * 1e3;

const Field: React.FC<{ label: string; value: number; onChange: (value: number) => void; step?: number }> = ({ label, value, onChange, step }) => (
  <label className="flex flex-col gap-0.5 text-[10px] app-muted-text">
    {label}
    <input
      type="number"
      step={step ?? 'any'}
      value={Number.isFinite(value) ? value : ''}
      onChange={(event) => onChange(Number(event.target.value))}
      className="w-full rounded-md border bg-transparent px-2 py-1 text-xs text-slate-100"
      style={{ borderColor: 'var(--app-border)' }}
    />
  </label>
);

const ApplyButton: React.FC<{ onClick: () => void; busy: boolean; children: React.ReactNode }> = ({ onClick, busy, children }) => (
  <button
    onClick={onClick}
    disabled={busy}
    className="rounded-md border px-2 py-1 text-[11px] font-medium disabled:opacity-40"
    style={{ borderColor: 'var(--app-border)' }}
  >
    {children}
  </button>
);

interface RFTerrainReceiverControlsProps {
  open: boolean;
  onToggleOpen: () => void;
  onExportPng: () => void;
  onExportCsv: () => void;
}

// Real receiver/analyzer controls (spec §61): reuses useSpectrumController
// (the same controller Live Monitor's SpectrumView already wires its own
// buttons to) and the existing ApiService contracts underneath it -- no
// new backend endpoints, no re-implemented connect/tune logic. Changing
// center/span/RBW/etc. here updates the same shared analyzerSettings/
// deviceStatus AppStore fields Live Monitor reads, so both views agree on
// what the one physical B200 is actually doing.
//
// Deliberately NOT ported from Live Monitor's panel: WFM Receiver open/
// close (a demodulation feature, not a terrain concern), BLE-RFFI Studio
// experiment profile presets (Best/E1/E3/E5/E6 -- belong to that module),
// Band-Pass/Peak-marker/overlay toggles that are specific to the 2D canvas
// (RF Terrain already has its own Objects/Overlays equivalents), and the
// noise-floor DISPLAY offset (spec §67 -- wiring it through the whole ARST
// pipeline without silently contaminating persistence/objects/TVI needs
// its own careful pass, not a rushed one here).
export const RFTerrainReceiverControls: React.FC<RFTerrainReceiverControlsProps> = ({ open, onToggleOpen, onExportPng, onExportCsv }) => {
  const settings = useAnalyzerSettings();
  const deviceStatus = useDeviceStatus();
  const controller = useSpectrumController();

  const [centerMHz, setCenterMHz] = useState(() => hzToMHz(settings.centerFrequency));
  const [spanMHz, setSpanMHz] = useState(() => hzToMHz(settings.span));
  const [sampleRateMHz, setSampleRateMHz] = useState(() => hzToMHz(settings.sampleRate));
  const [startMHz, setStartMHz] = useState(() => hzToMHz(settings.centerFrequency - settings.span / 2));
  const [stopMHz, setStopMHz] = useState(() => hzToMHz(settings.centerFrequency + settings.span / 2));
  const [rbwKHz, setRbwKHz] = useState(() => hzToKHz(settings.rbw));
  const [vbwKHz, setVbwKHz] = useState(() => hzToKHz(settings.vbw));
  const [refDb, setRefDb] = useState(settings.referenceLevel);
  const [gainDb, setGainDb] = useState(deviceStatus.gain);
  const [averaging, setAveragingLocal] = useState(settings.averaging);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed: ${label}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    // Panel unfurls to the LEFT of its own trigger button (flex-row,
    // button last) rather than downward, so it never collides with the
    // Inspector's right-edge column when both are open. Sits at top-14
    // (not top-3) so its trigger doesn't overlap the always-visible
    // Fullscreen button directly above it.
    <div className="pointer-events-none absolute right-3 top-14 z-20 flex items-start gap-2">
      {open && (
        <HudFrame className="pointer-events-auto w-80 space-y-3 rounded-sm p-3 text-slate-100 shadow-2xl">
          <div className="flex flex-wrap gap-2">
            <ApplyButton busy={busy !== null} onClick={() => run('connect', controller.connectDevice)}>Connect</ApplyButton>
            <ApplyButton busy={busy !== null} onClick={() => run('disconnect', controller.disconnectDevice)}>Disconnect</ApplyButton>
            <ApplyButton busy={busy !== null} onClick={() => run('start', controller.startDeviceStream)}>Start</ApplyButton>
            <ApplyButton busy={busy !== null} onClick={() => run('stop', controller.stopDeviceStream)}>Stop</ApplyButton>
            <ApplyButton busy={busy !== null} onClick={() => run('refresh', controller.refreshSpectrum)}>Refresh</ApplyButton>
          </div>

          <div>
            <div className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Frequency</div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Center MHz" value={centerMHz} onChange={setCenterMHz} />
              <ApplyButton busy={busy !== null} onClick={() => run('center', () => controller.setCenterFrequency(mhzToHz(centerMHz)))}>Apply</ApplyButton>
              <Field label="Span MHz" value={spanMHz} onChange={setSpanMHz} />
              <ApplyButton busy={busy !== null} onClick={() => run('span', () => controller.setSpan(mhzToHz(spanMHz)))}>Apply</ApplyButton>
              <Field label="Start MHz" value={startMHz} onChange={setStartMHz} />
              <Field label="Stop MHz" value={stopMHz} onChange={setStopMHz} />
            </div>
            <ApplyButton busy={busy !== null} onClick={() => run('edges', () => controller.setStartStop(mhzToHz(startMHz), mhzToHz(stopMHz)))}>Set Edges</ApplyButton>
            <p className="mt-1 text-[10px] app-muted-text">Pan (Left / Step MHz / Right) lives in its own floating window -- the "Pan" button.</p>
          </div>

          <div>
            <div className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Sampling and filters</div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Sample Rate MHz" value={sampleRateMHz} onChange={setSampleRateMHz} />
              <ApplyButton busy={busy !== null} onClick={() => run('sample-rate', () => controller.setSampleRate(mhzToHz(sampleRateMHz)))}>Apply Rate</ApplyButton>
              <Field label="RBW kHz" value={rbwKHz} onChange={setRbwKHz} />
              <ApplyButton busy={busy !== null} onClick={() => run('rbw', () => controller.setRbw(khzToHz(rbwKHz)))}>Apply</ApplyButton>
              <Field label="VBW kHz" value={vbwKHz} onChange={setVbwKHz} />
              <ApplyButton busy={busy !== null} onClick={() => run('vbw', () => controller.setVbw(khzToHz(vbwKHz)))}>Apply</ApplyButton>
            </div>
          </div>

          <div>
            <div className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Level and detector</div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Ref dB" value={refDb} onChange={setRefDb} />
              <ApplyButton busy={busy !== null} onClick={() => run('ref', () => controller.setReferenceLevel(refDb))}>Apply</ApplyButton>
              <Field label="Gain dB" value={gainDb} onChange={setGainDb} />
              <ApplyButton busy={busy !== null} onClick={() => run('gain', () => controller.setGain(gainDb))}>Apply</ApplyButton>
            </div>
            <label className="mt-2 flex flex-col gap-0.5 text-[10px] app-muted-text">
              Detector
              <select
                value={settings.detectorMode}
                onChange={(event) => run('detector', () => controller.setDetectorMode(event.target.value as typeof settings.detectorMode))}
                className="w-full rounded-md border bg-transparent px-2 py-1 text-xs"
                style={{ borderColor: 'var(--app-border)' }}
              >
                {(['sample', 'rms', 'average', 'peak', 'min_hold', 'max_hold', 'video'] as const).map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
            <div className="mt-2 flex items-end gap-2">
              <Field label="Averaging (frames)" value={averaging} onChange={setAveragingLocal} step={1} />
              <ApplyButton busy={busy !== null} onClick={() => run('averaging', () => controller.setAveraging(averaging))}>Apply</ApplyButton>
            </div>
          </div>

          <div>
            <div className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Export</div>
            <div className="flex gap-2">
              <ApplyButton busy={false} onClick={onExportPng}>PNG</ApplyButton>
              <ApplyButton busy={false} onClick={onExportCsv}>CSV</ApplyButton>
            </div>
          </div>

          {error && <p className="text-[11px] text-amber-400">{error}</p>}
          {deviceStatus.lastError && <p className="text-[11px] text-amber-400">Device: {deviceStatus.lastError}</p>}
        </HudFrame>
      )}

      <button
        onClick={onToggleOpen}
        className="pointer-events-auto flex flex-shrink-0 items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
        style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
      >
        <Radio className="h-3.5 w-3.5" />
        Receiver {deviceStatus.isConnected ? '(connected)' : '(disconnected)'}
      </button>
    </div>
  );
};
