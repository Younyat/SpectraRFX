import { describe, expect, it } from 'vitest';
import { createOccupancyEngine } from '../engine/occupancyEngine';

describe('createOccupancyEngine', () => {
  it('approaches 100% for a bin active on every update', () => {
    const engine = createOccupancyEngine({ bins: 1, thresholdDb: 6, tauSeconds: 5 });
    let value = 0;
    for (let i = 0; i < 100; i += 1) value = engine.update(new Float32Array([20]), 0.5)[0];
    expect(value).toBeGreaterThan(0.95);
  });

  it('approaches 0% for a bin that never crosses the threshold', () => {
    const engine = createOccupancyEngine({ bins: 1, thresholdDb: 6, tauSeconds: 5 });
    let value = 1;
    for (let i = 0; i < 100; i += 1) value = engine.update(new Float32Array([0]), 0.5)[0];
    expect(value).toBeLessThan(0.05);
  });

  it('is driven by real Δt, not update/frame count -- irregular jitter still converges to the same ratio', () => {
    const regular = createOccupancyEngine({ bins: 1, thresholdDb: 6, tauSeconds: 10 });
    const jittered = createOccupancyEngine({ bins: 1, thresholdDb: 6, tauSeconds: 10 });

    // Same total elapsed time (40s), same total active time (20s): regular
    // cadence (40 x 1s) vs jittered cadence (variable dt, same active ratio).
    for (let i = 0; i < 40; i += 1) regular.update(new Float32Array([i % 2 === 0 ? 20 : 0]), 1);
    const jitterPattern = [0.5, 1.5, 0.2, 1.8, 1, 1, 3, 1];
    let toggle = true;
    let elapsed = 0;
    while (elapsed < 40) {
      const dt = jitterPattern[Math.floor(elapsed) % jitterPattern.length];
      jittered.update(new Float32Array([toggle ? 20 : 0]), dt);
      toggle = !toggle;
      elapsed += dt;
    }

    const regularValue = regular.update(new Float32Array([20]), 0.001)[0];
    const jitteredValue = jittered.update(new Float32Array([20]), 0.001)[0];
    expect(Math.abs(regularValue - jitteredValue)).toBeLessThan(0.25);
  });

  it('reset() returns occupancy to zero', () => {
    const engine = createOccupancyEngine({ bins: 1, thresholdDb: 6, tauSeconds: 5 });
    for (let i = 0; i < 20; i += 1) engine.update(new Float32Array([20]), 1);
    engine.reset();
    expect(engine.update(new Float32Array([0]), 0.001)[0]).toBeCloseTo(0, 5);
  });
});
