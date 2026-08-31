import type { TerrainObject, TerrainProcessedRow } from '../../model/rfTerrainTypes';
import { RF_TERRAIN_PERSISTENCE_THRESHOLD_DB, RF_TERRAIN_OCCUPANCY_TAU_SECONDS } from '../../model/rfTerrainConstants';

// Spectral Context Audit (spec-adjacent, first version -- "pocas métricas
// y muy claras"): characterizes the ACQUISITION a preserved capture was
// taken in, never the device itself. Every metric here is a real
// aggregation over values the SAME adaptive-baseline/occupancy engines
// (§4 of the technical report) already computed for every row -- no new,
// independent statistic is introduced, and nothing here is fed back into
// the BLE-RFFI classifier (a hard separation kept at the call-site level,
// not by this module alone).
//
// C3 (nearby/adjacent spectral activity relative to a selected burst) and
// the "number of transient events" part of C5 are NOT implemented in this
// pass -- they need a real target/context frequency-band split around a
// specific selection that deserves its own careful design, not a rushed
// approximation. Documented gap, not a silent omission.

const quantile = (sortedAscending: number[], q: number): number => {
  if (sortedAscending.length === 0) return NaN;
  const index = q * (sortedAscending.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sortedAscending[lower];
  const weight = index - lower;
  return sortedAscending[lower] * (1 - weight) + sortedAscending[upper] * weight;
};

const mean = (values: number[]): number => (values.length === 0 ? NaN : values.reduce((a, b) => a + b, 0) / values.length);

const standardDeviation = (values: number[]): number => {
  if (values.length < 2) return 0;
  const m = mean(values);
  const variance = values.reduce((sum, v) => sum + (v - m) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
};

// C1 -- Local spectral baseline: distribution of the already-estimated
// per-bin noise floor across the observed window. Reports the median and
// interquartile range across every (row, bin) sample in the window, plus
// how much the ROW-level median baseline moves over time (temporal
// variability) -- never a single global number standing in for a
// genuinely time-varying quantity.
export interface ContextBaselineMetrics {
  medianBaselineDb: number;
  iqrBaselineDb: number;
  temporalVariabilityDb: number;
  sampleCount: number;
}

export const computeContextBaselineMetrics = (rows: TerrainProcessedRow[]): ContextBaselineMetrics => {
  const allValues: number[] = [];
  const perRowMedian: number[] = [];
  for (const row of rows) {
    const sorted = [...row.noiseFloorDb].sort((a, b) => a - b);
    if (sorted.length > 0) perRowMedian.push(quantile(sorted, 0.5));
    allValues.push(...row.noiseFloorDb);
  }
  const sortedAll = [...allValues].sort((a, b) => a - b);
  return {
    medianBaselineDb: quantile(sortedAll, 0.5),
    iqrBaselineDb: quantile(sortedAll, 0.75) - quantile(sortedAll, 0.25),
    temporalVariabilityDb: standardDeviation(perRowMedian),
    sampleCount: allValues.length,
  };
};

// C2 -- Spectral occupancy: mean of the already-computed real-Δt-weighted
// occupancy signal (engine/occupancyEngine.ts) across the window, plus how
// much it moves over time. The estimator/threshold/time-constant are
// reported alongside the number -- never presented as a bare probability
// with no stated method (spec's own "no presentarlo como una probabilidad
// física" instruction).
export interface ContextOccupancyMetrics {
  meanOccupancy: number;
  temporalVariability: number;
  estimator: 'exponential-decay';
  thresholdDb: number;
  tauSeconds: number;
  sampleCount: number;
}

export const computeContextOccupancyMetrics = (rows: TerrainProcessedRow[]): ContextOccupancyMetrics => {
  const allValues: number[] = [];
  const perRowMean: number[] = [];
  for (const row of rows) {
    if (row.occupancy.length > 0) perRowMean.push(mean(row.occupancy));
    allValues.push(...row.occupancy);
  }
  return {
    meanOccupancy: mean(allValues),
    temporalVariability: standardDeviation(perRowMean),
    estimator: 'exponential-decay',
    thresholdDb: RF_TERRAIN_PERSISTENCE_THRESHOLD_DB,
    tauSeconds: RF_TERRAIN_OCCUPANCY_TAU_SECONDS,
    sampleCount: allValues.length,
  };
};

// C4 -- Context object density: how many distinct terrain objects were
// segmented per second (and, separately, per Hz of observed bandwidth) in
// the window -- a real, already-computed count divided by a real,
// already-measured duration/bandwidth, not a new detector.
export interface ContextObjectDensityMetrics {
  objectsPerSecond: number;
  objectsPerMHz: number;
  objectCount: number;
  windowDurationSeconds: number;
  windowBandwidthHz: number;
}

export const computeContextObjectDensityMetrics = (
  objects: TerrainObject[],
  windowDurationSeconds: number,
  windowBandwidthHz: number,
): ContextObjectDensityMetrics => ({
  objectsPerSecond: windowDurationSeconds > 0 ? objects.length / windowDurationSeconds : NaN,
  objectsPerMHz: windowBandwidthHz > 0 ? objects.length / (windowBandwidthHz / 1e6) : NaN,
  objectCount: objects.length,
  windowDurationSeconds,
  windowBandwidthHz,
});

export interface ContextAuditReport {
  baseline: ContextBaselineMetrics;
  occupancy: ContextOccupancyMetrics;
  objectDensity: ContextObjectDensityMetrics;
}

export const computeContextAuditReport = (
  rows: TerrainProcessedRow[],
  objects: TerrainObject[],
  windowDurationSeconds: number,
  windowBandwidthHz: number,
): ContextAuditReport => ({
  baseline: computeContextBaselineMetrics(rows),
  occupancy: computeContextOccupancyMetrics(rows),
  objectDensity: computeContextObjectDensityMetrics(objects, windowDurationSeconds, windowBandwidthHz),
});
