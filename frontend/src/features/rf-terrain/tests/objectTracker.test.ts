import { describe, expect, it } from 'vitest';
import { createObjectTracker } from '../engine/objectTracker';
import type { TerrainObject } from '../model/rfTerrainTypes';

const makeObject = (overrides: Partial<TerrainObject>): TerrainObject => ({
  id: 'obj-fresh',
  trackId: '',
  morphology: 'RIDGE',
  active: false,
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

describe('createObjectTracker', () => {
  it('assigns a fresh, stable-looking trackId to a brand-new object', () => {
    const tracker = createObjectTracker();
    const [tracked] = tracker.assignTracks([makeObject({})]);
    expect(tracked.trackId).toMatch(/^RF-TRACK-\d{6}$/);
  });

  it('keeps the same trackId across passes for a persisting emission (overlapping frequency range)', () => {
    const tracker = createObjectTracker();
    const [first] = tracker.assignTracks([makeObject({ startTimeSeconds: 0, endTimeSeconds: 2 })]);
    const [second] = tracker.assignTracks([makeObject({ startTimeSeconds: 0, endTimeSeconds: 4 })]);
    expect(second.trackId).toBe(first.trackId);
  });

  it('gives an object at an unrelated frequency a different trackId', () => {
    const tracker = createObjectTracker();
    const [first] = tracker.assignTracks([makeObject({ centerFrequencyHz: 2_400_500_000 })]);
    const [second] = tracker.assignTracks([makeObject({ centerFrequencyHz: 5_800_000_000, startFrequencyHz: 5_799_500_000, stopFrequencyHz: 5_800_500_000 })]);
    expect(second.trackId).not.toBe(first.trackId);
  });

  it('marks only the object(s) reaching the latest endTimeSeconds in the pass as active', () => {
    const tracker = createObjectTracker();
    const [ended, stillGoing] = tracker.assignTracks([
      makeObject({ id: 'a', centerFrequencyHz: 2_400_500_000, startFrequencyHz: 2_400_000_000, stopFrequencyHz: 2_401_000_000, endTimeSeconds: 2 }),
      makeObject({ id: 'b', centerFrequencyHz: 5_800_500_000, startFrequencyHz: 5_800_000_000, stopFrequencyHz: 5_801_000_000, endTimeSeconds: 5 }),
    ]);
    expect(ended.active).toBe(false);
    expect(stillGoing.active).toBe(true);
  });

  it('reuses the trackId of a recently-ended lineage that reappears nearby in frequency (reactivation)', () => {
    const tracker = createObjectTracker({ reactivationWindowSeconds: 10 });
    const [first] = tracker.assignTracks([makeObject({ startTimeSeconds: 0, endTimeSeconds: 1, centerFrequencyHz: 2_400_500_000 })]);
    // Nothing at that frequency in the next pass -- the lineage "ends".
    tracker.assignTracks([makeObject({ id: 'other', startTimeSeconds: 2, endTimeSeconds: 3, centerFrequencyHz: 5_800_500_000, startFrequencyHz: 5_800_000_000, stopFrequencyHz: 5_801_000_000 })]);
    // It reappears a few seconds later, close to the same frequency.
    const [reactivated] = tracker.assignTracks([makeObject({ startTimeSeconds: 4, endTimeSeconds: 5, centerFrequencyHz: 2_400_600_000 })]);
    expect(reactivated.trackId).toBe(first.trackId);
  });

  it('overrides morphology to HOPPING_CLUSTER once a lineage has reactivated enough times', () => {
    // Gaps (5.5s) deliberately exceed the default continuityWindowSeconds
    // (3s) so each reappearance is scored as a genuine reactivation, not
    // treated as one uninterrupted detection.
    const tracker = createObjectTracker({ reactivationWindowSeconds: 10, reactivationsForHoppingCluster: 2 });
    const freq = (offsetSeconds: number) => makeObject({
      startTimeSeconds: offsetSeconds, endTimeSeconds: offsetSeconds + 0.5, centerFrequencyHz: 2_400_500_000, morphology: 'ISLAND',
    });
    tracker.assignTracks([freq(0)]);
    tracker.assignTracks([freq(6)]);
    const [third] = tracker.assignTracks([freq(12)]);
    expect(third.morphology).toBe('HOPPING_CLUSTER');
  });

  it('reset() clears lineage state so trackId numbering restarts', () => {
    const tracker = createObjectTracker();
    const [first] = tracker.assignTracks([makeObject({})]);
    tracker.reset();
    const [afterReset] = tracker.assignTracks([makeObject({})]);
    expect(afterReset.trackId).toBe(first.trackId);
  });
});
