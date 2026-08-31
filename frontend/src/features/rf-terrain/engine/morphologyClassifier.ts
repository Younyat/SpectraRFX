// DERIVED morphological classification (never a protocol/device label) --
// a cheap, purely geometric read of a segmented component's own shape.
// Thresholds are documented starting points (like the rest of ARST's
// constants), not a calibrated model.
export type TerrainObjectMorphology =
  | 'RIDGE' | 'ISLAND' | 'PLATEAU' | 'TRANSIENT' | 'DRIFTING' | 'HOPPING_CLUSTER' | 'IRREGULAR';

export interface MorphologyInput {
  rowSpan: number;
  colSpan: number;
  cellCount: number;
  ridgeSlopeHzPerSecond: number | null;
}

// A stationary continuous carrier has a slope near 0 Hz/s; real chirps
// documented/tested elsewhere in this codebase move far faster than this.
const DRIFT_SLOPE_THRESHOLD_HZ_PER_SECOND = 2000;
// Below this connected-cell-fill ratio (cells / bounding-box area), the
// component's own bounding box is mostly empty -- a sparse, holey shape
// rather than a solid ridge/island/plateau.
const IRREGULAR_FILL_RATIO = 0.35;

// HOPPING_CLUSTER is never assigned here -- it requires cross-pass
// context (has this frequency neighborhood re-triggered repeatedly?) that
// a single component's own shape cannot answer. See objectTracker.ts,
// which overrides this base classification when it detects that pattern.
export const classifyMorphology = ({ rowSpan, colSpan, cellCount, ridgeSlopeHzPerSecond }: MorphologyInput): TerrainObjectMorphology => {
  if (ridgeSlopeHzPerSecond !== null && Math.abs(ridgeSlopeHzPerSecond) >= DRIFT_SLOPE_THRESHOLD_HZ_PER_SECOND) {
    return 'DRIFTING';
  }

  const boundingArea = Math.max(1, rowSpan * colSpan);
  const fillRatio = cellCount / boundingArea;
  if (fillRatio < IRREGULAR_FILL_RATIO) {
    return 'IRREGULAR';
  }

  if (rowSpan <= 1) {
    return 'TRANSIENT';
  }

  const wide = colSpan >= Math.max(4, rowSpan);
  const shortLived = rowSpan <= 3;
  if (wide && shortLived) {
    return 'PLATEAU';
  }

  const persistent = rowSpan >= Math.max(4, colSpan * 2);
  if (persistent) {
    return 'RIDGE';
  }

  return 'ISLAND';
};
