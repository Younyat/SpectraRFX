// Power average (spec §24-25): averaging happens in linear domain, then
// converts back to dB -- 10*log10(mean(10^(P/10))) -- never a naive dB
// arithmetic mean. Implemented as a running linear-domain EWMA (continuous
// trace, spec §29) rather than a fixed-N cumulative mean, so it behaves
// like a live "Power Average" overlay instead of a one-shot statistic.
//
// The spec also calls for an independent RMS trace (§26), but with only
// per-bin power-in-dB samples available (no raw I/Q), RMS-of-power reduces
// to the exact same linear-domain-mean-then-log formula as Power Average --
// there is no additional real information to compute from. Rather than
// fabricate a second, cosmetically different number, this engine exposes
// one linear-domain average and documents that limitation instead of
// hiding it.
export const createAverageEngine = (bins: number, alpha: number) => {
  let linearMean: Float64Array | null = null;

  return {
    update(powerLevelsDb: Float32Array): Float32Array {
      if (!linearMean) {
        linearMean = new Float64Array(bins);
        for (let i = 0; i < bins; i += 1) {
          linearMean[i] = 10 ** (powerLevelsDb[i] / 10);
        }
      } else {
        for (let i = 0; i < bins; i += 1) {
          const sampleLinear = 10 ** (powerLevelsDb[i] / 10);
          linearMean[i] = (1 - alpha) * linearMean[i] + alpha * sampleLinear;
        }
      }

      const output = new Float32Array(bins);
      for (let i = 0; i < bins; i += 1) {
        output[i] = 10 * Math.log10(linearMean[i]);
      }
      return output;
    },
    reset() {
      linearMean = null;
    },
  };
};
