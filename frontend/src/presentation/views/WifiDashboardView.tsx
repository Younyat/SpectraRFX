import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Download, Play, RadioTower, Wifi, XCircle } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { ModulatedSignalCapture } from '../../shared/types';
import { formatFrequency } from '../../shared/utils';

const apiService = new ApiService();

const WIFI_JOB_POLL_INTERVAL_MS = 1500;

type WifiChannel = { channel: number; frequency_hz: number };
type WifiChannels = { channels_24ghz: WifiChannel[]; channels_5ghz: WifiChannel[] };
type WifiReport = Record<string, any>;
type WifiFrame = Record<string, any>;

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

const pollWifiJob = async (jobId: string, onProgress?: (message: string) => void): Promise<WifiReport> => {
  for (;;) {
    const job = await apiService.getWifiDemodulationJobStatus(jobId);
    if (job.status === 'done') return job.result || {};
    if (job.status === 'error') throw new Error(job.message || job.error || 'Wi-Fi demodulation job failed.');
    onProgress?.(job.message || 'Running worker...');
    await new Promise((resolve) => setTimeout(resolve, WIFI_JOB_POLL_INTERVAL_MS));
  }
};

const buildAnalyzePayload = (capture: ModulatedSignalCapture) => ({
  sample_id: capture.id,
  file_path: capture.iq_file,
  file_format: capture.file_format,
  // Capture Lab always writes complex64 (interleaved float32 I/Q) on disk
  // regardless of file_format/iq_dtype label -- the worker's own vocabulary is
  // cf32_le/ci16_le/cu8.
  datatype: 'cf32_le',
  sample_rate_hz: capture.sample_rate_hz,
  center_frequency_hz: capture.center_frequency_hz,
  hardware_center_frequency_hz: capture.center_frequency_hz,
  channel_center_frequency_hz: capture.center_frequency_hz,
  bandwidth_hz: capture.bandwidth_hz,
  channel_width_hz: capture.bandwidth_hz,
  capture_duration: capture.duration_seconds,
  source_dataset: 'wifi_dashboard',
  pipeline: 'wifi_80211',
  temporal_order_known: true,
});

const isWifiResult = (result: Record<string, any>) =>
  result.pipeline === 'wifi_80211' || result.protocol === 'wifi_80211' || result.demodulation_pipeline === 'wifi_80211';

const statusPalette = (status: string) => {
  if (status.includes('frames_confirmed')) return 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200';
  if (status.includes('no_valid_frames') || status.includes('not_decoded') || status.includes('missing') || status.includes('failed')) {
    return 'border-amber-400/40 bg-amber-500/10 text-amber-200';
  }
  return 'border-slate-600/40 bg-slate-800/40 text-slate-300';
};

const resultTime = (result: Record<string, any>) => {
  const value = result.generated_at_utc || result.timestamp_utc;
  if (!value) return 'time n/a';
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
};

export const WifiDashboardView: React.FC = () => {
  const [channels, setChannels] = useState<WifiChannels | null>(null);
  const [band, setBand] = useState<'2.4' | '5'>('2.4');
  const [selectedChannel, setSelectedChannel] = useState<number | null>(null);
  const [duration, setDuration] = useState(5);
  const [capturing, setCapturing] = useState(false);

  const [captures, setCaptures] = useState<ModulatedSignalCapture[]>([]);
  const [selectedCaptureId, setSelectedCaptureId] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<string | null>(null);

  const [currentReport, setCurrentReport] = useState<WifiReport | null>(null);
  const [currentFrames, setCurrentFrames] = useState<WifiFrame[]>([]);
  const [selectedFrameIndex, setSelectedFrameIndex] = useState(0);

  const [history, setHistory] = useState<WifiReport[]>([]);
  const [error, setError] = useState<string | null>(null);

  const channelList = useMemo(() => {
    if (!channels) return [];
    return band === '2.4' ? channels.channels_24ghz : channels.channels_5ghz;
  }, [channels, band]);

  const loadChannels = async () => {
    try {
      const data = await apiService.getWifi80211Channels();
      setChannels(data);
      if (data.channels_24ghz.length > 0) setSelectedChannel(data.channels_24ghz[0].channel);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const loadCaptures = async () => {
    try {
      const data = await apiService.getModulatedSignalCaptures();
      setCaptures(data);
      if (data.length > 0) setSelectedCaptureId(data[0].id);
    } catch {
      // Capture Lab may simply be empty -- not fatal for this dashboard.
    }
  };

  const loadHistory = async () => {
    try {
      const results = await apiService.getDemodulationResults();
      setHistory(results.filter(isWifiResult));
    } catch {
      // History is a convenience list -- not fatal.
    }
  };

  useEffect(() => {
    loadChannels();
    loadCaptures();
    loadHistory();
  }, []);

  useEffect(() => {
    if (!channels) return;
    const list = band === '2.4' ? channels.channels_24ghz : channels.channels_5ghz;
    if (list.length > 0) setSelectedChannel(list[0].channel);
  }, [band, channels]);

  const loadReportFromResult = async (result: WifiReport) => {
    setCurrentReport(result);
    setSelectedFrameIndex(0);
    if (!result.id) {
      setCurrentFrames([]);
      return;
    }
    try {
      const framesData = await apiService.getDemodulationOutputJson(result.id, 'decoded_frames.json');
      setCurrentFrames(Array.isArray(framesData.frames) ? framesData.frames : []);
    } catch {
      setCurrentFrames([]);
    }
  };

  const startCapture = async () => {
    const entry = channelList.find((item) => item.channel === selectedChannel);
    if (!entry) {
      setError('Select a Wi-Fi channel first.');
      return;
    }
    setError(null);
    setCapturing(true);
    try {
      const result = await apiService.demodulateMarkerBand({
        startFrequencyHz: entry.frequency_hz - 10_000_000,
        stopFrequencyHz: entry.frequency_hz + 10_000_000,
        mode: 'wifi_80211',
        durationSeconds: duration,
      });
      await loadReportFromResult(result);
      await loadHistory();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setCapturing(false);
    }
  };

  const analyzeExisting = async () => {
    const capture = captures.find((item) => item.id === selectedCaptureId);
    if (!capture) {
      setError('Select an existing capture first.');
      return;
    }
    setError(null);
    setAnalyzing(true);
    setAnalyzeProgress('Starting worker...');
    try {
      const { job_id: jobId } = await apiService.startWifiDemodulationJob(buildAnalyzePayload(capture));
      const result = await pollWifiJob(jobId, setAnalyzeProgress);
      await loadReportFromResult(result);
      await loadHistory();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setAnalyzing(false);
      setAnalyzeProgress(null);
    }
  };

  const diagnostics: Record<string, number> | null = currentReport?.receiver_diagnostics_summary ?? null;
  const outputs: Record<string, string | null> = currentReport?.outputs ?? {};
  const selectedFrame = currentFrames[selectedFrameIndex] ?? null;
  const busy = capturing || analyzing;

  return (
    <div className="h-full overflow-auto bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-amber-500">
        <Wifi className="h-4 w-4" />
        IEEE 802.11 Dedicated Workspace
      </div>
      <h1 className="mb-6 text-2xl font-semibold">Wi-Fi Dashboard</h1>

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
          <div className="mb-3 text-sm font-semibold">Capture a channel</div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">
              Band
              <select
                value={band}
                onChange={(event) => setBand(event.target.value as '2.4' | '5')}
                className="h-9 rounded-md border bg-transparent px-2 text-sm"
                style={{ borderColor: 'var(--app-border)' }}
              >
                <option value="2.4">2.4 GHz</option>
                <option value="5">5 GHz</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">
              Channel
              <select
                value={selectedChannel ?? ''}
                onChange={(event) => setSelectedChannel(Number(event.target.value))}
                className="h-9 min-w-[11rem] rounded-md border bg-transparent px-2 text-sm"
                style={{ borderColor: 'var(--app-border)' }}
              >
                {channelList.map((item) => (
                  <option key={item.channel} value={item.channel}>
                    CH{item.channel} — {formatFrequency(item.frequency_hz)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">
              Duration (s)
              <input
                type="number"
                min={1}
                max={60}
                value={duration}
                onChange={(event) => setDuration(Number(event.target.value))}
                className="h-9 w-20 rounded-md border bg-transparent px-2 text-sm"
                style={{ borderColor: 'var(--app-border)' }}
              />
            </label>
            <button
              type="button"
              onClick={startCapture}
              disabled={busy}
              className="inline-flex h-9 items-center rounded-md bg-amber-500 px-4 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RadioTower className="mr-2 h-4 w-4" />
              {capturing ? 'Capturing + decoding...' : 'Start Wi-Fi Capture'}
            </button>
          </div>
          <div className="mt-2 text-xs text-[var(--app-text-muted)]">
            Captures the real USRP-B200 at exactly 20 MS/s around the selected channel. This can take well over the
            requested duration to complete (decode + margin).
          </div>
        </section>

        <section className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
          <div className="mb-3 text-sm font-semibold">Analyze an existing capture</div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">
              Capture Lab recording
              <select
                value={selectedCaptureId}
                onChange={(event) => setSelectedCaptureId(event.target.value)}
                className="h-9 min-w-[16rem] rounded-md border bg-transparent px-2 text-sm"
                style={{ borderColor: 'var(--app-border)' }}
              >
                {captures.map((capture) => (
                  <option key={capture.id} value={capture.id}>
                    {capture.label || capture.id} | {formatFrequency(capture.center_frequency_hz)} | {formatFrequency(capture.sample_rate_hz)}/s
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={analyzeExisting}
              disabled={busy || captures.length === 0}
              className="inline-flex h-9 items-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Play className="mr-2 h-4 w-4" />
              {analyzing ? analyzeProgress || 'Analyzing...' : 'Analyze'}
            </button>
          </div>
          {captures.length === 0 && (
            <div className="mt-2 text-xs text-[var(--app-text-muted)]">No Capture Lab recordings available yet.</div>
          )}
        </section>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div>
      )}

      {currentReport ? (
        <>
          <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-4">
            <div className={`rounded-lg border p-4 ${statusPalette(String(currentReport.status || ''))}`}>
              <div className="text-xs uppercase tracking-wide opacity-80">Final status</div>
              <div className="mt-1 text-lg font-semibold">{currentReport.final_status || currentReport.status}</div>
            </div>
            <Metric title="Frames confirmed" value={String(currentReport.frames_decoded ?? 0)} />
            <Metric title="FCS valid" value={String(currentReport.frames_crc_valid ?? 0)} />
            <Metric
              title="Source / rate"
              value={`${currentReport.source || currentReport.source_dataset || 'n/a'} · ${formatFrequency(currentReport.sample_rate_hz)}/s`}
            />
          </div>

          {diagnostics && (
            <section className="mb-6 rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
              <div className="mb-3 text-sm font-semibold">Receiver diagnostics (per-stage, honest partial recovery)</div>
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4 lg:grid-cols-8">
                {Object.entries(diagnostics).map(([key, value]) => (
                  <div key={key} className="rounded-md bg-black/10 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wide text-[var(--app-text-muted)]">{key.replace(/_/g, ' ')}</div>
                    <div className="mt-1 text-lg font-semibold">{value}</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <section className="overflow-hidden rounded-lg border" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
              <div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>
                Confirmed frames ({currentFrames.length})
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">
                    <tr>
                      <th className="px-4 py-3">#</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">BSSID</th>
                      <th className="px-4 py-3">SSID</th>
                      <th className="px-4 py-3">Seq</th>
                      <th className="px-4 py-3">FCS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentFrames.map((frame, index) => (
                      <FrameRow
                        key={frame.arrival_order ?? index}
                        frame={frame}
                        selected={index === selectedFrameIndex}
                        onSelect={() => setSelectedFrameIndex(index)}
                      />
                    ))}
                    {currentFrames.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-10 text-center text-sm text-[var(--app-text-muted)]">
                          No confirmed frames for this result.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <aside className="rounded-lg border" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
              <div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>
                Frame detail
              </div>
              {selectedFrame ? (
                <div className="space-y-3 p-4 text-sm">
                  <SmallStat label="Frame" value={`${selectedFrame.frame_type ?? 'n/a'} / ${selectedFrame.subtype ?? 'n/a'}`} />
                  {selectedFrame.ssid !== undefined && (
                    <SmallStat label="SSID" value={selectedFrame.ssid || '(hidden)'} />
                  )}
                  <SmallStat label="Address 1 (dest)" value={selectedFrame.address_1 || 'n/a'} />
                  <SmallStat label="Address 2 (BSSID/src)" value={selectedFrame.address_2 || 'n/a'} />
                  <SmallStat label="Address 3" value={selectedFrame.address_3 || 'n/a'} />
                  <SmallStat label="Sequence" value={String(selectedFrame.sequence_number ?? 'n/a')} />
                  <SmallStat label="FCS valid" value={selectedFrame.fcs_valid ? 'yes' : 'no'} />
                  <SmallStat label="Payload state" value={selectedFrame.payload_state || 'n/a'} />
                  {selectedFrame.payload_state === 'clear' && selectedFrame.payload_hex && (
                    <div>
                      <div className="mb-1 text-xs uppercase tracking-wide text-[var(--app-text-muted)]">
                        Payload hex ({selectedFrame.payload_length} bytes)
                      </div>
                      <div className="max-h-40 overflow-auto break-all rounded-md bg-black/10 px-3 py-2 font-mono text-xs">
                        {selectedFrame.payload_hex}
                      </div>
                    </div>
                  )}
                  {selectedFrame.payload_state === 'protected_ciphertext' && (
                    <div className="rounded-md bg-black/10 px-3 py-2 text-xs">
                      Protected payload ({selectedFrame.ciphertext_length} bytes ciphertext) -- not decrypted.
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-4 text-sm text-[var(--app-text-muted)]">Select a frame to inspect it.</div>
              )}
            </aside>
          </div>

          <section className="mb-6 rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
            <div className="mb-2 text-sm font-semibold">Notes</div>
            <div className="space-y-1 text-xs text-[var(--app-text-muted)]">
              {(currentReport.notes || []).map((note: string) => (
                <div key={note}>- {note}</div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-4 text-xs">
              {Object.entries(outputs)
                .filter(([, path]) => Boolean(path))
                .map(([name, path]) => {
                  const filename = String(path).split(/[\\/]/).pop() || name;
                  return (
                    <a
                      key={name}
                      href={apiService.getDemodulationOutputUrl(currentReport.id, filename)}
                      className="inline-flex items-center gap-1 text-amber-400 hover:underline"
                    >
                      <Download className="h-3 w-3" />
                      {name}
                    </a>
                  );
                })}
            </div>
          </section>
        </>
      ) : (
        <div className="mb-6 rounded-lg border border-dashed p-8 text-center text-sm text-[var(--app-text-muted)]" style={{ borderColor: 'var(--app-border)' }}>
          Start a capture or analyze an existing recording to see the full report here.
        </div>
      )}

      <section className="rounded-lg border" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
        <div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>
          Wi-Fi results history
        </div>
        <div className="divide-y" style={{ borderColor: 'var(--app-border)' }}>
          {history.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => loadReportFromResult(item)}
              className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left text-sm hover:bg-black/5"
            >
              <span>{resultTime(item)} · {item.source || item.source_dataset || 'n/a'}</span>
              <span className="text-xs text-[var(--app-text-muted)]">
                {item.frames_decoded ?? 0} frame(s) · {item.final_status || item.status}
              </span>
            </button>
          ))}
          {history.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-[var(--app-text-muted)]">No Wi-Fi results yet.</div>
          )}
        </div>
      </section>
    </div>
  );
};

const Metric = ({ title, value }: { title: string; value: string }) => (
  <div className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
    <div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">{title}</div>
    <div className="mt-1 text-2xl font-semibold">{value}</div>
  </div>
);

const SmallStat = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-md bg-black/10 px-3 py-2">
    <div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">{label}</div>
    <div className="mt-1 break-all font-medium">{value}</div>
  </div>
);

const FrameRow = ({ frame, selected, onSelect }: { frame: WifiFrame; selected: boolean; onSelect: () => void }) => (
  <tr
    onClick={onSelect}
    className="cursor-pointer border-t transition-colors hover:bg-black/5"
    style={{ borderColor: 'var(--app-border)', background: selected ? 'rgba(245,158,11,0.10)' : undefined }}
  >
    <td className="px-4 py-3">{frame.arrival_order ?? 'n/a'}</td>
    <td className="px-4 py-3">{frame.frame_type}/{frame.subtype}</td>
    <td className="px-4 py-3 font-mono text-xs">{frame.address_2 || frame.address_1 || 'n/a'}</td>
    <td className="px-4 py-3">{frame.ssid !== undefined ? (frame.ssid || '(hidden)') : '—'}</td>
    <td className="px-4 py-3">{frame.sequence_number ?? 'n/a'}</td>
    <td className="px-4 py-3">
      {frame.fcs_valid ? (
        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
      ) : (
        <XCircle className="h-4 w-4 text-rose-500" />
      )}
    </td>
  </tr>
);
