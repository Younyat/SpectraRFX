import { createRollingQuantileWindow } from './rollingQuantileWindow';

export interface NoiseEstimatorConfig {
  bins: number;
  quantile: number;
  windowSamples: number;
  smoothingBeta: number;
}

// Adaptive spectral floor (spec §18): per bin, N_i(t) = β·N_i(t-Δt) +
// (1-β)·Q_q[window]. Documented limitation carried over verbatim from the
// spec: a continuously-present signal spanning the whole window can get
// absorbed into the baseline -- this estimator does not correct for that.
export const createNoiseEstimator = (config: NoiseEstimatorConfig) => {
  const window = createRollingQuantileWindow(config.bins, config.windowSamples);
  let smoothed: Float32Array | null = null;

  return {
    update(powerLevelsDb: Float32Array): Float32Array {
      window.push(powerLevelsDb);
      const quantileEstimate = window.quantile(config.quantile);

      if (!smoothed) {
        smoothed = Float32Array.from(quantileEstimate);
        return smoothed;
      }

      for (let i = 0; i < config.bins; i += 1) {
        const q = quantileEstimate[i];
        smoothed[i] = Number.isFinite(q) ? config.smoothingBeta * smoothed[i] + (1 - config.smoothingBeta) * q : smoothed[i];
      }
      return smoothed;
    },
    reset() {
      window.clear();
      smoothed = null;
    },
  };
};
