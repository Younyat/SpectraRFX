import { describe, expect, it } from 'vitest';
import { createHoldEngine } from '../engine/holdEngine';

describe('createHoldEngine', () => {
  it('maintains Min <= Live <= Max across a random-ish sequence', () => {
    const engine = createHoldEngine(1);
    const samples = [-80, -60, -95, -50, -70, -99, -40, -85];
    for (const sample of samples) {
      const { maxHold, minHold } = engine.update(new Float32Array([sample]));
      expect(minHold[0]).toBeLessThanOrEqual(sample + 1e-9);
      expect(maxHold[0]).toBeGreaterThanOrEqual(sample - 1e-9);
    }
  });

  it('maxHold never decreases and minHold never increases', () => {
    const engine = createHoldEngine(1);
    let prevMax = -Infinity;
    let prevMin = Infinity;
    for (const sample of [-80, -60, -95, -50, -70]) {
      const { maxHold, minHold } = engine.update(new Float32Array([sample]));
      expect(maxHold[0]).toBeGreaterThanOrEqual(prevMax);
      expect(minHold[0]).toBeLessThanOrEqual(prevMin);
      prevMax = maxHold[0]; prevMin = minHold[0];
    }
  });

  it('reset() clears accumulated holds', () => {
    const engine = createHoldEngine(1);
    engine.update(new Float32Array([-40]));
    engine.reset();
    const { maxHold, minHold } = engine.update(new Float32Array([-70]));
    expect(maxHold[0]).toBe(-70);
    expect(minHold[0]).toBe(-70);
  });
});
