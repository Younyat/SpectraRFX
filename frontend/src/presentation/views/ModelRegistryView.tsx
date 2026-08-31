import React, { useEffect, useMemo, useState } from 'react';
import { Boxes, BrainCircuit, Cpu, FlaskConical, GitCompare, Layers3, RadioTower, ScanSearch } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { ModelArtifactSummary, TrainingDashboard } from '../../shared/types';
import { formatFileSize } from '../../shared/utils';

const api = new ApiService();

type JsonRecord = Record<string, unknown>;

const formatTimestamp = (value?: string | null) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const isRecord = (value: unknown): value is JsonRecord => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const formatMetric = (value: unknown) => {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4);
  }
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (isRecord(value)) return `${Object.keys(value).length} fields`;
  return String(value ?? 'n/a');
};

const formatBytesMetric = (value: unknown) => (typeof value === 'number' ? formatFileSize(value) : formatMetric(value));

const getNested = (value: unknown, path: string): unknown => {
  return path.split('.').reduce<unknown>((current, part) => (isRecord(current) ? current[part] : undefined), value);
};

const displayEntries = (value: unknown, limit = 14): Array<[string, string]> => {
  if (!isRecord(value)) return [];
  return Object.entries(value)
    .filter(([, entryValue]) => entryValue !== undefined && entryValue !== null && entryValue !== '')
    .slice(0, limit)
    .map(([key, entryValue]) => [key, formatMetric(entryValue)]);
};

const summarizeModelMetrics = (model: ModelArtifactSummary | null) => {
  const metrics = (model?.metrics ?? {}) as JsonRecord;
  return Object.entries(metrics).slice(0, 8);
};

const scientificModels = [
  {
    key: 'current_softmax',
    title: 'Current operational fingerprinting baseline',
    experimentId: 'current_baseline',
    family: 'Operational baseline',
    useCase: 'Operational closed-set prediction over curated fingerprinting captures. This is the current production path, not a new RF Experiment Lab run.',
    aiType: 'NumPy/softmax-style baseline and profile-based operational model.',
    representation: 'Current exported fingerprinting dataset.',
    datasetColumns: ['transmitter_id', 'session_id', 'dataset_split', 'sample_rate_hz', 'center_frequency_hz', 'qc_status'],
    splitStrategy: 'Current Training/Validation split from Dataset Builder.',
    papers: [
      'RF-Fingerprint-Lab-v6 project baseline - Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline. Adopted as the permanent explainable waterfall region baseline; not presented as physical deep-learning RFF.',
    ],
  },
  {
    key: 'rf_signal_understanding',
    title: 'RF Signal Understanding models',
    experimentId: 'rf_signal_understanding',
    family: 'Operational signal-understanding layer',
    useCase: 'Signal region detection and signal-family understanding over waterfall/time-frequency regions.',
    aiType: 'Morphological detector, MLP spectral classifier, waterfall classifier and bispectral verification where available.',
    representation: 'STFT waterfall, spectral features, reviewed regions.',
    datasetColumns: ['analysis_id', 'bbox_id', 'label', 'review_status', 'center_frequency_hz', 'occupied_bandwidth_hz', 'snr_db'],
    splitStrategy: 'RF Signal Understanding training queue split, typically session_id or capture_id.',
    papers: [
      'Lin et al. - A Radio Frequency Signal Recognition Method Based on Spectrogram. Adopted as time-frequency signal understanding context.',
      'Liu et al. - RF Fingerprint Recognition Based on Spectrum Waterfall Diagram. Adopted as waterfall-image RF recognition context.',
      'Ochando and Mejias - Simple Detection and Classification of Spectrogram RF Signals Using a Four-Layer Perceptron. Adopted as lightweight spectrogram classification context.',
      'Sivolenko et al. - Bispectrum-Based Signal Processing Using Waterfall Features. Adopted as future high-order feature context.',
    ],
  },
  {
    key: 'E1',
    title: 'Raw IQ CNN 1D',
    experimentId: 'E1',
    family: 'RF Experiment Lab',
    useCase: 'Closed-set physical transmitter identification from raw IQ windows.',
    aiType: 'CNN 1D over [2, N] I/Q windows.',
    representation: 'raw_iq',
    datasetColumns: ['capture_id', 'session_id', 'day_id', 'transmitter_id', 'sample_rate_hz', 'center_frequency_hz'],
    splitStrategy: 'session_disjoint by default; capture_disjoint/device_holdout supported where configured.',
    papers: [
      'Riyaz et al. - Deep Learning Convolutional Neural Networks for Radio Identification. Adopted as raw I/Q CNN fingerprinting context.',
      'Jian et al. - Deep Learning for RF Fingerprinting: A Massive Experimental Study. Adopted as large-scale RFF methodology and validation context.',
    ],
  },
  {
    key: 'E3',
    title: 'Spectrogram/Waterfall CNN 2D',
    experimentId: 'E3',
    family: 'RF Experiment Lab',
    useCase: 'Closed-set signal recognition or device fingerprinting from RF images.',
    aiType: 'simple CNN 2D, optional ResNet18, optional VGG11 over [1, H, W].',
    representation: 'spectrogram or waterfall',
    datasetColumns: ['capture_id', 'session_id', 'day_id', 'label_field', 'input_representation', 'image_height', 'image_width'],
    splitStrategy: 'session_disjoint by default; group-disjoint split stored in split_definition.json.',
    papers: [
      'Shen et al. - Radio Frequency Fingerprint Identification for LoRa Using Deep Learning. Adopted as spectrogram-based RFF context.',
      'Lin et al. - A Radio Frequency Signal Recognition Method Based on Spectrogram. Adopted as RF spectrogram recognition context.',
      'Liu et al. - RF Fingerprint Recognition Based on Spectrum Waterfall Diagram. Adopted as waterfall-image recognition context.',
      'Bremnes et al. - Classification of UAVs Utilizing Fixed Boundary Empirical Wavelet Sub-Bands of RF Fingerprints and Deep CNN. Adopted as RF-image/deep-CNN comparison context.',
    ],
  },
  {
    key: 'E5',
    title: 'Spectral Feature Baseline',
    experimentId: 'E5',
    family: 'RF Experiment Lab',
    useCase: 'Explainable classical ML baseline before deep learning.',
    aiType: 'PSD/spectral features with Logistic Regression, Random Forest, SVM RBF and KNN.',
    representation: 'fft_psd and PSD-derived feature vector.',
    datasetColumns: ['capture_id', 'label', 'mean_power', 'peak_power', 'occupied_bandwidth_hz', 'spectral_entropy', 'snr_db'],
    splitStrategy: 'session_disjoint by default; comparison uses same dataset and same split for all selected models.',
    papers: [
      'Kilic et al. - Drone Classification Using RF Signal Based Spectral Features. Adopted as spectral-feature baseline context.',
      'Nie et al. - UAV Detection and Identification Based on WiFi Signal and RF Fingerprint. Adopted as physical/spectral feature context.',
      'O Shea, Clancy and Ebeid - Practical Signal Detection and Classification in GNU Radio. Adopted as PSD, energy and cyclostationary signal-detection context.',
    ],
  },
];

const experimentTypesByKey: Record<string, string> = {
  E1: 'e1_raw_iq_cnn1d',
  E3: 'e3_spectrogram_cnn2d',
  E5: 'e5_spectral_feature_baseline',
};

export const ModelRegistryView: React.FC = () => {
  const [overview, setOverview] = useState<TrainingDashboard | null>(null);
  const [currentModel, setCurrentModel] = useState<ModelArtifactSummary | null>(null);
  const [models, setModels] = useState<ModelArtifactSummary[]>([]);
  const [experimentRuns, setExperimentRuns] = useState<JsonRecord[]>([]);
  const [rsuModels, setRsuModels] = useState<JsonRecord[]>([]);
  const [selectedModelKey, setSelectedModelKey] = useState('current_softmax');
  const [lastRefresh, setLastRefresh] = useState('');

  useEffect(() => {
    let cancelled = false;

    const refreshRegistry = async () => {
      try {
        const [overviewData, current, modelList, experimentList, signalModels] = await Promise.all([
          api.getModelOverview(),
          api.getCurrentModel().catch(() => null),
          api.getTrainingModels(),
          api.listRFExperimentRuns().catch(() => []),
          api.getRFSignalUnderstandingModels().catch(() => []),
        ]);
        if (cancelled) return;
        setOverview(overviewData);
        setCurrentModel(current);
        setModels(modelList);
        setExperimentRuns(experimentList);
        setRsuModels(signalModels);
        setLastRefresh(new Date().toISOString());
      } catch (error) {
        if (!cancelled) console.error('Failed to load model registry', error);
      }
    };

    refreshRegistry();
    const interval = window.setInterval(refreshRegistry, 5000);
    window.addEventListener('rfp-job-started', refreshRegistry);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('rfp-job-started', refreshRegistry);
    };
  }, []);

  const currentMetrics = useMemo(() => summarizeModelMetrics(currentModel), [currentModel]);
  const selectedScientificModel = scientificModels.find((item) => item.key === selectedModelKey) ?? scientificModels[0];
  const selectedExperimentRuns = experimentRuns.filter((run) => run.experiment_type === experimentTypesByKey[selectedModelKey]);
  const selectedRecordCount =
    selectedModelKey === 'current_softmax'
      ? models.length
      : selectedModelKey === 'rf_signal_understanding'
        ? rsuModels.length
        : selectedExperimentRuns.length;

  return (
    <div className="app-page p-6">
      <div className="mb-6">
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-700">Model Registry</div>
        <h1 className="mt-2 font-serif text-4xl" style={{ color: 'var(--app-text)' }}>
          Model inventory by family, purpose, provenance, and validation status
        </h1>
        <p className="mt-3 max-w-5xl text-sm leading-7 app-muted-text">
          The registry is split by model family so the current operational baseline is not mixed with RF Experiment Lab
          experiments. Each card shows the use case, adopted technique, dataset fields, split strategy, papers, artifacts and
          metrics as interpreted fields instead of raw JSON dumps.
        </p>
        <p className="mt-2 text-sm app-muted-text">Last UI refresh: {formatTimestamp(lastRefresh)}</p>
      </div>

      <div className="mb-5 grid gap-5 xl:grid-cols-[0.34fr_0.66fr]">
        <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">
            <Layers3 className="h-4 w-4" />
            Model menu
          </div>
          <div className="space-y-2">
            {scientificModels.map((model) => {
              const active = selectedModelKey === model.key;
              const Icon =
                model.key === 'current_softmax'
                  ? Boxes
                  : model.key === 'rf_signal_understanding'
                    ? ScanSearch
                    : model.key === 'E5'
                      ? GitCompare
                      : model.key === 'E1'
                        ? BrainCircuit
                        : FlaskConical;
              return (
                <button
                  key={model.key}
                  onClick={() => setSelectedModelKey(model.key)}
                  className={`w-full rounded-2xl border p-4 text-left transition ${
                    active ? 'border-violet-800 bg-violet-950 text-white' : 'border-slate-200 bg-slate-50 text-slate-900 hover:bg-white'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <Icon className="mt-0.5 h-5 w-5" />
                    <div>
                      <div className="font-semibold">
                        {model.experimentId} - {model.title}
                      </div>
                      <div className="mt-1 text-xs opacity-75">{model.family}</div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Scientific model card</div>
              <h2 className="mt-2 text-2xl font-semibold" style={{ color: 'var(--app-text)' }}>
                {selectedScientificModel.experimentId} - {selectedScientificModel.title}
              </h2>
              <p className="mt-3 max-w-4xl text-sm leading-7 app-muted-text">{selectedScientificModel.useCase}</p>
            </div>
            <div className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] app-muted-text">
              {selectedRecordCount} records in this family
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <InfoBlock icon={<Cpu className="h-4 w-4" />} label="AI type" value={selectedScientificModel.aiType} />
            <InfoBlock icon={<RadioTower className="h-4 w-4" />} label="Input representation" value={selectedScientificModel.representation} />
            <InfoBlock icon={<GitCompare className="h-4 w-4" />} label="Split strategy" value={selectedScientificModel.splitStrategy} />
            <InfoBlock icon={<Boxes className="h-4 w-4" />} label="Dataset columns" value={selectedScientificModel.datasetColumns.join(', ')} />
          </div>

          <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">Papers / scientific traceability</div>
            <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
              {selectedScientificModel.papers.map((paper) => (
                <div key={paper}>- {paper}</div>
              ))}
            </div>
          </div>
        </section>
      </div>

      {selectedModelKey === 'current_softmax' && (
        <OperationalModelPanel
          overview={overview}
          currentModel={currentModel}
          currentMetrics={currentMetrics}
          models={models}
        />
      )}

      {selectedModelKey === 'rf_signal_understanding' && <RFSignalUnderstandingPanel models={rsuModels} />}

      {['E1', 'E3', 'E5'].includes(selectedModelKey) && (
        <ExperimentRunPanel modelKey={selectedModelKey} title={selectedScientificModel.title} runs={selectedExperimentRuns} />
      )}
    </div>
  );
};

function OperationalModelPanel({
  overview,
  currentModel,
  currentMetrics,
  models,
}: {
  overview: TrainingDashboard | null;
  currentModel: ModelArtifactSummary | null;
  currentMetrics: Array<[string, unknown]>;
  models: ModelArtifactSummary[];
}) {
  const currentArtifactInventory = overview?.current_model.file_inventory ?? [];
  const latestSnapshots = overview?.retraining.snapshots?.slice(-8).reverse() ?? [];
  const latestValidation = overview?.validation_reports?.slice(-3).reverse() ?? [];
  const datasetManifest = overview?.current_model.dataset_manifest ?? {};
  const trainConfig = overview?.current_model.train_config ?? {};
  const labelMap = overview?.current_model.label_map ?? {};

  return (
    <>
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        {[
          ['Operational model directory', formatFileSize(overview?.filesystem.model_dir_size_bytes ?? 0)],
          ['Train records', overview?.dataset.records ?? 0],
          ['Devices in model', overview?.dataset.devices ?? 0],
          ['Retraining snapshots', overview?.retraining.snapshot_count ?? 0],
        ].map(([label, value]) => (
          <div key={String(label)} className="app-surface-strong rounded-[1.5rem] p-5">
            <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{label}</div>
            <div className="mt-3 text-3xl font-semibold" style={{ color: 'var(--app-text)' }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="space-y-5">
          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Operational baseline model card</div>
                <div className="mt-2 text-2xl font-semibold" style={{ color: 'var(--app-text)' }}>
                  {String(currentModel?.version ?? 'current working model')}
                </div>
              </div>
              <div className="text-right text-xs app-muted-text">
                <div>modified: {formatTimestamp(overview?.current_model.modified_at_utc)}</div>
                <div>path exists: {overview?.current_model.exists ? 'yes' : 'no'}</div>
                <div>best model size: {formatFileSize(overview?.current_model.size_bytes ?? 0)}</div>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <MetricCard title="Operational readiness" entries={[
                ['Model file', overview?.prediction_readiness.has_model_file ? 'available' : 'missing'],
                ['Enrollment profiles', overview?.prediction_readiness.has_profiles ? 'available' : 'missing'],
                ['Dataset manifest', overview?.prediction_readiness.has_manifest ? 'available' : 'missing'],
                ['Validation evidence', overview?.prediction_readiness.has_validation ? 'available' : 'missing'],
              ]} />
              <MetricCard title="Training performance" entries={[
                ['Best test accuracy', (overview?.training.best_test_acc ?? 0).toFixed(4)],
                ['Last test accuracy', (overview?.training.last_test_acc ?? 0).toFixed(4)],
                ['Last train accuracy', (overview?.training.last_train_acc ?? 0).toFixed(4)],
                ['Best epoch', String(overview?.training.best_epoch ?? 'n/a')],
              ]} />
              <MetricCard title="Dataset provenance" entries={[
                ['Records', String(overview?.dataset.records ?? 0)],
                ['Devices', String(overview?.dataset.devices ?? 0)],
                ['Sessions', String(overview?.dataset.sessions ?? 0)],
                ['Labelled devices', String(overview?.training.labeled_devices ?? 0)],
              ]} />
              <MetricCard title="Filesystem footprint" entries={[
                ['Train dataset', formatFileSize(overview?.filesystem.train_dataset_size_bytes ?? 0)],
                ['Validation dataset', formatFileSize(overview?.filesystem.val_dataset_size_bytes ?? 0)],
                ['Predict dataset', formatFileSize(overview?.filesystem.predict_dataset_size_bytes ?? 0)],
                ['Model directory', formatFileSize(overview?.filesystem.model_dir_size_bytes ?? 0)],
              ]} />
            </div>

            <div className="mt-4">
              <div className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">Primary registered metrics</div>
              <div className="grid gap-3 md:grid-cols-2">
                {currentMetrics.map(([key, value]) => (
                  <div key={key} className="app-surface-muted rounded-2xl p-4">
                    <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{key}</div>
                    <div className="mt-2 text-sm font-semibold" style={{ color: 'var(--app-text)' }}>
                      {formatMetric(value)}
                    </div>
                  </div>
                ))}
                {currentMetrics.length === 0 && <div className="text-sm app-muted-text">No extra model metrics registered.</div>}
              </div>
            </div>
          </div>

          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Artifact inventory</div>
            <ArtifactList artifacts={currentArtifactInventory} />
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <ObjectSummaryCard title="Training configuration" data={trainConfig} />
            <ObjectSummaryCard title="Dataset manifest" data={datasetManifest} secondaryTitle="Label map" secondaryData={labelMap} />
          </div>
        </section>

        <section className="space-y-5">
          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Retraining lineage</div>
            <RecordList records={latestSnapshots} emptyLabel="No retraining snapshots recorded yet." titleKeyCandidates={['version', 'version_id', 'snapshot_id']} />
          </div>

          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Validation evidence</div>
            <RecordList records={latestValidation} emptyLabel="No validation reports stored yet." titlePrefix="Validation report" />
          </div>

          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Registered operational model versions</div>
            <RecordList records={models as JsonRecord[]} emptyLabel="No model versions registered." titleKeyCandidates={['version', 'model_id']} />
          </div>
        </section>
      </div>
    </>
  );
}

function RFSignalUnderstandingPanel({ models }: { models: JsonRecord[] }) {
  return (
    <section className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">RF Signal Understanding model inventory</div>
          <p className="mt-2 max-w-4xl text-sm leading-7 app-muted-text">
            These records belong to the signal-understanding layer: region classifiers, spectral/waterfall classifiers and
            reviewed training queues. They are intentionally separate from fingerprinting experiment models.
          </p>
        </div>
        <div className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] app-muted-text">
          {models.length} model records
        </div>
      </div>
      <RecordList
        records={models}
        emptyLabel="No RF Signal Understanding model records were returned by the backend."
        titleKeyCandidates={['model_id', 'name', 'version', 'classifier_name']}
      />
    </section>
  );
}

function ExperimentRunPanel({ modelKey, title, runs }: { modelKey: string; title: string; runs: JsonRecord[] }) {
  const sortedRuns = [...runs].sort((a, b) => String(b.created_at ?? b.created_at_utc ?? '').localeCompare(String(a.created_at ?? a.created_at_utc ?? '')));

  return (
    <section className="space-y-5">
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        {[
          ['Executed runs', sortedRuns.length],
          ['Best macro F1', bestMetric(sortedRuns, 'macro_f1')],
          ['Best balanced accuracy', bestMetric(sortedRuns, 'balanced_accuracy')],
          ['Smallest model', smallestModelSize(sortedRuns)],
        ].map(([label, value]) => (
          <div key={String(label)} className="app-surface-strong rounded-[1.5rem] p-5">
            <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{label}</div>
            <div className="mt-3 text-2xl font-semibold" style={{ color: 'var(--app-text)' }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">{modelKey} experiment runs</div>
            <h2 className="mt-2 text-2xl font-semibold" style={{ color: 'var(--app-text)' }}>
              {title}
            </h2>
            <p className="mt-2 max-w-4xl text-sm leading-7 app-muted-text">
              Runs shown here come from RF Experiment Lab result packages. They are comparable through the benchmark layer and
              do not reuse the old operational model card.
            </p>
          </div>
        </div>

        {sortedRuns.length > 0 ? (
          <>
            <div className="mt-5 overflow-auto rounded-2xl border border-slate-200">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="bg-slate-100 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Experiment</th>
                    <th>Model type</th>
                    <th>Representation</th>
                    <th>Dataset</th>
                    <th>Split</th>
                    <th>Accuracy</th>
                    <th>Macro F1</th>
                    <th>Inference</th>
                    <th>Size</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRuns.map((run) => {
                    const metrics = (run.metrics_summary ?? {}) as JsonRecord;
                    return (
                      <tr key={String(run.experiment_id ?? run.run_id ?? run.result_path)} className="border-t border-slate-100">
                        <td className="px-3 py-2 font-medium">{String(run.experiment_id ?? run.run_id ?? 'unknown')}</td>
                        <td>{String(run.model_type ?? run.technique_name ?? 'n/a')}</td>
                        <td>{String(run.input_representation ?? 'n/a')}</td>
                        <td>{String(run.dataset_version ?? 'unknown')}</td>
                        <td>{String(run.split_strategy ?? 'unknown')}</td>
                        <td>{formatMetric(metrics.accuracy)}</td>
                        <td>{formatMetric(metrics.macro_f1)}</td>
                        <td>{formatMetric(metrics.inference_time_ms)} ms</td>
                        <td>{formatBytesMetric(metrics.model_size_bytes)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              {sortedRuns.slice(0, 6).map((run) => (
                <ExperimentRunCard key={String(run.experiment_id ?? run.run_id ?? run.result_path)} run={run} />
              ))}
            </div>
          </>
        ) : (
          <div className="mt-5 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm app-muted-text">
            No executed {modelKey} runs were found yet. Create one from RF Experiment Lab, then return here to inspect its metrics,
            files and scientific traceability.
          </div>
        )}
      </div>
    </section>
  );
}

function ExperimentRunCard({ run }: { run: JsonRecord }) {
  const metrics = (run.metrics_summary ?? {}) as JsonRecord;
  return (
    <div className="app-surface-muted rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-semibold" style={{ color: 'var(--app-text)' }}>
            {String(run.experiment_id ?? run.run_id ?? 'experiment')}
          </div>
          <div className="mt-1 text-xs app-muted-text">{String(run.technique_name ?? run.experiment_type ?? 'RF Experiment Lab')}</div>
        </div>
        <div className="rounded-full border border-slate-300 px-3 py-1 text-xs app-muted-text">{String(run.status ?? 'recorded')}</div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <MiniField label="Model" value={String(run.model_type ?? run.technique_name ?? 'n/a')} />
        <MiniField label="Dataset" value={String(run.dataset_version ?? 'unknown')} />
        <MiniField label="Split" value={String(run.split_strategy ?? 'unknown')} />
        <MiniField label="Representation" value={String(run.input_representation ?? 'n/a')} />
        <MiniField label="Macro F1" value={formatMetric(metrics.macro_f1)} />
        <MiniField label="Balanced acc." value={formatMetric(metrics.balanced_accuracy)} />
        <MiniField label="Inference" value={`${formatMetric(metrics.inference_time_ms)} ms`} />
        <MiniField label="Model size" value={formatBytesMetric(metrics.model_size_bytes)} />
      </div>
      <div className="mt-4 rounded-xl border border-slate-200 bg-white/70 p-3">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] app-muted-text">Result package</div>
        <div className="mt-2 break-all text-xs app-muted-text">{String(run.result_path ?? 'not available')}</div>
      </div>
    </div>
  );
}

function InfoBlock({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="app-surface-muted rounded-2xl p-4">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">
        {icon}
        {label}
      </div>
      <div className="mt-3 text-sm leading-6" style={{ color: 'var(--app-text)' }}>
        {value}
      </div>
    </div>
  );
}

function MetricCard({ title, entries }: { title: string; entries: Array<[string, string]> }) {
  return (
    <div className="app-surface-muted rounded-2xl p-4">
      <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{title}</div>
      <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
        {entries.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4">
            <span className="app-muted-text">{label}</span>
            <span className="text-right font-medium">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ObjectSummaryCard({
  title,
  data,
  secondaryTitle,
  secondaryData,
}: {
  title: string;
  data: JsonRecord;
  secondaryTitle?: string;
  secondaryData?: JsonRecord;
}) {
  return (
    <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
      <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">{title}</div>
      <KeyValueGrid data={data} emptyLabel={`No ${title.toLowerCase()} available.`} />
      {secondaryTitle && (
        <div className="mt-5 border-t border-slate-200 pt-4">
          <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">{secondaryTitle}</div>
          <KeyValueGrid data={secondaryData ?? {}} emptyLabel={`No ${secondaryTitle.toLowerCase()} available.`} />
        </div>
      )}
    </div>
  );
}

function KeyValueGrid({ data, emptyLabel }: { data: JsonRecord; emptyLabel: string }) {
  const entries = displayEntries(data);
  if (entries.length === 0) return <div className="mt-4 text-sm app-muted-text">{emptyLabel}</div>;
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <MiniField key={key} label={key} value={value} />
      ))}
    </div>
  );
}

function MiniField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/70 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] app-muted-text">{label.replace(/_/g, ' ')}</div>
      <div className="mt-1 break-words text-sm font-medium" style={{ color: 'var(--app-text)' }}>
        {value}
      </div>
    </div>
  );
}

function ArtifactList({ artifacts }: { artifacts: Array<{ name: string; path: string; size_bytes: number; modified_at_utc?: string | null }> }) {
  return (
    <div className="mt-4 space-y-3">
      {artifacts.map((item) => (
        <div key={item.path} className="app-surface-muted rounded-2xl p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold" style={{ color: 'var(--app-text)' }}>
                {item.name}
              </div>
              <div className="mt-1 break-all text-xs app-muted-text">{item.path}</div>
            </div>
            <div className="text-right text-xs app-muted-text">
              <div>{formatFileSize(item.size_bytes)}</div>
              <div>{formatTimestamp(item.modified_at_utc)}</div>
            </div>
          </div>
        </div>
      ))}
      {artifacts.length === 0 && <div className="text-sm app-muted-text">No artifact inventory available.</div>}
    </div>
  );
}

function RecordList({
  records,
  emptyLabel,
  titleKeyCandidates = [],
  titlePrefix = 'Record',
}: {
  records: JsonRecord[];
  emptyLabel: string;
  titleKeyCandidates?: string[];
  titlePrefix?: string;
}) {
  return (
    <div className="mt-4 space-y-3">
      {records.map((record, index) => {
        const titleValue = titleKeyCandidates.map((key) => record[key]).find(Boolean);
        const metrics = isRecord(record.metrics) ? record.metrics : isRecord(record.metrics_summary) ? record.metrics_summary : undefined;
        return (
          <div key={`${String(titleValue ?? titlePrefix)}-${index}`} className="app-surface-muted rounded-2xl p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="font-semibold" style={{ color: 'var(--app-text)' }}>
                  {String(titleValue ?? `${titlePrefix} ${index + 1}`)}
                </div>
                <div className="mt-1 text-xs app-muted-text">{formatTimestamp(String(record.created_at_utc ?? record.created_at ?? ''))}</div>
              </div>
              {metrics && (
                <div className="text-right text-xs app-muted-text">
                  {Object.entries(metrics).slice(0, 3).map(([key, value]) => (
                    <div key={key}>
                      {key}: {formatMetric(value)}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <KeyValueGrid data={record} emptyLabel="No structured fields available." />
          </div>
        );
      })}
      {records.length === 0 && <div className="text-sm app-muted-text">{emptyLabel}</div>}
    </div>
  );
}

function bestMetric(runs: JsonRecord[], metric: string) {
  const values = runs
    .map((run) => getNested(run, `metrics_summary.${metric}`))
    .filter((value): value is number => typeof value === 'number');
  return values.length ? Math.max(...values).toFixed(4) : 'n/a';
}

function smallestModelSize(runs: JsonRecord[]) {
  const values = runs
    .map((run) => getNested(run, 'metrics_summary.model_size_bytes'))
    .filter((value): value is number => typeof value === 'number' && value > 0);
  return values.length ? formatFileSize(Math.min(...values)) : 'n/a';
}
