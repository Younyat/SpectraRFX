import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Utility for combining Tailwind classes
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Frequency formatting utilities
export function formatFrequency(hz: number | null | undefined): string {
  if (!Number.isFinite(hz)) {
    return 'n/a';
  }
  const safeHz = Number(hz);
  if (safeHz >= 1e9) {
    return `${(safeHz / 1e9).toFixed(2)} GHz`;
  } else if (safeHz >= 1e6) {
    return `${(safeHz / 1e6).toFixed(2)} MHz`;
  } else if (safeHz >= 1e3) {
    return `${(safeHz / 1e3).toFixed(2)} kHz`;
  } else {
    return `${safeHz.toFixed(0)} Hz`;
  }
}

export function parseFrequency(value: number, unit: 'Hz' | 'kHz' | 'MHz' | 'GHz'): number {
  const multipliers = {
    Hz: 1,
    kHz: 1000,
    MHz: 1000000,
    GHz: 1000000000,
  };
  return value * multipliers[unit];
}

// Power level formatting
export function formatPowerLevel(db: number | null | undefined): string {
  if (!Number.isFinite(db)) {
    return 'n/a';
  }
  const safeDb = Number(db);
  return `${safeDb >= 0 ? '+' : ''}${safeDb.toFixed(1)} dB`;
}

export interface BandQualityEstimate {
  peakLevelDb: number;
  peakFrequencyHz: number;
  noiseFloorDb: number;
  snrDb: number;
}

export function estimateBandQuality(
  frequencies: number[],
  levelsDb: number[],
  startFrequencyHz: number,
  stopFrequencyHz: number,
): BandQualityEstimate | null {
  if (
    frequencies.length === 0 ||
    levelsDb.length === 0 ||
    frequencies.length !== levelsDb.length ||
    !Number.isFinite(startFrequencyHz) ||
    !Number.isFinite(stopFrequencyHz) ||
    stopFrequencyHz <= startFrequencyHz
  ) {
    return null;
  }

  const inBandLevels: number[] = [];
  const inBandFrequencies: number[] = [];
  const outOfBandLevels: number[] = [];

  for (let index = 0; index < frequencies.length; index += 1) {
    const frequency = frequencies[index];
    const level = levelsDb[index];
    if (!Number.isFinite(frequency) || !Number.isFinite(level)) continue;
    if (frequency >= startFrequencyHz && frequency <= stopFrequencyHz) {
      inBandLevels.push(level);
      inBandFrequencies.push(frequency);
    } else {
      outOfBandLevels.push(level);
    }
  }

  if (inBandLevels.length === 0) return null;

  let peakIndex = 0;
  let peakLevelDb = -Infinity;
  inBandLevels.forEach((level, index) => {
    if (level > peakLevelDb) {
      peakLevelDb = level;
      peakIndex = index;
    }
  });

  const noiseCandidates = outOfBandLevels.length >= 8 ? outOfBandLevels : levelsDb.filter(Number.isFinite);
  if (noiseCandidates.length === 0) return null;
  const sortedNoise = [...noiseCandidates].sort((a, b) => a - b);
  const noiseIndex = Math.min(sortedNoise.length - 1, Math.max(0, Math.floor(sortedNoise.length * 0.2)));
  const noiseFloorDb = sortedNoise[noiseIndex];

  return {
    peakLevelDb,
    peakFrequencyHz: inBandFrequencies[peakIndex],
    noiseFloorDb,
    snrDb: peakLevelDb - noiseFloorDb,
  };
}

// Time formatting
export function formatDuration(seconds: number | null | undefined): string {
  if (!Number.isFinite(seconds)) {
    return 'n/a';
  }
  const safeSeconds = Number(seconds);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = Math.floor(safeSeconds % 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  } else {
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  }
}

// File size formatting
export function formatFileSize(bytes: number | null | undefined): string {
  if (!Number.isFinite(bytes) || (bytes ?? 0) < 0) {
    return 'n/a';
  }
  const safeBytes = Number(bytes);
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = safeBytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }

  return `${size.toFixed(1)} ${units[unitIndex]}`;
}

// Debounce utility
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

// Throttle utility
export function throttle<T extends (...args: any[]) => any>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle: boolean;
  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

// Generate unique ID
export function generateId(): string {
  return Math.random().toString(36).substr(2, 9);
}

// Clamp value between min and max
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

// Linear interpolation
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

// Color utilities for spectrum visualization
export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h /= 360;
  s /= 100;
  l /= 100;

  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1/6) return p + (q - p) * 6 * t;
    if (t < 1/2) return q;
    if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
    return p;
  };

  let r, g, b;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }

  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

// Turbo colormap implementation
export function turboColormap(t: number): [number, number, number] {
  // Turbo colormap approximation
  const r = Math.max(0, Math.min(255,
    34.61 + t * (1172.33 - t * (10793.56 - t * (33300.12 - t * (38394.49 - t * 14825.05))))
  ));
  const g = Math.max(0, Math.min(255,
    23.31 + t * (557.33 + t * (1225.33 - t * (3574.96 - t * (1073.77 + t * 707.56))))
  ));
  const b = Math.max(0, Math.min(255,
    27.2 + t * (3211.1 - t * (15327.97 - t * (27814 - t * (22569.18 - t * 6838.66))))
  ));

  return [r, g, b];
}


export interface RfCaptureDiagnosticInput {
  source: 'live' | 'offline';
  centerFrequencyHz: number;
  bandwidthHz: number;
  peakFrequencyHz?: number | null;
  frequencyOffsetHz?: number | null;
  occupiedBandwidthHz?: number | null;
  snrDb?: number | null;
  clippingPct?: number | null;
  silencePct?: number | null;
  canonicalizationEnabled?: boolean;
  qualityFlags?: string[];
  liveOffsetHz?: number | null;
}

export interface RfCaptureDiagnostic {
  status: 'valid' | 'doubtful' | 'rejected';
  title: string;
  summary: string;
  recommendations: string[];
  facts: string[];
  offsetHz: number | null;
  absOffsetHz: number | null;
  halfBandwidthHz: number | null;
  edgeMarginHz: number | null;
  offsetRatio: number | null;
}

const formatDiagFrequency = (hz: number | null) => {
  if (!Number.isFinite(hz ?? NaN) || hz === null) return 'n/a';
  const abs = Math.abs(hz);
  if (abs >= 1e6) return `${(hz / 1e6).toFixed(6)} MHz`;
  if (abs >= 1e3) return `${(hz / 1e3).toFixed(2)} kHz`;
  return `${hz.toFixed(1)} Hz`;
};

export function buildRfCaptureDiagnostic(input: RfCaptureDiagnosticInput): RfCaptureDiagnostic {
  const halfBandwidthHz = Number.isFinite(input.bandwidthHz) && input.bandwidthHz > 0 ? input.bandwidthHz / 2 : null;
  const offsetHz = Number.isFinite(input.frequencyOffsetHz ?? NaN)
    ? Number(input.frequencyOffsetHz)
    : Number.isFinite(input.peakFrequencyHz ?? NaN) && Number.isFinite(input.centerFrequencyHz)
      ? Number(input.peakFrequencyHz) - Number(input.centerFrequencyHz)
      : null;
  const absOffsetHz = offsetHz === null ? null : Math.abs(offsetHz);
  const edgeMarginHz = halfBandwidthHz !== null && absOffsetHz !== null ? halfBandwidthHz - absOffsetHz : null;
  const offsetRatio = halfBandwidthHz && absOffsetHz !== null ? absOffsetHz / halfBandwidthHz : null;
  const occupiedRatio = input.occupiedBandwidthHz && input.bandwidthHz > 0 ? input.occupiedBandwidthHz / input.bandwidthHz : null;
  const snrDb = Number(input.snrDb ?? NaN);
  const clippingPct = Number(input.clippingPct ?? 0);
  const silencePct = Number(input.silencePct ?? 0);
  const recommendations: string[] = [];
  const facts: string[] = [];
  let status: RfCaptureDiagnostic['status'] = 'valid';

  if (offsetHz !== null) facts.push(`Offset relative to capture center: ${formatDiagFrequency(offsetHz)}.`);
  if (edgeMarginHz !== null) facts.push(`Estimated margin to nearest capture edge: ${formatDiagFrequency(edgeMarginHz)}.`);
  if (input.occupiedBandwidthHz) facts.push(`Occupied bandwidth uses ${(occupiedRatio! * 100).toFixed(1)}% of selected capture bandwidth.`);
  if (Number.isFinite(snrDb)) facts.push(`Estimated SNR: ${snrDb.toFixed(1)} dB.`);

  if (edgeMarginHz !== null && edgeMarginHz < 0) {
    status = 'rejected';
    recommendations.push('The strongest detected component is outside the selected capture window. Move M1/M2 or recenter before capturing.');
  } else if (edgeMarginHz !== null && edgeMarginHz < 20_000) {
    status = 'doubtful';
    recommendations.push('The capture has very little guard margin. This is a strong acquisition warning and the dataset should be treated as doubtful.');
  } else if (offsetRatio !== null && offsetRatio >= 0.85) {
    recommendations.push('The signal is close to the capture edge. Recenter the marker window or increase bandwidth slightly to keep more guard margin.');
  } else if (offsetRatio !== null && offsetRatio >= 0.60) {
    recommendations.push('The capture is valid, but the peak is not ideally centered. For RF fingerprinting, prefer more symmetric margin when possible.');
  } else {
    recommendations.push('The signal is well placed inside the capture window for this workflow.');
  }

  if (occupiedRatio !== null && occupiedRatio > 0.95) {
    recommendations.push('The occupied bandwidth almost fills the selected window. Consider a slightly wider band if it does not add unrelated emissions.');
  }
  if (Number.isFinite(snrDb) && snrDb < 10) {
    status = 'rejected';
    recommendations.push('SNR is too low for a reliable RF fingerprinting sample. Improve signal level or reduce noise before capturing.');
  } else if (Number.isFinite(snrDb) && snrDb < 15) {
    if (status === 'valid') status = 'doubtful';
    recommendations.push('SNR is usable but borderline. Prefer a stronger/cleaner capture for training.');
  }
  if (clippingPct > 1) {
    status = 'rejected';
    recommendations.push('Clipping is high. Reduce gain before using this sample.');
  }
  if (silencePct > 80) {
    status = 'rejected';
    recommendations.push('Most of the capture is silent. Use triggered capture or shorten the window around the burst.');
  }
  if (input.qualityFlags?.includes('pre_post_qc_mismatch')) {
    facts.push('Pre-capture live preview and post-capture QC show significant offset disagreement.');
    recommendations.push('The live preview detected a different peak location than the offline analysis. Review the spectrum manually to understand the discrepancy.');
  }
  if (input.canonicalizationEnabled !== false) {
    recommendations.push('The RF canonicalization stage will compensate coarse frequency offset before ML, so the model should not learn absolute SDR tuning center as the device identity.');
  }

  const title = status === 'valid' ? 'RF capture looks valid' : status === 'doubtful' ? 'RF capture needs attention' : 'RF capture is risky';
  const summary = status === 'valid'
    ? 'This sample is scientifically usable with the current RF fingerprinting pipeline.'
    : status === 'doubtful'
      ? 'This sample can be used, but acquisition quality can be improved before relying on it.'
      : 'This sample is likely to harm dataset quality unless the acquisition is corrected.';

  return { status, title, summary, recommendations, facts, offsetHz, absOffsetHz, halfBandwidthHz, edgeMarginHz, offsetRatio };
}
