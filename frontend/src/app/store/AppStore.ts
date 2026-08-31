import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import {
  SpectrumData,
  WaterfallData,
  Marker,
  DeviceStatus,
  AnalyzerSettings,
  Recording,
  Session,
  Preset,
  UiState
} from '../../shared/types';
import { DEFAULT_SETTINGS } from '../../shared/constants';

interface AppState {
  // UI State
  ui: UiState;
  globalActivity: {
    visible: boolean;
    kind: 'connecting' | 'capturing' | 'streaming' | 'processing';
    title: string;
    detail?: string;
    operationId?: string;
    phase?: string;
    progressPercent?: number;
    elapsedSeconds?: number;
    estimatedRemainingSeconds?: number|null;
    target?: string;
    configuredDurationSeconds?: number;
    processedItems?: number;
    totalItems?: number;
  } | null;

  // Domain State
  spectrumData: SpectrumData | null;
  waterfallData: WaterfallData[];
  markers: Marker[];
  deviceStatus: DeviceStatus;
  analyzerSettings: AnalyzerSettings;
  recordings: Recording[];
  sessions: Session[];
  presets: Preset[];
  currentSession: Session | null;
  currentRecording: Recording | null;

  // Actions
  setUiState: (updates: Partial<UiState>) => void;
  setGlobalActivity: (activity: AppState['globalActivity']) => void;
  clearGlobalActivity: () => void;

  setSpectrumData: (data: SpectrumData) => void;
  setWaterfallData: (data: WaterfallData) => void;
  addWaterfallData: (data: WaterfallData) => void;
  clearWaterfallData: () => void;

  addMarker: (marker: Marker) => void;
  updateMarker: (id: string, updates: Partial<Marker>) => void;
  removeMarker: (id: string) => void;
  clearMarkers: () => void;

  setDeviceStatus: (status: Partial<DeviceStatus>) => void;
  updateAnalyzerSettings: (settings: Partial<AnalyzerSettings>) => void;

  addRecording: (recording: Recording) => void;
  setRecordings: (recordings: Recording[]) => void;
  setCurrentRecording: (recording: Recording | null) => void;

  addSession: (session: Session) => void;
  setSessions: (sessions: Session[]) => void;
  setCurrentSession: (session: Session | null) => void;

  addPreset: (preset: Preset) => void;
  setPresets: (presets: Preset[]) => void;
  removePreset: (id: string) => void;

  // Reset
  reset: () => void;
}

const getStoredTheme = (): UiState['theme'] => {
  if (typeof window === 'undefined') return 'light';
  const value = window.localStorage.getItem('rf-lab-theme');
  if (value === 'dark' || value === 'light' || value === 'laboratory') {
    return value;
  }
  return 'light';
};

const initialState = {
  ui: {
    theme: getStoredTheme(),
    sidebarCollapsed: false,
    topBarCollapsed: false,
    activeTab: 'spectrum' as const,
  },
  globalActivity: null,

  spectrumData: null,
  waterfallData: [],
  markers: [],
  deviceStatus: {
    isConnected: false,
    driver: 'uhd_gnuradio',
    centerFrequency: 89400000,
    sampleRate: 2000000,
    gain: 0,
  },
  analyzerSettings: DEFAULT_SETTINGS,
  recordings: [],
  sessions: [],
  presets: [],
  currentSession: null,
  currentRecording: null,
};

export const useAppStore = create<AppState>()(
  subscribeWithSelector((set) => ({
    ...initialState,

    setUiState: (updates) =>
      set((state) => {
        const nextUi = { ...state.ui, ...updates };
        if (typeof window !== 'undefined' && updates.theme) {
          window.localStorage.setItem('rf-lab-theme', updates.theme);
        }
        return { ui: nextUi };
      }),

    setGlobalActivity: (activity) =>
      set({ globalActivity: activity }),

    clearGlobalActivity: () =>
      set({ globalActivity: null }),

    setSpectrumData: (data) =>
      set({ spectrumData: data }),

    setWaterfallData: (data) =>
      set({ waterfallData: [data] }),

    addWaterfallData: (data) =>
      set((state) => ({
        waterfallData: [...state.waterfallData.slice(-99), data], // Keep last 100 entries
      })),

    clearWaterfallData: () =>
      set({ waterfallData: [] }),

    addMarker: (marker) =>
      set((state) => ({
        markers: [...state.markers, marker],
      })),

    updateMarker: (id, updates) =>
      set((state) => ({
        markers: state.markers.map((marker) =>
          marker.id === id ? { ...marker, ...updates } : marker
        ),
      })),

    removeMarker: (id) =>
      set((state) => ({
        markers: state.markers.filter((marker) => marker.id !== id),
      })),

    clearMarkers: () =>
      set({ markers: [] }),

    setDeviceStatus: (status) =>
      set((state) => ({
        deviceStatus: { ...state.deviceStatus, ...status },
      })),

    updateAnalyzerSettings: (settings) =>
      set((state) => ({
        analyzerSettings: { ...state.analyzerSettings, ...settings },
      })),

    addRecording: (recording) =>
      set((state) => ({
        recordings: [...state.recordings, recording],
      })),

    setRecordings: (recordings) =>
      set({ recordings }),

    setCurrentRecording: (recording) =>
      set({ currentRecording: recording }),

    addSession: (session) =>
      set((state) => ({
        sessions: [...state.sessions, session],
      })),

    setSessions: (sessions) =>
      set({ sessions }),

    setCurrentSession: (session) =>
      set({ currentSession: session }),

    addPreset: (preset) =>
      set((state) => ({
        presets: [...state.presets, preset],
      })),

    setPresets: (presets) =>
      set({ presets }),

    removePreset: (id) =>
      set((state) => ({
        presets: state.presets.filter((preset) => preset.id !== id),
      })),

    reset: () =>
      set(initialState),
  }))
);

// Selectors
export const useSpectrumData = () => useAppStore((state) => state.spectrumData);
export const useWaterfallData = () => useAppStore((state) => state.waterfallData);
export const useMarkers = () => useAppStore((state) => state.markers);
export const useDeviceStatus = () => useAppStore((state) => state.deviceStatus);
export const useAnalyzerSettings = () => useAppStore((state) => state.analyzerSettings);
export const useRecordings = () => useAppStore((state) => state.recordings);
export const useSessions = () => useAppStore((state) => state.sessions);
export const usePresets = () => useAppStore((state) => state.presets);
export const useCurrentSession = () => useAppStore((state) => state.currentSession);
export const useCurrentRecording = () => useAppStore((state) => state.currentRecording);
export const useUiState = () => useAppStore((state) => state.ui);
export const useGlobalActivity = () => useAppStore((state) => state.globalActivity);

// Actions
export const useAppActions = () => useAppStore((state) => ({
  setUiState: state.setUiState,
  setGlobalActivity: state.setGlobalActivity,
  clearGlobalActivity: state.clearGlobalActivity,
  setSpectrumData: state.setSpectrumData,
  setWaterfallData: state.setWaterfallData,
  addWaterfallData: state.addWaterfallData,
  clearWaterfallData: state.clearWaterfallData,
  addMarker: state.addMarker,
  updateMarker: state.updateMarker,
  removeMarker: state.removeMarker,
  clearMarkers: state.clearMarkers,
  setDeviceStatus: state.setDeviceStatus,
  updateAnalyzerSettings: state.updateAnalyzerSettings,
  addRecording: state.addRecording,
  setRecordings: state.setRecordings,
  setCurrentRecording: state.setCurrentRecording,
  addSession: state.addSession,
  setSessions: state.setSessions,
  setCurrentSession: state.setCurrentSession,
  addPreset: state.addPreset,
  setPresets: state.setPresets,
  removePreset: state.removePreset,
  reset: state.reset,
}));
