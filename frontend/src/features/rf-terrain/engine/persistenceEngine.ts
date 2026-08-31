export interface PersistenceEngineConfig {
  bins: number;
  thresholdDb: number;
  tauSeconds: number;
}

// Persistence (spec §19): ρ_i(t) = e^(-Δt/τ)·ρ_i(t-Δt) + (1-e^(-Δt/τ))·A_i(t),
// where A_i is 1 when excess above the estimated floor clears thresholdDb.
// Independent of height -- never encodes the same magnitude twice.
export const createPersistenceEngine = (config: PersistenceEngineConfig) => {
  let persistence = new Float32Array(config.bins);

  return {
    update(excessDb: Float32Array, deltaTimeSeconds: number): Float32Array {
      const decay = Math.exp(-Math.max(deltaTimeSeconds, 0) / config.tauSeconds);
      for (let i = 0; i < config.bins; i += 1) {
        const active = excessDb[i] > config.thresholdDb ? 1 : 0;
        persistence[i] = decay * persistence[i] + (1 - decay) * active;
      }
      return persistence;
    },
    reset() {
      persistence = new Float32Array(config.bins);
    },
  };
};
