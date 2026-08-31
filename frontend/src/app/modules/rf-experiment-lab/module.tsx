import { FlaskConical } from 'lucide-react';
import { RFExperimentLabView } from '../../../presentation/views/RFExperimentLabView';
import { LabModuleDefinition } from '../types';

export const rfExperimentLabModule: LabModuleDefinition = {
  id: 'rf-experiment-lab',
  name: 'RF Experiment Lab',
  path: '/rf-experiment-lab',
  icon: FlaskConical,
  element: <RFExperimentLabView />,
  enabled: true,
  showInNavigation: true,
  order: 65,
  description: 'Reproducible RF experiments: E0, E5, E1, E3, exports, strict splits, metrics, and benchmark reports.',
};
