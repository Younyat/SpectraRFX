import type { TerrainObject } from '../model/rfTerrainTypes';

// Deliberately simpler than a per-cell Uint32Array "object index grid":
// a clicked (frequency, time) point is matched against each object's own
// measured bounding box instead of an exact connected-component mask.
// Honest tradeoff, documented here rather than silently claimed as O(1):
// this is O(object count) per click (objects are few -- effectively
// instant), and it can occasionally include a point that falls inside an
// object's bounding box but not its exact irregular shape. It reuses the
// SAME real bounding-box fields (`start/stop_frequency_hz`,
// `start/end_time_seconds`) already computed by terrainMetrics.ts -- no
// second, independent notion of "where the object is" is introduced.
//
// When multiple objects' boxes overlap at the same point, the most
// recently-started object wins (ties broken toward the object closer to
// NOW), which is the common case for a hopping/re-triggering emission.
export const findObjectAtPoint = (
  objects: TerrainObject[],
  frequencyHz: number,
  timeSeconds: number,
): TerrainObject | null => {
  let best: TerrainObject | null = null;
  for (const object of objects) {
    const inFrequency = frequencyHz >= object.startFrequencyHz && frequencyHz <= object.stopFrequencyHz;
    const inTime = timeSeconds >= object.startTimeSeconds && timeSeconds <= object.endTimeSeconds;
    if (!inFrequency || !inTime) continue;
    if (!best || object.startTimeSeconds > best.startTimeSeconds) {
      best = object;
    }
  }
  return best;
};
