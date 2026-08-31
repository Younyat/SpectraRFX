import React from 'react';
import { HudBadge } from './hud/HudBadge';
import type { RFTerrainFrequencyInfo } from './RFTerrainToolbar';
import type { TerrainInspectorSelection } from '../model/rfTerrainTypes';

interface RFTerrainHudBadgesProps {
  frequencyInfo: RFTerrainFrequencyInfo | null;
  lastFrameTimestamp: number | null;
  selection: TerrainInspectorSelection | null;
}

const formatMHz = (hz: number) => `${(hz / 1e6).toFixed(3)} MHz`;

const formatClock = (epochMs: number) => {
  const date = new Date(epochMs);
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  const ms = String(date.getMilliseconds()).padStart(3, '0');
  return `${hh}:${mm}:${ss}.${ms}`;
};

// Floating readout row over the canvas top edge -- every value is real:
// FREQUENCY is the actual tuned center frequency, TIME is the real
// timestamp of the last accepted row (never a fake ticking system
// clock), and POWER only shows a number once something is actually
// selected -- otherwise an honest em dash, never a fabricated reading.
export const RFTerrainHudBadges: React.FC<RFTerrainHudBadgesProps> = ({ frequencyInfo, lastFrameTimestamp, selection }) => (
  <div className="pointer-events-none absolute left-1/2 top-3 z-20 flex -translate-x-1/2 gap-2">
    <HudBadge label="Frequency" value={frequencyInfo ? formatMHz(frequencyInfo.centerFrequencyHz) : '—'} />
    <HudBadge label="Time" value={lastFrameTimestamp !== null ? formatClock(lastFrameTimestamp) : '—'} />
    <HudBadge label="Power" value={selection ? `${selection.rawPowerDb.toFixed(1)} ${selection.powerUnit}` : '—'} />
  </div>
);
