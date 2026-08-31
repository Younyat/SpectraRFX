import React, { useState } from 'react';
import { Move } from 'lucide-react';
import { useSpectrumController } from '../../../presentation/controllers/SpectrumController';
import { useAnalyzerSettings } from '../../../app/store/AppStore';
import { HudFrame } from './hud/HudFrame';
import { HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND } from './hud/hudTheme';

interface RFTerrainPanControlProps {
  open: boolean;
  onToggleOpen: () => void;
}

// Its own small floating transparent window (Live Monitor groups Pan as
// its own control: Left / Step MHz / Right), kept separate from the
// bigger Receiver panel so it can stay open on its own while panning
// repeatedly through a band.
export const RFTerrainPanControl: React.FC<RFTerrainPanControlProps> = ({ open, onToggleOpen }) => {
  const settings = useAnalyzerSettings();
  const controller = useSpectrumController();
  const [stepMHz, setStepMHz] = useState(0.2);
  const [busy, setBusy] = useState(false);

  const pan = async (direction: 1 | -1) => {
    setBusy(true);
    try {
      await controller.setCenterFrequency(settings.centerFrequency + direction * stepMHz * 1e6);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-20 flex flex-col items-start gap-2">
      {open && (
        <HudFrame className="pointer-events-auto flex items-center gap-2 rounded-sm p-2 text-slate-100 shadow-2xl">
          <button disabled={busy} onClick={() => pan(-1)} className="rounded-sm border px-3 py-1 text-xs text-cyan-100/80 disabled:opacity-40" style={{ borderColor: HUD_BORDER_COLOR }}>◀ Left</button>
          <label className="flex flex-col items-center gap-0.5 text-[10px] app-muted-text">
            Step MHz
            <input
              type="number"
              step={0.1}
              value={stepMHz}
              onChange={(event) => setStepMHz(Number(event.target.value))}
              className="w-16 rounded-md border bg-transparent px-1 py-0.5 text-center text-xs text-slate-100"
              style={{ borderColor: 'var(--app-border)' }}
            />
          </label>
          <button disabled={busy} onClick={() => pan(1)} className="rounded-sm border px-3 py-1 text-xs text-cyan-100/80 disabled:opacity-40" style={{ borderColor: HUD_BORDER_COLOR }}>Right ▶</button>
        </HudFrame>
      )}
      <button
        onClick={onToggleOpen}
        className="pointer-events-auto flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
        style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
      >
        <Move className="h-3.5 w-3.5" />
        Pan
      </button>
    </div>
  );
};
