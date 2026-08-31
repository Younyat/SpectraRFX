import { describe, expect, it } from 'vitest';
import { validateCaptureManifest } from '../../engine/offline/captureMetadata';

const realManifestShape = () => ({
  schema_version: 'ble-sdr-capture-manifest-v1',
  capture_id: 'BLE-IQ-0000c11f06c3',
  data_sha256: 'abc123',
  metadata_sha256: 'def456',
  sample_rate_sps: 4000000,
  center_frequency_hz: 2402000000,
  bandwidth_hz: 2000000,
  sample_format: 'cf32_le',
  actual_samples: 40000000,
  actual_size_bytes: 320000000,
  device_serial: 'E3R04Z1B2',
  created_at_utc: '2026-01-01T00:00:00Z',
  gain_configuration: { gain_db: 30 },
  antenna: 'TX/RX',
  ble_channel: 37,
});

describe('validateCaptureManifest', () => {
  it('accepts a real manifest shape and extracts every documented field', () => {
    const result = validateCaptureManifest(realManifestShape());
    expect(result.valid).toBe(true);
    if (!result.valid) return;
    expect(result.metadata).toMatchObject({
      captureId: 'BLE-IQ-0000c11f06c3',
      dataSha256: 'abc123',
      sampleRateSps: 4000000,
      centerFrequencyHz: 2402000000,
      bandwidthHz: 2000000,
      sampleFormat: 'cf32_le',
      bytesPerSample: 8,
      sampleCount: 40000000,
      deviceSerial: 'E3R04Z1B2',
      gainDb: 30,
      antenna: 'TX/RX',
      bleChannel: 37,
      calibrationId: null,
    });
  });

  it('derives sample count from actual_size_bytes when actual_samples is absent', () => {
    const manifest = realManifestShape() as Record<string, unknown>;
    delete manifest.actual_samples;
    const result = validateCaptureManifest(manifest);
    expect(result.valid).toBe(true);
    if (!result.valid) return;
    expect(result.metadata.sampleCount).toBe(40000000);
  });

  it('rejects a manifest missing capture_id', () => {
    const manifest = realManifestShape() as Record<string, unknown>;
    delete manifest.capture_id;
    const result = validateCaptureManifest(manifest);
    expect(result.valid).toBe(false);
  });

  it('rejects a manifest with an unsupported sample_format instead of guessing a byte layout', () => {
    const manifest = { ...realManifestShape(), sample_format: 'ci16_le' };
    const result = validateCaptureManifest(manifest);
    expect(result.valid).toBe(false);
    if (result.valid) return;
    expect(result.reason).toMatch(/Unsupported/);
  });

  it('rejects a non-object payload', () => {
    expect(validateCaptureManifest(null).valid).toBe(false);
    expect(validateCaptureManifest('not an object').valid).toBe(false);
  });

  it('never fabricates a calibration_id -- the real schema has none', () => {
    const result = validateCaptureManifest({ ...realManifestShape(), calibration_id: 'CAL-99' });
    expect(result.valid).toBe(true);
    if (!result.valid) return;
    // Even if a caller injects a calibration_id field, it is not a real
    // part of the schema this was audited against -- stays null.
    expect(result.metadata.calibrationId).toBeNull();
  });
});
