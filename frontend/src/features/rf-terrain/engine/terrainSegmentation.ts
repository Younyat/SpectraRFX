export interface TerrainComponent {
  minRow: number;
  maxRow: number;
  minCol: number;
  maxCol: number;
  cellCount: number;
  peakExcessDb: number;
  peakCol: number;
  peakRow: number;
  sumExcessDb: number;
  sumExcessAboveThresholdDb: number;
  ridgePeakByRow: Map<number, number>;
}

export interface SegmentationResult {
  components: TerrainComponent[];
  // Int32Array(rows*cols), row-major: component's index into `components`,
  // or -1 for cells that belong to no object. Lets a caller resolve an
  // exact clicked cell to an object without re-running segmentation or
  // shipping the full excess matrix -- only ever read inside the worker
  // (or in tests), never sent over postMessage in bulk (spec-adjacent
  // "don't transmit ~120k values continuously" constraint).
  labelGrid: Int32Array;
  rows: number;
  cols: number;
}

export interface SegmentationFilters {
  // Minimum connected cell count -- the original single guard.
  minCellCount: number;
  // Minimum span in rows/cols -- rejects single-cell noise spikes that
  // happen to clear minCellCount only via a thin diagonal run.
  minRowSpan: number;
  minColSpan: number;
  // Minimum peak excess -- a component whose strongest cell barely clears
  // the seed threshold is more likely a threshold-boundary artifact than a
  // real emission.
  minPeakExcessDb: number;
}

export const DEFAULT_SEGMENTATION_FILTERS: SegmentationFilters = {
  minCellCount: 2,
  minRowSpan: 0,
  minColSpan: 0,
  minPeakExcessDb: -Infinity,
};

// 8-connected neighborhood (includes diagonals): a diagonally-drifting
// chirp ridge is one continuous physical emission, and 4-connectivity alone
// can fragment it into several disconnected components whenever the ridge
// crosses exactly one bin per one row with no shared edge, only a shared
// corner. Diagonal adjacency is still LOCAL (one cell away) -- this does
// not merge distant, unrelated regions.
const NEIGHBOR_OFFSETS: ReadonlyArray<[number, number]> = [
  [-1, -1], [-1, 0], [-1, 1],
  [0, -1], [0, 1],
  [1, -1], [1, 0], [1, 1],
];

// Morphological terrain object segmentation (spec §22), extended with
// hysteresis (dual-threshold) flood fill -- the same idea Canny edge
// detection uses: a component must contain at least one cell above the
// SEED threshold (theta_H) to be created at all, but once seeded it grows
// through any neighbor above the lower GROW threshold (theta_L < theta_H).
// This absorbs the small dips a single noisy emission naturally has
// (which theta_H alone would fracture into many separate slivers) without
// lowering the bar for what counts as "real" in the first place. Passing
// growThresholdDb === seedThresholdDb reproduces the original single-
// threshold behavior exactly.
//
// Output is morphology only -- no protocol/device labeling, per the spec's
// explicit instruction not to infer BLE/Wi-Fi/LoRa/radar identity from
// shape alone.
export const segmentExcessMatrix = (
  excessRows: Float32Array[],
  seedThresholdDb: number,
  growThresholdDb: number = seedThresholdDb,
  filters: Partial<SegmentationFilters> = {},
): SegmentationResult => {
  const resolvedFilters: SegmentationFilters = { ...DEFAULT_SEGMENTATION_FILTERS, ...filters };
  const rows = excessRows.length;
  if (rows === 0) {
    return { components: [], labelGrid: new Int32Array(0), rows: 0, cols: 0 };
  }
  const cols = excessRows[0].length;
  const visited = new Uint8Array(rows * cols);
  const labelGrid = new Int32Array(rows * cols).fill(-1);
  const components: TerrainComponent[] = [];

  const at = (r: number, c: number) => excessRows[r][c];

  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const flatIndex = r * cols + c;
      if (visited[flatIndex] || at(r, c) <= seedThresholdDb) {
        continue;
      }

      // Flood fill over the 8-connected region reachable through cells
      // above the (lower) grow threshold -- the seed check above only
      // gates whether a NEW component starts here.
      const stack: Array<[number, number]> = [[r, c]];
      visited[flatIndex] = 1;
      let minRow = r; let maxRow = r; let minCol = c; let maxCol = c;
      let cellCount = 0; let sumExcessDb = 0; let sumExcessAboveThresholdDb = 0; let peakExcessDb = -Infinity;
      let peakRow = r; let peakCol = c;
      const ridgePeakByRow = new Map<number, number>();
      const cellFlatIndices: number[] = [];

      while (stack.length > 0) {
        const [cr, cc] = stack.pop()!;
        const value = at(cr, cc);
        cellCount += 1;
        sumExcessDb += value;
        sumExcessAboveThresholdDb += value - growThresholdDb;
        cellFlatIndices.push(cr * cols + cc);
        if (value > peakExcessDb) {
          peakExcessDb = value; peakRow = cr; peakCol = cc;
        }
        const rowPeak = ridgePeakByRow.get(cr);
        if (rowPeak === undefined || value > at(cr, rowPeak)) {
          ridgePeakByRow.set(cr, cc);
        }
        minRow = Math.min(minRow, cr); maxRow = Math.max(maxRow, cr);
        minCol = Math.min(minCol, cc); maxCol = Math.max(maxCol, cc);

        for (const [dr, dc] of NEIGHBOR_OFFSETS) {
          const nr = cr + dr; const nc = cc + dc;
          if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
          const neighborFlat = nr * cols + nc;
          if (visited[neighborFlat] || at(nr, nc) <= growThresholdDb) continue;
          visited[neighborFlat] = 1;
          stack.push([nr, nc]);
        }
      }

      const rowSpan = maxRow - minRow + 1;
      const colSpan = maxCol - minCol + 1;
      if (
        cellCount >= resolvedFilters.minCellCount &&
        rowSpan >= resolvedFilters.minRowSpan &&
        colSpan >= resolvedFilters.minColSpan &&
        peakExcessDb >= resolvedFilters.minPeakExcessDb
      ) {
        const componentIndex = components.length;
        for (const flat of cellFlatIndices) {
          labelGrid[flat] = componentIndex;
        }
        components.push({ minRow, maxRow, minCol, maxCol, cellCount, peakExcessDb, peakCol, peakRow, sumExcessDb, sumExcessAboveThresholdDb, ridgePeakByRow });
      }
      // Cells belonging to a rejected component stay `visited` (never
      // re-examined) but keep labelGrid === -1 -- correctly "no object".
    }
  }

  return { components, labelGrid, rows, cols };
};
