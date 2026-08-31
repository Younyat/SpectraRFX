import { describe, expect, it } from 'vitest';
import { OfflineSpectrumGenerator, sampleIndexToTimestampMs } from '../../engine/offline/spectrumGenerator';

const makeToneSamples = (count: number, cyclesPerSample: number): { re: Float32Array; im: Float32Array } => {
  const re = new Float32Array(count);
  const im = new Float32Array(count);
  for (let n = 0; n < count; n += 1) {
    re[n] = Math.cos(2 * Math.PI * cyclesPerSample * n);
    im[n] = Math.sin(2 * Math.PI * cyclesPerSample * n);
  }
  return { re, im };
};

describe('sampleIndexToTimestampMs', () => {
  it('is derived purely from sample index / sample rate, never wall-clock', () => {
    expect(sampleIndexToTimestampMs(0, 1000)).toBeCloseTo(1, 5); // +1ms floor
    expect(sampleIndexToTimestampMs(1000, 1000)).toBeCloseTo(1001, 5);
    expect(sampleIndexToTimestampMs(4000, 4000)).toBeCloseTo(1001, 5);
  });

  it('the very first frame is always strictly positive (frameValidator requires timestamp > 0)', () => {
    expect(sampleIndexToTimestampMs(0, 4_000_000)).toBeGreaterThan(0);
  });
});

describe('OfflineSpectrumGenerator', () => {
  it('rejects an invalid hop/fft configuration up front', () => {
    expect(() => new OfflineSpectrumGenerator({ sampleRateSps: 1000, centerFrequencyHz: 0, fftSize: 64, hopSize: 0 })).toThrow();
    expect(() => new OfflineSpectrumGenerator({ sampleRateSps: 1000, centerFrequencyHz: 0, fftSize: 64, hopSize: 128 })).toThrow();
  });

  it('produces no frames until at least one full FFT window of samples has arrived', () => {
    const gen = new OfflineSpectrumGenerator({ sampleRateSps: 1000, centerFrequencyHz: 0, fftSize: 64, hopSize: 32 });
    const { re, im } = makeToneSamples(30, 0.1);
    expect(gen.pushChunk(re, im)).toHaveLength(0);
  });

  it('produces frames at the expected cadence once enough samples accumulate, carrying the tail forward', () => {
    const gen = new OfflineSpectrumGenerator({ sampleRateSps: 1000, centerFrequencyHz: 0, fftSize: 64, hopSize: 32 });
    const { re, im } = makeToneSamples(100, 0.1);
    const frames = gen.pushChunk(re, im);
    // 100 samples, fftSize=64, hop=32 -> windows at offset 0 and 32 (offset 64 needs 128 samples).
    expect(frames).toHaveLength(2);
    expect(frames[0].sampleIndex).toBe(0);
    expect(frames[1].sampleIndex).toBe(32);
  });

  it('produces byte-identical frames regardless of how the same underlying samples are chunked', () => {
    const total = 300;
    const { re, im } = makeToneSamples(total, 0.07);
    const config = { sampleRateSps: 2_000_000, centerFrequencyHz: 2_440_000_000, fftSize: 64, hopSize: 16 };

    // Pass 1: one big chunk.
    const genA = new OfflineSpectrumGenerator(config);
    const framesA = genA.pushChunk(re, im);

    // Pass 2: many small, unevenly-sized chunks.
    const genB = new OfflineSpectrumGenerator(config);
    const framesB: ReturnType<typeof genB.pushChunk> = [];
    const chunkSizes = [17, 23, 5, 40, 9, 100, 106];
    let cursor = 0;
    for (const size of chunkSizes) {
      const end = Math.min(cursor + size, total);
      framesB.push(...genB.pushChunk(re.slice(cursor, end), im.slice(cursor, end)));
      cursor = end;
    }

    expect(framesA.length).toBe(framesB.length);
    expect(framesA.length).toBeGreaterThan(0);
    for (let i = 0; i < framesA.length; i += 1) {
      expect(framesA[i].sampleIndex).toBe(framesB[i].sampleIndex);
      expect(Array.from(framesA[i].nativePowerLevelsDb)).toEqual(Array.from(framesB[i].nativePowerLevelsDb));
      expect(framesA[i].spectrumData.timestamp).toBe(framesB[i].spectrumData.timestamp);
    }
  });

  it('the emitted frequency array is centered on the real center frequency and monotonically increasing', () => {
    const gen = new OfflineSpectrumGenerator({ sampleRateSps: 4_000_000, centerFrequencyHz: 2_402_000_000, fftSize: 8, hopSize: 8 });
    const { re, im } = makeToneSamples(8, 0.1);
    const [frame] = gen.pushChunk(re, im);
    const freqs = frame.spectrumData.frequencyArray;
    for (let i = 1; i < freqs.length; i += 1) expect(freqs[i]).toBeGreaterThan(freqs[i - 1]);
    const mid = freqs[freqs.length / 2];
    expect(Math.abs(mid - 2_402_000_000)).toBeLessThan(4_000_000 / 8);
  });

  it('every emitted SpectrumData passes real frame validation semantics (finite, monotonic, positive timestamp/span)', () => {
    const gen = new OfflineSpectrumGenerator({ sampleRateSps: 4_000_000, centerFrequencyHz: 2_402_000_000, fftSize: 32, hopSize: 32 });
    const { re, im } = makeToneSamples(64, 0.05);
    const frames = gen.pushChunk(re, im);
    for (const frame of frames) {
      const d = frame.spectrumData;
      expect(d.timestamp).toBeGreaterThan(0);
      expect(Number.isFinite(d.centerFrequency)).toBe(true);
      expect(d.span).toBeGreaterThan(0);
      expect(d.frequencyArray.length).toBe(d.powerLevels.length);
      expect(d.frequencyArray.every(Number.isFinite)).toBe(true);
      expect(d.powerLevels.every(Number.isFinite)).toBe(true);
    }
  });
});
