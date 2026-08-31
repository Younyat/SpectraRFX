import { describe, expect, it } from 'vitest';
import { getSampleFormatSpec, SUPPORTED_SAMPLE_FORMATS } from '../../engine/offline/iqBytes';

const makeCf32LeBuffer = (samples: Array<[number, number]>): ArrayBuffer => {
  const buffer = new ArrayBuffer(samples.length * 8);
  const view = new DataView(buffer);
  samples.forEach(([i, q], idx) => {
    view.setFloat32(idx * 8, i, true);
    view.setFloat32(idx * 8 + 4, q, true);
  });
  return buffer;
};

describe('cf32_le parsing', () => {
  it('parses interleaved I/Q float32 pairs in order', () => {
    const buffer = makeCf32LeBuffer([[1, -1], [0.5, 0.25], [-3, 3]]);
    const { re, im } = SUPPORTED_SAMPLE_FORMATS.cf32_le.parse(buffer);
    expect(Array.from(re)).toEqual([1, 0.5, -3]);
    expect(Array.from(im)).toEqual([-1, 0.25, 3]);
  });

  it('throws on a buffer length that is not a multiple of 8 bytes rather than silently truncating', () => {
    const buffer = new ArrayBuffer(10);
    expect(() => SUPPORTED_SAMPLE_FORMATS.cf32_le.parse(buffer)).toThrow();
  });

  it('handles an empty buffer as zero samples, not an error', () => {
    const { re, im } = SUPPORTED_SAMPLE_FORMATS.cf32_le.parse(new ArrayBuffer(0));
    expect(re.length).toBe(0);
    expect(im.length).toBe(0);
  });
});

describe('getSampleFormatSpec', () => {
  it('resolves the real, campaign-frozen cf32_le format', () => {
    expect(getSampleFormatSpec('cf32_le').bytesPerSample).toBe(8);
  });

  it('fails closed for any unsupported/unimplemented format instead of guessing', () => {
    expect(() => getSampleFormatSpec('ci16_le')).toThrow(/Unsupported/);
    expect(() => getSampleFormatSpec('bogus')).toThrow(/Unsupported/);
  });
});
