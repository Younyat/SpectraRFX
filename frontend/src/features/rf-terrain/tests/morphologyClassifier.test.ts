import { describe, expect, it } from 'vitest';
import { classifyMorphology } from '../engine/morphologyClassifier';

describe('classifyMorphology', () => {
  it('a fast-moving ridge (chirp-like slope) is DRIFTING regardless of shape', () => {
    expect(classifyMorphology({ rowSpan: 10, colSpan: 10, cellCount: 100, ridgeSlopeHzPerSecond: 5000 })).toBe('DRIFTING');
    expect(classifyMorphology({ rowSpan: 10, colSpan: 10, cellCount: 100, ridgeSlopeHzPerSecond: -5000 })).toBe('DRIFTING');
  });

  it('a sparse, holey bounding box is IRREGULAR', () => {
    expect(classifyMorphology({ rowSpan: 10, colSpan: 10, cellCount: 10, ridgeSlopeHzPerSecond: 0 })).toBe('IRREGULAR');
  });

  it('a single-row detection is TRANSIENT', () => {
    expect(classifyMorphology({ rowSpan: 1, colSpan: 1, cellCount: 1, ridgeSlopeHzPerSecond: null })).toBe('TRANSIENT');
  });

  it('wide and short is a PLATEAU (wideband burst)', () => {
    expect(classifyMorphology({ rowSpan: 2, colSpan: 8, cellCount: 16, ridgeSlopeHzPerSecond: 0 })).toBe('PLATEAU');
  });

  it('narrow and long-lived is a RIDGE (continuous carrier)', () => {
    expect(classifyMorphology({ rowSpan: 20, colSpan: 1, cellCount: 20, ridgeSlopeHzPerSecond: 0 })).toBe('RIDGE');
  });

  it('narrow and brief (but more than one row) is an ISLAND', () => {
    expect(classifyMorphology({ rowSpan: 3, colSpan: 1, cellCount: 3, ridgeSlopeHzPerSecond: 0 })).toBe('ISLAND');
  });

  it('never returns a protocol/device-shaped value', () => {
    const result = classifyMorphology({ rowSpan: 5, colSpan: 5, cellCount: 25, ridgeSlopeHzPerSecond: 0 });
    expect(['RIDGE', 'ISLAND', 'PLATEAU', 'TRANSIENT', 'DRIFTING', 'IRREGULAR']).toContain(result);
  });
});
