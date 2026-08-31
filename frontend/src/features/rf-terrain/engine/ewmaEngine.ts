// Displayed-power EWMA (spec §29): S_t = alpha*X_t + (1-alpha)*S_(t-1),
// applied directly in the dB domain the trace is already displayed in.
// Deliberately its own engine with its own state -- distinct from the
// noise-floor estimator's internal smoothing and from the linear-domain
// Power Average engine (spec: "separate EWMA state used for displayed
// power smoothing from EWMA state used internally for analysis").
export const createEwmaEngine = (bins: number, alpha: number) => {
  let state: Float32Array | null = null;

  return {
    update(powerLevelsDb: Float32Array): Float32Array {
      if (!state) {
        state = Float32Array.from(powerLevelsDb);
        return state;
      }
      for (let i = 0; i < bins; i += 1) {
        state[i] = alpha * powerLevelsDb[i] + (1 - alpha) * state[i];
      }
      return state;
    },
    reset() {
      state = null;
    },
  };
};
