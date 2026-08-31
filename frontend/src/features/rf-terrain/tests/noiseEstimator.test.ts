import { describe, expect, it } from 'vitest';
import { createNoiseEstimator } from '../engine/noiseEstimator';

describe('createNoiseEstimator', () => {
  it('converges toward the P20 floor of a noise-only signal', () => {
    const estimator = createNoiseEstimator({ bins: 1, quantile: 0.2, windowSamples: 20, smoothingBeta: 0.5 });
    // Deterministic pseudo-noise around -90 dB so the test has no flake risk.
    const samples = [-88, -92, -85, -91, -89, -93, -86, -90, -94, -87, -90, -91, -88, -92, -89, -90, -91, -88, -93, -90];
    let last = new Float32Array(1);
    for (const value of samples) {
      last = estimator.update(new Float32Array([value]));
    }
    // The true P20 of this sample set is around -92/-93; after smoothing it
    // should sit well below the mean (-89.75) without chasing outliers.
    expect(last[0]).toBeLessThan(-89.75);
    expect(last[0]).toBeGreaterThan(-95);
  });

  it('rises when the noise floor itself steps up', () => {
    const estimator = createNoiseEstimator({ bins: 1, quantile: 0.2, windowSamples: 10, smoothingBeta: 0.3 });
    for (let i = 0; i < 30; i += 1) estimator.update(new Float32Array([-90]));
    const beforeStep = estimator.update(new Float32Array([-90]))[0];
    for (let i = 0; i < 30; i += 1) estimator.update(new Float32Array([-70]));
    const afterStep = estimator.update(new Float32Array([-70]))[0];
    expect(afterStep).toBeGreaterThan(beforeStep);
  });

  it('a continuously-present signal across the whole window gets absorbed into the baseline (documented limitation)', () => {
    const estimator = createNoiseEstimator({ bins: 1, quantile: 0.2, windowSamples: 10, smoothingBeta: 0.2 });
    let last = new Float32Array(1);
    for (let i = 0; i < 50; i += 1) last = estimator.update(new Float32Array([-40]));
    // A continuous carrier eventually reads as its own floor -- this
    // documents the known limitation rather than asserting it away.
    expect(last[0]).toBeGreaterThan(-45);
  });

  it('reset() forgets prior samples', () => {
    const estimator = createNoiseEstimator({ bins: 1, quantile: 0.2, windowSamples: 5, smoothingBeta: 0.5 });
    for (let i = 0; i < 10; i += 1) estimator.update(new Float32Array([-40]));
    estimator.reset();
    const first = estimator.update(new Float32Array([-90]));
    expect(first[0]).toBe(-90);
  });

  it('operates independently per bin', () => {
    const estimator = createNoiseEstimator({ bins: 2, quantile: 0.2, windowSamples: 5, smoothingBeta: 0.5 });
    let last = new Float32Array(2);
    for (let i = 0; i < 10; i += 1) last = estimator.update(new Float32Array([-90, -40]));
    expect(last[0]).toBeLessThan(last[1]);
  });
});
