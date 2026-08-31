import type { SpectrumData } from '../../../shared/types';
import type { TerrainInputFrame } from '../model/rfTerrainTypes';
import { resampleToBins } from '../engine/frequencyResampler';
import { RF_TERRAIN_DEFAULT_FREQUENCY_BINS } from '../model/rfTerrainConstants';

// Adapts an already-validated SpectrumData frame into the shape that
// crosses into the ring buffer / Web Worker, tagging it with the
// acquisition generation it belongs to (spec §12), and resampling both
// arrays to the fixed analysis/render bin count (spec §44 -- documented
// simplification: analysis runs on this resampled grid too, see
// rfTerrainConstants.ts).
export const adaptSpectrumFrame = (data: SpectrumData, generation: number, targetBins = RF_TERRAIN_DEFAULT_FREQUENCY_BINS): TerrainInputFrame => ({
  generation,
  timestamp: data.timestamp,
  centerFrequency: data.centerFrequency,
  span: data.span,
  frequencyArray: Array.from(resampleToBins(data.frequencyArray, targetBins)),
  powerLevels: Array.from(resampleToBins(data.powerLevels, targetBins)),
  sampleRateHz: data.sampleRateHz,
  fftSize: data.fftSize,
  requestedRbwHz: data.requestedRbwHz,
  effectiveRbwHz: data.effectiveRbwHz,
  powerUnit: data.powerUnit,
  sourceId: data.sourceId,
  deviceSerial: data.deviceSerial,
  calibrationId: data.calibrationId,
});
