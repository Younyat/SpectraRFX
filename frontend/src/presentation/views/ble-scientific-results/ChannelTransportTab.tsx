import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, ChannelTransportReport, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';
import MechanismDataNotice from './MechanismDataNotice';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: ChannelTransportReport | NoDataResponse | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

function channelBars(report: ChannelTransportReport, field: 'balanced_accuracy' | 'macro_f1' | 'coverage'): BarWithCiDatum[] {
  return report.per_channel
    .filter((c) => typeof c[field] === 'number')
    .map((c) => ({ category: `CH${c.channel}`, value: c[field] as number }));
}

/** S1 (2026-08-11): CH37->CH38/39 bounded channel transport. Real renderer
 * + real backend (compute_channel_transport_report / get_channel_transport_report)
 * now exist -- MECHANISM=READY regardless of whether a real frozen bundle
 * has been scored per-channel yet (DATA stays NO_DATA until it has). Never
 * labeled "channel invariance". */
export default function ChannelTransportTab() {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [report, setReport] = useState<ChannelTransportReport | NoDataResponse | null>(null);

  useEffect(() => {
    if (!paperRunId) { setReport(null); return; }
    sciApi.getChannelTransport(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Engineering -- CH37 -&gt; CH38/39 transport</div>
        <div className="mt-1 text-xs text-slate-500">
          Mantenido explicitamente fuera de RQ1-RQ4. Modelo congelado (entrenado en CH37, sin reentrenar), misma regla
          de decision aplicada a CH38/39. Interpretacion permitida: "bounded channel transport" -- nunca "channel
          invariance".
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-slate-500">
        <span>evidence maturity:</span><EvidenceMaturityBadge maturity="ENGINEERING" />
      </div>
      <MechanismDataNotice
        data={report && !isNoData(report) ? 'AVAILABLE' : 'NO_DATA'}
        dataReason="No existe todavia un bundle congelado real evaluado por canal (compute_channel_transport_report requiere predicciones ya puntuadas de UN solo modelo congelado)."
      />
      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(report) && <NoDataNotice reason="channel_transport_report.json no existe todavia para este run." />}
      {paperRunId && report && !isNoData(report) && (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Balanced accuracy por canal</div>
            <BarWithCiChart data={channelBars(report, 'balanced_accuracy')} yLabel="Balanced accuracy" noDataReason="Ningun canal tiene balanced_accuracy real en el reporte." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Macro-F1 por canal</div>
            <BarWithCiChart data={channelBars(report, 'macro_f1')} yLabel="Macro-F1" noDataReason="Ningun canal tiene macro_f1 real en el reporte." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por canal</div>
            <BarWithCiChart data={channelBars(report, 'coverage')} yLabel="Coverage" noDataReason="Ningun canal tiene coverage real en el reporte." />
          </div>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            {report.per_channel.map((c) => (
              <div key={c.channel} className="rounded border border-slate-800 bg-slate-950 p-2">
                <div className="text-slate-500">CH{c.channel} windows</div>
                <div className="font-mono text-slate-200">{c.windows}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Recall por unidad fisica y canal (real, physical_unit_id join)</div>
            {report.per_channel.every((c) => !c.per_unit_recall) ? (
              <NoDataNotice reason="Ningun canal tiene per_unit_recall real todavia -- las predicciones deben declarar physical_unit_id." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[500px] border-collapse text-[11px]">
                  <thead><tr className="border-b border-slate-800 text-left text-slate-500"><th className="py-1 pr-2">canal</th><th className="py-1 pr-2">recall por unidad</th></tr></thead>
                  <tbody>
                    {report.per_channel.filter((c) => c.per_unit_recall).map((c) => (
                      <tr key={c.channel} className="border-b border-slate-900 text-slate-300">
                        <td className="py-1.5 pr-2">CH{c.channel}</td>
                        <td className="py-1.5 pr-2 font-mono">{Object.entries(c.per_unit_recall as Record<string, number>).map(([unit, r]) => `${unit}=${r.toFixed(3)}`).join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
            MISSING_CANONICAL_METRIC -- un heatmap unidad x canal (una matriz densa cruzando ambas dimensiones a la
            vez) no esta expuesto todavia; solo el recall por unidad dentro de cada canal (arriba, real). No se
            fabrica una matriz cruzada aqui.
          </div>
          {report.per_channel.map((c) => (
            <div key={c.channel}>
              <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- CH{c.channel}</div>
              <ConfusionMatrixHeatmap matrix={c.confusion_matrix} noDataReason={`Sin confusion_matrix real para CH${c.channel}.`} />
            </div>
          ))}
          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[70vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
