import { Wifi } from 'lucide-react';
import { WifiDashboardView } from '../../../presentation/views/WifiDashboardView';
import { LabModuleDefinition } from '../types';

export const wifiDashboardModule: LabModuleDefinition = { id: 'wifi-dashboard', name: 'Wi-Fi Dashboard', path: '/wifi-dashboard', icon: Wifi, element: <WifiDashboardView />, enabled: true, showInNavigation: true, order: 121, description: 'Dedicated IEEE 802.11 workspace: capture a channel or analyze an existing recording, and inspect the full confirmed-frame report and diagnostics.' };
