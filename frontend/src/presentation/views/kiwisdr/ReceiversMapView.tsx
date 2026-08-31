import React, { useEffect, useMemo, useState } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';
import { ExternalLink, Globe2, Info, MapPinned, PlugZap, RadioReceiver, Square, SlidersHorizontal } from 'lucide-react';
import { ReceiverApiService } from '../../../app/services/kiwisdr/ReceiverApiService';
import { KiwiSessionApiService } from '../../../app/services/kiwisdr/KiwiSessionApiService';
import type { KiwiSession, Receiver, ReceiverFilters, ReceiverMapPoint } from '../../../domain/kiwisdr/Receiver';
import { cn } from '../../../shared/utils';
import { ReceiverFiltersPanel } from './ReceiverFiltersPanel';
import { ReceiverListPanel } from './ReceiverListPanel';

const receiverApi = new ReceiverApiService();
const sessionApi = new KiwiSessionApiService();

export const ReceiversMapView: React.FC = () => {
  const [filters, setFilters] = useState<ReceiverFilters>({ q: '', country: '', onlineOnly: false });
  const [receivers, setReceivers] = useState<Receiver[]>([]);
  const [points, setPoints] = useState<ReceiverMapPoint[]>([]);
  const [selected, setSelected] = useState<Receiver | null>(null);
  const [frequencyKhz, setFrequencyKhz] = useState('7100.0');
  const [session, setSession] = useState<KiwiSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showMapSelector, setShowMapSelector] = useState(true);
  const [agcEnabled, setAgcEnabled] = useState(true);
  const [agcHang, setAgcHang] = useState(false);
  const [agcThreshold, setAgcThreshold] = useState(-90);
  const [agcSlope, setAgcSlope] = useState(6);
  const [agcDecay, setAgcDecay] = useState(500);
  const [manualGain, setManualGain] = useState(60);

  const countries = useMemo(() => {
    return Array.from(new Set(receivers.map((item) => item.country).filter(Boolean))).sort();
  }, [receivers]);

  const clusters = useMemo(() => clusterPoints(points), [points]);

  const loadReceivers = async () => {
    setIsLoading(true);
    try {
      const [list, mapPoints] = await Promise.all([
        receiverApi.listReceivers(filters),
        receiverApi.getMapPoints(filters),
      ]);
      setReceivers(list);
      setPoints(mapPoints);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load KiwiSDR receivers');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    const handle = setTimeout(() => {
      loadReceivers();
    }, 250);
    return () => clearTimeout(handle);
  }, [filters.q, filters.country, filters.onlineOnly]);

  const refreshCatalog = async () => {
    setIsRefreshing(true);
    try {
      const result = await receiverApi.refreshCatalog();
      await loadReceivers();
      if (result.status === 'degraded') {
        setNotice(result.notes || result.error || 'Catalog refresh failed; showing local cache.');
      } else {
        setNotice(`Catalog refreshed: ${result.count} receivers.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to refresh receiver catalog');
    } finally {
      setIsRefreshing(false);
    }
  };

  const selectReceiver = async (receiver: Receiver) => {
    setSelected(receiver);
    setSession(null);
    if (!receiver.lat || !receiver.lon) {
      try {
        setSelected(await receiverApi.getReceiver(receiver.id));
      } catch {
        setSelected(receiver);
      }
    }
  };

  const connectSession = async (receiverOverride?: Receiver) => {
    const receiver = receiverOverride ?? selected;
    if (!receiver) return;
    const parsedFrequency = Number(frequencyKhz);
    if (!Number.isFinite(parsedFrequency) || parsedFrequency < 0) {
      setError('Frequency must be a positive kHz value.');
      return;
    }
    try {
      const created = await sessionApi.createSession({
        receiver_id: receiver.id,
        frequency_khz: parsedFrequency,
        mode: 'iq',
        compression: true,
        agc: true,
      });
      setSession(created);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create KiwiSDR session');
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-950 text-slate-100">
      <ReceiverFiltersPanel
        filters={filters}
        countries={countries}
        isRefreshing={isRefreshing}
        onChange={setFilters}
        onRefresh={refreshCatalog}
      />

      {error && <div className="border-b border-red-900 bg-red-950 px-4 py-2 text-sm text-red-100">{error}</div>}
      {notice && <div className="border-b border-amber-900 bg-amber-950 px-4 py-2 text-sm text-amber-100">{notice}</div>}
      {session && (
        <div className="border-b border-emerald-900 bg-emerald-950 px-4 py-2 text-sm text-emerald-100">
          Session {session.session_id} created for {session.host}:{session.port}, {session.sample_rate} S/s, {session.mode}, {session.status}.
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <SourceControlPanel
          selected={selected}
          session={session}
          frequencyKhz={frequencyKhz}
          agcEnabled={agcEnabled}
          agcHang={agcHang}
          agcThreshold={agcThreshold}
          agcSlope={agcSlope}
          agcDecay={agcDecay}
          manualGain={manualGain}
          onFrequencyChange={setFrequencyKhz}
          onChooseMap={() => setShowMapSelector((value) => !value)}
          onConnect={() => connectSession()}
          onStop={() => {
            setSession(null);
            setNotice('KiwiSDR source session stopped locally. Backend streaming handoff remains a future integration step.');
          }}
          onAgcEnabledChange={setAgcEnabled}
          onAgcHangChange={setAgcHang}
          onAgcThresholdChange={setAgcThreshold}
          onAgcSlopeChange={setAgcSlope}
          onAgcDecayChange={setAgcDecay}
          onManualGainChange={setManualGain}
        />

        <main className="relative min-h-0 flex-1 overflow-hidden bg-slate-950">
          <div className="absolute left-5 top-5 z-10 rounded-md border border-slate-700 bg-slate-900/95 px-3 py-2 text-sm shadow-xl">
            <div className="flex items-center gap-2 font-semibold">
              <Globe2 className="h-4 w-4 text-cyan-300" />
              KiwiSDR map selector
            </div>
            <div className="mt-1 text-xs text-slate-400">
              {isLoading ? 'Loading catalog' : `${points.length} mapped receivers from backend cache`}
            </div>
          </div>

          <div className={cn('h-full w-full transition-opacity', !showMapSelector && 'opacity-35')}>
            <MapContainer
              center={[25, 8]}
              zoom={2}
              minZoom={2}
              maxZoom={10}
              worldCopyJump
              className="h-full w-full bg-slate-950"
              zoomControl
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <MapFocus receiver={selected} />
              {clusters.map((cluster) => {
                const receiver = receivers.find((item) => item.id === cluster.primaryId);
                if (!receiver) return null;
                const isSelected = selected?.id === cluster.primaryId;
                return (
                  <CircleMarker
                    key={cluster.key}
                    center={[cluster.lat, cluster.lon]}
                    radius={cluster.count > 1 ? Math.min(20, 9 + cluster.count / 3) : 7}
                    pathOptions={{
                      color: isSelected ? '#fbbf24' : '#0f172a',
                      weight: isSelected ? 3 : 1.5,
                      fillColor: cluster.onlineCount > 0 ? '#22c55e' : '#ef4444',
                      fillOpacity: isSelected ? 0.95 : 0.78,
                    }}
                    eventHandlers={{ click: () => selectReceiver(receiver) }}
                  >
                    <Popup>
                      <div className="min-w-[220px] text-slate-900">
                        <div className="font-semibold">{receiver.name}</div>
                        <div className="mt-1 text-xs text-slate-600">{receiver.host}:{receiver.port}</div>
                        <div className="mt-2 text-xs">
                          {[receiver.city, receiver.country].filter(Boolean).join(', ') || 'Approximate location'}
                        </div>
                        {cluster.count > 1 && (
                          <div className="mt-1 text-xs text-slate-600">{cluster.count} receivers in this area</div>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            selectReceiver(receiver);
                            connectSession(receiver);
                          }}
                          className="mt-3 w-full rounded bg-emerald-600 px-3 py-2 text-xs font-semibold text-white"
                        >
                          Use as source
                        </button>
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
            </MapContainer>
          </div>

          <div className="absolute bottom-4 left-5 max-w-xl rounded-md border border-slate-700 bg-slate-900/95 p-3 text-xs text-slate-300 shadow-xl">
            <div className="flex gap-2">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
              <span>Map coordinates are approximate public display coordinates. Receiver discovery is owned by the backend cache, not by this frontend view.</span>
            </div>
          </div>

          {selected && (
            <MapSelectionCard receiver={selected} onConnect={() => connectSession()} />
          )}
        </main>

        <ReceiverListPanel receivers={receivers} selectedId={selected?.id ?? null} onSelect={selectReceiver} />
      </div>
    </div>
  );
};

function SourceControlPanel({
  selected,
  session,
  frequencyKhz,
  agcEnabled,
  agcHang,
  agcThreshold,
  agcSlope,
  agcDecay,
  manualGain,
  onFrequencyChange,
  onChooseMap,
  onConnect,
  onStop,
  onAgcEnabledChange,
  onAgcHangChange,
  onAgcThresholdChange,
  onAgcSlopeChange,
  onAgcDecayChange,
  onManualGainChange,
}: {
  selected: Receiver | null;
  session: KiwiSession | null;
  frequencyKhz: string;
  agcEnabled: boolean;
  agcHang: boolean;
  agcThreshold: number;
  agcSlope: number;
  agcDecay: number;
  manualGain: number;
  onFrequencyChange: (value: string) => void;
  onChooseMap: () => void;
  onConnect: () => void;
  onStop: () => void;
  onAgcEnabledChange: (value: boolean) => void;
  onAgcHangChange: (value: boolean) => void;
  onAgcThresholdChange: (value: number) => void;
  onAgcSlopeChange: (value: number) => void;
  onAgcDecayChange: (value: number) => void;
  onManualGainChange: (value: number) => void;
}) {
  const status = session ? session.status : selected ? 'ready' : 'no source selected';
  const streamPosition = session ? new Date(session.created_at).toLocaleString() : 'realtime';

  return (
    <aside className="min-h-0 w-[340px] border-r border-slate-800 bg-[#101722] p-4 text-slate-100">
      <div className="flex items-center gap-2">
        <RadioReceiver className="h-5 w-5 text-cyan-300" />
        <div>
          <div className="text-sm font-semibold">KiwiSDR Source</div>
          <div className="text-xs text-slate-400">Remote receiver input module</div>
        </div>
      </div>

      <button
        onClick={onChooseMap}
        className="mt-4 inline-flex h-10 w-full items-center justify-center rounded-md bg-cyan-600 text-sm font-semibold text-white hover:bg-cyan-500"
      >
        <MapPinned className="mr-2 h-4 w-4" />
        Choose on map
      </button>

      <div className="mt-4 rounded-md border border-slate-700 bg-slate-950 p-3">
        <PanelRow label="URL" value={selected ? `${selected.host}:${selected.port}` : 'not selected'} />
        <PanelRow label="QTH" value={selected ? [selected.city, selected.country].filter(Boolean).join(', ') || 'approximate' : '-'} />
        <PanelRow label="Loc" value={selected?.locator || 'public coordinates approximate'} />
        <PanelRow label="Status" value={status} tone={session ? 'ok' : selected ? 'warn' : undefined} />
        <PanelRow label="Sample rate" value="12 kS/s" />
        <PanelRow label="Stream pos" value={streamPosition} />
      </div>

      <label className="mt-4 flex flex-col gap-1 text-xs text-slate-400">
        Tune frequency kHz
        <input
          value={frequencyKhz}
          onChange={(event) => onFrequencyChange(event.target.value)}
          className="h-10 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:border-cyan-400"
        />
      </label>

      <div className="mt-3 flex gap-2">
        <button
          onClick={onConnect}
          disabled={!selected}
          className="inline-flex h-10 flex-1 items-center justify-center rounded-md bg-emerald-600 px-3 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700"
        >
          <PlugZap className="mr-2 h-4 w-4" />
          Start
        </button>
        <button
          onClick={onStop}
          disabled={!session}
          className="inline-flex h-10 items-center justify-center rounded-md bg-red-700 px-3 text-sm font-semibold text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        >
          <Square className="h-4 w-4" />
        </button>
        {selected && (
          <a
            href={selected.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-10 items-center justify-center rounded-md bg-slate-700 px-3 text-sm text-slate-100 hover:bg-slate-600"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </div>

      <div className="mt-5 rounded-md border border-slate-700 bg-slate-950 p-3">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <SlidersHorizontal className="h-4 w-4 text-cyan-300" />
          Receiver AGC
        </div>
        <label className="mb-2 flex items-center gap-2 text-sm text-slate-200">
          <input type="checkbox" checked={agcEnabled} onChange={(event) => onAgcEnabledChange(event.target.checked)} />
          AGC
        </label>
        <label className="mb-3 flex items-center gap-2 text-sm text-slate-200">
          <input type="checkbox" checked={agcHang} onChange={(event) => onAgcHangChange(event.target.checked)} />
          Hang
        </label>
        {agcEnabled ? (
          <>
            <Range label="Threshold" value={agcThreshold} min={-130} max={0} unit="dB" onChange={onAgcThresholdChange} />
            <Range label="Slope" value={agcSlope} min={0} max={10} unit="dB" onChange={onAgcSlopeChange} />
            <Range label="Decay" value={agcDecay} min={20} max={5000} unit="ms" onChange={onAgcDecayChange} />
          </>
        ) : (
          <Range label="Gain" value={manualGain} min={0} max={120} unit="dB" onChange={onManualGainChange} />
        )}
      </div>
    </aside>
  );
}

function MapSelectionCard({ receiver, onConnect }: { receiver: Receiver; onConnect: () => void }) {
  return (
    <div className="absolute right-5 top-5 z-20 w-[320px] rounded-md border border-slate-700 bg-slate-900/95 p-4 shadow-2xl">
      <div className="text-xs uppercase tracking-wide text-cyan-300">Map selection</div>
      <h3 className="mt-1 truncate text-lg font-semibold text-slate-100">{receiver.name}</h3>
      <div className="mt-1 text-sm text-slate-400">{receiver.host}:{receiver.port}</div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <PanelCell label="QTH" value={[receiver.city, receiver.country].filter(Boolean).join(', ') || 'Approx.'} />
        <PanelCell label="Users" value={receiver.current_users !== null && receiver.max_users !== null ? `${receiver.current_users}/${receiver.max_users}` : 'Unknown'} />
        <PanelCell label="SNR" value={receiver.snr !== null ? `${receiver.snr} dB` : 'Unknown'} />
        <PanelCell label="Coverage" value={`${(receiver.frequency_min_khz / 1000).toFixed(1)}-${(receiver.frequency_max_khz / 1000).toFixed(1)} MHz`} />
      </div>
      <button
        onClick={onConnect}
        className="mt-4 inline-flex h-10 w-full items-center justify-center rounded-md bg-emerald-600 px-3 text-sm font-semibold text-white hover:bg-emerald-500"
      >
        <PlugZap className="mr-2 h-4 w-4" />
        Use as source
      </button>
    </div>
  );
}

function PanelRow({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warn' }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-800 py-1.5 text-sm last:border-b-0">
      <span className="text-slate-500">{label}</span>
      <span className={cn('truncate text-right text-slate-100', tone === 'ok' && 'text-emerald-300', tone === 'warn' && 'text-amber-300')}>
        {value}
      </span>
    </div>
  );
}

function PanelCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 truncate text-slate-100">{value}</div>
    </div>
  );
}

function Range({ label, value, min, max, unit, onChange }: { label: string; value: number; min: number; max: number; unit: string; onChange: (value: number) => void }) {
  return (
    <label className="mb-3 block text-xs text-slate-400">
      <div className="mb-1 flex justify-between">
        <span>{label}</span>
        <span>{value} {unit}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-cyan-400"
      />
    </label>
  );
}

function MapFocus({ receiver }: { receiver: Receiver | null }) {
  const map = useMap();

  useEffect(() => {
    if (receiver?.lat === null || receiver?.lon === null || receiver?.lat === undefined || receiver?.lon === undefined) {
      return;
    }
    map.flyTo([receiver.lat, receiver.lon], Math.max(map.getZoom(), 5), { duration: 0.6 });
  }, [map, receiver?.id, receiver?.lat, receiver?.lon]);

  return null;
}

function clusterPoints(points: ReceiverMapPoint[]) {
  const buckets = new Map<string, {
    key: string;
    lat: number;
    lon: number;
    count: number;
    onlineCount: number;
    primaryId: string;
  }>();
  for (const point of points) {
    const lonBucket = Math.round(point.lon / 2.5);
    const latBucket = Math.round(point.lat / 2.0);
    const key = `${latBucket}:${lonBucket}`;
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        key,
        lat: point.lat,
        lon: point.lon,
        count: 1,
        onlineCount: point.is_online ? 1 : 0,
        primaryId: point.id,
      });
    } else {
      existing.lat = (existing.lat * existing.count + point.lat) / (existing.count + 1);
      existing.lon = (existing.lon * existing.count + point.lon) / (existing.count + 1);
      existing.count += 1;
      existing.onlineCount += point.is_online ? 1 : 0;
    }
  }
  return Array.from(buckets.values());
}
