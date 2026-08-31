import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BrainCircuit, Crosshair, RefreshCw, RadioTower, SlidersHorizontal } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import type { RFObjectDetection, RFSceneAnalysis } from '../../shared/types';
import { formatFrequency, formatPowerLevel } from '../../shared/utils';

const apiService = new ApiService();

const formatBandwidth = (hz: number) => {
  if (!Number.isFinite(hz)) return 'n/a';
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(2)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(1)} kHz`;
  return `${hz.toFixed(0)} Hz`;
};

const confidenceColor = (confidence: number) => {
  if (confidence >= 0.8) return 'text-emerald-500';
  if (confidence >= 0.6) return 'text-amber-500';
  return 'text-slate-500';
};

export const RFIntelligenceView: React.FC = () => {
  const [scene, setScene] = useState<RFSceneAnalysis | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [thresholdOffsetDb, setThresholdOffsetDb] = useState(10);
  const [minSnrDb, setMinSnrDb] = useState(6);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedDetection = useMemo(() => {
    return scene?.detections.find((detection) => detection.id === selectedId) ?? scene?.detections[0] ?? null;
  }, [scene, selectedId]);

  const refresh = async () => {
    try {
      setLoading(true);
      const nextScene = await apiService.getLiveRFScene({ thresholdOffsetDb, minSnrDb });
      setScene(nextScene);
      setError(null);
      if (!selectedId && nextScene.detections.length > 0) {
        setSelectedId(nextScene.detections[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'RF intelligence refresh failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(refresh, 1500);
    return () => window.clearInterval(timer);
  }, [autoRefresh, thresholdOffsetDb, minSnrDb, selectedId]);

  const detections = scene?.detections ?? [];

  return (
    <div className="min-h-full bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-amber-500">
            <BrainCircuit className="h-4 w-4" />
            RF Scene Understanding
          </div>
          <h1 className="text-2xl font-semibold">RF Intelligence</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setAutoRefresh((value) => !value)}
            className="rounded-md border px-3 py-2 text-sm"
            style={{ borderColor: 'var(--app-border)', background: autoRefresh ? 'var(--app-accent)' : 'var(--app-surface-strong)', color: autoRefresh ? 'var(--app-accent-foreground)' : 'var(--app-text)' }}
          >
            {autoRefresh ? 'Live on' : 'Live off'}
          </button>
          <button
            type="button"
            onClick={refresh}
            className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
            style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface-strong)' }}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-4">
        <Metric title="Detected objects" value={detections.length.toString()} icon={<RadioTower className="h-5 w-5" />} />
        <Metric title="Noise floor" value={formatPowerLevel(scene?.noise_floor_db)} icon={<SlidersHorizontal className="h-5 w-5" />} />
        <Metric title="Threshold" value={formatPowerLevel(scene?.threshold_db)} icon={<Crosshair className="h-5 w-5" />} />
        <Metric title="Unknown queue" value={(scene?.summary.families.unknown ?? 0).toString()} icon={<AlertTriangle className="h-5 w-5" />} />
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Control label="Threshold offset" value={`${thresholdOffsetDb.toFixed(1)} dB`}>
          <input className="w-full accent-amber-500" type="range" min="3" max="25" step="0.5" value={thresholdOffsetDb} onChange={(event) => setThresholdOffsetDb(Number(event.target.value))} />
        </Control>
        <Control label="Minimum SNR" value={`${minSnrDb.toFixed(1)} dB`}>
          <input className="w-full accent-amber-500" type="range" min="1" max="25" step="0.5" value={minSnrDb} onChange={(event) => setMinSnrDb(Number(event.target.value))} />
        </Control>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-500">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="overflow-hidden rounded-lg border" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
          <div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>
            Detected RF Objects
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">
                <tr>
                  <th className="px-4 py-3">Hypothesis</th>
                  <th className="px-4 py-3">Center</th>
                  <th className="px-4 py-3">Bandwidth</th>
                  <th className="px-4 py-3">SNR</th>
                  <th className="px-4 py-3">Temporal</th>
                  <th className="px-4 py-3">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {detections.map((detection) => (
                  <DetectionRow
                    key={detection.id}
                    detection={detection}
                    selected={selectedDetection?.id === detection.id}
                    onSelect={() => setSelectedId(detection.id)}
                  />
                ))}
                {detections.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-[var(--app-text-muted)]">
                      No active RF objects above the current threshold.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="rounded-lg border" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
          <div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>
            Confidence & Evidence
          </div>
          {selectedDetection ? (
            <div className="space-y-4 p-4 text-sm">
              <div>
                <div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Selected hypothesis</div>
                <div className="mt-1 text-lg font-semibold">{selectedDetection.label}</div>
                <div className={`mt-1 text-sm font-semibold ${confidenceColor(selectedDetection.confidence)}`}>
                  {(selectedDetection.confidence * 100).toFixed(0)}% confidence
                </div>
              </div>
              <EvidenceLine label="Band profile" active={selectedDetection.evidence.frequency_band_match} />
              <EvidenceLine label="Bandwidth" active={selectedDetection.evidence.bandwidth_match} />
              <EvidenceLine label="Temporal behavior" active={selectedDetection.evidence.temporal_match} />
              {selectedDetection.evidence.channel_grid_match && (
                <div className="rounded-md bg-black/5 px-3 py-2">
                  Channel grid: {selectedDetection.evidence.channel_grid_match}
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <SmallStat label="Start" value={formatFrequency(selectedDetection.start_frequency_hz)} />
                <SmallStat label="Stop" value={formatFrequency(selectedDetection.stop_frequency_hz)} />
                <SmallStat label="Peak" value={formatPowerLevel(selectedDetection.peak_power_db)} />
                <SmallStat label="Persistence" value={`${(selectedDetection.persistence * 100).toFixed(0)}%`} />
              </div>
              <div>
                <div className="mb-2 text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Evidence notes</div>
                <div className="space-y-2">
                  {selectedDetection.evidence.notes.map((note) => (
                    <div key={note} className="rounded-md bg-black/5 px-3 py-2">
                      {note}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="p-4 text-sm text-[var(--app-text-muted)]">Select a detection to inspect its evidence.</div>
          )}
        </aside>
      </div>
    </div>
  );
};

const Metric = ({ title, value, icon }: { title: string; value: string; icon: React.ReactNode }) => (
  <div className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
    <div className="mb-3 flex items-center justify-between text-[var(--app-text-muted)]">
      <span className="text-sm">{title}</span>
      {icon}
    </div>
    <div className="text-2xl font-semibold">{value}</div>
  </div>
);

const Control = ({ label, value, children }: { label: string; value: string; children: React.ReactNode }) => (
  <div className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
    <div className="mb-3 flex items-center justify-between text-sm">
      <span className="font-medium">{label}</span>
      <span className="text-[var(--app-text-muted)]">{value}</span>
    </div>
    {children}
  </div>
);

const DetectionRow = ({ detection, selected, onSelect }: { detection: RFObjectDetection; selected: boolean; onSelect: () => void }) => (
  <tr
    onClick={onSelect}
    className="cursor-pointer border-t transition-colors hover:bg-black/5"
    style={{ borderColor: 'var(--app-border)', background: selected ? 'rgba(245,158,11,0.10)' : undefined }}
  >
    <td className="px-4 py-3">
      <div className="font-medium">{detection.label}</div>
      <div className="text-xs text-[var(--app-text-muted)]">{detection.track_id ?? detection.id}</div>
    </td>
    <td className="px-4 py-3">{formatFrequency(detection.center_frequency_hz)}</td>
    <td className="px-4 py-3">{formatBandwidth(Math.max(detection.bandwidth_hz, detection.occupied_bandwidth_hz))}</td>
    <td className="px-4 py-3">{detection.snr_db.toFixed(1)} dB</td>
    <td className="px-4 py-3">{detection.temporal_type.replace('_', ' ')}</td>
    <td className={`px-4 py-3 font-semibold ${confidenceColor(detection.confidence)}`}>{(detection.confidence * 100).toFixed(0)}%</td>
  </tr>
);

const EvidenceLine = ({ label, active }: { label: string; active: boolean }) => (
  <div className="flex items-center justify-between rounded-md bg-black/5 px-3 py-2">
    <span>{label}</span>
    <span className={active ? 'text-emerald-500' : 'text-slate-500'}>{active ? 'match' : 'weak'}</span>
  </div>
);

const SmallStat = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-md bg-black/5 px-3 py-2">
    <div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">{label}</div>
    <div className="mt-1 font-medium">{value}</div>
  </div>
);
