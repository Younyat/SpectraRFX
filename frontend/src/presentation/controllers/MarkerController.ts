import { useCallback } from 'react';
import { useAppActions, useMarkers, useSpectrumData } from '../../app/store/AppStore';
import { ApiService } from '../../app/services/ApiService';
import { Marker } from '../../shared/types';

const apiService = new ApiService();

export const getLevelAtFrequency = (frequency: number, frequencies: number[], levels: number[]): number => {
  if (frequencies.length === 0 || levels.length === 0 || frequencies.length !== levels.length) {
    return Number.NaN;
  }
  if (frequency <= frequencies[0]) {
    return levels[0];
  }
  if (frequency >= frequencies[frequencies.length - 1]) {
    return levels[levels.length - 1];
  }

  let low = 0;
  let high = frequencies.length - 1;
  while (high - low > 1) {
    const mid = Math.floor((low + high) / 2);
    if (frequencies[mid] <= frequency) {
      low = mid;
    } else {
      high = mid;
    }
  }

  const f0 = frequencies[low];
  const f1 = frequencies[high];
  const l0 = levels[low];
  const l1 = levels[high];
  const t = f1 === f0 ? 0 : (frequency - f0) / (f1 - f0);
  return l0 + (l1 - l0) * t;
};

export const useMarkerController = () => {
  const actions = useAppActions();
  const markers = useMarkers();
  const spectrumData = useSpectrumData();

  const createMarker = useCallback(async (frequency: number, label?: string, level?: number): Promise<Marker> => {
    const resolvedLevel = level ?? (
      spectrumData
        ? getLevelAtFrequency(frequency, spectrumData.frequencyArray, spectrumData.powerLevels)
        : Number.NaN
    );

    const marker = await apiService.createMarker({
      label: label || `M${markers.length + 1}`,
      frequency,
      level: Number.isFinite(resolvedLevel) ? resolvedLevel : 0,
      type: 'normal',
      enabled: true,
    });

    const normalizedMarker = {
      ...marker,
      level: Number.isFinite(resolvedLevel) ? resolvedLevel : marker.level,
    };
    actions.addMarker(normalizedMarker);
    return normalizedMarker;
  }, [actions, markers.length, spectrumData]);

  const deleteMarker = useCallback(async (id: string) => {
    await apiService.deleteMarker(id);
    actions.removeMarker(id);
  }, [actions]);

  const updateMarker = useCallback((id: string, updates: Partial<Marker>) => {
    actions.updateMarker(id, updates);
  }, [actions]);

  const clearAllMarkers = useCallback(() => {
    actions.clearMarkers();
  }, [actions]);

  const createPeakMarker = useCallback(async (): Promise<Marker> => {
    if (!spectrumData || spectrumData.powerLevels.length === 0) {
      throw new Error('No spectrum data available');
    }

    let peakIndex = 0;
    let peakLevel = -Infinity;
    spectrumData.powerLevels.forEach((level, index) => {
      if (level > peakLevel) {
        peakLevel = level;
        peakIndex = index;
      }
    });

    const peakFrequency = spectrumData.frequencyArray[peakIndex];
    return createMarker(peakFrequency, `Peak ${peakLevel.toFixed(1)} dB`, peakLevel);
  }, [createMarker, spectrumData]);

  return {
    createMarker,
    deleteMarker,
    updateMarker,
    clearAllMarkers,
    createPeakMarker,
  };
};
