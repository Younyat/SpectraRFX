import React, { useEffect, useMemo, useState } from 'react';
import { BadgeCheck, BarChart3, BrainCircuit, DatabaseZap, FileJson, FlaskConical, GitCompare, Layers3, Play, RadioTower, RefreshCw, Route, Save, ScanSearch, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ApiService } from '../../app/services/ApiService';

const api = new ApiService();

type ExperimentKind = 'e5' | 'e1' | 'e3';
type CaptureSortKey = 'time' | 'modulation' | 'label' | 'qc' | 'source' | 'frequency';
type SortDirection = 'asc' | 'desc';
type TrainingReadinessPolicy = 'scientific_strict' | 'training_draft' | 'all_debug';

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_42px_rgba(15,23,42,0.07)]';

const papers = [
  {
    experiment: 'E0 Morphological Baseline',
    authors: 'RF-Fingerprint-Lab-v6 project baseline',
    title: 'Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline',
    adopted: 'The experiment formalizes the existing waterfall morphological detector as a reproducible baseline with detections, latency and region statistics.',
    boundary: 'This is not a learned detector and does not claim to reproduce SSD, Faster R-CNN or YOLO.',
  },
  {
    experiment: 'E5 Spectral Feature Baseline',
    authors: 'Kilic et al.; Nie et al.; O Shea, Clancy and Ebeid',
    title: 'Drone Classification Using RF Signal Based Spectral Features; UAV Detection and Identification Based on WiFi Signal and RF Fingerprint; Practical Signal Detection and Classification in GNU Radio',
    adopted: 'The implementation adopts the paper-level idea of explainable spectral descriptors: PSD statistics, spectral shape, bandwidth, energy ratios and classical ML classifiers.',
    boundary: 'It is a controlled baseline for comparison, not a claim that the exact original datasets, feature sets or hardware conditions are reproduced.',
  },
  {
    experiment: 'E1 Raw IQ CNN 1D',
    authors: 'Riyaz et al.; Jian et al.',
    title: 'Deep Learning Convolutional Neural Networks for Radio Identification; Deep Learning for RF Fingerprinting: A Massive Experimental Study',
    adopted: 'The implementation adopts direct supervised learning from raw I/Q windows with input shape [2, N], where the model can learn transmitter-specific distortions from I and Q channels.',
    boundary: 'It is closed-set device identification only. It is not open-set recognition, spoofing detection or universal cross-technology fingerprinting.',
  },
  {
    experiment: 'E3 Spectrogram/Waterfall CNN 2D',
    authors: 'Shen et al.; Lin et al.; Liu et al.; Bremnes et al.',
    title: 'Radio Frequency Fingerprint Identification for LoRa Using Deep Learning; A Radio Frequency Signal Recognition Method Based on Spectrogram; RF Fingerprint Recognition Based on Spectrum Waterfall Diagram; Classification of UAVs Utilizing Fixed Boundary Empirical Wavelet Sub-Bands of RF Fingerprints and Deep CNN',
    adopted: 'The implementation adopts the conversion of RF captures into time-frequency images and compares simple CNN 2D, optional ResNet18 and optional VGG11 under the same split and metrics.',
    boundary: 'It is image-based closed-set classification. It is not object detection and does not implement SSD, YOLO or Faster R-CNN.',
  },
  {
    experiment: 'Reproducibility layer',
    authors: 'SigMF community practice; ORACLE/WiSig dataset methodology; Jian et al.',
    title: 'SigMF-style metadata discipline; ORACLE/WiSig dataset traceability; Deep Learning for RF Fingerprinting: A Massive Experimental Study',
    adopted: 'The platform adopts traceable capture metadata, SHA-256 hashes, dataset versions, representation manifests, result packages and strict group-disjoint splits.',
    boundary: 'This layer is methodological infrastructure. It does not train a model by itself.',
  },
];

const flowCards = [
  { title: 'Capture Dataset', text: 'Acquire IQ from Capture Lab, RF Signal Understanding or the internal experimental sample registry.', icon: RadioTower, route: '/capture' },
  { title: 'Review Samples', text: 'Check labels, transmitter identity, QC status, hashes, metadata and split groups before training.', icon: DatabaseZap, route: '/dataset-builder' },
  { title: 'Export Dataset', text: 'Convert internal or external sources into RFExperimentDatasetV1 so E1, E3 and E5 consume the same contract.', icon: FileJson, route: '/rf-experiment-lab' },
  { title: 'Train Models', text: 'Run E5 spectral ML, E1 raw IQ CNN 1D or E3 spectrogram/waterfall CNN 2D with strict group-disjoint splits.', icon: BrainCircuit, route: '/rf-experiment-lab' },
  { title: 'Validate', text: 'Inspect confusion matrices, group metrics, confidence summaries and scientific warnings.', icon: ShieldCheck, route: '/rf-experiment-lab' },
  { title: 'Retrain', text: 'Launch a new version with the same manifest or a curated manifest and preserve every result package.', icon: RefreshCw, route: '/rf-experiment-lab' },
  { title: 'Live Prediction', text: 'Apply selected trained experiment results to saved captures, marker regions, frozen windows or live context.', icon: ScanSearch, route: '/spectrum' },
  { title: 'Model Comparison', text: 'Compare E1, E3 and E5 under the same dataset, split and metric table.', icon: BarChart3, route: '/rf-experiment-lab' },
];

const techniques: Array<{
  id: ExperimentKind | 'e0';
  title: string;
  stage: string;
  input: string;
  model: string;
  reference: string;
  purpose: string;
}> = [
  {
    id: 'e0',
    title: 'E0 Morphological Baseline',
    stage: 'Stage 1 region detection',
    input: 'waterfall',
    model: 'morphological_heuristic',
    reference: 'Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline',
    purpose: 'Fast explainable detector, permanent fallback, no training.',
  },
  {
    id: 'e5',
    title: 'E5 Spectral Feature Baseline',
    stage: 'Stage 1 or Stage 2 classical baseline',
    input: 'fft_psd',
    model: 'Logistic Regression, Random Forest, SVM RBF, KNN',
    reference: 'Drone Classification Using RF Signal Based Spectral Features; UAV Detection and Identification Based on WiFi Signal and RF Fingerprint; Practical Signal Detection and Classification in GNU Radio',
    purpose: 'Explainable PSD and spectral feature baseline before deep learning.',
  },
  {
    id: 'e1',
    title: 'E1 Raw IQ CNN 1D',
    stage: 'Stage 2 device fingerprinting',
    input: 'raw_iq [2, N]',
    model: 'CNN 1D',
    reference: 'Deep Learning Convolutional Neural Networks for Radio Identification; Deep Learning for RF Fingerprinting: A Massive Experimental Study',
    purpose: 'Closed-set transmitter identification directly from I/Q windows.',
  },
  {
    id: 'e3',
    title: 'E3 Spectrogram/Waterfall CNN 2D',
    stage: 'Closed-set signal recognition or fingerprinting',
    input: 'spectrogram or waterfall [1, H, W]',
    model: 'simple CNN 2D, optional ResNet18, optional VGG11',
    reference: 'Radio Frequency Fingerprint Identification for LoRa Using Deep Learning; A Radio Frequency Signal Recognition Method Based on Spectrogram; RF Fingerprint Recognition Based on Spectrum Waterfall Diagram; Classification of UAVs Utilizing Fixed Boundary Empirical Wavelet Sub-Bands of RF Fingerprints and Deep CNN',
    purpose: 'Compare time-frequency image learning against raw IQ and spectral features.',
  },
];

const defaultSplit = { strategy: 'capture_disjoint', group_by: ['capture_id'], train_ratio: 0.7, validation_ratio: 0.15, test_ratio: 0.15 };

const splitGroupFields = (strategy: string) => {
  if (strategy === 'session_disjoint') return ['session_id'];
  if (strategy === 'day_disjoint') return ['day_id'];
  if (strategy === 'receiver_disjoint') return ['receiver_id'];
  if (strategy === 'environment_disjoint') return ['environment_id'];
  if (strategy === 'device_holdout') return ['transmitter_id'];
  return ['capture_id'];
};

const formatDateTime = (value: unknown) => {
  if (!value) return 'time n/a';
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
};

const formatHzShort = (value: unknown) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) return 'freq n/a';
  const abs = Math.abs(numeric);
  if (abs >= 1e9) return `${(numeric / 1e9).toFixed(4)} GHz`;
  if (abs >= 1e6) return `${(numeric / 1e6).toFixed(3)} MHz`;
  if (abs >= 1e3) return `${(numeric / 1e3).toFixed(1)} kHz`;
  return `${numeric.toFixed(0)} Hz`;
};

const captureLabel = (capture: Record<string, any>) =>
  String(capture.transmitter_id ?? capture.label ?? capture.device_model ?? capture.capture_id ?? 'unknown capture');

const modulationLabel = (capture: Record<string, any>) =>
  String(capture.modulation_class ?? capture.modulation_family ?? capture.signal_type ?? capture.technology ?? capture.transmitter_class ?? 'modulation n/a');

const captureTimeValue = (capture: Record<string, any>) => {
  const value = capture.timestamp_utc ?? capture.created_at ?? capture.created_at_utc;
  const millis = value ? new Date(String(value)).getTime() : 0;
  return Number.isFinite(millis) ? millis : 0;
};

export const RFExperimentLabView: React.FC = () => {
  const [health, setHealth] = useState<Record<string, any> | null>(null);
  const [captures, setCaptures] = useState<Array<Record<string, any>>>([]);
  const [internalSamples, setInternalSamples] = useState<Array<Record<string, any>>>([]);
  const [runs, setRuns] = useState<Array<Record<string, any>>>([]);
  const [selectedTechnique, setSelectedTechnique] = useState<ExperimentKind>('e5');
  const [selectedCaptureIds, setSelectedCaptureIds] = useState<string[]>([]);
  const [datasetVersion, setDatasetVersion] = useState('experiment_dataset_v1');
  const [datasetSource, setDatasetSource] = useState<'internal' | 'external_custom' | 'oracle' | 'wisig' | 'radioml' | 'sig53'>('internal');
  const [datasetTask, setDatasetTask] = useState<'device_fingerprinting' | 'signal_recognition' | 'modulation_classification'>('device_fingerprinting');
  const [datasetRepresentation, setDatasetRepresentation] = useState<'raw_iq' | 'fft_psd' | 'spectrogram' | 'waterfall'>('raw_iq');
  const [splitStrategy, setSplitStrategy] = useState('session_disjoint');
  const [externalDatasetPath, setExternalDatasetPath] = useState('');
  const [externalSourceFormat, setExternalSourceFormat] = useState('auto');
  const [datasetManifestPath, setDatasetManifestPath] = useState('');
  const [datasetPreview, setDatasetPreview] = useState<Record<string, any> | null>(null);
  const [captureSortKey, setCaptureSortKey] = useState<CaptureSortKey>('time');
  const [captureSortDirection, setCaptureSortDirection] = useState<SortDirection>('desc');
  const [pendingCaptureSortKey, setPendingCaptureSortKey] = useState<CaptureSortKey>('time');
  const [pendingCaptureSortDirection, setPendingCaptureSortDirection] = useState<SortDirection>('desc');
  const [labelField, setLabelField] = useState('transmitter_id');
  const [trainingReadinessPolicy, setTrainingReadinessPolicy] = useState<TrainingReadinessPolicy>('scientific_strict');
  const [allowWeakLabelsDebug, setAllowWeakLabelsDebug] = useState(false);
  const [e3Representation, setE3Representation] = useState<'spectrogram' | 'waterfall'>('spectrogram');
  const [e3ModelType, setE3ModelType] = useState<'simple_cnn2d' | 'resnet18' | 'vgg11'>('simple_cnn2d');
  const [lastResponse, setLastResponse] = useState<Record<string, any> | null>(null);
  const [benchmark, setBenchmark] = useState<Record<string, any> | null>(null);
  const [prediction, setPrediction] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = async () => {
    const [nextHealth, nextCaptures, nextRuns, nextInternalSamples] = await Promise.all([
      api.getRFExperimentLabHealth().catch(() => null),
      api.getRFExperimentCaptures().catch(() => []),
      api.listRFExperimentRuns().catch(() => []),
      api.getRFExperimentInternalSamples().catch(() => []),
    ]);
    setHealth(nextHealth?.data ?? nextHealth);
    setCaptures(nextCaptures);
    setRuns(nextRuns);
    setInternalSamples(nextInternalSamples);
    if (selectedCaptureIds.length === 0 && nextCaptures.length > 0) {
      setSelectedCaptureIds(nextCaptures.slice(0, 12).map((item) => String(item.capture_id)));
    }
  };

  useEffect(() => {
    refresh().catch((error) => {
      console.error('Failed to load RF Experiment Lab', error);
      setMessage('Backend RF Experiment Lab is not reachable.');
    });
  }, []);

  useEffect(() => {
    if (selectedTechnique === 'e5') {
      setDatasetTask('signal_recognition');
      setLabelField('signal_type');
      return;
    }
    if (selectedTechnique === 'e1') {
      setDatasetTask('device_fingerprinting');
      setLabelField('transmitter_id');
      return;
    }
    setLabelField(datasetTask === 'signal_recognition' ? 'signal_type' : 'transmitter_id');
  }, [selectedTechnique]);

  useEffect(() => {
    setAllowWeakLabelsDebug(trainingReadinessPolicy === 'all_debug');
  }, [trainingReadinessPolicy]);

  const selectedTechniqueInfo = techniques.find((item) => item.id === selectedTechnique);
  const selectedRuns = useMemo(() => runs.filter((run) => ['e5_spectral_feature_baseline', 'e1_raw_iq_cnn1d', 'e3_spectrogram_cnn2d'].includes(String(run.experiment_type))), [runs]);
  const selectedCaptureObjects = useMemo(
    () => captures.filter((item) => selectedCaptureIds.includes(String(item.capture_id))),
    [captures, selectedCaptureIds],
  );
  const captureDiagnostics = useMemo(() => {
    const countBy = (key: string) =>
      captures.reduce<Record<string, number>>((acc, item) => {
        const value = String(item[key] ?? 'unknown');
        acc[value] = (acc[value] ?? 0) + 1;
        return acc;
      }, {});
    return {
      total: captures.length,
      withRaw: captures.filter((item) => item.raw_file).length,
      bySource: countBy('source'),
      bySplit: countBy('dataset_split'),
      byQc: countBy('qc_status'),
    };
  }, [captures]);
  const selectedEligibility = useMemo(() => {
    const counts = (key: string) =>
      selectedCaptureObjects.reduce<Record<string, number>>((acc, item) => {
        const value = String(item[key] ?? 'unknown');
        acc[value] = (acc[value] ?? 0) + 1;
        return acc;
      }, {});
    const labelCounts = selectedCaptureObjects.reduce<Record<string, number>>((acc, item) => {
      const value = String(item[labelField] ?? item.label ?? 'unknown');
      acc[value] = (acc[value] ?? 0) + 1;
      return acc;
    }, {});
    return {
      labelCounts,
      readiness: counts('training_readiness'),
      captureQuality: counts('capture_quality'),
      labelStatus: counts('label_status'),
    };
  }, [labelField, selectedCaptureObjects]);
  const sortedCaptures = useMemo(() => {
    const valueFor = (capture: Record<string, any>) => {
      if (captureSortKey === 'time') return captureTimeValue(capture);
      if (captureSortKey === 'modulation') return modulationLabel(capture).toLowerCase();
      if (captureSortKey === 'label') return captureLabel(capture).toLowerCase();
      if (captureSortKey === 'qc') return String(capture.qc_status ?? '').toLowerCase();
      if (captureSortKey === 'source') return String(capture.source ?? '').toLowerCase();
      return Number(capture.center_frequency_hz ?? 0);
    };
    return [...captures].sort((left, right) => {
      const a = valueFor(left);
      const b = valueFor(right);
      let result = 0;
      if (typeof a === 'number' && typeof b === 'number') result = a - b;
      else result = String(a).localeCompare(String(b));
      return captureSortDirection === 'asc' ? result : -result;
    });
  }, [captures, captureSortDirection, captureSortKey]);

  const experimentPayload = () => {
    const base = {
      dataset_version: datasetVersion,
      dataset_manifest_path: datasetManifestPath || undefined,
      capture_ids: selectedCaptureIds,
      label_field: labelField,
      training_readiness_policy: trainingReadinessPolicy,
      allow_weak_labels_debug: allowWeakLabelsDebug,
      split: { ...defaultSplit, strategy: splitStrategy, group_by: splitGroupFields(splitStrategy) },
    };
    if (selectedTechnique === 'e5') {
      return { ...base, models: ['logistic_regression', 'random_forest', 'svm_rbf', 'knn'], input_representation: 'fft_psd' };
    }
    if (selectedTechnique === 'e1') {
      return { ...base, epochs: 1, batch_size: 8, window_size_samples: 2048, max_windows: 64 };
    }
    return {
      ...base,
      input_representation: e3Representation,
      model_type: e3ModelType,
      task: datasetTask,
      epochs: 1,
      batch_size: 8,
      window_size_samples: 2048,
      max_samples: 64,
      image_height: 128,
      image_width: 128,
    };
  };

  const datasetPayload = () => ({
    dataset_id: 'rf_experiment_dataset',
    dataset_version: datasetVersion,
    dataset_source: datasetSource,
    task: datasetTask,
    representation: datasetRepresentation,
    experiment_id: selectedTechnique,
    capture_ids: selectedCaptureIds,
    label_field: labelField,
    training_readiness_policy: trainingReadinessPolicy,
    allow_weak_labels_debug: allowWeakLabelsDebug,
    split_strategy: splitStrategy,
    split_group_fields: splitGroupFields(splitStrategy),
    inclusion_mode: splitStrategy === 'random' ? 'debug_include_candidates' : 'scientific_strict',
    source_path: externalDatasetPath || undefined,
    source_format: externalSourceFormat,
  });

  const runDatasetAction = async (mode: 'preview' | 'export') => {
    setBusy(true);
    setMessage('');
    try {
      const payload = datasetPayload();
      const response = datasetSource === 'internal'
        ? mode === 'preview'
          ? await api.previewRFExperimentDatasetV1(payload)
          : await api.exportRFExperimentDatasetV1(payload)
        : mode === 'preview'
          ? await api.previewExternalRFExperimentDataset(payload)
          : await api.importExternalRFExperimentDataset(payload);
      const data = response.data ?? response;
      setDatasetPreview(data);
      if (data.manifest_path) setDatasetManifestPath(String(data.manifest_path));
      setLastResponse(response);
      setMessage(mode === 'preview' ? 'RFExperimentDatasetV1 preview completed.' : 'RFExperimentDatasetV1 manifest exported.');
    } catch (error: any) {
      setMessage(String(error?.response?.data?.message ?? error?.message ?? 'Dataset action failed'));
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (mode: 'preview' | 'run') => {
    setBusy(true);
    setMessage('');
    try {
      const payload = experimentPayload();
      const response = mode === 'preview'
        ? await api.previewRFExperiment(selectedTechnique, payload)
        : await api.runRFExperiment(selectedTechnique, payload);
      setLastResponse(response);
      setMessage(response.message ?? (mode === 'preview' ? 'Preview completed.' : 'Experiment run completed.'));
      await refresh();
    } catch (error: any) {
      const detail = error?.response?.data?.message ?? error?.response?.data?.detail ?? error?.message ?? 'Request failed';
      setMessage(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const runBenchmark = async (exportReport = false) => {
    setBusy(true);
    setMessage('');
    try {
      const ids = selectedRuns.slice(0, 12).map((run) => String(run.experiment_id));
      const response = await api.createRFExperimentBenchmark({
        experiment_ids: ids,
        sort_metric: 'macro_f1',
        include_predictions_summary: true,
        include_group_metrics: true,
        include_confusion_matrices: true,
        export: exportReport,
      });
      setBenchmark(response.data ?? response);
      setMessage(exportReport ? 'Benchmark exported.' : 'Benchmark generated.');
    } catch (error: any) {
      setMessage(String(error?.response?.data?.message ?? error?.message ?? 'Benchmark failed'));
    } finally {
      setBusy(false);
    }
  };

  const runPrediction = async (sourceType: 'saved_capture' | 'marker_region' | 'frozen_window' | 'live_context') => {
    setBusy(true);
    setMessage('');
    try {
      const ids = selectedRuns.slice(0, 3).map((run) => String(run.experiment_id));
      const payload = {
        experiment_ids: ids,
        source_type: sourceType,
        input_sample_id: selectedCaptureIds[0] ?? 'live_or_region_input',
        capture_id: selectedCaptureIds[0],
        marker_region: sourceType === 'marker_region' ? { marker_1: 'Marker 1', marker_2: 'Marker 2' } : undefined,
        live_context: sourceType === 'live_context' ? { panel: 'live_spectrum', overlay: 'rf_experiment_prediction' } : undefined,
        persist: true,
      };
      const response = sourceType === 'marker_region'
        ? await api.compareRFExperimentRegion(payload)
        : await api.predictRFExperiment(payload);
      const data = response.data ?? response;
      setPrediction(data);
      setLastResponse(response);
      setMessage('RF Experiment Lab prediction contract persisted.');
    } catch (error: any) {
      setMessage(String(error?.response?.data?.message ?? error?.message ?? 'Prediction failed'));
    } finally {
      setBusy(false);
    }
  };

  const toggleCapture = (captureId: string) => {
    setSelectedCaptureIds((current) =>
      current.includes(captureId) ? current.filter((item) => item !== captureId) : [...current, captureId],
    );
  };

  const selectAllSortedCaptures = () => {
    setSelectedCaptureIds(Array.from(new Set(sortedCaptures.map((item) => String(item.capture_id)).filter(Boolean))));
  };

  const clearSelectedCaptures = () => {
    setSelectedCaptureIds([]);
  };

  return (
    <div className="min-h-full bg-[linear-gradient(180deg,_#f8fafc,_#eef2f7)] p-6">
      <section className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-2xl border border-slate-200 bg-slate-950 p-7 text-slate-50 shadow-[0_28px_70px_rgba(15,23,42,0.22)]">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">
            <FlaskConical className="h-4 w-4" />
            RF Experiment Lab
          </div>
          <h1 className="mt-4 max-w-4xl text-3xl font-semibold leading-tight">
            Flujo reproducible desde captura y dataset hasta entrenamiento, validacion y benchmark cientifico.
          </h1>
          <p className="mt-4 max-w-4xl text-sm leading-7 text-slate-300">
            Esta capa no reemplaza Live Spectrum, Waterfall, Capture Lab, Dataset Builder, RF Intelligence ni RF Signal Understanding.
            Consume sus capturas y metadatos para ejecutar experimentos trazables: E0, E5, E1 y E3.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link className="rounded-full bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950" to="/capture">1. Capturar datos</Link>
            <Link className="rounded-full border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-100" to="/dataset-builder">2. Curar dataset</Link>
            <button className="rounded-full border border-cyan-300/40 px-4 py-2 text-sm font-semibold text-cyan-100" onClick={() => runAction('preview')} disabled={busy}>
              3. Preview experimental
            </button>
            <button className="rounded-full border border-emerald-300/40 px-4 py-2 text-sm font-semibold text-emerald-100" onClick={() => runBenchmark(false)} disabled={busy || selectedRuns.length === 0}>
              4. Benchmark
            </button>
          </div>
        </div>

        <div className={card}>
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Module health</div>
            <button className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700" onClick={() => refresh()}>
              <RefreshCw className="mr-1 inline h-3 w-3" />
              Refresh
            </button>
          </div>
          <div className="mt-4 grid gap-3 text-sm text-slate-700">
            <Fact label="Module loaded" value={String(Boolean(health?.module_loaded))} />
            <Fact label="Morphological detector" value={health?.morphological_detector_available?.status ?? 'unknown'} />
            <Fact label="Dataset adapter" value={String(Boolean(health?.dataset_adapter_available))} />
            <Fact label="Optional missing" value={(health?.optional_dependencies_missing ?? []).join(', ') || 'none reported'} />
            <Fact label="Visible captures" value={`${captureDiagnostics.total} (${captureDiagnostics.withRaw} with raw IQ)`} />
          </div>
        </div>
      </section>

      <section className="mt-5 grid gap-4 xl:grid-cols-4">
        {flowCards.map(({ title, text, icon: Icon, route }) => (
          <Link key={title} to={route} className={card}>
            <Icon className="h-5 w-5 text-slate-800" />
            <div className="mt-3 text-sm font-semibold text-slate-900">{title}</div>
            <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
          </Link>
        ))}
      </section>

      <section className="mt-5 grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <div className={card}>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            <Layers3 className="h-4 w-4" />
            Techniques adopted so far
          </div>
          <div className="mt-4 space-y-3">
            {techniques.map((technique) => (
              <button
                key={technique.id}
                onClick={() => technique.id !== 'e0' && setSelectedTechnique(technique.id)}
                className={`w-full rounded-2xl border p-4 text-left ${selectedTechnique === technique.id ? 'border-slate-950 bg-slate-950 text-white' : 'border-slate-200 bg-slate-50 text-slate-800'}`}
              >
                <div className="font-semibold">{technique.title}</div>
                <div className="mt-1 text-xs opacity-75">{technique.stage} | {technique.input}</div>
                <div className="mt-2 text-sm opacity-90">{technique.purpose}</div>
                <div className="mt-2 text-xs opacity-70">Reference: {technique.reference}</div>
              </button>
            ))}
          </div>
        </div>

        <div className={card}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Experiment control</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-900">{selectedTechniqueInfo?.title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">{selectedTechniqueInfo?.purpose}</p>
            </div>
            <div className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
              strict split
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <label className="text-sm text-slate-700">
              Dataset version
              <input className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={datasetVersion} onChange={(event) => setDatasetVersion(event.target.value)} />
            </label>
            <label className="text-sm text-slate-700">
              Label field
              <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={labelField} onChange={(event) => setLabelField(event.target.value)}>
                <option value="transmitter_id">transmitter_id</option>
                <option value="signal_type">signal_type</option>
                <option value="modulation_class">modulation_class</option>
                <option value="technology">technology</option>
              </select>
            </label>
            <label className="text-sm text-slate-700">
              Dataset eligibility
              <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={trainingReadinessPolicy} onChange={(event) => setTrainingReadinessPolicy(event.target.value as TrainingReadinessPolicy)}>
                <option value="scientific_strict">scientific_strict: ready_for_training only</option>
                <option value="training_draft">training_draft: candidate strong labels</option>
                <option value="all_debug">all_debug: bypass gates</option>
              </select>
            </label>
            <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={allowWeakLabelsDebug}
                disabled={trainingReadinessPolicy !== 'all_debug'}
                onChange={(event) => setAllowWeakLabelsDebug(event.target.checked)}
              />
              Allow weak labels only in debug
            </label>
            {selectedTechnique === 'e3' && (
              <>
                <label className="text-sm text-slate-700">
                  Representation
                  <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={e3Representation} onChange={(event) => setE3Representation(event.target.value as 'spectrogram' | 'waterfall')}>
                    <option value="spectrogram">spectrogram</option>
                    <option value="waterfall">waterfall</option>
                  </select>
                </label>
                <label className="text-sm text-slate-700">
                  E3 model
                  <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={e3ModelType} onChange={(event) => setE3ModelType(event.target.value as any)}>
                    <option value="simple_cnn2d">simple_cnn2d</option>
                    <option value="resnet18">resnet18 optional</option>
                    <option value="vgg11">vgg11 optional</option>
                  </select>
                </label>
              </>
            )}
          </div>
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
            {trainingReadinessPolicy === 'scientific_strict' && (
              <span>Scientific strict excludes `candidate`, `doubtful`, weak-label and manual-override captures. Use this for benchmarkable results.</span>
            )}
            {trainingReadinessPolicy === 'training_draft' && (
              <span>Training draft includes `candidate` captures only when the label is strong and QC is not invalid. Use it to debug E5/E1/E3 before curating final data.</span>
            )}
            {trainingReadinessPolicy === 'all_debug' && (
              <span>Debug mode can include weak or not-ready data. It is useful for plumbing tests, not for scientific reporting.</span>
            )}
            {selectedTechnique === 'e5' && <span> For E5 signal recognition, prefer `signal_type` or `modulation_class`; use `transmitter_id` only for confirmed physical-device labels.</span>}
            {selectedTechnique === 'e1' && <span> E1 requires confirmed physical `transmitter_id` classes and should not be trained from automatic weak band-profile labels.</span>}
          </div>

          <div className="mt-5 rounded-2xl border border-cyan-200 bg-cyan-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-800">Unified dataset contract</div>
                <div className="mt-1 text-sm font-semibold text-slate-900">RFExperimentDatasetV1</div>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-700">
                  All internal and external sources are first normalized to the same manifest before E1, E3 or E5 sees them.
                </p>
              </div>
              {datasetManifestPath && (
                <div className="max-w-sm truncate rounded-full border border-cyan-300 bg-white px-3 py-1 text-xs text-cyan-900">
                  {datasetManifestPath}
                </div>
              )}
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <label className="text-sm text-slate-700">
                Dataset source
                <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={datasetSource} onChange={(event) => setDatasetSource(event.target.value as any)}>
                  <option value="internal">internal: Capture Lab / RF Signal Understanding</option>
                  <option value="oracle">ORACLE public dataset</option>
                  <option value="wisig">WiSig public dataset</option>
                  <option value="radioml">RadioML public dataset</option>
                  <option value="sig53">Sig53 public dataset</option>
                  <option value="external_custom">custom folder / manifest</option>
                </select>
              </label>
              <label className="text-sm text-slate-700">
                Scientific task
                <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={datasetTask} onChange={(event) => {
                  const next = event.target.value as any;
                  setDatasetTask(next);
                  setLabelField(next === 'device_fingerprinting' ? 'transmitter_id' : 'modulation_class');
                }}>
                  <option value="device_fingerprinting">device_fingerprinting</option>
                  <option value="signal_recognition">signal_recognition</option>
                  <option value="modulation_classification">modulation_classification</option>
                </select>
              </label>
              <label className="text-sm text-slate-700">
                Representation
                <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={datasetRepresentation} onChange={(event) => setDatasetRepresentation(event.target.value as any)}>
                  <option value="raw_iq">raw_iq</option>
                  <option value="fft_psd">fft_psd</option>
                  <option value="spectrogram">spectrogram</option>
                  <option value="waterfall">waterfall</option>
                </select>
              </label>
              <label className="text-sm text-slate-700">
                Split strategy
                <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={splitStrategy} onChange={(event) => setSplitStrategy(event.target.value)}>
                  <option value="session_disjoint">session_disjoint</option>
                  <option value="day_disjoint">day_disjoint</option>
                  <option value="receiver_disjoint">receiver_disjoint</option>
                  <option value="environment_disjoint">environment_disjoint</option>
                  <option value="device_holdout">device_holdout</option>
                  <option value="random">random debug only</option>
                </select>
              </label>
              {datasetSource !== 'internal' && (
                <>
                  <label className="text-sm text-slate-700 md:col-span-2">
                    External dataset path
                    <input className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={externalDatasetPath} onChange={(event) => setExternalDatasetPath(event.target.value)} placeholder="Folder, JSON/CSV manifest, SigMF/HDF5/NumPy/MAT/Pickle/features/images root" />
                  </label>
                  <label className="text-sm text-slate-700">
                    Source format
                    <select className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" value={externalSourceFormat} onChange={(event) => setExternalSourceFormat(event.target.value)}>
                      <option value="auto">auto</option>
                      <option value="iq">iq</option>
                      <option value="cfile">cfile</option>
                      <option value="sigmf">sigmf</option>
                      <option value="hdf5">hdf5</option>
                      <option value="numpy">numpy</option>
                      <option value="matlab">matlab</option>
                      <option value="pickle">pickle</option>
                      <option value="csv_features">csv_features</option>
                      <option value="spectrogram_images">spectrogram_images</option>
                      <option value="waterfall_images">waterfall_images</option>
                    </select>
                  </label>
                </>
              )}
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button className="rounded-full border border-cyan-400 bg-white px-4 py-2 text-sm font-semibold text-cyan-900 disabled:opacity-50" onClick={() => runDatasetAction('preview')} disabled={busy || (datasetSource === 'internal' && selectedCaptureIds.length === 0)}>
                Preview unified dataset
              </button>
              <button className="rounded-full bg-cyan-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={() => runDatasetAction('export')} disabled={busy || (datasetSource === 'internal' && selectedCaptureIds.length === 0)}>
                Export RFExperimentDatasetV1
              </button>
              {datasetPreview && (
                <div className="rounded-full border border-cyan-300 bg-white px-3 py-2 text-xs text-cyan-900">
                  samples: {String(datasetPreview.sample_count ?? 'n/a')} | schema: {String(datasetPreview.schema_version ?? 'n/a')}
                </div>
              )}
            </div>
            {datasetPreview?.warnings?.length > 0 && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
                {datasetPreview?.warnings?.map((warning: any) => String(warning.message)).join(' ')}
              </div>
            )}
          </div>

          <div className="mt-5 rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-800">Internal dataset capture</div>
                <div className="mt-1 text-sm font-semibold text-slate-900">Experimental samples created inside RF Experiment Lab</div>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-700">
                  Each sample is expected to carry raw IQ, RF metadata, label semantics, transmitter or signal class, QC summary, SHA-256 and split_group before it is exported as RFExperimentDatasetV1.
                </p>
              </div>
              <button className="rounded-full border border-indigo-300 bg-white px-3 py-1 text-xs font-semibold text-indigo-900" onClick={() => refresh()}>
                Refresh samples
              </button>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <Fact label="Internal samples" value={String(internalSamples.length)} />
              <Fact label="Accepted" value={String(internalSamples.filter((item) => item.review_status === 'accepted').length)} />
              <Fact label="Pending review" value={String(internalSamples.filter((item) => item.review_status === 'unreviewed').length)} />
              <Fact label="Rejected" value={String(internalSamples.filter((item) => item.review_status === 'rejected').length)} />
            </div>
            <div className="mt-4 max-h-48 space-y-2 overflow-auto">
              {internalSamples.slice(0, 12).map((sample) => (
                <div key={String(sample.sample_id)} className="grid gap-2 rounded-xl border border-indigo-100 bg-white px-3 py-2 text-sm md:grid-cols-[1fr_1fr_1fr_0.8fr]">
                  <span className="font-medium text-slate-800">{String(sample.sample_id)}</span>
                  <span className="text-slate-600">{String(sample.label ?? sample.transmitter_id ?? sample.signal_type ?? 'unlabeled')}</span>
                  <span className="text-slate-500">{String(sample.session_id ?? sample.split_group ?? 'no group')}</span>
                  <span className="text-right text-xs font-semibold uppercase tracking-[0.12em] text-indigo-800">{String(sample.review_status ?? 'unreviewed')}</span>
                </div>
              ))}
              {internalSamples.length === 0 && (
                <div className="rounded-xl border border-dashed border-indigo-200 bg-white p-3 text-sm text-slate-500">
                  No internal RF Experiment Lab samples yet. Captures from Capture Lab and RF Signal Understanding can still be exported through the unified dataset contract above.
                </div>
              )}
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-slate-800">Selected captures: {selectedCaptureIds.length}</div>
              <div className="flex flex-wrap gap-2">
                <button className="text-xs font-semibold text-slate-600 underline" onClick={() => setSelectedCaptureIds(sortedCaptures.slice(0, 12).map((item) => String(item.capture_id)))}>
                  select first 12
                </button>
                <button className="text-xs font-semibold text-slate-600 underline" onClick={selectAllSortedCaptures}>
                  seleccionar todo
                </button>
                <button className="text-xs font-semibold text-slate-600 underline" onClick={clearSelectedCaptures}>
                  deseleccionar todo
                </button>
              </div>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-[1fr_0.7fr_auto]">
              <label className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                Sort by
                <select className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-800" value={pendingCaptureSortKey} onChange={(event) => setPendingCaptureSortKey(event.target.value as CaptureSortKey)}>
                  <option value="time">capture time</option>
                  <option value="modulation">modulation / signal type</option>
                  <option value="label">label / transmitter</option>
                  <option value="qc">QC status</option>
                  <option value="source">source</option>
                  <option value="frequency">center frequency</option>
                </select>
              </label>
              <label className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                Direction
                <select className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-800" value={pendingCaptureSortDirection} onChange={(event) => setPendingCaptureSortDirection(event.target.value as SortDirection)}>
                  <option value="desc">newest / Z-A / high first</option>
                  <option value="asc">oldest / A-Z / low first</option>
                </select>
              </label>
              <button className="self-end rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => {
                setCaptureSortKey(pendingCaptureSortKey);
                setCaptureSortDirection(pendingCaptureSortDirection);
              }}>
                Ordenar
              </button>
            </div>
            <div className="mt-2 text-xs text-slate-500">
              Orden aplicado: {captureSortKey} / {captureSortDirection}. La ordenacion se aplica a toda la lista visible, no solo a las capturas seleccionadas.
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600">
                <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">Sources</div>
                <div className="mt-2">{Object.entries(captureDiagnostics.bySource).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600">
                <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">Splits</div>
                <div className="mt-2">{Object.entries(captureDiagnostics.bySplit).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600">
                <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">QC</div>
                <div className="mt-2">{Object.entries(captureDiagnostics.byQc).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-4">
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-xs text-indigo-950">
                <div className="font-semibold uppercase tracking-[0.14em] text-indigo-700">Selected labels</div>
                <div className="mt-2 max-h-16 overflow-auto">{Object.entries(selectedEligibility.labelCounts).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-xs text-indigo-950">
                <div className="font-semibold uppercase tracking-[0.14em] text-indigo-700">Readiness</div>
                <div className="mt-2">{Object.entries(selectedEligibility.readiness).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-xs text-indigo-950">
                <div className="font-semibold uppercase tracking-[0.14em] text-indigo-700">Capture quality</div>
                <div className="mt-2">{Object.entries(selectedEligibility.captureQuality).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-xs text-indigo-950">
                <div className="font-semibold uppercase tracking-[0.14em] text-indigo-700">Label status</div>
                <div className="mt-2">{Object.entries(selectedEligibility.labelStatus).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'none'}</div>
              </div>
            </div>
            <div className="mt-3 max-h-52 space-y-2 overflow-auto">
              {sortedCaptures.map((capture, index) => (
                <div key={`${String(capture.source ?? 'source')}:${String(capture.capture_id)}:${index}`} className="grid gap-3 rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm md:grid-cols-[1.1fr_1fr_0.9fr]">
                  <span className="flex items-start gap-2">
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={selectedCaptureIds.includes(String(capture.capture_id))}
                      onChange={() => toggleCapture(String(capture.capture_id))}
                      aria-label={`Select capture ${String(capture.capture_id)}`}
                    />
                    <span>
                      <span className="block font-semibold text-slate-900">{String(capture.capture_id)}</span>
                      <span className="mt-1 block text-xs text-slate-500">{captureLabel(capture)}</span>
                    </span>
                  </span>
                  <span className="text-xs leading-5 text-slate-600">
                    <span className="block font-medium text-slate-800">{formatDateTime(capture.timestamp_utc ?? capture.created_at ?? capture.created_at_utc)}</span>
                    <span className="block">{Number(capture.duration_seconds ?? capture.duration_s ?? 0).toFixed(2)} s | {String(capture.session_id ?? 'session n/a')}</span>
                  </span>
                  <span className="text-xs leading-5 text-slate-600 md:text-right">
                    <span className="block font-medium text-slate-800">{modulationLabel(capture)}</span>
                    <span className="block">{formatHzShort(capture.center_frequency_hz)} | SR {formatHzShort(capture.sample_rate_hz)}</span>
                    <span className="block">QC {String(capture.capture_quality ?? capture.qc_status ?? 'unknown')} | {String(capture.training_readiness ?? 'readiness n/a')}</span>
                    <span className="block">{String(capture.label_status ?? 'label n/a')} | {String(capture.source ?? 'source n/a')}</span>
                  </span>
                </div>
              ))}
              {captures.length === 0 && <div className="text-sm text-slate-500">No captures visible to RF Experiment Lab yet.</div>}
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <button className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50" onClick={() => runAction('preview')} disabled={busy || (!datasetManifestPath && selectedCaptureIds.length === 0)}>
              <ScanSearch className="mr-2 inline h-4 w-4" />
              Preview, no training
            </button>
            <button className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={() => runAction('run')} disabled={busy || (!datasetManifestPath && selectedCaptureIds.length === 0)}>
              <Play className="mr-2 inline h-4 w-4" />
              Train and validate
            </button>
            <button className="rounded-full border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-50" onClick={() => runBenchmark(true)} disabled={busy || selectedRuns.length === 0}>
              <Save className="mr-2 inline h-4 w-4" />
              Export benchmark
            </button>
          </div>

          <div className="mt-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-800">Live and saved-capture prediction</div>
                <div className="mt-1 text-sm font-semibold text-slate-900">Prediction visibility for trained E1, E3 and E5 experiment results</div>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-700">
                  Use selected executed experiments as candidate models and persist the inference report with model_id, dataset_version, input_sample_id, timestamp, top-k, confidence, latency and agreement/disagreement.
                </p>
              </div>
              <div className="rounded-full border border-emerald-300 bg-white px-3 py-1 text-xs font-semibold text-emerald-900">
                models: {selectedRuns.length}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button className="rounded-full border border-emerald-300 bg-white px-4 py-2 text-sm font-semibold text-emerald-900 disabled:opacity-50" onClick={() => runPrediction('saved_capture')} disabled={busy || selectedRuns.length === 0}>
                Saved capture
              </button>
              <button className="rounded-full border border-emerald-300 bg-white px-4 py-2 text-sm font-semibold text-emerald-900 disabled:opacity-50" onClick={() => runPrediction('marker_region')} disabled={busy || selectedRuns.length === 0}>
                Marker 1 / Marker 2 region
              </button>
              <button className="rounded-full border border-emerald-300 bg-white px-4 py-2 text-sm font-semibold text-emerald-900 disabled:opacity-50" onClick={() => runPrediction('frozen_window')} disabled={busy || selectedRuns.length === 0}>
                Frozen window
              </button>
              <button className="rounded-full bg-emerald-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={() => runPrediction('live_context')} disabled={busy || selectedRuns.length === 0}>
                Live prediction overlay
              </button>
            </div>
            {prediction && (
              <div className="mt-4 grid gap-3 md:grid-cols-4">
                <Fact label="Top prediction" value={String(prediction.prediction_result?.top_prediction ?? 'unknown')} />
                <Fact label="Confidence" value={String(prediction.prediction_result?.confidence ?? 'n/a')} />
                <Fact label="Latency ms" value={String(prediction.prediction_result?.latency_ms ?? 'n/a')} />
                <Fact label="Agreement" value={prediction.prediction_result?.agreement?.disagreement ? 'disagreement' : 'agreement or single model'} />
              </div>
            )}
          </div>

          {message && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">{message}</div>}
        </div>
      </section>

      <section className="mt-5 grid gap-5 xl:grid-cols-[1fr_1fr]">
        <div className={card}>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            <GitCompare className="h-4 w-4" />
            Executed experiments
          </div>
          <div className="mt-4 overflow-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.12em] text-slate-500">
                <tr><th className="py-2">Experiment</th><th>Split</th><th>Macro F1</th><th>Path</th></tr>
              </thead>
              <tbody>
                {selectedRuns.slice(0, 10).map((run) => (
                  <tr key={String(run.experiment_id)} className="border-t border-slate-100">
                    <td className="py-2 font-medium text-slate-800">{String(run.experiment_type)}</td>
                    <td>{String(run.split_strategy ?? 'unknown')}</td>
                    <td>{String(run.metrics_summary?.macro_f1 ?? 'n/a')}</td>
                    <td className="max-w-[220px] truncate text-xs text-slate-500">{String(run.result_path ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className={card}>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            <BadgeCheck className="h-4 w-4" />
            Benchmark result
          </div>
          {benchmark ? (
            <div className="mt-4 space-y-3 text-sm text-slate-700">
              <Fact label="Benchmark" value={String(benchmark.benchmark_id)} />
              <Fact label="Best macro F1" value={`${benchmark.best_model_by_macro_f1?.model_type ?? 'n/a'} (${benchmark.best_model_by_macro_f1?.macro_f1 ?? 'n/a'})`} />
              <Fact label="Fastest" value={`${benchmark.fastest_model_by_inference_time_ms?.model_type ?? 'n/a'} (${benchmark.fastest_model_by_inference_time_ms?.inference_time_ms ?? 'n/a'} ms)`} />
              <Fact label="Dataset warning" value={String(Boolean(benchmark.warnings?.different_dataset_versions?.active))} />
              <Fact label="Split warning" value={String(Boolean(benchmark.warnings?.different_split_strategies?.active))} />
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
              Run a benchmark after at least one E1/E3/E5 experiment has been executed.
            </div>
          )}
        </div>
      </section>

      <section className="mt-5 grid gap-4 xl:grid-cols-5">
        {papers.map((paper) => (
          <article key={paper.experiment} className={card}>
            <FileJson className="h-5 w-5 text-slate-700" />
            <div className="mt-3 text-sm font-semibold text-slate-900">{paper.experiment}</div>
            <div className="mt-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Authors</div>
            <p className="mt-1 text-xs leading-5 text-slate-700">{paper.authors}</p>
            <div className="mt-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Paper / reference title</div>
            <p className="mt-1 text-xs leading-5 text-slate-700">{paper.title}</p>
            <div className="mt-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Adopted in this implementation</div>
            <p className="mt-1 text-xs leading-5 text-slate-600">{paper.adopted}</p>
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
              {paper.boundary}
            </div>
          </article>
        ))}
      </section>

      {lastResponse && (
        <section className="mt-5 rounded-2xl border border-slate-200 bg-slate-950 p-5 text-slate-100">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">
            <Route className="h-4 w-4" />
            Last structured response
          </div>
          <pre className="max-h-96 overflow-auto rounded-xl bg-black/40 p-4 text-xs leading-5">{JSON.stringify(lastResponse, null, 2)}</pre>
        </section>
      )}

      <section className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-5">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-1 h-5 w-5 text-amber-700" />
          <p className="text-sm leading-7 text-amber-950">
            Scientific rule: E1/E3/E5 are experimental comparators. A live spectrum overlay may show experiment readiness and best validated runs,
            but it must not claim live device identity unless a validated inference pipeline has been explicitly integrated.
          </p>
        </div>
      </section>
    </div>
  );
};

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2">
      <span className="text-slate-500">{label}</span>
      <span className="max-w-[65%] text-right font-medium text-slate-900">{value}</span>
    </div>
  );
}
