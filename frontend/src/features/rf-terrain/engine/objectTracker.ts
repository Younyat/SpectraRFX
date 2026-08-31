import type { TerrainObject } from '../model/rfTerrainTypes';

// Cross-pass object identity. Every SEGMENT pass re-segments the whole
// bounded history window from scratch (terrainWorkerState.ts) -- there is
// no incremental object state to carry forward inside segmentation itself.
// What DOES carry forward, and is real/measured rather than re-derived, is
// each object's own (frequency, time) footprint: a persisting emission's
// bounding box only grows or slides slightly between one pass and the
// next, so matching on real frequency-range overlap (never on `id`, which
// is recomputed fresh every pass) is enough to give it a stable `trackId`.
interface Lineage {
  trackId: string;
  lastCenterFrequencyHz: number;
  lastBandwidthHz: number;
  lastEndTimeSeconds: number;
  reactivationCount: number;
}

export interface ObjectTrackerOptions {
  // Minimum frequency-range overlap (as a fraction of the larger of the
  // two bandwidths) to call a new object "the same persisting emission"
  // as a lineage from the previous pass.
  frequencyOverlapRatioThreshold?: number;
  // A frequency-overlapping object only counts as "still the same,
  // continuously-going object" (rather than a later re-trigger, see
  // below) if it starts within this many seconds of the lineage's last
  // known end -- a small allowance above the SEGMENT cadence, so back-to-
  // back passes over one uninterrupted emission still match. A gap wider
  // than this, even at the exact same frequency, is treated as the
  // emission having genuinely ended and possibly restarted later.
  continuityWindowSeconds?: number;
  // A new object with no CONTINUOUS lineage match, appearing within this
  // many seconds of a recently-ended lineage and close to it in
  // frequency, is treated as a re-trigger of that lineage rather than a
  // brand-new track (spec-adjacent hopping/re-triggering signature) --
  // heuristic, not a certainty; documented, never silently upgraded to a
  // device claim.
  reactivationWindowSeconds?: number;
  reactivationFrequencyToleranceHz?: number;
  // Once a lineage has been re-triggered at least this many times, its
  // morphology is overridden to HOPPING_CLUSTER regardless of any single
  // detection's own shape.
  reactivationsForHoppingCluster?: number;
}

const DEFAULTS: Required<ObjectTrackerOptions> = {
  frequencyOverlapRatioThreshold: 0.3,
  continuityWindowSeconds: 3,
  reactivationWindowSeconds: 10,
  reactivationFrequencyToleranceHz: 500_000,
  reactivationsForHoppingCluster: 2,
};

const frequencyOverlapRatio = (aStartHz: number, aStopHz: number, bStartHz: number, bStopHz: number): number => {
  const overlap = Math.max(0, Math.min(aStopHz, bStopHz) - Math.max(aStartHz, bStartHz));
  const largerSpan = Math.max(aStopHz - aStartHz, bStopHz - bStartHz, 1);
  return overlap / largerSpan;
};

// Factory (matches the rest of this module's engine convention --
// createNoiseEstimator, createPersistenceEngine, etc.): owns lineage state
// across repeated `assignTracks` calls so it can be unit-tested directly
// without a real Worker.
export const createObjectTracker = (options: ObjectTrackerOptions = {}) => {
  const opts: Required<ObjectTrackerOptions> = { ...DEFAULTS, ...options };
  let nextTrackNumber = 1;
  let lineages: Lineage[] = [];

  const mintTrackId = (): string => {
    const id = `RF-TRACK-${String(nextTrackNumber).padStart(6, '0')}`;
    nextTrackNumber += 1;
    return id;
  };

  // Assigns a stable `trackId`, `active`, and (only on repeated
  // re-triggering) an overridden `morphology` to every object in the
  // CURRENT segmentation pass. `objects` should already carry their
  // intrinsic per-shape morphology from terrainMetrics.ts -- this only
  // ever overrides it to HOPPING_CLUSTER, never any other value.
  const assignTracks = (objects: TerrainObject[]): TerrainObject[] => {
    const latestEndTimeSeconds = objects.reduce((max, object) => Math.max(max, object.endTimeSeconds), -Infinity);
    const claimed = new Set<string>();
    const nextLineages: Lineage[] = [];

    const tracked = objects.map((object): TerrainObject => {
      let bestLineage: Lineage | null = null;
      let bestScore = 0;
      for (const lineage of lineages) {
        if (claimed.has(lineage.trackId)) continue;
        // Only a small, cadence-sized gap counts as "still the same
        // object" -- a wider gap falls through to the reactivation check
        // below even at an identical frequency, so a real re-trigger
        // (e.g. hopping back to the same channel) is never silently
        // absorbed as one uninterrupted emission.
        if (object.startTimeSeconds - lineage.lastEndTimeSeconds > opts.continuityWindowSeconds) continue;
        const bandwidthHalf = lineage.lastBandwidthHz / 2;
        const ratio = frequencyOverlapRatio(
          object.startFrequencyHz, object.stopFrequencyHz,
          lineage.lastCenterFrequencyHz - bandwidthHalf, lineage.lastCenterFrequencyHz + bandwidthHalf,
        );
        if (ratio >= opts.frequencyOverlapRatioThreshold && ratio > bestScore) {
          bestLineage = lineage;
          bestScore = ratio;
        }
      }

      let trackId: string;
      let reactivationCount: number;

      if (bestLineage) {
        trackId = bestLineage.trackId;
        reactivationCount = bestLineage.reactivationCount;
      } else {
        const recentlyEnded = lineages.find((lineage) =>
          !claimed.has(lineage.trackId) &&
          object.startTimeSeconds - lineage.lastEndTimeSeconds >= 0 &&
          object.startTimeSeconds - lineage.lastEndTimeSeconds <= opts.reactivationWindowSeconds &&
          Math.abs(object.centerFrequencyHz - lineage.lastCenterFrequencyHz) <= opts.reactivationFrequencyToleranceHz);

        if (recentlyEnded) {
          trackId = recentlyEnded.trackId;
          reactivationCount = recentlyEnded.reactivationCount + 1;
        } else {
          trackId = mintTrackId();
          reactivationCount = 0;
        }
      }

      claimed.add(trackId);
      const active = object.endTimeSeconds >= latestEndTimeSeconds;
      const morphology = reactivationCount >= opts.reactivationsForHoppingCluster ? 'HOPPING_CLUSTER' : object.morphology;

      nextLineages.push({
        trackId,
        lastCenterFrequencyHz: object.centerFrequencyHz,
        lastBandwidthHz: object.bandwidthHz,
        lastEndTimeSeconds: object.endTimeSeconds,
        reactivationCount,
      });

      return { ...object, trackId, active, morphology };
    });

    // Carry forward any lineage NOT re-detected this pass but still
    // within the reactivation window -- otherwise a lineage that briefly
    // stops being detected (the exact case reactivation exists to catch)
    // would be forgotten the instant it first drops out, and could never
    // be reactivated at all.
    for (const lineage of lineages) {
      if (claimed.has(lineage.trackId)) continue;
      if (latestEndTimeSeconds - lineage.lastEndTimeSeconds <= opts.reactivationWindowSeconds) {
        nextLineages.push(lineage);
      }
    }

    lineages = nextLineages;
    return tracked;
  };

  const reset = () => {
    nextTrackNumber = 1;
    lineages = [];
  };

  return { assignTracks, reset };
};
