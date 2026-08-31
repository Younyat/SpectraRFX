import { Suspense, lazy } from 'react';
import { Mountain } from 'lucide-react';
import { LabModuleDefinition } from '../types';
import { RUNTIME_CONFIG } from '../../../shared/config/runtime';
import { RFTerrainModuleBoundary } from './RFTerrainModuleBoundary';

// Lazy-loaded (spec §50): visiting any other module must never pull the
// rf-terrain chunk (and, once later PRs add it, must never initialize
// Three.js/WebGLRenderer/TerrainWorker as a side effect of import).
const RFTerrainView = lazy(() =>
  import('../../../features/rf-terrain/ui/RFTerrainView').then((module) => ({ default: module.RFTerrainView })),
);

export const rfTerrainModule: LabModuleDefinition = {
  id: 'rf-terrain',
  name: 'RF Terrain 3D',
  path: '/rf-terrain',
  icon: Mountain,
  element: (
    <RFTerrainModuleBoundary>
      <Suspense fallback={null}>
        <RFTerrainView />
      </Suspense>
    </RFTerrainModuleBoundary>
  ),
  // Feature-flagged (spec §6): when the flag is off, `enabled: false` drops
  // this module out of activeLabModules entirely, so it carries zero routes,
  // zero navigation entries, and zero chance of importing its own lazy chunk.
  enabled: RUNTIME_CONFIG.rfTerrainEnabled,
  showInNavigation: RUNTIME_CONFIG.rfTerrainEnabled,
  order: 101,
  description: 'RF Terrain 3D (ARST) -- experimental real-time spectral terrain, isolated from the legacy Waterfall view.',
};
