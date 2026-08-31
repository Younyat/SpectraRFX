import { useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Play, RefreshCw, ShieldAlert, XCircle } from 'lucide-react';
import {
  BleApiService,
  BlePacketLabAnalysis,
  BlePacketLabCaptureListing,
  BlePacketLabJob,
  BlePacketLabPacket,
  BlePacketLabTransmitter,
  BleProvenance,
} from '../../../app/services/bleApi';
import { ensureOperation, updateOperation, finishOperation, failOperation } from '../../../app/operations/operationTelemetry';

const api = new BleApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

type ProvenanceFilter = 'ALL' | 'B200_ONLY' | 'WINDOWS_ONLY' | 'BOTH' | 'CORROBORATED_ONLY' | 'UNCORROBORATED';
type MainTab = 'packets' | 'transmitters' | 'sensors';
type DetailTab = 'resumen' | 'rf' | 'estructura' | 'contenido' | 'fabricante' | 'windows' | 'bytes' | 'trazabilidad';

function statusText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  return String(value).replaceAll('_', ' ');
}
function formatNumber(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString('es-ES') : '-';
}

function Panel({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-700 bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 text-sm font-semibold">
        <span>{title}</span>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}
function Metric({ title, value, detail }: { title: string; value: React.ReactNode; detail?: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
      <div className="text-xs uppercase text-slate-400">{title}</div>
      <div className="mt-1 break-all text-lg font-semibold">{value}</div>
      {detail && <div className="text-xs text-slate-500">{detail}</div>}
    </div>
  );
}

const PROVENANCE_LABEL: Record<BleProvenance, string> = {
  B200: 'B200', WINDOWS: 'WINDOWS', B200_AND_WINDOWS: 'B200 + WINDOWS', DERIVED: 'DERIVADO',
  DECLARED_BY_OPERATOR: 'OPERADOR', MANUFACTURER_DOCUMENTATION: 'DOC. FABRICANTE', NOT_AVAILABLE: 'NO DISPONIBLE',
};
const PROVENANCE_STYLE: Record<BleProvenance, string> = {
  B200: 'bg-cyan-500/15 text-cyan-200 border-cyan-500/40',
  WINDOWS: 'bg-indigo-500/15 text-indigo-200 border-indigo-500/40',
  B200_AND_WINDOWS: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/40',
  DERIVED: 'bg-amber-500/15 text-amber-200 border-amber-500/40',
  DECLARED_BY_OPERATOR: 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/40',
  MANUFACTURER_DOCUMENTATION: 'bg-slate-500/15 text-slate-300 border-slate-500/40',
  NOT_AVAILABLE: 'bg-slate-800 text-slate-500 border-slate-700',
};
function ProvenanceTag({ source }: { source: BleProvenance }) {
  return <span className={`ml-1 inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${PROVENANCE_STYLE[source]}`}>{PROVENANCE_LABEL[source]}</span>;
}
function Field({ value, source, mono }: { value: React.ReactNode; source: BleProvenance; mono?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={mono ? 'font-mono' : ''}>{value === null || value === undefined || value === '' ? '-' : String(value)}</span>
      <ProvenanceTag source={source} />
    </span>
  );
}

export default function BlePacketAnalysisLab() {
  const [listing, setListing] = useState<BlePacketLabCaptureListing | null>(null);
  const [selectedCaptureId, setSelectedCaptureId] = useState('');
  const [captureView, setCaptureView] = useState<'FULLY_ANALYZED' | 'ALL' | 'PARTIAL' | 'WITH_CRC' | 'WITH_MATCHES' | 'NOT_ELIGIBLE'>('FULLY_ANALYZED');
  const [job, setJob] = useState<BlePacketLabJob | null>(null);
  const [analysis, setAnalysis] = useState<BlePacketLabAnalysis | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [mainTab, setMainTab] = useState<MainTab>('transmitters');
  const [provenanceFilter, setProvenanceFilter] = useState<ProvenanceFilter>('ALL');
  const [pduTypeFilter, setPduTypeFilter] = useState('ALL');
  const [crcFilter, setCrcFilter] = useState<'ALL' | 'VALID' | 'INVALID'>('ALL');
  const [targetFilter, setTargetFilter] = useState<'ALL' | 'TARGET' | 'NON_TARGET'>('ALL');
  const [selectedPacket, setSelectedPacket] = useState<BlePacketLabPacket | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('resumen');

  const load = async () => {
    const listed = await api.packetLabCaptures();
    setListing(listed);
    return listed;
  };
  useEffect(() => { load().catch((e) => setError(String(e))); }, []);

  useEffect(() => {
    if (!listing || selectedCaptureId) return;
    const preferred = listing.classification.LAST_FULLY_ANALYZED_CAPTURE || listing.classification.LAST_COMPLETED_CAPTURE || listing.classification.LAST_CREATED_CAPTURE;
    if (preferred) setSelectedCaptureId(preferred);
  }, [listing, selectedCaptureId]);

  useEffect(() => {
    if (!selectedCaptureId) return;
    setAnalysis(null); setJob(null); setSelectedPacket(null);
    api.packetLabLatestAnalysis(selectedCaptureId).then(setAnalysis).catch(() => undefined);
  }, [selectedCaptureId]);

  const selectedCapture = listing?.captures.find((c) => c.capture_id === selectedCaptureId);

  const startAnalysis = async (captureId: string) => {
    setBusy('analyze'); setError(''); setMessage('');
    const operationId = `ble-pktlab:${captureId}`;
    ensureOperation({ operationId, kind: 'processing', title: 'ANALIZANDO CAPTURA BLE', phase: 'Cargando metadatos', progressPercent: 1, target: captureId, detail: 'Solo lectura sobre el replay ya cerrado. No se usara hardware.' });
    try {
      const started = await api.packetLabStartJob(captureId);
      setJob(started);
      setMessage('Analisis lanzado. No se utilizara el B200 ni se realizara un nuevo escaneo Windows: solo se leen los artefactos ya preservados.');
    } catch (reason) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      failOperation(operationId, text);
    } finally {
      setBusy('');
    }
  };

  useEffect(() => {
    if (!job || JOB_TERMINAL.has(job.state)) return;
    const operationId = `ble-pktlab:${job.capture_id}`;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.packetLabJob(job.job_id);
        setJob(next);
        const percent = Math.max(1, Math.min(99, Math.round((next.overall_progress ?? 0) * 100)));
        ensureOperation({ operationId, kind: 'processing', title: 'ANALIZANDO CAPTURA BLE', phase: statusText(next.phase), progressPercent: percent, target: next.capture_id, detail: next.message || '' });
        updateOperation(operationId, { phase: statusText(next.phase), progressPercent: percent, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          if (next.state === 'completed') {
            const result = await api.packetLabLatestAnalysis(next.capture_id);
            setAnalysis(result);
            finishOperation(operationId, `${result.summary.crc_valid_packets} paquetes, ${result.summary.logical_transmitters_found} transmisores`);
            setMessage('Analisis completo. Ningun artefacto original fue modificado.');
          } else if (next.state === 'failed') {
            failOperation(operationId, next.error || 'Fallo desconocido');
            setError(next.error || 'Fallo desconocido');
          } else {
            finishOperation(operationId, 'Cancelado de forma ordenada');
          }
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.state]);

  const cancelJob = async () => {
    if (!job) return;
    await api.packetLabCancelJob(job.job_id);
  };

  const capturesForView = useMemo(() => {
    if (!listing) return [];
    const cls = listing.classification;
    switch (captureView) {
      case 'FULLY_ANALYZED': return listing.captures.filter((c) => c.capture_id === cls.LAST_FULLY_ANALYZED_CAPTURE || c.replay?.scientific_completion_status === 'COMPLETE');
      case 'PARTIAL': return listing.captures.filter((c) => c.replay && c.replay.scientific_completion_status !== 'COMPLETE');
      case 'WITH_CRC': return listing.captures.filter((c) => (c.replay?.crc_valid_packets ?? 0) > 0);
      case 'WITH_MATCHES': return listing.captures.filter((c) => (c.replay?.strong_target_matches ?? 0) > 0);
      case 'NOT_ELIGIBLE': return listing.captures.filter((c) => c.replay?.dataset_eligibility_status === 'NOT_ELIGIBLE');
      default: return listing.captures;
    }
  }, [listing, captureView]);

  const pduTypes = useMemo(() => Array.from(new Set((analysis?.packets ?? []).map((p) => p.pdu_type.value).filter(Boolean))) as string[], [analysis]);

  const filteredPackets = useMemo(() => {
    if (!analysis) return [];
    return analysis.packets.filter((p) => {
      if (provenanceFilter === 'CORROBORATED_ONLY' && p.windows_match.value !== 'WINDOWS_MATCHED') return false;
      if (provenanceFilter === 'UNCORROBORATED' && p.windows_match.value === 'WINDOWS_MATCHED') return false;
      if (provenanceFilter === 'BOTH' && !p.windows_evidence.nearest_windows_callback_timestamp) return false;
      if (pduTypeFilter !== 'ALL' && p.pdu_type.value !== pduTypeFilter) return false;
      if (crcFilter === 'VALID' && !p.crc_valid.value) return false;
      if (crcFilter === 'INVALID' && p.crc_valid.value) return false;
      if (targetFilter === 'TARGET' && !p.is_target) return false;
      if (targetFilter === 'NON_TARGET' && p.is_target) return false;
      return true;
    });
  }, [analysis, provenanceFilter, pduTypeFilter, crcFilter, targetFilter]);

  const showWindowsOnlyTable = provenanceFilter === 'WINDOWS_ONLY';
  const jobRunning = Boolean(job && !JOB_TERMINAL.has(job.state));

  return (
    <div className="space-y-4 p-4 text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">BLE Capture &amp; Packet Analysis Lab</h1>
          <p className="text-sm text-slate-400">Laboratorio de analisis de paquetes BLE - capa adicional de solo lectura sobre el replay offline ya cerrado.</p>
        </div>
        <Link to="/ble-rffi-stage-one" className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800">
          <ArrowLeft className="h-4 w-4" />Volver al replay original
        </Link>
      </div>

      <div className="rounded-md border border-cyan-500/40 bg-cyan-500/10 p-3 text-sm text-cyan-100">
        NO SE UTILIZARA HARDWARE - NO SE REALIZARA UNA NUEVA CAPTURA - NO SE REALIZARA UN ESCANEO WINDOWS NUEVO. Este laboratorio solo lee artefactos ya preservados del replay offline (candidate_manifest.jsonl, packet_association_ledger.jsonl, decoded_packets.jsonl, semantic_packets.jsonl, advertisements.jsonl).
      </div>

      {error && <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
      {message && !error && <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">{message}</div>}

      {/* Zone A: capture selection + info */}
      <Panel title="A. Captura seleccionada">
        <div className="flex flex-wrap items-center gap-2">
          <select value={captureView} onChange={(e) => setCaptureView(e.target.value as typeof captureView)} className="h-9 rounded-md border border-slate-700 bg-slate-900 px-2 text-sm">
            <option value="FULLY_ANALYZED">Ultima captura completamente analizada</option>
            <option value="ALL">Todas las capturas</option>
            <option value="PARTIAL">Capturas con replay parcial</option>
            <option value="WITH_CRC">Capturas con paquetes CRC validos</option>
            <option value="WITH_MATCHES">Capturas con coincidencias del objetivo</option>
            <option value="NOT_ELIGIBLE">Capturas no elegibles</option>
          </select>
          <select value={selectedCaptureId} onChange={(e) => setSelectedCaptureId(e.target.value)} className="h-9 min-w-[22rem] rounded-md border border-slate-700 bg-slate-900 px-2 text-sm">
            <option value="">Seleccione una captura...</option>
            {capturesForView.map((c) => (
              <option key={c.capture_id} value={c.capture_id}>
                {c.capture_id} - {statusText(c.replay?.execution_status ?? 'SIN REPLAY')} - CRC {formatNumber(c.replay?.crc_valid_packets)}
              </option>
            ))}
          </select>
          <button onClick={() => load().catch((e) => setError(String(e)))} className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800">
            <RefreshCw className="h-4 w-4" />Actualizar
          </button>
          {selectedCaptureId === listing?.classification.LAST_FULLY_ANALYZED_CAPTURE && (
            <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-semibold text-emerald-200">ULTIMA CAPTURA ANALIZADA COMPLETAMENTE</span>
          )}
        </div>
        {selectedCapture && (
          <div className="mt-3 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Metric title="capture_id" value={selectedCapture.capture_id} />
            <Metric title="execution_id" value={selectedCapture.execution_id ?? '-'} />
            <Metric title="iq_sha256" value={(selectedCapture.iq_sha256 ?? '-').slice(0, 16) + '...'} />
            <Metric title="fecha" value={statusText(selectedCapture.created_at_utc)} />
            <Metric title="duracion" value={`${selectedCapture.duration_seconds ?? '-'} s`} detail={`CH${selectedCapture.ble_channel ?? '-'}`} />
            <Metric title="receptor" value={selectedCapture.receiver ?? '-'} detail={`${formatNumber(selectedCapture.sample_rate_sps)} S/s`} />
            <Metric title="calidad de adquisicion" value={selectedCapture.acquisition_quality} />
            <Metric title="cobertura del replay" value={`${formatNumber(selectedCapture.replay?.coverage?.processed_segments)} / ${formatNumber(selectedCapture.replay?.coverage?.total_candidate_segments)}`} detail={statusText(selectedCapture.replay?.execution_status)} />
            <Metric title="paquetes CRC validos" value={formatNumber(selectedCapture.replay?.crc_valid_packets)} detail={`${formatNumber(selectedCapture.replay?.unique_crc_valid_packets)} unicos`} />
            <Metric title="coincidencias fuertes" value={formatNumber(selectedCapture.replay?.strong_target_matches)} detail={`${formatNumber(selectedCapture.replay?.conflicting_matches)} ambiguas`} />
            <Metric title="decision cientifica" value={statusText(selectedCapture.replay?.decision)} />
            <Metric title="dataset_eligibility" value={statusText(selectedCapture.replay?.dataset_eligibility_status)} />
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => selectedCaptureId && startAnalysis(selectedCaptureId)}
            disabled={!selectedCaptureId || busy === 'analyze' || jobRunning}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-cyan-600 px-4 text-sm font-semibold text-white disabled:opacity-40"
          >
            <Play className="h-4 w-4" />{analysis ? 'RE-ANALIZAR CAPTURA' : 'ANALIZAR CAPTURA'}
          </button>
          {jobRunning && (
            <button onClick={cancelJob} className="inline-flex h-10 items-center gap-2 rounded-md border border-rose-500 px-3 text-sm font-semibold text-rose-100">
              <XCircle className="h-4 w-4" />Cancelar de forma ordenada
            </button>
          )}
        </div>
        {job && (
          <div className="mt-3 rounded-md border border-slate-800 p-3">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{statusText(job.phase)}</span>
              <span>{Math.round((job.overall_progress ?? 0) * 100)}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded bg-slate-800">
              <div className="h-full bg-cyan-400" style={{ width: `${Math.round((job.overall_progress ?? 0) * 100)}%` }} />
            </div>
            <div className="mt-1 text-xs text-slate-500">{job.message}</div>
          </div>
        )}
      </Panel>

      {analysis && (
        <>
          {/* Zone B: findings summary */}
          <Panel title="B. Resumen de hallazgos">
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Metric title="candidatos analizados" value={formatNumber(analysis.summary.candidates_analyzed)} />
              <Metric title="paquetes CRC validos" value={formatNumber(analysis.summary.crc_valid_packets)} />
              <Metric title="contenidos unicos" value={formatNumber(analysis.summary.unique_contents)} />
              <Metric title="transmisores logicos" value={formatNumber(analysis.summary.logical_transmitters_found)} />
              <Metric title="candidatos direccion objetivo" value={formatNumber(analysis.summary.target_address_candidates)} />
              <Metric title="asociaciones fuertes" value={formatNumber(analysis.summary.strong_associations)} />
              <Metric title="asociaciones ambiguas" value={formatNumber(analysis.summary.ambiguous_associations)} />
              <Metric title="decision cientifica (Fase 1)" value={statusText(analysis.summary.scientific_decision)} />
            </div>
            <p className="mt-3 text-xs text-slate-500">
              purpose=BLE_PACKET_ANALYSIS - diagnostic_only=true - scientific_campaign_member=false - dataset_eligible=false - training_eligible=false.
              Este laboratorio no desbloquea S001-NEG, dataset ni entrenamiento.
            </p>
          </Panel>

          <div className="flex gap-2 border-b border-slate-800">
            {(['transmitters', 'packets', 'sensors'] as MainTab[]).map((tab) => (
              <button key={tab} onClick={() => setMainTab(tab)} className={`px-3 py-2 text-sm font-semibold ${mainTab === tab ? 'border-b-2 border-cyan-400 text-cyan-300' : 'text-slate-400'}`}>
                {tab === 'transmitters' ? 'C. Transmisores' : tab === 'packets' ? 'D. Paquetes' : 'Sensores y datos'}
              </button>
            ))}
          </div>

          {mainTab === 'transmitters' && <TransmittersZone transmitters={analysis.transmitters} onSelectAddress={(address) => { setTargetFilter('ALL'); setMainTab('packets'); setPduTypeFilter('ALL'); setProvenanceFilter('ALL'); setSelectedPacket(analysis.packets.find((p) => p.advertiser_address_canonical.value === address) ?? null); }} />}

          {mainTab === 'packets' && (
            <PacketsZone
              packets={filteredPackets}
              windowsOnly={analysis.windows_only_observations}
              showWindowsOnlyTable={showWindowsOnlyTable}
              provenanceFilter={provenanceFilter} setProvenanceFilter={setProvenanceFilter}
              pduTypeFilter={pduTypeFilter} setPduTypeFilter={setPduTypeFilter} pduTypes={pduTypes}
              crcFilter={crcFilter} setCrcFilter={setCrcFilter}
              targetFilter={targetFilter} setTargetFilter={setTargetFilter}
              selectedPacket={selectedPacket} onSelectPacket={setSelectedPacket}
            />
          )}

          {mainTab === 'sensors' && <SensorsZone sensorViews={analysis.sensor_views} transmitters={analysis.transmitters} />}

          {selectedPacket && <PacketDetail packet={selectedPacket} detailTab={detailTab} setDetailTab={setDetailTab} onClose={() => setSelectedPacket(null)} />}
        </>
      )}

      <Panel title="E. Guia del operador">
        <div className="space-y-2 text-sm text-slate-300">
          <p><b>Que esta viendo:</b> el contenido de los paquetes BLE recuperados por el replay offline (Fase 1) de la captura seleccionada, comparados con las observaciones Windows preservadas de la misma sesion.</p>
          <p><b>Que significa:</b> cada campo muestra su procedencia (B200, WINDOWS, DERIVADO, etc.). Un dato lógicamente corroborado (dirección + nombre + ventana temporal) no demuestra todavía una huella física RFFI - eso es una etapa posterior y separada.</p>
          <p><b>Que debe pulsar:</b> seleccione una captura arriba, pulse ANALIZAR CAPTURA, y explore las pestañas Transmisores / Paquetes / Sensores.</p>
          <p><b>Que resultado esperar:</b> una ficha por transmisor encontrado, una tabla de paquetes con filtros de procedencia, y una vista detallada al pulsar cada paquete.</p>
          <p><b>Que hacer si falla:</b> si el replay de la captura no esta completo (pending_segments &gt; 0), este laboratorio seguira funcionando sobre el subconjunto procesado, pero la decision cientifica original permanece INCOMPLETE_REPLAY hasta cerrar la Fase 1 de esa captura.</p>
        </div>
      </Panel>
    </div>
  );
}

function TransmittersZone({ transmitters, onSelectAddress }: { transmitters: BlePacketLabTransmitter[]; onSelectAddress: (address: string) => void }) {
  return (
    <Panel title="C. Dispositivos y transmisores encontrados">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {transmitters.map((tx) => (
          <button key={tx.logical_transmitter_id} onClick={() => onSelectAddress(tx.addresses_observed[0])} className={`rounded-md border p-3 text-left ${tx.is_target ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-slate-800 bg-slate-900'}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="font-mono text-sm font-semibold">{tx.addresses_observed.join(', ')}</div>
              {tx.is_target && <ShieldAlert className="h-4 w-4 text-emerald-300" />}
            </div>
            <div className="mt-1 text-xs text-slate-400">{tx.local_names.join(', ') || 'sin nombre'}</div>
            <div className="mt-2 flex flex-wrap gap-1 text-[11px]">
              <span className="rounded border border-slate-700 px-1.5 py-0.5">{statusText(tx.classification)}</span>
              <span className="rounded border border-slate-700 px-1.5 py-0.5">{statusText(tx.knowledge_level)}</span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-400">
              <div>Paquetes<div className="text-sm font-semibold text-slate-100">{tx.packet_count}</div></div>
              <div>Unicos<div className="text-sm font-semibold text-slate-100">{tx.unique_packet_count}</div></div>
              <div>Windows<div className="text-sm font-semibold text-slate-100">{tx.windows_observations}</div></div>
            </div>
          </button>
        ))}
      </div>
    </Panel>
  );
}

function PacketsZone(props: {
  packets: BlePacketLabPacket[]; windowsOnly: BlePacketLabAnalysis['windows_only_observations']; showWindowsOnlyTable: boolean;
  provenanceFilter: ProvenanceFilter; setProvenanceFilter: (v: ProvenanceFilter) => void;
  pduTypeFilter: string; setPduTypeFilter: (v: string) => void; pduTypes: string[];
  crcFilter: 'ALL' | 'VALID' | 'INVALID'; setCrcFilter: (v: 'ALL' | 'VALID' | 'INVALID') => void;
  targetFilter: 'ALL' | 'TARGET' | 'NON_TARGET'; setTargetFilter: (v: 'ALL' | 'TARGET' | 'NON_TARGET') => void;
  selectedPacket: BlePacketLabPacket | null; onSelectPacket: (p: BlePacketLabPacket) => void;
}) {
  const { packets, windowsOnly, showWindowsOnlyTable, provenanceFilter, setProvenanceFilter, pduTypeFilter, setPduTypeFilter, pduTypes, crcFilter, setCrcFilter, targetFilter, setTargetFilter, selectedPacket, onSelectPacket } = props;
  return (
    <Panel title="D. Paquetes">
      <div className="mb-3 flex flex-wrap gap-2">
        <select value={provenanceFilter} onChange={(e) => setProvenanceFilter(e.target.value as ProvenanceFilter)} className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs">
          <option value="ALL">Procedencia: TODOS</option>
          <option value="B200_ONLY">SOLO B200</option>
          <option value="WINDOWS_ONLY">SOLO WINDOWS</option>
          <option value="BOTH">B200 Y WINDOWS</option>
          <option value="CORROBORATED_ONLY">SOLO CORROBORADOS</option>
          <option value="UNCORROBORATED">SIN CORROBORAR</option>
        </select>
        {!showWindowsOnlyTable && (
          <>
            <select value={pduTypeFilter} onChange={(e) => setPduTypeFilter(e.target.value)} className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs">
              <option value="ALL">PDU type: TODOS</option>
              {pduTypes.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={crcFilter} onChange={(e) => setCrcFilter(e.target.value as typeof crcFilter)} className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs">
              <option value="ALL">CRC: TODOS</option>
              <option value="VALID">CRC valido</option>
              <option value="INVALID">CRC no valido</option>
            </select>
            <select value={targetFilter} onChange={(e) => setTargetFilter(e.target.value as typeof targetFilter)} className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs">
              <option value="ALL">Objetivo: TODOS</option>
              <option value="TARGET">Solo objetivo</option>
              <option value="NON_TARGET">Sin objetivo</option>
            </select>
          </>
        )}
      </div>

      {showWindowsOnlyTable ? (
        <div className="max-h-[32rem] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-950 text-slate-400"><tr>
              <th className="p-2">Timestamp</th><th className="p-2">Address</th><th className="p-2">Type</th><th className="p-2">Local name</th><th className="p-2">RSSI</th>
            </tr></thead>
            <tbody>
              {windowsOnly.map((row) => (
                <tr key={row.native_observation_id} className="border-t border-slate-800">
                  <td className="p-2">{row.timestamp_callback_utc}</td>
                  <td className="p-2 font-mono">{row.bluetooth_address}</td>
                  <td className="p-2">{row.bluetooth_address_type}</td>
                  <td className="p-2">{row.local_name || '-'}</td>
                  <td className="p-2">{row.rssi_dbm ?? '-'} dBm</td>
                </tr>
              ))}
            </tbody>
          </table>
          {windowsOnly.length === 0 && <div className="p-4 text-center text-sm text-slate-500">Sin callbacks Windows en la ventana de esta captura.</div>}
        </div>
      ) : (
        <div className="max-h-[32rem] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-950 text-slate-400"><tr>
              <th className="p-2">Packet</th><th className="p-2">CRC</th><th className="p-2">PDU type</th><th className="p-2">Address</th><th className="p-2">Type</th>
              <th className="p-2">Local name</th><th className="p-2">Company</th><th className="p-2">Windows</th><th className="p-2">Delta</th><th className="p-2">Nivel</th>
            </tr></thead>
            <tbody>
              {packets.map((p) => (
                <tr key={p.packet_id} onClick={() => onSelectPacket(p)} className={`cursor-pointer border-t border-slate-800 hover:bg-slate-900 ${selectedPacket?.packet_id === p.packet_id ? 'bg-slate-800' : ''} ${p.is_target ? 'text-emerald-200' : ''}`}>
                  <td className="p-2 font-mono">{p.packet_id.slice(0, 12)}</td>
                  <td className="p-2">{p.crc_valid.value ? 'VALID' : 'INVALID'}</td>
                  <td className="p-2">{statusText(p.pdu_type.value)}</td>
                  <td className="p-2 font-mono">{statusText(p.advertiser_address_canonical.value)}</td>
                  <td className="p-2">{statusText(p.address_type.value)}</td>
                  <td className="p-2">{p.local_name?.value || 'sin nombre'}</td>
                  <td className="p-2">{p.company_name?.value ? statusText(p.company_name.value) : 'UNKNOWN'}</td>
                  <td className="p-2">{statusText(p.windows_match.value)}</td>
                  <td className="p-2">{p.windows_evidence.time_delta_ms ? `${p.windows_evidence.time_delta_ms.value.toFixed(0)} ms` : '-'}</td>
                  <td className="p-2">{statusText(p.knowledge_level)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {packets.length === 0 && <div className="p-4 text-center text-sm text-slate-500">Ningun paquete coincide con los filtros actuales.</div>}
        </div>
      )}
    </Panel>
  );
}

function SensorsZone({ sensorViews, transmitters }: { sensorViews: BlePacketLabAnalysis['sensor_views']; transmitters: BlePacketLabTransmitter[] }) {
  return (
    <Panel title="Sensores y datos">
      <div className="space-y-4">
        {sensorViews.map((view) => {
          const tx = transmitters.find((t) => t.logical_transmitter_id === view.transmitter_id);
          return (
            <div key={view.transmitter_id} className="rounded-md border border-slate-800 p-3">
              <div className="font-mono text-sm font-semibold">{view.transmitter_id}{tx?.is_target ? ' (objetivo)' : ''}</div>
              <div className="mt-1 text-xs text-slate-500">Perfil documental: {statusText(view.sensor_profile_source)}</div>
              <table className="mt-2 w-full text-left text-xs">
                <thead className="text-slate-400"><tr><th className="p-1">Sensor</th><th className="p-1">Documentado</th><th className="p-1">En advertising (B200)</th><th className="p-1">Via GATT</th><th className="p-1">Estado</th></tr></thead>
                <tbody>
                  {view.observations.map((obs, index) => (
                    <tr key={index} className="border-t border-slate-800">
                      <td className="p-1">{statusText(obs.measurement_name)}</td>
                      <td className="p-1"><Field value={obs.documented_by.value} source={obs.documented_by.source} /></td>
                      <td className="p-1"><Field value={obs.value_in_advertising.value as React.ReactNode} source={obs.value_in_advertising.source} /></td>
                      <td className="p-1"><Field value={obs.value_via_gatt.value as React.ReactNode} source={obs.value_via_gatt.source} /></td>
                      <td className="p-1">{statusText(obs.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">{view.observations[0]?.note}</p>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function PacketDetail({ packet, detailTab, setDetailTab, onClose }: { packet: BlePacketLabPacket; detailTab: DetailTab; setDetailTab: (t: DetailTab) => void; onClose: () => void }) {
  const tabs: { id: DetailTab; label: string }[] = [
    { id: 'resumen', label: 'Resumen' }, { id: 'rf', label: 'Senal RF' }, { id: 'estructura', label: 'Estructura BLE' },
    { id: 'contenido', label: 'Contenido' }, { id: 'fabricante', label: 'Fabricante y servicios' },
    { id: 'windows', label: 'Comparacion Windows' }, { id: 'bytes', label: 'Bytes originales' }, { id: 'trazabilidad', label: 'Trazabilidad' },
  ];
  return (
    <Panel title={`Paquete ${packet.packet_id}`} action={<button onClick={onClose} className="text-xs text-slate-400 hover:text-slate-200">cerrar</button>}>
      <div className="mb-3 flex flex-wrap gap-1 border-b border-slate-800 pb-2">
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => setDetailTab(tab.id)} className={`rounded px-2 py-1 text-xs font-semibold ${detailTab === tab.id ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}>{tab.label}</button>
        ))}
      </div>

      {detailTab === 'resumen' && (
        <div className="grid gap-3 md:grid-cols-3">
          <Metric title="packet_id" value={packet.packet_id} />
          <Metric title="candidate_id" value={packet.candidate_id} />
          <Metric title="crc_status" value={<Field value={packet.crc_valid.value ? 'VALID' : 'INVALID'} source={packet.crc_valid.source} />} />
          <Metric title="pdu_type" value={<Field value={packet.pdu_type.value} source={packet.pdu_type.source} />} />
          <Metric title="address" value={<Field value={packet.advertiser_address_canonical.value} source={packet.advertiser_address_canonical.source} mono />} />
          <Metric title="clasificacion logica" value={packet.is_target ? 'TARGET_LOGICALLY_CORROBORATED (candidato)' : 'UNKNOWN_BLE_TRANSMITTER'} />
          <Metric title="knowledge_level" value={statusText(packet.knowledge_level)} />
          <Metric title="caveat" value={statusText(packet.physical_unit_caveat)} />
        </div>
      )}

      {detailTab === 'rf' && packet.link_layer && (
        <div className="grid gap-3 md:grid-cols-3">
          <Metric title="start_sample" value={formatNumber(packet.packet_start_sample)} />
          <Metric title="power_dbfs" value={<Field value={packet.link_layer.rf.power_dbfs.value?.toFixed?.(2) ?? packet.link_layer.rf.power_dbfs.value} source={packet.link_layer.rf.power_dbfs.source} />} />
          <Metric title="snr_db" value={<Field value={packet.link_layer.rf.snr_db.value} source={packet.link_layer.rf.snr_db.source} />} />
          <Metric title="frequency_hz" value={<Field value={formatNumber(packet.link_layer.rf.frequency_hz.value)} source={packet.link_layer.rf.frequency_hz.source} />} />
          <Metric title="rf_timestamp_utc" value={statusText(packet.rf_timestamp_utc)} />
        </div>
      )}

      {detailTab === 'estructura' && packet.link_layer && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1 font-mono text-xs">
            <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-2">PREAMBLE</span>
            <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-2">ACCESS ADDRESS<br />{packet.link_layer.access_address_hex.value}</span>
            <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-2">HEADER<br />{packet.link_layer.pdu_header_hex.value}</span>
            <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-2">PAYLOAD<br />{(packet.link_layer.pdu_payload_hex.value ?? '').slice(0, 24)}...</span>
            <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-2">CRC<br />{packet.link_layer.crc_valid.value ? 'VALID' : 'INVALID'}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <Metric title="pdu_type_raw" value={<Field value={packet.link_layer.header.pdu_type_raw.value} source={packet.link_layer.header.pdu_type_raw.source} />} />
            <Metric title="tx_add" value={<Field value={packet.link_layer.header.tx_add.value} source={packet.link_layer.header.tx_add.source} />} />
            <Metric title="rx_add" value={<Field value={packet.link_layer.header.rx_add.value} source={packet.link_layer.header.rx_add.source} />} />
            <Metric title="payload_length" value={<Field value={packet.link_layer.header.payload_length.value} source={packet.link_layer.header.payload_length.source} />} />
            <Metric title="header_valid" value={<Field value={packet.link_layer.header.header_valid.value ? 'true' : 'false'} source={packet.link_layer.header.header_valid.source} />} />
            <Metric title="parser_status" value={statusText(packet.link_layer.parser_status)} />
          </div>
          <Metric title="byte_order_conversion" value={packet.byte_order_conversion} />
          <Metric title="advertiser_address_raw (on-air)" value={<Field value={packet.advertiser_address_raw.value} source={packet.advertiser_address_raw.source} mono />} />
        </div>
      )}

      {detailTab === 'contenido' && (
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-slate-400"><tr><th className="p-1">#</th><th className="p-1">AD type</th><th className="p-1">Length</th><th className="p-1">Raw</th><th className="p-1">Interpreted</th><th className="p-1">Status</th></tr></thead>
            <tbody>
              {packet.ad_structures.map((s) => (
                <tr key={s.structure_index} className="border-t border-slate-800 align-top">
                  <td className="p-1">{s.structure_index}</td>
                  <td className="p-1">{s.ad_type_hex} {s.ad_type_name}</td>
                  <td className="p-1">{s.length}</td>
                  <td className="p-1 font-mono">{s.raw_data_hex.value}</td>
                  <td className="p-1 max-w-xs break-all">{s.interpreted_value ? JSON.stringify(s.interpreted_value.value) : (s.manufacturer ? 'ver Fabricante' : '-')}</td>
                  <td className="p-1">{s.parser_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {packet.ad_structures.length === 0 && <div className="p-4 text-center text-sm text-slate-500">Sin estructuras de advertising disponibles para este paquete.</div>}
        </div>
      )}

      {detailTab === 'fabricante' && (
        <div className="space-y-3">
          {packet.company_id ? (
            <div className="grid gap-3 md:grid-cols-3">
              <Metric title="company_id_raw" value={`0x${packet.company_id.value?.toString(16).padStart(4, '0').toUpperCase()}`} />
              <Metric title="company_id" value={<Field value={packet.company_id.value} source={packet.company_id.source} />} />
              <Metric title="company_name" value={<Field value={packet.company_name?.value} source={packet.company_name?.source ?? 'NOT_AVAILABLE'} />} />
              <Metric title="manufacturer_parser_status" value={statusText(packet.manufacturer_parser_status)} />
            </div>
          ) : <div className="text-sm text-slate-500">Sin Manufacturer Specific Data en este paquete.</div>}
          <div>
            <div className="text-xs uppercase text-slate-400">Service UUIDs</div>
            <div className="mt-1 flex flex-wrap gap-1">{packet.service_uuids.length ? packet.service_uuids.map((u) => <span key={u} className="rounded border border-slate-700 px-2 py-0.5 font-mono text-xs">{u}</span>) : <span className="text-sm text-slate-500">Ninguno</span>}</div>
          </div>
        </div>
      )}

      {detailTab === 'windows' && (
        <table className="w-full text-left text-sm">
          <thead className="text-slate-400"><tr><th className="p-2">Campo</th><th className="p-2">B200</th><th className="p-2">Windows</th><th className="p-2">Comparacion</th></tr></thead>
          <tbody>
            <tr className="border-t border-slate-800"><td className="p-2">Direccion</td><td className="p-2 font-mono">{statusText(packet.advertiser_address_canonical.value)}</td><td className="p-2 font-mono">-</td><td className="p-2">{statusText(packet.windows_evidence.address_match_status)}</td></tr>
            <tr className="border-t border-slate-800"><td className="p-2">Timestamp</td><td className="p-2">{statusText(packet.rf_timestamp_utc)}</td><td className="p-2">{packet.windows_evidence.nearest_windows_callback_timestamp?.value ?? 'WINDOWS_EVIDENCE_UNAVAILABLE'}</td><td className="p-2">{packet.windows_evidence.time_delta_ms ? `${packet.windows_evidence.time_delta_ms.value.toFixed(1)} ms` : '-'}</td></tr>
            <tr className="border-t border-slate-800"><td className="p-2">Asociacion</td><td className="p-2" colSpan={2}>{statusText(packet.windows_evidence.association_strength)}</td><td className="p-2">{statusText(packet.windows_match.value)}</td></tr>
            <tr className="border-t border-slate-800"><td className="p-2">Razon si no asociado</td><td className="p-2" colSpan={3}>{statusText(packet.windows_evidence.association_rejection_reason)}</td></tr>
          </tbody>
        </table>
      )}

      {detailTab === 'bytes' && packet.link_layer && (
        <div className="space-y-2 font-mono text-xs">
          <div><span className="text-slate-500">access_address_hex: </span>{packet.link_layer.access_address_hex.value}</div>
          <div><span className="text-slate-500">pdu_header_hex: </span>{packet.link_layer.pdu_header_hex.value}</div>
          <div className="break-all"><span className="text-slate-500">pdu_payload_hex: </span>{packet.link_layer.pdu_payload_hex.value}</div>
          <div><span className="text-slate-500">crc_received: </span>{packet.link_layer.crc_received_hex.value} <span className="text-slate-500">crc_calculated: </span>{packet.link_layer.crc_calculated_hex.value}</div>
        </div>
      )}

      {detailTab === 'trazabilidad' && (
        <div className="grid gap-2 text-sm md:grid-cols-2">
          <KeyValue name="packet_id" value={packet.packet_id} />
          <KeyValue name="candidate_id" value={packet.candidate_id} />
        </div>
      )}
    </Panel>
  );
}

function KeyValue({ name, value }: { name: string; value: React.ReactNode }) {
  return <div className="flex justify-between gap-3 rounded-md border border-slate-800 px-3 py-2 text-sm"><span className="text-slate-400">{name}</span><b className="break-all text-right font-mono">{value}</b></div>;
}
