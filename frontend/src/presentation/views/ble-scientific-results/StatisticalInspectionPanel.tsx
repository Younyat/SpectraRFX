// Common statistical-inspection panel (2026-08-11) -- one place to read
// estimate/CI/experimental unit/independent blocks/method/raw p/adjusted
// p/decision for a confirmatory result, reused across RQ1-4, instead of
// requiring "opening the JSON" to understand the inference. Every field is
// read verbatim from confirmatory_future_analysis_report.json's own
// MethodResult shape ({status, detail, value}) -- this module computes
// nothing, and reports MISSING_CANONICAL_METRIC (never a blank/0) for any
// quantity the canonical analysis does not expose.

export interface StatisticalInspectionRow {
  label: string;
  method: string;
  experimentalUnit: string | null;
  estimate: number | null;
  ciLow: number | null;
  ciHigh: number | null;
  independentBlocks: number | null;
  rawP: number | null;
  decision: string | null;
}

type MethodResult = { status?: string; detail?: string | null; value?: unknown } | undefined;

function n(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

/** hierarchical_cluster_bootstrap -- BootstrapCiResult. */
export function bootstrapRow(report: Record<string, unknown>, label: string, experimentalUnit: string): StatisticalInspectionRow | null {
  const method = report.hierarchical_cluster_bootstrap as MethodResult;
  if (method?.status !== 'EXECUTED') return null;
  const value = method.value as Record<string, unknown> | undefined;
  return {
    label, method: 'hierarchical cluster bootstrap (percentile CI)', experimentalUnit,
    estimate: n(value?.point_estimate), ciLow: n(value?.ci_low), ciHigh: n(value?.ci_high),
    independentBlocks: n(value?.n_resamples), rawP: null, decision: null,
  };
}

/** rq3_within_device_permutation_test -- StratifiedCrossoverTestResult. */
export function rq3PermutationRow(report: Record<string, unknown>): StatisticalInspectionRow | null {
  const method = report.rq3_within_device_permutation_test as MethodResult;
  if (method?.status !== 'EXECUTED') return null;
  const value = method.value as Record<string, unknown> | undefined;
  return {
    label: 'RQ3 -- reset-associated displacement', method: value?.exact ? 'stratified permutation test (exact)' : 'stratified permutation test (Monte Carlo)',
    experimentalUnit: 'device-day', estimate: n(value?.observed_statistic), ciLow: null, ciHigh: null,
    independentBlocks: n(value?.n_permutations), rawP: n(value?.p_value), decision: null,
  };
}

/** rq4_paired_comparison -- PairedContrast + exact randomization test. */
export function rq4PairedComparisonRow(report: Record<string, unknown>): StatisticalInspectionRow | null {
  const method = report.rq4_paired_comparison as MethodResult;
  if (method?.status !== 'EXECUTED') return null;
  const value = method.value as { contrast?: Record<string, unknown>; randomization_test?: Record<string, unknown> } | undefined;
  return {
    label: 'RQ4 -- paired region/condition comparison', method: 'exact randomization test on paired differences',
    experimentalUnit: 'physical unit', estimate: n(value?.contrast?.mean_difference), ciLow: null, ciHigh: null,
    independentBlocks: n(value?.contrast?.n_pairs), rawP: n(value?.randomization_test?.p_value), decision: null,
  };
}

/** non_inferiority -- NonInferiorityResult (one-sided). */
export function nonInferiorityRow(report: Record<string, unknown>): StatisticalInspectionRow | null {
  const method = report.non_inferiority as MethodResult;
  if (method?.status !== 'EXECUTED') return null;
  const value = method.value as Record<string, unknown> | undefined;
  return {
    label: 'RQ4 -- non-inferiority', method: 'one-sided non-inferiority test (t-distribution CI)',
    experimentalUnit: 'physical unit', estimate: n(value?.mean_difference), ciLow: n(value?.ci_low), ciHigh: null,
    independentBlocks: null, rawP: null, decision: value?.non_inferior === true ? 'NON_INFERIOR' : value?.non_inferior === false ? 'NOT_NON_INFERIOR' : null,
  };
}

export interface HolmSummary {
  pValues: number[];
  adjustedPValues: number[];
  reject: boolean[];
}

/** holm_correction -- HolmResult. Kept separate from the per-RQ rows above:
 * the persisted report does not declare which array index maps to which
 * hypothesis (the mapping is implicit in run_confirmatory_statistical_plan's
 * own call order), so this panel shows the real arrays as-is rather than
 * guessing a row-to-index correspondence that could be wrong. */
export function holmSummary(report: Record<string, unknown>): HolmSummary | null {
  const method = report.holm_correction as MethodResult;
  if (method?.status !== 'EXECUTED') return null;
  const value = method.value as Record<string, unknown> | undefined;
  const pValues = value?.p_values;
  const adjustedPValues = value?.adjusted_p_values;
  const reject = value?.reject;
  if (!Array.isArray(pValues) || !Array.isArray(adjustedPValues) || !Array.isArray(reject)) return null;
  return { pValues, adjustedPValues, reject };
}

function fmt(value: number | null): string {
  return value === null ? 'MISSING_CANONICAL_METRIC' : value.toFixed(4);
}

export default function StatisticalInspectionPanel({ rows, holm, noDataReason }: { rows: (StatisticalInspectionRow | null)[]; holm?: HolmSummary | null; noDataReason: string }) {
  const realRows = rows.filter((r): r is StatisticalInspectionRow => r !== null);
  if (realRows.length === 0) {
    return <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center text-xs text-slate-500">{noDataReason}</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-slate-800 text-left text-slate-500">
            <th className="py-1 pr-2 font-medium">Resultado</th>
            <th className="py-1 pr-2 font-medium">Metodo</th>
            <th className="py-1 pr-2 font-medium">Unidad experimental</th>
            <th className="py-1 pr-2 font-medium">Estimacion</th>
            <th className="py-1 pr-2 font-medium">CI</th>
            <th className="py-1 pr-2 font-medium">Bloques independientes</th>
            <th className="py-1 pr-2 font-medium">p (crudo)</th>
            <th className="py-1 pr-2 font-medium">Decision</th>
          </tr>
        </thead>
        <tbody>
          {realRows.map((row) => (
            <tr key={row.label} className="border-b border-slate-900 text-slate-300">
              <td className="py-1.5 pr-2 text-slate-200">{row.label}</td>
              <td className="py-1.5 pr-2 text-slate-500">{row.method}</td>
              <td className="py-1.5 pr-2 text-slate-500">{row.experimentalUnit ?? 'MISSING_CANONICAL_METRIC'}</td>
              <td className="py-1.5 pr-2 font-mono">{fmt(row.estimate)}</td>
              <td className="py-1.5 pr-2 font-mono">{row.ciLow !== null ? `[${row.ciLow.toFixed(4)}, ${row.ciHigh !== null ? row.ciHigh.toFixed(4) : '+inf)'}` : 'MISSING_CANONICAL_METRIC'}</td>
              <td className="py-1.5 pr-2 font-mono">{row.independentBlocks ?? 'MISSING_CANONICAL_METRIC'}</td>
              <td className="py-1.5 pr-2 font-mono">{fmt(row.rawP)}</td>
              <td className="py-1.5 pr-2">{row.decision ?? 'N/A'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {holm && (
        <div className="mt-2 text-[11px] text-slate-500">
          Correccion de Holm (familia confirmatoria, orden real de ejecucion -- ver holm_correction en el JSON crudo
          para el mapeo hipotesis-indice): p crudos=[{holm.pValues.map((v) => v.toFixed(4)).join(', ')}], p
          ajustados=[{holm.adjustedPValues.map((v) => v.toFixed(4)).join(', ')}], reject=[{holm.reject.map((v) => String(v)).join(', ')}]
        </div>
      )}
    </div>
  );
}
