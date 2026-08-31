import { BadgeCheck } from 'lucide-react';
import { ValidationLabView } from '../../../presentation/views/ValidationLabView';
import { LabModuleDefinition } from '../types';

export const validationModule: LabModuleDefinition = { id: 'validation', name: 'Validation', path: '/validation', icon: BadgeCheck, element: <ValidationLabView />, enabled: true, showInNavigation: true, order: 70, description: 'External validation over selected canonicalized validation captures with leakage checks.' };
