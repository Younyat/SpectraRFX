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

// One real, plain-language sentence per stage -- what is actually
// happening right now and, where relevant, the real bound on how long it
// can take before something is genuinely wrong (each chunk download times
// out and fails with a clear error after 30s -- see captureClient.ts's
// DEFAULT_CHUNK_TIMEOUT_MS -- so "how long do I wait" always has a real
// answer: at most ~30s of silence per chunk before either progress or an
// error appears).
const STAGE_EXPLANATIONS: Record<OfflineReconstructionStage, string> = {
  IDLE: '',
  FETCHING_CHUNK: 'Downloading the next 16 MB piece of the raw capture from the backend. Fails with a clear error after 30s if the connection stalls -- it will never hang silently forever.',
  PARSING_CHUNK: 'Decoding the downloaded bytes into I/Q samples. Fast (well under a second per chunk).',
  ANALYZING_FRAMES: 'Running the FFT and terrain engine (noise floor, persistence, occupancy) on this chunk\'s samples. Fast.',
  SEGMENTING: 'One-time pass identifying terrain objects across every reconstructed row. Runs once, after all chunks are downloaded.',
  COMPUTING_CONTEXT_AUDIT: 'Computing the C1/C2/C4 acquisition-context summary from the already-processed rows.',
  COMPUTING_HASHES: 'Computing the reproducibility fingerprint (SHA-256 of the profile and source data). Near-instant.',
  DONE: 'Reconstruction finished -- use the playback controls in the Offline Reconstruction panel to scrub through it.',
};

const FIELD_HELP: Record<string, string> = {
  Elapsed: 'Real wall-clock time since RECONSTRUCT was pressed. Keeps ticking even mid-download.',
  Progress: 'Bytes downloaded so far, as a percentage of the whole capture file.',
  Bytes: 'How much of the raw capture has been downloaded vs. its total real size on disk.',
  Chunk: 'Which 16 MB download is in flight, out of the total needed to cover the whole capture.',
  'Rows produced': 'How many terrain rows have been computed from the chunks downloaded so far.',
  Throughput: 'Real download speed, measured from bytes actually received -- appears once the first chunk completes.',
  ETA: 'Estimated time left, from current throughput × remaining bytes -- appears once the first chunk completes, and improves as more chunks land.',
};

// A stuck FIRST chunk (no bytes at all yet) past this point is worth
// flagging proactively -- the real 30s per-chunk timeout (captureClient.ts)
// will still fire and produce a clear error either way, but this gives
// the operator an earlier, honest heads-up rather than silent waiting.
const STUCK_FIRST_CHUNK_WARNING_MS = 15_000;

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

            {state.status !== 'ERROR_LOCAL' && STAGE_EXPLANATIONS[state.stage] && (
              <p className="text-[9px] leading-snug app-muted-text">{STAGE_EXPLANATIONS[state.stage]}</p>
            )}

            {state.error && <p className="text-[10px] text-red-400">{state.error}</p>}

            {state.status === 'RECONSTRUCTING' && state.chunksProcessed === 0 && state.elapsedMs > STUCK_FIRST_CHUNK_WARNING_MS && (
              <p className="rounded border border-amber-500/60 bg-amber-500/10 p-1 text-[9px] text-amber-300">
                No bytes received yet after {Math.round(state.elapsedMs / 1000)}s -- if this keeps going, it will fail with a clear error at 30s (never hang forever). This usually means the backend or network stalled.
              </p>
            )}

            <div className="h-2 w-full overflow-hidden rounded bg-white/10" title="Bytes downloaded so far, as a share of the whole capture file.">
              <div className="h-full transition-all" style={{ width: `${percent}%`, background: HUD_ACCENT_BRIGHT }} />
            </div>

            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
              <span className="app-muted-text" title={FIELD_HELP.Elapsed}>Elapsed</span>
              <span className="text-right font-mono">{formatDurationPrecise(state.elapsedMs)}</span>

              <span className="app-muted-text" title={FIELD_HELP.Progress}>Progress</span>
              <span className="text-right font-mono">{percent.toFixed(2)}%</span>

              <span className="app-muted-text" title={FIELD_HELP.Bytes}>Bytes</span>
              <span className="text-right font-mono">{formatBytes(state.bytesProcessed)} / {formatBytes(state.totalBytes)}</span>

              <span className="app-muted-text" title={FIELD_HELP.Chunk}>Chunk</span>
              <span className="text-right font-mono">{state.chunksProcessed} / {state.totalChunks}</span>

              <span className="app-muted-text" title={FIELD_HELP['Rows produced']}>Rows produced</span>
              <span className="text-right font-mono">{state.totalRows.toLocaleString()}</span>

              <span className="app-muted-text" title={FIELD_HELP.Throughput}>Throughput</span>
              <span className="text-right font-mono">
                {state.throughputBytesPerSecond === null ? 'not yet known' : `${formatBytes(state.throughputBytesPerSecond)}/s`}
              </span>

              <span className="app-muted-text" title={FIELD_HELP.ETA}>ETA</span>
              <span className="text-right font-mono">
                {state.estimatedRemainingMs === null ? 'not yet known' : `~${formatDurationApprox(state.estimatedRemainingMs)}`}
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
