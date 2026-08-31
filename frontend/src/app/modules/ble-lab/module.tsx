import { Bluetooth } from 'lucide-react';
import { BleLabView } from '../../../presentation/views/ble/BleLabView';
import { LabModuleDefinition } from '../types';
const featureEnabled = import.meta.env.VITE_BLE_ANALYZER_V1 !== 'false';
export const bleLabModule: LabModuleDefinition = { id: 'ble-lab', name: 'BLE Lab', path: '/ble-lab', aliases: ['/ble-lab/jobs/:jobId'], icon: Bluetooth, element: <BleLabView />, enabled: true, showInNavigation: featureEnabled, order: 175, description: 'Experimental passive BLE analyzer using validated bitstream replay while IQ/DSP recovery remains unavailable.' };
