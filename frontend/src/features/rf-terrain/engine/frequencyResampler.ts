// Controlled resampler (spec §44): maps a native-resolution array (e.g.
// 4096 FFT bins) down (or up) to a fixed target column count via nearest-
// neighbor sampling. Deliberately simple/deterministic -- this is a
// rendering/analysis-grid concern, not a scientific interpolation claim.
export const resampleToBins = (values: number[], targetBins: number): Float32Array => {
  const output = new Float32Array(targetBins);
  const sourceLength = values.length;
  if (sourceLength === 0 || targetBins <= 0) {
    return output;
  }
  for (let i = 0; i < targetBins; i += 1) {
    const sourceIndex = Math.min(sourceLength - 1, Math.floor((i * sourceLength) / targetBins));
    output[i] = values[sourceIndex];
  }
  return output;
};
