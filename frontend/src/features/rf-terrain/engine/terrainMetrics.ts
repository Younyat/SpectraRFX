import type { TerrainComponent } from './terrainSegmentation';
import { fitRidgeSlope } from './ridgeTracking';
import { classifyMorphology } from './morphologyClassifier';
import type { TerrainObject } from '../model/rfTerrainTypes';

// Per-object metrics (spec §37). Optional/later fields from the spec
// (spectral/temporal entropy, fragmentation, duty-cycle, frequency
// excursion, curvature) are not computed in this pass.
//
// `trackId` and `active` are left as placeholders here (filled in by
// engine/objectTracker.ts, which needs the FULL current+previous object
// lists to assign stable identity and detect re-triggering -- context a
// single component cannot see on its own).
export const buildTerrainObject = (
  id: string,
  component: TerrainComponent,
  frequencyHz: Float32Array,
  timestampsSeconds: number[],
  deltaFHz: number,
  deltaTSeconds: number,
): TerrainObject => {
  const startTimeSeconds = timestampsSeconds[component.minRow];
  const endTimeSeconds = timestampsSeconds[component.maxRow];
  const startFrequencyHz = frequencyHz[component.minCol];
  const stopFrequencyHz = frequencyHz[component.maxCol];

  const ridgePoints = [...component.ridgePeakByRow.entries()].map(([row, col]) => ({
    timestampSeconds: timestampsSeconds[row],
    frequencyHz: frequencyHz[col],
  }));
  const ridge = fitRidgeSlope(ridgePoints);

  let weightedFreqSum = 0;
  let weightedTimeSum = 0;
  for (const [row, col] of component.ridgePeakByRow) {
    weightedFreqSum += frequencyHz[col];
    weightedTimeSum += timestampsSeconds[row];
  }
  const rowCount = component.ridgePeakByRow.size || 1;
  const rowSpan = component.maxRow - component.minRow + 1;
  const colSpan = component.maxCol - component.minCol + 1;
  const morphology = classifyMorphology({
    rowSpan,
    colSpan,
    cellCount: component.cellCount,
    ridgeSlopeHzPerSecond: ridge?.slopeHzPerSecond ?? null,
  });

  return {
    id,
    trackId: '',
    active: false,
    morphology,
    startTimeSeconds,
    endTimeSeconds,
    durationSeconds: Math.max(0, endTimeSeconds - startTimeSeconds),
    startFrequencyHz,
    stopFrequencyHz,
    centerFrequencyHz: (startFrequencyHz + stopFrequencyHz) / 2,
    bandwidthHz: Math.max(0, stopFrequencyHz - startFrequencyHz),
    peakExcessDb: component.peakExcessDb,
    meanExcessDb: component.sumExcessDb / component.cellCount,
    frequencyCentroidHz: weightedFreqSum / rowCount,
    temporalCentroidSeconds: weightedTimeSum / rowCount,
    terrainVolumeIndex: Math.max(0, component.sumExcessAboveThresholdDb) * deltaFHz * deltaTSeconds,
    ridgeSlopeHzPerSecond: ridge?.slopeHzPerSecond ?? null,
    cellCount: component.cellCount,
  };
};
