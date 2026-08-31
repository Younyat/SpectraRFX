import { describe, expect, it } from 'vitest';
import {
  OFFLINE_RECONSTRUCTION_PROFILE_V1,
  computeHopSizeSamples,
  computeProfileConfigHash,
  computeReconstructionId,
} from '../../engine/offline/reconstructionProfile';

describe('computeHopSizeSamples', () => {
  it('derives a hop size close to fftSize/targetRowCount for a long capture', () => {
    const hop = computeHopSizeSamples(OFFLINE_RECONSTRUCTION_PROFILE_V1, 40_000_000);
    expect(hop).toBe(40_000);
  });

  it('never returns a hop smaller than the FFT size (no fabricated finer time resolution)', () => {
    const hop = computeHopSizeSamples(OFFLINE_RECONSTRUCTION_PROFILE_V1, 1000);
    expect(hop).toBe(OFFLINE_RECONSTRUCTION_PROFILE_V1.fftSize);
  });
});

describe('computeProfileConfigHash', () => {
  it('is deterministic for the same profile', async () => {
    const a = await computeProfileConfigHash(OFFLINE_RECONSTRUCTION_PROFILE_V1);
    const b = await computeProfileConfigHash(OFFLINE_RECONSTRUCTION_PROFILE_V1);
    expect(a).toBe(b);
    expect(a).toMatch(/^[0-9a-f]{64}$/);
  });

  it('changes if any profile parameter changes', async () => {
    const a = await computeProfileConfigHash(OFFLINE_RECONSTRUCTION_PROFILE_V1);
    const b = await computeProfileConfigHash({ ...OFFLINE_RECONSTRUCTION_PROFILE_V1, fftSize: 2048 });
    expect(a).not.toBe(b);
  });
});

describe('computeReconstructionId', () => {
  it('is deterministic for the same (iq hash, profile hash, commit) triple', async () => {
    const a = await computeReconstructionId('iqhash123', 'profilehashabc', 'commit456');
    const b = await computeReconstructionId('iqhash123', 'profilehashabc', 'commit456');
    expect(a).toBe(b);
  });

  it('changes if the source I/Q hash changes, even with everything else fixed', async () => {
    const a = await computeReconstructionId('iqhashA', 'profilehashabc', 'commit456');
    const b = await computeReconstructionId('iqhashB', 'profilehashabc', 'commit456');
    expect(a).not.toBe(b);
  });
});
