import React, { useEffect, useState } from 'react';
import { Brain, ChevronDown, ChevronUp, ExternalLink, RefreshCw, UploadCloud } from 'lucide-react';
import { HudFrame } from './hud/HudFrame';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_PANEL_BACKGROUND, hudLabelClass } from './hud/hudTheme';
import { AiResearchPluginApiError, AiResearchPluginClient } from '../../ai-research-plugin/api/aiResearchPluginClient';
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
}

type Source = 'LIVE' | 'OFFLINE';

const client = new AiResearchPluginClient();
const REPRESENTATIONS: InputRepresentation[] = ['iq_tensor', 'spectrogram', 'psd'];

const verdictColor: Record<CompatibilityResult['verdict'], string> = {
  COMPATIBLE: '#4ade80',
  PARTIALLY_COMPATIBLE: '#facc15',
  INCOMPATIBLE: '#f87171',
  UNKNOWN: HUD_BORDER_COLOR,
};

// Real, independently verified repositories/resources for pretrained RF
// signal-classification models -- never invented URLs. Format/caveats are
// stated honestly: most of these ship PyTorch weights, not ready-made
// ONNX files, and would need `torch.onnx.export` before they can be
// imported here.
const MODEL_SOURCES: Array<{ name: string; url: string; note: string }> = [
  { name: 'ONNX Model Zoo', url: 'https://github.com/onnx/models', note: 'Official ONNX-format models -- general-purpose, not RF-specific, but ready to import as-is.' },
  { name: 'TorchSig (TorchDSP)', url: 'https://github.com/TorchDSP/torchsig', note: 'Actively maintained; models pretrained on the Sig53/WidebandSig53 signal datasets. PyTorch -- export to ONNX first.' },
  { name: 'DeepSig RadioML', url: 'https://www.deepsig.ai/datasets', note: 'The standard AMC dataset (not a model download) -- most published AMC models are trained on this.' },
  { name: 'IQTLabs rfml', url: 'https://github.com/IQTLabs/rfml', note: 'RF machine-learning toolkit and reference models. PyTorch -- export to ONNX first.' },
];

const shapeText = (shape: (number | null)[] | null) => (shape ? `[${shape.map((d) => (d === null ? '?' : d)).join(', ')}]` : 'unknown');

// FSEI -- AI Model Inspection: an experimental sibling to the point/object
// FSEI dossier (Object Details panel, "Forensic Spectral Evidence
// Inspector") -- same forensic-evidence spirit, but inspecting what an
// imported AI model extracts from a signal rather than a clicked terrain
// point. Deliberately a separate panel/button rather than merged into the
// existing dossier, to avoid disturbing that already-shipped feature; the
// name is shared on purpose, the surface is not. Talks only to
// /api/ai-research-plugin/*; never touches RF Terrain's own canvas/engine,
// and its LIVE path only ever reads a bounded, on-demand raw I/Q snapshot
// from the SAME live SDR stream Live Monitor/RF Terrain already use --
// never a second device session.
export const RFTerrainAiPluginPanel: React.FC<RFTerrainAiPluginPanelProps> = ({ open, onToggleOpen }) => {
  const [models, setModels] = useState<RFModelManifest[]>([]);
  const [captures, setCaptures] = useState<AiPluginCaptureSummary[]>([]);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [source, setSource] = useState<Source>('OFFLINE');
  const [captureId, setCaptureId] = useState('');
  const [t0, setT0] = useState(0);
  const [t1, setT1] = useState(0.001);
  const [representation, setRepresentation] = useState<InputRepresentation>('iq_tensor');
  const [compatibility, setCompatibility] = useState<CompatibilityResult | null>(null);
  const [record, setRecord] = useState<InferenceRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'idle' | 'importing' | 'checking' | 'running'>('idle');
  const [liveAvailable, setLiveAvailable] = useState<boolean | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);

  const refreshModels = () => client.listModels().then(setModels).catch((e) => setError(String(e)));
  const refreshCaptures = () => client.listCaptures().then(setCaptures).catch((e) => setError(String(e)));

  useEffect(() => {
    if (open) {
      refreshModels();
      refreshCaptures();
      client.getStatus().then((s) => setLiveAvailable(s.live_inference_available)).catch(() => setLiveAvailable(null));
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
      setSelectedModelId(manifest.model_id);
    });

  const canRunOffline = selectedModelId !== '' && captureId !== '' && t1 > t0;
  const canRunLive = selectedModelId !== '' && liveAvailable === true;

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

          <div>
            <button onClick={() => setSourcesOpen((prev) => !prev)} className="flex w-full items-center justify-between text-[10px] app-muted-text">
              <span>Where to find models</span>
              {sourcesOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
            {sourcesOpen && (
              <div className="mt-1 flex flex-col gap-1.5 rounded border p-1.5" style={{ borderColor: HUD_BORDER_COLOR }}>
                {MODEL_SOURCES.map((s) => (
                  <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="group">
                    <span className="flex items-center gap-1 text-[10px] font-semibold" style={{ color: HUD_ACCENT_BRIGHT }}>
                      {s.name} <ExternalLink className="h-2.5 w-2.5" />
                    </span>
                    <span className="text-[9px] app-muted-text">{s.note}</span>
                  </a>
                ))}
              </div>
            )}
          </div>

          <label className="flex flex-col gap-1 text-[10px] app-muted-text">
            Model
            <select value={selectedModelId} onChange={(e) => setSelectedModelId(e.target.value)} className="rounded-md border bg-transparent px-2 py-1 text-xs text-slate-100" style={{ borderColor: 'var(--app-border)' }}>
              <option value="">{models.length === 0 ? 'No models imported yet' : 'Select…'}</option>
              {models.map((m) => <option key={m.model_id} value={m.model_id}>{m.model_name} ({m.framework})</option>)}
            </select>
          </label>

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
            <div className="rounded border border-dashed p-1.5 text-[10px]" style={{ borderColor: liveAvailable ? HUD_BORDER_COLOR : '#f59e0b' }}>
              {liveAvailable === false && <p className="text-amber-300">Live SDR bridge unavailable on this backend.</p>}
              {liveAvailable === null && <p className="app-muted-text">Checking live availability…</p>}
              {liveAvailable === true && (
                <p className="app-muted-text">
                  Captures a bounded raw I/Q snapshot from the SAME live SDR stream Live Monitor already uses (sized to the selected model's own declared input -- never an arbitrary duration).
                </p>
              )}
            </div>
          )}

          {source === 'OFFLINE' && (
            <>
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
            </>
          )}

          <label className="flex flex-col gap-1 text-[10px] app-muted-text">
            Representation
            <select value={representation} onChange={(e) => setRepresentation(e.target.value as InputRepresentation)} className="rounded-md border bg-transparent px-1 py-1 text-[11px] text-slate-100" style={{ borderColor: 'var(--app-border)' }}>
              {REPRESENTATIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>

          <div className="flex gap-2">
            {source === 'OFFLINE' && (
              <button
                disabled={!canRunOffline || busy !== 'idle'}
                onClick={() => runGuarded('checking', async () => setCompatibility(await client.checkCompatibility(selectedModelId, captureId, t0, t1, representation)))}
                className="flex-1 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
                style={{ borderColor: HUD_BORDER_COLOR }}
              >
                {busy === 'checking' ? 'Checking…' : 'Compatibility'}
              </button>
            )}
            <button
              disabled={(source === 'OFFLINE' ? !canRunOffline : !canRunLive) || busy !== 'idle'}
              onClick={() => runGuarded('running', async () => {
                const result = source === 'OFFLINE'
                  ? await client.runInference(selectedModelId, captureId, t0, t1, representation)
                  : await client.runInferenceLive(selectedModelId, representation);
                setRecord(result);
              })}
              className="flex-1 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40"
              style={{ borderColor: HUD_ACCENT_BRIGHT, color: HUD_ACCENT_BRIGHT }}
            >
              {busy === 'running' ? 'Running…' : source === 'LIVE' ? 'Capture live snapshot & run' : 'Run inference'}
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
              <p className="mt-1 app-muted-text">shape {shapeText(record.input_tensor_shape)}</p>
            </div>
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
      </button>
    </div>
  );
};
