import { describe, expect, it } from 'vitest';
import { RUNTIME_CONFIG } from '../../../shared/config/runtime';
import { activeLabModules, navigationModules, moduleRoutes } from '../../../app/modules/labModules';

// Mirrors the backend's test_module_registration.py: verifies spec
// section 22/25's acceptance rule on the frontend side too -- with the
// flag unset (the real default), this module contributes zero active
// routes and zero navigation entries, identical to a build where the
// feature does not exist.
describe('AI Research Plugin module registration', () => {
  it('is disabled by default', () => {
    expect(RUNTIME_CONFIG.aiResearchPluginEnabled).toBe(false);
  });

  it('is excluded from the real active module list the app renders routes/nav from', () => {
    expect(activeLabModules.some((module) => module.id === 'ai-research-plugin')).toBe(false);
    expect(navigationModules.some((module) => module.id === 'ai-research-plugin')).toBe(false);
    expect(moduleRoutes.some((route) => route.path === 'ai-research-plugin')).toBe(false);
  });
});
