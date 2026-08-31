import { useEffect, useRef, useState } from 'react';
import { useAppStore, useWaterfallData, useAnalyzerSettings, useDeviceStatus } from '../../app/store/AppStore';
import { ApiService } from '../../app/services/ApiService';
import { RUNTIME_CONFIG } from '../../shared/config/runtime';
import { turboColormap } from '../../shared/utils';

const apiService = new ApiService();

export const useWaterfall = (enabled = true, displayData: ReturnType<typeof useWaterfallData> | null = null, displaySettings: ReturnType<typeof useAnalyzerSettings> | null = null) => {
  const liveWaterfallData = useWaterfallData();
  const waterfallData = displayData ?? liveWaterfallData;
  const liveSettings = useAnalyzerSettings();
  const settings = displaySettings ?? liveSettings;
  const deviceStatus = useDeviceStatus();
  const addWaterfallData = useAppStore((state) => state.addWaterfallData);
  const clearWaterfallData = useAppStore((state) => state.clearWaterfallData);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageDataRef = useRef<ImageData | null>(null);
  const waterfallKeyRef = useRef('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Draw waterfall on canvas
  useEffect(() => {
    if (!canvasRef.current || waterfallData.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const { width, height } = canvas;
    const waterfallKey = `${settings.centerFrequency}:${settings.span}:${width}:${height}`;

    if (waterfallKeyRef.current !== waterfallKey) {
      imageDataRef.current = null;
      waterfallKeyRef.current = waterfallKey;
      ctx.clearRect(0, 0, width, height);
    }

    const maxHistory = Math.min(waterfallData.length, height);

    // Create or reuse ImageData
    if (!imageDataRef.current || imageDataRef.current.width !== width || imageDataRef.current.height !== height) {
      imageDataRef.current = ctx.createImageData(width, height);
    }

    const imageData = imageDataRef.current;
    const data = imageData.data;

    // Shift existing data down
    for (let y = height - 1; y >= 1; y--) {
      for (let x = 0; x < width; x++) {
        const srcIndex = ((y - 1) * width + x) * 4;
        const dstIndex = (y * width + x) * 4;

        data[dstIndex] = data[srcIndex];     // R
        data[dstIndex + 1] = data[srcIndex + 1]; // G
        data[dstIndex + 2] = data[srcIndex + 2]; // B
        data[dstIndex + 3] = data[srcIndex + 3]; // A
      }
    }

    // Add new spectrum data at the top
    if (waterfallData.length > 0) {
      const latestData = waterfallData[waterfallData.length - 1];
      const powerLevels = latestData.data[0] || []; // Assuming single row for simplicity
      const sourceCenter = latestData.centerFrequency || settings.centerFrequency;
      const sourceSpan = latestData.span || settings.span;
      const sourceStart = sourceCenter - sourceSpan / 2;
      const viewStart = settings.centerFrequency - settings.span / 2;
      const powerRange = Math.max(settings.dbPerDiv, 1) * 10;
      const powerTop = settings.referenceLevel;
      const powerBottom = powerTop - powerRange;

      for (let x = 0; x < width; x++) {
        const frequency = viewStart + (x / Math.max(width - 1, 1)) * settings.span;
        const relativeSource = (frequency - sourceStart) / Math.max(sourceSpan, 1);
        const powerIndex = Math.floor(relativeSource * powerLevels.length);
        const powerLevel = powerLevels[powerIndex] || -100;

        // Normalize power level to 0-1 range
        const normalizedPower = Math.max(0, Math.min(1, (powerLevel + settings.noiseFloorOffset - powerBottom) / powerRange));

        // Get color from turbo colormap
        const [r, g, b] = turboColormap(normalizedPower);

        const index = x * 4;
        data[index] = r;     // R
        data[index + 1] = g; // G
        data[index + 2] = b; // B
        data[index + 3] = 255; // A (fully opaque)
      }
    }

    // Put the image data on the canvas
    ctx.putImageData(imageData, 0, 0);

    // Draw frequency axis labels
    ctx.fillStyle = '#ffffff';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';

    const freqRange = settings.span;
    const freqStart = settings.centerFrequency - freqRange / 2;

    for (let i = 0; i <= 10; i++) {
      const x = (i / 10) * width;
      const freq = freqStart + (i / 10) * freqRange;

      // Draw tick mark
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, height - 20);
      ctx.lineTo(x, height - 15);
      ctx.stroke();

      // Draw label
      ctx.fillText(`${(freq / 1000000).toFixed(1)}M`, x, height - 5);
    }

    // Draw time axis labels
    ctx.textAlign = 'right';
    for (let i = 0; i < maxHistory; i += Math.max(1, Math.floor(maxHistory / 5))) {
      const y = height - i - 1;
      const timeOffset = ((maxHistory - i) * RUNTIME_CONFIG.waterfallPollIntervalMs) / 1000;

      ctx.fillText(`${timeOffset.toFixed(1)}s`, width - 5, y + 4);
    }

  }, [waterfallData, settings]);

  useEffect(() => {
    let cancelled = false;

    if (!enabled) {
      return;
    }

    if (!deviceStatus.isConnected) {
      clearWaterfallData();
      return;
    }

    // Same bottleneck fix as useSpectrum.ts: skip a tick entirely if the
    // previous one is still in flight, instead of ever stacking overlapping
    // requests behind a slow response.
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        setIsLoading(true);
        const data = await apiService.getLiveWaterfall();
        if (!cancelled && data.data.length > 0) {
          addWaterfallData(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to refresh waterfall');
        }
      } finally {
        inFlight = false;
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    refresh();
    const interval = setInterval(refresh, RUNTIME_CONFIG.waterfallPollIntervalMs);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [addWaterfallData, clearWaterfallData, deviceStatus.isConnected, enabled]);

  return {
    waterfallData,
    settings,
    isLoading,
    error,
    canvasRef,
  };
};
