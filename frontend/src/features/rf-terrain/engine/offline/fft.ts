// Deterministic radix-2 Cooley-Tukey FFT, iterative in-place (bit-reversal
// + butterfly), operating on separate real/imaginary Float64Arrays for
// numerical stability across the offline reconstruction's whole pipeline.
// No dependency on any live/render code -- this is the scientific-analysis
// primitive Offline Reconstruction needs and the frontend does not
// currently have (audited before writing this: no existing FFT/STFT
// implementation anywhere in `frontend/src/`).
//
// `size` MUST be a power of two. Complexity O(n log n), same result for
// the same input every time (pure function, no wall-clock/random input)
// -- the determinism the offline pipeline requires.
export const isPowerOfTwo = (n: number): boolean => n > 0 && (n & (n - 1)) === 0;

const bitReverseIndices = (size: number): Uint32Array => {
  const bits = Math.log2(size);
  const indices = new Uint32Array(size);
  for (let i = 0; i < size; i += 1) {
    let reversed = 0;
    let value = i;
    for (let b = 0; b < bits; b += 1) {
      reversed = (reversed << 1) | (value & 1);
      value >>= 1;
    }
    indices[i] = reversed;
  }
  return indices;
};

export interface ComplexArrays {
  re: Float64Array;
  im: Float64Array;
}

// In-place forward FFT. Callers own the input arrays; both are overwritten
// with the transformed result.
export const fftInPlace = ({ re, im }: ComplexArrays): void => {
  const size = re.length;
  if (!isPowerOfTwo(size)) {
    throw new Error(`fftInPlace: size must be a power of two, got ${size}`);
  }

  const bitReversed = bitReverseIndices(size);
  for (let i = 0; i < size; i += 1) {
    const j = bitReversed[i];
    if (j > i) {
      const tempRe = re[i]; re[i] = re[j]; re[j] = tempRe;
      const tempIm = im[i]; im[i] = im[j]; im[j] = tempIm;
    }
  }

  for (let span = 2; span <= size; span *= 2) {
    const half = span / 2;
    const angleStep = (-2 * Math.PI) / span;
    for (let start = 0; start < size; start += span) {
      for (let k = 0; k < half; k += 1) {
        const angle = angleStep * k;
        const wRe = Math.cos(angle);
        const wIm = Math.sin(angle);
        const evenIdx = start + k;
        const oddIdx = start + k + half;
        const oddRe = re[oddIdx] * wRe - im[oddIdx] * wIm;
        const oddIm = re[oddIdx] * wIm + im[oddIdx] * wRe;
        re[oddIdx] = re[evenIdx] - oddRe;
        im[oddIdx] = im[evenIdx] - oddIm;
        re[evenIdx] += oddRe;
        im[evenIdx] += oddIm;
      }
    }
  }
};

// Hann window -- standard, real, and applied identically every call
// (deterministic, no randomness). Reduces spectral leakage from framing a
// continuous I/Q stream into finite FFT blocks.
export const hannWindow = (size: number): Float64Array => {
  const window = new Float64Array(size);
  for (let i = 0; i < size; i += 1) {
    window[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (size - 1));
  }
  return window;
};

// Windowed magnitude spectrum (dB) of one complex I/Q block, FFT-shifted
// so index 0 is the most-negative frequency and the array reads
// low-to-high across the observed span (matches how TerrainInputFrame's
// frequencyArray is already ordered elsewhere in this module).
export const magnitudeSpectrumDb = (iqRe: Float64Array, iqIm: Float64Array, window: Float64Array): Float64Array => {
  const size = iqRe.length;
  const re = new Float64Array(size);
  const im = new Float64Array(size);
  for (let i = 0; i < size; i += 1) {
    re[i] = iqRe[i] * window[i];
    im[i] = iqIm[i] * window[i];
  }
  fftInPlace({ re, im });

  const shifted = new Float64Array(size);
  const half = size / 2;
  for (let i = 0; i < size; i += 1) {
    const srcIdx = (i + half) % size;
    const magnitudeSquared = re[srcIdx] * re[srcIdx] + im[srcIdx] * im[srcIdx];
    // 1e-20 floor avoids -Infinity for an exact-zero bin (e.g. a fully
    // zero-padded tail block) while being far below any real signal.
    shifted[i] = 10 * Math.log10(Math.max(magnitudeSquared, 1e-20));
  }
  return shifted;
};
