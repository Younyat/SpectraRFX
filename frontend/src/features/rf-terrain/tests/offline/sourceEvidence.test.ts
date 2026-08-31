import { describe, expect, it } from 'vitest';
import { deriveSourceSampleRange, isConsistentWithEvidence } from '../../offline/sourceEvidence';
import { sampleIndexToTimestampMs } from '../../engine/offline/spectrumGenerator';

const EVIDENCE = { captureId: 'BLE-IQ-test', dataSha256: 'a'.repeat(64), sampleRateSps: 4_000_000, fftSize: 4096 };

describe('deriveSourceSampleRange', () => {
  it('exactly inverts sampleIndexToTimestampMs for the first frame (sampleIndex 0)', () => {
    const timestamp = sampleIndexToTimestampMs(0, EVIDENCE.sampleRateSps);
    const range = deriveSourceSampleRange(timestamp, EVIDENCE);
    expect(range.startSampleIndex).toBe(0);
    expect(range.endSampleIndex).toBe(EVIDENCE.fftSize - 1);
  });

  it('exactly inverts sampleIndexToTimestampMs for an arbitrary later frame', () => {
    const originalSampleIndex = 123_456;
    const timestamp = sampleIndexToTimestampMs(originalSampleIndex, EVIDENCE.sampleRateSps);
    const range = deriveSourceSampleRange(timestamp, EVIDENCE);
    expect(range.startSampleIndex).toBe(originalSampleIndex);
    expect(range.endTimeSeconds).toBeGreaterThan(range.startTimeSeconds);
  });

  it('round-trips consistently for many sample indices', () => {
    for (const sampleIndex of [0, 1, 4096, 40_000, 4_000_000, 39_999_999]) {
      const timestamp = sampleIndexToTimestampMs(sampleIndex, EVIDENCE.sampleRateSps);
      expect(isConsistentWithEvidence(timestamp, EVIDENCE)).toBe(true);
    }
  });

  it('flags an arbitrary timestamp that was never produced by this evidence sample rate', () => {
    const arbitraryTimestamp = 12345.6789; // not aligned to any real sample index at EVIDENCE.sampleRateSps
    expect(isConsistentWithEvidence(arbitraryTimestamp, EVIDENCE)).toBe(false);
  });
});
