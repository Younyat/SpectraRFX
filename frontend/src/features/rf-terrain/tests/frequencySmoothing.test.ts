import { describe, expect, it } from 'vitest';
import { smoothAcrossFrequency } from '../engine/frequencySmoothing';

describe('smoothAcrossFrequency', () => {
  it('radius=0 returns the input unchanged (no smoothing)', () => {
    const input = Float32Array.from([0, 5, 20, 5, 0]);
    const output = smoothAcrossFrequency(input, 0);
    expect(Array.from(output)).toEqual(Array.from(input));
  });

  it('a perfectly flat row stays flat (smoothing a constant is a no-op)', () => {
    const input = Float32Array.from([10, 10, 10, 10, 10, 10]);
    const output = smoothAcrossFrequency(input, 2);
    output.forEach((v) => expect(v).toBeCloseTo(10, 5));
  });

  it('spreads a lone spike into its neighbors instead of leaving it isolated', () => {
    const input = Float32Array.from([0, 0, 0, 20, 0, 0, 0]);
    const output = smoothAcrossFrequency(input, 2);
    // The peak itself shrinks (its neighbors were 0)...
    expect(output[3]).toBeLessThan(20);
    expect(output[3]).toBeGreaterThan(0);
    // ...and its immediate neighbors pick up some of that energy, unlike
    // the untouched input where they were exactly 0.
    expect(output[2]).toBeGreaterThan(0);
    expect(output[4]).toBeGreaterThan(0);
  });

  it('edge bins are a true local average, never diluted by a phantom zero neighbor', () => {
    const input = Float32Array.from([10, 10, 10, 10, 10]);
    const output = smoothAcrossFrequency(input, 2);
    // If out-of-range neighbors silently contributed 0, the edge value
    // would be pulled below 10 even though every REAL neighbor is 10.
    expect(output[0]).toBeCloseTo(10, 5);
    expect(output[output.length - 1]).toBeCloseTo(10, 5);
  });

  it('preserves array length', () => {
    const input = Float32Array.from([1, 2, 3, 4, 5, 6, 7]);
    expect(smoothAcrossFrequency(input, 3).length).toBe(input.length);
  });

  it('handles a single-element array without throwing', () => {
    const input = Float32Array.from([42]);
    const output = smoothAcrossFrequency(input, 2);
    expect(output[0]).toBeCloseTo(42, 5);
  });
});
