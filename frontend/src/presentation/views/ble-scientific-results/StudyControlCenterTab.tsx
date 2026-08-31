import { useEffect, useState } from 'react';
import { BleRffiStudioApiService, StudioJob, StudioPaperCampaignRejection, StudioPaperCampaignSchedule, StudioPhysicalUnit } from '../../../app/services/bleRffiStudioApi';
import {
  BleScientificResultsApiService, ChannelTransportAnalysisJob, ConfirmatoryFutureAnalysisJob, CoverageAnalysisJob, HardwareQualificationJob, HierarchicalDesignInput, HoldoutGroupAssignment, NoDataResponse,
  OfflineNearliveAnalysisJob, PaperRunRecord, Rq2BenchmarkJob, Rq3FrrAnalysisJob, Rq4RegionAnalysisJob, SensitivityAnalysisJob, StudyControlCenterStatus,
  StudySizingDecision, StudySizingEvaluationResult,
} from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';
import AnalysisContractReadinessPanel from './AnalysisContractReadinessPanel';

const sciApi = new BleScientificResultsApiService();
const studioApi = new BleRffiStudioApiService();

const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

async function pollJob(jobId: string, onUpdate: (job: HardwareQualificationJob) => void): Promise<HardwareQualificationJob> {
  let current = await sciApi.getHardwareQualificationJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getHardwareQualificationJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Study Control Center, Phase 1 (2026-08-11): the 17-phase experimental
 * workflow map (read-only aggregation, computes no science) plus the RUN
 * REAL HARDWARE QUALIFICATION launcher -- the same real job/canonical
 * artifact path both the developer and a lab operator use; there is no
 * separate, simplified frontend flow and no hidden CLI step. */
export default function StudyControlCenterTab() {
  const [status, setStatus] = useState<StudyControlCenterStatus | null>(null);

  const refresh = () => {
    sciApi.getStudyControlCenterStatus().then(setStatus).catch(() => setStatus(null));
  };
  useEffect(refresh, []);

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Study Control Center</div>
        <div className="mt-1 text-xs text-slate-500">
          El mismo workflow experimental para el desarrollador y el operador de laboratorio -- sin un paso de CLI
          oculto del que dependa ningun resultado del paper. Cada fase se bloquea automaticamente con la razon real
          cuando falta un prerrequisito.
        </div>
      </div>

      {!status && <NoDataNotice reason="Cargando el estado del Study Control Center..." />}
      {status && (
        <>
          <div className="rounded border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-400">
            <span className="font-semibold text-slate-200">{status.phases_with_mechanism_and_launcher_ready}/{status.phases_total}</span> fases
            operacionalmente cerradas (mechanism=READY y launcher=READY) -- independiente de si ya se han ejecutado de verdad.
          </div>
          <div className="space-y-2">
            {status.phases.map((phase) => (
              <div key={phase.phase_id} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-500">{phase.phase_id}</span>
                  <span className="text-sm font-semibold text-slate-200">{phase.label}</span>
                  {phase.next_allowed_operation && <span className="text-[11px] text-cyan-400">{phase.next_allowed_operation}</span>}
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]">
                  <span className="flex items-center gap-1"><span className="text-slate-500">mechanism</span><StatusBadge status={phase.mechanism_state} /></span>
                  <span className="flex items-center gap-1"><span className="text-slate-500">launcher</span><StatusBadge status={phase.launcher_state} /></span>
                  <span className="flex items-center gap-1"><span className="text-slate-500">execution</span><StatusBadge status={phase.execution_state} /></span>
                </div>
                {phase.blocking_reasons.length > 0 && (
                  <div className="mt-1 text-[11px] text-red-400">
                    BLOCKED -- Missing: {phase.blocking_reasons.join(', ')}
                  </div>
                )}
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
                  <span>run_id: {phase.run_id ?? 'N/A'}</span>
                  <span>git_sha: {phase.git_sha.slice(0, 12)}</span>
                  <span>protocol_version: {phase.protocol_version ?? 'N/A'}</span>
                  <span>paper_section: {phase.paper_section}</span>
                  <span>real_data: {phase.real_data_available ? 'yes' : 'no'}</span>
                </div>
                {phase.artifacts.length > 0 && (
                  <div className="mt-1 text-[11px] text-slate-600">artifacts: {phase.artifacts.join(', ')}</div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      <HardwareQualificationLauncher onCompleted={refresh} />
      <PhysicalUnitQualificationLauncher onCompleted={refresh} />
      <StudySizingLauncher onCompleted={refresh} />
      <Rq2BenchmarkLauncher onCompleted={refresh} />
      <DefinitiveControlledCampaignPanel protocolFrozen={status?.phases.find((p) => p.phase_id === '10')?.execution_state === 'COMPLETE'} />
      <Rq3FrrAnalysisLauncher onCompleted={refresh} />
      <Rq4RegionAnalysisLauncher onCompleted={refresh} />
      <CoverageAnalysisLauncher onCompleted={refresh} />
      <SensitivityAnalysisLauncher onCompleted={refresh} />
      <ChannelTransportAnalysisLauncher onCompleted={refresh} />
      <OfflineNearliveAnalysisLauncher onCompleted={refresh} />
      <ProtectedFutureLauncher
        protocolFrozen={status?.phases.find((p) => p.phase_id === '10')?.execution_state === 'COMPLETE'}
        onCompleted={refresh}
      />
      <ConfirmatoryFutureAnalysisLauncher onCompleted={refresh} />
      <AnalysisContractReadinessPanel onCompleted={refresh} />
      <CampaignScheduleLauncher onCompleted={refresh} />
    </div>
  );
}

async function pollStudioJob(jobId: string, onUpdate: (job: StudioJob) => void): Promise<StudioJob> {
  let current = await studioApi.job(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await studioApi.job(jobId);
    onUpdate(current);
  }
  return current;
}

function CampaignScheduleLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [scheduleId, setScheduleId] = useState('');
  const [protocolId, setProtocolId] = useState('');
  const [entriesJson, setEntriesJson] = useState('[]');
  const [qualificationOnly, setQualificationOnly] = useState(true);
  const [schedule, setSchedule] = useState<StudioPaperCampaignSchedule | null>(null);
  const [rejections, setRejections] = useState<StudioPaperCampaignRejection[]>([]);
  const [job, setJob] = useState<StudioJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshSchedule = (id: string) => {
    if (!id) return;
    studioApi.getCampaignSchedule(id).then(setSchedule).catch(() => setSchedule(null));
    studioApi.getCampaignScheduleRejections(id).then(setRejections).catch(() => setRejections([]));
  };

  const freeze = async () => {
    setError(null);
    let entries: Record<string, unknown>[];
    try {
      entries = JSON.parse(entriesJson);
    } catch {
      setError('entries debe ser un JSON valido (lista de PaperCampaignScheduleEntry).');
      return;
    }
    if (!scheduleId || !protocolId) { setError('schedule_id y protocol_id son obligatorios.'); return; }
    setBusy(true);
    try {
      await studioApi.freezeCampaignSchedule({ schedule_id: scheduleId, protocol_id: protocolId, entries, qualification_only: qualificationOnly });
      refreshSchedule(scheduleId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const executeNext = async () => {
    setBusy(true);
    setJob(null);
    try {
      const started = await studioApi.executeNextCampaignScheduleCapture(scheduleId, {});
      const finished = await pollStudioJob(started.job_id, setJob);
      refreshSchedule(scheduleId);
      if (finished.state === 'completed') onCompleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const pendingCount = schedule ? schedule.entries.filter((e) => !e.executed).length : 0;
  const nextEntry = schedule ? schedule.entries.find((e) => !e.executed) : undefined;

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">Campaign Schedule (fases 04 Qualification Pilot / 06 DEVELOPMENT / 07 VALIDATION)</div>
      <div className="mt-1 text-xs text-slate-500">
        Un unico mecanismo real (PaperCampaignRunner) sirve las 3 fases -- solo cambia el schedule congelado y
        qualification_only. Rechaza automaticamente cualquier captura fuera de orden o con parametros que no
        coincidan con lo declarado (WRONG_UNIT, WRONG_CHANNEL, WRONG_CAPTURE_ORDER, etc.), persistido en
        rejections.jsonl.
      </div>
      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-slate-500">schedule_id</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={scheduleId} onChange={(e) => setScheduleId(e.target.value)} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">protocol_id</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={protocolId} onChange={(e) => setProtocolId(e.target.value)} disabled={busy} />
        </div>
        <div className="flex items-end gap-2">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={qualificationOnly} onChange={(e) => setQualificationOnly(e.target.checked)} disabled={busy} />
            qualification_only (fase 04)
          </label>
        </div>
      </div>

      <div className="mt-3">
        <label className="mb-1 block text-xs text-slate-500">entries (JSON -- lista de PaperCampaignScheduleEntry)</label>
        <textarea
          className="h-32 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 font-mono text-xs text-slate-100 focus:border-cyan-600 focus:outline-none"
          value={entriesJson} onChange={(e) => setEntriesJson(e.target.value)} disabled={busy}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700" disabled={busy} onClick={freeze}>
          Congelar schedule
        </button>
        <button className="rounded border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || !scheduleId} onClick={() => refreshSchedule(scheduleId)}>
          Ver estado
        </button>
        <button className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-700" disabled={busy || !schedule || pendingCount === 0} onClick={executeNext}>
          {busy ? 'Ejecutando...' : 'RUN NEXT PLANNED CAPTURE'}
        </button>
      </div>

      {schedule && (
        <div className="mt-4 space-y-2">
          <div className="text-xs text-slate-400">
            {schedule.entries.length - pendingCount}/{schedule.entries.length} ejecutadas
            {nextEntry && <> -- siguiente: <span className="font-mono text-slate-200">{nextEntry.planned_capture_id}</span> ({nextEntry.physical_unit_id}, {nextEntry.day_id}, {nextEntry.pre_or_post})</>}
          </div>
          <div className="grid gap-1 text-[11px]">
            {schedule.entries.map((entry) => (
              <div key={entry.planned_capture_id} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950 px-2 py-1">
                <span className="font-mono text-slate-400">{entry.planned_capture_id}</span>
                <span className="text-slate-500">{entry.physical_unit_id} / {entry.day_id} / {entry.pre_or_post} / {entry.intervention_arm}</span>
                <StatusBadge status={entry.executed ? 'COMPLETE' : 'NOT_STARTED'} />
              </div>
            ))}
          </div>
        </div>
      )}

      {rejections.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold text-red-400">rejections.jsonl ({rejections.length})</div>
          <div className="space-y-1 text-[11px]">
            {rejections.map((rejection, index) => (
              <div key={index} className="rounded border border-red-900 bg-red-950/30 px-2 py-1 text-red-300">
                {rejection.planned_capture_id ?? '(sin planned_capture_id)'}: {rejection.reason}
              </div>
            ))}
          </div>
        </div>
      )}

      {job && (
        <div className="mt-4 space-y-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">phase: {job.phase ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round((job.overall_progress ?? 0) * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
        </div>
      )}
    </div>
  );
}

function isNoDataResponse(value: unknown): value is NoDataResponse {
  return !!value && typeof value === 'object' && (value as NoDataResponse).status === 'NO_DATA';
}

function StudySizingLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [designsJson, setDesignsJson] = useState('[{"n_units": 8, "n_days": 4, "n_captures_per_unit_day": 5, "icc_unit": 0.1, "icc_day": 0.05}]');
  const [p1, setP1] = useState(0.5);
  const [p2, setP2] = useState(0.8);
  const [targetPower, setTargetPower] = useState(0.8);
  const [evaluation, setEvaluation] = useState<StudySizingEvaluationResult | null>(null);
  const [decision, setDecision] = useState<StudySizingDecision | NoDataResponse | null>(null);
  const [rationale, setRationale] = useState('');
  const [chosenIndex, setChosenIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.getStudySizingDecision().then(setDecision).catch(() => setDecision(null));
  }, []);

  const evaluate = async () => {
    setError(null);
    let candidateDesigns: HierarchicalDesignInput[];
    try {
      candidateDesigns = JSON.parse(designsJson);
    } catch {
      setError('candidate_designs debe ser un JSON valido (lista de HierarchicalDesign).');
      return;
    }
    setBusy(true);
    try {
      const result = await sciApi.evaluateStudySizing({ candidate_designs: candidateDesigns, p1, p2, target_power: targetPower });
      setEvaluation(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const recordDecision = async () => {
    if (!evaluation || !rationale.trim()) { setError('Se requiere una rationale real para registrar la decision.'); return; }
    setBusy(true);
    try {
      const chosen = evaluation.evaluations[chosenIndex].design;
      const recorded = await sciApi.recordStudySizingDecision({
        chosen_design: { n_units: chosen.n_units, n_days: chosen.n_days, n_captures_per_unit_day: chosen.n_captures_per_unit_day, icc_unit: chosen.icc_unit, icc_day: chosen.icc_day },
        p1, p2, target_power: targetPower, rationale,
      });
      setDecision(recorded);
      onCompleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">Study Sizing (fase 05)</div>
      <div className="mt-1 text-xs text-slate-500">
        Envuelve statistics/power_simulation.py (closed_form_power_two_proportions / evaluate_design_sufficiency /
        find_minimum_sufficient_design), previamente real pero sin ninguna ruta. La decision de sizing es siempre una
        eleccion humana explicita y razonada -- nunca el diseno minimo suficiente se persiste automaticamente.
      </div>
      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {decision && !isNoDataResponse(decision) && (
        <div className="mt-2 rounded border border-emerald-800 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-300">
          Decision registrada: n_units={decision.design.n_units}, power={decision.power.toFixed(3)}, verdict={decision.verdict}
        </div>
      )}

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-slate-500">p1 (tasa base)</label>
          <input type="number" step="0.01" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={p1} onChange={(e) => setP1(Number(e.target.value))} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">p2 (tasa alternativa)</label>
          <input type="number" step="0.01" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={p2} onChange={(e) => setP2(Number(e.target.value))} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">target_power</label>
          <input type="number" step="0.01" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={targetPower} onChange={(e) => setTargetPower(Number(e.target.value))} disabled={busy} />
        </div>
      </div>

      <div className="mt-3">
        <label className="mb-1 block text-xs text-slate-500">candidate_designs (JSON -- lista de HierarchicalDesign)</label>
        <textarea className="h-20 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 font-mono text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={designsJson} onChange={(e) => setDesignsJson(e.target.value)} disabled={busy} />
      </div>

      <button className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700" disabled={busy} onClick={evaluate}>
        Evaluar candidatos
      </button>

      {evaluation && (
        <div className="mt-4 space-y-2">
          <div className="grid gap-1 text-[11px]">
            {evaluation.evaluations.map((e, index) => (
              <label key={index} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950 px-2 py-1">
                <span className="flex items-center gap-2">
                  <input type="radio" name="chosen-design" checked={chosenIndex === index} onChange={() => setChosenIndex(index)} />
                  n_units={e.design.n_units}, n_days={e.design.n_days}, captures/unit-day={e.design.n_captures_per_unit_day}
                </span>
                <span className="font-mono text-slate-300">power={e.power.toFixed(3)}</span>
                <StatusBadge status={e.verdict} />
              </label>
            ))}
          </div>
          {evaluation.minimum_sufficient_design && (
            <div className="text-[11px] text-slate-500">
              minimum_sufficient_design (referencia, no auto-registrado): n_units={evaluation.minimum_sufficient_design.design.n_units}
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs text-slate-500">rationale (obligatorio para registrar la decision)</label>
            <textarea className="h-16 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={rationale} onChange={(e) => setRationale(e.target.value)} disabled={busy} />
          </div>
          <button className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-700" disabled={busy || !rationale.trim()} onClick={recordDecision}>
            Registrar decision de sizing
          </button>
        </div>
      )}
    </div>
  );
}

async function pollRq2Job(jobId: string, onUpdate: (job: Rq2BenchmarkJob) => void): Promise<Rq2BenchmarkJob> {
  let current = await sciApi.getRq2BenchmarkJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getRq2BenchmarkJob(jobId);
    onUpdate(current);
  }
  return current;
}

async function pollRq3FrrJob(jobId: string, onUpdate: (job: Rq3FrrAnalysisJob) => void): Promise<Rq3FrrAnalysisJob> {
  let current = await sciApi.getRq3FrrAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getRq3FrrAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Scientific Dashboard Closure audit finding (2026-08-11): RQ3's pair
 * CONSTRUCTION was real, but FRR_pre/FRR_post/D had no real caller even
 * though the frozen inference pipeline that computes it was already real
 * end-to-end -- this launcher is that missing real caller, driving
 * ScientificResultsRepository.run_rq3_frr_analysis via a real background
 * job (scoring can take a while against many pairs). bundle_id defaults
 * to the frozen PRIMARY RQ2 branch -- never guessed. */
function Rq3FrrAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [bundleId, setBundleId] = useState('');
  const [job, setJob] = useState<Rq3FrrAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) setPaperRunId(list[0].paper_run_id);
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startRq3FrrAnalysis({ paper_run_id: paperRunId, bundle_id: bundleId || undefined });
      const finished = await pollRq3FrrJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN RQ3 FRR ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Puntua cada par PRE/POST real (build_pre_post_pairs) con el pipeline de inferencia congelado
        (OfflineInferenceService.run_decision_windows -- rama primaria + preprocesamiento + regla de ventana de
        decision + umbral operativo calibrado, sin recalcular nada nuevo) y calcula FRR_pre/FRR_post/D real. Reutiliza
        el motor de permutacion ya existente (stratified_crossover_permutation_test) -- nunca una segunda
        implementacion estadistica.
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
          <select className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
            <option value="">(seleccionar run)</option>
            {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">bundle_id (opcional -- por defecto la rama PRIMARY congelada de RQ2)</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={bundleId} onChange={(e) => setBundleId(e.target.value)} disabled={busy} />
        </div>
      </div>

      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN RQ3 FRR ANALYSIS'}
      </button>

      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
          {job.result && (
            <details className="rounded border border-slate-800 bg-slate-950">
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
              <pre className="max-h-[50vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(job.result, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function Rq2BenchmarkLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [datasetVersion, setDatasetVersion] = useState('');
  const [job, setJob] = useState<Rq2BenchmarkJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) {
        setPaperRunId(list[0].paper_run_id);
        setDatasetId(list[0].dataset_id);
        setDatasetVersion(list[0].dataset_version);
      }
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId || !datasetId || !datasetVersion) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startRq2Benchmark({ paper_run_id: paperRunId, dataset_id: datasetId, dataset_version: datasetVersion });
      const finished = await pollRq2Job(started.job_id, setJob);
      if (finished.state === 'completed' && finished.result?.rq2_report) onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN RQ2 VALIDATION BENCHMARK (fase 08)</div>
      <div className="mt-1 text-xs text-slate-500">
        Entrena y evalúa las 4 ramas (engineered_rf/raw_iq/stft/coarse_morphology) en un unico job real
        (train_selected_models, VALIDATION unicamente) y persiste rq2_representation_comparison_report.json. La rama
        PRIMARY se decide por el mismo composite_score de VALIDATION ya usado en select_primary_rq2_branch_from_validation.
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
          <select className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
            <option value="">(seleccionar run)</option>
            {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">dataset_id</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">dataset_version</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetVersion} onChange={(e) => setDatasetVersion(e.target.value)} disabled={busy} />
        </div>
      </div>

      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId || !datasetId || !datasetVersion} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN RQ2 VALIDATION BENCHMARK'}
      </button>

      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}

          {job.result?.stopped_at && (
            <NoDataNotice reason={`Entrenamiento detenido en ${job.result.stopped_at}: ${job.result.stopped_reason ?? ''}`} />
          )}

          {job.result?.rq2_report && (
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="grid gap-1 text-[11px] sm:grid-cols-2">
                {job.result.rq2_report.branches.map((branch) => (
                  <div key={branch.branch} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900 px-2 py-1">
                    <span className="text-slate-400">{branch.branch}</span>
                    <StatusBadge status={branch.analysis_role} />
                    <span className="font-mono text-slate-300">BA={branch.balanced_accuracy?.toFixed(3) ?? 'N/A'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[50vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(job, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

async function pollCoverageAnalysisJob(jobId: string, onUpdate: (job: CoverageAnalysisJob) => void): Promise<CoverageAnalysisJob> {
  let current = await sciApi.getCoverageAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getCoverageAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Coverage audit finding (2026-08-12): real decision records already
 * carry everything coverage needs -- this launcher drives the missing
 * aggregation (by overall/evaluation_domain/branch/physical_unit) over
 * EVERY frozen RQ2 branch's bundle. */
function CoverageAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [job, setJob] = useState<CoverageAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) setPaperRunId(list[0].paper_run_id);
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startCoverageAnalysis({ paper_run_id: paperRunId });
      const finished = await pollCoverageAnalysisJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN COVERAGE ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Agrega ventanas de decision reales (run_decision_windows, mismo pipeline congelado de RQ3) por overall/dominio
        de evaluacion/rama/unidad fisica -- para TODAS las ramas congeladas de RQ2, no solo la PRIMARY. Nada se
        calcula en el frontend.
      </div>
      <div className="mt-3">
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className="w-full max-w-md rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN COVERAGE ANALYSIS'}
      </button>
      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
        </div>
      )}
    </div>
  );
}

async function pollSensitivityAnalysisJob(jobId: string, onUpdate: (job: SensitivityAnalysisJob) => void): Promise<SensitivityAnalysisJob> {
  let current = await sciApi.getSensitivityAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getSensitivityAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Sensitivity closure (2026-08-12): LODO + offset-retaining preprocessing
 * + reused RQ2 seed_variability, consolidated into one real report. */
function SensitivityAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [job, setJob] = useState<SensitivityAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) setPaperRunId(list[0].paper_run_id);
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startSensitivityAnalysis(paperRunId);
      const finished = await pollSensitivityAnalysisJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN SENSITIVITY ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Leave-one-device-out (real, delta_vs_full_set anadido) + offset-retaining-v1 (re-entrena la MISMA
        configuracion de la rama PRIMARY, solo cambia el perfil de preprocesamiento -- nunca una nueva seleccion de
        modelo ni un nuevo umbral) + variabilidad por semilla (reutilizada de RQ2, nunca recalculada). Requiere que
        RQ2 Benchmark ya haya congelado una rama PRIMARY.
      </div>
      <div className="mt-3">
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className="w-full max-w-md rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN SENSITIVITY ANALYSIS'}
      </button>
      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
        </div>
      )}
    </div>
  );
}

async function pollRq4RegionAnalysisJob(jobId: string, onUpdate: (job: Rq4RegionAnalysisJob) => void): Promise<Rq4RegionAnalysisJob> {
  let current = await sciApi.getRq4RegionAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getRq4RegionAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** RQ4 region-specific fitting closure (2026-08-12): rq4_primary_analysis=
 * REGION_SPECIFIC_FITTING_AND_EVALUATION. FULL_BURST reuses RQ2's own
 * frozen PRIMARY bundle directly; ADVA_EXCLUDED/PRE_PDU are fitted here as
 * independent realizations of that SAME frozen configuration (same
 * DEVELOPMENT/VALIDATION partitions, hyperparameters, seed -- only the
 * analytical_region changes), then scored per matched_region_block
 * (physical_unit_id/day_id/packet_condition) with the SAME frozen
 * decision-window pipeline RQ1-3 already use. Can take a while (two real
 * re-fits + real decision-window scoring), hence the background job. */
function Rq4RegionAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [fullBurstBundleId, setFullBurstBundleId] = useState('');
  const [job, setJob] = useState<Rq4RegionAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) setPaperRunId(list[0].paper_run_id);
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startRq4RegionAnalysis({ paper_run_id: paperRunId, full_burst_bundle_id: fullBurstBundleId || undefined });
      const finished = await pollRq4RegionAnalysisJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN RQ4 REGION-SPECIFIC ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Ajusta ADVA_EXCLUDED y PRE_PDU como realizaciones independientes de la MISMA configuracion congelada de la
        rama PRIMARY de RQ2 (mismos hiperparametros/semilla/particiones DEVELOPMENT-VALIDATION -- solo cambia
        analytical_region), reutiliza el bundle PRIMARY de RQ2 directamente para FULL_BURST, y puntua cada
        matched_region_block (physical_unit_id/day_id/packet_condition) con el mismo pipeline de ventana de decision
        congelado. Contraste PRIMARIO: FULL_BURST vs PRE_PDU (alimenta NI/Holm). SECUNDARIO/diagnostico: FULL_BURST
        vs ADVA_EXCLUDED (nunca corregido por Holm). Requiere que RQ2 Benchmark ya haya congelado una rama PRIMARY.
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
          <select className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
            <option value="">(seleccionar run)</option>
            {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">full_burst_bundle_id (opcional -- por defecto la rama PRIMARY congelada de RQ2)</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={fullBurstBundleId} onChange={(e) => setFullBurstBundleId(e.target.value)} disabled={busy} />
        </div>
      </div>

      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN RQ4 REGION-SPECIFIC ANALYSIS'}
      </button>

      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
          {job.result && (
            <details className="rounded border border-slate-800 bg-slate-950">
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
              <pre className="max-h-[50vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(job.result, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

async function pollChannelTransportAnalysisJob(jobId: string, onUpdate: (job: ChannelTransportAnalysisJob) => void): Promise<ChannelTransportAnalysisJob> {
  let current = await sciApi.getChannelTransportAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getChannelTransportAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Phase 14 (S1) launcher, fast-closure pass (2026-08-12):
 * compute_channel_transport_report was real and tested but had no real
 * caller -- scores every real capture with the frozen PRIMARY RQ2 branch
 * bundle (never retrained per channel), grouped by real ExampleRecord
 * channel. "Bounded channel transport", never "channel invariance". */
function ChannelTransportAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [bundleId, setBundleId] = useState('');
  const [job, setJob] = useState<ChannelTransportAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) setPaperRunId(list[0].paper_run_id);
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startChannelTransportAnalysis(paperRunId, bundleId || undefined);
      const finished = await pollChannelTransportAnalysisJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN S1 CHANNEL TRANSPORT ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Puntua cada captura real con la rama PRIMARY congelada de RQ2 (mismo bundle para todos los canales -- nunca
        reentrenado por canal) y agrega por canal real (ExampleRecord.channel). Requiere que RQ2 Benchmark ya haya
        congelado una rama PRIMARY.
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
          <select className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
            <option value="">(seleccionar run)</option>
            {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">bundle_id (opcional -- por defecto la rama PRIMARY congelada de RQ2)</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={bundleId} onChange={(e) => setBundleId(e.target.value)} disabled={busy} />
        </div>
      </div>
      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN S1 CHANNEL TRANSPORT ANALYSIS'}
      </button>
      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
        </div>
      )}
    </div>
  );
}

async function pollOfflineNearliveAnalysisJob(jobId: string, onUpdate: (job: OfflineNearliveAnalysisJob) => void): Promise<OfflineNearliveAnalysisJob> {
  let current = await sciApi.getOfflineNearliveAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getOfflineNearliveAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Phase 15 (S2) launcher, fast-closure pass (2026-08-12): wraps
 * compute_offline_nearlive_report as a real, callable job -- never invents
 * a near-live prediction source. No real near-live-inference gathering
 * mechanism exists yet in this codebase, so running this today honestly
 * persists a NO_DATA/NOT_MEASURED report -- never fabricated, never
 * blocking the rest of scientific closure. */
function OfflineNearliveAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [job, setJob] = useState<OfflineNearliveAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) setPaperRunId(list[0].paper_run_id);
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startOfflineNearliveAnalysis(paperRunId);
      const finished = await pollOfflineNearliveAnalysisJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN S2 OFFLINE/NEAR-LIVE ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Empareja predicciones offline y near-live por evidence_interval_id real (exacto, nunca por proximidad
        temporal). Sin un mecanismo real de inferencia near-live todavia, esto persiste honestamente
        pairing_status=NO_DATA / campos NOT_MEASURED -- nunca fabricado, y nunca bloquea el resto del cierre
        cientifico.
      </div>
      <div className="mt-3">
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className="w-full max-w-md rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      <button
        className="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN S2 OFFLINE/NEAR-LIVE ANALYSIS'}
      </button>
      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
        </div>
      )}
    </div>
  );
}

/** Phase 11 -- Definitive Controlled Campaign, fast-closure pass
 * (2026-08-12). "No duplicar logica": acquisition reuses the EXACT same
 * CAMPAIGN SCHEDULE launcher below (freeze_schedule/execute via
 * PaperCampaignRunner -- the same generic mechanism DEVELOPMENT/VALIDATION
 * already use, qualification_only=False) and scoring reuses the RQ3/RQ4
 * launchers already on this page -- there is no separate acquisition or
 * scoring code for "definitive" data. This panel is a pure orchestration
 * label: run Campaign Schedule (below) for the definitive captures once
 * frozen, then re-run RQ3 FRR Analysis / RQ4 Region-Specific Analysis
 * (above) to score them. */
function DefinitiveControlledCampaignPanel({ protocolFrozen }: { protocolFrozen: boolean | undefined }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">PHASE 11 -- DEFINITIVE CONTROLLED CAMPAIGN</div>
      {!protocolFrozen ? (
        <div className="mt-2 rounded border border-dashed border-red-800 bg-red-950/20 px-3 py-2 text-xs text-red-400">
          BLOCKED -- requiere Protocol Freeze (Fase 10) completado primero.
        </div>
      ) : (
        <div className="mt-2 text-xs text-slate-500">
          Desbloqueada. No hay un mecanismo de adquisicion/puntuacion separado para la campana definitiva -- reutiliza
          los MISMOS launchers ya reales de esta pagina: (1) <span className="text-slate-300">Campaign Schedule</span> (mas
          abajo) para adquirir las capturas reales bajo el Analysis Contract congelado, luego (2){' '}
          <span className="text-slate-300">RQ3 FRR Analysis</span> / <span className="text-slate-300">RQ4 Region-Specific Analysis</span> (arriba)
          para puntuarlas con la rama PRIMARY congelada.
        </div>
      )}
    </div>
  );
}

/** Phase 12 -- Protected FUTURE, fast-closure pass (2026-08-12). Maximum
 * simplicity, maximum protection: BLOCKED before protocol freeze,
 * ACQUIRE PROTECTED FUTURE after. freeze_holdout_groups is metadata-only
 * (declares which real physical_unit_ids/day_ids/session_ids belong to
 * group=FUTURE_TEST) -- it never acquires data itself and never scores
 * anything, so this launcher shows only the real assignment_id it
 * created, NEVER a scientific result. Confirmatory analysis (Phase 13) is
 * a completely separate launcher below. */
function ProtectedFutureLauncher({ protocolFrozen, onCompleted }: { protocolFrozen: boolean | undefined; onCompleted: () => void }) {
  const [datasetId, setDatasetId] = useState('');
  const [datasetVersion, setDatasetVersion] = useState('');
  const [physicalUnitIds, setPhysicalUnitIds] = useState('');
  const [dayIds, setDayIds] = useState('');
  const [sessionIds, setSessionIds] = useState('');
  const [assignment, setAssignment] = useState<HoldoutGroupAssignment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acquire = async () => {
    if (!datasetId.trim() || !datasetVersion.trim()) return;
    setBusy(true);
    setError(null);
    setAssignment(null);
    try {
      const result = await sciApi.freezeHoldoutGroups({
        dataset_id: datasetId.trim(), dataset_version: datasetVersion.trim(), group: 'FUTURE_TEST',
        physical_unit_ids: physicalUnitIds.split(',').map((s) => s.trim()).filter(Boolean),
        day_ids: dayIds.split(',').map((s) => s.trim()).filter(Boolean),
        session_ids: sessionIds.split(',').map((s) => s.trim()).filter(Boolean),
      });
      setAssignment(result);
      onCompleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">PHASE 12 -- PROTECTED FUTURE</div>
      <div className="mt-1 text-xs text-slate-500">
        Declara que unidades/dias/sesiones reales quedan selladas como FUTURE_TEST (metadata-only -- la adquisicion
        real usa el mismo mecanismo generico de campana que cualquier otra fase). Nunca muestra un resultado
        cientifico: el analisis confirmatorio (Fase 13) es un launcher completamente separado, mas abajo.
      </div>
      {!protocolFrozen ? (
        <div className="mt-3 rounded border border-dashed border-red-800 bg-red-950/20 px-3 py-2 text-xs text-red-400">
          BLOCKED -- requiere Protocol Freeze (Fase 10) completado primero.
        </div>
      ) : (
        <>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-slate-500">dataset_id</label>
              <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} disabled={busy} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">dataset_version</label>
              <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetVersion} onChange={(e) => setDatasetVersion(e.target.value)} disabled={busy} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">physical_unit_ids (coma-separado)</label>
              <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={physicalUnitIds} onChange={(e) => setPhysicalUnitIds(e.target.value)} disabled={busy} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">day_ids (coma-separado)</label>
              <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={dayIds} onChange={(e) => setDayIds(e.target.value)} disabled={busy} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">session_ids (coma-separado, opcional)</label>
              <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={sessionIds} onChange={(e) => setSessionIds(e.target.value)} disabled={busy} />
            </div>
          </div>
          <button
            className="mt-3 rounded bg-red-800 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-slate-700"
            disabled={busy || !datasetId.trim() || !datasetVersion.trim()} onClick={acquire}
          >
            {busy ? 'Sellando...' : 'ACQUIRE PROTECTED FUTURE'}
          </button>
          {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
          {assignment && (
            <div className="mt-3 rounded border border-emerald-800 bg-emerald-950/20 px-3 py-2 text-[11px] text-emerald-300">
              Sellado: assignment_id=<span className="font-mono">{assignment.assignment_id}</span>, group_manifest_sha256=
              <span className="font-mono">{assignment.group_manifest_sha256.slice(0, 16)}...</span>, frozen_at={assignment.frozen_at}
            </div>
          )}
        </>
      )}
    </div>
  );
}

async function pollConfirmatoryFutureAnalysisJob(jobId: string, onUpdate: (job: ConfirmatoryFutureAnalysisJob) => void): Promise<ConfirmatoryFutureAnalysisJob> {
  let current = await sciApi.getConfirmatoryFutureAnalysisJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getConfirmatoryFutureAnalysisJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Phase 13 -- Confirmatory Analysis, fast-closure pass (2026-08-12). A
 * single launcher for the already-existing, gate-protected
 * run_confirmatory_future_analysis engine (protocol-freeze close-out,
 * 2026-08-10) -- checks (in order): real protocol freeze, real
 * contract_sha256, real FUTURE_TEST holdout role, bundle confirmatory-
 * eligibility, contract-hash match. No recalibration, no model
 * re-selection, no threshold/NI/hypothesis edits happen here or inside the
 * engine it calls. */
function ConfirmatoryFutureAnalysisLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [runs, setRuns] = useState<PaperRunRecord[]>([]);
  const [paperRunId, setPaperRunId] = useState('');
  const [protocolId, setProtocolId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [datasetVersion, setDatasetVersion] = useState('');
  const [bundleId, setBundleId] = useState('');
  const [job, setJob] = useState<ConfirmatoryFutureAnalysisJob | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.listRuns().then((list) => {
      setRuns(list);
      if (list.length > 0) {
        setPaperRunId(list[0].paper_run_id);
        setProtocolId(list[0].protocol_id);
        setDatasetId(list[0].dataset_id);
        setDatasetVersion(list[0].dataset_version);
      }
    }).catch(() => setRuns([]));
  }, []);

  const start = async () => {
    if (!paperRunId || !protocolId || !datasetId || !datasetVersion || !bundleId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startConfirmatoryFutureAnalysis({
        paper_run_id: paperRunId, protocol_id: protocolId, dataset_id: datasetId, dataset_version: datasetVersion, bundle_id: bundleId,
      });
      const finished = await pollConfirmatoryFutureAnalysisJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">PHASE 13 -- RUN CONFIRMATORY ANALYSIS</div>
      <div className="mt-1 text-xs text-slate-500">
        Invoca run_confirmatory_future_analysis (ya existente) -- 5 gates no bypasseables (protocol freeze real,
        contract_sha256 real, FUTURE_TEST holdout declarado, bundle confirmatory-eligible, contract hash coincide).
        Ningun umbral, hipotesis, NI o seleccion de modelo se modifica aqui.
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
          <select className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)} disabled={busy}>
            <option value="">(seleccionar run)</option>
            {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">protocol_id</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={protocolId} onChange={(e) => setProtocolId(e.target.value)} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">dataset_id</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">dataset_version</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetVersion} onChange={(e) => setDatasetVersion(e.target.value)} disabled={busy} />
        </div>
        <div className="sm:col-span-2">
          <label className="mb-1 block text-xs text-slate-500">bundle_id (a verificar confirmatory_eligible)</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none" value={bundleId} onChange={(e) => setBundleId(e.target.value)} disabled={busy} />
        </div>
      </div>
      <button
        className="mt-3 rounded bg-red-800 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !paperRunId || !protocolId || !datasetId || !datasetVersion || !bundleId} onClick={start}
      >
        {busy ? 'Ejecutando...' : 'RUN CONFIRMATORY ANALYSIS'}
      </button>
      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}
        </div>
      )}
    </div>
  );
}

function PhysicalUnitQualificationLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [units, setUnits] = useState<StudioPhysicalUnit[]>([]);
  const [basisById, setBasisById] = useState<Record<string, string>>({});
  const [reasonById, setReasonById] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    studioApi.physicalUnits().then(setUnits).catch(() => setUnits([]));
  };
  useEffect(refresh, []);

  const confirmSameModel = async (unitId: string) => {
    const basis = (basisById[unitId] || '').trim();
    if (!basis) { setError('Se requiere una base real (basis) para confirmar same-model.'); return; }
    setBusyId(unitId);
    setError(null);
    try {
      await studioApi.confirmSameModel(unitId, basis);
      refresh();
      onCompleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const setEligibility = async (unitId: string, eligible: boolean) => {
    const reason = (reasonById[unitId] || '').trim();
    if (!reason) { setError('Se requiere una razon real para declarar RQ4 eligibility.'); return; }
    setBusyId(unitId);
    setError(null);
    try {
      await studioApi.setRq4Eligibility(unitId, eligible, reason);
      refresh();
      onCompleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">Physical Unit Qualification (fase 02)</div>
      <div className="mt-1 text-xs text-slate-500">
        same_model_confirmation y rq4_eligibility son siempre una decision explicita del operador, con base/razon
        reales -- nunca inferidas de device_family/model.
      </div>
      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {units.length === 0 && <div className="mt-3"><NoDataNotice reason="Ningun physical_unit_id registrado todavia." /></div>}

      <div className="mt-3 space-y-3">
        {units.map((unit) => (
          <div key={unit.physical_unit_id} className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-mono text-slate-200">{unit.physical_unit_id}</span>
              <StatusBadge status={unit.same_model_confirmation} />
              <StatusBadge status={unit.rq4_eligibility} />
            </div>
            {unit.same_model_confirmation_basis && <div className="mt-1 text-[11px] text-slate-500">basis: {unit.same_model_confirmation_basis}</div>}
            {unit.rq4_eligibility_reason && <div className="text-[11px] text-slate-500">reason: {unit.rq4_eligibility_reason}</div>}

            {unit.same_model_confirmation !== 'CONFIRMED' && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  className="min-w-64 flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none"
                  placeholder="basis: p.ej. internal_serial prefix match + inspeccion fisica"
                  value={basisById[unit.physical_unit_id] || ''}
                  onChange={(e) => setBasisById((prev) => ({ ...prev, [unit.physical_unit_id]: e.target.value }))}
                  disabled={busyId === unit.physical_unit_id}
                />
                <button
                  className="rounded bg-cyan-700 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
                  disabled={busyId === unit.physical_unit_id} onClick={() => confirmSameModel(unit.physical_unit_id)}
                >
                  Confirmar same-model
                </button>
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                className="min-w-64 flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none"
                placeholder="reason: razon real para RQ4 eligibility"
                value={reasonById[unit.physical_unit_id] || ''}
                onChange={(e) => setReasonById((prev) => ({ ...prev, [unit.physical_unit_id]: e.target.value }))}
                disabled={busyId === unit.physical_unit_id}
              />
              <button
                className="rounded border border-emerald-800 px-3 py-1 text-xs text-emerald-400 hover:bg-emerald-950 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={busyId === unit.physical_unit_id} onClick={() => setEligibility(unit.physical_unit_id, true)}
              >
                ELIGIBLE
              </button>
              <button
                className="rounded border border-red-800 px-3 py-1 text-xs text-red-400 hover:bg-red-950 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={busyId === unit.physical_unit_id} onClick={() => setEligibility(unit.physical_unit_id, false)}
              >
                NOT_ELIGIBLE
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HardwareQualificationLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [physicalUnitId, setPhysicalUnitId] = useState('');
  const [channel, setChannel] = useState(37);
  // Bug fix (2026-08-13): the real HybridBleCaptureManager.start() hard-validates
  // 1<=duration_seconds<=60 (ble_hybrid_campaign_manager.py) -- the previous
  // default of 180 here always failed with INVALID_HYBRID_CONFIGURATION before
  // the B200 was even queried, for every operator. 30 matches the manager's own
  // internal default.
  const [durationSeconds, setDurationSeconds] = useState(30);
  const [job, setJob] = useState<HardwareQualificationJob | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!physicalUnitId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startHardwareQualification({ physical_unit_id: physicalUnitId, channel, duration_seconds: durationSeconds });
      const finished = await pollJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    if (job) sciApi.cancelHardwareQualificationJob(job.job_id).then(setJob);
  };

  const preflight = job?.result?.preflight_report as { overall_status?: string; items?: Record<string, { status: string; detail: unknown }> } | undefined;

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN REAL HARDWARE QUALIFICATION</div>
      <div className="mt-1 text-xs text-slate-500">
        B200 real -&gt; adquisicion real de I/Q -&gt; decodificacion BLE + CRC -&gt; Eq.(6)-(7) smoke test -&gt; estado real de
        asociacion/RQ3/RQ4 -&gt; campaign_qualification_preflight_report.json. Ningun paso se simula.
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-slate-500">physical_unit_id</label>
          <input
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none"
            value={physicalUnitId} onChange={(e) => setPhysicalUnitId(e.target.value)} placeholder="UNIT-01" disabled={busy}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">canal BLE</label>
          <input
            type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none"
            value={channel} onChange={(e) => setChannel(Number(e.target.value))} disabled={busy}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">duracion (s)</label>
          <input
            type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none"
            value={durationSeconds} onChange={(e) => setDurationSeconds(Number(e.target.value))} disabled={busy}
          />
        </div>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
          disabled={busy || !physicalUnitId} onClick={start}
        >
          {busy ? 'Ejecutando...' : 'RUN REAL HARDWARE QUALIFICATION'}
        </button>
        {busy && job && !JOB_TERMINAL.has(job.state) && (
          <button className="rounded border border-red-800 px-4 py-2 text-sm text-red-400 hover:bg-red-950" onClick={cancel}>
            Cancelar
          </button>
        )}
      </div>

      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}

          {preflight && (
            <div className="mt-2 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-500">overall_status</span>
                <StatusBadge status={preflight.overall_status ?? 'NOT_STARTED'} />
              </div>
              {preflight.items && (
                <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-2">
                  {Object.entries(preflight.items).map(([name, item]) => (
                    <div key={name} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900 px-2 py-1">
                      <span className="text-slate-400">{name}</span>
                      <StatusBadge status={item.status} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[50vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(job, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
