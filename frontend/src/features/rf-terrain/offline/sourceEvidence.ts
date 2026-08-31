import { sampleIndexToTimestampMs } from '../engine/offline/spectrumGenerator';

export interface SourceEvidence {
  captureId: string;
  dataSha256: string;
  sampleRateSps: number;
  fftSize: number;
}

export interface SourceSampleRange {
  startSampleIndex: number;
  endSampleIndex: number;
  startTimeSeconds: number;
  endTimeSeconds: number;
}

// Exact inverse of sampleIndexToTimestampMs -- a FSEI selection's
// `timestamp` IS `(sampleIndex / sampleRateSps) * 1000 + 1` by construction
// (spectrumGenerator.ts), so the original sample index is recovered
// exactly (rounded only for the inevitable floating-point round-trip),
// never approximated or looked up from a second, independent source. The
// FFT window this row was computed from spans
// [startSampleIndex, startSampleIndex + fftSize - 1] in the original
// preserved capture (spec's "SOURCE EVIDENCE": link a Terrain Object back
// to its exact sample range in the original I/Q).
export const deriveSourceSampleRange = (selectionTimestampMs: number, evidence: SourceEvidence): SourceSampleRange => {
  const startSampleIndex = Math.round(((selectionTimestampMs - 1) / 1000) * evidence.sampleRateSps);
  const endSampleIndex = startSampleIndex + evidence.fftSize - 1;
  return {
    startSampleIndex,
    endSampleIndex,
    startTimeSeconds: startSampleIndex / evidence.sampleRateSps,
    endTimeSeconds: endSampleIndex / evidence.sampleRateSps,
  };
};

// Round-trip sanity used by callers/tests that want to confirm a
// timestamp really did originate from this evidence's sample rate
// (defensive -- never trust a selection blindly to be OFFLINE-sourced
// just because an evidence object happens to be present).
export const isConsistentWithEvidence = (selectionTimestampMs: number, evidence: SourceEvidence): boolean => {
  const { startSampleIndex } = deriveSourceSampleRange(selectionTimestampMs, evidence);
  const roundTripped = sampleIndexToTimestampMs(startSampleIndex, evidence.sampleRateSps);
  return Math.abs(roundTripped - selectionTimestampMs) < 1e-6;
};
