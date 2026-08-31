import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  AlertTriangle, Award, CheckCircle2, ChevronDown, ChevronRight, Clock,
  Database, DatabaseZap, Download, FlaskConical, FolderOpen, Loader2, Play,
  Plus, Radio, RefreshCw, Settings2, Trash2, Trophy, Upload, Zap,
} from 'lucide-react';
import { cn } from '../../shared/utils';

const API = '/api/e6';

type Tab = 'datasets' | 'local-builder' | 'training' | 'models' | 'predict';

interface E6Health { sklearn_available: boolean; joblib_available: boolean; feature_count: number; supported_models: string[]; supported_external_sources: string[] }
interface DatasetSummary { dataset_name: string; dataset_type: string; source: string; task: string; signal_family: string; dtype: string; capture_count: number; label_count: number; labels: string[]; label_counts: Record<string, number>; created_at: string; updated_at: string; environment?: string }
interface ModelEntry { model_id: string; model_name: string; algorithm: string; task: string; dataset_name: string; classes: string[]; class_count: number; window_size: number; dtype: string; metrics: { accuracy?: number; macro_f1?: number; balanced_accuracy?: number }; enabled_for_live: boolean; registered_at: string; model_path: string }
interface TrainResult { model_id: string; model_kind: string; dataset_name: string; metrics: { accuracy: number; macro_f1: number; balanced_accuracy: number; weighted_f1: number; class_count?: number; train_windows: number; test_windows: number; model_size_bytes: number; train_time_ms: number; inference_time_ms?: number; windows_total?: number }; classes: string[]; window_size: number; window_strategy: string; windows_per_file: number; feature_extractor_version: string; dataset_iq_size_bytes: number }
interface BenchmarkRow { rank: number; model_kind: string; model_id: string; accuracy: number; macro_f1: number; balanced_accuracy: number; weighted_f1: number; correct: number; failed: number; total_test: number; train_time_ms: number; model_size_bytes: number; dataset_iq_size_bytes: number }
interface BenchmarkResult { dataset_name: string; task: string; results: BenchmarkRow[]; errors: { model_kind: string; error: string }[]; best_model: string; benchmark_at: string; total_trained: number }
interface PredictResult { model_id: string; task: string; prediction: string; confidence: number; top_k: { label: string; probability: number }[]; inference_time_ms: number; warning?: string }
interface ScannedModel { file_name: string; file_path: string; size_mb: number; algorithm: string; dataset_name: string; already_registered: boolean }
interface ScanResult { record_count: number; label_count: number; total_data_gb: number }
interface JobStep { progress: number; message: string; t: number }
interface JobStatus {
  job_id: string; operation: string; description: string;
  status: 'running' | 'done' | 'error';
  progress: number; message: string;
  result: unknown; error: string | null;
  started_at: number; finished_at: number | null; elapsed_s: number | null;
  steps: JobStep[];
  current_model?: string | null; model_index?: number | null; total_models?: number | null;
}

// ── Job polling hook ────────────────────────────────────────────────────────

function useJobPoller(jobId: string | null, onDone?: (job: JobStatus) => void) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!jobId) { setJob(null); return; }
    let active = true;
    const poll = async () => {
      try {
        const r = await axios.get(`${API}/jobs/${jobId}`);
        const j: JobStatus = r.data.data;
        if (!active) return;
        setJob(j);
        if (j.status !== 'running') {
          if (intervalRef.current) clearInterval(intervalRef.current);
          if (onDoneRef.current) onDoneRef.current(j);
        }
      } catch { /* ignore poll errors */ }
    };
    poll();
    intervalRef.current = setInterval(poll, 800);
    return () => { active = false; if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [jobId]);

  return job;
}

// ── Shared UI helpers ────────────────────────────────────────────────────────

function useE6Api<T>(endpoint: string, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetch = useCallback(async () => {
    setLoading(true); setError(null);
    try { const r = await axios.get(`${API}${endpoint}`); setData(r.data.data); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : 'Request failed'); }
    finally { setLoading(false); }
  }, deps);
  return { data, loading, error, fetch };
}

function Badge({ label, variant = 'neutral' }: { label: string; variant?: 'green' | 'amber' | 'red' | 'neutral' | 'blue' }) {
  return (
    <span className={cn('inline-block rounded-full px-2 py-0.5 text-xs font-medium', {
      'bg-emerald-500/15 text-emerald-400': variant === 'green',
      'bg-amber-500/15 text-amber-400': variant === 'amber',
      'bg-red-500/15 text-red-400': variant === 'red',
      'bg-slate-500/15 text-slate-400': variant === 'neutral',
      'bg-blue-500/15 text-blue-400': variant === 'blue',
    })}>
      {label}
    </span>
  );
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('rounded-2xl border p-4', className)} style={{ background: 'var(--app-surface)', borderColor: 'var(--app-border)' }}>{children}</div>;
}

function SectionTitle({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-amber-400" />
      <h3 className="font-semibold text-sm">{title}</h3>
    </div>
  );
}

// ── Job progress bar ─────────────────────────────────────────────────────────

function JobProgressBar({ job }: { job: JobStatus }) {
  const isDone = job.status === 'done';
  const isError = job.status === 'error';
  const barColor = isError ? '#ef4444' : isDone ? '#10b981' : '#22c55e';
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className={cn('font-medium truncate max-w-xs', isError ? 'text-red-400' : isDone ? 'text-emerald-400' : 'text-amber-300')}>
          {isError ? `Error: ${job.error}` : job.message}
        </span>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          {job.current_model && <span className="app-muted-text">{job.current_model} ({job.model_index}/{job.total_models})</span>}
          {job.elapsed_s != null && (
            <span className="app-muted-text flex items-center gap-1"><Clock className="w-3 h-3" />{job.elapsed_s}s</span>
          )}
        </div>
      </div>
      <div className="relative w-full rounded-full h-4 overflow-hidden" style={{ background: 'var(--app-surface-strong)' }}>
        <div className="h-full rounded-full transition-all duration-300 ease-out"
          style={{ width: `${job.progress}%`, background: barColor }} />
        <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-white mix-blend-luminosity">
          {job.progress}%
        </span>
      </div>
    </div>
  );
}

// ── Job audit card ───────────────────────────────────────────────────────────

function fmtBytes(n: number | null | undefined): string {
  if (n == null || n === 0) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + ' GB';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + ' MB';
  return (n / 1024).toFixed(0) + ' KB';
}

function JobAuditCard({ job }: { job: JobStatus }) {
  const [showSteps, setShowSteps] = useState(false);
  if (job.status === 'error') {
    return (
      <Card>
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="font-semibold text-sm">Operation Failed</span>
        </div>
        <div className="text-xs bg-red-500/10 rounded-xl px-3 py-2">{job.error}</div>
      </Card>
    );
  }
  if (job.status !== 'done') return null;

  const r = job.result as TrainResult | null;
  if (!r) return null;

  const m = r.metrics || {};
  const modelMB = m.model_size_bytes ? (m.model_size_bytes / 1_000_000).toFixed(2) : null;
  const iqGB = r.dataset_iq_size_bytes ? fmtBytes(r.dataset_iq_size_bytes) : null;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        <span className="font-semibold text-sm">{r.model_id || r.model_kind}</span>
        <Badge label="done" variant="green" />
      </div>

      {/* Weight + IQ size bar */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="rounded-xl p-2.5 text-center" style={{ background: 'var(--app-surface-strong)' }}>
          <div className="text-base font-bold text-amber-400">{modelMB ? `${modelMB} MB` : '—'}</div>
          <div className="text-xs app-muted-text mt-0.5">model weight</div>
        </div>
        <div className="rounded-xl p-2.5 text-center" style={{ background: 'var(--app-surface-strong)' }}>
          <div className="text-base font-bold text-amber-400">{iqGB || '—'}</div>
          <div className="text-xs app-muted-text mt-0.5">dataset IQ used</div>
        </div>
      </div>

      {/* Core metrics */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        {[
          ['accuracy', m.accuracy],
          ['macro F1', m.macro_f1],
          ['balanced acc', m.balanced_accuracy],
        ].map(([k, v]) => (
          <div key={String(k)} className="rounded-xl p-2 text-center" style={{ background: 'var(--app-surface-strong)' }}>
            <div className="text-base font-bold text-amber-400">{v != null ? (Number(v) * 100).toFixed(1) + '%' : '—'}</div>
            <div className="text-xs app-muted-text">{k}</div>
          </div>
        ))}
      </div>

      {/* Secondary info */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs app-muted-text mb-3">
        {m.train_windows != null && <span>train windows: <strong className="text-white/70">{m.train_windows.toLocaleString()}</strong></span>}
        {m.test_windows != null && <span>test windows: <strong className="text-white/70">{m.test_windows.toLocaleString()}</strong></span>}
        {m.windows_total != null && <span>total windows: <strong className="text-white/70">{m.windows_total.toLocaleString()}</strong></span>}
        {m.train_time_ms != null && <span>train time: <strong className="text-white/70">{(m.train_time_ms / 1000).toFixed(1)}s</strong></span>}
        {m.inference_time_ms != null && <span>infer/window: <strong className="text-white/70">{m.inference_time_ms.toFixed(2)}ms</strong></span>}
        {r.window_size && <span>window size: <strong className="text-white/70">{r.window_size}</strong></span>}
        {r.window_strategy && <span>strategy: <strong className="text-white/70">{r.window_strategy}</strong></span>}
        {r.dataset_name && <span>dataset: <strong className="text-white/70">{r.dataset_name}</strong></span>}
        {r.feature_extractor_version && <span>extractor: <strong className="text-white/70">v{r.feature_extractor_version}</strong></span>}
        {job.elapsed_s != null && <span>total elapsed: <strong className="text-white/70">{job.elapsed_s}s</strong></span>}
      </div>

      {r.classes && r.classes.length > 0 && (
        <div className="text-xs app-muted-text mb-3">
          classes: {r.classes.slice(0, 10).join(' · ')}{r.classes.length > 10 ? ` +${r.classes.length - 10}` : ''}
        </div>
      )}

      {/* Step log */}
      {job.steps && job.steps.length > 0 && (
        <div>
          <button onClick={() => setShowSteps(s => !s)}
            className="flex items-center gap-1 text-xs app-muted-text hover:text-white transition-colors">
            {showSteps ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Step log ({job.steps.length} steps)
          </button>
          {showSteps && (
            <div className="mt-2 space-y-0.5 max-h-40 overflow-y-auto">
              {job.steps.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <span className="text-amber-400 w-7 text-right flex-shrink-0">{s.progress}%</span>
                  <span className="app-muted-text w-10 flex-shrink-0">{s.t.toFixed(1)}s</span>
                  <span className="truncate">{s.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function DatasetSelect({ value, onChange, placeholder = 'Select dataset…' }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const { data: datasets, fetch } = useE6Api<DatasetSummary[]>('/datasets');
  useEffect(() => { fetch(); }, []);
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className="w-full rounded-xl border px-3 py-2 text-sm"
      style={{ background: 'var(--app-surface-strong)', borderColor: 'var(--app-border)', color: value ? 'var(--app-text)' : 'var(--app-muted)' }}>
      <option value="">{placeholder}</option>
      {(datasets || []).map(ds => (
        <option key={ds.dataset_name} value={ds.dataset_name}>
          {ds.dataset_name} ({ds.capture_count} captures · {ds.label_count} classes)
        </option>
      ))}
    </select>
  );
}

function iStyle() { return { background: 'var(--app-surface-strong)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }; }
function iCls(extra = '') { return `w-full rounded-xl border px-3 py-2 text-sm ${extra}`; }
function StatusMsg({ s }: { s: { ok: boolean; msg: string } | null }) {
  if (!s) return null;
  return <div className={cn('mt-2 rounded-xl px-3 py-2 text-xs', s.ok ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400')}>{s.msg}</div>;
}

// ── Datasets panel ─────────────────────────────────────────────────────────

function DatasetsPanel({ health }: { health: E6Health | null }) {
  const { data: datasets, loading, fetch } = useE6Api<DatasetSummary[]>('/datasets');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [importForm, setImportForm] = useState({ source_type: 'kri_wifi', source_root: '', dataset_name: '', ieee_target: 'auto' });
  const [importPct, setImportPct] = useState(100);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const [importStatus, setImportStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => { fetch(); }, []);

  const importJob = useJobPoller(importJobId, job => {
    if (job.status === 'done') {
      const d = job.result as { captures_imported?: number; label_count?: number } | null;
      setImportStatus({ ok: true, msg: d ? `Imported ${d.captures_imported} captures · ${d.label_count} classes` : 'Import complete' });
      fetch();
    } else if (job.status === 'error') {
      setImportStatus({ ok: false, msg: job.error || 'Import failed' });
    }
  });

  const effectiveFiles = scanResult ? Math.max(1, Math.round(scanResult.record_count * importPct / 100)) : null;

  const handleScan = async () => {
    setScanning(true); setScanResult(null); setImportStatus(null);
    try {
      const r = await axios.post(`${API}/datasets/scan-external`, {
        source_type: importForm.source_type, source_root: importForm.source_root, ieee_target: importForm.ieee_target,
      });
      setScanResult(r.data.data);
    } catch (e: unknown) {
      setImportStatus({ ok: false, msg: e instanceof Error ? e.message : 'Scan failed' });
    } finally { setScanning(false); }
  };

  const handleImport = async () => {
    setImportStatus(null); setImportJobId(null);
    try {
      const payload: Record<string, unknown> = {
        source_type: importForm.source_type, source_root: importForm.source_root,
        dataset_name: importForm.dataset_name || importForm.source_type, ieee_target: importForm.ieee_target,
      };
      if (importPct < 100 && scanResult) payload.import_percentage = importPct / 100;
      const r = await axios.post(`${API}/datasets/import-external`, payload);
      const jobId: string | undefined = r.data.data?.job_id;
      if (jobId) {
        setImportJobId(jobId);
      } else {
        // Fallback: direct result (non-async path)
        const d = r.data.data;
        setImportStatus({ ok: true, msg: `Imported ${d.captures_imported} captures · ${d.label_count} classes` });
        fetch();
      }
    } catch (e: unknown) {
      setImportStatus({ ok: false, msg: e instanceof Error ? e.message : 'Import failed' });
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete dataset "${name}"?`)) return;
    await axios.delete(`${API}/datasets/${name}`); fetch();
  };

  const sources = health?.supported_external_sources || [];
  const isImporting = importJob?.status === 'running';

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle icon={Download} title="Import External Dataset" />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <label className="text-xs app-muted-text mb-1 block">Source type</label>
            <select value={importForm.source_type}
              onChange={e => { setImportForm(f => ({ ...f, source_type: e.target.value })); setScanResult(null); }}
              className={iCls()} style={iStyle()}>
              {sources.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs app-muted-text mb-1 block">Dataset name (storage key)</label>
            <input value={importForm.dataset_name}
              onChange={e => setImportForm(f => ({ ...f, dataset_name: e.target.value }))}
              placeholder={importForm.source_type} className={iCls()} style={iStyle()} />
          </div>
          <div className="sm:col-span-2">
            <label className="text-xs app-muted-text mb-1 block">Source root path</label>
            <div className="flex gap-2">
              <input value={importForm.source_root}
                onChange={e => { setImportForm(f => ({ ...f, source_root: e.target.value })); setScanResult(null); }}
                placeholder="C:\Users\Usuario\Desktop\NICS\datasets\rf oracle\…"
                className={iCls('flex-1 font-mono')} style={iStyle()} />
              <button onClick={handleScan} disabled={scanning || !importForm.source_root}
                className="flex items-center gap-1.5 rounded-xl border px-3 py-2 text-sm font-medium disabled:opacity-50 hover:bg-white/5 whitespace-nowrap"
                style={{ borderColor: 'var(--app-border)' }}>
                {scanning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FolderOpen className="w-3.5 h-3.5 text-amber-400" />}
                Scan
              </button>
            </div>
          </div>

          {scanResult && (
            <div className="sm:col-span-2 rounded-xl p-3 space-y-2" style={{ background: 'var(--app-surface-strong)' }}>
              <div className="flex items-center justify-between text-xs">
                <span className="text-emerald-400 font-medium">
                  {scanResult.record_count} files · {scanResult.label_count} classes · {scanResult.total_data_gb.toFixed(2)} GB
                </span>
                <span className="app-muted-text">{effectiveFiles} files at {importPct}%</span>
              </div>
              <input type="range" min={10} max={100} step={5} value={importPct}
                onChange={e => setImportPct(Number(e.target.value))}
                className="w-full accent-amber-400" />
              <div className="flex justify-between text-xs app-muted-text">
                <span>10%</span>
                <span className="font-semibold text-amber-400">{importPct}% → {effectiveFiles} files
                  {scanResult.total_data_gb > 0 ? ` (~${(scanResult.total_data_gb * importPct / 100).toFixed(2)} GB)` : ''}</span>
                <span>100%</span>
              </div>
            </div>
          )}

          <div className={scanResult ? 'sm:col-span-1' : 'sm:col-span-2'}>
            <button onClick={handleImport} disabled={isImporting || !importForm.source_root}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
              {isImporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              {isImporting ? 'Importing…' : scanResult && importPct < 100 ? `Import ${importPct}% (${effectiveFiles} files)` : 'Import'}
            </button>
          </div>
        </div>

        {importJob && importJob.status === 'running' && (
          <div className="mt-3">
            <JobProgressBar job={importJob} />
          </div>
        )}
        <StatusMsg s={importStatus} />
      </Card>

      <Card>
        <div className="flex items-center justify-between mb-3">
          <SectionTitle icon={Database} title="E6 Datasets" />
          <button onClick={fetch} disabled={loading} className="rounded-lg p-1.5 hover:bg-white/5">
            <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
          </button>
        </div>
        {!datasets || datasets.length === 0 ? (
          <div className="text-center text-sm app-muted-text py-6">No datasets yet.</div>
        ) : (
          <div className="space-y-2">
            {datasets.map(ds => (
              <div key={ds.dataset_name} className="rounded-xl border" style={{ borderColor: 'var(--app-border)' }}>
                <button onClick={() => setExpanded(expanded === ds.dataset_name ? null : ds.dataset_name)}
                  className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-white/5 rounded-xl">
                  <div className="flex items-center gap-2.5">
                    {expanded === ds.dataset_name ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    <span className="font-medium text-sm">{ds.dataset_name}</span>
                    <Badge label={ds.dataset_type} variant={ds.dataset_type === 'local' ? 'green' : 'amber'} />
                    <Badge label={ds.task.replace(/_/g, ' ')} variant="blue" />
                  </div>
                  <div className="flex items-center gap-3 text-xs app-muted-text">
                    <span>{ds.capture_count} captures · {ds.label_count} classes</span>
                    <button onClick={e => { e.stopPropagation(); handleDelete(ds.dataset_name); }}
                      className="rounded-lg p-1 text-red-400 hover:bg-red-500/10"><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </button>
                {expanded === ds.dataset_name && (
                  <div className="px-3 pb-3 border-t" style={{ borderColor: 'var(--app-border)' }}>
                    <div className="mt-2 grid grid-cols-2 gap-1 text-xs">
                      {Object.entries(ds.label_counts || {}).map(([lbl, cnt]) => (
                        <div key={lbl} className="flex justify-between rounded-lg px-2 py-1" style={{ background: 'var(--app-surface-strong)' }}>
                          <span className="truncate font-mono">{lbl}</span>
                          <span className="ml-2 text-amber-400">{cnt}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 text-xs app-muted-text">dtype: {ds.dtype} · signal: {ds.signal_family || '—'} · env: {ds.environment || 'lab'}</div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Local dataset builder panel ────────────────────────────────────────────

function LocalBuilderPanel() {
  const [form, setForm] = useState({
    dataset_name: '', task: 'device_fingerprinting', signal_family: '', protocol: '',
    dtype: 'cf32', receiver_model: 'USRP B200', antenna: 'RX2', environment: 'lab',
    center_frequency_hz: '', sample_rate_hz: '', gain_db: '', notes: '',
  });
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [addForm, setAddForm] = useState({ dataset_name: '', iq_path: '', label: '', session_id: '', notes: '' });
  const [addStatus, setAddStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [captureMode, setCaptureMode] = useState<'path' | 'upload'>('path');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [splitForm, setSplitForm] = useState({ dataset_name: '', train_ratio: '0.70', val_ratio: '0.15', seed: '42' });
  const [splitStatus, setSplitStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const createDataset = async () => {
    setBusy(true); setStatus(null);
    try {
      await axios.post(`${API}/datasets/create-local`, {
        ...form,
        center_frequency_hz: form.center_frequency_hz ? parseFloat(form.center_frequency_hz) : null,
        sample_rate_hz: form.sample_rate_hz ? parseFloat(form.sample_rate_hz) : null,
        gain_db: form.gain_db ? parseFloat(form.gain_db) : null,
      });
      setStatus({ ok: true, msg: `Dataset "${form.dataset_name}" created` });
    } catch (e: unknown) { setStatus({ ok: false, msg: e instanceof Error ? e.message : 'Create failed' }); }
    finally { setBusy(false); }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setAddStatus(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await axios.post(`${API}/files/upload`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      const savedPath: string = r.data.data.saved_path;
      setAddForm(f => ({ ...f, iq_path: savedPath }));
      setAddStatus({ ok: true, msg: `Uploaded: ${r.data.data.filename} (${(r.data.data.size_bytes / 1024).toFixed(1)} KB)` });
    } catch (err: unknown) {
      setAddStatus({ ok: false, msg: err instanceof Error ? err.message : 'Upload failed' });
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  };

  const addCapture = async () => {
    setBusy(true); setAddStatus(null);
    try {
      const r = await axios.post(`${API}/datasets/add-capture`, addForm);
      setAddStatus({ ok: true, msg: `Capture added. Total: ${r.data.data.total_captures}` });
    } catch (e: unknown) { setAddStatus({ ok: false, msg: e instanceof Error ? e.message : 'Add failed' }); }
    finally { setBusy(false); }
  };

  const buildSplits = async () => {
    setBusy(true); setSplitStatus(null);
    try {
      const r = await axios.post(`${API}/datasets/build-splits`, {
        dataset_name: splitForm.dataset_name,
        train_ratio: parseFloat(splitForm.train_ratio),
        val_ratio: parseFloat(splitForm.val_ratio),
        seed: parseInt(splitForm.seed),
      });
      const sp = r.data.data.splits;
      setSplitStatus({ ok: true, msg: `train=${sp.train?.length ?? 0} · val=${sp.validation?.length ?? 0} · test=${sp.test?.length ?? 0}` });
    } catch (e: unknown) { setSplitStatus({ ok: false, msg: e instanceof Error ? e.message : 'Split failed' }); }
    finally { setBusy(false); }
  };

  const field = (label: string, key: keyof typeof form, placeholder = '') => (
    <div>
      <label className="text-xs app-muted-text mb-1 block">{label}</label>
      <input value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
        placeholder={placeholder} className={iCls()} style={iStyle()} />
    </div>
  );

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle icon={Plus} title="Create Local Dataset" />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {field('Dataset name *', 'dataset_name', 'local_wifi_lab')}
          <div>
            <label className="text-xs app-muted-text mb-1 block">Task</label>
            <select value={form.task} onChange={e => setForm(f => ({ ...f, task: e.target.value }))} className={iCls()} style={iStyle()}>
              <option value="device_fingerprinting">Device Fingerprinting</option>
              <option value="signal_recognition">Signal Recognition</option>
              <option value="open_set_detection">Open-Set Detection</option>
            </select>
          </div>
          {field('Signal family', 'signal_family', 'wifi / ble / zigbee / uav')}
          {field('Protocol', 'protocol', 'ieee80211 / lightbridge')}
          {field('Center frequency (Hz)', 'center_frequency_hz', '2412000000')}
          {field('Sample rate (Hz)', 'sample_rate_hz', '5000000')}
          {field('Gain (dB)', 'gain_db', '40')}
          {field('Receiver model', 'receiver_model', 'USRP B200')}
          {field('Antenna', 'antenna', 'RX2')}
          {field('Environment', 'environment', 'lab / outdoor / office')}
          <div>
            <label className="text-xs app-muted-text mb-1 block">IQ dtype</label>
            <select value={form.dtype} onChange={e => setForm(f => ({ ...f, dtype: e.target.value }))} className={iCls()} style={iStyle()}>
              <option value="cf32">cf32 (complex float32)</option>
              <option value="cf16_le">cf16_le (float16 little-endian)</option>
              <option value="cf32_le">cf32_le</option>
            </select>
          </div>
          {field('Notes', 'notes', 'optional')}
        </div>
        <button onClick={createDataset} disabled={busy || !form.dataset_name}
          className="mt-3 flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}Create Dataset
        </button>
        <StatusMsg s={status} />
      </Card>

      <Card>
        <SectionTitle icon={FolderOpen} title="Add Capture to Local Dataset" />
        <div className="flex gap-1 mb-3 rounded-xl p-1" style={{ background: 'var(--app-surface-strong)' }}>
          {(['path', 'upload'] as const).map(m => (
            <button key={m} onClick={() => setCaptureMode(m)}
              className={cn('flex-1 rounded-lg py-1.5 text-xs font-medium transition-colors',
                captureMode === m ? 'bg-amber-500 text-slate-900' : 'app-muted-text hover:text-white')}>
              {m === 'path' ? 'Enter Path' : 'Upload File'}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <label className="text-xs app-muted-text mb-1 block">Dataset name</label>
            <DatasetSelect value={addForm.dataset_name} onChange={v => setAddForm(f => ({ ...f, dataset_name: v }))} />
          </div>
          <div>
            <label className="text-xs app-muted-text mb-1 block">Label (class / device ID)</label>
            <input value={addForm.label} onChange={e => setAddForm(f => ({ ...f, label: e.target.value }))}
              placeholder="3123D52 / drone_1 / wifi_ap_A" className={iCls()} style={iStyle()} />
          </div>

          {captureMode === 'path' ? (
            <div className="sm:col-span-2">
              <label className="text-xs app-muted-text mb-1 block">IQ file path</label>
              <input value={addForm.iq_path} onChange={e => setAddForm(f => ({ ...f, iq_path: e.target.value }))}
                placeholder="C:\captures\device_A.iq" className={iCls('font-mono')} style={iStyle()} />
            </div>
          ) : (
            <div className="sm:col-span-2">
              <input type="file" ref={fileRef} className="hidden"
                accept=".iq,.sigmf-data,.bin,.dat,.complex,.cf32,.cf16"
                onChange={handleFileUpload} />
              <div onClick={() => fileRef.current?.click()}
                className={cn('cursor-pointer rounded-xl border-2 border-dashed p-5 text-center transition-colors hover:border-amber-400/50',
                  uploading ? 'opacity-50 pointer-events-none' : '')}
                style={{ borderColor: 'var(--app-border)' }}>
                {uploading ? <Loader2 className="w-8 h-8 mx-auto text-amber-400 animate-spin mb-2" />
                  : <Upload className="w-8 h-8 mx-auto mb-2" style={{ color: 'var(--app-muted)' }} />}
                <div className="text-sm app-muted-text">{uploading ? 'Uploading…' : 'Click to upload IQ file'}</div>
                <div className="text-xs app-muted-text mt-1">.iq · .sigmf-data · .bin · .dat · .cf32 · .cf16</div>
                {addForm.iq_path && !uploading && <div className="mt-2 text-xs text-amber-400 font-mono truncate">{addForm.iq_path}</div>}
              </div>
            </div>
          )}

          <div>
            <label className="text-xs app-muted-text mb-1 block">Session ID (optional)</label>
            <input value={addForm.session_id} onChange={e => setAddForm(f => ({ ...f, session_id: e.target.value }))} className={iCls()} style={iStyle()} />
          </div>
          <div>
            <label className="text-xs app-muted-text mb-1 block">Notes (optional)</label>
            <input value={addForm.notes} onChange={e => setAddForm(f => ({ ...f, notes: e.target.value }))} className={iCls()} style={iStyle()} />
          </div>
        </div>
        <button onClick={addCapture} disabled={busy || !addForm.dataset_name || !addForm.iq_path || !addForm.label}
          className="mt-3 flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}Add Capture
        </button>
        <StatusMsg s={addStatus} />
      </Card>

      <Card>
        <SectionTitle icon={Settings2} title="Build Train / Validation / Test Splits" />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
          <div className="sm:col-span-4">
            <label className="text-xs app-muted-text mb-1 block">Dataset</label>
            <DatasetSelect value={splitForm.dataset_name} onChange={v => setSplitForm(f => ({ ...f, dataset_name: v }))} />
          </div>
          {(['train_ratio', 'val_ratio', 'seed'] as const).map(k => (
            <div key={k}>
              <label className="text-xs app-muted-text mb-1 block">{k.replace('_', ' ')}</label>
              <input value={splitForm[k]} onChange={e => setSplitForm(f => ({ ...f, [k]: e.target.value }))} className={iCls()} style={iStyle()} />
            </div>
          ))}
        </div>
        <button onClick={buildSplits} disabled={busy || !splitForm.dataset_name}
          className="mt-3 flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Settings2 className="w-4 h-4" />}Build Splits
        </button>
        <StatusMsg s={splitStatus} />
      </Card>
    </div>
  );
}

// ── Training panel ─────────────────────────────────────────────────────────

function BenchmarkTable({ result, iqBytes }: { result: BenchmarkResult; iqBytes?: number }) {
  const medals = ['🥇', '🥈', '🥉'];
  return (
    <Card>
      <div className="flex items-center gap-2 mb-4">
        <Trophy className="w-4 h-4 text-amber-400" />
        <h3 className="font-semibold text-sm">Benchmark — {result.dataset_name}</h3>
        <Badge label={result.task.replace(/_/g, ' ')} variant="blue" />
        <Badge label={`${result.total_trained} models`} variant="neutral" />
      </div>

      {/* Best model hero + dataset IQ size */}
      {result.results[0] && (
        <div className="rounded-xl p-3 mb-4 flex items-center gap-3" style={{ background: 'var(--app-surface-strong)' }}>
          <Award className="w-8 h-8 text-amber-400 flex-shrink-0" />
          <div className="flex-1">
            <div className="font-bold text-amber-400">Best: {result.best_model?.replace(/_/g, ' ')}</div>
            <div className="text-xs app-muted-text">
              Acc {(result.results[0].accuracy * 100).toFixed(1)}% ·
              F1 {(result.results[0].macro_f1 * 100).toFixed(1)}% ·
              {result.results[0].correct}/{result.results[0].total_test} correct
            </div>
          </div>
          {(iqBytes || result.results[0]?.dataset_iq_size_bytes) && (
            <div className="text-right text-xs app-muted-text">
              <div className="text-amber-400 font-semibold">{fmtBytes(iqBytes || result.results[0].dataset_iq_size_bytes)}</div>
              <div>dataset IQ</div>
            </div>
          )}
        </div>
      )}

      {/* Ranking table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left app-muted-text border-b" style={{ borderColor: 'var(--app-border)' }}>
              <th className="pb-2 pr-3">Rank</th>
              <th className="pb-2 pr-3">Model</th>
              <th className="pb-2 pr-3 text-right">Acc%</th>
              <th className="pb-2 pr-3 text-right">F1%</th>
              <th className="pb-2 pr-3 text-right">BAcc%</th>
              <th className="pb-2 pr-3 text-right">Correct</th>
              <th className="pb-2 pr-3 text-right">Failed</th>
              <th className="pb-2 pr-3 text-right">Train(s)</th>
              <th className="pb-2 text-right">MB</th>
            </tr>
          </thead>
          <tbody>
            {result.results.map((row, i) => (
              <tr key={row.model_kind}
                className={cn('border-b transition-colors', i === 0 ? 'text-amber-400' : i === 1 ? 'text-slate-300' : i === 2 ? 'text-amber-600' : '')}
                style={{ borderColor: 'var(--app-border)' }}>
                <td className="py-2 pr-3 font-bold">{medals[i] || `#${row.rank}`}</td>
                <td className="py-2 pr-3 font-medium">{row.model_kind.replace(/_/g, ' ')}</td>
                <td className="py-2 pr-3 text-right font-mono">{(row.accuracy * 100).toFixed(1)}</td>
                <td className="py-2 pr-3 text-right font-mono">{(row.macro_f1 * 100).toFixed(1)}</td>
                <td className="py-2 pr-3 text-right font-mono">{(row.balanced_accuracy * 100).toFixed(1)}</td>
                <td className="py-2 pr-3 text-right font-mono text-emerald-400">{row.correct}</td>
                <td className="py-2 pr-3 text-right font-mono text-red-400">{row.failed}</td>
                <td className="py-2 pr-3 text-right font-mono app-muted-text">{((row.train_time_ms || 0) / 1000).toFixed(1)}</td>
                <td className="py-2 text-right font-mono app-muted-text">{row.model_size_bytes ? (row.model_size_bytes / 1_000_000).toFixed(1) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Bar chart comparison */}
      <div className="mt-4 space-y-1.5">
        {result.results.map((row, i) => (
          <div key={row.model_kind} className="flex items-center gap-2">
            <div className="w-28 truncate text-xs app-muted-text">{row.model_kind.replace(/_/g, ' ')}</div>
            <div className="flex-1 rounded-full h-2 overflow-hidden" style={{ background: 'var(--app-surface-strong)' }}>
              <div className="h-full rounded-full transition-all"
                style={{ width: `${row.accuracy * 100}%`, background: i === 0 ? '#f59e0b' : i === 1 ? '#94a3b8' : i === 2 ? '#b45309' : '#475569' }} />
            </div>
            <div className="text-xs font-mono w-12 text-right" style={{ color: i === 0 ? '#f59e0b' : 'var(--app-muted)' }}>
              {(row.accuracy * 100).toFixed(1)}%
            </div>
          </div>
        ))}
      </div>

      {result.errors.length > 0 && (
        <div className="mt-3 rounded-xl px-3 py-2 text-xs bg-red-500/10 text-red-400">
          <div className="font-semibold">
            {result.errors.length} model(s) failed: {result.errors.map(e => e.model_kind).join(', ')}
          </div>
          <div className="mt-2 space-y-1">
            {result.errors.map(e => (
              <div key={e.model_kind}>
                <span className="font-mono">{e.model_kind}</span>: {e.error || 'No backend error detail returned'}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function TrainingPanel({ health }: { health: E6Health | null }) {
  const [form, setForm] = useState({
    dataset_name: '', model_kind: 'extra_trees', window_size: '4096', windows_per_file: '3',
    window_strategy: 'linspace', test_size: '0.25', random_state: '42',
    split_from_manifest: true, enabled_for_live: true, model_name: '', notes: '',
  });

  // Single train job
  const [trainJobId, setTrainJobId] = useState<string | null>(null);
  const [trainAudit, setTrainAudit] = useState<JobStatus | null>(null);

  // Train-all benchmark job
  const [allJobId, setAllJobId] = useState<string | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null>(null);
  const [benchmarkIqBytes, setBenchmarkIqBytes] = useState<number>(0);

  const [error, setError] = useState<string | null>(null);

  const trainJob = useJobPoller(trainJobId, job => {
    if (job.status === 'done') setTrainAudit(job);
    else if (job.status === 'error') setError(job.error || 'Training failed');
  });

  const allJob = useJobPoller(allJobId, job => {
    if (job.status === 'done') {
      const r = job.result as BenchmarkResult | null;
      if (r?.results) {
        setBenchmark(r);
        const iq = r.results[0]?.dataset_iq_size_bytes;
        if (iq) setBenchmarkIqBytes(iq);
      }
    } else if (job.status === 'error') {
      setError(job.error || 'Benchmark training failed');
    }
  });

  const isTraining = trainJob?.status === 'running';
  const isAllTraining = allJob?.status === 'running';

  const train = async () => {
    setTrainJobId(null); setTrainAudit(null); setError(null); setBenchmark(null);
    try {
      const r = await axios.post(`${API}/train`, {
        ...form,
        window_size: parseInt(form.window_size), windows_per_file: parseInt(form.windows_per_file),
        test_size: parseFloat(form.test_size), random_state: parseInt(form.random_state),
      });
      const jobId: string | undefined = r.data.data?.job_id;
      if (jobId) setTrainJobId(jobId);
      else {
        // Direct result (no job system)
        const fakeJob: JobStatus = { job_id: '', operation: 'train', description: '', status: 'done', progress: 100, message: 'Complete', result: r.data.data, error: null, started_at: Date.now() / 1000, finished_at: Date.now() / 1000, elapsed_s: 0, steps: [] };
        setTrainAudit(fakeJob);
      }
    } catch (e: unknown) { setError(e instanceof Error ? e.message : 'Training failed'); }
  };

  const trainAll = async () => {
    setAllJobId(null); setBenchmark(null); setTrainAudit(null); setError(null); setTrainJobId(null);
    try {
      const r = await axios.post(`${API}/train-all`, {
        dataset_name: form.dataset_name,
        window_size: parseInt(form.window_size), windows_per_file: parseInt(form.windows_per_file),
        window_strategy: form.window_strategy, test_size: parseFloat(form.test_size),
        random_state: parseInt(form.random_state), split_from_manifest: form.split_from_manifest,
        enabled_for_live: form.enabled_for_live,
      });
      const jobId: string | undefined = r.data.data?.job_id;
      if (jobId) setAllJobId(jobId);
      else setBenchmark(r.data.data as BenchmarkResult);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : 'Benchmark training failed'); }
  };

  const algorithms = health?.supported_models || [];

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle icon={FlaskConical} title="Train E6 Classical Model" />
        <div className="mb-3 rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--app-surface-strong)' }}>
          37 tabular RF features · StandardScaler · group-disjoint stratified split · models isolated per dataset
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="text-xs app-muted-text mb-1 block">Dataset *</label>
            <DatasetSelect value={form.dataset_name} onChange={v => setForm(f => ({ ...f, dataset_name: v }))} />
          </div>
          <div>
            <label className="text-xs app-muted-text mb-1 block">Algorithm</label>
            <select value={form.model_kind} onChange={e => setForm(f => ({ ...f, model_kind: e.target.value }))} className={iCls()} style={iStyle()}>
              {algorithms.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs app-muted-text mb-1 block">Model name (optional)</label>
            <input value={form.model_name} onChange={e => setForm(f => ({ ...f, model_name: e.target.value }))} className={iCls()} style={iStyle()} />
          </div>
          {[['Window size', 'window_size', '4096'], ['Windows/file', 'windows_per_file', '3'], ['Test size', 'test_size', '0.25'], ['Seed', 'random_state', '42']].map(([lbl, k, ph]) => (
            <div key={k}>
              <label className="text-xs app-muted-text mb-1 block">{lbl}</label>
              <input value={(form as Record<string, string | boolean>)[k] as string}
                onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))}
                placeholder={ph} type="number" className={iCls()} style={iStyle()} />
            </div>
          ))}
          <div>
            <label className="text-xs app-muted-text mb-1 block">Window strategy</label>
            <select value={form.window_strategy} onChange={e => setForm(f => ({ ...f, window_strategy: e.target.value }))} className={iCls()} style={iStyle()}>
              <option value="linspace">linspace (uniform)</option>
              <option value="energy">energy (highest power windows)</option>
            </select>
          </div>
          <div className="sm:col-span-2 flex gap-4">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={form.split_from_manifest}
                onChange={e => setForm(f => ({ ...f, split_from_manifest: e.target.checked }))} />
              Use manifest splits
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={form.enabled_for_live}
                onChange={e => setForm(f => ({ ...f, enabled_for_live: e.target.checked }))} />
              Enable for live detection
            </label>
          </div>
        </div>

        <div className="mt-3 flex flex-col sm:flex-row gap-2">
          <button onClick={train} disabled={isTraining || isAllTraining || !form.dataset_name}
            className="flex items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
            {isTraining ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {isTraining ? 'Training…' : 'Train Selected Model'}
          </button>
          <button onClick={trainAll} disabled={isTraining || isAllTraining || !form.dataset_name}
            className="flex items-center justify-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold disabled:opacity-50 hover:bg-amber-500/10"
            style={{ borderColor: 'var(--app-accent)', color: 'var(--app-accent)' }}>
            {isAllTraining ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trophy className="w-4 h-4" />}
            {isAllTraining ? `Training… (${allJob?.model_index ?? '?'}/8 — ${allJob?.current_model ?? ''})` : 'Train All 8 — Benchmark'}
          </button>
        </div>

        {error && <div className="mt-2 rounded-xl px-3 py-2 text-xs bg-red-500/10 text-red-400">{error}</div>}

        {/* Live progress bars */}
        {trainJob && (trainJob.status === 'running' || trainJob.status === 'done') && (
          <div className="mt-3">
            <JobProgressBar job={trainJob} />
          </div>
        )}
        {allJob && (allJob.status === 'running' || allJob.status === 'done') && (
          <div className="mt-3">
            <JobProgressBar job={allJob} />
          </div>
        )}
      </Card>

      {trainAudit && <JobAuditCard job={trainAudit} />}
      {benchmark && <BenchmarkTable result={benchmark} iqBytes={benchmarkIqBytes} />}
    </div>
  );
}

// ── Models panel ───────────────────────────────────────────────────────────

function ModelsPanel() {
  const { data: models, loading, fetch } = useE6Api<ModelEntry[]>('/models');
  const [busy, setBusy] = useState<string | null>(null);
  const [expandedDataset, setExpandedDataset] = useState<string | null>(null);

  const [importPath, setImportPath] = useState('');
  const [scanModels, setScanModels] = useState<ScannedModel[] | null>(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [scanMsg, setScanMsg] = useState<{ ok: boolean; msg: string } | null>(null);
  const [importAllBusy, setImportAllBusy] = useState(false);
  const [importingFile, setImportingFile] = useState<string | null>(null);

  useEffect(() => { fetch(); }, []);

  const toggle = async (model: ModelEntry) => {
    setBusy(model.model_id);
    try {
      await axios.post(`${API}/models/${model.model_id}/${model.enabled_for_live ? 'disable-live' : 'enable-live'}`);
      fetch();
    } finally { setBusy(null); }
  };

  const handleScanModels = async () => {
    setScanBusy(true); setScanMsg(null); setScanModels(null);
    try {
      const r = await axios.post(`${API}/models/scan-directory`, { models_dir: importPath });
      setScanModels(r.data.data.models);
      setScanMsg({ ok: true, msg: `Found ${r.data.data.count} model files` });
    } catch (e: unknown) {
      setScanMsg({ ok: false, msg: e instanceof Error ? e.message : 'Scan failed' });
    } finally { setScanBusy(false); }
  };

  const handleImportOne = async (filePath: string, fileName: string) => {
    setImportingFile(fileName);
    try {
      await axios.post(`${API}/models/import-existing`, { model_path: filePath, enabled_for_live: true });
      setScanModels(prev => prev ? prev.map(m => m.file_path === filePath ? { ...m, already_registered: true } : m) : prev);
      fetch();
    } catch (e: unknown) {
      setScanMsg({ ok: false, msg: e instanceof Error ? e.message : `Import failed: ${fileName}` });
    } finally { setImportingFile(null); }
  };

  const handleImportAll = async () => {
    setImportAllBusy(true); setScanMsg(null);
    try {
      const r = await axios.post(`${API}/models/import-directory`, { models_dir: importPath, enabled_for_live: true });
      const d = r.data.data;
      setScanMsg({ ok: true, msg: `Imported ${d.imported_count} models${d.error_count > 0 ? `, ${d.error_count} errors` : ''}` });
      setScanModels(prev => prev ? prev.map(m => ({ ...m, already_registered: true })) : prev);
      fetch();
    } catch (e: unknown) {
      setScanMsg({ ok: false, msg: e instanceof Error ? e.message : 'Bulk import failed' });
    } finally { setImportAllBusy(false); }
  };

  const unregisteredCount = (scanModels || []).filter(m => !m.already_registered).length;

  const grouped = (models || []).reduce<Record<string, ModelEntry[]>>((acc, m) => {
    const key = m.dataset_name || 'unknown';
    return { ...acc, [key]: [...(acc[key] || []), m] };
  }, {});
  const datasetKeys = Object.keys(grouped).sort();

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle icon={FolderOpen} title="Import Pre-trained Models from Directory" />
        <div className="text-xs app-muted-text mb-3">
          Scan a folder for <code className="px-1 rounded" style={{ background: 'var(--app-surface-strong)' }}>.joblib</code> bundles.
          Algorithm and dataset are auto-detected from filename (e.g. <code className="px-1 rounded" style={{ background: 'var(--app-surface-strong)' }}>kri_wifi_extra_trees_model.joblib</code>).
        </div>
        <div className="flex gap-2">
          <input value={importPath} onChange={e => { setImportPath(e.target.value); setScanModels(null); }}
            placeholder="C:\Users\Usuario\Desktop\NICS\datasets\rf oracle\models"
            className={iCls('flex-1 font-mono')} style={iStyle()} />
          <button onClick={handleScanModels} disabled={scanBusy || !importPath}
            className="flex items-center gap-1.5 rounded-xl border px-3 py-2 text-sm font-medium disabled:opacity-50 hover:bg-white/5 whitespace-nowrap"
            style={{ borderColor: 'var(--app-border)' }}>
            {scanBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FolderOpen className="w-3.5 h-3.5 text-amber-400" />}
            Scan
          </button>
        </div>
        <StatusMsg s={scanMsg} />

        {scanModels && scanModels.length > 0 && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs app-muted-text">{scanModels.length} found · {unregisteredCount} not imported</span>
              {unregisteredCount > 0 && (
                <button onClick={handleImportAll} disabled={importAllBusy}
                  className="flex items-center gap-1.5 rounded-xl bg-amber-500 px-3 py-1.5 text-xs font-semibold text-slate-900 disabled:opacity-50">
                  {importAllBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                  Import All ({unregisteredCount})
                </button>
              )}
            </div>
            <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
              {scanModels.map(m => (
                <div key={m.file_name} className="flex items-center justify-between gap-2 rounded-xl px-3 py-2"
                  style={{ background: 'var(--app-surface-strong)' }}>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-mono truncate">{m.file_name.replace('_model.joblib', '')}</span>
                      {m.algorithm !== 'unknown' && <Badge label={m.algorithm} variant="amber" />}
                      <span className="text-xs app-muted-text">{m.size_mb} MB</span>
                    </div>
                    <div className="text-xs app-muted-text mt-0.5">dataset: {m.dataset_name}</div>
                  </div>
                  {m.already_registered ? (
                    <Badge label="registered" variant="green" />
                  ) : (
                    <button onClick={() => handleImportOne(m.file_path, m.file_name)}
                      disabled={importingFile === m.file_name || importAllBusy}
                      className="flex-shrink-0 flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 disabled:opacity-50">
                      {importingFile === m.file_name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                      Import
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      <div className="flex justify-between items-center">
        <h3 className="font-semibold text-sm">E6 Model Registry</h3>
        <button onClick={fetch} disabled={loading} className="rounded-lg p-1.5 hover:bg-white/5">
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {datasetKeys.length === 0 ? (
        <Card>
          <div className="text-center text-sm app-muted-text py-6">
            No models yet. Import pre-trained .joblib bundles above or train from the Training tab.
          </div>
        </Card>
      ) : datasetKeys.map(dsKey => {
        const dsModels = grouped[dsKey];
        const isOpen = expandedDataset === dsKey || expandedDataset === null;
        const liveCount = dsModels.filter(m => m.enabled_for_live).length;
        const taskBadge = dsModels[0]?.task.replace(/_/g, ' ') || '';
        return (
          <div key={dsKey}>
            <button onClick={() => setExpandedDataset(expandedDataset === dsKey ? null : dsKey)}
              className="w-full flex items-center justify-between px-3 py-2 rounded-xl hover:bg-white/5 mb-1">
              <div className="flex items-center gap-2">
                {isOpen ? <ChevronDown className="w-4 h-4 text-amber-400" /> : <ChevronRight className="w-4 h-4 text-amber-400" />}
                <span className="font-semibold text-sm">{dsKey}</span>
                <Badge label={taskBadge} variant="blue" />
                <Badge label={`${dsModels.length} models`} variant="neutral" />
                {liveCount > 0 && <Badge label={`${liveCount} live`} variant="green" />}
              </div>
            </button>
            {isOpen && (
              <div className="space-y-2 ml-2">
                {dsModels.map(m => (
                  <Card key={m.model_id}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-sm truncate">{m.algorithm}</span>
                          <Badge label={m.enabled_for_live ? 'live ready' : 'disabled'} variant={m.enabled_for_live ? 'green' : 'neutral'} />
                        </div>
                        <div className="mt-1 text-xs app-muted-text">{m.class_count} classes · window {m.window_size} · {m.dtype}</div>
                        <div className="mt-1.5 flex gap-3 text-xs">
                          {m.metrics.accuracy != null && <span>Acc <strong className="text-amber-400">{(m.metrics.accuracy * 100).toFixed(1)}%</strong></span>}
                          {m.metrics.macro_f1 != null && <span>F1 <strong className="text-amber-400">{(m.metrics.macro_f1 * 100).toFixed(1)}%</strong></span>}
                          {m.metrics.balanced_accuracy != null && <span>BAcc <strong className="text-amber-400">{(m.metrics.balanced_accuracy * 100).toFixed(1)}%</strong></span>}
                        </div>
                        <div className="mt-1 text-xs app-muted-text truncate">
                          {m.classes.slice(0, 8).join(' · ')}{m.classes.length > 8 ? ` +${m.classes.length - 8}` : ''}
                        </div>
                      </div>
                      <button onClick={() => toggle(m)} disabled={busy === m.model_id}
                        className={cn('flex-shrink-0 rounded-xl px-3 py-1.5 text-xs font-semibold',
                          m.enabled_for_live
                            ? 'bg-emerald-500/15 text-emerald-400 hover:bg-red-500/15 hover:text-red-400'
                            : 'bg-slate-500/15 text-slate-400 hover:bg-emerald-500/15 hover:text-emerald-400')}>
                        {busy === m.model_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : (m.enabled_for_live ? 'Live ON' : 'Live OFF')}
                      </button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Predict panel ──────────────────────────────────────────────────────────

function PredictPanel() {
  const { data: models, fetch: fetchModels } = useE6Api<ModelEntry[]>('/models');
  useEffect(() => { fetchModels(); }, []);
  const liveModels = (models || []).filter(m => m.enabled_for_live);
  const [selectedModel, setSelectedModel] = useState('');
  const [iqPath, setIqPath] = useState('');
  const [dtype, setDtype] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PredictResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!selectedModel && liveModels.length > 0) setSelectedModel(liveModels[0].model_id); }, [models]);

  const predict = async () => {
    setBusy(true); setResult(null); setError(null);
    try {
      const r = await axios.post(`${API}/predict-file`, { model_id: selectedModel, iq_path: iqPath, dtype: dtype || null, top_k: 5 });
      setResult(r.data.data);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : 'Prediction failed'); }
    finally { setBusy(false); }
  };

  const selectedModelInfo = liveModels.find(m => m.model_id === selectedModel);

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle icon={Zap} title="Predict from IQ File" />
        {liveModels.length === 0 ? (
          <div className="rounded-xl px-3 py-2 text-sm bg-amber-500/10 text-amber-400">
            No models enabled for live detection. Enable a model in the Models tab.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <div>
                <label className="text-xs app-muted-text mb-1 block">Model</label>
                <select value={selectedModel} onChange={e => setSelectedModel(e.target.value)} className={iCls()} style={iStyle()}>
                  {liveModels.map(m => (
                    <option key={m.model_id} value={m.model_id}>
                      [{m.dataset_name}] {m.algorithm} {m.metrics.accuracy != null ? `(${(m.metrics.accuracy * 100).toFixed(0)}%)` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs app-muted-text mb-1 block">IQ dtype (optional)</label>
                <select value={dtype} onChange={e => setDtype(e.target.value)} className={iCls()} style={iStyle()}>
                  <option value="">auto (from model)</option>
                  <option value="cf32">cf32</option>
                  <option value="cf16_le">cf16_le</option>
                  <option value="cf32_le">cf32_le</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="text-xs app-muted-text mb-1 block">IQ file path</label>
                <input value={iqPath} onChange={e => setIqPath(e.target.value)}
                  placeholder="C:\path\to\capture.iq or .sigmf-data"
                  className={iCls('font-mono')} style={iStyle()} />
              </div>
            </div>

            {selectedModelInfo && (
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                {[
                  ['algorithm', selectedModelInfo.algorithm],
                  ['classes', String(selectedModelInfo.class_count)],
                  ['window', String(selectedModelInfo.window_size)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg px-2 py-1.5 text-center" style={{ background: 'var(--app-surface-strong)' }}>
                    <div className="font-semibold text-amber-400">{v}</div>
                    <div className="app-muted-text">{k}</div>
                  </div>
                ))}
              </div>
            )}

            <button onClick={predict} disabled={busy || !selectedModel || !iqPath}
              className="mt-3 flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              {busy ? 'Predicting…' : 'Run Prediction'}
            </button>
            {error && <div className="mt-2 rounded-xl px-3 py-2 text-xs bg-red-500/10 text-red-400">{error}</div>}
          </>
        )}
      </Card>

      {result && (
        <Card>
          <SectionTitle icon={Radio} title="Prediction Result" />
          {result.warning && (
            <div className="mb-3 rounded-xl px-3 py-2 text-xs bg-amber-500/10 text-amber-400 flex gap-2">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />{result.warning}
            </div>
          )}
          <div className="rounded-2xl p-4 text-center mb-3" style={{ background: 'var(--app-surface-strong)' }}>
            <div className="text-3xl font-bold text-amber-400">{result.prediction}</div>
            <div className="text-sm app-muted-text mt-1">{(result.confidence * 100).toFixed(1)}% confidence</div>
            <div className="text-xs app-muted-text mt-0.5">{result.inference_time_ms.toFixed(1)} ms · {result.task.replace(/_/g, ' ')}</div>
          </div>
          <div className="space-y-1.5">
            {result.top_k.map((k, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="w-32 truncate text-sm">{k.label}</div>
                <div className="flex-1 rounded-full h-1.5 bg-white/10 overflow-hidden">
                  <div className="h-full rounded-full bg-amber-400" style={{ width: `${k.probability * 100}%` }} />
                </div>
                <div className="text-xs text-amber-400 w-10 text-right">{(k.probability * 100).toFixed(1)}%</div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

// ── Main view ──────────────────────────────────────────────────────────────

export const E6OracleStyleLabView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('datasets');
  const [health, setHealth] = useState<E6Health | null>(null);

  useEffect(() => {
    axios.get(`${API}/health`).then(r => setHealth(r.data.data)).catch(() => null);
  }, []);

  const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: 'datasets', label: 'Datasets', icon: Database },
    { id: 'local-builder', label: 'Local Builder', icon: Plus },
    { id: 'training', label: 'Training', icon: FlaskConical },
    { id: 'models', label: 'Models', icon: DatabaseZap },
    { id: 'predict', label: 'Predict', icon: Zap },
  ];

  return (
    <div className="h-full flex flex-col">
      <div className="flex-shrink-0 border-b px-6 py-3" style={{ borderColor: 'var(--app-border)' }}>
        <div className="flex items-center gap-2">
          <DatabaseZap className="w-5 h-5 text-amber-400" />
          <span className="font-bold">E6 Oracle-Style RF Lab</span>
          {health && <Badge label={health.sklearn_available ? 'sklearn ready' : 'sklearn missing'} variant={health.sklearn_available ? 'green' : 'red'} />}
        </div>
        {health && (
          <div className="text-xs app-muted-text mt-0.5">
            {health.feature_count} features · {health.supported_models.length} algorithms · {health.supported_external_sources.length} external sources
          </div>
        )}
        <div className="flex gap-1 mt-3 overflow-x-auto">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={cn('flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors',
                tab === t.id ? 'text-slate-900' : 'app-muted-text hover:bg-white/5')}
              style={tab === t.id ? { background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' } : {}}>
              <t.icon className="w-3.5 h-3.5" />{t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-6">
        {tab === 'datasets' && <DatasetsPanel health={health} />}
        {tab === 'local-builder' && <LocalBuilderPanel />}
        {tab === 'training' && <TrainingPanel health={health} />}
        {tab === 'models' && <ModelsPanel />}
        {tab === 'predict' && <PredictPanel />}
      </div>
    </div>
  );
};
