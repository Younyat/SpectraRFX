import { createRingBuffer, RingBuffer } from './ringBuffer';
import { createNoiseEstimator } from './noiseEstimator';
import { createPersistenceEngine } from './persistenceEngine';
import { createOccupancyEngine } from './occupancyEngine';
import { createHoldEngine } from './holdEngine';
import { createAverageEngine } from './averageEngine';
import { createEwmaEngine } from './ewmaEngine';
import { createPercentileEngine } from './percentileEngine';
import { segmentExcessMatrix } from './terrainSegmentation';
import { buildTerrainObject } from './terrainMetrics';
import { createObjectTracker } from './objectTracker';
import {
  RF_TERRAIN_DEFAULT_FREQUENCY_BINS,
  RF_TERRAIN_NOISE_QUANTILE,
  RF_TERRAIN_NOISE_WINDOW_SECONDS,
  RF_TERRAIN_NOISE_SMOOTHING_BETA,
  RF_TERRAIN_PERSISTENCE_THRESHOLD_DB,
  RF_TERRAIN_PERSISTENCE_TAU_SECONDS,
  RF_TERRAIN_OCCUPANCY_TAU_SECONDS,
  RF_TERRAIN_MAX_EXCESS_DB,
  RF_TERRAIN_POLL_INTERVAL_MS,
  RF_TERRAIN_SEGMENTATION_SEED_THRESHOLD_DB,
  RF_TERRAIN_SEGMENTATION_GROW_THRESHOLD_DB,
  RF_TERRAIN_SEGMENTATION_MIN_CELL_COUNT,
} from '../model/rfTerrainConstants';
import type { TerrainWorkerInput, TerrainWorkerOutput, TerrainProcessedRow } from '../model/rfTerrainTypes';

interface ExcessHistoryRow {
  excess: Float32Array;
  timestampSeconds: number;
  frequencyHz: Float32Array;
}

// Pure reducer over TerrainWorkerInput -> TerrainWorkerOutput[]. Owns every
// ARST accumulator (spec §11: noise floor, persistence, occupancy, holds,
// average, history, segmentation) so terrain.worker.ts stays a thin
// postMessage wrapper and unit tests can drive this directly without a
// real Worker (unavailable under jsdom).
export const createTerrainWorkerState = (bins: number = RF_TERRAIN_DEFAULT_FREQUENCY_BINS) => {
  const windowSamples = Math.max(3, Math.round((RF_TERRAIN_NOISE_WINDOW_SECONDS * 1000) / RF_TERRAIN_POLL_INTERVAL_MS));

  let generation = 0;
  let buffer: RingBuffer<TerrainProcessedRow> | null = null;
  let excessHistory: RingBuffer<ExcessHistoryRow> | null = null;
  let lastTimestamp: number | null = null;

  const noiseEstimator = createNoiseEstimator({ bins, quantile: RF_TERRAIN_NOISE_QUANTILE, windowSamples, smoothingBeta: RF_TERRAIN_NOISE_SMOOTHING_BETA });
  const persistenceEngine = createPersistenceEngine({ bins, thresholdDb: RF_TERRAIN_PERSISTENCE_THRESHOLD_DB, tauSeconds: RF_TERRAIN_PERSISTENCE_TAU_SECONDS });
  const occupancyEngine = createOccupancyEngine({ bins, thresholdDb: RF_TERRAIN_PERSISTENCE_THRESHOLD_DB, tauSeconds: RF_TERRAIN_OCCUPANCY_TAU_SECONDS });
  const holdEngine = createHoldEngine(bins);
  const averageEngine = createAverageEngine(bins, 0.2);
  const ewmaEngine = createEwmaEngine(bins, 0.3);
  const percentileEngine = createPercentileEngine(bins, windowSamples);
  const objectTracker = createObjectTracker();

  const handle = (input: TerrainWorkerInput): TerrainWorkerOutput[] => {
    try {
      if (input.type === 'RESET') {
        generation = input.generation;
        buffer = createRingBuffer<TerrainProcessedRow>(input.capacity);
        excessHistory = createRingBuffer<ExcessHistoryRow>(input.capacity);
        lastTimestamp = null;
        noiseEstimator.reset();
        persistenceEngine.reset();
        occupancyEngine.reset();
        holdEngine.reset();
        averageEngine.reset();
        ewmaEngine.reset();
        percentileEngine.reset();
        objectTracker.reset();
        return [];
      }

      if (input.type === 'SEGMENT') {
        if (input.generation !== generation || !excessHistory || excessHistory.size < 2) {
          return [];
        }
        const rows = excessHistory.toChronologicalArray();
        const timestamps = rows.map((row) => row.timestampSeconds);
        const latestFrequencyHz = rows[rows.length - 1].frequencyHz;
        const deltaFHz = latestFrequencyHz.length > 1 ? Math.abs(latestFrequencyHz[1] - latestFrequencyHz[0]) : 0;
        const deltaTSeconds = timestamps.length > 1
          ? Math.abs(timestamps[timestamps.length - 1] - timestamps[0]) / (timestamps.length - 1)
          : 0;

        const { components } = segmentExcessMatrix(
          rows.map((row) => row.excess),
          RF_TERRAIN_SEGMENTATION_SEED_THRESHOLD_DB,
          RF_TERRAIN_SEGMENTATION_GROW_THRESHOLD_DB,
          { minCellCount: RF_TERRAIN_SEGMENTATION_MIN_CELL_COUNT },
        );
        const freshObjects = components.map((component, index) =>
          buildTerrainObject(`obj-${generation}-${index}`, component, latestFrequencyHz, timestamps, deltaFHz, deltaTSeconds));
        // Assigns stable trackId/active/HOPPING_CLUSTER-override across
        // this and previous SEGMENT passes (engine/objectTracker.ts) --
        // `id` above stays a fresh per-pass label, `trackId` is the one
        // that persists while the same emission keeps being re-detected.
        const objects = objectTracker.assignTracks(freshObjects);
        return [{ type: 'OBJECTS', generation, objects }];
      }

      // FRAME
      if (input.generation !== generation || !buffer || !excessHistory) {
        // Stale message from a superseded acquisition generation -- discard (spec §12).
        return [];
      }

      const powerLevelsDb = Float32Array.from(input.frame.powerLevels);
      const deltaTimeSeconds = lastTimestamp === null
        ? RF_TERRAIN_POLL_INTERVAL_MS / 1000
        : Math.max(0.001, (input.frame.timestamp - lastTimestamp) / 1000);
      lastTimestamp = input.frame.timestamp;

      const noiseFloorDb = noiseEstimator.update(powerLevelsDb);
      const excessDb = new Float32Array(bins);
      for (let i = 0; i < bins; i += 1) {
        excessDb[i] = Math.min(RF_TERRAIN_MAX_EXCESS_DB, Math.max(0, powerLevelsDb[i] - noiseFloorDb[i]));
      }
      const persistence = persistenceEngine.update(excessDb, deltaTimeSeconds);
      const occupancy = occupancyEngine.update(excessDb, deltaTimeSeconds);
      const { maxHold, minHold } = holdEngine.update(powerLevelsDb);
      const averageDb = averageEngine.update(powerLevelsDb);
      const ewmaDb = ewmaEngine.update(powerLevelsDb);
      const percentiles = percentileEngine.update(powerLevelsDb);

      const row: TerrainProcessedRow = {
        frame: input.frame,
        noiseFloorDb: Array.from(noiseFloorDb),
        excessDb: Array.from(excessDb),
        persistence: Array.from(persistence),
        occupancy: Array.from(occupancy),
        maxHoldDb: Array.from(maxHold),
        minHoldDb: Array.from(minHold),
        averageDb: Array.from(averageDb),
        ewmaDb: Array.from(ewmaDb),
        p50Db: Array.from(percentiles.p50),
        p90Db: Array.from(percentiles.p90),
        p95Db: Array.from(percentiles.p95),
        p99Db: Array.from(percentiles.p99),
      };
      buffer.push(row);
      excessHistory.push({
        excess: Float32Array.from(excessDb),
        timestampSeconds: input.frame.timestamp / 1000,
        frequencyHz: Float32Array.from(input.frame.frequencyArray),
      });

      return [{
        type: 'ROW',
        generation,
        rowIndex: buffer.size - 1,
        bufferSize: buffer.size,
        bufferCapacity: buffer.capacity,
        row,
      }];
    } catch (error) {
      return [{
        type: 'ERROR',
        recoverable: true,
        code: 'TERRAIN_WORKER_STATE_EXCEPTION',
        message: error instanceof Error ? error.message : String(error),
      }];
    }
  };

  return { handle };
};
