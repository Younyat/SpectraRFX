import { useCallback, useEffect, useState } from 'react';
import {
  BleScientificResultsApiService,
  EvidenceDashboardClosedSet,
  EvidenceDashboardPerUnitRun,
  EvidenceDashboardSummary,
  EvidenceFigureRegenerationResult,
  PartitionCompositionTable,
  Rq2BranchResult,
} from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import RiskCoverageChart from './charts/RiskCoverageChart';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

function domainBars(rq1: EvidenceDashboardClosedSet['rq1']): BarWithCiDatum[] {
  if (!rq1) return [];
  const bars: BarWithCiDatum[] = [];
  if (typeof rq1.ba_window === 'number') bars.push({ category: 'BA_window (intra-session)', value: rq1.ba_window });
  if (typeof rq1.ba_capture === 'number') {
    // ba_window intentionally has no CI here -- it's the leakage-violating
    // diagnostic, never a valid estimator; only ba_capture (capture-disjoint,
    // confirmatory) gets a real cluster-bootstrap CI.
    const ci = rq1.uncertainty_ci?.ba_capture_ci;
    bars.push({ category: 'BA_capture (capture-disjoint)', value: rq1.ba_capture, ciLow: ci?.ci_low, ciHigh: ci?.ci_high });
  }
  // The current TEST result is NOT protected FUTURE -- FUTURE has not been
  // executed yet (protected_future_test_status stays UNTOUCHED until then).
  if (typeof rq1.ba_future === 'number') bars.push({ category: 'BA_future (protected FUTURE, if executed)', value: rq1.ba_future });
  return bars;
}

function branchBars(rq2: EvidenceDashboardClosedSet['rq2'], field: 'balanced_accuracy' | 'macro_f1'): BarWithCiDatum[] {
  const branches = (rq2?.branches as Rq2BranchResult[] | undefined) ?? [];
  return branches
    .filter((b) => typeof b[field] === 'number')
    .map((b) => ({ category: `${b.branch} (${b.analysis_role})`, value: b[field] as number }));
}

function computationalCostBars(rq2: EvidenceDashboardClosedSet['rq2'], field: 'inference_latency_ms' | 'serialized_model_size_bytes'): BarWithCiDatum[] {
  const branches = (rq2?.branches as Rq2BranchResult[] | undefined) ?? [];
  return branches.filter((b) => typeof b[field] === 'number').map((b) => ({ category: b.branch, value: b[field] as number }));
}

function primaryBranch(rq2: EvidenceDashboardClosedSet['rq2']): Rq2BranchResult | undefined {
  const branches = (rq2?.branches as Rq2BranchResult[] | undefined) ?? [];
  return branches.find((b) => b.analysis_role === 'PRIMARY');
}

function seedVariabilityBars(rq2: EvidenceDashboardClosedSet['rq2']): BarWithCiDatum[] {
  const primary = primaryBranch(rq2);
  return (primary?.seed_variability ?? [])
    .filter((s) => typeof s.validation_balanced_accuracy === 'number')
    .map((s) => ({ category: `seed ${s.seed}`, value: s.validation_balanced_accuracy as number }));
}

function perClassBars(byClass: Record<string, number> | null | undefined): BarWithCiDatum[] {
  if (!byClass) return [];
  return Object.entries(byClass).map(([unit, value]) => ({ category: unit, value }));
}

function Provenance({ items }: { items: (string | null | undefined)[] }) {
  const parts = items.filter((v): v is string => !!v);
  if (parts.length === 0) return null;
  return <div className="mt-1 font-mono text-[10.5px] text-slate-500">{parts.join(' · ')}</div>;
}

function ClosedSetSection({ closedSet, partitionComposition }: { closedSet: EvidenceDashboardClosedSet | null; partitionComposition: PartitionCompositionTable | null }) {
  if (!closedSet) {
    return <NoDataNotice reason="Ningun paper_run con scientific_task=MULTI_DEVICE_CLASSIFICATION existe todavia." />;
  }
  const primaryTest = closedSet.primary_test;
  const domains = partitionComposition?.domains;
  return (
    <div className="space-y-4">
      <Provenance items={[`paper_run_id=${closedSet.paper_run_id}`, `dataset_id=${closedSet.dataset_id}`, `dataset_version=${closedSet.dataset_version}`]} />

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-400">RQ1 -- BA por dominio de evaluacion</div>
        <BarWithCiChart data={domainBars(closedSet.rq1)} yLabel="Balanced accuracy" noDataReason="rq1_acquisition_dependence_report.json no existe todavia para este run." />
        {closedSet.rq1 && typeof closedSet.rq1.delta_dependence === 'number' && (
          <div className="mt-1 text-[11px] text-slate-500">
            delta_dependence = <span className="font-mono text-slate-300">{closedSet.rq1.delta_dependence.toFixed(4)}</span>
            {' · '}ba_future_status = <span className="font-mono text-slate-300">{closedSet.rq1.ba_future_status}</span>
          </div>
        )}
        {domains && (
          <div className="mt-1 text-[11px] text-slate-500">
            tamano efectivo (VALIDATION) = <span className="font-mono text-slate-300">{domains.VALIDATION.n_examples}</span> examples (ExampleRecord, RQ1's real evaluation unit)
            {' / '}<span className="font-mono text-slate-300">{domains.VALIDATION.n_captures}</span> capturas independientes
            {' · '}(TEST) = <span className="font-mono text-slate-300">{domains.TEST.n_examples}</span> examples / <span className="font-mono text-slate-300">{domains.TEST.n_captures}</span> capturas
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">RQ2 -- balanced accuracy por rama (VALIDATION)</div>
          <BarWithCiChart data={branchBars(closedSet.rq2, 'balanced_accuracy')} yLabel="Balanced accuracy" noDataReason="rq2_representation_comparison_report.json no existe todavia para este run." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">RQ2 -- macro-F1 por rama (VALIDATION)</div>
          <BarWithCiChart data={branchBars(closedSet.rq2, 'macro_f1')} yLabel="Macro-F1" noDataReason="rq2_representation_comparison_report.json no existe todavia para este run." />
        </div>
      </div>

      {closedSet.rq2?.selection_rule && (
        <div className="rounded border border-cyan-800 bg-cyan-950/20 px-3 py-2 text-[11px] text-cyan-200">
          PRIMARY seleccionado solo con datos de <span className="font-mono">{closedSet.rq2.selection_domain}</span>: {closedSet.rq2.selection_rule}
          {' · '}FUTURE (cuando exista) es evaluacion, nunca puede cambiar esta seleccion.
        </div>
      )}

      {closedSet.primary_branch && (
        <div className="text-[11px] text-slate-500">
          STUDY PRIMARY BRANCH = <span className="font-mono text-slate-300">{closedSet.primary_branch}</span>
          {' · '}training_run_id = <span className="font-mono text-slate-300">{closedSet.primary_training_run_id}</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Costo computacional -- latencia de inferencia por rama (ms)</div>
          <BarWithCiChart data={computationalCostBars(closedSet.rq2, 'inference_latency_ms')} yLabel="ms" noDataReason="inference_latency_ms no esta presente en ninguna rama." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Costo computacional -- tamano de modelo serializado por rama (bytes)</div>
          <BarWithCiChart data={computationalCostBars(closedSet.rq2, 'serialized_model_size_bytes')} yLabel="bytes" noDataReason="serialized_model_size_bytes no esta presente en ninguna rama." />
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-400">Seed variability -- branch primaria (re-entrenada bajo las semillas congeladas restantes, VALIDATION-only)</div>
        <BarWithCiChart data={seedVariabilityBars(closedSet.rq2)} yLabel="Balanced accuracy" noDataReason="La branch primaria no tiene seed_variability calculado todavia." />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- VALIDATION (capture-disjoint)</div>
          <ConfusionMatrixHeatmap matrix={closedSet.rq1?.confusion_matrix_capture ?? null} noDataReason="confusion_matrix_capture no esta presente en el reporte." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- TEST (branch primaria, held-out)</div>
          <ConfusionMatrixHeatmap matrix={primaryTest?.confusion_matrix ?? null} noDataReason="El training run de la branch primaria todavia no tiene TEST evaluado." />
        </div>
      </div>

      {primaryTest && (
        <div className="text-[11px] text-slate-500">
          PRIMARY TEST: BA = <span className="font-mono text-slate-300">{primaryTest.balanced_accuracy?.toFixed(4) ?? '—'}</span>
          {' · '}macro-F1 = <span className="font-mono text-slate-300">{primaryTest.macro_f1?.toFixed(4) ?? '—'}</span>
          {' · '}accuracy = <span className="font-mono text-slate-300">{primaryTest.accuracy?.toFixed(4) ?? '—'}</span>
          {' · '}n_comparable = <span className="font-mono text-slate-300">{primaryTest.n_comparable_to_known_classes ?? '—'}</span> / <span className="font-mono text-slate-300">{primaryTest.n_examples ?? '—'}</span>
          {' · '}evaluation_validity = <span className="font-mono text-slate-300">{primaryTest.evaluation_validity ?? '—'}</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Precision por unidad (TEST, branch primaria)</div>
          <BarWithCiChart data={perClassBars(primaryTest?.precision_per_class)} yLabel="Precision" noDataReason="precision_per_class no esta presente en la evaluacion TEST." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">F1 por unidad (TEST, branch primaria)</div>
          <BarWithCiChart data={perClassBars(primaryTest?.f1_per_class)} yLabel="F1" noDataReason="f1_per_class no esta presente en la evaluacion TEST." />
        </div>
      </div>

      <div>
        <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-slate-400">
          Risk-coverage (TEST, branch primaria) -- El-Yaniv &amp; Wiener (2010)
          <span className="rounded border border-amber-800 bg-amber-950/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-300">
            CURRENT TEST EVIDENCE
          </span>
        </div>
        <div className="mb-1 text-[10.5px] text-slate-500">
          Ventanas del TEST actual, no de la campana confirmatoria final -- la version DEFINITIVE se regenerara con decision windows de la campana protegida FUTURE cuando exista.
        </div>
        <RiskCoverageChart points={primaryTest?.risk_coverage ?? null} noDataReason="risk_coverage no esta presente en la evaluacion TEST." />
      </div>

      {primaryTest?.recall_per_class && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Recall por unidad (TEST, branch primaria)</div>
          <BarWithCiChart
            data={Object.entries(primaryTest.recall_per_class).map(([unit, recall]) => ({ category: unit, value: recall }))}
            yLabel="Recall" noDataReason="recall_per_class no esta presente en la evaluacion TEST."
          />
        </div>
      )}
    </div>
  );
}

function PerUnitAuxiliarySection({ runs }: { runs: EvidenceDashboardPerUnitRun[] }) {
  if (runs.length === 0) {
    return <NoDataNotice reason="Ningun paper_run con scientific_task=TARGET_VS_BACKGROUND existe todavia." />;
  }
  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">dataset_id</th>
            <th className="px-3 py-2 text-right">BA_window</th>
            <th className="px-3 py-2 text-right">BA_capture</th>
            <th className="px-3 py-2 text-right">delta_dependence</th>
            <th className="px-3 py-2 text-left">primary branch</th>
            <th className="px-3 py-2 text-right">primary BA (VALIDATION)</th>
            <th className="px-3 py-2 text-right">latency (ms)</th>
            <th className="px-3 py-2 text-right">model size (bytes)</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {runs.map((run) => {
            const branches = (run.rq2?.branches as Rq2BranchResult[] | undefined) ?? [];
            const primary = branches.find((b) => b.analysis_role === 'PRIMARY');
            return (
              <tr key={run.paper_run_id}>
                <td className="px-3 py-2 font-mono text-slate-300">{run.dataset_id}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{run.rq1?.ba_window?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{run.rq1?.ba_capture?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{run.rq1?.delta_dependence?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-slate-300">{primary?.branch ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{primary?.balanced_accuracy?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{primary?.inference_latency_ms?.toFixed(2) ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{primary?.serialized_model_size_bytes ?? '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Rq3Section({ rq3 }: { rq3: EvidenceDashboardSummary['rq3'] }) {
  const decision = rq3.sample_size_decision;
  const progress = rq3.campaign_progress;
  return (
    <div className="space-y-3">
      {decision ? (
        <div className="text-[11px] text-slate-500">
          rationale = <span className="font-mono text-slate-300">{decision.rationale}</span>
          {' · '}decided_by = <span className="font-mono text-slate-300">{decision.decided_by ?? '—'}</span>
          {' · '}decided_at = <span className="font-mono text-slate-300">{decision.decided_at}</span>
          <pre className="mt-1 overflow-auto rounded border border-slate-800 bg-slate-950 p-2 text-[11px] text-slate-300">
            {JSON.stringify(decision.selected_value, null, 2)}
          </pre>
        </div>
      ) : (
        <NoDataNotice reason="rq3_sample_size no ha sido registrado todavia via record_scientist_decision()." />
      )}
      <div className="text-[11px] text-slate-500">
        Progreso real de campana: <span className="font-mono text-slate-300">{progress.captures_with_rq3_metadata}</span> de{' '}
        <span className="font-mono text-slate-300">{progress.total_captures}</span> capturas totales tienen day_id/pre_or_post/intervention_arm declarados.
      </div>
      {Object.keys(progress.declared_by_unit).length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2 text-left">unit</th><th className="px-3 py-2 text-right">RESET declarados</th><th className="px-3 py-2 text-right">CONTROL declarados</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {Object.entries(progress.declared_by_unit).map(([unit, counts]) => (
                <tr key={unit}>
                  <td className="px-3 py-2 font-mono text-slate-300">{unit}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-300">{counts.RESET}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-300">{counts.CONTROL}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Rq4Section({ rq4 }: { rq4: EvidenceDashboardSummary['rq4'] }) {
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-slate-500">status = <StatusBadge status={rq4.status} /></div>
      {rq4.physical_units.length === 0 ? (
        <NoDataNotice reason="Ningun physical_unit registrado todavia." />
      ) : (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2 text-left">physical_unit_id</th><th className="px-3 py-2 text-left">eligibility</th><th className="px-3 py-2 text-left">reason</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rq4.physical_units.map((unit) => (
                <tr key={unit.physical_unit_id}>
                  <td className="px-3 py-2 font-mono text-slate-300">{unit.physical_unit_id}</td>
                  <td className="px-3 py-2"><StatusBadge status={unit.rq4_eligibility} /></td>
                  <td className="px-3 py-2 text-slate-400">{unit.rq4_eligibility_reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Real, in-platform paper-support dashboard: aggregates already-persisted
 * RQ1/RQ2 reports (closed-set + per-unit auxiliary runs), the frozen
 * rq3_sample_size decision + live RQ3 campaign progress, and RQ4 per-unit
 * eligibility. Computes nothing -- reads GET /evidence-dashboard, a plain
 * synchronous cross-reference of already-real getters (see
 * ScientificResultsRepository.get_evidence_dashboard_summary). Not
 * run-scoped (unlike RunScopedJsonReport) since it spans every run at
 * once; "Refrescar" simply re-fetches. */
export default function EvidenceDashboardTab() {
  const [data, setData] = useState<EvidenceDashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [partitionComposition, setPartitionComposition] = useState<PartitionCompositionTable | null>(null);

  const [regenerating, setRegenerating] = useState(false);
  const [regenResult, setRegenResult] = useState<EvidenceFigureRegenerationResult | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setPartitionComposition(null);
    sciApi.evidenceDashboardSummary()
      .then((summary) => {
        setData(summary);
        const closedSet = summary.closed_set;
        if (closedSet) {
          sciApi.partitionComposition(closedSet.dataset_id, closedSet.dataset_version, 'MULTI_DEVICE_CLASSIFICATION')
            .then(setPartitionComposition)
            .catch(() => setPartitionComposition(null));
        }
      })
      .catch(() => setError('No se pudo cargar el dashboard de evidencia.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const regenerateFigures = useCallback(() => {
    setRegenerating(true);
    setRegenError(null);
    setRegenResult(null);
    sciApi.regenerateEvidenceFigures()
      .then(setRegenResult)
      .catch(() => setRegenError('No se pudieron regenerar las imagenes/notebook. Revisa que el backend tenga acceso al repositorio (docs/ble/).'))
      .finally(() => setRegenerating(false));
  }, []);

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-slate-200">Evidence Dashboard -- soporte real para el paper</div>
          <div className="mt-1 text-xs text-slate-500">
            RQ1/RQ2 closed-set + 4 runs auxiliares por unidad, RQ3 (tamano muestral congelado + progreso real de campana), RQ4 (elegibilidad por unidad).
            Cada seccion lee directamente su artefacto persistido -- nada se recalcula aqui.
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button" onClick={load} disabled={loading}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {loading ? 'Actualizando…' : 'Refrescar'}
          </button>
          <button
            type="button" onClick={regenerateFigures} disabled={regenerating}
            title="Regenera los PNG de readme_img/ y docs/ble/evidence_figures.ipynb a partir del estado real actual -- exactamente lo mismo que ejecutar generate_evidence_figures.py + build_evidence_notebook.py desde una terminal. No hace commit ni push."
            className="rounded border border-amber-800 bg-amber-950/40 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-900/40 disabled:opacity-50"
          >
            {regenerating ? 'Generando imagenes…' : 'Generar imagenes nuevas (README + notebook)'}
          </button>
        </div>
      </div>

      {error && <NoDataNotice reason={error} />}
      {regenError && <NoDataNotice reason={regenError} />}
      {regenResult && (
        <div className="rounded border border-amber-800 bg-amber-950/20 px-4 py-3 text-[11px] text-amber-200">
          <div className="font-semibold">
            {regenResult.png_files.length} PNG regenerados{regenResult.notebook_written ? ' + notebook actualizado' : ''} en readme_img/ y docs/ble/evidence_figures.ipynb.
          </div>
          <div className="mt-1 font-mono text-amber-300/80">{regenResult.png_files.join(', ')}</div>
          <div className="mt-2 text-amber-300/70">{regenResult.note} (`git add -A &amp;&amp; git commit &amp;&amp; git push` desde una terminal).</div>
        </div>
      )}

      {data && (
        <>
          <Provenance items={[`generated_at=${data.generated_at}`, `git_sha=${data.git_sha}`, `protocol_id=${data.protocol_id}`, `contract_sha256=${data.contract_sha256}`]} />

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">RQ1 / RQ2 -- Closed-set (4-unit, MULTI_DEVICE_CLASSIFICATION)</h3>
            <ClosedSetSection closedSet={data.closed_set} partitionComposition={partitionComposition} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Per-unit auxiliary analysis (TARGET_VS_BACKGROUND)</h3>
            <PerUnitAuxiliarySection runs={data.per_unit_auxiliary} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">RQ3 -- Reset-associated displacement</h3>
            <Rq3Section rq3={data.rq3} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">RQ4 -- Packet-content dependence</h3>
            <Rq4Section rq4={data.rq4} />
          </section>
        </>
      )}
    </div>
  );
}
