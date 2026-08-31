import { describe, expect, it } from 'vitest';
import { createEwmaEngine } from '../engine/ewmaEngine';

describe('createEwmaEngine', () => {
  it('the first sample is returned unchanged (no prior state to blend with)', () => {
    const engine = createEwmaEngine(1, 0.3);
    expect(engine.update(new Float32Array([-42]))[0]).toBeCloseTo(-42, 5);
  });

  it('respects alpha exactly (dB-domain, distinct from the linear-domain average engine)', () => {
    const engine = createEwmaEngine(1, 0.5);
    engine.update(new Float32Array([-100]));
    const result = engine.update(new Float32Array([-80]))[0];
    // S_t = 0.5*(-80) + 0.5*(-100) = -90, plain dB-domain arithmetic --
    // deliberately NOT the linear-power-domain formula createAverageEngine uses.
    expect(result).toBeCloseTo(-90, 5);
  });

  it('reset() forgets prior state', () => {
    const engine = createEwmaEngine(1, 0.5);
    engine.update(new Float32Array([-10]));
    engine.reset();
    expect(engine.update(new Float32Array([-90]))[0]).toBeCloseTo(-90, 5);
  });
});
