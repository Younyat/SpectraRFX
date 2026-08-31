import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { useAppActions } from '../../app/store/AppStore';
import { AsyncJobStatus, FingerprintingCaptureRecord } from '../../shared/types';
import { RUNTIME_CONFIG } from '../../shared/config/runtime';
import { formatFrequency } from '../../shared/utils';

const api = new ApiService();
const JOB_STORAGE_KEY = 'rfp.retraining.jobId';

const formatTimestamp = (value?: string | null) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const getErrorDetail = (error: unknown): string => {
  const detail = (error as any)?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (typeof (error as any)?.message === 'string' && (error as any).message.trim()) return (error as any).message;
  return 'Retraining request failed.';
};

type FrequencyOption = {
  centerHz: number;
  count: number;
  transmitters: string[];
  sampleRates: number[];
};

const buildFrequencyOptions = (captures: FingerprintingCaptureRecord[]): FrequencyOption[] => {
  const buckets = new Map<number, { count: number; transmitters: Set<string>; sampleRates: Set<number> }>();
  captures.forEach((capture) => {
    if (capture.quality_review.status !== 'valid') return;
    const centerHz = capture.capture_config.center_frequency_hz;
    if (!Number.isFinite(centerHz)) return;
    const transmitterId = capture.transmitter.transmitter_id || capture.transmitter.transmitter_label;
    const sampleRate = capture.capture_config.sample_rate_hz;
    const current = buckets.get(centerHz) ?? { count: 0, transmitters: new Set<string>(), sampleRates: new Set<number>() };
    current.count += 1;
    if (transmitterId) current.transmitters.add(transmitterId);
    if (Number.isFinite(sampleRate)) current.sampleRates.add(sampleRate);
    buckets.set(centerHz, current);
  });
  return Array.from(buckets.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([centerHz, bucket]) => ({
      centerHz,
      count: bucket.count,
      transmitters: Array.from(bucket.transmitters).sort(),
      sampleRates: Array.from(bucket.sampleRates).sort((a, b) => a - b),
    }));
};

export const RetrainingLabView: React.FC = () => {
  const { setGlobalActivity } = useAppActions();
  const [captures, setCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [status, setStatus] = useState<AsyncJobStatus | null>(null);
  const [lastRefresh, setLastRefresh] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const pollRef = useRef<number | null>(null);
  const [form, setForm] = useState({
    remote_user: RUNTIME_CONFIG.remoteUser,
    remote_host: RUNTIME_CONFIG.remoteHost,
    remote_venv_activate: RUNTIME_CONFIG.remoteVenvActivate,
    target_center_frequency_hz: '',
    epochs: 10,
    batch_size: 128,
    window_size: 1024,
    stride: 1024,
    local_dataset_dir: 'rf_dataset',
    local_output_dir: 'remote_trained_model',
  });

  const frequencyOptions = useMemo(() => buildFrequencyOptions(captures), [captures]);
  const selectedFrequency = useMemo(
    () => frequencyOptions.find((item) => String(item.centerHz) === form.target_center_frequency_hz) ?? null,
    [frequencyOptions, form.target_center_frequency_hz],
  );

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  };

  const refresh = async (jobId?: string | null) => {
    const [trainCaptures, trainingStatus] = await Promise.all([
      api.getFingerprintingCaptures('train'),
      api.getTrainingStatus(jobId ?? undefined),
    ]);
    setCaptures(trainCaptures);
    setStatus(trainingStatus);
    setLastRefresh(new Date().toISOString());
    if (trainingStatus?.job_id) {
      localStorage.setItem(JOB_STORAGE_KEY, trainingStatus.job_id);
      window.dispatchEvent(new CustomEvent('rfp-job-started'));
    }
    return trainingStatus;
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
        console.error('Retraining polling failed', error);
      }
    }, 2000);
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem(JOB_STORAGE_KEY);
    refresh(savedJobId)
      .then((trainingStatus) => {
        if (trainingStatus.status === 'running' && trainingStatus.job_id) {
          schedulePoll(trainingStatus.job_id);
        }
      })
      .catch((error) => console.error('Failed to load retraining lab', error));
    return () => stopPolling();
  }, []);

  useEffect(() => {
    if (frequencyOptions.length === 1 && !form.target_center_frequency_hz) {
      setForm((current) => ({ ...current, target_center_frequency_hz: String(frequencyOptions[0].centerHz) }));
    }
  }, [frequencyOptions, form.target_center_frequency_hz]);

  useEffect(() => {
    if (status?.status === 'running') {
      setGlobalActivity({
        visible: true,
        kind: 'processing',
        title: 'Retraining job running',
        detail: selectedFrequency
          ? `${formatFrequency(selectedFrequency.centerHz)} · ${selectedFrequency.count} captures · ${selectedFrequency.transmitters.length} transmitters`
          : `job ${status.job_id ?? 'pending'} · rebuilding model with current train campaign`,
      });
      return;
    }
  }, [selectedFrequency, setGlobalActivity, status?.job_id, status?.status]);

  const launchRetrain = async () => {
    setIsLaunching(true);
    setErrorMessage('');
    try {
      const result = await api.retrainModel({
        ...form,
        target_center_frequency_hz: form.target_center_frequency_hz.trim() || undefined,
      });
      setStatus(result);
      if (result.job_id) {
        localStorage.setItem(JOB_STORAGE_KEY, result.job_id);
        window.dispatchEvent(new CustomEvent('rfp-job-started'));
        schedulePoll(result.job_id);
      }
      await refresh(result.job_id);
    } catch (error) {
      setErrorMessage(getErrorDetail(error));
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <div className="app-page p-6">
      <div className="mb-6">
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-700">Retraining Lab</div>
        <h1 className="mt-2 font-serif text-4xl" style={{ color: 'var(--app-text)' }}>
          Continual retraining on the unified train registry
        </h1>
        <p className="mt-3 max-w-4xl text-sm leading-7 app-muted-text">
          Retraining reuses the curated `train + valid` registry, keeps the same scientific homogeneity checks as fresh training,
          and preserves the asynchronous job state across navigation.
        </p>
        <p className="mt-2 text-sm app-muted-text">Last UI refresh: {formatTimestamp(lastRefresh)}</p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="grid gap-4 md:grid-cols-2">
            {['remote_user', 'remote_host', 'remote_venv_activate', 'local_dataset_dir', 'local_output_dir'].map((field) => (
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
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] app-muted-text">target_center_frequency_hz</div>
              <select
                className="mt-2 w-full rounded-2xl border px-3 py-2 text-sm"
                style={{ background: 'var(--app-surface-muted)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
                value={form.target_center_frequency_hz}
                onChange={(e) => setForm((current) => ({ ...current, target_center_frequency_hz: e.target.value }))}
              >
                <option value="">All valid train frequencies</option>
                {frequencyOptions.map((option) => (
                  <option key={option.centerHz} value={String(option.centerHz)}>
                    {formatFrequency(option.centerHz)} · {option.count} valid captures
                  </option>
                ))}
              </select>
            </label>
            {['epochs', 'batch_size', 'window_size', 'stride'].map((field) => (
              <label key={field}>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] app-muted-text">{field}</div>
                <input
                  className="mt-2 w-full rounded-2xl border px-3 py-2 text-sm"
                  style={{ background: 'var(--app-surface-muted)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
                  type="number"
                  value={Number((form as Record<string, unknown>)[field] ?? 0)}
                  onChange={(e) => setForm((current) => ({ ...current, [field]: Number(e.target.value) }))}
                />
              </label>
            ))}
          </div>

          <div className="app-surface-muted mt-4 rounded-2xl p-4 text-sm">
            `remote_venv_activate` can stay empty. Recommended legacy remote venv:
            {' '}
            {RUNTIME_CONFIG.remoteVenvActivate || '/home/assouyat/rfenv/bin/activate'}.
            Retraining uses only `train + valid` captures and keeps the same scientific prechecks as fresh training.
          </div>

          {selectedFrequency && (
            <div className="mt-4 rounded-2xl border border-violet-100 bg-violet-50 p-4 text-sm text-violet-900">
              Selected campaign: {formatFrequency(selectedFrequency.centerHz)} · {selectedFrequency.count} captures ·{' '}
              {selectedFrequency.transmitters.length} transmitters · {selectedFrequency.sampleRates.length} sample rates
            </div>
          )}

          {errorMessage && (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{errorMessage}</div>
          )}

          <div className="mt-5 flex gap-3">
            <button
              className="rounded-full bg-violet-600 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => launchRetrain()}
              disabled={isLaunching || status?.status === 'running'}
            >
              {status?.status === 'running' ? 'Retraining Running...' : isLaunching ? 'Launching...' : 'Launch Retraining'}
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
            <div className="text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">Retraining Job</div>
            <div className="mt-3 text-lg font-semibold" style={{ color: 'var(--app-text)' }}>
              {status?.status ?? 'not_found'}
            </div>
            <div className="mt-2 text-xs app-muted-text">
              job_id: {status?.job_id ?? localStorage.getItem(JOB_STORAGE_KEY) ?? 'none'} · started {formatTimestamp(status?.started_at_utc)} · ended {formatTimestamp(status?.ended_at_utc)}
            </div>
            <div className="mt-4 grid gap-4">
              <pre className="h-80 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-slate-100">{status?.stdout || 'No stdout yet.'}</pre>
              <pre className="h-48 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-rose-200">{status?.stderr || 'No stderr.'}</pre>
            </div>
          </div>
        </section>

        <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Training campaign inventory</div>
            <div className="text-xs app-muted-text">{captures.length} captures</div>
          </div>
          <div className="mb-4 rounded-2xl border border-violet-100 bg-violet-50 p-4 text-sm text-violet-900">
            Source: fingerprinting registry filtered by `dataset_split = train`.
          </div>
          <div className="mb-4 space-y-3">
            {frequencyOptions.map((option) => (
              <button
                key={option.centerHz}
                type="button"
                onClick={() => setForm((current) => ({ ...current, target_center_frequency_hz: String(option.centerHz) }))}
                className="flex w-full items-center justify-between rounded-2xl border px-4 py-3 text-left"
                style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface-muted)' }}
              >
                <div>
                  <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{formatFrequency(option.centerHz)}</div>
                  <div className="mt-1 text-xs app-muted-text">
                    {option.count} captures · {option.transmitters.length} transmitters · {option.sampleRates.length} sample rates
                  </div>
                </div>
                <div className={`rounded-full px-3 py-1 text-xs font-semibold ${option.transmitters.length >= 2 && option.sampleRates.length === 1 ? 'bg-emerald-100 text-emerald-900' : 'bg-amber-100 text-amber-900'}`}>
                  {option.transmitters.length >= 2 && option.sampleRates.length === 1 ? 'ready' : 'not ready'}
                </div>
              </button>
            ))}
            {frequencyOptions.length === 0 && <div className="text-sm app-muted-text">No valid train captures found.</div>}
          </div>
          <div className="space-y-3">
            {captures.map((capture) => (
              <div key={capture.capture_id} className="app-surface-muted rounded-2xl p-4">
                <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{capture.transmitter.transmitter_id || capture.transmitter.transmitter_label}</div>
                <div className="mt-1 text-xs app-muted-text">
                  {capture.transmitter.transmitter_class} · {capture.session_id} · {capture.quality_review.status}
                </div>
                <div className="mt-2 text-xs app-muted-text">
                  {formatFrequency(capture.capture_config.center_frequency_hz)} · {formatFrequency(capture.capture_config.sample_rate_hz)} sample rate
                </div>
                <div className="mt-2 text-xs app-muted-text">
                  created {formatTimestamp(capture.created_at_utc)}
                </div>
              </div>
            ))}
            {captures.length === 0 && <div className="text-sm app-muted-text">No captures marked as train found.</div>}
          </div>
        </section>
      </div>
    </div>
  );
};
