import { describe, expect, it } from 'vitest';
import { createAverageEngine } from '../engine/averageEngine';

describe('createAverageEngine', () => {
  it('averages in the linear domain, not a naive dB mean', () => {
    const engine = createAverageEngine(1, 1); // alpha=1 -> always the latest linear sample
    const a = engine.update(new Float32Array([-10]))[0];
    expect(a).toBeCloseTo(-10, 5);

    // Two equal-power samples should average back to the same value
    // regardless of domain, so use two different values where the linear-
    // domain mean provably differs from the naive dB mean: -10 dB and
    // -Infinity-like very low dB should pull the linear mean toward the
    // stronger (less negative) signal, not the arithmetic midpoint.
    const engine2 = createAverageEngine(1, 0.5);
    engine2.update(new Float32Array([-10]));
    const result = engine2.update(new Float32Array([-60]))[0];
    const naiveDbMean = (-10 + -60) / 2; // -35
    expect(result).toBeGreaterThan(naiveDbMean);
  });

  it('reset() forgets the running mean', () => {
    const engine = createAverageEngine(1, 0.5);
    engine.update(new Float32Array([-10]));
    engine.reset();
    const first = engine.update(new Float32Array([-90]))[0];
    expect(first).toBeCloseTo(-90, 5);
  });

  it('operates independently per bin', () => {
    const engine = createAverageEngine(2, 1);
    const result = engine.update(new Float32Array([-10, -80]));
    expect(result[0]).toBeCloseTo(-10, 5);
    expect(result[1]).toBeCloseTo(-80, 5);
  });
});
