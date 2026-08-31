import { SpectrumData, WaterfallData, Marker, DeviceStatus, AnalyzerSettings, Recording, Session, Preset } from '../../shared/types';

export class SpectrumModel {
  private data: SpectrumData | null = null;
  private listeners: ((data: SpectrumData | null) => void)[] = [];

  setData(data: SpectrumData) {
    this.data = data;
    this.notifyListeners();
  }

  getData(): SpectrumData | null {
    return this.data;
  }

  subscribe(listener: (data: SpectrumData | null) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  private notifyListeners() {
    this.listeners.forEach(listener => listener(this.data));
  }
}

export class WaterfallModel {
  private data: WaterfallData[] = [];
  private maxHistory = 100;

  addData(data: WaterfallData) {
    this.data.push(data);
    if (this.data.length > this.maxHistory) {
      this.data.shift();
    }
  }

  getData(): WaterfallData[] {
    return [...this.data];
  }

  clear() {
    this.data = [];
  }

  setMaxHistory(max: number) {
    this.maxHistory = max;
    if (this.data.length > max) {
      this.data = this.data.slice(-max);
    }
  }
}

export class MarkerModel {
  private markers: Marker[] = [];

  addMarker(marker: Omit<Marker, 'id'>): Marker {
    const newMarker: Marker = {
      ...marker,
      id: crypto.randomUUID(),
    };
    this.markers.push(newMarker);
    return newMarker;
  }

  updateMarker(id: string, updates: Partial<Marker>) {
    const index = this.markers.findIndex(m => m.id === id);
    if (index !== -1) {
      this.markers[index] = { ...this.markers[index], ...updates };
    }
  }

  removeMarker(id: string) {
    this.markers = this.markers.filter(m => m.id !== id);
  }

  getMarkers(): Marker[] {
    return [...this.markers];
  }

  getMarker(id: string): Marker | undefined {
    return this.markers.find(m => m.id === id);
  }

  clearMarkers() {
    this.markers = [];
  }
}

export class DeviceModel {
  private status: DeviceStatus = {
    isConnected: false,
    driver: 'uhd_gnuradio',
    centerFrequency: 89400000,
    sampleRate: 2000000,
    gain: 0,
  };

  private listeners: ((status: DeviceStatus) => void)[] = [];

  setStatus(status: Partial<DeviceStatus>) {
    this.status = { ...this.status, ...status };
    this.notifyListeners();
  }

  getStatus(): DeviceStatus {
    return { ...this.status };
  }

  subscribe(listener: (status: DeviceStatus) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  private notifyListeners() {
    this.listeners.forEach(listener => listener(this.status));
  }
}

export class AnalyzerSettingsModel {
  private settings: AnalyzerSettings = {
    centerFrequency: 89400000,
    span: 2000000,
    sampleRate: 4000000,
    rbw: 10000,
    vbw: 10000,
    referenceLevel: 0,
    noiseFloorOffset: 0,
    detectorMode: 'sample',
    traceMode: 'clear_write',
    dbPerDiv: 10,
    colorScheme: 'blue',
    averaging: 1,
    smoothing: 0,
  };

  private listeners: ((settings: AnalyzerSettings) => void)[] = [];

  updateSettings(updates: Partial<AnalyzerSettings>) {
    this.settings = { ...this.settings, ...updates };
    this.notifyListeners();
  }

  getSettings(): AnalyzerSettings {
    return { ...this.settings };
  }

  subscribe(listener: (settings: AnalyzerSettings) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  private notifyListeners() {
    this.listeners.forEach(listener => listener(this.settings));
  }
}

export class RecordingModel {
  private recordings: Recording[] = [];
  private currentRecording: Recording | null = null;

  addRecording(recording: Recording) {
    this.recordings.push(recording);
  }

  setCurrentRecording(recording: Recording | null) {
    this.currentRecording = recording;
  }

  getCurrentRecording(): Recording | null {
    return this.currentRecording;
  }

  getRecordings(): Recording[] {
    return [...this.recordings];
  }

  getRecordingsBySession(sessionId: string): Recording[] {
    return this.recordings.filter(r => r.sessionId === sessionId);
  }
}

export class SessionModel {
  private sessions: Session[] = [];
  private currentSession: Session | null = null;

  addSession(session: Session) {
    this.sessions.push(session);
  }

  setCurrentSession(session: Session | null) {
    this.currentSession = session;
  }

  getCurrentSession(): Session | null {
    return this.currentSession;
  }

  getSessions(): Session[] {
    return [...this.sessions];
  }

  getSession(id: string): Session | undefined {
    return this.sessions.find(s => s.id === id);
  }
}

export class PresetModel {
  private presets: Preset[] = [];

  addPreset(preset: Preset) {
    this.presets.push(preset);
  }

  removePreset(id: string) {
    this.presets = this.presets.filter(p => p.id !== id);
  }

  getPresets(): Preset[] {
    return [...this.presets];
  }

  getPreset(id: string): Preset | undefined {
    return this.presets.find(p => p.id === id);
  }
}
