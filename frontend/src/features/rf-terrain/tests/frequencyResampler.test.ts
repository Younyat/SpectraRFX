import { describe, expect, it } from 'vitest';
import { resampleToBins } from '../engine/frequencyResampler';

describe('resampleToBins', () => {
  it('downsamples a longer array to the exact target length', () => {
    const source = Array.from({ length: 4096 }, (_, i) => i);
    const output = resampleToBins(source, 512);
    expect(output).toHaveLength(512);
  });

  it('upsamples a shorter array to the exact target length', () => {
    const output = resampleToBins([1, 2, 3], 8);
    expect(output).toHaveLength(8);
  });

  it('preserves the first source value and stays within the source range', () => {
    const source = [10, 20, 30, 40, 50, 60, 70, 80];
    const output = resampleToBins(source, 4);
    expect(output[0]).toBe(10);
    expect(Array.from(output).every((v) => v >= 10 && v <= 80)).toBe(true);
  });

  it('never reads past the end of the source array', () => {
    const output = resampleToBins([1, 2, 3], 10);
    expect(Array.from(output).every((v) => Number.isFinite(v))).toBe(true);
  });

  it('returns an all-zero array for empty input rather than throwing', () => {
    expect(() => resampleToBins([], 16)).not.toThrow();
    expect(Array.from(resampleToBins([], 16))).toEqual(new Array(16).fill(0));
  });
});
