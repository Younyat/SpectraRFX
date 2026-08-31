export interface RidgeSamplePoint {
  timestampSeconds: number;
  frequencyHz: number;
}

export interface RidgeFit {
  slopeHzPerSecond: number;
  interceptHz: number;
}

// Ridge dynamics (spec §21): v_f = df/dt, estimated by ordinary least
// squares over the object's per-row peak-frequency samples. Curvature is
// intentionally not computed in this pass (documented gap, not silently
// wrong) -- higher-order fits need more points per object than the current
// default history depth reliably provides.
export const fitRidgeSlope = (points: RidgeSamplePoint[]): RidgeFit | null => {
  if (points.length < 2) {
    return null;
  }

  const n = points.length;
  let sumT = 0; let sumF = 0; let sumTT = 0; let sumTF = 0;
  for (const point of points) {
    sumT += point.timestampSeconds;
    sumF += point.frequencyHz;
    sumTT += point.timestampSeconds * point.timestampSeconds;
    sumTF += point.timestampSeconds * point.frequencyHz;
  }

  const denominator = n * sumTT - sumT * sumT;
  if (denominator === 0) {
    return { slopeHzPerSecond: 0, interceptHz: sumF / n };
  }

  const slope = (n * sumTF - sumT * sumF) / denominator;
  const intercept = (sumF - slope * sumT) / n;
  return { slopeHzPerSecond: slope, interceptHz: intercept };
};
