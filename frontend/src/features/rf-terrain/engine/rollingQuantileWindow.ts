// Per-bin sliding window of raw samples, used by noiseEstimator (P20
// baseline) and available for percentile overlays (P50/P90/P95/P99) --
// spec §18/§30, one shared window instead of two independent copies of the
// same bookkeeping.
export const createRollingQuantileWindow = (bins: number, capacity: number) => {
  const windows: number[][] = Array.from({ length: bins }, () => []);

  return {
    push(values: Float32Array | number[]) {
      for (let i = 0; i < bins; i += 1) {
        const window = windows[i];
        window.push(values[i]);
        if (window.length > capacity) {
          window.shift();
        }
      }
    },
    quantile(q: number): Float32Array {
      const output = new Float32Array(bins);
      for (let i = 0; i < bins; i += 1) {
        const sorted = [...windows[i]].sort((a, b) => a - b);
        if (sorted.length === 0) {
          output[i] = NaN;
          continue;
        }
        const index = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))));
        output[i] = sorted[index];
      }
      return output;
    },
    clear() {
      windows.forEach((window) => { window.length = 0; });
    },
  };
};
