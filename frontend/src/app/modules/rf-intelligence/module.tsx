import { BrainCircuit } from 'lucide-react';
import { RFIntelligenceView } from '../../../presentation/views/RFIntelligenceView';
import { LabModuleDefinition } from '../types';

export const rfIntelligenceModule: LabModuleDefinition = {
  id: 'rf-intelligence',
  name: 'RF Intelligence',
  path: '/rf-intelligence',
  icon: BrainCircuit,
  element: <RFIntelligenceView />,
  enabled: true,
  showInNavigation: true,
  order: 65,
  description: 'Real-time RF object detection, rule-based protocol hypotheses, and evidence review.',
};
