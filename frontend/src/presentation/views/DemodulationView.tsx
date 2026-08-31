import React, { useEffect, useMemo, useState } from 'react';
import { Play, RotateCcw, Radio, Download, Trash2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { ApiService } from '../../app/services/ApiService';
import { useMarkers } from '../../app/store/AppStore';
import { DEMODULATION_MODES } from '../../shared/constants';
import { DemodulationResult, FingerprintingCaptureRecord } from '../../shared/types';
import { formatFrequency } from '../../shared/utils';
import { cn } from '../../shared/utils';

const apiService = new ApiService();
const markerBandpassStorageKey = 'spectrum-view-marker-bandpass-settings';

const loadMarkerBandpassSettings = () => {
  try {
    const raw = window.localStorage.getItem(markerBandpassStorageKey);
    if (!raw) return { enabled: false, attenuationDb: 60 };
    const parsed = JSON.parse(raw) as { enabled?: boolean; attenuation_db?: number };
    return {
      enabled: Boolean(parsed.enabled),
      attenuationDb: Number.isFinite(parsed.attenuation_db) ? Number(parsed.attenuation_db) : 60,
    };
  } catch {
    return { enabled: false, attenuationDb: 60 };
  }
};

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

const getResultTime = (result: DemodulationResult | Record<string, any>) => {
  const data = result as Record<string, any>;
  const value = data.generated_at_utc || data.timestamp_utc || data.created_at || data.metadata_created_at;
  if (!value) return 'time n/a';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
};

const isPacketLikeResult = (result: DemodulationResult | Record<string, any>, decodedPackets?: Record<string, any> | null) => {
  const data = result as Record<string, any>;
  const protocol = String(data.protocol ?? data.signal_type ?? decodedPackets?.protocol ?? '').toLowerCase();
  const pipeline = String(data.pipeline ?? data.demodulation_pipeline ?? data.pipeline_name ?? '').toLowerCase();
  return protocol.includes('bluetooth')
    || protocol.includes('ble')
    || pipeline.includes('ble')
    || ['wifi', '80211', 'ieee802154', 'zigbee', 'adsb', 'lora'].some((name) => protocol.includes(name) || pipeline.includes(name));
};

const AUDIO_MODES = new Set(['wfm', 'wfm_broadcast', 'nfm', 'fm', 'am']);

const isAudioResult = (result: Record<string, any>) => {
  const mode = String(result.mode ?? result.pipeline ?? result.demodulation_pipeline ?? '').toLowerCase();
  const pipeline = String(result.pipeline ?? result.demodulation_pipeline ?? '').toLowerCase();
  return AUDIO_MODES.has(mode) || [...AUDIO_MODES].some((m) => pipeline.includes(m));
};

type DemodulationPipeline = {
  id: string;
  category?: string;
  family: string;
  label: string;
  status: string;
  outputs: string[];
};

type DecodedPacket = {
  packet_index?: number;
  timestamp_seconds?: number;
  channel?: number;
  access_address?: string;
  crc_valid?: boolean;
  pdu_type?: string;
  advertiser_address?: string;
  payload_hex?: string;
  payload_fields?: Record<string, unknown>;
  crc_computed?: string;
  crc_received?: string;
  trust_level?: string;
  rssi_estimate_db?: number;
  snr_estimate_db?: number;
};

const captureToDemodPayload = (
  capture: FingerprintingCaptureRecord,
  pipeline: string,
  manualSignalType: string,
  decoderMode: string,
) => ({
  dataset_id: capture.capture_config.dataset_destination || capture.dataset_split || 'dataset_builder',
  sample_id: capture.capture_id,
  file_path: capture.capture_config.output_path,
  file_format: capture.capture_config.file_format,
  datatype: capture.capture_config.sample_dtype,
  sample_rate_hz: capture.capture_config.sample_rate_hz,
  center_frequency_hz: capture.capture_config.center_frequency_hz,
  bandwidth_hz: capture.capture_config.effective_bandwidth_hz,
  capture_duration: capture.capture_config.capture_duration_s,
  source_dataset: 'dataset_builder',
  signal_type: manualSignalType || capture.transmitter.signal_type || capture.transmitter.modulation_class || capture.transmitter.transmitter_class,
  device_profile: capture.transmitter.transmitter_id || capture.transmitter.profile_key || capture.capture_config.sdr_model,
  pipeline: pipeline === 'auto' ? undefined : pipeline,
  manual_signal_type: manualSignalType || undefined,
  decoder_mode: pipeline === 'wifi_80211' ? decoderMode : undefined,
  hardware_center_frequency_hz: capture.capture_config.center_frequency_hz,
  channel_center_frequency_hz: capture.capture_config.center_frequency_hz,
  channel_width_hz: capture.capture_config.effective_bandwidth_hz,
});

const outputFilename = (value?: string | null) => {
  if (!value) return null;
  const parts = String(value).split(/[\\/]/);
  return parts[parts.length - 1] || null;
};

const formatRfCenterFrequency = (hz: number | null | undefined): string => {
  if (!Number.isFinite(hz)) return 'n/a';
  const safeHz = Number(hz);
  if (Math.abs(safeHz) >= 1e9) return `${(safeHz / 1e9).toFixed(6)} GHz`;
  if (Math.abs(safeHz) >= 1e6) return `${(safeHz / 1e6).toFixed(3)} MHz`;
  return formatFrequency(safeHz);
};

type LiveBandDetection = {
  pipeline: string;
  label: string;
  detail: string;
  confidence: 'high' | 'medium';
};

const detectLiveBandProfiles = (band: { center: number; bandwidth: number } | null): LiveBandDetection[] => {
  if (!band) return [];
  const centerMhz = band.center / 1_000_000;
  const bandwidthMhz = band.bandwidth / 1_000_000;
  const detections: LiveBandDetection[] = [];

  if (bandwidthMhz >= 10 && centerMhz >= 2401 && centerMhz <= 2495) {
    const channel = Math.round((centerMhz - 2407) / 5);
    detections.push({
      pipeline: 'wifi_80211',
      label: `Wi-Fi channel-profile match: 2.4 GHz CH${channel}`,
      detail: 'Suggested IEEE 802.11 decoder based on channel geometry only; Wi-Fi is not confirmed without a valid preamble and PHY header.',
      confidence: 'medium',
    });
  }
  if (bandwidthMhz >= 10 && centerMhz >= 5000 && centerMhz <= 5900) {
    const channel = Math.round((centerMhz - 5000) / 5);
    detections.push({
      pipeline: 'wifi_80211',
      label: `Wi-Fi channel-profile match: 5 GHz CH${channel}`,
      detail: 'Suggested IEEE 802.11 decoder based on channel geometry only; Wi-Fi is not confirmed without a valid preamble and PHY header.',
      confidence: 'medium',
    });
  }

  const bleChannels = [
    { channel: 37, frequencyMhz: 2402 },
    { channel: 38, frequencyMhz: 2426 },
    { channel: 39, frequencyMhz: 2480 },
  ];
  for (const ble of bleChannels) {
    if (bandwidthMhz <= 4 && Math.abs(centerMhz - ble.frequencyMhz) <= 2) {
      detections.push({
        pipeline: 'ble_advertising',
        label: `BLE advertising CH${ble.channel}`,
        detail: 'Use the BLE advertising pipeline for Access Address and CRC validation.',
        confidence: 'high',
      });
    }
  }

  if (bandwidthMhz <= 5 && centerMhz >= 2405 && centerMhz <= 2480) {
    const channel = Math.round((centerMhz - 2405) / 5) + 11;
    if (channel >= 11 && channel <= 26) {
      detections.push({
        pipeline: 'zigbee_ieee802154',
        label: `Zigbee / IEEE 802.15.4 CH${channel}`,
        detail: 'Use the Zigbee pipeline for O-QPSK DSSS frame recovery.',
        confidence: 'high',
      });
    }
  }

  if (centerMhz >= 88 && centerMhz <= 108 && bandwidthMhz >= 0.15) {
    detections.push({
      pipeline: 'wfm',
      label: 'WFM broadcast band',
      detail: 'Use WFM when the marker band covers a broadcast FM channel.',
      confidence: 'medium',
    });
  }

  if (centerMhz >= 445.9 && centerMhz <= 446.2 && bandwidthMhz <= 0.1) {
    detections.push({
      pipeline: 'nfm',
      label: 'PMR446 NFM channel',
      detail: 'PMR446 walkie-talkie band (446 MHz, 12.5 kHz channels, ±2.5 kHz deviation). Use NFM demodulation.',
      confidence: 'high',
    });
  }

  if (bandwidthMhz <= 0.05 && (
    (centerMhz >= 136 && centerMhz <= 174) ||
    (centerMhz >= 400 && centerMhz <= 512)
  )) {
    detections.push({
      pipeline: 'nfm',
      label: 'VHF/UHF land mobile NFM',
      detail: 'Narrowband VHF/UHF channel. Use NFM for land mobile radio (PMR, public safety, aviation).',
      confidence: 'medium',
    });
  }
  if (Math.abs(centerMhz - 433.92) <= 1.5 || Math.abs(centerMhz - 315) <= 1.5 || Math.abs(centerMhz - 868.3) <= 2) {
    detections.push({
      pipeline: 'fsk_remote_decoder',
      label: 'FSK remote / ISM sensor band',
      detail: 'Use the FSK remote pipeline when OOK diagnostics show two-tone FSK candidates or no symbol-level OOK transitions.',
      confidence: 'medium',
    });
    detections.push({
      pipeline: 'ook_433_remote',
      label: 'OOK remote / ISM sensor band',
      detail: 'Use the OOK remote pipeline for 315/433/868 MHz burst remotes and simple ASK/OOK sensors.',
      confidence: 'medium',
    });
  }
  if (centerMhz >= 863 && centerMhz <= 870 && bandwidthMhz <= 1) {
    detections.push({
      pipeline: 'lora_css',
      label: 'LoRa 868 MHz candidate',
      detail: 'Use LoRa CSS for narrowband LoRa packet captures.',
      confidence: 'medium',
    });
  }

  return detections;
};

export const DemodulationView: React.FC = () => {
  const markers = useMarkers();
  const [searchParams] = useSearchParams();
  const [workMode, setWorkMode] = useState<'live' | 'dataset'>(searchParams.get('capture_id') ? 'dataset' : 'live');
  const [mode, setMode] = useState('fm');
  const [durationSeconds, setDurationSeconds] = useState('5');
  const [isRunning, setIsRunning] = useState(false);
  const [isDatasetRunning, setIsDatasetRunning] = useState(false);
  const [isBleTestRunning, setIsBleTestRunning] = useState(false);
  const [isWifi5GhzTestRunning, setIsWifi5GhzTestRunning] = useState(false);
  const [bleChannelTest, setBleChannelTest] = useState<Record<string, any> | null>(null);
  const [wifi5GhzChannelTest, setWifi5GhzChannelTest] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<DemodulationResult[]>([]);
  const [markerBandpass, setMarkerBandpass] = useState(() => loadMarkerBandpassSettings());
  const [datasetCaptures, setDatasetCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [selectedCaptureId, setSelectedCaptureId] = useState('');
  const [pipelines, setPipelines] = useState<DemodulationPipeline[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState('auto');
  const [manualSignalType, setManualSignalType] = useState('');
  const [wifiDecoderMode, setWifiDecoderMode] = useState('auto');
  const [wifiJobProgress, setWifiJobProgress] = useState<string | null>(null);

  const selectedBand = useMemo(() => {
    if (markers.length < 2) return null;
    const [first, second] = markers;
    const start = Math.min(first.frequency, second.frequency);
    const stop = Math.max(first.frequency, second.frequency);
    return {
      start,
      stop,
      center: start + (stop - start) / 2,
      bandwidth: stop - start,
      first,
      second,
    };
  }, [markers]);

  const iotPipelines = useMemo(
    () => pipelines.filter((pipeline) => ['IoT Demodulation Pipelines', 'Wireless LAN decoders'].includes(pipeline.category || '')),
    [pipelines],
  );

  const liveDetections = useMemo(() => detectLiveBandProfiles(selectedBand), [selectedBand]);
  const availableLiveModes = useMemo(
    () => new Set([...DEMODULATION_MODES.map((item) => item.value), ...pipelines.map((pipeline) => pipeline.id)]),
    [pipelines],
  );
  const liveSuggestion = useMemo(
    () => liveDetections.find((detection) => availableLiveModes.has(detection.pipeline)) ?? liveDetections[0] ?? null,
    [liveDetections, availableLiveModes],
  );
  const hasSuggestedPipeline = Boolean(liveSuggestion && availableLiveModes.has(liveSuggestion.pipeline));

  const pipelinesByCategory = useMemo(() => {
    const grouped: Record<string, DemodulationPipeline[]> = {};
    for (const pipeline of pipelines) {
      const category = pipeline.category || 'Other pipelines';
      grouped[category] = [...(grouped[category] ?? []), pipeline];
    }
    return grouped;
  }, [pipelines]);

  const loadResults = async () => {
    const data = await apiService.getDemodulationResults();
    setResults(data);
  };

  const loadDatasetInputs = async () => {
    const [captures, pipelineList] = await Promise.all([
      apiService.getFingerprintingCaptures(),
      apiService.getDemodulationPipelines(),
    ]);
    setDatasetCaptures(captures);
    setPipelines(pipelineList as DemodulationPipeline[]);
    const queryCaptureId = searchParams.get('capture_id');
    if (queryCaptureId && captures.some((capture) => capture.capture_id === queryCaptureId)) {
      setSelectedCaptureId(queryCaptureId);
      setWorkMode('dataset');
    } else if (!selectedCaptureId && captures.length > 0) {
      setSelectedCaptureId(captures[0].capture_id);
    }
  };

  useEffect(() => {
    loadResults().catch(() => undefined);
  }, []);

  useEffect(() => {
    loadDatasetInputs().catch(() => undefined);
  }, [searchParams]);

  useEffect(() => {
    const syncFilter = () => setMarkerBandpass(loadMarkerBandpassSettings());
    syncFilter();
    window.addEventListener('focus', syncFilter);
    window.addEventListener('storage', syncFilter);
    return () => {
      window.removeEventListener('focus', syncFilter);
      window.removeEventListener('storage', syncFilter);
    };
  }, []);

  const applyDemodulation = async () => {
    if (!selectedBand) {
      setError('Create at least two markers first. M1 and M2 define the demodulation band.');
      return;
    }

    const duration = Number(durationSeconds);
    if (!Number.isFinite(duration) || duration <= 0 || duration > 60) {
      setError('Duration must be between 0 and 60 seconds.');
      return;
    }

    setError(null);
    setIsRunning(true);
    try {
      const result = await apiService.demodulateMarkerBand({
        startFrequencyHz: selectedBand.start,
        stopFrequencyHz: selectedBand.stop,
        mode,
        durationSeconds: duration,
        applyBandpassFilter: markerBandpass.enabled,
        filterStopbandAttenuationDb: markerBandpass.attenuationDb,
      });
      setResults((current) => [result, ...current]);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsRunning(false);
    }
  };

  const selectedCapture = useMemo(
    () => datasetCaptures.find((capture) => capture.capture_id === selectedCaptureId) ?? null,
    [datasetCaptures, selectedCaptureId],
  );

  // Wi-Fi decoding runs a real GNU Radio subprocess that can take much longer than
  // the other (fast, in-process) pipelines, and demodulate_dataset_capture runs
  // synchronously inside the request handler -- calling it directly for wifi_80211
  // would block the whole backend event loop (freezing spectrum/waterfall polling
  // for every other view) for the duration of the decode. Route wifi_80211 through
  // the same background-job endpoints Capture Lab uses instead, so this stays the
  // one reusable Wi-Fi decode path across the platform.
  const pollWifiJob = async (jobId: string): Promise<Record<string, any>> => {
    for (;;) {
      const job = await apiService.getWifiDemodulationJobStatus(jobId);
      if (job.status === 'done') return job.result || {};
      if (job.status === 'error') throw new Error(job.message || job.error || 'Wi-Fi demodulation job failed.');
      setWifiJobProgress(job.message || 'Running worker...');
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  };

  const applyDatasetDemodulation = async () => {
    if (!selectedCapture) {
      setError('Select a Dataset Builder capture first.');
      return;
    }
    setError(null);
    setIsDatasetRunning(true);
    setWifiJobProgress(null);
    const payload = captureToDemodPayload(selectedCapture, selectedPipeline, manualSignalType, wifiDecoderMode);
    try {
      let result: DemodulationResult;
      if (selectedPipeline === 'wifi_80211') {
        const { job_id: jobId } = await apiService.startWifiDemodulationJob(payload);
        setWifiJobProgress('Starting worker...');
        result = (await pollWifiJob(jobId)) as DemodulationResult;
      } else {
        result = await apiService.demodulateDatasetCapture(payload);
      }
      setResults((current) => [result, ...current]);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsDatasetRunning(false);
      setWifiJobProgress(null);
    }
  };

  const testBleAdvertisingChannels = async () => {
    const duration = Number(durationSeconds);
    if (!Number.isFinite(duration) || duration <= 0 || duration > 10) {
      setError('BLE channel test duration must be between 0 and 10 seconds.');
      return;
    }
    setError(null);
    setIsBleTestRunning(true);
    setBleChannelTest(null);
    try {
      const response = await apiService.testBleAdvertisingChannels({
        durationSeconds: duration,
        sampleRateHz: 8_000_000,
        bandwidthHz: 2_000_000,
      });
      setBleChannelTest(response);
      await loadResults();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsBleTestRunning(false);
    }
  };

  const testWifi5GhzChannels = async () => {
    const duration = Number(durationSeconds);
    if (!Number.isFinite(duration) || duration <= 0 || duration > 5) {
      setError('Wi-Fi 5 GHz channel sweep duration must be between 0 and 5 seconds per channel.');
      return;
    }
    setError(null);
    setIsWifi5GhzTestRunning(true);
    setWifi5GhzChannelTest(null);
    try {
      const response = await apiService.testWifi5GhzChannels({
        durationSeconds: duration,
        bandwidthHz: 20_000_000,
      });
      setWifi5GhzChannelTest(response);
      await loadResults();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsWifi5GhzTestRunning(false);
    }
  };

  const deleteResult = async (id: string) => {
    const confirmed = window.confirm('Delete this demodulation recording and its local files?');
    if (!confirmed) return;
    setError(null);
    try {
      await apiService.deleteDemodulationResult(id);
      setResults((current) => current.filter((item) => item.id !== id));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <div className="h-full overflow-auto bg-slate-950 text-slate-100">
      <div className="max-w-6xl mx-auto p-6 space-y-5">
        <section className="border border-slate-800 bg-slate-900 p-4 rounded-md">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Demodulator</h2>
              <p className="text-sm text-slate-400">
                Two input modes share the same demodulation pipeline architecture: live SDR marker-band input and reproducible Dataset Builder file input.
              </p>
            </div>
            <button
              onClick={() => loadResults()}
              className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Refresh
            </button>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
            <button
              onClick={() => setWorkMode('live')}
              className={cn(
                'rounded-md border px-4 py-3 text-left',
                workMode === 'live' ? 'border-emerald-400 bg-emerald-500/10 text-emerald-100' : 'border-slate-800 bg-slate-950 text-slate-300'
              )}
            >
              <div className="text-sm font-semibold">1. Live Demodulation</div>
              <div className="mt-1 text-xs text-slate-400">Source: live_sdr, markers M1/M2, computed_from_live_iq, optional saved evidence.</div>
            </button>
            <button
              onClick={() => setWorkMode('dataset')}
              className={cn(
                'rounded-md border px-4 py-3 text-left',
                workMode === 'dataset' ? 'border-blue-400 bg-blue-500/10 text-blue-100' : 'border-slate-800 bg-slate-950 text-slate-300'
              )}
            >
              <div className="text-sm font-semibold">2. Dataset Demodulation</div>
              <div className="mt-1 text-xs text-slate-400">Source: dataset_builder, stored IQ/cfile/SigMF, computed_from_file_iq, persistent outputs.</div>
            </button>
          </div>
        </section>

        {workMode === 'dataset' && <section className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md space-y-4">
            <div>
              <h3 className="text-base font-semibold">Dataset Demodulation</h3>
              <p className="mt-1 text-sm text-slate-400">
                Select an existing Dataset Builder IQ/cfile/SigMF-compatible capture, choose automatic or manual pipeline selection, and create traceable persistent outputs.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400 md:col-span-2">
                Dataset capture
                <select
                  value={selectedCaptureId}
                  onChange={(event) => setSelectedCaptureId(event.target.value)}
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  {datasetCaptures.map((capture) => (
                    <option key={capture.capture_id} value={capture.capture_id}>
                      {capture.capture_id} | {capture.transmitter.transmitter_label || capture.transmitter.transmitter_class || 'unknown'} | {capture.capture_config.file_format}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Pipeline
                <select
                  value={selectedPipeline}
                  onChange={(event) => setSelectedPipeline(event.target.value)}
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  <option value="auto">Auto from metadata</option>
                  {Object.entries(pipelinesByCategory).map(([category, items]) => (
                    <optgroup key={category} label={category}>
                      {items.map((pipeline) => (
                        <option key={pipeline.id} value={pipeline.id}>{pipeline.label}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
            </div>

            {selectedPipeline === 'wifi_80211' && (
              <label className="flex max-w-md flex-col gap-1 text-xs text-slate-400">
                Decoder mode
                <select value={wifiDecoderMode} onChange={(event) => setWifiDecoderMode(event.target.value)} className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400">
                  <option value="auto">Auto</option>
                  <option value="legacy_ofdm">Legacy OFDM 802.11a/g</option>
                  <option value="dsss_cck">DSSS/CCK 802.11b (not implemented)</option>
                  <option value="phy_identification">HT/VHT/HE identification (not implemented)</option>
                  <option value="current_scaffold">Current scaffold</option>
                </select>
                <span>V2 requires WIFI_DEMOD_V2=true; otherwise the current scaffold remains active.</span>
              </label>
            )}

            <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Manual signal type override
                <input
                  value={manualSignalType}
                  onChange={(event) => setManualSignalType(event.target.value)}
                  placeholder="ble_advertising_gfsk, ieee802154, adsb_1090, wfm..."
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                />
              </label>
              <button
                onClick={applyDatasetDemodulation}
                disabled={isDatasetRunning || !selectedCapture}
                className={cn(
                  'h-9 inline-flex items-center px-4 rounded-md text-sm font-semibold',
                  isDatasetRunning || !selectedCapture
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-blue-600 hover:bg-blue-500 text-white'
                )}
              >
                <Play className="w-4 h-4 mr-2" />
                {isDatasetRunning
                  ? (selectedPipeline === 'wifi_80211' ? (wifiJobProgress || 'Running worker...') : 'Running...')
                  : 'Run Post-capture Pipeline'}
              </button>
            </div>
            {selectedPipeline === 'wifi_80211' && (
              <div className="rounded-md border border-indigo-800 bg-indigo-950/30 p-2 text-xs text-indigo-200">
                Recovery is partial: this decoder does not recover every transmitted frame, even on a clean channel. Confirmed frames passed FCS; see receiver_internal_events.jsonl in the result outputs for the full diagnostic trace.
              </div>
            )}

            {selectedCapture ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Info label="Format" value={selectedCapture.capture_config.file_format || 'unknown'} />
                <Info label="Datatype" value={selectedCapture.capture_config.sample_dtype || 'missing'} />
                <Info label="Sample rate" value={formatFrequency(selectedCapture.capture_config.sample_rate_hz) + '/s'} />
              <Info label="Center" value={formatRfCenterFrequency(selectedCapture.capture_config.center_frequency_hz)} />
                <Info label="Signal type" value={selectedCapture.transmitter.signal_type || selectedCapture.transmitter.modulation_class || 'unknown'} />
                <Info label="Bandwidth" value={formatFrequency(selectedCapture.capture_config.effective_bandwidth_hz)} />
                <Info label="Duration" value={`${selectedCapture.capture_config.capture_duration_s}s`} />
                <Info label="Source" value={selectedCapture.capture_config.dataset_destination || selectedCapture.dataset_split} />
              </div>
            ) : (
              <div className="rounded-md border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">
                No Dataset Builder captures available.
              </div>
            )}
          </div>

          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md">
            <h3 className="text-sm font-semibold mb-3">Dataset Mode Contract</h3>
            <div className="space-y-2 text-sm text-slate-300">
              <p>Input source is a stored file and metadata from Dataset Builder.</p>
              <p>Reports use <span className="font-mono">computed_from_file_iq</span> for RF analysis and demodulation source.</p>
              <p>Outputs are always persisted under <span className="font-mono">demodulation_outputs/&lt;sample_id&gt;</span>.</p>
              <p>RF activity is not reported as successful demodulation.</p>
              <p>Reports separate signal detection, pipeline compatibility, synchronization, bits, frames, CRC and extracted content.</p>
              <p>DVB-S/S2 is marked experimental and requires an external satellite RF front-end.</p>
              <div className="pt-2">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-300">IoT Demodulation Pipelines</div>
                <div className="mt-2 space-y-1 text-xs text-slate-400">
                  {iotPipelines.map((pipeline) => (
                    <div key={pipeline.id}>{pipeline.label}: {pipeline.status}</div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>}

        {workMode === 'live' && <section className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md space-y-4">
            <div>
              <h3 className="text-base font-semibold">Live Demodulation</h3>
              <p className="mt-1 text-sm text-slate-400">
                M1 and M2 define the live SDR region of interest. The worker captures real IQ from that marker band, applies optional channel filtering, and reports results as live evidence.
              </p>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Info label="M1" value={selectedBand ? formatRfCenterFrequency(selectedBand.first.frequency) : 'Not set'} />
              <Info label="M2" value={selectedBand ? formatRfCenterFrequency(selectedBand.second.frequency) : 'Not set'} />
              <Info label="Center" value={selectedBand ? formatRfCenterFrequency(selectedBand.center) : 'Not set'} />
              <Info label="Bandwidth" value={selectedBand ? formatFrequency(selectedBand.bandwidth) : 'Not set'} />
              <Info label="FIR filter" value={markerBandpass.enabled ? `ON, ${markerBandpass.attenuationDb} dB` : 'Off'} />
              {liveSuggestion && <Info label="Recommended" value={liveSuggestion.label} />}
            </div>

            {liveSuggestion && (
              <div className="rounded-md border border-sky-800 bg-sky-950/30 p-3 text-sm text-sky-100">
                <div className="font-semibold">{liveSuggestion.label}</div>
                <div className="mt-1 text-xs text-sky-300">{liveSuggestion.detail}</div>
                {liveDetections.length > 1 && (
                  <div className="mt-3 grid gap-1 text-xs text-sky-200">
                    {liveDetections.map((detection) => (
                      <div key={`${detection.pipeline}-${detection.label}`}>
                        {detection.label}: {detection.pipeline} ({detection.confidence})
                      </div>
                    ))}
                  </div>
                )}
                {hasSuggestedPipeline && mode !== liveSuggestion.pipeline && (
                  <button
                    onClick={() => setMode(liveSuggestion.pipeline)}
                    className="mt-3 h-8 rounded-md bg-sky-700 px-3 text-xs font-semibold text-white hover:bg-sky-600"
                  >
                    Use {liveSuggestion.label}
                  </button>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Demodulation
                <select
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                  className="h-9 w-56 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  <optgroup label="Basic analog demodulation">
                    {DEMODULATION_MODES.filter((item) => ['am', 'fm', 'nfm', 'wfm'].includes(item.value)).map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </optgroup>
                  <optgroup label="Physical-layer demodulation">
                    {DEMODULATION_MODES.filter((item) => ['ask', 'fsk', 'psk', 'ook'].includes(item.value)).map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </optgroup>
                  <optgroup label="IoT Demodulation Pipelines">
                    {iotPipelines.map((pipeline) => (
                      <option key={pipeline.id} value={pipeline.id}>{pipeline.label}</option>
                    ))}
                  </optgroup>
                </select>
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Duration s
                <input
                  value={durationSeconds}
                  onChange={(event) => setDurationSeconds(event.target.value)}
                  className="h-9 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                />
              </label>

              <button
                onClick={applyDemodulation}
                disabled={isRunning || !selectedBand}
                className={cn(
                  'h-9 inline-flex items-center px-4 rounded-md text-sm font-semibold',
                  isRunning || !selectedBand
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                )}
              >
                <Play className="w-4 h-4 mr-2" />
                {isRunning ? 'Demodulating...' : 'Apply Demodulation'}
              </button>
              <button
                onClick={testBleAdvertisingChannels}
                disabled={isRunning || isBleTestRunning || isWifi5GhzTestRunning}
                className={cn(
                  'h-9 inline-flex items-center px-4 rounded-md text-sm font-semibold',
                  isRunning || isBleTestRunning || isWifi5GhzTestRunning
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-cyan-700 hover:bg-cyan-600 text-white'
                )}
              >
                <Radio className="w-4 h-4 mr-2" />
                {isBleTestRunning ? 'Testing BLE...' : 'Test BLE advertising channels'}
              </button>
              <button
                onClick={testWifi5GhzChannels}
                disabled={isRunning || isBleTestRunning || isWifi5GhzTestRunning}
                className={cn(
                  'h-9 inline-flex items-center px-4 rounded-md text-sm font-semibold',
                  isRunning || isBleTestRunning || isWifi5GhzTestRunning
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-sky-700 hover:bg-sky-600 text-white'
                )}
              >
                <Radio className="w-4 h-4 mr-2" />
                {isWifi5GhzTestRunning ? 'Sweeping Wi-Fi...' : 'Sweep Wi-Fi 5 GHz channels'}
              </button>
            </div>

            {error && <div className="text-sm text-red-300">{error}</div>}
            {bleChannelTest && <BleChannelTestTable test={bleChannelTest} />}
            {wifi5GhzChannelTest && <Wifi5GhzChannelSweepTable test={wifi5GhzChannelTest} />}
          </div>

          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md">
            <h3 className="text-sm font-semibold mb-3">Live Mode Contract</h3>
            <div className="space-y-2 text-sm text-slate-300">
              <p>Input source is <span className="font-mono">live_sdr</span> and the selected band comes from Marker 1 and Marker 2.</p>
              <p>Reports use <span className="font-mono">computed_from_live_iq</span> for RF analysis and demodulation source.</p>
              <p><span className="text-slate-100 font-medium">AM/FM/WFM:</span> produce a WAV file that can be played in the dashboard.</p>
              <p><span className="text-slate-100 font-medium">ASK/FSK/PSK/OOK:</span> capture the selected marker band as IQ plus metadata for later symbol analysis.</p>
              <p><span className="text-slate-100 font-medium">IoT pipelines:</span> capture real IQ from the marked band and run the same layered IoT analysis used by Dataset mode.</p>
              <p>Center frequency is the midpoint between M1 and M2; bandwidth is the marker distance.</p>
              <p><span className="text-slate-100 font-medium">Marker Band-Pass:</span> when enabled in Spectrum, a real FIR filter is applied to the demodulation IQ before audio/digital output.</p>
              <div className="pt-2">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">IoT Demodulation Pipelines</div>
                <div className="mt-2 space-y-1 text-xs text-slate-400">
                  {iotPipelines.map((pipeline) => (
                    <div key={pipeline.id}>{pipeline.label}: {pipeline.status}</div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>}

        <section className="border border-slate-800 bg-slate-900 rounded-md overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
            <Radio className="w-4 h-4" />
            <h3 className="text-sm font-semibold">Demodulation Results</h3>
          </div>
          <div className="divide-y divide-slate-800">
            {results.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No demodulation results yet.</div>
            ) : results.map((result) => (
              <ResultRow key={result.id} result={result} onDelete={deleteResult} />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function BleChannelTestTable({ test }: { test: Record<string, any> }) {
  const rows = Array.isArray(test.rows) ? test.rows : [];
  return (
    <div className="rounded-md border border-cyan-900/70 bg-cyan-950/20 p-3">
      <div className="text-sm font-semibold text-cyan-100">BLE Advertising Channel Test</div>
      <div className="mt-1 text-xs text-cyan-300">
        Captures CH37, CH38 and CH39 sequentially from live SDR. Success still requires Access Address, packet reconstruction and CRC validation.
      </div>
      <div className="mt-3 overflow-auto rounded-md border border-slate-800">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-950 text-slate-400">
            <tr>
              <th className="px-3 py-2">Channel</th>
              <th className="px-3 py-2">Frequency</th>
              <th className="px-3 py-2">RF activity</th>
              <th className="px-3 py-2">Bursts</th>
              <th className="px-3 py-2">Bitstream</th>
              <th className="px-3 py-2">Access Address</th>
              <th className="px-3 py-2">Packets</th>
              <th className="px-3 py-2">Candidates</th>
              <th className="px-3 py-2">CRC valid</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map((row: any) => (
              <tr key={row.channel} className="bg-slate-900/70">
                <td className="px-3 py-2 font-semibold">CH{row.channel}</td>
                <td className="px-3 py-2">{formatRfCenterFrequency(Number(row.frequency_hz || 0))}</td>
                <td className={cn('px-3 py-2 font-semibold', row.rf_activity ? 'text-emerald-300' : 'text-slate-400')}>{String(Boolean(row.rf_activity))}</td>
                <td className="px-3 py-2">{String(row.bursts ?? 0)}</td>
                <td className={cn('px-3 py-2 font-semibold', row.bitstream ? 'text-emerald-300' : 'text-slate-400')}>{String(Boolean(row.bitstream))}</td>
                <td className={cn('px-3 py-2 font-semibold', row.access_address ? 'text-emerald-300' : 'text-slate-400')}>{String(Boolean(row.access_address))}</td>
                <td className="px-3 py-2">{String(row.packets ?? 0)}</td>
                <td className="px-3 py-2">{String(row.candidates ?? 0)}</td>
                <td className="px-3 py-2">{String(row.crc_valid ?? 0)}</td>
                <td className="px-3 py-2">{String(row.status ?? 'unknown')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Wifi5GhzChannelSweepTable({ test }: { test: Record<string, any> }) {
  const rows = Array.isArray(test.rows) ? test.rows : [];
  return (
    <div className="rounded-md border border-sky-900/70 bg-sky-950/20 p-3">
      <div className="text-sm font-semibold text-sky-100">Wi-Fi 5 GHz Channel Sweep</div>
      <div className="mt-1 text-xs text-sky-300">
        Captures common 20 MHz 5 GHz Wi-Fi channels sequentially from live SDR and runs the Wi-Fi 802.11 pipeline scaffold.
      </div>
      <div className="mt-3 overflow-auto rounded-md border border-slate-800">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-950 text-slate-400">
            <tr>
              <th className="px-3 py-2">Channel</th>
              <th className="px-3 py-2">Frequency</th>
              <th className="px-3 py-2">RF activity</th>
              <th className="px-3 py-2">Frames</th>
              <th className="px-3 py-2">CRC valid</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map((row: any) => (
              <tr key={row.channel} className="bg-slate-900/70">
                <td className="px-3 py-2 font-semibold">CH{row.channel}</td>
                <td className="px-3 py-2">{formatRfCenterFrequency(Number(row.frequency_hz || 0))}</td>
                <td className={cn('px-3 py-2 font-semibold', row.rf_activity ? 'text-emerald-300' : 'text-slate-400')}>{String(Boolean(row.rf_activity))}</td>
                <td className="px-3 py-2">{String(row.frames ?? 0)}</td>
                <td className="px-3 py-2">{String(row.crc_valid ?? 0)}</td>
                <td className={cn('px-3 py-2', row.status === 'error' ? 'text-red-300' : 'text-slate-300')}>
                  {String(row.status ?? 'n/a')}
                  {row.error ? <div className="mt-1 text-red-300">{String(row.error).slice(0, 180)}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ResultRow({ result, onDelete }: { result: DemodulationResult; onDelete: (id: string) => void }) {
  const audioUrl = result.audio_url ? apiService.getDemodulationAudioUrl(result.id) : null;
  const [report, setReport] = useState<Record<string, any> | null>(result as any);
  const [decodedPackets, setDecodedPackets] = useState<Record<string, any> | null>(
    result.decoded_packets ? result.decoded_packets as Record<string, any> : null,
  );
  const [outputError, setOutputError] = useState<string | null>(null);
  const title = result.sample_id
    ? `${result.sample_id} | ${result.demodulation_pipeline || result.pipeline || result.mode} | ${result.final_status || result.status}`
    : `${(result.mode || 'unknown').toUpperCase()} | ${formatRfCenterFrequency(result.center_frequency_hz || 0)} | BW ${formatFrequency(result.bandwidth_hz || 0)}`;
  const decodedCount = result.packets_decoded ?? result.frames_decoded;
  const crcCount = result.packets_crc_valid ?? result.frames_crc_valid;
  const reportFile = outputFilename(result.outputs?.report || result.metadata_file || 'demodulation_report.json');
  const decodedPacketsFile = outputFilename(result.outputs?.decoded_packets || (result.decoded_packets ? 'decoded_packets.json' : null));
  const bitstreamFile = outputFilename(result.outputs?.bitstream || null);
  const candidateDiagnosticsFile = outputFilename(result.outputs?.candidate_diagnostics || null);
  const burstDiagnosticsFile = outputFilename(result.outputs?.burst_diagnostics || null);
  const rawPulsesFile = outputFilename(result.outputs?.raw_pulses || null);
  const burstFeaturesFile = outputFilename(result.outputs?.burst_features || null);
  const candidateDecodingsFile = outputFilename(result.outputs?.candidate_decodings || null);
  const selectedDecodingFile = outputFilename(result.outputs?.selected_decoding || null);
  const fskBurstDiagnosticsFile = outputFilename(result.outputs?.fsk_burst_diagnostics || null);
  const fskCandidateDecodingsFile = outputFilename(result.outputs?.fsk_candidate_decodings || null);
  const selectedFskDecodingFile = outputFilename(result.outputs?.selected_fsk_decoding || null);
  const logsFile = outputFilename(result.outputs?.logs || null);
  const outputDir = String((report || result as any).output_dir || '');
  const packets: DecodedPacket[] = Array.isArray(decodedPackets?.packets) ? decodedPackets?.packets : [];
  const candidatePackets: DecodedPacket[] = Array.isArray(decodedPackets?.candidate_packets) ? decodedPackets?.candidate_packets : [];
  const packetCount = Number(report?.packets_decoded ?? decodedPackets?.packets_decoded ?? packets.length ?? 0);
  const candidateCount = Number(report?.packet_candidates ?? decodedPackets?.packet_candidates ?? candidatePackets.length ?? 0);
  const crcValidCount = Number(report?.packets_crc_valid ?? decodedPackets?.packets_crc_valid ?? packets.filter((packet) => packet.crc_valid).length ?? 0);
  const crcRate = packetCount > 0 ? `${((crcValidCount / packetCount) * 100).toFixed(1)}%` : 'n/a';
  const captureTime = getResultTime(report || result as any);
  const packetLike = isPacketLikeResult(report || result as any, decodedPackets);
  const isAudio = isAudioResult(report || result as any);
  const hasDecodedOutput = !isAudio && (packetLike || packets.length > 0 || candidatePackets.length > 0 || Boolean(bitstreamFile || candidateDiagnosticsFile || burstDiagnosticsFile || rawPulsesFile || burstFeaturesFile || candidateDecodingsFile || selectedDecodingFile || fskBurstDiagnosticsFile || fskCandidateDecodingsFile || selectedFskDecodingFile || logsFile));

  useEffect(() => {
    let cancelled = false;
    const loadDecodedOutputs = async () => {
      setOutputError(null);
      try {
        if (reportFile) {
          const nextReport = await apiService.getDemodulationOutputJson(result.id, reportFile);
          if (!cancelled) setReport(nextReport);
        }
      } catch {
        if (!cancelled) setReport(result as any);
      }
      try {
        if (decodedPacketsFile) {
          const nextPackets = await apiService.getDemodulationOutputJson(result.id, decodedPacketsFile);
          if (!cancelled) setDecodedPackets(nextPackets);
        }
      } catch {
        if (!cancelled && result.outputs?.decoded_packets) {
          setOutputError('decoded_packets.json is not available for this result.');
        }
      }
    };
    loadDecodedOutputs();
    return () => {
      cancelled = true;
    };
  }, [result.id]);

  const openOutput = (filename: string | null) => {
    if (!filename) return;
    window.open(apiService.getDemodulationOutputUrl(result.id, filename), '_blank', 'noopener,noreferrer');
  };

  const exportResult = () => {
    openOutput(reportFile);
  };

  const showOutputFolder = async () => {
    if (!outputDir) return;
    try {
      await navigator.clipboard.writeText(outputDir);
      window.alert(`Output folder path copied:\n${outputDir}`);
    } catch {
      window.alert(outputDir);
    }
  };

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">{title}</div>
          <div className="text-xs text-slate-400">
            {captureTime} | {result.duration_seconds ?? 'n/a'}s capture | {formatFrequency(result.sample_rate_hz || 0)}/s | {result.signal_type || result.protocol || 'unknown signal'}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {audioUrl && (
            <a
              href={audioUrl}
              className="h-9 inline-flex items-center px-3 rounded-md bg-blue-600 hover:bg-blue-500 text-sm font-medium"
            >
              <Download className="w-4 h-4 mr-2" />
              WAV
            </a>
          )}
          {!isAudio && (
            <button
              onClick={() => openOutput(decodedPacketsFile)}
              className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm font-medium"
            >
              Open decoded_packets.json
            </button>
          )}
          <button
            onClick={() => openOutput(reportFile)}
            className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm font-medium"
          >
            Open demodulation_report.json
          </button>
          <button
            onClick={showOutputFolder}
            className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm font-medium"
          >
            Open output folder
          </button>
          <button
            onClick={exportResult}
            className="h-9 inline-flex items-center px-3 rounded-md bg-indigo-700 hover:bg-indigo-600 text-sm font-medium"
          >
            Export result
          </button>
          <button
            onClick={() => onDelete(result.id)}
            className="h-9 inline-flex items-center px-3 rounded-md bg-red-700 hover:bg-red-600 text-sm font-medium"
            title="Delete demodulation metadata, audio, and IQ files from local storage"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Delete
          </button>
        </div>
      </div>
      {audioUrl ? (
        <audio controls src={audioUrl} className="w-full" />
      ) : (
        !isAudio && (
          <div className="text-sm text-slate-400">
            This result does not include playable audio. Review decoded packets, payloads, bitstream or report outputs below.
          </div>
        )
      )}
      {isAudio ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <Info label="Capture time" value={captureTime} />
            <Info label="Source" value={String(result.source || 'live_sdr')} />
            <Info label="Demod mode" value={String((report as any)?.mode || result.pipeline || result.demodulation_pipeline || 'n/a').toUpperCase()} />
            <Info label="Status" value={String(result.final_status || result.status || 'n/a')} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <Info label="Center freq" value={formatRfCenterFrequency(result.center_frequency_hz || 0)} />
            <Info label="Bandwidth" value={formatFrequency(result.bandwidth_hz || 0)} />
            <Info label="Sample rate" value={`${formatFrequency(result.sample_rate_hz || 0)}/s`} />
            <Info label="Duration" value={result.duration_seconds !== undefined ? `${result.duration_seconds} s` : 'n/a'} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <Info label="Audio" value={audioUrl ? 'âœ“ WAV available' : 'âœ— not generated'} />
            <Info label="Audio rate" value={(report as any)?.audio_rate_hz ? `${((report as any).audio_rate_hz / 1000).toFixed(0)} kHz` : 'n/a'} />
            <Info label="Gain" value={(report as any)?.gain_db !== undefined ? `${(report as any).gain_db} dB` : 'n/a'} />
            <Info label="Antenna" value={String((report as any)?.antenna || 'n/a')} />
          </div>
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
            <Info label="Capture time" value={captureTime} />
            <Info label="Source" value={String(result.source || (result.sample_id ? 'dataset_builder' : 'live_sdr'))} />
            <Info label="Final status" value={String(result.final_status || result.status || 'n/a')} />
            <Info label="Protocol" value={String(result.protocol || result.signal_type || 'n/a')} />
            <Info label="Pipeline" value={String(result.demodulation_pipeline || result.pipeline || result.mode || 'n/a')} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
            <Info label="Packets/frames" value={decodedCount === undefined ? 'n/a' : String(decodedCount)} />
            <Info label="CRC valid" value={crcCount === undefined ? 'n/a' : String(crcCount)} />
            <Info label="Channel" value={result.channel === undefined ? 'n/a' : String(result.channel)} />
          </div>
        </>
      )}
      {result.notes && result.notes.length > 0 && (
        <div className="rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300">
          {result.notes.join(' ')}
        </div>
      )}
      {result.outputs && Object.keys(result.outputs).length > 0 && (
        <div className="rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">
          <div className="mb-2 font-semibold text-slate-200">Outputs</div>
          <div className="space-y-1">
            {Object.entries(result.outputs).map(([key, value]) => (
              <div key={key} className="font-mono">{key}: {String(value || 'not generated')}</div>
            ))}
          </div>
        </div>
      )}
      {hasDecodedOutput && (
        <DecodedOutputPanel
          report={report}
          decodedPackets={decodedPackets}
          packets={packets}
          candidatePackets={candidatePackets}
          packetCount={packetCount}
          candidateCount={candidateCount}
          crcValidCount={crcValidCount}
          crcRate={crcRate}
          outputError={outputError}
          bitstreamFile={bitstreamFile}
          candidateDiagnosticsFile={candidateDiagnosticsFile}
          burstDiagnosticsFile={burstDiagnosticsFile}
          rawPulsesFile={rawPulsesFile}
          burstFeaturesFile={burstFeaturesFile}
          candidateDecodingsFile={candidateDecodingsFile}
          selectedDecodingFile={selectedDecodingFile}
          fskBurstDiagnosticsFile={fskBurstDiagnosticsFile}
          fskCandidateDecodingsFile={fskCandidateDecodingsFile}
          selectedFskDecodingFile={selectedFskDecodingFile}
          logsFile={logsFile}
          onOpenOutput={openOutput}
        />
      )}
    </div>
  );
}

function DecodedOutputPanel({
  report,
  decodedPackets,
  packets,
  candidatePackets,
  packetCount,
  candidateCount,
  crcValidCount,
  crcRate,
  outputError,
  bitstreamFile,
  candidateDiagnosticsFile,
  burstDiagnosticsFile,
  rawPulsesFile,
  burstFeaturesFile,
  candidateDecodingsFile,
  selectedDecodingFile,
  fskBurstDiagnosticsFile,
  fskCandidateDecodingsFile,
  selectedFskDecodingFile,
  logsFile,
  onOpenOutput,
}: {
  report: Record<string, any> | null;
  decodedPackets: Record<string, any> | null;
  packets: DecodedPacket[];
  candidatePackets: DecodedPacket[];
  packetCount: number;
  candidateCount: number;
  crcValidCount: number;
  crcRate: string;
  outputError: string | null;
  bitstreamFile: string | null;
  candidateDiagnosticsFile: string | null;
  burstDiagnosticsFile: string | null;
  rawPulsesFile: string | null;
  burstFeaturesFile: string | null;
  candidateDecodingsFile: string | null;
  selectedDecodingFile: string | null;
  fskBurstDiagnosticsFile: string | null;
  fskCandidateDecodingsFile: string | null;
  selectedFskDecodingFile: string | null;
  logsFile: string | null;
  onOpenOutput: (filename: string | null) => void;
}) {
  const finalStatus = String(report?.final_status ?? report?.status ?? 'not_attempted');
  const protocol = String(report?.protocol ?? report?.signal_type ?? decodedPackets?.protocol ?? '').toLowerCase();
  const pipeline = String(report?.pipeline ?? report?.demodulation_pipeline ?? report?.pipeline_name ?? '').toLowerCase();
  const isBle = protocol.includes('bluetooth') || protocol.includes('ble') || pipeline.includes('ble');
  const isWifi = protocol.includes('wifi') || protocol.includes('80211') || pipeline.includes('wifi') || pipeline.includes('80211');
  const isOokRemote = protocol.includes('ook_433_remote') || pipeline.includes('ook_433_remote') || protocol.includes('fsk_remote') || pipeline.includes('fsk_remote');
  const isPacketProtocol = isBle || isWifi || ['ieee802154', 'zigbee', 'adsb', 'lora'].some((name) => protocol.includes(name) || pipeline.includes(name));
  const emptyPacketMessage = isBle
    ? 'RF activity detected, but no valid BLE advertising packet was recovered.'
    : isWifi
      ? 'Wi-Fi-band RF burst candidates may be present, but no CRC-valid IEEE 802.11 frame was reconstructed.'
    : isOokRemote
      ? 'OOK burst activity was detected, but no known remote-control protocol was decoded. Check symbol-level transitions and possible FSK/ASK classification below.'
    : isPacketProtocol
      ? 'RF activity detected, but no valid protocol packet or frame was recovered.'
      : 'No decoded packet output is expected for this demodulation type.';
  const confidence = report?.confidence_score === null || report?.confidence_score === undefined
    ? 'not_computed'
    : String(report.confidence_score);
  const accessAddressDetected = Boolean(report?.access_address_detected ?? decodedPackets?.access_address_detected ?? false);
  const validDemodulation = Boolean(report?.valid_demodulation ?? (accessAddressDetected && packetCount >= 1 && crcValidCount >= 1));
  const ookBursts = Array.isArray(report?.decoded_frames?.burst_diagnostics)
    ? report.decoded_frames.burst_diagnostics
    : Array.isArray(report?.decoded_frames?.bursts)
      ? report.decoded_frames.bursts
      : [];
  const ookComparison = report?.burst_comparison ?? report?.decoded_frames?.burst_comparison ?? {};
  const ookRepeat = report?.repeat_analysis ?? report?.decoded_frames?.repeat_analysis ?? {};
  const ookAdaptive = report?.adaptive_decoding ?? report?.decoded_frames?.adaptive_decoding ?? {};
  const visibleCandidatePackets = candidatePackets.slice(0, 20);
  return (
    <div className="rounded-md border border-cyan-900/70 bg-cyan-950/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-cyan-100">Analyze Result / Decoded Output</div>
          <div className="mt-1 text-xs text-cyan-300">
            Loaded from demodulation report and decoded output files when available.
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {bitstreamFile && (
            <button onClick={() => onOpenOutput(bitstreamFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open bitstream.bin
            </button>
          )}
          {candidateDiagnosticsFile && (
            <button onClick={() => onOpenOutput(candidateDiagnosticsFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open candidate_diagnostics.json
            </button>
          )}
          {burstDiagnosticsFile && (
            <button onClick={() => onOpenOutput(burstDiagnosticsFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open ook_burst_diagnostics.json
            </button>
          )}
          {selectedDecodingFile && (
            <button onClick={() => onOpenOutput(selectedDecodingFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open selected_decoding.json
            </button>
          )}
          {fskBurstDiagnosticsFile && (
            <button onClick={() => onOpenOutput(fskBurstDiagnosticsFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open fsk_burst_diagnostics.json
            </button>
          )}
          {fskCandidateDecodingsFile && (
            <button onClick={() => onOpenOutput(fskCandidateDecodingsFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open fsk_candidate_decodings.json
            </button>
          )}
          {selectedFskDecodingFile && (
            <button onClick={() => onOpenOutput(selectedFskDecodingFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open selected_fsk_decoding.json
            </button>
          )}
          {candidateDecodingsFile && (
            <button onClick={() => onOpenOutput(candidateDecodingsFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open candidate_decodings.json
            </button>
          )}
          {burstFeaturesFile && (
            <button onClick={() => onOpenOutput(burstFeaturesFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open burst_features.json
            </button>
          )}
          {rawPulsesFile && (
            <button onClick={() => onOpenOutput(rawPulsesFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open raw_pulses.json
            </button>
          )}
          {logsFile && (
            <button onClick={() => onOpenOutput(logsFile)} className="rounded-md bg-cyan-800 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
              Open logs.txt
            </button>
          )}
        </div>
      </div>

      {isOokRemote ? (
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
          <Info label="Final status" value={finalStatus} />
          <Info label="Valid protocol" value={validDemodulation ? 'true' : 'false'} />
          <Info label="Confidence" value={confidence} />
          <Info label="OOK bursts" value={String(report?.bursts_detected ?? report?.decoded_frames?.bursts_detected ?? ookBursts.length ?? 0)} />
          <Info label="Symbol bursts" value={String(report?.symbol_level_bursts ?? report?.decoded_frames?.symbol_level_bursts ?? 'n/a')} />
          <Info label="No-symbol bursts" value={String(report?.no_symbol_level_bursts ?? report?.decoded_frames?.no_symbol_level_bursts ?? 'n/a')} />
          <Info label="Possible modulation" value={(report?.possible_modulation_counts ?? report?.decoded_frames?.possible_modulation_counts) ? JSON.stringify(report?.possible_modulation_counts ?? report?.decoded_frames?.possible_modulation_counts) : 'n/a'} />
          <Info label="Repeated" value={ookRepeat?.repetition_detected ? 'true' : 'false'} />
          <Info label="Repetitions" value={String(ookRepeat?.repetition_count ?? 'n/a')} />
          <Info label="Clusters" value={ookComparison?.cluster_counts ? JSON.stringify(ookComparison.cluster_counts) : 'n/a'} />
          <Info label="Interpretation" value={String(ookComparison?.interpretation ?? 'n/a')} />
          <Info label="Selected encoding" value={String(ookAdaptive?.selected_encoding_type ?? 'n/a')} />
          <Info label="Burst stability" value={ookAdaptive?.burst_stability_confidence !== undefined ? String(ookAdaptive.burst_stability_confidence) : 'n/a'} />
          <Info label="Protocol confidence" value={ookAdaptive?.protocol_decoding_confidence !== undefined ? String(ookAdaptive.protocol_decoding_confidence) : 'n/a'} />
          <Info label="Encoding confidence" value={(ookAdaptive?.selected_encoding_confidence ?? ookAdaptive?.selected_confidence) !== undefined ? String(ookAdaptive.selected_encoding_confidence ?? ookAdaptive.selected_confidence) : 'n/a'} />
          <Info label="Encoding warning" value={String(ookAdaptive?.selected_warning ?? 'none')} />
          <Info label="Recommended" value={String(report?.recommended_pipeline ?? ookAdaptive?.recommended_pipeline ?? 'n/a')} />
          <Info label="T unit" value={report?.t_unit_us !== undefined ? `${report.t_unit_us} us` : 'n/a'} />
          <Info label="Symbol rate" value={report?.symbol_rate_baud ? `${report.symbol_rate_baud} baud` : 'n/a'} />
          <Info label="Center" value={report?.center_frequency_hz ? formatRfCenterFrequency(Number(report.center_frequency_hz)) : 'n/a'} />
          <Info label="Sample rate" value={report?.sample_rate_hz ? `${formatFrequency(Number(report.sample_rate_hz))}/s` : 'n/a'} />
          <Info label="Duration" value={String(report?.capture_duration_seconds ?? report?.duration_seconds ?? 'n/a')} />
        </div>
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
          <Info label="Final status" value={finalStatus} />
          <Info label="Valid demod" value={validDemodulation ? 'true' : 'false'} />
          <Info label="Confidence" value={confidence} />
          <Info label="Packets decoded" value={String(packetCount)} />
          {candidateCount > 0 && <Info label={isWifi ? 'Wi-Fi candidates' : 'BLE candidates'} value={String(candidateCount)} />}
          <Info label="CRC valid" value={`${crcValidCount} (${crcRate})`} />
          {isBle && <Info label="Access address" value={accessAddressDetected ? String(report?.access_address ?? '0x8E89BED6') : 'false'} />}
          {isBle && <Info label="BLE channel" value={String(report?.computed_ble_channel ?? report?.channel ?? decodedPackets?.channel ?? 'n/a')} />}
          {isWifi && <Info label="Wi-Fi band" value={String(report?.wifi_band ?? decodedPackets?.band ?? 'n/a')} />}
          {isWifi && <Info label="Wi-Fi channel" value={String(report?.wifi_channel ?? decodedPackets?.channel ?? 'n/a')} />}
          <Info label="Center" value={report?.center_frequency_hz ? formatRfCenterFrequency(Number(report.center_frequency_hz)) : 'n/a'} />
          <Info label="Sample rate" value={report?.sample_rate_hz ? `${formatFrequency(Number(report.sample_rate_hz))}/s` : 'n/a'} />
          <Info label="Duration" value={String(report?.capture_duration_seconds ?? report?.duration_seconds ?? 'n/a')} />
          {report?.ble_receiver_chain_version && <Info label="BLE chain" value={String(report.ble_receiver_chain_version)} />}
        </div>
      )}

      {outputError && <div className="mt-3 text-xs text-amber-300">{outputError}</div>}

      {isOokRemote && (report?.recommended_pipeline === 'fsk_remote_decoder' || ookAdaptive?.recommended_pipeline === 'fsk_remote_decoder') && (
        <div className="mt-3 rounded-md border border-amber-700 bg-amber-950/40 p-3 text-sm font-semibold text-amber-100">
          Recommended next step: Run FSK remote decoder.
        </div>
      )}

      {isOokRemote && ookAdaptive?.selected_reason && (
        <div className="mt-3 rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300">
          {String(ookAdaptive.selected_reason)}
        </div>
      )}

      {packetCount === 0 && (
        <div className="mt-3 rounded-md border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-200">
          {emptyPacketMessage}
          {candidateCount > 0 && (
            <div className="mt-2 text-xs text-amber-100">
              {candidateCount} BLE packet candidate(s) were found, but they are not decoded packets because CRC validation failed.
              {candidateCount > visibleCandidatePackets.length ? ` Showing first ${visibleCandidatePackets.length}.` : ''}
            </div>
          )}
        </div>
      )}

      {isOokRemote && ookBursts.length > 0 && (
        <div className="mt-4 overflow-auto rounded-md border border-slate-800">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="px-3 py-2">Burst</th>
                <th className="px-3 py-2">Start</th>
                <th className="px-3 py-2">Duration</th>
                <th className="px-3 py-2">Peak</th>
                <th className="px-3 py-2">SNR</th>
                <th className="px-3 py-2">Transitions</th>
                <th className="px-3 py-2">Marks/spaces</th>
                <th className="px-3 py-2">Symbol level</th>
                <th className="px-3 py-2">Possible modulation</th>
                <th className="px-3 py-2">Bits</th>
                <th className="px-3 py-2">Cluster</th>
                <th className="px-3 py-2">Repetition</th>
                <th className="px-3 py-2">Hex candidate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {ookBursts.slice(0, 20).map((burst: any, index: number) => (
                <tr key={`ook-burst-${burst.burst_index ?? index}`} className="bg-slate-900/70">
                  <td className="px-3 py-2">{burst.burst_index ?? index}</td>
                  <td className="px-3 py-2">{burst.burst_start_time !== undefined ? `${Number(burst.burst_start_time).toFixed(5)} s` : 'n/a'}</td>
                  <td className="px-3 py-2">{burst.burst_duration !== undefined ? `${(Number(burst.burst_duration) * 1000).toFixed(2)} ms` : 'n/a'}</td>
                  <td className="px-3 py-2">{burst.peak_frequency_hz ? formatRfCenterFrequency(Number(burst.peak_frequency_hz)) : 'n/a'}</td>
                  <td className="px-3 py-2">{burst.snr_db !== undefined && burst.snr_db !== null ? `${Number(burst.snr_db).toFixed(1)} dB` : 'n/a'}</td>
                  <td className="px-3 py-2">{burst.internal_transition_count ?? 'n/a'}</td>
                  <td className="px-3 py-2">{`${burst.mark_count ?? 'n/a'} / ${burst.space_count ?? 'n/a'}`}</td>
                  <td className="px-3 py-2">{burst.symbol_level_detected === true ? 'true' : burst.symbol_level_detected === false ? 'false' : 'n/a'}</td>
                  <td className="px-3 py-2">{burst.possible_modulation ?? 'n/a'}</td>
                  <td className="px-3 py-2">{burst.bit_count ?? 'n/a'}</td>
                  <td className="px-3 py-2">{burst.clustering_id ?? 'n/a'}</td>
                  <td className="px-3 py-2">{burst.repetition_score !== undefined ? Number(burst.repetition_score).toFixed(2) : 'n/a'}</td>
                  <td className="max-w-[360px] truncate px-3 py-2 font-mono">{burst.hex_candidate ?? burst.bits_hex ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!isOokRemote && packets.length > 0 ? (
        <div className="mt-4 overflow-auto rounded-md border border-slate-800">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="px-3 py-2">Index</th>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2">PDU type</th>
                <th className="px-3 py-2">Advertiser address</th>
                <th className="px-3 py-2">CRC</th>
                <th className="px-3 py-2">Payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {packets.map((packet, index) => (
                <tr key={`${packet.packet_index ?? index}-${packet.timestamp_seconds ?? index}`} className="bg-slate-900/70">
                  <td className="px-3 py-2">{packet.packet_index ?? index}</td>
                  <td className="px-3 py-2">{packet.timestamp_seconds !== undefined ? `${packet.timestamp_seconds.toFixed(5)} s` : 'n/a'}</td>
                  <td className="px-3 py-2">{packet.channel !== undefined ? `CH${packet.channel}` : 'n/a'}</td>
                  <td className="px-3 py-2">{packet.pdu_type ?? 'n/a'}</td>
                  <td className="px-3 py-2 font-mono">{packet.advertiser_address ?? 'n/a'}</td>
                  <td className={cn('px-3 py-2 font-semibold', packet.crc_valid ? 'text-emerald-300' : 'text-rose-300')}>
                    {packet.crc_valid ? 'valid' : 'invalid'}
                  </td>
                  <td className="max-w-[360px] truncate px-3 py-2 font-mono">{packet.payload_hex ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-3 text-xs text-slate-400">
          {isOokRemote
            ? 'OOK raw burst diagnostics are shown above when available. No packet table is expected unless a known protocol is decoded.'
            : isPacketProtocol && candidateCount === 0 ? 'decoded_packets.json contains no recovered packets.' : !isPacketProtocol ? 'No packet table is available for this result.' : ''}
        </div>
      )}

      {!isOokRemote && candidatePackets.length > 0 && (
        <div className="mt-4 overflow-auto rounded-md border border-amber-800/70">
          <div className="border-b border-amber-800/70 bg-amber-950/50 px-3 py-2 text-xs font-semibold text-amber-200">
            Candidate packets only - CRC invalid, fields are not trusted decoded content
          </div>
          <table className="min-w-full text-left text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="px-3 py-2">Index</th>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2">PDU type</th>
                <th className="px-3 py-2">Candidate address</th>
                <th className="px-3 py-2">CRC</th>
                <th className="px-3 py-2">Computed / received</th>
                <th className="px-3 py-2">Payload candidate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {visibleCandidatePackets.map((packet, index) => (
                <tr key={`candidate-${packet.packet_index ?? index}-${packet.timestamp_seconds ?? index}`} className="bg-slate-900/70">
                  <td className="px-3 py-2">{packet.packet_index ?? index}</td>
                  <td className="px-3 py-2">{packet.timestamp_seconds !== undefined ? `${packet.timestamp_seconds.toFixed(5)} s` : 'n/a'}</td>
                  <td className="px-3 py-2">{packet.channel !== undefined ? `CH${packet.channel}` : 'n/a'}</td>
                  <td className="px-3 py-2">{packet.pdu_type ?? 'n/a'}</td>
                  <td className="px-3 py-2 font-mono text-amber-200">{packet.advertiser_address ?? 'n/a'}</td>
                  <td className="px-3 py-2 font-semibold text-rose-300">{packet.crc_valid ? 'valid' : 'invalid'}</td>
                  <td className="px-3 py-2 font-mono">{packet.crc_computed ?? 'n/a'} / {packet.crc_received ?? 'n/a'}</td>
                  <td className="max-w-[360px] truncate px-3 py-2 font-mono text-slate-300">{packet.payload_hex ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Array.isArray(report?.warnings) && report.warnings.length > 0 && (
        <div className="mt-3 rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300">
          Warnings: {report.warnings.join(' ')}
        </div>
      )}
    </div>
  );
}
