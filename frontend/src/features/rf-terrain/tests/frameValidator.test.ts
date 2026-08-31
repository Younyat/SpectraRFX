import { describe, expect, it } from 'vitest';
import { validateSpectrumFrame } from '../data/frameValidator';
import type { SpectrumData } from '../../../shared/types';

const validFrame: SpectrumData = {
  timestamp: 1_700_000_000_000,
  centerFrequency: 2_440_000_000,
  span: 40_000_000,
  frequencyArray: [2_420_000_000, 2_430_000_000, 2_440_000_000, 2_450_000_000],
  powerLevels: [-90, -85, -60, -88],
  sampleRateHz: 40_000_000,
  fftSize: 4096,
  powerUnit: 'dBFS',
};

describe('validateSpectrumFrame', () => {
  it('accepts a well-formed frame', () => {
    expect(validateSpectrumFrame(validFrame)).toEqual({ valid: true, frame: validFrame });
  });

  it('rejects an empty/too-short frequency array', () => {
    const result = validateSpectrumFrame({ ...validFrame, frequencyArray: [], powerLevels: [] });
    expect(result.valid).toBe(false);
  });

  it('rejects mismatched frequencyArray/powerLevels lengths', () => {
    const result = validateSpectrumFrame({ ...validFrame, powerLevels: [-90, -85] });
    expect(result.valid).toBe(false);
  });

  it('rejects NaN in powerLevels', () => {
    const result = validateSpectrumFrame({ ...validFrame, powerLevels: [-90, NaN, -60, -88] });
    expect(result.valid).toBe(false);
  });

  it('rejects Infinity in frequencyArray', () => {
    const result = validateSpectrumFrame({ ...validFrame, frequencyArray: [2_420_000_000, Infinity, 2_440_000_000, 2_450_000_000] });
    expect(result.valid).toBe(false);
  });

  it('rejects a non-monotonic frequency array', () => {
    const result = validateSpectrumFrame({ ...validFrame, frequencyArray: [2_420_000_000, 2_450_000_000, 2_430_000_000, 2_460_000_000] });
    expect(result.valid).toBe(false);
  });

  it('rejects a non-positive span', () => {
    const result = validateSpectrumFrame({ ...validFrame, span: 0 });
    expect(result.valid).toBe(false);
  });

  it('rejects an invalid timestamp', () => {
    expect(validateSpectrumFrame({ ...validFrame, timestamp: 0 }).valid).toBe(false);
    expect(validateSpectrumFrame({ ...validFrame, timestamp: NaN }).valid).toBe(false);
  });

  it('never throws on malformed input', () => {
    expect(() => validateSpectrumFrame({ ...validFrame, frequencyArray: undefined as unknown as number[] })).not.toThrow();
  });
});
