export type SpectrumToolKind =
  | 'max_hold' | 'min_hold' | 'power_average' | 'rms_power' | 'ewma'
  | 'percentiles' | 'trace_history' | 'density' | 'spectrum_mask'
  | 'gated_spectrum' | 'zero_span' | 'occupancy';

export type SpectrumToolStatus = 'inactive' | 'collecting' | 'ready' | 'paused' | 'insufficient_data' | 'stale' | 'error' | 'unavailable';

export interface SpectrumToolConfig {
  ewmaTauSeconds?: number;
  percentileWindow?: number;
  historyFrames?: number;
  thresholdDb?: number;
  maskUpperDb?: number;
}

export interface SpectrumToolInstance {
  active: boolean;
  visible: boolean;
  status: SpectrumToolStatus;
  sampleCount: number;
  color: string;
  config: SpectrumToolConfig;
  message?: string;
}

export interface SpectrumLineSeries {
  id: string;
  toolId: string;
  label: string;
  frequenciesHz: number[];
  powerLevelsDb: number[];
  color: string;
  opacity: number;
  lineWidth: number;
  lineDash: number[];
  visible: boolean;
  zIndex: number;
}

export interface SpectrumRasterLayer {
  id: string;
  toolId: string;
  kind: 'density' | 'occupancy';
  width: number;
  height: number;
  values: number[];
  opacity: number;
  visible: boolean;
  zIndex: number;
}

export interface SpectrumAnnotation {
  id: string;
  toolId: string;
  type: 'mask_upper' | 'threshold';
  coordinates: number[];
  label?: string;
  color: string;
  visible: boolean;
}
