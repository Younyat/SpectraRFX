import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Download, ExternalLink, Search, ShieldAlert, ShieldCheck, X } from 'lucide-react';
import { CatalogApiError, ModelCatalogClient } from '../api/catalogClient';
import type {
  CatalogEntryKind, CatalogInputRepresentation, CatalogStatus, CatalogTask, RFModelCatalogEntry,
} from '../types';

const client = new ModelCatalogClient();

const TASK_OPTIONS: CatalogTask[] = [
  'MODULATION_CLASSIFICATION', 'WIRELESS_TECHNOLOGY_CLASSIFICATION', 'RADIO_SYSTEM_IDENTIFICATION',
  'PROTOCOL_IDENTIFICATION', 'SIGNAL_DETECTION', 'WIDEBAND_SIGNAL_DETECTION', 'RF_FINGERPRINTING',
  'EMITTER_IDENTIFICATION', 'INTERFERENCE_CLASSIFICATION', 'RADAR_WAVEFORM_CLASSIFICATION',
  'UAV_RF_CLASSIFICATION', 'SPECTRUM_SENSING', 'SPECTRUM_ANOMALY_DETECTION', 'FOUNDATION_MODEL',
  'REPRESENTATION_MODEL',
];

const INPUT_OPTIONS: CatalogInputRepresentation[] = [
  'RAW_IQ', 'COMPLEX_IQ', 'IQ_FEATURES', 'SPECTROGRAM', 'WATERFALL_IMAGE', 'PSD', 'FFT',
  'CONSTELLATION', 'MEL_SPECTROGRAM', 'PREAMBLE_IQ', 'TRANSIENT_IQ', 'FEATURE_VECTOR', 'CSI', 'CIR', 'OTHER',
];

const KIND_OPTIONS: CatalogEntryKind[] = ['MODEL', 'FRAMEWORK_TOOLKIT', 'DATASET'];

const STATUS_STYLE: Record<CatalogStatus, string> = {
  READY: 'border-emerald-300 bg-emerald-50 text-emerald-700',
  CONVERTIBLE: 'border-teal-300 bg-teal-50 text-teal-700',
  CONVERSION_REQUIRED: 'border-amber-300 bg-amber-50 text-amber-700',
  PLATFORM_ADAPTER_REQUIRED: 'border-orange-300 bg-orange-50 text-orange-700',
  FOUNDATION_FINE_TUNING_REQUIRED: 'border-purple-300 bg-purple-50 text-purple-700',
  RESEARCH_MODEL: 'border-slate-300 bg-slate-50 text-slate-600',
  DATASET_ONLY: 'border-slate-300 bg-slate-50 text-slate-500',
  UNSUPPORTED: 'border-red-300 bg-red-50 text-red-700',
};

const STATUS_LABEL: Record<CatalogStatus, string> = {
  READY: 'Ready',
  CONVERTIBLE: 'Convertible',
  CONVERSION_REQUIRED: 'Conversion required',
  PLATFORM_ADAPTER_REQUIRED: 'Needs a new adapter in this plugin',
  FOUNDATION_FINE_TUNING_REQUIRED: 'Foundation / fine-tuning required',
  RESEARCH_MODEL: 'Research model',
  DATASET_ONLY: 'Dataset only',
  UNSUPPORTED: 'Unsupported',
};

interface RFModelCatalogModalProps {
  onClose: () => void;
}

// "Discover RF Models" -- replaces the old four static links (spec section
// 26: "NO quiero cuatro botones estáticos"). Two tabs: the curated,
// hand-verified seed catalog (spec section 7), and a live search against
// the public Hugging Face Hub API (spec section 13) -- the one live
// discovery source implemented so far; GitHub/Zenodo/arXiv/PapersWithCode/
// Kaggle are disclosed, not-yet-built gaps (spec sections 14-15), never
// presented as if they were covered.
export const RFModelCatalogModal: React.FC<RFModelCatalogModalProps> = ({ onClose }) => {
  const [tab, setTab] = useState<'curated' | 'huggingface'>('curated');
  const [entries, setEntries] = useState<RFModelCatalogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskFilter, setTaskFilter] = useState<CatalogTask | ''>('');
  const [inputFilter, setInputFilter] = useState<CatalogInputRepresentation | ''>('');
  const [kindFilter, setKindFilter] = useState<CatalogEntryKind | ''>('');
  const [onnxOnly, setOnnxOnly] = useState(false);
  const [hfQuery, setHfQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadCurated = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await client.listCurated({
        task: taskFilter || undefined,
        input_representation: inputFilter || undefined,
        kind: kindFilter || undefined,
        onnx_available: onnxOnly ? true : undefined,
      });
      setEntries(response.entries);
    } catch (e) {
      setError(e instanceof CatalogApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const runHuggingFaceSearch = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await client.searchHuggingFace(hfQuery, 20);
      setEntries(response.entries);
    } catch (e) {
      setError(e instanceof CatalogApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (tab === 'curated') loadCurated();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberate: only re-fetch curated on filter/tab change
  }, [tab, taskFilter, inputFilter, kindFilter, onnxOnly]);

  const filteredCount = entries.length;
  const modelCount = useMemo(() => entries.filter((entry) => entry.kind === 'MODEL').length, [entries]);

  // Portalled directly to document.body: this component is mounted deep
  // inside RF Terrain's own DOM tree, which sits alongside a WebGL
  // <canvas> (Three.js). A `position: fixed` overlay nested under that
  // tree does not reliably escape it for HIT-TESTING purposes even with a
  // high z-index -- confirmed via browser automation that the canvas was
  // intercepting pointer events at the exact coordinates of this modal's
  // own controls (elementFromPoint() returned the <canvas>, not the
  // control), which is what made the filters/checkboxes unusable. A real
  // DOM portal to <body> sidesteps the ancestor stacking context
  // entirely, matching the same fix already used by SpectrumToolsPanel's
  // tooltip for the identical class of bug.
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/60 p-4">
      <div className="flex max-h-[88vh] w-full max-w-5xl flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Discover RF Models</h2>
            <p className="text-xs text-slate-500">An open catalog of externally published RF models, frameworks, and datasets -- not four static links.</p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>

        <div className="flex gap-1 border-b border-slate-100 px-5 pt-2">
          {(['curated', 'huggingface'] as const).map((option) => (
            <button
              key={option}
              onClick={() => setTab(option)}
              className={`rounded-t-lg px-3 py-1.5 text-sm font-medium ${tab === option ? 'border border-b-0 border-slate-200 bg-white text-indigo-600' : 'text-slate-500 hover:text-slate-700'}`}
            >
              {option === 'curated' ? 'Curated catalog' : 'Search Hugging Face (live)'}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 overflow-y-auto p-5">
          {tab === 'curated' ? (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value as CatalogEntryKind | '')} className="rounded-lg border border-slate-300 px-2 py-1">
                <option value="">All kinds</option>
                {KIND_OPTIONS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
              <select value={taskFilter} onChange={(e) => setTaskFilter(e.target.value as CatalogTask | '')} className="rounded-lg border border-slate-300 px-2 py-1">
                <option value="">All tasks</option>
                {TASK_OPTIONS.map((t) => <option key={t} value={t}>{t.replaceAll('_', ' ')}</option>)}
              </select>
              <select value={inputFilter} onChange={(e) => setInputFilter(e.target.value as CatalogInputRepresentation | '')} className="rounded-lg border border-slate-300 px-2 py-1">
                <option value="">All inputs</option>
                {INPUT_OPTIONS.map((i) => <option key={i} value={i}>{i.replaceAll('_', ' ')}</option>)}
              </select>
              <label className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-2 py-1">
                <input type="checkbox" checked={onnxOnly} onChange={(e) => setOnnxOnly(e.target.checked)} />
                ONNX available
              </label>
              <span className="ml-auto text-slate-400">{filteredCount} entries · {modelCount} models</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs">
              <div className="flex flex-1 items-center gap-1.5 rounded-lg border border-slate-300 px-2 py-1.5">
                <Search className="h-3.5 w-3.5 text-slate-400" />
                <input
                  value={hfQuery}
                  onChange={(e) => setHfQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && hfQuery.trim()) runHuggingFaceSearch(); }}
                  placeholder="repo or author name fragment, e.g. rfml, lwm-spectro, torchsig..."
                  className="flex-1 text-sm outline-none"
                />
              </div>
              <button onClick={runHuggingFaceSearch} disabled={loading || !hfQuery.trim()} className="rounded-lg bg-indigo-600 px-3 py-1.5 font-semibold text-white disabled:opacity-40">
                {loading ? 'Searching…' : 'Search'}
              </button>
            </div>
          )}

          {tab === 'huggingface' && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-2.5 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
              <p>
                Live results are real (from Hugging Face's own API), but the search only matches repository/author names -- not model
                card text -- so short name fragments work far better than natural-language phrases (confirmed: "modulation
                classification" returns 0 results; "rf" or a known repo fragment returns real matches). Nothing here is individually
                reviewed -- task, input representation, and classes are unknown until you check the model card yourself. GitHub, Zenodo,
                arXiv, Papers with Code, and Kaggle are not yet covered by live search; only the curated catalog and Hugging Face are
                searched right now.
              </p>
            </div>
          )}

          {error && <div className="rounded-xl border border-red-300 bg-red-50 p-2.5 text-sm text-red-700">{error}</div>}
          {loading && entries.length === 0 && <p className="text-sm text-slate-500">Loading…</p>}
          {!loading && entries.length === 0 && !error && <p className="text-sm text-slate-500">No entries match these filters.</p>}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {entries.map((entry) => (
              <CatalogCard key={entry.id} entry={entry} expanded={expandedId === entry.id} onToggleExpand={() => setExpandedId((prev) => (prev === entry.id ? null : entry.id))} />
            ))}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
};

const CatalogCard: React.FC<{ entry: RFModelCatalogEntry; expanded: boolean; onToggleExpand: () => void }> = ({ entry, expanded, onToggleExpand }) => (
  <div className="flex flex-col gap-2 rounded-xl border border-slate-200 p-3">
    <div className="flex items-start justify-between gap-2">
      <div>
        <button onClick={onToggleExpand} className="text-left font-semibold text-slate-800 hover:text-indigo-600">{entry.name}</button>
        <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] text-slate-400">
          <span className="rounded bg-slate-100 px-1.5 py-0.5 uppercase tracking-wide">{entry.kind}</span>
          <span>{entry.provider}</span>
        </div>
      </div>
      <span className={`flex-shrink-0 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold ${STATUS_STYLE[entry.conversion_status]}`}>
        {STATUS_LABEL[entry.conversion_status]}
      </span>
    </div>

    <div className="flex flex-wrap gap-1 text-[10px]">
      {entry.task !== 'UNKNOWN' && <span className="rounded bg-indigo-50 px-1.5 py-0.5 font-medium text-indigo-700">{entry.task.replaceAll('_', ' ')}</span>}
      {entry.input_representation !== 'UNKNOWN' && <span className="rounded bg-sky-50 px-1.5 py-0.5 font-medium text-sky-700">{entry.input_representation.replaceAll('_', ' ')}</span>}
      {entry.onnx_available && <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700">ONNX</span>}
      {entry.download_url && <span className="flex items-center gap-0.5 rounded bg-indigo-50 px-1.5 py-0.5 font-medium text-indigo-700"><Download className="h-2.5 w-2.5" /> Download available</span>}
    </div>

    {entry.signal_domain && <p className="text-xs text-slate-600">{entry.signal_domain}</p>}

    {entry.classes && entry.classes.length > 0 && (
      <p className="text-[11px] text-slate-500">
        {entry.classes.length} classes: {entry.classes.slice(0, 6).join(' · ')}{entry.classes.length > 6 ? ` · +${entry.classes.length - 6} more` : ''}
      </p>
    )}

    <div className="flex items-center gap-1.5 text-[10px]">
      {entry.independently_verified ? (
        <span className="flex items-center gap-1 text-emerald-600"><ShieldCheck className="h-3 w-3" /> Independently verified</span>
      ) : (
        <span className="flex items-center gap-1 text-amber-600"><ShieldAlert className="h-3 w-3" /> Not independently verified</span>
      )}
      {entry.priority && <span className="text-slate-400">· priority: {entry.priority}</span>}
    </div>

    {expanded && (
      <div className="mt-1 flex flex-col gap-1.5 border-t border-slate-100 pt-2 text-[11px] text-slate-600">
        {entry.framework && <p><span className="font-semibold text-slate-500">Framework:</span> {entry.framework}</p>}
        {entry.original_format !== 'unknown' && <p><span className="font-semibold text-slate-500">Original format:</span> {entry.original_format}{entry.opset !== null ? ` (opset ${entry.opset})` : ''}</p>}
        {entry.preprocessing && <p><span className="font-semibold text-slate-500">Preprocessing:</span> {entry.preprocessing}</p>}
        {entry.dataset && <p><span className="font-semibold text-slate-500">Dataset:</span> {entry.dataset}</p>}
        {entry.license && <p><span className="font-semibold text-slate-500">License:</span> {entry.license}</p>}
        {entry.reported_metrics && (
          <p><span className="font-semibold text-slate-500">Reported metrics:</span> {Object.entries(entry.reported_metrics).map(([k, v]) => `${k}=${String(v)}`).join(', ')}</p>
        )}
        {entry.notes && <p className="rounded bg-slate-50 p-1.5 text-slate-500">{entry.notes}</p>}
        <div className="flex flex-wrap gap-3 pt-1">
          {entry.download_url && (
            <a
              href={entry.download_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1 font-semibold text-white hover:bg-indigo-700"
            >
              <Download className="h-3 w-3" /> Download
            </a>
          )}
          <a href={entry.source_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 font-medium text-indigo-600 hover:underline">
            Source <ExternalLink className="h-3 w-3" />
          </a>
          {entry.paper_url && (
            <a href={entry.paper_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 font-medium text-indigo-600 hover:underline">
              Paper <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
        <p className="text-slate-400">
          {entry.download_url
            ? 'Download opens the real artifact file (or, if gated/unclear, the exact file listing) directly from its host -- nothing is proxied or auto-imported through this platform.'
            : 'No direct download link could be verified for this entry -- open Source and locate the artifact yourself.'}
          {' '}Once you have a real ONNX file, use "Import .onnx model" above to bring it into this plugin.
        </p>
      </div>
    )}
  </div>
);
