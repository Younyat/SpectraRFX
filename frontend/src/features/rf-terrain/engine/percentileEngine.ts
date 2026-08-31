import { createRollingQuantileWindow } from './rollingQuantileWindow';

export interface PercentileSnapshot {
  p50: Float32Array;
  p90: Float32Array;
  p95: Float32Array;
  p99: Float32Array;
}

// P50/P90/P95/P99 (spec §30), sharing the same per-bin rolling-window
// bookkeeping as the noise estimator's own P20 baseline (rollingQuantileWindow.ts)
// rather than a second, independent implementation of the same sliding window.
export const createPercentileEngine = (bins: number, windowSamples: number) => {
  const window = createRollingQuantileWindow(bins, windowSamples);

  return {
    update(powerLevelsDb: Float32Array): PercentileSnapshot {
      window.push(powerLevelsDb);
      return {
        p50: window.quantile(0.5),
        p90: window.quantile(0.9),
        p95: window.quantile(0.95),
        p99: window.quantile(0.99),
      };
    },
    reset() {
      window.clear();
    },
  };
};
