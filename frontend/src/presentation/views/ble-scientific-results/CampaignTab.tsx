import { Fragment, useEffect, useState } from 'react';
import { BleScientificResultsApiService, CampaignAccountingResponse, ScientificCampaignDeviationRecord } from '../../../app/services/bleScientificResultsApi';
import RunPickerBar from './RunPickerBar';
import { useRunRecords } from './useRunRecords';

const sciApi = new BleScientificResultsApiService();

export default function CampaignTab() {
  const { runs, paperRunId, setPaperRunId, status, building, buildRecords, error } = useRunRecords();
  const [accounting, setAccounting] = useState<CampaignAccountingResponse | null>(null);
  const [deviations, setDeviations] = useState<ScientificCampaignDeviationRecord[]>([]);
  const [expandedDeviation, setExpandedDeviation] = useState<string | null>(null);

  useEffect(() => {
    if (!paperRunId || !status?.built) {
      setAccounting(null);
      setDeviations([]);
      return;
    }
    sciApi.campaignAccounting(paperRunId).then(setAccounting).catch(() => setAccounting(null));
    sciApi.deviations(paperRunId, 100, 0).then(setDeviations).catch(() => setDeviations([]));
  }, [paperRunId, status?.built]);

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Campaign accounting</div>
        <div className="mt-1 text-xs text-slate-500">
          Contabilidad real planned-vs-observed y desviaciones de campana, reconstruidas desde los registros canonicos
          (nunca cifras fijas). Cada desviacion muestra su regla, severidad, y los IDs de artefacto de origen.
        </div>
      </div>

      <RunPickerBar runs={runs} paperRunId={paperRunId} setPaperRunId={setPaperRunId} status={status} building={building} buildRecords={buildRecords} error={error} />

      {accounting && (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Contadores de campana</div>
            <div className="grid grid-cols-3 gap-2 text-xs md:grid-cols-4">
              {Object.entries(accounting.counters).map(([key, value]) => (
                <div key={key} className="rounded border border-slate-700 bg-slate-900/60 px-2 py-1.5">
                  <div className="text-slate-500">{key}</div>
                  <div className="font-mono text-slate-200">{String(value)}</div>
                </div>
              ))}
            </div>
          </div>

          {Object.keys(accounting.balance).length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Matrices de balance experimental (Seccion D)</div>
              <div className="space-y-3">
                {Object.entries(accounting.balance).map(([matrixName, matrix]) => (
                  <div key={matrixName} className="rounded border border-slate-800 p-2">
                    <div className="mb-1 text-xs text-cyan-300">{matrixName}</div>
                    <pre className="overflow-x-auto text-[11px] text-slate-300">{JSON.stringify(matrix, null, 1)}</pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Desviaciones de campana ({deviations.length})</div>
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="text-slate-500">
                <tr><th className="py-1 pr-3">tipo</th><th className="py-1 pr-3">objeto</th><th className="py-1 pr-3">severidad</th><th className="py-1 pr-3">bloqueante</th><th className="py-1"></th></tr>
              </thead>
              <tbody>
                {deviations.map((deviation) => (
                  <Fragment key={deviation.deviation_id}>
                    <tr className="cursor-pointer border-t border-slate-800 hover:bg-slate-900/40" onClick={() => setExpandedDeviation(expandedDeviation === deviation.deviation_id ? null : deviation.deviation_id)}>
                      <td className="py-1 pr-3">{deviation.deviation_type}</td>
                      <td className="py-1 pr-3">{deviation.affected_object_type}:{deviation.affected_object_id}</td>
                      <td className="py-1 pr-3">{deviation.severity}</td>
                      <td className="py-1 pr-3">{deviation.blocking ? 'si' : 'no'}</td>
                      <td className="py-1 text-cyan-400">{expandedDeviation === deviation.deviation_id ? 'ocultar' : 'ver'}</td>
                    </tr>
                    {expandedDeviation === deviation.deviation_id && (
                      <tr className="border-t border-slate-800 bg-slate-900/30">
                        <td colSpan={5} className="px-3 py-2 text-[11px]">
                          <div><span className="text-slate-500">description:</span> {deviation.description}</div>
                          <div><span className="text-slate-500">action:</span> {deviation.action}</div>
                          <div><span className="text-slate-500">scientific_impact:</span> {deviation.scientific_impact}</div>
                          <div><span className="text-slate-500">source_artifact_ids:</span> {deviation.source_artifact_ids.join(', ') || '(none)'}</div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
