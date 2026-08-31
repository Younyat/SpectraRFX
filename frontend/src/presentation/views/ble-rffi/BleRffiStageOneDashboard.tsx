import { useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { AlertTriangle, Bluetooth, CheckCircle2, Database, Play, RefreshCw, ScanSearch, ShieldCheck, XCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  BleApiService,
  BleCaptureCapabilities,
  BleCaptureJob,
  BleCaptureLive,
  BleCaptureRecord,
  BleDatasetDetail,
  BleHybridSession,
  BleNativeDevice,
  BleNativeStatus,
  BleOfflineReplay,
  BleOfflineReplayJob,
  BleOfflineReplayProgress,
  BleRfDiagnostic,
  BleSdrDevice,
  BleScientificSummary,
} from '../../../app/services/bleApi';
import { beginBleButtonAction } from '../../../app/operations/bleActionTelemetry';
import { ensureOperation, failOperation, finishOperation, startOperation, updateOperation } from '../../../app/operations/operationTelemetry';
import { freezeTarget } from '../ble/bleTargetModel';
import { campaignContract } from '../ble/campaignPolicy';

const api = new BleApiService();
const BASE_PROTOCOL_ID = 'BLE-RFFI-ONE-TARGET-STAGE-ONE-v1';
const PROFILE_STORAGE_KEY = 'ble-rffi-device-profiles-v1';
const ACTIVE_PROFILE_STORAGE_KEY = 'ble-rffi-active-profile-v1';
const INTRO_STORAGE_KEY = 'ble-rffi-hide-intro-v1';
const PREFLIGHT_VALID_MS = 5 * 60 * 1000;
const ABSENCE_SCAN_SECONDS = 30;
const DEFAULT_CAPTURE_SECONDS = 10;
const QUALIFICATION_CAPTURE_SECONDS = 10;
const QUALIFICATION_REQUIRED_CLEAN = 3;
const QUALIFICATION_EXPECTED_SAMPLES = 40_000_000;
const QUALIFICATION_EXPECTED_FILE_SIZE = 320_000_000;
const MINIMUM_RF_CONCURRENCY_OVERLAP_SECONDS = 9;
const MINIMUM_RF_CONCURRENCY_OVERLAP_FRACTION = 0.90;
const MINIMUM_TARGET_CRC_PACKETS = 1;
const MINIMUM_TARGET_STRONG_MATCHES = 1;
const MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION = 1;
const MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE = 3;
const POSITIVE_PILOT_QUALITY_GATE_VERSION = 'ble-rffi-positive-pilot-gate-v2';
const POSITIVE_PILOT_RECEIVER_SERIAL = 'E3R04Z1B2';
const terminalStates = new Set(['completed', 'failed', 'cancelled', 'timed_out']);
const inputClass = 'min-h-10 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:border-cyan-500';
const diagnosticSteps: { id: DiagnosticStepId; title: string; objective: string; user: string }[] = [
  { id: 'A_RECEIVER_TRANSPORT', title: 'Diagnostico A - Estado del B200 y transporte', objective: 'Comprobar receptor, acceso exclusivo, USB/UHD, driver y host antes de capturar.', user: 'Compruebe que el B200 esta conectado directamente a USB 3, sin hub, y que ningun otro proceso usa el receptor.' },
  { id: 'B_STREAM_NO_DISK', title: 'Diagnostico B - Streaming sin escritura a disco', objective: 'Determinar si las perdidas aparecen antes de la persistencia.', user: 'No toque el SensorTag. Esta prueba descarta muestras y no genera evidencia.' },
  { id: 'C_PERSISTENCE_MINIMAL', title: 'Diagnostico C - Persistencia minima', objective: 'Determinar si la escritura a disco introduce perdidas.', user: 'Mantenga cerradas otras tareas pesadas. La interfaz reduce preview/polling.' },
  { id: 'D_INTERFACE_MONITORING', title: 'Diagnostico D - Interfaz y servicios concurrentes', objective: 'Determinar si monitorizacion/API afectan al hilo critico.', user: 'Observe progreso normal; Windows BLE, decoder y correlacion siguen desactivados.' },
  { id: 'E_ALT_FORMAT', title: 'Diagnostico E - Formato alternativo opcional', objective: 'Aislar sensibilidad a caudal/formato con ci16_le sin cambiar el protocolo cientifico.', user: 'Use esta prueba solo como diagnostico; no mezcla perfiles de cualificacion.' },
];

const tabs = ['Campana', 'Matriz experimental', 'Resultados', 'Evidencia', 'Configuracion avanzada'] as const;
type Tab = typeof tabs[number];
type GateState = 'pass' | 'warn' | 'fail' | 'pending';
type StageState = 'done' | 'active' | 'locked';
type CampaignStep = 'device' | 'qualification' | 'prepare' | 'replay' | 'positive' | 'negative' | 'repeat' | 'dataset';
type QualificationPhase = 'ACQUISITION_QUALIFICATION' | 'HYBRID_CONCURRENCY_QUALIFICATION';
type DiagnosticStepId = 'A_RECEIVER_TRANSPORT' | 'B_STREAM_NO_DISK' | 'C_PERSISTENCE_MINIMAL' | 'D_INTERFACE_MONITORING' | 'E_ALT_FORMAT';
type AbsenceVerification = { conditionId: string; checkedAt: string; targetSeen: boolean; validUntil: number };
type OperationEvent = { id: string; at: string; phase: string; detail: string; state: 'running' | 'done' | 'error' };

type DeviceProfile = {
  device_profile_id: string;
  physical_unit_id: string;
  display_name: string;
  manufacturer: string;
  model: string;
  hardware_revision: string;
  firmware_version: string;
  protocol: string;
  logical_address: string;
  address_type: string;
  local_name: string;
  advertising_identifiers: string;
  preferred_channels: number[];
  operator_notes: string;
  created_at: string;
  status: string;
};

type MatrixCondition = {
  index: number;
  condition_id: string;
  day_id: string;
  positive_session_id: string;
  negative_session_id: string;
  power_cycle_id: string;
  distance: string;
  orientation: string;
  location: string;
  operator_notes: string;
  environment_notes: string;
  relevant_obstacles: string;
  receiver_position: string;
  transmitter_position: string;
};

type QualificationStatus = {
  phase: QualificationPhase;
  cleanConsecutive: number;
  failureConsecutive: number;
  totalForProfile: number;
  passed: boolean;
  latest?: BleCaptureRecord;
  latestFailure?: BleCaptureRecord;
};

type DiagnosticResult = {
  step: DiagnosticStepId;
  status: 'PENDING' | 'PASSED' | 'FAILED' | 'BLOCKED' | 'NOT_RUN';
  observed_result: string;
  supported_interpretation: string;
  unresolved_alternatives: string[];
  recommended_next_action: string;
  capture_id?: string;
};

const defaultProfile: DeviceProfile = {
  device_profile_id: 'ble-profile-cc2650-unit-01',
  physical_unit_id: 'CC2650-UNIT-01',
  display_name: 'TI SensorTag CC2650',
  manufacturer: 'Texas Instruments',
  model: 'SensorTag CC2650',
  hardware_revision: 'unknown',
  firmware_version: 'unknown',
  protocol: 'BLE advertising',
  logical_address: 'B0:B4:48:C0:36:06',
  address_type: 'public_or_random_not_confirmed',
  local_name: 'SensorTag',
  advertising_identifiers: 'not_observed',
  preferred_channels: [37],
  operator_notes: 'Primer dispositivo piloto.',
  created_at: '2026-07-21T00:00:00Z',
  status: 'active',
};

const modelPlan = [
  ['E5', 'Logistic Regression, Random Forest, SVM RBF, KNN'],
  ['E1', 'CNN1D sobre I/Q alineado a paquetes'],
  ['E3', 'CNN2D / ResNet18 / VGG11 sobre espectrogramas'],
  ['E6', 'Solo si usa exactamente el mismo dataset y split'],
];

const splitPlan = ['capture_disjoint', 'session_disjoint', 'power_cycle_disjoint', 'day_disjoint', 'distance_disjoint'];
const metricPlan = ['balanced accuracy', 'macro-F1', 'AUROC', 'AUPRC', 'TPR', 'FPR', 'FAR', 'FRR', 'EER', 'matriz de confusion', 'metricas por sesion', 'latencia', 'tamano de modelo'];

function normalizeAddress(value?: string | null) {
  return String(value ?? '').toUpperCase();
}

function statusText(value: unknown) {
  if (value == null || value === '') return '-';
  if (typeof value === 'boolean') return value ? 'si' : 'no';
  return String(value).replaceAll('_', ' ');
}

function formatNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toLocaleString() : '-';
}

function shortHash(value: string) {
  if (!value || value === '-') return '-';
  return value.length > 16 ? `${value.slice(0, 12)}...${value.slice(-6)}` : value;
}

function stableToken(value: unknown) {
  return String(value ?? 'unknown').replace(/[^A-Z0-9.-]+/gi, '-').replace(/^-+|-+$/g, '').toUpperCase() || 'UNKNOWN';
}

function qualificationProfile(sdr: BleSdrDevice | null | undefined, durationSeconds: number) {
  const receiver = sdr?.serial_masked ?? sdr?.device_id ?? 'no-sdr';
  const fields = {
    receiver_serial: receiver,
    host_id: 'browser_host_not_available',
    usb_path: 'not_reported_by_frontend',
    storage_target: 'ble_iq_capture_store',
    center_frequency_hz: 2_402_000_000,
    sample_rate_sps: 4_000_000,
    bandwidth_hz: 2_000_000,
    sample_format: 'cf32_le',
    antenna: 'RX2',
    gain_db: 20,
    duration_seconds: durationSeconds,
    capture_software_revision: 'ble-rffi-stage-one-dashboard-v2',
    uhd_version: 'reported_by_backend_after_capture',
  };
  return {
    ...fields,
    qualification_profile_id: `QPROFILE-${stableToken(receiver)}-${fields.center_frequency_hz}-${fields.sample_rate_sps}-${fields.bandwidth_hz}-${fields.sample_format}-${fields.antenna}-G${fields.gain_db}-${fields.duration_seconds}S`,
  };
}

function captureStage(capture: BleCaptureRecord): QualificationPhase | '' {
  const stage = String(capture.experimental_metadata?.stage ?? '');
  return stage === 'ACQUISITION_QUALIFICATION' || stage === 'HYBRID_CONCURRENCY_QUALIFICATION' ? stage : '';
}

function latestByTime<T extends { created_at_utc?: string; updated_at_utc?: string }>(items: T[]) {
  return [...items].sort((left, right) => String(right.updated_at_utc ?? right.created_at_utc ?? '').localeCompare(String(left.updated_at_utc ?? left.created_at_utc ?? '')));
}

function padId(prefix: string, value: number) {
  return `${prefix}${String(Math.max(1, value)).padStart(3, '0')}`;
}

function todayId() {
  return new Date().toISOString().slice(0, 10);
}

function campaignMatrix(): MatrixCondition[] {
  const distances = ['0.50 m', '1 m', '1.50 m'];
  const orientations = ['0', '90', '180'];
  let index = 0;
  return distances.flatMap((distance) => orientations.map((orientation) => {
    index += 1;
    const baseSession = padId('S', index);
    return {
      index,
      condition_id: padId('C', index),
      day_id: todayId(),
      positive_session_id: `${baseSession}-POS`,
      negative_session_id: `${baseSession}-NEG`,
      power_cycle_id: padId('PC', index),
      distance,
      orientation,
      location: 'LAB-A',
      operator_notes: '',
      environment_notes: '',
      relevant_obstacles: 'not_observed',
      receiver_position: 'fixed',
      transmitter_position: 'matrix_position',
    };
  }));
}

function profileCampaignId(profile: DeviceProfile) {
  const token = profile.physical_unit_id.replace(/[^A-Z0-9]+/gi, '-').toUpperCase();
  return `BLE-RFFI-${token}-CH37-v1`;
}

function profileDatasetId(profile: DeviceProfile) {
  const token = profile.physical_unit_id.replace(/[^A-Z0-9]+/gi, '-').toUpperCase();
  return `BLE-RFFI-${token}-DS01`;
}

function targetLabel(profile: DeviceProfile) {
  return `TARGET_${profile.physical_unit_id.replace(/[^A-Z0-9]+/gi, '_').toUpperCase()}`;
}

function protocolRows(profile: DeviceProfile) {
  return [
    ['base_protocol', BASE_PROTOCOL_ID],
    ['campaign_protocol', profileCampaignId(profile)],
    ['device_profile_id', profile.device_profile_id],
    ['physical_unit_id', profile.physical_unit_id],
    ['logical_address', profile.logical_address || 'not_observed'],
    ['labels', `${targetLabel(profile)} / BACKGROUND_UNKNOWN`],
    ['channel', String(profile.preferred_channels[0] ?? 37)],
    ['center_frequency_hz', '2402000000'],
    ['sample_rate_sps', '4000000'],
    ['bandwidth_hz', '2000000'],
    ['antenna', 'RX2'],
    ['sample_format', 'cf32_le'],
    ['duration_seconds', 'protocol_parameter_locked_per_condition_pair'],
    ['qualification_stage', 'ACQUISITION_QUALIFICATION'],
    ['qualification_repetitions', String(QUALIFICATION_REQUIRED_CLEAN)],
    ['qualification_duration_seconds', String(QUALIFICATION_CAPTURE_SECONDS)],
    ['minimum_target_crc_packets', String(MINIMUM_TARGET_CRC_PACKETS)],
    ['minimum_target_strong_matches', String(MINIMUM_TARGET_STRONG_MATCHES)],
    ['minimum_unique_target_packets_for_e4_observation', String(MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION)],
    ['minimum_unique_target_packets_for_dataset_acceptance', String(MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE)],
    ['quality_gate_version', POSITIVE_PILOT_QUALITY_GATE_VERSION],
    ['principal_split', 'session_disjoint'],
  ];
}

function loadProfiles(): DeviceProfile[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PROFILE_STORAGE_KEY) || '[]') as DeviceProfile[];
    return parsed.length ? parsed : [defaultProfile];
  } catch {
    return [defaultProfile];
  }
}

function loadActiveProfileId() {
  return window.localStorage.getItem(ACTIVE_PROFILE_STORAGE_KEY) || defaultProfile.device_profile_id;
}

function apiErrorMessage(error: unknown) {
  const response = (error as { response?: { data?: unknown; status?: number } })?.response;
  const detail = (response?.data as { detail?: unknown })?.detail;
  if (typeof detail === 'string') return detail;
  if (detail) return JSON.stringify(detail);
  return error instanceof Error ? error.message : String(error);
}

function sessionConditionId(session: BleHybridSession) {
  const metadata = session.experimental_metadata ?? {};
  const id = metadata.condition_id ?? metadata.operator_session_id ?? metadata.session_id;
  return typeof id === 'string' ? id : '';
}

function sessionOperatorId(session: BleHybridSession) {
  const metadata = session.experimental_metadata ?? {};
  const id = metadata.operator_session_id ?? metadata.session_id;
  return typeof id === 'string' ? id : session.session_id;
}

function isStageOneSession(session: BleHybridSession, profile?: DeviceProfile) {
  const metadata = session.experimental_metadata ?? {};
  if (metadata.base_protocol_id !== BASE_PROTOCOL_ID && metadata.protocol_id !== BASE_PROTOCOL_ID) return false;
  return profile ? metadata.device_profile_id === profile.device_profile_id && metadata.physical_unit_id === profile.physical_unit_id : true;
}

function isCleanSession(session: BleHybridSession, summary?: BleScientificSummary) {
  const overflows = Number(session.counters?.overflows ?? summary?.acquisition?.overflow_count ?? 0);
  const discontinuities = Number(session.counters?.discontinuities ?? summary?.acquisition?.discontinuity_count ?? 0);
  return session.state === 'completed' && overflows === 0 && discontinuities === 0;
}

function isProcessingSession(session: BleHybridSession) {
  return !terminalStates.has(session.state);
}

function positiveDecision(session?: BleHybridSession, summary?: BleScientificSummary) {
  if (!session) return { result: 'PENDING', reason: 'No se ha ejecutado la captura positiva.', action: 'Buscar y confirmar objetivo.' };
  if (isProcessingSession(session)) return { result: 'PROCESSING', reason: `Pipeline en curso: ${statusText(session.state)}.`, action: 'Espere a que terminen CRC, correlacion, QC y resumen.' };
  if (session.state === 'cancelled') return { result: 'CANCELLED_BY_OPERATOR', reason: session.error || 'Cancelada por operador.', action: 'Repita la captura positiva si la condicion sigue siendo valida.' };
  if (session.state === 'failed' || session.state === 'timed_out') return { result: 'CAPTURE_FAILED', reason: session.error || session.state, action: 'Revise hardware, libere B200 y repita la condicion.' };
  if (!summary) return { result: 'SUMMARY_PENDING', reason: 'La adquisicion termino, pero falta el resumen cientifico; la procedencia sigue pendiente.', action: 'Espere o regenere el resumen antes de decidir elegibilidad.' };
  if (summary.target?.status === 'TARGET_NOT_OBSERVED') return { result: 'TARGET_NOT_OBSERVED', reason: 'Windows/B200 no corroboraron el objetivo declarado.', action: 'Despierte el SensorTag, confirme preflight y repita.' };
  const targetCrc = Number(summary.funnel?.target_crc_valid_packets ?? summary.target?.b200_crc_packets ?? 0);
  const targetStrongMatches = Number(summary.funnel?.target_strong_matches ?? summary.target?.strong_matches ?? session.counters?.strong_matches ?? 0);
  const uniqueStrongOnlyTargetCrc = Number(summary.funnel?.unique_strong_only_target_crc_packets ?? summary.target?.unique_strong_only_target_crc_packets ?? summary.funnel?.unique_target_crc_packets_with_strong_association ?? summary.target?.unique_target_crc_packets_with_strong_association ?? targetStrongMatches);
  const minimumDatasetAcceptance = Number(summary.protocol?.minimum_unique_target_packets_for_dataset_acceptance ?? MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE);
  const passed = summary.terminal_status === 'COMPLETED'
    && summary.ground_truth_status === 'PASSED_E4'
    && targetCrc >= Number(summary.protocol?.minimum_target_crc_packets ?? MINIMUM_TARGET_CRC_PACKETS)
    && targetStrongMatches >= Number(summary.protocol?.minimum_target_strong_matches ?? MINIMUM_TARGET_STRONG_MATCHES)
    && uniqueStrongOnlyTargetCrc >= minimumDatasetAcceptance
    && summary.acquisition_quality_status === 'PASSED'
    && summary.protocol_conformance_status === 'PASSED'
    && summary.metadata_status === 'COMPLETE'
    && summary.artifact_integrity_status === 'VERIFIED'
    && summary.summary_status === 'COMPLETE'
    && summary.dataset_eligibility_status === 'ELIGIBLE'
    && isCleanSession(session, summary);
  if (passed) return { result: 'POSITIVE_ACCEPTED', reason: 'Objetivo E4 corroborado, umbrales cumplidos y captura elegible.', action: 'Ejecute el control negativo de la misma condicion.' };
  const codes = summary.final_reason_codes?.length ? summary.final_reason_codes.join(',') : 'STRICT_E4_GATE_NOT_PASSED';
  return { result: 'POSITIVE_QUARANTINED', reason: `quarantine_reason_codes=[${codes}]; recoverable=true.`, action: 'No desbloquea el negativo; repita la positiva o revise artefactos.' };
}

function negativeDecision(session?: BleHybridSession, summary?: BleScientificSummary) {
  if (!session) return { result: 'PENDING', reason: 'No se ha ejecutado el control negativo.', action: 'Apague el objetivo y verifique ausencia.' };
  if (isProcessingSession(session)) return { result: 'PROCESSING', reason: `Pipeline en curso: ${statusText(session.state)}.`, action: 'Espere decision de control negativo.' };
  if (session.state === 'cancelled') return { result: 'CANCELLED_BY_OPERATOR', reason: session.error || 'Cancelada por operador.', action: 'Repita el control negativo si la condicion sigue siendo valida.' };
  if (session.state === 'failed' || session.state === 'timed_out') return { result: 'CAPTURE_FAILED', reason: session.error || session.state, action: 'Revise hardware, libere B200 y repita el control.' };
  if (!summary) return { result: 'SUMMARY_PENDING', reason: 'La adquisicion negativa termino, pero falta el resumen cientifico.', action: 'Espere o regenere el resumen antes de decidir elegibilidad.' };
  const negative = summary?.negative_control;
  if (Number(negative?.target_native_observations ?? 0) > 0 || Number(negative?.target_b200_crc_valid_packets ?? 0) > 0 || Number(negative?.false_target_attributions ?? 0) > 0) {
    return { result: 'NEGATIVE_CONTROL_FAILED_TARGET_SEEN', reason: 'El objetivo aparecio durante la campana negativa.', action: 'No aceptar etiqueta negativa; apague/retire el objetivo y repita.' };
  }
  if (negative?.training_ready === true || (negative?.clean_capture === true && negative.result?.includes('PASSED'))) {
    return { result: 'NEGATIVE_ACCEPTED', reason: 'Control negativo declarado sin atribucion al objetivo.', action: 'Avance a la siguiente condicion.' };
  }
  if (session.state === 'completed') return { result: 'NEGATIVE_QUARANTINED', reason: 'Control terminado pero no apto para entrenamiento.', action: 'Revise QC y repita si hace falta.' };
  return { result: 'PENDING', reason: 'Control negativo pendiente.', action: 'Espere decision.' };
}

function positiveGateSummary(session?: BleHybridSession, summary?: BleScientificSummary) {
  const metadata = session?.experimental_metadata ?? {};
  const overflows = Number(session?.counters?.overflows ?? summary?.acquisition?.overflow_count ?? 0);
  const discontinuities = Number(session?.counters?.discontinuities ?? summary?.acquisition?.discontinuity_count ?? 0);
  const captureQuality = session && session.state === 'completed' && overflows === 0 && discontinuities === 0 ? 'ACCEPTED' : session && isProcessingSession(session) ? 'PENDING' : 'BLOCKED';
  const effectiveClaimLevel = String(summary?.effective_claim_level ?? summary?.evidence_level ?? 'PENDING');
  const maximumObservedEvidenceLevel = String(summary?.maximum_observed_evidence_level ?? summary?.target?.maximum_observed_evidence_level ?? 'PENDING');
  const associationEvidenceStatus = String(summary?.association_evidence_status ?? 'PENDING');
  const targetStrongMatches = Number(summary?.funnel?.target_strong_matches ?? summary?.target?.strong_matches ?? session?.counters?.strong_matches ?? 0);
  const targetCrcPackets = Number(summary?.funnel?.target_crc_valid_packets ?? summary?.target?.b200_crc_packets ?? 0);
  const uniqueTargetStrongCrc = Number(summary?.funnel?.unique_target_crc_packets_with_strong_association ?? summary?.target?.unique_target_crc_packets_with_strong_association ?? targetStrongMatches);
  const uniqueStrongOnlyTargetCrc = Number(summary?.funnel?.unique_strong_only_target_crc_packets ?? summary?.target?.unique_strong_only_target_crc_packets ?? uniqueTargetStrongCrc);
  const groundTruth = summary?.ground_truth_status ?? (effectiveClaimLevel === 'E4' && targetStrongMatches > 0 ? 'PASSED_E4' : summary ? 'INSUFFICIENT_FOR_ACCEPTED_E4' : session ? 'SUMMARY_PENDING' : 'PENDING');
  const summaryStatus = summary ? 'COMPLETE' : session?.state === 'completed' ? 'SUMMARY_PENDING' : session ? 'PROCESSING' : 'PENDING';
  const eligible = captureQuality === 'ACCEPTED' && groundTruth === 'PASSED_E4' && summaryStatus === 'COMPLETE';
  return {
    acquisition_quality_status: summary?.acquisition_quality_status ?? summary?.signal_quality_status ?? (captureQuality === 'ACCEPTED' ? 'PASSED' : captureQuality),
    protocol_conformance_status: summary?.protocol_conformance_status ?? (metadata.condition_id && metadata.operator_session_id ? 'PASSED' : 'METADATA_PENDING'),
    ground_truth_status: groundTruth,
    provenance_status: summary?.artifact_integrity_status ?? summaryStatus,
    metadata_status: summary?.metadata_status ?? (metadata.condition_id && metadata.operator_session_id && metadata.physical_unit_id ? 'COMPLETE' : 'INCOMPLETE'),
    summary_status: summary?.summary_status ?? summaryStatus,
    dataset_eligibility_status: summary?.dataset_eligibility_status ?? (eligible ? 'ELIGIBLE' : summaryStatus === 'SUMMARY_PENDING' ? 'BLOCKED_PENDING_ARTIFACT' : 'NOT_ELIGIBLE'),
    target_result: summary?.target_result ?? summary?.target?.status ?? 'PENDING',
    reason_codes: summary?.final_reason_codes ?? [],
    maximum_observed_evidence_level: maximumObservedEvidenceLevel,
    e4_observation_status: summary?.e4_observation_status ?? (uniqueTargetStrongCrc >= MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION ? 'E4_MINIMAL_OBSERVED' : 'NOT_OBSERVED'),
    e4_dataset_acceptance_status: summary?.e4_dataset_acceptance_status ?? (uniqueStrongOnlyTargetCrc >= MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE ? 'E4_ACCEPTED_FOR_DATASET' : 'NOT_ACCEPTED_FOR_DATASET'),
    association_evidence_status: associationEvidenceStatus,
    effective_claim_level: effectiveClaimLevel,
    target_strong_matches: targetStrongMatches,
    unique_target_crc_packets_with_strong_association: uniqueTargetStrongCrc,
    unique_strong_only_target_crc_packets: uniqueStrongOnlyTargetCrc,
    unique_target_crc_packets_with_ambiguous_association: Number(summary?.funnel?.unique_target_crc_packets_with_ambiguous_association ?? summary?.target?.unique_target_crc_packets_with_ambiguous_association ?? summary?.funnel?.target_ambiguous_matches ?? 0),
    unique_target_crc_packets_with_conflicting_association: Number(summary?.funnel?.unique_target_crc_packets_with_conflicting_association ?? summary?.target?.unique_target_crc_packets_with_conflicting_association ?? 0),
    target_association_conflict_count: Number(summary?.funnel?.target_association_conflict_count ?? summary?.target?.target_association_conflict_count ?? 0),
    target_ambiguous_matches: Number(summary?.funnel?.target_ambiguous_matches ?? summary?.target?.ambiguous_matches ?? 0),
    target_crc_valid_packets: targetCrcPackets,
    total_crc_valid_packets: Number(summary?.funnel?.total_crc_valid_packets ?? summary?.funnel?.crc_valid_packets ?? session?.counters?.crc_valid_packets ?? 0),
    environmental_crc_valid_packets: Number(summary?.funnel?.environmental_crc_valid_packets ?? 0),
    environmental_strong_matches: Number(summary?.funnel?.environmental_strong_matches ?? summary?.funnel?.environmental_matches ?? 0),
    unattributed_crc_valid_packets: Number(summary?.funnel?.unattributed_crc_valid_packets ?? 0),
    ambiguity_reason_codes: summary?.ambiguity_reason_codes ?? (Array.isArray(summary?.target?.ambiguity_reason_codes) ? summary.target.ambiguity_reason_codes as string[] : []),
    overflows,
    discontinuities,
    metadata_complete: (summary?.metadata_status ?? '') === 'COMPLETE' || Boolean(metadata.condition_id && metadata.operator_session_id && metadata.physical_unit_id),
    preflight_valid_at_capture_start: statusText(metadata.preflight_valid_at_capture_start),
    preflight_age_at_capture_start_seconds: statusText(metadata.preflight_age_at_capture_start_seconds),
    target_seen_during_capture: statusText(metadata.target_seen_during_capture),
    protocol_duration_seconds: statusText(summary?.protocol?.protocol_duration_seconds ?? metadata.protocol_duration_seconds),
    effective_duration_seconds: statusText(summary?.protocol?.effective_duration_seconds ?? metadata.effective_duration_seconds),
    protocol_revision: statusText(summary?.protocol?.protocol_revision ?? metadata.protocol_revision),
    protocol_override: statusText(summary?.protocol?.protocol_override ?? metadata.protocol_override),
    capture_id: session?.capture_id ?? '-',
    execution_id: session?.session_id ?? '-',
    source_repository_commit: statusText(summary?.protocol?.source_repository_commit ?? metadata.source_repository_commit),
    source_working_tree_status: statusText(summary?.protocol?.source_working_tree_status ?? metadata.source_working_tree_status),
    source_working_tree_diff_sha256: statusText(summary?.protocol?.source_working_tree_diff_sha256 ?? metadata.source_working_tree_diff_sha256),
    protocol_manifest_sha256: statusText(summary?.protocol?.protocol_manifest_sha256 ?? metadata.protocol_manifest_sha256),
    quality_gate_version: statusText(summary?.quality_gate_version ?? summary?.protocol?.quality_gate_version ?? metadata.quality_gate_version),
    qualification_profile_id: statusText(metadata.qualification_profile_id),
    actual_samples: statusText(summary?.acquisition?.captured_samples ?? summary?.acquisition?.actual_samples),
    actual_file_size_bytes: statusText(summary?.acquisition?.actual_file_size_bytes ?? summary?.acquisition?.bytes),
    short_read_count: statusText(summary?.acquisition?.short_read_count ?? 0),
    write_error_count: statusText(summary?.acquisition?.write_error_count ?? 0),
    writer_queue_overrun_count: statusText(summary?.acquisition?.writer_queue_overrun_count ?? 0),
    hash_status: statusText(summary?.acquisition?.hash_status ?? summary?.artifact_integrity_status),
  };
}

function isCleanCapture(capture: BleCaptureRecord) {
  const discontinuities = Number(capture.input_discontinuities ?? 0);
  return capture.capture_complete === true
    && Number(capture.ble_channel) === 37
    && Number(capture.overflow_count ?? 0) === 0
    && discontinuities === 0;
}

function captureReason(capture: BleCaptureRecord) {
  if (!capture.capture_complete) return 'captura incompleta';
  if (Number(capture.ble_channel) !== 37) return 'no es CH37';
  if (Number(capture.overflow_count ?? 0) > 0) return `overflow=${capture.overflow_count}`;
  if (Number(capture.input_discontinuities ?? 0) > 0) return `discontinuidades=${capture.input_discontinuities}`;
  return 'apta por calidad basica';
}

function isQualificationCapture(capture: BleCaptureRecord) {
  const metadata = capture.experimental_metadata ?? {};
  return metadata.stage === 'ACQUISITION_QUALIFICATION'
    || metadata.stage === 'HYBRID_CONCURRENCY_QUALIFICATION'
    || capture.purpose === 'BLE-RFFI acquisition qualification';
}

function qualificationActualSamples(capture: BleCaptureRecord) {
  const actual = Number(capture.actual_samples);
  if (Number.isFinite(actual) && actual > 0) return actual;
  return Math.floor(Number(capture.actual_size_bytes ?? 0) / 8);
}

function isCleanQualificationCapture(capture: BleCaptureRecord, phase?: QualificationPhase, profileId?: string) {
  const metadata = capture.experimental_metadata ?? {};
  const expectedSize = Number(capture.expected_file_size_bytes ?? capture.expected_file_size ?? QUALIFICATION_EXPECTED_FILE_SIZE);
  const actualSize = Number(capture.actual_file_size_bytes ?? capture.actual_size_bytes);
  const discontinuities = Number(capture.discontinuity_count ?? capture.input_discontinuities ?? 0);
  const stage = captureStage(capture);
  const baseClean = isQualificationCapture(capture)
    && (!phase || stage === phase)
    && (!profileId || String(capture.qualification_profile_id ?? metadata.qualification_profile_id ?? '') === profileId)
    && capture.capture_complete === true
    && Number(capture.sample_rate_sps) === 4_000_000
    && Number(capture.center_frequency_hz) === 2_402_000_000
    && Number(capture.bandwidth_hz) === 2_000_000
    && String(capture.sample_format ?? 'cf32_le') === 'cf32_le'
    && qualificationActualSamples(capture) === QUALIFICATION_EXPECTED_SAMPLES
    && expectedSize === QUALIFICATION_EXPECTED_FILE_SIZE
    && actualSize === QUALIFICATION_EXPECTED_FILE_SIZE
    && Number(capture.overflow_count ?? 0) === 0
    && discontinuities === 0
    && Number(capture.short_read_count ?? 0) === 0
    && Number(capture.write_error_count ?? 0) === 0
    && String(capture.hash_status ?? '') === 'VERIFIED'
    && String(capture.metadata_status ?? '') === 'COMPLETE';
  if (!baseClean) return false;
  if (stage !== 'HYBRID_CONCURRENCY_QUALIFICATION') return true;
  const rfDuration = Number(capture.b200_rf_duration_seconds ?? metadata.b200_rf_duration_seconds);
  const rfOverlapSeconds = Number(capture.rf_concurrency_overlap_seconds ?? metadata.rf_concurrency_overlap_seconds);
  const rfOverlapFraction = Number(capture.rf_concurrency_overlap_fraction ?? metadata.rf_concurrency_overlap_fraction);
  return rfDuration === QUALIFICATION_CAPTURE_SECONDS
    && Number.isFinite(rfOverlapSeconds)
    && Number.isFinite(rfOverlapFraction)
    && rfOverlapSeconds >= MINIMUM_RF_CONCURRENCY_OVERLAP_SECONDS
    && rfOverlapSeconds <= QUALIFICATION_CAPTURE_SECONDS
    && rfOverlapFraction >= MINIMUM_RF_CONCURRENCY_OVERLAP_FRACTION
    && rfOverlapFraction <= 1;
}

function qualificationStatus(captures: BleCaptureRecord[], phase: QualificationPhase, profileId: string): QualificationStatus {
  const ordered = [...captures]
    .filter((capture) => captureStage(capture) === phase && String(capture.qualification_profile_id ?? capture.experimental_metadata?.qualification_profile_id ?? '') === profileId)
    .sort((left, right) => String(left.created_at_utc ?? '').localeCompare(String(right.created_at_utc ?? '')));
  let cleanConsecutive = 0;
  let failureConsecutive = 0;
  let latestFailure: BleCaptureRecord | undefined;
  for (const capture of ordered) {
    if (isCleanQualificationCapture(capture, phase, profileId)) {
      cleanConsecutive += 1;
      failureConsecutive = 0;
    } else {
      cleanConsecutive = 0;
      failureConsecutive += 1;
      latestFailure = capture;
    }
  }
  return {
    phase,
    cleanConsecutive,
    failureConsecutive,
    totalForProfile: ordered.length,
    passed: cleanConsecutive >= QUALIFICATION_REQUIRED_CLEAN,
    latest: ordered[ordered.length - 1],
    latestFailure,
  };
}

function isContinuityFailure(capture?: BleCaptureRecord) {
  return Boolean(capture) && (Number(capture?.overflow_count ?? 0) > 0 || Number(capture?.input_discontinuities ?? capture?.discontinuity_count ?? 0) > 0);
}

function diagnosticStep(capture: BleCaptureRecord): DiagnosticStepId | '' {
  const step = String(capture.diagnostic_step ?? capture.experimental_metadata?.diagnostic_step ?? '');
  return diagnosticSteps.some((item) => item.id === step) ? step as DiagnosticStepId : '';
}

function isDiagnosticCapture(capture: BleCaptureRecord) {
  return String(capture.experimental_metadata?.stage ?? '') === 'ACQUISITION_DIAGNOSTIC' || Boolean(diagnosticStep(capture));
}

function diagnosticCaptureStatus(capture?: BleCaptureRecord) {
  if (!capture) return 'PENDING';
  if (!capture.capture_complete) return 'FAILED';
  return isContinuityFailure(capture) ? 'FAILED' : 'PASSED';
}

function diagnosticInterpretation(step: DiagnosticStepId) {
  const table: Record<DiagnosticStepId, { passed: string; failed: string; unresolved: string[]; passedAction: string; failedAction: string }> = {
    A_RECEIVER_TRANSPORT: {
      passed: 'El receptor esta detectado por la plataforma. Esto no demuestra todavia continuidad de streaming.',
      failed: 'No se puede confirmar receptor disponible o acceso suficiente.',
      unresolved: ['velocidad USB exacta', 'otro proceso SDR no visible', 'buffers UHD', 'carga del host'],
      passedAction: 'Continuar con streaming sin escritura a disco.',
      failedAction: 'Revise conexion USB 3 directa, driver UHD y procesos que puedan usar el B200.',
    },
    B_STREAM_NO_DISK: {
      passed: 'No hubo perdidas antes de escribir a disco; la persistencia queda como posible factor a aislar.',
      failed: 'Las perdidas aparecen sin escritura a disco. La causa posible esta antes de persistir: USB, UHD, buffers, CPU o recepcion.',
      unresolved: ['USB/UHD', 'buffers', 'CPU', 'recepcion RF', 'planificacion del sistema operativo'],
      passedAction: 'Continuar con persistencia minima.',
      failedAction: 'No repita cualificacion. Revise transporte USB/UHD, buffers y carga del host.',
    },
    C_PERSISTENCE_MINIMAL: {
      passed: 'Streaming con escritura minima no introdujo perdidas bajo esta prueba.',
      failed: 'Streaming limpio sin disco pero con perdidas al guardar sugiere revisar almacenamiento, persistencia o copias de memoria.',
      unresolved: ['rendimiento de disco', 'latencia de escritura', 'copias de memoria', 'antivirus/indexacion'],
      passedAction: 'Continuar con interfaz y monitorizacion normal.',
      failedAction: 'Revise almacenamiento antes de reintentar cualificacion.',
    },
    D_INTERFACE_MONITORING: {
      passed: 'La interfaz y el polling normal no introdujeron perdidas en esta prueba.',
      failed: 'La captura limpia sin interfaz pero fallida con interfaz sugiere revisar polling, preview o concurrencia backend.',
      unresolved: ['polling API', 'preview FFT', 'lectores de live.json', 'carga concurrente'],
      passedAction: 'Volver a ejecutar la cualificacion B200-only.',
      failedAction: 'Reduzca monitorizacion/preview antes de reintentar cualificacion.',
    },
    E_ALT_FORMAT: {
      passed: 'El formato alternativo fue limpio; el problema puede ser sensible a caudal o formato.',
      failed: 'El formato alternativo tambien presenta perdidas; no se puede atribuir solo a cf32_le.',
      unresolved: ['caudal USB', 'buffers', 'CPU', 'driver', 'host'],
      passedAction: 'Decidir explicitamente si corregir infraestructura cf32_le o crear nueva revision de protocolo.',
      failedAction: 'Corregir infraestructura antes de cambiar el protocolo cientifico.',
    },
  };
  return table[step];
}

function distanceMeters(value: string) {
  const numeric = Number(String(value).replace(',', '.').replace(/[^0-9.]+/g, ''));
  return Number.isFinite(numeric) ? numeric : Number.NaN;
}

function validateCondition(condition: MatrixCondition, profile: DeviceProfile, matrix: MatrixCondition[]) {
  const issues: string[] = [];
  const distance = distanceMeters(condition.distance);
  const orientation = Number(condition.orientation);
  if (!profile.physical_unit_id.trim()) issues.push('physical_unit_id obligatorio');
  if (!condition.condition_id.trim()) issues.push('condition_id obligatorio');
  if (!condition.positive_session_id.trim()) issues.push('positive_session_id obligatorio');
  if (!condition.negative_session_id.trim()) issues.push('negative_session_id obligatorio');
  if (condition.positive_session_id === condition.negative_session_id) issues.push('positive_session_id y negative_session_id deben ser distintos');
  if (!Number.isFinite(distance) || distance <= 0) issues.push('distance_m debe ser mayor que 0');
  if (!Number.isInteger(orientation) || orientation < 0 || orientation > 359) issues.push('orientation_deg debe estar entre 0 y 359');
  if (!condition.location.trim()) issues.push('location_id obligatorio');
  if (!condition.power_cycle_id.trim()) issues.push('power_cycle_id obligatorio');
  const duplicatedCondition = matrix.filter((item) => item.condition_id === condition.condition_id).length > 1;
  const duplicatedPositive = matrix.filter((item) => item.positive_session_id === condition.positive_session_id).length > 1;
  const duplicatedNegative = matrix.filter((item) => item.negative_session_id === condition.negative_session_id).length > 1;
  if (duplicatedCondition) issues.push(`condition_id duplicado: ${condition.condition_id}`);
  if (duplicatedPositive) issues.push(`positive_session_id duplicado: ${condition.positive_session_id}`);
  if (duplicatedNegative) issues.push(`negative_session_id duplicado: ${condition.negative_session_id}`);
  return issues;
}

function stageOrder(step: CampaignStep) {
  return ['device', 'qualification', 'prepare', 'replay', 'positive', 'negative', 'repeat', 'dataset'].indexOf(step);
}

export default function BleRffiStageOneDashboard() {
  const [profiles, setProfiles] = useState<DeviceProfile[]>(() => loadProfiles());
  const [selectedProfileId, setSelectedProfileId] = useState(() => loadActiveProfileId());
  const selectedProfile = profiles.find((profile) => profile.device_profile_id === selectedProfileId) ?? profiles[0] ?? defaultProfile;
  const [showIntro, setShowIntro] = useState(() => window.localStorage.getItem(INTRO_STORAGE_KEY) !== 'true');
  const [native, setNative] = useState<BleNativeStatus | null>(null);
  const [caps, setCaps] = useState<BleCaptureCapabilities | null>(null);
  const [devices, setDevices] = useState<BleNativeDevice[]>([]);
  const [sessions, setSessions] = useState<BleHybridSession[]>([]);
  const [captures, setCaptures] = useState<BleCaptureRecord[]>([]);
  const [rfDiagnostic, setRfDiagnostic] = useState<BleRfDiagnostic | null>(null);
  const [offlineReplay, setOfflineReplay] = useState<BleOfflineReplay | null>(null);
  const [offlineReplayJob, setOfflineReplayJob] = useState<BleOfflineReplayJob | null>(null);
  const [rfDiagnosticProfiles, setRfDiagnosticProfiles] = useState<Record<string, unknown> | null>(null);
  const [summaries, setSummaries] = useState<Record<string, BleScientificSummary>>({});
  const [dataset, setDataset] = useState<BleDatasetDetail | null>(null);
  const [datasetKnown, setDatasetKnown] = useState(false);
  const [activeSession, setActiveSession] = useState<BleHybridSession | null>(null);
  const [absence, setAbsence] = useState<AbsenceVerification | null>(null);
  const [operatorConfirmed, setOperatorConfirmed] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('Campana');
  const [conditionOverrides, setConditionOverrides] = useState<Record<string, Partial<MatrixCondition>>>({});
  const [metadataMode, setMetadataMode] = useState<'matrix' | 'edit'>('matrix');
  const [profileDraft, setProfileDraft] = useState<DeviceProfile>(() => ({ ...defaultProfile, device_profile_id: `ble-profile-${Date.now()}`, physical_unit_id: '', display_name: '', logical_address: '', created_at: new Date().toISOString(), operator_notes: '' }));
  const [operationEvents, setOperationEvents] = useState<OperationEvent[]>([]);
  const [captureDurationSeconds, setCaptureDurationSeconds] = useState(DEFAULT_CAPTURE_SECONDS);
  const [qualificationJob, setQualificationJob] = useState<BleCaptureJob | null>(null);
  const [qualificationLive, setQualificationLive] = useState<BleCaptureLive | null>(null);
  const [positiveWizardStarted, setPositiveWizardStarted] = useState(false);
  const [positiveDeviceConfirmed, setPositiveDeviceConfirmed] = useState(false);
  const [positiveConditionSaved, setPositiveConditionSaved] = useState(false);
  const [positivePositionPrepared, setPositivePositionPrepared] = useState(false);
  const [positivePhysicalPrepared, setPositivePhysicalPrepared] = useState(false);
  const [targetPowerConfirmedAt, setTargetPowerConfirmedAt] = useState<string | null>(null);

  const matrix = useMemo(() => campaignMatrix(), []);
  const effectiveMatrix = matrix.slice(0, 1).map((condition) => ({ ...condition, ...(conditionOverrides[condition.condition_id] ?? {}) }));
  const target = useMemo(() => devices.find((device) => selectedProfile.logical_address && normalizeAddress(device.address) === normalizeAddress(selectedProfile.logical_address)) ?? null, [devices, selectedProfile.logical_address]);
  const sdr = caps?.devices.find((device) => device.available) ?? null;
  const stageOneSessions = useMemo(() => sessions.filter((session) => isStageOneSession(session, selectedProfile)), [sessions, selectedProfile]);
  const historicalSessions = useMemo(() => sessions.filter((session) => !isStageOneSession(session, selectedProfile)), [sessions, selectedProfile]);
  const active = Boolean(activeSession && !terminalStates.has(activeSession.state));
  const targetAgeMs = target?.last_seen_utc ? Date.now() - new Date(target.last_seen_utc).getTime() : Number.POSITIVE_INFINITY;
  const targetSeenInCurrentScan = Boolean(target && native?.scan_session_id && target.scan_session_id === native.scan_session_id);
  const preflightValid = targetSeenInCurrentScan && targetAgeMs <= PREFLIGHT_VALID_MS;
  const campaignId = profileCampaignId(selectedProfile);
  const datasetId = profileDatasetId(selectedProfile);
  const datasetManifest = (dataset?.manifest ?? dataset) as Record<string, unknown> | null;
  const maxCaptureSeconds = Math.max(DEFAULT_CAPTURE_SECONDS, Number(caps?.maximum_duration_seconds ?? 120));
  const captureSeconds = Math.max(3, Math.min(maxCaptureSeconds, Math.round(Number(captureDurationSeconds) || DEFAULT_CAPTURE_SECONDS)));
  const qualificationProfile10s = useMemo(() => qualificationProfile(sdr, QUALIFICATION_CAPTURE_SECONDS), [sdr]);
  const campaignQualificationProfile = useMemo(() => qualificationProfile(sdr, captureSeconds), [sdr, captureSeconds]);
  const qualificationProfileMatchesCampaign = qualificationProfile10s.qualification_profile_id === campaignQualificationProfile.qualification_profile_id;
  const qualificationCaptures = useMemo(() => captures.filter(isQualificationCapture), [captures]);
  const b200QualificationStatus = useMemo(() => qualificationStatus(qualificationCaptures, 'ACQUISITION_QUALIFICATION', qualificationProfile10s.qualification_profile_id), [qualificationCaptures, qualificationProfile10s.qualification_profile_id]);
  const hybridQualificationStatus = useMemo(() => qualificationStatus(qualificationCaptures, 'HYBRID_CONCURRENCY_QUALIFICATION', qualificationProfile10s.qualification_profile_id), [qualificationCaptures, qualificationProfile10s.qualification_profile_id]);
  const qualificationPassed = b200QualificationStatus.passed && hybridQualificationStatus.passed && qualificationProfileMatchesCampaign;
  const diagnosticRequired = !b200QualificationStatus.passed && b200QualificationStatus.failureConsecutive >= QUALIFICATION_REQUIRED_CLEAN;
  const diagnosticCaptures = useMemo(() => captures.filter(isDiagnosticCapture), [captures]);
  const latestDiagnosticByStep = useMemo(() => {
    const entries = new Map<DiagnosticStepId, BleCaptureRecord>();
    for (const capture of [...diagnosticCaptures].sort((left, right) => String(left.created_at_utc ?? '').localeCompare(String(right.created_at_utc ?? '')))) {
      const step = diagnosticStep(capture);
      if (step) entries.set(step, capture);
    }
    return entries;
  }, [diagnosticCaptures]);
  const [diagnosticAResult, setDiagnosticAResult] = useState<DiagnosticResult | null>(null);
  const diagnosticResults = useMemo<Record<DiagnosticStepId, DiagnosticResult>>(() => {
    const makeCaptureResult = (step: DiagnosticStepId): DiagnosticResult => {
      const capture = latestDiagnosticByStep.get(step);
      const status = diagnosticCaptureStatus(capture) as DiagnosticResult['status'];
      const loss = isContinuityFailure(capture);
      const base = diagnosticSteps.find((item) => item.id === step)!;
      return {
        step,
        status,
        capture_id: capture?.capture_id,
        observed_result: !capture ? 'No ejecutado' : loss ? `Perdidas: ${formatNumber(capture.overflow_count)} overflows y ${formatNumber(capture.input_discontinuities ?? capture.discontinuity_count)} discontinuidades` : 'Sin perdidas notificadas',
        supported_interpretation: !capture ? base.objective : loss ? diagnosticInterpretation(step).failed : diagnosticInterpretation(step).passed,
        unresolved_alternatives: diagnosticInterpretation(step).unresolved,
        recommended_next_action: !capture ? `Ejecutar ${base.title}` : loss ? diagnosticInterpretation(step).failedAction : diagnosticInterpretation(step).passedAction,
      };
    };
    return {
      A_RECEIVER_TRANSPORT: diagnosticAResult ?? {
        step: 'A_RECEIVER_TRANSPORT',
        status: 'PENDING',
        observed_result: 'Pendiente',
        supported_interpretation: 'Todavia no se ha comprobado receptor, driver, UHD/USB y acceso exclusivo.',
        unresolved_alternatives: ['USB/UHD', 'buffers', 'CPU', 'otro proceso SDR', 'escritura a disco'],
        recommended_next_action: 'Iniciar diagnostico de adquisicion',
      },
      B_STREAM_NO_DISK: makeCaptureResult('B_STREAM_NO_DISK'),
      C_PERSISTENCE_MINIMAL: makeCaptureResult('C_PERSISTENCE_MINIMAL'),
      D_INTERFACE_MONITORING: makeCaptureResult('D_INTERFACE_MONITORING'),
      E_ALT_FORMAT: makeCaptureResult('E_ALT_FORMAT'),
    };
  }, [diagnosticAResult, latestDiagnosticByStep]);
  const diagnosticCurrentStep: DiagnosticStepId | 'DONE' = diagnosticResults.A_RECEIVER_TRANSPORT.status === 'PENDING' ? 'A_RECEIVER_TRANSPORT'
    : diagnosticResults.B_STREAM_NO_DISK.status === 'PENDING' ? 'B_STREAM_NO_DISK'
      : diagnosticResults.B_STREAM_NO_DISK.status === 'FAILED' ? 'B_STREAM_NO_DISK'
        : diagnosticResults.C_PERSISTENCE_MINIMAL.status === 'PENDING' ? 'C_PERSISTENCE_MINIMAL'
          : diagnosticResults.C_PERSISTENCE_MINIMAL.status === 'FAILED' ? 'C_PERSISTENCE_MINIMAL'
            : diagnosticResults.D_INTERFACE_MONITORING.status === 'PENDING' ? 'D_INTERFACE_MONITORING'
              : diagnosticResults.D_INTERFACE_MONITORING.status === 'FAILED' ? 'D_INTERFACE_MONITORING'
              : 'DONE';
  const diagnosticCompleted = diagnosticCurrentStep === 'DONE';
  const diagnosticReadyToRetry = diagnosticCompleted
    && diagnosticResults.B_STREAM_NO_DISK.status === 'PASSED'
    && diagnosticResults.C_PERSISTENCE_MINIMAL.status === 'PASSED'
    && diagnosticResults.D_INTERFACE_MONITORING.status === 'PASSED';

  useEffect(() => {
    window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profiles));
  }, [profiles]);

  useEffect(() => {
    window.localStorage.setItem(ACTIVE_PROFILE_STORAGE_KEY, selectedProfile.device_profile_id);
  }, [selectedProfile.device_profile_id]);

  const byCondition = useMemo(() => {
    const grouped: Record<string, { positive?: BleHybridSession; negative?: BleHybridSession }> = {};
    for (const session of stageOneSessions) {
      const conditionId = sessionConditionId(session);
      if (!conditionId) continue;
      grouped[conditionId] ??= {};
      if (session.campaign_intent === 'positive_target_validation') grouped[conditionId].positive ??= session;
      if (session.campaign_intent === 'negative_control') grouped[conditionId].negative ??= session;
    }
    return grouped;
  }, [stageOneSessions]);

  const conditionRows = effectiveMatrix.map((condition) => {
    const pair = byCondition[condition.condition_id] ?? {};
    const positive = positiveDecision(pair.positive, pair.positive ? summaries[pair.positive.session_id] : undefined);
    const negative = negativeDecision(pair.negative, pair.negative ? summaries[pair.negative.session_id] : undefined);
    return { condition, pair, positive, negative };
  });
  const completedRows = conditionRows.filter((row) => row.positive.result === 'POSITIVE_ACCEPTED' && row.negative.result === 'NEGATIVE_ACCEPTED');
  const acceptedPositiveRows = conditionRows.filter((row) => row.positive.result === 'POSITIVE_ACCEPTED');
  const acceptedNegativeRows = conditionRows.filter((row) => row.negative.result === 'NEGATIVE_ACCEPTED');
  const currentRow = conditionRows.find((row) => row.positive.result !== 'POSITIVE_ACCEPTED' || row.negative.result !== 'NEGATIVE_ACCEPTED') ?? conditionRows[conditionRows.length - 1];
  const currentCondition = currentRow.condition;
  const positiveAccepted = currentRow.positive.result === 'POSITIVE_ACCEPTED';
  const negativeAccepted = currentRow.negative.result === 'NEGATIVE_ACCEPTED';
  const absenceValid = absence?.conditionId === currentCondition.condition_id && absence.validUntil > Date.now() && !absence.targetSeen;
  const conditionLockedDuration = Number(currentRow.pair.positive?.experimental_metadata?.effective_duration_seconds ?? currentRow.pair.positive?.duration_seconds);
  const negativeDurationSeconds = Number.isFinite(conditionLockedDuration) && conditionLockedDuration > 0 ? Math.round(conditionLockedDuration) : captureSeconds;

  const latestPositivePilot = latestByTime(stageOneSessions)
    .find((session) => session.campaign_intent === 'positive_target_validation' && session.experimental_metadata?.execution_purpose === 'POSITIVE_PILOT');
  const latestPositivePilotCaptureId = latestPositivePilot?.capture_id ?? '';
  const latestPositiveSummary = latestPositivePilot ? summaries[latestPositivePilot.session_id] : undefined;
  const latestPositiveNeedsRfDiagnostic = latestPositivePilot?.state === 'completed'
    && latestPositiveSummary?.target_result === 'TARGET_NATIVE_ONLY'
    && Number(latestPositiveSummary?.funnel?.detected_bursts ?? latestPositivePilot.counters?.detected_bursts ?? 0) === 0;
  const currentRfDiagnostic = rfDiagnostic?.capture_id === latestPositivePilotCaptureId ? rfDiagnostic : null;
  const currentOfflineReplay = offlineReplay?.capture_id === latestPositivePilotCaptureId ? offlineReplay : null;
  const latestPositiveCaptureRecord = captures.find((capture) => capture.capture_id === latestPositivePilotCaptureId);
  const rfCandidateCount = Number(currentRfDiagnostic?.burst_detection_replay?.candidate_count ?? 0);
  // A replay that ran but did not reach pending_segments=0 must keep blocking
  // hardware/dataset/training exactly like "never ran" -- a partial subset
  // is not a closed scientific result (see README "Replay offline detector/
  // decoder trazable").
  const replayIncomplete = Boolean(currentOfflineReplay) && currentOfflineReplay?.scientific_completion_status !== 'COMPLETE';
  const latestPositiveNeedsOfflineReplay = Boolean(latestPositivePilotCaptureId)
    && (replayIncomplete || (!currentOfflineReplay && (latestPositiveNeedsRfDiagnostic || rfCandidateCount > 0)));
  const currentStep: CampaignStep = !selectedProfile?.physical_unit_id ? 'device'
    : active ? (activeSession?.campaign_intent === 'negative_control' ? 'negative' : 'positive')
    : !qualificationPassed ? 'qualification'
    : latestPositiveNeedsOfflineReplay ? 'replay'
      : completedRows.length === effectiveMatrix.length ? 'dataset'
        : !preflightValid && !positiveAccepted ? 'prepare'
          : !positiveAccepted ? 'positive'
            : !negativeAccepted ? 'negative'
              : 'repeat';

  const logOperation = (phase: string, detail: string, state: OperationEvent['state'] = 'running') => {
    setOperationEvents((items) => [
      { id: `${Date.now()}:${Math.random().toString(16).slice(2)}`, at: new Date().toISOString(), phase, detail, state },
      ...items,
    ].slice(0, 30));
  };

  const runRfDiagnostic = async () => {
    if (!latestPositivePilotCaptureId) {
      setError('No hay captura positiva preservada para diagnosticar.');
      return;
    }
    const operationId = `ble-rffi-rf-diagnostic:${latestPositivePilotCaptureId}:${Date.now()}`;
    setBusy('rf-diagnostic');
    setError('');
    setMessage('');
    logOperation('Diagnostico RF offline iniciado', `${latestPositivePilotCaptureId}: separar recepcion RF y detector de rafagas.`);
    startOperation({
      operationId,
      kind: 'processing',
      title: 'RF_RECEPTION_VS_DETECTION_DIAGNOSTIC',
      phase: 'Analizando I/Q preservado',
      progressPercent: 20,
      target: latestPositivePilotCaptureId,
      detail: 'Calculando potencia, clipping, PSD, energia temporal y candidatos previos al decoder.',
    });
    try {
      const result = await api.rfDiagnostic(latestPositivePilotCaptureId);
      setRfDiagnostic(result);
      const candidates = Number(result.burst_detection_replay?.candidate_count ?? 0);
      const layer = statusText(result.diagnostic_conclusion?.layer);
      finishOperation(operationId, `${formatNumber(candidates)} candidatos energeticos; capa=${layer}.`);
      logOperation('Diagnostico RF offline completado', `${formatNumber(candidates)} candidatos previos al decoder; ${layer}.`, 'done');
      setMessage(candidates > 0
        ? 'Existe energia candidata en el I/Q preservado. La siguiente accion tecnica es replay offline detector/decoder; no avance a negativa ni dataset.'
        : 'No se observo energia candidata. Revise antena, RX2, sintonia, ganancia, driver y flujo de muestras antes de repetir S001-POS.');
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. No repita S001-POS hasta resolver el diagnostico RF.`;
      setError(text);
      failOperation(operationId, text);
      logOperation('Diagnostico RF offline fallido', text, 'error');
    } finally {
      setBusy('');
    }
  };

  const runOfflineReplay = async (resumeRunId?: string) => {
    if (!latestPositivePilot || !latestPositivePilotCaptureId) {
      setError('No hay ejecucion positiva preservada para replay.');
      return;
    }
    const operationId = `ble-rffi-offline-replay:${latestPositivePilotCaptureId}`;
    setBusy('offline-replay');
    setError('');
    setMessage('');
    logOperation(resumeRunId ? 'Replay detector/decoder reanudado desde checkpoint' : 'Replay detector/decoder iniciado', `${latestPositivePilot.session_id} Â· ${latestPositivePilotCaptureId}`);
    startOperation({
      operationId,
      kind: 'processing',
      title: 'OFFLINE_DETECTOR_DECODER_REPLAY',
      phase: resumeRunId ? 'Reanudando desde checkpoint' : 'Reanalizando I/Q preservado',
      progressPercent: 15,
      target: latestPositivePilotCaptureId,
      detail: 'Regenera candidatos, ejecuta decoder offline y asocia solo observaciones Windows preservadas.',
    });
    try {
      const job = await api.startOfflineReplayJob(latestPositivePilotCaptureId, {
        execution_id: latestPositivePilot.session_id,
        expected_iq_sha256: latestPositiveCaptureRecord?.data_sha256,
        sample_format: 'cf32_le',
        sample_rate_sps: 4_000_000,
        center_frequency_hz: 2_402_000_000,
        bandwidth_hz: 2_000_000,
        ble_channel: 37,
        analysis_configuration_id: 'ble-rffi-offline-detector-decoder-replay-v1',
        ...(resumeRunId ? { replay_run_id: resumeRunId } : {}),
      });
      setOfflineReplayJob(job);
      updateOperation(operationId, {
        phase: 'Replay offline en ejecucion',
        progressPercent: Math.max(1, Number(job.progress_percent ?? 1)),
        detail: `${job.replay_run_id}: use Cancelar replay si necesita detenerlo de forma ordenada.`,
      });
      logOperation('Replay detector/decoder en ejecucion', `${job.replay_run_id} - progreso disponible por polling.`);
      setMessage('Replay offline lanzado como job. No necesita encender el SensorTag; se analiza el I/Q preservado. Puede cancelarlo desde esta pantalla.');
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. No avance a hardware, negativa, dataset ni entrenamiento.`;
      setError(text);
      failOperation(operationId, text);
      logOperation('Replay detector/decoder fallido', text, 'error');
    } finally {
      setBusy('');
    }
  };

  const cancelOfflineReplay = async () => {
    if (!latestPositivePilotCaptureId || !offlineReplayJob?.replay_run_id) return;
    try {
      const job = await api.cancelOfflineReplayJob(latestPositivePilotCaptureId, offlineReplayJob.replay_run_id);
      setOfflineReplayJob(job);
      logOperation('Cancelacion de replay solicitada', `${job.replay_run_id} - se preservara resultado parcial.`, 'error');
      setMessage('Cancelacion solicitada. El backend cerrara el decoder y conservara los artefactos parciales.');
    } catch (reason) {
      setError(apiErrorMessage(reason));
    }
  };

  const reportBleAction = (event: React.MouseEvent<HTMLElement>) => {
    const control = (event.target as HTMLElement).closest<HTMLElement>('button,a,[role="button"]');
    if (!control || control.matches(':disabled') || control.dataset.silentAction === 'true') return;
    const label = control.getAttribute('aria-label') || control.getAttribute('title') || control.textContent || 'Accion BLE-RFFI';
    beginBleButtonAction(label, selectedProfile.physical_unit_id || selectedProfile.logical_address || undefined);
  };

  const runQualificationCapture = async (phase: QualificationPhase) => {
    if (!sdr) {
      setError('B200 no disponible. Accion: revise UHD/USB y pulse Actualizar.');
      return;
    }
    if (phase === 'HYBRID_CONCURRENCY_QUALIFICATION' && !b200QualificationStatus.passed) {
      setError('HYBRID_CONCURRENCY_QUALIFICATION bloqueada. Antes deben existir tres B200-only limpios consecutivos.');
      return;
    }
    const profile = qualificationProfile10s;
    const status = phase === 'ACQUISITION_QUALIFICATION' ? b200QualificationStatus : hybridQualificationStatus;
    const index = Math.min(QUALIFICATION_REQUIRED_CLEAN, status.cleanConsecutive + 1);
    const operationId = `ble-rffi-qualification:${phase}:${Date.now()}`;
    setBusy('qualification');
    setError('');
    setMessage('');
    setQualificationJob(null);
    setQualificationLive(null);
    const hybrid = phase === 'HYBRID_CONCURRENCY_QUALIFICATION';
    const qualificationRunId = hybrid ? `HCQ${index}` : `Q${index}`;
    const captureIdPrefix = hybrid ? 'BLE-IQ-HYBQUAL' : 'BLE-IQ-ACQQUAL';
    const requestedCaptureId = `${captureIdPrefix}-${qualificationRunId}-${Date.now().toString(36)}`;
    logOperation(hybrid ? 'Cualificacion concurrente iniciada' : 'Cualificacion B200-only iniciada', `Diagnostico ${index}/${QUALIFICATION_REQUIRED_CLEAN}: 10 s, 4 MS/s, cf32_le, CH37.`);
    startOperation({
      operationId,
      kind: 'capturing',
      title: phase,
      phase: hybrid ? 'Arrancando Windows BLE + solicitando B200' : 'Solicitando captura B200-only',
      progressPercent: 2,
      target: 'USRP B200 CH37',
      configuredDurationSeconds: QUALIFICATION_CAPTURE_SECONDS,
      estimatedTotalSeconds: QUALIFICATION_CAPTURE_SECONDS,
      detail: 'Decoder online desactivado; correlacion online desactivada; no entra al dataset.',
    });
    try {
      if (hybrid) await api.startNativeScan();
      let job = await api.createCapture({
        requested_capture_id: requestedCaptureId,
        device_id: sdr.device_id,
        ble_channel: 37,
        center_frequency_hz: 2_402_000_000,
        sample_rate_sps: 4_000_000,
        bandwidth_hz: 2_000_000,
        gain_mode: 'manual',
        gain_db: 20,
        antenna: 'RX2',
        duration_seconds: QUALIFICATION_CAPTURE_SECONDS,
        sample_format: 'cf32_le',
        purpose: 'BLE-RFFI acquisition qualification',
        controlled_transmitter_state: 'unknown',
        operator_confirmed: false,
        capture_role: 'background_control_A',
        experimental_metadata: {
          ...profile,
          stage: phase,
          execution_purpose: phase,
          qualification_run_id: qualificationRunId,
          scientific_campaign_member: false,
          dataset_eligible: false,
          qualification_only: true,
          b200_capture_enabled: true,
          windows_ble_scan_enabled: hybrid,
          base_protocol_id: BASE_PROTOCOL_ID,
          campaign_protocol_id: campaignId,
          dataset_eligibility_status: 'DIAGNOSTIC_NOT_DATASET',
          scientific_corpus_membership: 'none',
          decoder_online_enabled: false,
          correlation_online_enabled: false,
          protocol_duration_seconds: QUALIFICATION_CAPTURE_SECONDS,
          effective_duration_seconds: QUALIFICATION_CAPTURE_SECONDS,
          duration_source: 'qualification_protocol',
          protocol_override: false,
          override_reason: null,
          protocol_revision: 'qualification-rev1',
          expected_samples: QUALIFICATION_EXPECTED_SAMPLES,
          expected_file_size: QUALIFICATION_EXPECTED_FILE_SIZE,
          expected_file_size_bytes: QUALIFICATION_EXPECTED_FILE_SIZE,
        },
      });
      setQualificationJob(job);
      while (!terminalStates.has(job.state)) {
        const live = await api.captureLive(job.capture_id).catch(() => null);
        setQualificationLive(live);
        const samples = Number(live?.samples_received ?? 0);
        updateOperation(operationId, {
          phase: 'Adquisicion critica B200-only',
          progressPercent: 5 + 90 * Math.min(1, samples / QUALIFICATION_EXPECTED_SAMPLES),
          processedItems: samples,
          totalItems: QUALIFICATION_EXPECTED_SAMPLES,
          detail: `${formatNumber(samples)} muestras Â· ${formatNumber(live?.bytes_written)} bytes Â· overflows ${formatNumber(live?.stream_overflows)} Â· discontinuidades ${formatNumber(live?.input_discontinuities)}`,
        });
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        job = await api.captureJob(job.capture_id);
        setQualificationJob(job);
      }
      if (hybrid) await api.stopNativeScan().catch(() => null);
      if (job.state !== 'completed') throw new Error(job.error || job.state);
      updateOperation(operationId, { phase: 'Cierre, hash y verificacion de artefactos', progressPercent: 98 });
      const verify = await api.verifyCapture(job.capture_id);
      await load(false);
      finishOperation(operationId, `Diagnostico preservado: ${job.capture_id}; hash data=${statusText(verify.data_valid)} meta=${statusText(verify.metadata_valid)}.`);
      logOperation(hybrid ? 'Cualificacion concurrente terminada' : 'Cualificacion B200-only terminada', `${job.capture_id} completada; revise si cumple 40M muestras, 320MB, hash verificado y cero perdidas.`, 'done');
      setMessage('Diagnostico terminado. Si una ejecucion falla, la secuencia de tres limpias consecutivas se reinicia para esa fase.');
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. Accion: no continue; revise UHD/USB, escritura a disco, buffers o carga concurrente.`;
      setError(text);
      failOperation(operationId, text);
      logOperation(hybrid ? 'Cualificacion concurrente fallida' : 'Cualificacion B200-only fallida', text, 'error');
    } finally {
      if (phase === 'HYBRID_CONCURRENCY_QUALIFICATION') await api.stopNativeScan().catch(() => null);
      setBusy('');
    }
  };

  const runAcquisitionDiagnostic = async (step: DiagnosticStepId) => {
    if (!sdr) {
      setError('B200 no disponible. Accion: revise UHD/USB y pulse Actualizar.');
      return;
    }
    const definition = diagnosticSteps.find((item) => item.id === step)!;
    const operationId = `ble-rffi-acquisition-diagnostic:${step}:${Date.now()}`;
    setBusy('diagnostic');
    setError('');
    setMessage('');
    logOperation(definition.title, definition.objective);
    startOperation({
      operationId,
      kind: 'capturing',
      title: 'ACQUISITION_DIAGNOSTIC',
      phase: definition.title,
      progressPercent: 2,
      target: 'USRP B200 CH37',
      configuredDurationSeconds: step === 'A_RECEIVER_TRANSPORT' ? 0 : QUALIFICATION_CAPTURE_SECONDS,
      estimatedTotalSeconds: step === 'A_RECEIVER_TRANSPORT' ? 3 : QUALIFICATION_CAPTURE_SECONDS,
      detail: definition.objective,
    });
    try {
      if (step === 'A_RECEIVER_TRANSPORT') {
        const refreshed = await api.captureCapabilities(true);
        const receiverDetected = Boolean(refreshed.devices.find((device) => device.available));
        const result: DiagnosticResult = {
          step,
          status: receiverDetected ? 'PASSED' : 'FAILED',
          observed_result: receiverDetected
            ? `receiver_detected=true; receiver_serial=${sdr.serial_masked ?? sdr.device_id}; receiver_exclusive_access=not_measured; other_sdr_processes_detected=not_measured; usb_transport=not_reported; usb_speed=not_reported; usb_path=not_reported; uhd_version=reported_after_capture; driver_status=available; host_id=browser_host_not_available`
            : 'receiver_detected=false; driver_status=unavailable',
          supported_interpretation: receiverDetected ? diagnosticInterpretation(step).passed : diagnosticInterpretation(step).failed,
          unresolved_alternatives: diagnosticInterpretation(step).unresolved,
          recommended_next_action: receiverDetected ? diagnosticInterpretation(step).passedAction : diagnosticInterpretation(step).failedAction,
        };
        setDiagnosticAResult(result);
        finishOperation(operationId, result.observed_result);
        logOperation(definition.title, result.recommended_next_action, result.status === 'PASSED' ? 'done' : 'error');
        return;
      }
      const profile = qualificationProfile10s;
      const persist = step !== 'B_STREAM_NO_DISK';
      const preview = step === 'D_INTERFACE_MONITORING';
      const fmt = step === 'E_ALT_FORMAT' ? 'ci16_le' : 'cf32_le';
      let job = await api.createCapture({
        device_id: sdr.device_id,
        ble_channel: 37,
        center_frequency_hz: 2_402_000_000,
        sample_rate_sps: 4_000_000,
        bandwidth_hz: 2_000_000,
        gain_mode: 'manual',
        gain_db: 20,
        antenna: 'RX2',
        duration_seconds: QUALIFICATION_CAPTURE_SECONDS,
        sample_format: fmt,
        purpose: 'BLE-RFFI acquisition diagnostic',
        controlled_transmitter_state: 'unknown',
        operator_confirmed: false,
        capture_role: 'background_control_A',
        disk_persistence_enabled: persist,
        frontend_preview_enabled: preview,
        ui_polling_mode: step === 'D_INTERFACE_MONITORING' ? 'normal' : 'reduced',
        diagnostic_step: step,
        experimental_metadata: {
          ...profile,
          stage: 'ACQUISITION_DIAGNOSTIC',
          diagnostic_step: step,
          execution_purpose: 'ACQUISITION_DIAGNOSTIC',
          scientific_campaign_member: false,
          dataset_eligible: false,
          qualification_only: true,
          b200_capture_enabled: true,
          windows_ble_scan_enabled: false,
          disk_persistence_enabled: persist,
          frontend_preview_enabled: preview,
          decoder_online_enabled: false,
          correlation_online_enabled: false,
          protocol_duration_seconds: QUALIFICATION_CAPTURE_SECONDS,
          effective_duration_seconds: QUALIFICATION_CAPTURE_SECONDS,
          duration_source: 'diagnostic_protocol',
          protocol_override: fmt !== 'cf32_le',
          override_reason: fmt !== 'cf32_le' ? 'diagnostic_alternative_format_only' : null,
          protocol_revision: 'diagnostic-rev1',
          expected_samples: QUALIFICATION_EXPECTED_SAMPLES,
          expected_file_size: persist ? (fmt === 'cf32_le' ? QUALIFICATION_EXPECTED_FILE_SIZE : 160_000_000) : 0,
          expected_file_size_bytes: persist ? (fmt === 'cf32_le' ? QUALIFICATION_EXPECTED_FILE_SIZE : 160_000_000) : 0,
          gap_handling_policy: 'overflow_counter_only_no_local_gap_reconstruction',
        },
      });
      setQualificationJob(job);
      while (!terminalStates.has(job.state)) {
        const live = await api.captureLive(job.capture_id).catch(() => null);
        setQualificationLive(live);
        const samples = Number(live?.samples_received ?? 0);
        updateOperation(operationId, {
          phase: definition.title,
          progressPercent: 5 + 90 * Math.min(1, samples / QUALIFICATION_EXPECTED_SAMPLES),
          processedItems: samples,
          totalItems: QUALIFICATION_EXPECTED_SAMPLES,
          detail: `${formatNumber(samples)} muestras; ${formatNumber(live?.bytes_written)} bytes; overflows ${formatNumber(live?.stream_overflows)}; discontinuidades ${formatNumber(live?.input_discontinuities)}`,
        });
        await new Promise((resolve) => window.setTimeout(resolve, step === 'D_INTERFACE_MONITORING' ? 1000 : 2000));
        job = await api.captureJob(job.capture_id);
        setQualificationJob(job);
      }
      if (job.state !== 'completed') throw new Error(job.error || job.state);
      await load(false);
      finishOperation(operationId, `Diagnostico preservado: ${job.capture_id}. Revise continuidad antes de continuar.`);
      logOperation(definition.title, `Terminado ${job.capture_id}; la conclusion se muestra en el panel de diagnostico.`, 'done');
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. No se selecciona una causa concreta sin completar las pruebas.`;
      setError(text);
      failOperation(operationId, text);
      logOperation(definition.title, text, 'error');
    } finally {
      setBusy('');
    }
  };

  const load = async (forceSdr = false) => {
    setError('');
    const [nextNative, nextCaps, nextDevices, nextSessions, nextCaptures, nextDatasets, nextRfProfiles] = await Promise.all([
      api.nativeStatus(),
      api.captureCapabilities(forceSdr),
      api.nativeDevices(),
      api.hybridSessions().catch(() => []),
      api.captures().catch(() => []),
      api.datasets().catch(() => []),
      api.rfDiagnosticProfiles().catch(() => null),
    ]);
    const availableDatasetIds = new Set(nextDatasets.map((item) => item.dataset_id));
    const detailId = availableDatasetIds.has(datasetId) ? datasetId : availableDatasetIds.has('BLE-EVIDENCE-DS01') ? 'BLE-EVIDENCE-DS01' : '';
    const nextDataset = detailId ? await api.dataset(detailId).catch(() => null) : null;
    setNative(nextNative);
    setCaps(nextCaps);
    setDevices(nextDevices);
    setSessions(nextSessions);
    setCaptures(nextCaptures);
    setRfDiagnosticProfiles(nextRfProfiles);
    setDataset(nextDataset);
    setDatasetKnown(availableDatasetIds.has(datasetId));
    const loadedPositivePilot = latestByTime(nextSessions)
      .find((session) => session.campaign_intent === 'positive_target_validation' && session.experimental_metadata?.execution_purpose === 'POSITIVE_PILOT');
    const loadedReplay = loadedPositivePilot?.capture_id ? await api.latestOfflineReplay(loadedPositivePilot.capture_id).catch(() => null) : null;
    const loadedReplayJob = loadedPositivePilot?.capture_id ? await api.latestOfflineReplayJob(loadedPositivePilot.capture_id).catch(() => null) : null;
    setOfflineReplay(loadedReplay);
    setOfflineReplayJob(loadedReplayJob);
    const latestCompleted = latestByTime(nextSessions).filter((session) => session.state === 'completed').slice(0, 12);
    const loaded = await Promise.allSettled(latestCompleted.map((session) => api.hybridScientificSummary(session.session_id)));
    setSummaries(Object.fromEntries(loaded.flatMap((result) => result.status === 'fulfilled' ? [[result.value.session_id, result.value]] : [])));
    setActiveSession((current) => {
      if (current && !terminalStates.has(current.state)) return nextSessions.find((item) => item.session_id === current.session_id) ?? current;
      return nextSessions.find((item) => !terminalStates.has(item.state)) ?? null;
    });
  };

  useEffect(() => {
    void load(false).catch((reason) => setError(apiErrorMessage(reason)));
  }, []);

  useEffect(() => {
    if (!activeSession || terminalStates.has(activeSession.state)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.hybridSession(activeSession.session_id);
        setActiveSession(next);
        setSessions((items) => [next, ...items.filter((item) => item.session_id !== next.session_id)]);
        if (terminalStates.has(next.state)) await load(false);
      } catch (reason) {
        setError(apiErrorMessage(reason));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeSession?.session_id, activeSession?.state]);

  useEffect(() => {
    if (!latestPositivePilotCaptureId || !offlineReplayJob?.replay_run_id || terminalStates.has(offlineReplayJob.state)) return undefined;
    const operationId = `ble-rffi-offline-replay:${latestPositivePilotCaptureId}`;
    const timer = window.setInterval(async () => {
      try {
        const job = await api.offlineReplayJob(latestPositivePilotCaptureId, offlineReplayJob.replay_run_id);
        setOfflineReplayJob(job);
        const progress: Partial<BleOfflineReplayProgress> = job.progress ?? {};
        const processed = Number(progress.processed_segments ?? 0);
        const total = Number(progress.total_candidate_segments ?? 0);
        const failed = Number(progress.failed_segments ?? 0);
        ensureOperation({
          operationId,
          kind: 'processing',
          title: 'OFFLINE_DETECTOR_DECODER_REPLAY',
          phase: statusText(job.state),
          progressPercent: Math.max(1, Math.min(99, Number(job.progress_percent ?? 1))),
          target: latestPositivePilotCaptureId,
          detail: `${formatNumber(processed)} / ${formatNumber(total)} segmentos (${formatNumber(failed)} fallidos).`,
        });
        updateOperation(operationId, {
          phase: statusText(job.state),
          progressPercent: Math.max(1, Math.min(99, Number(job.progress_percent ?? 1))),
          detail: `${formatNumber(processed)} / ${formatNumber(total)} segmentos (${formatNumber(failed)} fallidos).`,
        });
        if (terminalStates.has(job.state)) {
          setBusy('');
          if (job.result) {
            setOfflineReplay(job.result);
            const funnel = job.result.candidate_funnel ?? {};
            const decision = job.result.decision ?? {};
            const incomplete = job.result.scientific_completion_status !== 'COMPLETE';
            finishOperation(operationId, `${formatNumber(funnel.pre_decoder_candidate_regions)} regiones; CRC=${formatNumber(funnel.crc_valid_packets)}; decision=${statusText(decision.decision)}.`);
            logOperation('Replay detector/decoder terminado', `${job.replay_run_id} - ${statusText(decision.decision)}.`, job.state === 'completed' && !incomplete ? 'done' : 'error');
            setMessage(incomplete
              ? `Replay detenido con checkpoint (${statusText(job.result.termination_reason)}). Quedan ${formatNumber(job.result.coverage?.pending_segments)} segmentos pendientes; use Continuar desde checkpoint. No se emite decision cientifica global todavia.`
              : 'Replay offline cerrado con cobertura total. Revise embudo, descartes, CRC, asociacion temporal y elegibilidad antes de cualquier nueva captura.');
          }
        }
      } catch (reason) {
        setError(apiErrorMessage(reason));
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [latestPositivePilotCaptureId, offlineReplayJob?.replay_run_id, offlineReplayJob?.state]);

  useEffect(() => {
    if (!activeSession) return;
    const id = `ble-rffi-stage1:${activeSession.session_id}`;
    const expectedSamples = Math.max(1, Number(activeSession.duration_seconds || 30) * 4_000_000);
    const samples = Number(activeSession.live?.telemetry?.samples_received ?? 0);
    const totalSegments = Number(activeSession.decode_progress?.total_segments ?? activeSession.counters?.detected_bursts ?? 0);
    const processedSegments = Number(activeSession.decode_progress?.processed_segments ?? activeSession.counters?.processed_bursts ?? 0);
    const target = `${sessionOperatorId(activeSession)} Â· CH${activeSession.channel}`;

    if (activeSession.state === 'completed') {
      finishOperation(id, `${formatNumber(activeSession.counters?.crc_valid_packets)} CRC validos Â· ${formatNumber(activeSession.counters?.strong_matches)} coincidencias`);
      logOperation('Sesion completada', `${activeSession.session_id} termino y pasa a decision cientifica.`, 'done');
      return;
    }
    if (terminalStates.has(activeSession.state)) {
      failOperation(id, activeSession.error || activeSession.state);
      logOperation('Sesion terminada con error', `${activeSession.session_id}: ${activeSession.error || activeSession.state}`, 'error');
      return;
    }

    ensureOperation({
      operationId: id,
      kind: 'capturing',
      title: activeSession.campaign_intent === 'negative_control' ? 'Control negativo BLE-RFFI' : 'Captura positiva BLE-RFFI',
      phase: 'Preparando hardware',
      progressPercent: 2,
      target,
      configuredDurationSeconds: activeSession.duration_seconds,
      estimatedTotalSeconds: activeSession.duration_seconds + 60,
      detail: `${selectedProfile.physical_unit_id} Â· Windows BLE + B200`,
    });

    let phase = 'Preparando hardware';
    let percent = 2;
    let processedItems: number | undefined;
    let totalItems: number | undefined;
    let estimatedTotalSeconds: number | null = activeSession.duration_seconds + 60;

    if (activeSession.state === 'capturing') {
      phase = 'Capturando I/Q B200 y observaciones Windows BLE';
      percent = 5 + 45 * Math.min(1, samples / expectedSamples);
      processedItems = samples;
      totalItems = expectedSamples;
      estimatedTotalSeconds = activeSession.duration_seconds;
    } else if (activeSession.state === 'decoding') {
      phase = 'Detectando rafagas y decodificando CRC BLE';
      percent = 55 + 25 * (totalSegments ? processedSegments / totalSegments : 0);
      processedItems = processedSegments;
      totalItems = totalSegments || undefined;
      estimatedTotalSeconds = null;
    } else if (activeSession.state === 'correlating') {
      phase = 'Correlacionando observaciones Windows BLE con paquetes B200';
      percent = 88;
      processedItems = Number(activeSession.counters?.strong_matches ?? 0);
      totalItems = Number(activeSession.counters?.crc_valid_packets ?? 0) || undefined;
      estimatedTotalSeconds = null;
    } else {
      phase = `Estado backend: ${statusText(activeSession.state)}`;
      percent = 15;
    }

    updateOperation(id, {
      phase,
      progressPercent: percent,
      processedItems,
      totalItems,
      estimatedTotalSeconds,
      detail: `${formatNumber(samples)} muestras Â· overflows ${formatNumber(activeSession.live?.telemetry?.stream_overflows ?? activeSession.counters?.overflows)} Â· discontinuidades ${formatNumber(activeSession.live?.telemetry?.input_discontinuities ?? activeSession.counters?.discontinuities)}`,
    });
  }, [
    activeSession?.session_id,
    activeSession?.state,
    activeSession?.live?.telemetry?.samples_received,
    activeSession?.live?.telemetry?.stream_overflows,
    activeSession?.live?.telemetry?.input_discontinuities,
    activeSession?.decode_progress?.processed_segments,
    activeSession?.decode_progress?.total_segments,
    activeSession?.counters?.crc_valid_packets,
    activeSession?.counters?.strong_matches,
    selectedProfile.physical_unit_id,
  ]);

  const targetPayload = () => {
    if (target) return freezeTarget(target, native?.scan_session_id);
    return {
      kind: 'device',
      device_id: `physical:${selectedProfile.physical_unit_id}`,
      address: selectedProfile.logical_address,
      label: selectedProfile.display_name || selectedProfile.physical_unit_id,
      selection_source: 'frozen_protocol_target',
    };
  };

  const scanTarget = async () => {
    const operationId = `ble-rffi-scan:${Date.now()}`;
    const started = Date.now();
    setBusy('scan');
    setError('');
    setMessage('');
    logOperation('Escaneo live iniciado', `Buscando ${selectedProfile.physical_unit_id} durante 30 s.`);
    startOperation({
      operationId,
      kind: 'connecting',
      title: 'Escaneo live BLE-RFFI',
      phase: 'Arrancando adaptador BLE Windows',
      progressPercent: 0,
      target: selectedProfile.logical_address || selectedProfile.physical_unit_id,
      configuredDurationSeconds: 30,
      estimatedTotalSeconds: 30,
      detail: 'La captura positiva queda bloqueada hasta ver el objetivo en este escaneo.',
    });
    const timer = window.setInterval(() => {
      const elapsed = Math.min(30, (Date.now() - started) / 1000);
      updateOperation(operationId, { phase: 'Escuchando advertising BLE live', progressPercent: (elapsed / 30) * 100 });
    }, 500);
    try {
      await api.startNativeScan();
      await new Promise((resolve) => window.setTimeout(resolve, 30_000));
      await api.stopNativeScan();
      await load(false);
      setMessage('Preflight terminado. La captura positiva se desbloquea solo si el objetivo fue visto en este escaneo.');
      finishOperation(operationId, 'Escaneo terminado; se actualizo el registro de dispositivos.');
      logOperation('Escaneo live terminado', 'Registro BLE actualizado; revise si el objetivo fue visto ahora.', 'done');
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. Accion: compruebe Bluetooth Windows y repita Buscar y confirmar objetivo.`;
      setError(text);
      failOperation(operationId, text);
      logOperation('Escaneo live fallido', text, 'error');
    } finally {
      window.clearInterval(timer);
      setBusy('');
    }
  };

  const verifyAbsence = async () => {
    const operationId = `ble-rffi-absence:${Date.now()}`;
    const started = Date.now();
    setBusy('absence');
    setError('');
    setMessage('');
    logOperation('Verificacion negativa iniciada', `Comprobando ausencia de ${selectedProfile.physical_unit_id} durante ${ABSENCE_SCAN_SECONDS} s.`);
    startOperation({
      operationId,
      kind: 'connecting',
      title: 'Verificacion de ausencia BLE-RFFI',
      phase: 'Arrancando escaneo negativo',
      progressPercent: 0,
      target: selectedProfile.logical_address || selectedProfile.physical_unit_id,
      configuredDurationSeconds: ABSENCE_SCAN_SECONDS,
      estimatedTotalSeconds: ABSENCE_SCAN_SECONDS,
      detail: 'Si el objetivo aparece, el control negativo queda bloqueado.',
    });
    const timer = window.setInterval(() => {
      const elapsed = Math.min(ABSENCE_SCAN_SECONDS, (Date.now() - started) / 1000);
      updateOperation(operationId, { phase: 'Escuchando para confirmar ausencia del objetivo', progressPercent: (elapsed / ABSENCE_SCAN_SECONDS) * 100 });
    }, 500);
    try {
      await api.startNativeScan();
      await new Promise((resolve) => window.setTimeout(resolve, ABSENCE_SCAN_SECONDS * 1000));
      await api.stopNativeScan();
      const [nextNative, nextDevices] = await Promise.all([api.nativeStatus(), api.nativeDevices()]);
      setNative(nextNative);
      setDevices(nextDevices);
      const seen = nextDevices.some((device) => selectedProfile.logical_address && normalizeAddress(device.address) === normalizeAddress(selectedProfile.logical_address) && device.scan_session_id === nextNative.scan_session_id);
      setAbsence({ conditionId: currentCondition.condition_id, checkedAt: new Date().toISOString(), targetSeen: seen, validUntil: Date.now() + PREFLIGHT_VALID_MS });
      setOperatorConfirmed(false);
      setMessage(seen ? 'El objetivo aparecio durante la verificacion. No se puede iniciar negativo.' : 'Ausencia verificada temporalmente. Confirme la condicion fisica para iniciar el control negativo.');
      if (seen) {
        failOperation(operationId, 'Objetivo visto durante el control negativo.');
        logOperation('Ausencia rechazada', 'El objetivo aparecio durante el escaneo negativo; no se puede etiquetar como fondo.', 'error');
      } else {
        finishOperation(operationId, 'Ausencia verificada; falta confirmacion fisica del operador.');
        logOperation('Ausencia verificada', 'No se observo el objetivo en el escaneo negativo actual.', 'done');
      }
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. Accion: compruebe Bluetooth Windows y repita la verificacion de ausencia.`;
      setError(text);
      failOperation(operationId, text);
      logOperation('Verificacion negativa fallida', text, 'error');
    } finally {
      window.clearInterval(timer);
      setBusy('');
    }
  };

  const startCampaign = async (intent: 'positive_target_validation' | 'negative_control') => {
    const validationIssues = validateCondition(currentCondition, selectedProfile, effectiveMatrix);
    if (validationIssues.length) {
      setError(`Revise la condicion antes de capturar: ${validationIssues.join('; ')}`);
      return;
    }
    if (!sdr) {
      setError('B200 no disponible. Accion: revise UHD/USB y pulse Actualizar.');
      return;
    }
    if (!b200QualificationStatus.passed || !hybridQualificationStatus.passed || !qualificationProfileMatchesCampaign) {
      setError(`REQUALIFICATION_REQUIRED. Antes de capturar ${intent === 'negative_control' ? 'negativo' : 'positivo'} deben pasar ACQUISITION_QUALIFICATION, HYBRID_CONCURRENCY_QUALIFICATION y qualification_profile_matches_campaign=true.`);
      return;
    }
    if (intent === 'positive_target_validation' && !preflightValid) {
      setError('Preflight caducado o no valido. Accion: pulse Buscar y confirmar objetivo.');
      return;
    }
    if (intent === 'positive_target_validation' && !targetPowerConfirmedAt) {
      setError(`S001-POS bloqueada. Accion: confirme en el asistente que ${selectedProfile.physical_unit_id} esta fisicamente encendido antes del preflight y la captura.`);
      return;
    }
    if (intent === 'positive_target_validation' && latestPositiveNeedsRfDiagnostic && !currentRfDiagnostic) {
      setError('S001-POS bloqueada temporalmente. La ultima positiva tuvo 0 rafagas B200 con Windows viendo el objetivo. Accion: ejecute primero Diagnostico RF offline sobre el I/Q preservado para separar recepcion y detector.');
      return;
    }
    if (intent === 'positive_target_validation' && latestPositiveNeedsOfflineReplay) {
      setError('S001-POS bloqueada. Estado: OFFLINE_DETECTOR_DECODER_REPLAY_REQUIRED. Accion: ejecute primero Replay detector/decoder sobre el I/Q preservado.');
      return;
    }
    if (intent === 'negative_control' && currentRow.positive.result !== 'POSITIVE_ACCEPTED') {
      setError(`Control negativo bloqueado. Antes debe existir una positiva terminal aceptada y elegible. Estado actual: ${currentRow.positive.result}. Accion: espere resumen, revise cuarentena o repita ${currentCondition.positive_session_id}.`);
      return;
    }
    if (intent === 'negative_control' && (!absenceValid || !operatorConfirmed)) {
      setError(`Control negativo bloqueado. Accion: verifique ausencia y confirme que ${selectedProfile.physical_unit_id} esta fisicamente apagado.`);
      return;
    }
    const effectiveDurationSeconds = intent === 'negative_control' ? negativeDurationSeconds : captureSeconds;
    const existingConditionSessions = stageOneSessions.filter((session) => sessionConditionId(session) === currentCondition.condition_id);
    const protocolOverride = effectiveDurationSeconds !== DEFAULT_CAPTURE_SECONDS || (intent === 'negative_control' && effectiveDurationSeconds !== captureSeconds);
    const protocolRevision = intent === 'positive_target_validation'
      ? 'positive-pilot-gate-v2'
      : protocolOverride || existingConditionSessions.length ? `rev${existingConditionSessions.length + 1}` : 'rev1';
    const overrideReason = protocolOverride
      ? effectiveDurationSeconds !== DEFAULT_CAPTURE_SECONDS
        ? 'operator_duration_override'
        : 'negative_duration_locked_to_positive'
      : null;
    setBusy(intent);
    setError('');
    setMessage('');
    const operationId = `ble-rffi-request:${Date.now()}`;
    logOperation('Solicitud de captura enviada', `${intent === 'negative_control' ? currentCondition.negative_session_id : currentCondition.positive_session_id} Â· ${selectedProfile.physical_unit_id}`);
    startOperation({
      operationId,
      kind: 'capturing',
      title: intent === 'negative_control' ? 'Solicitando control negativo BLE-RFFI' : 'Solicitando captura positiva BLE-RFFI',
      phase: 'Enviando contrato al backend',
      progressPercent: 5,
      target: `${selectedProfile.physical_unit_id} Â· CH37`,
      configuredDurationSeconds: effectiveDurationSeconds,
      estimatedTotalSeconds: effectiveDurationSeconds + 60,
      detail: 'Se prepara Windows BLE + B200. La operacion larga continuara con telemetria de la sesion.',
    });
    try {
      const session = await api.startHybrid({
        device_profile_id: selectedProfile.device_profile_id,
        physical_unit_id: selectedProfile.physical_unit_id,
        campaign_id: campaignId,
        dataset_id: datasetId,
        device_id: sdr.device_id,
        channel: 37,
        duration_seconds: effectiveDurationSeconds,
        gain_db: 20,
        target: targetPayload(),
        experimental_metadata: {
          base_protocol_id: BASE_PROTOCOL_ID,
          protocol_id: BASE_PROTOCOL_ID,
          campaign_protocol_id: campaignId,
          campaign_id: campaignId,
          dataset_id: datasetId,
          execution_purpose: intent === 'positive_target_validation' ? 'POSITIVE_PILOT' : 'NEGATIVE_CONTROL',
          scientific_campaign_member: intent === 'positive_target_validation',
          dataset_eligible: false,
          qualification_only: false,
          scientific_corpus_membership: intent === 'positive_target_validation' ? 'positive_pilot_pending_gate' : 'negative_control_pending_gate',
          device_profile_id: selectedProfile.device_profile_id,
          physical_unit_id: selectedProfile.physical_unit_id,
          display_name: selectedProfile.display_name,
          logical_address: selectedProfile.logical_address || 'not_observed',
          address_type: selectedProfile.address_type || 'unknown',
          condition_id: currentCondition.condition_id,
          distance: currentCondition.distance,
          distance_m: currentCondition.distance,
          orientation: currentCondition.orientation,
          orientation_deg: currentCondition.orientation,
          location: currentCondition.location,
          location_id: currentCondition.location,
          power_state: intent === 'negative_control' ? 'powered_off' : 'powered_on',
          operator_declared_target_powered_on: intent === 'positive_target_validation',
          target_power_on_confirmed_at_utc: intent === 'positive_target_validation' ? targetPowerConfirmedAt : null,
          day_id: currentCondition.day_id,
          operator_session_id: intent === 'negative_control' ? currentCondition.negative_session_id : currentCondition.positive_session_id,
          session_id: intent === 'negative_control' ? currentCondition.negative_session_id : currentCondition.positive_session_id,
          positive_session_id: currentCondition.positive_session_id,
          negative_session_id: currentCondition.negative_session_id,
          power_cycle_id: currentCondition.power_cycle_id,
          operator_notes: currentCondition.operator_notes,
          environment_notes: currentCondition.environment_notes,
          relevant_obstacles: currentCondition.relevant_obstacles,
          receiver_position: currentCondition.receiver_position,
          transmitter_position: currentCondition.transmitter_position,
          requested_capture_duration_seconds: effectiveDurationSeconds,
          protocol_duration_seconds: effectiveDurationSeconds,
          effective_duration_seconds: effectiveDurationSeconds,
          duration_source: protocolOverride ? 'operator_parameter_override' : 'frozen_protocol_default',
          protocol_override: protocolOverride,
          override_reason: overrideReason,
          protocol_revision: protocolRevision,
          protocol_manifest: {
            protocol_id: BASE_PROTOCOL_ID,
            protocol_revision: protocolRevision,
            quality_gate_version: POSITIVE_PILOT_QUALITY_GATE_VERSION,
            execution_purpose: intent === 'positive_target_validation' ? 'POSITIVE_PILOT' : 'NEGATIVE_CONTROL',
            physical_unit_id: selectedProfile.physical_unit_id,
            condition_id: currentCondition.condition_id,
            session_id: intent === 'negative_control' ? currentCondition.negative_session_id : currentCondition.positive_session_id,
            qualification_profile_id: campaignQualificationProfile.qualification_profile_id,
            receiver_serial: POSITIVE_PILOT_RECEIVER_SERIAL,
            usb_mode: 'USB_3',
            center_frequency_hz: campaignQualificationProfile.center_frequency_hz,
            sample_rate_sps: campaignQualificationProfile.sample_rate_sps,
            bandwidth_hz: campaignQualificationProfile.bandwidth_hz,
            analog_bandwidth_hz: campaignQualificationProfile.bandwidth_hz,
            cpu_format: 'cf32',
            file_format: campaignQualificationProfile.sample_format,
            sample_format: campaignQualificationProfile.sample_format,
            antenna: campaignQualificationProfile.antenna,
            gain_db: campaignQualificationProfile.gain_db,
            duration_seconds: effectiveDurationSeconds,
            disk_persistence_enabled: true,
            windows_ble_scan_enabled: true,
            frontend_preview_enabled: false,
            analysis_enabled: true,
            online_decoder_enabled: false,
            online_correlation_enabled: false,
            minimum_unique_target_packets_for_e4_observation: MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION,
            minimum_unique_target_packets_for_dataset_acceptance: MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE,
          },
          minimum_target_crc_packets: MINIMUM_TARGET_CRC_PACKETS,
          minimum_target_strong_matches: MINIMUM_TARGET_STRONG_MATCHES,
          minimum_unique_target_packets_for_e4_observation: MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION,
          minimum_unique_target_packets_for_dataset_acceptance: MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE,
          quality_gate_version: POSITIVE_PILOT_QUALITY_GATE_VERSION,
          qualification_profile_id: campaignQualificationProfile.qualification_profile_id,
          receiver_serial: POSITIVE_PILOT_RECEIVER_SERIAL,
          host_id: campaignQualificationProfile.host_id,
          usb_mode: 'USB_3',
          usb_path: campaignQualificationProfile.usb_path,
          storage_target: campaignQualificationProfile.storage_target,
          center_frequency_hz: campaignQualificationProfile.center_frequency_hz,
          sample_rate_sps: campaignQualificationProfile.sample_rate_sps,
          bandwidth_hz: campaignQualificationProfile.bandwidth_hz,
          analog_bandwidth_hz: campaignQualificationProfile.bandwidth_hz,
          cpu_format: 'cf32',
          file_format: campaignQualificationProfile.sample_format,
          sample_format: campaignQualificationProfile.sample_format,
          antenna: campaignQualificationProfile.antenna,
          gain_db: campaignQualificationProfile.gain_db,
          disk_persistence_enabled: true,
          windows_ble_scan_enabled: true,
          frontend_preview_enabled: false,
          analysis_enabled: true,
          ui_polling_mode: 'minimal',
          qualification_profile_matches_campaign: qualificationProfileMatchesCampaign,
          qualification_requirement: 'ACQUISITION_QUALIFICATION_AND_HYBRID_CONCURRENCY_QUALIFICATION_PASSED',
          qualification_status: qualificationPassed ? 'PASSED' : 'REQUALIFICATION_REQUIRED',
          decoder_online_enabled: false,
          correlation_online_enabled: false,
          online_decoder_enabled: false,
          online_correlation_enabled: false,
          preflight_valid_at_capture_start: intent === 'positive_target_validation' ? preflightValid : absenceValid,
          preflight_age_at_capture_start_seconds: Number.isFinite(targetAgeMs) ? Math.round(targetAgeMs / 1000) : null,
          target_seen_during_capture: 'pending_processing',
          label_space: [targetLabel(selectedProfile), 'BACKGROUND_UNKNOWN'],
          positive_label_basis: 'HYBRID_E4',
          negative_label_basis: 'NEGATIVE_BY_EXPERIMENTAL_CONTRACT',
          model_input_policy: 'B200_IQ_ONLY',
          native_ble_role: 'GROUND_TRUTH_ONLY',
        },
        ...campaignContract(intent, intent === 'negative_control' ? 'target_powered_off' : '', intent === 'negative_control'),
      });
      finishOperation(operationId, `Sesion creada: ${session.session_id}`);
      logOperation('Sesion hibrida creada', `${session.session_id} Â· estado ${session.state}`, 'done');
      setActiveSession(session);
      setSessions((items) => [session, ...items]);
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. Accion: revise el paso activo y repita solo cuando el boton principal este disponible.`;
      setError(text);
      failOperation(operationId, text);
      logOperation('Solicitud de captura fallida', text, 'error');
    } finally {
      setBusy('');
    }
  };

  const stopActive = async () => {
    if (!activeSession) return;
    if (activeSession.state !== 'capturing') {
      setMessage('La adquisicion ya termino. No se cancela procesamiento desde este asistente porque no hay reanudacion segura garantizada.');
      return;
    }
    if (!window.confirm('Cancelar S001-POS conserva los artefactos parciales como NOT_ELIGIBLE y no desbloquea la negativa. Â¿Desea cancelar la captura activa?')) return;
    const operationId = `ble-rffi-stop:${activeSession.session_id}`;
    setBusy('stop');
    logOperation('Detencion solicitada', `Solicitando parar ${activeSession.session_id}.`);
    startOperation({
      operationId,
      kind: 'processing',
      title: 'Deteniendo sesion BLE-RFFI',
      phase: 'Enviando stop al backend',
      progressPercent: 20,
      target: activeSession.session_id,
      estimatedTotalSeconds: 10,
      detail: 'No se inicia ninguna captura nueva.',
    });
    try {
      setActiveSession(await api.stopHybrid(activeSession.session_id));
      await load(false);
      finishOperation(operationId, 'Backend acepto detener la sesion.');
      logOperation('Detencion procesada', `${activeSession.session_id} fue actualizada desde backend.`, 'done');
    } catch (reason) {
      const text = `${apiErrorMessage(reason)}. Accion: revise la sesion en BLE Lab.`;
      setError(text);
      failOperation(operationId, text);
      logOperation('Detencion fallida', text, 'error');
    } finally {
      setBusy('');
    }
  };

  const activeIntent = activeSession?.campaign_intent === 'negative_control' ? 'Control negativo' : 'Captura positiva';
  const elapsed = activeSession?.created_at_utc ? Math.max(0, Math.round((Date.now() - new Date(activeSession.created_at_utc).getTime()) / 1000)) : 0;
  const activeOperatorId = activeSession ? sessionOperatorId(activeSession) : '';
  const activePhase = !activeSession ? ''
    : activeSession.state === 'capturing' ? 'CAPTURING'
      : ['decoding', 'correlating'].includes(activeSession.state) ? 'PROCESSING'
        : activeSession.state === 'completed' ? 'COMPLETED'
          : activeSession.state === 'cancelled' ? 'CANCELLED'
            : terminalStates.has(activeSession.state) ? 'FAILED'
              : 'PROCESSING';
  const headerText = active
    ? activeSession?.state === 'capturing'
      ? `${activeIntent} ${activeOperatorId} en adquisicion - ${Math.min(activeSession.duration_seconds, elapsed)}/${activeSession.duration_seconds} s.`
      : `Adquisicion ${activeOperatorId} completada - Procesando evidencia - ${activeSession?.state === 'decoding' ? 'Decoding CRC' : statusText(activeSession?.state)}.`
    : currentStep === 'device' ? 'Seleccione o registre una unidad BLE.'
      : currentStep === 'qualification' ? `Cualificacion: B200-only ${b200QualificationStatus.cleanConsecutive}/${QUALIFICATION_REQUIRED_CLEAN} y concurrencia ${hybridQualificationStatus.cleanConsecutive}/${QUALIFICATION_REQUIRED_CLEAN}.`
      : currentStep === 'prepare' ? `Etapa actual: Captura positiva piloto ${currentCondition.condition_id} / ${currentCondition.positive_session_id}.`
      : currentStep === 'positive' ? `Etapa actual: Captura positiva piloto ${currentCondition.condition_id} / ${currentCondition.positive_session_id}.`
        : currentStep === 'negative' ? `Control negativo ${currentCondition.negative_session_id}.`
          : currentStep === 'repeat' ? `${currentCondition.condition_id} completada.`
            : 'Generar dataset.';
  const nextAction = active
    ? activeSession?.state === 'capturing' ? 'No cambie el objetivo ni la condicion durante la adquisicion.' : 'La captura I/Q ya fue preservada; espere a que termine el procesamiento.'
    : currentStep === 'device' ? 'Seleccione una unidad existente o registre una nueva antes de crear la campana.'
    : currentStep === 'qualification' ? (qualificationProfileMatchesCampaign ? 'Ejecute tres B200-only limpias y luego tres Windows-B200 concurrentes limpias antes de buscar objetivo.' : 'REQUALIFICATION_REQUIRED: la duracion/configuracion de campana no coincide con la cualificacion de 10 s.')
    : currentStep === 'prepare' ? `Accion unica: preparar ${currentCondition.positive_session_id}. Encienda ${selectedProfile.display_name || selectedProfile.physical_unit_id}, coloque la geometria declarada y valide PREFLIGHT.`
      : currentStep === 'replay' ? 'Accion unica: ejecutar replay detector/decoder sobre el I/Q preservado. No usar hardware, negativa, dataset ni entrenamiento.'
      : currentStep === 'positive' ? 'Accion unica: ejecutar S001-POS. Debe demostrar adquisicion limpia, integridad, CRC valido, asociacion no ambigua y elegibilidad.'
        : currentStep === 'negative' && !absenceValid ? `Apague fisicamente ${selectedProfile.physical_unit_id} y verifique ausencia.`
          : currentStep === 'negative' && !operatorConfirmed ? `Confirme que ${selectedProfile.physical_unit_id} esta fisicamente apagado o retirado.`
            : currentStep === 'negative' ? 'Inicie el control negativo.'
              : currentStep === 'repeat' ? 'Avance a la siguiente condicion generada por la matriz.'
                : 'Abra Dataset Studio y genere ejemplos packet-aligned.';
  const stageGuide = [
    {
      step: 'device' as CampaignStep,
      title: '1. Seleccionar unidad BLE',
      action: 'Seleccione una unidad registrada o cree un perfil nuevo.',
      expected: 'Debe quedar congelado un physical_unit_id, un perfil de dispositivo y un identificador observado si existe.',
      blocked: 'Sin unidad fisica no se puede interpretar ninguna captura como evidencia de un objetivo.',
    },
    {
      step: 'qualification' as CampaignStep,
      title: '2. Cualificar adquisicion',
      action: `Ejecute ${QUALIFICATION_REQUIRED_CLEAN} B200-only limpias y despues ${QUALIFICATION_REQUIRED_CLEAN} Windows-B200 concurrentes limpias, todas de ${QUALIFICATION_CAPTURE_SECONDS} s.`,
      expected: 'Cada diagnostico debe cerrar con 40.000.000 muestras, 320.000.000 bytes, hash verificado, metadatos completos, cero overflows, cero discontinuidades, cero short reads y cero errores de escritura.',
      blocked: 'Si una falla, la secuencia de tres limpias consecutivas de esa fase se reinicia. Si cambia duracion o configuracion critica, aparece REQUALIFICATION_REQUIRED.',
    },
    {
      step: 'prepare' as CampaignStep,
      title: '3. Preparar condicion',
      action: `Prepare ${currentCondition.condition_id} / ${currentCondition.positive_session_id}, con protocolo congelado y preflight vigente.`,
      expected: 'La unidad fisica correcta debe estar seleccionada, encendida, colocada en la geometria declarada y observada por Windows BLE en el escaneo actual.',
      blocked: 'Si no aparece ahora, no se inicia la positiva: puede estar apagada, fuera de alcance, con direccion BLE distinta o el adaptador BLE puede estar fallando.',
    },
    {
      step: 'replay' as CampaignStep,
      title: '4. Replay offline detector/decoder',
      action: `Ejecute replay sobre ${latestPositivePilotCaptureId || 'el I/Q preservado'} enlazado a la ejecucion fuente, sin recapturar hardware.`,
      expected: 'Debe mostrar embudo detector/decoder, descartes, CRC validos, asociacion Windows preservada, calidad de la sesion fuente y decision cientifica.',
      blocked: 'Hasta cerrar este replay: NO S001-NEG, NO DATASET, NO TRAINING, NO LIVE MODEL y NO nueva S001-POS.',
    },
    {
      step: 'positive' as CampaignStep,
      title: '5. Captura positiva',
      action: `Ejecute solo ${currentCondition.positive_session_id} con el objetivo encendido.`,
      expected: 'Debe cerrar con 40.000.000 muestras, 320.000.000 bytes, cero perdidas, hash verificado, CRC valido, asociacion Windows-B200 no ambigua y E4 aceptado.',
      blocked: 'Si falla adquisicion, integridad, preflight, CRC o asociacion, la sesion se conserva como no elegible y no desbloquea el negativo.',
    },
    {
      step: 'negative' as CampaignStep,
      title: '6. Control negativo',
      action: `Capture ${currentCondition.negative_session_id} con el objetivo fisicamente apagado o retirado.`,
      expected: 'Se espera trafico BLE ambiente sin atribucion al objetivo declarado.',
      blocked: 'Si el objetivo aparece durante el negativo, la etiqueta negativa queda contaminada y la condicion debe repetirse.',
    },
    {
      step: 'repeat' as CampaignStep,
      title: '7. Revisar piloto',
      action: 'Pase a la siguiente condicion solo cuando el par positivo/negativo anterior este aceptado.',
      expected: 'La etapa actual se detiene tras C001 POS/NEG para revisar artefactos antes de habilitar mas condiciones.',
      blocked: 'Si falta una captura positiva o negativa, la condicion queda incompleta respecto a la matriz experimental y no constituye un par controlado aceptado.',
    },
    {
      step: 'dataset' as CampaignStep,
      title: '8. Generar dataset',
      action: 'Cree el dataset, ejecute QC, split por sesion y comparacion de modelos sobre el mismo split.',
      expected: datasetKnown ? 'El dataset de la unidad ya existe y puede revisarse.' : 'El dataset esta reservado y planificado; todavia no contiene ejemplos aceptados.',
      blocked: 'Entrenar antes de completar las condiciones rompe el contrato experimental y puede mezclar evidencia incompleta.',
    },
  ];

  const latestFinalSession = latestByTime(stageOneSessions.filter((session) => terminalStates.has(session.state)))[0];
  const latestSummary = latestFinalSession ? summaries[latestFinalSession.session_id] : undefined;
  const latestDecision = latestFinalSession?.campaign_intent === 'negative_control'
    ? negativeDecision(latestFinalSession, latestSummary)
    : positiveDecision(latestFinalSession, latestSummary);
  const historicalCleanCaptures = captures.filter((capture) => !isQualificationCapture(capture) && !isDiagnosticCapture(capture) && isCleanCapture(capture));

  return (
    <main onClick={reportBleAction} className="mx-auto max-w-[1500px] space-y-5 p-4 text-slate-100">
      <section className="rounded-lg border border-slate-700 bg-slate-950 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[.18em] text-cyan-300">BLE-RFFI etapa 1</div>
            <h1 className="mt-1 text-2xl font-semibold">Asistente de campana BLE-RFFI</h1>
            <div className="mt-1 text-sm text-slate-400">Dispositivo: {selectedProfile.display_name || selectedProfile.physical_unit_id} Â· Dataset: {datasetId}</div>
            <div className="mt-2 text-lg font-semibold text-cyan-100">{headerText}</div>
            {active && <div className="mt-1 text-xs font-semibold uppercase tracking-[.18em] text-amber-300">Fase: {activePhase}</div>}
            <p className="mt-1 text-sm text-slate-300">{nextAction}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => void load(true)} disabled={Boolean(busy) || active} className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-600 px-3 text-sm disabled:opacity-40" title="Actualizar hardware y estado">
              <RefreshCw className="h-4 w-4" />Actualizar
            </button>
            <Link to="/ble-lab" className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-600 px-3 text-sm" title="Abrir BLE Lab">
              <Bluetooth className="h-4 w-4" />BLE Lab
            </Link>
          </div>
        </div>
      </section>

      {showIntro && !diagnosticRequired && <IntroCard onStart={() => setShowIntro(false)} onHide={() => { window.localStorage.setItem(INTRO_STORAGE_KEY, 'true'); setShowIntro(false); }} />}

      {!diagnosticRequired && <DeviceSelector
        profiles={profiles}
        selectedProfileId={selectedProfile.device_profile_id}
        draft={profileDraft}
        active={active}
        onSelect={setSelectedProfileId}
        onDraft={setProfileDraft}
        onSaveDraft={() => {
          const next = {
            ...profileDraft,
            device_profile_id: profileDraft.device_profile_id || `ble-profile-${Date.now()}`,
            physical_unit_id: profileDraft.physical_unit_id || `BLE-UNIT-${profiles.length + 1}`,
            display_name: profileDraft.display_name || profileDraft.physical_unit_id || 'Unidad BLE',
            manufacturer: profileDraft.manufacturer || 'unknown',
            model: profileDraft.model || 'unknown',
            hardware_revision: profileDraft.hardware_revision || 'unknown',
            firmware_version: profileDraft.firmware_version || 'unknown',
            protocol: profileDraft.protocol || 'BLE advertising',
            logical_address: profileDraft.logical_address || 'not_observed',
            address_type: profileDraft.address_type || 'unknown',
            local_name: profileDraft.local_name || 'not_observed',
            advertising_identifiers: profileDraft.advertising_identifiers || 'not_observed',
            preferred_channels: profileDraft.preferred_channels?.length ? profileDraft.preferred_channels : [37],
            created_at: profileDraft.created_at || new Date().toISOString(),
            status: 'active',
          };
          setProfiles((items) => [...items.filter((item) => item.device_profile_id !== next.device_profile_id), next]);
          setSelectedProfileId(next.device_profile_id);
        }}
      />}

      <ProgressSteps current={currentStep} completed={completedRows.length} positives={acceptedPositiveRows.length} negatives={acceptedNegativeRows.length} total={effectiveMatrix.length} diagnosticRequired={diagnosticRequired} />
      {!diagnosticRequired && <CurrentScientificStatePanel profile={selectedProfile} condition={currentCondition} qualificationProfileId={qualificationProfile10s.qualification_profile_id} b200Passed={b200QualificationStatus.passed} hybridPassed={hybridQualificationStatus.passed} profileMatchesCampaign={qualificationProfileMatchesCampaign} />}
      {diagnosticRequired ? <DiagnosticFlowStatus /> : <StageGuide stages={stageGuide} current={currentStep} />}
      <OperationAuditPanel activeSession={activeSession} qualificationJob={qualificationJob} qualificationLive={qualificationLive} busy={busy} events={operationEvents} />

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Panel title="Paso actual">
          {currentStep === 'device' && !active && <DeviceStep profile={selectedProfile} />}
          {currentStep === 'qualification' && !active && diagnosticRequired && <DiagnosticRecoveryStep status={b200QualificationStatus} diagnosticResults={diagnosticResults} currentDiagnosticStep={diagnosticCurrentStep} readyToRetry={diagnosticReadyToRetry} profile={qualificationProfile10s} captures={qualificationCaptures} busy={busy} onRunDiagnostic={(step) => void runAcquisitionDiagnostic(step)} onRetry={() => void runQualificationCapture('ACQUISITION_QUALIFICATION')} />}
          {currentStep === 'qualification' && !active && !diagnosticRequired && <QualificationStep captures={qualificationCaptures} b200Status={b200QualificationStatus} hybridStatus={hybridQualificationStatus} profileMatchesCampaign={qualificationProfileMatchesCampaign} qualificationProfileId={qualificationProfile10s.qualification_profile_id} campaignDurationSeconds={captureSeconds} busy={busy} job={qualificationJob} live={qualificationLive} onStartB200={() => void runQualificationCapture('ACQUISITION_QUALIFICATION')} onStartHybrid={() => void runQualificationCapture('HYBRID_CONCURRENCY_QUALIFICATION')} />}
          {currentStep === 'prepare' && !active && <PrepareStep condition={currentCondition} profile={selectedProfile} target={target} targetAgeMs={targetAgeMs} preflightValid={preflightValid} native={native} busy={busy} started={positiveWizardStarted} deviceConfirmed={positiveDeviceConfirmed} conditionSaved={positiveConditionSaved} positionPrepared={positivePositionPrepared} physicalPrepared={positivePhysicalPrepared} targetPowerConfirmedAt={targetPowerConfirmedAt} onStartWizard={() => setPositiveWizardStarted(true)} onConfirmDevice={() => setPositiveDeviceConfirmed(true)} onSaveCondition={() => setPositiveConditionSaved(true)} onPositionPrepared={() => setPositivePositionPrepared(true)} onPhysicalPrepared={() => setPositivePhysicalPrepared(true)} onConfirmPower={() => setTargetPowerConfirmedAt(new Date().toISOString())} onScan={() => void scanTarget()} onChange={setConditionOverrides} metadataMode={metadataMode} onMode={setMetadataMode} />}
          {currentStep === 'replay' && !active && <OfflineReplayStep session={latestPositivePilot} capture={latestPositiveCaptureRecord} diagnostic={currentRfDiagnostic} replay={currentOfflineReplay} job={offlineReplayJob} busy={busy} onRun={() => void runOfflineReplay()} onContinue={() => void runOfflineReplay(offlineReplayJob?.replay_run_id)} onCancel={() => void cancelOfflineReplay()} />}
          {currentStep === 'positive' && !active && <PositiveStep condition={currentCondition} profile={selectedProfile} busy={busy} durationSeconds={captureSeconds} maxDurationSeconds={maxCaptureSeconds} onStart={() => void startCampaign('positive_target_validation')} />}
          {currentStep === 'negative' && !active && <NegativeStep condition={currentCondition} profile={selectedProfile} absence={absence} absenceValid={absenceValid} confirmed={operatorConfirmed} busy={busy} durationSeconds={negativeDurationSeconds} maxDurationSeconds={maxCaptureSeconds} lockedDurationSeconds={negativeDurationSeconds} onDuration={setCaptureDurationSeconds} onVerify={() => void verifyAbsence()} onConfirm={setOperatorConfirmed} onStart={() => void startCampaign('negative_control')} onChange={setConditionOverrides} metadataMode={metadataMode} onMode={setMetadataMode} />}
          {currentStep === 'repeat' && !active && <RepeatStep profile={selectedProfile} completed={completedRows.length} total={effectiveMatrix.length} next={conditionRows.find((row) => row.positive.result !== 'POSITIVE_ACCEPTED' || row.negative.result !== 'NEGATIVE_ACCEPTED')?.condition} onRefresh={() => void load(false)} />}
          {currentStep === 'dataset' && !active && <DatasetStep datasetManifest={datasetManifest} datasetId={datasetId} datasetKnown={datasetKnown} />}
          {active && <ActiveGuidance session={activeSession!} />}
          {message && <p className="mt-3 rounded-md border border-sky-500/30 bg-sky-500/10 p-3 text-sm text-sky-200">{message}</p>}
          {error && <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p>}
        </Panel>

        <Panel title="Ejecucion activa">
          {active && activeSession ? <ActiveSessionCard session={activeSession} onStop={() => void stopActive()} busy={busy} /> : <Empty text="Sin ejecucion activa" />}
        </Panel>
      </section>

      {!diagnosticRequired && <Panel title="Ultima ejecucion finalizada">
        {latestFinalSession ? (
          <div className="grid gap-3 lg:grid-cols-4">
            <Metric title="execution_id" value={latestFinalSession.session_id} detail={statusText(latestFinalSession.campaign_intent)} />
            <Metric title="resultado" value={latestDecision.result} detail={latestDecision.reason} />
            <Metric title="accion recomendada" value={latestDecision.action} detail="siguiente paso" />
            <Metric title="condicion" value={sessionConditionId(latestFinalSession)} detail={latestFinalSession.target_address ?? selectedProfile.logical_address} />
          </div>
        ) : <Empty text="Todavia no hay ejecuciones terminales de la campana nueva" />}
      </Panel>}

      {!diagnosticRequired && (latestPositiveNeedsRfDiagnostic || currentRfDiagnostic) && (
        <RfDiagnosticPanel
          captureId={latestPositivePilotCaptureId}
          diagnostic={currentRfDiagnostic}
          profiles={rfDiagnosticProfiles}
          busy={busy}
          onRun={() => void runRfDiagnostic()}
        />
      )}

      {!diagnosticRequired && <nav className="flex flex-wrap gap-2">
        {tabs.map((item) => (
          <button key={item} onClick={() => setTab(item)} className={`rounded-md px-3 py-2 text-sm ${tab === item ? 'bg-cyan-700 text-white' : 'border border-slate-700 bg-slate-950 text-slate-300'}`}>
            {item}
          </button>
        ))}
      </nav>}

      {diagnosticRequired ? (
        <QualificationOnlyPanel captures={qualificationCaptures} diagnosticCaptures={diagnosticCaptures} historicalCleanCaptures={historicalCleanCaptures.length} />
      ) : (
        <>
          {tab === 'Campana' && <CampaignTab profile={selectedProfile} campaignId={campaignId} datasetId={datasetId} native={native} sdr={sdr} target={target} targetAgeMs={targetAgeMs} preflightValid={preflightValid} historicalCount={historicalSessions.length} newCount={stageOneSessions.length} cleanCaptures={historicalCleanCaptures.length} totalCaptures={captures.length} b200Qualification={b200QualificationStatus} hybridQualification={hybridQualificationStatus} qualificationProfileMatchesCampaign={qualificationProfileMatchesCampaign} qualificationTotal={qualificationCaptures.length} />}
          {tab === 'Matriz experimental' && <MatrixTab rows={conditionRows} completed={completedRows.length} />}
          {tab === 'Resultados' && <ResultsTab rows={conditionRows} historicalSessions={historicalSessions} summaries={summaries} />}
          {tab === 'Evidencia' && <EvidenceTab captures={captures} cleanCaptures={historicalCleanCaptures.length} />}
          {tab === 'Configuracion avanzada' && <AdvancedTab profile={selectedProfile} caps={caps} datasetManifest={datasetManifest} />}
        </>
      )}
    </main>
  );
}

function IntroCard({ onStart, onHide }: { onStart: () => void; onHide: () => void }) {
  return (
    <section className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 p-5">
      <div className="text-xs font-bold uppercase tracking-[.18em] text-cyan-300">Ayuda del experimento</div>
      <h2 className="mt-1 text-xl font-semibold">Que hace este experimento</h2>
      <p className="mt-2 text-sm leading-6 text-slate-200">
        Esta etapa permite enrolar una unidad BLE controlada y construir un detector RF especifico para ella frente a trafico desconocido. El adaptador Bluetooth de Windows se usa durante el dataset para confirmar que dispositivo se observa; el modelo final usara solamente I/Q del USRP B200.
      </p>
      <p className="mt-2 text-sm text-slate-300">Cada condicion contiene una captura positiva con el objetivo encendido y un control negativo con el objetivo apagado o retirado. No se generan datos ficticios.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button onClick={onStart} className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold">Comenzar campana</button>
        <button onClick={onStart} className="rounded-md border border-slate-600 px-3 py-2 text-sm">Ver como funciona</button>
        <button onClick={onHide} className="rounded-md border border-slate-600 px-3 py-2 text-sm">No mostrar de nuevo</button>
      </div>
    </section>
  );
}

function DeviceSelector({ profiles, selectedProfileId, draft, active, onSelect, onDraft, onSaveDraft }: { profiles: DeviceProfile[]; selectedProfileId: string; draft: DeviceProfile; active: boolean; onSelect: (id: string) => void; onDraft: (profile: DeviceProfile) => void; onSaveDraft: () => void }) {
  return (
    <Panel title="Dispositivos BLE enrolados">
      {active && <p className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">Cambio de objetivo bloqueado: hay una adquisicion o procesamiento activo. Mantener el perfil congelado evita mezclar evidencia de otra unidad con esta campana.</p>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {profiles.map((profile) => (
            <button key={profile.device_profile_id} disabled={active} onClick={() => onSelect(profile.device_profile_id)} className={`rounded-md border p-3 text-left disabled:opacity-50 ${profile.device_profile_id === selectedProfileId ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-800 bg-slate-900'}`}>
              <div className="font-semibold">{profile.display_name}</div>
              <div className="mt-1 text-xs text-slate-400">{profile.physical_unit_id}</div>
              <div className="mt-1 text-xs text-slate-500">{profile.logical_address || 'not_observed'}</div>
              <div className="mt-3 flex flex-wrap gap-1 text-[11px] text-slate-300"><Badge>Seleccionar</Badge><Badge>Campanas</Badge><Badge>Datasets</Badge><Badge>Modelos</Badge><Badge>Live Monitor</Badge></div>
            </button>
          ))}
        </div>
        {!active && <div className="rounded-md border border-slate-800 p-3">
          <div className="font-semibold">Registrar nueva unidad</div>
          <div className="mt-2 grid gap-2">
            <input className={inputClass} placeholder="physical_unit_id" value={draft.physical_unit_id} onChange={(event) => onDraft({ ...draft, physical_unit_id: event.target.value })} />
            <input className={inputClass} placeholder="display_name" value={draft.display_name} onChange={(event) => onDraft({ ...draft, display_name: event.target.value })} />
            <input className={inputClass} placeholder="manufacturer" value={draft.manufacturer} onChange={(event) => onDraft({ ...draft, manufacturer: event.target.value })} />
            <input className={inputClass} placeholder="model" value={draft.model} onChange={(event) => onDraft({ ...draft, model: event.target.value })} />
            <input className={inputClass} placeholder="logical_address observado o not_observed" value={draft.logical_address} onChange={(event) => onDraft({ ...draft, logical_address: event.target.value })} />
          </div>
          <p className="mt-2 text-xs text-slate-400">Una direccion BLE no demuestra identidad fisica. La asociacion inicial queda respaldada por seleccion y confirmacion del operador.</p>
          <button disabled={active} onClick={onSaveDraft} className="mt-3 rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold disabled:opacity-40">Guardar perfil</button>
        </div>}
      </div>
    </Panel>
  );
}

function DeviceStep({ profile }: { profile: DeviceProfile }) {
  return <Instruction title="Seleccionar dispositivo" text={`La campana actual pertenece solo a ${profile.physical_unit_id}. Para otro objetivo cree otra campana independiente; no mezcle datasets ni modelos entre unidades.`} />;
}

function QualificationStep({ captures, b200Status, hybridStatus, profileMatchesCampaign, qualificationProfileId, campaignDurationSeconds, busy, job, live, onStartB200, onStartHybrid }: { captures: BleCaptureRecord[]; b200Status: QualificationStatus; hybridStatus: QualificationStatus; profileMatchesCampaign: boolean; qualificationProfileId: string; campaignDurationSeconds: number; busy: string; job: BleCaptureJob | null; live: BleCaptureLive | null; onStartB200: () => void; onStartHybrid: () => void }) {
  const running = busy === 'qualification' || Boolean(job && !terminalStates.has(job.state));
  const samples = Number(live?.samples_received ?? 0);
  const bytes = Number(live?.bytes_written ?? 0);
  return (
    <div className="space-y-4">
      <Instruction title="ACQUISITION_QUALIFICATION" text="Antes de repetir una positiva completa, estabilice el B200 con tres capturas B200-only limpias y despues tres capturas concurrentes Windows-B200 limpias. Estas capturas se preservan como evidencia tecnica, pero no se incorporan al dataset." />
      <div className="grid gap-3 md:grid-cols-4">
        <Metric title="B200-only consecutivas" value={`${b200Status.cleanConsecutive}/${QUALIFICATION_REQUIRED_CLEAN}`} detail={`${b200Status.totalForProfile} para este perfil`} />
        <Metric title="Windows-B200 consecutivas" value={`${hybridStatus.cleanConsecutive}/${QUALIFICATION_REQUIRED_CLEAN}`} detail={`${hybridStatus.totalForProfile} para este perfil`} />
        <Metric title="profile match" value={profileMatchesCampaign ? 'true' : 'REQUALIFICATION_REQUIRED'} detail={`campana ${campaignDurationSeconds}s / qual ${QUALIFICATION_CAPTURE_SECONDS}s`} />
        <Metric title="qualification_profile_id" value={qualificationProfileId} detail="configuracion critica congelada" />
        <Metric title="expected_samples" value={formatNumber(QUALIFICATION_EXPECTED_SAMPLES)} detail="10 s Â· 4 MS/s" />
        <Metric title="expected_file_size" value={`${formatNumber(QUALIFICATION_EXPECTED_FILE_SIZE)} bytes`} detail="cf32_le" />
        <Metric title="online" value="decoder off Â· correlacion off" detail="fuera del hilo de adquisicion" />
      </div>
      {!profileMatchesCampaign && <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">REQUALIFICATION_REQUIRED: una cualificacion de 10 s no habilita una captura de {campaignDurationSeconds} s.</p>}
      {job && (
        <div className="rounded-md border border-slate-800 p-3">
          <div className="font-semibold">Diagnostico actual: {job.capture_id}</div>
          <div className="mt-3 h-2 rounded bg-slate-800">
            <div className="h-2 rounded bg-cyan-500" style={{ width: `${Math.min(100, Math.round(samples * 100 / QUALIFICATION_EXPECTED_SAMPLES))}%` }} />
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-4">
            <Metric title="estado" value={statusText(job.state)} detail={job.error ?? 'sin error'} />
            <Metric title="muestras" value={formatNumber(samples)} detail={`de ${formatNumber(QUALIFICATION_EXPECTED_SAMPLES)}`} />
            <Metric title="bytes" value={formatNumber(bytes)} detail={`de ${formatNumber(QUALIFICATION_EXPECTED_FILE_SIZE)}`} />
            <Metric title="perdidas" value={`${formatNumber(live?.stream_overflows)} / ${formatNumber(live?.input_discontinuities)}`} detail="overflows / discontinuidades" />
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button onClick={onStartB200} disabled={running || b200Status.passed} className="inline-flex h-11 items-center gap-2 rounded-md bg-cyan-700 px-4 text-sm font-semibold disabled:opacity-40">
          <Play className="h-4 w-4" />Ejecutar B200-only 10 s
        </button>
        <button onClick={onStartHybrid} disabled={running || !b200Status.passed || hybridStatus.passed} className="inline-flex h-11 items-center gap-2 rounded-md bg-sky-700 px-4 text-sm font-semibold disabled:opacity-40">
          <Play className="h-4 w-4" />Ejecutar Windows-B200 10 s
        </button>
      </div>
      <div className="grid gap-2">
        {latestByTime(captures).slice(0, 6).map((capture) => {
          const stage = captureStage(capture) || undefined;
          const clean = isCleanQualificationCapture(capture, stage, qualificationProfileId);
          const hybrid = stage === 'HYBRID_CONCURRENCY_QUALIFICATION';
          return (
            <div key={capture.capture_id} className="rounded-md border border-slate-800 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs">{capture.capture_id}</span>
                <Badge>{stage ?? 'QUALIFICATION'}</Badge>
                <Badge>{clean ? 'Cualificacion superada' : 'Cualificacion no superada: revise perdidas, hash y solape RF'}</Badge>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-4">
                <Metric title="actual_samples" value={formatNumber(qualificationActualSamples(capture))} detail={`expected ${formatNumber(QUALIFICATION_EXPECTED_SAMPLES)}`} />
                <Metric title="actual_file_size" value={formatNumber(capture.actual_file_size_bytes ?? capture.actual_size_bytes)} detail={`expected ${formatNumber(QUALIFICATION_EXPECTED_FILE_SIZE)}`} />
                <Metric title="overflows" value={formatNumber(capture.overflow_count)} detail="debe ser 0" />
                <Metric title="discontinuidades" value={formatNumber(capture.discontinuity_count ?? capture.input_discontinuities)} detail="debe ser 0" />
                <Metric title="short_read_count" value={formatNumber(capture.short_read_count)} detail="debe ser 0" />
                <Metric title="write_error_count" value={formatNumber(capture.write_error_count)} detail="debe ser 0" />
                <Metric title="hash_status" value={statusText(capture.hash_status)} detail="debe ser VERIFIED" />
                <Metric title="metadata_status" value={statusText(capture.metadata_status)} detail="debe ser COMPLETE" />
                {hybrid && <Metric title="rf_overlap_seconds" value={formatNumber(capture.rf_concurrency_overlap_seconds ?? capture.experimental_metadata?.rf_concurrency_overlap_seconds)} detail={`minimo ${MINIMUM_RF_CONCURRENCY_OVERLAP_SECONDS}s; maximo ${QUALIFICATION_CAPTURE_SECONDS}s`} />}
                {hybrid && <Metric title="rf_overlap_fraction" value={formatNumber(capture.rf_concurrency_overlap_fraction ?? capture.experimental_metadata?.rf_concurrency_overlap_fraction)} detail={`minimo ${MINIMUM_RF_CONCURRENCY_OVERLAP_FRACTION}`} />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DiagnosticFlowStatus() {
  const rows: [string, GateState, string][] = [
    ['Dispositivo seleccionado', 'pass', 'COMPLETADO'],
    ['Cualificacion B200', 'fail', 'FALLIDA'],
    ['Diagnostico de adquisicion', 'warn', 'REQUERIDO'],
    ['Cualificacion Windows-B200', 'pending', 'BLOQUEADA'],
    ['Preparacion del objetivo', 'pending', 'BLOQUEADA'],
    ['Captura positiva', 'pending', 'BLOQUEADA'],
    ['Control negativo', 'pending', 'BLOQUEADO'],
    ['Dataset', 'pending', 'BLOQUEADO'],
  ];
  return (
    <Panel title="Estado correcto del flujo actual">
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {rows.map(([label, state, value]) => <GateCard key={label} label={label} state={state} value={value} />)}
      </div>
    </Panel>
  );
}

function DiagnosticRecoveryStep({ status, diagnosticResults, currentDiagnosticStep, readyToRetry, profile, captures, busy, onRunDiagnostic, onRetry }: { status: QualificationStatus; diagnosticResults: Record<DiagnosticStepId, DiagnosticResult>; currentDiagnosticStep: DiagnosticStepId | 'DONE'; readyToRetry: boolean; profile: ReturnType<typeof qualificationProfile>; captures: BleCaptureRecord[]; busy: string; onRunDiagnostic: (step: DiagnosticStepId) => void; onRetry: () => void }) {
  const latestFailure = status.latestFailure ?? latestByTime(captures)[0];
  const expectedSamples = Number(latestFailure?.expected_samples ?? QUALIFICATION_EXPECTED_SAMPLES);
  const actualSamples = qualificationActualSamples(latestFailure ?? {} as BleCaptureRecord);
  const expectedSize = Number(latestFailure?.expected_file_size_bytes ?? latestFailure?.expected_file_size ?? QUALIFICATION_EXPECTED_FILE_SIZE);
  const actualSize = Number(latestFailure?.actual_file_size_bytes ?? latestFailure?.actual_size_bytes ?? 0);
  const overflows = Number(latestFailure?.overflow_count ?? 0);
  const discontinuities = Number(latestFailure?.discontinuity_count ?? latestFailure?.input_discontinuities ?? 0);
  const currentDefinition = currentDiagnosticStep === 'DONE' ? null : diagnosticSteps.find((step) => step.id === currentDiagnosticStep)!;
  const diagnosticDoneButBlocked = currentDiagnosticStep === 'DONE' && !readyToRetry;
  const currentResult = currentDefinition ? diagnosticResults[currentDefinition.id] : null;
  const currentButtonLabel = currentResult?.status === 'FAILED' ? 'Repetir prueba tras corregir' : diagnosticResults.A_RECEIVER_TRANSPORT.status === 'PENDING' ? 'Iniciar diagnostico de adquisicion' : 'Continuar con la siguiente prueba';
  const nextAction = readyToRetry ? 'Reintentar cualificacion B200-only' : currentDefinition ? currentButtonLabel : 'Corregir infraestructura antes de reintentar';
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-4">
        <div className="text-lg font-semibold text-rose-100">Cualificacion B200 bloqueada por perdidas de adquisicion.</div>
        <p className="mt-2 text-sm leading-6 text-rose-50">Tres diagnosticos consecutivos han registrado overflows y discontinuidades. No repita la misma captura todavia. Ejecute el diagnostico guiado para determinar si el problema procede del transporte USB/UHD, del procesamiento del host, de la escritura a disco o de procesos concurrentes.</p>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric title="qualification_status" value="DIAGNOSTIC_REQUIRED" detail="fallos consecutivos" />
        <Metric title="pilot_status" value="BLOCKED" detail="no hay positiva piloto habilitada" />
        <Metric title="hybrid_qualification_status" value="BLOCKED" detail="Windows-B200 sigue deshabilitado" />
        <Metric title="accion recomendada" value={nextAction} detail="unica accion valida de esta etapa" />
      </div>

      <ContextHelp
        doing="Comprobando si el B200 puede adquirir 10 segundos de senal de forma continua."
        user="No encienda ni apague el SensorTag; el dispositivo objetivo no interviene en esta prueba."
        expected="40 millones de muestras, 320 MB, hash valido y cero perdidas."
        failure={`Tamano correcto, pero ${formatNumber(overflows)} overflows y ${formatNumber(discontinuities)} discontinuidades.`}
        next={nextAction}
      />

      <Panel title="Causa del bloqueo">
        <p className="text-sm leading-6 text-slate-200">Un overflow indica que el receptor produjo muestras mas rapido de lo que el sistema pudo recibirlas o procesarlas. Esto provoca perdida de continuidad temporal.</p>
        <p className="mt-2 text-sm leading-6 text-slate-300">Aunque el archivo tenga el tamano esperado, puede contener huecos, sustituciones o discontinuidades. Por ello no se acepta para entrenamiento.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Metric title="Muestras solicitadas" value={formatNumber(expectedSamples)} detail="protocolo" />
          <Metric title="Muestras escritas" value={formatNumber(actualSamples)} detail={actualSamples === expectedSamples ? 'tamano correcto' : 'tamano incompleto'} />
          <Metric title="Bytes esperados" value={formatNumber(expectedSize)} detail="cf32_le" />
          <Metric title="Bytes escritos" value={formatNumber(actualSize)} detail={actualSize === expectedSize ? 'tamano correcto' : 'tamano incompleto'} />
          <Metric title="Continuidad RF" value="FALLIDA" detail={`overflows ${formatNumber(overflows)} / discontinuidades ${formatNumber(discontinuities)}`} />
          <Metric title="Dataset" value="NO ELEGIBLE" detail="no se usa para entrenamiento" />
        </div>
        <details className="mt-3 rounded-md border border-slate-800 p-3">
          <summary className="cursor-pointer text-sm font-semibold">Detalles tecnicos</summary>
          <div className="mt-3 grid gap-2 md:grid-cols-4">
            <Metric title="gap_handling_policy" value={statusText(latestFailure?.gap_handling_policy ?? 'overflow_counter_only_no_local_gap_reconstruction')} detail="no reconstruye huecos" />
            <Metric title="samples_lost_estimated" value={statusText(latestFailure?.samples_lost_estimated ?? 'not_available')} detail="requiere intervalos exactos" />
            <Metric title="samples_inserted_or_repeated" value={formatNumber(latestFailure?.samples_inserted_or_repeated ?? 0)} detail="no justifica continuidad" />
            <Metric title="continuity_status" value={statusText(latestFailure?.continuity_status ?? 'FAILED')} detail="criterio RF" />
          </div>
        </details>
      </Panel>

      <Panel title="Diagnostico guiado">
        <div className="space-y-3">
          {diagnosticSteps.map((step) => {
            const result = diagnosticResults[step.id];
            const active = currentDiagnosticStep === step.id;
            return (
              <div key={step.id} className={`rounded-md border p-3 ${active ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-800 bg-slate-950'}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-semibold">{step.title}</div>
                  <Badge>{statusText(result.status)}</Badge>
                </div>
                <div className="mt-2 text-sm text-slate-300">{step.objective}</div>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <Metric title="observed_result" value={result.observed_result} detail={result.capture_id ?? 'sin captura'} />
                  <Metric title="supported_interpretation" value={result.supported_interpretation} detail="limitada por evidencia" />
                  <Metric title="recommended_next_action" value={result.recommended_next_action} detail="siguiente accion" />
                  <Metric title="unresolved_alternatives" value={result.unresolved_alternatives.join(', ')} detail="no descartadas" />
                </div>
              </div>
            );
          })}
          <div className="flex flex-wrap gap-2">
            {currentDefinition && (
              <button disabled={busy === 'diagnostic'} onClick={() => onRunDiagnostic(currentDefinition.id)} className="inline-flex h-11 items-center gap-2 rounded-md bg-cyan-700 px-4 text-sm font-semibold disabled:opacity-40">
                <Play className="h-4 w-4" />{currentButtonLabel}
              </button>
            )}
            {readyToRetry && (
              <button disabled={busy === 'qualification'} onClick={onRetry} className="inline-flex h-11 items-center gap-2 rounded-md bg-emerald-700 px-4 text-sm font-semibold disabled:opacity-40">
                <Play className="h-4 w-4" />Reintentar cualificacion B200-only
              </button>
            )}
          </div>
          {diagnosticDoneButBlocked && <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">Diagnostico terminado con perdidas. No se habilita reintento automatico; revise la accion recomendada y corrija infraestructura antes de capturar otra vez.</p>}
        </div>
      </Panel>

      <Panel title="Configuracion cualificada">
        <div className="grid gap-2 md:grid-cols-3">
          {Object.entries(profile).map(([key, value]) => <Metric key={key} title={key} value={statusText(value)} detail="perfil de cualificacion" />)}
        </div>
      </Panel>
    </div>
  );
}

function ContextHelp({ doing, user, expected, failure, next }: { doing: string; user: string; expected: string; failure: string; next: string }) {
  return (
    <Panel title="Ayuda contextual del paso actual">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric title="Que esta haciendo" value={doing} detail="plataforma" />
        <Metric title="Que debe hacer" value={user} detail="usuario" />
        <Metric title="Resultado esperado" value={expected} detail="criterio" />
        <Metric title="Que significa un fallo" value={failure} detail="interpretacion" />
        <Metric title="Que accion viene despues" value={next} detail="flujo" />
      </div>
    </Panel>
  );
}

function CurrentScientificStatePanel({ profile, condition, qualificationProfileId, b200Passed, hybridPassed, profileMatchesCampaign }: { profile: DeviceProfile; condition: MatrixCondition; qualificationProfileId: string; b200Passed: boolean; hybridPassed: boolean; profileMatchesCampaign: boolean }) {
  return (
    <Panel title="Estado cientifico y tecnico actual">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="rounded-md border border-slate-800 p-4">
          <div className="text-sm font-semibold text-cyan-100">Objetivo final del modulo</div>
          <p className="mt-2 text-sm text-slate-300">
            Construir una cadena BLE-RFFI trazable para evaluar si una emision BLE capturada por el USRP B200 es compatible con la unidad fisica enrolada o con la poblacion alternativa declarada. El modelo final solo puede usar informacion derivada del I/Q del B200; Windows BLE se reserva para observacion logica, ground truth, asociacion temporal y etiquetado.
          </p>
          <p className="mt-2 text-xs text-slate-400">
            Alcance limitado a unidades evaluadas, receptor, canal, configuracion, periodo experimental y poblacion alternativa declarada. No es identificacion universal de dispositivos BLE.
          </p>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          <Metric title="Etapa actual" value="PREPARATION_FOR_POSITIVE_PILOT" detail={`${condition.condition_id} / ${condition.positive_session_id}`} />
          <Metric title="Accion unica" value="Preparar y ejecutar S001-POS" detail="no negativa, dataset ni training" />
          <Metric title="ACQUISITION_DIAGNOSTIC" value="COMPLETED" detail="diagnostico A-E cerrado" />
          <Metric title="ACQUISITION_QUALIFICATION" value={b200Passed ? 'PASSED_3_CONSECUTIVE' : 'BLOCKED'} detail="B200-only 10 s" />
          <Metric title="HYBRID_CONCURRENCY_QUALIFICATION" value={hybridPassed ? 'PASSED_3_CONSECUTIVE' : 'BLOCKED'} detail="Windows BLE + B200 10 s" />
          <Metric title="qualification_profile_matches_campaign" value={profileMatchesCampaign ? 'true' : 'REQUALIFICATION_REQUIRED'} detail="solo perfil de 10 s" />
          <Metric title="S001-POS" value="UNLOCKED_NEXT_ONLY" detail={profile.physical_unit_id} />
          <Metric title="S001-NEG / DATASET / TRAINING" value="BLOCKED" detail="hasta positiva aceptada y elegible" />
          <Metric title="LIVE_MODEL" value="BLOCKED" detail="requiere dataset y entrenamiento verificados" />
          <Metric title="NEXT_OPERATOR_ACTION" value="PREPARE_AND_EXECUTE_S001_POS" detail="wizard numerado" />
          <Metric title="Campana 120 s" value="NOT_QUALIFIED" detail="requiere nuevo perfil" />
          <Metric title="ROOT_CAUSE_PRIOR_LOSSES" value="NOT_FULLY_ISOLATED" detail="USB, writer e instrumentacion cambiaron juntos" />
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <Metric title="qualification_profile_id" value={qualificationProfileId} detail="perfil cualificado" />
        <Metric title="receiver_serial" value="E3R04Z1B2" detail="USRP B200" />
        <Metric title="configuracion RF" value="2402 MHz Â· 4 MS/s Â· 2 MHz" detail="cf32_le Â· RX2 Â· G20 Â· USB 3" />
        <Metric title="E4_MINIMAL_OBSERVED" value={`${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION} paquete`} detail="unique target CRC strong" />
        <Metric title="E4_ACCEPTED_FOR_DATASET" value={`${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE} paquetes`} detail="strong-only no conflictivos" />
      </div>
      <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
        Las cualificaciones prueban estabilidad tecnica de adquisicion y concurrencia para 10 s. No prueban identidad del SensorTag, ground truth E4, fingerprinting valido, dataset entrenable, generalizacion ni estabilidad de capturas de 120 s.
      </div>
    </Panel>
  );
}

function QualificationOnlyPanel({ captures, diagnosticCaptures, historicalCleanCaptures }: { captures: BleCaptureRecord[]; diagnosticCaptures: BleCaptureRecord[]; historicalCleanCaptures: number }) {
  return (
    <Panel title="Historial de cualificacion">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric title="Cualificaciones B200 limpias" value={`${captures.filter((capture) => captureStage(capture) === 'ACQUISITION_QUALIFICATION' && isCleanQualificationCapture(capture)).length}/${QUALIFICATION_REQUIRED_CLEAN}`} detail="no cuenta dataset" />
        <Metric title="Cualificaciones hibridas limpias" value={`${captures.filter((capture) => captureStage(capture) === 'HYBRID_CONCURRENCY_QUALIFICATION' && isCleanQualificationCapture(capture)).length}/${QUALIFICATION_REQUIRED_CLEAN}`} detail="bloqueada hasta B200 limpio" />
        <Metric title="Capturas piloto positivas aceptadas" value="0/1" detail="bloqueado" />
        <Metric title="Capturas piloto negativas aceptadas" value="0/1" detail="bloqueado" />
        <Metric title="Capturas historicas limpias" value={formatNumber(historicalCleanCaptures)} detail="separadas de cualificacion" />
      </div>
      <div className="mt-3 grid gap-2">
        {latestByTime([...captures, ...diagnosticCaptures]).slice(0, 8).map((capture) => {
          const loss = isContinuityFailure(capture);
          return (
            <div key={capture.capture_id} className="rounded-md border border-slate-800 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs">{capture.capture_id}</span>
                <Badge>{loss ? 'Cualificacion no superada: se detectaron perdidas' : 'Sin perdidas notificadas'}</Badge>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-5">
                <Metric title="fase" value={statusText(captureStage(capture) || diagnosticStep(capture) || 'diagnostico')} detail="tecnico" />
                <Metric title="muestras" value={formatNumber(qualificationActualSamples(capture))} detail="escritas/recibidas" />
                <Metric title="bytes" value={formatNumber(capture.actual_file_size_bytes ?? capture.actual_size_bytes)} detail="archivo o diagnostico" />
                <Metric title="overflows" value={formatNumber(capture.overflow_count)} detail="continuidad" />
                <Metric title="discontinuidades" value={formatNumber(capture.discontinuity_count ?? capture.input_discontinuities)} detail="continuidad" />
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
function ConditionReview({ condition, mode, onMode, onChange }: { condition: MatrixCondition; mode: 'matrix' | 'edit'; onMode: (mode: 'matrix' | 'edit') => void; onChange: React.Dispatch<React.SetStateAction<Record<string, Partial<MatrixCondition>>>> }) {
  const set = (key: keyof MatrixCondition, value: string) => onChange((current) => ({ ...current, [condition.condition_id]: { ...(current[condition.condition_id] ?? {}), [key]: value } }));
  const restore = () => onChange((current) => {
    const next = { ...current };
    delete next[condition.condition_id];
    return next;
  });
  return (
    <div className="rounded-md border border-slate-800 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">Revisar configuracion de la condicion</div>
        <div className="flex gap-2">
          <button onClick={() => onMode('matrix')} className={`rounded px-3 py-1 text-xs ${mode === 'matrix' ? 'bg-cyan-700' : 'border border-slate-700'}`}>Usar valores de matriz</button>
          <button onClick={() => onMode('edit')} className={`rounded px-3 py-1 text-xs ${mode === 'edit' ? 'bg-cyan-700' : 'border border-slate-700'}`}>Modificar esta condicion</button>
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-400">Los cambios puntuales no modifican silenciosamente toda la campana. Los campos derivados de captura no son editables aqui.</p>
      {mode === 'edit' && (
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <input className={inputClass} value={condition.condition_id} onChange={(event) => set('condition_id', event.target.value)} />
          <input className={inputClass} value={condition.positive_session_id} onChange={(event) => set('positive_session_id', event.target.value)} />
          <input className={inputClass} value={condition.negative_session_id} onChange={(event) => set('negative_session_id', event.target.value)} />
          <input className={inputClass} value={condition.power_cycle_id} onChange={(event) => set('power_cycle_id', event.target.value)} />
          <input className={inputClass} value={condition.distance} onChange={(event) => set('distance', event.target.value)} />
          <input className={inputClass} value={condition.orientation} onChange={(event) => set('orientation', event.target.value)} />
          <input className={inputClass} value={condition.location} onChange={(event) => set('location', event.target.value)} />
          <input className={inputClass} value={condition.operator_notes} placeholder="operator_notes" onChange={(event) => set('operator_notes', event.target.value)} />
          <input className={inputClass} value={condition.environment_notes} placeholder="environment_notes" onChange={(event) => set('environment_notes', event.target.value)} />
          <button onClick={restore} className="rounded-md border border-slate-600 px-3 py-2 text-sm">Restaurar matriz</button>
        </div>
      )}
    </div>
  );
}

function OperatorWizardBlock({ title, doing, user, expected, failure, actionLabel, onAction, disabled = false, children }: { title: string; doing: string; user: string; expected: string; failure: string; actionLabel: string; onAction?: () => void; disabled?: boolean; children?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-800 p-4">
      <div className="text-sm font-semibold text-cyan-100">{title}</div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric title="Que comprueba" value={doing} detail="plataforma" />
        <Metric title="Que debe hacer" value={user} detail="operador" />
        <Metric title="Resultado esperado" value={expected} detail="para continuar" />
        <Metric title="Si falla" value={failure} detail="accion segura" />
      </div>
      {children && <div className="mt-4">{children}</div>}
      {onAction && (
        <button onClick={onAction} disabled={disabled} className="mt-4 inline-flex h-11 items-center gap-2 rounded-md bg-cyan-700 px-4 text-sm font-semibold disabled:opacity-40">
          <CheckCircle2 className="h-4 w-4" />{actionLabel}
        </button>
      )}
    </div>
  );
}

function PrepareStep({ condition, profile, target, targetAgeMs, preflightValid, native, busy, started, deviceConfirmed, conditionSaved, positionPrepared, physicalPrepared, targetPowerConfirmedAt, onStartWizard, onConfirmDevice, onSaveCondition, onPositionPrepared, onPhysicalPrepared, onConfirmPower, onScan, onChange, metadataMode, onMode }: { condition: MatrixCondition; profile: DeviceProfile; target: BleNativeDevice | null; targetAgeMs: number; preflightValid: boolean; native: BleNativeStatus | null; busy: string; started: boolean; deviceConfirmed: boolean; conditionSaved: boolean; positionPrepared: boolean; physicalPrepared: boolean; targetPowerConfirmedAt: string | null; onStartWizard: () => void; onConfirmDevice: () => void; onSaveCondition: () => void; onPositionPrepared: () => void; onPhysicalPrepared: () => void; onConfirmPower: () => void; onScan: () => void; onChange: React.Dispatch<React.SetStateAction<Record<string, Partial<MatrixCondition>>>>; metadataMode: 'matrix' | 'edit'; onMode: (mode: 'matrix' | 'edit') => void }) {
  const conditionValid = validateCondition(condition, profile, [condition]).length === 0;
  return (
    <div className="space-y-4">
      {!started && (
        <OperatorWizardBlock
          title="Paso 0 - Preparacion de la captura positiva piloto"
          doing="Presenta el estado actual y bloquea fases futuras."
          user="No encienda todavia el SensorTag."
          expected="S001-POS sera la unica ejecucion permitida."
          failure="Si intenta avanzar a negativa, dataset o training, el flujo queda bloqueado."
          actionLabel="Comenzar preparacion de S001-POS"
          onAction={onStartWizard}
        >
          <div className="grid gap-2 md:grid-cols-3">
            <Metric title="Diagnostico de adquisicion" value="COMPLETADO" detail="A-E cerrado" />
            <Metric title="Cualificacion B200" value="SUPERADA" detail="3 limpias consecutivas" />
            <Metric title="Cualificacion Windows BLE-B200" value="SUPERADA" detail="3 limpias consecutivas" />
            <Metric title="Captura positiva S001-POS" value="SIGUIENTE" detail="unica accion" />
            <Metric title="Control negativo" value="BLOQUEADO" detail="hasta positiva aceptada" />
            <Metric title="Dataset / Training" value="BLOQUEADO" detail="sin autoavance" />
          </div>
        </OperatorWizardBlock>
      )}

      {started && !deviceConfirmed && (
        <OperatorWizardBlock
          title="Paso 1 - Comprobacion automatica del sistema"
          doing="Comprueba B200 disponible, Windows BLE disponible, perfil 10 s, gate v2 y ausencia de captura activa. El backend validara el commit limpio al iniciar."
          user="Mantenga el B200 en el mismo USB 3. No cambie cable, puerto ni abra otra aplicacion SDR. No encienda aun el SensorTag."
          expected="Sistema preparado para seleccionar la unidad fisica."
          failure="Si falta B200, USB 3, Windows BLE o el arbol Git limpio, no se inicia la positiva."
          actionLabel="Continuar a seleccion del dispositivo"
          onAction={onConfirmDevice}
          disabled={!native?.available}
        >
          <div className="grid gap-2 md:grid-cols-3">
            <Metric title="B200" value="validado por backend" detail="serial exacto E3R04Z1B2" />
            <Metric title="Windows BLE" value={native?.available ? 'disponible' : 'no disponible'} detail={native?.backend ?? '-'} />
            <Metric title="Perfil" value="10 s / cf32_le / USB 3" detail="QPROFILE-Z1B2..." />
            <Metric title="Git" value="validacion backend" detail="CLEAN requerido" />
            <Metric title="Gate" value={POSITIVE_PILOT_QUALITY_GATE_VERSION} detail="v2" />
            <Metric title="Captura activa" value="ninguna requerida" detail="si existe, backend bloquea" />
          </div>
        </OperatorWizardBlock>
      )}

      {started && deviceConfirmed && !conditionSaved && (
        <OperatorWizardBlock
          title="Paso 2 - Seleccion del dispositivo fisico"
          doing="Carga la unidad fisica esperada y su identidad logica declarada."
          user="Compruebe fisicamente la etiqueta del SensorTag. No use otro CC2650 ni otro BLE."
          expected="El operador confirma CC2650-UNIT-01 como objetivo."
          failure="Si no puede identificarlo, no continue: revise la etiqueta fisica o el registro."
          actionLabel="Confirmo que el dispositivo fisico es CC2650-UNIT-01"
          onAction={onSaveCondition}
          disabled={profile.physical_unit_id !== 'CC2650-UNIT-01'}
        >
          <ConditionSummary condition={condition} profile={profile} />
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            <Metric title="physical_unit_id" value={profile.physical_unit_id} detail="debe ser CC2650-UNIT-01" />
            <Metric title="display_name" value={profile.display_name || 'TI SensorTag CC2650'} detail="referencia fisica" />
            <Metric title="logical_address_expected" value={profile.logical_address || 'B0:B4:48:C0:36:06'} detail="se verificara en preflight" />
          </div>
        </OperatorWizardBlock>
      )}

      {started && deviceConfirmed && conditionSaved && !positionPrepared && (
        <OperatorWizardBlock
          title="Paso 3 - Condicion experimental C001"
          doing="Prepara condition_id=C001 y session_id=S001-POS con metadatos trazables."
          user="Confirme distancia, orientacion, ubicacion, posiciones y notas. Distancia es separacion SensorTag-antena; orientacion 0 deg es la referencia del protocolo."
          expected="Metadatos obligatorios completos y coherentes."
          failure="Si falta distancia con unidad, ubicacion o power_cycle_id, el backend rechaza la captura."
          actionLabel="Guardar condicion C001"
          onAction={onPositionPrepared}
          disabled={!conditionValid}
        >
          <ConditionReview condition={condition} mode={metadataMode} onMode={onMode} onChange={onChange} />
          {!conditionValid && <p className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">Complete distance_m con unidad, orientation_deg, location_id y power_cycle_id antes de continuar.</p>}
        </OperatorWizardBlock>
      )}

      {started && deviceConfirmed && conditionSaved && positionPrepared && !physicalPrepared && (
        <OperatorWizardBlock
          title="Paso 4 - Preparacion fisica antes de encender"
          doing="Comprueba que la escena fisica coincide con la condicion declarada antes de activar el objetivo."
          user="Coloque el SensorTag en la posicion declarada, mantenga distancia y orientacion, aleje otros CC2650 controlados y confirme que el B200 sigue en USB 3. No encienda todavia el SensorTag."
          expected="La posicion esta preparada sin trafico objetivo todavia."
          failure="Si otro dispositivo controlado esta cerca o el objetivo se mueve, la asociacion puede quedar ambigua."
          actionLabel="La posicion esta preparada"
          onAction={onPhysicalPrepared}
        />
      )}

      {started && deviceConfirmed && conditionSaved && positionPrepared && physicalPrepared && !targetPowerConfirmedAt && (
        <OperatorWizardBlock
          title="Paso 5 - Momento exacto de encender el SensorTag"
          doing="Registra la declaracion fisica de que el objetivo se ha encendido para esta positiva."
          user="Encienda ahora el SensorTag CC2650-UNIT-01. No pulse otros botones, no lo conecte mediante GATT y no lo mueva."
          expected="operator_declared_target_powered_on=true con timestamp UTC."
          failure="Si no puede confirmar que el objetivo correcto esta encendido, vuelva a la seleccion del dispositivo."
          actionLabel="Confirmo que CC2650-UNIT-01 esta encendido"
          onAction={onConfirmPower}
        />
      )}

      {started && deviceConfirmed && conditionSaved && positionPrepared && physicalPrepared && targetPowerConfirmedAt && (
        <OperatorWizardBlock
          title="Paso 6 - Preflight Windows BLE"
          doing="Ejecuta un escaneo BLE actual para comprobar que Windows observa la identidad logica esperada."
          user="Espere sin mover ni apagar el SensorTag. No conecte el dispositivo con otra aplicacion BLE."
          expected="Objetivo observado, direccion esperada y preflight vigente."
          failure="Si no aparece, repita escaneo. Si aparece otra direccion, no se inicia B200."
          actionLabel={preflightValid ? 'Preflight valido: pasar a revision final' : 'Iniciar comprobacion BLE'}
          onAction={preflightValid ? undefined : onScan}
          disabled={Boolean(busy)}
        >
          <div className="grid gap-3 md:grid-cols-3">
            <Metric title="objetivo encontrado" value={preflightValid ? 'si' : 'no'} detail={profile.logical_address || 'not_observed'} />
            <Metric title="ultima observacion" value={target?.last_seen_utc ?? '-'} detail={target ? `${Math.max(0, Math.round(targetAgeMs / 1000))} s de antiguedad` : 'sin observacion'} />
            <Metric title="preflight" value={preflightValid ? 'VALIDO' : 'NO VALIDO'} detail={`scan ${native?.scan_session_id ?? '-'}`} />
            <Metric title="encendido confirmado" value={targetPowerConfirmedAt} detail="operator_declared_target_powered_on" />
          </div>
          {preflightValid && <p className="mt-3 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">Preflight valido. La siguiente pantalla mostrara la revision final no editable antes de iniciar S001-POS.</p>}
        </OperatorWizardBlock>
      )}
    </div>
  );
}

function CaptureDurationControl({ value, max, onChange }: { value: number; max: number; onChange: (value: number) => void }) {
  return (
    <div className="rounded-md border border-slate-800 p-4">
      <div className="font-semibold">Duracion de captura B200</div>
      <p className="mt-1 text-xs text-slate-400">Ajuste operativo de tiempo. Campanas cortas son mas rapidas; campanas largas pueden dar mas paquetes pero tardan mas y ocupan mas disco.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <input type="range" min={3} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} className="w-64" />
        <input className={`${inputClass} w-24`} type="number" min={3} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} />
        <Badge>{value} s</Badge>
      </div>
    </div>
  );
}

function PositiveStep({ condition, profile, busy, durationSeconds, maxDurationSeconds, onStart }: { condition: MatrixCondition; profile: DeviceProfile; busy: string; durationSeconds: number; maxDurationSeconds: number; onStart: () => void }) {
  return (
    <div className="space-y-4">
      <OperatorWizardBlock
        title="Paso 7 - Revision final antes de capturar"
        doing="Congela el contrato y prepara la unica ejecucion permitida: C001 / S001-POS."
        user="Durante los proximos 10 segundos no mueva, apague ni conecte el SensorTag. No cierre la pagina ni abra otras aplicaciones SDR."
        expected="El backend validara contrato, commit limpio, perfil, gate v2 y receptor antes de arrancar hardware."
        failure="Si aparece PROTOCOL_FREEZE_MISMATCH, no se captura: corrija el campo indicado y no modifique thresholds."
        actionLabel="Iniciar S001-POS"
        onAction={onStart}
        disabled={Boolean(busy)}
      >
        <ConditionSummary condition={condition} profile={profile} />
      </OperatorWizardBlock>
      <div className="rounded-md border border-slate-800 p-4">
        <div className="font-semibold">Resumen no editable del protocolo congelado</div>
        <p className="mt-1 text-xs text-slate-400">No cambie duracion, sample rate, frecuencia, bandwidth, ganancia, antena ni formato antes de S001-POS. Cualquier cambio critico requiere REQUALIFICATION_REQUIRED.</p>
        <div className="mt-3 grid gap-2 md:grid-cols-4">
          <Metric title="Dispositivo" value={profile.physical_unit_id} detail={profile.logical_address || 'B0:B4:48:C0:36:06'} />
          <Metric title="Finalidad" value="POSITIVE_PILOT" detail={`${condition.condition_id} / ${condition.positive_session_id}`} />
          <Metric title="duration_seconds" value={`${durationSeconds} s`} detail={`max backend ${maxDurationSeconds}s`} />
          <Metric title="BLE CH37" value="2402 MHz" detail="center_frequency_hz" />
          <Metric title="sample_rate_sps" value="4 MS/s" detail="4000000" />
          <Metric title="bandwidth_hz" value="2 MHz" detail="2000000" />
          <Metric title="Formato" value="cf32_le" detail="cpu cf32" />
          <Metric title="USB / RF" value="USB 3 / RX2 / G20" detail="perfil cualificado" />
          <Metric title="expected_samples" value={formatNumber(QUALIFICATION_EXPECTED_SAMPLES)} detail="4 MS/s" />
          <Metric title="expected_file_size_bytes" value={formatNumber(QUALIFICATION_EXPECTED_FILE_SIZE)} detail="cf32_le" />
          <Metric title="E4_MINIMAL_OBSERVED" value={`${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION}`} detail="paquete unico CRC fuerte" />
          <Metric title="E4_ACCEPTED_FOR_DATASET" value={`${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE}`} detail="strong-only sin conflicto" />
        </div>
      </div>
      <div className="rounded-md border border-slate-800 p-4">
        <div className="font-semibold">Criterios de aceptacion S001-POS</div>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Metric title="preflight_valid_at_capture_start" value="true requerido" detail="Windows BLE vio objetivo" />
          <Metric title="adquisicion" value="PASSED requerido" detail="0 overflow/discontinuity/short/write/queue" />
          <Metric title="artifact_integrity_status" value="VERIFIED requerido" detail="hash y manifiesto completos" />
          <Metric title="ground_truth_status" value="PASSED_E4 requerido" detail="asociacion aceptada" />
          <Metric title="dataset_eligibility_status" value="ELIGIBLE requerido" detail="solo si pasa todo" />
          <Metric title="si falla" value="S001-NEG sigue BLOCKED" detail="una positiva fallida nunca es negativa" />
        </div>
        <p className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
          Un unico paquete fuerte puede producir E4_MINIMAL_OBSERVED, pero no acepta la sesion para dataset. La aceptacion cientifica del piloto exige {MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE} paquetes unicos CRC validos strong-only y cero conflictos.
        </p>
      </div>
      <button onClick={() => window.history.back()} disabled={Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-600 px-3 text-sm disabled:opacity-40">
        Cancelar y volver
      </button>
    </div>
  );
}

function NegativeStep({ condition, profile, absence, absenceValid, confirmed, busy, durationSeconds, maxDurationSeconds, lockedDurationSeconds, onDuration, onVerify, onConfirm, onStart, onChange, metadataMode, onMode }: { condition: MatrixCondition; profile: DeviceProfile; absence: AbsenceVerification | null; absenceValid: boolean; confirmed: boolean; busy: string; durationSeconds: number; maxDurationSeconds: number; lockedDurationSeconds?: number; onDuration: (value: number) => void; onVerify: () => void; onConfirm: (value: boolean) => void; onStart: () => void; onChange: React.Dispatch<React.SetStateAction<Record<string, Partial<MatrixCondition>>>>; metadataMode: 'matrix' | 'edit'; onMode: (mode: 'matrix' | 'edit') => void }) {
  const targetSeen = absence?.conditionId === condition.condition_id && absence.targetSeen;
  return (
    <div className="space-y-4">
      <Instruction title="Control negativo" text={`Apague fisicamente o retire ${profile.physical_unit_id}. No basta con desconectar GATT; la condicion negativa exige ausencia RF/BLE del objetivo.`} />
      <ConditionSummary condition={condition} profile={profile} />
      <ConditionReview condition={condition} mode={metadataMode} onMode={onMode} onChange={onChange} />
      {lockedDurationSeconds ? (
        <div className="rounded-md border border-slate-800 p-4">
          <div className="font-semibold">Duracion de captura B200</div>
          <p className="mt-1 text-xs text-slate-400">Bloqueada por la positiva de esta condicion. Positiva y negativa deben usar la misma duracion.</p>
          <div className="mt-3"><Badge>{durationSeconds} s Â· protocol locked</Badge></div>
        </div>
      ) : <CaptureDurationControl value={durationSeconds} max={maxDurationSeconds} onChange={onDuration} />}
      <div className="grid gap-3 md:grid-cols-3">
        <Metric title="ausencia" value={absenceValid ? 'verificada' : targetSeen ? 'objetivo visto' : 'pendiente'} detail={absence?.checkedAt ?? 'sin preflight negativo'} />
        <Metric title="validez temporal" value={absenceValid ? 'vigente' : 'no vigente'} detail={`${ABSENCE_SCAN_SECONDS} s de escucha`} />
        <Metric title="confirmacion" value={confirmed ? 'confirmada' : 'pendiente'} detail="operador" />
      </div>
      {!absenceValid ? (
        <button onClick={onVerify} disabled={Boolean(busy)} className="inline-flex h-11 items-center gap-2 rounded-md bg-sky-700 px-4 text-sm font-semibold disabled:opacity-40">
          <ScanSearch className="h-4 w-4" />Verificar ausencia del objetivo
        </button>
      ) : !confirmed ? (
        <label className="inline-flex min-h-11 items-center gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 text-sm">
          <input type="checkbox" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} />
          Confirmo que {profile.physical_unit_id} esta fisicamente apagado
        </label>
      ) : (
        <button onClick={onStart} disabled={Boolean(busy)} className="inline-flex h-11 items-center gap-2 rounded-md bg-violet-700 px-4 text-sm font-semibold disabled:opacity-40">
          <ShieldCheck className="h-4 w-4" />Confirmar e iniciar control negativo
        </button>
      )}
    </div>
  );
}

function RepeatStep({ profile, completed, total, next, onRefresh }: { profile: DeviceProfile; completed: number; total: number; next?: MatrixCondition; onRefresh: () => void }) {
  return (
    <div className="space-y-4">
      <Instruction title={`Sesion completada (${completed}/${total})`} text="Prepare la siguiente condicion generada por la matriz congelada." />
      {next ? <ConditionSummary condition={next} profile={profile} /> : <Empty text="Todas las condiciones estan completadas" />}
      <button onClick={onRefresh} className="inline-flex h-11 items-center gap-2 rounded-md bg-cyan-700 px-4 text-sm font-semibold">
        <RefreshCw className="h-4 w-4" />Cargar siguiente condicion
      </button>
    </div>
  );
}

function DatasetStep({ datasetManifest, datasetId, datasetKnown }: { datasetManifest: Record<string, unknown> | null; datasetId: string; datasetKnown: boolean }) {
  return (
    <div className="space-y-4">
      <Instruction title="Dataset" text="Genere ejemplos packet-aligned, revise QC, cree split por sesion y compruebe fuga." />
      <div className="grid gap-3 md:grid-cols-4">
        <Metric title="dataset_id" value={statusText(datasetManifest?.dataset_id ?? datasetId)} detail="reservado" />
        <Metric title="manifest_status" value={datasetKnown ? statusText(datasetManifest?.state ?? 'available') : 'planned'} detail="manifest" />
        <Metric title="collection_status" value="in_progress" detail="campana en curso" />
        <Metric title="readiness" value={statusText(datasetManifest?.training_readiness ?? 'pendiente')} detail="training readiness" />
        <Metric title="ejemplos incluidos" value={formatNumber(datasetManifest?.examples_included)} detail="Dataset Studio" />
      </div>
      {!datasetKnown && <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">El dataset esta definido y reservado, pero todavia no contiene ejemplos aceptados. El manifiesto persistente se generara cuando existan capturas elegibles.</p>}
      <Link to="/ble-lab" className="inline-flex h-11 items-center gap-2 rounded-md bg-emerald-700 px-4 text-sm font-semibold">
        <Database className="h-4 w-4" />Ir a Dataset Studio
      </Link>
    </div>
  );
}

function StageGuide({ stages, current }: { stages: { step: CampaignStep; title: string; action: string; expected: string; blocked: string }[]; current: CampaignStep }) {
  const currentIndex = stageOrder(current);
  return (
    <Panel title="Flujo guiado y bloqueo cientifico">
      <div className="grid gap-2">
        {stages.map((stage) => {
          const index = stageOrder(stage.step);
          const state: StageState = index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'locked';
          const style = state === 'done'
            ? 'border-emerald-500/40 bg-emerald-500/10'
            : state === 'active'
              ? 'border-cyan-500/50 bg-cyan-500/10'
              : 'border-slate-800 bg-slate-900/70 opacity-75';
          if (state !== 'active') {
            return (
              <div key={stage.step} className={`flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 ${style}`}>
                <span className="text-sm font-semibold">{stage.title}</span>
                <Badge>{state === 'done' ? 'completado' : 'bloqueado'}</Badge>
              </div>
            );
          }
          return (
            <div key={stage.step} className={`rounded-md border p-4 ${style}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="font-semibold">{stage.title}</div>
                <Badge>AHORA</Badge>
              </div>
              <details className="mt-3" open>
                <summary className="cursor-pointer text-sm font-semibold text-slate-200">Mas informacion</summary>
                <div className="mt-3 text-sm text-slate-200"><b>Accion:</b> {stage.action}</div>
                <div className="mt-2 text-sm text-slate-300"><b>Debe salir:</b> {stage.expected}</div>
                <div className="mt-2 text-xs leading-5 text-slate-400"><b>Si no sale:</b> {stage.blocked}</div>
              </details>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function operationSnapshot(session: BleHybridSession | null, qualificationJob?: BleCaptureJob | null, qualificationLive?: BleCaptureLive | null) {
  if (!session && qualificationJob) {
    const samples = Number(qualificationLive?.samples_received ?? 0);
    if (qualificationJob.state === 'running') {
      return {
        phase: 'Adquisicion critica B200-only',
        percent: Math.round(5 + 90 * Math.min(1, samples / QUALIFICATION_EXPECTED_SAMPLES)),
        detail: `${formatNumber(samples)} de ${formatNumber(QUALIFICATION_EXPECTED_SAMPLES)} muestras esperadas`,
      };
    }
    if (qualificationJob.state === 'completed') return { phase: 'Cierre, hash y comprobacion de perdidas', percent: 100, detail: 'Diagnostico terminal; revise criterios de cualificacion.' };
    if (terminalStates.has(qualificationJob.state)) return { phase: `Diagnostico terminado: ${statusText(qualificationJob.state)}`, percent: 100, detail: qualificationJob.error || 'job terminal' };
    return { phase: `Diagnostico B200: ${statusText(qualificationJob.state)}`, percent: 10, detail: 'Esperando telemetria de captura.' };
  }
  if (!session) return { phase: 'Sin operacion activa', percent: 0, detail: 'No hay captura o procesamiento en curso.' };
  const expectedSamples = Math.max(1, Number(session.duration_seconds || 30) * 4_000_000);
  const samples = Number(session.live?.telemetry?.samples_received ?? 0);
  const totalSegments = Number(session.decode_progress?.total_segments ?? session.counters?.detected_bursts ?? 0);
  const processedSegments = Number(session.decode_progress?.processed_segments ?? session.counters?.processed_bursts ?? 0);
  if (session.state === 'capturing') {
    return {
      phase: 'Capturando I/Q B200 + observaciones Windows BLE',
      percent: Math.round(5 + 45 * Math.min(1, samples / expectedSamples)),
      detail: `${formatNumber(samples)} de ${formatNumber(expectedSamples)} muestras esperadas`,
    };
  }
  if (session.state === 'decoding') {
    return {
      phase: 'Detectando rafagas y decodificando CRC',
      percent: Math.round(55 + 25 * (totalSegments ? processedSegments / totalSegments : 0)),
      detail: `${formatNumber(processedSegments)} de ${formatNumber(totalSegments)} segmentos procesados`,
    };
  }
  if (session.state === 'correlating') {
    return {
      phase: 'Correlacionando Windows BLE con B200',
      percent: 88,
      detail: `${formatNumber(session.counters?.strong_matches)} coincidencias fuertes actuales`,
    };
  }
  if (session.state === 'completed') return { phase: 'Procesamiento completado', percent: 100, detail: 'La decision cientifica ya puede revisarse.' };
  if (terminalStates.has(session.state)) return { phase: `Terminado: ${statusText(session.state)}`, percent: 100, detail: session.error || 'Sesion terminal.' };
  return { phase: `Backend: ${statusText(session.state)}`, percent: 15, detail: 'Esperando telemetria de la sesion.' };
}

function OperationAuditPanel({ activeSession, qualificationJob, qualificationLive, busy, events }: { activeSession: BleHybridSession | null; qualificationJob: BleCaptureJob | null; qualificationLive: BleCaptureLive | null; busy: string; events: OperationEvent[] }) {
  const snapshot = operationSnapshot(activeSession, qualificationJob, qualificationLive);
  const elapsed = activeSession?.created_at_utc ? Math.max(0, Math.round((Date.now() - new Date(activeSession.created_at_utc).getTime()) / 1000)) : 0;
  const telemetry = activeSession?.live?.telemetry;
  const diagnosticTelemetry = qualificationLive;
  const metadata = activeSession?.experimental_metadata ?? {};
  const rows = [
    ['Estado backend', statusText(activeSession?.state ?? qualificationJob?.state ?? (busy || 'idle')), activeSession?.session_id ?? qualificationJob?.capture_id ?? 'sin sesion'],
    ['Fase exacta', snapshot.phase, snapshot.detail],
    ['Tiempo transcurrido', activeSession ? `${elapsed} s` : '-', activeSession ? `duracion nominal ${activeSession.duration_seconds}s` : 'sin reloj activo'],
    ['Preflight al iniciar', statusText(metadata.preflight_valid_at_capture_start), `${statusText(metadata.preflight_age_at_capture_start_seconds)} s de antiguedad`],
    ['Preflight actual', activeSession ? 'no aplica retrospectivamente' : '-', 'puede caducar despues de iniciar'],
    ['Objetivo durante captura', statusText(metadata.target_seen_during_capture), 'se resuelve durante procesamiento'],
    ['Windows BLE', statusText(activeSession?.steps?.native_scan), 'adaptador nativo / ground truth'],
    ['B200 I/Q', statusText(activeSession?.steps?.b200_capture), `CH${activeSession?.channel ?? 37}`],
    ['Muestras', formatNumber(telemetry?.samples_received ?? diagnosticTelemetry?.samples_received), `${formatNumber(telemetry?.bytes_written ?? diagnosticTelemetry?.bytes_written)} bytes escritos`],
    ['Overflows', formatNumber(telemetry?.stream_overflows ?? diagnosticTelemetry?.stream_overflows ?? activeSession?.counters?.overflows), 'deben ser 0 para entrenamiento limpio'],
    ['Discontinuidades', formatNumber(telemetry?.input_discontinuities ?? diagnosticTelemetry?.input_discontinuities ?? activeSession?.counters?.discontinuities), 'deben ser 0 para entrenamiento limpio'],
    ['Rafagas', formatNumber(activeSession?.counters?.detected_bursts), `${formatNumber(activeSession?.counters?.processed_bursts)} procesadas`],
    ['CRC validos', formatNumber(activeSession?.decode_progress?.crc_valid_packets ?? activeSession?.counters?.crc_valid_packets), 'evidencia RF decodificada'],
    ['Coincidencias', formatNumber(activeSession?.counters?.strong_matches), 'correlacion Windows-B200'],
    ['Potencia RF', telemetry?.average_power_dbfs == null ? '-' : `${Number(telemetry.average_power_dbfs).toFixed(1)} dBFS`, telemetry?.clipping_percentage == null ? 'clipping no disponible' : `clipping ${Number(telemetry.clipping_percentage).toFixed(3)}%`],
  ];
  return (
    <Panel title="Ventana de progreso operacional">
      <div className="space-y-4">
        <div className="rounded-md border border-sky-500/40 bg-sky-500/10 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-sky-100">{snapshot.phase}</div>
              <div className="mt-1 text-xs text-slate-300">{snapshot.detail}</div>
            </div>
            <Badge>{snapshot.percent}%</Badge>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded bg-slate-800">
            <div className="h-full bg-sky-400 transition-all" style={{ width: `${Math.max(3, Math.min(100, snapshot.percent))}%` }} />
          </div>
        </div>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {rows.map(([name, value, detail]) => <Metric key={name} title={String(name)} value={value} detail={String(detail)} />)}
        </div>
        <div className="rounded-md border border-slate-800 p-3">
          <div className="mb-2 text-sm font-semibold">Registro de operaciones recientes</div>
          <div className="max-h-44 overflow-auto text-xs">
            {events.length ? events.map((event) => (
              <div key={event.id} className={`border-t border-slate-800 py-2 ${event.state === 'error' ? 'text-rose-200' : event.state === 'done' ? 'text-emerald-200' : 'text-slate-300'}`}>
                <span className="font-mono text-slate-500">{event.at}</span> Â· <b>{event.phase}</b> Â· {event.detail}
              </div>
            )) : <div className="py-2 text-slate-500">Todavia no hay eventos registrados en este dashboard.</div>}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function OfflineReplayStep({ session, capture, diagnostic, replay, job, busy, onRun, onContinue, onCancel }: { session?: BleHybridSession; capture?: BleCaptureRecord; diagnostic: BleRfDiagnostic | null; replay: BleOfflineReplay | null; job: BleOfflineReplayJob | null; busy: string; onRun: () => void; onContinue: () => void; onCancel: () => void }) {
  const funnel = replay?.candidate_funnel ?? {};
  const decision = replay?.decision ?? {};
  const association = replay?.target_association_results ?? {};
  const rejection = replay?.candidate_rejection_summary ?? {};
  const diagnosticCandidates = Number(diagnostic?.burst_detection_replay?.candidate_count ?? 0);
  const progress: Partial<BleOfflineReplayProgress> = job?.progress ?? replay?.coverage ?? {};
  const jobRunning = Boolean(job && !terminalStates.has(job.state));
  const cancelSupported = job?.cancel_supported !== false;
  const incomplete = replay ? replay.scientific_completion_status !== 'COMPLETE' : false;
  const resumeAvailable = Boolean(!jobRunning && (job?.resume_available || replay?.resume_available));
  const coveragePercent = Number(progress.coverage_percentage ?? job?.progress_percent ?? 0);
  return (
    <div className="space-y-4">
      <OperatorWizardBlock
        title="Replay offline detector/decoder requerido"
        doing="Reanaliza el I/Q ya preservado y localiza donde se descartan los candidatos RF."
        user="No encienda ni apague nada para esta etapa. El SensorTag no interviene: no hay captura B200 nueva."
        expected="Embudo completo, descartes, CRC validos, asociacion temporal Windows preservada y decision cientifica."
        failure="Si falla procedencia, SHA o configuracion RF, el replay se rechaza sin modificar el I/Q original."
        actionLabel={resumeAvailable ? 'Ejecutar nuevo replay (desde cero)' : 'Ejecutar replay detector/decoder'}
        onAction={onRun}
        disabled={!session?.capture_id || busy === 'offline-replay' || jobRunning}
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric title="stage" value="OFFLINE_DETECTOR_DECODER_REPLAY_REQUIRED" detail="hardware bloqueado" />
        <Metric title="execution_id" value={session?.session_id ?? '-'} detail="fuente unica de verdad" />
        <Metric title="capture_id" value={session?.capture_id ?? '-'} detail="I/Q preservado" />
        <Metric title="iq_sha256" value={shortHash(String(capture?.data_sha256 ?? replay?.iq_sha256 ?? '-'))} detail="esperado/verificado" />
        <Metric title="campaign_id" value={statusText(session?.experimental_metadata?.campaign_id)} detail={statusText(session?.experimental_metadata?.condition_id)} />
        <Metric title="session_role" value={statusText(session?.experimental_metadata?.session_id)} detail={statusText(session?.experimental_metadata?.execution_purpose)} />
        <Metric title="pre_decoder_candidate_regions" value={formatNumber(diagnosticCandidates || funnel.pre_decoder_candidate_regions)} detail="no son paquetes BLE todavia" />
        <Metric title="decision" value={statusText(decision.decision ?? 'PENDING')} detail={statusText(decision.dataset_eligibility_status ?? 'NO_DATASET')} />
      </div>
      {job && (
        <div className="rounded-md border border-slate-800 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-100">Replay job: {job.replay_run_id}</div>
              <div className="mt-1 text-xs text-slate-400">
                {statusText(job.state)} - {formatNumber(progress.processed_segments)} / {formatNumber(progress.total_candidate_segments)} segmentos - {formatNumber(progress.pending_segments)} pendientes - {formatNumber(progress.failed_segments)} fallidos
              </div>
            </div>
            <div className="flex gap-2">
              {jobRunning && cancelSupported && (
                <button onClick={onCancel} className="inline-flex h-10 items-center gap-2 rounded-md border border-rose-500 px-3 text-sm font-semibold text-rose-100">
                  <XCircle className="h-4 w-4" />Cancelar de forma ordenada
                </button>
              )}
              {resumeAvailable && (
                <button onClick={onContinue} disabled={busy === 'offline-replay'} className="inline-flex h-10 items-center gap-2 rounded-md bg-cyan-600 px-3 text-sm font-semibold text-white disabled:opacity-40">
                  Continuar desde checkpoint
                </button>
              )}
            </div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded bg-slate-800">
            <div className="h-full bg-cyan-400" style={{ width: `${Math.max(0, Math.min(100, coveragePercent))}%` }} />
          </div>
          <div className="mt-1 text-xs text-slate-400">{coveragePercent.toFixed(2)}% cobertura - checkpoint #{formatNumber(progress.checkpoint_sequence)} - ultimo checkpoint {statusText(progress.last_checkpoint_at)}</div>
          <p className="mt-2 text-xs text-slate-400">{cancelSupported ? 'Cancelar conserva los artefactos parciales, guarda checkpoint y no convierte esta captura en dataset ni en negativa.' : 'Este replay fue iniciado con el flujo sincronico anterior; muestra progreso, pero no puede cancelarse desde este job.'}</p>
        </div>
      )}
      {replay && (
        <div className="space-y-3">
          {incomplete && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
              <div className="font-semibold">Replay incompleto: decision cientifica no emitida</div>
              <p className="mt-1 text-slate-200">
                {statusText(replay.execution_status)} ({statusText(replay.termination_reason)}). Quedan {formatNumber(replay.coverage?.pending_segments)} de {formatNumber(replay.coverage?.total_candidate_segments)} segmentos pendientes.
                Alcance de la decision: {statusText(replay.decision_scope)}. No avance a S001-NEG, dataset ni entrenamiento mientras pending_segments &gt; 0.
              </p>
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Metric title="coverage_percentage" value={`${Number(replay.coverage?.coverage_percentage ?? 0).toFixed(2)}%`} detail={`${formatNumber(replay.coverage?.pending_segments)} pendientes`} />
            <Metric title="energy_excursion_groups" value={formatNumber(funnel.energy_excursion_groups)} detail="energia agrupada" />
            <Metric title="duration_filtered_candidates" value={formatNumber(funnel.duration_filtered_candidates)} detail="filtro duracion" />
            <Metric title="gfsk_demodulation_attempts" value={formatNumber(funnel.gfsk_demodulation_attempts)} detail="hipotesis procesadas" />
            <Metric title="crc_valid_packets" value={formatNumber(funnel.crc_valid_packets)} detail={`${formatNumber(funnel.unique_crc_valid_packets)} unicos`} />
            <Metric title="target_address_candidates" value={formatNumber(funnel.target_address_candidates)} detail="direccion objetivo en paquete" />
            <Metric title="strong_target_matches" value={formatNumber(funnel.strong_target_matches)} detail={`${formatNumber(funnel.conflicting_matches)} conflictos`} />
            <Metric title="target callbacks" value={formatNumber(association.windows_target_callbacks_inside_window)} detail="solo ventana original" />
            <Metric title="rejected_duration" value={formatNumber(rejection.rejected_duration)} detail="muestra acotada preservada" />
            <Metric title="decoder_timeout / error" value={`${formatNumber(funnel.decoder_timeout_count)} / ${formatNumber(funnel.decoder_internal_error_count)}`} detail={`${formatNumber(funnel.worker_restart_count)} reinicios de worker`} />
            <Metric title="replay_run_id" value={replay.replay_run_id} detail="artefacto nuevo" />
            <Metric title="scientific_completion_status" value={statusText(replay.scientific_completion_status)} detail={statusText(replay.decision_scope)} />
          </div>
          <div className="rounded-md border border-slate-800 p-3 text-sm text-slate-300">
            <div className="font-semibold text-slate-100">Siguiente accion permitida</div>
            <p className="mt-1">{statusText(decision.next_operator_action ?? 'REVIEW_REPLAY_RESULT_BEFORE_ANY_HARDWARE')}</p>
            <p className="mt-2 text-xs text-slate-400">El resultado original de S001-POS permanece preservado. Este replay no genera dataset ni desbloquea entrenamiento por si solo.</p>
          </div>
          {Number(funnel.crc_valid_packets) > 0 && (
            <Link to="/ble-packet-lab" className="inline-flex h-10 items-center gap-2 rounded-md border border-cyan-500 px-3 text-sm font-semibold text-cyan-100 hover:bg-cyan-500/10">
              ANALIZAR CAPTURA EN BLE PACKET LAB
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

function RfDiagnosticPanel({ captureId, diagnostic, profiles, busy, onRun }: { captureId: string; diagnostic: BleRfDiagnostic | null; profiles: Record<string, unknown> | null; busy: string; onRun: () => void }) {
  const burst = diagnostic?.burst_detection_replay ?? {};
  const power = diagnostic?.power ?? {};
  const clipping = diagnostic?.clipping ?? {};
  const integrity = diagnostic?.integrity ?? {};
  const capture = diagnostic?.capture ?? {};
  const psd = diagnostic?.psd ?? {};
  const conclusion = diagnostic?.diagnostic_conclusion ?? {};
  const profileList = Array.isArray(profiles?.profiles) ? profiles?.profiles as Record<string, unknown>[] : [];
  const profile = profileList[0] ?? {};
  const candidates = Number(burst.candidate_count ?? 0);
  const energyPoints = Array.isArray(diagnostic?.energy_time_series) ? diagnostic?.energy_time_series.length : 0;
  const psdPoints = Array.isArray(psd.points) ? psd.points.length : 0;
  return (
    <Panel title="Diagnostico RF previo a repetir S001-POS">
      <div className="space-y-4">
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-amber-100">Separar recepcion RF y detector de rafagas</div>
              <p className="mt-1 text-sm text-slate-300">No avance a S001-NEG, dataset ni entrenamiento. Analice primero el I/Q preservado: si hay energia y candidatos, el problema esta en la configuracion/replay del detector-decoder; si no hay energia, revise la cadena RF fisica.</p>
            </div>
            <button onClick={onRun} disabled={busy === 'rf-diagnostic' || !captureId} className="inline-flex h-10 items-center gap-2 rounded-md bg-amber-600 px-3 text-sm font-semibold text-white disabled:opacity-40">
              <ScanSearch className="h-4 w-4" />Diagnosticar I/Q preservado
            </button>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Metric title="capture_id" value={captureId || '-'} detail="I/Q preservado" />
          <Metric title="muestras reales" value={formatNumber(capture.actual_samples)} detail={`${formatNumber(capture.actual_file_size_bytes)} bytes`} />
          <Metric title="hash e integridad" value={statusText(integrity.data_hash_status)} detail={`metadata ${statusText(integrity.metadata_hash_status)}`} />
          <Metric title="noise floor" value={power.noise_floor_dbfs == null ? '-' : `${Number(power.noise_floor_dbfs).toFixed(2)} dBFS`} detail={`mean ${power.mean_power_dbfs == null ? '-' : Number(power.mean_power_dbfs).toFixed(2)} dBFS`} />
          <Metric title="potencia maxima" value={power.maximum_block_power_dbfs == null ? '-' : `${Number(power.maximum_block_power_dbfs).toFixed(2)} dBFS`} detail={`amplitud ${formatNumber(power.maximum_amplitude)}`} />
          <Metric title="clipping" value={clipping.clipping_percent == null ? '-' : `${Number(clipping.clipping_percent).toFixed(6)}%`} detail={statusText(clipping.status)} />
          <Metric title="threshold detector" value={burst.threshold_dbfs == null ? '-' : `${Number(burst.threshold_dbfs).toFixed(2)} dBFS`} detail={`${formatNumber(burst.active_blocks)} bloques activos`} />
          <Metric title="candidatos pre-decoder" value={formatNumber(burst.candidate_count)} detail={`${formatNumber(burst.energy_excursion_count)} excursiones`} />
          <Metric title="PSD 2402 MHz" value={`${formatNumber(psdPoints)} puntos`} detail={`pico ${psd.peak_frequency_hz ? `${formatNumber(psd.peak_frequency_hz)} Hz` : '-'}`} />
          <Metric title="energia vs tiempo" value={`${formatNumber(energyPoints)} puntos`} detail="serie temporal offline" />
          <Metric title="capa localizada" value={statusText(conclusion.layer)} detail={statusText(conclusion.recommended_next_action)} />
          <Metric title="decision" value={candidates > 0 ? 'REPLAY_DETECTOR_DECODER' : diagnostic ? 'RF_CHAIN_REVIEW' : 'PENDIENTE'} detail="fuera de campana/dataset" />
        </div>
        <div className="rounded-md border border-slate-800 p-3">
          <div className="text-sm font-semibold">Perfil diagnostico independiente</div>
          <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <Metric title="profile_id" value={statusText(profile.diagnostic_profile_id)} detail="no sustituye cualificacion" />
            <Metric title="frecuencia" value={formatNumber(profile.center_frequency_hz)} detail="CH37 / 2402 MHz" />
            <Metric title="sample rates" value={Array.isArray(profile.sample_rate_sps) ? profile.sample_rate_sps.map(formatNumber).join(' / ') : '-'} detail="4/8 MS/s" />
            <Metric title="bandwidth / gain" value={`${formatNumber(profile.bandwidth_hz)} Hz`} detail={Array.isArray(profile.gain_db) ? `G${profile.gain_db.join('/G')}` : '-'} />
          </div>
        </div>
        <p className="text-xs leading-5 text-slate-400">Estas capturas y replays son diagnosticos: `scientific_campaign_member=false`, `dataset_eligible=false`, `qualification_only=true`. Cambiar sample rate, bandwidth o ganancia para campana cientifica requiere `REQUALIFICATION_REQUIRED`.</p>
      </div>
    </Panel>
  );
}

function ActiveGuidance({ session }: { session: BleHybridSession }) {
  const negative = session.campaign_intent === 'negative_control';
  return (
    <div className="rounded-md border border-cyan-500/40 bg-cyan-500/10 p-4">
      <div className="text-lg font-semibold">{negative ? 'Mantenga el SensorTag apagado.' : 'Mantenga el SensorTag encendido.'}</div>
      <p className="mt-1 text-sm text-slate-300">No realice ninguna otra accion hasta que termine la sesion. CRC, correlacion y decision se calcularan despues de finalizar la adquisicion.</p>
    </div>
  );
}

function ActiveSessionCard({ session, onStop, busy }: { session: BleHybridSession; onStop: () => void; busy: string }) {
  const elapsed = session.created_at_utc ? Math.max(0, Math.round((Date.now() - new Date(session.created_at_utc).getTime()) / 1000)) : 0;
  const capturing = session.state === 'capturing';
  const processing = ['decoding', 'correlating'].includes(session.state);
  const metadata = session.experimental_metadata ?? {};
  const logicalSessionId = String(metadata.operator_session_id ?? metadata.session_id ?? sessionOperatorId(session));
  const conditionId = sessionConditionId(session);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Metric title="condition_id" value={conditionId || '-'} detail="une positivo y negativo" />
        <Metric title="session_id" value={logicalSessionId} detail="captura de la matriz" />
        <Metric title="execution_id" value={session.session_id} detail={session.state} />
      </div>
      {capturing && (
        <OperatorWizardBlock
          title="Paso 8 - Captura activa"
          doing="Windows BLE esta observando y el B200 esta capturando I/Q persistente."
          user="No toque el SensorTag, no desconecte el B200, no cierre la pagina y no abra otras aplicaciones SDR."
          expected="Capturar exactamente 10 s sin mostrar aun E4 ni elegibilidad provisional."
          failure="Si se cancela o falla la adquisicion, S001-POS queda NOT_ELIGIBLE y la negativa sigue bloqueada."
          actionLabel="Cancelar captura"
          onAction={onStop}
          disabled={busy === 'stop'}
        >
          <div className="grid gap-3 md:grid-cols-2">
            <Metric title="Capturando S001-POS" value={`${Math.min(session.duration_seconds, elapsed)}/${session.duration_seconds} s`} detail="0-10 s" />
            <Metric title="Windows BLE" value={statusText(session.steps?.native_scan)} detail="ground truth" />
            <Metric title="B200" value={statusText(session.steps?.b200_capture)} detail="I/Q" />
            <Metric title="muestras capturadas" value={formatNumber(session.live?.telemetry?.samples_received)} detail="CRC se calcula despues" />
          </div>
        </OperatorWizardBlock>
      )}
      {processing && (
        <OperatorWizardBlock
          title="Paso 9 - Procesamiento posterior"
          doing="La captura termino; ahora se verifican integridad, CRC, deduplicacion, asociacion y elegibilidad."
          user="Espere. Puede tardar mas que la captura. No inicie otra sesion."
          expected="Resumen cientifico completo antes de mostrar COMPLETED."
          failure="Si queda SUMMARY_PENDING, reanude procesamiento; no clasifique como negativa ni dataset."
          actionLabel=""
        >
          <ProcessingPhases session={session} />
        </OperatorWizardBlock>
      )}
      {!capturing && !processing && <Metric title="estado" value={statusText(session.state)} detail={session.error ?? 'sin error activo'} />}
      {processing && <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">La captura I/Q ya fue preservada. No se muestra detener captura durante procesamiento; espere a que termine CRC, correlacion y resumen.</p>}
    </div>
  );
}

function ProcessingPhases({ session }: { session: BleHybridSession }) {
  const phases = [
    ['1. Cerrando archivo I/Q', session.steps?.b200_capture],
    ['2. Verificando muestras y tamano', session.steps?.b200_capture],
    ['3. Calculando SHA-256', session.steps?.b200_capture],
    ['4. Completando manifiesto', session.steps?.b200_capture],
    ['5. Detectando bursts BLE', session.steps?.burst_detection],
    ['6. Decodificando paquetes', session.steps?.decoding],
    ['7. Verificando CRC', session.steps?.decoding],
    ['8. Eliminando duplicados', session.steps?.decoding],
    ['9. Asociando Windows BLE y B200', session.steps?.correlation],
    ['10. Evaluando evidencia y elegibilidad', session.steps?.results],
  ];
  return <div className="grid gap-2">{phases.map(([label, state]) => <GateCard key={label} label={label} state={state === 'completed' ? 'pass' : state === 'running' ? 'warn' : 'pending'} value={statusText(state)} />)}</div>;
}

function ProgressSteps({ current, completed, positives, negatives, total, diagnosticRequired = false }: { current: CampaignStep; completed: number; positives: number; negatives: number; total: number; diagnosticRequired?: boolean }) {
  const steps: [CampaignStep, string][] = [['device', 'Seleccionar dispositivo'], ['qualification', 'Cualificar B200'], ['prepare', 'Preparar'], ['replay', 'Replay offline'], ['positive', 'Captura positiva'], ['negative', 'Control negativo'], ['repeat', 'Revisar piloto'], ['dataset', 'Generar dataset']];
  const currentIndex = steps.findIndex(([step]) => step === current);
  return (
    <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>Progreso de campana</span>
        <div className="flex flex-wrap gap-2">
          <Badge>{completed}/{total} condiciones completas</Badge>
          <Badge>{current === 'qualification' ? 'cualificacion requerida' : 'cualificacion pasada'}</Badge>
          <Badge>{positives}/{total} positivas aceptadas</Badge>
          <Badge>{negatives}/{total} negativas aceptadas</Badge>
          <Badge>{positives + negatives}/{total * 2} capturas aceptadas</Badge>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-7">
        {steps.map(([step, label], index) => {
          const state = diagnosticRequired && step !== 'device' ? (step === 'qualification' ? 'fail' : 'pending') : index < currentIndex ? 'pass' : index === currentIndex ? 'warn' : 'pending';
          const value = diagnosticRequired
            ? step === 'device' ? 'completado' : step === 'qualification' ? 'fallida' : 'bloqueado'
            : index === currentIndex ? 'paso activo' : index < currentIndex ? 'hecho' : 'bloqueado';
          return <GateCard key={step} label={`${index + 1}. ${label}`} state={state} value={value} />;
        })}
      </div>
    </section>
  );
}

function CampaignTab({ profile, campaignId, datasetId, native, sdr, target, targetAgeMs, preflightValid, historicalCount, newCount, cleanCaptures, totalCaptures, b200Qualification, hybridQualification, qualificationProfileMatchesCampaign, qualificationTotal }: { profile: DeviceProfile; campaignId: string; datasetId: string; native: BleNativeStatus | null; sdr: { label?: string; serial_masked?: string | null } | null; target: BleNativeDevice | null; targetAgeMs: number; preflightValid: boolean; historicalCount: number; newCount: number; cleanCaptures: number; totalCaptures: number; b200Qualification: QualificationStatus; hybridQualification: QualificationStatus; qualificationProfileMatchesCampaign: boolean; qualificationTotal: number }) {
  return (
    <Panel title="Campana">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric title="unidad fisica" value={profile.physical_unit_id} detail={profile.display_name} />
        <Metric title="id observado" value={profile.logical_address || 'not_observed'} detail="direccion BLE no equivale a identidad fisica" />
        <Metric title="objetivo observado" value={target ? statusText(target.local_name || target.profile_label || target.address) : 'no observado'} detail={target?.last_seen_utc ? `${Math.round(targetAgeMs / 1000)} s de antiguedad` : 'sin ultima vez visto'} />
        <Metric title="preflight" value={preflightValid ? 'valido' : 'no valido'} detail={`scan ${native?.scan_session_id ?? '-'}`} />
        <Metric title="B200" value={sdr ? 'disponible' : 'no disponible'} detail={sdr?.label ?? '-'} />
        <Metric title="ACQUISITION_QUALIFICATION" value={`${b200Qualification.cleanConsecutive}/${QUALIFICATION_REQUIRED_CLEAN}`} detail={`${qualificationTotal} diagnosticos preservados`} />
        <Metric title="HYBRID_CONCURRENCY_QUALIFICATION" value={`${hybridQualification.cleanConsecutive}/${QUALIFICATION_REQUIRED_CLEAN}`} detail="Windows BLE concurrente, decoder off" />
        <Metric title="qualification_profile_matches_campaign" value={qualificationProfileMatchesCampaign ? 'true' : 'REQUALIFICATION_REQUIRED'} detail="duracion y configuracion critica" />
        <Metric title="campana" value={campaignId} detail={BASE_PROTOCOL_ID} />
        <Metric title="dataset" value={datasetId} detail="separado por unidad" />
        <Metric title="sesiones nuevas" value={newCount} detail="solo perfil activo" />
        <Metric title="sesiones historicas" value={historicalCount} detail="separadas de la campana nueva" />
        <Metric title="capturas historicas limpias" value={`${cleanCaptures}/${totalCaptures}`} detail="aptas por calidad basica" />
        <Metric title="Bluetooth Windows" value={native?.available ? 'disponible' : 'no disponible'} detail={native?.scanning ? 'escaneando' : 'en espera'} />
      </div>
    </Panel>
  );
}

function MatrixTab({ rows, completed }: { rows: ReturnType<typeof buildRows>; completed: number }) {
  return (
    <Panel title={`Matriz experimental (${completed}/${rows.length} condiciones)`}>
      <div className="max-h-[520px] overflow-auto">
        <table className="min-w-[1100px] text-left text-sm">
          <thead className="text-xs uppercase text-slate-400">
            <tr><th className="p-2">Orden</th><th className="p-2">Condicion</th><th className="p-2">Positiva</th><th className="p-2">Negativa</th><th className="p-2">Ciclo</th><th className="p-2">Distancia</th><th className="p-2">Orientacion</th><th className="p-2">Ubicacion</th><th className="p-2">Resultado +</th><th className="p-2">Resultado -</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.condition.condition_id} className="border-t border-slate-800">
                <td className="p-2">{row.condition.index}</td>
                <td className="p-2 font-mono">{row.condition.condition_id}</td>
                <td className="p-2 font-mono">{row.condition.positive_session_id}</td>
                <td className="p-2 font-mono">{row.condition.negative_session_id}</td>
                <td className="p-2 font-mono">{row.condition.power_cycle_id}</td>
                <td className="p-2">{row.condition.distance}</td>
                <td className="p-2">{row.condition.orientation} deg</td>
                <td className="p-2">{row.condition.location}</td>
                <td className="p-2">{row.positive.result}</td>
                <td className="p-2">{row.negative.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function buildRows() {
  return [] as {
    condition: MatrixCondition;
    pair: { positive?: BleHybridSession; negative?: BleHybridSession };
    positive: ReturnType<typeof positiveDecision>;
    negative: ReturnType<typeof negativeDecision>;
  }[];
}

function ResultsTab({ rows, historicalSessions, summaries }: { rows: ReturnType<typeof buildRows>; historicalSessions: BleHybridSession[]; summaries: Record<string, BleScientificSummary> }) {
  return (
    <Panel title="Resultados">
      <div className="space-y-4">
        {rows.filter((row) => row.pair.positive || row.pair.negative).map((row) => (
          <div key={row.condition.condition_id} className="rounded-md border border-slate-800 p-3">
            <div className="font-semibold">{row.condition.condition_id}</div>
            <div className="text-xs text-slate-500">{row.condition.positive_session_id} / {row.condition.negative_session_id}</div>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <Metric title="positivo" value={row.positive.result} detail={row.positive.reason} />
              <Metric title="negativo" value={row.negative.result} detail={row.negative.reason} />
            </div>
            {row.pair.positive && <PositiveGateSummary session={row.pair.positive} summary={summaries[row.pair.positive.session_id]} />}
          </div>
        ))}
        <div className="rounded-md border border-slate-800 p-3">
          <div className="font-semibold">Sesiones historicas separadas</div>
          <div className="mt-2 text-sm text-slate-400">{historicalSessions.length} sesiones no pertenecen al perfil activo o al protocolo base y no cuentan para la campana actual.</div>
          <div className="mt-2 max-h-40 overflow-auto text-xs text-slate-400">
            {historicalSessions.slice(0, 12).map((session) => <div key={session.session_id}>{session.session_id} Â· {statusText(session.state)} Â· claim {statusText(summaries[session.session_id]?.effective_claim_level ?? summaries[session.session_id]?.evidence_level)}</div>)}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function EvidenceTab({ captures, cleanCaptures }: { captures: BleCaptureRecord[]; cleanCaptures: number }) {
  return (
    <Panel title={`Evidencia B200 (${cleanCaptures}/${captures.length} limpias)`}>
      <div className="grid gap-3">
        {latestByTime(captures).slice(0, 12).map((capture) => (
          <div key={capture.capture_id} className="rounded-md border border-slate-800 p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="font-mono text-xs">{capture.capture_id}</span>
              <span className={isCleanCapture(capture) ? 'text-emerald-300' : 'text-amber-300'}>{isCleanCapture(capture) ? 'limpia' : 'no apta directa'}</span>
            </div>
            <div className="mt-2 text-slate-400">Motivo: {captureReason(capture)}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function PositiveGateSummary({ session, summary }: { session: BleHybridSession; summary?: BleScientificSummary }) {
  const gates = positiveGateSummary(session, summary);
  const lossFailure = Number(gates.overflows) > 0 || Number(gates.discontinuities) > 0 || Number(gates.short_read_count) > 0 || Number(gates.write_error_count) > 0 || Number(gates.writer_queue_overrun_count) > 0;
  const human = gates.dataset_eligibility_status === 'ELIGIBLE'
    ? { title: 'Captura positiva aceptada', text: 'La adquisicion termino sin perdidas y se observaron al menos tres paquetes unicos del objetivo con asociacion fuerte y sin conflictos.', state: 'ACCEPTED', action: 'Revisar resultado y preparar control negativo.' }
    : gates.summary_status === 'SUMMARY_PENDING'
      ? { title: 'Resumen pendiente', text: 'La captura termino, pero el analisis final todavia no esta completo.', state: 'SUMMARY_PENDING', action: 'Reanudar o esperar procesamiento; no clasificar todavia.' }
      : lossFailure
        ? { title: 'Perdida de adquisicion', text: 'El tamano del archivo puede ser correcto, pero la continuidad RF no esta garantizada.', state: 'NOT_ELIGIBLE', action: 'No usar para dataset; revisar USB 3, SDR concurrentes y writer.' }
        : gates.provenance_status !== 'VERIFIED'
          ? { title: 'Fallo de integridad o procedencia', text: 'No se pudo verificar completamente el archivo, manifiesto o resumen.', state: 'NOT_ELIGIBLE', action: 'Reintentar procesamiento o revisar almacenamiento antes de recapturar.' }
          : Number(gates.target_association_conflict_count) > 0 || Number(gates.unique_target_crc_packets_with_conflicting_association) > 0
            ? { title: 'Conflicto de identidad', text: 'Un paquete o intervalo quedo asociado con identidades incompatibles.', state: 'NOT_ELIGIBLE', action: 'Revisar relaciones de asociacion; no repetir automaticamente.' }
            : gates.association_evidence_status === 'AMBIGUOUS'
              ? { title: 'Asociacion ambigua', text: 'Se observaron paquetes compatibles, pero no pudieron atribuirse de forma inequivoca al objetivo.', state: 'NOT_ELIGIBLE', action: 'Alejar otros BLE controlados, repetir preflight y no cambiar thresholds.' }
              : Number(gates.unique_strong_only_target_crc_packets) > 0 && Number(gates.unique_strong_only_target_crc_packets) < MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE
                ? { title: 'Solo observacion minima', text: 'Se observo el objetivo, pero la evidencia no alcanza el minimo de tres paquetes target unicos strong-only.', state: 'NOT_ELIGIBLE', action: 'Revisar detalles o preparar una nueva positiva sin modificar K=3.' }
                : { title: 'Objetivo no observado', text: 'No se obtuvo evidencia suficiente del dispositivo seleccionado durante la captura.', state: 'NOT_ELIGIBLE', action: 'Revisar preparacion fisica, direccion BLE, CH37 y preflight.' };
  return (
    <div className="mt-3 rounded-md border border-slate-800 p-3">
      <div className="text-sm font-semibold">Paso 10 - Resultado completo</div>
      <div className={`mt-3 rounded-md border p-4 ${human.state === 'ACCEPTED' ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-amber-500/30 bg-amber-500/10'}`}>
        <div className="text-base font-semibold">{human.title}</div>
        <p className="mt-2 text-sm text-slate-200">{human.text}</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Metric title="S001-POS" value={human.state === 'ACCEPTED' ? 'ACCEPTED' : 'NOT_ACCEPTED'} detail="revision humana requerida" />
          <Metric title="ground_truth_status" value={statusText(gates.ground_truth_status)} detail="gate v2" />
          <Metric title="dataset_eligibility_status" value={statusText(gates.dataset_eligibility_status)} detail="sin autoavance" />
          <Metric title="Paquetes strong-only" value={formatNumber(gates.unique_strong_only_target_crc_packets)} detail={`umbral ${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE}`} />
          <Metric title="Conflictos" value={formatNumber(gates.target_association_conflict_count)} detail="debe ser 0" />
          <Metric title="Accion permitida" value={human.action} detail="operador" />
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3 xl:grid-cols-5">
        <Metric title="acquisition_quality_status" value={statusText(gates.acquisition_quality_status)} detail={`overflows ${gates.overflows} / disc ${gates.discontinuities}`} />
        <Metric title="maximum_observed_evidence_level" value={statusText(gates.maximum_observed_evidence_level)} detail="candidato observado" />
        <Metric title="e4_observation_status" value={statusText(gates.e4_observation_status)} detail="minimo tecnico" />
        <Metric title="e4_dataset_acceptance_status" value={statusText(gates.e4_dataset_acceptance_status)} detail="gate cientifico" />
        <Metric title="association_evidence_status" value={statusText(gates.association_evidence_status)} detail={(gates.ambiguity_reason_codes as string[]).join(',') || 'sin ambiguedad'} />
        <Metric title="effective_claim_level" value={statusText(gates.effective_claim_level)} detail="nivel aceptable para claim" />
        <Metric title="ground_truth_status" value={statusText(gates.ground_truth_status)} detail="E4 solo si se acepta" />
        <Metric title="provenance_status" value={statusText(gates.provenance_status)} detail="resumen cientifico" />
        <Metric title="dataset_eligibility" value={statusText(gates.dataset_eligibility_status)} detail="gate final" />
        <Metric title="target_result" value={statusText(gates.target_result)} detail={(gates.reason_codes as string[]).join(',') || 'sin motivos'} />
        <Metric title="total_crc_valid_packets" value={formatNumber(gates.total_crc_valid_packets)} detail="todos los paquetes RF" />
        <Metric title="target_crc_valid_packets" value={formatNumber(gates.target_crc_valid_packets)} detail="solo objetivo" />
        <Metric title="target_ambiguous_matches" value={formatNumber(gates.target_ambiguous_matches)} detail="asociaciones ambiguas" />
        <Metric title="environmental_crc_valid_packets" value={formatNumber(gates.environmental_crc_valid_packets)} detail="no justifica E4 del objetivo" />
        <Metric title="target_strong_matches" value={formatNumber(gates.target_strong_matches)} detail="umbral objetivo" />
        <Metric title="unique_target_crc_packets_with_strong_association" value={formatNumber(gates.unique_target_crc_packets_with_strong_association)} detail={`observacion minima >= ${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_E4_OBSERVATION}`} />
        <Metric title="unique_strong_only_target_crc_packets" value={formatNumber(gates.unique_strong_only_target_crc_packets)} detail={`aceptacion dataset >= ${MINIMUM_UNIQUE_TARGET_PACKETS_FOR_DATASET_ACCEPTANCE}`} />
        <Metric title="unique_target_crc_packets_with_ambiguous_association" value={formatNumber(gates.unique_target_crc_packets_with_ambiguous_association)} detail="no strong-only" />
        <Metric title="unique_target_crc_packets_with_conflicting_association" value={formatNumber(gates.unique_target_crc_packets_with_conflicting_association)} detail="excluye gate cientifico" />
        <Metric title="target_association_conflict_count" value={formatNumber(gates.target_association_conflict_count)} detail="debe ser 0" />
        <Metric title="environmental_strong_matches" value={formatNumber(gates.environmental_strong_matches)} detail="trafico ambiental" />
        <Metric title="unattributed_crc_valid_packets" value={formatNumber(gates.unattributed_crc_valid_packets)} detail="CRC sin atribucion" />
        <Metric title="metadatos completos" value={statusText(gates.metadata_complete)} detail={statusText(gates.protocol_conformance_status)} />
        <Metric title="duracion protocolo" value={`${gates.protocol_duration_seconds} s`} detail={`efectiva ${gates.effective_duration_seconds} s`} />
        <Metric title="revision protocolo" value={statusText(gates.protocol_revision)} detail={`override ${gates.protocol_override}`} />
        <Metric title="preflight al iniciar" value={statusText(gates.preflight_valid_at_capture_start)} detail={`${gates.preflight_age_at_capture_start_seconds} s`} />
        <Metric title="preflight actual" value="no retrospectivo" detail="puede caducar despues" />
        <Metric title="objetivo durante captura" value={statusText(gates.target_seen_during_capture)} detail="concurrente obligatorio para E4" />
      </div>
      <details className="mt-3 rounded-md border border-slate-800 p-3">
        <summary className="cursor-pointer text-sm font-semibold">Ver detalles tecnicos</summary>
        <div className="mt-3 grid gap-2 md:grid-cols-3 xl:grid-cols-5">
          <Metric title="capture_id" value={gates.capture_id} detail="I/Q" />
          <Metric title="execution_id" value={gates.execution_id} detail="sesion backend" />
          <Metric title="source_repository_commit" value={gates.source_repository_commit} detail={gates.source_working_tree_status} />
          <Metric title="source_working_tree_diff_sha256" value={gates.source_working_tree_diff_sha256} detail="solo si DIRTY_RECORDED" />
          <Metric title="protocol_manifest_sha256" value={gates.protocol_manifest_sha256} detail="contrato congelado" />
          <Metric title="qualification_profile_id" value={gates.qualification_profile_id} detail="perfil 10 s" />
          <Metric title="quality_gate_version" value={gates.quality_gate_version} detail="gate v2" />
          <Metric title="actual_samples" value={gates.actual_samples} detail="esperado 40000000" />
          <Metric title="actual_file_size_bytes" value={gates.actual_file_size_bytes} detail="esperado 320000000" />
          <Metric title="short_read_count" value={gates.short_read_count} detail="debe ser 0" />
          <Metric title="write_error_count" value={gates.write_error_count} detail="debe ser 0" />
          <Metric title="writer_queue_overrun_count" value={gates.writer_queue_overrun_count} detail="debe ser 0" />
          <Metric title="hash_status" value={gates.hash_status} detail="integridad" />
        </div>
      </details>
    </div>
  );
}

function AdvancedTab({ profile, caps, datasetManifest }: { profile: DeviceProfile; caps: BleCaptureCapabilities | null; datasetManifest: Record<string, unknown> | null }) {
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel title="Protocolo completo">
        <div className="grid gap-2 md:grid-cols-2">{protocolRows(profile).map(([key, value]) => <KeyValue key={key} name={key} value={value} />)}</div>
      </Panel>
      <Panel title="Configuracion SDR">
        <div className="grid gap-2">{(caps?.devices ?? []).map((device) => <KeyValue key={device.device_id} name={device.label} value={`${device.serial_masked ?? '-'} Â· ${device.available ? 'disponible' : 'no disponible'}`} />)}</div>
      </Panel>
      <Panel title="Modelos permitidos">
        <div className="space-y-2">{modelPlan.map(([stage, item]) => <KeyValue key={stage} name={stage} value={item} />)}</div>
      </Panel>
      <Panel title="Metricas y split">
        <div className="flex flex-wrap gap-2">{metricPlan.map((item) => <Badge key={item}>{item}</Badge>)}</div>
        <div className="mt-4 flex flex-wrap gap-2">{splitPlan.map((item) => <Badge key={item}>{item}</Badge>)}</div>
      </Panel>
      <Panel title="RFExperimentDatasetV1">
        <div className="grid gap-2">
          <KeyValue name="dataset" value={statusText(datasetManifest?.dataset_id ?? profileDatasetId(profile))} />
          <KeyValue name="training_readiness" value={statusText(datasetManifest?.training_readiness ?? 'pendiente')} />
          <KeyValue name="flujo" value="packet-aligned IQ -> QC -> split por sesion -> leakage check -> entrenamiento" />
        </div>
      </Panel>
    </div>
  );
}

function ConditionSummary({ condition, profile }: { condition: MatrixCondition; profile: DeviceProfile }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Metric title="Condicion" value={condition.condition_id} detail={`Dia ${condition.day_id}`} />
      <Metric title="Sesion positiva" value={condition.positive_session_id} detail="objetivo encendido" />
      <Metric title="Sesion negativa" value={condition.negative_session_id} detail="objetivo apagado" />
      <Metric title="Ciclo" value={condition.power_cycle_id} detail="generado por matriz" />
      <Metric title="Distancia" value={condition.distance} detail="con unidad fisica" />
      <Metric title="Orientacion" value={`${condition.orientation} deg`} detail="posicion objetivo" />
      <Metric title="Ubicacion" value={condition.location} detail="entorno declarado" />
      <Metric title="Unidad fisica" value={profile.physical_unit_id} detail={profile.logical_address || 'not_observed'} />
    </div>
  );
}

function Instruction({ title, text }: { title: string; text: string }) {
  return <div className="rounded-md border border-cyan-500/40 bg-cyan-500/10 p-4"><div className="text-lg font-semibold text-cyan-100">{title}</div><p className="mt-1 text-sm text-slate-300">{text}</p></div>;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-lg border border-slate-700 bg-slate-950"><div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold">{title}</div><div className="p-4">{children}</div></section>;
}

function Metric({ title, value, detail }: { title: string; value: React.ReactNode; detail: string }) {
  return <div className="rounded-md border border-slate-800 bg-slate-900 p-3"><div className="text-xs uppercase text-slate-400">{title}</div><div className="mt-1 break-all text-lg font-semibold">{value}</div><div className="text-xs text-slate-500">{detail}</div></div>;
}

function KeyValue({ name, value }: { name: string; value: React.ReactNode }) {
  return <div className="flex justify-between gap-3 rounded-md border border-slate-800 px-3 py-2 text-sm"><span className="text-slate-400">{name}</span><b className="break-all text-right">{value}</b></div>;
}

function GateCard({ label, state, value }: { label: string; state: GateState; value: string }) {
  const style = {
    pass: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200',
    warn: 'border-amber-500/50 bg-amber-500/10 text-amber-200',
    fail: 'border-rose-500/50 bg-rose-500/10 text-rose-200',
    pending: 'border-slate-700 bg-slate-950 text-slate-200',
  }[state];
  const Icon = state === 'pass' ? CheckCircle2 : state === 'fail' ? XCircle : AlertTriangle;
  return <div className={`rounded-lg border p-3 ${style}`}><div className="flex items-center justify-between gap-3"><div className="text-xs uppercase text-slate-400">{label}</div><Icon className="h-4 w-4" /></div><div className="mt-2 break-all font-semibold">{value}</div></div>;
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-200">{children}</span>;
}

function Empty({ text }: { text: string }) {
  return <div className="flex min-h-[180px] items-center justify-center rounded-md border border-dashed border-slate-700 text-sm text-slate-400">{text}</div>;
}
