import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkFrequencyApplicability, checkRepresentationCompatibility, useAiLiveDetection } from '../../ai/useAiLiveDetection';
import type { RFModelInputFields, RFModelManifest } from '../../../ai-research-plugin/types';
import type { RFTerrainFrequencyInfo } from '../../ui/RFTerrainToolbar';

const emptyInput: RFModelInputFields = {
  representation: null, tensor_shape: null, dtype: null, input_name: null,
  sample_rate_hz: null, bandwidth_hz: null, center_frequency_dependency: null,
  window_samples: null, overlap: null, expected_center_frequency_hz: null, expected_frequency_tolerance_hz: null,
};

const manifest = (overrides: Partial<RFModelInputFields> = {}, id = 'AI-MODEL-1'): RFModelManifest => ({
  model_id: id,
  model_name: 'Toy Model',
  framework: 'onnx',
  model_file: 'toy.onnx',
  model_sha256: 'a'.repeat(64),
  imported_at_utc: '2026-01-01T00:00:00Z',
  task: 'other',
  input_discovered: emptyInput,
  input_overrides: { ...emptyInput, ...overrides },
  preprocessing: { normalization: null, fft_size: null, stft_window: null, stft_hop: null, scaling: null },
  output_discovered: { output_type: null, tensor_shape: null, output_name: null, classes: null },
  output_overrides: { output_type: null, tensor_shape: null, output_name: null, classes: null },
  provenance: { paper: null, authors: null, repository: null, dataset: null, model_version: null, notes: null },
});

const freq = (centerFrequencyHz: number): RFTerrainFrequencyInfo => ({ centerFrequencyHz, spanHz: 2_000_000 });

describe('checkFrequencyApplicability', () => {
  it('is not applicable with no model selected', () => {
    expect(checkFrequencyApplicability(undefined, freq(2_440_000_000))).toEqual({ applicable: false, reason: 'No model selected.' });
  });

  it('is applicable (with a disclaimer) when the model declares no expected frequency', () => {
    const result = checkFrequencyApplicability(manifest(), freq(2_440_000_000));
    expect(result.applicable).toBe(true);
    expect(result.reason).toMatch(/does not declare an expected frequency/);
  });

  it('is applicable when within tolerance', () => {
    const result = checkFrequencyApplicability(
      manifest({ expected_center_frequency_hz: 2_440_000_000, expected_frequency_tolerance_hz: 1_000_000 }),
      freq(2_440_500_000),
    );
    expect(result).toEqual({ applicable: true, reason: '' });
  });

  it('is not applicable when outside tolerance, with a clear real-frequency message', () => {
    const result = checkFrequencyApplicability(
      manifest({ expected_center_frequency_hz: 915_000_000, expected_frequency_tolerance_hz: 500_000 }),
      freq(2_440_000_000),
    );
    expect(result.applicable).toBe(false);
    expect(result.reason).toMatch(/915\.000 MHz/);
    expect(result.reason).toMatch(/2440\.000 MHz/);
  });

  it('is not applicable when live tuning is not known yet', () => {
    const result = checkFrequencyApplicability(
      manifest({ expected_center_frequency_hz: 915_000_000 }),
      null,
    );
    expect(result).toEqual({ applicable: false, reason: 'Live tuning information is not available yet.' });
  });
});

describe('checkRepresentationCompatibility', () => {
  it('is not compatible with no model selected', () => {
    expect(checkRepresentationCompatibility(undefined, 'iq_tensor')).toEqual({ compatible: false, reason: 'No model selected.' });
  });

  it('is compatible (unknown, not blocked) when the model declares no tensor shape', () => {
    expect(checkRepresentationCompatibility(manifest(), 'iq_tensor')).toEqual({ compatible: true, reason: '' });
  });

  it('is compatible when the declared rank matches the representation the adapter produces', () => {
    // iq_tensor -> [1,2,N], rank 3
    expect(checkRepresentationCompatibility(manifest({ tensor_shape: [1, 2, 4096] }), 'iq_tensor')).toEqual({ compatible: true, reason: '' });
  });

  it('reproduces the real reported bug: a rank-4 image-like model against iq_tensor (rank 3) is refused with a clear reason', () => {
    const result = checkRepresentationCompatibility(manifest({ tensor_shape: [null, 224, 224, 3] }), 'iq_tensor');
    expect(result.compatible).toBe(false);
    expect(result.reason).toMatch(/rank-4/);
    expect(result.reason).toMatch(/rank-3/);
    expect(result.reason).toMatch(/224/);
  });

  it('spectrogram (rank 4) is compatible with a rank-4 declared model', () => {
    expect(checkRepresentationCompatibility(manifest({ tensor_shape: [1, 1, 129, 32] }), 'spectrogram')).toEqual({ compatible: true, reason: '' });
  });

  it('psd (rank 2) is compatible with a rank-2 declared model', () => {
    expect(checkRepresentationCompatibility(manifest({ tensor_shape: [1, 256] }), 'psd')).toEqual({ compatible: true, reason: '' });
  });
});

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe('useAiLiveDetection', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('fetches models and live status on mount', async () => {
    const models = [manifest()];
    const fetchImpl = vi.fn((url: string) => {
      if (url.includes('/models')) return Promise.resolve(jsonResponse(models));
      if (url.includes('/status')) return Promise.resolve(jsonResponse({ enabled: true, capture_bridge_available: true, live_inference_available: true }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchImpl);

    const { result } = renderHook(() => useAiLiveDetection({ frequencyInfo: null }));

    await waitFor(() => expect(result.current.models).toHaveLength(1));
    expect(result.current.liveAvailable).toBe(true);
  });

  it('runOnce() is a no-op when the selected model is not applicable at the current frequency', async () => {
    const models = [manifest({ expected_center_frequency_hz: 915_000_000, expected_frequency_tolerance_hz: 500_000 })];
    const fetchImpl = vi.fn((url: string) => {
      if (url.includes('/models')) return Promise.resolve(jsonResponse(models));
      if (url.includes('/status')) return Promise.resolve(jsonResponse({ enabled: true, capture_bridge_available: true, live_inference_available: true }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchImpl);

    const { result } = renderHook(() => useAiLiveDetection({ frequencyInfo: freq(2_440_000_000) }));
    await waitFor(() => expect(result.current.models).toHaveLength(1));

    act(() => result.current.setSelectedModelId('AI-MODEL-1'));
    await waitFor(() => expect(result.current.applicability?.applicable).toBe(false));

    await act(async () => { await result.current.runOnce(); });

    expect(fetchImpl.mock.calls.some((call) => String(call[0]).includes('/inference/live'))).toBe(false);
  });

  it('runOnce() calls runInferenceLive and records a detection when applicable', async () => {
    const onDetection = vi.fn();
    const models = [manifest()]; // no declared frequency -- always "applicable" (with disclaimer)
    const inferenceRecord = {
      record_id: 'AI-INFER-1', model_id: 'AI-MODEL-1', model_sha256: 'a'.repeat(64), model_manifest_snapshot: models[0],
      capture_id: 'LIVE', capture_data_sha256: 'hash', selected_time_seconds: [0, 0.002], selected_frequency_hz: null,
      input_transformation: 'iq_tensor', input_tensor_shape: [1, 2, 4096], input_dtype: 'float32', normalization_applied: 'none',
      inference_timestamp_utc: '2026-01-01T00:00:01Z', software_backend: 'onnxruntime==1.18.0',
      raw_output: [0.1, 0.9], raw_output_shape: [1, 2],
      interpretation: { kind: 'classification', predicted_class: 'QPSK', score: 0.9, score_type: 'probability' },
      compatibility: { verdict: 'UNKNOWN', checks: [{ field: 'sample_rate_hz', capture_value: 2_000_000, model_value: null, matched: null, note: '' }] },
      capture_latency_ms: 12, inference_latency_ms: 8, total_latency_ms: 20,
    };
    const fetchImpl = vi.fn((url: string) => {
      if (url.includes('/models')) return Promise.resolve(jsonResponse(models));
      if (url.includes('/status')) return Promise.resolve(jsonResponse({ enabled: true, capture_bridge_available: true, live_inference_available: true }));
      if (url.includes('/inference/live')) return Promise.resolve(jsonResponse(inferenceRecord));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchImpl);

    const { result } = renderHook(() => useAiLiveDetection({ frequencyInfo: freq(2_440_000_000), onDetection }));
    await waitFor(() => expect(result.current.models).toHaveLength(1));
    act(() => result.current.setSelectedModelId('AI-MODEL-1'));

    await act(async () => { await result.current.runOnce(); });

    expect(fetchImpl.mock.calls.some((call) => String(call[0]).includes('/inference/live'))).toBe(true);
    expect(result.current.detections).toHaveLength(1);
    expect(result.current.detections[0].summary).toMatch(/QPSK/);
    expect(result.current.detections[0].totalLatencyMs).toBe(20);
    expect(onDetection).toHaveBeenCalledTimes(1);
    expect(result.current.pollCount).toBe(1);
  });

  it('surfaces a real API error via latestError without throwing', async () => {
    const models = [manifest()];
    const fetchImpl = vi.fn((url: string) => {
      if (url.includes('/models')) return Promise.resolve(jsonResponse(models));
      if (url.includes('/status')) return Promise.resolve(jsonResponse({ enabled: true, capture_bridge_available: true, live_inference_available: true }));
      if (url.includes('/inference/live')) return Promise.resolve(new Response('no live SDR', { status: 400 }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchImpl);

    const { result } = renderHook(() => useAiLiveDetection({ frequencyInfo: freq(2_440_000_000) }));
    await waitFor(() => expect(result.current.models).toHaveLength(1));
    act(() => result.current.setSelectedModelId('AI-MODEL-1'));

    await act(async () => { await result.current.runOnce(); });

    expect(result.current.latestError).toMatch(/400/);
    expect(result.current.detections).toHaveLength(0);
  });

  it('runOnce() refuses a guaranteed shape mismatch without ever calling the backend, and stops continuous mode', async () => {
    // The exact real bug report: a rank-4 image-like model (combined_model.onnx,
    // [None,224,224,3]) selected with the default 'iq_tensor' representation
    // (rank 3) -- previously hammered /inference/live every 800ms forever with
    // the same guaranteed HTTP 400 ONNXRuntimeError.
    const models = [manifest({ tensor_shape: [null, 224, 224, 3] })];
    const fetchImpl = vi.fn((url: string) => {
      if (url.includes('/models')) return Promise.resolve(jsonResponse(models));
      if (url.includes('/status')) return Promise.resolve(jsonResponse({ enabled: true, capture_bridge_available: true, live_inference_available: true }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchImpl);

    const { result } = renderHook(() => useAiLiveDetection({ frequencyInfo: freq(2_440_000_000) }));
    await waitFor(() => expect(result.current.models).toHaveLength(1));
    act(() => result.current.setSelectedModelId('AI-MODEL-1'));
    act(() => result.current.setContinuousEnabled(true));

    await waitFor(() => expect(result.current.continuousEnabled).toBe(false));

    expect(fetchImpl.mock.calls.some((call) => String(call[0]).includes('/inference/live'))).toBe(false);
    expect(result.current.latestError).toMatch(/rank-4/);
    expect(result.current.representationApplicability?.compatible).toBe(false);
  });

  it('auto-stops continuous mode after 3 consecutive backend failures instead of retrying forever', async () => {
    const models = [manifest()]; // no declared shape -- passes the pre-flight check, so it really hits the backend
    const fetchImpl = vi.fn((url: string) => {
      if (url.includes('/models')) return Promise.resolve(jsonResponse(models));
      if (url.includes('/status')) return Promise.resolve(jsonResponse({ enabled: true, capture_bridge_available: true, live_inference_available: true }));
      if (url.includes('/inference/live')) return Promise.resolve(new Response('persistent failure', { status: 400 }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchImpl);

    const { result } = renderHook(() => useAiLiveDetection({ frequencyInfo: freq(2_440_000_000) }));
    await waitFor(() => expect(result.current.models).toHaveLength(1));
    act(() => result.current.setSelectedModelId('AI-MODEL-1'));
    act(() => result.current.setContinuousEnabled(true));

    await waitFor(() => expect(result.current.continuousEnabled).toBe(false), { timeout: 10_000 });

    const liveCalls = fetchImpl.mock.calls.filter((call) => String(call[0]).includes('/inference/live'));
    expect(liveCalls.length).toBe(3);
    expect(result.current.latestError).toMatch(/Stopped after 3 consecutive failures/);
  });
});
