import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, PaperRunRecord } from '../../../app/services/bleScientificResultsApi';

const sciApi = new BleScientificResultsApiService();

/** Read-only run picker for the paper progress dashboard tabs -- lists real
 * paper runs and lets the user select one, with NO build/mutate action
 * (unlike useRunRecords, which also exposes buildRecords()). These tabs
 * only ever read already-built artifacts. */
export function useReadOnlyRuns() {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (!paperRunId && list.length > 0) setPaperRunId(list[0].paper_run_id);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }).catch(() => setRuns([]));
  }, []);

  return { runs, paperRunId, setPaperRunId };
}

export const READ_ONLY_PICKER_CLASS =
  'w-full max-w-md rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none';
