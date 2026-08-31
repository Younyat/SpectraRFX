import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { useAppActions } from '../../app/store/AppStore';
import { AsyncJobStatus, FingerprintingCaptureRecord } from '../../shared/types';
import { RUNTIME_CONFIG } from '../../shared/config/runtime';
import { formatFileSize, formatFrequency } from '../../shared/utils';

const api = new ApiService();
const JOB_STORAGE_KEY = 'rfp.inference.jobId';
const CAPTURE_STORAGE_KEY = 'rfp.inference.captureId';

const formatTimestamp = (value?: string | null) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const getErrorDetail = (error: unknown): string => {
  const detail = (error as any)?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (typeof (error as any)?.message === 'string' && (error as any).message.trim()) return (error as any).message;
  return 'Prediction request failed.';
};

const formatPercent = (value?: number | null) => (Number.isFinite(value) ? `${(Number(value) * 100).toFixed(2)}%` : 'n/a');
const formatDecimal = (value?: number | null, digits = 3) => (Number.isFinite(value) ? Number(value).toFixed(digits) : 'n/a');
const formatRiskLabel = (value?: string | null) => (value && value.trim() ? value.split('_').join(' ') : 'none');

type PredictionReport = {
  input?: {
    cfile_path?: string;
    metadata_path?: string;
    num_iq_samples?: number;
    window_size?: number;
    stride?: number;
    num_windows?: number;
  };
  prediction?: {
    predicted_device?: string;
    nearest_profile_device?: string;
    is_known?: boolean;
    is_verified_prediction?: boolean;
    predicted_probability_mean?: number;
    probability_entropy?: number;
    probability_peak_to_second?: number;
    distance_to_predicted_profile?: number;
    predicted_threshold?: number;
    nearest_profile_distance?: number;
    nearest_profile_threshold?: number;
    distance_margin_to_second_profile?: number;
    vote_distribution?: Record<string, number>;
    class_probability_mean?: Record<string, number>;
    all_profile_distances?: Record<string, number>;
  };
  scientific_interpretation?: {
    prediction_confidence_level?: string;
    risk_flags?: string[];
  };
  ground_truth_comparison?: {
    has_ground_truth?: boolean;
    true_device?: string;
    closed_set_match?: boolean;
    nearest_profile_match?: boolean;
  };
  metadata?: Record<string, unknown>;
};

const sortNumericEntries = (values: Record<string, number> | undefined) =>
  Object.entries(values ?? {}).sort((a, b) => b[1] - a[1]);

export const InferenceLabView: React.FC = () => {
  const { setGlobalActivity } = useAppActions();
  const [captures, setCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [status, setStatus] = useState<AsyncJobStatus | null>(null);
  const [lastRefresh, setLastRefresh] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const [selectedCaptureId, setSelectedCaptureId] = useState<string>(() => localStorage.getItem(CAPTURE_STORAGE_KEY) || '');
  const pollRef = useRef<number | null>(null);
  const [form, setForm] = useState({
    cfile_path: '',
    metadata_path: '',
    model_dir: 'remote_trained_model',
    output_json: 'inference/prediction_report.json',
    batch_size: 256,
    python_exe: RUNTIME_CONFIG.radioCondaPython,
  });

  const selectedCapture = useMemo(
    () => captures.find((capture) => capture.capture_id === selectedCaptureId) ?? null,
    [captures, selectedCaptureId],
  );

  const report = useMemo(() => (status?.report ?? null) as PredictionReport | null, [status?.report]);
  const probabilityRanking = useMemo(
    () => sortNumericEntries(report?.prediction?.class_probability_mean).slice(0, 5),
    [report?.prediction?.class_probability_mean],
  );
  const distanceRanking = useMemo(
    () => sortNumericEntries(report?.prediction?.all_profile_distances).reverse().slice(0, 5).reverse(),
    [report?.prediction?.all_profile_distances],
  );
  const voteRanking = useMemo(
    () => sortNumericEntries(report?.prediction?.vote_distribution),
    [report?.prediction?.vote_distribution],
  );

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  };

  const refresh = async (jobId?: string | null) => {
    const [predictCaptures, predictionStatus] = await Promise.all([
      api.getPredictionCaptures(),
      api.getPredictionStatus(jobId ?? undefined),
    ]);
    setCaptures(predictCaptures);
    setSelectedCaptureId((current) => {
      if (current && predictCaptures.some((capture) => capture.capture_id === current)) return current;
      return predictCaptures[0]?.capture_id ?? '';
    });
    setStatus(predictionStatus);
    setLastRefresh(new Date().toISOString());
    if (predictionStatus?.job_id) {
      localStorage.setItem(JOB_STORAGE_KEY, predictionStatus.job_id);
      window.dispatchEvent(new CustomEvent('rfp-job-started'));
    }
    return predictionStatus;
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
        console.error('Prediction polling failed', error);
      }
    }, 2000);
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem(JOB_STORAGE_KEY);
    refresh(savedJobId)
      .then((predictionStatus) => {
        if (predictionStatus.status === 'running' && predictionStatus.job_id) {
          schedulePoll(predictionStatus.job_id);
        }
      })
      .catch((error) => console.error('Failed to load inference lab', error));
    return () => stopPolling();
  }, []);

  useEffect(() => {
    if (!selectedCaptureId) return;
    localStorage.setItem(CAPTURE_STORAGE_KEY, selectedCaptureId);
  }, [selectedCaptureId]);

  useEffect(() => {
    if (!selectedCapture) return;
    setForm((current) => ({
      ...current,
      cfile_path: selectedCapture.artifacts.iq_file || '',
      metadata_path: selectedCapture.artifacts.metadata_file || '',
    }));
  }, [selectedCapture]);

  useEffect(() => {
    if (status?.status === 'running') {
      setGlobalActivity({
        visible: true,
        kind: 'processing',
        title: 'Prediction job running',
        detail: selectedCapture
          ? `${selectedCapture.transmitter.transmitter_id || selectedCapture.transmitter.transmitter_label} · ${formatFrequency(selectedCapture.capture_config.center_frequency_hz)}`
          : `model ${form.model_dir} · evaluating capture`,
      });
      return;
    }
  }, [form.model_dir, selectedCapture, setGlobalActivity, status?.status]);

  const launchPrediction = async () => {
    if (selectedCapture && selectedCapture.prediction_ready === false) {
      setErrorMessage(selectedCapture.prediction_ready_reason || 'Selected predict capture is not ready for prediction.');
      return;
    }
    if (!form.cfile_path.trim()) {
      setErrorMessage('Select a predict capture or provide a valid cfile_path.');
      return;
    }
    setIsLaunching(true);
    setErrorMessage('');
    try {
      const result = await api.startPrediction({
        ...form,
        python_exe: form.python_exe.trim(),
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
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-700">Inference Lab</div>
        <h1 className="mt-2 font-serif text-4xl" style={{ color: 'var(--app-text)' }}>
          Scientific prediction report for new captures
        </h1>
        <p className="mt-3 max-w-4xl text-sm leading-7 app-muted-text">
          Prediction uses the trained fingerprint model, keeps the asynchronous job attached across navigation, and translates the raw
          report into a structured scientific interpretation with confidence, profile distances, vote stability, and traceability.
        </p>
        <p className="mt-2 text-sm app-muted-text">Last UI refresh: {formatTimestamp(lastRefresh)}</p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.92fr_1.08fr]">
        <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="mb-4 rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-900">
            Start Prediction launches an asynchronous inference job over the current model artifacts under `remote_trained_model`.
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {['cfile_path', 'metadata_path', 'model_dir', 'output_json', 'python_exe'].map((field) => (
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
                min={1}
                value={form.batch_size}
                onChange={(e) => setForm((current) => ({ ...current, batch_size: Number(e.target.value) }))}
              />
            </label>
          </div>

          <div className="app-surface-muted mt-4 rounded-2xl p-4 text-sm">
            Python default detected: {form.python_exe || 'backend default / RADIOCONDA_PYTHON'}.
            Leave it empty to let the backend use its default interpreter.
          </div>

          {errorMessage && (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{errorMessage}</div>
          )}

          <div className="mt-5 flex gap-3">
            <button
              className="rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => launchPrediction()}
              disabled={isLaunching || status?.status === 'running'}
            >
              {status?.status === 'running' ? 'Prediction Running...' : isLaunching ? 'Launching...' : 'Start Prediction'}
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
                <div className="text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">Prediction Job</div>
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
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">stdout</div>
                <pre className="h-56 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-slate-100">{status?.stdout || 'No stdout yet.'}</pre>
              </div>
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">stderr</div>
                <pre className="h-40 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-rose-200">{status?.stderr || 'No stderr.'}</pre>
              </div>
            </div>
          </div>
        </section>

        <div className="space-y-5">
          <section className="grid gap-4 md:grid-cols-4">
            {[
              ['Confidence level', report?.scientific_interpretation?.prediction_confidence_level ?? 'n/a'],
              ['Known device', report?.prediction?.is_known ? 'yes' : report ? 'no' : 'n/a'],
              ['Mean class prob.', formatPercent(report?.prediction?.predicted_probability_mean)],
              ['Distance margin', formatDecimal(report?.prediction?.distance_margin_to_second_profile)],
            ].map(([label, value]) => (
              <div key={String(label)} className="app-surface-strong rounded-[1.5rem] p-5">
                <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{label}</div>
                <div className="mt-3 text-2xl font-semibold" style={{ color: 'var(--app-text)' }}>{value}</div>
              </div>
            ))}
          </section>

          <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Scientific interpretation</div>
            {report ? (
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div className="app-surface-muted rounded-2xl p-4">
                  <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Decision summary</div>
                  <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                    <div>Predicted device: {report.prediction?.predicted_device ?? 'n/a'}</div>
                    <div>Nearest profile: {report.prediction?.nearest_profile_device ?? 'n/a'}</div>
                    <div>Verified prediction: {report.prediction?.is_verified_prediction ? 'yes' : 'no'}</div>
                    <div>Ground truth available: {report.ground_truth_comparison?.has_ground_truth ? 'yes' : 'no'}</div>
                  </div>
                </div>
                <div className="app-surface-muted rounded-2xl p-4">
                  <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Confidence and uncertainty</div>
                  <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                    <div>Probability entropy: {formatDecimal(report.prediction?.probability_entropy)}</div>
                    <div>Peak-to-second probability: {formatDecimal(report.prediction?.probability_peak_to_second)}</div>
                    <div>Distance to predicted profile: {formatDecimal(report.prediction?.distance_to_predicted_profile)}</div>
                    <div>Threshold at predicted profile: {formatDecimal(report.prediction?.predicted_threshold)}</div>
                  </div>
                </div>
                <div className="app-surface-muted rounded-2xl p-4 md:col-span-2">
                  <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Risk flags</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(report.scientific_interpretation?.risk_flags ?? []).length > 0 ? (
                      (report.scientific_interpretation?.risk_flags ?? []).map((flag) => (
                        <span key={flag} className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">
                          {formatRiskLabel(flag)}
                        </span>
                      ))
                    ) : (
                      <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-900">no risk flags raised</span>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-4 text-sm app-muted-text">No prediction report attached yet.</div>
            )}
          </section>

          <section className="grid gap-5 lg:grid-cols-2">
            <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Class probability ranking</div>
              <div className="mt-4 space-y-3">
                {probabilityRanking.map(([label, value]) => (
                  <div key={label} className="app-surface-muted rounded-2xl p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{label}</div>
                      <div className="text-sm font-semibold text-emerald-700">{formatPercent(value)}</div>
                    </div>
                    <div className="mt-3 h-2 rounded-full bg-slate-200">
                      <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${Math.max(2, Number(value) * 100)}%` }} />
                    </div>
                  </div>
                ))}
                {probabilityRanking.length === 0 && <div className="text-sm app-muted-text">No probability distribution available.</div>}
              </div>
            </div>

            <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Profile distance ranking</div>
              <div className="mt-4 space-y-3">
                {distanceRanking.map(([label, value]) => (
                  <div key={label} className="app-surface-muted rounded-2xl p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{label}</div>
                      <div className="text-sm font-semibold text-sky-700">{formatDecimal(value)}</div>
                    </div>
                  </div>
                ))}
                {distanceRanking.length === 0 && <div className="text-sm app-muted-text">No profile distance information available.</div>}
              </div>
            </div>
          </section>

          <section className="grid gap-5 lg:grid-cols-2">
            <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Window vote distribution</div>
              <div className="mt-4 space-y-3">
                {voteRanking.map(([label, value]) => (
                  <div key={label} className="app-surface-muted rounded-2xl p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{label}</div>
                      <div className="text-sm font-semibold" style={{ color: 'var(--app-text)' }}>{value} windows</div>
                    </div>
                  </div>
                ))}
                {voteRanking.length === 0 && <div className="text-sm app-muted-text">No vote distribution available.</div>}
              </div>
            </div>

            <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Traceability and acquisition context</div>
              <div className="mt-4 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                <div>Capture file: {report?.input?.cfile_path || form.cfile_path || 'n/a'}</div>
                <div>Metadata file: {report?.input?.metadata_path || form.metadata_path || 'n/a'}</div>
                <div>IQ samples: {report?.input?.num_iq_samples?.toLocaleString?.() ?? 'n/a'}</div>
                <div>Windows: {report?.input?.num_windows?.toLocaleString?.() ?? 'n/a'}</div>
                <div>Window size / stride: {report?.input?.window_size ?? 'n/a'} / {report?.input?.stride ?? 'n/a'}</div>
                <div>Raw report size: {report ? formatFileSize(JSON.stringify(report).length) : 'n/a'}</div>
              </div>
            </div>
          </section>

          <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Predict capture inventory</div>
              <div className="text-xs app-muted-text">{captures.length} captures</div>
            </div>
            <div className="mb-4 rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-900">
              Source: inference backend inventory from the fingerprinting registry filtered by `dataset_split = predict`. Missing IQ artifacts are flagged before launch.
            </div>
            <div className="space-y-3">
              {captures.map((capture) => {
                const active = capture.capture_id === selectedCaptureId;
                const ready = capture.prediction_ready !== false;
                return (
                  <button
                    key={capture.capture_id}
                    type="button"
                    onClick={() => setSelectedCaptureId(capture.capture_id)}
                    className="w-full rounded-2xl border p-4 text-left"
                    style={{
                      borderColor: active ? 'rgb(52 211 153)' : 'var(--app-border)',
                      background: active ? 'rgba(16,185,129,0.10)' : 'var(--app-surface-muted)',
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{capture.transmitter.transmitter_id || capture.transmitter.transmitter_label}</div>
                        <div className="mt-1 text-xs app-muted-text">
                          {capture.transmitter.transmitter_class} · {capture.session_id} · {capture.quality_review.status}
                        </div>
                        <div className="mt-2 text-xs app-muted-text">
                          {formatFrequency(capture.capture_config.center_frequency_hz)} · SNR {formatDecimal(capture.quality_metrics.estimated_snr_db, 2)} dB
                        </div>
                        <div className="mt-2 text-xs app-muted-text">
                          created {formatTimestamp(capture.created_at_utc)}
                        </div>
                        {!ready && (
                          <div className="mt-2 rounded-xl border border-amber-300/50 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                            {capture.prediction_ready_reason || 'IQ artifact is missing or not reachable'}
                          </div>
                        )}
                      </div>
                      <div className="rounded-full bg-white/80 px-3 py-1 text-xs font-semibold text-slate-700">
                        {!ready ? 'missing IQ' : active ? 'selected' : 'use'}
                      </div>
                    </div>
                  </button>
                );
              })}
              {captures.length === 0 && <div className="text-sm app-muted-text">No captures marked as predict found.</div>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
