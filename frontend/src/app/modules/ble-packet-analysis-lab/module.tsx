import { Radio } from 'lucide-react';
import BlePacketAnalysisLab from '../../../presentation/views/ble-packet-lab/BlePacketAnalysisLab';
import { LabModuleDefinition } from '../types';

export const blePacketAnalysisLabModule: LabModuleDefinition = {
  id: 'ble-packet-analysis-lab',
  name: 'BLE Packet Lab',
  path: '/ble-packet-lab',
  icon: Radio,
  element: <BlePacketAnalysisLab />,
  enabled: true,
  showInNavigation: true,
  order: 177,
  description: 'BLE Capture & Packet Analysis Lab: interpreta el contenido de los paquetes ya recuperados por el replay offline (Fase 1) y los compara con las observaciones Windows preservadas. Solo lectura -- no repite hardware, no genera dataset.',
};
