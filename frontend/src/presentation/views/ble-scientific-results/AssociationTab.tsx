import { useEffect, useState } from 'react';
import { AssociationCalibrationSummary, AssociationPolicyStatusResponse, BleScientificResultsApiService, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

function isNoData(summary: AssociationCalibrationSummary | NoDataResponse | null): summary is NoDataResponse {
  return !!summary && (summary as NoDataResponse).status === 'NO_DATA';
}

/** Paper-representation pass (2026-08-17) -- the real per-threshold sweep
 * from the most recent calibration attempt, shown regardless of outcome.
 * Previously this data existed only inside a stringified exception
 * message; now it is structured and always visible here, even while
 * NO_THRESHOLD_SATISFIES_CRITERIA stays the real, current status. */
function CalibrationSweepSection() {
  const [summary, setSummary] = useState<AssociationCalibrationSummary | NoDataResponse | null>(null);

  useEffect(() => {
    sciApi.associationCalibrationSummary().then(setSummary).catch(() => setSummary({ status: 'NO_DATA' }));
  }, []);

  if (!summary) return <div className="text-xs text-slate-500">Cargando...</div>;
  if (isNoData(summary)) {
    return <NoDataNotice reason="Ningun intento de calibracion se ha ejecutado todavia (ni exitoso ni fallido)." />;
  }

  const grid = summary.threshold_grid ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span>ultimo intento:</span>
        <StatusBadge status={summary.status} />
        {summary.evaluated_at && <span className="font-mono text-slate-400">{summary.evaluated_at}</span>}
      </div>
      {summary.acceptance_criterion && (
        <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-[11px] text-slate-400">
          criterio de aceptacion: {summary.acceptance_criterion}
        </div>
      )}
      {(summary.n_calibration_events !== undefined || summary.n_target_absence_events !== undefined) && (
        <div className="text-[11px] text-slate-500">
          n_calibration_events = <span className="font-mono text-slate-300">{summary.n_calibration_events ?? '—'}</span>
          {' · '}n_target_absence_events = <span className="font-mono text-slate-300">{summary.n_target_absence_events ?? '—'}</span>
        </div>
      )}
      {grid.length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">threshold_ms</th>
                <th className="px-3 py-2 text-right">coverage</th>
                <th className="px-3 py-2 text-right">false_strong</th>
                <th className="px-3 py-2 text-right">ambiguous</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {grid.map((threshold) => {
                const key = String(threshold);
                const coverage = summary.coverage_by_threshold_ms?.[key];
                const falseStrong = summary.false_strong_by_threshold_ms?.[key];
                const ambiguous = summary.ambiguous_by_threshold_ms?.[key];
                const accepted = coverage !== undefined && coverage >= (summary.minimum_coverage ?? 1) && falseStrong === 0;
                return (
                  <tr key={key} className={accepted ? 'bg-emerald-950/20' : undefined}>
                    <td className="px-3 py-2 font-mono text-slate-300">{threshold}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{coverage?.toFixed(4) ?? '—'}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{falseStrong ?? '—'}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{ambiguous ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function AssociationTab() {
  const [status, setStatus] = useState<AssociationPolicyStatusResponse | null>(null);

  useEffect(() => {
    sciApi.associationPolicyStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Association calibration</div>
        <div className="mt-1 text-xs text-slate-500">
          Estado real de find_frozen_association_policy() -- fail-closed. Nunca se recalibra desde aqui.
        </div>
      </div>

      {status && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-400">Policy state:</span>
          <StatusBadge status={status.status} />
        </div>
      )}

      {status?.status === 'NONE' && (
        <NoDataNotice reason="Ningun intento de calibracion ha producido todavia una policy FROZEN -- estado real, honesto (0 STRONG), no un error." />
      )}

      {status?.status === 'FROZEN' && status.policy && (
        <pre className="max-h-[60vh] overflow-auto rounded border border-slate-800 bg-slate-950 p-3 text-[11px] text-slate-300">
          {JSON.stringify(status.policy, null, 2)}
        </pre>
      )}

      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Real per-threshold calibration sweep (ultimo intento)</h3>
        <CalibrationSweepSection />
      </div>
    </div>
  );
}
