import { Suspense, lazy } from 'react';
import { FlaskConical } from 'lucide-react';
import { LabModuleDefinition } from '../types';
import { RUNTIME_CONFIG } from '../../../shared/config/runtime';

// Lazy-loaded, same discipline as rf-terrain/module.tsx: visiting any
// other module must never pull this feature's chunk (or its
// AiResearchPluginClient) as a side effect of import.
const AiResearchPluginView = lazy(() =>
  import('../../../features/ai-research-plugin/ui/AiResearchPluginView').then((module) => ({ default: module.AiResearchPluginView })),
);

export const aiResearchPluginModule: LabModuleDefinition = {
  id: 'ai-research-plugin',
  name: 'AI Research Plugin',
  path: '/ai-research-plugin',
  icon: FlaskConical,
  element: (
    <Suspense fallback={null}>
      <AiResearchPluginView />
    </Suspense>
  ),
  // Off by default (spec section 22): when disabled, this module carries
  // zero routes and zero navigation entries -- identical to a build where
  // it does not exist. Enable with VITE_AI_RESEARCH_PLUGIN_ENABLED=true
  // (and the backend's AI_RESEARCH_PLUGIN_ENABLED=true, independently).
  enabled: RUNTIME_CONFIG.aiResearchPluginEnabled,
  showInNavigation: RUNTIME_CONFIG.aiResearchPluginEnabled,
  // 200 previously buried this dead last below ~26 other nav entries in a
  // scrolling sidebar -- easy to miss entirely. 25 puts it near the top,
  // right after Live Monitor, since it is the module currently being
  // exercised/tested.
  order: 25,
  description: 'Experimental: import a pretrained ONNX model and run isolated research inference over preserved RF captures.',
};
