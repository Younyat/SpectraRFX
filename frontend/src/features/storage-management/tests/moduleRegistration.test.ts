import { describe, expect, it } from 'vitest';
import { activeLabModules, navigationModules, moduleRoutes } from '../../../app/modules/labModules';

// Mirrors ai-research-plugin's moduleRegistration.test.ts, but for a
// module that is always on: verifies it really is part of the real
// active-module list the app renders routes/navigation from.
describe('Storage & Artifact Repository module registration', () => {
  it('is included in the real active module list the app renders routes/nav from', () => {
    expect(activeLabModules.some((module) => module.id === 'storage-management')).toBe(true);
    expect(navigationModules.some((module) => module.id === 'storage-management')).toBe(true);
    expect(moduleRoutes.some((route) => route.path === 'storage-management')).toBe(true);
  });
});
