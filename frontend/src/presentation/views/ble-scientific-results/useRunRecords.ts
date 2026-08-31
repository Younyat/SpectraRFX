import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, PaperRunRecord, RecordsStatusResponse } from '../../../app/services/bleScientificResultsApi';

const sciApi = new BleScientificResultsApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

/** Shared by the Campaign / Integrity and Leakage / Acquisition Quality
 * tabs: pick a paper_run_id, check whether its canonical records were
 * already built, and (re)build them (records + campaign accounting +
 * quality summary + figures, in one async job) -- same pattern each of
 * those three tabs needs, so it lives in one place instead of being
 * copied three times. */
export function useRunRecords() {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [status, setStatus] = useState<RecordsStatusResponse | null>(null);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    sciApi.listRuns().then(setRuns).catch(() => setRuns([]));
  }, []);

  useEffect(() => {
    if (!paperRunId) {
      setStatus(null);
      return;
    }
    sciApi.recordsStatus(paperRunId).then(setStatus).catch(() => setStatus(null));
  }, [paperRunId]);

  const buildRecords = async () => {
    if (!paperRunId) return;
    setBuilding(true);
    setError(null);
    try {
      let job = await sciApi.startBuildRecords(paperRunId);
      while (!JOB_TERMINAL.has(job.state)) {
        await new Promise((resolve) => setTimeout(resolve, 800));
        job = await sciApi.getJob(job.job_id);
      }
      if (job.state === 'failed') {
        setError(job.error || 'La construccion de registros fallo.');
      }
      const nextStatus = await sciApi.recordsStatus(paperRunId);
      setStatus(nextStatus);
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'No se pudo construir los registros.');
    } finally {
      setBuilding(false);
    }
  };

  return { runs, paperRunId, setPaperRunId, status, building, buildRecords, error };
}

export const RUN_PICKER_CLASS = 'w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none';
