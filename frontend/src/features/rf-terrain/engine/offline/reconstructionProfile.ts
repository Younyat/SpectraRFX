import { isPowerOfTwo } from './fft';

// Frozen analysis parameters for offline reconstruction (spec §27). A
// profile is versioned and hashed so "same IQ + same metadata + same
// profile + same software version -> same output" (§28 determinism) is a
// checkable claim, not an assertion.
export interface OfflineReconstructionProfile {
  profileId: string;
  profileVersion: number;
  fftSize: number;
  windowType: 'hann';
  // Not a raw hop-size constant: derived per-capture from the real
  // sample rate/duration so a wildly different capture length still
  // produces a reasonable, bounded row count for the terrain's ring
  // buffer (RESET's `capacity` is caller-specified, not hardcoded --
  // this profile decides what to pass).
  targetRowCount: number;
}

export const OFFLINE_RECONSTRUCTION_PROFILE_V1: OfflineReconstructionProfile = {
  profileId: 'offline-context-v1',
  profileVersion: 1,
  fftSize: 4096,
  windowType: 'hann',
  targetRowCount: 1000,
};

if (!isPowerOfTwo(OFFLINE_RECONSTRUCTION_PROFILE_V1.fftSize)) {
  throw new Error('OFFLINE_RECONSTRUCTION_PROFILE_V1.fftSize must be a power of two');
}

// Non-overlapping windows by default (hop === fftSize) unless the capture
// is short enough that fewer than `targetRowCount` non-overlapping
// windows fit -- in that case fftSize-sized hops are still used (never
// invented finer time resolution than the FFT block itself provides
// without explicit, documented overlap), simply yielding fewer rows than
// the target for a short capture.
export const computeHopSizeSamples = (profile: OfflineReconstructionProfile, sampleCount: number): number => {
  const evenHop = Math.floor(sampleCount / Math.max(1, profile.targetRowCount));
  return Math.max(profile.fftSize, evenHop);
};

const bufferToHex = (buffer: ArrayBuffer): string =>
  Array.from(new Uint8Array(buffer)).map((b) => b.toString(16).padStart(2, '0')).join('');

// SHA-256 over the profile's own frozen parameters (Web Crypto API,
// standard in both browsers and this project's test environment) --
// deterministic for the same profile object every time.
export const computeProfileConfigHash = async (profile: OfflineReconstructionProfile): Promise<string> => {
  const canonical = JSON.stringify({
    profileId: profile.profileId,
    profileVersion: profile.profileVersion,
    fftSize: profile.fftSize,
    windowType: profile.windowType,
    targetRowCount: profile.targetRowCount,
  });
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return bufferToHex(digest);
};

// Reproducibility fingerprint (spec §29): identifies one real
// reconstruction run by the three things that actually determine its
// output -- the source bytes, the analysis profile, and the code that ran
// it. Same three inputs -> same fingerprint, always.
export const computeReconstructionId = async (iqSha256: string, profileConfigHash: string, softwareCommit: string): Promise<string> => {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${iqSha256}:${profileConfigHash}:${softwareCommit}`));
  return bufferToHex(digest);
};
