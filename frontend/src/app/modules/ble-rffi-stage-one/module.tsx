import { ShieldCheck } from 'lucide-react';
import BleRffiStageOneDashboard from '../../../presentation/views/ble-rffi/BleRffiStageOneDashboard';
import { LabModuleDefinition } from '../types';

const featureEnabled = import.meta.env.VITE_BLE_ANALYZER_V1 !== 'false';

export const bleRffiStageOneModule: LabModuleDefinition = {
  id: 'ble-rffi-stage-one',
  name: 'BLE-RFFI Etapa 1',
  path: '/ble-rffi-stage-one',
  icon: ShieldCheck,
  element: <BleRffiStageOneDashboard />,
  enabled: true,
  showInNavigation: featureEnabled,
  order: 176,
  description: 'Dashboard modular para enrolamiento binario de una unidad BLE registrada contra fondo BLE en CH37.',
};
