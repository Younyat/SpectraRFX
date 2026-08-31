import React from 'react';
import type { RFTerrainFrameSourceDiagnostics } from '../model/rfTerrainTypes';
import { RF_TERRAIN_DEFAULT_FREQUENCY_BINS } from '../model/rfTerrainConstants';
import { HUD_BORDER_COLOR, HUD_PANEL_BACKGROUND } from './hud/hudTheme';

interface RFTerrainStatusProps {
  diagnostics: RFTerrainFrameSourceDiagnostics;
  fps: number;
  webglVersion: number;
  frozen: boolean;
}

// Local performance/diagnostic line (spec §94):
// "LIVE | WebGL2 | 38 FPS | 4096→512 bins | 240 rows | dropped 0"
export const RFTerrainStatus: React.FC<RFTerrainStatusProps> = ({ diagnostics, fps, webglVersion, frozen }) => (
  <div
    className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-3 py-1 text-[11px] font-mono tracking-wide text-cyan-100/60"
    style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND }}
  >
    <span className={frozen ? 'text-amber-400' : 'text-emerald-300'}>{frozen ? 'FROZEN' : 'LIVE'}</span>
    <span>ARST CORE</span>
    <span>WebGL{webglVersion || '?'}</span>
    <span className="text-cyan-200">{fps} FPS -- GPU OPTIMIZED</span>
    <span>→{RF_TERRAIN_DEFAULT_FREQUENCY_BINS} bins</span>
    <span>{diagnostics.ringBufferSize}/{diagnostics.ringBufferCapacity} rows</span>
    <span>gen {diagnostics.generation}</span>
    <span>dropped {diagnostics.droppedProcessingFrames}</span>
    <span>invalid {diagnostics.invalidFrames}</span>
    <span>{diagnostics.state}</span>
  </div>
);
