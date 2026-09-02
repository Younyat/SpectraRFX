import { describe, expect, it } from 'vitest';
import { lookupKnownRfTerm } from '../../ai/knownRfTerms';

describe('lookupKnownRfTerm', () => {
  it('matches a standard term exactly', () => {
    expect(lookupKnownRfTerm('BPSK')).toMatch(/Binary Phase Shift Keying/);
  });

  it('is case-insensitive', () => {
    expect(lookupKnownRfTerm('bpsk')).toMatch(/Binary Phase Shift Keying/);
  });

  it('tolerates spaces/underscores/hyphens', () => {
    expect(lookupKnownRfTerm('16-QAM')).toMatch(/16-ary Quadrature Amplitude Modulation/);
    expect(lookupKnownRfTerm('16_qam')).toMatch(/16-ary Quadrature Amplitude Modulation/);
  });

  it('returns null for an unknown/model-specific class name -- never a fabricated guess', () => {
    expect(lookupKnownRfTerm('DEMO_CLASS_A')).toBeNull();
    expect(lookupKnownRfTerm('class_3')).toBeNull();
  });
});
