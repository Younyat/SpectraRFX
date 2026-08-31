// 1D smoothing across the frequency axis of a single row (backs DENSITY
// mode, model/rfTerrainTypes.ts): turns many independent per-bin spikes
// into one coherent curve. A normalized, edge-clamped triangular
// convolution -- every bin in a row already has a real measured value
// (unlike the Spectral Object Envelope's sparse object mask, §15 in the
// technical report), so there is no "no data" case to gate against; the
// kernel simply shrinks near the array edges (fewer real neighbors
// contribute, but the result is still a true local average, never
// diluted by a phantom zero-padded neighbor).
export const smoothAcrossFrequency = (values: Float32Array, radius: number = 2): Float32Array => {
  const n = values.length;
  const output = new Float32Array(n);
  if (radius <= 0) {
    output.set(values);
    return output;
  }

  for (let i = 0; i < n; i += 1) {
    let weightedSum = 0;
    let weightTotal = 0;
    for (let offset = -radius; offset <= radius; offset += 1) {
      const j = i + offset;
      if (j < 0 || j >= n) continue;
      // Triangular falloff: the center bin weighs radius+1, its
      // immediate neighbors radius, and so on down to 1 at the edge.
      const weight = radius + 1 - Math.abs(offset);
      weightedSum += values[j] * weight;
      weightTotal += weight;
    }
    output[i] = weightTotal > 0 ? weightedSum / weightTotal : values[i];
  }
  return output;
};
