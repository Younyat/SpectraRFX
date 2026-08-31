import { BleScientificResultsApiService, BootstrapCiResult, NoDataResponse, Rq3Pair, Rq3PerUnitMeanD } from '../../../app/services/bleScientificResultsApi';
import EvidenceMaturityBadge, { EvidenceMaturity } from './EvidenceMaturityBadge';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import HistogramChart from './charts/HistogramChart';
import PairedPrePostChart, { PairedPrePostDatum } from './charts/PairedPrePostChart';
import RunScopedJsonReport from './RunScopedJsonReport';
import StatisticalInspectionPanel, { rq3PermutationRow } from './StatisticalInspectionPanel';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: Record<string, unknown> | NoDataResponse): report is NoDataResponse {
  return (report as NoDataResponse).status === 'NO_DATA';
}

function permutationDraws(report: Record<string, unknown>): number[] {
  const method = report.rq3_within_device_permutation_test as { value?: { null_distribution?: number[] } } | undefined;
  const draws = method?.value?.null_distribution;
  return Array.isArray(draws) ? draws.filter((v) => typeof v === 'number') : [];
}

function observedStatistic(report: Record<string, unknown>): number | null {
  const method = report.rq3_within_device_permutation_test as { value?: { observed_statistic?: number } } | undefined;
  return typeof method?.value?.observed_statistic === 'number' ? method.value.observed_statistic : null;
}

function pairs(report: Record<string, unknown>): Rq3Pair[] {
  const value = report.rq3_pairs;
  return Array.isArray(value) ? (value as Rq3Pair[]) : [];
}

function pairedPrePost(realPairs: Rq3Pair[], arm: 'RESET' | 'CONTROL'): PairedPrePostDatum[] {
  return realPairs
    .filter((p) => p.valid && p.intervention_arm === arm && typeof p.pre_frr === 'number' && typeof p.post_frr === 'number')
    .map((p) => ({ unitId: `${p.physical_unit_id} (${p.day_id})`, pre: p.pre_frr as number, post: p.post_frr as number }));
}

function perUnitDBars(realPairs: Rq3Pair[]): BarWithCiDatum[] {
  return realPairs
    .filter((p) => p.valid && typeof p.d === 'number')
    .map((p) => ({ category: `${p.physical_unit_id} (${p.day_id}, ${p.intervention_arm})`, value: p.d as number }));
}

/** Fast-closure pass (2026-08-12): the arm-level D + CI figure the paper
 * requires ("D / delta_cycle + CI"), reusing hierarchical_cluster_bootstrap
 * (mean_d_with_ci, backend) -- never a new statistic. */
function meanDWithCiBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const reset = report.rq3_reset_mean_d_ci as BootstrapCiResult | null | undefined;
  const control = report.rq3_control_mean_d_ci as BootstrapCiResult | null | undefined;
  const bars: BarWithCiDatum[] = [];
  if (reset) bars.push({ category: 'RESET', value: reset.point_estimate, ciLow: reset.ci_low, ciHigh: reset.ci_high });
  if (control) bars.push({ category: 'CONTROL', value: control.point_estimate, ciLow: control.ci_low, ciHigh: control.ci_high });
  return bars;
}

function perUnitMeanD(report: Record<string, unknown>): { reset: BarWithCiDatum[]; control: BarWithCiDatum[] } {
  const value = report.rq3_per_unit_mean_d as Rq3PerUnitMeanD | undefined;
  if (!value) return { reset: [], control: [] };
  return {
    reset: Object.entries(value.reset || {}).map(([unit, d]) => ({ category: unit, value: d })),
    control: Object.entries(value.control || {}).map(([unit, d]) => ({ category: unit, value: d })),
  };
}

/** RQ3 reads whichever real confirmatory statistical report exists,
 * preferring the FUTURE-gated CONFIRMATORY one (confirmatory_future_
 * analysis_report.json) only when it has actually been produced (requires
 * a real protocol freeze + opened FUTURE holdout -- never triggered by
 * this dashboard), and otherwise falling back to the non-FUTURE VALIDATION
 * dry-run (confirmatory_statistical_plan_report.json) -- the SAME
 * statistical engine, just never touching FUTURE_TEST. Every field is
 * tagged with which source backed it so a VALIDATION figure can never be
 * mistaken for a CONFIRMATORY one. */
async function fetchRq3Report(paperRunId: string): Promise<Record<string, unknown> | NoDataResponse> {
  const confirmatory = await sciApi.confirmatoryFutureAnalysis(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(confirmatory)) return { ...confirmatory, _evidence_source: 'CONFIRMATORY' };
  const validation = await sciApi.confirmatoryStatisticalPlan(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(validation)) return { ...validation, _evidence_source: 'VALIDATION' };
  return { status: 'NO_DATA' };
}

export default function Rq3Tab() {
  return (
    <RunScopedJsonReport
      title="RQ3 -- Reset-associated displacement"
      description="FRR_pre/FRR_post/D por par PRE/POST -- real, via el pipeline de inferencia congelado (rama primaria + preprocesamiento + regla de ventana de decision + umbral operativo calibrado). run_rq3_frr_analysis (POST /rq3-frr-analysis) es el productor real; lee confirmatory_future_analysis_report.json (CONFIRMATORY) cuando existe, o confirmatory_statistical_plan_report.json (VALIDATION, no toca FUTURE) en caso contrario."
      noDataReason="Ni confirmatory_future_analysis_report.json ni confirmatory_statistical_plan_report.json existen todavia para este run -- ejecuta RQ3 FRR Analysis (Study Control Center) primero."
      fetchReport={fetchRq3Report}
      renderCharts={(report) => {
        const source = (report._evidence_source as EvidenceMaturity) ?? 'VALIDATION';
        const realPairs = pairs(report);
        const invalidPairs = realPairs.filter((p) => !p.valid);
        const scoredPairs = realPairs.filter((p) => p.valid && typeof p.d === 'number');
        const meanD = perUnitMeanD(report);
        return (
          <>
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span>fuente de evidencia:</span><EvidenceMaturityBadge maturity={source} />
              {report.rq3_bundle_id != null && <span className="ml-2">bundle: <span className="font-mono text-slate-400">{String(report.rq3_bundle_id)}</span></span>}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Inspeccion estadistica</div>
              <StatisticalInspectionPanel rows={[rq3PermutationRow(report)]} noDataReason="rq3_within_device_permutation_test.status != EXECUTED todavia." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Distribucion nula de la prueba de permutacion (dentro de dispositivo)</div>
              <HistogramChart
                values={permutationDraws(report)}
                observedValue={observedStatistic(report)}
                xLabel="estadistico de permutacion"
                noDataReason="rq3_within_device_permutation_test.value.null_distribution no esta presente en el reporte."
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">RESET -- FRR pareado PRE-&gt;POST</div>
                <PairedPrePostChart data={pairedPrePost(realPairs, 'RESET')} yLabel="FRR" noDataReason="Sin pares RESET reales con FRR calculado todavia." />
              </div>
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">CONTROL -- FRR pareado PRE-&gt;POST</div>
                <PairedPrePostChart data={pairedPrePost(realPairs, 'CONTROL')} yLabel="FRR" noDataReason="Sin pares CONTROL reales con FRR calculado todavia." />
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">D = FRR_post - FRR_pre, por unidad/dia/arm</div>
              <BarWithCiChart data={perUnitDBars(realPairs)} yLabel="D" noDataReason="Sin D real calculado todavia." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">D medio por arm, con CI bootstrap por cluster (unidad fisica)</div>
              <BarWithCiChart data={meanDWithCiBars(report)} yLabel="D medio (bootstrap CI)" noDataReason="rq3_reset_mean_d_ci/rq3_control_mean_d_ci no estan presentes en el reporte todavia." />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">D medio por unidad -- RESET</div>
                <BarWithCiChart data={meanD.reset} yLabel="D medio (RESET)" noDataReason="Sin D medio RESET real todavia." />
              </div>
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">D medio por unidad -- CONTROL</div>
                <BarWithCiChart data={meanD.control} yLabel="D medio (CONTROL)" noDataReason="Sin D medio CONTROL real todavia." />
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Registro real de pares PRE/POST (identidad + FRR/D reales)</div>
              {realPairs.length === 0 ? (
                <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center text-xs text-slate-500">
                  0 pares reales todavia (0/0 capturas declaran day_id/intervention_arm/pre_or_post a la vez -- esperado hasta la campana definitiva).
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-800 text-left text-slate-500">
                        <th className="py-1 pr-2">unidad</th><th className="py-1 pr-2">dia</th><th className="py-1 pr-2">arm</th>
                        <th className="py-1 pr-2">pre_capture_id</th><th className="py-1 pr-2">post_capture_id</th>
                        <th className="py-1 pr-2">valido</th><th className="py-1 pr-2">razon de invalidacion</th>
                        <th className="py-1 pr-2">n_pre_windows</th><th className="py-1 pr-2">n_post_windows</th>
                        <th className="py-1 pr-2">FRR_pre</th><th className="py-1 pr-2">FRR_post</th><th className="py-1 pr-2">D</th>
                      </tr>
                    </thead>
                    <tbody>
                      {realPairs.map((p, i) => (
                        <tr key={i} className={`border-b border-slate-900 ${p.valid ? 'text-slate-300' : 'text-red-400/80'}`}>
                          <td className="py-1.5 pr-2">{p.physical_unit_id}</td><td className="py-1.5 pr-2">{p.day_id}</td><td className="py-1.5 pr-2">{p.intervention_arm}</td>
                          <td className="py-1.5 pr-2 font-mono">{p.pre_capture_id}</td><td className="py-1.5 pr-2 font-mono">{p.post_capture_id}</td>
                          <td className="py-1.5 pr-2">{p.valid ? 'yes' : 'no'}</td><td className="py-1.5 pr-2">{p.invalidation_reason ?? '-'}</td>
                          <td className="py-1.5 pr-2 font-mono">{p.n_pre_windows ?? 'N/A'}</td><td className="py-1.5 pr-2 font-mono">{p.n_post_windows ?? 'N/A'}</td>
                          <td className="py-1.5 pr-2 font-mono">{p.pre_frr != null ? p.pre_frr.toFixed(4) : 'N/A'}</td>
                          <td className="py-1.5 pr-2 font-mono">{p.post_frr != null ? p.post_frr.toFixed(4) : 'N/A'}</td>
                          <td className="py-1.5 pr-2 font-mono">{p.d != null ? p.d.toFixed(4) : 'N/A'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {invalidPairs.length > 0 && (
                    <div className="mt-1 text-[11px] text-slate-500">{invalidPairs.length} de {realPairs.length} pares invalidos (ver razon en la tabla).</div>
                  )}
                  {realPairs.length > invalidPairs.length && scoredPairs.length === 0 && (
                    <div className="mt-1 text-[11px] text-amber-400/80">
                      Pares validos existen pero ninguno tiene FRR real todavia -- ejecuta RQ3 FRR Analysis para puntuarlos con la rama primaria congelada.
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        );
      }}
    />
  );
}
