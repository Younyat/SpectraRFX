import React, { useEffect, useState } from 'react';
import { Database, Play, Pause, SkipForward, RotateCcw, X, RefreshCw } from 'lucide-react';
import { HudFrame } from './hud/HudFrame';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_PANEL_BACKGROUND, hudLabelClass } from './hud/hudTheme';
import type { OfflineReconstructionController, OfflineReconstructionState } from '../offline/OfflineReconstructionController';

export type RFTerrainSource = 'LIVE' | 'OFFLINE';

interface RFTerrainOfflinePanelProps {
  open: boolean;
  onToggleOpen: () => void;
  source: RFTerrainSource;
  onSourceChange: (source: RFTerrainSource) => void;
  controller: OfflineReconstructionController;
  state: OfflineReconstructionState;
}

const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8];

// Import + RECONSTRUCT + playback for a preserved BLE I/Q capture (spec's
// Offline Spectral Reconstruction). LIVE stays the default and untouched;
// switching SOURCE to OFFLINE only changes what feeds RFTerrainCanvas via
// onRow, never how LIVE itself works.
export const RFTerrainOfflinePanel: React.FC<RFTerrainOfflinePanelProps> = ({ open, onToggleOpen, source, onSourceChange, controller, state }) => {
  const [captureIdInput, setCaptureIdInput] = useState('');
  const [manualEntryOpen, setManualEntryOpen] = useState(false);

  const busy = state.status === 'LOADING' || state.status === 'VALIDATING' || state.status === 'RECONSTRUCTING';

  // Auto-detect (no click required): as soon as the panel is open on
  // OFFLINE with nothing loaded yet, list the most recent captures via
  // the real /recordings endpoint instead of making the operator already
  // know a capture ID.
  useEffect(() => {
    if (open && source === 'OFFLINE' && state.status === 'NO_CAPTURE' && state.recentCapturesStatus === 'IDLE') {
      controller.refreshRecentCaptures();
    }
  }, [open, source, state.status, state.recentCapturesStatus, controller]);

  return (
    <div className="pointer-events-none absolute bottom-3 right-3 z-20 flex flex-col items-end gap-2">
      {open && (
        <HudFrame className="pointer-events-auto flex w-80 flex-col gap-2 rounded-sm p-3 text-slate-100 shadow-2xl">
          <div className="flex items-center justify-between">
            <h3 className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Source</h3>
            <div className="flex overflow-hidden rounded border" style={{ borderColor: HUD_BORDER_COLOR }}>
              {(['LIVE', 'OFFLINE'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => onSourceChange(option)}
                  className="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                  style={{ background: source === option ? HUD_ACCENT_BRIGHT : 'transparent', color: source === option ? '#04121a' : undefined }}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          {source === 'LIVE' && (
            <p className="text-[11px] app-muted-text">LIVE polls the connected SDR in real time. Switch to OFFLINE to reconstruct a preserved capture instead.</p>
          )}

          {source === 'OFFLINE' && (
            <div className="flex flex-col gap-2">
              <div className="rounded border border-dashed p-1.5 text-[10px] text-amber-300" style={{ borderColor: '#f59e0b' }}>
                OBSERVED SPECTRAL WINDOW ONLY -- this reconstructs the frequency span the receiver actually captured, never the full 2.4 GHz band.
              </div>

              {state.status === 'NO_CAPTURE' && (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] app-muted-text">
                      Recent captures {state.recentCapturesStatus === 'READY' ? `(${state.recentCaptures.length})` : ''}
                    </span>
                    <button
                      onClick={() => controller.refreshRecentCaptures()}
                      disabled={state.recentCapturesStatus === 'LOADING'}
                      title="Refresh"
                      className="rounded border p-1 disabled:opacity-40"
                      style={{ borderColor: HUD_BORDER_COLOR }}
                    >
                      <RefreshCw className={`h-3 w-3 ${state.recentCapturesStatus === 'LOADING' ? 'animate-spin' : ''}`} />
                    </button>
                  </div>

                  {state.recentCapturesStatus === 'LOADING' && <p className="text-[10px] app-muted-text">Detecting recent captures…</p>}
                  {state.recentCapturesStatus === 'ERROR' && <p className="text-[10px] text-red-400">{state.recentCapturesError}</p>}
                  {state.recentCapturesStatus === 'READY' && state.recentCaptures.length === 0 && (
                    <p className="text-[10px] app-muted-text">No preserved captures found.</p>
                  )}

                  {state.recentCapturesStatus === 'READY' && state.recentCaptures.length > 0 && (
                    <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
                      {state.recentCaptures.map((capture) => (
                        <button
                          key={capture.captureId}
                          onClick={() => controller.loadCapture(capture.captureId)}
                          className="flex flex-col items-start gap-0.5 rounded border px-2 py-1 text-left hover:bg-white/5"
                          style={{ borderColor: HUD_BORDER_COLOR }}
                        >
                          <span className="w-full truncate font-mono text-[10px]">{capture.captureId}</span>
                          <span className="flex w-full items-center justify-between text-[9px] app-muted-text">
                            <span>{(capture.centerFrequencyHz / 1e6).toFixed(3)} MHz</span>
                            <span>{(capture.sampleCount / capture.sampleRateSps).toFixed(1)}s</span>
                            <span>{capture.createdAtUtc ? new Date(capture.createdAtUtc).toLocaleString() : 'unknown date'}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}

                  <button
                    onClick={() => setManualEntryOpen((prev) => !prev)}
                    className="text-left text-[10px] app-muted-text underline"
                  >
                    {manualEntryOpen ? 'Hide manual entry' : 'Enter a capture ID manually'}
                  </button>
                </div>
              )}

              {(manualEntryOpen || state.status !== 'NO_CAPTURE') && (
                <label className="flex flex-col gap-1 text-[10px] app-muted-text">
                  Capture ID
                  <input
                    value={captureIdInput}
                    onChange={(event) => setCaptureIdInput(event.target.value)}
                    placeholder="BLE-IQ-..."
                    disabled={busy}
                    className="rounded-md border bg-transparent px-2 py-1 text-xs text-slate-100"
                    style={{ borderColor: 'var(--app-border)' }}
                  />
                </label>
              )}

              <div className="flex gap-2">
                {(manualEntryOpen || state.status !== 'NO_CAPTURE') && (
                  <button
                    disabled={busy || !captureIdInput}
                    onClick={() => controller.loadCapture(captureIdInput.trim())}
                    className="flex-1 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
                    style={{ borderColor: HUD_BORDER_COLOR }}
                  >
                    Import
                  </button>
                )}
                <button
                  disabled={busy || !['READY', 'COMPLETE', 'PAUSED'].includes(state.status)}
                  onClick={() => controller.reconstruct()}
                  className="flex-1 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
                  style={{ borderColor: HUD_ACCENT_BRIGHT, color: HUD_ACCENT_BRIGHT }}
                >
                  Reconstruct
                </button>
              </div>

              <div className="flex items-center justify-between text-[10px] app-muted-text">
                <span>Status</span>
                <span className="font-mono" style={{ color: state.status === 'ERROR_LOCAL' ? '#f87171' : undefined }}>{state.status}</span>
              </div>

              {state.status === 'RECONSTRUCTING' && (
                <p className="text-[10px] app-muted-text">See the Reconstruction Monitor (top of screen) for precise time/progress.</p>
              )}

              {state.error && <p className="text-[10px] text-red-400">{state.error}</p>}

              {state.metadata && (
                <div className="space-y-0.5 rounded border p-1.5 text-[10px]" style={{ borderColor: HUD_BORDER_COLOR }}>
                  <div className="flex justify-between"><span className="app-muted-text">Sample rate</span><span className="font-mono">{(state.metadata.sampleRateSps / 1e6).toFixed(3)} Msps</span></div>
                  <div className="flex justify-between"><span className="app-muted-text">Bandwidth</span><span className="font-mono">{(state.metadata.bandwidthHz / 1e6).toFixed(3)} MHz</span></div>
                  <div className="flex justify-between"><span className="app-muted-text">Duration</span><span className="font-mono">{(state.metadata.sampleCount / state.metadata.sampleRateSps).toFixed(2)} s</span></div>
                  <div className="flex justify-between"><span className="app-muted-text">Device</span><span className="font-mono">{state.metadata.deviceSerial ?? 'unknown'}</span></div>
                  <div className="flex justify-between"><span className="app-muted-text">Calibration</span><span className="font-mono">NOT DOCUMENTED</span></div>
                </div>
              )}

              {(state.status === 'COMPLETE' || state.status === 'PAUSED' || state.status === 'PLAYING') && state.totalRows > 0 && (
                <div className="flex flex-col gap-1.5">
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, state.totalRows - 1)}
                    value={Math.min(state.currentRowIndex, state.totalRows - 1)}
                    onChange={(event) => controller.seekToRowIndex(Number(event.target.value))}
                    className="w-full"
                  />
                  <div className="flex items-center justify-between gap-1">
                    <button onClick={() => controller.restart()} title="Restart" className="rounded border p-1" style={{ borderColor: HUD_BORDER_COLOR }}><RotateCcw className="h-3 w-3" /></button>
                    {state.status === 'PLAYING' ? (
                      <button onClick={() => controller.pause()} title="Pause" className="rounded border p-1" style={{ borderColor: HUD_BORDER_COLOR }}><Pause className="h-3 w-3" /></button>
                    ) : (
                      <button onClick={() => controller.play()} title="Play" className="rounded border p-1" style={{ borderColor: HUD_BORDER_COLOR }}><Play className="h-3 w-3" /></button>
                    )}
                    <button onClick={() => controller.step()} title="Step" className="rounded border p-1" style={{ borderColor: HUD_BORDER_COLOR }}><SkipForward className="h-3 w-3" /></button>
                    <select
                      value={state.playbackSpeed}
                      onChange={(event) => controller.setPlaybackSpeed(Number(event.target.value))}
                      className="rounded border bg-transparent px-1 py-0.5 text-[10px]"
                      style={{ borderColor: HUD_BORDER_COLOR }}
                    >
                      {PLAYBACK_SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
                    </select>
                    <span className="ml-auto font-mono text-[10px] app-muted-text">{state.currentRowIndex}/{state.totalRows}</span>
                  </div>
                </div>
              )}

              {state.contextAudit && (
                <div className="space-y-0.5 rounded border p-1.5 text-[10px]" style={{ borderColor: HUD_BORDER_COLOR }}>
                  <div className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Spectral Context Audit</div>
                  <p className="app-muted-text">Characterizes the acquisition, never fed into any classifier.</p>
                  <div className="flex justify-between"><span className="app-muted-text">C1 baseline (median)</span><span className="font-mono">{state.contextAudit.baseline.medianBaselineDb.toFixed(1)} dB</span></div>
                  <div className="flex justify-between"><span className="app-muted-text">C2 occupancy (mean)</span><span className="font-mono">{(state.contextAudit.occupancy.meanOccupancy * 100).toFixed(0)}%</span></div>
                  <div className="flex justify-between"><span className="app-muted-text">C4 object density</span><span className="font-mono">{state.contextAudit.objectDensity.objectsPerSecond.toFixed(2)}/s</span></div>
                  <p className="app-muted-text">C3 (nearby activity) and part of C5: not implemented.</p>
                </div>
              )}

              {state.metadata && (
                <button onClick={() => controller.cancel()} className="flex items-center justify-center gap-1 rounded border px-2 py-1 text-[10px] uppercase tracking-wide app-muted-text" style={{ borderColor: HUD_BORDER_COLOR }}>
                  <X className="h-3 w-3" /> Unload capture
                </button>
              )}
            </div>
          )}
        </HudFrame>
      )}
      <button
        onClick={onToggleOpen}
        className="pointer-events-auto flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
        style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND }}
      >
        <Database className="h-3.5 w-3.5" />
        Offline Reconstruction
      </button>
    </div>
  );
};
