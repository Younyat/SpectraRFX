// Parses raw preserved-capture bytes into I/Q sample arrays. The real,
// audited campaign format is `cf32_le` (SigMF `core:datatype`) --
// interleaved little-endian float32 I,Q,I,Q..., 8 bytes per complex
// sample, no header in the data file itself (see
// capture_manifest.json's real `sample_format` field). `ci16_le`/`ci8`
// are schema-supported upstream but the frozen campaign protocol never
// produced them -- this module only implements what is real.
export const BYTES_PER_CF32LE_SAMPLE = 8;

export interface SampleFormatSpec {
  bytesPerSample: number;
  parse: (buffer: ArrayBuffer) => { re: Float32Array; im: Float32Array };
}

const parseCf32Le = (buffer: ArrayBuffer): { re: Float32Array; im: Float32Array } => {
  if (buffer.byteLength % BYTES_PER_CF32LE_SAMPLE !== 0) {
    throw new Error(`cf32_le buffer length ${buffer.byteLength} is not a multiple of ${BYTES_PER_CF32LE_SAMPLE} bytes`);
  }
  const sampleCount = buffer.byteLength / BYTES_PER_CF32LE_SAMPLE;
  const view = new DataView(buffer);
  const re = new Float32Array(sampleCount);
  const im = new Float32Array(sampleCount);
  for (let i = 0; i < sampleCount; i += 1) {
    const offset = i * BYTES_PER_CF32LE_SAMPLE;
    re[i] = view.getFloat32(offset, true);
    im[i] = view.getFloat32(offset + 4, true);
  }
  return { re, im };
};

// Only the one real, campaign-frozen format is implemented -- an
// unsupported `sample_format` fails closed (§ "never fabricate a reading
// for a format this module cannot honestly parse") rather than silently
// misinterpreting bytes.
export const SUPPORTED_SAMPLE_FORMATS: Record<string, SampleFormatSpec> = {
  cf32_le: { bytesPerSample: BYTES_PER_CF32LE_SAMPLE, parse: parseCf32Le },
};

export const getSampleFormatSpec = (sampleFormat: string): SampleFormatSpec => {
  const spec = SUPPORTED_SAMPLE_FORMATS[sampleFormat];
  if (!spec) {
    throw new Error(`Unsupported capture sample_format "${sampleFormat}" -- only cf32_le is implemented (the real, frozen campaign format)`);
  }
  return spec;
};
