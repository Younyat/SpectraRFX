import { describe, expect, it } from 'vitest';
import { fitRidgeSlope } from '../engine/ridgeTracking';

describe('fitRidgeSlope', () => {
  it('a perfect linear chirp yields a coherent, correct non-zero slope', () => {
    // frequency = 1000 + 500*t -- slope should be ~500 Hz/s.
    const points = Array.from({ length: 10 }, (_, i) => ({ timestampSeconds: i, frequencyHz: 1000 + 500 * i }));
    const fit = fitRidgeSlope(points);
    expect(fit).not.toBeNull();
    expect(fit!.slopeHzPerSecond).toBeCloseTo(500, 5);
  });

  it('a stationary carrier yields ~zero slope', () => {
    const points = Array.from({ length: 10 }, (_, i) => ({ timestampSeconds: i, frequencyHz: 2440 }));
    const fit = fitRidgeSlope(points);
    expect(fit!.slopeHzPerSecond).toBeCloseTo(0, 5);
  });

  it('returns null for fewer than 2 points', () => {
    expect(fitRidgeSlope([])).toBeNull();
    expect(fitRidgeSlope([{ timestampSeconds: 0, frequencyHz: 100 }])).toBeNull();
  });

  it('a negative-slope (descending) chirp yields a negative slope', () => {
    const points = Array.from({ length: 6 }, (_, i) => ({ timestampSeconds: i, frequencyHz: 5000 - 200 * i }));
    const fit = fitRidgeSlope(points);
    expect(fit!.slopeHzPerSecond).toBeCloseTo(-200, 5);
  });
});
