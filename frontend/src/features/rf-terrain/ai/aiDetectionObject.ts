import type { AiLiveDetection, TerrainObject } from '../model/rfTerrainTypes';

// How long an AI detection stays selectable (its TerrainObject bounding
// box) and listed in the Inspector's "Objects" list -- matches roughly how
// long the 3D highlight box itself stays visible before aging out of the
// terrain's history window, so "if you can still see it, you can still
// click it" holds for both mechanisms even though they age independently
// (the 3D box via row-count, this object via wall-clock time).
export const AI_DETECTION_TIME_WINDOW_SECONDS = 20;

// Converts a real LIVE inference result into a TerrainObject so it flows
// through the SAME click-to-select/Inspector pipeline real segmented
// terrain objects already use (per spec: "si pulso en el lóbulo detectado
// me debería salir su información en el menú lateral... junto con info de
// objetos que ya tenía"). Geometric fields with no real measurement for a
// synthetic AI box (peakExcessDb, terrainVolumeIndex, cellCount, ...) are
// explicitly zeroed/null rather than guessed -- the Inspector must check
// `origin === 'AI_DETECTION'` before presenting them as real geometry.
export function buildAiDetectionTerrainObject(detection: AiLiveDetection): TerrainObject {
  const detectedAtSeconds = new Date(detection.detectedAtUtc).getTime() / 1000;
  const halfBandwidthHz = Math.max(detection.bandwidthHz, 1) / 2;
  return {
    id: detection.id,
    trackId: detection.id,
    startTimeSeconds: detectedAtSeconds - AI_DETECTION_TIME_WINDOW_SECONDS,
    endTimeSeconds: detectedAtSeconds + AI_DETECTION_TIME_WINDOW_SECONDS,
    durationSeconds: AI_DETECTION_TIME_WINDOW_SECONDS * 2,
    startFrequencyHz: detection.centerFrequencyHz - halfBandwidthHz,
    stopFrequencyHz: detection.centerFrequencyHz + halfBandwidthHz,
    centerFrequencyHz: detection.centerFrequencyHz,
    bandwidthHz: detection.bandwidthHz,
    peakExcessDb: 0,
    meanExcessDb: 0,
    frequencyCentroidHz: detection.centerFrequencyHz,
    temporalCentroidSeconds: detectedAtSeconds,
    terrainVolumeIndex: 0,
    ridgeSlopeHzPerSecond: null,
    cellCount: 0,
    // A box region has no real measured shape -- 'ISLAND' (a single
    // bounded region) is the least misleading default; the Inspector never
    // presents this as a real geometric classification for an AI object.
    morphology: 'ISLAND',
    active: true,
    origin: 'AI_DETECTION',
    aiDetection: {
      modelId: detection.modelId,
      modelName: detection.modelName,
      summary: detection.summary,
      detectedAtUtc: detection.detectedAtUtc,
      totalLatencyMs: detection.totalLatencyMs,
      predictedClass: detection.predictedClass,
      classDescription: detection.classDescription,
      bandwidthIsKnown: detection.bandwidthIsKnown,
    },
  };
}

// Drops AI-detection objects whose clickable time window has fully
// elapsed relative to `nowSeconds` -- keeps the merged objects list (and
// the Inspector's "Objects (N)" count) from growing forever across a long
// continuous-mode session.
export function pruneExpiredAiDetectionObjects(objects: TerrainObject[], nowSeconds: number): TerrainObject[] {
  return objects.filter((object) => object.origin !== 'AI_DETECTION' || object.endTimeSeconds >= nowSeconds);
}
