import { describe, expect, it } from 'vitest';
import { createPersistenceEngine } from '../engine/persistenceEngine';

describe('createPersistenceEngine', () => {
  it('rises toward 1 for a continuously active bin and decays toward 0 once inactive', () => {
    const engine = createPersistenceEngine({ bins: 1, thresholdDb: 6, tauSeconds: 1 });
    let value = 0;
    for (let i = 0; i < 20; i += 1) value = engine.update(new Float32Array([20]), 0.5)[0];
    expect(value).toBeGreaterThan(0.9);

    for (let i = 0; i < 20; i += 1) value = engine.update(new Float32Array([0]), 0.5)[0];
    expect(value).toBeLessThan(0.1);
  });

  it('a single impulsive burst leaves persistence low even though it was momentarily active', () => {
    const engine = createPersistenceEngine({ bins: 1, thresholdDb: 6, tauSeconds: 2 });
    engine.update(new Float32Array([0]), 1);
    engine.update(new Float32Array([0]), 1);
    const afterBurst = engine.update(new Float32Array([30]), 1)[0];
    expect(afterBurst).toBeLessThan(0.5);
  });

  it('is time-aware: identical activation over a longer real Δt moves persistence further', () => {
    const fast = createPersistenceEngine({ bins: 1, thresholdDb: 6, tauSeconds: 2 });
    const slow = createPersistenceEngine({ bins: 1, thresholdDb: 6, tauSeconds: 2 });
    const fastValue = fast.update(new Float32Array([20]), 0.1)[0];
    const slowValue = slow.update(new Float32Array([20]), 5)[0];
    expect(slowValue).toBeGreaterThan(fastValue);
  });

  it('reset() returns persistence to zero', () => {
    const engine = createPersistenceEngine({ bins: 1, thresholdDb: 6, tauSeconds: 1 });
    for (let i = 0; i < 10; i += 1) engine.update(new Float32Array([20]), 1);
    engine.reset();
    expect(engine.update(new Float32Array([0]), 0.001)[0]).toBeCloseTo(0, 5);
  });
});
