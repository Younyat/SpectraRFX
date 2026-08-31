import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiService } from '../../app/services/ApiService';
import { FingerprintingCaptureRecord, ModulatedSignalCapture } from '../../shared/types';
import { buildRfCaptureDiagnostic } from '../../shared/utils';

const api = new ApiService();

const reviewTemplate = {
  operator_decision: 'valid',
  review_notes: 'Accepted after manual review.',
  export_windows: ['transient_start', 'whole_burst'],
};

const formatTimestamp = (value?: string) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const formatHz = (value?: number | null) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'not available';
  const absolute = Math.abs(value);
  if (absolute >= 1e9) return `${(value / 1e9).toFixed(6)} GHz`;
  if (absolute >= 1e6) return `${(value / 1e6).toFixed(6)} MHz`;
  if (absolute >= 1e3) return `${(value / 1e3).toFixed(3)} kHz`;
  return `${value.toFixed(2)} Hz`;
};

export const DatasetBuilderView: React.FC = () => {
  const [captures, setCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [rsuCaptures, setRsuCaptures] = useState<Array<Record<string, any>>>([]);
  const [captureLabCaptures, setCaptureLabCaptures] = useState<ModulatedSignalCapture[]>([]);
  const [selectedCaptureId, setSelectedCaptureId] = useState<string>('');
  const [splitFilter, setSplitFilter] = useState<'all' | 'train' | 'val' | 'predict'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'valid' | 'doubtful' | 'rejected'>('all');
  const [lastRefresh, setLastRefresh] = useState<string>('');
  const [isRecomputingQc, setIsRecomputingQc] = useState(false);
  const [isApplyingBandProfile, setIsApplyingBandProfile] = useState(false);
  const [isDeletingCapture, setIsDeletingCapture] = useState(false);
  const [actionMessage, setActionMessage] = useState<string>('');

  const refresh = async () => {
    const [data, rsuRegistry, captureLabData] = await Promise.all([
      api.getFingerprintingCaptures(),
      api.getRFSignalCaptureRegistry().catch(() => ({ captures: [] })),
      api.getModulatedSignalCaptures().catch(() => []),
    ]);
    setCaptures(data);
    setRsuCaptures(rsuRegistry.captures ?? []);
    setCaptureLabCaptures(Array.isArray(captureLabData) ? captureLabData : (captureLabData as any)?.captures ?? []);
    setLastRefresh(new Date().toISOString());
    if (!selectedCaptureId && data.length > 0) {
      setSelectedCaptureId(data[0].capture_id);
    }
  };

  const importModulatedCapture = async (capture: ModulatedSignalCapture) => {
    setActionMessage('');
    const captureId = String(capture.id);
    const alreadyImported = captures.some(
      (item) => item.artifacts?.source_capture_id === captureId || item.capture_id === captureId,
    );
    if (alreadyImported) {
      setActionMessage(`Capture Lab dataset ${captureId} is already present in Dataset Builder.`);
      return;
    }
    try {
      await api.importModulatedCaptureToFingerprinting(captureId, {
        session_id: capture.session_id || `capture_lab_${captureId}`,
        dataset_split: capture.dataset_split || 'train',
        transmitter_label: String(capture.label ?? capture.transmitter_id ?? `capture_lab_${captureId}`),
        transmitter_class: String(capture.transmitter_class ?? capture.modulation_hint ?? 'unknown'),
        transmitter_id: String(capture.transmitter_id ?? capture.label ?? `capture_lab_${captureId}`),
        operator: String(capture.operator ?? 'capture_lab'),
        environment: String(capture.environment ?? 'unknown'),
        notes: String(capture.notes ?? 'Imported from Capture Lab for Dataset Builder QC review.'),
        ground_truth_confidence: 'weak_from_capture_lab',
        family: String(capture.transmitter_class ?? capture.modulation_hint ?? 'unknown'),
        signal_family: String(capture.transmitter_class ?? capture.modulation_hint ?? 'unknown'),
        signal_type: String(capture.transmitter_class ?? capture.modulation_hint ?? 'unknown'),
        modulation_class: capture.modulation_hint,
        band_label: String(capture.label ?? ''),
        profile_key: null,
        label_status: 'weak_label',
      });
      setActionMessage(`Imported Capture Lab dataset ${captureId}. Review it before using it for training.`);
      await refresh();
      setSelectedCaptureId(captureId);
    } catch (error) {
      console.error('Failed to import Capture Lab dataset', error);
      setActionMessage(`Failed to import Capture Lab dataset ${captureId}.`);
    }
  };

  const importRsuCapture = async (capture: Record<string, any>) => {
    setActionMessage('');
    const captureId = String(capture.capture_id ?? '');
    const alreadyImported = captures.some((item) => item.artifacts?.source_capture_id === captureId || item.capture_id === captureId);
    if (alreadyImported) {
      setActionMessage(`RF Signal Understanding capture ${captureId} is already present in Dataset Builder.`);
      return;
    }
    try {
      const filePath = String(capture.file_path ?? '');
      await api.createFingerprintingCapture({
        capture_id: captureId,
        capture_mode: 'rf_signal_understanding_import',
        session_id: capture.session_id || 'rsu_session_unassigned',
        dataset_split: 'train',
        capture_config: {
          device_source: 'rf_signal_understanding',
          sdr_model: 'unknown',
          sdr_serial: 'unknown',
          gain_stage: 'manual',
          antenna_port: 'unknown',
          capture_type: 'iq_file',
          center_frequency_hz: Number(capture.center_frequency_hz ?? 0),
          sample_rate_hz: Number(capture.sample_rate_hz ?? 0),
          effective_bandwidth_hz: Number(capture.sample_rate_hz ?? 0),
          gain_settings: { composite_gain_db: Number(capture.gain_db ?? 0) },
          capture_duration_s: Number(capture.duration_s ?? 0),
          file_format: String(capture.file_format ?? 'iq'),
          sample_dtype: 'complex64',
          output_path: filePath,
          dataset_destination: 'fingerprinting/train',
        },
        transmitter: {
          transmitter_label: String((capture.labels ?? [])[0] ?? capture.profile?.signal_type ?? 'rsu_unlabeled'),
          transmitter_class: String(capture.profile?.family ?? capture.profile?.signal_type ?? 'unknown'),
          transmitter_id: String((capture.labels ?? [])[0] ?? `rsu_${captureId}`),
          family: String(capture.profile?.family ?? 'unknown'),
          ground_truth_confidence: 'weak_from_rsu',
        },
        scenario: {
          operator: 'RF Signal Understanding',
          environment: String(capture.profile?.environment ?? 'unspecified'),
          notes: 'Imported from RF Signal Understanding capture registry for Dataset Builder QC review.',
          timestamp_utc: capture.created_at,
        },
        quality_metrics: {
          estimated_snr_db: 0,
          frequency_offset_hz: 0,
          clipping_pct: 0,
          silence_pct: 0,
        },
        burst_detection: {
          method: 'rf_signal_understanding_region_capture',
          burst_count: Number(capture.region_count ?? 1),
          regions_of_interest: ['rf_signal_understanding'],
        },
        artifacts: {
          iq_file: filePath,
          metadata_file: '',
          source_capture_id: captureId,
        },
        operator_decision: 'doubtful',
        review_notes: 'Needs Dataset Builder review before training use.',
      });
      setActionMessage(`Imported RF Signal Understanding capture ${captureId}. Review it before using it for training.`);
      await refresh();
      setSelectedCaptureId(captureId);
    } catch (error) {
      console.error('Failed to import RF Signal Understanding capture', error);
      setActionMessage(`Failed to import RF Signal Understanding capture ${captureId}.`);
    }
  };

  const registerSelectedForRFSignalUnderstanding = async () => {
    if (!selectedCapture) return;
    setActionMessage('');
    if (selectedCapture.quality_review.status !== 'valid') {
      setActionMessage('Only valid captures should be registered into RF Signal Understanding. Mark this capture valid after QC first.');
      return;
    }
    const iqPath = selectedCapture.artifacts.iq_file || selectedCapture.capture_config.output_path;
    if (!iqPath) {
      setActionMessage('This capture has no linked IQ file, so it cannot be registered into RF Signal Understanding.');
      return;
    }
    try {
      await api.registerRFSignalUnderstandingCapture({
        capture_id: selectedCapture.capture_id,
        file_path: iqPath,
        file_format: selectedCapture.capture_config.file_format === 'iq' ? 'iq' : 'cfile',
        sample_rate_hz: selectedCapture.capture_config.sample_rate_hz,
        center_frequency_hz: selectedCapture.capture_config.center_frequency_hz,
        gain_db: Number(selectedCapture.capture_config.gain_settings?.['composite_gain_db'] ?? 0),
        duration_s: selectedCapture.capture_config.capture_duration_s,
        source: 'dataset_builder_validated',
        session_id: selectedCapture.session_id,
        profile_key: selectedCapture.transmitter.family || selectedCapture.transmitter.transmitter_class,
        profile: {
          signal_type: selectedCapture.transmitter.transmitter_class,
          family: selectedCapture.transmitter.family,
          environment: selectedCapture.scenario.environment,
          dataset_split: selectedCapture.dataset_split,
          quality_review_status: selectedCapture.quality_review.status,
          transmitter_id: selectedCapture.transmitter.transmitter_id,
        },
      });
      setActionMessage(`Registered ${selectedCapture.capture_id} in RF Signal Understanding. Open that tab and refresh Captured RF files.`);
    } catch (error) {
      console.error('Failed to register capture in RF Signal Understanding', error);
      setActionMessage('Failed to register this capture in RF Signal Understanding.');
    }
  };

  useEffect(() => {
    refresh().catch((error) => console.error('Failed to load dataset builder data', error));
  }, []);

  const filteredCaptures = useMemo(() => {
    return captures.filter((capture) => {
      const splitOk = splitFilter === 'all' || capture.dataset_split === splitFilter;
      const statusOk = statusFilter === 'all' || capture.quality_review.status === statusFilter;
      return splitOk && statusOk;
    });
  }, [captures, splitFilter, statusFilter]);

  const selectedCapture =
    filteredCaptures.find((item) => item.capture_id === selectedCaptureId) ??
    captures.find((item) => item.capture_id === selectedCaptureId) ??
    filteredCaptures[0] ??
    captures[0];

  const selectedDiagnostic = selectedCapture
    ? buildRfCaptureDiagnostic({
        source: 'offline',
        centerFrequencyHz: selectedCapture.capture_config.center_frequency_hz,
        bandwidthHz: selectedCapture.capture_config.effective_bandwidth_hz,
        peakFrequencyHz: selectedCapture.quality_metrics.peak_frequency_hz,
        frequencyOffsetHz: selectedCapture.quality_metrics.frequency_offset_hz,
        occupiedBandwidthHz: selectedCapture.quality_metrics.occupied_bandwidth_hz,
        snrDb: selectedCapture.quality_metrics.estimated_snr_db,
        clippingPct: selectedCapture.quality_metrics.clipping_pct,
        silencePct: selectedCapture.quality_metrics.silence_pct,
        canonicalizationEnabled: true,
        qualityFlags: selectedCapture.quality_review.quality_flags,
        liveOffsetHz: selectedCapture.quality_metrics.live_offset_hz,
      })
    : null;
  const selectedLabelIsWeakOrMissing = selectedCapture
    ? ['unknown', 'tx_unknown', 'unlabeled_transmitter', 'rsu_unlabeled', 'profile_pending', 'band_profile_pending', ''].includes(
        String(selectedCapture.transmitter.transmitter_id || selectedCapture.transmitter.transmitter_label || '').trim().toLowerCase(),
      ) || selectedCapture.quality_review.label_status !== 'strong_label'
    : false;

  const reviewCapture = async (status: 'valid' | 'doubtful' | 'rejected') => {
    if (!selectedCapture) {
      return;
    }
    await api.reviewFingerprintingCapture(selectedCapture.capture_id, {
      ...reviewTemplate,
      operator_decision: status,
      review_notes:
        status === 'valid'
          ? 'Accepted for dataset export.'
          : status === 'doubtful'
            ? 'Borderline quality; retain for manual comparison only.'
            : 'Rejected due to quality or labeling issues.',
    });
    await refresh();
  };

  const recomputeQc = async () => {
    if (!selectedCapture) return;
    setIsRecomputingQc(true);
    setActionMessage('');
    try {
      const updated = await api.recomputeFingerprintingCaptureQc(selectedCapture.capture_id);
      setActionMessage(
        `QC recomputed for ${updated.capture_id}. Automatic status: ${updated.quality_review.status}. ` +
          `Capture quality: ${updated.quality_review.capture_quality ?? 'unknown'}. ` +
          `Training readiness: ${updated.quality_review.training_readiness ?? 'unknown'}.`,
      );
      await refresh();
      setSelectedCaptureId(updated.capture_id);
    } catch (error) {
      console.error('Failed to recompute capture QC', error);
      setActionMessage('Failed to recompute QC for this capture.');
    } finally {
      setIsRecomputingQc(false);
    }
  };

  const applyBandProfile = async (confirmAsStrongLabel = false) => {
    if (!selectedCapture) return;
    setIsApplyingBandProfile(true);
    setActionMessage('');
    try {
      const updated = await api.applyBandProfileToFingerprintingCapture(selectedCapture.capture_id, {
        confirm_as_strong_label: confirmAsStrongLabel,
        overwrite_existing: false,
      });
      const profile = updated.quality_review?.band_profile_resolution?.profile_key ?? updated.transmitter.profile_key ?? 'band_profiles.json';
      setActionMessage(
        confirmAsStrongLabel
          ? `Applied ${profile} and marked the label as strong. Run Recompute QC before scientific export.`
          : `Applied weak label defaults from ${profile}. Review and confirm before scientific training.`,
      );
      await refresh();
      setSelectedCaptureId(updated.capture_id);
    } catch (error) {
      console.error('Failed to apply band profile label', error);
      setActionMessage('Failed to apply band-profile defaults. Check center frequency and bandwidth metadata.');
    } finally {
      setIsApplyingBandProfile(false);
    }
  };

  const deleteCapture = async () => {
    if (!selectedCapture) return;
    const confirmed = window.confirm(
      `Delete capture ${selectedCapture.capture_id} (${selectedCapture.transmitter.transmitter_label}) from Dataset Builder?`,
    );
    if (!confirmed) return;
    setIsDeletingCapture(true);
    setActionMessage('');
    try {
      const result = await api.deleteFingerprintingCapture(selectedCapture.capture_id, { delete_artifacts: true });
      setActionMessage(
        result.deleted_artifacts.length > 0
          ? `Capture ${result.capture_id} deleted. Removed ${result.deleted_artifacts.length} linked artifact(s).`
          : `Capture ${result.capture_id} deleted from the fingerprinting registry.`,
      );
      const deletedId = selectedCapture.capture_id;
      await refresh();
      setSelectedCaptureId((current) => (current === deletedId ? '' : current));
    } catch (error) {
      console.error('Failed to delete capture', error);
      setActionMessage('Failed to delete this capture from Dataset Builder.');
    } finally {
      setIsDeletingCapture(false);
    }
  };

  return (
    <div className="min-h-full bg-[linear-gradient(180deg,_#fffef8,_#f5f7fb)] p-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-amber-700">Dataset Builder</div>
          <h1 className="mt-2 font-serif text-4xl text-slate-900">Curación manual y calidad antes de entrenar</h1>
          <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-600">
            Esta pestaña no captura señal. Esta pestaña decide qué capturas pasan a ser dataset serio. Aquí revisas calidad,
            separas `train`, `val` y `predict`, y aceptas o rechazas cada adquisición antes de contaminar el pipeline.
          </p>
          <p className="mt-2 max-w-4xl text-sm leading-7 text-slate-500">
            Último refresco UI: {formatTimestamp(lastRefresh)}. Fuente: registro fingerprinting del backend.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
            <div className="text-2xl font-semibold text-slate-900">{captures.length}</div>
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Total</div>
          </div>
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <div className="text-2xl font-semibold text-emerald-700">
              {captures.filter((capture) => capture.quality_review.status === 'valid').length}
            </div>
            <div className="text-xs uppercase tracking-[0.18em] text-emerald-700">Valid</div>
          </div>
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3">
            <div className="text-2xl font-semibold text-rose-700">
              {captures.filter((capture) => capture.quality_review.status === 'rejected').length}
            </div>
            <div className="text-xs uppercase tracking-[0.18em] text-rose-700">Rejected</div>
          </div>
        </div>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">What It Does</div>
          <div className="mt-3 text-sm leading-6 text-slate-700">
            Revisa trazabilidad, calidad, burst extraction y destino experimental antes de exportar un registro al dataset usable.
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Accept</div>
          <div className="mt-3 text-sm leading-6 text-slate-700">
            Marca la captura como válida para el split ya definido. No cambia `train`, `val` o `predict`; valida su calidad.
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Reject / Doubtful</div>
          <div className="mt-3 text-sm leading-6 text-slate-700">
            Evita que una muestra mal etiquetada, duplicada o degradada entre en entrenamiento, validación o predicción.
          </div>
        </div>
      </div>

      <section className="mb-5 rounded-[1.75rem] border border-cyan-200 bg-cyan-50/80 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.06)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-800">RF Signal Understanding candidates</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">Capturas pendientes de curacion para fingerprinting</h2>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700">
              Las capturas creadas desde RF Signal Understanding viven primero en su propio registro. Importalas aqui para someterlas al mismo QC,
              decision de validez, split y trazabilidad que el resto del Dataset Builder.
            </p>
          </div>
          <button className="rounded-full border border-cyan-300 bg-white px-4 py-2 text-sm font-semibold text-cyan-800" onClick={() => refresh()}>
            Refresh candidates
          </button>
        </div>
        <div className="mt-4 grid gap-3 xl:grid-cols-3">
          {rsuCaptures.slice(0, 6).map((capture) => {
            const captureId = String(capture.capture_id ?? '');
            const imported = captures.some((item) => item.artifacts?.source_capture_id === captureId || item.capture_id === captureId);
            return (
              <article key={captureId} className="rounded-2xl border border-cyan-100 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold text-slate-900">{captureId}</div>
                    <div className="mt-1 text-xs text-slate-500">{capture.source ?? 'rf_signal_understanding'} | {capture.analysis_status ?? 'pending'}</div>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${imported ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
                    {imported ? 'imported' : 'candidate'}
                  </span>
                </div>
                <div className="mt-3 space-y-1 text-xs text-slate-600">
                  <div>Sample rate: {formatHz(Number(capture.sample_rate_hz ?? 0))}</div>
                  <div>Center: {formatHz(Number(capture.center_frequency_hz ?? 0))}</div>
                  <div>Regions: {String(capture.region_count ?? 'not analyzed')}</div>
                  <div className="truncate">Path: {String(capture.file_path ?? 'not linked')}</div>
                </div>
                <button
                  className="mt-3 w-full rounded-full border border-cyan-300 px-3 py-2 text-sm font-semibold text-cyan-800 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => importRsuCapture(capture)}
                  disabled={imported}
                >
                  {imported ? 'Already in Dataset Builder' : 'Import for QC review'}
                </button>
              </article>
            );
          })}
          {rsuCaptures.length === 0 && (
            <div className="rounded-2xl border border-dashed border-cyan-200 bg-white p-4 text-sm text-slate-500">
              No RF Signal Understanding captures are registered yet.
            </div>
          )}
        </div>
      </section>

      <section className="mb-5 rounded-[1.75rem] border border-amber-200 bg-amber-50/80 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.06)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-800">Capture Lab candidates</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">Capturas de Capture Lab disponibles para Dataset Builder</h2>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700">
              Estas capturas ya existen en el registro de Capture Lab. Puedes importarlas al Dataset Builder para someterlas a QC,
              decidir su split y validar etiquetas antes de usarlas en entrenamiento.
            </p>
          </div>
          <button className="rounded-full border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-800" onClick={() => refresh()}>
            Refresh candidates
          </button>
        </div>
        <div className="mt-4 grid gap-3 xl:grid-cols-3">
          {captureLabCaptures.map((capture) => {
            const captureId = String(capture.id);
            const imported = captures.some((item) => item.artifacts?.source_capture_id === captureId || item.capture_id === captureId);
            return (
              <article key={captureId} className="rounded-2xl border border-amber-100 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold text-slate-900">{captureId}</div>
                    <div className="mt-1 text-xs text-slate-500">{capture.capture_type ?? 'capture_lab'} | {capture.file_format ?? 'iq'}</div>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${imported ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
                    {imported ? 'imported' : 'candidate'}
                  </span>
                </div>
                <div className="mt-3 space-y-1 text-xs text-slate-600">
                  <div>Split: {capture.dataset_split ?? 'unknown'}</div>
                  <div>Session: {capture.session_id ?? 'none'}</div>
                  <div>Source: {capture.source_device ?? capture.driver ?? 'unknown'}</div>
                  <div>Trigger: {String(capture.trigger_capture?.trigger_detected ?? 'unknown')}</div>
                  <div className="truncate">IQ: {String(capture.iq_file ?? capture.metadata_file ?? 'not linked')}</div>
                </div>
                <button
                  className="mt-3 w-full rounded-full border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-800 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => importModulatedCapture(capture)}
                  disabled={imported}
                >
                  {imported ? 'Already in Dataset Builder' : 'Import for QC review'}
                </button>
              </article>
            );
          })}
          {captureLabCaptures.length === 0 && (
            <div className="rounded-2xl border border-dashed border-amber-200 bg-white p-4 text-sm text-slate-500">
              No Capture Lab datasets were found in the modulated capture registry.
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-[1.75rem] border border-slate-200 bg-white/90 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Capture inventory</div>
            <button className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700" onClick={() => refresh()}>
              Refresh
            </button>
          </div>

          <div className="mb-4 grid gap-3 md:grid-cols-2">
            <label>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Split filter</div>
              <select
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
                value={splitFilter}
                onChange={(event) => setSplitFilter(event.target.value as typeof splitFilter)}
              >
                <option value="all">all</option>
                <option value="train">train</option>
                <option value="val">val</option>
                <option value="predict">predict</option>
              </select>
            </label>
            <label>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Status filter</div>
              <select
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
              >
                <option value="all">all</option>
                <option value="valid">valid</option>
                <option value="doubtful">doubtful</option>
                <option value="rejected">rejected</option>
              </select>
            </label>
          </div>

          <div className="mb-4 text-xs text-slate-500">
            Showing {filteredCaptures.length} of {captures.length} captures.
          </div>

          <div className="space-y-3">
            {filteredCaptures.map((capture) => (
              <button
                key={capture.capture_id}
                onClick={() => setSelectedCaptureId(capture.capture_id)}
                className={`w-full rounded-2xl border p-4 text-left transition ${
                  capture.capture_id === selectedCapture?.capture_id
                    ? 'border-slate-900 bg-slate-950 text-white'
                    : 'border-slate-200 bg-slate-50 text-slate-900 hover:bg-slate-100'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold">{capture.transmitter.transmitter_id}</div>
                    <div className="mt-1 text-xs opacity-75">
                      {capture.session_id} · {capture.capture_config.file_format} · {capture.dataset_split}
                    </div>
                    <div className="mt-1 text-xs opacity-75">
                      Captured: {formatTimestamp(capture.created_at_utc)}
                    </div>
                  </div>
                  <div className="text-xs uppercase tracking-[0.18em]">{capture.quality_review.status}</div>
                </div>
              </button>
            ))}
            {filteredCaptures.length === 0 && (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                No captures match the current filters.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-[1.75rem] border border-slate-200 bg-white/90 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          {selectedCapture ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Capture summary</div>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-900">{selectedCapture.transmitter.transmitter_label}</h2>
                  <div className="mt-2 text-sm text-slate-600">
                    {selectedCapture.transmitter.transmitter_class} · {selectedCapture.scenario.environment} · session {selectedCapture.scenario.session_number}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => recomputeQc()}
                    disabled={isRecomputingQc}
                  >
                    {isRecomputingQc ? 'Recomputing QC...' : 'Recompute QC'}
                  </button>
                  <button
                    className="rounded-full border border-teal-300 bg-teal-50 px-4 py-2 text-sm font-semibold text-teal-800 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => applyBandProfile(false)}
                    disabled={isApplyingBandProfile}
                    title="Fill missing or weak label/class fields from backend/app/modules/rf_intelligence/band_profiles.json"
                  >
                    {isApplyingBandProfile ? 'Applying profile...' : 'Fill label from band profile'}
                  </button>
                  <button className="rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => reviewCapture('valid')}>
                    Accept
                  </button>
                  <button className="rounded-full bg-amber-500 px-4 py-2 text-sm font-semibold text-white" onClick={() => reviewCapture('doubtful')}>
                    Doubtful
                  </button>
                  <button className="rounded-full bg-rose-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => reviewCapture('rejected')}>
                    Reject
                  </button>
                  <button
                    className="rounded-full border border-rose-300 bg-white px-4 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => deleteCapture()}
                    disabled={isDeletingCapture}
                  >
                    {isDeletingCapture ? 'Deleting...' : 'Delete'}
                  </button>
                </div>
              </div>

              {actionMessage && (
                <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  {actionMessage}
                </div>
              )}

              <div className={`mt-4 rounded-2xl border p-4 ${selectedLabelIsWeakOrMissing ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50'}`}>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className={`text-xs font-semibold uppercase tracking-[0.18em] ${selectedLabelIsWeakOrMissing ? 'text-amber-800' : 'text-emerald-800'}`}>
                      Label and class audit
                    </div>
                    <h3 className="mt-2 text-lg font-semibold text-slate-900">
                      {selectedLabelIsWeakOrMissing ? 'Needs label confirmation before scientific training' : 'Strong label available'}
                    </h3>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-700">
                      Dataset Builder can fill missing class metadata from <span className="font-mono">band_profiles.json</span> using
                      center frequency and occupied bandwidth. This produces a weak technical label; use strong confirmation only when
                      the operator has verified the class/transmitter identity.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      className="rounded-full border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-900 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => applyBandProfile(false)}
                      disabled={isApplyingBandProfile}
                    >
                      Fill missing fields
                    </button>
                  <button
                    className="rounded-full border border-slate-900 bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => applyBandProfile(true)}
                    disabled={isApplyingBandProfile}
                  >
                    Confirm as strong label
                  </button>
                  <Link
                    className="rounded-full border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-900"
                    to={`/demodulation?capture_id=${encodeURIComponent(selectedCapture.capture_id)}`}
                  >
                    Send to Demodulator
                  </Link>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-slate-700 md:grid-cols-4">
                  <div className="rounded-xl bg-white px-3 py-2">Label: {selectedCapture.transmitter.transmitter_label || 'missing'}</div>
                  <div className="rounded-xl bg-white px-3 py-2">Class: {selectedCapture.transmitter.transmitter_class || 'missing'}</div>
                  <div className="rounded-xl bg-white px-3 py-2">Modulation: {selectedCapture.transmitter.modulation_class || 'missing'}</div>
                  <div className="rounded-xl bg-white px-3 py-2">Profile: {selectedCapture.transmitter.profile_key || 'not assigned'}</div>
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-800">Validated dataset routing</div>
                    <h3 className="mt-2 text-lg font-semibold text-slate-900">Send this validated capture to RF Signal Understanding</h3>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-700">
                      Use this only after QC has accepted the capture. RF Signal Understanding learns signal family, modulation-like or
                      protocol-like labels; RF Experiment Lab E1/E3/E5 can still use the same capture later through RFExperimentDatasetV1.
                    </p>
                  </div>
                  <button
                    className="rounded-full border border-indigo-300 bg-white px-4 py-2 text-sm font-semibold text-indigo-900 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => registerSelectedForRFSignalUnderstanding()}
                    disabled={selectedCapture.quality_review.status !== 'valid'}
                  >
                    Register in RF Signal Understanding
                  </button>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-indigo-950 md:grid-cols-3">
                  <div className="rounded-xl border border-indigo-100 bg-white px-3 py-2">E1 needs `transmitter_id` and raw IQ.</div>
                  <div className="rounded-xl border border-indigo-100 bg-white px-3 py-2">E3 needs raw IQ or derived spectrogram/waterfall.</div>
                  <div className="rounded-xl border border-indigo-100 bg-white px-3 py-2">RF Signal Understanding needs `signal_type` or modulation-like labels.</div>
                </div>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div>Created: {formatTimestamp(selectedCapture.created_at_utc)}</div>
                  <div className="mt-2">Record updated: {formatTimestamp(selectedCapture.updated_at_utc)}</div>
                  <div className="mt-2">Scenario timestamp: {formatTimestamp(selectedCapture.scenario.timestamp_utc)}</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div>Split: {selectedCapture.dataset_split}</div>
                  <div className="mt-2">Dataset destination: {selectedCapture.capture_config.dataset_destination}</div>
                  <div className="mt-2">Legacy QC status: {selectedCapture.quality_review.status}</div>
                  <div className="mt-2">Capture quality: {selectedCapture.quality_review.capture_quality ?? 'unknown'}</div>
                  <div className="mt-2">Label status: {selectedCapture.quality_review.label_status ?? 'unknown'}</div>
                  <div className="mt-2">Review status: {selectedCapture.quality_review.review_status ?? 'unknown'}</div>
                  <div className="mt-2">Training readiness: {selectedCapture.quality_review.training_readiness ?? 'unknown'}</div>
                  <div className="mt-2">QC profile: {selectedCapture.quality_review.qc_policy_profile ?? 'legacy'}</div>
                </div>
              </div>

              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Capture configuration</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    <div>Center frequency: {formatHz(selectedCapture.capture_config.center_frequency_hz)}</div>
                    <div>Sample rate: {formatHz(selectedCapture.capture_config.sample_rate_hz)}</div>
                    <div>Effective bandwidth: {formatHz(selectedCapture.capture_config.effective_bandwidth_hz)}</div>
                    <div>Gain: {String((selectedCapture.capture_config.gain_settings?.['composite_gain_db'] ?? 'not available'))} dB</div>
                    <div>Antenna: {selectedCapture.capture_config.antenna_port || 'not available'}</div>
                    <div>Format: {selectedCapture.capture_config.file_format}</div>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Quality metrics</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    <div>Selected SNR: {selectedCapture.quality_metrics.selected_snr_db ?? selectedCapture.quality_metrics.estimated_snr_db ?? 0} dB</div>
                    <div>SNR method: {selectedCapture.quality_metrics.selected_snr_method || selectedCapture.snr?.selected_snr_method || 'not available'}</div>
                    <div>SNR temporal/burst: {selectedCapture.quality_metrics.burst_snr_db ?? selectedCapture.snr?.burst_snr_db ?? 'not available'} dB</div>
                    <div>SNR espectral: {selectedCapture.quality_metrics.spectral_snr_db ?? selectedCapture.snr?.spectral_snr_db ?? 'not available'} dB</div>
                    <div>Channel presence: {selectedCapture.quality_metrics.channel_presence_ratio !== undefined ? `${(Number(selectedCapture.quality_metrics.channel_presence_ratio) * 100).toFixed(1)}%` : 'not available'}</div>
                    <div>Offset de frecuencia: {selectedCapture.quality_metrics.frequency_offset_hz ?? 0} Hz</div>
                    <div>Occupied bandwidth: {selectedCapture.quality_metrics.occupied_bandwidth_hz ?? 0} Hz</div>
                    <div>Clipping: {selectedCapture.quality_metrics.clipping_pct ?? 0}%</div>
                    <div>Silence: {selectedCapture.quality_metrics.silence_pct ?? 0}%</div>
                    <div>IQ samples: {selectedCapture.iq_file_diagnostics?.num_complex_samples ?? 'not available'}</div>
                    <div>IQ near-zero: {selectedCapture.iq_file_diagnostics?.near_zero_ratio !== undefined ? `${(Number(selectedCapture.iq_file_diagnostics.near_zero_ratio) * 100).toFixed(3)}%` : 'not available'}</div>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Burst extraction</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    <div>Method: {selectedCapture.burst_detection.method}</div>
                    <div>Pre-trigger: {selectedCapture.burst_detection.pre_trigger_samples}</div>
                    <div>Post-trigger: {selectedCapture.burst_detection.post_trigger_samples}</div>
                    <div>ROI: {selectedCapture.burst_detection.regions_of_interest.join(', ') || 'none'}</div>
                    <div>Export windows: {(selectedCapture.quality_review.export_windows ?? []).join(', ') || 'not reviewed'}</div>
                  </div>
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Capture-time live preview</div>
                <div className="mt-3 space-y-2 text-sm text-slate-700">
                  <div>Live SNR: {selectedCapture.preview_metrics?.live_preview_snr_db ?? 'not available'} dB</div>
                  <div>Live noise floor: {selectedCapture.preview_metrics?.live_preview_noise_floor_db ?? 'not available'} dB</div>
                  <div>Live peak: {selectedCapture.preview_metrics?.live_preview_peak_level_db ?? 'not available'} dB</div>
                  <div>Live peak frequency: {formatHz(selectedCapture.preview_metrics?.live_preview_peak_frequency_hz)}</div>
                </div>
                <div className="mt-3 text-xs leading-6 text-slate-500">
                  Este bloque muestra lo que veía el operador justo antes de capturar. No sustituye el QC offline calculado sobre el archivo IQ guardado.
                </div>
              </div>

              {selectedDiagnostic && (
                <RfDatasetDiagnosticCard diagnostic={selectedDiagnostic} />
              )}

              <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Automatic review flags</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(selectedCapture.quality_review.quality_flags ?? []).map((flag) => (
                    <span key={flag} className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs text-slate-700">
                      {flag}
                    </span>
                  ))}
                  {(selectedCapture.quality_review.quality_flags ?? []).length === 0 && (
                    <span className="text-sm text-slate-500">No automatic flags raised.</span>
                  )}
                </div>
                <div className="mt-4 text-sm text-slate-700">
                  IQ path: <span className="font-mono text-xs">{selectedCapture.artifacts.iq_file || selectedCapture.capture_config.output_path || 'not linked'}</span>
                </div>
                <div className="mt-2 text-sm text-slate-700">
                  SHA-256: <span className="font-mono text-xs">{selectedCapture.artifacts.sha256 || 'pending'}</span>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm text-slate-500">No fingerprinting captures available yet.</div>
          )}
        </section>
      </div>
    </div>
  );
};

function RfDatasetDiagnosticCard({ diagnostic }: { diagnostic: ReturnType<typeof buildRfCaptureDiagnostic> }) {
  const palette =
    diagnostic.status === 'valid'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-950'
      : diagnostic.status === 'doubtful'
        ? 'border-amber-200 bg-amber-50 text-amber-950'
        : 'border-rose-200 bg-rose-50 text-rose-950';
  return (
    <div className={`mt-4 rounded-2xl border p-4 ${palette}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-[0.18em]">Post-capture RF intelligence</div>
        <span className="rounded-full border border-current/30 px-2 py-1 text-xs font-semibold uppercase tracking-[0.14em]">
          {diagnostic.status}
        </span>
      </div>
      <div className="mt-2 text-sm font-semibold">{diagnostic.title}</div>
      <div className="mt-1 text-sm opacity-90">{diagnostic.summary}</div>
      <div className="mt-3 grid gap-1 text-xs opacity-90 md:grid-cols-2">
        {diagnostic.facts.map((fact) => <div key={fact}>{fact}</div>)}
      </div>
      <div className="mt-3 space-y-1 text-xs leading-5 opacity-95">
        {diagnostic.recommendations.slice(0, 4).map((item) => (
          <div key={item}>- {item}</div>
        ))}
      </div>
    </div>
  );
}
