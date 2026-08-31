import { Globe2 } from 'lucide-react';
import { ReceiversMapView } from '../../../presentation/views/kiwisdr/ReceiversMapView';
import { LabModuleDefinition } from '../types';

export const kiwiSdrMapModule: LabModuleDefinition = { id: 'kiwisdr-map', name: 'KiwiSDR Map', path: '/kiwisdr', icon: Globe2, element: <ReceiversMapView />, enabled: true, showInNavigation: true, order: 130, description: 'Remote receiver discovery and map module.' };
