import React, { useRef } from 'react';
import { Link } from 'react-router-dom';
import { useRFTerrainFrameSource } from '../data/useRFTerrainFrameSource';
import { colormapFor } from '../render/TerrainColors';
import { RF_TERRAIN_LEGACY_WATERFALL_PATH, RF_TERRAIN_RAW_DISPLAY_MAX_DB, RF_TERRAIN_RAW_DISPLAY_MIN_DB } from '../model/rfTerrainConstants';
import type { TerrainProcessedRow } from '../model/rfTerrainTypes';

const HEATMAP_HEIGHT = 120;

// Internal 2D fallback (spec §53): used when WebGL is unavailable or the
// 3D renderer degrades. Consumes the SAME frame-source hook as the 3D path
// -- its own instance, but never the full legacy WaterfallView, which
// would start a second, competing acquisition loop.
export const RFTerrainFallback2D: React.FC = () => {
  const traceCanvasRef = useRef<HTMLCanvasElement>(null);
  const heatmapCanvasRef = useRef<HTMLCanvasElement>(null);

  const { diagnostics } = useRFTerrainFrameSource({
    onRow: (row: TerrainProcessedRow) => {
      const traceCanvas = traceCanvasRef.current;
      const heatmapCanvas = heatmapCanvasRef.current;
      if (!traceCanvas || !heatmapCanvas) return;

      const bins = row.frame.powerLevels.length;
      const traceCtx = traceCanvas.getContext('2d');
      if (traceCtx) {
        const { width, height } = traceCanvas;
        traceCtx.fillStyle = '#020617';
        traceCtx.fillRect(0, 0, width, height);
        traceCtx.strokeStyle = '#38bdf8';
        traceCtx.lineWidth = 1.5;
        traceCtx.beginPath();
        for (let i = 0; i < bins; i += 1) {
          const x = (i / (bins - 1)) * width;
          const normalized = Math.min(1, Math.max(0, (row.frame.powerLevels[i] - RF_TERRAIN_RAW_DISPLAY_MIN_DB) / (RF_TERRAIN_RAW_DISPLAY_MAX_DB - RF_TERRAIN_RAW_DISPLAY_MIN_DB)));
          const y = height - normalized * height;
          if (i === 0) traceCtx.moveTo(x, y); else traceCtx.lineTo(x, y);
        }
        traceCtx.stroke();
      }

      const heatmapCtx = heatmapCanvas.getContext('2d');
      if (heatmapCtx) {
        const { width, height } = heatmapCanvas;
        heatmapCtx.drawImage(heatmapCanvas, 0, 1, width, height - 1, 0, 0, width, height - 1);
        const colormap = colormapFor('turbo');
        for (let i = 0; i < bins; i += 1) {
          const x = Math.floor((i / bins) * width);
          const normalized = Math.min(1, Math.max(0, (row.frame.powerLevels[i] - RF_TERRAIN_RAW_DISPLAY_MIN_DB) / (RF_TERRAIN_RAW_DISPLAY_MAX_DB - RF_TERRAIN_RAW_DISPLAY_MIN_DB)));
          const [r, g, b] = colormap(normalized);
          heatmapCtx.fillStyle = `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
          heatmapCtx.fillRect(x, height - 1, Math.ceil(width / bins), 1);
        }
      }
    },
  });

  return (
    <div className="flex h-full w-full flex-col gap-3 p-4">
      <div className="rounded-xl border p-2 text-xs app-muted-text" style={{ borderColor: 'var(--app-border)' }}>
        RF Terrain -- 2D fallback mode (WebGL unavailable or degraded). State: <strong>{diagnostics.state}</strong>
        {diagnostics.lastError && <span> · {diagnostics.lastError}</span>}
      </div>
      <canvas ref={traceCanvasRef} width={800} height={200} className="w-full rounded-xl border" style={{ borderColor: 'var(--app-border)' }} />
      <canvas ref={heatmapCanvasRef} width={800} height={HEATMAP_HEIGHT} className="w-full rounded-xl border" style={{ borderColor: 'var(--app-border)' }} />
      <Link to={RF_TERRAIN_LEGACY_WATERFALL_PATH} className="text-sm underline app-muted-text hover:opacity-80">
        Open Waterfall (legacy)
      </Link>
    </div>
  );
};
