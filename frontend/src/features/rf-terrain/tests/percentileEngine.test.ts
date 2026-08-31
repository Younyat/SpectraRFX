import { describe, expect, it } from 'vitest';
import { createPercentileEngine } from '../engine/percentileEngine';

describe('createPercentileEngine', () => {
  it('P50/P90/P95/P99 are monotonically non-decreasing for the same window', () => {
    const engine = createPercentileEngine(1, 20);
    let snapshot = { p50: new Float32Array(1), p90: new Float32Array(1), p95: new Float32Array(1), p99: new Float32Array(1) };
    const samples = [-90, -85, -60, -95, -70, -88, -50, -92, -65, -80];
    for (const value of samples) {
      snapshot = engine.update(new Float32Array([value]));
    }
    expect(snapshot.p50[0]).toBeLessThanOrEqual(snapshot.p90[0]);
    expect(snapshot.p90[0]).toBeLessThanOrEqual(snapshot.p95[0]);
    expect(snapshot.p95[0]).toBeLessThanOrEqual(snapshot.p99[0]);
  });

  it('P99 reflects the top of the window once enough strong samples enter it', () => {
    const engine = createPercentileEngine(1, 10);
    let snapshot = { p50: new Float32Array(1), p90: new Float32Array(1), p95: new Float32Array(1), p99: new Float32Array(1) };
    for (let i = 0; i < 8; i += 1) snapshot = engine.update(new Float32Array([-90]));
    for (let i = 0; i < 2; i += 1) snapshot = engine.update(new Float32Array([-20]));
    expect(snapshot.p99[0]).toBeCloseTo(-20, 5);
    expect(snapshot.p50[0]).toBeCloseTo(-90, 5);
  });

  it('reset() clears the rolling window', () => {
    const engine = createPercentileEngine(1, 5);
    for (let i = 0; i < 5; i += 1) engine.update(new Float32Array([-20]));
    engine.reset();
    const snapshot = engine.update(new Float32Array([-90]));
    expect(snapshot.p50[0]).toBeCloseTo(-90, 5);
  });
});
