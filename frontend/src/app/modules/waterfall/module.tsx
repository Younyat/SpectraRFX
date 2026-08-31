import { BarChart3 } from 'lucide-react';
import { WaterfallView } from '../../../presentation/views/WaterfallView';
import { LabModuleDefinition } from '../types';
import { RUNTIME_CONFIG } from '../../../shared/config/runtime';

// PR8 (RF Terrain spec §81): once RF Terrain is validated and enabled, it
// becomes the visible nav entry and Waterfall drops out of the sidebar --
// but `enabled` stays true unconditionally, so /waterfall keeps working as
// a manual fallback (linked directly from every RF Terrain screen).
export const waterfallModule: LabModuleDefinition = { id: 'waterfall', name: 'Waterfall', path: '/waterfall', icon: BarChart3, element: <WaterfallView />, enabled: true, showInNavigation: !RUNTIME_CONFIG.rfTerrainEnabled, order: 100, description: 'Waterfall visualization module for spectrum history.' };
