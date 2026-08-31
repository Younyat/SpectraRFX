import { Boxes } from 'lucide-react';
import { ModelRegistryView } from '../../../presentation/views/ModelRegistryView';
import { LabModuleDefinition } from '../types';

export const modelsModule: LabModuleDefinition = { id: 'models', name: 'Models', path: '/models', icon: Boxes, element: <ModelRegistryView />, enabled: true, showInNavigation: true, order: 90, description: 'Model card, registry, lineage, validation evidence, and artifact readiness.' };
