import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Brain, Database, FlaskConical, History, RefreshCw, Trash2, UploadCloud } from 'lucide-react';
import { AiResearchPluginApiError, AiResearchPluginClient } from '../api/aiResearchPluginClient';
import type {
  AiPluginCaptureSummary,
  CompatibilityResult,
  InferenceRecord,
  InputRepresentation,
  RFModelManifest,
  RFTask,
} from '../types';

const client = new AiResearchPluginClient();
const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_42px_rgba(15,23,42,0.07)]';

const REPRESENTATIONS: InputRepresentation[] = ['iq_tensor', 'spectrogram', 'psd'];
const TASKS: RFTask[] = [
  'modulation_classification', 'signal_classification', 'fingerprinting',
  'anomaly_detection', 'emitter_identification', 'other',
];

const verdictColor: Record<CompatibilityResult['verdict'], string> = {
  COMPATIBLE: 'text-emerald-700 bg-emerald-50 border-emerald-300',
  PARTIALLY_COMPATIBLE: 'text-amber-700 bg-amber-50 border-amber-300',
  INCOMPATIBLE: 'text-red-700 bg-red-50 border-red-300',
  UNKNOWN: 'text-slate-600 bg-slate-50 border-slate-300',
};

const shapeText = (shape: (number | null)[] | null) => (shape ? `[${shape.map((d) => (d === null ? '?' : d)).join(', ')}]` : 'unknown');

// Experimental, entirely isolated research view (spec: "AI Model Research
// Plugin"). Talks ONLY to /api/ai-research-plugin/* -- a router that does
// not even exist unless the backend module is enabled -- and never
// imports anything from Live Monitor, RF Terrain, or any existing
// acquisition/processing code. If this file is deleted or its route
// disabled, nothing else in the platform is affected.
export const AiResearchPluginView: React.FC = () => {
  const [models, setModels] = useState<RFModelManifest[]>([]);
  const [captures, setCaptures] = useState<AiPluginCaptureSummary[]>([]);
  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);
  const [selectedCaptureId, setSelectedCaptureId] = useState<string>('');
  const [t0, setT0] = useState(0);
  const [t1, setT1] = useState(0.001);
  const [representation, setRepresentation] = useState<InputRepresentation>('iq_tensor');
  const [compatibility, setCompatibility] = useState<Record<string, CompatibilityResult>>({});
  const [results, setResults] = useState<Record<string, InferenceRecord>>({});
  const [history, setHistory] = useState<InferenceRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'idle' | 'importing' | 'checking' | 'running'>('idle');
  const [expandedModelId, setExpandedModelId] = useState<string | null>(null);

  const refreshModels = async () => setModels(await client.listModels());
  const refreshCaptures = async () => setCaptures(await client.listCaptures());
  const refreshHistory = async () => setHistory(await client.listInferenceRecords());

  useEffect(() => {
    refreshModels().catch((e) => setError(String(e)));
    refreshCaptures().catch((e) => setError(String(e)));
    refreshHistory().catch((e) => setError(String(e)));
  }, []);

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
      await client.importModel(file);
      await refreshModels();
    });

  const handleCheckCompatibility = () =>
    runGuarded('checking', async () => {
      const entries = await Promise.all(
        selectedModelIds.map(async (modelId) => [modelId, await client.checkCompatibility(modelId, selectedCaptureId, t0, t1, representation)] as const),
      );
      setCompatibility(Object.fromEntries(entries));
    });

  const handleRunInference = () =>
    runGuarded('running', async () => {
      const entries = await Promise.all(
        selectedModelIds.map(async (modelId) => [modelId, await client.runInference(modelId, selectedCaptureId, t0, t1, representation)] as const),
      );
      setResults(Object.fromEntries(entries));
      await refreshHistory();
    });

  const toggleModelSelection = (modelId: string) =>
    setSelectedModelIds((prev) => (prev.includes(modelId) ? prev.filter((id) => id !== modelId) : [...prev, modelId]));

  const canRun = selectedModelIds.length > 0 && selectedCaptureId !== '' && t1 > t0;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center gap-3">
        <FlaskConical className="h-7 w-7 text-indigo-600" />
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">AI Model Research Plugin</h1>
          <p className="text-sm text-slate-500">Import a pretrained ONNX model and study what it extracts from real, preserved RF captures. Experimental -- entirely separate from every existing detection/classification path.</p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <p>Nothing here is a validated detector. A prediction only reflects the imported model's own training -- it is never automatically presented as confirmed protocol/device identification. Only ONNX models are supported in this phase; PyTorch/TorchScript and TensorFlow are documented, not-yet-implemented gaps.</p>
      </div>

      {error && <div className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Models */}
      <section className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800"><Brain className="h-5 w-5" /> Models</h2>
          <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <UploadCloud className="h-4 w-4" />
            {busy === 'importing' ? 'Importing…' : 'Import .onnx model'}
            <input
              type="file"
              accept=".onnx"
              className="hidden"
              disabled={busy === 'importing'}
              onChange={(event) => { const file = event.target.files?.[0]; if (file) handleImport(file); event.target.value = ''; }}
            />
          </label>
        </div>

        {models.length === 0 && <p className="text-sm text-slate-500">No models imported yet.</p>}

        <div className="flex flex-col gap-2">
          {models.map((model) => (
            <ModelRow
              key={model.model_id}
              model={model}
              selected={selectedModelIds.includes(model.model_id)}
              expanded={expandedModelId === model.model_id}
              onToggleSelect={() => toggleModelSelection(model.model_id)}
              onToggleExpand={() => setExpandedModelId((prev) => (prev === model.model_id ? null : model.model_id))}
              onDelete={() => runGuarded('idle', async () => { await client.deleteModel(model.model_id); await refreshModels(); })}
              onSaveOverrides={async (overrides) => { await client.updateModel(model.model_id, overrides); await refreshModels(); }}
            />
          ))}
        </div>
      </section>

      {/* Capture + region + representation */}
      <section className={card}>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-800"><Database className="h-5 w-5" /> Capture &amp; region</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Capture
            <select value={selectedCaptureId} onChange={(e) => setSelectedCaptureId(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
              <option value="">Select…</option>
              {captures.map((c) => <option key={c.capture_id} value={c.capture_id}>{c.capture_id}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            t0 (s)
            <input type="number" step={0.0001} value={t0} onChange={(e) => setT0(Number(e.target.value))} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            t1 (s)
            <input type="number" step={0.0001} value={t1} onChange={(e) => setT1(Number(e.target.value))} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Representation
            <select value={representation} onChange={(e) => setRepresentation(e.target.value as InputRepresentation)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
              {REPRESENTATIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
        </div>
        <button onClick={refreshCaptures} className="mt-2 flex items-center gap-1 text-xs text-indigo-600 hover:underline"><RefreshCw className="h-3 w-3" /> Refresh captures</button>

        <div className="mt-4 flex gap-2">
          <button disabled={!canRun || busy !== 'idle'} onClick={handleCheckCompatibility} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40">
            {busy === 'checking' ? 'Checking…' : 'Check compatibility'}
          </button>
          <button disabled={!canRun || busy !== 'idle'} onClick={handleRunInference} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
            {busy === 'running' ? 'Running…' : `Run inference (${selectedModelIds.length} model${selectedModelIds.length === 1 ? '' : 's'})`}
          </button>
        </div>
      </section>

      {/* Results: compatibility + interpretation, kept visually separate (spec section 12) */}
      {selectedModelIds.length > 0 && (Object.keys(compatibility).length > 0 || Object.keys(results).length > 0) && (
        <section className={card}>
          <h2 className="mb-3 text-lg font-semibold text-slate-800">Results (same RF region, per model)</h2>
          <div className="flex flex-col gap-4">
            {selectedModelIds.map((modelId) => {
              const model = models.find((m) => m.model_id === modelId);
              const compat = compatibility[modelId];
              const record = results[modelId];
              return (
                <div key={modelId} className="rounded-xl border border-slate-200 p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-medium text-slate-800">{model?.model_name ?? modelId}</span>
                    {compat && <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${verdictColor[compat.verdict]}`}>{compat.verdict}</span>}
                  </div>

                  {compat && (
                    <table className="mb-3 w-full text-xs">
                      <tbody>
                        {compat.checks.map((check) => (
                          <tr key={check.field} className="border-t border-slate-100">
                            <td className="py-1 pr-2 text-slate-500">{check.field}</td>
                            <td className="py-1 pr-2 font-mono">{JSON.stringify(check.capture_value)}</td>
                            <td className="py-1 pr-2 font-mono">{JSON.stringify(check.model_value)}</td>
                            <td className="py-1">{check.matched === null ? '—' : check.matched ? '✓' : '✕'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}

                  {record && (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <div className="rounded-lg bg-slate-50 p-2">
                        <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">Raw output</div>
                        <p className="break-all font-mono text-[11px] text-slate-700">[{record.raw_output.map((v) => v.toFixed(3)).join(', ')}]</p>
                      </div>
                      <div className="rounded-lg bg-slate-50 p-2">
                        <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">Interpretation</div>
                        {record.interpretation.kind === 'classification' ? (
                          <p className="text-[11px] text-slate-700">
                            <strong>{record.interpretation.predicted_class}</strong> ({record.interpretation.score_type}={record.interpretation.score?.toFixed(3)})
                          </p>
                        ) : record.interpretation.kind === 'embedding' ? (
                          <p className="text-[11px] text-slate-700">embedding, dim={record.interpretation.dimensionality}, ‖z‖={record.interpretation.l2_norm?.toFixed(3)}</p>
                        ) : (
                          <p className="text-[11px] text-slate-500">not automatically interpretable</p>
                        )}
                        {record.interpretation.warning && <p className="mt-1 text-[10px] text-amber-600">{record.interpretation.warning}</p>}
                      </div>
                      <div className="rounded-lg bg-slate-50 p-2">
                        <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">RF evidence</div>
                        <p className="text-[11px] text-slate-700">{record.capture_id}<br />t=[{record.selected_time_seconds[0].toFixed(6)}, {record.selected_time_seconds[1].toFixed(6)}]s<br />{record.input_transformation}, shape {shapeText(record.input_tensor_shape)}</p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* History */}
      <section className={card}>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-800"><History className="h-5 w-5" /> Inference history ({history.length})</h2>
        {history.length === 0 && <p className="text-sm text-slate-500">No inference runs yet.</p>}
        <div className="flex flex-col gap-1">
          {history.slice(0, 20).map((record) => (
            <div key={record.record_id} className="flex items-center justify-between rounded-lg border border-slate-100 px-2 py-1 text-xs text-slate-600">
              <span className="font-mono">{record.record_id}</span>
              <span>{record.model_manifest_snapshot.model_name}</span>
              <span>{record.capture_id}</span>
              <span>{record.interpretation.kind === 'classification' ? record.interpretation.predicted_class : record.interpretation.kind}</span>
              <span>{record.inference_timestamp_utc}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};

interface ModelRowProps {
  model: RFModelManifest;
  selected: boolean;
  expanded: boolean;
  onToggleSelect: () => void;
  onToggleExpand: () => void;
  onDelete: () => void;
  onSaveOverrides: (overrides: { task?: RFTask; input_overrides?: Record<string, unknown>; output_overrides?: Record<string, unknown> }) => Promise<void>;
}

const ModelRow: React.FC<ModelRowProps> = ({ model, selected, expanded, onToggleSelect, onToggleExpand, onDelete, onSaveOverrides }) => {
  const [task, setTask] = useState<RFTask>(model.task);
  const [sampleRate, setSampleRate] = useState(model.input_overrides.sample_rate_hz ?? '');
  const [classes, setClasses] = useState((model.output_overrides.classes ?? model.output_discovered.classes ?? []).join(', '));
  const [saving, setSaving] = useState(false);

  const effectiveInput = useMemo(() => ({ ...model.input_discovered, ...Object.fromEntries(Object.entries(model.input_overrides).filter(([, v]) => v !== null)) }), [model]);
  const effectiveOutput = useMemo(() => ({ ...model.output_discovered, ...Object.fromEntries(Object.entries(model.output_overrides).filter(([, v]) => v !== null)) }), [model]);

  return (
    <div className="rounded-xl border border-slate-200">
      <div className="flex items-center gap-3 px-3 py-2">
        <input type="checkbox" checked={selected} onChange={onToggleSelect} />
        <button onClick={onToggleExpand} className="flex-1 text-left">
          <span className="font-medium text-slate-800">{model.model_name}</span>
          <span className="ml-2 text-xs text-slate-400">{model.framework} · {shapeText(effectiveInput.tensor_shape)} → {shapeText(effectiveOutput.tensor_shape)}</span>
        </button>
        <button onClick={onDelete} title="Delete model" className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 p-3 text-xs">
          <div className="mb-3 grid grid-cols-2 gap-3">
            <div>
              <div className="mb-1 font-semibold text-slate-500">Discovered (real, from the ONNX graph)</div>
              <p>representation: {model.input_discovered.representation ?? 'unknown'}</p>
              <p>tensor_shape: {shapeText(model.input_discovered.tensor_shape)}</p>
              <p>dtype: {model.input_discovered.dtype ?? 'unknown'}</p>
              <p>output tensor_shape: {shapeText(model.output_discovered.tensor_shape)}</p>
              <p>output_type (heuristic): {model.output_discovered.output_type ?? 'unknown'}</p>
            </div>
            <div>
              <div className="mb-1 font-semibold text-slate-500">Your overrides (never inferred, never inventable)</div>
              <label className="flex flex-col gap-1">
                Task
                <select value={task} onChange={(e) => setTask(e.target.value as RFTask)} className="rounded border border-slate-300 px-1 py-0.5">
                  {TASKS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label className="mt-1 flex flex-col gap-1">
                Sample rate (Hz)
                <input value={sampleRate} onChange={(e) => setSampleRate(e.target.value === '' ? '' : Number(e.target.value))} className="rounded border border-slate-300 px-1 py-0.5" />
              </label>
              <label className="mt-1 flex flex-col gap-1">
                Classes (comma-separated, in output order)
                <input value={classes} onChange={(e) => setClasses(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5" />
              </label>
              <button
                disabled={saving}
                onClick={async () => {
                  setSaving(true);
                  try {
                    await onSaveOverrides({
                      task,
                      input_overrides: sampleRate === '' ? {} : { sample_rate_hz: sampleRate },
                      output_overrides: classes.trim() === '' ? {} : { classes: classes.split(',').map((c) => c.trim()).filter(Boolean) },
                    });
                  } finally {
                    setSaving(false);
                  }
                }}
                className="mt-2 rounded bg-indigo-600 px-2 py-1 text-white disabled:opacity-40"
              >
                {saving ? 'Saving…' : 'Save overrides'}
              </button>
            </div>
          </div>
          {model.provenance.paper && <p className="text-slate-500">Paper: {model.provenance.paper}</p>}
        </div>
      )}
    </div>
  );
};
