import { useEffect, useMemo, useState } from 'react';
import { OfflineReconstructionController, OfflineReconstructionCallbacks, OfflineReconstructionState } from './OfflineReconstructionController';
import type { TerrainProcessedRow } from '../model/rfTerrainTypes';

export interface UseOfflineReconstructionArgs {
  onRow: (row: TerrainProcessedRow) => void;
  onReset: () => void;
}

// Thin React wrapper over OfflineReconstructionController -- same
// onRow/onReset contract useRFTerrainFrameSource already gives
// RFTerrainView, so the canvas needs zero changes to accept rows from
// either source. Owns exactly one controller instance for the lifetime of
// the component; disposed on unmount (never leaks a running engine).
export const useOfflineReconstruction = ({ onRow, onReset }: UseOfflineReconstructionArgs) => {
  const controller = useMemo(() => {
    const callbacks: OfflineReconstructionCallbacks = { onRow, onReset, onStateChange: () => {} };
    return new OfflineReconstructionController(callbacks);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- one controller per component lifetime, callbacks captured via refs below

  const [state, setState] = useState<OfflineReconstructionState>(controller.getState());

  useEffect(() => {
    // Re-point the controller's callbacks at the latest closures on every
    // render (the controller itself is created once) so onRow/onReset
    // always see current props/state without recreating the engine.
    controller.setCallbacks({ onRow, onReset, onStateChange: setState });
  });

  useEffect(() => () => controller.dispose(), [controller]);

  return { state, controller };
};
