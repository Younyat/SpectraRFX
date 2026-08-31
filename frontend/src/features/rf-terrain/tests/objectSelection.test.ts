import { describe, expect, it } from 'vitest';
import { findObjectAtPoint } from '../engine/objectSelection';
import type { TerrainObject } from '../model/rfTerrainTypes';

const makeObject = (overrides: Partial<TerrainObject>): TerrainObject => ({
  id: 'obj-1',
  trackId: 'RF-TRACK-000001',
  morphology: 'RIDGE',
  active: true,
  startTimeSeconds: 0,
  endTimeSeconds: 1,
  durationSeconds: 1,
  startFrequencyHz: 2_400_000_000,
  stopFrequencyHz: 2_410_000_000,
  centerFrequencyHz: 2_405_000_000,
  bandwidthHz: 10_000_000,
  peakExcessDb: 20,
  meanExcessDb: 15,
  frequencyCentroidHz: 2_405_000_000,
  temporalCentroidSeconds: 0.5,
  terrainVolumeIndex: 1,
  ridgeSlopeHzPerSecond: null,
  cellCount: 10,
  ...overrides,
});

describe('findObjectAtPoint', () => {
  it('finds the object whose bounding box contains the point', () => {
    const object = makeObject({});
    expect(findObjectAtPoint([object], 2_405_000_000, 0.5)?.id).toBe('obj-1');
  });

  it('returns null for a point outside every bounding box (point selection fallback)', () => {
    const object = makeObject({});
    expect(findObjectAtPoint([object], 2_500_000_000, 0.5)).toBeNull();
    expect(findObjectAtPoint([object], 2_405_000_000, 5)).toBeNull();
  });

  it('treats the exact boundary as inside (inclusive)', () => {
    const object = makeObject({});
    expect(findObjectAtPoint([object], object.startFrequencyHz, object.startTimeSeconds)?.id).toBe('obj-1');
    expect(findObjectAtPoint([object], object.stopFrequencyHz, object.endTimeSeconds)?.id).toBe('obj-1');
  });

  it('when two boxes overlap, prefers the one that started more recently', () => {
    const older = makeObject({ id: 'older', startTimeSeconds: 0, endTimeSeconds: 2 });
    const newer = makeObject({ id: 'newer', startTimeSeconds: 1, endTimeSeconds: 3 });
    expect(findObjectAtPoint([older, newer], 2_405_000_000, 1.5)?.id).toBe('newer');
  });

  it('returns null for an empty object list', () => {
    expect(findObjectAtPoint([], 2_405_000_000, 0.5)).toBeNull();
  });
});
