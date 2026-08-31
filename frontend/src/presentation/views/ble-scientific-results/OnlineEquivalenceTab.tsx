import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, NoDataResponse, OfflineNearliveReport } from '../../../app/services/bleScientificResultsApi';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';
import MechanismDataNotice from './MechanismDataNotice';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: OfflineNearliveReport | NoDataResponse | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

/** S2 (2026-08-11, join-key frozen 2026-08-11): offline vs near-live. Two
 * decisions pair iff they share the same `evidence_interval_id` (a real,
 * deterministic identity over source_iq_sha256 + sample_start + sample_end)
 * -- never a nearest-timestamp or other proximity heuristic, and frozen
 * before any real campaign runs. Renderer + backend
 * (compute_offline_nearlive_report / get_offline_nearlive_report) are
 * real and tested (MECHANISM=READY); computational fields default to
 * NOT_MEASURED, never 0. */
export default function OnlineEquivalenceTab() {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [report, setReport] = useState<OfflineNearliveReport | NoDataResponse | null>(null);

  useEffect(() => {
    if (!paperRunId) { setReport(null); return; }
    sciApi.getOfflineNearlive(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);

  const analytical = report && !isNoData(report) ? report.analytical_agreement : null;
  const computational = report && !isNoData(report) ? report.computational_behavior : null;

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Engineering -- Offline vs near-live</div>
        <div className="mt-1 text-xs text-slate-500">
          Emparejamiento por evidence_interval_id exacto (source_iq_sha256 + sample_start + sample_end) -- nunca por
          proximidad temporal. Dos clases separadas: (A) acuerdo analitico (conteo de decisiones, acuerdo de clase,
          acuerdo de score, acuerdo de abstencion) y (B) comportamiento computacional (latencia, throughput, drops).
          Nunca 0 cuando no este medido -- NOT_MEASURED explicito.
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-slate-500">
        <span>evidence maturity:</span><EvidenceMaturityBadge maturity="ENGINEERING" />
      </div>
      <MechanismDataNotice
        data={analytical ? 'AVAILABLE' : 'NO_DATA'}
        dataReason="El join-key (evidence_interval_id) esta congelado y el emparejamiento exacto esta implementado y probado -- todavia no existen predicciones offline/near-live reales que aportar."
      />
      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(report) && <NoDataNotice reason="offline_nearlive_report.json no existe todavia para este run." />}
      {paperRunId && report && !isNoData(report) && (
        <>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-slate-500">matched_pair_count</div>
              <div className="font-mono text-slate-200">{report.matched_pair_count}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-slate-500">unpaired_offline_count</div>
              <div className="font-mono text-slate-200">{report.unpaired_offline_count}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-slate-500">unpaired_nearlive_count</div>
              <div className="font-mono text-slate-200">{report.unpaired_nearlive_count}</div>
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Acuerdo analitico</div>
            {analytical ? (
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                {Object.entries(analytical).map(([key, value]) => (
                  <div key={key} className="rounded border border-slate-800 bg-slate-950 p-2">
                    <div className="text-slate-500">{key}</div>
                    <div className="font-mono text-slate-200">{value ?? 'NOT_MEASURED'}</div>
                  </div>
                ))}
              </div>
            ) : (
              <NoDataNotice reason={report.pairing_note} />
            )}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Comportamiento computacional</div>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              {Object.entries(computational ?? {}).map(([key, value]) => (
                <div key={key} className="rounded border border-slate-800 bg-slate-950 p-2">
                  <div className="text-slate-500">{key}</div>
                  <div className="font-mono text-slate-200">{String(value)}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
            MISSING_CANONICAL_METRIC -- histograma de latencia, ECDF de latencia, timeline de throughput y timeline de
            drops requieren muestras individuales por peticion; computational_behavior solo persiste resumenes
            escalares (median_latency_ms/p95_latency_ms/throughput_per_s/drop_count/drop_rate/backlog). Confirmado
            por revision directa del codebase (2026-08-11): ningun codigo mide latencia individual de una prediccion
            offline/near-live real (el unico timing existente, training_service.py's _measure_latency_ms, colapsa un
            micro-benchmark de 10 repeticiones sobre la MISMA muestra en su propia media antes de devolver nada), y
            "near-live" no existe todavia como concepto de request individual en ble_rffi_studio. No se fabrican
            series en el frontend -- si el backend llega a instrumentar y persistir muestras crudas reales, EcdfChart
            y HistogramChart (ya existentes) se conectaran aqui.
          </div>
          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[70vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
