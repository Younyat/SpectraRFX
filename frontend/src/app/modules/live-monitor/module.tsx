import { Activity } from 'lucide-react';
import { SpectrumView } from '../../../presentation/views/SpectrumView';
import { LabModuleDefinition } from '../types';

export const liveMonitorModule: LabModuleDefinition = { id: 'live-monitor', name: 'Live Monitor', path: '/spectrum', icon: Activity, element: <SpectrumView />, enabled: true, showInNavigation: true, order: 20, description: 'Real-time RF spectrum monitoring and analyzer controls.' };
