import { hannWindow, magnitudeSpectrumDb } from './fft';
import type { SpectrumData } from '../../../../shared/types';

export interface OfflineSpectrumGeneratorConfig {
  sampleRateSps: number;
  centerFrequencyHz: number;
  // Native FFT resolution -- the "SCIENTIFIC ANALYSIS" resolution (spec
  // §30), kept separate from whatever bin count the 3D render/analysis
  // grid resamples to (RF_TERRAIN_DEFAULT_FREQUENCY_BINS, via the
  // existing frequencyResampler.ts -- unchanged, reused as-is).
  fftSize: number;
  // Hop < fftSize gives overlapping STFT windows (denser time
  // resolution); hop === fftSize gives non-overlapping framing.
  hopSize: number;
  deviceSerial?: string;
}

const concatFloat32 = (a: Float32Array, b: Float32Array): Float32Array => {
  const out = new Float32Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
};

// Real-only scientific time (spec §9): t_n = n / f_s, from the ABSOLUTE
// sample index of each window's first sample -- never Date.now(). The
// same capture, reconstructed twice, produces byte-identical timestamps
// every time. `+1` keeps the very first frame's timestamp strictly
// positive (frameValidator.ts rejects `timestamp <= 0`) without
// perturbing the real, constant spacing between frames.
export const sampleIndexToTimestampMs = (sampleIndex: number, sampleRateSps: number): number =>
  (sampleIndex / sampleRateSps) * 1000 + 1;

export interface NativeResolutionFrame {
  spectrumData: SpectrumData;
  // The exact per-bin excess-domain input Context Audit metrics operate
  // on, kept at native (unresampled) resolution -- spec §30's "scientific
  // resolution" side of the split.
  nativePowerLevelsDb: Float32Array;
  nativeFrequencyArrayHz: Float64Array;
  sampleIndex: number;
}

// Stateful STFT framer -- the ONLY stateful piece of the offline pipeline
// (it must remember the tail of one chunk to overlap into the next
// window), but still fully deterministic: the same sequence of pushChunk
// calls over the same bytes always produces the same frames, regardless
// of how the caller happened to size the chunks (verified by
// offlineDeterminism.test.ts with different chunk sizes over identical
// bytes).
export class OfflineSpectrumGenerator {
  private readonly config: OfflineSpectrumGeneratorConfig;
  private readonly window: Float64Array;
  private readonly frequencyArrayHz: Float64Array;
  private bufferRe: Float32Array = new Float32Array(0);
  private bufferIm: Float32Array = new Float32Array(0);
  private bufferStartSampleIndex = 0;

  constructor(config: OfflineSpectrumGeneratorConfig) {
    if (config.hopSize <= 0 || config.hopSize > config.fftSize) {
      throw new Error(`hopSize must be in (0, fftSize] -- got hopSize=${config.hopSize}, fftSize=${config.fftSize}`);
    }
    this.config = config;
    this.window = hannWindow(config.fftSize);
    const binHz = config.sampleRateSps / config.fftSize;
    const frequencyArrayHz = new Float64Array(config.fftSize);
    for (let i = 0; i < config.fftSize; i += 1) {
      frequencyArrayHz[i] = config.centerFrequencyHz + (i - config.fftSize / 2) * binHz;
    }
    this.frequencyArrayHz = frequencyArrayHz;
  }

  // Appends newly-read I/Q samples (in absolute stream order) and returns
  // every complete STFT frame that can now be produced. Any remaining
  // tail shorter than one FFT window is buffered for the next call.
  pushChunk(chunkRe: Float32Array, chunkIm: Float32Array): NativeResolutionFrame[] {
    const combinedRe = concatFloat32(this.bufferRe, chunkRe);
    const combinedIm = concatFloat32(this.bufferIm, chunkIm);
    const { fftSize, hopSize } = this.config;

    const frames: NativeResolutionFrame[] = [];
    let offset = 0;
    while (offset + fftSize <= combinedRe.length) {
      const windowRe = new Float64Array(fftSize);
      const windowIm = new Float64Array(fftSize);
      for (let i = 0; i < fftSize; i += 1) {
        windowRe[i] = combinedRe[offset + i];
        windowIm[i] = combinedIm[offset + i];
      }
      const spectrumDb = magnitudeSpectrumDb(windowRe, windowIm, this.window);
      const sampleIndex = this.bufferStartSampleIndex + offset;

      frames.push({
        sampleIndex,
        nativePowerLevelsDb: Float32Array.from(spectrumDb),
        nativeFrequencyArrayHz: this.frequencyArrayHz,
        spectrumData: {
          timestamp: sampleIndexToTimestampMs(sampleIndex, this.config.sampleRateSps),
          centerFrequency: this.config.centerFrequencyHz,
          span: this.config.sampleRateSps,
          frequencyArray: Array.from(this.frequencyArrayHz),
          powerLevels: Array.from(spectrumDb),
          sampleRateHz: this.config.sampleRateSps,
          fftSize,
          effectiveRbwHz: this.config.sampleRateSps / fftSize,
          powerUnit: 'dBFS',
          sourceId: 'offline_reconstruction',
          deviceSerial: this.config.deviceSerial,
        },
      });

      offset += hopSize;
    }

    this.bufferRe = combinedRe.slice(offset);
    this.bufferIm = combinedIm.slice(offset);
    this.bufferStartSampleIndex += offset;

    return frames;
  }
}
