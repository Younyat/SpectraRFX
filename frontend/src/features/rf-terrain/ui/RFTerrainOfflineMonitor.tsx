import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Activity } from 'lucide-react';
import { HudFrame } from './hud/HudFrame';
import { HUD_ACCENT_BRIGHT, hudLabelClass } from './hud/hudTheme';
import type { OfflineReconstructionStage, OfflineReconstructionState } from '../offline/OfflineReconstructionController';

interface RFTerrainOfflineMonitorProps {
  state: OfflineReconstructionState;
}

const STAGE_LABELS: Record<OfflineReconstructionStage, string> = {
  IDLE: 'Idle',
  FETCHING_CHUNK: 'Fetching I/Q chunk',
  PARSING_CHUNK: 'Parsing cf32_le bytes',
  ANALYZING_FRAMES: 'FFT / terrain analysis',
  SEGMENTING: 'Segmenting terrain objects',
  COMPUTING_CONTEXT_AUDIT: 'Computing Spectral Context Audit',
  COMPUTING_HASHES: 'Computing reproducibility hashes',
  DONE: 'Done',
};

// mm:ss.mmm -- millisecond precision, since the whole point of this panel
// is a PRECISE read of real elapsed time, not a rounded approximation.
const formatDurationPrecise = (ms: number): string => {
  const totalMs = Math.max(0, Math.round(ms));
  const minutes = Math.floor(totalMs / 60000);
  const seconds = Math.floor((totalMs % 60000) / 1000);
  const millis = totalMs % 1000;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`;
};

const formatDurationApprox = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
};

const formatBytes = (bytes: number): string => {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

const ACTIVE_STATUSES = new Set(['LOADING', 'VALIDATING', 'RECONSTRUCTING']);

// A dedicated, always-on-top, transparent glass HUD window that tracks
// Offline Reconstruction precisely -- real elapsed time (ms precision,
// ticking every 200ms off the wall clock even between chunk fetches),
// real bytes/chunks/rows actually processed so far, and a real,
// measurement-derived throughput/ETA. Every number here is either
// directly measured or a direct arithmetic derivation of measured values
// (bytesProcessed / elapsedSeconds, remainingBytes / throughput) -- never
// a fixed fake increment or a cosmetic animation standing in for real
// progress. Independent of the Menu/Offline-panel open state so it stays
// visible for the whole run.
export const RFTerrainOfflineMonitor: React.FC<RFTerrainOfflineMonitorProps> = ({ state }) => {
  const [collapsed, setCollapsed] = useState(false);
  const visible = ACTIVE_STATUSES.has(state.status) || state.status === 'ERROR_LOCAL' || (state.status === 'COMPLETE' && state.stage === 'DONE');

  // A brand-new reconstruction always re-opens the panel, even if the
  // previous run's summary had been collapsed.
  useEffect(() => {
    if (state.status === 'RECONSTRUCTING' && state.chunksProcessed === 0 && state.bytesProcessed === 0) {
      setCollapsed(false);
    }
  }, [state.status, state.chunksProcessed, state.bytesProcessed]);

  if (!visible) return null;

  const percent = state.totalBytes > 0 ? Math.min(100, (state.bytesProcessed / state.totalBytes) * 100) : 0;

  return (
    <div className="pointer-events-none absolute left-1/2 top-3 z-30 flex -translate-x-1/2 flex-col items-center">
      <HudFrame className="pointer-events-auto flex w-96 flex-col gap-2 rounded-sm p-3 text-slate-100 shadow-2xl">
        <button
          onClick={() => setCollapsed((prev) => !prev)}
          className="flex w-full items-center justify-between"
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          <span className={`flex items-center gap-1.5 ${hudLabelClass}`} style={{ color: HUD_ACCENT_BRIGHT }}>
            <Activity className="h-3.5 w-3.5" />
            Offline Reconstruction Monitor
          </span>
          {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
        </button>

        {collapsed ? (
          <div className="flex items-center justify-between text-[11px] app-muted-text">
            <span>{STAGE_LABELS[state.stage]}</span>
            <span className="font-mono">{percent.toFixed(1)}% · {formatDurationPrecise(state.elapsedMs)}</span>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-[11px]">
              <span className="app-muted-text">Stage</span>
              <span
                className="font-mono"
                style={{ color: state.status === 'ERROR_LOCAL' ? '#f87171' : HUD_ACCENT_BRIGHT }}
              >
                {state.status === 'ERROR_LOCAL' ? 'Error' : STAGE_LABELS[state.stage]}
              </span>
            </div>

            {state.error && <p className="text-[10px] text-red-400">{state.error}</p>}

            <div className="h-2 w-full overflow-hidden rounded bg-white/10">
              <div className="h-full transition-all" style={{ width: `${percent}%`, background: HUD_ACCENT_BRIGHT }} />
            </div>

            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
              <span className="app-muted-text">Elapsed</span>
              <span className="text-right font-mono">{formatDurationPrecise(state.elapsedMs)}</span>

              <span className="app-muted-text">Progress</span>
              <span className="text-right font-mono">{percent.toFixed(2)}%</span>

              <span className="app-muted-text">Bytes</span>
              <span className="text-right font-mono">{formatBytes(state.bytesProcessed)} / {formatBytes(state.totalBytes)}</span>

              <span className="app-muted-text">Chunk</span>
              <span className="text-right font-mono">{state.chunksProcessed} / {state.totalChunks}</span>

              <span className="app-muted-text">Rows produced</span>
              <span className="text-right font-mono">{state.totalRows.toLocaleString()}</span>

              <span className="app-muted-text">Throughput</span>
              <span className="text-right font-mono">
                {state.throughputBytesPerSecond === null ? '—' : `${formatBytes(state.throughputBytesPerSecond)}/s`}
              </span>

              <span className="app-muted-text">ETA</span>
              <span className="text-right font-mono">
                {state.estimatedRemainingMs === null ? '—' : `~${formatDurationApprox(state.estimatedRemainingMs)}`}
              </span>
            </div>

            {state.status === 'COMPLETE' && (
              <p className="text-[10px] app-muted-text">
                Reconstruction complete in {formatDurationPrecise(state.elapsedMs)}.
              </p>
            )}
          </div>
        )}
      </HudFrame>
    </div>
  );
};
