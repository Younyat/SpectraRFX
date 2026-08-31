import { describe, expect, it } from 'vitest';
import { createAcquisitionEpochTracker } from '../data/acquisitionEpoch';
import type { SpectrumData } from '../../../shared/types';

const baseFrame: SpectrumData = {
  timestamp: 1,
  centerFrequency: 2_440_000_000,
  span: 40_000_000,
  frequencyArray: [1, 2, 3, 4],
  powerLevels: [-90, -85, -60, -88],
  sampleRateHz: 40_000_000,
  fftSize: 4096,
  powerUnit: 'dBFS',
};

describe('createAcquisitionEpochTracker', () => {
  it('opens generation 1 on the very first frame', () => {
    const tracker = createAcquisitionEpochTracker();
    const result = tracker.update(baseFrame);
    expect(result).toEqual({ generation: 1, changed: true });
  });

  it('does not bump generation across frames with an identical acquisition-relevant key', () => {
    const tracker = createAcquisitionEpochTracker();
    tracker.update(baseFrame);
    const result = tracker.update({ ...baseFrame, timestamp: baseFrame.timestamp + 100, powerLevels: [-91, -84, -61, -87] });
    expect(result).toEqual({ generation: 1, changed: false });
  });

  it('bumps generation when center frequency changes', () => {
    const tracker = createAcquisitionEpochTracker();
    tracker.update(baseFrame);
    const result = tracker.update({ ...baseFrame, centerFrequency: baseFrame.centerFrequency + 1_000_000 });
    expect(result).toEqual({ generation: 2, changed: true });
  });

  it('bumps generation when span changes', () => {
    const tracker = createAcquisitionEpochTracker();
    tracker.update(baseFrame);
    expect(tracker.update({ ...baseFrame, span: baseFrame.span * 2 }).changed).toBe(true);
  });

  it('bumps generation when power unit changes', () => {
    const tracker = createAcquisitionEpochTracker();
    tracker.update(baseFrame);
    expect(tracker.update({ ...baseFrame, powerUnit: 'dBm' }).changed).toBe(true);
  });

  it('bumps generation when the source/device identity changes', () => {
    const tracker = createAcquisitionEpochTracker();
    tracker.update({ ...baseFrame, deviceSerial: 'B200-A' });
    expect(tracker.update({ ...baseFrame, deviceSerial: 'B200-B' }).changed).toBe(true);
  });

  it('reset() forgets prior state so the next frame reopens generation 1', () => {
    const tracker = createAcquisitionEpochTracker();
    tracker.update(baseFrame);
    tracker.update({ ...baseFrame, centerFrequency: baseFrame.centerFrequency + 1 });
    tracker.reset();
    expect(tracker.update(baseFrame)).toEqual({ generation: 1, changed: true });
  });
});
