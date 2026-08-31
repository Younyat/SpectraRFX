import { useCallback, useEffect, useState } from 'react';
import { BleScientificResultsApiService, ScientificCompletenessReport } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

/** Paper-representation pass (2026-08-17) -- ONE artifact answering "what
 * does the paper still need, and what is its real status": AVAILABLE /
 * PENDING_REAL_ACQUISITION / BLOCKED / NOT_ELIGIBLE / PROTECTED, with a
 * real reason and missing-evidence list per item. Composes
 * get_paper_readiness() + get_analysis_contract_readiness() + RQ3/RQ4/
 * association status server-side -- this tab renders that composition
 * verbatim, never disguising a real BLOCKED/NOT_ELIGIBLE state (e.g. 0
 * STRONG associations, no accepted calibration policy) as anything softer. */
export default function ScientificCompletenessTab() {
  const [report, setReport] = useState<ScientificCompletenessReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    sciApi.scientificCompleteness()
      .then(setReport)
      .catch(() => setError('No se pudo cargar el reporte de completitud cientifica.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-slate-200">Scientific Completeness -- que le falta al paper y por que</div>
          <div className="mt-1 text-xs text-slate-500">
            Un item por elemento del manuscrito con su estado real: AVAILABLE, PENDING_REAL_ACQUISITION, BLOCKED,
            NOT_ELIGIBLE o PROTECTED, mas la razon y la evidencia faltante exacta. Preserva la distincion
            "implementado" vs "experimentalmente validado" -- nunca disimula un BLOCKED/NOT_ELIGIBLE real.
          </div>
        </div>
        <button
          type="button" onClick={load} disabled={loading}
          className="shrink-0 rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? 'Actualizando…' : 'Refrescar'}
        </button>
      </div>

      {error && <NoDataNotice reason={error} />}

      {report && (
        <>
          <div className="font-mono text-[10.5px] text-slate-500">generated_at={report.generated_at} · git_sha={report.git_sha ?? '—'}</div>

          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">item</th>
                  <th className="px-3 py-2 text-left">status</th>
                  <th className="px-3 py-2 text-left">reason</th>
                  <th className="px-3 py-2 text-left">missing evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {report.items.map((item) => (
                  <tr key={item.item}>
                    <td className="px-3 py-2 font-mono text-slate-300">{item.item}</td>
                    <td className="px-3 py-2"><StatusBadge status={item.status} /></td>
                    <td className="px-3 py-2 text-slate-400">{item.reason}</td>
                    <td className="px-3 py-2 text-slate-400">
                      {item.missing_evidence.length === 0 ? '—' : (
                        <ul className="list-disc space-y-0.5 pl-4">
                          {item.missing_evidence.map((evidence, idx) => <li key={idx}>{evidence}</li>)}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
