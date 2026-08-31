import { BleScientificResultsApiService, NoDataResponse, Rq4RegionReport } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import HistogramChart from './charts/HistogramChart';
import NonInferiorityChart, { NonInferiorityDatum } from './charts/NonInferiorityChart';
import EvidenceMaturityBadge, { EvidenceMaturity } from './EvidenceMaturityBadge';
import NoDataNotice from './NoDataNotice';
import RunScopedJsonReport from './RunScopedJsonReport';
import StatisticalInspectionPanel, { holmSummary, nonInferiorityRow, rq4PairedComparisonRow } from './StatisticalInspectionPanel';

const ANALYTICAL_REGIONS = ['FULL_BURST', 'ADVA_EXCLUDED', 'PRE_PDU'] as const;

function rq4RegionReport(report: Record<string, unknown>): Rq4RegionReport | null {
  const value = report.rq4_region_report as Rq4RegionReport | undefined;
  return value && Array.isArray(value.matched_region_blocks) ? value : null;
}

/** Mean recall per analytical_region across every matched_region_block that
 * has a real (non-null) result for it -- point comparison, no CI (recall
 * here is already an aggregate across windows within one block; a CI across
 * the small number of matched blocks would need its own bootstrap, not yet
 * computed anywhere -- reported as a plain bar, never fabricated). */
function regionComparisonBars(regionReport: Rq4RegionReport): BarWithCiDatum[] {
  const bars: BarWithCiDatum[] = [];
  for (const region of ANALYTICAL_REGIONS) {
    const values = regionReport.matched_region_blocks
      .map((row) => row.regions[region]?.recall)
      .filter((v): v is number => typeof v === 'number');
    if (values.length === 0) continue;
    bars.push({ category: region, value: values.reduce((a, b) => a + b, 0) / values.length });
  }
  return bars;
}

const sciApi = new BleScientificResultsApiService();

function isNoData(report: Record<string, unknown> | NoDataResponse): report is NoDataResponse {
  return (report as NoDataResponse).status === 'NO_DATA';
}

/** Same VALIDATION-fallback pattern as RQ3: prefer the real CONFIRMATORY
 * (FUTURE-gated) report when it exists, otherwise the non-FUTURE
 * VALIDATION dry-run -- same statistical engine either way, badge shows
 * which one actually backs the currently-displayed figures. */
async function fetchRq4Report(paperRunId: string): Promise<Record<string, unknown> | NoDataResponse> {
  const confirmatory = await sciApi.confirmatoryFutureAnalysis(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(confirmatory)) return { ...confirmatory, _evidence_source: 'CONFIRMATORY' };
  const validation = await sciApi.confirmatoryStatisticalPlan(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(validation)) return { ...validation, _evidence_source: 'VALIDATION' };
  return { status: 'NO_DATA' };
}

function pairedDifferences(report: Record<string, unknown>): number[] {
  const method = report.rq4_paired_comparison as { value?: { contrast?: { differences?: number[] } } } | undefined;
  const differences = method?.value?.contrast?.differences;
  return Array.isArray(differences) ? differences.filter((v) => typeof v === 'number') : [];
}

function observedStatistic(report: Record<string, unknown>): number | null {
  const method = report.rq4_paired_comparison as { value?: { randomization_test?: { observed_statistic?: number } } } | undefined;
  return typeof method?.value?.randomization_test?.observed_statistic === 'number' ? method.value.randomization_test.observed_statistic : null;
}

function nonInferiorityChartData(report: Record<string, unknown>): NonInferiorityDatum[] {
  const method = report.non_inferiority as { value?: { mean_difference?: number; ci_low?: number; margin?: number; non_inferior?: boolean } } | undefined;
  const value = method?.value;
  if (!value || typeof value.mean_difference !== 'number' || typeof value.ci_low !== 'number' || typeof value.margin !== 'number') return [];
  return [{ label: 'RQ4 (agregado)', meanDifference: value.mean_difference, ciLow: value.ci_low, margin: value.margin, nonInferior: value.non_inferior === true }];
}

export default function Rq4Tab() {
  return (
    <RunScopedJsonReport
      title="RQ4 -- Packet-content dependence"
      description="FULL_BURST / ADVA_EXCLUDED / PRE_PDU (analytical_region) vs ORIGINAL / CONTROLLED_VARIANT (packet_condition), comparacion pareada y non-inferiority -- leido de confirmatory_future_analysis_report.json (rq4_paired_comparison, non_inferiority)."
      noDataReason="Ni confirmatory_future_analysis_report.json ni confirmatory_statistical_plan_report.json existen todavia para este run."
      fetchReport={fetchRq4Report}
      renderCharts={(report) => (
        <>
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span>fuente de evidencia:</span><EvidenceMaturityBadge maturity={(report._evidence_source as EvidenceMaturity) ?? 'VALIDATION'} />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Inspeccion estadistica</div>
            <StatisticalInspectionPanel
              rows={[rq4PairedComparisonRow(report), nonInferiorityRow(report)]}
              holm={holmSummary(report)}
              noDataReason="rq4_paired_comparison/non_inferiority.status != EXECUTED todavia."
            />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Diferencias pareadas (nuevo - referencia)</div>
            <HistogramChart
              values={pairedDifferences(report)}
              observedValue={observedStatistic(report)}
              xLabel="diferencia pareada"
              noDataReason="rq4_paired_comparison.value.contrast.differences no esta presente en el reporte."
            />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Non-inferiority -- estimacion, CI unilateral y frontera de decision (-margin)</div>
            <NonInferiorityChart data={nonInferiorityChartData(report)} noDataReason="non_inferiority.value no esta presente en el reporte." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Comparacion por region analitica (recall medio, FULL_BURST / ADVA_EXCLUDED / PRE_PDU)</div>
            {(() => {
              const regionReport = rq4RegionReport(report);
              return (
                <BarWithCiChart
                  data={regionReport ? regionComparisonBars(regionReport) : []}
                  yLabel="Recall medio (1 - FRR)"
                  noDataReason="rq4_region_report no existe todavia -- ejecuta RQ4 Region-Specific Analysis (Study Control Center) primero."
                />
              );
            })()}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">
              Desglose por matched_region_block (rq4_primary_analysis=REGION_SPECIFIC_FITTING_AND_EVALUATION)
            </div>
            {(() => {
              const regionReport = rq4RegionReport(report);
              if (!regionReport) {
                return <NoDataNotice reason="rq4_region_report no existe todavia -- ejecuta RQ4 Region-Specific Analysis (Study Control Center) primero." />;
              }
              return (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                    <div className="rounded border border-slate-800 bg-slate-950 p-2">
                      <div className="text-slate-500">contraste PRIMARIO</div>
                      <div className="font-mono text-slate-200">{regionReport.primary_contrast.a_region} vs {regionReport.primary_contrast.b_region}</div>
                      <div className="text-slate-500">n bloques pareados: <span className="font-mono text-slate-300">{regionReport.primary_contrast.n_matched_blocks}</span></div>
                    </div>
                    <div className="rounded border border-slate-800 bg-slate-950 p-2">
                      <div className="text-slate-500">contraste SECUNDARIO/diagnostico</div>
                      <div className="font-mono text-slate-200">{regionReport.secondary_contrast.a_region} vs {regionReport.secondary_contrast.b_region}</div>
                      <div className="text-slate-500">n bloques pareados: <span className="font-mono text-slate-300">{regionReport.secondary_contrast.n_matched_blocks}</span></div>
                    </div>
                    {ANALYTICAL_REGIONS.map((region) => (
                      <div key={region} className="rounded border border-slate-800 bg-slate-950 p-2">
                        <div className="text-slate-500">bundle {region}</div>
                        <div className="truncate font-mono text-slate-300">{regionReport.bundle_ids[region] ?? 'NO_DATA'}</div>
                      </div>
                    ))}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] border-collapse text-[11px]">
                      <thead>
                        <tr className="border-b border-slate-800 text-left text-slate-500">
                          <th className="py-1 pr-2">matched_region_block_id</th>
                          {ANALYTICAL_REGIONS.map((region) => (<th key={region} className="py-1 pr-2">{region} (recall / coverage)</th>))}
                        </tr>
                      </thead>
                      <tbody>
                        {regionReport.matched_region_blocks.map((row) => (
                          <tr key={row.matched_region_block_id} className="border-b border-slate-900 text-slate-300">
                            <td className="py-1.5 pr-2 font-mono">{row.matched_region_block_id}</td>
                            {ANALYTICAL_REGIONS.map((region) => {
                              const cell = row.regions[region];
                              return (
                                <td key={region} className="py-1.5 pr-2 font-mono">
                                  {cell ? `${cell.recall?.toFixed(3) ?? 'N/A'} / ${cell.coverage?.toFixed(3) ?? 'N/A'} (n=${cell.eligible_windows})` : 'NO_DATA'}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })()}
          </div>
        </>
      )}
    />
  );
}
