import { Fragment, useEffect, useState } from 'react';
import { CheckCircle2, ChevronRight, Circle, Loader2, Radio } from 'lucide-react';
import {
  BleNativeScanApiService,
  BleRffiStudioApiService,
  NativeBleDevice,
  StudioAddressBinding,
  StudioBundleManifest,
  StudioCampaignDeviceStatus,
  StudioCampaignSessionResult,
  StudioCaptureDecision,
  StudioCapturePurpose,
  StudioCaptureRecord,
  StudioEvaluationResult,
  StudioFeasibility,
  StudioJob,
  StudioDatasetCompositionReport,
  StudioDatasetManifest,
  StudioDeviceSource,
  StudioLabelProvenanceReport,
  StudioLegacyCapture,
  StudioLegacyCaptureListing,
  StudioPhysicalUnit,
  StudioExample,
  StudioPrepareAndTrainSummary,
  StudioQuickPresenceCheck,
  StudioTaskRecommendation,
  StudioTestEvaluationProvenance,
  StudioTrainingPreview,
  StudioTrainingRun,
  describeApiError,
  describeCampaignSessionError,
  isDeviceActiveNow,
} from '../../../app/services/bleRffiStudioApi';
import { ensureOperation, updateOperation, finishOperation, failOperation } from '../../../app/operations/operationTelemetry';

const api = new BleRffiStudioApiService();
const nativeScan = new BleNativeScanApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

// Same includable-set definition StudioRepository._capture_decision() uses
// backend-side: quality PASSED and not already excluded outright. Evidence
// Stage never itself sets dataset_eligibility=ELIGIBLE (only the Dataset
// Builder gate does, per-dataset) -- filtering on '=== ELIGIBLE' alone always
// showed 0 here even when hundreds of examples were genuinely includable.
const isDatasetIncludable = (example: StudioExample) =>
  example.quality_status === 'PASSED' && (example.dataset_eligibility === 'PENDING_ANALYSIS' || example.dataset_eligibility === 'ELIGIBLE');

const inputClass = 'h-9 rounded-md border border-slate-700 bg-slate-900 px-2 text-sm text-slate-100';
const buttonClass = 'inline-flex h-10 items-center gap-2 rounded-md border border-cyan-600 bg-cyan-600/20 px-4 text-sm font-medium text-cyan-100 hover:bg-cyan-600/30 disabled:cursor-not-allowed disabled:opacity-40';
const secondaryButtonClass = 'inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40';

// Guided mode is real-hardware-only: no synthetic/demo path is offered or
// displayed here (SYNTHETIC_DEMO still exists as a backend regression
// fixture and remains reachable from Advanced mode for engineers).
type DataSource = 'real' | null;

// Human-facing "Tipo de captura" text -- must match StudioRepository's own
// _capture_type_and_decision() mapping exactly, since it is displayed
// alongside rows the backend already labelled this way.
const CAPTURE_TYPE_DEVICE = 'Dispositivo encendido';
const CAPTURE_TYPE_ENVIRONMENT_DECLARED = 'Entorno -- dispositivo apagado';
const CAPTURE_TYPE_ENVIRONMENT_GENERAL = 'Entorno general';
const CAPTURE_TYPE_UNKNOWN_COLLECTION = 'Recoleccion de dispositivos desconocidos';
const CAPTURE_TYPE_UNCLASSIFIED = 'Sin clasificar';
// A capture attempt that overflowed/discontinued mid-acquisition (the
// automatic retry mechanism's real, measured ~46% single-attempt failure
// rate) still writes a complete manifest, so it shows up in the list even
// though only the retry that finally succeeded ever gets a CaptureRecord --
// there is nothing to analyze in these, only to discard.
const CAPTURE_TYPE_DISCARDED_RF_FAILURE = 'Descartada (fallo de adquisicion RF)';

type CaptureListFilter = 'ALL' | 'DEVICE' | 'ENVIRONMENT' | 'UNKNOWN_DEVICE' | 'UNANALYZED';

function matchesCaptureFilter(row: StudioLegacyCapture, filter: CaptureListFilter): boolean {
  if (filter === 'ALL') return true;
  if (filter === 'DEVICE') return row.capture_type_label === CAPTURE_TYPE_DEVICE;
  if (filter === 'ENVIRONMENT') return row.capture_type_label === CAPTURE_TYPE_ENVIRONMENT_DECLARED || row.capture_type_label === CAPTURE_TYPE_ENVIRONMENT_GENERAL;
  if (filter === 'UNKNOWN_DEVICE') return row.capture_type_label === CAPTURE_TYPE_UNKNOWN_COLLECTION;
  return row.capture_decision === 'NOT_ANALYZED_YET' || !row.capture_type_label || row.capture_type_label === CAPTURE_TYPE_UNCLASSIFIED;
}

type CaptureSortKey = 'TIME_DESC' | 'TIME_ASC' | 'TYPE' | 'DECISION';

function compareCaptureRows(a: StudioLegacyCapture, b: StudioLegacyCapture, sortKey: CaptureSortKey): number {
  if (sortKey === 'TIME_ASC') return new Date(a.created_at_utc ?? 0).getTime() - new Date(b.created_at_utc ?? 0).getTime();
  if (sortKey === 'TYPE') return (a.capture_type_label || '').localeCompare(b.capture_type_label || '');
  if (sortKey === 'DECISION') return (a.capture_decision || '').localeCompare(b.capture_decision || '');
  return new Date(b.created_at_utc ?? 0).getTime() - new Date(a.created_at_utc ?? 0).getTime();
}

function StepHeader({ index, title, done, active }: { index: number; title: string; done: boolean; active: boolean }) {
  return (
    <div className="flex items-center gap-3">
      {done ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : active ? <Loader2 className="h-5 w-5 animate-spin text-cyan-400" /> : <Circle className="h-5 w-5 text-slate-600" />}
      <span className={`text-sm font-semibold ${active ? 'text-cyan-200' : done ? 'text-emerald-200' : 'text-slate-500'}`}>Paso {index}. {title}</span>
    </div>
  );
}

function previewDatasetIdFor(projectId: string, captureIds: string[]): string {
  // A dataset manifest is immutable once frozen (DATASET_ALREADY_FROZEN on a
  // second attempt), and a fixed "PREVIEW-DS" id collided with itself the
  // moment more than one feasibility check ran for the same operator (the
  // automatic recommendation and the manual "Comprobar" button, or simply
  // adding more captures between two checks). Folding a short, deterministic
  // hash of the actual capture set into the id gives each distinct set of
  // captures its own preview dataset, so recomputing feasibility for the
  // SAME captures reuses it (no collision) and a DIFFERENT set gets a fresh
  // one (reflects what was actually just captured).
  const sortedIds = [...captureIds].sort().join(',');
  let hash = 0;
  for (let i = 0; i < sortedIds.length; i++) hash = (hash * 31 + sortedIds.charCodeAt(i)) >>> 0;
  return `${projectId}-PREVIEW-DS-${hash.toString(36)}`.replace(/[^A-Za-z0-9._-]/g, '');
}

/** Idempotent: a dataset manifest is immutable once frozen, so re-checking
 * feasibility for the exact same capture set must reuse the existing
 * preview dataset (DATASET_ALREADY_FROZEN from api.createDataset is
 * expected and swallowed here) rather than error out. */
async function ensurePreviewDataset(projectId: string, campaignId: string, captureIds: string[]): Promise<string> {
  const previewDatasetId = previewDatasetIdFor(projectId, captureIds);
  try {
    await api.createDataset({ dataset_id: previewDatasetId, dataset_version: '0.0.0', project_id: projectId, campaign_id: campaignId, capture_ids: captureIds });
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '';
    if (!detail.includes('DATASET_ALREADY_FROZEN')) throw e;
  }
  return previewDatasetId;
}

// Remembers the last capture selection actually used to train (i.e. the one
// behind "Usar N captura(s) real(es)"), per project, purely client-side --
// re-selecting the same 20-30 checkboxes by hand every time an operator
// wants to retrain was the real, reported pain point. Never a substitute
// for "Acceso directo a datasets": this is just a one-click shortcut back to
// whatever was last selected, so Steps 1-3 don't have to be redone by hand.
interface LastCaptureSelection { project_id: string; capture_ids: string[]; saved_at: string }
const LAST_CAPTURE_SELECTION_STORAGE_KEY = 'ble-rffi-studio-last-capture-selection';
function loadLastCaptureSelection(): LastCaptureSelection | null {
  try {
    const raw = window.localStorage.getItem(LAST_CAPTURE_SELECTION_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as LastCaptureSelection) : null;
  } catch {
    return null;
  }
}
function saveLastCaptureSelection(projectId: string, captureIds: string[]): void {
  try {
    window.localStorage.setItem(LAST_CAPTURE_SELECTION_STORAGE_KEY, JSON.stringify({
      project_id: projectId, capture_ids: captureIds, saved_at: new Date().toISOString(),
    } satisfies LastCaptureSelection));
  } catch {
    // best-effort only -- a localStorage failure (private browsing, quota)
    // must never break the real action (useRealCaptures) it's attached to.
  }
}

function formatCaptureTimestamp(iso: string | null | undefined): string {
  if (!iso) return 'fecha desconocida';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'fecha desconocida';
  return date.toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'medium' });
}

function DeviceLabelBadge({ label, source }: { label?: string; source?: StudioDeviceSource }) {
  if (!label || !source) return <span className="text-slate-600">--</span>;
  const toneClass: Record<StudioDeviceSource, string> = {
    ISOLATION_DECLARED: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200',
    ADDRESS_MATCH: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    MULTIPLE_ADDRESS_MATCHES: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    ENVIRONMENT_NO_MATCH: 'border-slate-600 bg-slate-800 text-slate-400',
    NOT_ANALYZED: 'border-slate-700 text-slate-500',
    DECLARED_NOT_CONFIRMED: 'border-violet-500/40 bg-violet-500/10 text-violet-200',
  };
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${toneClass[source]}`}>{label}</span>;
}

const CAPTURE_DECISION_TONE: Record<StudioCaptureDecision, string> = {
  ELIGIBLE_AS_POSITIVE: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  ELIGIBLE_AS_BACKGROUND: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  ELIGIBLE_AS_UNKNOWN: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  CONTROL_ONLY: 'border-sky-500/40 bg-sky-500/10 text-sky-200',
  REPETITION_NEEDED: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  QUARANTINED: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  QUARANTINED_AMBIGUOUS: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  NOT_ANALYZED_YET: 'border-slate-700 text-slate-500',
};
const CAPTURE_DECISION_TEXT: Record<StudioCaptureDecision, string> = {
  ELIGIBLE_AS_POSITIVE: 'VALIDADA COMO DISPOSITIVO',
  ELIGIBLE_AS_BACKGROUND: 'VALIDADA COMO ENTORNO',
  ELIGIBLE_AS_UNKNOWN: 'VALIDADA COMO DESCONOCIDO',
  CONTROL_ONLY: 'CONTROL VALIDO SIN EJEMPLOS SUFICIENTES',
  REPETITION_NEEDED: 'REPETICION NECESARIA',
  // Only the one real, provable contradiction (BACKGROUND_TARGET_OFF whose
  // declared-off target was actually detected) -- never used for generic
  // native-scan ambiguity, which gets its own, honest label below.
  QUARANTINED: 'CUARENTENA POR CONTRADICCION',
  QUARANTINED_AMBIGUOUS: 'CUARENTENA POR AMBIGUEDAD DE CORRELACION',
  NOT_ANALYZED_YET: 'SIN ANALIZAR',
};

function CaptureDecisionBadge({ decision }: { decision?: StudioCaptureDecision | string | null }) {
  const key = (decision as StudioCaptureDecision) || 'NOT_ANALYZED_YET';
  const toneClass = CAPTURE_DECISION_TONE[key] || 'border-slate-700 text-slate-500';
  const text = CAPTURE_DECISION_TEXT[key] || String(decision || 'SIN ANALIZAR');
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${toneClass}`}>{text}</span>;
}

function DataSourceBadge({ source }: { source: DataSource }) {
  if (!source) return null;
  return <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-200">REAL</span>;
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone: 'ok' | 'warn' | 'muted' }) {
  const toneClass = tone === 'ok' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : 'text-slate-400';
  return (
    <div className="flex items-center justify-between border-b border-slate-800/60 py-1 text-xs last:border-b-0">
      <span className="text-slate-400">{label}</span>
      <span className={`font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

interface CampaignSessionRecord {
  session_index: number;
  capture_id: string;
  session_id: string;
  condition_label: string;
  capture_purpose: StudioCapturePurpose;
  target_state?: string;
  eligible_examples: number;
  total_examples: number;
  discontinuities: number;
  acquisition_quality?: string;
  capture_type_label?: string;
  capture_decision?: StudioCaptureDecision;
  device_label?: string;
  started_at_utc: string;
  error?: string;
}

function PipelineStatusBlock({ bundles, trainingRuns }: { bundles: StudioBundleManifest[]; trainingRuns: StudioTrainingRun[] }) {
  const realCompletedRun = trainingRuns.some((r) => r.data_origin === 'REAL_B200' && r.status === 'COMPLETED');
  const realModelAvailable = bundles.some((b) => b.data_origin === 'REAL_B200' && (b.approval_status === 'EVALUATED' || b.approval_status === 'APPROVED_FOR_LIVE_PILOT'));
  const liveMonitorApproved = bundles.some((b) => b.approval_status === 'APPROVED_FOR_LIVE_PILOT');

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-950 p-3">
      <StatusRow label="Pipeline de software" value="OPERATIVO" tone="ok" />
      <StatusRow label="Dataset real disponible" value={realCompletedRun ? 'SUFICIENTE' : 'INSUFICIENTE'} tone={realCompletedRun ? 'ok' : 'warn'} />
      <StatusRow label="Modelo BLE-RFFI con datos reales" value={realModelAvailable ? 'DISPONIBLE' : 'NO DISPONIBLE'} tone={realModelAvailable ? 'ok' : 'warn'} />
      <StatusRow label="Integracion Live Monitor" value={liveMonitorApproved ? 'LISTA (bundle aprobado)' : 'PENDIENTE'} tone={liveMonitorApproved ? 'ok' : 'muted'} />
    </section>
  );
}

export default function BleRffiStudioGuided() {
  const [backendError, setBackendError] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  // Step 1: que quieres capturar (the very first question -- never forces a
  // device to be picked before this, since a background/environment capture
  // may not need one at all).
  const [capturePurpose, setCapturePurpose] = useState<StudioCapturePurpose | null>(null);

  // Step 2a: device (mandatory for TARGET_DEVICE, optional/documentary for
  // BACKGROUND_ENVIRONMENT)
  const [units, setUnits] = useState<StudioPhysicalUnit[]>([]);
  const [selectedUnitId, setSelectedUnitId] = useState('');
  const [newUnitId, setNewUnitId] = useState('');
  const [newUnitFamily, setNewUnitFamily] = useState('');
  const [newUnitManufacturer, setNewUnitManufacturer] = useState('');
  const [newBindingAddress, setNewBindingAddress] = useState('');
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [showIdentityHelp, setShowIdentityHelp] = useState(false);
  const [addressBindings, setAddressBindings] = useState<StudioAddressBinding[]>([]);
  const [activeDevices, setActiveDevices] = useState<NativeBleDevice[]>([]);
  const [detectingDevices, setDetectingDevices] = useState(false);
  const [devicesDetectedAt, setDevicesDetectedAt] = useState<Date | null>(null);
  // How long the real BLE scan window itself runs for -- 8s was a fixed
  // default, not a hardware limit. A longer window catches more/weaker
  // devices (and devices that advertise less often) at the cost of a longer
  // wait; a shorter one is faster when the operator already knows what
  // they're looking for.
  const [scanDurationSeconds, setScanDurationSeconds] = useState(8);
  // Filters for the detected-devices dropdown (see unregisteredActiveDevices
  // below) -- a real BLE scan in a populated area easily returns dozens of
  // far-away devices; without these, the operator has to scroll past all of
  // them to find the one they actually want to register.
  const [deviceFilterName, setDeviceFilterName] = useState('');
  const [deviceFilterMac, setDeviceFilterMac] = useState('');
  // -127 dBm is the practical floor of the RSSI scale -- nothing is excluded
  // by default. Real far-away devices commonly report well below -100 dBm,
  // so defaulting the floor any higher silently hid devices the operator
  // used to see; the filter is opt-in, only tightened when the operator
  // actually wants to cut out distant devices.
  const [deviceFilterMinRssiDbm, setDeviceFilterMinRssiDbm] = useState(-127);
  // Generous on purpose (not NATIVE_DEVICE_FRESHNESS_SECONDS=45): this is a
  // review of the LAST SCAN's results, which the operator must still be able
  // to open minutes later (e.g. after a capture/analysis step that runs
  // long) -- a tight default here silently emptied the whole dropdown while
  // real work was still running, not just while nothing was ever found.
  const [deviceFilterMaxAgeSeconds, setDeviceFilterMaxAgeSeconds] = useState(3600);

  // Step 2b: condicion experimental / operator declaration
  const [isolationDeclared, setIsolationDeclared] = useState(false);
  const [operatorConfirmedTargetAbsent, setOperatorConfirmedTargetAbsent] = useState(false);

  // Data selected/captured so far
  const [dataSource, setDataSource] = useState<DataSource>(null);
  const [legacy, setLegacy] = useState<StudioLegacyCaptureListing | null>(null);
  const [selectedLegacyIds, setSelectedLegacyIds] = useState<string[]>([]);
  const [lastCaptureSelection, setLastCaptureSelection] = useState<LastCaptureSelection | null>(() => loadLastCaptureSelection());
  const [captureListFilter, setCaptureListFilter] = useState<CaptureListFilter>('ALL');
  const [captureSortKey, setCaptureSortKey] = useState<CaptureSortKey>('TIME_DESC');
  const [projectId, setProjectId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  // Bumped whenever the operator changes the objetivo (scientific_task)
  // AFTER captures already exist under the current campaign -- a new
  // objetivo must never silently reinterpret earlier captures as evidence
  // for a different question than the one they were actually gathered for.
  const [campaignVersion, setCampaignVersion] = useState(1);
  const [captureIds, setCaptureIds] = useState<string[]>([]);

  // Step 3: iniciar captura (real campaign session via B200)
  const [campaignDeviceStatus, setCampaignDeviceStatus] = useState<StudioCampaignDeviceStatus | null>(null);
  const [campaignBleChannel, setCampaignBleChannel] = useState(37);
  const [campaignDurationSeconds, setCampaignDurationSeconds] = useState(10);
  const [campaignGainDb, setCampaignGainDb] = useState(20);
  const [campaignConditionLabel, setCampaignConditionLabel] = useState('');
  const [campaignTargetEligibleExamples, setCampaignTargetEligibleExamples] = useState(60);
  const [campaignMaxSessions, setCampaignMaxSessions] = useState(6);
  const [campaignJob, setCampaignJob] = useState<StudioJob | null>(null);
  const [campaignSessions, setCampaignSessions] = useState<CampaignSessionRecord[]>([]);
  // OFFLINE_REPLAY (decode) is by far the slowest phase -- can take many
  // minutes per capture, while the RF acquisition itself is only a handful
  // of seconds. Checking this lets the operator capture several devices
  // quickly while they're powered on, and apply the slow analysis to each
  // one later (see the per-row "Aplicar analisis" action below) instead of
  // waiting on decode between every single capture.
  const [captureOnly, setCaptureOnly] = useState(false);
  const campaignJobRunning = !!campaignJob && !JOB_TERMINAL.has(campaignJob.state);
  const campaignEligibleTotal = campaignSessions.reduce((sum, s) => sum + s.eligible_examples, 0);

  // Progress counted separately per capture_purpose -- an operator with one
  // physical unit and no environment recordings yet needs to see exactly
  // that gap, not a single conflated number.
  const deviceSessions = campaignSessions.filter((s) => s.capture_purpose === 'TARGET_DEVICE_ON' && !s.error);
  const backgroundSessions = campaignSessions.filter((s) => (s.capture_purpose === 'BACKGROUND_TARGET_OFF' || s.capture_purpose === 'BACKGROUND_GENERAL') && !s.error);
  const deviceEligibleSessions = deviceSessions.filter((s) => s.capture_decision === 'ELIGIBLE_AS_POSITIVE');
  const backgroundEligibleSessions = backgroundSessions.filter((s) => s.capture_decision === 'ELIGIBLE_AS_BACKGROUND');
  const deviceEligibleExamples = deviceSessions.reduce((sum, s) => sum + s.eligible_examples, 0);
  const backgroundEligibleExamples = backgroundSessions.reduce((sum, s) => sum + s.eligible_examples, 0);
  // Derived from the sessions actually used, never from selectedUnitId alone
  // -- that Step 2 selection can be stale (or belong to a different unit
  // entirely) by the time an operator has selected several EXISTING captures
  // via "Usar N capturas", which never re-touches selectedUnitId at all.
  const deviceLabelsUsed = Array.from(new Set(deviceSessions.map((s) => s.device_label).filter((label): label is string => !!label)));

  // Step 4: objetivo (scientific task)
  const [scientificTasks, setScientificTasks] = useState<Record<string, string>>({});
  const [scientificTask, setScientificTask] = useState('SAME_MODEL_UNIT_IDENTIFICATION');

  // Step 5: prepare + train
  const [speedProfile, setSpeedProfile] = useState<'quick_pilot' | 'normal'>('quick_pilot');
  const [job, setJob] = useState<StudioJob | null>(null);
  const [result, setResult] = useState<StudioPrepareAndTrainSummary | null>(null);

  // Step 6: export -- per-training_run_id state (never a single selection),
  // so exporting one candidate never removes the option to export another.
  // The backend itself has no single-export restriction (export_bundle()
  // accepts any evaluated training_run_id); every candidate already has its
  // own persisted VALIDATION-only evaluation from prepare_and_train's
  // comparison pass. Only the recommended run also has a one-time TEST
  // evaluation by default -- exporting a non-recommended candidate this way
  // still works (bundle comes back REJECTED, since min_test_accuracy can't
  // be checked without a TEST evaluation), and resultTestEvalProvenance
  // tracks the explicit, audited opt-in (evaluateOnTestOptIn) that lets a
  // specific non-recommended candidate become EVALUATED/approvable too, for
  // comparing several exported models live in Live Monitor.
  const [resultBundleIds, setResultBundleIds] = useState<Record<string, string>>({});
  const [resultExported, setResultExported] = useState<Record<string, StudioBundleManifest>>({});
  const [resultTestEvalProvenance, setResultTestEvalProvenance] = useState<Record<string, StudioTestEvaluationProvenance>>({});

  // Acceso directo: browse/export any EXISTING training run (already on
  // disk, from this or any previous session) without redoing Steps 1-5.
  // Reported gap: the wizard's `result`/`trained_models` only ever exist in
  // React state after prepare_and_train just ran in THIS page load -- a
  // reload, or simply wanting to export something trained earlier, had no
  // path other than re-running the whole guided flow again (which, being
  // fully deterministic on the same captures, wastes real time for zero
  // new information). Every training run's evaluation is already persisted
  // to disk regardless -- this panel just exposes that directly.
  const [directAccessOpen, setDirectAccessOpen] = useState(false);
  const [directExpandedId, setDirectExpandedId] = useState<string | null>(null);
  const [directEvaluations, setDirectEvaluations] = useState<Record<string, StudioEvaluationResult>>({});
  const [directEvaluationsLoading, setDirectEvaluationsLoading] = useState(false);
  const [directBundleIds, setDirectBundleIds] = useState<Record<string, string>>({});
  const [directExportedBundles, setDirectExportedBundles] = useState<Record<string, StudioBundleManifest>>({});
  // gate_reasons explain WHY a bundle came back REJECTED (single-class TRAIN,
  // missing background class, TEST accuracy below minimum, etc.) -- the
  // export call always returns them, but they were being silently dropped,
  // leaving "Estado: REJECTED" with no explanation at all.
  const [directGateReasons, setDirectGateReasons] = useState<Record<string, string[]>>({});
  // dataset_id/version -> physical_units, fetched ONCE (not per training run)
  // so the table can show WHICH device each run was trained for.
  const [datasetPhysicalUnits, setDatasetPhysicalUnits] = useState<Record<string, string[]>>({});
  // Root-level fix, not another warning banner: single-class runs are all
  // LEFTOVER artifacts from before the split_builder single-class-TRAIN gate
  // (see that section above) -- structurally impossible to produce again
  // going forward, since SplitBuilder now refuses to freeze a split whose
  // TRAIN has fewer than 2 classes. They clutter this list for old data
  // only. Hidden by default (never silently deleted -- still one click away)
  // instead of making every operator discover each one by expanding it.
  const [directShowDegenerate, setDirectShowDegenerate] = useState(false);
  // Bulk delete over training runs listed in "Acceso directo" -- reported
  // need: 97+ accumulated runs (many from earlier debugging sessions) with
  // no way to clear them except one-by-one through the API directly.
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set());

  // Datasets + bundles: the two other artifact types the pipeline produces
  // (captura -> evidencia -> DATASET -> particion -> entrenamiento -> BUNDLE),
  // with the same direct view+delete access as training runs above -- kept as
  // its own section rather than folded into "Acceso directo" since a dataset
  // isn't a model and shouldn't be found by looking for one.
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const [datasets, setDatasets] = useState<StudioDatasetManifest[]>([]);
  const [selectedDatasetKeys, setSelectedDatasetKeys] = useState<Set<string>>(new Set());
  const [selectedBundleIds, setSelectedBundleIds] = useState<Set<string>>(new Set());

  // Device Scrubbing: for an "always-on" device (never genuinely off, so
  // TARGET_VS_BACKGROUND never sees a real "absent" example -- see
  // backend/README.md), removes its own decoded packets from its
  // contaminated background captures and trains original-vs-scrubbed side
  // by side. One button, auto-detected candidates -- see
  // StudioRepository.scrub_device_from_background().
  const [scrubOpen, setScrubOpen] = useState(false);
  const [scrubUnitId, setScrubUnitId] = useState('');
  const [scrubCandidates, setScrubCandidates] = useState<StudioCaptureRecord[] | null>(null);
  const [scrubJob, setScrubJob] = useState<StudioJob | null>(null);

  // Training Service: operator picks an ALREADY-frozen, already-labeled
  // dataset (e.g. either SHELLY-PLUG-01's WITH-device or WITHOUT-device
  // background variant) plus exactly which model_type candidates to train
  // -- never builds a new dataset. Run name (date+time+device) is generated
  // internally by the backend as each TrainingRun's campaign_id -- see
  // StudioRepository.train_selected_models().
  const ALL_MODEL_TYPES = ['logistic_regression', 'svm_rbf', 'random_forest', 'cnn1d', 'cnn2d'] as const;
  const [trainSvcOpen, setTrainSvcOpen] = useState(false);
  const [trainSvcDatasetKeys, setTrainSvcDatasetKeys] = useState<Set<string>>(new Set());
  const [trainSvcModelTypes, setTrainSvcModelTypes] = useState<Set<string>>(new Set(ALL_MODEL_TYPES));
  // Optional, only used when combining 2+ datasets: use ONE dataset's own
  // background-only examples as the SHARED "environment absent" evidence
  // for every device, instead of pooling each device's own (often much
  // thinner) background pool -- real request after SHELLY-PLUG-01's
  // combined identity model failed to recognize it live, traced to most
  // per-device datasets carrying only the bare 3-session background
  // minimum while SHELLY-PLUG-01-SCRUBBED-BG-TVB has real, verified,
  // 8-session background evidence (see backend/README.md).
  const [trainSvcBackgroundKey, setTrainSvcBackgroundKey] = useState('');
  const [trainSvcJob, setTrainSvcJob] = useState<StudioJob | null>(null);
  const [trainSvcExporting, setTrainSvcExporting] = useState(false);

  const refreshDatasets = async () => {
    const all = await api.datasets();
    setDatasets(Array.isArray(all) ? all : []);
  };

  useEffect(() => {
    if (!(artifactsOpen || trainSvcOpen) || datasets.length) return;
    refreshDatasets().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactsOpen, trainSvcOpen]);

  // Benchmark: professional side-by-side comparison across every trained
  // model, real request after live detection kept failing despite a good
  // TEST score -- reuses the exact same allTrainingRuns/directEvaluations
  // data Acceso Directo already loads (see the shared eager-fetch effects
  // below), adding only per-dataset label provenance on top.
  const [benchmarkOpen, setBenchmarkOpen] = useState(false);
  const [datasetLabelProvenance, setDatasetLabelProvenance] = useState<Record<string, StudioLabelProvenanceReport>>({});
  // Real request: "como lanzar la comparacion de benchmark de todos los
  // modelos o de algunos modelos" -- a passive table alone did not answer
  // that. benchmarkTaskFilter narrows to a comparable subset (models on
  // different scientific_task never answer the same question, so comparing
  // across tasks is meaningless); benchmarkSelected + "Comparar
  // seleccionados" runs a real, sequential VALIDATION re-evaluation over
  // exactly the chosen rows (or every visible row if none are checked) and
  // then the table sorts by task and marks the top scorer per task.
  const [benchmarkTaskFilter, setBenchmarkTaskFilter] = useState<'ALL' | 'TARGET_VS_BACKGROUND' | 'IDENTITY' | 'UNKNOWN_DEVICE_REJECTION'>('ALL');
  const [benchmarkSelected, setBenchmarkSelected] = useState<Record<string, boolean>>({});
  const [benchmarkComparing, setBenchmarkComparing] = useState(false);
  const [benchmarkProgress, setBenchmarkProgress] = useState('');

  const isSingleClassRun = (trainingRunId: string): boolean | undefined => {
    const evaluation = directEvaluations[trainingRunId];
    if (!evaluation) return undefined;
    const validation = evaluation.evaluation_report.VALIDATION;
    if (!validation) return undefined;
    return validation.evaluation_validity === 'INVALID_SINGLE_CLASS_EVALUATION' || Object.keys(validation.confusion_matrix || {}).length < 2;
  };

  // A FAILED run never produced predictions.json/evaluation_report.json at
  // all -- export_bundle() correctly refuses it (surfaced as a confusing
  // bare 404, "TRAINING_RUN_NOT_EVALUATED_YET"), so it belongs in the same
  // "never exportable, hide by default" bucket as single-class runs.
  const isJunkRun = (run: StudioTrainingRun): boolean => run.status !== 'COMPLETED' || isSingleClassRun(run.training_run_id) === true;

  // Fetches every training run's evaluation ONCE when the panel opens (all
  // in parallel -- against a local backend this is fast even for 47+ runs),
  // so the list itself is honest from the start instead of showing a
  // misleading 100% until the operator happens to expand that exact row.
  const toggleDirectExpand = (trainingRunId: string) => run(`direct-expand-${trainingRunId}`, async () => {
    if (directExpandedId === trainingRunId) {
      setDirectExpandedId(null);
      return;
    }
    setDirectExpandedId(trainingRunId);
    if (!directEvaluations[trainingRunId]) {
      const evaluation = await api.getEvaluation(trainingRunId).catch(() => null);
      if (evaluation) setDirectEvaluations((prev) => ({ ...prev, [trainingRunId]: evaluation }));
    }
    if (!directBundleIds[trainingRunId]) setDirectBundleIds((prev) => ({ ...prev, [trainingRunId]: `${trainingRunId}-bundle` }));
    // Already exported in a PREVIOUS session (not just this page load)? Show
    // that immediately -- gate_reasons themselves are only returned at
    // export time (never persisted on the bundle), so an old export's
    // original reasons are only visible again by re-exporting (harmless and
    // deterministic: same training_run_id always recomputes the same result).
    if (!directExportedBundles[trainingRunId]) {
      const alreadyExported = bundles.find((b) => b.training_run_id === trainingRunId);
      if (alreadyExported) setDirectExportedBundles((prev) => ({ ...prev, [trainingRunId]: alreadyExported }));
    }
  });

  const exportDirect = (trainingRunId: string) => run(`direct-export-${trainingRunId}`, async () => {
    const targetBundleId = directBundleIds[trainingRunId] || `${trainingRunId}-bundle`;
    const exported = await api.exportBundle(trainingRunId, {
      bundle_id: targetBundleId, acceptance_criteria: { min_test_accuracy: 0.5 },
      model_card_text: `# ${targetBundleId}\nExportado desde Acceso directo (BLE-RFFI Studio), sin repetir el flujo guiado.`,
    });
    setDirectExportedBundles((prev) => ({ ...prev, [trainingRunId]: exported.bundle }));
    setDirectGateReasons((prev) => ({ ...prev, [trainingRunId]: exported.gate_reasons || [] }));
    await refreshStatusBlock();
  });

  // Pipeline-wide status block (top of page)
  const [bundles, setBundles] = useState<StudioBundleManifest[]>([]);
  const [allTrainingRuns, setAllTrainingRuns] = useState<StudioTrainingRun[]>([]);

  const refreshStatusBlock = async () => {
    const [bundlesRes, runsRes] = await Promise.all([api.bundles(), api.trainingRuns()]);
    setBundles(Array.isArray(bundlesRes) ? bundlesRes : []);
    setAllTrainingRuns(Array.isArray(runsRes) ? runsRes : []);
  };

  useEffect(() => {
    if (!(directAccessOpen || benchmarkOpen || trainSvcOpen) || Object.keys(datasetPhysicalUnits).length) return;
    api.datasets().then((all) => {
      const map: Record<string, string[]> = {};
      for (const ds of all) map[`${ds.dataset_id}/${ds.dataset_version}`] = ds.physical_units;
      setDatasetPhysicalUnits(map);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directAccessOpen, benchmarkOpen, trainSvcOpen]);

  useEffect(() => {
    if (!(directAccessOpen || benchmarkOpen) || !allTrainingRuns.length) return;
    const missing = allTrainingRuns.filter((r) => !directEvaluations[r.training_run_id] && r.status === 'COMPLETED');
    if (!missing.length) return;
    setDirectEvaluationsLoading(true);
    Promise.all(missing.map((r) => api.getEvaluation(r.training_run_id).then((ev) => [r.training_run_id, ev] as const).catch(() => null)))
      .then((results) => {
        setDirectEvaluations((prev) => {
          const next = { ...prev };
          for (const entry of results) if (entry) next[entry[0]] = entry[1];
          return next;
        });
      })
      .finally(() => setDirectEvaluationsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directAccessOpen, benchmarkOpen, allTrainingRuns.length]);

  // Label provenance is per-DATASET, not per-run -- dedup by dataset_id/
  // version so N training runs sharing one dataset only fetch it once.
  useEffect(() => {
    if (!benchmarkOpen || !allTrainingRuns.length) return;
    const uniqueDatasets = Array.from(new Set(
      allTrainingRuns.filter((r) => r.status === 'COMPLETED').map((r) => `${r.dataset_id}::${r.dataset_version}`)
    )).filter((key) => !datasetLabelProvenance[key]);
    if (!uniqueDatasets.length) return;
    Promise.all(uniqueDatasets.map((key) => {
      const [datasetId, datasetVersion] = key.split('::');
      return api.labelProvenance(datasetId, datasetVersion).then((report) => [key, report] as const).catch(() => null);
    })).then((results) => {
      setDatasetLabelProvenance((prev) => {
        const next = { ...prev };
        for (const entry of results) if (entry) next[entry[0]] = entry[1];
        return next;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [benchmarkOpen, allTrainingRuns.length]);

  useEffect(() => {
    (async () => {
      try {
        const [unitsRes, legacyRes, tasksRes, bindingsRes] = await Promise.all([api.physicalUnits(), api.legacyCaptures(), api.scientificTasks(), api.addressBindings()]);
        setUnits(Array.isArray(unitsRes) ? unitsRes : []);
        setLegacy(legacyRes);
        setScientificTasks(tasksRes || {});
        setAddressBindings(Array.isArray(bindingsRes) ? bindingsRes : []);
        await refreshStatusBlock();
        try {
          setCampaignDeviceStatus(await api.campaignDeviceStatus());
        } catch {
          // No B200/hybrid manager available in this environment -- the
          // campaign launcher below stays disabled with an explanation
          // instead of silently pretending hardware is reachable.
          setCampaignDeviceStatus(null);
        }
      } catch (e) {
        setBackendError(describeApiError(e));
      }
    })();
  }, []);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(describeApiError(e));
    } finally {
      setBusy('');
    }
  };

  // --- Step 1 action ---
  const chooseCapturePurpose = (purpose: StudioCapturePurpose) => {
    setCapturePurpose(purpose);
    setOperatorConfirmedTargetAbsent(false);
    setIsolationDeclared(false);
    // No specific unit in question for these three -- TARGET_DEVICE_ON is
    // the only purpose that names one.
    if (purpose !== 'TARGET_DEVICE_ON') {
      setSelectedUnitId('');
    }
  };

  // --- Step 2 device actions ---
  const selectExistingUnit = (unit: StudioPhysicalUnit) => {
    setSelectedUnitId(unit.physical_unit_id);
    setProjectId(unit.project_id);
  };

  const clearSelectedUnit = () => setSelectedUnitId('');

  const boundAddressesFor = (physicalUnitId: string): string[] =>
    addressBindings.filter((b) => b.bound_physical_unit_id === physicalUnitId).map((b) => String(b.address).toUpperCase());

  // Returns the actual scanned device behind a registered unit's "ACTIVO
  // AHORA" badge (not just a boolean) so its real-time RSSI can be shown --
  // an operator deciding where to stand/how close to hold the device needs
  // the number, not just an on/off indicator.
  const activeDeviceFor = (unit: StudioPhysicalUnit): NativeBleDevice | undefined => {
    const addresses = boundAddressesFor(unit.physical_unit_id);
    return activeDevices.find((d) => addresses.includes(d.address.toUpperCase()) && isDeviceActiveNow(d));
  };

  const isUnitActiveNow = (unit: StudioPhysicalUnit): boolean => !!activeDeviceFor(unit);

  const boundAddressSet = new Set(addressBindings.map((b) => String(b.address).toUpperCase()));
  // Deliberately NOT gated by isDeviceActiveNow (a 45s-fresh, constantly
  // draining check): this is "what did the last scan see", not "what is
  // broadcasting this exact instant" -- it must stay reviewable (collapsed,
  // reopenable) long after the scan itself, e.g. while a capture/analysis
  // step is still running. Recency is only a filter inside the dropdown
  // (deviceFilterMaxAgeSeconds), never a reason for the whole section to
  // vanish.
  const unregisteredActiveDevices = activeDevices.filter((d) => !boundAddressSet.has(d.address.toUpperCase()));

  const filteredUnregisteredActiveDevices = unregisteredActiveDevices.filter((d) => {
    if (deviceFilterName.trim() && !(d.local_name || '').toLowerCase().includes(deviceFilterName.trim().toLowerCase())) return false;
    if (deviceFilterMac.trim() && !d.address.toLowerCase().includes(deviceFilterMac.trim().toLowerCase())) return false;
    if (typeof d.rssi_dbm === 'number' && d.rssi_dbm < deviceFilterMinRssiDbm) return false;
    if (d.last_seen_utc) {
      const ageSeconds = (Date.now() - new Date(d.last_seen_utc).getTime()) / 1000;
      if (!Number.isNaN(ageSeconds) && ageSeconds > deviceFilterMaxAgeSeconds) return false;
    }
    return true;
  });

  // Real BLE scan (existing native adapter): start it, let advertisements
  // arrive for a few seconds, stop it. This is the same mechanism a real
  // capture session uses -- never simulated/fabricated presence.
  const detectActiveDevices = () => run('detect-devices', async () => {
    setDetectingDevices(true);
    try {
      await nativeScan.start();
      await new Promise((resolve) => setTimeout(resolve, Math.max(1, scanDurationSeconds) * 1000));
      // The backend only merges the scan worker's fresh observations into
      // its persistent registry INSIDE stop() (BleNativeJobManager._stop_scan
      // -> _write_scan_devices_snapshot) -- devices() itself never reads the
      // worker's live snapshot directly. Fetching devices() before stop()
      // returned only whatever a PREVIOUS scan had merged, which is often
      // already older than the 45s freshness window by the time it's read
      // (a real regression: showed 0 devices despite a real scan just
      // having run). stop() must complete first so this scan's own
      // observations are the ones just merged, with last_seen_utc from now.
      await nativeScan.stop().catch(() => {});
      const devices = await nativeScan.devices();
      setActiveDevices(devices);
      setDevicesDetectedAt(new Date());
    } finally {
      setDetectingDevices(false);
    }
  });

  const registerAndBind = () => run('register-device', async () => {
    const autoProjectId = `BLE-RFFI-${newUnitFamily.trim().toUpperCase().replace(/\s+/g, '_') || 'DEVICE'}`;
    const unit = await api.createPhysicalUnit({ physical_unit_id: newUnitId, project_id: autoProjectId, device_family: newUnitFamily, manufacturer: newUnitManufacturer || undefined, operator_declaration_id: `guided-decl-${newUnitId}` });
    if (newBindingAddress.trim()) {
      await api.createAddressBinding({ project_id: autoProjectId, address: newBindingAddress.trim(), address_type: 'public', physical_unit_id: unit.physical_unit_id, reason: 'Declaracion del operador (modo guiado)' });
    }
    setUnits(await api.physicalUnits());
    setAddressBindings(await api.addressBindings());
    setSelectedUnitId(unit.physical_unit_id);
    setProjectId(unit.project_id);
    setShowRegisterForm(false);
  });

  // Derives the same capture_purpose/target_state/target_reference_id/
  // dataset_role fields the backend contract expects, from what the
  // operator declared in Step 1/2 -- kept in one place so the live-campaign
  // path and the existing-capture path can never diverge on this mapping.
  const deriveCaptureFields = () => {
    if (capturePurpose === 'BACKGROUND_TARGET_OFF') {
      return {
        capture_purpose: 'BACKGROUND_TARGET_OFF' as const,
        target_state: 'OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED' as const,
        background_kind: 'TARGET_DECLARED_OFF_OR_REMOVED' as const,
        target_reference_id: selectedUnitId || undefined,
        dataset_role: 'NEGATIVE_CANDIDATE' as const,
      };
    }
    if (capturePurpose === 'BACKGROUND_GENERAL') {
      return {
        capture_purpose: 'BACKGROUND_GENERAL' as const,
        target_state: undefined,
        background_kind: 'GENERAL_AMBIENT' as const,
        target_reference_id: undefined,
        dataset_role: 'NEGATIVE_CANDIDATE' as const,
      };
    }
    if (capturePurpose === 'UNKNOWN_DEVICE_COLLECTION') {
      return {
        capture_purpose: 'UNKNOWN_DEVICE_COLLECTION' as const,
        target_state: undefined,
        background_kind: undefined,
        target_reference_id: undefined,
        dataset_role: 'UNKNOWN_CANDIDATE' as const,
      };
    }
    return {
      capture_purpose: 'TARGET_DEVICE_ON' as const,
      target_state: 'POWERED_ON' as const,
      background_kind: undefined,
      target_reference_id: selectedUnitId || undefined,
      dataset_role: 'POSITIVE_CANDIDATE' as const,
    };
  };

  // --- Step 2/3: use already-existing real captures instead of a live launch ---
  // overrideIds lets "Restaurar la ultima seleccion usada" (below) jump
  // straight to this exact action without waiting on a setSelectedLegacyIds
  // state update to land first -- selectedLegacyIds is still the default,
  // so every existing manual-checkbox call site is unaffected.
  const useRealCaptures = (overrideIds?: string[]) => run('use-real', async () => {
    const idsToUse = overrideIds ?? selectedLegacyIds;
    const autoCampaignId = `${projectId || 'BLE-RFFI-PROJECT'}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`;
    const effectiveProjectId = projectId || 'BLE-RFFI-PROJECT';
    setProjectId(effectiveProjectId);
    setCampaignId(autoCampaignId);
    const fields = deriveCaptureFields();
    const total = idsToUse.length;
    const operationId = `ble-rffi-studio-use-existing-${Date.now()}`;
    // This loop can take real, visible time (a network round-trip per
    // capture, plus a full resumable replay+evidence decode for any capture
    // not already analyzed) -- without this, clicking the button looked
    // like nothing was happening at all while several captures were
    // processed one by one in the background.
    ensureOperation({ operationId, kind: 'processing', title: `USANDO ${total} CAPTURA(S) EXISTENTE(S)`, phase: 'Iniciando', progressPercent: 0, target: `0/${total}`, detail: '' });
    try {
      const built: CampaignSessionRecord[] = [];
      for (let index = 0; index < idsToUse.length; index++) {
        const legacyId = idsToUse[index];
        const baseProgress = (index / total) * 100;
        updateOperation(operationId, { phase: `Captura ${index + 1}/${total}`, progressPercent: baseProgress, target: `${index}/${total}`, detail: `Construyendo registro para ${legacyId}...` });
        // execution_id/session_id are immutable facts about which physical
        // acquisition produced this capture -- the raw legacy manifest never
        // records session_id at all (only the orchestrator's live session
        // knew it), so rebuilding without carrying it forward from any
        // PREVIOUSLY built CaptureRecord fails with SESSION_ID_MISSING for
        // any capture built via a live campaign session.
        const existing = await api.getCapture(legacyId).catch(() => null);
        // A capture that was ALREADY declared/built before (it has its own
        // capture_purpose from whenever it was live-captured or first
        // classified) keeps its own identity here -- it must NEVER be
        // silently overwritten by whatever unit happens to be selected in
        // Step 2 right now. The "Capturas ya existentes" picker lets an
        // operator multi-select captures spanning SEVERAL different devices
        // at once (e.g. batching several sessions before training); blindly
        // re-declaring all of them under one current Step 2 selection was a
        // real, observed bug that silently relabeled already-correct
        // captures (e.g. a CC2650-UNIT-01 capture becoming declared as
        // CC2541SensorTag just because that was selected when "Usar N
        // capturas" was clicked). Only a capture with NO prior declaration
        // at all (genuinely being classified for the first time) uses
        // today's Step 1/2 fields.
        const captureFields = existing?.capture_purpose
          ? {
              capture_purpose: existing.capture_purpose, target_state: existing.target_state ?? undefined,
              background_kind: existing.background_kind ?? undefined, target_reference_id: existing.target_reference_id ?? undefined,
              dataset_role: existing.dataset_role ?? undefined,
            }
          : fields;
        const capture: StudioCaptureRecord = await api.createCapture({
          capture_id: legacyId, project_id: effectiveProjectId, campaign_id: autoCampaignId,
          execution_id: existing?.execution_id, session_id: existing?.session_id,
          ...captureFields,
        });
        // Replay + evidence must run against the CaptureRecord that was just
        // (re)declared -- the eligibility verdict for a BACKGROUND_TARGET_OFF
        // capture depends on the suppression rule in EvidenceStage, which only
        // applies at build time. Uses the full resumable-replay-then-evidence
        // job (not the evidence-only one) since a manually-selected legacy
        // capture may never have been decoded at all yet; it's also idempotent
        // by default (force not set), so re-selecting an already-analyzed
        // capture just skips instead of burning real decode time again.
        updateOperation(operationId, { phase: `Captura ${index + 1}/${total}`, progressPercent: baseProgress, target: `${index}/${total}`, detail: `Analizando ${legacyId} (replay + evidencia si hace falta)...` });
        let replayJob = await api.startReplayAndEvidenceJob(capture.capture_id, { project_id: effectiveProjectId, ble_channel: campaignBleChannel });
        while (!JOB_TERMINAL.has(replayJob.state)) {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          replayJob = await api.job(replayJob.job_id);
          updateOperation(operationId, { phase: `Captura ${index + 1}/${total}`, progressPercent: baseProgress, target: `${index}/${total}`, detail: `${legacyId}: ${replayJob.message || replayJob.state}` });
        }
        const examples = await api.examples(capture.capture_id).catch(() => []);
        const eligible = examples.filter(isDatasetIncludable).length;
        const freshLegacy = await api.legacyCaptures().catch(() => legacy);
        const row = freshLegacy?.captures.find((r) => r.capture_id === capture.capture_id);
        built.push({
          session_index: campaignSessions.length + built.length + 1, capture_id: capture.capture_id, session_id: capture.session_id,
          condition_label: campaignConditionLabel || 'Captura ya existente (seleccionada manualmente)',
          capture_purpose: (capture.capture_purpose as StudioCapturePurpose) || fields.capture_purpose, target_state: capture.target_state || fields.target_state,
          eligible_examples: eligible, total_examples: examples.length,
          discontinuities: 0, acquisition_quality: capture.acquisition_quality,
          capture_type_label: row?.capture_type_label, capture_decision: row?.capture_decision,
          device_label: row?.device_label,
          started_at_utc: capture.created_at,
        });
        if (freshLegacy) setLegacy(freshLegacy);
      }
      finishOperation(operationId, `${total} captura(s) lista(s)`);
      // Deduplicated by capture_id: clicking "Usar N captura(s) real(es)"
      // more than once with an overlapping selection must never let the same
      // capture_id end up repeated in captureIds -- a real, observed bug
      // where a repeated capture_id in the dataset's source list produced
      // hundreds of exact-duplicate example groups at quality-gate time
      // (build_dataset now also de-duplicates defensively, but this is
      // where the duplication was actually introduced).
      setCampaignSessions((prev) => {
        const seen = new Set(prev.map((s) => s.capture_id));
        return [...prev, ...built.filter((b) => !seen.has(b.capture_id))];
      });
      setCaptureIds((prev) => Array.from(new Set([...prev, ...built.map((b) => b.capture_id)])));
    } catch (e) {
      failOperation(operationId, describeApiError(e));
      throw e;
    }
    setDataSource('real');
    setResult(null);
    setJob(null);
    setSelectedLegacyIds(idsToUse);
    saveLastCaptureSelection(effectiveProjectId, idsToUse);
    setLastCaptureSelection({ project_id: effectiveProjectId, capture_ids: idsToUse, saved_at: new Date().toISOString() });
  });

  const launchCampaignSession = () => run('launch-campaign-session', async () => {
    if (!capturePurpose) return;
    const effectiveProjectId = projectId || 'BLE-RFFI-PROJECT';
    setProjectId(effectiveProjectId);
    if (!campaignId) setCampaignId(`${effectiveProjectId}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`);
    const effectiveCampaignId = campaignId || `${effectiveProjectId}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`;
    setCampaignId(effectiveCampaignId);
    const startedJob = await api.startCampaignSession({
      ble_channel: campaignBleChannel, duration_seconds: campaignDurationSeconds, gain_db: campaignGainDb,
      condition_label: campaignConditionLabel || 'Sin condicion declarada por el operador',
      physical_unit_id: selectedUnitId || null, project_id: effectiveProjectId, campaign_id: effectiveCampaignId,
      session_index: campaignSessions.length + 1,
      capture_purpose: capturePurpose,
      isolation_declared: capturePurpose === 'TARGET_DEVICE_ON' ? isolationDeclared : false,
      operator_confirmed_target_absent: capturePurpose === 'BACKGROUND_TARGET_OFF' ? operatorConfirmedTargetAbsent : undefined,
      capture_only: captureOnly,
    });
    setCampaignJob(startedJob);
  });

  // Guided capture: same result shape as launchCampaignSession (session_id,
  // capture_id, capture_purpose, etc.), so it reuses that exact same
  // campaignJob state + polling effect below -- no separate job-tracking
  // state needed. Only difference is which endpoint starts it: this one
  // probes with short B200 captures for a real signal (or a clean
  // environment) before recording the real, saved capture.
  const launchGuidedCapture = () => run('launch-guided-capture', async () => {
    if (!capturePurpose) return;
    const effectiveProjectId = projectId || 'BLE-RFFI-PROJECT';
    setProjectId(effectiveProjectId);
    if (!campaignId) setCampaignId(`${effectiveProjectId}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`);
    const effectiveCampaignId = campaignId || `${effectiveProjectId}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`;
    setCampaignId(effectiveCampaignId);
    const startedJob = await api.startGuidedCapture({
      ble_channel: campaignBleChannel, duration_seconds: campaignDurationSeconds, gain_db: campaignGainDb,
      condition_label: campaignConditionLabel || 'Sin condicion declarada por el operador',
      physical_unit_id: selectedUnitId || null, project_id: effectiveProjectId, campaign_id: effectiveCampaignId,
      session_index: campaignSessions.length + 1,
      capture_purpose: capturePurpose,
      isolation_declared: capturePurpose === 'TARGET_DEVICE_ON' ? isolationDeclared : false,
      operator_confirmed_target_absent: capturePurpose === 'BACKGROUND_TARGET_OFF' ? operatorConfirmedTargetAbsent : undefined,
    });
    setCampaignJob(startedJob);
  });

  // Runs the slow OFFLINE_REPLAY + Evidence Stage for a capture that already
  // has a CaptureRecord (built either by a capture_only session or by
  // "Usar captura(s) real(es)") -- the deliberately separable counterpart to
  // capture_only. Idempotent by default: re-clicking on an
  // already-processed capture just reports "skipped" (see
  // StudioRepository.run_replay_and_evidence) rather than re-decoding it;
  // pass force=true for a deliberate redo (e.g. after fixing an
  // AddressBinding). Processes one capture_id at a time (sequential, not
  // concurrent decodes) via a queue, so both a single-row click and a bulk
  // "aplicar a todas/seleccion" action share the exact same live progress
  // window as the real B200 capture session (ensureOperation/updateOperation).
  const [analysisQueue, setAnalysisQueue] = useState<string[]>([]);
  const [analysisForce, setAnalysisForce] = useState(false);
  const [currentAnalysisCaptureId, setCurrentAnalysisCaptureId] = useState<string | null>(null);
  const [analysisJob, setAnalysisJob] = useState<StudioJob | null>(null);
  const [analysisTotal, setAnalysisTotal] = useState(0);

  const queueAnalysis = (captureIds: string[], force = false) => {
    if (captureIds.length === 0) return;
    setError('');
    setAnalysisForce(force);
    setAnalysisTotal(captureIds.length);
    setAnalysisQueue(captureIds);
  };
  const applyAnalysis = (captureId: string, force = false) => queueAnalysis([captureId], force);

  // Fast (~1s, no IQ decode) native-scan-only triage -- lets the operator
  // learn a capture is doomed (target never seen natively) BEFORE spending
  // minutes on "Aplicar analisis". Per-capture, never auto-run (it's an
  // explicit opt-in action so it never adds latency to the normal list load).
  const [quickChecks, setQuickChecks] = useState<Record<string, StudioQuickPresenceCheck>>({});
  const [quickChecking, setQuickChecking] = useState('');
  const runQuickCheck = (captureId: string) => run(`quick-check-${captureId}`, async () => {
    setQuickChecking(captureId);
    try {
      const result = await api.quickPresenceCheck(captureId);
      setQuickChecks((prev) => ({ ...prev, [captureId]: result }));
    } finally {
      setQuickChecking('');
    }
  });

  const refreshCaptureRow = async (captureId: string) => {
    const freshLegacy = await api.legacyCaptures().catch(() => null);
    if (freshLegacy) setLegacy(freshLegacy);
    const row = freshLegacy?.captures.find((r) => r.capture_id === captureId);
    if (!row) return;
    const examples = await api.examples(captureId).catch(() => []);
    const eligible = examples.filter(isDatasetIncludable).length;
    setCampaignSessions((prev) => prev.map((s) => s.capture_id === captureId
      ? { ...s, capture_type_label: row.capture_type_label, capture_decision: row.capture_decision, eligible_examples: eligible, total_examples: examples.length }
      : s));
  };

  // Picks up the next queued capture_id once the previous one (if any) has
  // finished -- currentAnalysisCaptureId is only cleared by the polling
  // effect below once its job reaches a terminal state.
  useEffect(() => {
    if (currentAnalysisCaptureId || analysisQueue.length === 0) return;
    const [next, ...rest] = analysisQueue;
    setAnalysisQueue(rest);
    setCurrentAnalysisCaptureId(next);
    (async () => {
      try {
        // Use THIS capture's own recorded project_id, never the current
        // Step 1 field -- a session that captured under several project_id
        // spellings (e.g. mid-campaign renames) would otherwise silently
        // send the wrong one for whichever captures don't match whatever
        // happens to be typed in Step 1 right now, breaking AddressBinding
        // lookups for every packet in that capture even with zero real
        // correlation ambiguity.
        const captureRow = legacy?.captures.find((r) => r.capture_id === next);
        const effectiveProjectId = captureRow?.project_id || projectId || 'BLE-RFFI-PROJECT';
        const startedJob = await api.startReplayAndEvidenceJob(next, { project_id: effectiveProjectId, ble_channel: campaignBleChannel, force: analysisForce });
        setAnalysisJob(startedJob);
      } catch (e) {
        setError(describeApiError(e));
        setCurrentAnalysisCaptureId(null);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisQueue, currentAnalysisCaptureId]);

  useEffect(() => {
    if (!analysisJob || !currentAnalysisCaptureId || JOB_TERMINAL.has(analysisJob.state)) return;
    const operationId = `ble-rffi-studio-analysis-${analysisJob.job_id}`;
    const remaining = analysisQueue.length + 1;
    const positionLabel = analysisTotal > 1 ? ` (${analysisTotal - remaining + 1}/${analysisTotal})` : '';
    ensureOperation({
      operationId, kind: 'processing', title: `APLICANDO ANALISIS (REPLAY + EVIDENCIA)${positionLabel}`,
      phase: analysisJob.phase || 'Iniciando', progressPercent: (analysisJob.overall_progress || 0) * 100,
      target: currentAnalysisCaptureId, detail: analysisJob.message || '',
    });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(analysisJob.job_id);
        setAnalysisJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          const skipped = !!(next.result_summary as { skipped?: boolean } | undefined)?.skipped;
          if (next.state === 'completed') {
            finishOperation(operationId, skipped ? 'Ya estaba analizada (sin cambios)' : 'Analisis completado');
          } else {
            failOperation(operationId, next.error || 'El analisis fallo');
            setError(next.error || 'El analisis (replay + evidencia) fallo.');
          }
          await refreshCaptureRow(currentAnalysisCaptureId).catch(() => {});
          setCurrentAnalysisCaptureId(null);
          setAnalysisJob(null);
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
        setCurrentAnalysisCaptureId(null);
        setAnalysisJob(null);
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisJob?.job_id, analysisJob?.state]);

  const analysisRunning = !!currentAnalysisCaptureId;

  const deleteCapture = (captureId: string) => run(`delete-${captureId}`, async () => {
    if (!window.confirm(`Borrar la captura ${captureId}? Esto elimina el archivo IQ real de forma permanente (no se puede deshacer).`)) return;
    await api.deleteLegacyCapture(captureId);
    setSelectedLegacyIds((prev) => prev.filter((id) => id !== captureId));
    const freshLegacy = await api.legacyCaptures().catch(() => null);
    if (freshLegacy) setLegacy(freshLegacy);
  });

  // "Corregir y repetir": reuses the failed capture's declared purpose/unit
  // configuration in Step 1/2, then scrolls to Step 3 so the operator can
  // apply the specific fix repair_guidance named (duration, gain, physical
  // setup) and launch a genuinely NEW capture/session -- never mutates the
  // original IQ, never silently retries with the same broken setup.
  const applyRepairAndRepeat = (captureId: string) => run(`repair-${captureId}`, async () => {
    const capture = await api.getCapture(captureId).catch(() => null);
    if (!capture) return;
    setCapturePurpose((capture.capture_purpose as StudioCapturePurpose) || 'TARGET_DEVICE_ON');
    setSelectedUnitId(capture.target_reference_id || capture.physical_unit_id || '');
    setOperatorConfirmedTargetAbsent(false);
    setIsolationDeclared(false);
    if (capture.project_id) setProjectId(capture.project_id);
    document.getElementById('step-3-launch')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });

  const campaignOperationTitle = (phase: string | null | undefined) => phase === 'WAITING_FOR_DEVICE' ? 'AHORA ENCIENDE EL DISPOSITIVO' : phase === 'PROBE_BASELINE' || phase === 'PROBE_ENVIRONMENT' ? 'SONDEANDO EL ESPECTRO (B200)' : 'CAPTURANDO SESION REAL (B200)';

  useEffect(() => {
    if (!campaignJob || JOB_TERMINAL.has(campaignJob.state)) return;
    const operationId = `ble-rffi-studio-campaign-${campaignJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: campaignOperationTitle(campaignJob.phase), phase: campaignJob.phase || 'Iniciando', progressPercent: (campaignJob.overall_progress || 0) * 100, target: campaignConditionLabel, detail: campaignJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(campaignJob.job_id);
        setCampaignJob(next);
        updateOperation(operationId, { title: campaignOperationTitle(next.phase), phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, 'Sesion completada');
            const sessionResult = next.result_summary as unknown as StudioCampaignSessionResult;
            const examples = await api.examples(sessionResult.capture_id).catch(() => []);
            const eligible = examples.filter(isDatasetIncludable).length;
            const capture = await api.getCapture(sessionResult.capture_id).catch(() => null);
            const freshLegacy = await api.legacyCaptures().catch(() => null);
            const row = freshLegacy?.captures.find((r) => r.capture_id === sessionResult.capture_id);
            // Deduplicated by capture_id (see useRealCaptures' identical
            // guard) -- a real B200 session always mints a fresh capture_id,
            // but never trust that alone.
            setCampaignSessions((prev) => prev.some((s) => s.capture_id === sessionResult.capture_id) ? prev : [...prev, {
              session_index: prev.length + 1, capture_id: sessionResult.capture_id, session_id: sessionResult.session_id,
              condition_label: sessionResult.condition_label,
              capture_purpose: sessionResult.capture_purpose || 'TARGET_DEVICE_ON', target_state: sessionResult.target_state,
              eligible_examples: eligible, total_examples: examples.length,
              discontinuities: Number(capture?.discontinuities ?? 0), acquisition_quality: capture?.acquisition_quality,
              capture_type_label: row?.capture_type_label, capture_decision: row?.capture_decision,
              device_label: row?.device_label,
              started_at_utc: String(capture?.created_at ?? new Date().toISOString()),
            }]);
            setCaptureIds((prev) => prev.includes(sessionResult.capture_id) ? prev : [...prev, sessionResult.capture_id]);
            setDataSource('real');
            setResult(null);
            setJob(null);
            // A new real capture just finished -- the "capturas ya
            // existentes" picker must show it without a manual page reload.
            // Best-effort: never let a refresh failure break the session
            // that just genuinely succeeded.
            if (freshLegacy) setLegacy(freshLegacy);
          } else {
            failOperation(operationId, next.error || 'La sesion de captura fallo');
            const errorText = next.error || 'La sesion de captura fallo de forma inesperada.';
            setError(errorText);
            setCampaignSessions((prev) => [...prev, {
              session_index: prev.length + 1, capture_id: '', session_id: '', condition_label: campaignConditionLabel,
              capture_purpose: capturePurpose || 'TARGET_DEVICE_ON',
              eligible_examples: 0, total_examples: 0, discontinuities: 0, started_at_utc: new Date().toISOString(), error: errorText,
            }]);
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignJob?.job_id, campaignJob?.state]);

  // --- Step 4: feasibility preview (best-effort, dataset may not exist yet) ---
  const [feasibilityPreview, setFeasibilityPreview] = useState<StudioFeasibility | null>(null);
  const [taskRecommendation, setTaskRecommendation] = useState<StudioTaskRecommendation | null>(null);
  const [recommending, setRecommending] = useState(false);

  // An operator with no RF-fingerprinting background has no way to know
  // e.g. that one physical unit rules out "identificar unidades del mismo
  // modelo" (needs two) -- recommend the best-fitting task automatically
  // instead of leaving the default (SAME_MODEL_UNIT_IDENTIFICATION)
  // selected regardless of what was actually captured.
  useEffect(() => {
    const stepTwoIsDone = captureIds.length > 0 && dataSource !== null;
    if (!stepTwoIsDone) { setTaskRecommendation(null); return; }
    let cancelled = false;
    (async () => {
      setRecommending(true);
      try {
        const previewDatasetId = await ensurePreviewDataset(projectId, campaignId, captureIds);
        const recommendation = await api.taskRecommendation(previewDatasetId, '0.0.0');
        if (cancelled) return;
        setTaskRecommendation(recommendation);
        setScientificTask(recommendation.recommended_task);
        setFeasibilityPreview(recommendation.candidates.find((c) => c.scientific_task === recommendation.recommended_task) ?? null);
      } catch {
        // Best-effort only -- the operator can still pick a task manually
        // and press "Comprobar si hay datos suficientes" themselves.
      } finally {
        if (!cancelled) setRecommending(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captureIds.length, dataSource]);

  // Changing objetivo AFTER captures already exist under the current
  // campaign must never silently reinterpret them as evidence for a
  // different question -- starts a genuinely new campaign version instead
  // (captures themselves are never deleted, only the in-progress selection).
  const changeScientificTask = (newTask: string) => {
    if (newTask === scientificTask) return;
    if (step3Done) {
      if (!window.confirm('Cambiar el objetivo despues de usar capturas inicia una nueva version de la campana: la seleccion actual se borra (las capturas grabadas no se eliminan, pero hay que volver a elegirlas). Continuar?')) return;
      const nextVersion = campaignVersion + 1;
      setCampaignVersion(nextVersion);
      setCampaignId((prev) => `${prev.replace(/-v\d+$/, '')}-v${nextVersion}`);
      setCaptureIds([]);
      setDataSource(null);
      setSelectedLegacyIds([]);
      setCampaignSessions([]);
      setResult(null);
      setJob(null);
    }
    setScientificTask(newTask);
    setFeasibilityPreview(taskRecommendation?.candidates.find((c) => c.scientific_task === newTask) ?? null);
    setTrainingPreview(null);
  };

  // --- Step 5: review before training ---
  // The reviewer's explicit demand: TRAIN/VALIDATION/TEST classes, sessions
  // per class, examples per class and capture_ids actually used must be
  // shown -- and "Preparar dataset y entrenar" must only be enabled once
  // that review is coherent (>=2 real classes in TRAIN, i.e. split_status
  // READY) -- never left to train silently on a single-class TRAIN split.
  const [trainingPreview, setTrainingPreview] = useState<StudioTrainingPreview | null>(null);
  // Purely informational (never a gate): channel/day/session/unit balance,
  // so a lopsided capture protocol (everything on one channel, all in one
  // afternoon) is visible before training instead of hiding behind an
  // aggregate accuracy number.
  const [datasetComposition, setDatasetComposition] = useState<StudioDatasetCompositionReport | null>(null);
  const [datasetLabelProvenancePreview, setDatasetLabelProvenancePreview] = useState<StudioLabelProvenanceReport | null>(null);
  // Extracted from reviewDataset() (not wrapped in its own run()) so
  // resolveDuplicatesAndReview can await it directly -- nesting two run()
  // calls would let the inner one's own finally clear `busy` before the
  // outer action truly finishes (same reasoning as retrainFromTrainingRun).
  const doReviewDataset = async () => {
    setTrainingPreview(null);
    setDatasetComposition(null);
    setDatasetLabelProvenancePreview(null);
    const previewDatasetId = await ensurePreviewDataset(projectId, campaignId, captureIds);
    await api.buildSplit(previewDatasetId, '0.0.0', scientificTask);
    const preview = await api.trainingPreview(previewDatasetId, '0.0.0', scientificTask);
    setTrainingPreview(preview);
    const composition = await api.datasetComposition(previewDatasetId, '0.0.0').catch(() => null);
    setDatasetComposition(composition);
    const provenance = await api.labelProvenance(previewDatasetId, '0.0.0').catch(() => null);
    setDatasetLabelProvenancePreview(provenance);
  };
  const reviewDataset = () => run('review-dataset', doReviewDataset);

  // UI-reachable fix for a quality gate blocked on exact duplicates or
  // sample overlap -- real request: any future occurrence of this class of
  // error must be solvable from the UI, not just diagnosable. Quarantines
  // exactly the redundant/overlapping examples via a deterministic backend
  // rule (never a guess at which decode is "better"), then re-runs the
  // review so the gate re-evaluates against the now-fixed evidence.
  const [resolveDuplicatesSummary, setResolveDuplicatesSummary] = useState<{ quarantined_example_ids: string[]; captures_updated: string[] } | null>(null);
  const resolveDuplicatesAndReview = () => run('resolve-duplicates', async () => {
    setResolveDuplicatesSummary(null);
    const summary = await api.resolveDatasetDuplicates(captureIds);
    setResolveDuplicatesSummary(summary);
    await doReviewDataset();
  });

  // --- Step 5 action ---
  const startPrepareAndTrain = () => run('prepare-and-train', async () => {
    setResult(null);
    setFeasibilityPreview(null);
    const startedJob = await api.prepareAndTrain({
      capture_ids: captureIds, project_id: projectId, campaign_id: campaignId, scientific_task: scientificTask,
      dataset_id: `${projectId}-${scientificTask}-DS`.replace(/[^A-Za-z0-9._-]/g, ''), speed_profile: speedProfile,
    });
    setJob(startedJob);
  });

  useEffect(() => {
    if (!job || JOB_TERMINAL.has(job.state)) return;
    const operationId = `ble-rffi-studio-guided-${job.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'PREPARANDO DATASET Y ENTRENANDO', phase: job.phase || 'Iniciando', progressPercent: (job.overall_progress || 0) * 100, target: scientificTask, detail: job.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(job.job_id);
        setJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, next.result_summary?.stopped_at ? 'Detenido con explicacion' : 'Completado');
            setResult((next.result_summary as unknown as StudioPrepareAndTrainSummary) ?? null);
            await refreshStatusBlock();
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
            setError(next.error || 'El proceso fallo de forma inesperada.');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.state]);

  useEffect(() => {
    if (!scrubJob || JOB_TERMINAL.has(scrubJob.state)) return;
    const operationId = `ble-rffi-studio-scrub-${scrubJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'DEPURANDO FONDO CONTAMINADO', phase: scrubJob.phase || 'Iniciando', progressPercent: (scrubJob.overall_progress || 0) * 100, target: scrubUnitId, detail: scrubJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(scrubJob.job_id);
        setScrubJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, 'Depuracion completada');
            await Promise.all([refreshStatusBlock(), refreshDatasets()]);
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
            setError(next.error || 'El proceso fallo de forma inesperada.');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrubJob?.job_id, scrubJob?.state]);

  const scrubSummary = scrubJob?.result_summary as
    | {
        stopped_at?: string | null; stopped_reason?: string | null;
        scrubbed_captures?: Array<{
          skipped: boolean; reason?: string; source_capture_id: string; new_capture_id?: string;
          windows_removed?: number; windows_without_donor?: [number, number][]; samples_replaced?: number;
          residual_examples?: number; verified?: boolean;
        }>;
        original?: { dataset_id: string | null; stopped_reason?: string | null; final_test_evaluation?: {
          accuracy?: number; balanced_accuracy?: number; macro_f1?: number;
          precision_per_class?: Record<string, number>; recall_per_class?: Record<string, number>;
        } | null; exported_bundles?: Array<{ bundle_id: string; model_type: string; approval_status: string | null; error?: string }> };
        scrubbed?: { dataset_id: string | null; stopped_reason?: string | null; final_test_evaluation?: {
          accuracy?: number; balanced_accuracy?: number; macro_f1?: number;
          precision_per_class?: Record<string, number>; recall_per_class?: Record<string, number>;
        } | null; exported_bundles?: Array<{ bundle_id: string; model_type: string; approval_status: string | null; error?: string }> };
      }
    | undefined;

  useEffect(() => {
    if (!trainSvcJob || JOB_TERMINAL.has(trainSvcJob.state)) return;
    const operationId = `ble-rffi-studio-train-svc-${trainSvcJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'SERVICIO DE ENTRENAMIENTO', phase: trainSvcJob.phase || 'Iniciando', progressPercent: (trainSvcJob.overall_progress || 0) * 100, target: Array.from(trainSvcDatasetKeys).join(' + '), detail: trainSvcJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(trainSvcJob.job_id);
        setTrainSvcJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, 'Entrenamiento completado');
            await refreshStatusBlock();
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
            setError(next.error || 'El proceso fallo de forma inesperada.');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trainSvcJob?.job_id, trainSvcJob?.state]);

  const trainSvcSummary = trainSvcJob?.result_summary as
    | {
        run_name?: string | null; stopped_at?: string | null; stopped_reason?: string | null;
        recommended_training_run_id?: string | null; recommended_reason?: string | null;
        final_test_evaluation?: {
          accuracy?: number; balanced_accuracy?: number; macro_f1?: number;
          precision_per_class?: Record<string, number>; recall_per_class?: Record<string, number>;
        } | null;
        trained_models?: Array<{ training_run_id: string; model_type: string; composite_score: number }>;
        skipped_models?: Array<{ model_type: string; reason: string }>;
        exported_bundles?: Array<{ bundle_id: string; model_type: string; training_run_id: string; approval_status: string | null; error?: string }>;
      }
    | undefined;

  // Training Service catalog: groups every TrainingRun whose campaign_id was
  // generated by train_selected_models() (prefix "TRAIN-") -- each group is
  // one past run of this service, showing the device(s) (via
  // datasetPhysicalUnits) and which models were trained/exported for it.
  const trainSvcCatalog = (() => {
    const groups: Record<string, { runs: StudioTrainingRun[]; datasetKey: string }> = {};
    for (const r of allTrainingRuns) {
      const campaignId = r.campaign_id || '';
      if (!campaignId.startsWith('TRAIN-')) continue;
      const key = `${r.dataset_id}/${r.dataset_version}`;
      if (!groups[campaignId]) groups[campaignId] = { runs: [], datasetKey: key };
      groups[campaignId].runs.push(r);
    }
    return Object.entries(groups).sort(([a], [b]) => b.localeCompare(a));
  })();

  // --- Step 6 actions ---
  // Exports ANY trained candidate, independently -- exporting one never
  // removes the option to export another (per-training_run_id state, not a
  // single global "the" exported bundle).
  const exportResultModel = (trainingRunId: string) => run(`export-result-${trainingRunId}`, async () => {
    const targetBundleId = resultBundleIds[trainingRunId] || `${trainingRunId}-bundle`;
    const exported = await api.exportBundle(trainingRunId, {
      bundle_id: targetBundleId, acceptance_criteria: { min_test_accuracy: 0.5 },
      model_card_text: `# ${targetBundleId}\nExportado desde el modo guiado de BLE-RFFI Studio (datos reales B200).`,
    });
    setResultExported((prev) => ({ ...prev, [trainingRunId]: exported.bundle }));
    await refreshStatusBlock();
  });

  const approveResultModel = (trainingRunId: string) => run(`approve-result-${trainingRunId}`, async () => {
    const bundle = resultExported[trainingRunId];
    if (!bundle) return;
    const approved = await api.approveBundle(bundle.bundle_id);
    setResultExported((prev) => ({ ...prev, [trainingRunId]: approved }));
    await refreshStatusBlock();
  });

  // Explicit, audited opt-in: TEST-evaluate a NON-recommended candidate
  // anyway. Deliberately breaks "TEST evaluated exactly once" -- confirmed
  // via window.confirm (same pattern as deleteCapture's irreversible-action
  // guard) since this is a permanent, real statistical caveat, not cosmetic.
  const optInTestEvalForResultModel = (trainingRunId: string) => run(`test-eval-result-${trainingRunId}`, async () => {
    if (!window.confirm(
      'Vas a evaluar este modelo (NO el recomendado) sobre el conjunto TEST para poder aprobarlo en Live Monitor. '
      + 'Esto rompe deliberadamente la garantia de "el TEST se evalua una sola vez" -- es un cambio permanente, '
      + 'pensado solo para comparar varios modelos de forma experimental y practica, nunca para elegir el modelo '
      + '"real" a partir de varias miradas al conjunto de prueba. ¿Continuar?'
    )) return;
    const evalResult = await api.evaluateOnTestOptIn(trainingRunId);
    setResultTestEvalProvenance((prev) => ({ ...prev, [trainingRunId]: evalResult.test_evaluation_provenance || 'OPT_IN_MULTI_CANDIDATE_COMPARISON' }));
  });

  // Shared export cell for both Step 6 tables (accepted-with-recommendation
  // and NO_MODEL_ACCEPTED's rejected-candidates table) -- every row gets its
  // own independent export/approve state, so exporting one model never
  // hides the option to export another.
  // approval_status vocabulary shown here, kept deliberately distinct:
  //   TEST_NOT_EXECUTED -- every other gate passed; the ONLY gap is that
  //     this candidate has no TEST evaluation yet (normal/expected for a
  //     non-recommended model). Never styled as a failure.
  //   REJECTED -- a gate was actually checked and failed (bad data, TEST
  //     accuracy measured and below the floor, etc.). A real problem.
  //   EVALUATED -- passed every gate, awaiting the separate human sign-off.
  //   APPROVED_FOR_LIVE_PILOT -- that sign-off happened; live in Live Monitor.
  const BUNDLE_STATUS_STYLE: Record<string, string> = {
    REJECTED: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
    TEST_NOT_EXECUTED: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    DRAFT: 'border-slate-700 bg-slate-800 text-slate-300',
  };
  const BUNDLE_STATUS_TEXT: Record<string, string> = {
    REJECTED: 'RECHAZADO',
    TEST_NOT_EXECUTED: 'SIN EVALUAR EN TEST',
    EVALUATED: 'EVALUADO',
    SYNTHETIC_PIPELINE_VERIFIED: 'PIPELINE SINTETICO VERIFICADO',
    APPROVED_FOR_LIVE_PILOT: 'APROBADO PARA LIVE MONITOR',
    DRAFT: 'BORRADOR',
  };
  const renderResultExportCell = (trainingRunId: string, hasOwnTestEvaluation: boolean) => {
    const bundle = resultExported[trainingRunId];
    const provenance = resultTestEvalProvenance[trainingRunId];
    const canOptInTest = !hasOwnTestEvaluation && provenance !== 'OPT_IN_MULTI_CANDIDATE_COMPARISON';
    if (bundle) {
      return (
        <div className="flex flex-col items-start gap-1">
          <div className={`rounded border px-2 py-0.5 ${BUNDLE_STATUS_STYLE[bundle.approval_status] || 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'}`}>
            {bundle.bundle_id} ({BUNDLE_STATUS_TEXT[bundle.approval_status] || bundle.approval_status})
          </div>
          {bundle.approval_status === 'TEST_NOT_EXECUTED' && (
            <div className="text-[10px] text-amber-300">
              No es un rechazo: entreno bien y paso el resto de criterios, solo falta evaluarlo sobre TEST para poder aprobarlo.
            </div>
          )}
          {bundle.approval_status === 'REJECTED' && (
            <div className="text-[10px] text-rose-300">No cumplio un criterio real de aceptacion (ver motivo al exportar).</div>
          )}
          {bundle.approval_status === 'EVALUATED' && (
            <button className="text-cyan-300 underline" disabled={!!busy} onClick={() => approveResultModel(trainingRunId)}>Aprobar para Live Monitor</button>
          )}
          {bundle.approval_status === 'APPROVED_FOR_LIVE_PILOT' && <span className="text-emerald-300">Disponible en Live Monitor</span>}
          {bundle.approval_status === 'TEST_NOT_EXECUTED' && canOptInTest && (
            <button className="text-[10px] text-amber-300 underline" disabled={!!busy} onClick={() => optInTestEvalForResultModel(trainingRunId)}>
              Evaluar sobre TEST (opcional) para poder aprobarlo
            </button>
          )}
          {bundle.approval_status === 'TEST_NOT_EXECUTED' && provenance === 'OPT_IN_MULTI_CANDIDATE_COMPARISON' && (
            <button className="text-[10px] text-emerald-300 underline" disabled={!!busy} onClick={() => exportResultModel(trainingRunId)}>
              Ya evaluado sobre TEST -- reexportar para actualizar
            </button>
          )}
          {bundle.test_evaluation_provenance === 'OPT_IN_MULTI_CANDIDATE_COMPARISON' && (
            <span className="text-amber-300">TEST evaluado por comparacion multiple, no por la garantia de seleccion unica.</span>
          )}
        </div>
      );
    }
    return (
      <div className="flex flex-col items-start gap-1">
        <div className="flex items-end gap-1">
          <input
            className={`${inputClass} h-7 w-40`} placeholder="bundle_id"
            value={resultBundleIds[trainingRunId] ?? `${trainingRunId}-bundle`}
            onChange={(e) => setResultBundleIds((prev) => ({ ...prev, [trainingRunId]: e.target.value }))}
          />
          <button className={secondaryButtonClass} disabled={!!busy} onClick={() => exportResultModel(trainingRunId)}>Exportar</button>
        </div>
        {canOptInTest && (
          <button className="text-[10px] text-amber-300 underline" disabled={!!busy} onClick={() => optInTestEvalForResultModel(trainingRunId)}>
            Evaluar sobre TEST (opcional) para poder aprobarlo
          </button>
        )}
        {provenance === 'OPT_IN_MULTI_CANDIDATE_COMPARISON' && (
          <span className="text-[10px] text-emerald-300">Evaluado sobre TEST (comparacion multiple) -- ya se puede exportar y aprobar.</span>
        )}
      </div>
    );
  };

  // Benchmark panel's "Reentrenar (mismas capturas)": jumps straight to
  // Step 3's capture picker already populated and launched, skipping Steps
  // 1-2 entirely -- real request ("sin tener que pasar por etapas
  // anteriores"). Not wrapped in run(): useRealCaptures() already manages
  // its own busy/error state, and nesting two run() calls would let the
  // inner one's `finally` clear `busy` before this outer action truly
  // finishes.
  const retrainFromTrainingRun = async (trainingRunId: string) => {
    let reference: Awaited<ReturnType<typeof api.retrainReferenceFromTrainingRun>>;
    try {
      reference = await api.retrainReferenceFromTrainingRun(trainingRunId);
    } catch (e) {
      setError(describeApiError(e));
      return;
    }
    setProjectId(reference.project_id);
    setCampaignId(reference.campaign_id);
    setScientificTask(reference.scientific_task);
    setCampaignBleChannel(reference.ble_channel);
    await useRealCaptures(reference.capture_ids);
    document.getElementById('step-3-launch')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  // TARGET_VS_BACKGROUND/UNKNOWN_DEVICE_REJECTION never mean the same thing
  // as SAME_MODEL_UNIT_IDENTIFICATION/MULTI_DEVICE_CLASSIFICATION -- grouping
  // them together as "IDENTITY" here is purely a UI bucket for the task
  // filter/grouping, never used to compare a raw score across tasks.
  const benchmarkTaskGroup = (task: string): 'TARGET_VS_BACKGROUND' | 'IDENTITY' | 'UNKNOWN_DEVICE_REJECTION' =>
    task === 'TARGET_VS_BACKGROUND' ? 'TARGET_VS_BACKGROUND'
      : task === 'UNKNOWN_DEVICE_REJECTION' ? 'UNKNOWN_DEVICE_REJECTION'
      : 'IDENTITY';

  // Runs a REAL, sequential VALIDATION re-evaluation over the given
  // training_run_ids (never cached/simulated) -- this IS "lanzar la
  // comparacion", not just displaying whatever happened to be cached from
  // whenever each model last trained.
  const compareModels = async (trainingRunIds: string[]) => {
    if (!trainingRunIds.length) return;
    setBenchmarkComparing(true);
    try {
      for (let i = 0; i < trainingRunIds.length; i++) {
        const id = trainingRunIds[i];
        setBenchmarkProgress(`Verificando ${i + 1}/${trainingRunIds.length}: ${id}`);
        try {
          const fresh = await api.evaluate(id);
          setDirectEvaluations((prev) => ({ ...prev, [id]: fresh }));
        } catch (e) {
          setError(describeApiError(e));
        }
      }
    } finally {
      setBenchmarkComparing(false);
      setBenchmarkProgress('');
    }
  };

  const step1Done = capturePurpose !== null;
  const step2Done = step1Done && (
    capturePurpose === 'TARGET_DEVICE_ON' ? !!selectedUnitId
    : capturePurpose === 'BACKGROUND_TARGET_OFF' ? operatorConfirmedTargetAbsent
    : true // BACKGROUND_GENERAL/UNKNOWN_DEVICE_COLLECTION have no specific target to confirm
  );
  const step3Done = captureIds.length > 0 && dataSource !== null;
  const step4Done = step3Done && !!scientificTask;
  const step5Done = !!result;
  const jobRunning = !!job && !JOB_TERMINAL.has(job.state);

  const canLaunchLiveSession = step2Done && !!campaignDeviceStatus && campaignDeviceStatus.status === 'AVAILABLE';
  const canUseExistingCaptures = step2Done && selectedLegacyIds.length > 0;

  const visibleCaptureRows = [...(legacy?.captures ?? [])]
    .filter((c) => matchesCaptureFilter(c, captureListFilter))
    .sort((a, b) => compareCaptureRows(a, b, captureSortKey));

  // What the operator has actually CHECKED so far -- before they click "Usar
  // captura(s) real(es)" this is the only feedback available on whether
  // there's enough of each kind, since step4Done's own feasibility check
  // only runs after that click loads captureIds.
  const selectedRows = (legacy?.captures ?? []).filter((c) => selectedLegacyIds.includes(c.capture_id));
  const selectedDeviceCount = selectedRows.filter((c) => c.capture_type_label === CAPTURE_TYPE_DEVICE).length;
  const selectedEnvironmentCount = selectedRows.filter((c) => c.capture_type_label === CAPTURE_TYPE_ENVIRONMENT_DECLARED || c.capture_type_label === CAPTURE_TYPE_ENVIRONMENT_GENERAL).length;
  const selectedEligibleCount = selectedRows.filter((c) => c.capture_decision === 'ELIGIBLE_AS_POSITIVE' || c.capture_decision === 'ELIGIBLE_AS_BACKGROUND').length;

  if (backendError) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          <div className="font-semibold">No se pudo acceder al servicio BLE-RFFI Studio.</div>
          <div className="mt-1">{backendError}</div>
          <div className="mt-2 text-xs text-rose-300">Verifica que el backend este en ejecucion (puerto 8000) y vuelve a cargar la pagina.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 p-4 text-slate-100">
      <PipelineStatusBlock bundles={bundles} trainingRuns={allTrainingRuns} />
      {error && <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}

      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setDirectAccessOpen((v) => !v)}>
          <span className="text-sm font-semibold text-slate-100">Acceso directo: ver y exportar modelos ya entrenados ({allTrainingRuns.length})</span>
          <ChevronRight className={`h-4 w-4 transition-transform ${directAccessOpen ? 'rotate-90' : ''}`} />
        </button>
        {directAccessOpen && (
          <div className="mt-3 space-y-2">
            <div className="text-xs text-slate-400">
              Salta directamente a cualquier modelo ya entrenado (de esta sesion o de una anterior) sin repetir los Pasos 1-5 -- util si solo quieres exportar algo que ya entrenaste antes.
            </div>
            <div className="rounded-md border border-slate-800 bg-slate-900/40 p-2 text-[11px] text-slate-400">
              <span className="font-semibold text-slate-300">Los modelos "de una sola clase" (100% falso, siempre rechazados) o que fallaron al entrenar son restos de ANTES de una correccion ya aplicada al sistema</span>{' '}
              (SplitBuilder ahora exige al menos 2 clases reales en entrenamiento -- ver el README del modulo) -- nunca van a volver a producirse.
              Ninguno de los dos tiene nada exportable (por eso intentarlo daba un 404 confuso). Por eso se ocultan por defecto abajo en vez de hacerte descubrir cada uno a mano.
              {directEvaluationsLoading && <span className="ml-1 text-cyan-300">Analizando entrenamientos...</span>}
            </div>
            <label className="flex items-center gap-2 text-[11px] text-slate-400">
              <input type="checkbox" checked={directShowDegenerate} onChange={(e) => setDirectShowDegenerate(e.target.checked)} />
              Mostrar tambien los descartados (una sola clase o fallidos) ({allTrainingRuns.filter(isJunkRun).length})
            </label>
            {(() => {
              const visibleRuns = allTrainingRuns.filter((r) => directShowDegenerate || !isJunkRun(r));
              const allSelected = visibleRuns.length > 0 && visibleRuns.every((r) => selectedRunIds.has(r.training_run_id));
              const deleteRuns = (ids: string[]) => run('delete-training-runs', async () => {
                if (!ids.length) return;
                if (!window.confirm(`Borrar ${ids.length} entrenamiento(s)? Los bundles ya exportados de estos entrenamientos siguen intactos (guardan su propia copia); solo se pierde la posibilidad de reexportar exactamente el mismo desde aqui. No se puede deshacer.`)) return;
                await Promise.all(ids.map((id) => api.deleteTrainingRun(id).catch(() => null)));
                setSelectedRunIds(new Set());
                await refreshStatusBlock();
              });
              return (
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                  <label className="flex items-center gap-1">
                    <input
                      type="checkbox" checked={allSelected}
                      onChange={(e) => setSelectedRunIds(e.target.checked ? new Set(visibleRuns.map((r) => r.training_run_id)) : new Set())}
                    />
                    Seleccionar todo lo visible ({visibleRuns.length})
                  </label>
                  <button
                    className="rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                    disabled={!!busy || selectedRunIds.size === 0}
                    onClick={() => deleteRuns(Array.from(selectedRunIds))}
                  >
                    Eliminar seleccionados ({selectedRunIds.size})
                  </button>
                  <button
                    className="rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                    disabled={!!busy || !visibleRuns.length}
                    onClick={() => deleteRuns(visibleRuns.map((r) => r.training_run_id))}
                  >
                    Eliminar todos los visibles ({visibleRuns.length})
                  </button>
                </div>
              );
            })()}
            <div className="max-h-96 overflow-y-auto rounded-md border border-slate-800">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-900 text-slate-500">
                  <tr>
                    <th className="p-1"></th><th className="p-1"></th><th className="p-1">training_run_id</th><th className="p-1">Modelo</th>
                    <th className="p-1">Objetivo</th><th className="p-1">Dispositivo</th><th className="p-1">Entrenado</th>
                    <th className="p-1">Origen</th><th className="p-1">Estado</th>
                    <th className="p-1">Puntuacion (VALIDATION)</th>
                  </tr>
                </thead>
                <tbody>
                  {allTrainingRuns.filter((r) => directShowDegenerate || !isJunkRun(r)).map((run_) => {
                    const expanded = directExpandedId === run_.training_run_id;
                    const evaluation = directEvaluations[run_.training_run_id];
                    const exported = directExportedBundles[run_.training_run_id];
                    const gateReasons = directGateReasons[run_.training_run_id] || [];
                    const physicalUnits = datasetPhysicalUnits[`${run_.dataset_id}/${run_.dataset_version}`];
                    const trainedAt = run_.completed_at || run_.started_at;
                    // Accuracy on VALIDATION -- the same split prepare_and_train's own
                    // model-selection comparison scores on, never TEST (comparing
                    // multiple candidates on TEST would leak the held-out set). This is
                    // the raw accuracy, not the wizard's composite_score (which also
                    // folds in balanced accuracy, unknown-rejection capability, latency
                    // and model size, and is only ever computed transiently during one
                    // specific prepare_and_train call, never persisted per training_run_id
                    // for retrieval afterward) -- labeled honestly as accuracy, not
                    // re-implementing that scoring formula a second time in the frontend.
                    const validationAccuracy = run_.metrics?.VALIDATION?.accuracy;
                    const singleClass = isSingleClassRun(run_.training_run_id);
                    return (
                      <Fragment key={run_.training_run_id}>
                        <tr className="cursor-pointer border-t border-slate-800 hover:bg-slate-900" onClick={() => toggleDirectExpand(run_.training_run_id)}>
                          <td className="p-1" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox" checked={selectedRunIds.has(run_.training_run_id)}
                              onChange={(e) => setSelectedRunIds((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(run_.training_run_id); else next.delete(run_.training_run_id);
                                return next;
                              })}
                            />
                          </td>
                          <td className="p-1"><ChevronRight className={`h-3 w-3 transition-transform ${expanded ? 'rotate-90' : ''}`} /></td>
                          <td className="p-1 font-mono text-slate-400">{run_.training_run_id}</td>
                          <td className="p-1">{run_.model_type}</td>
                          <td className="p-1">{run_.scientific_task}</td>
                          <td className="p-1">{physicalUnits ? (physicalUnits.join(' + ') || 'General') : '...'}</td>
                          <td className="p-1 text-cyan-300">{trainedAt ? new Date(trainedAt).toLocaleString() : 'N/D'}</td>
                          <td className="p-1">
                            {run_.data_origin === 'REAL_B200'
                              ? <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200">REAL</span>
                              : <span className="rounded-full border border-slate-600 bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">SINTETICO</span>}
                          </td>
                          <td className="p-1">{run_.status}</td>
                          <td className="p-1">
                            {singleClass ? (
                              <span title="Una sola clase real en VALIDATION -- el porcentaje es trivial, no una senal de calidad." className="text-amber-400">
                                {typeof validationAccuracy === 'number' ? `${(validationAccuracy * 100).toFixed(1)}%` : 'N/D'} (1 clase)
                              </span>
                            ) : (
                              typeof validationAccuracy === 'number' ? `${(validationAccuracy * 100).toFixed(1)}%` : (directEvaluationsLoading ? '...' : 'N/D')
                            )}
                          </td>
                        </tr>
                        {expanded && (
                          <tr className="border-t border-slate-800 bg-slate-900/40">
                            <td className="p-2" colSpan={10}>
                              <button
                                className="mb-2 rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-[11px] text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                                disabled={!!busy}
                                onClick={() => run('delete-training-run', async () => {
                                  if (!window.confirm(`Borrar el entrenamiento ${run_.training_run_id}? Un bundle ya exportado de el sigue intacto. No se puede deshacer.`)) return;
                                  await api.deleteTrainingRun(run_.training_run_id);
                                  await refreshStatusBlock();
                                })}
                              >
                                Eliminar este entrenamiento
                              </button>
                              {evaluation ? (
                                <>
                                  {(evaluation.evaluation_report.VALIDATION?.evaluation_validity === 'INVALID_SINGLE_CLASS_EVALUATION'
                                    // Fallback for evaluations cached to disk BEFORE evaluation_validity existed --
                                    // the confusion_matrix's own key count is always a reliable signal regardless
                                    // of when this particular evaluation_report.json was last written.
                                    || Object.keys(evaluation.evaluation_report.VALIDATION?.confusion_matrix || {}).length < 2) && (
                                    <div className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-100">
                                      <div className="font-semibold">La puntuacion de arriba NO es real.</div>
                                      <div className="mt-0.5 opacity-90">
                                        Este entrenamiento solo vio UNA clase en VALIDATION (ej. nunca hubo sesiones de entorno reales
                                        disponibles en ese momento) -- un modelo que siempre adivina la unica clase que existe acierta
                                        el 100% trivialmente, eso no prueba que distinga nada. Por eso el sistema lo rechaza al exportar
                                        (ver mas abajo), aunque la tabla muestre un porcentaje alto.
                                      </div>
                                    </div>
                                  )}
                                  <details className="mb-2 text-slate-300"><summary className="cursor-pointer">Evaluacion (VALIDATION{evaluation.evaluation_report.TEST ? ' + TEST' : ''})</summary>
                                    <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{JSON.stringify(evaluation.evaluation_report, null, 2)}</pre>
                                  </details>
                                </>
                              ) : <div className="mb-2 text-slate-500">Sin evaluacion guardada todavia para este training_run.</div>}
                              {exported ? (
                                <div className={`rounded-md border p-2 ${BUNDLE_STATUS_STYLE[exported.approval_status] || 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'}`}>
                                  <div>Exportado: {exported.bundle_id} (estado: {BUNDLE_STATUS_TEXT[exported.approval_status] || exported.approval_status})</div>
                                  {exported.approval_status === 'TEST_NOT_EXECUTED' && (
                                    <div className="mt-1">
                                      <div className="font-semibold">No es un rechazo -- entreno bien y paso el resto de criterios:</div>
                                      {gateReasons.length ? (
                                        <ul className="mt-0.5 list-disc pl-4 opacity-90">
                                          {gateReasons.map((reason, i) => <li key={i}>{reason}</li>)}
                                        </ul>
                                      ) : (
                                        <div className="mt-1 opacity-70">Falta evaluarlo sobre TEST para poder aprobarlo (normal para un candidato no recomendado -- TEST se reserva para el modelo seleccionado).</div>
                                      )}
                                      <div className="mt-1 opacity-70">
                                        Usa "Evaluar sobre TEST" en la tabla de Paso 6 (o el opt-in equivalente) y luego reexporta para que este bundle pueda aprobarse.
                                      </div>
                                    </div>
                                  )}
                                  {exported.approval_status === 'REJECTED' && (
                                    <div className="mt-1">
                                      <div className="font-semibold">Rechazado automaticamente por:</div>
                                      {gateReasons.length ? (
                                        <ul className="mt-0.5 list-disc pl-4 opacity-90">
                                          {gateReasons.map((reason, i) => <li key={i}>{reason}</li>)}
                                        </ul>
                                      ) : (
                                        <div className="mt-1">
                                          <div className="opacity-70">Motivo no disponible (bundle exportado antes de esta sesion -- los motivos solo se guardan al exportar, no despues).</div>
                                          <button className="mt-1 text-cyan-300 underline" onClick={() => exportDirect(run_.training_run_id)}>Reexportar para ver el motivo (mismo resultado, no crea nada nuevo)</button>
                                        </div>
                                      )}
                                      <div className="mt-1 opacity-70">
                                        Esto NO es un error de la interfaz: el bundle SI se exporto (queda guardado), pero el sistema
                                        decidio automaticamente que no cumple la calidad minima para aprobarse para uso en vivo -- por
                                        eso puedes verlo aqui aunque no salga en el desplegable de Live Monitor (que solo muestra APPROVED_FOR_LIVE_PILOT).
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ) : run_.status !== 'COMPLETED' ? (
                                // FAILED runs never produced predictions.json/evaluation_report.json at all --
                                // export_bundle() correctly refuses them (TRAINING_RUN_NOT_EVALUATED_YET,
                                // surfaced as a bare 404), which read as a confusing routing error rather
                                // than "this training run never finished." Show the real reason instead of
                                // offering an export button that can only ever fail.
                                <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-rose-200">
                                  <div className="font-semibold">Este entrenamiento no se completo (estado: {run_.status}) -- no hay nada que exportar.</div>
                                  <div className="mt-1 opacity-90">
                                    {run_.error ? String((run_.error as Record<string, unknown>).error ?? JSON.stringify(run_.error)) : 'Motivo no registrado.'}
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-end gap-2">
                                  <label className="flex flex-col gap-1 text-slate-400">bundle_id
                                    <input
                                      className={inputClass} value={directBundleIds[run_.training_run_id] || ''}
                                      onChange={(e) => setDirectBundleIds((prev) => ({ ...prev, [run_.training_run_id]: e.target.value }))}
                                    />
                                  </label>
                                  <button className={secondaryButtonClass} disabled={!!busy} onClick={() => exportDirect(run_.training_run_id)}>Exportar</button>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setArtifactsOpen((v) => !v)}>
          <span className="text-sm font-semibold text-slate-100">Datasets y modelos exportados: ver y eliminar ({datasets.length} datasets, {bundles.length} bundles)</span>
          <ChevronRight className={`h-4 w-4 transition-transform ${artifactsOpen ? 'rotate-90' : ''}`} />
        </button>
        {artifactsOpen && (
          <div className="mt-3 space-y-5">
            <div>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                <span className="text-xs font-semibold text-slate-200">Datasets ({datasets.length})</span>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox" checked={datasets.length > 0 && datasets.every((d) => selectedDatasetKeys.has(`${d.dataset_id}/${d.dataset_version}`))}
                    onChange={(e) => setSelectedDatasetKeys(e.target.checked ? new Set(datasets.map((d) => `${d.dataset_id}/${d.dataset_version}`)) : new Set())}
                  />
                  Seleccionar todo
                </label>
                <button
                  className="rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={!!busy || selectedDatasetKeys.size === 0}
                  onClick={() => run('delete-datasets', async () => {
                    const keys = Array.from(selectedDatasetKeys);
                    if (!window.confirm(`Borrar ${keys.length} dataset(s) y sus particiones? Las capturas y evidencia originales no se tocan. No se puede deshacer.`)) return;
                    await Promise.all(keys.map((key) => { const [id, ver] = key.split('/'); return api.deleteDataset(id, ver).catch(() => null); }));
                    setSelectedDatasetKeys(new Set());
                    await refreshDatasets();
                  })}
                >
                  Eliminar seleccionados ({selectedDatasetKeys.size})
                </button>
                <button
                  className="rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={!!busy || !datasets.length}
                  onClick={() => run('delete-all-datasets', async () => {
                    if (!window.confirm(`Borrar TODOS los ${datasets.length} datasets y sus particiones? Las capturas y evidencia originales no se tocan. No se puede deshacer.`)) return;
                    await Promise.all(datasets.map((d) => api.deleteDataset(d.dataset_id, d.dataset_version).catch(() => null)));
                    setSelectedDatasetKeys(new Set());
                    await refreshDatasets();
                  })}
                >
                  Eliminar todos
                </button>
              </div>
              <div className="max-h-64 overflow-y-auto rounded-md border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500">
                    <tr><th className="p-1"></th><th className="p-1">dataset_id</th><th className="p-1">version</th><th className="p-1">congelado</th><th className="p-1">ejemplos</th><th className="p-1"></th></tr>
                  </thead>
                  <tbody>
                    {datasets.map((d) => {
                      const key = `${d.dataset_id}/${d.dataset_version}`;
                      return (
                        <tr key={key} className="border-t border-slate-800">
                          <td className="p-1">
                            <input
                              type="checkbox" checked={selectedDatasetKeys.has(key)}
                              onChange={(e) => setSelectedDatasetKeys((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(key); else next.delete(key);
                                return next;
                              })}
                            />
                          </td>
                          <td className="p-1 font-mono text-slate-400">{d.dataset_id}</td>
                          <td className="p-1 font-mono text-slate-400">{d.dataset_version}</td>
                          <td className="p-1">{d.frozen ? 'si' : 'no'}</td>
                          <td className="p-1">{d.example_ids.length}</td>
                          <td className="p-1">
                            <button
                              className="text-rose-300 underline disabled:cursor-not-allowed disabled:opacity-40" disabled={!!busy}
                              onClick={() => run(`delete-dataset-${key}`, async () => {
                                if (!window.confirm(`Borrar el dataset ${key}? No se puede deshacer.`)) return;
                                await api.deleteDataset(d.dataset_id, d.dataset_version);
                                await refreshDatasets();
                              })}
                            >
                              Eliminar
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                <span className="text-xs font-semibold text-slate-200">Modelos exportados / bundles ({bundles.length})</span>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox" checked={bundles.length > 0 && bundles.every((b) => selectedBundleIds.has(b.bundle_id))}
                    onChange={(e) => setSelectedBundleIds(e.target.checked ? new Set(bundles.map((b) => b.bundle_id)) : new Set())}
                  />
                  Seleccionar todo
                </label>
                <button
                  className="rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={!!busy || selectedBundleIds.size === 0}
                  onClick={() => run('delete-bundles', async () => {
                    const ids = Array.from(selectedBundleIds);
                    if (!window.confirm(`Borrar ${ids.length} bundle(s)? Si alguno esta aprobado para Live Monitor, deja de estar disponible en el desplegable. No se puede deshacer.`)) return;
                    await Promise.all(ids.map((id) => api.deleteBundle(id).catch(() => null)));
                    setSelectedBundleIds(new Set());
                    await refreshStatusBlock();
                  })}
                >
                  Eliminar seleccionados ({selectedBundleIds.size})
                </button>
                <button
                  className="rounded-md border border-rose-600/60 bg-rose-600/10 px-2 py-1 text-rose-200 hover:bg-rose-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={!!busy || !bundles.length}
                  onClick={() => run('delete-all-bundles', async () => {
                    if (!window.confirm(`Borrar TODOS los ${bundles.length} bundles? Ninguno seguira disponible en Live Monitor. No se puede deshacer.`)) return;
                    await Promise.all(bundles.map((b) => api.deleteBundle(b.bundle_id).catch(() => null)));
                    setSelectedBundleIds(new Set());
                    await refreshStatusBlock();
                  })}
                >
                  Eliminar todos
                </button>
              </div>
              <div className="max-h-64 overflow-y-auto rounded-md border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500">
                    <tr><th className="p-1"></th><th className="p-1">bundle_id</th><th className="p-1">training_run_id</th><th className="p-1">estado</th><th className="p-1"></th></tr>
                  </thead>
                  <tbody>
                    {bundles.map((b) => (
                      <tr key={b.bundle_id} className="border-t border-slate-800">
                        <td className="p-1">
                          <input
                            type="checkbox" checked={selectedBundleIds.has(b.bundle_id)}
                            onChange={(e) => setSelectedBundleIds((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(b.bundle_id); else next.delete(b.bundle_id);
                              return next;
                            })}
                          />
                        </td>
                        <td className="p-1 font-mono text-slate-400">{b.bundle_id}</td>
                        <td className="p-1 font-mono text-slate-500">{b.training_run_id}</td>
                        <td className="p-1">{BUNDLE_STATUS_TEXT[b.approval_status] || b.approval_status}</td>
                        <td className="p-1">
                          <button
                            className="text-rose-300 underline disabled:cursor-not-allowed disabled:opacity-40" disabled={!!busy}
                            onClick={() => run(`delete-bundle-${b.bundle_id}`, async () => {
                              if (!window.confirm(`Borrar el bundle ${b.bundle_id}? No se puede deshacer.`)) return;
                              await api.deleteBundle(b.bundle_id);
                              await refreshStatusBlock();
                            })}
                          >
                            Eliminar
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setScrubOpen((v) => !v)}>
          <span className="text-sm font-semibold text-slate-100">Depurar fondo contaminado por un dispositivo siempre encendido</span>
          <ChevronRight className={`h-4 w-4 transition-transform ${scrubOpen ? 'rotate-90' : ''}`} />
        </button>
        {scrubOpen && (
          <div className="mt-3 space-y-3 text-xs">
            <p className="text-slate-400">
              Para un dispositivo que nunca esta realmente apagado, sus propias capturas de fondo siempre lo contienen -- TARGET_VS_BACKGROUND nunca ve una ausencia real. Esto detecta esas capturas, elimina las ventanas del paquete de ese dispositivo (sustituidas por ruido real silencioso tomado de la misma grabacion, nunca inventado), y entrena+exporta dos conjuntos de 5 modelos -- uno con el fondo original (contaminado) y otro con el fondo depurado -- para comparar sus metricas TEST reales lado a lado.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
                value={scrubUnitId}
                onChange={(e) => { setScrubUnitId(e.target.value); setScrubCandidates(null); }}
              >
                <option value="">Selecciona un dispositivo...</option>
                {units.map((u) => <option key={u.physical_unit_id} value={u.physical_unit_id}>{u.physical_unit_id}</option>)}
              </select>
              <button
                className="rounded-md border border-slate-600 px-2 py-1 text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!!busy || !scrubUnitId}
                onClick={() => run('scrub-preview', async () => {
                  setScrubCandidates(await api.scrubBackgroundCandidates(scrubUnitId));
                })}
              >
                Detectar capturas contaminadas
              </button>
              <button
                className="rounded-md border border-amber-600/60 bg-amber-600/10 px-2 py-1 text-amber-200 hover:bg-amber-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!!busy || !scrubUnitId || (!!scrubJob && !JOB_TERMINAL.has(scrubJob.state))}
                onClick={() => run('scrub-launch', async () => {
                  const startedJob = await api.scrubBackground(scrubUnitId);
                  setScrubJob(startedJob);
                })}
              >
                Detectar y depurar fondo (un clic)
              </button>
            </div>

            {scrubCandidates && (
              <div className="text-slate-300">
                {scrubCandidates.length === 0
                  ? 'No se encontraron capturas de fondo contaminadas por este dispositivo.'
                  : `${scrubCandidates.length} captura(s) de fondo contaminada(s): ${scrubCandidates.map((c) => c.capture_id).join(', ')}`}
              </div>
            )}

            {scrubJob && (
              <div className="rounded-md border border-slate-700 bg-slate-900 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-100">{scrubUnitId}</span>
                  <span className={scrubJob.state === 'completed' ? 'text-emerald-300' : scrubJob.state === 'failed' ? 'text-rose-300' : 'text-amber-300'}>{scrubJob.state.toUpperCase()}</span>
                  {scrubJob.message && <span className="text-slate-400">{scrubJob.message}</span>}
                </div>
                {scrubJob.state === 'completed' && scrubSummary && (
                  scrubSummary.stopped_reason ? (
                    <div className="text-amber-200">{scrubSummary.stopped_reason}</div>
                  ) : (
                    <>
                      <div className="text-slate-200">
                        Capturas depuradas: {(scrubSummary.scrubbed_captures || []).filter((c) => c.verified).length}/{(scrubSummary.scrubbed_captures || []).length} verificadas sin ejemplos residuales del dispositivo.
                      </div>
                      <table className="w-full text-left text-[11px]">
                        <thead className="text-slate-400">
                          <tr><th className="p-1">captura origen</th><th className="p-1">captura depurada</th><th className="p-1">ventanas borradas</th><th className="p-1">residuales</th><th className="p-1">verificado</th></tr>
                        </thead>
                        <tbody>
                          {(scrubSummary.scrubbed_captures || []).map((c) => (
                            <tr key={c.source_capture_id} className="border-t border-slate-800">
                              <td className="p-1 font-mono">{c.source_capture_id}</td>
                              <td className="p-1 font-mono">{c.new_capture_id || '-'}</td>
                              <td className="p-1">{c.skipped ? c.reason : c.windows_removed}</td>
                              <td className="p-1">{c.residual_examples ?? '-'}</td>
                              <td className="p-1">{c.skipped ? '-' : <span className={c.verified ? 'text-emerald-300' : 'text-rose-300'}>{c.verified ? 'SI' : 'NO'}</span>}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>

                      <div className="grid grid-cols-1 gap-3 pt-2 md:grid-cols-2" style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {([['original', 'Fondo ORIGINAL (contaminado)'], ['scrubbed', 'Fondo DEPURADO']] as const).map(([key, label]) => {
                          const side = scrubSummary[key];
                          const test = side?.final_test_evaluation;
                          return (
                            <div key={key} className="rounded-md border border-slate-800 p-2">
                              <div className="mb-1 font-semibold text-slate-200">{label}</div>
                              {side?.stopped_reason ? (
                                <div className="text-amber-200">{side.stopped_reason}</div>
                              ) : test ? (
                                <div className="space-y-1 font-mono text-slate-300">
                                  <div>macro_f1: {test.macro_f1?.toFixed(3)} · balanced_accuracy: {test.balanced_accuracy?.toFixed(3)} · accuracy: {test.accuracy?.toFixed(3)}</div>
                                  <div>precision(TARGET_DEVICE): {test.precision_per_class?.TARGET_DEVICE?.toFixed(3)} · recall(BACKGROUND_ENVIRONMENT): {test.recall_per_class?.BACKGROUND_ENVIRONMENT?.toFixed(3)}</div>
                                </div>
                              ) : null}
                              {side?.exported_bundles && (
                                <div className="mt-1 text-slate-400">
                                  {side.exported_bundles.filter((b) => b.approval_status === 'APPROVED_FOR_LIVE_PILOT').length}/{side.exported_bundles.length} modelos aprobados para Live Monitor
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </>
                  )
                )}
              </div>
            )}
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setTrainSvcOpen((v) => !v)}>
          <span className="text-sm font-semibold text-slate-100">Servicio de entrenamiento personalizado: elegir dataset y modelos ({trainSvcCatalog.length})</span>
          <ChevronRight className={`h-4 w-4 transition-transform ${trainSvcOpen ? 'rotate-90' : ''}`} />
        </button>
        {trainSvcOpen && (
          <div className="mt-3 space-y-3 text-xs">
            <p className="text-slate-400">
              Elige uno o varios datasets ya construidos y ya etiquetados (por ejemplo, la variante de un dispositivo CON su señal o SIN su señal en el fondo) y que tipos de modelo entrenar. Un solo dataset entrena un detector normal (objetivo vs. entorno). Dos o mas datasets se combinan en un unico modelo que distingue CUAL de esos dispositivos esta presente (nunca los mezcla en una sola clase "cualquiera de estos"). El nombre de la ejecucion se genera solo (fecha, hora y dispositivo(s)); al terminar, todos los modelos elegidos se exportan y aprueban automaticamente para Live Monitor.
            </p>
            <div className="flex flex-wrap items-start gap-6">
              <div className="max-h-40 overflow-y-auto rounded-md border border-slate-700 bg-slate-900 p-2">
                {datasets.map((d) => {
                  const key = `${d.dataset_id}/${d.dataset_version}`;
                  return (
                    <label key={key} className="flex items-center gap-2 whitespace-nowrap py-0.5 text-slate-200">
                      <input
                        type="checkbox"
                        checked={trainSvcDatasetKeys.has(key)}
                        onChange={(e) => setTrainSvcDatasetKeys((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(key); else next.delete(key);
                          return next;
                        })}
                      />
                      <span className="font-mono">{d.dataset_id}</span> ({(d.physical_units || []).join(' + ') || 'General'})
                    </label>
                  );
                })}
              </div>
              <div className="flex flex-wrap gap-3">
                {ALL_MODEL_TYPES.map((mt) => (
                  <label key={mt} className="flex items-center gap-1 text-slate-200">
                    <input
                      type="checkbox"
                      checked={trainSvcModelTypes.has(mt)}
                      onChange={(e) => setTrainSvcModelTypes((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(mt); else next.delete(mt);
                        return next;
                      })}
                    />
                    {mt}
                  </label>
                ))}
              </div>
              {trainSvcDatasetKeys.size >= 2 && (
                <div className="flex items-center gap-2">
                  <label className="text-slate-400">Dataset de entorno compartido (opcional, recomendado):</label>
                  <select
                    className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
                    value={trainSvcBackgroundKey}
                    onChange={(e) => setTrainSvcBackgroundKey(e.target.value)}
                  >
                    <option value="">Usar el fondo propio de cada dataset (por defecto)</option>
                    {datasets.map((d) => {
                      const key = `${d.dataset_id}/${d.dataset_version}`;
                      return <option key={key} value={key}>{d.dataset_id} ({(d.physical_units || []).join(' + ') || 'General'})</option>;
                    })}
                  </select>
                </div>
              )}
              <button
                className="rounded-md border border-emerald-600/60 bg-emerald-600/10 px-2 py-1 text-emerald-200 hover:bg-emerald-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!!busy || trainSvcDatasetKeys.size === 0 || trainSvcModelTypes.size === 0 || (!!trainSvcJob && !JOB_TERMINAL.has(trainSvcJob.state))}
                onClick={() => run('train-svc-launch', async () => {
                  const datasetKeys = Array.from(trainSvcDatasetKeys).map((key) => {
                    const [dataset_id, dataset_version] = key.split('/');
                    return { dataset_id, dataset_version };
                  });
                  const background = trainSvcBackgroundKey ? (() => {
                    const [dataset_id, dataset_version] = trainSvcBackgroundKey.split('/');
                    return { dataset_id, dataset_version };
                  })() : null;
                  const startedJob = await api.trainSelectedModels(datasetKeys, Array.from(trainSvcModelTypes), background);
                  setTrainSvcJob(startedJob);
                })}
              >
                {trainSvcDatasetKeys.size >= 2 ? 'Combinar y entrenar (identificacion)' : 'Entrenar seleccionados'}
              </button>
            </div>

            {trainSvcJob && (
              <div className="rounded-md border border-slate-700 bg-slate-900 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-semibold text-slate-100">{trainSvcSummary?.run_name || Array.from(trainSvcDatasetKeys).join(' + ')}</span>
                  <span className={trainSvcJob.state === 'completed' ? 'text-emerald-300' : trainSvcJob.state === 'failed' ? 'text-rose-300' : 'text-amber-300'}>{trainSvcJob.state.toUpperCase()}</span>
                  {trainSvcJob.message && <span className="text-slate-400">{trainSvcJob.message}</span>}
                </div>
                {trainSvcJob.state === 'completed' && trainSvcSummary && (
                  trainSvcSummary.stopped_reason ? (
                    <div className="text-amber-200">{trainSvcSummary.stopped_reason}</div>
                  ) : (
                    <>
                      {trainSvcSummary.recommended_training_run_id && (
                        <div>Recomendado (mejor en VALIDATION): <span className="font-mono">{trainSvcSummary.recommended_training_run_id}</span> -- {trainSvcSummary.recommended_reason}</div>
                      )}
                      {trainSvcSummary.final_test_evaluation && (
                        <div className="flex flex-wrap gap-4 font-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
                          <span>macro_f1: {trainSvcSummary.final_test_evaluation.macro_f1?.toFixed(3)}</span>
                          <span>balanced_accuracy: {trainSvcSummary.final_test_evaluation.balanced_accuracy?.toFixed(3)}</span>
                          <span>accuracy: {trainSvcSummary.final_test_evaluation.accuracy?.toFixed(3)}</span>
                        </div>
                      )}
                      <div className="mt-1 flex items-center gap-2">
                        <button
                          type="button"
                          className="rounded-md border border-emerald-600/60 bg-emerald-600/10 px-2 py-1 text-emerald-200 hover:bg-emerald-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                          disabled={trainSvcExporting || !trainSvcSummary.trained_models?.length}
                          onClick={() => run('train-svc-export', async () => {
                            setTrainSvcExporting(true);
                            try {
                              const exported = await api.trainingServiceExport(
                                trainSvcSummary.run_name || '', trainSvcSummary.trained_models || [], trainSvcSummary.recommended_training_run_id,
                              );
                              setTrainSvcJob((prev) => prev ? { ...prev, result_summary: { ...prev.result_summary, exported_bundles: exported } } : prev);
                              await refreshStatusBlock();
                            } finally {
                              setTrainSvcExporting(false);
                            }
                          })}
                        >
                          {trainSvcExporting ? 'Exportando…' : 'Exportar modelos entrenados'}
                        </button>
                        <span className="text-slate-500">(ya se exportan solos al terminar -- este boton los vuelve a exportar/aprobar si hace falta)</span>
                      </div>
                      <table className="mt-1 w-full text-left text-[11px]">
                        <thead className="text-slate-400">
                          <tr><th className="p-1">bundle_id</th><th className="p-1">modelo</th><th className="p-1">estado</th></tr>
                        </thead>
                        <tbody>
                          {(trainSvcSummary.exported_bundles || []).map((eb) => (
                            <tr key={eb.bundle_id} className="border-t border-slate-800">
                              <td className="p-1 font-mono">{eb.bundle_id}</td>
                              <td className="p-1">{eb.model_type}{eb.training_run_id === trainSvcSummary.recommended_training_run_id ? ' (recomendado)' : ''}</td>
                              <td className={eb.approval_status === 'APPROVED_FOR_LIVE_PILOT' ? 'p-1 text-emerald-300' : 'p-1 text-amber-300'}>{eb.approval_status || eb.error || 'ERROR'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  )
                )}
              </div>
            )}

            <div className="border-t border-slate-800 pt-2">
              <div className="mb-1 text-xs font-semibold text-slate-200">Dispositivos y modelos usados (ejecuciones de este servicio)</div>
              {trainSvcCatalog.length === 0 ? (
                <div className="text-slate-500">Todavia no se ha lanzado ninguna ejecucion de este servicio.</div>
              ) : (
                <table className="w-full text-left text-[11px]">
                  <thead className="text-slate-400">
                    <tr><th className="p-1">ejecucion</th><th className="p-1">dispositivo(s)</th><th className="p-1">dataset</th><th className="p-1">modelos entrenados</th><th className="p-1">exportados</th></tr>
                  </thead>
                  <tbody>
                    {trainSvcCatalog.map(([campaignId, group]) => {
                      const physicalUnits = datasetPhysicalUnits[group.datasetKey];
                      const exportedCount = group.runs.filter((r) => bundles.some((b) => b.training_run_id === r.training_run_id && b.approval_status === 'APPROVED_FOR_LIVE_PILOT')).length;
                      return (
                        <tr key={campaignId} className="border-t border-slate-800">
                          <td className="p-1 font-mono">{campaignId}</td>
                          <td className="p-1">{physicalUnits ? (physicalUnits.join(' + ') || 'General') : '...'}</td>
                          <td className="p-1 font-mono text-slate-400">{group.datasetKey}</td>
                          <td className="p-1">{group.runs.map((r) => r.model_type).join(', ')}</td>
                          <td className="p-1">{exportedCount}/{group.runs.length} aprobados</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setBenchmarkOpen((v) => !v)}>
          <span className="text-sm font-semibold text-slate-100">Benchmark: comparar todos los modelos entrenados ({allTrainingRuns.filter((r) => r.status === 'COMPLETED').length})</span>
          <ChevronRight className={`h-4 w-4 transition-transform ${benchmarkOpen ? 'rotate-90' : ''}`} />
        </button>
        {benchmarkOpen && (() => {
          const completedRuns = allTrainingRuns.filter((r) => r.status === 'COMPLETED');
          const visibleRuns = completedRuns.filter((r) => benchmarkTaskFilter === 'ALL' || benchmarkTaskGroup(r.scientific_task) === benchmarkTaskFilter);
          const sortedRuns = [...visibleRuns].sort((a, b) => {
            const groupCompare = benchmarkTaskGroup(a.scientific_task).localeCompare(benchmarkTaskGroup(b.scientific_task));
            if (groupCompare !== 0) return groupCompare;
            const scoreA = directEvaluations[a.training_run_id]?.evaluation_report?.VALIDATION?.accuracy ?? -1;
            const scoreB = directEvaluations[b.training_run_id]?.evaluation_report?.VALIDATION?.accuracy ?? -1;
            return scoreB - scoreA;
          });
          // Real inconsistency this fixes: comparing raw accuracy alone
          // arbitrarily crowned whichever run happened to sort first among
          // several TIED scores as "MEJOR", while Step 6's actual selection
          // (composite_score, which also weighs latency/unknown-rejection)
          // could legitimately pick a DIFFERENT one from that same tied
          // group -- e.g. CNN1D and Logistic Regression both at 0.787
          // VALIDATION accuracy, Logistic Regression selected for its lower
          // latency. Showing "MEJOR" on CNN1D there was flatly wrong: it
          // never beat Logistic Regression, they tied, and something else
          // broke the tie. Comparisons use 3-decimal rounding to match what
          // the table itself displays (toFixed(3)) -- two runs that display
          // as the same number must never disagree on tie status.
          const topScoreByGroup: Record<string, number> = {};
          for (const r of sortedRuns) {
            const group = benchmarkTaskGroup(r.scientific_task);
            const acc = directEvaluations[r.training_run_id]?.evaluation_report?.VALIDATION?.accuracy;
            if (typeof acc === 'number') {
              const rounded = Number(acc.toFixed(3));
              if (!(group in topScoreByGroup) || rounded > topScoreByGroup[group]) topScoreByGroup[group] = rounded;
            }
          }
          const tiedTopIdsByGroup: Record<string, string[]> = {};
          for (const r of sortedRuns) {
            const group = benchmarkTaskGroup(r.scientific_task);
            const acc = directEvaluations[r.training_run_id]?.evaluation_report?.VALIDATION?.accuracy;
            if (typeof acc === 'number' && Number(acc.toFixed(3)) === topScoreByGroup[group]) {
              (tiedTopIdsByGroup[group] ??= []).push(r.training_run_id);
            }
          }
          const selectedIds = sortedRuns.map((r) => r.training_run_id).filter((id) => benchmarkSelected[id]);

          return (
            <div className="mt-3 space-y-2">
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-100">
                La exactitud (accuracy) sola puede parecer excelente y aun asi no distinguir nada real: macro-F1 y exactitud balanceada promedian el rendimiento POR CLASE, asi que un modelo que siempre predice la clase mayoritaria no puede esconderse detras de un numero alto. "Procedencia de etiquetas" muestra que fraccion de los ejemplos del dataset viene de asociacion STRONG (direccion + Windows, independiente) frente a aislamiento fisico declarado por el operador (mas debil) u otros casos ambiguos -- una puntuacion alta apoyada casi solo en aislamiento declarado nunca deberia leerse igual que una apoyada en asociacion fuerte. Modelos de tareas distintas (deteccion de presencia / identidad / rechazo de desconocidos) nunca responden la misma pregunta -- no se comparan entre si, solo dentro de su propio grupo.
              </div>

              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-slate-400">Comparar:</span>
                {([
                  ['ALL', 'Todas las tareas'], ['TARGET_VS_BACKGROUND', 'Deteccion de presencia'],
                  ['IDENTITY', 'Identidad de dispositivo'], ['UNKNOWN_DEVICE_REJECTION', 'Rechazo de desconocidos'],
                ] as const).map(([key, label]) => (
                  <button
                    key={key}
                    className={`rounded-full border px-2 py-0.5 ${benchmarkTaskFilter === key ? 'border-cyan-500 bg-cyan-500/10 text-cyan-200' : 'border-slate-700 text-slate-400 hover:bg-slate-900'}`}
                    onClick={() => setBenchmarkTaskFilter(key)}
                  >
                    {label}
                  </button>
                ))}
                <span className="ml-2 text-slate-500">|</span>
                <button className="text-cyan-300 underline" onClick={() => setBenchmarkSelected(Object.fromEntries(sortedRuns.map((r) => [r.training_run_id, true])))}>
                  Seleccionar todos los visibles ({sortedRuns.length})
                </button>
                <button className="text-slate-400 underline" onClick={() => setBenchmarkSelected({})}>Deseleccionar todos</button>
                <button
                  className={`${buttonClass} disabled:opacity-50`} disabled={benchmarkComparing || !!busy}
                  onClick={() => compareModels(selectedIds.length ? selectedIds : sortedRuns.map((r) => r.training_run_id))}
                >
                  {benchmarkComparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
                  {selectedIds.length ? `Comparar seleccionados (${selectedIds.length})` : `Comparar todos los visibles (${sortedRuns.length})`}
                </button>
                {benchmarkProgress && <span className="text-slate-400">{benchmarkProgress}</span>}
              </div>

              {directEvaluationsLoading && <div className="text-xs text-slate-500">Cargando evaluaciones...</div>}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[950px] text-left text-xs">
                  <thead className="text-slate-400">
                    <tr>
                      <th className="p-1"></th>
                      <th className="p-1">Modelo</th>
                      <th className="p-1">Tarea</th>
                      <th className="p-1">Dataset</th>
                      <th className="p-1">VALIDATION (acc / macro-F1 / bal.acc)</th>
                      <th className="p-1">TEST (acc / macro-F1 / bal.acc)</th>
                      <th className="p-1">Procedencia etiquetas</th>
                      <th className="p-1">Estado</th>
                      <th className="p-1">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRuns.map((run_) => {
                      const evaluation = directEvaluations[run_.training_run_id];
                      const validation = evaluation?.evaluation_report?.VALIDATION;
                      const test = evaluation?.evaluation_report?.TEST;
                      const provenance = datasetLabelProvenance[`${run_.dataset_id}::${run_.dataset_version}`];
                      const relatedBundles = bundles.filter((b) => b.training_run_id === run_.training_run_id);
                      const taskLabel = run_.scientific_task === 'TARGET_VS_BACKGROUND' ? 'Deteccion de presencia'
                        : run_.scientific_task === 'UNKNOWN_DEVICE_REJECTION' ? 'Rechazo de desconocidos'
                        : (run_.scientific_task === 'SAME_MODEL_UNIT_IDENTIFICATION' || run_.scientific_task === 'MULTI_DEVICE_CLASSIFICATION') ? 'Identidad de dispositivo'
                        : run_.scientific_task;
                      const tiedTopIds = tiedTopIdsByGroup[benchmarkTaskGroup(run_.scientific_task)] || [];
                      const isTopScorer = tiedTopIds.includes(run_.training_run_id);
                      const isSoleTop = isTopScorer && tiedTopIds.length === 1;
                      const isTiedTop = isTopScorer && tiedTopIds.length > 1;
                      const isRecommendedAmongTie = isTiedTop && !!result?.recommended_training_run_id && result.recommended_training_run_id === run_.training_run_id;
                      return (
                        <tr key={run_.training_run_id} className={`border-t border-slate-800 align-top ${isSoleTop ? 'bg-emerald-500/10' : isRecommendedAmongTie ? 'bg-cyan-500/10' : isTiedTop ? 'bg-amber-500/5' : ''}`}>
                          <td className="p-1">
                            <input
                              type="checkbox" checked={!!benchmarkSelected[run_.training_run_id]}
                              onChange={() => setBenchmarkSelected((prev) => ({ ...prev, [run_.training_run_id]: !prev[run_.training_run_id] }))}
                            />
                          </td>
                          <td className="p-1 font-mono">
                            {isSoleTop && (
                              <span className="mr-1 rounded-full border border-emerald-500/40 bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-sans text-emerald-200" title="Mejor puntuacion VALIDATION dentro de este grupo de tarea, sin empate">
                                MEJOR
                              </span>
                            )}
                            {isRecommendedAmongTie && (
                              <span className="mr-1 rounded-full border border-cyan-500/40 bg-cyan-500/20 px-1.5 py-0.5 text-[10px] font-sans text-cyan-200">
                                SELECCIONADO (desempate)
                              </span>
                            )}
                            {isTiedTop && !isRecommendedAmongTie && (
                              <span className="mr-1 rounded-full border border-amber-500/40 bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-sans text-amber-200" title="Empatado en VALIDATION con otro(s) modelo(s) de este grupo">
                                EMPATE
                              </span>
                            )}
                            {run_.model_type}
                            {isRecommendedAmongTie && (
                              <div className="mt-0.5 font-sans text-[10px] font-normal text-cyan-300">
                                Empatados en validacion; {run_.model_type} seleccionado por desempate{result?.recommended_reason ? ` (${result.recommended_reason})` : ' de latencia'}.
                              </div>
                            )}
                            {isTiedTop && !isRecommendedAmongTie && (
                              <div className="mt-0.5 font-sans text-[10px] font-normal text-amber-300/80">
                                Empatado en validacion -- ver Paso 6 para el modelo seleccionado y el motivo real de desempate.
                              </div>
                            )}
                          </td>
                          <td className="p-1">
                            <span className={`rounded-full border px-2 py-0.5 ${run_.scientific_task === 'TARGET_VS_BACKGROUND' ? 'border-amber-500/40 bg-amber-500/10 text-amber-200' : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'}`}>
                              {taskLabel}
                            </span>
                          </td>
                          <td className="p-1 font-mono text-slate-500">{run_.dataset_id}<br />{run_.dataset_version}</td>
                          <td className="p-1">
                            {validation ? `${validation.accuracy?.toFixed(3) ?? 'N/D'} / ${validation.macro_f1?.toFixed(3) ?? 'N/D'} / ${validation.balanced_accuracy?.toFixed(3) ?? 'N/D'}` : '--'}
                          </td>
                          <td className="p-1">
                            {test ? `${test.accuracy?.toFixed(3) ?? 'N/D'} / ${test.macro_f1?.toFixed(3) ?? 'N/D'} / ${test.balanced_accuracy?.toFixed(3) ?? 'N/D'}` : 'Sin evaluar'}
                          </td>
                          <td className="p-1">
                            {provenance && provenance.total_examples > 0 ? (
                              <div className="space-y-0.5">
                                <div className={provenance.strong_fraction < 0.1 ? 'text-rose-300' : provenance.strong_fraction < 0.5 ? 'text-amber-300' : 'text-emerald-300'}>
                                  STRONG: {(provenance.strong_fraction * 100).toFixed(0)}%
                                </div>
                                <div className="text-slate-500">
                                  {Object.entries(provenance.fractions).filter(([k]) => k !== 'STRONG').map(([k, v]) => `${k}: ${(v * 100).toFixed(0)}%`).join(', ')}
                                </div>
                              </div>
                            ) : '--'}
                          </td>
                          <td className="p-1">
                            {relatedBundles.length ? relatedBundles.map((b) => (
                              <div
                                key={b.bundle_id}
                                title={b.approval_status === 'TEST_NOT_EXECUTED' ? 'No es un rechazo: paso el resto de criterios, solo falta evaluarlo sobre TEST.' : undefined}
                                className={b.approval_status === 'APPROVED_FOR_LIVE_PILOT' ? 'text-emerald-300' : b.approval_status === 'REJECTED' ? 'text-rose-300' : b.approval_status === 'TEST_NOT_EXECUTED' ? 'text-amber-300' : 'text-slate-400'}
                              >
                                {BUNDLE_STATUS_TEXT[b.approval_status] || b.approval_status}
                              </div>
                            )) : <span className="text-slate-600">Sin exportar</span>}
                          </td>
                          <td className="p-1">
                            <div className="flex flex-col items-start gap-1">
                              <button
                                className="text-cyan-300 underline disabled:opacity-50" disabled={!!busy}
                                onClick={() => run(`benchmark-reverify-${run_.training_run_id}`, async () => {
                                  const fresh = await api.evaluate(run_.training_run_id);
                                  setDirectEvaluations((prev) => ({ ...prev, [run_.training_run_id]: fresh }));
                                })}
                              >
                                Reverificar (VALIDATION)
                              </button>
                              <button
                                className="text-emerald-300 underline disabled:opacity-50" disabled={!!busy}
                                onClick={() => retrainFromTrainingRun(run_.training_run_id)}
                                title="Usa el mismo project_id/objetivo/canal y todas las capturas actualmente registradas para ese proyecto (incluye capturas nuevas desde entonces) -- salta directamente a Paso 3 ya lanzado, sin repetir Pasos 1-2."
                              >
                                Reentrenar (mismas capturas)
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()}
      </section>

      {/* Step 1: que quieres capturar ahora */}
      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <StepHeader index={1} title="¿Que quieres capturar ahora?" done={step1Done} active={!step1Done} />
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <button
            className={`rounded-md border p-4 text-left text-sm transition-colors ${capturePurpose === 'TARGET_DEVICE_ON' ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}
            onClick={() => chooseCapturePurpose('TARGET_DEVICE_ON')}
          >
            <div className="font-semibold text-slate-100">CAPTURAR MI DISPOSITIVO ENCENDIDO</div>
            <div className="mt-1 text-xs text-slate-400">El dispositivo objetivo esta encendido y transmitiendo. Esta captura podra convertirse en un ejemplo positivo si la evidencia lo confirma.</div>
          </button>
          <button
            className={`rounded-md border p-4 text-left text-sm transition-colors ${capturePurpose === 'BACKGROUND_TARGET_OFF' ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}
            onClick={() => chooseCapturePurpose('BACKGROUND_TARGET_OFF')}
          >
            <div className="font-semibold text-slate-100">CAPTURAR EL ENTORNO CON MI DISPOSITIVO APAGADO O RETIRADO</div>
            <div className="mt-1 text-xs text-slate-400">El dispositivo objetivo esta apagado o fuera del entorno. La ausencia del objetivo es el resultado esperado -- nunca se penaliza por eso.</div>
          </button>
          <button
            className={`rounded-md border p-4 text-left text-sm transition-colors ${capturePurpose === 'BACKGROUND_GENERAL' ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}
            onClick={() => chooseCapturePurpose('BACKGROUND_GENERAL')}
          >
            <div className="font-semibold text-slate-100">REGISTRAR EL ENTORNO SIN UN DISPOSITIVO CONCRETO</div>
            <div className="mt-1 text-xs text-slate-400">Entorno general, sin relacionarlo con ninguna unidad registrada en particular.</div>
          </button>
          <button
            className={`rounded-md border p-4 text-left text-sm transition-colors ${capturePurpose === 'UNKNOWN_DEVICE_COLLECTION' ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}
            onClick={() => chooseCapturePurpose('UNKNOWN_DEVICE_COLLECTION')}
          >
            <div className="font-semibold text-slate-100">RECOLECTAR DISPOSITIVOS DESCONOCIDOS</div>
            <div className="mt-1 text-xs text-slate-400">Capturar transmisores fisicos no incluidos entre las unidades conocidas -- solo para entrenar el rechazo de dispositivos desconocidos.</div>
          </button>
        </div>
      </section>

      {/* Step 2: preparar la captura */}
      <section className={`rounded-lg border p-4 ${step1Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={2} title="Preparar la captura" done={step2Done} active={step1Done && !step2Done} />
        {step1Done && (
          <div className="mt-3 space-y-4">
            {capturePurpose === 'TARGET_DEVICE_ON' && (
              <div className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs text-cyan-200">
                Enciende el dispositivo y mantenlo en la condicion indicada.
              </div>
            )}
            {capturePurpose === 'BACKGROUND_TARGET_OFF' && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-200">
                Apaga o retira el dispositivo objetivo antes de comenzar.
              </div>
            )}
            {capturePurpose === 'BACKGROUND_GENERAL' && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-200">
                No hace falta seleccionar ni apagar ningun dispositivo concreto -- listo para continuar al Paso 3.
              </div>
            )}
            {capturePurpose === 'UNKNOWN_DEVICE_COLLECTION' && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-200">
                Esta captura es solo para entrenar el rechazo de dispositivos desconocidos -- no hace falta seleccionar una unidad registrada.
              </div>
            )}

            {/* Device selection: mandatory for TARGET_DEVICE_ON, optional/documentary for
                BACKGROUND_TARGET_OFF, never shown for BACKGROUND_GENERAL/UNKNOWN_DEVICE_COLLECTION
                (neither has a specific unit in question at all). */}
            {(capturePurpose === 'TARGET_DEVICE_ON' || capturePurpose === 'BACKGROUND_TARGET_OFF') && (
            <div className="space-y-3">
              <div className="text-xs font-semibold text-slate-300">
                {capturePurpose === 'TARGET_DEVICE_ON' ? 'Selecciona la unidad fisica' : 'Que dispositivo se ha apagado (opcional, solo para documentar el experimento)'}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button className={secondaryButtonClass} disabled={!!busy} onClick={detectActiveDevices}>
                  {detectingDevices ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Detectar dispositivos activos ahora (escaneo real, ~{scanDurationSeconds}s)
                </button>
                <label className="flex items-center gap-1 text-xs text-slate-400">Duracion del escaneo (s)
                  <input
                    type="number" min={1} max={120} className={`${inputClass} h-8 w-16`}
                    value={scanDurationSeconds} disabled={!!busy}
                    onChange={(e) => setScanDurationSeconds(Math.max(1, Number(e.target.value) || 1))}
                  />
                </label>
                {devicesDetectedAt && <span className="text-xs text-slate-500">Ultimo escaneo: {devicesDetectedAt.toLocaleTimeString('es-ES')} -- {activeDevices.length} dispositivo(s) visto(s)</span>}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {capturePurpose === 'BACKGROUND_TARGET_OFF' && (
                  <button onClick={clearSelectedUnit} className={`rounded-md border p-3 text-left text-sm transition-colors ${!selectedUnitId ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}>
                    <div className="font-semibold">Ninguno (sin unidad concreta)</div>
                    <div className="text-xs text-slate-400">No se declara un dispositivo especifico apagado.</div>
                  </button>
                )}
                {units.map((u) => {
                  const activeNow = devicesDetectedAt ? isUnitActiveNow(u) : null;
                  const activeDevice = activeNow ? activeDeviceFor(u) : undefined;
                  return (
                    <button key={u.physical_unit_id} onClick={() => selectExistingUnit(u)} className={`rounded-md border p-3 text-left text-sm transition-colors ${selectedUnitId === u.physical_unit_id ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}>
                      <div className="flex items-center justify-between">
                        <div className="font-semibold">{u.model || u.physical_unit_id}</div>
                        {activeNow !== null && (
                          <span className={`rounded-full border px-2 py-0.5 text-xs ${activeNow ? 'border-emerald-500/40 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
                            {activeNow ? `ACTIVO AHORA (rssi ${activeDevice?.rssi_dbm ?? 'N/D'} dBm)` : 'no detectado -- enciendelo'}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-400">{u.manufacturer || 'Fabricante no declarado'} -- {u.device_family}</div>
                      <div className="mt-1 font-mono text-xs text-slate-500">{u.physical_unit_id}</div>
                    </button>
                  );
                })}
              </div>
              {devicesDetectedAt && unregisteredActiveDevices.length > 0 && (
                <details className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs">
                  <summary className="cursor-pointer font-semibold text-slate-300">
                    Dispositivos detectados en el ultimo escaneo, sin registrar ({unregisteredActiveDevices.length}) -- click para ver y filtrar
                  </summary>
                  <div className="mt-2 space-y-2">
                    <div className="grid gap-2 sm:grid-cols-4">
                      <label className="flex flex-col gap-1 text-slate-400">Nombre
                        <input className={inputClass} value={deviceFilterName} onChange={(e) => setDeviceFilterName(e.target.value)} placeholder="Filtrar por nombre" />
                      </label>
                      <label className="flex flex-col gap-1 text-slate-400">Direccion MAC
                        <input className={inputClass} value={deviceFilterMac} onChange={(e) => setDeviceFilterMac(e.target.value)} placeholder="Filtrar por MAC" />
                      </label>
                      <label className="flex flex-col gap-1 text-slate-400">RSSI minimo (dBm)
                        <input type="number" className={inputClass} value={deviceFilterMinRssiDbm} onChange={(e) => setDeviceFilterMinRssiDbm(Number(e.target.value))} />
                      </label>
                      <label className="flex flex-col gap-1 text-slate-400">Visto hace menos de (s)
                        <input type="number" min={1} className={inputClass} value={deviceFilterMaxAgeSeconds} onChange={(e) => setDeviceFilterMaxAgeSeconds(Number(e.target.value))} />
                      </label>
                    </div>
                    <div className="text-slate-500">
                      {filteredUnregisteredActiveDevices.length} de {unregisteredActiveDevices.length} dispositivo(s) con estos filtros (direccion detectada por el escaneo real) -- sube el RSSI minimo para ignorar los mas lejanos.
                    </div>
                    <div className="max-h-48 space-y-1 overflow-auto">
                      {filteredUnregisteredActiveDevices.map((d) => (
                        <div key={d.address} className="flex items-center justify-between gap-2">
                          <span className="font-mono">{d.address}</span>
                          <span className="text-slate-500">
                            {d.local_name || 'sin nombre publico'} (rssi {d.rssi_dbm ?? 'N/D'} dBm, visto hace {d.last_seen_utc ? `${Math.round((Date.now() - new Date(d.last_seen_utc).getTime()) / 1000)}s` : 'N/D'})
                          </span>
                          <button className="text-cyan-300 underline" onClick={() => { setNewBindingAddress(d.address); setShowRegisterForm(true); }}>Usar esta direccion</button>
                        </div>
                      ))}
                    </div>
                  </div>
                </details>
              )}

              {!showRegisterForm && <button className={secondaryButtonClass} onClick={() => setShowRegisterForm(true)}>+ Registrar un dispositivo nuevo</button>}
              {showRegisterForm && (
                <div className="space-y-2 rounded-md border border-slate-800 p-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Identificador de la unidad<input className={inputClass} value={newUnitId} onChange={(e) => setNewUnitId(e.target.value)} placeholder="CC2650-UNIT-01" /></label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Modelo / familia<input className={inputClass} value={newUnitFamily} onChange={(e) => setNewUnitFamily(e.target.value)} placeholder="TI SensorTag CC2650" /></label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Fabricante<input className={inputClass} value={newUnitManufacturer} onChange={(e) => setNewUnitManufacturer(e.target.value)} placeholder="Texas Instruments" /></label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Direccion BLE observada (opcional)<input className={inputClass} value={newBindingAddress} onChange={(e) => setNewBindingAddress(e.target.value)} placeholder="B0:B4:48:C0:36:06" /></label>
                  </div>
                  <button className="text-xs text-cyan-300 underline" onClick={() => setShowIdentityHelp(!showIdentityHelp)}>¿Por que la direccion BLE no es lo mismo que el dispositivo?</button>
                  {showIdentityHelp && (
                    <div className="rounded-md border border-slate-800 bg-slate-900 p-2 text-xs text-slate-400">
                      Un dispositivo puede cambiar de direccion BLE (direcciones aleatorias) o compartir la misma direccion con otro por error de fabrica.
                      Por eso el sistema separa la identidad del dispositivo (que tu declaras) de las direcciones observadas (que el sistema vincula con evidencia).
                    </div>
                  )}
                  <button className={buttonClass} disabled={!!busy || !newUnitId || !newUnitFamily} onClick={registerAndBind}>Registrar dispositivo</button>
                </div>
              )}
            </div>
            )}

            {/* Common capture configuration */}
            <div className="rounded-md border border-slate-800 p-3">
              <div className="grid gap-2 sm:grid-cols-4">
                <label className="flex flex-col gap-1 text-xs text-slate-400">Canal BLE
                  <select className={inputClass} value={campaignBleChannel} onChange={(e) => setCampaignBleChannel(Number(e.target.value))}>
                    <option value={37}>37</option><option value={38}>38</option><option value={39}>39</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">Duracion maxima (s)<input type="number" min={1} max={30} className={inputClass} value={campaignDurationSeconds} onChange={(e) => setCampaignDurationSeconds(Number(e.target.value))} /></label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">Ganancia (dB)<input type="number" min={0} max={70} className={inputClass} value={campaignGainDb} onChange={(e) => setCampaignGainDb(Number(e.target.value))} /></label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">Objetivo de ejemplos elegibles<input type="number" min={1} className={inputClass} value={campaignTargetEligibleExamples} onChange={(e) => setCampaignTargetEligibleExamples(Number(e.target.value))} /></label>
              </div>
              <label className="mt-2 flex flex-col gap-1 text-xs text-slate-400">Condicion experimental (declarada por el operador, ej. "encendido a 0.5m" / "apagado / ambiente")
                <input className={inputClass} value={campaignConditionLabel} onChange={(e) => setCampaignConditionLabel(e.target.value)} placeholder="Describe como esta fisicamente el dispositivo ahora mismo" />
              </label>

              {capturePurpose === 'TARGET_DEVICE_ON' && (
                <label className="mt-2 flex items-start gap-2 text-xs text-slate-400">
                  <input type="checkbox" className="mt-0.5" checked={isolationDeclared} onChange={(e) => setIsolationDeclared(e.target.checked)} />
                  <span>
                    Confirmo aislamiento fisico: solo esta unidad estaba transmitiendo cerca durante toda la captura.
                    <span className="block text-slate-500">
                      Usa esto cuando el dispositivo no tenga una direccion BLE fija (muchos dispositivos reales rotan su direccion, y entonces la coincidencia por direccion nunca funciona). Es una verdad de referencia mas debil que una coincidencia por direccion -- depende de que el aislamiento fisico sea correcto.
                    </span>
                  </span>
                </label>
              )}
              {capturePurpose === 'BACKGROUND_TARGET_OFF' && (
                <label className="mt-2 flex items-start gap-2 text-xs text-slate-400">
                  <input type="checkbox" className="mt-0.5" checked={operatorConfirmedTargetAbsent} onChange={(e) => setOperatorConfirmedTargetAbsent(e.target.checked)} />
                  <span>
                    Confirmo que el dispositivo objetivo estaba apagado o fuera del entorno durante toda la captura.
                    <span className="block text-slate-500">
                      El sistema nunca deduce que el dispositivo estaba apagado por la ausencia de señal -- esta declaracion es la unica fuente de ese dato, y por eso es obligatoria antes de lanzar una captura de entorno.
                    </span>
                  </span>
                </label>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Step 3: iniciar captura */}
      <section className={`rounded-lg border p-4 ${step2Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={3} title="Iniciar captura" done={step3Done} active={step2Done && !step3Done} />
        {step2Done && (
          <div className="mt-3 space-y-3">
            <div className="rounded-md border border-slate-800 p-3">
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-300">Captura real con B200</span>
                {campaignDeviceStatus ? (
                  <span className={`rounded-full border px-2 py-0.5 ${campaignDeviceStatus.status === 'AVAILABLE' ? 'border-emerald-500/40 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
                    B200: {campaignDeviceStatus.status}{campaignDeviceStatus.owner ? ` (en uso por ${campaignDeviceStatus.owner})` : ''}
                  </span>
                ) : (
                  <span className="rounded-full border border-rose-500/40 px-2 py-0.5 text-rose-300">B200 no disponible en este entorno</span>
                )}
              </div>
              {!campaignDeviceStatus && (
                <div className="mb-2 text-xs text-slate-500">
                  El orquestador de campaña real requiere que el modulo BLE Lab (con el B200 y el escaneo nativo) este activo en el backend. Mientras tanto puedes usar capturas reales ya existentes mas abajo.
                </div>
              )}
              <label className="mb-2 flex items-start gap-2 text-xs text-slate-400">
                <input type="checkbox" className="mt-0.5" checked={captureOnly} onChange={(e) => setCaptureOnly(e.target.checked)} />
                <span>
                  Solo capturar ahora (aplicar el analisis mas tarde)
                  <span className="block text-slate-500">
                    OFFLINE_REPLAY (decodificar la captura) es la fase mas lenta -- puede tardar varios minutos, mientras que la adquisicion RF en si solo dura los segundos configurados abajo. Marca esto para capturar varios dispositivos rapido mientras estan encendidos, y aplica el analisis de cada uno mas tarde desde la lista de capturas.
                    {' '}Mientras no apliques el analisis, la lista de abajo mostrara "{selectedUnitId || 'la unidad elegida'} (declarado, sin confirmar aun)" -- lo que TU dijiste que estabas capturando en el Paso 2, no todavia una identidad confirmada por direccion. Util para no perder la cuenta al capturar varios dispositivos seguidos, pero no lo confundas con una confirmacion real hasta aplicar el analisis.
                  </span>
                </span>
              </label>
              <div id="step-3-launch" className="flex flex-wrap items-center gap-2">
                <button
                  className="inline-flex h-10 items-center gap-2 rounded-md border border-emerald-500 bg-emerald-600/20 px-4 text-sm font-medium text-emerald-100 hover:bg-emerald-600/30 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={!!busy || campaignJobRunning || !canLaunchLiveSession} onClick={launchCampaignSession}
                  title="Graba de forma CONTINUA durante toda la duracion configurada, sin huecos -- la opcion recomendada para grabar datos reales de entrenamiento."
                >
                  {campaignJobRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
                  {captureOnly ? 'Capturar ahora (analisis pendiente)' : 'Iniciar captura real con B200'}
                  <span className="rounded-full border border-emerald-400/60 px-1.5 py-0.5 text-[10px] font-semibold">RECOMENDADO</span>
                </button>
                <button
                  className="inline-flex items-center gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!!busy || campaignJobRunning || !canLaunchLiveSession}
                  onClick={launchGuidedCapture}
                  title="Analiza el espectro antes de capturar con sondeos CORTOS y espaciados (1s cada varios segundos) -- barato, pero por eso puede no pillar un anuncio BLE poco frecuente aunque el dispositivo si este transmitiendo. Si tu objetivo es grabar datos reales para entrenar, usa 'Iniciar captura real con B200' (a la izquierda): graba 10s SEGUIDOS sin huecos, así no depende de tener suerte con el momento exacto del anuncio."
                >
                  {campaignJobRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />}
                  Captura guiada (verifica senal antes de grabar)
                  <span className="rounded-full border border-amber-400/60 px-1.5 py-0.5 text-[10px] font-semibold">CON CUIDADO</span>
                </button>
                {campaignJob && <span className="text-xs text-slate-400">{campaignJob.message || campaignJob.state}</span>}
              </div>
              <div className="mt-1 text-[11px] text-slate-500">
                <span className="font-semibold text-slate-400">Diferencia entre los dos botones:</span> "Iniciar captura real con B200" graba de forma continua durante toda la duracion configurada -- la opcion mas fiable para grabar datos reales, casi imposible que se le escape un anuncio BLE. "Captura guiada" solo hace sondeos cortos y espaciados para verificar señal ANTES de grabar -- mas barato en tiempo de B200, pero puede reportar "sin señal" por mala suerte de tiempo aunque el dispositivo este encendido y el B200 lo vea perfectamente en una captura continua. Si "Captura guiada" falla repetidamente, no asumas que el dispositivo esta apagado o lejos -- prueba primero con la captura normal.
              </div>
              {campaignJobRunning && campaignJob && ['PROBE_BASELINE', 'WAITING_FOR_DEVICE', 'PROBE_ENVIRONMENT'].includes(campaignJob.phase || '') && (
                <div className={`mt-2 rounded-md border p-3 text-sm ${campaignJob.phase === 'WAITING_FOR_DEVICE' ? 'animate-pulse border-amber-400 bg-amber-500/15 text-amber-100' : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100'}`}>
                  {campaignJob.phase === 'WAITING_FOR_DEVICE' ? (
                    <div className="flex items-center gap-2 text-base font-bold">
                      <Radio className="h-5 w-5 animate-pulse" /> AHORA ENCIENDE EL DISPOSITIVO
                    </div>
                  ) : (
                    <div className="font-semibold">
                      {campaignJob.phase === 'PROBE_BASELINE' ? 'Comprobando linea base (sin senal esperada todavia)...' : 'Comprobando que el entorno este limpio antes de capturar...'}
                    </div>
                  )}
                  <div className="mt-1 text-xs opacity-90">{campaignJob.message}</div>
                </div>
              )}
              {!campaignJobRunning && campaignJob?.state === 'failed' && campaignJob.error?.includes('GUIDED_CAPTURE_NO_SIGNAL_DETECTED') && (
                <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
                  <span className="font-semibold">La Captura guiada no encontro señal en sus sondeos cortos -- esto NO significa necesariamente que el dispositivo este apagado o lejos.</span> Los sondeos son de solo 1s cada varios segundos: si tu dispositivo anuncia con poca frecuencia, puede fallar por mala suerte de tiempo aunque el B200 lo vea bien. Antes de mover nada, prueba con <span className="font-semibold">"Iniciar captura real con B200"</span> (arriba, captura continua de 10s) -- si tampoco detecta nada ahi, entonces si conviene revisar canal (37/38/39), distancia a la antena, y que el dispositivo este realmente encendido.
                </div>
              )}
              {!campaignJobRunning && campaignJob?.state === 'failed' && campaignJob.error?.includes('GUIDED_CAPTURE_ENVIRONMENT_TOO_HOT') && (
                <div className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-100">
                  <span className="font-semibold">Se sigue detectando una senal demasiado potente cerca de la antena.</span> Aleja o apaga lo que este transmitiendo tan cerca antes de repetir la captura de entorno.
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 text-xs text-slate-500"><div className="h-px flex-1 bg-slate-800" />o, alternativamente<div className="h-px flex-1 bg-slate-800" /></div>

            <details className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs text-cyan-100" open>
              <summary className="cursor-pointer font-semibold">¿Que capturas tengo que seleccionar abajo?</summary>
              <div className="mt-2 space-y-2 text-cyan-200/90">
                <div>Depende de que quieres que el modelo aprenda a distinguir. Combina capturas de "Tipo de captura" segun el objetivo:</div>
                <ul className="list-disc space-y-1 pl-4">
                  <li><span className="font-semibold">Detectar el objetivo frente al entorno:</span> al menos 3 capturas de "Dispositivo encendido" del MISMO dispositivo (sesiones distintas, no la misma repetida) + al menos 1 captura de "Entorno" con ese dispositivo apagado/retirado.</li>
                  <li><span className="font-semibold">Identificar unidades del mismo modelo:</span> al menos 2 unidades fisicas DISTINTAS del mismo modelo (por ejemplo dos SensorTag diferentes), cada una con al menos 3 capturas "Dispositivo encendido" propias -- capturas de una sola unidad, por muchas que sean, no sirven para esto.</li>
                  <li><span className="font-semibold">Rechazar dispositivos desconocidos:</span> al menos 1 unidad conocida con 3 capturas "Dispositivo encendido" + al menos 2 capturas de dispositivos sin registrar (entorno con otros aparatos alrededor, no el silencio total).</li>
                </ul>
                <div>No hace falta saber cual elegir de antemano: selecciona todas las capturas relevantes que tengas y el Paso 4 recomienda automaticamente el objetivo que mejor encaja, o te dice exactamente que anadir si a ninguno le falta poco.</div>
              </div>
            </details>

            {lastCaptureSelection && lastCaptureSelection.capture_ids.length > 0 && (() => {
              const stillExisting = lastCaptureSelection.capture_ids.filter((id) => (legacy?.captures ?? []).some((c) => c.capture_id === id));
              if (stillExisting.length === 0) return null;
              return (
                <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-cyan-500/40 bg-cyan-500/10 p-2 text-xs text-cyan-100">
                  <span>
                    Ultima seleccion usada para entrenar: {stillExisting.length} captura(s) ({formatCaptureTimestamp(lastCaptureSelection.saved_at)})
                    {stillExisting.length !== lastCaptureSelection.capture_ids.length ? ` -- ${lastCaptureSelection.capture_ids.length - stillExisting.length} ya no existen (borradas)` : ''}.
                  </span>
                  <button className={secondaryButtonClass} disabled={!!busy} onClick={() => useRealCaptures(stillExisting)}>
                    Restaurar y usar esta seleccion de nuevo ({stillExisting.length})
                  </button>
                </div>
              );
            })()}

            <div>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span>Capturas ya existentes (selecciona una o varias):</span>
                <span className="flex gap-1">
                  {(['ALL', 'DEVICE', 'ENVIRONMENT', 'UNKNOWN_DEVICE', 'UNANALYZED'] as CaptureListFilter[]).map((f) => (
                    <button
                      key={f}
                      className={`rounded-full border px-2 py-0.5 text-xs ${captureListFilter === f ? 'border-cyan-500 bg-cyan-500/10 text-cyan-200' : 'border-slate-700 text-slate-400 hover:bg-slate-900'}`}
                      onClick={() => setCaptureListFilter(f)}
                    >
                      {f === 'ALL' ? 'Todas' : f === 'DEVICE' ? 'Dispositivo' : f === 'ENVIRONMENT' ? 'Entorno' : f === 'UNKNOWN_DEVICE' ? 'Desconocidos' : 'Sin analizar'}
                    </button>
                  ))}
                </span>
                <label className="ml-auto flex items-center gap-1">Ordenar por
                  <select className={`${inputClass} h-7`} value={captureSortKey} onChange={(e) => setCaptureSortKey(e.target.value as CaptureSortKey)}>
                    <option value="TIME_DESC">Hora (mas reciente primero)</option>
                    <option value="TIME_ASC">Hora (mas antigua primero)</option>
                    <option value="TYPE">Tipo de captura</option>
                    <option value="DECISION">Decision</option>
                  </select>
                </label>
              </div>
              <div className="max-h-56 overflow-auto rounded border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500"><tr><th className="p-1"></th><th className="p-1">Captura</th><th className="p-1">Hora</th><th className="p-1">Duracion</th><th className="p-1">Dispositivo</th><th className="p-1">Tipo de captura</th><th className="p-1">Analisis</th><th className="p-1"></th></tr></thead>
                  <tbody>
                    {visibleCaptureRows.map((c) => {
                      const discarded = c.capture_type_label === CAPTURE_TYPE_DISCARDED_RF_FAILURE;
                      const queued = analysisQueue.includes(c.capture_id);
                      const analyzingNow = currentAnalysisCaptureId === c.capture_id;
                      return (
                        <tr key={c.capture_id} className="cursor-pointer border-t border-slate-800 hover:bg-slate-900" onClick={() => setSelectedLegacyIds((prev) => prev.includes(c.capture_id) ? prev.filter((id) => id !== c.capture_id) : [...prev, c.capture_id])}>
                          <td className="p-1"><input type="checkbox" checked={selectedLegacyIds.includes(c.capture_id)} onChange={() => {}} /></td>
                          <td className="p-1 font-mono">{c.capture_id}</td>
                          <td className="p-1 text-cyan-300">{formatCaptureTimestamp(c.created_at_utc)}</td>
                          <td className="p-1 text-slate-500">{typeof c.duration_seconds === 'number' ? `${c.duration_seconds.toFixed(1)}s` : 'N/D'}</td>
                          <td className="p-1"><DeviceLabelBadge label={c.device_label} source={c.device_source} /></td>
                          <td className={`p-1 ${discarded ? 'text-amber-400' : 'text-slate-400'}`}>{c.capture_type_label || CAPTURE_TYPE_UNCLASSIFIED}</td>
                          <td className="p-1" onClick={(e) => e.stopPropagation()}>
                            {discarded ? (
                              <span className="text-slate-600">-- (sin datos utiles)</span>
                            ) : analyzingNow ? (
                              <span className="flex items-center gap-1 text-cyan-300"><Loader2 className="h-3 w-3 animate-spin" />Analizando...</span>
                            ) : queued ? (
                              <span className="text-slate-500">En cola...</span>
                            ) : c.capture_decision && c.capture_decision !== 'NOT_ANALYZED_YET' ? (
                              <div className="flex flex-col gap-0.5">
                                <span className="flex items-center gap-1">
                                  <CaptureDecisionBadge decision={c.capture_decision} />
                                  <button className="text-[10px] text-cyan-300 underline" onClick={() => applyAnalysis(c.capture_id, true)}>repetir analisis</button>
                                </span>
                                {!!c.repair_guidance?.length && (
                                  <details className="text-[10px] text-amber-300">
                                    <summary className="cursor-pointer">Por que -- {c.repair_guidance.length} causa(s)</summary>
                                    <ul className="mt-0.5 list-disc pl-3 text-slate-400">
                                      {c.repair_guidance.map((g) => <li key={g.code}>{g.message}</li>)}
                                    </ul>
                                    <button className="mt-0.5 text-cyan-300 underline" onClick={() => applyRepairAndRepeat(c.capture_id)}>Corregir y repetir</button>
                                  </details>
                                )}
                              </div>
                            ) : (
                              <div className="flex flex-col gap-0.5">
                                <button className="text-xs text-cyan-300 underline" onClick={() => applyAnalysis(c.capture_id)}>Aplicar analisis</button>
                                {quickChecks[c.capture_id] ? (
                                  quickChecks[c.capture_id].applicable ? (
                                    <span className={`text-[10px] ${quickChecks[c.capture_id].target_observed ? 'text-emerald-300' : 'text-amber-300'}`}>
                                      {quickChecks[c.capture_id].target_observed
                                        ? `Visto ${quickChecks[c.capture_id].target_observation_count}x por Bluetooth nativo`
                                        : 'NO visto por Bluetooth nativo (probable repeticion)'}
                                    </span>
                                  ) : (
                                    <span className="text-[10px] text-slate-600">Verificacion no aplicable ({quickChecks[c.capture_id].reason})</span>
                                  )
                                ) : (
                                  <button
                                    className="text-[10px] text-slate-400 underline disabled:opacity-50"
                                    disabled={quickChecking === c.capture_id}
                                    onClick={() => runQuickCheck(c.capture_id)}
                                  >
                                    {quickChecking === c.capture_id ? 'Verificando...' : 'Verificar ahora (rapido, ~1s)'}
                                  </button>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="p-1" onClick={(e) => e.stopPropagation()}>
                            <button className="text-xs text-rose-400 underline" disabled={analyzingNow} onClick={() => deleteCapture(c.capture_id)}>Borrar</button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {selectedLegacyIds.length > 0 && !step3Done && (
                <div className="mt-2 rounded-md border border-cyan-500/40 bg-cyan-500/10 p-2 text-xs text-cyan-100">
                  Has seleccionado {selectedLegacyIds.length} captura(s): {selectedDeviceCount} de dispositivo, {selectedEnvironmentCount} de entorno
                  {selectedRows.length > 0 && ` (${selectedEligibleCount} ya elegible(s))`}.
                  Pulsa <span className="font-semibold">"Usar {selectedLegacyIds.length} captura(s) real(es)"</span> abajo para continuar al Paso 4 -- solo marcar las casillas todavia no hace nada por si solo.
                </div>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  className={`${buttonClass} ${selectedLegacyIds.length > 0 && !step3Done ? 'ring-2 ring-cyan-400 ring-offset-2 ring-offset-slate-950' : ''}`}
                  disabled={!!busy || !canUseExistingCaptures} onClick={() => useRealCaptures()}
                >
                  Usar {selectedLegacyIds.length || ''} captura(s) real(es)
                </button>
                <button
                  className={secondaryButtonClass}
                  disabled={analysisRunning || selectedLegacyIds.length === 0}
                  onClick={() => queueAnalysis(selectedLegacyIds.filter((id) => visibleCaptureRows.find((r) => r.capture_id === id)?.capture_type_label !== CAPTURE_TYPE_DISCARDED_RF_FAILURE))}
                >
                  Aplicar analisis a la seleccion ({selectedLegacyIds.length})
                </button>
                <button
                  className={secondaryButtonClass}
                  disabled={analysisRunning || visibleCaptureRows.length === 0}
                  onClick={() => queueAnalysis(visibleCaptureRows.filter((r) => r.capture_type_label !== CAPTURE_TYPE_DISCARDED_RF_FAILURE).map((r) => r.capture_id))}
                >
                  Aplicar analisis a todas las visibles ({visibleCaptureRows.length})
                </button>
                {(analysisRunning || analysisQueue.length > 0) && (
                  <span className="text-xs text-slate-400">
                    {analysisTotal > 1 ? `Analizando ${analysisTotal - analysisQueue.length}/${analysisTotal}...` : 'Analizando...'}
                  </span>
                )}
              </div>
            </div>

            {step3Done && <div className="text-xs text-slate-400">Origen seleccionado: <DataSourceBadge source={dataSource} /> -- {captureIds.length} captura(s), proyecto <span className="font-mono">{projectId}</span></div>}

            {campaignSessions.length > 0 && (
              <div className="mt-3 rounded-md border border-slate-800 p-2 text-xs">
                <div className="mb-1 font-semibold text-slate-300">
                  {campaignSessions.length} sesion(es) registrada(s) (max {campaignMaxSessions}) -- Ejemplos elegibles: {campaignEligibleTotal} / objetivo {campaignTargetEligibleExamples}
                </div>
                <label className="mb-1 flex items-center gap-1 text-slate-500">Maximo de sesiones (limite de seguridad)<input type="number" min={1} className={`${inputClass} h-7 w-16`} value={campaignMaxSessions} onChange={(e) => setCampaignMaxSessions(Number(e.target.value))} /></label>

                {/* Paso 4 del pedido del operador: resultado de cada sesion */}
                <table className="w-full text-left">
                  <thead className="text-slate-500"><tr><th className="p-1">#</th><th className="p-1">Captura</th><th className="p-1">Hora</th><th className="p-1">Dispositivo</th><th className="p-1">Tipo</th><th className="p-1">Estado declarado</th><th className="p-1">Condicion</th><th className="p-1">Paquetes</th><th className="p-1">Elegibles</th><th className="p-1">Calidad</th><th className="p-1">Decision</th><th className="p-1">Analisis</th></tr></thead>
                  <tbody>
                    {campaignSessions.map((s) => (
                      <tr key={s.session_index} className="border-t border-slate-800">
                        <td className="p-1">{s.session_index}</td>
                        <td className="p-1 font-mono text-slate-500">{s.capture_id || '--'}</td>
                        <td className="p-1 text-cyan-300">{formatCaptureTimestamp(s.started_at_utc)}</td>
                        <td className="p-1 text-slate-300">{s.device_label || (s.error ? '--' : 'Sin analizar aun')}</td>
                        <td className="p-1">{s.capture_type_label || (s.capture_purpose === 'TARGET_DEVICE_ON' ? CAPTURE_TYPE_DEVICE : CAPTURE_TYPE_ENVIRONMENT_GENERAL)}</td>
                        <td className="p-1 text-slate-400">{s.target_state === 'POWERED_ON' ? 'Encendido' : s.target_state ? 'Apagado/retirado (declarado)' : '--'}</td>
                        <td className="p-1">{s.condition_label}</td>
                        <td className="p-1">{s.error ? '-' : s.total_examples}</td>
                        <td className="p-1">{s.error ? '-' : s.eligible_examples}</td>
                        <td className="p-1">{s.error ? '-' : (s.acquisition_quality || 'N/D')}</td>
                        <td className="p-1">
                          {s.error ? (
                            <details>
                              <summary className="cursor-pointer text-rose-300">Fallida (ver motivo)</summary>
                              <div className="mt-1 max-w-md whitespace-normal text-slate-300">{describeCampaignSessionError(s.error)}</div>
                              <div className="mt-1 max-w-md whitespace-normal break-all text-slate-600">Detalle tecnico: {s.error}</div>
                            </details>
                          ) : <CaptureDecisionBadge decision={s.capture_decision} />}
                        </td>
                        <td className="p-1">
                          {!s.error && s.capture_id && (
                            currentAnalysisCaptureId === s.capture_id ? (
                              <span className="flex items-center gap-1 text-cyan-300"><Loader2 className="h-3 w-3 animate-spin" />Analizando...</span>
                            ) : analysisQueue.includes(s.capture_id) ? (
                              <span className="text-slate-500">En cola...</span>
                            ) : s.capture_decision && s.capture_decision !== 'NOT_ANALYZED_YET' ? (
                              <button className="text-xs text-cyan-300 underline" onClick={() => applyAnalysis(s.capture_id, true)}>Ya aplicado -- repetir</button>
                            ) : (
                              <button className="text-xs text-cyan-300 underline" onClick={() => applyAnalysis(s.capture_id)}>Aplicar analisis</button>
                            )
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Progreso de la campaña, contado por separado */}
                <div className="mt-2 space-y-0.5 text-slate-400">
                  <div>Dispositivo{deviceLabelsUsed.length ? ` ${deviceLabelsUsed.join(' + ')}` : selectedUnitId ? ` ${selectedUnitId}` : ''}: {deviceSessions.length} sesion(es) realizada(s), {deviceEligibleSessions.length} elegible(s), {deviceEligibleExamples} ejemplo(s) elegible(s).</div>
                  <div>Entorno (dispositivo apagado): {backgroundSessions.length} sesion(es) realizada(s), {backgroundEligibleSessions.length} elegible(s), {backgroundEligibleExamples} ejemplo(s) negativo(s) elegible(s).</div>
                </div>

                {campaignEligibleTotal >= campaignTargetEligibleExamples ? (
                  <div className="mt-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-2 text-emerald-200">Objetivo de ejemplos elegibles alcanzado. Puedes continuar al paso 4 o seguir capturando mas sesiones.</div>
                ) : campaignSessions.length >= campaignMaxSessions ? (
                  <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-200">Se alcanzo el limite de seguridad de sesiones sin llegar al objetivo. Continuar puede resultar en un dataset insuficiente (se explicara en el paso 4).</div>
                ) : (
                  <div className="mt-2 text-slate-500">Todavia no se alcanza el objetivo ni el limite de seguridad -- puedes lanzar otra sesion.</div>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Step 4 */}
      <section className={`rounded-lg border p-4 ${step3Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={4} title="Elegir el objetivo del entrenamiento" done={step4Done} active={step3Done} />
        {step3Done && (
          <div className="mt-3 space-y-2">
            <div className="rounded-md border border-slate-800 bg-slate-900/50 p-2 text-xs text-slate-400">
              El "objetivo" es la pregunta cientifica que el modelo va a aprender a responder (por ejemplo: "¿esta transmision es de mi dispositivo o del entorno?", o "¿cual de mis unidades registradas es esta?"). Cada objetivo necesita un tipo y una cantidad distinta de capturas -- por eso el sistema recomienda automaticamente el que mejor encaja con lo que ya capturaste, abajo. No hace falta elegir un modelo de IA en este paso: eso lo hace el sistema solo en el Paso 5.
            </div>
            {recommending && <div className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="h-3 w-3 animate-spin" />Calculando cual objetivo encaja mejor con lo que ya tienes...</div>}
            {taskRecommendation && !recommending && (
              <div className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs text-cyan-200">
                <span className="font-semibold">Recomendado: {taskRecommendation.recommended_task_display}.</span> {taskRecommendation.reason}
              </div>
            )}
            <select className={inputClass} value={scientificTask} onChange={(e) => changeScientificTask(e.target.value)}>
              {Object.entries(scientificTasks).map(([key, label]) => <option key={key} value={key}>{label}{taskRecommendation?.recommended_task === key ? ' (recomendado)' : ''}</option>)}
            </select>
            <button className={secondaryButtonClass} disabled={!!busy} onClick={() => run('feasibility', async () => {
              // Feasibility needs a dataset; build a lightweight preview dataset from the selected captures.
              const previewDatasetId = await ensurePreviewDataset(projectId, campaignId, captureIds);
              const preview = await api.feasibility(previewDatasetId, '0.0.0', scientificTask);
              setFeasibilityPreview(preview);
            })}>Comprobar si hay datos suficientes</button>
            {feasibilityPreview && (
              <div className={`rounded-md border p-3 text-sm ${feasibilityPreview.feasible ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100' : 'border-amber-500/40 bg-amber-500/10 text-amber-100'}`}>
                <div className="font-semibold">{feasibilityPreview.feasible ? 'Hay datos suficientes para esta tarea.' : 'Todavia no hay datos suficientes para entrenar este objetivo.'}</div>
                <div className="mt-1 whitespace-pre-line text-xs opacity-90">{feasibilityPreview.human_summary}</div>
                {feasibilityPreview.next_steps.length > 0 && (
                  <div className="mt-2 text-xs">
                    <div className="font-semibold opacity-90">Que hacer ahora:</div>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 opacity-90">
                      {feasibilityPreview.next_steps.map((step, i) => <li key={i}>{step}</li>)}
                    </ul>
                  </div>
                )}
                <details className="mt-2 text-xs opacity-70"><summary className="cursor-pointer">Detalles avanzados</summary>
                  <pre className="mt-1 overflow-auto">{JSON.stringify({ have: feasibilityPreview.have, need: feasibilityPreview.need }, null, 2)}</pre>
                </details>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Step 5 */}
      <section className={`rounded-lg border p-4 ${step4Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={5} title="Preparar dataset y entrenar" done={step5Done} active={step4Done && !step5Done} />
        {step4Done && (
          <div className="mt-3 space-y-3">
            <div className="rounded-md border border-slate-800 bg-slate-900/50 p-2 text-xs text-slate-400">
              Un solo click hace todo lo que falta con las capturas ya analizadas: congela el dataset, comprueba su calidad (duplicados, fugas entre entrenamiento/prueba), entrena varios modelos candidatos EN PARALELO (regresion logistica, SVM, Random Forest, y ademas CNN1D/CNN2D si el perfil "normal" esta activo y hay datos suficientes), y elige automaticamente el mejor segun su puntuacion en un conjunto de validacion -- nunca hace falta elegir un modelo a mano. Si ningun candidato alcanza la calidad minima, el sistema lo dice claramente en vez de recomendar el menos malo. El modelo elegido (si lo hay) se evalua una unica vez sobre el conjunto de prueba y aparece en el Paso 6 "Resultado" de aqui abajo, junto con la opcion de exportarlo.
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-slate-400"><input type="radio" checked={speedProfile === 'quick_pilot'} onChange={() => setSpeedProfile('quick_pilot')} />Piloto rapido (solo modelos base, mas rapido)</label>
              <label className="flex items-center gap-2 text-xs text-slate-400"><input type="radio" checked={speedProfile === 'normal'} onChange={() => setSpeedProfile('normal')} />Entrenamiento normal (incluye CNN si hay datos suficientes)</label>
            </div>

            <button className={secondaryButtonClass} disabled={!!busy} onClick={reviewDataset}>Revisar datos que se van a usar antes de entrenar</button>

            {trainingPreview && (
              <div className={`rounded-md border p-3 text-sm ${trainingPreview.ready_to_train ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100' : 'border-rose-500/40 bg-rose-500/10 text-rose-200'}`}>
                <div className="font-semibold">
                  {trainingPreview.ready_to_train ? 'Datos listos para entrenar.' : 'Todavia no se puede entrenar con estos datos.'}
                </div>
                {!trainingPreview.ready_to_train && trainingPreview.infeasibility_reason && (
                  <div className="mt-1 whitespace-pre-line text-xs opacity-90">{trainingPreview.infeasibility_reason}</div>
                )}
                {!trainingPreview.quality_gate_ok && (
                  <div className="mt-1 text-xs opacity-90">
                    <div className="font-semibold">El control de calidad del dataset (duplicados/solapamiento) todavia no pasa:</div>
                    <ul className="mt-0.5 list-disc pl-4">
                      {trainingPreview.quality_gate_reasons.map((reason, i) => <li key={i}>{reason}</li>)}
                    </ul>
                    <button className={`${secondaryButtonClass} mt-2`} disabled={!!busy} onClick={resolveDuplicatesAndReview}>
                      Resolver automaticamente (excluir el minimo necesario) y revisar de nuevo
                    </button>
                    <div className="mt-1 text-slate-500">
                      Nunca decide cual de dos decodificaciones es "mejor" -- para duplicados exactos conserva uno y descarta el resto; para solapamientos conserva el mayor conjunto posible de ejemplos independientes (regla deterministica, reproducible). Los ejemplos excluidos quedan marcados como cuarentena, nunca borrados -- siguen en el disco por si hace falta auditarlos.
                    </div>
                    {resolveDuplicatesSummary && (
                      <div className="mt-1 rounded border border-emerald-500/30 bg-emerald-950/20 p-1.5 text-emerald-200">
                        {resolveDuplicatesSummary.quarantined_example_ids.length > 0
                          ? `${resolveDuplicatesSummary.quarantined_example_ids.length} ejemplo(s) puesto(s) en cuarentena en ${resolveDuplicatesSummary.captures_updated.length} captura(s). Recalculando...`
                          : 'No se encontro nada que resolver (el bloqueo puede tener otra causa).'}
                      </div>
                    )}
                  </div>
                )}
                {trainingPreview.sample_overlap_pairs?.length > 0 && (
                  <div className="mt-2 space-y-2">
                    <div className="font-semibold text-xs">Pareja(s) exacta(s) que causan el bloqueo por solapamiento:</div>
                    {trainingPreview.sample_overlap_pairs.map((pair, i) => (
                      <div key={i} className="rounded border border-rose-500/30 bg-rose-950/30 p-2 text-[11px]">
                        <div className={`mb-1 inline-block rounded-full border px-2 py-0.5 font-semibold ${pair.cross_partition ? 'border-red-400 bg-red-500/20 text-red-200' : 'border-slate-600 bg-slate-800 text-slate-300'}`}>
                          {pair.cross_partition ? 'FUGA ENTRE PARTICIONES' : `Misma particion (${pair.split_a ?? 'sin asignar'})`}
                        </div>
                        <table className="w-full text-left">
                          <thead className="text-slate-500"><tr><th className="pr-2"></th><th className="pr-2">example_id</th><th className="pr-2">capture_id</th><th className="pr-2">sample_start</th><th className="pr-2">sample_end</th><th>particion</th></tr></thead>
                          <tbody>
                            <tr><td className="pr-2 text-slate-500">A</td><td className="pr-2 font-mono">{pair.example_id_a}</td><td className="pr-2 font-mono">{pair.capture_id_a}</td><td className="pr-2">{pair.iq_start_sample_a}</td><td className="pr-2">{pair.iq_end_sample_a}</td><td>{pair.split_a ?? '--'}</td></tr>
                            <tr><td className="pr-2 text-slate-500">B</td><td className="pr-2 font-mono">{pair.example_id_b}</td><td className="pr-2 font-mono">{pair.capture_id_b}</td><td className="pr-2">{pair.iq_start_sample_b}</td><td className="pr-2">{pair.iq_end_sample_b}</td><td>{pair.split_b ?? '--'}</td></tr>
                          </tbody>
                        </table>
                        <div className="mt-1 text-slate-400">{pair.overlap_samples} muestra(s) solapada(s) -- {(pair.overlap_fraction_of_smaller_window * 100).toFixed(1)}% de la ventana mas pequena.</div>
                        <div className="mt-1 text-slate-300">{pair.reason}</div>
                      </div>
                    ))}
                  </div>
                )}
                {datasetComposition && (
                  <div className="mt-2 rounded border border-slate-700/60 bg-slate-950/40 p-2 text-xs">
                    <div className="font-semibold text-slate-300">Composicion del dataset (informativo, nunca bloquea):</div>
                    <div className="mt-1 opacity-90">
                      Canal BLE: {Object.entries(datasetComposition.channel_counts).map(([ch, n]) => `${ch}: ${n}`).join(', ') || 'N/D'}
                      {Object.keys(datasetComposition.channel_counts).length === 1 && (
                        <span className="ml-1 text-amber-300">(un solo canal -- el modelo solo se ha probado ahi)</span>
                      )}
                    </div>
                    <div className="opacity-90">Sesiones distintas: {datasetComposition.session_count}</div>
                    <div className="opacity-90">
                      Dias de captura: {Object.entries(datasetComposition.day_counts).map(([day, n]) => `${day}: ${n}`).join(', ') || 'N/D'}
                      {Object.keys(datasetComposition.day_counts).length === 1 && (
                        <span className="ml-1 text-amber-300">(todo capturado el mismo dia)</span>
                      )}
                    </div>
                    <div className="opacity-90">Por unidad fisica: {Object.entries(datasetComposition.physical_unit_counts).map(([unit, n]) => `${unit}: ${n}`).join(', ') || 'N/D'}</div>
                  </div>
                )}
                {datasetLabelProvenancePreview && datasetLabelProvenancePreview.total_examples > 0 && (
                  <div className={`mt-2 rounded border p-2 text-xs ${datasetLabelProvenancePreview.strong_fraction < 0.1 ? 'border-rose-500/40 bg-rose-500/10' : datasetLabelProvenancePreview.strong_fraction < 0.5 ? 'border-amber-500/40 bg-amber-500/10' : 'border-emerald-500/40 bg-emerald-500/10'}`}>
                    <div className="font-semibold text-slate-200">Procedencia de las etiquetas (informativo, nunca bloquea):</div>
                    <div className="mt-1">
                      STRONG (direccion + Windows, independiente): <span className="font-semibold">{(datasetLabelProvenancePreview.strong_fraction * 100).toFixed(0)}%</span>
                    </div>
                    <div className="opacity-90">
                      {Object.entries(datasetLabelProvenancePreview.fractions).filter(([k]) => k !== 'STRONG').map(([k, v]) => `${k}: ${(v * 100).toFixed(0)}%`).join(', ')}
                    </div>
                    {datasetLabelProvenancePreview.strong_fraction < 0.5 && (
                      <div className="mt-1 opacity-90">
                        La mayoria de las etiquetas de este dataset dependen de aislamiento fisico declarado por el operador (o son ambiguas), no de una asociacion confirmada por direccion + Windows. Es una verdad de referencia mas debil -- una puntuacion alta aqui no equivale a una con asociacion fuerte.
                      </div>
                    )}
                  </div>
                )}
                <div className="mt-2 space-y-2 text-xs">
                  {(['TRAIN', 'VALIDATION', 'TEST'] as const).map((splitName) => {
                    const splitData = trainingPreview.splits[splitName];
                    return (
                      <div key={splitName} className="rounded border border-slate-700/60 bg-slate-950/40 p-2">
                        <div className="font-semibold text-slate-300">{splitName}: {splitData.classes.length} clase(s) -- {splitData.classes.join(', ') || 'ninguna'}</div>
                        {splitData.classes.map((className) => (
                          <div key={className} className="ml-2 opacity-90">
                            {className}: {splitData.examples_by_class[className] ?? 0} ejemplo(s), {(splitData.sessions_by_class[className] ?? []).length} sesion(es)
                          </div>
                        ))}
                        <div className="ml-2 opacity-60">Capturas usadas: {splitData.capture_ids.join(', ') || 'ninguna'}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 text-xs opacity-80">
                  Ejemplos elegibles totales (dataset congelado): {trainingPreview.eligible_examples_total}. Excluidos: {trainingPreview.excluded_examples_total}.
                  {trainingPreview.quarantined_capture_ids.length > 0 && <> Capturas en cuarentena: {trainingPreview.quarantined_capture_ids.join(', ')}.</>}
                </div>
              </div>
            )}

            <button className={buttonClass} disabled={!!busy || jobRunning || !trainingPreview?.ready_to_train} onClick={startPrepareAndTrain}>
              {jobRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
              Preparar dataset y entrenar
            </button>
            {!trainingPreview && <div className="text-xs text-slate-500">Primero revisa los datos que se van a usar -- el boton se habilita cuando la revision es coherente.</div>}
            {job && <div className="text-xs text-slate-400">{job.message || job.state}</div>}
          </div>
        )}
      </section>

      {/* Step 6 */}
      {result && (
        <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
          <StepHeader index={6} title="Resultado" done={Object.keys(resultExported).length > 0} active={Object.keys(resultExported).length === 0} />
          <div className="mt-3 space-y-3">
            <div className="flex items-center gap-2 text-xs text-slate-400">Origen: <DataSourceBadge source={dataSource} /></div>

            {result.stopped_at && result.stopped_at === 'model_selection' && (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
                <div className="font-semibold">NO_MODEL_ACCEPTED: ningun modelo candidato paso el criterio minimo de aceptacion.</div>
                <div className="mt-1 whitespace-pre-line text-xs opacity-90">{result.stopped_reason}</div>
                <div className="mt-1 text-xs opacity-70">
                  Los datos eran suficientes para entrenar (todos los candidatos se entrenaron y se compararon en VALIDATION); ninguno alcanzo la calidad minima para recomendarse. No se exporta automaticamente el modelo menos malo.
                </div>
                {!!result.trained_models.length && (
                  <>
                    <table className="mt-2 w-full text-left text-xs">
                      <thead className="text-slate-400"><tr><th className="p-1">Modelo</th><th className="p-1">Puntuacion (VALIDATION)</th><th className="p-1">Exportar</th></tr></thead>
                      <tbody>
                        {result.trained_models.map((m) => (
                          <tr key={m.training_run_id} className="border-t border-slate-800">
                            <td className="p-1">{m.model_type}</td>
                            <td className="p-1">{m.composite_score.toFixed(3)}</td>
                            <td className="p-1">{renderResultExportCell(m.training_run_id, false)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="mt-1 text-xs opacity-70">
                      Ninguno alcanzo la calidad minima recomendada, pero puedes exportar cualquiera -- o varios -- de todas formas si quieres usarlos (ej. para comparar o depurar). Se exportan con su evaluacion de VALIDATION; ninguno tuvo evaluacion en TEST automaticamente (ninguno fue seleccionado), pero puedes pedirla de forma explicita por fila para poder aprobarlo en Live Monitor.
                    </div>
                  </>
                )}
              </div>
            )}

            {result.stopped_at && result.stopped_at !== 'model_selection' && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
                <div className="font-semibold">Todavia no hay datos suficientes para entrenar este objetivo.</div>
                <div className="mt-1 whitespace-pre-line text-xs opacity-90">{result.stopped_reason}</div>
                {!!result.feasibility?.next_steps?.length && (
                  <div className="mt-2 text-xs">
                    <div className="font-semibold opacity-90">Que hacer ahora:</div>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 opacity-90">
                      {result.feasibility.next_steps.map((step, i) => <li key={i}>{step}</li>)}
                    </ul>
                  </div>
                )}
                <details className="mt-2 text-xs opacity-70"><summary className="cursor-pointer">Detalles avanzados</summary>
                  <pre>stopped_at: {result.stopped_at}{'\n'}split_status: {result.split_status}</pre>
                </details>
              </div>
            )}

            {!result.stopped_at && (
              <>
                <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-2 text-xs font-semibold text-emerald-200">
                  MODELO ENTRENADO CON B200 REAL
                </div>
                {/* Five deliberately separate columns -- entrenamiento, validacion,
                    seleccion como candidato final, ejecucion de TEST y
                    aprobacion para Live Monitor are different questions with
                    different answers; collapsing them into one "Estado" word
                    is what made a merely-not-yet-tested candidate readable
                    as "rejected"/"invalid". */}
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-400">
                    <tr>
                      <th className="p-1">Modelo</th>
                      <th className="p-1">Entrenamiento</th>
                      <th className="p-1">Candidato final</th>
                      <th className="p-1">Puntuacion (VALIDATION)</th>
                      <th className="p-1">TEST</th>
                      <th className="p-1">Exportar / Live Monitor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trained_models.map((m) => {
                      const isRecommended = m.training_run_id === result.recommended_training_run_id;
                      const testProvenance = resultTestEvalProvenance[m.training_run_id];
                      const testStatusText = isRecommended
                        ? (result.final_test_evaluation ? 'Unico (garantia de seleccion)' : 'Pendiente (se ejecuta una vez, al congelar)')
                        : testProvenance === 'OPT_IN_MULTI_CANDIDATE_COMPARISON'
                        ? 'Opcional (comparacion multiple)'
                        : 'No ejecutado (reservado)';
                      return (
                        <tr key={m.training_run_id} className={`border-t border-slate-800 ${isRecommended ? 'bg-cyan-500/10' : ''}`}>
                          <td className="p-1 font-mono">{m.model_type}</td>
                          <td className="p-1 text-emerald-300">Completado</td>
                          <td className="p-1">{isRecommended ? <span className="text-cyan-300">Seleccionado</span> : <span className="text-slate-400">No seleccionado</span>}</td>
                          <td className="p-1">{m.composite_score.toFixed(3)}</td>
                          <td className={`p-1 ${isRecommended ? 'text-emerald-300' : testProvenance === 'OPT_IN_MULTI_CANDIDATE_COMPARISON' ? 'text-amber-300' : 'text-slate-500'}`}>{testStatusText}</td>
                          <td className="p-1">{renderResultExportCell(m.training_run_id, isRecommended)}</td>
                        </tr>
                      );
                    })}
                    {result.skipped_models.map((m) => (
                      <tr key={m.model_type} className="border-t border-slate-800 text-slate-500">
                        <td className="p-1">{m.model_type}</td><td className="p-1" colSpan={5}>No disponible: {m.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="text-[11px] text-slate-500">
                  "No seleccionado" no significa invalido: todos estos modelos entrenaron correctamente y llegaron a la misma puntuacion de VALIDATION comparable ("Candidato final" es solo la eleccion, hecha por criterio de desempate cuando hay empate -- ver el aviso de empate en el Benchmark si aplica). Puedes exportar varios modelos a la vez, no solo el seleccionado -- cada fila tiene su propio boton. Solo el seleccionado tiene evaluacion sobre TEST automaticamente (evaluar varios candidatos en TEST invalidaria la reserva de datos de prueba); para los demas puedes pedirla de forma explicita por fila si quieres poder aprobarlos tambien en Live Monitor.
                </div>

                {result.recommended_training_run_id ? (
                  <div className="rounded-md border border-cyan-500/40 bg-cyan-500/10 p-3 text-sm text-cyan-100">
                    <div className="font-semibold">Modelo recomendado: {result.trained_models.find((m) => m.training_run_id === result.recommended_training_run_id)?.model_type}</div>
                    <div className="mt-1 text-xs opacity-90">Motivo (VALIDATION): {result.recommended_reason}</div>
                    {result.final_test_evaluation ? (
                      <div className="mt-2 border-t border-cyan-500/30 pt-2 text-xs">
                        <div className="font-semibold opacity-90">Evaluacion final (TEST, unica, tras congelar el modelo)</div>
                        <div className="mt-1 opacity-90">
                          exactitud: {typeof result.final_test_evaluation.accuracy === 'number' ? result.final_test_evaluation.accuracy.toFixed(3) : 'N/D'}
                          {'  '}| ejemplos: {String(result.final_test_evaluation.n_examples ?? 'N/D')}
                        </div>
                        <details className="mt-1 opacity-70"><summary className="cursor-pointer">Detalle por clase</summary>
                          <pre className="whitespace-pre-wrap">{JSON.stringify(result.final_test_evaluation, null, 2)}</pre>
                        </details>
                      </div>
                    ) : (
                      <div className="mt-2 border-t border-cyan-500/30 pt-2 text-xs opacity-70">Evaluacion final sobre TEST aun no disponible para esta ejecucion.</div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">Ningun modelo cumple los criterios de aceptacion.</div>
                )}

                {Object.values(resultExported).some((b) => b.approval_status === 'APPROVED_FOR_LIVE_PILOT') && (
                  <div className="space-y-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                    <div>{Object.values(resultExported).filter((b) => b.approval_status === 'APPROVED_FOR_LIVE_PILOT').length} modelo(s) aprobado(s) para piloto en Live Monitor.</div>
                    <div className="text-xs text-amber-200">
                      La seleccion de modelos BLE-RFFI dentro de Live Monitor, y la inferencia sobre I/Q en vivo (no solo PSD), todavia no estan conectadas -- ver "funciones no conectadas".
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
