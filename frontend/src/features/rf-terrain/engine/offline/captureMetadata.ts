import { getSampleFormatSpec } from './iqBytes';

// Real fields sourced from `capture_manifest.json`
// (schema_version "ble-sdr-capture-manifest-v1",
// backend/app/infrastructure/ble/capture/ble_capture_job_manager.py) --
// audited from an actual on-disk manifest before writing this, never
// invented. Fields NOT present in the real schema (notably
// `calibration_id`) stay `null` here rather than being fabricated.
export interface OfflineCaptureMetadata {
  captureId: string;
  dataSha256: string;
  sampleRateSps: number;
  centerFrequencyHz: number;
  bandwidthHz: number;
  sampleFormat: string;
  bytesPerSample: number;
  sampleCount: number;
  deviceSerial: string | null;
  createdAtUtc: string | null;
  gainDb: number | null;
  antenna: string | null;
  bleChannel: number | null;
  // Not a real field in capture_manifest.json today -- always null,
  // rendered as an honest "not documented" in the Evidence panel rather
  // than silently omitted.
  calibrationId: null;
}

export type CaptureMetadataValidation =
  | { valid: true; metadata: OfflineCaptureMetadata }
  | { valid: false; reason: string };

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

// Validates a raw manifest JSON payload (from GET
// /api/ble/capture/recordings/{capture_id}) and extracts exactly the real
// fields this module needs -- fails closed (with a specific reason) on
// anything missing or malformed, never guesses a fallback value for a
// field that determines scientific interpretation (sample rate, center
// frequency, sample format).
export const validateCaptureManifest = (raw: unknown): CaptureMetadataValidation => {
  if (typeof raw !== 'object' || raw === null) {
    return { valid: false, reason: 'Manifest is not a JSON object' };
  }
  const m = raw as Record<string, unknown>;

  const captureId = m.capture_id;
  if (typeof captureId !== 'string' || captureId.length === 0) {
    return { valid: false, reason: 'Missing or invalid capture_id' };
  }
  const dataSha256 = m.data_sha256;
  if (typeof dataSha256 !== 'string' || dataSha256.length === 0) {
    return { valid: false, reason: 'Missing or invalid data_sha256' };
  }
  const sampleRateSps = m.sample_rate_sps;
  if (!isFiniteNumber(sampleRateSps) || sampleRateSps <= 0) {
    return { valid: false, reason: 'Missing or invalid sample_rate_sps' };
  }
  const centerFrequencyHz = m.center_frequency_hz;
  if (!isFiniteNumber(centerFrequencyHz)) {
    return { valid: false, reason: 'Missing or invalid center_frequency_hz' };
  }
  const bandwidthHz = m.bandwidth_hz;
  if (!isFiniteNumber(bandwidthHz) || bandwidthHz <= 0) {
    return { valid: false, reason: 'Missing or invalid bandwidth_hz' };
  }
  const sampleFormat = m.sample_format;
  if (typeof sampleFormat !== 'string') {
    return { valid: false, reason: 'Missing or invalid sample_format' };
  }
  let bytesPerSample: number;
  try {
    bytesPerSample = getSampleFormatSpec(sampleFormat).bytesPerSample;
  } catch (error) {
    return { valid: false, reason: error instanceof Error ? error.message : String(error) };
  }

  const actualSamples = m.actual_samples;
  const actualSizeBytes = m.actual_size_bytes ?? m.actual_file_size_bytes;
  let sampleCount: number;
  if (isFiniteNumber(actualSamples) && actualSamples > 0) {
    sampleCount = actualSamples;
  } else if (isFiniteNumber(actualSizeBytes) && actualSizeBytes > 0) {
    sampleCount = Math.floor(actualSizeBytes / bytesPerSample);
  } else {
    return { valid: false, reason: 'Missing both actual_samples and actual_size_bytes -- cannot determine capture length' };
  }
  if (sampleCount <= 0) {
    return { valid: false, reason: 'Computed sample count is not positive' };
  }

  const gainConfiguration = m.gain_configuration as Record<string, unknown> | undefined;
  const gainDb = gainConfiguration && isFiniteNumber(gainConfiguration.gain_db) ? gainConfiguration.gain_db : null;

  return {
    valid: true,
    metadata: {
      captureId,
      dataSha256,
      sampleRateSps,
      centerFrequencyHz,
      bandwidthHz,
      sampleFormat,
      bytesPerSample,
      sampleCount,
      deviceSerial: typeof m.device_serial === 'string' ? m.device_serial : null,
      createdAtUtc: typeof m.created_at_utc === 'string' ? m.created_at_utc : null,
      gainDb,
      antenna: typeof m.antenna === 'string' ? m.antenna : null,
      bleChannel: isFiniteNumber(m.ble_channel) ? m.ble_channel : null,
      calibrationId: null,
    },
  };
};
