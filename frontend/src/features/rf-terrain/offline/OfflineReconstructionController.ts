import { OfflineCaptureClient } from '../engine/offline/captureClient';
import { validateCaptureManifest, OfflineCaptureMetadata } from '../engine/offline/captureMetadata';
import { OfflineSpectrumGenerator, NativeResolutionFrame } from '../engine/offline/spectrumGenerator';
import { getSampleFormatSpec } from '../engine/offline/iqBytes';
import { OFFLINE_RECONSTRUCTION_PROFILE_V1, OfflineReconstructionProfile, computeHopSizeSamples, computeProfileConfigHash, computeReconstructionId } from '../engine/offline/reconstructionProfile';
import { computeContextAuditReport, ContextAuditReport } from '../engine/offline/contextAudit';
import { validateSpectrumFrame } from '../data/frameValidator';
import { adaptSpectrumFrame } from '../data/spectrumFrameAdapter';
import { createTerrainWorkerState } from '../engine/terrainWorkerState';
import type { TerrainObject, TerrainProcessedRow } from '../model/rfTerrainTypes';
import { RF_TERRAIN_DEFAULT_FREQUENCY_BINS } from '../model/rfTerrainConstants';

export type OfflineReconstructionStatus =
  | 'NO_CAPTURE' | 'LOADING' | 'VALIDATING' | 'READY' | 'RECONSTRUCTING'
  | 'PAUSED' | 'PLAYING' | 'COMPLETE' | 'ERROR_LOCAL';

export type RecentCapturesStatus = 'IDLE' | 'LOADING' | 'READY' | 'ERROR';

export const RECENT_CAPTURES_LIMIT = 50;

// Fine-grained stage within `status === 'RECONSTRUCTING'` -- precise
// enough that a monitor UI can show exactly what is happening right now,
// not just a single "working..." bucket.
export type OfflineReconstructionStage =
  | 'IDLE'
  | 'FETCHING_CHUNK'
  | 'PARSING_CHUNK'
  | 'ANALYZING_FRAMES'
  | 'SEGMENTING'
  | 'COMPUTING_CONTEXT_AUDIT'
  | 'COMPUTING_HASHES'
  | 'DONE';

export interface OfflineReconstructionState {
  status: OfflineReconstructionStatus;
  captureId: string | null;
  metadata: OfflineCaptureMetadata | null;
  error: string | null;
  progressFraction: number;
  totalRows: number;
  currentRowIndex: number;
  playbackSpeed: number;
  objects: TerrainObject[];
  contextAudit: ContextAuditReport | null;
  reconstructionId: string | null;
  // Auto-detected candidates for import (spec: NO_CAPTURE should surface
  // the most recent captures rather than requiring a memorized ID). Real
  // manifests from the same read-only /recordings endpoint, sorted
  // newest-first by the backend, capped at RECENT_CAPTURES_LIMIT --
  // never filtered by frequency, so a receiver retune between captures
  // never hides one.
  recentCaptures: OfflineCaptureMetadata[];
  recentCapturesStatus: RecentCapturesStatus;
  recentCapturesError: string | null;
  // Precise reconstruction telemetry -- every field here is a real,
  // directly-measured or directly-derived quantity (wall-clock elapsed
  // time, real bytes/chunks/rows counted as they are actually processed),
  // never a fabricated smoothing or a fixed fake increment. Lets a
  // monitor UI show exactly where time is going.
  stage: OfflineReconstructionStage;
  elapsedMs: number;
  bytesProcessed: number;
  totalBytes: number;
  chunksProcessed: number;
  totalChunks: number;
  // Derived from real bytesProcessed/elapsedMs -- null until at least one
  // chunk has completed (never a divide-by-zero guess).
  throughputBytesPerSecond: number | null;
  estimatedRemainingMs: number | null;
}

export interface OfflineReconstructionCallbacks {
  onStateChange?: (state: OfflineReconstructionState) => void;
  // Fired once per row during PLAYING, in order -- the exact same shape
  // useRFTerrainFrameSource's onRow gives the canvas, so RFTerrainCanvas
  // itself needs zero changes to consume either source (spec §6/§31).
  onRow?: (row: TerrainProcessedRow) => void;
  onReset?: () => void;
}

// 16 MiB per HTTP range request -- bounded memory (never "read entire
// file"; a multi-GB capture is still read in small pieces), while keeping
// the request COUNT for a large capture reasonable: at 4 MiB, a ~1.6 GB
// capture needed ~400 sequential round trips, each carrying real
// per-request backend overhead on top of the actual transfer -- the
// single largest, measured contributor to a slow reconstruction.
// Configurable per instance (constructor `chunkBytes`) mainly so tests can
// exercise multi-chunk progress deterministically with a tiny buffer.
const DEFAULT_CHUNK_BYTES = 16 * 1024 * 1024;
const PROGRESS_TICK_INTERVAL_MS = 200;

// Additive, isolated orchestrator for Offline Spectral Reconstruction.
// Owns its OWN instance of the SAME pure engine LIVE's terrain.worker.ts
// wraps (createTerrainWorkerState -- noise floor, persistence, occupancy,
// holds, segmentation) -- zero duplication of that logic, and zero
// changes to it. Deliberately kept out of useRFTerrainFrameSource.ts
// (spec §7): a completely separate module the live hook has no
// dependency on and no awareness of. Runs the engine in-process
// (synchronously) rather than through a real Worker thread: offline
// reconstruction has no live-polling deadline to protect, the FFT (the
// actually expensive step) already happens before this point in
// OfflineSpectrumGenerator, and staying synchronous keeps this whole
// module deterministically unit-testable without a Worker
// polyfill/mock. Known, disclosed limitation: a very large capture can
// block the main thread during RECONSTRUCTING -- moving this to a real
// dedicated worker later is possible without changing this class's
// public contract, and is not implemented in this pass.
export class OfflineReconstructionController {
  private readonly client: OfflineCaptureClient;
  private readonly profile: OfflineReconstructionProfile;
  private readonly chunkBytes: number;
  private callbacks: OfflineReconstructionCallbacks;
  private engine: ReturnType<typeof createTerrainWorkerState> | null = null;
  private generation = 1;
  private rows: TerrainProcessedRow[] = [];
  private playbackTimer: ReturnType<typeof setTimeout> | null = null;
  private abortController: AbortController | null = null;
  private reconstructionStartedAtMs: number | null = null;
  private progressTicker: ReturnType<typeof setInterval> | null = null;

  private state: OfflineReconstructionState = {
    status: 'NO_CAPTURE',
    captureId: null,
    metadata: null,
    error: null,
    progressFraction: 0,
    totalRows: 0,
    currentRowIndex: 0,
    playbackSpeed: 1,
    objects: [],
    contextAudit: null,
    reconstructionId: null,
    recentCaptures: [],
    recentCapturesStatus: 'IDLE',
    recentCapturesError: null,
    stage: 'IDLE',
    elapsedMs: 0,
    bytesProcessed: 0,
    totalBytes: 0,
    chunksProcessed: 0,
    totalChunks: 0,
    throughputBytesPerSecond: null,
    estimatedRemainingMs: null,
  };

  private readonly softwareCommit: string;

  constructor(
    callbacks: OfflineReconstructionCallbacks = {},
    config: { baseUrl?: string; fetchImpl?: typeof fetch; profile?: OfflineReconstructionProfile; softwareCommit?: string; chunkBytes?: number } = {},
  ) {
    this.callbacks = callbacks;
    this.client = new OfflineCaptureClient({ baseUrl: config.baseUrl, fetchImpl: config.fetchImpl });
    this.profile = config.profile ?? OFFLINE_RECONSTRUCTION_PROFILE_V1;
    this.chunkBytes = config.chunkBytes ?? DEFAULT_CHUNK_BYTES;
    // No build step in this project wires in a real git commit today
    // (confirmed: no `define`/`import.meta.env` plumbing for it in
    // vite.config.ts) -- 'unknown' is an honest value, never a fabricated
    // SHA. Callers that DO have a real commit (e.g. a future CI-injected
    // env var) can pass it explicitly.
    this.softwareCommit = config.softwareCommit ?? 'unknown';
  }

  // Lets a React wrapper re-point callbacks at fresh closures every render
  // without recreating the underlying engine/state.
  setCallbacks(callbacks: OfflineReconstructionCallbacks) {
    this.callbacks = callbacks;
  }

  getState(): OfflineReconstructionState {
    return this.state;
  }

  getRows(): readonly TerrainProcessedRow[] {
    return this.rows;
  }

  private setState(partial: Partial<OfflineReconstructionState>) {
    this.state = { ...this.state, ...partial };
    this.callbacks.onStateChange?.(this.state);
  }

  // Recomputes elapsed/throughput/ETA purely from real, already-known
  // values (wall-clock start time, bytes actually processed so far) --
  // never advances bytesProcessed or chunksProcessed itself. Called both
  // right after each real chunk completes and on a periodic ticker so
  // elapsed time visibly keeps moving even while a single chunk fetch is
  // still in flight, instead of looking frozen between updates.
  private recomputeTiming() {
    if (this.reconstructionStartedAtMs === null) return;
    const elapsedMs = Date.now() - this.reconstructionStartedAtMs;
    const elapsedSeconds = elapsedMs / 1000;
    const throughputBytesPerSecond = this.state.bytesProcessed > 0 && elapsedSeconds > 0
      ? this.state.bytesProcessed / elapsedSeconds
      : null;
    const remainingBytes = this.state.totalBytes - this.state.bytesProcessed;
    const estimatedRemainingMs = throughputBytesPerSecond && throughputBytesPerSecond > 0
      ? (remainingBytes / throughputBytesPerSecond) * 1000
      : null;
    this.setState({ elapsedMs, throughputBytesPerSecond, estimatedRemainingMs });
  }

  private startProgressTicker() {
    this.stopProgressTicker();
    this.reconstructionStartedAtMs = Date.now();
    this.progressTicker = setInterval(() => this.recomputeTiming(), PROGRESS_TICK_INTERVAL_MS);
  }

  private stopProgressTicker() {
    if (this.progressTicker) {
      clearInterval(this.progressTicker);
      this.progressTicker = null;
    }
    this.reconstructionStartedAtMs = null;
  }

  private ensureEngine(): ReturnType<typeof createTerrainWorkerState> {
    if (!this.engine) {
      this.engine = createTerrainWorkerState(RF_TERRAIN_DEFAULT_FREQUENCY_BINS);
    }
    return this.engine;
  }

  private feedFrame(frame: Parameters<typeof adaptSpectrumFrame>[0]): TerrainProcessedRow | null {
    const engine = this.ensureEngine();
    const terrainFrame = adaptSpectrumFrame(frame, this.generation, RF_TERRAIN_DEFAULT_FREQUENCY_BINS);
    const outputs = engine.handle({ type: 'FRAME', generation: this.generation, frame: terrainFrame });
    for (const output of outputs) {
      if (output.type === 'ROW') return output.row;
      if (output.type === 'ERROR' && !output.recoverable) throw new Error(`${output.code}: ${output.message}`);
    }
    return null;
  }

  private requestObjects(): TerrainObject[] {
    const engine = this.ensureEngine();
    const outputs = engine.handle({ type: 'SEGMENT', generation: this.generation });
    for (const output of outputs) {
      if (output.type === 'OBJECTS') return output.objects;
    }
    return [];
  }

  // Auto-detect: lists the most recent captures via the real, read-only
  // /recordings endpoint (the same one every single-capture import
  // already uses) so NO_CAPTURE can offer a one-click picker instead of
  // requiring the operator to already know a capture ID. Deliberately
  // does not filter by frequency -- a capture taken while tuned elsewhere
  // is exactly as valid an OFFLINE reconstruction target. Each raw
  // manifest is validated the same way a manual import would be; a
  // malformed individual manifest is skipped rather than failing the
  // whole list.
  async refreshRecentCaptures(limit: number = RECENT_CAPTURES_LIMIT): Promise<void> {
    this.setState({ recentCapturesStatus: 'LOADING', recentCapturesError: null });
    try {
      const rawManifests = await this.client.fetchRecentCaptureManifests();
      const validated = rawManifests
        .map((raw) => validateCaptureManifest(raw))
        .filter((result): result is { valid: true; metadata: OfflineCaptureMetadata } => result.valid)
        .map((result) => result.metadata)
        .slice(0, limit);
      this.setState({ recentCaptures: validated, recentCapturesStatus: 'READY' });
    } catch (error) {
      this.setState({
        recentCapturesStatus: 'ERROR',
        recentCapturesError: error instanceof Error ? error.message : String(error),
      });
    }
  }

  // 1) Import preserved capture -- fetches ONLY the manifest (a few
  // hundred bytes), never the I/Q itself. No SDR access, no writes.
  async loadCapture(captureId: string): Promise<void> {
    this.setState({ status: 'LOADING', captureId, error: null, metadata: null });
    try {
      const raw = await this.client.fetchManifest(captureId);
      this.setState({ status: 'VALIDATING' });
      const validation = validateCaptureManifest(raw);
      if (!validation.valid) {
        this.setState({ status: 'ERROR_LOCAL', error: `Invalid capture metadata: ${validation.reason}` });
        return;
      }
      this.setState({ status: 'READY', metadata: validation.metadata });
    } catch (error) {
      this.setState({ status: 'ERROR_LOCAL', error: error instanceof Error ? error.message : String(error) });
    }
  }

  // 2) RECONSTRUCT -- chunked read, deterministic FFT/STFT, same RF
  // Terrain analysis as LIVE, via the same worker contract. Processes
  // EVERY chunk-derived frame (no "latest wins" dropping -- offline needs
  // the complete, deterministic sequence, unlike live's real-time
  // backpressure). The NEXT chunk's fetch is kicked off before the
  // CURRENT chunk finishes being parsed/analyzed (real network latency
  // overlapped with real CPU work, never both paid serially for the same
  // pair of chunks) -- processing order itself stays strictly sequential,
  // which is what determinism actually depends on, not fetch timing.
  async reconstruct(): Promise<void> {
    const metadata = this.state.metadata;
    if (!metadata) {
      this.setState({ status: 'ERROR_LOCAL', error: 'reconstruct() called before a capture was loaded' });
      return;
    }

    this.generation += 1;
    this.rows = [];
    this.abortController = new AbortController();
    const engine = this.ensureEngine();
    const hopSizeSamples = computeHopSizeSamples(this.profile, metadata.sampleCount);
    engine.handle({ type: 'RESET', generation: this.generation, capacity: Math.ceil(metadata.sampleCount / hopSizeSamples) + 1 });

    const { bytesPerSample, parse } = getSampleFormatSpec(metadata.sampleFormat);
    const totalBytes = metadata.sampleCount * bytesPerSample;
    const totalChunks = Math.max(1, Math.ceil(totalBytes / this.chunkBytes));

    this.setState({
      status: 'RECONSTRUCTING', progressFraction: 0, currentRowIndex: 0, objects: [], contextAudit: null,
      stage: 'FETCHING_CHUNK', bytesProcessed: 0, totalBytes, chunksProcessed: 0, totalChunks,
      elapsedMs: 0, throughputBytesPerSecond: null, estimatedRemainingMs: null,
    });
    this.callbacks.onReset?.();
    this.startProgressTicker();

    const generator = new OfflineSpectrumGenerator({
      sampleRateSps: metadata.sampleRateSps,
      centerFrequencyHz: metadata.centerFrequencyHz,
      fftSize: this.profile.fftSize,
      hopSize: hopSizeSamples,
      deviceSerial: metadata.deviceSerial ?? undefined,
    });

    const fetchChunk = (startByte: number) => {
      const endByteInclusive = Math.min(startByte + this.chunkBytes, totalBytes) - 1;
      return this.client.fetchIqByteRange(metadata.captureId, startByte, endByteInclusive, this.abortController!.signal);
    };

    try {
      let cursor = 0;
      let chunksProcessed = 0;
      let pendingFetch = totalBytes > 0 ? fetchChunk(cursor) : null;

      while (pendingFetch) {
        let buffer: ArrayBuffer;
        try {
          buffer = await pendingFetch;
        } catch (error) {
          // A pipelined fetch already in flight when cancel() aborts it
          // rejects here -- treated as a clean stop, never surfaced as a
          // reconstruction error. Always awaited (never abandoned) so
          // this rejection is never left unhandled.
          if (this.abortController.signal.aborted) {
            this.stopProgressTicker();
            this.setState({ status: 'READY', stage: 'IDLE' });
            return;
          }
          throw error;
        }

        const nextCursor = cursor + buffer.byteLength;
        // Prefetch the next range immediately -- overlaps its network
        // latency with this chunk's parse/FFT/engine work below.
        pendingFetch = buffer.byteLength > 0 && nextCursor < totalBytes ? fetchChunk(nextCursor) : null;

        this.setState({ stage: 'PARSING_CHUNK' });
        const { re, im } = parse(buffer);

        this.setState({ stage: 'ANALYZING_FRAMES' });
        const nativeFrames = generator.pushChunk(re, im);
        for (const nativeFrame of nativeFrames) {
          const row = this.processNativeFrame(nativeFrame);
          if (row) this.rows.push(row);
        }

        cursor = nextCursor;
        chunksProcessed += 1;
        this.setState({
          totalRows: this.rows.length,
          progressFraction: totalBytes > 0 ? cursor / totalBytes : 1,
          bytesProcessed: cursor,
          chunksProcessed,
          stage: pendingFetch ? 'FETCHING_CHUNK' : 'SEGMENTING',
        });
        this.recomputeTiming();

        if (buffer.byteLength === 0) break; // defensive: never spin forever on a zero-length response
      }

      this.setState({ stage: 'SEGMENTING' });
      const objects = this.requestObjects();
      this.setState({ stage: 'COMPUTING_CONTEXT_AUDIT' });
      const windowDurationSeconds = metadata.sampleCount / metadata.sampleRateSps;
      const contextAudit = computeContextAuditReport(this.rows, objects, windowDurationSeconds, metadata.bandwidthHz);
      this.setState({ stage: 'COMPUTING_HASHES' });
      const profileConfigHash = await computeProfileConfigHash(this.profile);
      const reconstructionId = await computeReconstructionId(metadata.dataSha256, profileConfigHash, this.softwareCommit);

      this.recomputeTiming();
      this.stopProgressTicker();
      this.setState({
        status: 'COMPLETE', objects, contextAudit, reconstructionId, progressFraction: 1,
        currentRowIndex: this.rows.length - 1, stage: 'DONE',
      });
    } catch (error) {
      this.stopProgressTicker();
      this.setState({ status: 'ERROR_LOCAL', error: error instanceof Error ? error.message : String(error), stage: 'IDLE' });
    }
  }

  private processNativeFrame(nativeFrame: NativeResolutionFrame): TerrainProcessedRow | null {
    const validation = validateSpectrumFrame(nativeFrame.spectrumData);
    if (!validation.valid) {
      return null;
    }
    return this.feedFrame(validation.frame);
  }

  // --- Playback (spec §10/§14): visual replay of already-computed rows.
  // Never recomputes anything -- 1x/4x/MAX only change how fast already-
  // deterministic rows are handed to the renderer via onRow, exactly the
  // same values every time regardless of speed.

  play(intervalMs = 100) {
    if (this.playbackTimer || this.rows.length === 0) return;
    this.setState({ status: 'PLAYING' });
    const step = () => {
      if (this.state.currentRowIndex >= this.rows.length) {
        this.pause();
        this.setState({ status: 'COMPLETE' });
        return;
      }
      const row = this.rows[this.state.currentRowIndex];
      this.callbacks.onRow?.(row);
      this.setState({ currentRowIndex: this.state.currentRowIndex + 1 });
      this.playbackTimer = setTimeout(step, intervalMs / this.state.playbackSpeed);
    };
    this.playbackTimer = setTimeout(step, 0);
  }

  pause() {
    if (this.playbackTimer) {
      clearTimeout(this.playbackTimer);
      this.playbackTimer = null;
    }
    if (this.state.status === 'PLAYING') {
      this.setState({ status: 'PAUSED' });
    }
  }

  setPlaybackSpeed(speed: number) {
    this.setState({ playbackSpeed: speed });
  }

  step() {
    if (this.state.currentRowIndex >= this.rows.length) return;
    const row = this.rows[this.state.currentRowIndex];
    this.callbacks.onRow?.(row);
    this.setState({ currentRowIndex: this.state.currentRowIndex + 1, status: 'PAUSED' });
  }

  // Deterministic "jump to time": replays every row from the start up to
  // the target index so the renderer's own incremental state (flow
  // animation, reference ribbons) stays correct -- O(target index), not
  // O(1), an honest tradeoff for reusing RFTerrainCanvas.applyRow()
  // unmodified rather than adding a new bulk-seek renderer method.
  seekToRowIndex(targetIndex: number) {
    this.pause();
    const clamped = Math.max(0, Math.min(targetIndex, this.rows.length - 1));
    this.callbacks.onReset?.();
    for (let i = 0; i <= clamped; i += 1) {
      this.callbacks.onRow?.(this.rows[i]);
    }
    this.setState({ currentRowIndex: clamped + 1, status: 'PAUSED' });
  }

  restart() {
    this.seekToRowIndex(0);
  }

  // Cancellation (spec §33): aborts any in-flight fetch, stops playback,
  // drops the engine instance, resets state -- never affects LIVE.
  cancel() {
    this.abortController?.abort();
    this.pause();
    this.stopProgressTicker();
    this.engine = null;
    this.rows = [];
    this.setState({
      status: 'NO_CAPTURE', captureId: null, metadata: null, error: null, progressFraction: 0,
      totalRows: 0, currentRowIndex: 0, objects: [], contextAudit: null, reconstructionId: null,
      stage: 'IDLE', elapsedMs: 0, bytesProcessed: 0, totalBytes: 0, chunksProcessed: 0, totalChunks: 0,
      throughputBytesPerSecond: null, estimatedRemainingMs: null,
    });
  }

  dispose() {
    this.pause();
    this.abortController?.abort();
    this.stopProgressTicker();
    this.engine = null;
  }
}
