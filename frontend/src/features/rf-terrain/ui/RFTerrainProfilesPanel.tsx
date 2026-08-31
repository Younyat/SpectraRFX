import React, { useMemo, useState } from 'react';
import { ListMusic } from 'lucide-react';
import { RF_PROFILE_LIST, applyRFProfile } from '../../../shared/rfProfiles';
import { useSpectrumController } from '../../../presentation/controllers/SpectrumController';
import { HudFrame } from './hud/HudFrame';
import { HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND } from './hud/hudTheme';

interface RFTerrainProfilesPanelProps {
  open: boolean;
  onToggleOpen: () => void;
}

// Frequency profiles (spec-adjacent "RF Profile" selector from Live
// Monitor): reuses the SAME shared, already-exported `RF_PROFILES` list
// (frontend/src/shared/rfProfiles.ts) and its pure `applyRFProfile()`
// helper -- the exact band definitions Live Monitor itself would tune to,
// never a second hand-typed copy. Tuning still goes through
// useSpectrumController, the same controller Live Monitor's own buttons use.
export const RFTerrainProfilesPanel: React.FC<RFTerrainProfilesPanelProps> = ({ open, onToggleOpen }) => {
  const controller = useSpectrumController();
  const [query, setQuery] = useState('');
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return RF_PROFILE_LIST;
    return RF_PROFILE_LIST.filter((profile) =>
      profile.label.toLowerCase().includes(q) || profile.family.toLowerCase().includes(q) || profile.signal_type.toLowerCase().includes(q));
  }, [query]);

  const tune = async (profile: (typeof RF_PROFILE_LIST)[number]) => {
    setBusyKey(profile.key);
    try {
      const applied = applyRFProfile(profile);
      await controller.setStartStop(applied.start_frequency_hz, applied.stop_frequency_hz);
      await controller.setSampleRate(applied.sample_rate_hz);
    } finally {
      setBusyKey(null);
    }
  };

  return (
    // bottom-14 (not bottom-3) so its trigger doesn't overlap Offline
    // Reconstruction's trigger directly below it in the same corner.
    <div className="pointer-events-none absolute bottom-14 right-3 z-20 flex flex-col items-end gap-2">
      {open && (
        <HudFrame className="pointer-events-auto flex max-h-[70vh] w-80 flex-col rounded-sm p-3 text-slate-100 shadow-2xl">
          <input
            type="text"
            placeholder="Search band... (BLE, Wi-Fi, LoRa, PMR446...)"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="mb-2 w-full rounded-md border bg-transparent px-2 py-1 text-xs"
            style={{ borderColor: 'var(--app-border)' }}
          />
          <div className="flex-1 space-y-1 overflow-y-auto">
            {filtered.map((profile) => (
              <button
                key={profile.key}
                disabled={busyKey !== null}
                onClick={() => tune(profile)}
                className="flex w-full flex-col rounded-md px-2 py-1 text-left text-xs hover:bg-white/10 disabled:opacity-40"
              >
                <span className="font-medium">{profile.label}</span>
                <span className="text-[10px] app-muted-text">{(profile.center_frequency_hz / 1e6).toFixed(3)} MHz · {profile.family}</span>
              </button>
            ))}
            {filtered.length === 0 && <p className="px-2 text-xs app-muted-text">No results.</p>}
          </div>
        </HudFrame>
      )}

      <button
        onClick={onToggleOpen}
        className="pointer-events-auto flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
        style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
      >
        <ListMusic className="h-3.5 w-3.5" />
        Profiles
      </button>
    </div>
  );
};
