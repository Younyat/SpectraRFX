import React from 'react';
import type { RFTerrainCameraPreset } from '../model/rfTerrainTypes';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_PANEL_BACKGROUND } from './hud/hudTheme';

export interface RFTerrainFrequencyInfo {
  centerFrequencyHz: number;
  spanHz: number;
  sampleRateHz?: number;
  effectiveRbwHz?: number;
  powerUnit?: 'dBFS' | 'dBm';
  deviceSerial?: string;
  calibrationId?: string;
}

interface RFTerrainToolbarProps {
  frequencyInfo: RFTerrainFrequencyInfo | null;
  cameraPreset: RFTerrainCameraPreset;
  onCameraPresetChange: (preset: RFTerrainCameraPreset) => void;
  frozen: boolean;
  onFrozenToggle: () => void;
  onReset: () => void;
  viewOffsetRows: number;
  maxOffsetRows: number;
  onViewOffsetChange: (offsetRows: number) => void;
  pollIntervalMs: number;
}

const buttonClass = (active: boolean) =>
  `rounded-sm border px-3 py-1 text-xs font-medium tracking-wide transition-colors ${active ? 'text-slate-950' : 'text-cyan-100/80 hover:text-cyan-50'}`;

const buttonStyle = (active: boolean): React.CSSProperties => ({
  borderColor: HUD_BORDER_COLOR,
  background: active ? HUD_ACCENT_BRIGHT : 'transparent',
});

const formatHz = (hz: number) => (hz >= 1e9 ? `${(hz / 1e9).toFixed(4)} GHz` : hz >= 1e6 ? `${(hz / 1e6).toFixed(3)} MHz` : `${(hz / 1e3).toFixed(1)} kHz`);

// Control dock (camera presets, freeze/reset, bounded rewind -- see
// RF_TERRAIN_REWIND_MAX_OFFSET_ROWS so scrubbing back never grows memory
// beyond the already-bounded extended history cache). The live frequency/
// time/power readout itself now floats over the canvas as HUD badges
// (RFTerrainHudBadges.tsx) instead of living here.
export const RFTerrainToolbar: React.FC<RFTerrainToolbarProps> = ({
  frequencyInfo, cameraPreset, onCameraPresetChange, frozen, onFrozenToggle, onReset,
  viewOffsetRows, maxOffsetRows, onViewOffsetChange, pollIntervalMs,
}) => {
  const secondsBack = (viewOffsetRows * pollIntervalMs) / 1000;
  const maxSecondsBack = (maxOffsetRows * pollIntervalMs) / 1000;

  return (
    <div
      className="flex flex-col gap-2 border-b p-2"
      style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND }}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono text-cyan-100/60">
        {frequencyInfo ? (
          <>
            <span>Span <strong className="text-slate-100">{formatHz(frequencyInfo.spanHz)}</strong></span>
            {frequencyInfo.sampleRateHz != null && <span>SR {formatHz(frequencyInfo.sampleRateHz)}</span>}
            {frequencyInfo.effectiveRbwHz != null && <span>RBW {formatHz(frequencyInfo.effectiveRbwHz)}</span>}
            <span>Unit {frequencyInfo.powerUnit ?? 'dBFS'}</span>
            <span>Calibration {frequencyInfo.calibrationId ?? 'none'}</span>
          </>
        ) : (
          <span>No frames yet -- waiting for device</span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {(['3d', 'top', 'front', 'side'] as const).map((preset) => (
            <button key={preset} className={buttonClass(cameraPreset === preset)} style={buttonStyle(cameraPreset === preset)} onClick={() => onCameraPresetChange(preset)}>
              {preset.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="ml-auto flex gap-2">
          <button className={buttonClass(frozen)} style={buttonStyle(frozen)} onClick={onFrozenToggle}>{frozen ? 'RESUME' : 'FREEZE'}</button>
          <button className={buttonClass(false)} style={buttonStyle(false)} onClick={onReset}>RESET TERRAIN</button>
        </div>
      </div>

      <div className="flex items-center gap-2 text-[11px] text-cyan-100/60">
        <span className="w-14 flex-shrink-0 font-mono">{viewOffsetRows === 0 ? 'LIVE' : `-${secondsBack.toFixed(1)}s`}</span>
        <input
          type="range"
          min={0}
          max={maxOffsetRows}
          step={1}
          value={viewOffsetRows}
          onChange={(event) => onViewOffsetChange(Number(event.target.value))}
          className="flex-1 accent-cyan-300"
        />
        <span className="w-16 flex-shrink-0 text-right font-mono">-{maxSecondsBack.toFixed(0)}s max</span>
      </div>
    </div>
  );
};
