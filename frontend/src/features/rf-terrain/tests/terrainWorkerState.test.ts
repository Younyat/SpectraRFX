import { describe, expect, it } from 'vitest';
import { createTerrainWorkerState } from '../engine/terrainWorkerState';
import type { TerrainInputFrame } from '../model/rfTerrainTypes';

const BINS = 4;

const frame = (generation: number, timestamp: number, powerLevels = [-90, -90, -90, -90]): TerrainInputFrame => ({
  generation,
  timestamp,
  centerFrequency: 2_440_000_000,
  span: 40_000_000,
  frequencyArray: [2_420_000_000, 2_430_000_000, 2_440_000_000, 2_450_000_000],
  powerLevels,
});

describe('createTerrainWorkerState', () => {
  it('produces no output for a FRAME received before any RESET', () => {
    const state = createTerrainWorkerState(BINS);
    expect(state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100) })).toEqual([]);
  });

  it('buffers a FRAME matching the current generation and reports buffer growth', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 1, capacity: 4 });
    const outputs = state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100) });
    expect(outputs).toHaveLength(1);
    expect(outputs[0]).toMatchObject({ type: 'ROW', generation: 1, rowIndex: 0, bufferSize: 1, bufferCapacity: 4 });
    const row = (outputs[0] as { row: { noiseFloorDb: number[]; excessDb: number[] } }).row;
    expect(row.noiseFloorDb).toHaveLength(BINS);
    expect(row.excessDb).toHaveLength(BINS);
  });

  it('discards a FRAME tagged with a stale (superseded) generation', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 2, capacity: 4 });
    expect(state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100) })).toEqual([]);
  });

  it('RESET clears prior buffered rows -- the next FRAME starts again at rowIndex 0', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 1, capacity: 4 });
    state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100) });
    state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 200) });
    state.handle({ type: 'RESET', generation: 2, capacity: 4 });
    const outputs = state.handle({ type: 'FRAME', generation: 2, frame: frame(2, 300) });
    expect(outputs[0]).toMatchObject({ type: 'ROW', generation: 2, rowIndex: 0, bufferSize: 1 });
  });

  it('never exceeds the declared capacity, wrapping instead of growing', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 1, capacity: 2 });
    state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100) });
    state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 200) });
    const outputs = state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 300) });
    expect(outputs[0]).toMatchObject({ bufferSize: 2, bufferCapacity: 2 });
  });

  it('RESET also clears the noise/persistence/occupancy/hold/average engines, not just the ring buffer', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 1, capacity: 10 });
    // Push a strong, active signal so holds/persistence build up.
    for (let i = 0; i < 10; i += 1) {
      state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100 + i * 100, [-20, -20, -20, -20]) });
    }
    state.handle({ type: 'RESET', generation: 2, capacity: 10 });
    const outputs = state.handle({ type: 'FRAME', generation: 2, frame: frame(2, 100, [-90, -90, -90, -90]) });
    const row = (outputs[0] as { row: { maxHoldDb: number[]; persistence: number[] } }).row;
    // A fresh engine sees -90 as both the first sample and the max hold --
    // if state had leaked across RESET, maxHold would still show -20.
    expect(row.maxHoldDb[0]).toBeCloseTo(-90, 5);
    expect(row.persistence[0]).toBeLessThan(0.5);
  });

  it('SEGMENT produces no output before any history exists', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 1, capacity: 10 });
    expect(state.handle({ type: 'SEGMENT', generation: 1 })).toEqual([]);
  });

  it('SEGMENT emits an OBJECTS message once a strong, sustained signal has built up history', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 1, capacity: 20 });
    for (let i = 0; i < 10; i += 1) {
      state.handle({ type: 'FRAME', generation: 1, frame: frame(1, 100 + i * 100, [-90, -20, -90, -90]) });
    }
    const outputs = state.handle({ type: 'SEGMENT', generation: 1 });
    expect(outputs).toHaveLength(1);
    expect(outputs[0].type).toBe('OBJECTS');
  });

  it('a SEGMENT tagged with a stale generation is discarded', () => {
    const state = createTerrainWorkerState(BINS);
    state.handle({ type: 'RESET', generation: 2, capacity: 10 });
    expect(state.handle({ type: 'SEGMENT', generation: 1 })).toEqual([]);
  });
});
