import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { useAppActions } from '../../app/store/AppStore';
import { AsyncJobStatus, FingerprintingCaptureRecord } from '../../shared/types';
import { RUNTIME_CONFIG } from '../../shared/config/runtime';
import { formatFileSize, formatFrequency } from '../../shared/utils';

const api = new ApiService();
const JOB_STORAGE_KEY = 'rfp.validation.jobId';
const SELECTION_STORAGE_KEY = 'rfp.validation.selectedCaptureIds';

const formatTimestamp = (value?: string | null) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const getErrorDetail = (error: unknown): string => {
  const detail = (error as any)?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (typeof (error as any)?.message === 'string' && (error as any).message.trim()) return (error as any).message;
  return 'Validation request failed.';
};

const formatDb = (value?: number | null) => (Number.isFinite(value) ? `${Number(value).toFixed(2)} dB` : 'n/a');

const getValidationArtifactPath = (capture: FingerprintingCaptureRecord) =>
  String(capture.artifacts?.iq_file || capture.capture_config?.output_path || '').trim();

const isSelectableValidationCapture = (capture: FingerprintingCaptureRecord) =>
  capture.quality_review.status === 'valid' && Boolean(getValidationArtifactPath(capture));

const summarizeReport = (report: Record<string, unknown>) => {
  const summary = (report.summary ?? {}) as Record<string, unknown>;
  const metrics = (report.metrics ?? {}) as Record<string, unknown>;
  const records = Array.isArray(report.records) ? report.records as Array<Record<string, unknown>> : [];
  const totalWindows = records.reduce((total, record) => total + Number(record.num_windows ?? 0), 0);

  return {
    totalWindows: Number(summary.total_windows ?? metrics.total_windows ?? totalWindows),
    accuracy: Number(
      metrics.accuracy
        ?? metrics.closed_set_accuracy
        ?? report.record_level_closed_set_accuracy
        ?? report.window_level_closed_set_accuracy
        ?? 0,
    ),
    macroF1: Number(metrics.macro_f1 ?? metrics.f1_macro ?? 0),
    balancedAccuracy: Number(metrics.balanced_accuracy ?? report.window_level_closed_set_accuracy ?? 0),
  };
};

export const ValidationLabView: React.FC = () => {
  const { setGlobalActivity, clearGlobalActivity } = useAppActions();
  const [reports, setReports] = useState<Record<string, unknown>[]>([]);
  const [status, setStatus] = useState<AsyncJobStatus | null>(null);
  const [captures, setCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [lastRefresh, setLastRefresh] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const [selectedCaptureIds, setSelectedCaptureIds] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(SELECTION_STORAGE_KEY) || '[]');
    } catch {
      return [];
    }
  });
  const pollRef = useRef<number | null>(null);
  const [form, setForm] = useState({
    val_root: 'rf_dataset_val',
    model_dir: 'remote_trained_model',
    output_json: 'validation/validation_report.json',
    batch_size: 256,
    python_exe: RUNTIME_CONFIG.radioCondaPython,
  });

  const validCaptures = useMemo(
    () => captures.filter(isSelectableValidationCapture),
    [captures],
  );

  const selectedCaptures = useMemo(
    () => validCaptures.filter((capture) => selectedCaptureIds.includes(capture.capture_id)),
    [validCaptures, selectedCaptureIds],
  );

  const validationScopeCaptures = selectedCaptures.length > 0 ? selectedCaptures : validCaptures;

  const validationScopeFrequencies = useMemo(
    () => Array.from(new Set(validationScopeCaptures.map((capture) => Math.round(capture.capture_config.center_frequency_hz * 1000) / 1000))).sort((a, b) => a - b),
    [validationScopeCaptures],
  );

  const validationFrequencyMessage = validationScopeFrequencies.length > 1
    ? `Original center frequencies differ (${validationScopeFrequencies.map((value) => formatFrequency(value)).join(', ')}). This is allowed: validation uses canonicalized IQ and checks preprocessing compatibility instead of absolute SDR tuning center.`
    : '';

  const reportSummary = useMemo(
    () => (status?.report ? summarizeReport(status.report) : null),
    [status?.report],
  );

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  };

  const refresh = async (jobId?: string | null) => {
    const [reportList, validationStatus, valCaptures] = await Promise.all([
      api.getValidationReports(),
      api.getValidationStatus(jobId ?? undefined),
      api.getFingerprintingCaptures('val'),
    ]);
    setReports(reportList);
    setStatus(validationStatus);
    setCaptures(valCaptures);
    setLastRefresh(new Date().toISOString());
    if (validationStatus?.job_id) {
      localStorage.setItem(JOB_STORAGE_KEY, validationStatus.job_id);
      window.dispatchEvent(new CustomEvent('rfp-job-started'));
    }
    return validationStatus;
  };

  const schedulePoll = (jobId: string) => {
    stopPolling();
    pollRef.current = window.setTimeout(async () => {
      try {
        const nextStatus = await refresh(jobId);
        if (nextStatus.status === 'running') {
          schedulePoll(jobId);
        }
      } catch (error) {
        console.error('Validation polling failed', error);
      }
    }, 2000);
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem(JOB_STORAGE_KEY);
    refresh(savedJobId)
      .then((validationStatus) => {
        if (validationStatus.status === 'running' && validationStatus.job_id) {
          schedulePoll(validationStatus.job_id);
        }
      })
      .catch((error) => console.error('Failed to load validation lab', error));
    return () => stopPolling();
  }, []);

  useEffect(() => {
    localStorage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(selectedCaptureIds));
  }, [selectedCaptureIds]);

  useEffect(() => {
    if (status?.status === 'running') {
      setGlobalActivity({
        visible: true,
        kind: 'processing',
        title: 'Validation in progress',
        detail: `${selectedCaptures.length || selectedCaptureIds.length} selected validation captures · model ${form.model_dir}`,
      });
      return;
    }
  }, [form.model_dir, selectedCaptureIds.length, selectedCaptures.length, setGlobalActivity, status?.status]);

  const toggleCapture = (captureId: string) => {
    if (!captureId) return;
    setSelectedCaptureIds((current) =>
      current.includes(captureId) ? current.filter((item) => item !== captureId) : [...current, captureId],
    );
  };

  const getDisabledReason = (capture: FingerprintingCaptureRecord) => {
    if (capture.quality_review.status !== 'valid') return `quality status is ${capture.quality_review.status}`;
    if (!getValidationArtifactPath(capture)) return 'missing IQ artifact path';
    return '';
  };

  const run = async (mode: 'sync' | 'async') => {
    const activeSelectionCount = selectedCaptures.length || selectedCaptureIds.length || validCaptures.length;
    setGlobalActivity({
      visible: true,
      kind: 'processing',
      title: mode === 'async' ? 'Validation job launching' : 'Validation running',
      detail: `${activeSelectionCount} validation captures - model ${form.model_dir}`,
    });

    setStatus((current) => ({
      ...(current ?? {}),
      status: mode === 'async' ? 'starting' : 'running',
      stdout: current?.stdout ?? 'Validation request submitted. Waiting for backend output...',
      stderr: current?.stderr ?? '',
    }));
    setIsLaunching(true);
    setErrorMessage('');
    try {
      const payload = {
        ...form,
        python_exe: form.python_exe.trim(),
        selected_capture_ids: selectedCaptureIds,
      };
      const result = mode === 'sync' ? await api.runValidation(payload) : await api.startValidation(payload);
      if ('status' in result) {
        setStatus(result);
        if (result.job_id) {
          localStorage.setItem(JOB_STORAGE_KEY, result.job_id);
          window.dispatchEvent(new CustomEvent('rfp-job-started'));
          schedulePoll(result.job_id);
        }
      } else {
        const commandResult = (result as any).command_result ?? {};
        setStatus({
          status: commandResult.returncode === 0 ? 'completed' : 'failed',
          returncode: commandResult.returncode ?? null,
          stdout: commandResult.stdout || 'Validation finished without stdout.',
          stderr: commandResult.stderr || '',
          report: (result as any).report,
          metadata: {
            output_json: (result as any).output_json,
            dataset_export: (result as any).dataset_export,
            selected_metadata_paths: (result as any).selected_metadata_paths,
          },
        });
        const [reportList, valCaptures] = await Promise.all([
          api.getValidationReports(),
          api.getFingerprintingCaptures('val'),
        ]);
        setReports(reportList);
        setCaptures(valCaptures);
        setLastRefresh(new Date().toISOString());
        clearGlobalActivity();
      }
    } catch (error) {
      setErrorMessage(getErrorDetail(error));
      setStatus((current) => ({
        ...(current ?? {}),
        status: 'failed',
        stderr: getErrorDetail(error),
      }));
      clearGlobalActivity();
    } finally {
      setIsLaunching(false);
    }
  };

  const selectAllValid = () => {
    setSelectedCaptureIds(validCaptures.map((capture) => capture.capture_id));
  };

  const clearSelection = () => setSelectedCaptureIds([]);

  return (
    <div className="app-page p-6">
      <div className="mb-6">
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-amber-700">Validation Lab</div>
        <h1 className="mt-2 font-serif text-4xl" style={{ color: 'var(--app-text)' }}>
          External validation with explicit capture selection
        </h1>
        <p className="mt-3 max-w-4xl text-sm leading-7 app-muted-text">
          Validation exports a clean `val` subset from the unified registry, keeps the run attached across navigation, and exposes a
          stable console plus a reproducible summary of what was actually evaluated.
        </p>
        <p className="mt-2 text-sm app-muted-text">Last UI refresh: {formatTimestamp(lastRefresh)}</p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="grid gap-4 md:grid-cols-2">
            {['val_root', 'model_dir', 'output_json', 'python_exe'].map((field) => (
              <label key={field}>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] app-muted-text">{field}</div>
                <input
                  className="mt-2 w-full rounded-2xl border px-3 py-2 text-sm"
                  style={{ background: 'var(--app-surface-muted)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
                  value={String((form as Record<string, unknown>)[field] ?? '')}
                  onChange={(e) => setForm((current) => ({ ...current, [field]: e.target.value }))}
                />
              </label>
            ))}
            <label>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] app-muted-text">batch_size</div>
              <input
                className="mt-2 w-full rounded-2xl border px-3 py-2 text-sm"
                style={{ background: 'var(--app-surface-muted)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
                type="number"
                value={form.batch_size}
                onChange={(e) => setForm((current) => ({ ...current, batch_size: Number(e.target.value) }))}
              />
            </label>
          </div>

          <div className="app-surface-muted mt-4 rounded-2xl p-4 text-sm">
            Python default detected: {form.python_exe || 'backend default / RADIOCONDA_PYTHON'}.
            Leave it empty to let the backend use its default interpreter.
          </div>
          <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            The backend rebuilds `rf_dataset_val` using only `val + valid` captures, canonicalizes IQ to a shared baseband representation,
            checks canonical preprocessing compatibility, and then launches the validation pipeline on the selected subset.
          </div>

          {validationFrequencyMessage && (
            <div className="mt-4 rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900">
              {validationFrequencyMessage}
            </div>
          )}

          {errorMessage && (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{errorMessage}</div>
          )}

          <div className="mt-5 flex flex-wrap gap-3">
            <button
              className="rounded-full bg-amber-500 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => run('sync')}
              disabled={isLaunching || status?.status === 'running'}
            >
              Run Validation
            </button>
            <button
              className="rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => run('async')}
              disabled={isLaunching || status?.status === 'running'}
            >
              Start Async Validation
            </button>
            <button
              className="rounded-full border px-5 py-3 text-sm font-semibold"
              style={{ borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
              onClick={() => refresh(status?.job_id)}
            >
              Refresh
            </button>
          </div>

          <div className="app-surface-muted mt-5 rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">Validation Job</div>
                <div className="mt-2 text-lg font-semibold" style={{ color: 'var(--app-text)' }}>{status?.status ?? 'not_found'}</div>
              </div>
              <div className="text-right text-xs app-muted-text">
                <div>job_id: {status?.job_id ?? localStorage.getItem(JOB_STORAGE_KEY) ?? 'none'}</div>
                <div>started: {formatTimestamp(status?.started_at_utc)}</div>
                <div>ended: {formatTimestamp(status?.ended_at_utc)}</div>
                <div>returncode: {status?.returncode ?? 'running/not finished'}</div>
              </div>
            </div>
            <div className="mt-4 grid gap-4">
              <pre className="h-72 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-slate-100">{status?.stdout || 'No stdout yet.'}</pre>
              <pre className="h-44 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-rose-200">{status?.stderr || 'No stderr.'}</pre>
            </div>
          </div>
        </section>

        <div className="space-y-5">
          <section className="grid gap-4 md:grid-cols-4">
            {[
              ['Valid val captures', validCaptures.length],
              ['Selected captures', selectedCaptures.length],
              ['Accuracy', reportSummary ? `${(reportSummary.accuracy * 100).toFixed(1)}%` : 'n/a'],
              ['Macro F1', reportSummary ? reportSummary.macroF1.toFixed(3) : 'n/a'],
            ].map(([label, value]) => (
              <div key={String(label)} className="app-surface-strong rounded-[1.5rem] p-5">
                <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{label}</div>
                <div className="mt-3 text-3xl font-semibold" style={{ color: 'var(--app-text)' }}>{value}</div>
              </div>
            ))}
          </section>

          <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Validation capture selection</div>
              <div className="text-xs app-muted-text">{selectedCaptures.length} selected</div>
            </div>
            <div className="mb-4 rounded-2xl border border-amber-100 bg-amber-50 p-4 text-sm text-amber-900">
              Source: fingerprinting registry filtered by `dataset_split = val`. Select the exact captures to include in this run.
            </div>
            <div className="mb-4 flex flex-wrap gap-3">
              {Array.from(new Set(validCaptures.map((capture) => Math.round(capture.capture_config.center_frequency_hz * 1000) / 1000))).sort((a, b) => a - b).map((frequency) => (
                <button
                  key={frequency}
                  className="rounded-full border border-sky-300 px-4 py-2 text-xs font-semibold text-sky-900"
                  onClick={() => setSelectedCaptureIds(validCaptures.filter((capture) => Math.round(capture.capture_config.center_frequency_hz * 1000) / 1000 === frequency).map((capture) => capture.capture_id))}
                >
                  Select {formatFrequency(frequency)}
                </button>
              ))}
              <button className="rounded-full border border-amber-300 px-4 py-2 text-xs font-semibold text-amber-900" onClick={() => selectAllValid()}>
                Select All Valid
              </button>
              <button className="rounded-full border px-4 py-2 text-xs font-semibold" style={{ borderColor: 'var(--app-border)', color: 'var(--app-text)' }} onClick={() => clearSelection()}>
                Clear Selection
              </button>
            </div>
            <div className="space-y-3">
              {captures.map((capture) => {
                const disabledReason = getDisabledReason(capture);
                const disabled = Boolean(disabledReason);
                const checked = selectedCaptureIds.includes(capture.capture_id);
                return (
                  <div
                    key={capture.capture_id}
                    role="button"
                    tabIndex={disabled ? -1 : 0}
                    aria-disabled={disabled}
                    aria-pressed={checked}
                    onClick={() => {
                      if (!disabled) toggleCapture(capture.capture_id);
                    }}
                    onKeyDown={(event) => {
                      if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
                        event.preventDefault();
                        toggleCapture(capture.capture_id);
                      }
                    }}
                    className={`flex gap-3 rounded-2xl border p-4 text-left transition ${disabled ? 'cursor-not-allowed opacity-70' : 'cursor-pointer hover:border-amber-300'} ${checked ? 'ring-2 ring-amber-300' : ''}`}
                    style={{ borderColor: checked ? 'rgb(252 211 77)' : 'var(--app-border)', background: checked ? 'rgba(245,158,11,0.10)' : 'var(--app-surface-muted)', color: 'var(--app-text)' }}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 accent-amber-500"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => toggleCapture(capture.capture_id)}
                      onClick={(event) => event.stopPropagation()}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="font-semibold">{capture.transmitter.transmitter_id || capture.transmitter.transmitter_label}</div>
                        {checked && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">selected</span>}
                        {disabledReason && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-semibold text-slate-700">{disabledReason}</span>}
                      </div>
                      <div className="mt-1 text-xs app-muted-text">
                        {capture.transmitter.transmitter_class} - {capture.session_id} - {capture.quality_review.status}
                      </div>
                      <div className="mt-2 text-xs app-muted-text">
                        {formatFrequency(capture.capture_config.center_frequency_hz)} - SNR {formatDb(capture.quality_metrics.estimated_snr_db)}
                      </div>
                      <div className="mt-2 text-xs app-muted-text">created {formatTimestamp(capture.created_at_utc)}</div>
                    </div>
                  </div>
                );
              })}
              {captures.length === 0 && <div className="text-sm app-muted-text">No captures marked as val found.</div>}
            </div>
          </section>

          <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Validation result summary</div>
            {status?.report ? (
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div className="app-surface-muted rounded-2xl p-4">
                  <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Primary metrics</div>
                  <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                    <div>Accuracy: {(reportSummary?.accuracy ?? 0).toFixed(3)}</div>
                    <div>Macro F1: {(reportSummary?.macroF1 ?? 0).toFixed(3)}</div>
                    <div>Balanced accuracy: {(reportSummary?.balancedAccuracy ?? 0).toFixed(3)}</div>
                    <div>Total windows: {reportSummary?.totalWindows ?? 0}</div>
                  </div>
                </div>
                <div className="app-surface-muted rounded-2xl p-4">
                  <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Artifact summary</div>
                  <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                    <div>Model dir: {form.model_dir}</div>
                    <div>Validation root: {form.val_root}</div>
                    <div>Selected captures: {selectedCaptures.length}</div>
                    <div>Report size: {formatFileSize(JSON.stringify(status.report).length)}</div>
                  </div>
                </div>
                <pre className="md:col-span-2 h-72 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
                  {JSON.stringify(status.report, null, 2)}
                </pre>
              </div>
            ) : (
              <div className="mt-4 text-sm app-muted-text">No validation report attached to the current job yet.</div>
            )}
          </section>

          <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Stored validation reports</div>
            <div className="mt-4 space-y-3">
              {reports.map((report, index) => {
                const reportMetrics = summarizeReport(report);
                return (
                  <div key={index} className="app-surface-muted rounded-2xl p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>Validation report {index + 1}</div>
                      <div className="text-xs app-muted-text">
                        acc {(reportMetrics.accuracy * 100).toFixed(1)}% · macro-F1 {reportMetrics.macroF1.toFixed(3)}
                      </div>
                    </div>
                    <pre className="mt-3 h-48 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-slate-100">
                      {JSON.stringify(report, null, 2)}
                    </pre>
                  </div>
                );
              })}
              {reports.length === 0 && <div className="text-sm app-muted-text">No validation reports found.</div>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
