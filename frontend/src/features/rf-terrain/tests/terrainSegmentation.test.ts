import { describe, expect, it } from 'vitest';
import { segmentExcessMatrix } from '../engine/terrainSegmentation';

const rowsOf = (grid: number[][]) => grid.map((r) => Float32Array.from(r));

describe('segmentExcessMatrix', () => {
  it('a continuous carrier (same bin, every row) yields one long ridge-shaped component', () => {
    const rows = rowsOf(Array.from({ length: 10 }, () => [0, 0, 20, 0, 0]));
    const { components } = segmentExcessMatrix(rows, 6);
    expect(components).toHaveLength(1);
    expect(components[0].minRow).toBe(0);
    expect(components[0].maxRow).toBe(9);
    expect(components[0].minCol).toBe(2);
    expect(components[0].maxCol).toBe(2);
  });

  it('a single-row burst yields one short island, not a ridge', () => {
    const rows = rowsOf([[0, 0, 0], [0, 20, 0], [0, 0, 0]]);
    const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1 });
    expect(components).toHaveLength(1);
    expect(components[0].minRow).toBe(1);
    expect(components[0].maxRow).toBe(1);
  });

  it('frequency-hopping (disjoint bins across time) yields multiple separate islands', () => {
    const rows = rowsOf([
      [20, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 20],
      [0, 0, 0, 0, 0],
      [0, 20, 0, 0, 0],
    ]);
    const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1 });
    expect(components).toHaveLength(3);
  });

  it('a wideband plateau (many adjacent active bins, few rows) yields one broad, short component', () => {
    const rows = rowsOf([
      [20, 20, 20, 20, 20, 20],
      [20, 20, 20, 20, 20, 20],
    ]);
    const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1 });
    expect(components).toHaveLength(1);
    expect(components[0].maxCol - components[0].minCol).toBe(5);
    expect(components[0].maxRow - components[0].minRow).toBe(1);
  });

  it('never emits a component below minCellCount', () => {
    const rows = rowsOf([[0, 20, 0], [0, 0, 0]]);
    const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 5 });
    expect(components).toHaveLength(0);
  });

  it('does not classify shape into a protocol label -- only morphological bounds/stats', () => {
    const rows = rowsOf(Array.from({ length: 5 }, () => [0, 20, 0]));
    const { components } = segmentExcessMatrix(rows, 6);
    expect(components[0]).not.toHaveProperty('label');
    expect(components[0]).not.toHaveProperty('protocol');
  });

  describe('hysteresis (dual threshold)', () => {
    it('a lone weak cell (above grow, below seed) forms no component -- it never had a seed', () => {
      const rows = rowsOf([[0, 8, 0], [0, 0, 0]]);
      const { components } = segmentExcessMatrix(rows, 15, 6, { minCellCount: 1 });
      expect(components).toHaveLength(0);
    });

    it('a weak cell touching a strong seed is absorbed into the same component', () => {
      // Column 1 dips to 8 dB (below the 15 dB seed threshold, above the 6
      // dB grow threshold) in the middle row -- single-threshold
      // segmentation at 15 dB would fracture this into two ridges.
      const rows = rowsOf([[0, 20, 0], [0, 8, 0], [0, 20, 0]]);
      const { components } = segmentExcessMatrix(rows, 15, 6, { minCellCount: 1 });
      expect(components).toHaveLength(1);
      expect(components[0].minRow).toBe(0);
      expect(components[0].maxRow).toBe(2);
    });

    it('a weak region with no adjacent seed anywhere is never grown into a component', () => {
      const rows = rowsOf([[20, 0, 0, 0], [0, 0, 8, 0], [0, 0, 0, 0]]);
      const { components } = segmentExcessMatrix(rows, 15, 6, { minCellCount: 1 });
      expect(components).toHaveLength(1);
      expect(components[0].minCol).toBe(0);
      expect(components[0].maxCol).toBe(0);
    });
  });

  describe('8-connectivity', () => {
    it('merges a purely diagonal run into one ridge instead of fragmenting it', () => {
      const rows = rowsOf([
        [20, 0, 0, 0],
        [0, 20, 0, 0],
        [0, 0, 20, 0],
        [0, 0, 0, 20],
      ]);
      const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1 });
      expect(components).toHaveLength(1);
      expect(components[0].cellCount).toBe(4);
    });
  });

  describe('physical filters', () => {
    it('rejects a component narrower than minColSpan even if minCellCount passes', () => {
      const rows = rowsOf(Array.from({ length: 6 }, () => [0, 20, 0]));
      const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1, minColSpan: 2 });
      expect(components).toHaveLength(0);
    });

    it('rejects a component whose peak excess never clears minPeakExcessDb', () => {
      const rows = rowsOf([[0, 7, 0], [0, 7, 0]]);
      const { components } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1, minPeakExcessDb: 15 });
      expect(components).toHaveLength(0);
    });
  });

  describe('labelGrid', () => {
    it('assigns every accepted cell its component index and leaves background cells at -1', () => {
      const rows = rowsOf([
        [20, 0, 0, 20],
        [20, 0, 0, 20],
      ]);
      const { components, labelGrid, rows: gridRows, cols } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 1 });
      expect(components).toHaveLength(2);
      expect(gridRows).toBe(2);
      expect(cols).toBe(4);
      // Background cells (column 1/2) never belong to any object.
      expect(labelGrid[0 * cols + 1]).toBe(-1);
      expect(labelGrid[0 * cols + 2]).toBe(-1);
      // Both cells of the left-hand ridge share one component index.
      expect(labelGrid[0 * cols + 0]).toBe(labelGrid[1 * cols + 0]);
      expect(labelGrid[0 * cols + 0]).toBeGreaterThanOrEqual(0);
      // The two ridges are different components.
      expect(labelGrid[0 * cols + 0]).not.toBe(labelGrid[0 * cols + 3]);
    });

    it('a rejected (filtered-out) component leaves its cells at -1 in labelGrid', () => {
      const rows = rowsOf([[0, 20, 0]]);
      const { components, labelGrid } = segmentExcessMatrix(rows, 6, 6, { minCellCount: 5 });
      expect(components).toHaveLength(0);
      expect(Array.from(labelGrid)).toEqual([-1, -1, -1]);
    });
  });
});
