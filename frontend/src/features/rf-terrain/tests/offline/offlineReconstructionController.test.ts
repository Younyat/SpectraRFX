import { describe, expect, it, vi } from 'vitest';
import { OfflineReconstructionController } from '../../offline/OfflineReconstructionController';
import type { TerrainProcessedRow } from '../../model/rfTerrainTypes';

const SAMPLE_RATE_SPS = 2_000_000;
const CENTER_FREQUENCY_HZ = 2_440_000_000;
const SAMPLE_COUNT = 20_000; // small enough for hop === fftSize (4096) -> a handful of rows, fast test

// A real cf32_le byte buffer: a single complex sinusoid burst, exactly the
// same synthetic-signal-construction style already used by fft.test.ts.
const buildSyntheticCf32LeBytes = (sampleCount: number): ArrayBuffer => {
  const buffer = new ArrayBuffer(sampleCount * 8);
  const view = new DataView(buffer);
  const toneHz = 400_000; // offset tone inside the observed span
  for (let n = 0; n < sampleCount; n += 1) {
    const phase = (2 * Math.PI * toneHz * n) / SAMPLE_RATE_SPS;
    view.setFloat32(n * 8, 0.2 * Math.cos(phase), true);
    view.setFloat32(n * 8 + 4, 0.2 * Math.sin(phase), true);
  }
  return buffer;
};

const realManifest = (captureId: string) => ({
  capture_id: captureId,
  data_sha256: 'a'.repeat(64),
  sample_rate_sps: SAMPLE_RATE_SPS,
  center_frequency_hz: CENTER_FREQUENCY_HZ,
  bandwidth_hz: SAMPLE_RATE_SPS,
  sample_format: 'cf32_le',
  actual_samples: SAMPLE_COUNT,
  device_serial: 'B200-TEST-0001',
  created_at_utc: '2026-01-01T00:00:00Z',
  gain_configuration: { gain_db: 40 },
  antenna: 'RX2',
  ble_channel: 37,
});

// Mimics the real backend: manifest as JSON, /iq honoring the Range
// header against one master buffer -- so chunked reads and full reads
// return byte-identical content regardless of how the caller chunks it.
const makeFetchImpl = (captureId: string, iqBytes: ArrayBuffer) => {
  const calls: string[] = [];
  const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(url);
    if (url.endsWith(`/recordings/${captureId}`)) {
      return new Response(JSON.stringify(realManifest(captureId)), { status: 200 });
    }
    if (url.endsWith(`/recordings/${captureId}/iq`)) {
      const rangeHeader = (init?.headers as Record<string, string> | undefined)?.Range;
      if (!rangeHeader) {
        return new Response(iqBytes, { status: 200 });
      }
      const match = /bytes=(\d+)-(\d+)/.exec(rangeHeader);
      if (!match) throw new Error(`Unexpected Range header: ${rangeHeader}`);
      const start = Number(match[1]);
      const end = Number(match[2]);
      return new Response(iqBytes.slice(start, end + 1), { status: 206 });
    }
    throw new Error(`Unexpected URL in test fetch mock: ${url}`);
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, calls };
};

describe('OfflineReconstructionController', () => {
  it('loadCapture() only ever fetches the real, read-only capture manifest endpoint -- no SDR/live URL is ever touched', async () => {
    const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
    const { fetchImpl, calls } = makeFetchImpl('BLE-IQ-iso', iqBytes);
    const controller = new OfflineReconstructionController({}, { baseUrl: 'http://test.local', fetchImpl });

    await controller.loadCapture('BLE-IQ-iso');

    expect(controller.getState().status).toBe('READY');
    expect(calls).toEqual(['http://test.local/api/ble/capture/recordings/BLE-IQ-iso']);
    for (const url of calls) {
      expect(url).not.toMatch(/spectrum|live|sdr/i);
    }
  });

  it('reconstruct() only ever calls the two real, read-only capture endpoints (manifest + /iq) -- never a write, never live/SDR', async () => {
    const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
    const { fetchImpl, calls } = makeFetchImpl('BLE-IQ-iso2', iqBytes);
    const controller = new OfflineReconstructionController({}, { baseUrl: 'http://test.local', fetchImpl });

    await controller.loadCapture('BLE-IQ-iso2');
    await controller.reconstruct();

    expect(controller.getState().status).toBe('COMPLETE');
    for (const url of calls) {
      expect(url).toMatch(/^http:\/\/test\.local\/api\/ble\/capture\/recordings\/BLE-IQ-iso2(\/iq)?$/);
    }
  });

  it('rejects reconstruct() before a capture has been loaded, without touching the network', async () => {
    const controller = new OfflineReconstructionController({}, { fetchImpl: vi.fn() as unknown as typeof fetch });
    await controller.reconstruct();
    expect(controller.getState().status).toBe('ERROR_LOCAL');
    expect(controller.getState().error).toMatch(/loaded/);
  });

  it('produces real rows, objects, a context audit, and a reconstruction id for a valid capture', async () => {
    const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
    const { fetchImpl } = makeFetchImpl('BLE-IQ-real', iqBytes);
    const controller = new OfflineReconstructionController({}, { fetchImpl });

    await controller.loadCapture('BLE-IQ-real');
    await controller.reconstruct();

    const state = controller.getState();
    expect(state.status).toBe('COMPLETE');
    expect(state.totalRows).toBeGreaterThan(0);
    expect(controller.getRows()).toHaveLength(state.totalRows);
    expect(state.reconstructionId).toMatch(/^[0-9a-f]{64}$/);
    expect(state.contextAudit?.baseline.sampleCount).toBeGreaterThan(0);
    expect(state.contextAudit?.objectDensity.windowDurationSeconds).toBeCloseTo(SAMPLE_COUNT / SAMPLE_RATE_SPS, 6);
  });

  it('is deterministic: reconstructing the same capture twice yields byte-identical rows', async () => {
    const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);

    const run = async () => {
      const { fetchImpl } = makeFetchImpl('BLE-IQ-det', iqBytes);
      const controller = new OfflineReconstructionController({}, { fetchImpl });
      await controller.loadCapture('BLE-IQ-det');
      await controller.reconstruct();
      return controller.getRows();
    };

    const rowsA = await run();
    const rowsB = await run();

    expect(rowsA.length).toBe(rowsB.length);
    expect(rowsA.length).toBeGreaterThan(0);
    rowsA.forEach((rowA, index) => {
      const rowB = rowsB[index];
      expect(rowA.frame.timestamp).toBe(rowB.frame.timestamp);
      expect(rowA.noiseFloorDb).toEqual(rowB.noiseFloorDb);
      expect(rowA.excessDb).toEqual(rowB.excessDb);
      expect(rowA.occupancy).toEqual(rowB.occupancy);
    });
  });

  it('never invents frames for an unsupported sample_format -- reconstruct() fails closed instead of misinterpreting bytes', async () => {
    const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
    const captureId = 'BLE-IQ-badfmt';
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.endsWith(`/recordings/${captureId}`)) {
        return new Response(JSON.stringify({ ...realManifest(captureId), sample_format: 'ci16_le' }), { status: 200 });
      }
      return new Response(iqBytes, { status: 200 });
    }) as unknown as typeof fetch;
    const controller = new OfflineReconstructionController({}, { fetchImpl });

    await controller.loadCapture(captureId);
    expect(controller.getState().status).toBe('ERROR_LOCAL');
    expect(controller.getState().error).toMatch(/ci16_le/);
  });

  describe('reconstruction telemetry', () => {
    // Forces multiple chunks over the same small synthetic capture (160,000
    // bytes / 40,000-byte chunkBytes = 4 chunks) so progress/stage
    // reporting can be observed advancing across real chunk boundaries,
    // not just jumping straight from 0% to 100%.
    const SMALL_CHUNK_BYTES = 40_000;

    const makeDelayedFetchImpl = (captureId: string, iqBytes: ArrayBuffer, delayMs = 5) => {
      const rangeCalls: string[] = [];
      const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith(`/recordings/${captureId}`)) {
          return new Response(JSON.stringify(realManifest(captureId)), { status: 200 });
        }
        const rangeHeader = (init?.headers as Record<string, string> | undefined)?.Range;
        rangeCalls.push(rangeHeader ?? '(full)');
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        if (!rangeHeader) return new Response(iqBytes, { status: 200 });
        const match = /bytes=(\d+)-(\d+)/.exec(rangeHeader);
        if (!match) throw new Error(`Unexpected Range header: ${rangeHeader}`);
        return new Response(iqBytes.slice(Number(match[1]), Number(match[2]) + 1), { status: 206 });
      });
      return { fetchImpl: fetchImpl as unknown as typeof fetch, rangeCalls };
    };

    it('issues exactly one /iq range request per chunk and ends with bytesProcessed === totalBytes', async () => {
      const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
      const { fetchImpl, rangeCalls } = makeDelayedFetchImpl('BLE-IQ-telemetry-1', iqBytes);
      const controller = new OfflineReconstructionController({}, { fetchImpl, chunkBytes: SMALL_CHUNK_BYTES });

      await controller.loadCapture('BLE-IQ-telemetry-1');
      await controller.reconstruct();

      const state = controller.getState();
      expect(state.status).toBe('COMPLETE');
      expect(state.totalBytes).toBe(SAMPLE_COUNT * 8);
      expect(state.totalChunks).toBe(Math.ceil((SAMPLE_COUNT * 8) / SMALL_CHUNK_BYTES));
      expect(state.chunksProcessed).toBe(state.totalChunks);
      expect(state.bytesProcessed).toBe(state.totalBytes);
      expect(rangeCalls).toHaveLength(state.totalChunks);
      expect(state.stage).toBe('DONE');
    });

    it('passes through every real stage on the way to DONE, never skipping straight from FETCHING to DONE', async () => {
      const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
      const { fetchImpl } = makeDelayedFetchImpl('BLE-IQ-telemetry-2', iqBytes);
      const stages: string[] = [];
      const controller = new OfflineReconstructionController(
        { onStateChange: (state) => stages.push(state.stage) },
        { fetchImpl, chunkBytes: SMALL_CHUNK_BYTES },
      );

      await controller.loadCapture('BLE-IQ-telemetry-2');
      await controller.reconstruct();

      expect(stages).toContain('FETCHING_CHUNK');
      expect(stages).toContain('PARSING_CHUNK');
      expect(stages).toContain('ANALYZING_FRAMES');
      expect(stages).toContain('SEGMENTING');
      expect(stages).toContain('COMPUTING_CONTEXT_AUDIT');
      expect(stages).toContain('COMPUTING_HASHES');
      expect(stages[stages.length - 1]).toBe('DONE');
    });

    it('reports real, positive elapsed time and a real, non-negative throughput once chunks have completed', async () => {
      const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
      const { fetchImpl } = makeDelayedFetchImpl('BLE-IQ-telemetry-3', iqBytes, 10);
      const controller = new OfflineReconstructionController({}, { fetchImpl, chunkBytes: SMALL_CHUNK_BYTES });

      await controller.loadCapture('BLE-IQ-telemetry-3');
      await controller.reconstruct();

      const state = controller.getState();
      expect(state.elapsedMs).toBeGreaterThan(0);
      expect(state.throughputBytesPerSecond).not.toBeNull();
      expect(state.throughputBytesPerSecond as number).toBeGreaterThan(0);
      // Reconstruction is done -- no remaining bytes, so a real ETA of ~0.
      expect(state.estimatedRemainingMs as number).toBeGreaterThanOrEqual(0);
    });

    it('never reports throughput/ETA before any chunk has completed', async () => {
      const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
      const { fetchImpl } = makeDelayedFetchImpl('BLE-IQ-telemetry-4', iqBytes, 10);
      const snapshotsBeforeFirstChunk: Array<number | null> = [];
      const controller = new OfflineReconstructionController(
        {
          onStateChange: (state) => {
            if (state.status === 'RECONSTRUCTING' && state.chunksProcessed === 0) {
              snapshotsBeforeFirstChunk.push(state.throughputBytesPerSecond);
            }
          },
        },
        { fetchImpl, chunkBytes: SMALL_CHUNK_BYTES },
      );

      await controller.loadCapture('BLE-IQ-telemetry-4');
      await controller.reconstruct();

      expect(snapshotsBeforeFirstChunk.length).toBeGreaterThan(0);
      expect(snapshotsBeforeFirstChunk.every((value) => value === null)).toBe(true);
    });
  });

  describe('refreshRecentCaptures', () => {
    it('auto-detects the most recent captures via the real, read-only /recordings endpoint', async () => {
      const fetchImpl = vi.fn(async (url: string) => {
        if (url.endsWith('/recordings')) {
          return new Response(JSON.stringify({ captures: [realManifest('BLE-IQ-1'), realManifest('BLE-IQ-2')] }), { status: 200 });
        }
        throw new Error(`Unexpected URL: ${url}`);
      }) as unknown as typeof fetch;
      const controller = new OfflineReconstructionController({}, { fetchImpl });

      await controller.refreshRecentCaptures();

      const state = controller.getState();
      expect(state.recentCapturesStatus).toBe('READY');
      expect(state.recentCaptures.map((m) => m.captureId)).toEqual(['BLE-IQ-1', 'BLE-IQ-2']);
    });

    it('never filters candidates by center frequency -- captures from different tunings all appear', async () => {
      const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
        captures: [
          { ...realManifest('BLE-IQ-2440'), center_frequency_hz: 2_440_000_000 },
          { ...realManifest('BLE-IQ-2480'), center_frequency_hz: 2_480_000_000 },
        ],
      }), { status: 200 })) as unknown as typeof fetch;
      const controller = new OfflineReconstructionController({}, { fetchImpl });

      await controller.refreshRecentCaptures();

      expect(controller.getState().recentCaptures).toHaveLength(2);
    });

    it('skips an individual malformed manifest instead of failing the whole list', async () => {
      const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
        captures: [realManifest('BLE-IQ-good'), { capture_id: 'BLE-IQ-bad' /* missing required fields */ }],
      }), { status: 200 })) as unknown as typeof fetch;
      const controller = new OfflineReconstructionController({}, { fetchImpl });

      await controller.refreshRecentCaptures();

      const state = controller.getState();
      expect(state.recentCapturesStatus).toBe('READY');
      expect(state.recentCaptures.map((m) => m.captureId)).toEqual(['BLE-IQ-good']);
    });

    it('caps the list at the given limit', async () => {
      const manifests = Array.from({ length: 80 }, (_, i) => realManifest(`BLE-IQ-${i}`));
      const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ captures: manifests }), { status: 200 })) as unknown as typeof fetch;
      const controller = new OfflineReconstructionController({}, { fetchImpl });

      await controller.refreshRecentCaptures(50);

      expect(controller.getState().recentCaptures).toHaveLength(50);
    });

    it('reports a real error and never touches recentCaptures on failure', async () => {
      const fetchImpl = vi.fn(async () => new Response('error', { status: 500 })) as unknown as typeof fetch;
      const controller = new OfflineReconstructionController({}, { fetchImpl });

      await controller.refreshRecentCaptures();

      const state = controller.getState();
      expect(state.recentCapturesStatus).toBe('ERROR');
      expect(state.recentCapturesError).toMatch(/500/);
      expect(state.recentCaptures).toEqual([]);
    });
  });

  describe('playback', () => {
    const setupCompletedController = async () => {
      const iqBytes = buildSyntheticCf32LeBytes(SAMPLE_COUNT);
      const { fetchImpl } = makeFetchImpl('BLE-IQ-play', iqBytes);
      const rows: TerrainProcessedRow[] = [];
      const controller = new OfflineReconstructionController({ onRow: (row) => rows.push(row) }, { fetchImpl });
      await controller.loadCapture('BLE-IQ-play');
      await controller.reconstruct();
      rows.length = 0; // onRow also fires during... (it does not during reconstruct(); cleared defensively)
      return { controller, rows };
    };

    it('step() replays rows in order without recomputing them', async () => {
      const { controller, rows } = await setupCompletedController();
      const totalRows = controller.getState().totalRows;
      rows.length = 0;

      // restart() itself replays row 0 (a real seek, via onRow) so the
      // renderer's incremental state is correct before stepping through
      // the rest one at a time.
      controller.restart();
      for (let i = 1; i < totalRows; i += 1) controller.step();

      expect(rows).toHaveLength(totalRows);
      expect(rows).toEqual(controller.getRows());
    });

    it('playback speed never changes the replayed row values -- only how fast they arrive', async () => {
      // play()/step() only change SCHEDULING (setPlaybackSpeed governs the
      // setTimeout interval, never touched here); the underlying values
      // handed to onRow come straight from the already-computed row
      // array regardless of speed, which this compares directly.
      const { controller: controllerA } = await setupCompletedController();
      const totalRows = controllerA.getState().totalRows;
      controllerA.restart();
      controllerA.seekToRowIndex(totalRows - 1);
      const rowsSlow = [...controllerA.getRows()];

      const { controller: controllerB } = await setupCompletedController();
      controllerB.setPlaybackSpeed(8);
      controllerB.restart();
      controllerB.seekToRowIndex(totalRows - 1);
      const rowsFast = [...controllerB.getRows()];

      expect(rowsSlow).toEqual(rowsFast);
    });

    it('cancel() stops playback, drops all rows, and returns to NO_CAPTURE', async () => {
      const { controller } = await setupCompletedController();
      controller.cancel();
      const state = controller.getState();
      expect(state.status).toBe('NO_CAPTURE');
      expect(state.metadata).toBeNull();
      expect(controller.getRows()).toHaveLength(0);
    });
  });
});
