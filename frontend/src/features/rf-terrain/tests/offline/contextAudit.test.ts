import { describe, expect, it } from 'vitest';
import {
  computeContextBaselineMetrics,
  computeContextOccupancyMetrics,
  computeContextObjectDensityMetrics,
  computeContextAuditReport,
} from '../../engine/offline/contextAudit';
import type { TerrainObject, TerrainProcessedRow } from '../../model/rfTerrainTypes';

const makeRow = (noiseFloorDb: number[], occupancy: number[]): TerrainProcessedRow => ({
  frame: {
    generation: 1,
    timestamp: 0,
    centerFrequency: 2_440_000_000,
    span: 4_000_000,
    frequencyArray: noiseFloorDb.map((_, i) => i),
    powerLevels: noiseFloorDb.map(() => -50),
  },
  noiseFloorDb,
  excessDb: noiseFloorDb.map(() => 0),
  persistence: occupancy,
  occupancy,
  maxHoldDb: noiseFloorDb,
  minHoldDb: noiseFloorDb,
  averageDb: noiseFloorDb,
  ewmaDb: noiseFloorDb,
  p50Db: noiseFloorDb,
  p90Db: noiseFloorDb,
  p95Db: noiseFloorDb,
  p99Db: noiseFloorDb,
});

const makeObject = (overrides: Partial<TerrainObject> = {}): TerrainObject => ({
  id: 'obj-1',
  trackId: 'RF-TRACK-000001',
  morphology: 'RIDGE',
  active: true,
  startTimeSeconds: 0,
  endTimeSeconds: 1,
  durationSeconds: 1,
  startFrequencyHz: 2_400_000_000,
  stopFrequencyHz: 2_401_000_000,
  centerFrequencyHz: 2_400_500_000,
  bandwidthHz: 1_000_000,
  peakExcessDb: 20,
  meanExcessDb: 15,
  frequencyCentroidHz: 2_400_500_000,
  temporalCentroidSeconds: 0.5,
  terrainVolumeIndex: 1,
  ridgeSlopeHzPerSecond: null,
  cellCount: 10,
  ...overrides,
});

describe('computeContextBaselineMetrics (C1)', () => {
  it('computes median/IQR over every real per-bin noise-floor value in the window', () => {
    const rows = [makeRow([-90, -90, -90, -90], [0, 0, 0, 0]), makeRow([-80, -80, -80, -80], [0, 0, 0, 0])];
    const metrics = computeContextBaselineMetrics(rows);
    expect(metrics.sampleCount).toBe(8);
    expect(metrics.medianBaselineDb).toBeCloseTo(-85, 5);
  });

  it('reports zero temporal variability when the baseline never changes row to row', () => {
    const rows = [makeRow([-90, -90], [0, 0]), makeRow([-90, -90], [0, 0]), makeRow([-90, -90], [0, 0])];
    const metrics = computeContextBaselineMetrics(rows);
    expect(metrics.temporalVariabilityDb).toBeCloseTo(0, 6);
  });

  it('reports nonzero temporal variability when the baseline genuinely moves over time', () => {
    const rows = [makeRow([-90], [0]), makeRow([-70], [0]), makeRow([-50], [0])];
    const metrics = computeContextBaselineMetrics(rows);
    expect(metrics.temporalVariabilityDb).toBeGreaterThan(0);
  });

  it('handles an empty row list without throwing', () => {
    const metrics = computeContextBaselineMetrics([]);
    expect(metrics.sampleCount).toBe(0);
  });
});

describe('computeContextOccupancyMetrics (C2)', () => {
  it('reports the real estimator/threshold/time-constant alongside the number, never a bare probability', () => {
    const rows = [makeRow([-90], [0.4]), makeRow([-90], [0.6])];
    const metrics = computeContextOccupancyMetrics(rows);
    expect(metrics.estimator).toBe('exponential-decay');
    expect(Number.isFinite(metrics.thresholdDb)).toBe(true);
    expect(Number.isFinite(metrics.tauSeconds)).toBe(true);
    expect(metrics.meanOccupancy).toBeCloseTo(0.5, 5);
  });
});

describe('computeContextObjectDensityMetrics (C4)', () => {
  it('divides a real object count by a real duration/bandwidth, never invents a detector', () => {
    const objects = [makeObject({ id: 'a' }), makeObject({ id: 'b' }), makeObject({ id: 'c' })];
    const metrics = computeContextObjectDensityMetrics(objects, 3, 2_000_000);
    expect(metrics.objectCount).toBe(3);
    expect(metrics.objectsPerSecond).toBeCloseTo(1, 5);
    expect(metrics.objectsPerMHz).toBeCloseTo(1.5, 5);
  });

  it('returns NaN (not a fabricated zero) for a zero-duration or zero-bandwidth window', () => {
    const metrics = computeContextObjectDensityMetrics([makeObject()], 0, 0);
    expect(Number.isNaN(metrics.objectsPerSecond)).toBe(true);
    expect(Number.isNaN(metrics.objectsPerMHz)).toBe(true);
  });
});

describe('computeContextAuditReport', () => {
  it('composes all three real metric groups without recomputing anything independently', () => {
    const rows = [makeRow([-90, -85], [0.2, 0.3])];
    const objects = [makeObject()];
    const report = computeContextAuditReport(rows, objects, 1, 1_000_000);
    expect(report.baseline.sampleCount).toBe(2);
    expect(report.occupancy.sampleCount).toBe(2);
    expect(report.objectDensity.objectCount).toBe(1);
  });
});
