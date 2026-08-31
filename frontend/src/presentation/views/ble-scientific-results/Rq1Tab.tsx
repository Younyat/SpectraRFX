import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

// Label fix (2026-08-18, DEVELOPMENT EVIDENCE closure pass): the raw field
// name ba_window reads as if it were the platform's separate 10-second
// decision-window unit (RQ3/RQ4/coverage_analysis's group_examples_into_
// windows) -- it is not. This report's own evaluation_unit is EXAMPLE_RECORD
// (burst-level) for every bar here; only the display label changed, the
// underlying report field names (report.ba_window, etc.) are untouched.
function domainBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const bars: BarWithCiDatum[] = [];
  if (typeof report.ba_window === 'number') bars.push({ category: 'capture-dependent (same capture)', value: report.ba_window });
  if (typeof report.ba_capture === 'number') bars.push({ category: 'capture-disjoint (VALIDATION)', value: report.ba_capture });
  if (typeof report.ba_future === 'number') bars.push({ category: 'protected FUTURE', value: report.ba_future });
  return bars;
}

function deltaBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const bars: BarWithCiDatum[] = [];
  if (typeof report.delta_dependence === 'number') bars.push({ category: 'delta_dependence (capture-dependent - capture-disjoint)', value: report.delta_dependence });
  if (typeof report.delta_future === 'number') bars.push({ category: 'delta_future', value: report.delta_future });
  return bars;
}

function perUnitRecallBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const perUnit = report.per_unit_recall as Record<string, { recall?: number | null }> | null | undefined;
  if (!perUnit) return [];
  return Object.entries(perUnit)
    .filter(([, v]) => typeof v?.recall === 'number')
    .map(([unitId, v]) => ({ category: unitId, value: v.recall as number }));
}

export default function Rq1Tab() {
  return (
    <RunScopedJsonReport
      title="RQ1 -- Acquisition dependence"
      description="Capture-dependent / capture-disjoint / protected FUTURE (EXAMPLE_RECORD-level, not the platform's separate 10-second decision-window unit), deltas, cobertura -- leidos directamente de rq1_acquisition_dependence_report.json (persist_rq1_acquisition_dependence_report). No se recalcula nada aqui."
      noDataReason="rq1_acquisition_dependence_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
      fetchReport={(paperRunId) => sciApi.rq1AcquisitionDependence(paperRunId)}
      renderCharts={(report) => {
        const futureAvailable = typeof report.ba_future === 'number';
        return (
          <>
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span>dominio window/capture:</span><EvidenceMaturityBadge maturity="VALIDATION" />
              <span className="ml-3">dominio future:</span>
              {futureAvailable ? <EvidenceMaturityBadge maturity="CONFIRMATORY" /> : <span className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-slate-500">SEALED / NO_DATA</span>}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">BA por dominio de evaluacion</div>
              <BarWithCiChart data={domainBars(report)} yLabel="Balanced accuracy" noDataReason="capture-dependent/capture-disjoint no estan presentes en el reporte." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Deltas (acquisition-dependence / future)</div>
              <BarWithCiChart data={deltaBars(report)} yLabel="delta" noDataReason="delta_dependence/delta_future no estan presentes en el reporte." />
            </div>
            {report.uncertainty_ci != null && (
              <div className="text-[11px] text-slate-500">
                uncertainty_ci (tal como fue persistido, sin reinterpretar su forma): <span className="font-mono text-slate-300">{JSON.stringify(report.uncertainty_ci)}</span>
              </div>
            )}
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Recall por unidad fisica</div>
              <BarWithCiChart data={perUnitRecallBars(report)} yLabel="Recall" noDataReason="per_unit_recall no esta presente en el reporte." />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- capture-disjoint</div>
                <ConfusionMatrixHeatmap matrix={report.confusion_matrix_capture as Record<string, Record<string, number>> | null} noDataReason="confusion_matrix_capture no esta presente en el reporte." />
              </div>
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- future{!futureAvailable ? ' (SEALED)' : ''}</div>
                <ConfusionMatrixHeatmap matrix={report.confusion_matrix_future as Record<string, Record<string, number>> | null} noDataReason="confusion_matrix_future no esta presente en el reporte -- FUTURE sellado o no comparado todavia." />
              </div>
            </div>
          </>
        );
      }}
    />
  );
}
