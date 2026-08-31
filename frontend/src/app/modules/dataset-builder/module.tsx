import { LibraryBig } from 'lucide-react';
import { DatasetBuilderView } from '../../../presentation/views/DatasetBuilderView';
import { LabModuleDefinition } from '../types';

export const datasetBuilderModule: LabModuleDefinition = { id: 'dataset-builder', name: 'Dataset Builder', path: '/dataset-builder', icon: LibraryBig, element: <DatasetBuilderView />, enabled: true, showInNavigation: true, order: 40, description: 'QC review, manual acceptance/rejection, recomputation, and curated dataset governance.' };
