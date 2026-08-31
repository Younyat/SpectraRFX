import { ReactNode, useEffect, useState } from 'react';
import { NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

type Report = Record<string, unknown> | NoDataResponse;

function isNoData(report: Report | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

/** Shared shape for every RQ1-4/coverage/sensitivity report tab: pick a
 * real paper_run_id, fetch its canonical artifact, and render it as-is --
 * this never recomputes anything, it only displays the real JSON the
 * backend already persisted. Explicit NO DATA (never blank, never 0) when
 * the artifact does not exist for the selected run.
 *
 * `renderCharts`, when supplied, renders real chart primitives above the
 * raw JSON (which stays visible, collapsed by default, for transparency --
 * charts never replace the ability to see the exact persisted numbers). It
 * receives the real report object and is never called for a NO_DATA
 * report -- each chart primitive still handles its own missing sub-fields
 * with its own NoDataNotice, since a report can be present while a
 * specific sub-field (e.g. a confusion matrix) is still absent. */
export default function RunScopedJsonReport({
  title,
  description,
  noDataReason,
  fetchReport,
  renderCharts,
}: {
  title: string;
  description: string;
  noDataReason: string;
  fetchReport: (paperRunId: string) => Promise<Report>;
  renderCharts?: (report: Record<string, unknown>, paperRunId: string) => ReactNode;
}) {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    if (!paperRunId) {
      setReport(null);
      return;
    }
    fetchReport(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperRunId]);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">{title}</div>
        <div className="mt-1 text-xs text-slate-500">{description}</div>
      </div>

      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (
            <option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>
          ))}
        </select>
      </div>

      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(report) && <NoDataNotice reason={noDataReason} />}
      {paperRunId && report && !isNoData(report) && renderCharts && (
        <div className="space-y-6">{renderCharts(report, paperRunId)}</div>
      )}
      {paperRunId && report && !isNoData(report) && (
        <details className="rounded border border-slate-800 bg-slate-950">
          <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
          <pre className="max-h-[70vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(report, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
