import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, NoDataResponse, SensitivityReport } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: SensitivityReport | NoDataResponse | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

/** Sensitivity canonical producer (2026-08-12, Scientific Closure pass) --
 * consolidates LODO (real, delta_vs_full_set added), offset-retaining
 * preprocessing (real, previously never called), and RQ2's own
 * seed_variability (REUSED verbatim, never recomputed). PRIMARY is shown
 * only as a reference baseline -- never mixed into the sensitivity
 * estimates themselves. */
export default function SensitivityTab() {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [report, setReport] = useState<SensitivityReport | NoDataResponse | null>(null);

  useEffect(() => {
    if (!paperRunId) { setReport(null); return; }
    sciApi.getSensitivityAnalysis(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Sensitivity analyses</div>
        <div className="mt-1 text-xs text-slate-500">
          Leave-one-device-out, offset-retaining preprocessing, variabilidad por semilla fija (reutilizada de RQ2) --
          real, via sensitivity_report.json (run_sensitivity_analysis). Nunca mezclado con el resultado confirmatorio
          principal de RQ1-4.
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-slate-500">
        <span>evidence maturity:</span><EvidenceMaturityBadge maturity="VALIDATION" />
        <span className="ml-2">-- nunca CONFIRMATORY.</span>
      </div>
      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>

      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(report) && <NoDataNotice reason="sensitivity_report.json no existe todavia para este run -- ejecuta Sensitivity Analysis (Study Control Center) primero." />}

      {paperRunId && report && !isNoData(report) && (
        <>
          <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
            <span className="text-slate-500">PRIMARY (referencia, rama {report.primary.branch}):</span>{' '}
            <span className="font-mono text-slate-200">BA={report.primary.balanced_accuracy?.toFixed(4) ?? 'N/A'}</span>
          </div>

          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Leave-one-device-out (delta vs full-set)</div>
            <BarWithCiChart
              data={report.leave_one_device_out.rows.filter((r) => r.estimate != null).map((r): BarWithCiDatum => ({ category: `sin ${r.omitted_physical_unit}`, value: r.estimate as number }))}
              yLabel="Balanced accuracy"
              noDataReason="Sin filas LODO reales todavia."
            />
            {report.leave_one_device_out.rows.length > 0 && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full min-w-[600px] border-collapse text-[11px]">
                  <thead><tr className="border-b border-slate-800 text-left text-slate-500"><th className="py-1 pr-2">unidad omitida</th><th className="py-1 pr-2">estimate</th><th className="py-1 pr-2">coverage</th><th className="py-1 pr-2">delta_vs_full_set</th></tr></thead>
                  <tbody>
                    {report.leave_one_device_out.rows.map((r) => (
                      <tr key={r.omitted_physical_unit} className="border-b border-slate-900 text-slate-300">
                        <td className="py-1.5 pr-2">{r.omitted_physical_unit}</td>
                        <td className="py-1.5 pr-2 font-mono">{r.estimate?.toFixed(4) ?? 'N/A'}</td>
                        <td className="py-1.5 pr-2 font-mono">{r.coverage ?? 'N/A'}</td>
                        <td className="py-1.5 pr-2 font-mono">{r.delta_vs_full_set?.toFixed(4) ?? 'N/A'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Offset-retaining preprocessing sensitivity</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3 text-[11px]">
              <div className="text-slate-500">analysis_role: <span className="font-mono text-slate-300">{report.offset_retaining.analysis_role}</span></div>
              <div className="text-slate-500">estimate (BA): <span className="font-mono text-slate-300">{report.offset_retaining.estimate?.toFixed(4) ?? 'N/A'}</span></div>
              <div className="text-slate-500">coverage: <span className="font-mono text-slate-300">{report.offset_retaining.coverage ?? 'N/A (sin regla de umbral calibrada en esta ruta de evaluacion)'}</span></div>
              <div className="text-slate-500">delta_vs_primary: <span className="font-mono text-slate-300">{report.offset_retaining.delta_vs_primary?.toFixed(4) ?? 'N/A'}</span></div>
              <div className="text-slate-500">preprocessing profile: <span className="font-mono text-slate-300">{report.offset_retaining.base_preprocessing_profile_id}</span></div>
            </div>
          </div>

          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Variabilidad por semilla fija (reutilizada de RQ2 PRIMARY -- nunca recalculada aqui)</div>
            {report.seed_variability ? (
              <BarWithCiChart
                data={report.seed_variability.rows.filter((r) => r.validation_balanced_accuracy != null).map((r): BarWithCiDatum => ({ category: `seed=${r.seed}`, value: r.validation_balanced_accuracy as number }))}
                yLabel="Balanced accuracy (VALIDATION)"
                noDataReason="Sin seed_variability real todavia."
              />
            ) : (
              <NoDataNotice reason="RQ2 no tiene seed_variability real todavia para la rama PRIMARY." />
            )}
          </div>
        </>
      )}
    </div>
  );
}
