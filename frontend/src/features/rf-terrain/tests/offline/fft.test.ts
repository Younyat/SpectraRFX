import { describe, expect, it } from 'vitest';
import { fftInPlace, hannWindow, isPowerOfTwo, magnitudeSpectrumDb } from '../../engine/offline/fft';

describe('isPowerOfTwo', () => {
  it('accepts real powers of two and rejects everything else', () => {
    expect(isPowerOfTwo(1)).toBe(true);
    expect(isPowerOfTwo(2)).toBe(true);
    expect(isPowerOfTwo(1024)).toBe(true);
    expect(isPowerOfTwo(0)).toBe(false);
    expect(isPowerOfTwo(-4)).toBe(false);
    expect(isPowerOfTwo(100)).toBe(false);
  });
});

describe('fftInPlace', () => {
  it('throws for a non-power-of-two size instead of silently misbehaving', () => {
    const re = new Float64Array(100);
    const im = new Float64Array(100);
    expect(() => fftInPlace({ re, im })).toThrow();
  });

  it('a DC-only signal (constant real value) transforms to energy only in bin 0', () => {
    const size = 64;
    const re = new Float64Array(size).fill(3);
    const im = new Float64Array(size);
    fftInPlace({ re, im });
    expect(re[0]).toBeCloseTo(3 * size, 6);
    for (let i = 1; i < size; i += 1) {
      expect(re[i]).toBeCloseTo(0, 6);
      expect(im[i]).toBeCloseTo(0, 6);
    }
  });

  it('a pure sinusoid at bin k produces energy concentrated at bin k (and its mirror)', () => {
    const size = 64;
    const k = 5;
    const re = new Float64Array(size);
    const im = new Float64Array(size);
    for (let n = 0; n < size; n += 1) {
      re[n] = Math.cos((2 * Math.PI * k * n) / size);
    }
    fftInPlace({ re, im });
    const magnitude = (i: number) => Math.hypot(re[i], im[i]);
    expect(magnitude(k)).toBeGreaterThan(size * 0.4);
    expect(magnitude(size - k)).toBeGreaterThan(size * 0.4);
    // Everything else should be near zero.
    for (let i = 0; i < size; i += 1) {
      if (i === k || i === size - k) continue;
      expect(magnitude(i)).toBeLessThan(1e-6);
    }
  });

  it('satisfies Parseval\'s theorem (energy preserved between time and frequency domain)', () => {
    const size = 128;
    const re = new Float64Array(size);
    const im = new Float64Array(size);
    for (let n = 0; n < size; n += 1) {
      re[n] = Math.sin((2 * Math.PI * 3 * n) / size) + 0.5;
    }
    let timeEnergy = 0;
    for (let n = 0; n < size; n += 1) timeEnergy += re[n] * re[n] + im[n] * im[n];

    fftInPlace({ re, im });
    let freqEnergy = 0;
    for (let n = 0; n < size; n += 1) freqEnergy += re[n] * re[n] + im[n] * im[n];

    expect(freqEnergy / size).toBeCloseTo(timeEnergy, 6);
  });

  it('is deterministic -- the same input always produces the same output', () => {
    const size = 32;
    const build = () => {
      const re = new Float64Array(size);
      const im = new Float64Array(size);
      for (let n = 0; n < size; n += 1) re[n] = Math.sin(n * 0.3) + Math.cos(n * 0.7);
      return { re, im };
    };
    const a = build();
    const b = build();
    fftInPlace(a);
    fftInPlace(b);
    expect(Array.from(a.re)).toEqual(Array.from(b.re));
    expect(Array.from(a.im)).toEqual(Array.from(b.im));
  });
});

describe('hannWindow', () => {
  it('starts and ends near zero and peaks at 1 in the middle', () => {
    const window = hannWindow(65);
    expect(window[0]).toBeCloseTo(0, 6);
    expect(window[64]).toBeCloseTo(0, 6);
    expect(window[32]).toBeCloseTo(1, 6);
  });
});

describe('magnitudeSpectrumDb', () => {
  it('places a pure tone\'s peak at the frequency-shifted bin matching its cycle rate', () => {
    const size = 64;
    const k = 8; // positive-frequency bin before fftshift
    const re = new Float64Array(size);
    const im = new Float64Array(size);
    for (let n = 0; n < size; n += 1) {
      re[n] = Math.cos((2 * Math.PI * k * n) / size);
    }
    const window = new Float64Array(size).fill(1); // rectangular, for a clean peak
    const spectrum = magnitudeSpectrumDb(re, im, window);
    // After fftshift, positive frequency k lands at size/2 + k.
    const expectedBin = size / 2 + k;
    let peakBin = 0;
    for (let i = 1; i < size; i += 1) if (spectrum[i] > spectrum[peakBin]) peakBin = i;
    expect(peakBin).toBe(expectedBin);
  });

  it('is deterministic across repeated calls on identical input', () => {
    const size = 32;
    const re = Float64Array.from({ length: size }, (_, n) => Math.sin(n));
    const im = new Float64Array(size);
    const window = hannWindow(size);
    const a = magnitudeSpectrumDb(re, im, window);
    const b = magnitudeSpectrumDb(re, im, window);
    expect(Array.from(a)).toEqual(Array.from(b));
  });
});
