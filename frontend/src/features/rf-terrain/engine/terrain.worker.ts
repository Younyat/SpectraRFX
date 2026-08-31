import { createTerrainWorkerState } from './terrainWorkerState';
import type { TerrainWorkerInput } from '../model/rfTerrainTypes';

// Real Web Worker entry point (spec §11). All logic lives in
// terrainWorkerState.ts -- this file only wires postMessage in/out, so a
// worker thread failure can only ever be a postMessage/wiring bug, never a
// hidden second copy of the ring-buffer/generation logic to drift from the
// tested one.
const state = createTerrainWorkerState();

self.onmessage = (event: MessageEvent<TerrainWorkerInput>) => {
  const outputs = state.handle(event.data);
  outputs.forEach((output) => self.postMessage(output));
};
