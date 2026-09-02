// Explicit module state machine (spec §60).
export type RFTerrainModuleState =
  | 'DISABLED'
  | 'IDLE'
  | 'WAITING_FOR_DEVICE'
  | 'WAITING_FOR_FRAME'
  | 'STREAMING'
  | 'FROZEN'
  | 'RESETTING'
  | 'DEGRADED_2D'
  | 'ERROR_LOCAL';

// 'density' reads the same noise-referenced excess ADAPTIVE/OCCUPANCY
// already compute, but smoothed across the frequency axis (see
// engine/frequencySmoothing.ts) into one coherent curve instead of many
// independent per-bin spikes -- a visual reconstruction, same discipline
// as the Spectral Object Envelope (docs §15): never claimed as a
// calibrated Power Spectral Density, and the Inspector/raycaster always
// keep reading the real, unsmoothed per-bin value regardless of mode.
export type RFTerrainMode = 'raw' | 'adaptive' | 'occupancy' | 'density';
export type RFTerrainCameraPreset = '3d' | 'top' | 'front' | 'side';

// A raw spectrum frame, already validated, resampled to a fixed bin count,
// and tagged with the acquisition generation it belongs to (spec §12).
export interface TerrainInputFrame {
  generation: number;
  timestamp: number;
  centerFrequency: number;
  span: number;
  frequencyArray: number[];
  powerLevels: number[];
  sampleRateHz?: number;
  fftSize?: number;
  requestedRbwHz?: number;
  effectiveRbwHz?: number;
  powerUnit?: 'dBFS' | 'dBm';
  sourceId?: string;
  deviceSerial?: string;
  calibrationId?: string;
}

export type TerrainObjectMorphology =
  | 'RIDGE' | 'ISLAND' | 'PLATEAU' | 'TRANSIENT' | 'DRIFTING' | 'HOPPING_CLUSTER' | 'IRREGULAR';

// Per-object morphological metrics (spec §37). Optional/later fields
// (entropy, fragmentation, duty-cycle, curvature) are not computed in this
// pass -- see terrainMetrics.ts.
export interface TerrainObject {
  id: string;
  // Stable across segmentation passes for as long as the same physical
  // emission (or, for HOPPING_CLUSTER, the same re-triggering frequency
  // neighborhood) keeps being re-detected -- unlike `id`, which is
  // recomputed fresh every SEGMENT pass. See engine/objectTracker.ts.
  trackId: string;
  startTimeSeconds: number;
  endTimeSeconds: number;
  durationSeconds: number;
  startFrequencyHz: number;
  stopFrequencyHz: number;
  centerFrequencyHz: number;
  bandwidthHz: number;
  peakExcessDb: number;
  meanExcessDb: number;
  frequencyCentroidHz: number;
  temporalCentroidSeconds: number;
  terrainVolumeIndex: number;
  ridgeSlopeHzPerSecond: number | null;
  cellCount: number;
  // DERIVED (geometric) classification -- never a protocol/device label.
  morphology: TerrainObjectMorphology;
  // True if this object was still being detected in the most recent row
  // of the segmented window (i.e. it has not yet ended); false once its
  // last detected row has aged into the past.
  active: boolean;
  // Absent (undefined) = a real object from the terrain's own segmentation
  // algorithm -- every existing construction site keeps working untouched.
  // 'AI_DETECTION' = synthetic, injected from an AI Research Plugin LIVE
  // result (see ai/aiDetectionObject.ts) -- reuses this SAME type so it is
  // selectable via the SAME findObjectAtPoint/Inspector pipeline, but its
  // peakExcessDb/meanExcessDb/terrainVolumeIndex/cellCount/ridgeSlope
  // fields are NOT measured (always 0/null) and callers (the Inspector)
  // must branch on `origin` before presenting them as real geometry.
  origin?: 'AI_DETECTION';
  aiDetection?: AiDetectionInfo;
}

// Real info carried by an AI-injected TerrainObject -- everything the
// model/backend actually reported for this detection, never fabricated.
export interface AiDetectionInfo {
  modelId: string;
  modelName: string;
  // Short, human-readable summary (predicted class + score, or embedding
  // dims, or "not automatically interpretable") -- never a confirmed
  // protocol/device label.
  summary: string;
  detectedAtUtc: string;
  // Real, measured end-to-end latency (backend total_latency_ms, or the
  // client round-trip fallback) -- null only when genuinely unknown.
  totalLatencyMs: number | null;
}

// One AI Research Plugin LIVE inference result, anchored to the terrain
// row that was newest AT THE MOMENT the result arrived (a live detection
// is inherently "just now", not a historical range lookup -- see
// AiDetectionOverlay.ts). Deliberately NOT a TerrainObject: none of its
// numeric fields (peakExcessDb, terrainVolumeIndex, cellCount, ...) are
// measured for an AI-flagged region, so folding it into that type would
// misrepresent asserted/inferred values as segmentation measurements.
export interface AiLiveDetection {
  id: string;
  modelId: string;
  modelName: string;
  detectedAtUtc: string;
  centerFrequencyHz: number;
  bandwidthHz: number;
  // A short, human-readable summary of the interpretation -- never a
  // confirmed protocol/device label (same discipline as the FSEI-AI panel
  // itself).
  summary: string;
  // Real, measured latency (backend-reported total_latency_ms, or the
  // client-measured round-trip if the backend didn't report one) -- null
  // only when genuinely unknown, never a placeholder guess.
  totalLatencyMs: number | null;
}

// Typed worker protocol (spec §11).
export type TerrainWorkerInput =
  | { type: 'RESET'; generation: number; capacity: number }
  | { type: 'FRAME'; generation: number; frame: TerrainInputFrame }
  | { type: 'SEGMENT'; generation: number };

export interface TerrainProcessedRow {
  frame: TerrainInputFrame;
  noiseFloorDb: number[];
  excessDb: number[];
  persistence: number[];
  occupancy: number[];
  maxHoldDb: number[];
  minHoldDb: number[];
  averageDb: number[];
  ewmaDb: number[];
  p50Db: number[];
  p90Db: number[];
  p95Db: number[];
  p99Db: number[];
}

export type TerrainWorkerOutput =
  | { type: 'ROW'; generation: number; rowIndex: number; bufferSize: number; bufferCapacity: number; row: TerrainProcessedRow }
  | { type: 'OBJECTS'; generation: number; objects: TerrainObject[] }
  | { type: 'ERROR'; recoverable: boolean; code: string; message: string };

export interface RFTerrainFrameSourceDiagnostics {
  state: RFTerrainModuleState;
  generation: number;
  framesReceived: number;
  invalidFrames: number;
  droppedProcessingFrames: number;
  ringBufferSize: number;
  ringBufferCapacity: number;
  lastFrameTimestamp: number | null;
  lastError: string | null;
}

// FSEI epistemic status (Forensic Spectral Evidence Inspector): every
// field the inspector shows is tagged by what kind of knowledge it
// represents, so a hypothesis can never be silently rendered with the
// same visual weight as a measured or evidence-backed value.
export type EpistemicStatus = 'MEASURED' | 'DERIVED' | 'HYPOTHESIS' | 'EVIDENCE' | 'SIMULATED';

// No real event-to-capture linkage exists yet (see the technical report,
// §"Explicitly not implemented") -- this always resolves to 'UNAVAILABLE'
// today. The type exists so the UI has one real, honest state to render
// rather than omitting the concept entirely.
export type EvidenceLinkStatus = 'LINKED' | 'CAPTURE_UNRESOLVED' | 'NOT_PRESERVED' | 'UNAVAILABLE';

export interface TerrainInspectorSelection {
  kind: 'POINT' | 'TERRAIN_OBJECT';
  generation: number;
  frequencyHz: number;
  timestamp: number;
  rawPowerDb: number;
  noiseFloorDb: number;
  excessDb: number;
  persistence: number;
  occupancy: number;
  maxHoldDb: number;
  minHoldDb: number;
  averageDb: number;
  ewmaDb: number;
  powerUnit: 'dBFS' | 'dBm';
  calibrationId?: string;
  objectId: string | null;
  pinned: boolean;
  // True once the selected reticle has aged past the visible history depth
  // (spec-adjacent OUT OF VIEW). Only reachable when pinned=true -- an
  // unpinned selection is cleared outright the moment it ages out instead
  // of being kept around in a stale, unreachable state.
  outOfView: boolean;
}
