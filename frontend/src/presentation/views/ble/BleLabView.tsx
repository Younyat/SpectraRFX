import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Bluetooth, CheckCircle2, Download, Play, RefreshCw, RotateCcw, Square } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { BleAdvertisement, BleAdvertiser, BleApiService, BleCapabilities, BleCaptureCapabilities, BleCaptureJob, BleCaptureLive, BleCaptureRecord, BleConnectionJob, BleGate2a2Candidate, BleGate2a2ConfirmedPacket, BleGate2a2Job, BleGate2a2Status, BleHybridEvidence, BleHybridMatch, BleHybridSession, BleJob, BleJobEvent, BleNativeDevice, BleNativeService, BleNativeStatus, BlePacket, TiSensorState } from '../../../app/services/bleApi';
import BleHybridController from './BleHybridController';
import BleUc02Panel from './BleUc02Panel';
import BleDatasetStudio from './BleDatasetStudio';
import {ensureOperation,failOperation,finishOperation,updateOperation} from '../../../app/operations/operationTelemetry';
import {beginBleButtonAction} from '../../../app/operations/bleActionTelemetry';

const TI_SENSOR_STATUS_LABEL: Record<string, string> = { available: 'Disabled', unavailable: 'Unavailable', starting: 'Starting', starting_no_data_yet: 'Starting (no data yet)', active: 'Active', disabled: 'Disabled', disconnected: 'Disconnected' };
const formatUpdated = (iso?: string) => (iso ? new Date(iso).toLocaleString() : 'Never');

const TiSensorCard = ({ title, sensor, busy, onStart, onStop, children }: { title: string; sensor?: TiSensorState; busy: boolean; onStart: () => void; onStop: () => void; children?: React.ReactNode }) => {
  if (!sensor?.available) {
    return <div className="rounded border p-3 text-sm text-amber-400">{title}: measurement unavailable in discovered GATT profile</div>;
  }
  const statusLabel = TI_SENSOR_STATUS_LABEL[sensor.status ?? 'available'] ?? sensor.status;
  return (
    <div className="rounded border p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <b>{title}</b>
        <span className={`rounded-full px-2 py-0.5 text-xs ${sensor.active ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-500/15 text-slate-300'}`}>{statusLabel}</span>
      </div>
      {children}
      <div className="mt-2 flex gap-2">
        <button disabled={busy || sensor.active} onClick={onStart} className="rounded bg-sky-600 px-3 py-1 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">Start {title}</button>
        <button disabled={busy || !sensor.active} onClick={onStop} className="rounded border px-3 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-40">Stop</button>
      </div>
    </div>
  );
};

const api = new BleApiService();
const replayNotice = 'This result was produced from a validated bitstream replay. No IQ demodulation or RF recovery was performed.';
export const BLE_DSP_UNAVAILABLE_REASON = 'IQ-based BLE analysis is unavailable because the DSP recovery gate has not been completed. Validated bitstream replay is available for platform-integration testing.';
const BLE_PRIMARY_CHANNELS = [
  { channel: 37, frequencyMHz: 2402 },
  { channel: 38, frequencyMHz: 2426 },
  { channel: 39, frequencyMHz: 2480 },
] as const;
const surfaceStyle = { borderColor: 'var(--app-border)', background: 'var(--app-surface)' };
const Panel: React.FC<React.PropsWithChildren<{ title: string; className?: string }>> = ({ title, className = '', children }) => <section className={`overflow-hidden rounded-lg border ${className}`} style={surfaceStyle}><div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>{title}</div><div className="p-4">{children}</div></section>;
const Metric = ({ label, display }: { label: string; display: React.ReactNode }) => <div className="rounded-lg border p-4" style={surfaceStyle}><div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">{label}</div><div className="mt-1 break-all text-xl font-semibold">{display}</div></div>;
const summaryNumber = (summary: Record<string, unknown> | undefined, ...keys: string[]) => Number(keys.map((key) => summary?.[key]).find((item) => item !== undefined) ?? 0);
const JOB_PROGRESS: Record<string, number> = { created: 5, queued: 12, validating_input: 25, starting_worker: 38, running: 60, validating_artifacts: 85, cancel_requested: 90, completed: 100, completed_with_diagnostics: 100, failed: 100, timed_out: 100, cancelled: 100 };

const BleJobProgress = ({ job }: { job: BleJob }) => {
  const progress = JOB_PROGRESS[job.state] ?? 0;
  const terminal = ['completed', 'completed_with_diagnostics', 'failed', 'timed_out', 'cancelled'].includes(job.state);
  return <div className="mt-3 min-w-[18rem]">
    <div className="mb-1 flex justify-between text-xs"><span>{terminal ? 'Finished' : 'Analysis progress'}</span><b>{progress}%</b></div>
    <div className="h-2 overflow-hidden rounded-full bg-black/15"><div className={`h-full transition-all duration-500 ${job.state === 'failed' || job.state === 'timed_out' ? 'bg-red-500' : 'bg-sky-500'}`} style={{ width: `${progress}%` }} /></div>
  </div>;
};

export const BleCapabilityStatus = ({ capabilities }: { capabilities: BleCapabilities | null }) => {
  const rows = [['Bit-true primitives', 'bit_true_gate', 'passed'], ['Link Layer bitstream decoder', 'link_layer_bitstream_gate', 'passed'], ['Advertising semantic parser', 'semantic_advertising_gate', 'passed'], ['Platform integration', 'platform_integration_gate', 'in_progress'], ['IQ/DSP recovery', 'dsp_gate', 'not_started'], ['OTA validation', 'ota_validated', 'not_performed']];
  return <Panel title="Decoder readiness — not a running job"><p className="mb-2 text-xs text-[var(--app-text-muted)]">These are validation gates for the BLE decoder. They do not mean an analysis is currently running.</p><dl className="grid gap-x-6 md:grid-cols-2">{rows.map(([label, key, fallback]) => <div key={key} className="flex justify-between border-b py-2 text-sm" style={{ borderColor: 'var(--app-border)' }}><dt>{label}</dt><dd className="font-semibold">{String(capabilities?.gates[key] ?? fallback).replaceAll('_', ' ')}</dd></div>)}<div className="flex justify-between border-b py-2 text-sm" style={{ borderColor: 'var(--app-border)' }}><dt>Normative conformance</dt><dd className="font-semibold">{(capabilities?.normative_conformance ?? 'not_established').replaceAll('_', ' ')}</dd></div></dl></Panel>;
};

export const BleJobLauncher = ({ enabled, captureCapabilities, captureBusy, onCreated, onCaptureCreated }: { enabled: boolean; captureCapabilities: BleCaptureCapabilities | null; captureBusy: boolean; onCreated: (job: BleJob) => void; onCaptureCreated: (job: BleCaptureJob) => void }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [channel, setChannel] = useState(37);
  const [duration, setDuration] = useState(5);
  const selected = BLE_PRIMARY_CHANNELS.find((item) => item.channel === channel) ?? BLE_PRIMARY_CHANNELS[0];
  const launch = async () => { setBusy(true); setError(''); try { onCreated(await api.createReplayJob()); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to create replay job'); } finally { setBusy(false); } };
  const captureDevice = captureCapabilities?.devices[0];
  const launchCapture = async () => {
    if (!captureDevice) return;
    setBusy(true); setError('');
    try {
      const formats = captureDevice.stream_formats ?? [];
      const sampleFormat = formats.includes('CF32') ? 'cf32_le' : formats.includes('CS16') ? 'ci16_le' : 'ci8';
      onCaptureCreated(await api.createCapture({ device_id: captureDevice.device_id, ble_channel: selected.channel, center_frequency_hz: selected.frequencyMHz * 1e6, sample_rate_sps: 4_000_000, bandwidth_hz: 2_000_000, gain_mode: 'manual', gain_db: 20, antenna: captureDevice.antenna_options.includes('RX2') ? 'RX2' : captureDevice.antenna_options[0], duration_seconds: duration, sample_format: sampleFormat, description: 'USRP B200 real IQ capture — manual dashboard action', purpose: 'interactive_experimental_capture' }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to start real-IQ capture'); } finally { setBusy(false); }
  };
  return <div className="contents">
    <Panel title="Capture a BLE advertising channel">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">PHY<select className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} disabled><option>LE 1M</option></select></label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">Primary channel<select value={channel} onChange={(event) => setChannel(Number(event.target.value))} className="h-9 min-w-[13rem] rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>{BLE_PRIMARY_CHANNELS.map((item) => <option key={item.channel} value={item.channel}>CH{item.channel} — {item.frequencyMHz} MHz</option>)}</select></label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">Duration (s)<input type="number" min={1} max={60} value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="h-9 w-20 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} /></label>
        <button type="button" onClick={() => void launchCapture()} disabled={!captureCapabilities?.capture_enabled || !captureDevice || captureBusy || busy} title={!captureDevice ? 'No compatible SDR detected' : 'Starts a preserved real-IQ recording; it does not decode BLE'} className="inline-flex h-9 items-center rounded-md bg-sky-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"><Bluetooth className="mr-2 h-4 w-4" />{captureBusy ? 'Capturing IQ…' : 'Start Real IQ Capture'}</button>
      </div>
      <div className="mt-3 rounded-md bg-black/10 px-3 py-2 text-xs"><b>Selected RF center:</b> {selected.frequencyMHz} MHz · CH{selected.channel} · {duration}s<div className="mt-1 text-cyan-500">Manual real-IQ capture only. No BLE decoding or Gate 2A.2 analysis starts automatically.</div></div>
    </Panel>
    <Panel title="Analyze validated BLE traffic">
      <p className="mb-3 text-sm text-[var(--app-text-muted)]">Run the frozen Gate 1B campaign and inspect CRC-valid PDUs, headers, payload bytes, addresses and Advertising Data structures.</p>
      <div className="mb-3 rounded-md bg-black/10 px-3 py-2 text-xs"><span className="text-[var(--app-text-muted)]">Input mode</span><div className="mt-1 font-semibold">Validated bitstream replay · channels 37, 38 and 39</div></div>
      <button onClick={() => void launch()} disabled={!enabled || busy} className="inline-flex h-9 items-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"><Play className="mr-2 h-4 w-4" />{busy ? 'Creating job...' : 'Analyze replay frames'}</button>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </Panel>
  </div>;
};

export const BleJobSummary = ({ job }: { job: BleJob }) => { const s = job.result_summary; const metrics: [string, React.ReactNode][] = [['CRC-valid packets', summaryNumber(s, 'confirmed_packet_count', 'crc_valid_packets')], ['Parsed advertising PDUs', summaryNumber(s, 'parsed_packet_count', 'parsed_advertising_pdus')], ['Advertising Data structures', summaryNumber(s, 'ad_structure_count')], ['Observed advertiser addresses', summaryNumber(s, 'advertiser_count')], ['PDU types observed', summaryNumber(s, 'pdu_type_count')], ['Channels represented', summaryNumber(s, 'channel_count')], ['CRC-invalid diagnostic candidates', summaryNumber(s, 'crc_invalid_candidate_count')], ['Duplicate publications', summaryNumber(s, 'duplicate_publications')], ['Worker commit', String(job.worker?.worker_commit ?? job.worker?.commit ?? 'Unavailable')], ['Processing duration', job.processing_duration_seconds == null ? 'Unavailable' : `${job.processing_duration_seconds}s`], ['Input mode', 'Validated bitstream replay']]; return <Panel title="Job summary"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{metrics.map(([label, display]) => <Metric key={label} label={label} display={display} />)}</div></Panel>; };

export const BleChannelMap = ({ represented }: { represented: number[] }) => <Panel title="Channel overview"><div className="grid grid-cols-5 gap-2 sm:grid-cols-8 lg:grid-cols-10">{Array.from({ length: 40 }, (_, channel) => { const present = represented.includes(channel); return <div key={channel} title={present ? 'represented_in_test_vector' : 'not_represented_in_test_vector'} className={`rounded border p-2 text-center text-xs ${present ? 'border-cyan-400 bg-cyan-400/15' : 'border-slate-700 text-slate-500'} ${channel >= 37 ? 'ring-1 ring-amber-400' : ''}`}><b>{channel}</b><div>{present ? 'represented' : 'not represented'}</div></div>; })}</div></Panel>;
export const BlePacketDetails = ({ packet }: { packet: BlePacket }) => {
  const raw = packet as Record<string, unknown>;
  return <div className="space-y-3">
    <div className="grid grid-cols-2 gap-2 text-sm">
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">Access Address</div><code>{String(raw.access_address ?? 'Unknown')}</code></div>
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">PDU type</div><b>{String(packet.pdu_type ?? 'Unknown')}</b></div>
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">Channel / frequency</div><b>CH{String(packet.channel_index ?? '?')} · {BLE_PRIMARY_CHANNELS.find((item) => item.channel === Number(packet.channel_index))?.frequencyMHz ?? 'Unknown'} MHz</b></div>
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">CRC</div><b className="text-emerald-500">{packet.crc_valid ? 'Valid' : 'Invalid'}</b></div>
    </div>
    <div><div className="mb-1 text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Complete Link Layer PDU</div><div className="max-h-32 overflow-auto break-all rounded-md bg-black/10 px-3 py-2 font-mono text-xs">{String(raw.pdu_hex ?? raw.payload_hex ?? 'Unavailable')}</div></div>
    <details><summary className="cursor-pointer text-xs font-semibold text-sky-500">All packet metadata</summary><pre className="mt-2 max-h-72 overflow-auto break-all rounded-md bg-black/10 p-3 text-xs">{JSON.stringify(packet, null, 2)}</pre></details>
  </div>;
};
export const BlePacketTable = ({ packets }: { packets: BlePacket[] }) => { const [selected, setSelected] = useState<BlePacket | null>(null); return <Panel title="Confirmed packets"><div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="text-slate-400"><tr><th className="p-2">Packet ID</th><th>PDU type</th><th>Channel</th><th>CRC</th></tr></thead><tbody>{packets.map((packet, index) => <tr key={packet.packet_id ?? index} onClick={() => setSelected(packet)} className="cursor-pointer border-t border-slate-800"><td className="p-2">{packet.packet_id ?? `packet-${index + 1}`}</td><td>{packet.pdu_type ?? 'Unknown'}</td><td>{packet.channel_index ?? 'Unknown'}</td><td className={packet.crc_valid ? 'text-emerald-300' : 'text-rose-300'}>{String(packet.crc_valid)}</td></tr>)}</tbody></table></div>{selected && <BlePacketDetails packet={selected} />}</Panel>; };
export const BleAdStructureViewer = ({ structures }: { structures: unknown[] }) => <pre className="max-h-64 overflow-auto rounded bg-slate-950 p-3 text-xs">{JSON.stringify(structures, null, 2)}</pre>;
export const BleAdvertisementDetails = ({ advertisement }: { advertisement: BleAdvertisement }) => <div><p className="mb-2 text-xs text-amber-200">An observed address is not a permanent device identity.</p><BleAdStructureViewer structures={advertisement.ad_structures ?? []} /></div>;
export const BleAdvertisementTable = ({ advertisements }: { advertisements: BleAdvertisement[] }) => { const [selected, setSelected] = useState<BleAdvertisement | null>(null); return <Panel title="Advertisements">{advertisements.map((ad, index) => <button key={ad.packet_id ?? index} onClick={() => setSelected(ad)} className="mb-2 flex w-full justify-between rounded border border-slate-700 p-2 text-sm"><span>{ad.pdu_type ?? 'Unknown PDU'}</span><span className="font-mono">{ad.advertiser_address ?? 'No address'}</span></button>)}{selected && <BleAdvertisementDetails advertisement={selected} />}</Panel>; };
export const BleAdvertiserTable = ({ advertisers }: { advertisers: BleAdvertiser[] }) => <Panel title="Observed advertiser addresses"><p className="mb-2 text-xs text-amber-200">Addresses are observations, not stable device identities.</p>{advertisers.map((advertiser, index) => <div key={`${advertiser.address}-${index}`} className="flex justify-between border-t border-slate-800 py-2 text-sm"><code>{advertiser.address ?? 'Unknown'}</code><span>{advertiser.address_type ?? 'unknown type'} · {advertiser.packet_count ?? 0}</span></div>)}</Panel>;
export const BleReceiverPipeline = ({ events }: { events: BleJobEvent[] }) => <Panel title="Receiver / job pipeline"><ol>{events.map((event, index) => <li key={event.sequence ?? index} className="mb-2 text-sm"><code className="mr-3 text-cyan-300">#{event.sequence ?? index + 1}</code>{event.previous_state ?? 'start'} → <b>{event.new_state ?? 'unknown'}</b> · {event.reason ?? 'no reason supplied'}</li>)}</ol></Panel>;
export const BleDiagnostics = ({ diagnostics }: { diagnostics: unknown }) => <Panel title="Diagnostics"><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(diagnostics, null, 2)}</pre></Panel>;
export const BleKnownLimitations = () => <Panel title="Known limitations"><ul className="list-disc space-y-2 pl-5 text-sm text-slate-300"><li>{BLE_DSP_UNAVAILABLE_REASON}</li><li>RSSI, SNR, CFO, RF bursts, sample coverage and timing lock: Unavailable — DSP not implemented.</li><li>OTA validation: Not performed. Normative conformance: Not established.</li><li>Replay timestamps are sequence-derived, never RF timestamps.</li></ul></Panel>;
export const BleArtifactDownloads = ({ jobId, artifacts }: { jobId: string; artifacts: unknown }) => <Panel title="Artifacts"><a href={api.bundleUrl(jobId)} className="inline-flex items-center gap-2 rounded bg-slate-700 px-3 py-2 text-sm"><Download className="h-4 w-4" />Download reproducible bundle</a><pre className="mt-3 max-h-44 overflow-auto text-xs">{JSON.stringify(artifacts, null, 2)}</pre></Panel>;
export const BleWorkerProvenance = ({ capabilities, job }: { capabilities: BleCapabilities | null; job?: BleJob }) => <Panel title="Worker provenance"><div className="grid gap-2 text-sm md:grid-cols-2"><div>Frozen worker commit: <code>{capabilities?.worker_commit ?? 'Unavailable'}</code></div><div>Scientific status: <b>{capabilities?.scientific_status ?? 'BLE_P0_INCOMPLETE'}</b></div><div>Capability: <b>{capabilities?.capability_status ?? 'experimental'}</b></div><div>Job: <b>{job?.job_id ?? 'No job selected'}</b></div></div></Panel>;

// ── Gate 2A.2 -- experimental IQ recovery, separate from Gate 1B above ──────
// Every panel below must keep reading live status/results from the backend;
// none of these numbers are hardcoded, and none of this is ever framed as
// approved, frozen, or validated.

const GATE2A2_CHANNELS = [37, 38, 39] as const;
export const CAPTURE_AND_DECODE_DISABLED_REASON = 'Disabled because Receiver Candidate B is not frozen and OTA validation has not been completed.';
const GATE2A2_JOB_TERMINAL = ['completed', 'cancelled', 'failed', 'timed_out'];

export const Gate2a2StatusPanel = ({ status }: { status: BleGate2a2Status | null }) => {
  if (!status) return <Panel title="Gate 2A.2 status">Loading…</Panel>;
  if (!status.available) {
    return <Panel title="Gate 2A.2 status"><p className="text-sm text-amber-500">Status unavailable: {status.reason ?? 'unknown'}</p></Panel>;
  }
  const sweep = status.development_timing_sweep;
  const rows: [string, string][] = [
    ['Gate 2A.1', status.gate_2a1_status ?? 'unknown'],
    ['Gate 2A.2', status.gate_2a2_status ?? 'unknown'],
    ['DSP gate', status.dsp_gate ?? 'unknown'],
    ['Receiver candidate', status.receiver_candidate ?? 'unknown'],
    ['Candidate frozen', String(status.candidate_frozen ?? false)],
    ['Development timing sweep', `${sweep?.byte_exact ?? '?'} / ${sweep?.cases ?? '?'} (${sweep?.result ?? 'unknown'})`],
    ['Residual failures', String(status.residual_failures ?? 'unknown')],
    ['Holdout B created', String(status.holdout_b_created ?? false)],
    ['IQ recovery validated', String(status.iq_recovery_validated ?? false)],
    ['OTA validated', String(status.ota_validated ?? false)],
    ['Worker repository commit', status.worker_repository_commit ?? 'unknown'],
    ['Receiver commit', status.receiver_commit ?? 'unknown'],
  ];
  return (
    <Panel title="Gate 2A.2 status — experimental, not approved">
      <dl className="grid gap-x-6 md:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between border-b py-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>
            <dt>{label}</dt><dd className="break-all font-mono font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-amber-500">{status.disabled_reason}</p>
    </Panel>
  );
};

export const AnalyzeIqFilePanel = ({ enabled, disabledReason, onCreated }: { enabled: boolean; disabledReason?: string; onCreated: (job: BleGate2a2Job) => void }) => {
  const [path, setPath] = useState('');
  const [channel, setChannel] = useState<number>(38);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const launch = async () => {
    if (!path.trim()) { setError('Enter a local cf32_le IQ file path first.'); return; }
    setBusy(true); setError('');
    try {
      onCreated(await api.createGate2a2Job({ iq_file_path: path.trim(), channel_index: channel }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start analysis');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Analyze IQ file — experimental offline analysis">
      <p className="mb-3 text-xs font-semibold text-amber-500">
        Experimental offline IQ analysis. Receiver Candidate B is not frozen. Not validated for OTA reception. Results may contain decoding errors.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[18rem] flex-1 flex-col gap-1 text-xs text-[var(--app-text-muted)]">
          IQ file path (cf32_le, 4 MS/s)
          <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\path\to\capture.cf32" className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">
          Primary channel
          <select value={channel} onChange={(event) => setChannel(Number(event.target.value))} className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>
            {GATE2A2_CHANNELS.map((item) => <option key={item} value={item}>CH{item}</option>)}
          </select>
        </label>
        <button
          type="button"
          onClick={() => void launch()}
          disabled={!enabled || busy}
          title={!enabled ? disabledReason : undefined}
          className="inline-flex h-9 items-center rounded-md bg-sky-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Play className="mr-2 h-4 w-4" />{busy ? 'Starting…' : 'Analyze IQ File'}
        </button>
      </div>
      {!enabled && <p className="mt-2 text-xs text-amber-500">{disabledReason ?? 'Disabled.'}</p>}
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </Panel>
  );
};

export const Gate2a2CandidateTable = ({ candidates }: { candidates: BleGate2a2Candidate[] }) => {
  const [selected, setSelected] = useState<BleGate2a2Candidate | null>(null);
  return (
    <Panel title={`Recovered candidates (${candidates.length})`}>
      <div className="overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-slate-400"><tr><th className="p-2">Trace ID</th><th>Channel</th><th>Winning hypothesis</th><th>Hypotheses evaluated</th><th>CFO (Hz)</th></tr></thead>
          <tbody>
            {candidates.map((candidate, index) => (
              <tr key={String(candidate.receiver_trace_id ?? index)} onClick={() => setSelected(candidate)} className="cursor-pointer border-t border-slate-800">
                <td className="p-2 font-mono text-xs">{String(candidate.receiver_trace_id ?? index)}</td>
                <td>{candidate.channel_index ?? 'Unknown'}</td>
                <td>{candidate.winning_timing_hypothesis_id ?? 'Unknown'}</td>
                <td>{candidate.timing_hypotheses_evaluated ?? 0}</td>
                <td>{typeof candidate.estimated_cfo_hz === 'number' ? candidate.estimated_cfo_hz.toFixed(1) : 'Unknown'}</td>
              </tr>
            ))}
            {candidates.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-[var(--app-text-muted)]">No candidates recovered for this job.</td></tr>}
          </tbody>
        </table>
      </div>
      {selected && (
        <div className="mt-3 space-y-2 text-sm">
          <div className="rounded-md bg-black/10 px-3 py-2">
            <div className="text-xs text-[var(--app-text-muted)]">Winning hypothesis / evaluated / losing hypotheses</div>
            <div className="break-all font-mono">{selected.winning_timing_hypothesis_id} / {selected.timing_hypotheses_evaluated} / {(selected.merged_timing_hypothesis_ids ?? []).join(', ') || 'none'}</div>
          </div>
          <div className="rounded-md bg-black/10 px-3 py-2">
            <div className="text-xs text-[var(--app-text-muted)]">Estimated CFO / timing phase (input samples)</div>
            <div className="font-mono">{selected.estimated_cfo_hz?.toFixed(1) ?? 'Unknown'} Hz / {selected.estimated_timing_phase?.toFixed(4) ?? 'Unknown'}</div>
          </div>
        </div>
      )}
    </Panel>
  );
};

export const Gate2a2ConfirmedPacketsPanel = ({ packets }: { packets: BleGate2a2ConfirmedPacket[] }) => {
  const [native,setNative]=useState<BleNativeDevice[]>([]);
  useEffect(()=>{void api.nativeDevices().then(setNative).catch(()=>setNative([]));},[packets.length]);
  const nativeMatch=(packet:BleGate2a2ConfirmedPacket)=>{
    const persisted=packet.correlation as {status?:string}|undefined;if(persisted?.status)return persisted.status;
    const device=native.find(item=>item.address.toUpperCase()===packet.address?.toUpperCase());
    if(!device)return 'B200_ONLY';
    const structures=(packet.ad_structures as Array<{ad_type_raw?:number;decoded_value?:{company_identifier?:number;vendor_payload_hex?:string}}> | undefined)??[];
    const manufacturer=structures.find(item=>item.ad_type_raw===255)?.decoded_value;
    if(!manufacturer||manufacturer.company_identifier==null||!manufacturer.vendor_payload_hex)return 'AMBIGUOUS';
    const key=`0x${manufacturer.company_identifier.toString(16).padStart(4,'0')}`.toUpperCase();
    const observed=Object.entries(device.manufacturer_data).find(([name])=>name.toUpperCase()===key)?.[1];
    return observed?.toUpperCase()===manufacturer.vendor_payload_hex.toUpperCase()?'MATCHED_BY_BOTH':'AMBIGUOUS';
  };
  const manufacturer=(packet:BleGate2a2ConfirmedPacket)=>((packet.ad_structures as Array<{decoded_value?:{company?:{name?:string}}}>|undefined)??[]).find(Boolean)?.decoded_value?.company?.name??'not available';
  return <Panel title={`B200 decoded packets (${packets.filter(packet=>packet.crc_valid).length})`}>
    <p className="mb-2 text-xs text-[var(--app-text-muted)]">
      These passed the same frozen Gate 1A/1B CRC check Gate 1B trusts — only the DSP front end that produced the candidate bits is experimental.
    </p>
    <table className="w-full text-left text-sm">
      <thead className="text-slate-400"><tr><th className="p-2">Time</th><th>Channel</th><th>PDU</th><th>Address</th><th>Address type</th><th>Manufacturer</th><th>Name</th><th>Payload</th><th>CRC</th><th>Power</th><th>SNR</th><th>Native match</th><th>Correlation rule</th></tr></thead>
      <tbody>
        {packets.filter(packet=>packet.crc_valid).map((packet, index) => (
          <tr key={packet.packet_sha256 ?? index} className="border-t border-slate-800">
            <td className="p-2">{String(packet.timestamp??'not available')}</td><td>{packet.channel_index ?? 'Unknown'}</td><td>{packet.pdu_type_name ?? 'Unknown'}</td>
            <td className="font-mono text-xs">{packet.address??'not available'}</td><td>{packet.address_type??'not available'}</td><td>{manufacturer(packet)}</td><td>{packet.local_name??'not available'}</td>
            <td className="max-w-52 truncate font-mono text-xs" title={packet.payload_octets}>{packet.payload_octets??'not available'}</td>
            <td className="text-emerald-300">valid</td><td>{packet.power_dbfs==null?'not available':`${packet.power_dbfs.toFixed(1)} dBFS`}</td>
            <td>{packet.snr_db==null?'not available':`${packet.snr_db.toFixed(1)} dB`}</td><td>{nativeMatch(packet)}</td><td>{String((packet.correlation as {rule?:string}|undefined)?.rule??'not executed')}</td>
          </tr>
        ))}
        {packets.filter(packet=>packet.crc_valid).length === 0 && <tr><td colSpan={13} className="p-4 text-center text-[var(--app-text-muted)]">No CRC-valid BLE packets.</td></tr>}
      </tbody>
    </table>
  </Panel>
};

const Trace = ({ values, color }: { values: number[]; color: string }) => { if(values.length<2)return <div className="flex h-32 items-center justify-center text-xs text-[var(--app-text-muted)]">Waiting for real SDR samples…</div>; const lo=Math.min(...values), hi=Math.max(...values), span=Math.max(1e-9,hi-lo); const points=values.map((v,i)=>`${i*100/(values.length-1)},${100-(v-lo)*100/span}`).join(' '); return <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-32 w-full bg-black/20"><polyline points={points} fill="none" stroke={color} strokeWidth="1" vectorEffect="non-scaling-stroke" /></svg>; };
const LiveHistory = ({ live }: { live: BleCaptureLive|null }) => { const [rows,setRows]=useState<number[][]>([]),[power,setPower]=useState<number[]>([]); useEffect(()=>{if(!live?.spectrum_dbfs?.length)return;setRows(old=>[...old.slice(-39),live.spectrum_dbfs!]);if(typeof live.average_power_dbfs==='number')setPower(old=>[...old.slice(-119),live.average_power_dbfs!]);},[live?.timestamp_utc]); return <div className="grid gap-4 xl:grid-cols-2"><Panel title="Live waterfall — time / frequency / dBFS"><div className="h-40 overflow-hidden rounded bg-black">{rows.map((row,i)=><div key={i} className="flex h-1" title={live?.timestamp_utc}>{row.filter((_,x)=>x%4===0).map((v,x)=>{const level=Math.max(0,Math.min(1,(v+120)/120));return <span key={x} className="h-full flex-1" style={{backgroundColor:`hsl(${240-level*240} 90% ${15+level*45}%)`}}/>;})}</div>)}</div></Panel><Panel title="Temporal average power"><Trace values={power} color="#f59e0b" /></Panel></div>; };

const NativeBleDevices = () => {
  const [status,setStatus]=useState<BleNativeStatus|null>(null),[devices,setDevices]=useState<BleNativeDevice[]>([]),[selected,setSelected]=useState<BleNativeDevice|null>(null),[services,setServices]=useState<BleNativeService[]>([]),[remaining,setRemaining]=useState(0),[error,setError]=useState(''),[sensorBusy,setSensorBusy]=useState(false),[connectionJob,setConnectionJob]=useState<BleConnectionJob|null>(null);
  const refresh=async()=>{try{const [nextStatus,nextDevices]=await Promise.all([api.nativeStatus(),api.nativeDevices()]);setStatus(nextStatus);setDevices(nextDevices);if(selected){const updated=nextDevices.find(item=>item.device_id===selected.device_id);if(updated)setSelected(updated);}}catch(reason){setError(reason instanceof Error?reason.message:'Native BLE API unavailable');}};
  useEffect(()=>{void refresh();},[]);
  useEffect(()=>{const listener=()=>void refresh();window.addEventListener('ble-native-registry-updated',listener);return()=>window.removeEventListener('ble-native-registry-updated',listener);},[]);
  useEffect(()=>{if(!status?.scanning)return;const timer=window.setInterval(()=>{void refresh();setRemaining(value=>Math.max(0,value-1));},1000);return()=>window.clearInterval(timer);},[status?.scanning,selected?.device_id]);
  useEffect(()=>{if(status?.scanning&&remaining===0){void api.stopNativeScan().then(()=>refresh());}},[remaining,status?.scanning]);
  const start=async(seconds:number)=>{setError('');try{await api.startNativeScan();setRemaining(seconds);await refresh();}catch(reason){setError(reason instanceof Error?reason.message:'Unable to start BLE scan');}};
  const connect=async(device:BleNativeDevice)=>{if(connectionJob&&!['CONNECTED','FAILED','TIMED_OUT','CANCELLED_BY_USER'].includes(connectionJob.status))return;setError('');try{setSelected(device);setConnectionJob(await api.connectNative(device.device_id));}catch(reason){setError(reason instanceof Error?reason.message:'Unable to connect');}};
  useEffect(()=>{if(!connectionJob||['CONNECTED','FAILED','TIMED_OUT','CANCELLED_BY_USER','CANCELLED_BY_WINDOWS','OPERATION_ABORTED'].includes(connectionJob.status))return;const timer=window.setInterval(async()=>{try{const next=await api.nativeConnectionJob(connectionJob.connection_job_id);setConnectionJob(next);if(next.status==='CONNECTED'){setSelected(await api.nativeDevice(next.device_id));setServices(await api.nativeServices(next.device_id));await refresh();}}catch(reason){setError(reason instanceof Error?reason.message:'Connection status unavailable');}},500);return()=>window.clearInterval(timer);},[connectionJob?.connection_job_id,connectionJob?.status]);
  useEffect(()=>{if(!connectionJob)return;const id=`ble-gatt:${connectionJob.connection_job_id}`,terminalStatus=['CONNECTED','FAILED','TIMED_OUT','CANCELLED_BY_USER','CANCELLED_BY_WINDOWS','OPERATION_ABORTED'];if(connectionJob.status==='CONNECTED'){finishOperation(id,`Conectado · ${selected?.address||connectionJob.device_id}`);return}if(terminalStatus.includes(connectionJob.status)){failOperation(id,connectionJob.error||connectionJob.status);return}ensureOperation({operationId:id,kind:'connecting',title:'Conexión GATT',phase:connectionJob.current_stage||'Conectando',progressPercent:0,target:selected?.address||connectionJob.device_id,estimatedTotalSeconds:connectionJob.total_steps*12,detail:`Intento ${connectionJob.attempt}/${connectionJob.max_attempts}`});updateOperation(id,{phase:connectionJob.current_stage||connectionJob.status,progressPercent:100*connectionJob.step/Math.max(1,connectionJob.total_steps),processedItems:connectionJob.step,totalItems:connectionJob.total_steps})},[connectionJob,selected?.address]);
  const disconnect=async(device:BleNativeDevice)=>{setError('');try{const next=await api.disconnectNative(device.device_id);if(selected?.device_id===device.device_id){setSelected(next);setServices([]);}await refresh();}catch(reason){setError(reason instanceof Error?reason.message:'Unable to disconnect');}};
  const characteristicAction=async(uuid:string,action:'read'|'subscribe')=>{if(!selected)return;setError('');try{if(action==='read')await api.readNative(selected.device_id,uuid);else await api.subscribeNative(selected.device_id,uuid);setSelected(await api.nativeDevice(selected.device_id));}catch(reason){setError(reason instanceof Error?reason.message:'GATT operation failed');}};
  // Live-poll while a TI sensor is actively streaming -- the scan-only poll
  // above stops once scanning ends, but notifications keep arriving.
  useEffect(()=>{
    if(!selected)return;
    const active=selected.environmental_sensor?.active||selected.ir_temperature_sensor?.active;
    if(!active)return;
    const timer=window.setInterval(async()=>{try{setSelected(await api.nativeDevice(selected.device_id));}catch{/* transient poll error, ignore */}},1000);
    return()=>window.clearInterval(timer);
  },[selected?.device_id,selected?.environmental_sensor?.active,selected?.ir_temperature_sensor?.active]);
  const selectedRef=useRef<BleNativeDevice|null>(null);
  useEffect(()=>{selectedRef.current=selected;},[selected]);
  useEffect(()=>()=>{
    // Cleanup on view close: stop any TI sensor left actively streaming.
    const device=selectedRef.current;
    if(device?.environmental_sensor?.active) void api.stopEnvironmental(device.device_id).catch(()=>undefined);
    if(device?.ir_temperature_sensor?.active) void api.stopIrTemperature(device.device_id).catch(()=>undefined);
  },[]);
  const withSensorBusy=async(action:()=>Promise<BleNativeDevice>)=>{setSensorBusy(true);setError('');try{setSelected(await action());}catch(reason){setError(reason instanceof Error?reason.message:'Sensor operation failed');}finally{setSensorBusy(false);}};
  const legacySensorAction=async(name:string,startSensor:boolean)=>{if(!selected)return;await withSensorBusy(()=>startSensor?api.startLegacySensor(selected.device_id,name):api.stopLegacySensor(selected.device_id,name));};
  const startAllSensors=async()=>{if(!selected)return;setSensorBusy(true);setError('');try{const result=await api.startSupportedSensors(selected.device_id);setSelected(result.device);setError(`${result.active} sensors active · ${result.failed} failed`);}catch(reason){setError(reason instanceof Error?reason.message:'Unable to start supported sensors');}finally{setSensorBusy(false);}};
  return <div className="space-y-4"><Panel title="Dispositivos BLE — adaptador nativo"><div className="mb-4 flex flex-wrap items-center gap-3"><div className={`rounded-full px-3 py-1 text-xs font-semibold ${status?.available?'bg-emerald-500/15 text-emerald-300':'bg-amber-500/15 text-amber-300'}`}>{status?.available?'Adaptador BLE preparado':status?.reason_code??'Comprobando adaptador'}</div><button disabled={!status?.available||Boolean(status?.scanning)} onClick={()=>void start(30)} className="h-9 rounded bg-sky-600 px-4 text-sm font-semibold text-white disabled:opacity-40">Escanear 30 segundos</button><button disabled={!status?.available||Boolean(status?.scanning)} onClick={()=>void start(60)} className="h-9 rounded border px-4 text-sm disabled:opacity-40">Escanear 60 segundos</button>{status?.scanning&&<><div className="text-sm text-sky-300">Escaneando… {remaining}s</div><button onClick={async()=>{await api.stopNativeScan();setRemaining(0);await refresh();}} className="h-9 rounded bg-red-600 px-3 text-sm text-white">Detener escaneo</button></>}<button onClick={()=>void refresh()} className="h-9 rounded border px-3 text-sm">Actualizar</button></div>{status&&!status.available&&<p className="mb-3 text-sm text-amber-400">{status.message} {status.diagnostic&&<code className="ml-1 text-xs">{status.diagnostic}</code>}</p>}{error&&<p className="mb-3 text-sm text-red-400">{error}</p>}<div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>Dispositivo</th><th>Dirección</th><th>RSSI</th><th>Última observación</th><th>Modo de datos</th><th>Conexión</th><th>Perfil</th><th>Parser</th><th>Mediciones</th><th>Acción</th></tr></thead><tbody>{devices.map(device=><tr key={device.device_id} className="border-t"><td className="py-2">{device.local_name||'Dispositivo BLE sin nombre'} <span className="text-[10px] text-[var(--app-text-muted)]">· …{device.device_id.slice(-4)}</span></td><td className="font-mono text-xs">{device.address}</td><td>{device.rssi_dbm??'n/d'} dBm</td><td>{device.last_seen_utc}</td><td>{device.data_mode}</td><td>{device.connection}</td><td>{device.profile_label||'—'}</td><td>{device.parser_available?'disponible':'no disponible'}</td><td>{device.measurements?.length??0}</td><td className="space-x-2"><button onClick={()=>setSelected(device)} className="text-cyan-400">Inspeccionar</button>{device.connection==='disconnected'?<button onClick={()=>void connect(device)} className="text-emerald-400">Conectar GATT</button>:<button onClick={()=>void disconnect(device)} className="text-rose-400">Desconectar</button>}</td></tr>)}</tbody></table>{devices.length===0&&<p className="p-6 text-center text-sm text-[var(--app-text-muted)]">Encienda los sensores y pulse Escanear. Ningún escaneo comienza automáticamente.</p>}</div></Panel>
  {connectionJob&&!['CONNECTED','FAILED','TIMED_OUT','CANCELLED_BY_USER','CANCELLED_BY_WINDOWS','OPERATION_ABORTED'].includes(connectionJob.status)&&<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55"><div className="w-[28rem] rounded-xl border border-sky-500/50 bg-slate-950 p-5 shadow-2xl"><div className="flex items-center gap-3"><RefreshCw className="h-5 w-5 animate-spin text-sky-400"/><b>Connecting to {selected?.local_name||selected?.address||'BLE device'}…</b></div><div className="mt-4 text-sm">Step {connectionJob.step} of {connectionJob.total_steps}: {connectionJob.current_stage.replaceAll('_',' ').toLowerCase()}</div><div className="mt-2 text-sm text-slate-400">Elapsed: {connectionJob.elapsed_seconds.toFixed(1)} s · Attempt: {connectionJob.attempt||1} of {connectionJob.max_attempts}</div><button onClick={async()=>setConnectionJob(await api.cancelNativeConnection(connectionJob.connection_job_id))} className="mt-4 rounded bg-rose-700 px-4 py-2 text-sm text-white">Cancel</button></div></div>}
  {selected&&<Panel title={`Device details — ${selected.local_name||selected.address} · …${selected.device_id.slice(-4)}`}>
    <div className="mb-3 flex items-center justify-between gap-3 text-sm">
      <span>Connection: <b>{selected.connection}</b></span><span>Native state: <b>{selected.native_state??'DISCOVERED'}</b></span><span>Diagnostic status: <b>{selected.native_status??'ADVERTISEMENT_ONLY'}</b></span>
      {selected.connection==='disconnected'?<button onClick={()=>void connect(selected)} className="rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white">Connect GATT</button>:<button onClick={()=>void disconnect(selected)} className="rounded bg-rose-600 px-3 py-1 text-xs font-semibold text-white">Disconnect</button>}
    </div>
    <div className="grid gap-4 lg:grid-cols-3"><div className="rounded border p-3 text-xs"><b>Raw advertising</b><pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap">{JSON.stringify({manufacturer_data:selected.manufacturer_data,service_data:selected.service_data,service_uuids:selected.service_uuids,tx_power_dbm:selected.tx_power_dbm},null,2)}</pre></div><div className="lg:col-span-2"><b className="text-sm">Real measurements</b><div className="mt-2 grid gap-3 sm:grid-cols-3">{selected.measurements?.slice(-6).reverse().map(measurement=><div key={measurement.measurement_id} className="rounded border p-3"><div className="text-xs capitalize text-[var(--app-text-muted)]">{measurement.measurement_type}</div><div className="text-xl font-semibold">{measurement.value} {measurement.unit}</div><div className="mt-2 text-[10px]">{measurement.observed_at_utc}<br/>{measurement.acquisition_mode} · {measurement.parser_id}<br/><code>{measurement.source_raw_hex}</code></div></div>)}{!selected.measurements?.length&&<p className="text-sm text-amber-400">Device detected. Raw BLE data available. Sensor value parser not yet supported, or GATT reading is required.</p>}</div></div></div>
    <div className="rounded border p-3"><b className="text-sm">GATT diagnostics</b><div className="mt-2 overflow-auto"><table className="w-full text-left text-xs"><thead><tr><th>Operation</th><th>Attempt</th><th>Duration</th><th>Cache</th><th>Status</th><th>Technical error</th></tr></thead><tbody>{selected.gatt_diagnostics?.slice(-10).reverse().map((item,index)=><tr key={`${item.timestamp_utc}-${index}`} className="border-t"><td>{item.operation}</td><td>{item.attempt}</td><td>{item.duration_ms} ms</td><td>{item.cache_mode}</td><td>{item.status}</td><td>{item.exception_class?`${item.exception_class}: ${item.exception_message??''}`:'—'}</td></tr>)}</tbody></table>{!selected.gatt_diagnostics?.length&&<p className="py-2 text-[var(--app-text-muted)]">No GATT operation has been attempted yet.</p>}</div></div>
    {selected.profile_id?.startsWith('ti-sensortag-')&&<div className="mt-4 rounded border border-sky-500/30 p-4">
      <div className="mb-1 text-sm font-semibold text-sky-300">{selected.profile_label||'Texas Instruments SensorTag'}</div>
      <div className="mb-3 text-xs text-[var(--app-text-muted)]">Profile: {selected.profile_label||'TI SensorTag-compatible'} · Identification source: {selected.profile_detection_source==='gatt_fingerprint'?'Connected GATT service fingerprint':'Unknown'} · Confidence: {selected.profile_detection_source==='gatt_fingerprint'?'High':'Low'}</div>
      <div className="grid gap-3 md:grid-cols-2">
        <TiSensorCard title="Environmental sensor" sensor={selected.environmental_sensor} busy={sensorBusy} onStart={()=>void withSensorBusy(()=>api.startEnvironmental(selected.device_id))} onStop={()=>void withSensorBusy(()=>api.stopEnvironmental(selected.device_id))}>
          {selected.environmental_sensor?.last_reading?<div className="space-y-1">
            <div>Temperature: <b>{selected.environmental_sensor.last_reading.temperature_c?.toFixed(2)} °C</b>{selected.environmental_sensor.last_reading.stale&&<span className="ml-2 text-amber-400">(stale)</span>}</div>
            <div>Relative humidity: <b>{selected.environmental_sensor.last_reading.relative_humidity_percent?.toFixed(2)} %RH</b></div>
            <div className="text-[10px] text-[var(--app-text-muted)]">Updated {formatUpdated(selected.environmental_sensor.last_reading.observed_at_utc)} · GATT notification · Service TI Humidity Service AA20 · Data characteristic AA21 · Parser ti-cc2650-hdc1000-v1</div>
            <div className="text-[10px]"><code>{selected.environmental_sensor.last_reading.source_raw_hex}</code></div>
          </div>:<div className="text-xs text-[var(--app-text-muted)]">-- °C / -- %RH — no reading yet.</div>}
        </TiSensorCard>
        <TiSensorCard title="IR temperature sensor" sensor={selected.ir_temperature_sensor} busy={sensorBusy} onStart={()=>void withSensorBusy(()=>api.startIrTemperature(selected.device_id))} onStop={()=>void withSensorBusy(()=>api.stopIrTemperature(selected.device_id))}>
          {selected.ir_temperature_sensor?.last_reading?<div className="space-y-1">
            <div>Object temperature: <b>{selected.ir_temperature_sensor.last_reading.object_temperature_c==null?'Parser correction required':`${selected.ir_temperature_sensor.last_reading.object_temperature_c.toFixed(3)} °C`}</b>{selected.ir_temperature_sensor.last_reading.stale&&<span className="ml-2 text-amber-400">(stale)</span>}</div>
            <div>Ambient temperature: <b>{selected.ir_temperature_sensor.last_reading.ambient_temperature_c?.toFixed(3)} °C</b></div>
            <div className="text-[10px] text-[var(--app-text-muted)]">Updated {formatUpdated(selected.ir_temperature_sensor.last_reading.observed_at_utc)} · GATT notification · Service TI IR Temperature Service AA00 · Data characteristic AA01 · Parser ti-cc2650-tmp007-v1</div>
          </div>:<div className="text-xs text-[var(--app-text-muted)]">-- °C — no reading yet.</div>}
        </TiSensorCard>
      </div>
      <p className="mt-2 text-xs text-amber-400">Battery measurement unavailable in discovered GATT profile.</p>
      <button disabled={sensorBusy} onClick={()=>void startAllSensors()} className="mt-3 rounded bg-sky-600 px-3 py-2 text-xs text-white disabled:opacity-40">{sensorBusy?'Activating sensors…':'Start supported sensors'}</button>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries((selected as BleNativeDevice&{sensor_inventory?:Record<string,{present:boolean;status:string}>;sensor_states?:Record<string,{active?:boolean;status?:string;last_reading?:Array<{measurement_type:string;value:number|null;unit:string;source_raw_hex:string}>;calibration_status?:string}>}).sensor_inventory||{}).filter(([name])=>!['test_service'].includes(name)).map(([name,value])=>{const state=(selected as BleNativeDevice&{sensor_states?:Record<string,{active?:boolean;status?:string;last_reading?:Array<{measurement_type:string;value:number|null;unit:string;source_raw_hex:string}>;calibration_status?:string}>}).sensor_states?.[name];const controllable=['accelerometer','magnetometer','barometer','gyroscope','simple_keys','ambient_light','movement'].includes(name);return <div key={name} className="rounded border p-3 text-xs"><b className="capitalize">{name.replaceAll('_',' ')}</b><div className={value.present?'text-emerald-300':'text-slate-400'}>{state?.status?.replaceAll('_',' ')||value.status.replaceAll('_',' ')}</div>{name==='movement'&&value.present&&<div className="mt-1 text-slate-400">Combined accelerometer · gyroscope · magnetometer</div>}{state?.last_reading?.map(item=><div key={item.measurement_type} className="mt-1"><span>{item.measurement_type.replaceAll('_',' ')}: </span><b>{item.value==null?'calibration required':`${item.value} ${item.unit}`}</b></div>)}{state?.calibration_status&&<div className="mt-1 text-amber-300">Calibration: {state.calibration_status.replaceAll('_',' ')}</div>}{value.present&&controllable&&<button disabled={sensorBusy} onClick={()=>void legacySensorAction(name,!state?.active)} className={`mt-2 rounded px-2 py-1 text-white disabled:opacity-40 ${state?.active?'bg-rose-700':'bg-emerald-700'}`}>{sensorBusy?'Working…':state?.active?'Stop':'Start'}</button>}</div>})}</div>
    </div>}
    {services.length>0&&<div className="mt-4"><b className="text-sm">GATT services and characteristics</b><div className="mt-2 space-y-2">{services.map(service=><details key={service.service_uuid} className="rounded border p-3"><summary className="cursor-pointer text-sm">{service.known_name||service.description||'Vendor specific'} · <code>{service.service_uuid}</code></summary>{service.characteristics.map(char=><div key={char.uuid} className="mt-2 flex flex-wrap items-center gap-2 border-t pt-2 text-xs"><code className="mr-auto">{char.uuid}</code><span>{char.properties.join(', ')}</span>{char.properties.includes('read')&&<button onClick={()=>void characteristicAction(char.uuid,'read')} className="rounded bg-sky-600 px-2 py-1 text-white">Read</button>}{(char.properties.includes('notify')||char.properties.includes('indicate'))&&<button onClick={()=>void characteristicAction(char.uuid,'subscribe')} className="rounded bg-emerald-600 px-2 py-1 text-white">Subscribe</button>}</div>)}</details>)}</div></div>}
  </Panel>}</div>;
};

export const RealIqCapture = ({ capabilities, job, live, records, onJob, onOpen, refresh }: { capabilities: BleCaptureCapabilities|null; job: BleCaptureJob|null; live: BleCaptureLive|null; records: BleCaptureRecord[]; onJob:(job:BleCaptureJob)=>void; onOpen:(id:string)=>Promise<void>; refresh:()=>Promise<void> }) => {
  const [channel,setChannel]=useState(37),[duration,setDuration]=useState(3),[gain,setGain]=useState(20),[rate,setRate]=useState(4_000_000),[bandwidth,setBandwidth]=useState(2_000_000),[format,setFormat]=useState('cf32_le'),[antenna,setAntenna]=useState('RX2'),[error,setError]=useState(''); const device=capabilities?.devices[0];
  useEffect(()=>{if(!device)return;const rates=device.sample_rate_ranges_sps.flatMap(x=>x.minimum===x.maximum?[x.minimum]:[x.minimum,x.maximum]);if(rates.length)setRate(rates.reduce((best,x)=>Math.abs(x-4_000_000)<Math.abs(best-4_000_000)?x:best));if(device.antenna_options.length)setAntenna(device.antenna_options.includes('RX2')?'RX2':device.antenna_options[0]);const formats=device.stream_formats??[];setFormat(formats.includes('CF32')?'cf32_le':formats.includes('CS16')?'ci16_le':'ci8');},[device?.device_id]);
  const start=async()=>{if(!device)return;setError('');try{const frequency=BLE_PRIMARY_CHANNELS.find(x=>x.channel===channel)?.frequencyMHz??2402;onJob(await api.createCapture({device_id:device.device_id,ble_channel:channel,center_frequency_hz:frequency*1e6,sample_rate_sps:rate,bandwidth_hz:bandwidth,gain_mode:'manual',gain_db:gain,antenna,duration_seconds:duration,sample_format:format,description:'USRP B200 real IQ capture — experimental',purpose:'interactive_experimental_capture'}));}catch(reason){setError(reason instanceof Error?reason.message:'Capture failed');}};
  const active=job&&!['completed','failed','cancelled','timed_out'].includes(job.state);
  const requestedRate=Number(job?.request?.sample_rate_sps??rate),requestedDuration=Number(job?.request?.duration_seconds??duration),targetSamples=Math.max(1,requestedRate*requestedDuration),receivedSamples=Number(live?.samples_received??0),capturePercent=Math.max(0,Math.min(100,receivedSamples*100/targetSamples));
  return <div className="space-y-4"><Panel title="Capture Real IQ — Experimental capture">
    {!capabilities?.available&&<div className="mb-3 rounded bg-amber-500/10 p-3 text-sm text-amber-500"><b>{capabilities?.reason_code??'DETECTING_SDR'}</b> — {capabilities?.message??'Detecting compatible SDR.'}</div>}
    {capabilities?.available&&!capabilities.capture_enabled&&<div className="mb-3 rounded border border-sky-400/30 bg-sky-500/10 p-3 text-sm text-sky-200"><b>USRP B200 detected.</b> Real-IQ capture is disabled in this already-running backend process. Restart the normal laboratory launcher to apply the new default. No capture starts until you press <b>Capture Real IQ</b>; Capture and Decode BLE remains disabled.</div>}
    {capabilities?.available&&capabilities.capture_enabled&&<div className="mb-3 rounded border border-emerald-400/30 bg-emerald-500/10 p-3 text-sm text-emerald-200"><b>USRP B200 ready.</b> Experimental real-IQ capture is enabled. BLE decoding is not started automatically.</div>}
    <div className="flex flex-wrap items-end gap-3"><label className="text-xs">SDR<select disabled className="mt-1 block h-9 min-w-48 rounded border bg-transparent px-2"><option>{device?`${device.label} (${device.driver})`:'No compatible SDR'}</option></select></label><label className="text-xs">Channel<select value={channel} onChange={e=>setChannel(Number(e.target.value))} className="mt-1 block h-9 rounded border bg-transparent px-2">{BLE_PRIMARY_CHANNELS.map(x=><option key={x.channel} value={x.channel}>CH{x.channel} — {x.frequencyMHz} MHz</option>)}</select></label><label className="text-xs">Rate<input type="number" value={rate} onChange={e=>setRate(Number(e.target.value))} className="mt-1 block h-9 w-28 rounded border bg-transparent px-2" /></label><label className="text-xs">Bandwidth<input type="number" value={bandwidth} onChange={e=>setBandwidth(Number(e.target.value))} className="mt-1 block h-9 w-28 rounded border bg-transparent px-2" /></label><label className="text-xs">Format<select value={format} onChange={e=>setFormat(e.target.value)} className="mt-1 block h-9 rounded border bg-transparent px-2"><option value="cf32_le">cf32_le</option><option value="ci16_le">ci16_le</option><option value="ci8">ci8</option></select></label><label className="text-xs">Antenna<select value={antenna} onChange={e=>setAntenna(e.target.value)} className="mt-1 block h-9 rounded border bg-transparent px-2">{(device?.antenna_options??[]).map(x=><option key={x}>{x}</option>)}</select></label><label className="text-xs">Duration s<input type="number" min={1} max={60} value={duration} onChange={e=>setDuration(Number(e.target.value))} className="mt-1 block h-9 w-20 rounded border bg-transparent px-2" /></label><label className="text-xs">Gain dB<input type="number" value={gain} onChange={e=>setGain(Number(e.target.value))} className="mt-1 block h-9 w-20 rounded border bg-transparent px-2" /></label><button disabled={!capabilities?.capture_enabled||!device||Boolean(active)} onClick={()=>void start()} title={active?'A real-IQ capture is already running':undefined} className="h-9 rounded bg-sky-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">{active?'Capture in progress…':'Capture Real IQ'}</button>{active&&<button onClick={async()=>onJob(await api.cancelCapture(job.capture_id))} className="h-9 rounded bg-red-600 px-4 text-sm text-white">Stop</button>}<button onClick={()=>void refresh()} className="h-9 rounded border px-3 text-sm">Refresh</button></div>
    <div className="mt-2 text-xs text-[var(--app-text-muted)]">Profile derived from {device?.label??'the detected SDR'} capabilities: {format} · {rate} S/s · {bandwidth} Hz · {antenna||'default antenna'}. Capture is preserved before optional analysis.</div>{job&&<div className="mt-2 text-sm"><code>{job.capture_id}</code> · {job.state} {job.error&&<span className="text-red-400">· {job.error}</span>}</div>}{error&&<div className="mt-2 text-red-400">{error}</div>}
  </Panel>{active&&<div className="pointer-events-none fixed right-6 top-6 z-50 w-80 rounded-xl border border-sky-300/30 bg-slate-950/75 p-4 text-slate-100 shadow-2xl backdrop-blur-md"><div className="mb-1 flex items-center justify-between text-sm"><span className="font-semibold">Real-IQ capture running</span><b className="font-mono text-sky-300">{capturePercent.toFixed(1)}%</b></div><div className="h-2 overflow-hidden rounded-full bg-white/15"><div className="h-full bg-sky-400 transition-[width] duration-300" style={{width:`${capturePercent}%`}} /></div><div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-slate-300"><span>Status: {job?.state.replaceAll('_',' ')}</span><span className="text-right">CH{String(job?.request?.ble_channel??channel)}</span><span>{receivedSamples.toLocaleString()} samples</span><span className="text-right">{Number(live?.bytes_written??0).toLocaleString()} bytes</span></div><p className="mt-2 text-[10px] text-slate-400">You can continue viewing the dashboard. Use Stop beside the disabled capture button to cancel.</p></div>}<div className="grid gap-4 xl:grid-cols-3"><Panel title="Live spectrum (dBFS)"><Trace values={live?.spectrum_dbfs??[]} color="#38bdf8" /></Panel><Panel title="I component"><Trace values={live?.i_preview??[]} color="#34d399" /></Panel><Panel title="Q component"><Trace values={live?.q_preview??[]} color="#f472b6" /></Panel></div><LiveHistory live={live} />
  <Panel title="Capture telemetry"><div className="grid gap-2 sm:grid-cols-4 lg:grid-cols-8">{[['Samples',live?.samples_received],['Bytes',live?.bytes_written],['Overflows',live?.stream_overflows],['Discontinuities',live?.input_discontinuities],['Average dBFS',live?.average_power_dbfs?.toFixed(2)],['Peak dBFS',live?.peak_power_dbfs?.toFixed(2)],['Clipping %',live?.clipping_percentage?.toFixed(3)],['UTC',live?.timestamp_utc]].map(([k,v])=><div key={String(k)} className="rounded border p-2 text-xs"><div className="text-[var(--app-text-muted)]">{k}</div><b>{String(v??'Unavailable')}</b></div>)}</div></Panel>
  <Panel title="Real IQ Captures"><div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>ID</th><th>UTC</th><th>Channel</th><th>Sample rate</th><th>Size</th><th>Integrity</th><th>Actions</th></tr></thead><tbody>{records.map(r=><tr key={r.capture_id} className="border-t"><td className="py-2 font-mono">{r.capture_id}</td><td>{r.created_at_utc}</td><td>CH{r.ble_channel??'?'}</td><td>{r.sample_rate_sps}</td><td>{r.actual_size_bytes}</td><td>{r.capture_complete?`complete · ${r.overflow_count} overflow`:'incomplete'}</td><td className="space-x-2"><button onClick={()=>void onOpen(r.capture_id)} className="text-cyan-500">Open</button><a href={api.captureMetaUrl(r.capture_id)} className="text-sky-500">Metadata</a><button onClick={async()=>window.alert(JSON.stringify(await api.verifyCapture(r.capture_id)))} className="text-emerald-500">Verify</button></td></tr>)}</tbody></table>{records.length===0&&<p className="p-4 text-center text-[var(--app-text-muted)]">No preserved real IQ captures.</p>}</div><p className="mt-2 text-xs text-amber-500">These are preserved real RF samples. The dashboard does not claim that visible activity is a decoded BLE frame.</p></Panel></div>;
};

export const Gate2a2DisabledCaptureButtons = () => (
  <Panel title="Automatic capture and decode remains unavailable">
    <div className="flex flex-wrap gap-3">
      <button type="button" disabled title={CAPTURE_AND_DECODE_DISABLED_REASON} className="inline-flex h-9 cursor-not-allowed items-center rounded-md bg-slate-700 px-4 text-sm font-semibold opacity-50">
        <Bluetooth className="mr-2 h-4 w-4" />Capture and Decode BLE
      </button>
    </div>
    <p className="text-xs text-[var(--app-text-muted)]">{CAPTURE_AND_DECODE_DISABLED_REASON}</p>
  </Panel>
);

export const BleLabView: React.FC = () => {
  const { jobId } = useParams(); const navigate = useNavigate(); const [capabilities, setCapabilities] = useState<BleCapabilities | null>(null); const [job, setJob] = useState<BleJob | null>(null); const [packets, setPackets] = useState<BlePacket[]>([]); const [advertisements, setAdvertisements] = useState<BleAdvertisement[]>([]); const [advertisers, setAdvertisers] = useState<BleAdvertiser[]>([]); const [events, setEvents] = useState<BleJobEvent[]>([]); const [channels, setChannels] = useState<unknown>([]); const [diagnostics, setDiagnostics] = useState<unknown>([]); const [artifacts, setArtifacts] = useState<unknown>([]); const [error, setError] = useState('');
  const load = async () => { setError(''); try { setCapabilities(await api.capabilities()); if (!jobId) return; setJob(await api.job(jobId)); const results = await Promise.allSettled([api.packets(jobId), api.advertisements(jobId), api.advertisers(jobId), api.resource<unknown>(jobId, 'channels'), api.resource<BleJobEvent[]>(jobId, 'events'), api.resource<unknown>(jobId, 'diagnostics'), api.resource<unknown>(jobId, 'artifacts')]); const item = <T,>(index: number, fallback: T) => results[index].status === 'fulfilled' ? (results[index] as PromiseFulfilledResult<T>).value : fallback; setPackets(item(0, [])); setAdvertisements(item(1, [])); setAdvertisers(item(2, [])); setChannels(item(3, [])); setEvents(item(4, [])); setDiagnostics(item(5, [])); setArtifacts(item(6, [])); } catch (reason) { setError(reason instanceof Error ? reason.message : 'BLE API unavailable'); } };
  useEffect(() => { void load(); }, [jobId]);
  useEffect(() => {
    if (!jobId || !job || ['completed', 'completed_with_diagnostics', 'failed', 'timed_out', 'cancelled'].includes(job.state)) return;
    const timer = window.setInterval(() => void load(), 750);
    return () => window.clearInterval(timer);
  }, [jobId, job?.state]);
  const represented = useMemo(() => (Array.isArray(channels) ? channels : []).map((entry) => typeof entry === 'number' ? entry : Number((entry as Record<string, unknown>).channel_index ?? (entry as Record<string, unknown>).channel)).filter(Number.isFinite), [channels]);
  const active = job && ['created', 'queued', 'validating_input', 'starting_worker', 'running', 'validating_artifacts', 'cancel_requested'].includes(job.state);
  const reportBleAction=(event:React.MouseEvent<HTMLDivElement>)=>{const control=(event.target as HTMLElement).closest<HTMLElement>('button,a,[role="button"]');if(!control||control.matches(':disabled')||control.dataset.silentAction==='true')return;const label=control.getAttribute('aria-label')||control.getAttribute('title')||control.textContent||'Acción BLE';beginBleButtonAction(label,control.getAttribute('data-operation-target')||undefined)};

  // ── Gate 2A.2 -- entirely separate state, never mixed with Gate 1B above ──
  const [gate2a2Status, setGate2a2Status] = useState<BleGate2a2Status | null>(null);
  const [gate2a2Job, setGate2a2Job] = useState<BleGate2a2Job | null>(null);
  const [gate2a2Candidates, setGate2a2Candidates] = useState<BleGate2a2Candidate[]>([]);
  const [gate2a2ConfirmedPackets, setGate2a2ConfirmedPackets] = useState<BleGate2a2ConfirmedPacket[]>([]);
  const [hybridPackets,setHybridPackets]=useState<BleGate2a2ConfirmedPacket[]>([]);
  const [hybridMatches,setHybridMatches]=useState<BleHybridMatch[]>([]),[hybridEvidence,setHybridEvidence]=useState<BleHybridEvidence|null>(null),[hybridHistory,setHybridHistory]=useState<BleHybridSession[]>([]),[resultSessionId,setResultSessionId]=useState('');
  const [captureCapabilities,setCaptureCapabilities]=useState<BleCaptureCapabilities|null>(null),[captureJob,setCaptureJob]=useState<BleCaptureJob|null>(null),[captureLive,setCaptureLive]=useState<BleCaptureLive|null>(null),[captureRecords,setCaptureRecords]=useState<BleCaptureRecord[]>([]);
  const loadCapture=async(forceSdr=false)=>{try{const [caps,records]=await Promise.all([api.captureCapabilities(forceSdr),api.captures()]);setCaptureCapabilities(caps);setCaptureRecords(records);}catch{setCaptureCapabilities({available:false,capture_enabled:false,capture_and_decode_enabled:false,reason_code:'CAPTURE_API_UNAVAILABLE',message:'Capture API unavailable.',devices:[],default_duration_seconds:10,maximum_duration_seconds:60,supported_formats:[],ble_channels:{}});}};
  const loadGate2a2Status = async () => { try { setGate2a2Status(await api.gate2a2Status()); } catch { setGate2a2Status({ available: false, reason: 'gate2a2_api_unavailable' }); } };
  useEffect(() => { void loadGate2a2Status(); }, []);
  useEffect(()=>{void api.latestHybridPackets().then(setHybridPackets).catch(()=>setHybridPackets([]));},[]);
  useEffect(()=>{void loadCapture();},[]);
  useEffect(()=>{if(!captureJob||['completed','failed','cancelled','timed_out'].includes(captureJob.state))return;const timer=window.setInterval(async()=>{const next=await api.captureJob(captureJob.capture_id);setCaptureJob(next);setCaptureLive(await api.captureLive(next.capture_id));if(['completed','failed','cancelled','timed_out'].includes(next.state))await loadCapture();},500);return()=>window.clearInterval(timer);},[captureJob?.capture_id,captureJob?.state]);
  useEffect(()=>{if(!captureJob)return;const id=`ble-capture:${captureJob.capture_id}`,request=captureJob.request||{},duration=Number(request.duration_seconds||0),rate=Number(request.sample_rate_sps||0),expected=duration*rate,samples=captureLive?.samples_received??0;if(['completed'].includes(captureJob.state)){finishOperation(id,`${samples.toLocaleString()} muestras preservadas`);return}if(['failed','cancelled','timed_out'].includes(captureJob.state)){failOperation(id,captureJob.error||captureJob.state);return}ensureOperation({operationId:id,kind:'capturing',title:'Captura IQ B200',phase:'Adquiriendo muestras RF',progressPercent:0,target:`CH${String(request.ble_channel??'—')}`,configuredDurationSeconds:duration,estimatedTotalSeconds:duration,detail:`${rate.toLocaleString()} S/s`});updateOperation(id,{progressPercent:expected?100*samples/expected:undefined,processedItems:samples,totalItems:expected||undefined,phase:captureJob.state==='running'?'Adquiriendo muestras RF':'Preparando receptor'})},[captureJob,captureLive]);
  useEffect(() => {
    if (!gate2a2Job || GATE2A2_JOB_TERMINAL.includes(gate2a2Job.state)) return;
    const timer = window.setInterval(async () => {
      const next = await api.gate2a2Job(gate2a2Job.job_id);
      setGate2a2Job(next);
      if (GATE2A2_JOB_TERMINAL.includes(next.state) && next.state === 'completed') {
        setGate2a2Candidates(await api.gate2a2Candidates(next.job_id));
        setGate2a2ConfirmedPackets(await api.gate2a2ConfirmedPackets(next.job_id));
      }
    }, 750);
    return () => window.clearInterval(timer);
  }, [gate2a2Job?.job_id, gate2a2Job?.state]);
  const operatorDashboard = true;
  const [detailTab,setDetailTab]=useState<'overview'|'uc02'|'dataset'|'native'|'b200'|'hybrid'|'gatt'|'evidence'|'sessions'>('overview');
  useEffect(()=>{const listener=(event:Event)=>{const {sessionId,tab}=(event as CustomEvent<{sessionId:string;tab:typeof detailTab}>).detail;setResultSessionId(sessionId);setDetailTab(tab);void Promise.all([api.hybridPackets(sessionId),api.hybridMatches(sessionId),api.hybridEvidence(sessionId),api.hybridSessions()]).then(([packets,matches,evidence,history])=>{setHybridPackets(packets);setHybridMatches(matches);setHybridEvidence(evidence);setHybridHistory(history);}).catch(reason=>setError(reason instanceof Error?reason.message:'Unable to load hybrid results'));setTimeout(()=>document.getElementById('ble-session-results')?.scrollIntoView({behavior:'smooth'}),50);};window.addEventListener('ble-hybrid-open-results',listener);return()=>window.removeEventListener('ble-hybrid-open-results',listener);},[]);
  if (operatorDashboard) return (
    <div onClickCapture={reportBleAction} className="h-full overflow-auto bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-sky-500"><Bluetooth className="h-4 w-4" />Adquisición RF real</div>
          <h1 className="text-2xl font-semibold">Bluetooth LE Sensors</h1>
          <p className="mt-1 text-sm text-[var(--app-text-muted)]">Primero mediciones BLE nativas · captura RF USRP B200 opcional</p>
        </div>
        <button type="button" onClick={() => void loadCapture(true)} className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium" style={{ borderColor: 'var(--app-border)' }}><RefreshCw className="h-4 w-4" />Actualizar SDR</button>
      </div>

      <BleHybridController />

      <Panel title="Flujo recomendado">
        <ol className="grid gap-3 lg:grid-cols-5">
          {[
            ['1', 'Encienda los sensores', 'Encienda los dispositivos BLE reales y active Bluetooth en este equipo.'],
            ['2', 'Escanee', 'Ejecute un escaneo nativo e identifique el sensor por nombre, dirección y advertising.'],
            ['3', 'Inspeccione', 'Si los valores no están en advertising, conecte GATT e inspeccione sus características.'],
            ['4', 'Lea los valores', 'Use lectura o suscripción sólo cuando la característica lo permita. Cada valor conserva parser y bytes originales.'],
            ['5', 'Evidencia RF opcional', 'Use el B200 para preservar IQ en el canal elegido. El espectro no se interpreta como medida del sensor.'],
          ].map(([number,title,description])=><li key={number} className="rounded-lg border p-4" style={{ borderColor:'var(--app-border)' }}><div className="mb-2 flex h-7 w-7 items-center justify-center rounded-full bg-sky-600 text-sm font-bold text-white">{number}</div><div className="font-semibold">{title}</div><p className="mt-1 text-xs leading-5 text-[var(--app-text-muted)]">{description}</p></li>)}
        </ol>
      </Panel>

      <div className="my-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
        <AlertTriangle className="mr-2 inline h-4 w-4" /><b>Regla de medición:</b> temperatura, humedad y batería proceden exclusivamente de bytes advertising o GATT interpretados. Nunca se infieren del espectro, RSSI o waterfall. Los formatos desconocidos permanecen como datos crudos.
      </div>

      <div id="ble-session-results" className="mb-2 text-sm text-sky-300">{resultSessionId?`Mostrando exclusivamente: ${resultSessionId}`:'Selecciona una sesión desde el controlador para ver sus resultados actuales.'}</div>
      <div className="mb-5 flex flex-wrap gap-2 border-b pb-3" style={{borderColor:'var(--app-border)'}}>{([['overview','Resumen'],['uc02','UC-02 · Identificar SensorTag'],['dataset','Dataset Studio'],['native','Dispositivos nativos'],['b200','Paquetes B200'],['hybrid','Coincidencias híbridas'],['gatt','Diagnóstico GATT'],['evidence','Evidencia'],['sessions','Sesiones']] as const).map(([id,label])=><button key={id} onClick={()=>setDetailTab(id)} className={`rounded px-3 py-2 text-sm ${detailTab===id?'bg-sky-600 text-white':'bg-slate-800 text-slate-300'}`}>{label}</button>)}</div>
      {detailTab==='overview'&&<Panel title="Resumen operacional"><p className="text-sm text-[var(--app-text-muted)]">Utilice el controlador superior para completar el flujo. Los datos científicos detallados permanecen disponibles en las pestañas.</p></Panel>}
      {detailTab==='uc02'&&<BleUc02Panel />}
      {detailTab==='dataset'&&<BleDatasetStudio />}
      {(detailTab==='native'||detailTab==='gatt')&&<div className="mb-8"><NativeBleDevices /></div>}
      {detailTab==='b200'&&<div className="mb-8"><Gate2a2ConfirmedPacketsPanel packets={hybridPackets} /></div>}
      {detailTab==='hybrid'&&<Panel title={`Hybrid matches — ${resultSessionId||'select a session'}`}><div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>Status</th><th>Rule</th><th>SDR observation</th><th>Native observation</th><th>Δt</th><th>Payload</th></tr></thead><tbody>{hybridMatches.map((match,index)=><tr key={`${match.sdr_observation_id}-${index}`} className="border-t"><td>{match.status}</td><td>{match.rule}</td><td className="font-mono text-xs">{match.sdr_observation_id}</td><td className="font-mono text-xs">{match.native_observation_id||'—'}</td><td>{match.time_difference_ms??'—'} ms</td><td>{match.payload_match?'match':'—'}</td></tr>)}</tbody></table>{!hybridMatches.length&&<p className="p-4 text-[var(--app-text-muted)]">No matches for the selected session.</p>}</div></Panel>}
      {detailTab==='evidence'&&<Panel title={`Evidence — ${resultSessionId||'select a session'}`}><div className="space-y-2 text-sm">{Object.entries(hybridEvidence?.artifacts||{}).map(([name,path])=><div key={name} className="rounded border p-3"><b>{name.replaceAll('_',' ')}</b><div className="break-all font-mono text-xs text-[var(--app-text-muted)]">{path||'not available'}</div></div>)}</div></Panel>}
      {detailTab==='sessions'&&<Panel title="Hybrid sessions"><div className="space-y-2">{hybridHistory.map(item=><button key={item.session_id} onClick={()=>window.dispatchEvent(new CustomEvent('ble-hybrid-open-results',{detail:{sessionId:item.session_id,tab:'overview'}}))} className="block w-full rounded border p-3 text-left"><b>{item.session_id}</b><span className="ml-3 text-sm">{item.state} · CH{item.channel} · {item.duration_seconds}s · {item.counters?.crc_valid_packets??0} CRC · {item.counters?.strong_matches??0} matches</span></button>)}</div></Panel>}
    </div>
  );
  return (
    <div className="h-full overflow-auto bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">
            <Bluetooth className="h-4 w-4" /> Experimental passive analyzer
          </div>
          <h1 className="text-2xl font-semibold">Bluetooth LE Analysis</h1>
          <p className="mt-1 text-sm text-[var(--app-text-muted)]">LE 1M primary advertising</p>
        </div>
        <div className="flex gap-2">
          {jobId && <Link to="/ble-lab" className="inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium" style={{ borderColor: 'var(--app-border)' }}>BLE Lab home</Link>}
          <button type="button" onClick={() => void load()} className="inline-flex h-9 w-9 items-center justify-center rounded-md border" style={{ borderColor: 'var(--app-border)' }} title="Refresh"><RefreshCw className="h-4 w-4" /></button>
        </div>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div>}

      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-500">Validated bitstream replay — Gate 1B</div>
      <div className="mb-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
        <AlertTriangle className="mr-2 inline h-4 w-4" />{replayNotice}
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <BleJobLauncher enabled={Boolean(capabilities?.enabled)} captureCapabilities={captureCapabilities} captureBusy={Boolean(captureJob&&!['completed','failed','cancelled','timed_out'].includes(captureJob.state))} onCreated={(created) => navigate(`/ble-lab/jobs/${created.job_id}`)} onCaptureCreated={setCaptureJob} />
        <BleCapabilityStatus capabilities={capabilities} />
      </div>

      {job ? <>
        <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4" style={surfaceStyle}>
          <div className="flex items-center gap-3">
            <CheckCircle2 className={`h-5 w-5 ${job.state === 'completed' ? 'text-emerald-500' : 'text-amber-500'}`} />
            <div><div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Current analysis</div><code className="font-semibold">{job.job_id}</code> <span className="ml-2 text-sm">{job.state.replaceAll('_', ' ')}</span><BleJobProgress job={job} /></div>
          </div>
          <div>{active && <button onClick={async () => setJob(await api.cancel(job.job_id))} className="mr-2 inline-flex h-9 items-center gap-2 rounded-md bg-red-600 px-3 text-sm font-semibold text-white"><Square className="h-4 w-4" />Cancel</button>}{['failed', 'timed_out', 'cancelled'].includes(job.state) && <button onClick={async () => { const next = await api.retry(job.job_id); navigate(`/ble-lab/jobs/${next.job_id}`); }} className="inline-flex h-9 items-center gap-2 rounded-md bg-amber-500 px-3 text-sm font-semibold text-slate-950"><RotateCcw className="h-4 w-4" />Retry</button>}</div>
        </section>
        <div className="mb-6"><BleJobSummary job={job} /></div>
        <div className="mb-6"><BleChannelMap represented={represented} /></div>
        <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.75fr)]">
          <BlePacketTable packets={packets} />
          <div className="space-y-6"><BleAdvertisementTable advertisements={advertisements} /><BleAdvertiserTable advertisers={advertisers} /></div>
        </div>
        <div className="mb-6 grid gap-6 xl:grid-cols-2"><BleReceiverPipeline events={events} /><BleDiagnostics diagnostics={diagnostics} /></div>
        <div className="mb-6"><BleArtifactDownloads jobId={job.job_id} artifacts={artifacts} /></div>
      </> : <div className="mb-6 rounded-lg border border-dashed p-8 text-center" style={{ borderColor: 'var(--app-border)' }}><div className="text-base font-semibold">No BLE analysis is running</div><div className="mt-1 text-sm text-[var(--app-text-muted)]">Choose a channel for the future IQ capture workflow, or press “Analyze replay frames” to launch the validated decoder test.</div></div>}

      <div className="mb-10 grid gap-6 xl:grid-cols-2"><BleWorkerProvenance capabilities={capabilities} job={job ?? undefined} /><BleKnownLimitations /></div>

      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-500">Real IQ capture and visualization</div>
      <div className="mb-8"><RealIqCapture capabilities={captureCapabilities} job={captureJob} live={captureLive} records={captureRecords} onJob={setCaptureJob} onOpen={async(id)=>setCaptureLive(await api.captureLive(id))} refresh={()=>loadCapture(true)} /></div>

      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Experimental IQ recovery — Gate 2A.2</div>
      <div className="mb-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        Experimental offline IQ analysis. Receiver Candidate B is not frozen. Not validated for OTA reception. Results may contain decoding errors.
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Gate2a2StatusPanel status={gate2a2Status} />
        <AnalyzeIqFilePanel
          enabled={Boolean(gate2a2Status?.available)}
          disabledReason={gate2a2Status?.disabled_reason ?? gate2a2Status?.reason}
          onCreated={setGate2a2Job}
        />
      </div>

      {gate2a2Job && (
        <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4" style={surfaceStyle}>
          <div className="flex items-center gap-3">
            <CheckCircle2 className={`h-5 w-5 ${gate2a2Job.state === 'completed' ? 'text-emerald-500' : 'text-amber-500'}`} />
            <div>
              <div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Current offline analysis</div>
              <code className="font-semibold">{gate2a2Job.job_id}</code> <span className="ml-2 text-sm">{gate2a2Job.state.replaceAll('_', ' ')}</span>
              {gate2a2Job.error && <div className="mt-1 text-sm text-red-400">{gate2a2Job.error}</div>}
            </div>
          </div>
          {!GATE2A2_JOB_TERMINAL.includes(gate2a2Job.state) && (
            <button onClick={async () => setGate2a2Job(await api.cancelGate2a2Job(gate2a2Job.job_id))} className="inline-flex h-9 items-center gap-2 rounded-md bg-red-600 px-3 text-sm font-semibold text-white">
              <Square className="h-4 w-4" />Cancel
            </button>
          )}
        </section>
      )}

      {gate2a2Job?.state === 'completed' && (
        <>
          <div className="mb-6"><Gate2a2CandidateTable candidates={gate2a2Candidates} /></div>
          <div className="mb-6"><Gate2a2ConfirmedPacketsPanel packets={gate2a2ConfirmedPackets} /></div>
          <div className="mb-6">
            <a href={api.gate2a2BundleUrl(gate2a2Job.job_id)} className="inline-flex items-center gap-2 rounded bg-slate-700 px-3 py-2 text-sm"><Download className="h-4 w-4" />Download reproducible bundle</a>
          </div>
        </>
      )}

      <div className="mb-6"><Gate2a2DisabledCaptureButtons /></div>
    </div>
  );
};
