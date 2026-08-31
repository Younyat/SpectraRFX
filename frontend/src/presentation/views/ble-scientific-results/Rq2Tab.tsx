import { BleScientificResultsApiService, Rq2BranchResult } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ScatterChart, { ScatterDatum } from './charts/ScatterChart';
import EvidenceMaturityBadge, { EvidenceMaturity } from './EvidenceMaturityBadge';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function branches(report: Record<string, unknown>): Rq2BranchResult[] {
  const value = report.branches;
  return Array.isArray(value) ? (value as Rq2BranchResult[]) : [];
}

function branchLabel(b: Rq2BranchResult): string {
  return `${b.branch} (${b.analysis_role})`;
}

function ciBars(list: Rq2BranchResult[], field: 'balanced_accuracy' | 'macro_f1' | 'coverage'): BarWithCiDatum[] {
  return list
    .filter((b) => typeof b[field] === 'number')
    .map((b) => ({
      category: branchLabel(b), value: b[field] as number,
      ciLow: field === 'balanced_accuracy' ? b.balanced_accuracy_ci?.ci_low ?? null : null,
      ciHigh: field === 'balanced_accuracy' ? b.balanced_accuracy_ci?.ci_high ?? null : null,
    }));
}

function computationalBars(list: Rq2BranchResult[], field: 'serialized_model_size_bytes' | 'inference_latency_ms'): BarWithCiDatum[] {
  return list.filter((b) => typeof b[field] === 'number').map((b) => ({ category: branchLabel(b), value: b[field] as number }));
}

function evaluationDomainMaturity(domain: string | undefined): EvidenceMaturity {
  if (!domain) return 'VALIDATION';
  const upper = domain.toUpperCase();
  if (upper.includes('CONFIRMATORY') || upper.includes('FUTURE')) return 'CONFIRMATORY';
  if (upper.includes('DEVELOPMENT')) return 'DEVELOPMENT';
  return 'VALIDATION';
}

function performanceLatencyScatter(list: Rq2BranchResult[]): ScatterDatum[] {
  return list
    .filter((b) => typeof b.inference_latency_ms === 'number' && typeof b.balanced_accuracy === 'number')
    .map((b) => ({ label: branchLabel(b), x: b.inference_latency_ms as number, y: b.balanced_accuracy as number }));
}

function seedVariabilityBars(list: Rq2BranchResult[]): { branch: Rq2BranchResult; bars: BarWithCiDatum[] } | null {
  const primary = list.find((b) => b.analysis_role === 'PRIMARY' && b.seed_variability && b.seed_variability.length > 0);
  if (!primary || !primary.seed_variability) return null;
  return {
    branch: primary,
    bars: primary.seed_variability
      .filter((s) => typeof s.validation_balanced_accuracy === 'number')
      .map((s) => ({ category: `seed ${s.seed}`, value: s.validation_balanced_accuracy as number })),
  };
}

function classwiseRecallRows(list: Rq2BranchResult[]): { branch: string; recall: Record<string, number> }[] {
  return list.filter((b) => b.classwise_recall && Object.keys(b.classwise_recall).length > 0).map((b) => ({ branch: branchLabel(b), recall: b.classwise_recall as Record<string, number> }));
}

export default function Rq2Tab() {
  return (
    <RunScopedJsonReport
      title="RQ2 -- Representation comparison"
      description="Engineered RF / raw I/Q CNN1D / STFT CNN2D / coarse morphology -- leido de rq2_representation_comparison_report.json (persist_rq2_representation_comparison_report). Cada rama declara su propio analysis_role (PRIMARY/SENSITIVITY/UNSELECTED); nada se recalcula aqui."
      noDataReason="rq2_representation_comparison_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.rq2RepresentationComparison(paperRunId)}
      renderCharts={(report) => {
        const list = branches(report);
        const seedVariability = seedVariabilityBars(list);
        const recallRows = classwiseRecallRows(list);
        return (
          <>
            <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
              {list.map((b) => (
                <span key={b.branch} className="flex items-center gap-1">
                  {branchLabel(b)}: <EvidenceMaturityBadge maturity={evaluationDomainMaturity(b.evaluation_domain)} />
                </span>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Balanced accuracy por rama (+ CI cuando existe)</div>
              <BarWithCiChart data={ciBars(list, 'balanced_accuracy')} yLabel="Balanced accuracy" noDataReason="Ninguna rama tiene balanced_accuracy real en el reporte." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Macro-F1 por rama</div>
              <BarWithCiChart data={ciBars(list, 'macro_f1')} yLabel="Macro-F1" noDataReason="Ninguna rama tiene macro_f1 real en el reporte." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por rama</div>
              <BarWithCiChart data={ciBars(list, 'coverage')} yLabel="Coverage" noDataReason="Ninguna rama tiene coverage real en el reporte." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Recall por clase y rama</div>
              {recallRows.length === 0 ? (
                <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center text-xs text-slate-500">Ninguna rama tiene classwise_recall real en el reporte.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[500px] border-collapse text-[11px]">
                    <thead><tr className="border-b border-slate-800 text-left text-slate-500"><th className="py-1 pr-2">rama</th><th className="py-1 pr-2">recall por clase</th></tr></thead>
                    <tbody>
                      {recallRows.map((row) => (
                        <tr key={row.branch} className="border-b border-slate-900 text-slate-300">
                          <td className="py-1.5 pr-2">{row.branch}</td>
                          <td className="py-1.5 pr-2 font-mono">{Object.entries(row.recall).map(([cls, v]) => `${cls}=${v.toFixed(3)}`).join(', ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">Tamano de modelo serializado por rama</div>
                <BarWithCiChart data={computationalBars(list, 'serialized_model_size_bytes')} yLabel="bytes" noDataReason="Ninguna rama tiene serialized_model_size_bytes real en el reporte." />
              </div>
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">Latencia de inferencia por rama (valor unico medido, no una distribucion)</div>
                <BarWithCiChart data={computationalBars(list, 'inference_latency_ms')} yLabel="ms" noDataReason="Ninguna rama tiene inference_latency_ms real en el reporte." />
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Performance vs latencia</div>
              <ScatterChart data={performanceLatencyScatter(list)} xLabel="latencia de inferencia (ms)" yLabel="balanced accuracy" noDataReason="Ninguna rama tiene balanced_accuracy e inference_latency_ms reales a la vez." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">
                Variabilidad por semilla (solo rama PRIMARY -- train_seed_variability_analysis, real, VALIDATION-only)
              </div>
              {seedVariability ? (
                <BarWithCiChart data={seedVariability.bars} yLabel="Balanced accuracy (VALIDATION)" noDataReason="La rama PRIMARY no tiene seed_variability real en el reporte." />
              ) : (
                <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center text-xs text-slate-500">
                  Ninguna rama PRIMARY tiene seed_variability real en el reporte todavia -- se calcula solo para la rama PRIMARY (coste real acotado), nunca para SENSITIVITY/UNSELECTED.
                </div>
              )}
            </div>
          </>
        );
      }}
    />
  );
}
