import { useCallback, useEffect, useState } from 'react';
import { BleScientificResultsApiService, CoverageAnalysisJob, CoverageAnalysisReport, CoverageBucket, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import RiskCoverageChart, { RiskCoveragePoint } from './charts/RiskCoverageChart';
import NoDataNotice from './NoDataNotice';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: CoverageAnalysisReport | NoDataResponse | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

function riskCoveragePoints(report: Record<string, unknown>): RiskCoveragePoint[] {
  const method = report.risk_coverage as { status?: string; value?: { coverage?: number; risk?: number }[] } | undefined;
  if (method?.status !== 'EXECUTED' || !Array.isArray(method.value)) return [];
  return method.value
    .filter((p) => typeof p.coverage === 'number' && typeof p.risk === 'number')
    .map((p) => ({ coverage: p.coverage as number, risk: p.risk as number }));
}

function coverageMethodValue(report: Record<string, unknown>): number | null {
  const method = report.coverage as { status?: string; value?: number } | undefined;
  return method?.status === 'EXECUTED' && typeof method.value === 'number' ? method.value : null;
}

function bucketsToBars(buckets: Record<string, CoverageBucket>): BarWithCiDatum[] {
  return Object.entries(buckets).map(([key, bucket]) => ({ category: key, value: bucket.coverage }));
}

/** Coverage canonical producer (2026-08-12, Scientific Closure pass) --
 * real decision-window rows (OfflineInferenceService.run_decision_windows,
 * the SAME frozen pipeline RQ3 uses) grouped by overall/evaluation_domain/
 * branch/physical_unit -- nothing computed in the frontend. */
function CoverageAnalysisSection({ paperRunId }: { paperRunId: string }) {
  const [report, setReport] = useState<CoverageAnalysisReport | NoDataResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [evaluateWindowLevel, setEvaluateWindowLevel] = useState(false);

  const load = useCallback(() => {
    sciApi.getCoverageAnalysis(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);
  useEffect(() => { setReport(null); load(); }, [load]);

  const runAnalysis = useCallback(() => {
    setRunning(true);
    setRunError(null);
    sciApi.startCoverageAnalysis({ paper_run_id: paperRunId, evaluate_window_level: evaluateWindowLevel })
      .then((job) => {
        const poll = (): void => {
          sciApi.getCoverageAnalysisJob(job.job_id).then((current: CoverageAnalysisJob) => {
            if (current.state === 'completed') { setRunning(false); load(); return; }
            if (current.state === 'failed' || current.state === 'cancelled') { setRunning(false); setRunError(current.error ?? 'El job fallo.'); return; }
            setTimeout(poll, 3000);
          }).catch(() => { setRunning(false); setRunError('No se pudo consultar el estado del job.'); });
        };
        poll();
      })
      .catch(() => { setRunning(false); setRunError('No se pudo lanzar Coverage Analysis (revisa que exista una rama RQ2 con model_bundle_id).'); });
  }, [paperRunId, evaluateWindowLevel, load]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2">
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <input type="checkbox" checked={evaluateWindowLevel} onChange={(e) => setEvaluateWindowLevel(e.target.checked)} />
          incluir BA/matriz de confusion/risk-coverage a nivel de decision-window (10s)
        </label>
        <button
          type="button" onClick={runAnalysis} disabled={running}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {running ? 'Corriendo…' : 'Correr Coverage Analysis'}
        </button>
      </div>
      {runError && <NoDataNotice reason={runError} />}
      {!report ? (
        <div className="text-xs text-slate-500">Cargando coverage_analysis_report...</div>
      ) : isNoData(report) ? (
        <NoDataNotice reason="coverage_analysis_report.json no existe todavia para este run -- corre Coverage Analysis arriba." />
      ) : (
        <CoverageAnalysisReportView report={report} />
      )}
    </div>
  );
}

function CoverageAnalysisReportView({ report }: { report: CoverageAnalysisReport }) {
  const overall = report.overall;
  return (
    <>
      {overall && (
        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-5">
          <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">eligible</div><div className="font-mono text-slate-200">{overall.eligible_windows}</div></div>
          <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">decided</div><div className="font-mono text-slate-200">{overall.decided_windows}</div></div>
          <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">abstained</div><div className="font-mono text-slate-200">{overall.abstained_windows}</div></div>
          <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">coverage</div><div className="font-mono text-slate-200">{overall.coverage.toFixed(4)}</div></div>
          <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">risk among decided</div><div className="font-mono text-slate-200">{overall.risk_among_decided?.toFixed(4) ?? 'N/A'}</div></div>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por dominio de evaluacion</div>
          <BarWithCiChart data={bucketsToBars(report.by_evaluation_domain)} yLabel="Coverage" noDataReason="Ninguna ventana real con dominio de split resuelto todavia." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por rama (RQ2)</div>
          <BarWithCiChart data={bucketsToBars(report.by_branch)} yLabel="Coverage" noDataReason="Sin ramas reales todavia." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por unidad fisica</div>
          <BarWithCiChart data={bucketsToBars(report.by_physical_unit)} yLabel="Coverage" noDataReason="Sin unidades reales todavia." />
        </div>
      </div>
      <div>
        <div className="mb-1 text-xs font-semibold text-slate-400">Distribucion de razones de abstencion (real, run_decision_windows)</div>
        {report.abstention_reason_counts === 'NOT_AVAILABLE' ? (
          <NoDataNotice reason="Ninguna razon de abstencion fue registrada todavia -- NOT_AVAILABLE, nunca inferida retrospectivamente." />
        ) : (
          <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
            {Object.entries(report.abstention_reason_counts).map(([reason, count]) => (
              <div key={reason} className="rounded border border-slate-800 bg-slate-950 p-2">
                <div className="text-slate-500">{reason}</div>
                <div className="font-mono text-slate-200">{count}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      {report.domain_resolution_diagnostic && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">
            Diagnostico de resolucion de dominio (por que una decision window real no cae en TRAIN/VALIDATION/TEST)
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-5">
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">total_windows</div><div className="font-mono text-slate-200">{report.domain_resolution_diagnostic.total_windows}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">assigned_train</div><div className="font-mono text-slate-200">{report.domain_resolution_diagnostic.assigned_train}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">assigned_validation</div><div className="font-mono text-slate-200">{report.domain_resolution_diagnostic.assigned_validation}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">assigned_test</div><div className="font-mono text-slate-200">{report.domain_resolution_diagnostic.assigned_test}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">unresolved</div><div className="font-mono text-slate-200">{report.domain_resolution_diagnostic.unresolved}</div></div>
          </div>
          {Object.keys(report.domain_resolution_diagnostic.unresolved_by_reason).length > 0 && (
            <div className="mt-2 grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-3">
              {Object.entries(report.domain_resolution_diagnostic.unresolved_by_reason).map(([reason, count]) => (
                <div key={reason} className="rounded border border-slate-800 bg-slate-950 p-2">
                  <div className="text-slate-500">{reason}</div>
                  <div className="font-mono text-slate-200">{count}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {report.window_level_evaluation && (
        <div className="space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-400">
            Closed-set -- BA / matriz de confusion / risk-coverage a nivel de decision-window (10s)
          </h3>
          {Object.entries(report.window_level_evaluation).map(([branch, branchEval]) => (
            <div key={branch} className="space-y-3 rounded border border-slate-800 p-3">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span className="font-mono text-slate-300">{branch}</span>
                {branchEval.classifier_acceptance_threshold !== null ? (
                  <span className="rounded border border-emerald-800 bg-emerald-950/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-300">
                    OPERATING POINT = {branchEval.classifier_acceptance_threshold} (calibrated_on={branchEval.classifier_acceptance_threshold_calibrated_on})
                  </span>
                ) : (
                  <span className="rounded border border-amber-800 bg-amber-950/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-300">
                    OPERATING POINT NOT FROZEN
                  </span>
                )}
                <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] font-mono text-slate-500">
                  association_time_threshold_ms = {branchEval.association_time_threshold_ms ?? 'null (fail-closed)'}
                </span>
              </div>
              {Object.entries(branchEval.by_evaluation_domain).map(([domain, domainEval]) => (
                <div key={domain} className="space-y-2 border-t border-slate-800 pt-2">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <span className="font-mono text-slate-300">{domain}</span>
                    <span className="rounded border border-amber-800 bg-amber-950/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-300">
                      {domainEval.evidence_maturity}
                    </span>
                    <span>BA = <span className="font-mono text-slate-300">{domainEval.balanced_accuracy?.toFixed(4) ?? '—'}</span></span>
                    <span>n = <span className="font-mono text-slate-300">{domainEval.n_comparable}</span></span>
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${domainEval.paper_ready ? 'border-emerald-800 bg-emerald-950/30 text-emerald-300' : 'border-red-800 bg-red-950/30 text-red-300'}`}>
                      {domainEval.paper_ready ? 'PAPER_READY' : 'NOT PAPER_READY'}
                    </span>
                  </div>
                  {!domainEval.paper_ready && domainEval.paper_ready_reason && (
                    <div className="text-[10.5px] text-red-300/80">{domainEval.paper_ready_reason} -- prueba funcional real, no citable todavia.</div>
                  )}
                  <div className="grid gap-3 md:grid-cols-2">
                    <ConfusionMatrixHeatmap matrix={domainEval.confusion_matrix} noDataReason="Sin matriz de confusion real para este dominio." />
                    <RiskCoverageChart points={domainEval.risk_coverage ?? null} noDataReason="Sin risk_coverage real para este dominio (probabilidades agregadas no disponibles)." />
                  </div>
                  {domainEval.risk_coverage && domainEval.risk_coverage.length > 0 && (
                    <div className="overflow-x-auto rounded border border-slate-800">
                      <table className="min-w-full text-[10.5px]">
                        <thead className="bg-slate-950 uppercase tracking-wide text-slate-500">
                          <tr>
                            <th className="px-2 py-1 text-right">threshold</th>
                            <th className="px-2 py-1 text-right">coverage</th>
                            <th className="px-2 py-1 text-right">selective_error</th>
                            <th className="px-2 py-1 text-right">n_decided</th>
                            <th className="px-2 py-1 text-right">n_abstained</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800">
                          {domainEval.risk_coverage.map((point, idx) => (
                            <tr key={idx}>
                              <td className="px-2 py-1 text-right font-mono text-slate-300">{point.threshold.toFixed(4)}</td>
                              <td className="px-2 py-1 text-right font-mono text-slate-300">{point.coverage.toFixed(4)}</td>
                              <td className="px-2 py-1 text-right font-mono text-slate-300">{point.risk.toFixed(4)}</td>
                              <td className="px-2 py-1 text-right font-mono text-slate-300">{point.n_decided}</td>
                              <td className="px-2 py-1 text-right font-mono text-slate-300">{point.n_abstained}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}
              {branchEval.decision_windows.length > 0 && (
                <div className="border-t border-slate-800 pt-2">
                  <div className="mb-1 text-[11px] font-semibold text-slate-400">
                    Decision windows reales (10s) -- true TX / predicted TX / score / decision
                  </div>
                  <div className="max-h-64 overflow-auto rounded border border-slate-800">
                    <table className="min-w-full text-[10.5px]">
                      <thead className="sticky top-0 bg-slate-950 uppercase tracking-wide text-slate-500">
                        <tr>
                          <th className="px-2 py-1 text-left">decision_window_id</th>
                          <th className="px-2 py-1 text-left">domain</th>
                          <th className="px-2 py-1 text-right">burst_count</th>
                          <th className="px-2 py-1 text-left">true TX</th>
                          <th className="px-2 py-1 text-left">predicted TX</th>
                          <th className="px-2 py-1 text-right">score</th>
                          <th className="px-2 py-1 text-left">decision</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {branchEval.decision_windows.map((row) => (
                          <tr key={row.decision_window_id ?? `${row.capture_id}-${row.evaluation_domain}`}>
                            <td className="px-2 py-1 font-mono text-slate-300">{row.decision_window_id ?? '—'}</td>
                            <td className="px-2 py-1 font-mono text-slate-400">{row.evaluation_domain ?? '—'}</td>
                            <td className="px-2 py-1 text-right font-mono text-slate-300">{row.burst_count ?? '—'}</td>
                            <td className="px-2 py-1 font-mono text-slate-300">{row.true_physical_unit_id ?? '—'}</td>
                            <td className="px-2 py-1 font-mono text-slate-300">{row.predicted_class ?? '—'}</td>
                            <td className="px-2 py-1 text-right font-mono text-slate-300">{row.class_probability?.toFixed(4) ?? '—'}</td>
                            <td className="px-2 py-1 font-mono text-slate-300">{row.final_decision ?? '—'}{row.abstention_reason ? ` (${row.abstention_reason})` : ''}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function CoverageTab() {
  return (
    <RunScopedJsonReport
      title="Coverage / Abstention"
      description="Ventanas elegibles, decididas, abstenidas y curva risk-coverage -- leido de confirmatory_future_analysis_report.json (coverage, risk_coverage) + coverage_analysis_report.json (por dominio/rama/unidad, real, run_decision_windows). Obligatorio para el paper: ningun BA/F1 que use una regla con abstencion deberia mostrarse sin su coverage."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
      renderCharts={(report, paperRunId) => (
        <>
          <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
            <span className="text-slate-500">coverage (real, EXECUTED):</span>{' '}
            <span className="font-mono text-slate-200">{coverageMethodValue(report) ?? 'N/A'}</span>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Curva risk-coverage (regla operativa ya definida -- ninguna familia de thresholds nueva)</div>
            <RiskCoverageChart points={riskCoveragePoints(report)} noDataReason="risk_coverage no esta EXECUTED en el reporte para este run." />
          </div>
          <CoverageAnalysisSection paperRunId={paperRunId} />
        </>
      )}
    />
  );
}
