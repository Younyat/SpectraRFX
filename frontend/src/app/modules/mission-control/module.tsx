import { Activity } from 'lucide-react';
import { FingerprintingOverviewView } from '../../../presentation/views/FingerprintingOverviewView';
import { LabModuleDefinition } from '../types';

export const missionControlModule: LabModuleDefinition = { id: 'mission-control', name: 'Mission Control', path: '/', index: true, icon: Activity, element: <FingerprintingOverviewView />, enabled: true, showInNavigation: true, order: 10, description: 'Top-level workflow overview for acquisition, curation, ML operations, and model readiness.' };
