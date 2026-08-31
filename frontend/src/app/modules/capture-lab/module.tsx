import { Database } from 'lucide-react';
import { ModulatedSignalAnalysisView } from '../../../presentation/views/ModulatedSignalAnalysisView';
import { LabModuleDefinition } from '../types';

export const captureLabModule: LabModuleDefinition = { id: 'capture-lab', name: 'Capture Lab', path: '/capture', aliases: ['/guided-capture', '/modulated-analysis'], icon: Database, element: <ModulatedSignalAnalysisView />, enabled: true, showInNavigation: true, order: 30, description: 'Controlled I/Q acquisition, RF pre/post-capture guidance, dataset split assignment, and safe capture deletion.' };
