const DEFAULT_SPECTRUM_POLL_INTERVAL_MS = 100;
const DEFAULT_WATERFALL_POLL_INTERVAL_MS = 100;
const DEFAULT_APP_SYNC_INTERVAL_MS = 5000;

const parsePositiveInteger = (value: string | undefined, fallback: number): number => {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }

  return parsed;
};

const parseBoolean = (value: string | undefined, fallback: boolean): boolean => {
  if (value === undefined) {
    return fallback;
  }

  return value === 'true' || value === '1';
};

export const RUNTIME_CONFIG = {
  appSyncIntervalMs: parsePositiveInteger(
    import.meta.env.VITE_APP_SYNC_INTERVAL_MS,
    DEFAULT_APP_SYNC_INTERVAL_MS,
  ),
  spectrumPollIntervalMs: parsePositiveInteger(
    import.meta.env.VITE_SPECTRUM_POLL_INTERVAL_MS,
    DEFAULT_SPECTRUM_POLL_INTERVAL_MS,
  ),
  waterfallPollIntervalMs: parsePositiveInteger(
    import.meta.env.VITE_WATERFALL_POLL_INTERVAL_MS,
    DEFAULT_WATERFALL_POLL_INTERVAL_MS,
  ),
  remoteUser: import.meta.env.VITE_REMOTE_USER ?? '',
  remoteHost: import.meta.env.VITE_REMOTE_HOST ?? '',
  remoteVenvActivate:
    import.meta.env.VITE_REMOTE_VENV_ACTIVATE ??
    (import.meta.env.VITE_REMOTE_USER ? `/home/${import.meta.env.VITE_REMOTE_USER}/rfenv/bin/activate` : ''),
  radioCondaPython: import.meta.env.VITE_RADIOCONDA_PYTHON ?? '',
  // Kill switch for the RF Terrain 3D module. Now the primary view (PR8):
  // on by default, RF Terrain replaces Waterfall in navigation while
  // /waterfall keeps working as a manual fallback. Set to "false" to pull
  // the module out of navigation entirely if it ever needs to be disabled.
  rfTerrainEnabled: parseBoolean(import.meta.env.VITE_RF_TERRAIN_ENABLED, true),
  // AI Model Research Plugin: an experimental, explicitly opt-in module
  // (off by default, matching the backend's AI_RESEARCH_PLUGIN_ENABLED
  // default) -- when off, this module carries zero routes and zero
  // navigation entries, identical to a build where it does not exist.
  aiResearchPluginEnabled: parseBoolean(import.meta.env.VITE_AI_RESEARCH_PLUGIN_ENABLED, false),
} as const;
