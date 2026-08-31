import { describe, expect, it } from 'vitest';
import { pickTraceValues } from '../engine/traceSource';
import type { TerrainProcessedRow } from '../model/rfTerrainTypes';

const makeRow = (): TerrainProcessedRow => ({
  frame: {
    generation: 1,
    timestamp: 0,
    centerFrequency: 2_440_000_000,
    span: 40_000_000,
    frequencyArray: [1, 2, 3],
    powerLevels: [-10, -10, -10],
  },
  noiseFloorDb: [-90, -90, -90],
  excessDb: [80, 80, 80],
  persistence: [0.5, 0.5, 0.5],
  occupancy: [0.5, 0.5, 0.5],
  maxHoldDb: [-20, -20, -20],
  minHoldDb: [-30, -30, -30],
  averageDb: [-40, -40, -40],
  ewmaDb: [-50, -50, -50],
  p50Db: [-60, -60, -60],
  p90Db: [-70, -70, -70],
  p95Db: [-80, -80, -80],
  p99Db: [-90, -90, -90],
});

describe('pickTraceValues', () => {
  it('returns the live per-bin power levels for "live"', () => {
    expect(pickTraceValues(makeRow(), 'live')).toEqual([-10, -10, -10]);
  });

  it('returns maxHoldDb for "maxHold"', () => {
    expect(pickTraceValues(makeRow(), 'maxHold')).toEqual([-20, -20, -20]);
  });

  it('returns minHoldDb for "minHold"', () => {
    expect(pickTraceValues(makeRow(), 'minHold')).toEqual([-30, -30, -30]);
  });

  it('returns averageDb for "average"', () => {
    expect(pickTraceValues(makeRow(), 'average')).toEqual([-40, -40, -40]);
  });

  it('returns ewmaDb for "ewma"', () => {
    expect(pickTraceValues(makeRow(), 'ewma')).toEqual([-50, -50, -50]);
  });

  it('returns the matching percentile array for p50/p90/p95/p99', () => {
    const row = makeRow();
    expect(pickTraceValues(row, 'p50')).toEqual(row.p50Db);
    expect(pickTraceValues(row, 'p90')).toEqual(row.p90Db);
    expect(pickTraceValues(row, 'p95')).toEqual(row.p95Db);
    expect(pickTraceValues(row, 'p99')).toEqual(row.p99Db);
  });

  it('never returns a fabricated array -- always one of the real per-row fields, by reference', () => {
    const row = makeRow();
    expect(pickTraceValues(row, 'maxHold')).toBe(row.maxHoldDb);
    expect(pickTraceValues(row, 'live')).toBe(row.frame.powerLevels);
  });
});
