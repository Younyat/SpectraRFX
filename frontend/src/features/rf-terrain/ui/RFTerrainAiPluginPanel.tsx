import React, { useEffect, useState } from 'react';
import { AlertTriangle, Brain, CheckCircle2, Compass, PauseCircle, PlayCircle, RefreshCw, UploadCloud } from 'lucide-react';
import { HudFrame } from './hud/HudFrame';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_PANEL_BACKGROUND, hudLabelClass } from './hud/hudTheme';
import { AiResearchPluginApiError, AiResearchPluginClient } from '../../ai-research-plugin/api/aiResearchPluginClient';
import { RFModelCatalogModal } from '../../ai-research-plugin/catalog/ui/RFModelCatalogModal';
import type { UseAiLiveDetectionResult } from '../ai/useAiLiveDetection';
import type {
  AiPluginCaptureSummary,
  CompatibilityResult,
  InferenceRecord,
  InputRepresentation,
  RFModelManifest,
} from '../../ai-research-plugin/types';

interface RFTerrainAiPluginPanelProps {
  open: boolean;
  onToggleOpen: () => void;
  liveDetection: UseAiLiveDetectionResult;
}

type Source = 'LIVE' | 'OFFLINE';

const client = new AiResearchPluginClient();
const REPRESENTATIONS: InputRepresentation[] = ['iq_tensor', 'flat_iq', 'spectrogram', 'psd'];

const verdictColor: Record<CompatibilityResult['verdict'], string> = {
  COMPATIBLE: '#4ade80',
  PARTIALLY_COMPATIBLE: '#facc15',
  INCOMPATIBLE: '#f87171',
  UNKNOWN: HUD_BORDER_COLOR,
};

const shapeText = (shape: (number | null)[] | null) => (shape ? `[${shape.map((d) => (d === null ? '?' : d)).join(', ')}]` : 'unknown');

const formatLatency = (ms: number | null): string => (ms === null ? 'unknown' : ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms.toFixed(0)} ms`);

// FSEI -- AI Model Inspection: an experimental sibling to the point/object
// FSEI dossier (Object Details panel, "Forensic Spectral Evidence
// Inspector") -- same forensic-evidence spirit, but inspecting what an
// imported AI model extracts from a signal rather than a clicked terrain
// point. Deliberately a separate panel/button rather than merged into the
// existing dossier, to avoid disturbing that already-shipped feature; the
// name is shared on purpose, the surface is not. Talks only to
// /api/ai-research-plugin/*.
//
// OFFLINE stays fully one-shot, local state (unchanged). LIVE is driven
// by `liveDetection` (useAiLiveDetection, owned by RFTerrainView) so its
// continuous polling loop -- and the 3D detection boxes it feeds --
// keep running after this panel closes, exactly like OFFLINE
// RECONSTRUCTION's objects stay visible after that panel closes.
export const RFTerrainAiPluginPanel: React.FC<RFTerrainAiPluginPanelProps> = ({ open, onToggleOpen, liveDetection }) => {
  const [captures, setCaptures] = useState<AiPluginCaptureSummary[]>([]);
  const [offlineModelId, setOfflineModelId] = useState('');
  const [source, setSource] = useState<Source>('OFFLINE');
  const [captureId, setCaptureId] = useState('');
  const [t0, setT0] = useState(0);
  const [t1, setT1] = useState(0.001);
  const [representation, setRepresentation] = useState<InputRepresentation>('iq_tensor');
  const [compatibility, setCompatibility] = useState<CompatibilityResult | null>(null);
  const [record, setRecord] = useState<InferenceRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'idle' | 'importing' | 'checking' | 'running'>('idle');
  const [catalogOpen, setCatalogOpen] = useState(false);

  const { models, refreshModels, liveAvailable } = liveDetection;
  const refreshCaptures = () => client.listCaptures().then(setCaptures).catch((e) => setError(String(e)));

  useEffect(() => {
    if (open) {
      refreshModels();
      refreshCaptures();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-fetch when the panel opens
  }, [open]);

  const runGuarded = async (label: typeof busy, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof AiResearchPluginApiError ? e.message : String(e));
    } finally {
      setBusy('idle');
    }
  };

  const handleImport = (file: File) =>
    runGuarded('importing', async () => {
      const manifest = await client.importModel(file);
      await refreshModels();
      setOfflineModelId(manifest.model_id);
      liveDetection.setSelectedModelId(manifest.model_id);
    });

  const canRunOffline = offlineModelId !== '' && captureId !== '' && t1 > t0;

  return (
    <div className="pointer-events-none absolute bottom-14 left-3 z-20 flex flex-col items-start gap-2">
      {open && (
        <HudFrame className="pointer-events-auto flex w-80 flex-col gap-2 rounded-sm p-3 text-slate-100 shadow-2xl">
          <div className="flex items-center justify-between">
            <div>
              <h3 className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>FSEI -- AI Model Inspection</h3>
              <p className="text-[9px] app-muted-text">Separate from the point/object FSEI dossier (Object Details).</p>
            </div>
            <button onClick={refreshModels} title="Refresh" className="rounded border p-1" style={{ borderColor: HUD_BORDER_COLOR }}>
              <RefreshCw className="h-3 w-3" />
            </button>
          </div>

          <div className="rounded border border-dashed p-1.5 text-[10px] text-amber-300" style={{ borderColor: '#f59e0b' }}>
            Experimental. A prediction only reflects the imported model's own training -- never confirmed device/protocol identification. ONNX only in this phase.
          </div>

          {error && <p className="text-[10px] text-red-400">{error}</p>}

          <label className="flex cursor-pointer items-center justify-center gap-2 rounded border px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide" style={{ borderColor: HUD_BORDER_COLOR }}>
            <UploadCloud className="h-3.5 w-3.5" />
            {busy === 'importing' ? 'Importing…' : 'Import .onnx model'}
            <input
              type="file"
              accept=".onnx"
              className="hidden"
              disabled={busy === 'importing'}
              onChange={(event) => { const file = event.target.files?.[0]; if (file) handleImport(file); event.target.value = ''; }}
            />
          </label>

          <button
            onClick={() => setCatalogOpen(true)}
            className="flex items-center justify-center gap-2 rounded border px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ borderColor: HUD_BORDER_COLOR }}
          >
            <Compass className="h-3.5 w-3.5" />
            Discover RF Models
          </button>

          <div className="flex items-center justify-between">
            <span className="text-[10px] app-muted-text">Source</span>
            <div className="flex overflow-hidden rounded border" style={{ borderColor: HUD_BORDER_COLOR }}>
              {(['LIVE', 'OFFLINE'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => setSource(option)}
                  className="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                  style={{ background: source === option ? HUD_ACCENT_BRIGHT : 'transparent', color: source === option ? '#04121a' : undefined }}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          {source === 'LIVE' && (
            <LivePanel liveDetection={liveDetection} models={models} liveAvailable={liveAvailable} />
          )}

          {source === 'OFFLINE' && (
            <>
              <label className="flex flex-col gap-1 text-[10px] app-muted-text">
                Model
                <select value={offlineModelId} onChange={(e) => setOfflineModelId(e.target.value)} className="rounded-md border bg-transparent px-2 py-1 text-xs text-slate-100" style={{ borderColor: 'var(--app-border)' }}>
                  <option value="">{models.length === 0 ? 'No models imported yet' : 'Select…'}</option>
                  {models.map((m) => <option key={m.model_id} value={m.model_id}>{m.model_name} ({m.framework})</option>)}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-[10px] app-muted-text">
                Capture ID
                <div className="flex gap-1">
                  <input
                    value={captureId}
                    onChange={(e) => setCaptureId(e.target.value)}
                    placeholder="BLE-IQ-..."
                    list="ai-plugin-captures"
                    className="flex-1 rounded-md border bg-transparent px-2 py-1 text-xs text-slate-100"
                    style={{ borderColor: 'var(--app-border)' }}
                  />
                  <datalist id="ai-plugin-captures">
                    {captures.map((c) => <option key={c.capture_id} value={c.capture_id} />)}
                  </datalist>
                </div>
              </label>

              <div className="grid grid-cols-2 gap-1.5">
                <label className="flex flex-col gap-1 text-[10px] app-muted-text">
                  t0 (s)
                  <input type="number" step={0.0001} value={t0} onChange={(e) => setT0(Number(e.target.value))} className="rounded-md border bg-transparent px-1.5 py-1 text-xs text-slate-100" style={{ borderColor: 'var(--app-border)' }} />
                </label>
                <label className="flex flex-col gap-1 text-[10px] app-muted-text">
                  t1 (s)
                  <input type="number" step={0.0001} value={t1} onChange={(e) => setT1(Number(e.target.value))} className="rounded-md border bg-transparent px-1.5 py-1 text-xs text-slate-100" style={{ borderColor: 'var(--app-border)' }} />
                </label>
              </div>

              <label className="flex flex-col gap-1 text-[10px] app-muted-text">
                Representation
                <select value={representation} onChange={(e) => setRepresentation(e.target.value as InputRepresentation)} className="rounded-md border bg-transparent px-1 py-1 text-[11px] text-slate-100" style={{ borderColor: 'var(--app-border)' }}>
                  {REPRESENTATIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>

              <div className="flex gap-2">
                <button
                  disabled={!canRunOffline || busy !== 'idle'}
                  onClick={() => runGuarded('checking', async () => setCompatibility(await client.checkCompatibility(offlineModelId, captureId, t0, t1, representation)))}
                  className="flex-1 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
                  style={{ borderColor: HUD_BORDER_COLOR }}
                >
                  {busy === 'checking' ? 'Checking…' : 'Compatibility'}
                </button>
                <button
                  disabled={!canRunOffline || busy !== 'idle'}
                  onClick={() => runGuarded('running', async () => setRecord(await client.runInference(offlineModelId, captureId, t0, t1, representation)))}
                  className="flex-1 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
                  style={{ borderColor: HUD_ACCENT_BRIGHT, color: HUD_ACCENT_BRIGHT }}
                >
                  {busy === 'running' ? 'Running…' : 'Run inference'}
                </button>
              </div>

              {compatibility && (
                <div className="rounded border p-1.5 text-[10px]" style={{ borderColor: HUD_BORDER_COLOR }}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="app-muted-text">Compatibility</span>
                    <span className="font-semibold" style={{ color: verdictColor[compatibility.verdict] }}>{compatibility.verdict}</span>
                  </div>
                  {compatibility.checks.map((c) => (
                    <div key={c.field} className="flex justify-between app-muted-text">
                      <span>{c.field}</span>
                      <span>{c.matched === null ? '—' : c.matched ? '✓' : '✕'}</span>
                    </div>
                  ))}
                </div>
              )}

              {record && (
                <div className="rounded border p-1.5 text-[10px]" style={{ borderColor: HUD_BORDER_COLOR }}>
                  <div className="mb-1 flex items-center justify-between app-muted-text">
                    <span>Result</span>
                    <span className="font-mono">{record.capture_id}</span>
                  </div>
                  {record.interpretation.kind === 'classification' ? (
                    <p><strong>{record.interpretation.predicted_class}</strong> ({record.interpretation.score_type}={record.interpretation.score?.toFixed(3)})</p>
                  ) : record.interpretation.kind === 'embedding' ? (
                    <p>embedding, dim={record.interpretation.dimensionality}, ‖z‖={record.interpretation.l2_norm?.toFixed(3)}</p>
                  ) : (
                    <p className="app-muted-text">not automatically interpretable</p>
                  )}
                  {record.interpretation.warning && <p className="mt-1 text-amber-400">{record.interpretation.warning}</p>}
                  <p className="mt-1 app-muted-text">shape {shapeText(record.input_tensor_shape)} · inference {formatLatency(record.inference_latency_ms)}</p>
                </div>
              )}
            </>
          )}
        </HudFrame>
      )}
      <button
        onClick={onToggleOpen}
        className="pointer-events-auto flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
        style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND }}
      >
        <Brain className="h-3.5 w-3.5" />
        FSEI -- AI
        {liveDetection.continuousEnabled && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: liveDetection.applicability?.applicable ? '#4ade80' : '#f59e0b' }} title="Continuous LIVE detection running" />
        )}
      </button>

      {catalogOpen && <RFModelCatalogModal onClose={() => setCatalogOpen(false)} />}
    </div>
  );
};

const LivePanel: React.FC<{
  liveDetection: UseAiLiveDetectionResult;
  models: RFModelManifest[];
  liveAvailable: boolean | null;
}> = ({ liveDetection, models, liveAvailable }) => {
  const {
    selectedModelId, setSelectedModelId, representation, setRepresentation,
    continuousEnabled, setContinuousEnabled, applicability, representationApplicability, latestRecord, latestError,
    detections, pollCount, busy, runOnce,
  } = liveDetection;

  const canRunLive = selectedModelId !== '' && liveAvailable === true && representationApplicability?.compatible !== false;
  const latest = detections[0];

  return (
    <>
      <label className="flex flex-col gap-1 text-[10px] app-muted-text">
        Model
        <select value={selectedModelId} onChange={(e) => setSelectedModelId(e.target.value)} className="rounded-md border bg-transparent px-2 py-1 text-xs text-slate-100" style={{ borderColor: 'var(--app-border)' }}>
          <option value="">{models.length === 0 ? 'No models imported yet' : 'Select…'}</option>
          {models.map((m) => <option key={m.model_id} value={m.model_id}>{m.model_name} ({m.framework})</option>)}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-[10px] app-muted-text">
        Representation
        <select value={representation} onChange={(e) => setRepresentation(e.target.value as InputRepresentation)} className="rounded-md border bg-transparent px-1 py-1 text-[11px] text-slate-100" style={{ borderColor: 'var(--app-border)' }}>
          {REPRESENTATIONS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </label>

      {liveAvailable === false && (
        <p className="rounded border border-dashed p-1.5 text-[10px] text-amber-300" style={{ borderColor: '#f59e0b' }}>Live SDR bridge unavailable on this backend.</p>
      )}

      {applicability && !applicability.applicable && (
        <div className="flex items-start gap-1.5 rounded border p-1.5 text-[10px] text-amber-300" style={{ borderColor: '#f59e0b' }}>
          <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
          <p>{applicability.reason}</p>
        </div>
      )}
      {applicability?.applicable && applicability.reason && (
        <div className="flex items-start gap-1.5 rounded border p-1.5 text-[10px] app-muted-text" style={{ borderColor: HUD_BORDER_COLOR }}>
          <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0 text-amber-300" />
          <p>{applicability.reason}</p>
        </div>
      )}

      {representationApplicability && !representationApplicability.compatible && (
        <div className="flex items-start gap-1.5 rounded border p-1.5 text-[10px] text-red-400" style={{ borderColor: '#f87171' }}>
          <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
          <p>{representationApplicability.reason}</p>
        </div>
      )}

      <div className="flex gap-2">
        <button
          disabled={!canRunLive}
          onClick={() => setContinuousEnabled(!continuousEnabled)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded border px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
          style={{
            borderColor: continuousEnabled ? '#f87171' : HUD_ACCENT_BRIGHT,
            color: continuousEnabled ? '#f87171' : HUD_ACCENT_BRIGHT,
          }}
        >
          {continuousEnabled ? <PauseCircle className="h-3.5 w-3.5" /> : <PlayCircle className="h-3.5 w-3.5" />}
          {continuousEnabled ? 'Stop continuous' : 'Start continuous'}
        </button>
        <button
          disabled={!canRunLive || continuousEnabled || busy}
          onClick={() => runOnce()}
          className="rounded border px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
          style={{ borderColor: HUD_BORDER_COLOR }}
        >
          Once
        </button>
      </div>

      {continuousEnabled && (
        <p className="text-[9px] app-muted-text">
          Applying model to the live capture as it streams from the B200 -- polls at least every 0.8s, never overlapping requests. {pollCount} run{pollCount === 1 ? '' : 's'} so far.
        </p>
      )}

      {latestError && <p className="text-[10px] text-red-400">{latestError}</p>}

      {latest && (
        <div className="rounded border p-1.5 text-[10px]" style={{ borderColor: HUD_BORDER_COLOR }}>
          <div className="mb-1 flex items-center justify-between app-muted-text">
            <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-400" /> Latest detection</span>
            <span className="font-mono">{formatLatency(latest.totalLatencyMs)}</span>
          </div>
          <p><strong>{latest.summary}</strong></p>
          <p className="mt-1 app-muted-text">{(latest.centerFrequencyHz / 1e6).toFixed(3)} MHz · {new Date(latest.detectedAtUtc).toLocaleTimeString()}</p>
        </div>
      )}

      {latestRecord && (
        <p className="text-[9px] app-muted-text">
          {latestRecord.total_latency_ms !== null
            ? `Real end-to-end latency: ${formatLatency(latestRecord.total_latency_ms)} (capture ${formatLatency(latestRecord.capture_latency_ms)} + inference ${formatLatency(latestRecord.inference_latency_ms)}). ${latestRecord.total_latency_ms > 1000 ? 'Not real-time at this cadence -- treat detections as periodic samples, not continuous coverage.' : ''}`
            : ''}
        </p>
      )}
    </>
  );
};
