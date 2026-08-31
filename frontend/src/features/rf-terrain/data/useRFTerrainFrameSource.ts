import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiService } from '../../../app/services/ApiService';
import { useDeviceStatus } from '../../../app/store/AppStore';
import { validateSpectrumFrame } from './frameValidator';
import { createAcquisitionEpochTracker } from './acquisitionEpoch';
import { adaptSpectrumFrame } from './spectrumFrameAdapter';
import { RF_TERRAIN_DEFAULT_HISTORY_ROWS, RF_TERRAIN_POLL_INTERVAL_MS } from '../model/rfTerrainConstants';
import type {
  RFTerrainFrameSourceDiagnostics,
  TerrainInputFrame,
  TerrainObject,
  TerrainProcessedRow,
  TerrainWorkerOutput,
} from '../model/rfTerrainTypes';

const apiService = new ApiService();
const SEGMENT_INTERVAL_MS = 2000;

const initialDiagnostics = (state: RFTerrainFrameSourceDiagnostics['state']): RFTerrainFrameSourceDiagnostics => ({
  state,
  generation: 0,
  framesReceived: 0,
  invalidFrames: 0,
  droppedProcessingFrames: 0,
  ringBufferSize: 0,
  ringBufferCapacity: RF_TERRAIN_DEFAULT_HISTORY_ROWS,
  lastFrameTimestamp: null,
  lastError: null,
});

export interface UseRFTerrainFrameSourceOptions {
  enabled?: boolean;
  frozen?: boolean;
  onRow?: (row: TerrainProcessedRow, meta: { generation: number; rowIndex: number; bufferSize: number; bufferCapacity: number }) => void;
  onObjects?: (objects: TerrainObject[]) => void;
  onReset?: () => void;
}

// Deliberately does NOT call useSpectrum()/useWaterfall() (spec §9): its
// own single poller, its own AbortController, its own Web Worker. Reads
// only the shared, lightweight `deviceStatus` slice of AppStore -- never
// writes RF Terrain history back into it (spec §61-62).
export const useRFTerrainFrameSource = (options: UseRFTerrainFrameSourceOptions = {}) => {
  const { enabled = true } = options;
  const deviceStatus = useDeviceStatus();
  const [diagnostics, setDiagnostics] = useState<RFTerrainFrameSourceDiagnostics>(() =>
    initialDiagnostics(enabled ? 'WAITING_FOR_DEVICE' : 'DISABLED'),
  );

  // Latest-callback refs: toggling frozen/objectsEnabled or passing a new
  // inline callback must never tear down and recreate the worker/poller.
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const epochRef = useRef(createAcquisitionEpochTracker());
  const workerRef = useRef<Worker | null>(null);
  const pendingFrameRef = useRef<TerrainInputFrame | null>(null);
  const frameInFlightToWorkerRef = useRef(false);

  const resetTerrain = useCallback(() => {
    const worker = workerRef.current;
    const generation = epochRef.current.generation;
    if (!worker || generation === 0) {
      return;
    }
    pendingFrameRef.current = null;
    frameInFlightToWorkerRef.current = false;
    worker.postMessage({ type: 'RESET', generation, capacity: RF_TERRAIN_DEFAULT_HISTORY_ROWS });
    setDiagnostics((prev) => ({ ...prev, ringBufferSize: 0 }));
    optionsRef.current.onReset?.();
  }, []);

  // Worker lifecycle: one worker per mount while enabled, terminated on
  // unmount/disable -- zero orphan workers across route changes (spec §92).
  useEffect(() => {
    if (!enabled) {
      setDiagnostics(initialDiagnostics('DISABLED'));
      return;
    }

    if (typeof Worker === 'undefined') {
      setDiagnostics((prev) => ({ ...prev, state: 'ERROR_LOCAL', lastError: 'Web Worker unavailable in this browser' }));
      return;
    }

    let worker: Worker;
    try {
      worker = new Worker(new URL('../engine/terrain.worker.ts', import.meta.url), { type: 'module' });
    } catch (error) {
      setDiagnostics((prev) => ({ ...prev, state: 'ERROR_LOCAL', lastError: error instanceof Error ? error.message : 'Worker failed to start' }));
      return;
    }

    workerRef.current = worker;

    worker.onmessage = (event: MessageEvent<TerrainWorkerOutput>) => {
      const output = event.data;
      if (output.type === 'ROW') {
        if (output.generation !== epochRef.current.generation) {
          // Stale response from a superseded acquisition generation -- discard (spec §12).
          return;
        }
        frameInFlightToWorkerRef.current = false;
        setDiagnostics((prev) => ({ ...prev, ringBufferSize: output.bufferSize, ringBufferCapacity: output.bufferCapacity, state: 'STREAMING' }));
        optionsRef.current.onRow?.(output.row, { generation: output.generation, rowIndex: output.rowIndex, bufferSize: output.bufferSize, bufferCapacity: output.bufferCapacity });

        const pending = pendingFrameRef.current;
        if (pending && pending.generation === epochRef.current.generation) {
          pendingFrameRef.current = null;
          frameInFlightToWorkerRef.current = true;
          worker.postMessage({ type: 'FRAME', generation: pending.generation, frame: pending });
        }
      } else if (output.type === 'OBJECTS') {
        if (output.generation === epochRef.current.generation) {
          optionsRef.current.onObjects?.(output.objects);
        }
      } else if (output.type === 'ERROR') {
        setDiagnostics((prev) => ({ ...prev, lastError: `${output.code}: ${output.message}` }));
      }
    };

    worker.onerror = (event: ErrorEvent) => {
      setDiagnostics((prev) => ({ ...prev, state: 'ERROR_LOCAL', lastError: event.message || 'Terrain worker error' }));
    };

    return () => {
      worker.terminate();
      workerRef.current = null;
    };
  }, [enabled]);

  // Independent, slower rate domain for object segmentation (spec §57) --
  // decoupled from the ~10Hz frame cadence. Runs whenever the terrain is
  // streaming and not frozen, REGARDLESS of `objectsEnabled` -- selection
  // (click-to-inspect a terrain object) must keep working even while the
  // operator has the objects overlay/list hidden; `objectsEnabled` only
  // ever gated the DISPLAY, and gating the underlying computation on it
  // too meant a hidden overlay silently broke selection.
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const timer = setInterval(() => {
      if (optionsRef.current.frozen) {
        return;
      }
      workerRef.current?.postMessage({ type: 'SEGMENT', generation: epochRef.current.generation });
    }, SEGMENT_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [enabled]);

  // Single frame producer (spec §9): recursive setTimeout, never
  // setInterval, never more than one /api/spectrum/live request in flight.
  useEffect(() => {
    if (!enabled) {
      return;
    }

    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const sendFrameToWorker = (frame: TerrainInputFrame) => {
      const worker = workerRef.current;
      if (!worker) {
        return;
      }
      if (frameInFlightToWorkerRef.current) {
        // Backpressure, "latest wins" (spec §10): at most one frame
        // processing plus one pending -- a newer frame replaces whatever
        // was already waiting, never an unbounded queue.
        const hadPending = pendingFrameRef.current !== null;
        pendingFrameRef.current = frame;
        if (hadPending) {
          setDiagnostics((prev) => ({ ...prev, droppedProcessingFrames: prev.droppedProcessingFrames + 1 }));
        }
        return;
      }
      frameInFlightToWorkerRef.current = true;
      worker.postMessage({ type: 'FRAME', generation: frame.generation, frame });
    };

    const poll = async () => {
      if (!active) {
        return;
      }

      if (!deviceStatus.isConnected) {
        setDiagnostics((prev) => (prev.state === 'ERROR_LOCAL' ? prev : { ...prev, state: 'WAITING_FOR_DEVICE' }));
      } else {
        controller = new AbortController();
        try {
          const raw = await apiService.getLiveSpectrum(controller.signal);
          if (!active) {
            return;
          }
          const validation = validateSpectrumFrame(raw);
          if (!validation.valid) {
            setDiagnostics((prev) => ({ ...prev, invalidFrames: prev.invalidFrames + 1, lastError: validation.reason }));
          } else {
            const epoch = epochRef.current.update(validation.frame);
            if (epoch.changed) {
              // Acquisition-meaning change (spec §12): clear everything
              // downstream rather than mix two configurations in one terrain.
              pendingFrameRef.current = null;
              frameInFlightToWorkerRef.current = false;
              workerRef.current?.postMessage({ type: 'RESET', generation: epoch.generation, capacity: RF_TERRAIN_DEFAULT_HISTORY_ROWS });
              setDiagnostics((prev) => ({ ...prev, generation: epoch.generation, ringBufferSize: 0 }));
              optionsRef.current.onReset?.();
            }

            const terrainFrame = adaptSpectrumFrame(validation.frame, epoch.generation);
            setDiagnostics((prev) => ({
              ...prev,
              framesReceived: prev.framesReceived + 1,
              lastFrameTimestamp: terrainFrame.timestamp,
              state: prev.state === 'STREAMING' || prev.state === 'ERROR_LOCAL' ? prev.state : 'WAITING_FOR_FRAME',
            }));

            // Freeze (spec §42): data stops evolving, UI (camera, inspector,
            // cross-sections) keeps working off the last accepted snapshot.
            if (!optionsRef.current.frozen) {
              sendFrameToWorker(terrainFrame);
            }
          }
        } catch (error) {
          if (active && !(error instanceof DOMException && error.name === 'AbortError')) {
            setDiagnostics((prev) => ({ ...prev, lastError: error instanceof Error ? error.message : 'Failed to fetch live spectrum' }));
          }
        }
      }

      if (active) {
        timer = setTimeout(poll, RF_TERRAIN_POLL_INTERVAL_MS);
      }
    };

    poll();

    return () => {
      active = false;
      if (timer) {
        clearTimeout(timer);
      }
      controller?.abort();
    };
  }, [enabled, deviceStatus.isConnected]);

  return { diagnostics, resetTerrain };
};
