import { ScanSearch } from 'lucide-react';
import { InferenceLabView } from '../../../presentation/views/InferenceLabView';
import { LabModuleDefinition } from '../types';

export const inferenceModule: LabModuleDefinition = { id: 'inference', name: 'Inference', path: '/inference', icon: ScanSearch, element: <InferenceLabView />, enabled: true, showInNavigation: true, order: 80, description: 'Asynchronous prediction on curated predict captures.' };
