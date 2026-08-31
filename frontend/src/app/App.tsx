import { useEffect } from 'react';
import { AppRouter } from './router/AppRouter';
import { ApiService } from './services/ApiService';
import { useAppStore } from './store/AppStore';
import { RUNTIME_CONFIG } from '../shared/config/runtime';
import { usePersistentJobActivity } from '../presentation/hooks/usePersistentJobActivity';

const apiService = new ApiService();

function App() {
  usePersistentJobActivity();
  const setDeviceStatus = useAppStore((state) => state.setDeviceStatus);
  const setRecordings = useAppStore((state) => state.setRecordings);
  const setSessions = useAppStore((state) => state.setSessions);
  const setPresets = useAppStore((state) => state.setPresets);
  const theme = useAppStore((state) => state.ui.theme);

  useEffect(() => {
    let cancelled = false;

    const syncAppData = async () => {
      try {
        const [deviceStatus, recordings, sessions, presets] = await Promise.all([
          apiService.getDeviceStatus(),
          apiService.getRecordings(),
          apiService.getSessions(),
          apiService.getPresets(),
        ]);

        if (cancelled) {
          return;
        }

        setDeviceStatus(deviceStatus);
        setRecordings(recordings);
        setSessions(sessions);
        setPresets(presets);
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to sync app data:', error);
        }
      }
    };

    syncAppData();
    const interval = setInterval(syncAppData, RUNTIME_CONFIG.appSyncIntervalMs);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setDeviceStatus, setPresets, setRecordings, setSessions]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return <AppRouter />;
}

export { App };
