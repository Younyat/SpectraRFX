import { useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { RefreshCw } from 'lucide-react';
import {
  BleRffiStudioApiService,
  StudioAddressBinding,
  StudioBundleManifest,
  StudioCaptureRecord,
  StudioDatasetManifest,
  StudioEvaluationResult,
  StudioExample,
  StudioInferenceDecision,
  StudioJob,
  StudioLegacyCaptureListing,
  StudioPhysicalUnit,
  StudioQualityReport,
  StudioSplitManifest,
  StudioTrainingRun,
  describeApiError,
} from '../../../app/services/bleRffiStudioApi';
import { ensureOperation, updateOperation, finishOperation, failOperation } from '../../../app/operations/operationTelemetry';

const api = new BleRffiStudioApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);
const SCIENTIFIC_TASKS = ['SAME_MODEL_UNIT_IDENTIFICATION', 'TARGET_VS_BACKGROUND', 'UNKNOWN_DEVICE_REJECTION', 'MULTI_DEVICE_CLASSIFICATION'];
const MODEL_TYPES: { value: string; representation: string; label: string }[] = [
  { value: 'logistic_regression', representation: 'feature_vector-v1', label: 'Logistic Regression (baseline)' },
  { value: 'svm_rbf', representation: 'feature_vector-v1', label: 'SVM RBF (baseline)' },
  { value: 'random_forest', representation: 'feature_vector-v1', label: 'Random Forest (baseline)' },
  { value: 'cnn1d', representation: 'raw_iq-v1', label: 'CNN1D (raw I/Q)' },
  { value: 'cnn2d', representation: 'spectrogram-v1', label: 'CNN2D (spectrogram)' },
];

function Panel({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-700 bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 text-sm font-semibold">
        <span>{title}</span>
        {action}
      </div>
      <div className="space-y-3 p-4">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      {label}
      {children}
    </label>
  );
}

const inputClass = 'h-9 rounded-md border border-slate-700 bg-slate-900 px-2 text-sm text-slate-100';
const buttonClass = 'inline-flex h-9 items-center gap-2 rounded-md border border-cyan-600 bg-cyan-600/20 px-3 text-sm text-cyan-100 hover:bg-cyan-600/30 disabled:cursor-not-allowed disabled:opacity-40';
const secondaryButtonClass = 'inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40';

function statusPillClass(status: string): string {
  if (['ACCEPTED_FOR_TRAINING', 'PASSED', 'READY', 'COMPLETED', 'EVALUATED', 'APPROVED_FOR_LIVE_PILOT', 'IDENTIFIED'].includes(status)) return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200';
  if (['ACCEPTED_WITH_LIMITATIONS', 'DIAGNOSTIC_CHECK', 'UNKNOWN', 'PENDING_ANALYSIS', 'REPETITION_NEEDED', 'CONTROL_ONLY', 'TEST_NOT_EXECUTED'].includes(status)) return 'border-amber-500/40 bg-amber-500/10 text-amber-200';
  if (['NOT_ACCEPTED_FOR_TRAINING', 'FAILED', 'NOT_FEASIBLE', 'REJECTED', 'QUARANTINED', 'QUARANTINED_AMBIGUOUS'].includes(status)) return 'border-rose-500/40 bg-rose-500/10 text-rose-200';
  return 'border-slate-700 bg-slate-800 text-slate-300';
}
function Pill({ value }: { value: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${statusPillClass(value)}`}>{value}</span>;
}

export default function BleRffiStudioDashboard() {
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState('');

  const [projectId, setProjectId] = useState('BLE-RFFI-CC2650');
  const [campaignId, setCampaignId] = useState('CC2650-CAMPAIGN-01');

  // Auto-train: one click per registered device, no manual capture_id
  // curation -- see StudioRepository.auto_train_candidates()/resolve_auto_train_capture_ids().
  const [autoTrainCandidates, setAutoTrainCandidates] = useState<Array<{
    physical_unit_id: string; project_id: string; target_captures: number; target_sessions: number;
    background_captures: number; background_sessions: number; ready: boolean;
  }>>([]);
  const [autoTrainUnitId, setAutoTrainUnitId] = useState('');
  const [autoTrainJob, setAutoTrainJob] = useState<StudioJob | null>(null);

  // A. Legacy captures (read-only)
  const [legacy, setLegacy] = useState<StudioLegacyCaptureListing | null>(null);
  const [selectedLegacyId, setSelectedLegacyId] = useState('');

  // B. Physical Device Registry
  const [units, setUnits] = useState<StudioPhysicalUnit[]>([]);
  const [bindings, setBindings] = useState<StudioAddressBinding[]>([]);
  const [newUnitId, setNewUnitId] = useState('CC2650-UNIT-01');
  const [newUnitFamily, setNewUnitFamily] = useState('TI_SENSOR_TAG');
  const [newBindingAddress, setNewBindingAddress] = useState('');
  const [newBindingUnitId, setNewBindingUnitId] = useState('');

  // C. Capture Stage
  const [captures, setCaptures] = useState<StudioCaptureRecord[]>([]);
  const [selectedCaptureId, setSelectedCaptureId] = useState('');

  // D. Evidence Stage
  const [bleChannel, setBleChannel] = useState(37);
  const [evidenceJob, setEvidenceJob] = useState<StudioJob | null>(null);
  const [examples, setExamples] = useState<StudioExample[] | null>(null);

  // E. Dataset Builder
  const [datasets, setDatasets] = useState<StudioDatasetManifest[]>([]);
  const [newDatasetId, setNewDatasetId] = useState('BLE-RFFI-DS01');
  const [newDatasetVersion, setNewDatasetVersion] = useState('1.0.0');
  const [selectedDatasetId, setSelectedDatasetId] = useState('');
  const [selectedDatasetVersion, setSelectedDatasetVersion] = useState('');

  // F. Dataset Analyzer
  const [qualityReport, setQualityReport] = useState<StudioQualityReport | null>(null);

  // G. Split Builder
  const [scientificTask, setScientificTask] = useState(SCIENTIFIC_TASKS[0]);
  const [split, setSplit] = useState<StudioSplitManifest | null>(null);

  // H. Training
  const [modelType, setModelType] = useState(MODEL_TYPES[0].value);
  const [trainingJob, setTrainingJob] = useState<StudioJob | null>(null);
  const [trainingRuns, setTrainingRuns] = useState<StudioTrainingRun[]>([]);
  const [selectedTrainingRunId, setSelectedTrainingRunId] = useState('');

  // I. Evaluation
  const [evaluation, setEvaluation] = useState<StudioEvaluationResult | null>(null);

  // J. Export + inference
  const [bundles, setBundles] = useState<StudioBundleManifest[]>([]);
  const [newBundleId, setNewBundleId] = useState('bundle-01');
  const [minTestAccuracy, setMinTestAccuracy] = useState('0.5');
  const [selectedBundleId, setSelectedBundleId] = useState('');
  const [inferenceCaptureId, setInferenceCaptureId] = useState('');
  const [inferenceDecisions, setInferenceDecisions] = useState<StudioInferenceDecision[] | null>(null);

  const selectedModel = useMemo(() => MODEL_TYPES.find((m) => m.value === modelType) ?? MODEL_TYPES[0], [modelType]);

  // The backend is a live network boundary: a transient 404/500 (e.g. mid
  // server-restart) or a proxy error page must never crash the whole render
  // tree just because a .map() downstream assumed the array shape held.
  function asArray<T>(value: T[] | unknown): T[] {
    return Array.isArray(value) ? value : [];
  }

  const refreshAll = async () => {
    const [legacyRes, unitsRes, bindingsRes, capturesRes, datasetsRes, runsRes, bundlesRes, autoTrainRes] = await Promise.all([
      api.legacyCaptures(), api.physicalUnits(), api.addressBindings(), api.captures(), api.datasets(), api.trainingRuns(), api.bundles(),
      api.autoTrainCandidates(),
    ]);
    setLegacy(legacyRes);
    setUnits(asArray(unitsRes));
    setBindings(asArray(bindingsRes));
    setCaptures(asArray(capturesRes));
    setDatasets(asArray(datasetsRes));
    setTrainingRuns(asArray(runsRes));
    setBundles(asArray(bundlesRes));
    setAutoTrainCandidates(asArray(autoTrainRes));
  };

  const [backendUnavailable, setBackendUnavailable] = useState(false);

  useEffect(() => {
    refreshAll()
      .then(() => setBackendUnavailable(false))
      .catch((e) => { setError(describeApiError(e)); setBackendUnavailable(true); });
  }, []);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError('');
    setMessage('');
    try {
      await fn();
      setBackendUnavailable(false);
    } catch (e) {
      setError(describeApiError(e));
    } finally {
      setBusy('');
    }
  };

  // --- Evidence job polling ---
  useEffect(() => {
    if (!evidenceJob || JOB_TERMINAL.has(evidenceJob.state)) return;
    const operationId = `ble-rffi-studio-evidence-${evidenceJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'CONSTRUYENDO EVIDENCIA', phase: evidenceJob.phase || 'Iniciando', progressPercent: (evidenceJob.overall_progress || 0) * 100, target: selectedCaptureId, detail: evidenceJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(evidenceJob.job_id);
        setEvidenceJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, `${next.result_summary?.n_examples ?? '?'} ejemplos`);
            const built = await api.examples(selectedCaptureId);
            setExamples(built);
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, String(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evidenceJob?.job_id, evidenceJob?.state]);

  // --- Training job polling ---
  useEffect(() => {
    if (!trainingJob || JOB_TERMINAL.has(trainingJob.state)) return;
    const operationId = `ble-rffi-studio-training-${trainingJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'ENTRENANDO MODELO', phase: trainingJob.phase || 'Iniciando', progressPercent: (trainingJob.overall_progress || 0) * 100, target: modelType, detail: trainingJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(trainingJob.job_id);
        setTrainingJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, 'Entrenamiento completado');
            setTrainingRuns(asArray(await api.trainingRuns()));
            if (next.training_run_id) setSelectedTrainingRunId(next.training_run_id);
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, String(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trainingJob?.job_id, trainingJob?.state]);

  // --- Auto-train job polling ---
  useEffect(() => {
    if (!autoTrainJob || JOB_TERMINAL.has(autoTrainJob.state)) return;
    const operationId = `ble-rffi-studio-auto-train-${autoTrainJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'ENTRENAMIENTO AUTOMATICO', phase: autoTrainJob.phase || 'Iniciando', progressPercent: (autoTrainJob.overall_progress || 0) * 100, target: autoTrainUnitId, detail: autoTrainJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(autoTrainJob.job_id);
        setAutoTrainJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, 'Entrenamiento automatico completado');
            setAutoTrainCandidates(asArray(await api.autoTrainCandidates()));
            setBundles(asArray(await api.bundles()));
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, String(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoTrainJob?.job_id, autoTrainJob?.state]);

  const autoTrainSummary = autoTrainJob?.result_summary as
    | { recommended_training_run_id?: string; recommended_reason?: string; final_test_evaluation?: {
        balanced_accuracy?: number; macro_f1?: number; accuracy?: number;
        confusion_matrix?: Record<string, Record<string, number>>;
      }; trained_models?: Array<{ model_type: string; training_run_id: string; composite_score: number }>;
      split_status?: string | null; feasibility?: { human_summary?: string } | null;
      stopped_at?: string | null; stopped_reason?: string | null;
      exported_bundles?: Array<{ training_run_id: string; model_type: string; bundle_id: string; approval_status: string | null; error?: string }> }
    | undefined;
  // Two independent gates can block training before any model is trained:
  // the split feasibility check (not enough independent sessions -- see
  // split_status) and the dataset quality gate (e.g. sample overlap --
  // stopped_at/stopped_reason). Different result shapes, same "nothing to
  // recommend yet" outcome -- surfaced together so the operator sees the
  // real reason either way instead of a generic failure.
  const autoTrainBlockedReason = autoTrainSummary && autoTrainSummary.split_status !== 'READY'
    ? autoTrainSummary.feasibility?.human_summary || autoTrainSummary.stopped_reason || `Bloqueado en: ${autoTrainSummary.stopped_at || 'motivo desconocido'}`
    : null;

  return (
    <div className="space-y-4 p-4 text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">BLE-RFFI End-to-End Studio</h1>
          <p className="text-sm text-slate-400">Captura -&gt; evidencia -&gt; dataset -&gt; entrenamiento -&gt; evaluacion -&gt; exportacion -&gt; inferencia offline. Modulo nuevo e independiente; no reutiliza contratos ni decisiones de los dashboards antiguos.</p>
        </div>
        <button className={secondaryButtonClass} onClick={() => run('refresh', refreshAll)} disabled={!!busy || backendUnavailable}>
          <RefreshCw className="h-4 w-4" />Actualizar
        </button>
      </div>

      <div className="rounded-md border border-cyan-500/40 bg-cyan-500/10 p-3 text-sm text-cyan-100">
        Live Monitor queda fuera de alcance hasta que un bundle sea entrenado, evaluado y exportado. Las particiones (splits) se construyen por sesion completa y pueden salir <b>NOT_FEASIBLE</b> honestamente cuando no hay evidencia suficiente -- eso no es un error.
      </div>

      {backendUnavailable && (
        <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
          No se pudo acceder al servicio BLE-RFFI Studio. Las acciones estan deshabilitadas hasta que el backend responda. Pulsa "Actualizar" para reintentar.
        </div>
      )}
      {error && <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
      {message && !error && <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">{message}</div>}

      <Panel title="Entrenamiento automatico (un clic por dispositivo)">
        <p className="text-xs text-slate-400">
          Resuelve por si solo las capturas de cada dispositivo (TARGET_DEVICE_ON propias + BACKGROUND_TARGET_OFF/BACKGROUND_GENERAL compartidas del proyecto), construye el dataset, la particion y entrena los 5 modelos candidatos -- sin pasar por captura -&gt; evidencia -&gt; dataset -&gt; particion a mano.
        </p>
        <table className="w-full text-left text-xs">
          <thead className="text-slate-400">
            <tr><th className="p-1">dispositivo</th><th className="p-1">proyecto</th><th className="p-1">sesiones objetivo</th><th className="p-1">sesiones entorno</th><th className="p-1">listo</th><th className="p-1" /></tr>
          </thead>
          <tbody>{autoTrainCandidates.map((c) => (
            <tr key={c.physical_unit_id} className="border-t border-slate-800">
              <td className="p-1 font-mono">{c.physical_unit_id}</td>
              <td className="p-1 font-mono text-slate-400">{c.project_id}</td>
              <td className="p-1">{c.target_sessions} ({c.target_captures} capturas)</td>
              <td className="p-1">{c.background_sessions} ({c.background_captures} capturas)</td>
              <td className="p-1"><Pill value={c.ready ? 'READY' : 'NOT_FEASIBLE'} /></td>
              <td className="p-1">
                <button
                  className={buttonClass}
                  disabled={!!busy || backendUnavailable || !c.ready || (!!autoTrainJob && !JOB_TERMINAL.has(autoTrainJob.state))}
                  onClick={() => run('auto-train', async () => {
                    setAutoTrainUnitId(c.physical_unit_id);
                    const job = await api.autoTrain(c.physical_unit_id);
                    setAutoTrainJob(job);
                    setMessage(`Entrenamiento automatico iniciado para ${c.physical_unit_id}: al terminar, los 5 modelos candidatos se exportaran y aprobaran solos.`);
                  })}
                >
                  Entrenar
                </button>
              </td>
            </tr>
          ))}</tbody>
        </table>

        {autoTrainJob && (
          <div className="rounded-md border border-slate-700 bg-slate-900 p-3 text-xs space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-semibold">{autoTrainUnitId}</span>
              <Pill value={autoTrainJob.state.toUpperCase()} />
              {autoTrainJob.message && <span className="text-slate-400">{autoTrainJob.message}</span>}
            </div>
            {autoTrainJob.state === 'completed' && autoTrainSummary && (
              autoTrainBlockedReason ? (
                <div className="text-amber-200">{autoTrainBlockedReason}</div>
              ) : (
                <>
                  <div>Recomendado (mejor en VALIDATION): <span className="font-mono">{autoTrainSummary.recommended_training_run_id}</span> -- {autoTrainSummary.recommended_reason}</div>
                  {autoTrainSummary.final_test_evaluation && (
                    <div className="flex flex-wrap gap-4 font-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      <span>balanced_accuracy: {autoTrainSummary.final_test_evaluation.balanced_accuracy?.toFixed(3)}</span>
                      <span>macro_f1: {autoTrainSummary.final_test_evaluation.macro_f1?.toFixed(3)}</span>
                      <span>accuracy: {autoTrainSummary.final_test_evaluation.accuracy?.toFixed(3)}</span>
                    </div>
                  )}
                  <div className="pt-2">
                    <div className="text-xs font-semibold text-slate-200">
                      Los {autoTrainSummary.exported_bundles?.length ?? 0} modelos candidatos ya se exportaron y aprobaron automaticamente:
                    </div>
                    <table className="mt-1 w-full text-left text-xs">
                      <thead className="text-slate-400">
                        <tr><th className="p-1">bundle_id</th><th className="p-1">modelo</th><th className="p-1">estado</th></tr>
                      </thead>
                      <tbody>
                        {(autoTrainSummary.exported_bundles || []).map((eb) => (
                          <tr key={eb.bundle_id} className="border-t border-slate-800">
                            <td className="p-1 font-mono">{eb.bundle_id}</td>
                            <td className="p-1">{eb.model_type}{eb.training_run_id === autoTrainSummary.recommended_training_run_id ? ' (recomendado)' : ''}</td>
                            <td className="p-1"><Pill value={eb.approval_status || eb.error || 'ERROR'} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )
            )}
          </div>
        )}
      </Panel>

      <Panel title="Contexto: proyecto / campana (modo manual, avanzado)">
        <div className="flex flex-wrap gap-3">
          <Field label="project_id"><input className={inputClass} value={projectId} onChange={(e) => setProjectId(e.target.value)} /></Field>
          <Field label="campaign_id"><input className={inputClass} value={campaignId} onChange={(e) => setCampaignId(e.target.value)} /></Field>
        </div>
      </Panel>

      {/* A. Legacy captures */}
      <Panel title="A. Capturas legacy disponibles (solo lectura)">
        <div className="max-h-48 overflow-auto rounded border border-slate-800">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-900 text-slate-400"><tr><th className="p-2">capture_id</th><th className="p-2">execution_id</th><th className="p-2">target_address</th><th className="p-2">replay</th><th className="p-2" /></tr></thead>
            <tbody>
              {(legacy?.captures ?? []).map((c) => (
                <tr key={c.capture_id} className="border-t border-slate-800 hover:bg-slate-900">
                  <td className="p-2 font-mono">{c.capture_id}</td>
                  <td className="p-2 font-mono">{c.execution_id ?? '-'}</td>
                  <td className="p-2 font-mono">{c.target_address ?? '-'}</td>
                  <td className="p-2">{String((c.replay as Record<string, unknown> | undefined)?.scientific_completion_status ?? '-')}</td>
                  <td className="p-2"><button className={secondaryButtonClass} onClick={() => setSelectedLegacyId(c.capture_id)}>Elegir</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-xs text-slate-400">Seleccionada: <span className="font-mono text-slate-200">{selectedLegacyId || '-'}</span></div>
      </Panel>

      {/* B. Physical Device Registry */}
      <Panel title="B. Registro de dispositivos fisicos (Physical Device Registry)">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="physical_unit_id"><input className={inputClass} value={newUnitId} onChange={(e) => setNewUnitId(e.target.value)} /></Field>
          <Field label="device_family"><input className={inputClass} value={newUnitFamily} onChange={(e) => setNewUnitFamily(e.target.value)} /></Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable} onClick={() => run('unit', async () => {
            await api.createPhysicalUnit({ physical_unit_id: newUnitId, project_id: projectId, device_family: newUnitFamily, operator_declaration_id: `decl-${newUnitId}` });
            setUnits(asArray(await api.physicalUnits()));
            setMessage(`Unidad ${newUnitId} registrada.`);
          })}>Registrar unidad</button>
        </div>
        <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="p-1">physical_unit_id</th><th className="p-1">device_family</th><th className="p-1">status</th></tr></thead>
          <tbody>{units.map((u) => <tr key={u.physical_unit_id} className="border-t border-slate-800"><td className="p-1 font-mono">{u.physical_unit_id}</td><td className="p-1">{u.device_family}</td><td className="p-1"><Pill value={u.status} /></td></tr>)}</tbody>
        </table>

        <div className="flex flex-wrap items-end gap-2 pt-2">
          <Field label="address (MAC)"><input className={inputClass} value={newBindingAddress} onChange={(e) => setNewBindingAddress(e.target.value)} placeholder="B0:B4:48:C0:36:06" /></Field>
          <Field label="physical_unit_id">
            <select className={inputClass} value={newBindingUnitId} onChange={(e) => setNewBindingUnitId(e.target.value)}>
              <option value="">-</option>
              {units.map((u) => <option key={u.physical_unit_id} value={u.physical_unit_id}>{u.physical_unit_id}</option>)}
            </select>
          </Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !newBindingAddress || !newBindingUnitId} onClick={() => run('binding', async () => {
            await api.createAddressBinding({ project_id: projectId, address: newBindingAddress, address_type: 'public', physical_unit_id: newBindingUnitId, reason: 'Operator declares factory address (dashboard)' });
            setBindings(asArray(await api.addressBindings()));
            setMessage('Vinculo direccion -> unidad declarado.');
          })}>Declarar vinculo</button>
        </div>
        <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="p-1">address</th><th className="p-1">bound_physical_unit_id</th><th className="p-1">binding_status</th></tr></thead>
          <tbody>{bindings.map((b) => <tr key={b.binding_id} className="border-t border-slate-800"><td className="p-1 font-mono">{b.address}</td><td className="p-1 font-mono">{b.bound_physical_unit_id ?? '-'}</td><td className="p-1"><Pill value={b.binding_status} /></td></tr>)}</tbody>
        </table>
      </Panel>

      {/* C. Capture Stage */}
      <Panel title="C. Capture Stage">
        <div className="flex flex-wrap items-end gap-2">
          <div className="text-xs text-slate-400">A partir de la captura legacy seleccionada arriba: <span className="font-mono text-slate-200">{selectedLegacyId || '(ninguna)'}</span></div>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedLegacyId} onClick={() => run('capture', async () => {
            const capture = await api.createCapture({ capture_id: selectedLegacyId, project_id: projectId, campaign_id: campaignId });
            setCaptures(asArray(await api.captures()));
            setSelectedCaptureId(capture.capture_id);
            setMessage(`CaptureRecord construido para ${capture.capture_id}.`);
          })}>Construir CaptureRecord</button>
        </div>
        <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="p-1">capture_id</th><th className="p-1">session_id</th><th className="p-1">acquisition_quality</th><th className="p-1">replay_status</th><th className="p-1" /></tr></thead>
          <tbody>{captures.map((c) => (
            <tr key={c.capture_id} className="border-t border-slate-800">
              <td className="p-1 font-mono">{c.capture_id}</td><td className="p-1 font-mono">{c.session_id}</td>
              <td className="p-1"><Pill value={c.acquisition_quality} /></td><td className="p-1"><Pill value={c.replay_status} /></td>
              <td className="p-1"><button className={secondaryButtonClass} onClick={() => setSelectedCaptureId(c.capture_id)}>Elegir</button></td>
            </tr>
          ))}</tbody>
        </table>
        <div className="text-xs text-slate-400">Elegida para Evidence Stage: <span className="font-mono text-slate-200">{selectedCaptureId || '-'}</span></div>
      </Panel>

      {/* D. Evidence Stage */}
      <Panel title="D. Evidence Stage">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="ble_channel"><input className={inputClass} type="number" value={bleChannel} onChange={(e) => setBleChannel(Number(e.target.value))} /></Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedCaptureId} onClick={() => run('evidence', async () => {
            const job = await api.startEvidenceJob(selectedCaptureId, { project_id: projectId, ble_channel: bleChannel });
            setEvidenceJob(job);
          })}>Construir evidencia (job)</button>
        </div>
        {evidenceJob && <div className="text-xs text-slate-400">Job: <span className="font-mono">{evidenceJob.job_id}</span> -- <Pill value={evidenceJob.state} /> {evidenceJob.message}</div>}
        {examples && (
          <div className="text-xs text-slate-400">
            {examples.length} ejemplos construidos. Por association_status: {Object.entries(countBy(examples, 'association_status')).map(([k, v]) => `${k}=${v}`).join(', ')}
          </div>
        )}
      </Panel>

      {/* E. Dataset Builder */}
      <Panel title="E. Dataset Builder">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="dataset_id"><input className={inputClass} value={newDatasetId} onChange={(e) => setNewDatasetId(e.target.value)} /></Field>
          <Field label="dataset_version"><input className={inputClass} value={newDatasetVersion} onChange={(e) => setNewDatasetVersion(e.target.value)} /></Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedCaptureId} onClick={() => run('dataset', async () => {
            const result = await api.createDataset({ dataset_id: newDatasetId, dataset_version: newDatasetVersion, project_id: projectId, campaign_id: campaignId, capture_ids: [selectedCaptureId] });
            setDatasets(asArray(await api.datasets()));
            setSelectedDatasetId(result.dataset.dataset_id);
            setSelectedDatasetVersion(result.dataset.dataset_version);
            setMessage(`Dataset congelado: ${result.n_selected} seleccionados, ${result.n_excluded} excluidos.`);
          })}>Construir + congelar dataset</button>
        </div>
        <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="p-1">dataset_id</th><th className="p-1">version</th><th className="p-1">frozen</th><th className="p-1">examples</th><th className="p-1">class_distribution</th><th className="p-1" /><th className="p-1" /></tr></thead>
          <tbody>{datasets.map((d) => (
            <tr key={`${d.dataset_id}-${d.dataset_version}`} className="border-t border-slate-800">
              <td className="p-1 font-mono">{d.dataset_id}</td><td className="p-1 font-mono">{d.dataset_version}</td>
              <td className="p-1">{d.frozen ? 'si' : 'no'}</td><td className="p-1">{d.example_ids.length}</td>
              <td className="p-1 font-mono">{JSON.stringify(d.class_distribution)}</td>
              <td className="p-1"><button className={secondaryButtonClass} onClick={() => { setSelectedDatasetId(d.dataset_id); setSelectedDatasetVersion(d.dataset_version); }}>Elegir</button></td>
              <td className="p-1">
                <button
                  className={secondaryButtonClass}
                  disabled={!!busy || backendUnavailable}
                  onClick={() => run(`delete-dataset-${d.dataset_id}-${d.dataset_version}`, async () => {
                    if (!window.confirm(`Borrar el dataset ${d.dataset_id}@${d.dataset_version}? Esto elimina el manifiesto congelado y cualquier split construido a partir de el (no se puede deshacer). Las capturas y evidencia originales no se tocan.`)) return;
                    await api.deleteDataset(d.dataset_id, d.dataset_version);
                    setDatasets(asArray(await api.datasets()));
                    if (selectedDatasetId === d.dataset_id && selectedDatasetVersion === d.dataset_version) {
                      setSelectedDatasetId('');
                      setSelectedDatasetVersion('');
                    }
                    setMessage(`Dataset ${d.dataset_id}@${d.dataset_version} eliminado.`);
                  })}
                >
                  Eliminar
                </button>
              </td>
            </tr>
          ))}</tbody>
        </table>
        <div className="text-xs text-slate-400">Elegido: <span className="font-mono text-slate-200">{selectedDatasetId || '-'} @ {selectedDatasetVersion || '-'}</span></div>
      </Panel>

      {/* F. Dataset Analyzer */}
      <Panel title="F. Dataset Analyzer (gate de calidad)">
        <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedDatasetId} onClick={() => run('quality', async () => {
          const report = await api.buildQualityReport(selectedDatasetId, selectedDatasetVersion, false);
          setQualityReport(report);
        })}>Ejecutar analisis de calidad</button>
        {qualityReport && (
          <div className="space-y-1 text-xs">
            <div>gate_decision: <Pill value={qualityReport.gate_decision} /></div>
            <div>exact_duplicates: <Pill value={qualityReport.exact_duplicates.status} /> ({qualityReport.exact_duplicates.duplicate_groups.length} grupos)</div>
            <div>sample_overlap: <Pill value={qualityReport.sample_overlap.status} /> ({qualityReport.sample_overlap.overlapping_pairs.length} pares)</div>
            <div>near_duplicates (diagnostico, nunca bloquea): <Pill value={qualityReport.near_duplicates.status} /></div>
            {qualityReport.gate_reasons.length > 0 && <div className="text-slate-400">{qualityReport.gate_reasons.join(' | ')}</div>}
          </div>
        )}
      </Panel>

      {/* G. Split Builder */}
      <Panel title="G. Split Builder">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="scientific_task">
            <select className={inputClass} value={scientificTask} onChange={(e) => setScientificTask(e.target.value)}>
              {SCIENTIFIC_TASKS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedDatasetId} onClick={() => run('split', async () => {
            const result = await api.buildSplit(selectedDatasetId, selectedDatasetVersion, scientificTask);
            setSplit(result);
          })}>Construir split</button>
        </div>
        {split && (
          <div className="space-y-1 text-xs">
            <div>split_status: <Pill value={split.split_status} /></div>
            {split.infeasibility_reason && <div className="text-amber-200">{split.infeasibility_reason}</div>}
            {split.split_status === 'READY' && (
              <div>
                <div>leakage_check: <Pill value={split.leakage_check.status} /></div>
                <div>asignaciones: {split.assignments.length} ({['TRAIN', 'VALIDATION', 'TEST'].map((s) => `${s}=${split.assignments.filter((a) => a.split === s).length}`).join(', ')})</div>
              </div>
            )}
          </div>
        )}
      </Panel>

      {/* H. Training */}
      <Panel title="H. Entrenamiento">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="model_type">
            <select className={inputClass} value={modelType} onChange={(e) => setModelType(e.target.value)}>
              {MODEL_TYPES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !split || split.split_status !== 'READY'} onClick={() => run('training', async () => {
            if (!split) return;
            const runId = `run-${Date.now()}`;
            const job = await api.startTraining({
              training_run_id: runId, project_id: projectId, campaign_id: campaignId,
              dataset_id: selectedDatasetId, dataset_version: selectedDatasetVersion,
              dataset_manifest_sha256: datasets.find((d) => d.dataset_id === selectedDatasetId)?.dataset_manifest_sha256 || '',
              split_manifest_sha256: split.split_manifest_sha256 || '', scientific_task: scientificTask,
              model_type: modelType, representation_profile_id: selectedModel.representation, random_seed: 0,
            });
            setTrainingJob(job);
          })}>Entrenar {!split || split.split_status !== 'READY' ? '(requiere split READY)' : ''}</button>
        </div>
        {trainingJob && <div className="text-xs text-slate-400">Job: <span className="font-mono">{trainingJob.job_id}</span> -- <Pill value={trainingJob.state} /> {trainingJob.message}</div>}
        <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="p-1">training_run_id</th><th className="p-1">model_type</th><th className="p-1">status</th><th className="p-1">TEST accuracy</th><th className="p-1" /></tr></thead>
          <tbody>{trainingRuns.map((r) => (
            <tr key={r.training_run_id} className="border-t border-slate-800">
              <td className="p-1 font-mono">{r.training_run_id}</td><td className="p-1">{r.model_type}</td>
              <td className="p-1"><Pill value={r.status} /></td><td className="p-1">{r.metrics?.TEST?.accuracy != null ? r.metrics.TEST.accuracy.toFixed(3) : '-'}</td>
              <td className="p-1"><button className={secondaryButtonClass} onClick={() => setSelectedTrainingRunId(r.training_run_id)}>Elegir</button></td>
            </tr>
          ))}</tbody>
        </table>
        <div className="text-xs text-slate-400">Elegido para evaluacion/exportacion: <span className="font-mono text-slate-200">{selectedTrainingRunId || '-'}</span></div>
      </Panel>

      {/* I. Evaluation */}
      <Panel title="I. Evaluacion + calibracion UNKNOWN">
        <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedTrainingRunId} onClick={() => run('evaluation', async () => {
          const result = await api.evaluate(selectedTrainingRunId, 0.9);
          setEvaluation(result);
        })}>Evaluar (calibra con VALIDATION)</button>
        {evaluation && (
          <div className="space-y-2 text-xs">
            <div>acceptance_threshold: <span className="font-mono">{evaluation.calibration.acceptance_threshold?.toFixed(4) ?? '-'}</span> (calibrado solo con {evaluation.calibration.calibrated_on})</div>
            {Object.entries(evaluation.evaluation_report).map(([split_name, report]) => (
              <div key={split_name}>{split_name}: accuracy={report.accuracy != null ? report.accuracy.toFixed(3) : 'N/A'} ({report.n_comparable_to_known_classes}/{report.n_examples} comparables)</div>
            ))}
          </div>
        )}
      </Panel>

      {/* J. Export + inference */}
      <Panel title="J. Exportacion + inferencia offline">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="bundle_id"><input className={inputClass} value={newBundleId} onChange={(e) => setNewBundleId(e.target.value)} /></Field>
          <Field label="min_test_accuracy"><input className={inputClass} value={minTestAccuracy} onChange={(e) => setMinTestAccuracy(e.target.value)} /></Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedTrainingRunId || !evaluation} onClick={() => run('export', async () => {
            const result = await api.exportBundle(selectedTrainingRunId, { bundle_id: newBundleId, acceptance_criteria: { min_test_accuracy: Number(minTestAccuracy) }, model_card_text: `# ${newBundleId}\nExportado desde el dashboard BLE-RFFI Studio.` });
            setBundles(asArray(await api.bundles()));
            setSelectedBundleId(result.bundle.bundle_id);
            setMessage(`Bundle ${result.bundle.bundle_id}: ${result.bundle.approval_status}.`);
          })}>Exportar bundle</button>
        </div>
        <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="p-1">bundle_id</th><th className="p-1">approval_status</th><th className="p-1" /></tr></thead>
          <tbody>{bundles.map((b) => (
            <tr key={b.bundle_id} className="border-t border-slate-800">
              <td className="p-1 font-mono">{b.bundle_id}</td><td className="p-1"><Pill value={b.approval_status} /></td>
              <td className="p-1 flex gap-2">
                <button className={secondaryButtonClass} onClick={() => setSelectedBundleId(b.bundle_id)}>Elegir</button>
                {b.approval_status === 'EVALUATED' && <button className={secondaryButtonClass} onClick={() => run('approve', async () => { await api.approveBundle(b.bundle_id); setBundles(asArray(await api.bundles())); })}>Aprobar para piloto en vivo</button>}
              </td>
            </tr>
          ))}</tbody>
        </table>

        <div className="flex flex-wrap items-end gap-2 pt-2">
          <Field label="capture_id (para inferencia)"><input className={inputClass} value={inferenceCaptureId} onChange={(e) => setInferenceCaptureId(e.target.value)} placeholder={selectedCaptureId || 'capture_id'} /></Field>
          <button className={buttonClass} disabled={!!busy || backendUnavailable || !selectedBundleId || !inferenceCaptureId} onClick={() => run('inference', async () => {
            const decisions = await api.runInference(selectedBundleId, inferenceCaptureId);
            setInferenceDecisions(decisions);
          })}>Ejecutar inferencia offline</button>
        </div>
        {inferenceDecisions && (
          <div className="max-h-64 overflow-auto rounded border border-slate-800">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-slate-900 text-slate-400"><tr><th className="p-1">example_id</th><th className="p-1">predicted_class</th><th className="p-1">class_probability</th><th className="p-1">final_decision</th></tr></thead>
              <tbody>{inferenceDecisions.map((d) => (
                <tr key={d.example_id} className="border-t border-slate-800">
                  <td className="p-1 font-mono">{d.example_id.slice(0, 18)}...</td><td className="p-1 font-mono">{d.predicted_class ?? '-'}</td>
                  <td className="p-1">{d.class_probability != null ? d.class_probability.toFixed(3) : '-'}</td><td className="p-1"><Pill value={d.final_decision} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function countBy(items: StudioExample[], field: keyof StudioExample): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const key = String(item[field] ?? 'null');
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}
