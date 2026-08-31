/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_SYNC_INTERVAL_MS?: string;
  readonly VITE_SPECTRUM_POLL_INTERVAL_MS?: string;
  readonly VITE_WATERFALL_POLL_INTERVAL_MS?: string;
  readonly VITE_REMOTE_USER?: string;
  readonly VITE_REMOTE_HOST?: string;
  readonly VITE_REMOTE_VENV_ACTIVATE?: string;
  readonly VITE_RADIOCONDA_PYTHON?: string;
  readonly VITE_SPECTRUM_TOOLS_V2?: string;
  readonly VITE_RF_TERRAIN_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
