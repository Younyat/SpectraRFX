// Max/Min Hold (spec §27/§28): M_i(t) = max(M_i(t-Δt), P_i(t)),
// m_i(t) = min(m_i(t-Δt), P_i(t)). Invariant maintained by construction:
// minHold_i <= live_i <= maxHold_i.
export const createHoldEngine = (bins: number) => {
  let maxHold = new Float32Array(bins).fill(-Infinity);
  let minHold = new Float32Array(bins).fill(Infinity);

  return {
    update(powerLevelsDb: Float32Array): { maxHold: Float32Array; minHold: Float32Array } {
      for (let i = 0; i < bins; i += 1) {
        maxHold[i] = Math.max(maxHold[i], powerLevelsDb[i]);
        minHold[i] = Math.min(minHold[i], powerLevelsDb[i]);
      }
      return { maxHold, minHold };
    },
    reset() {
      maxHold = new Float32Array(bins).fill(-Infinity);
      minHold = new Float32Array(bins).fill(Infinity);
    },
  };
};
