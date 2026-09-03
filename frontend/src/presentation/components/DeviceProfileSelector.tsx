import React, { useEffect, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { useSpectrumController } from '../controllers/SpectrumController';

const api = new ApiService();

interface DeviceProfile {
  id: string;
  label: string;
  description: string;
  values: Record<string, string | number>;
}

interface DeviceProfilesPayload {
  profiles: DeviceProfile[];
  active_profile_id: string | null;
}

// Lets the operator pick which real receiver (B200 vs NI USRP-2932, or any
// future profile) BEFORE clicking Connect, right where Connect lives (Live
// Monitor and RF Terrain 3D both mount this) -- so a leftover frequency
// valid for the previous device never surfaces the confusing
// "center_frequency_hz must be between ... for <device>" rejection.
// Deliberately not just a Settings-page action: applying a profile here
// also (1) disconnects any live session against the OLD device and (2)
// pushes the new profile's own real starting frequency/sample-rate/gain
// into the SAME shared AnalyzerSettings this view's Connect button reads,
// through useSpectrumController() -- the exact controller Live Monitor and
// RF Terrain already share (see RFTerrainReceiverControls's own docstring:
// "so both views agree on what the one physical ... is actually doing").
// Backend-side, rf_safety.current_limits()/active_device_args() now read
// runtime_settings.json live on every request, so none of this needs a
// backend restart -- only Connect (a real hardware action) is left for the
// operator to press deliberately.
export const DeviceProfileSelector: React.FC<{ className?: string }> = ({ className }) => {
  const controller = useSpectrumController();
  const [payload, setPayload] = useState<DeviceProfilesPayload | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const load = () => {
    api.getDeviceProfiles()
      .then((data) => setPayload(data as DeviceProfilesPayload))
      .catch((err) => console.error('Failed to load device profiles:', err));
  };

  useEffect(() => { load(); }, []);

  const applyProfile = async (profile: DeviceProfile) => {
    setApplyingId(profile.id);
    setError(null);
    setReady(false);
    try {
      await api.applyDeviceProfile(profile.id);
      // A worker still running against the OLD device must not linger.
      await controller.disconnectDevice().catch(() => undefined);
      const centerHz = profile.values.DEFAULT_CENTER_FREQUENCY_HZ;
      const sampleRateHz = profile.values.DEFAULT_SAMPLE_RATE_HZ;
      const gainDb = profile.values.DEFAULT_GAIN_DB;
      if (typeof centerHz === 'number') await controller.setCenterFrequency(centerHz);
      if (typeof sampleRateHz === 'number') await controller.setSampleRate(sampleRateHz);
      if (typeof gainDb === 'number') await controller.setGain(gainDb);
      load();
      setReady(true);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'No se pudo aplicar el perfil de dispositivo.');
    } finally {
      setApplyingId(null);
    }
  };

  if (!payload || payload.profiles.length === 0) return null;

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs app-muted-text">Device:</span>
        {payload.profiles.map((profile) => {
          const active = payload.active_profile_id === profile.id;
          return (
            <button
              key={profile.id}
              type="button"
              title={profile.description}
              onClick={() => applyProfile(profile)}
              disabled={active || applyingId !== null}
              className="h-8 rounded-md border px-2 text-xs font-medium disabled:cursor-default"
              style={{
                borderColor: active ? '#10b981' : 'var(--app-border)',
                background: active ? 'rgba(16,185,129,0.15)' : 'transparent',
                color: active ? '#10b981' : undefined,
                opacity: applyingId !== null && !active ? 0.5 : 1,
              }}
            >
              {applyingId === profile.id ? 'Applying...' : profile.label}
            </button>
          );
        })}
      </div>
      {ready && !error && <p className="mt-1 text-[11px] text-emerald-400">Listo -- pulsa Connect para usar este dispositivo.</p>}
      {error && <p className="mt-1 text-[11px] text-red-400">{error}</p>}
    </div>
  );
};
