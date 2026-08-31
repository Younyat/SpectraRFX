import { Radio } from 'lucide-react';
import { LiveDemodulationView } from '../../../presentation/views/LiveDemodulationView';
import { LabModuleDefinition } from '../types';

export const liveDemodulationModule: LabModuleDefinition = { id: 'live-demodulation', name: 'Live Demodulation', path: '/live-demodulation', icon: Radio, element: <LiveDemodulationView />, enabled: true, showInNavigation: true, order: 125, description: 'Real-time AM/FM/NFM/WFM audio demodulation with Web Audio API streaming.' };
