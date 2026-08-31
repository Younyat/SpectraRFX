import { useEffect, useRef } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { useAppActions } from '../../app/store/AppStore';
import type { AsyncJobStatus } from '../../shared/types';

const api = new ApiService();
const POLL_INTERVAL_MS = 2000;
const ACTIVE_STATUSES = new Set(['running', 'starting', 'queued', 'pending']);

type JobDescriptor = {
  label: string;
  storageKey: string;
  title: string;
  getStatus: (jobId?: string) => Promise<AsyncJobStatus>;
};

const jobs: JobDescriptor[] = [
  {
    label: 'Training',
    storageKey: 'rfp.training.jobId',
    title: 'Training execution in progress',
    getStatus: (jobId) => api.getTrainingStatus(jobId),
  },
  {
    label: 'Retraining',
    storageKey: 'rfp.retraining.jobId',
    title: 'Retraining execution in progress',
    getStatus: (jobId) => api.getTrainingStatus(jobId),
  },
  {
    label: 'Validation',
    storageKey: 'rfp.validation.jobId',
    title: 'Validation execution in progress',
    getStatus: (jobId) => api.getValidationStatus(jobId),
  },
  {
    label: 'Prediction',
    storageKey: 'rfp.inference.jobId',
    title: 'Prediction execution in progress',
    getStatus: (jobId) => api.getPredictionStatus(jobId),
  },
];

const isActive = (status?: AsyncJobStatus | null) => status ? ACTIVE_STATUSES.has(String(status.status).toLowerCase()) : false;

const formatStarted = (value?: string | null) => {
  if (!value) return 'started time pending';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `started ${date.toLocaleTimeString()}`;
};

export const usePersistentJobActivity = () => {
  const { setGlobalActivity, clearGlobalActivity } = useAppActions();
  const activeJobRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const scheduleNextPoll = () => {
      if (!cancelled) {
        if (timer !== null) window.clearTimeout(timer);
        timer = window.setTimeout(poll, POLL_INTERVAL_MS);
      }
    };

    const poll = async () => {
      try {
        const candidates = jobs
          .map((job) => ({ ...job, jobId: window.localStorage.getItem(job.storageKey) ?? undefined }))
          .filter((job) => Boolean(job.jobId));

        const results = await Promise.allSettled(
          candidates.map(async (job) => ({ job, status: await job.getStatus(job.jobId) })),
        );

        if (cancelled) return;

        const active = results.flatMap((result) => {
          if (result.status !== 'fulfilled') return [];
          return isActive(result.value.status) ? [result.value] : [];
        });

        if (active.length > 0) {
          const current = active[0];
          const otherCount = active.length - 1;
          activeJobRef.current = `${current.job.label}:${current.status.job_id ?? current.job.jobId ?? 'unknown'}`;
          setGlobalActivity({
            visible: true,
            kind: 'processing',
            title: current.job.title,
            detail: [
              `job ${current.status.job_id ?? current.job.jobId ?? 'unknown'}`,
              formatStarted(current.status.started_at_utc),
              otherCount > 0 ? `+${otherCount} more execution${otherCount > 1 ? 's' : ''}` : null,
            ].filter(Boolean).join(' - '),
          });
        } else if (activeJobRef.current !== null && candidates.length === 0) {
          activeJobRef.current = null;
          clearGlobalActivity();
        } else if (activeJobRef.current !== null && results.every((result) => result.status === 'fulfilled')) {
          activeJobRef.current = null;
          clearGlobalActivity();
        }
      } catch (error) {
        console.error('Persistent job activity polling failed', error);
      } finally {
        scheduleNextPoll();
      }
    };

    const pollNow = () => {
      if (timer !== null) window.clearTimeout(timer);
      void poll();
    };

    window.addEventListener('rfp-job-started', pollNow);
    window.addEventListener('storage', pollNow);
    poll();

    return () => {
      cancelled = true;
      window.removeEventListener('rfp-job-started', pollNow);
      window.removeEventListener('storage', pollNow);
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [clearGlobalActivity, setGlobalActivity]);
};
