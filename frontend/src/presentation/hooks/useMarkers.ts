import { useCallback, useEffect } from 'react';
import { useAppActions, useMarkers as useStoreMarkers, useSpectrumData } from '../../app/store/AppStore';
import { Marker } from '../../shared/types';
import { getLevelAtFrequency } from '../controllers/MarkerController';

export const useMarkerMeasurements = () => {
  const markers = useStoreMarkers();
  const spectrumData = useSpectrumData();
  const { updateMarker } = useAppActions();

  // Update marker levels based on current spectrum data
  useEffect(() => {
    if (!spectrumData) return;

    markers.forEach((marker: Marker) => {
      if (!marker.enabled) return;

      const level = getLevelAtFrequency(marker.frequency, spectrumData.frequencyArray, spectrumData.powerLevels);
      if (Number.isFinite(level) && Math.abs(marker.level - level) > 0.1) {
        updateMarker(marker.id, { level });
      }
    });
  }, [spectrumData, markers, updateMarker]);

  const getMarkerAtFrequency = useCallback((frequency: number, tolerance: number = 1000): Marker | null => {
    return markers.find(marker =>
      marker.enabled && Math.abs(marker.frequency - frequency) <= tolerance
    ) || null;
  }, [markers]);

  const getMarkersInRange = useCallback((startFreq: number, endFreq: number): Marker[] => {
    return markers.filter(marker =>
      marker.enabled &&
      marker.frequency >= startFreq &&
      marker.frequency <= endFreq
    );
  }, [markers]);

  const getPeakMarker = useCallback((): Marker | null => {
    return markers.find(marker => marker.type === 'peak') || null;
  }, [markers]);

  const getDeltaMarkers = useCallback((_referenceId: string): Marker[] => {
    return markers.filter(marker =>
      marker.type === 'delta' &&
      // In a real implementation, you'd check for reference relationship
      true
    );
  }, [markers]);

  return {
    markers,
    getMarkerAtFrequency,
    getMarkersInRange,
    getPeakMarker,
    getDeltaMarkers,
  };
};
