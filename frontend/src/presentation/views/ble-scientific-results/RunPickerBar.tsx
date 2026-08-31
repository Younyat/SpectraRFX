import { PaperRunRecord, RecordsStatusResponse } from '../../../app/services/bleScientificResultsApi';
import { RUN_PICKER_CLASS } from './useRunRecords';

export default function RunPickerBar({
  runs, paperRunId, setPaperRunId, status, building, buildRecords, error,
}: {
  runs: PaperRunRecord[]; paperRunId: string; setPaperRunId: (id: string) => void;
  status: RecordsStatusResponse | null; building: boolean; buildRecords: () => void; error: string | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-900/40 p-3">
      <select className={RUN_PICKER_CLASS + ' max-w-md'} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
        <option value="">Selecciona una ejecucion (paper_run_id)...</option>
        {runs.map((run) => (
          <option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id} -- {run.dataset_id}</option>
        ))}
      </select>
      <button
        className="rounded bg-cyan-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={!paperRunId || building}
        onClick={buildRecords}
      >
        {building ? 'Construyendo...' : status?.built ? 'Reconstruir registros' : 'Construir registros'}
      </button>
      {status && (
        <span className="text-xs text-slate-500">
          {status.built ? `capturas=${status.capture_record_count} bursts=${status.burst_record_count} ventanas=${status.decision_window_record_count} desviaciones=${status.campaign_deviation_count}` : 'Aun no construidos para esta ejecucion.'}
        </span>
      )}
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  );
}
