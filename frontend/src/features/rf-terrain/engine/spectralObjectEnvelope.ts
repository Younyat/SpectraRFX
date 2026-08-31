// Spectral Object Envelope (SOE): a smoothed, masked surface patch built
// ONLY for the currently-selected terrain object, ONLY at selection time
// (never per-frame) -- a visual reconstruction layered ON TOP of the
// scientific terrain, never a replacement for it. The underlying terrain
// keeps rendering the raw, un-smoothed 512-bin excess grid exactly as
// measured; this only ever affects the small gold overlay patch.
//
// Documented approximation: without the worker's exact per-cell
// connected-component mask (a real `Uint32Array` label grid exists inside
// the worker's segmentation pass, see terrainSegmentation.ts, but is
// deliberately never shipped to the main thread in bulk -- same "why" as
// the bounding-box click hit-test tradeoff in objectSelection.ts), a
// cell's envelope membership is approximated here by a simple local
// magnitude gate (excess > growThresholdDb) rather than the object's
// exact irregular flood-filled shape. This can occasionally include a
// cell that is inside the object's bounding box but not its true
// connected shape -- an honest, small approximation, not a silent one.
export interface EnvelopeSourceRow {
  // Mesh-space row index (0 = NOW/front) at the moment the envelope is
  // built -- the SAME convention TerrainMesh/TerrainRaycaster already use.
  meshRow: number;
  excessDb: number[];
  frequencyHz: number[];
}

export interface SpectralObjectEnvelope {
  subRows: number;
  subCols: number;
  // Mesh row (z) that local sub-row 0 corresponds to, at build time.
  meshRowOffset: number;
  // Global frequency-bin index that local sub-column 0 corresponds to.
  colOffset: number;
  // subRows*subCols, row-major. Raw excess-dB domain (NOT visually
  // scaled) -- scaling is applied by the renderer, matching every other
  // height value in this codebase (spec §7's unscaled-source-of-truth
  // discipline).
  heights: Float32Array;
  // Which cells are considered real object members after the local
  // magnitude gate -- callers use this to skip triangulating "no data"
  // cells rather than padding the envelope into a solid rectangle.
  mask: Uint8Array;
}

// 3x3 normalized-convolution kernel (Gaussian-shaped weights). Applied as
// a NORMALIZED convolution -- each cell's smoothed value is a weighted
// average of only its MASKED neighbors (unmasked neighbors contribute
// neither value nor weight), so the object's own edges stay sharp instead
// of being dragged toward zero by the surrounding background.
const KERNEL_OFFSETS: ReadonlyArray<readonly [number, number, number]> = [
  [-1, -1, 1], [-1, 0, 2], [-1, 1, 1],
  [0, -1, 2], [0, 0, 4], [0, 1, 2],
  [1, -1, 1], [1, 0, 2], [1, 1, 1],
];

const nearestBinIndex = (frequencyHz: number[], targetHz: number): number => {
  let best = 0;
  let bestDistance = Infinity;
  for (let i = 0; i < frequencyHz.length; i += 1) {
    const distance = Math.abs(frequencyHz[i] - targetHz);
    if (distance < bestDistance) { bestDistance = distance; best = i; }
  }
  return best;
};

export const buildSpectralObjectEnvelope = (
  rows: EnvelopeSourceRow[],
  startFrequencyHz: number,
  stopFrequencyHz: number,
  growThresholdDb: number,
): SpectralObjectEnvelope | null => {
  if (rows.length === 0) {
    return null;
  }

  const referenceFrequencies = rows[0].frequencyHz;
  const minCol = Math.min(nearestBinIndex(referenceFrequencies, startFrequencyHz), nearestBinIndex(referenceFrequencies, stopFrequencyHz));
  const maxCol = Math.max(nearestBinIndex(referenceFrequencies, startFrequencyHz), nearestBinIndex(referenceFrequencies, stopFrequencyHz));
  const subCols = maxCol - minCol + 1;

  const meshRows = rows.map((row) => row.meshRow);
  const minMeshRow = Math.min(...meshRows);
  const maxMeshRow = Math.max(...meshRows);
  const subRows = maxMeshRow - minMeshRow + 1;

  // Too small to form any triangle -- caller should fall back to the
  // point reticle alone rather than render a degenerate sliver.
  if (subRows < 2 || subCols < 2) {
    return null;
  }

  const byMeshRow = new Map(rows.map((row) => [row.meshRow, row]));
  const rawExcess = new Float32Array(subRows * subCols);
  const mask = new Uint8Array(subRows * subCols);

  for (let sr = 0; sr < subRows; sr += 1) {
    const rowData = byMeshRow.get(minMeshRow + sr);
    if (!rowData) continue;
    for (let sc = 0; sc < subCols; sc += 1) {
      const col = minCol + sc;
      const excess = rowData.excessDb[col] ?? 0;
      const idx = sr * subCols + sc;
      rawExcess[idx] = excess;
      mask[idx] = excess > growThresholdDb ? 1 : 0;
    }
  }

  const heights = new Float32Array(subRows * subCols);
  for (let sr = 0; sr < subRows; sr += 1) {
    for (let sc = 0; sc < subCols; sc += 1) {
      const idx = sr * subCols + sc;
      if (!mask[idx]) continue;
      let weightedSum = 0;
      let weightTotal = 0;
      for (const [dr, dc, weight] of KERNEL_OFFSETS) {
        const nr = sr + dr; const nc = sc + dc;
        if (nr < 0 || nr >= subRows || nc < 0 || nc >= subCols) continue;
        const neighborIdx = nr * subCols + nc;
        if (!mask[neighborIdx]) continue;
        weightedSum += rawExcess[neighborIdx] * weight;
        weightTotal += weight;
      }
      heights[idx] = weightTotal > 0 ? weightedSum / weightTotal : rawExcess[idx];
    }
  }

  return { subRows, subCols, meshRowOffset: minMeshRow, colOffset: minCol, heights, mask };
};
