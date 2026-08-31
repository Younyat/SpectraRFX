import { BrainCircuit } from 'lucide-react';
import { TrainingLabView } from '../../../presentation/views/TrainingLabView';
import { LabModuleDefinition } from '../types';

export const trainingModule: LabModuleDefinition = { id: 'training', name: 'Training', path: '/training', icon: BrainCircuit, element: <TrainingLabView />, enabled: true, showInNavigation: true, order: 50, description: 'Remote RF fingerprinting training from canonicalized train captures.' };
