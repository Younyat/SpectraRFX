import { RefreshCcw } from 'lucide-react';
import { RetrainingLabView } from '../../../presentation/views/RetrainingLabView';
import { LabModuleDefinition } from '../types';

export const retrainingModule: LabModuleDefinition = { id: 'retraining', name: 'Retraining', path: '/retraining', icon: RefreshCcw, element: <RetrainingLabView />, enabled: true, showInNavigation: true, order: 60, description: 'Controlled retraining over the updated curated train registry.' };
