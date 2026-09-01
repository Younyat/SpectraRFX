import { Suspense, lazy } from 'react';
import { HardDrive } from 'lucide-react';
import { LabModuleDefinition } from '../types';

// Lazy-loaded, same discipline as every other module here: visiting any
// other module must never pull this feature's chunk (or its
// StorageManagementClient) as a side effect of import.
const StorageManagementView = lazy(() =>
  import('../../../features/storage-management/ui/StorageManagementView').then((module) => ({ default: module.StorageManagementView })),
);

export const storageManagementModule: LabModuleDefinition = {
  id: 'storage-management',
  name: 'Storage & Artifacts',
  path: '/storage-management',
  icon: HardDrive,
  element: (
    <Suspense fallback={null}>
      <StorageManagementView />
    </Suspense>
  ),
  enabled: true,
  showInNavigation: true,
  order: 145,
  description: 'Real disk-usage inventory across every capture, dataset, and artifact category, with confirmation-gated deletion.',
};
