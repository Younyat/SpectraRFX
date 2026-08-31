import { Waves } from 'lucide-react';
import { DemodulationView } from '../../../presentation/views/DemodulationView';
import { LabModuleDefinition } from '../types';

export const demodulationModule: LabModuleDefinition = { id: 'demodulation', name: 'Demodulation', path: '/demodulation', icon: Waves, element: <DemodulationView />, enabled: true, showInNavigation: true, order: 120, description: 'Marker-band analog and digital demodulation module.' };
