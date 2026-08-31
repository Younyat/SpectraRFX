import { FlaskConical } from 'lucide-react';
import BleRffiStudioPage from '../../../presentation/views/ble-rffi-studio/BleRffiStudioPage';
import { LabModuleDefinition } from '../types';

export const bleRffiStudioModule: LabModuleDefinition = {
  id: 'ble-rffi-studio',
  name: 'BLE-RFFI Studio',
  path: '/ble-rffi-studio',
  icon: FlaskConical,
  element: <BleRffiStudioPage />,
  enabled: true,
  showInNavigation: true,
  order: 178,
  description: 'BLE-RFFI End-to-End Studio: modulo nuevo e independiente que cubre captura, evidencia, dataset, entrenamiento, evaluacion, exportacion e inferencia offline. No sustituye ni modifica los dashboards antiguos.',
};
