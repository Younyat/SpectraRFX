import { Settings } from 'lucide-react';
import { SettingsView } from '../../../presentation/views/SettingsView';
import { LabModuleDefinition } from '../types';

export const settingsModule: LabModuleDefinition = { id: 'settings', name: 'Settings', path: '/settings', icon: Settings, element: <SettingsView />, enabled: true, showInNavigation: true, order: 140, description: 'Application and analyzer settings module.' };
