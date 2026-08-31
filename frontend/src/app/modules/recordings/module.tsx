import { Radio } from 'lucide-react';
import { RecordingsView } from '../../../presentation/views/RecordingsView';
import { LabModuleDefinition } from '../types';

export const recordingsModule: LabModuleDefinition = { id: 'recordings', name: 'Recordings', path: '/recordings', icon: Radio, element: <RecordingsView />, enabled: true, showInNavigation: true, order: 110, description: 'Recording/session library module.' };
