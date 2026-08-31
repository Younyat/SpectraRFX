import { DatabaseZap } from 'lucide-react';
import { E6OracleStyleLabView } from '../../../presentation/views/E6OracleStyleLabView';
import { LabModuleDefinition } from '../types';

export const e6OracleStyleLabModule: LabModuleDefinition = {
  id: 'e6-oracle-style-lab',
  name: 'E6 Oracle-Style Lab',
  path: '/e6-oracle-style-lab',
  icon: DatabaseZap,
  element: <E6OracleStyleLabView />,
  enabled: true,
  showInNavigation: true,
  order: 66,
  description: 'ORACLE/KRI/UAV/CBRS dataset import, local dataset creation, classical RF fingerprinting with 8 sklearn models, live spectrum detection.',
};
