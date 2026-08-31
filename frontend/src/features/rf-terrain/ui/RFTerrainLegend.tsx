import React from 'react';
import type { RFTerrainMode } from '../model/rfTerrainTypes';
import type { RFTerrainColorSource } from './RFTerrainCanvas';
import { RF_TERRAIN_MAX_EXCESS_DB, RF_TERRAIN_RAW_DISPLAY_MAX_DB, RF_TERRAIN_RAW_DISPLAY_MIN_DB } from '../model/rfTerrainConstants';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND } from './hud/hudTheme';

const HEIGHT_TEXT: Record<RFTerrainMode, string> = {
  raw: `raw power [${RF_TERRAIN_RAW_DISPLAY_MIN_DB}, ${RF_TERRAIN_RAW_DISPLAY_MAX_DB}] dB (RAW POWER TERRAIN -- reference/validation mode)`,
  adaptive: `0-${RF_TERRAIN_MAX_EXCESS_DB} dB above the estimated noise floor ("excess over noise", not a calibrated SNR)`,
  occupancy: `0-${RF_TERRAIN_MAX_EXCESS_DB} dB above the estimated noise floor (same height as ADAPTIVE)`,
  density: `0-${RF_TERRAIN_MAX_EXCESS_DB} dB of excess, smoothed across frequency (same quantity as ADAPTIVE, not a calibrated PSD -- the inspector still shows the real, unsmoothed value)`,
};

const COLOR_TEXT: Record<RFTerrainColorSource, string> = {
  magnitude: 'same magnitude as height -- heat map: equal power/excess = equal color, tall peaks = warm colors',
  persistence: 'persistence 0%-100% (independent of height)',
  occupancy: 'occupancy 0%-100% -- fraction of recent time active, by real Δt (independent of height)',
};

// Every mode must show an explicit height/color unit+range legend (spec §65)
// -- without it the representation "loses scientific value." Color source
// is now independently selectable from height (mode), so the legend reads
// both together rather than assuming a fixed pairing.
export const RFTerrainLegend: React.FC<{ mode: RFTerrainMode; colorSource: RFTerrainColorSource }> = ({ mode, colorSource }) => (
  <div
    className="pointer-events-none absolute bottom-2 left-2 rounded-sm border px-3 py-2 text-[11px] text-cyan-100/70 backdrop-blur"
    style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
  >
    <div><span style={{ color: HUD_ACCENT_BRIGHT }}>HEIGHT</span>: {HEIGHT_TEXT[mode]}</div>
    <div><span style={{ color: HUD_ACCENT_BRIGHT }}>COLOR</span>: {COLOR_TEXT[colorSource]}</div>
  </div>
);
