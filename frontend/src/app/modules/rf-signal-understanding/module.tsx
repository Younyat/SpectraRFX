import { ScanSearch } from 'lucide-react';
import { RFSignalUnderstandingView } from '../../../presentation/views/RFSignalUnderstandingView';
import { LabModuleDefinition } from '../types';

export const rfSignalUnderstandingModule: LabModuleDefinition = {
  id: 'rf-signal-understanding',
  name: 'RF Signal Understanding',
  path: '/rf-signal-understanding',
  icon: ScanSearch,
  element: <RFSignalUnderstandingView />,
  enabled: true,
  showInNavigation: true,
  order: 66,
  description: 'Waterfall-based I/Q analysis, region detection, cautious signal hypotheses, and legacy comparison.',
};
