export interface OccupancyEngineConfig {
  bins: number;
  thresholdDb: number;
  tauSeconds: number;
}

// Occupancy (spec §20): the spec defines it as a real-Δt-weighted ratio of
// active time over total time in a window,
// O_i = Σ(Δt_j·1[E_i>θ]) / Σ(Δt_j). This engine computes the same ratio as
// a continuous exponential moving average driven by real Δt (never frame
// counts, per the spec's explicit warning about jitter/dropped frames) --
// an online approximation of the windowed ratio, documented here rather
// than left implicit.
export const createOccupancyEngine = (config: OccupancyEngineConfig) => {
  let occupancy = new Float32Array(config.bins);

  return {
    update(excessDb: Float32Array, deltaTimeSeconds: number): Float32Array {
      const decay = Math.exp(-Math.max(deltaTimeSeconds, 0) / config.tauSeconds);
      for (let i = 0; i < config.bins; i += 1) {
        const active = excessDb[i] > config.thresholdDb ? 1 : 0;
        occupancy[i] = decay * occupancy[i] + (1 - decay) * active;
      }
      return occupancy;
    },
    reset() {
      occupancy = new Float32Array(config.bins);
    },
  };
};
