import { FileCheck2 } from 'lucide-react';
import BleScientificResultsPage from '../../../presentation/views/ble-scientific-results/BleScientificResultsPage';
import { LabModuleDefinition } from '../types';

export const bleScientificResultsModule: LabModuleDefinition = {
  id: 'ble-scientific-results',
  name: 'BLE Scientific Results',
  path: '/ble-scientific-results',
  icon: FileCheck2,
  element: <BleScientificResultsPage />,
  enabled: true,
  showInNavigation: true,
  order: 179,
  description: 'Orquestador cientifico deterministico para los resultados del paper BLE: contratos de analisis congelados y preflight cientifico (Fase 1). Reutiliza los manifests y artefactos de BLE-RFFI Studio -- nunca los modifica.',
};
