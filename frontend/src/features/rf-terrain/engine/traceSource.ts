import type { TerrainProcessedRow } from '../model/rfTerrainTypes';

// Which already-computed per-bin quantity feeds the terrain surface --
// spec-adjacent "apply Max Hold/Average/etc. to the whole 3D view, not
// just a thin reference ribbon" request. Every array here was already
// computed once, per real frame, by the same engines behind the 2D
// ribbons (holdEngine.ts, averageEngine.ts, ewmaEngine.ts,
// percentileEngine.ts) -- this never recomputes or approximates a new
// statistic, it only picks which already-real one drives height/color.
export type RFTerrainTraceSource = 'live' | 'maxHold' | 'minHold' | 'average' | 'ewma' | 'p50' | 'p90' | 'p95' | 'p99';

const TRACE_FIELD: Record<Exclude<RFTerrainTraceSource, 'live'>, keyof TerrainProcessedRow> = {
  maxHold: 'maxHoldDb',
  minHold: 'minHoldDb',
  average: 'averageDb',
  ewma: 'ewmaDb',
  p50: 'p50Db',
  p90: 'p90Db',
  p95: 'p95Db',
  p99: 'p99Db',
};

export const pickTraceValues = (row: TerrainProcessedRow, traceSource: RFTerrainTraceSource): number[] =>
  traceSource === 'live' ? row.frame.powerLevels : (row[TRACE_FIELD[traceSource]] as number[]);
