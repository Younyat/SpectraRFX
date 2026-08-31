import { describe, expect, it } from 'vitest';
import { SpectralObjectEnvelopeMesh } from '../render/SpectralObjectEnvelope';
import { buildSpectralObjectEnvelope, EnvelopeSourceRow } from '../engine/spectralObjectEnvelope';

const FREQS = [2_400_000_000, 2_400_100_000, 2_400_200_000, 2_400_300_000, 2_400_400_000];
const row = (meshRow: number, excessDb: number[]): EnvelopeSourceRow => ({ meshRow, excessDb, frequencyHz: FREQS });

const makeEnvelope = () => buildSpectralObjectEnvelope(
  [row(2, [0, 20, 20, 20, 0]), row(3, [0, 20, 20, 20, 0]), row(4, [0, 20, 20, 20, 0])],
  FREQS[1], FREQS[3], 6,
)!;

describe('SpectralObjectEnvelopeMesh', () => {
  it('starts hidden with no mesh built', () => {
    const overlay = new SpectralObjectEnvelopeMesh();
    expect(overlay.group.visible).toBe(false);
    expect(overlay.group.children).toHaveLength(0);
  });

  it('build() creates a visible mesh positioned at the envelope\'s meshRowOffset', () => {
    const overlay = new SpectralObjectEnvelopeMesh();
    overlay.build(makeEnvelope(), 64, 4);
    expect(overlay.group.visible).toBe(true);
    expect(overlay.group.children).toHaveLength(1);
    expect(overlay.group.position.z).toBe(-2);
  });

  it('ages back by one row per call, matching the reticle idiom', () => {
    const overlay = new SpectralObjectEnvelopeMesh();
    overlay.build(makeEnvelope(), 64, 4);
    const stillInView = overlay.ageByOneRow(240);
    expect(stillInView).toBe(true);
    expect(overlay.group.position.z).toBe(-3);
  });

  it('hides and reports OUT_OF_VIEW once aged past the visible history depth', () => {
    const overlay = new SpectralObjectEnvelopeMesh();
    overlay.build(makeEnvelope(), 64, 4);
    let wentOutOfView = false;
    for (let i = 0; i < 5; i += 1) {
      if (!overlay.ageByOneRow(3)) wentOutOfView = true;
    }
    expect(wentOutOfView).toBe(true);
    expect(overlay.group.visible).toBe(false);
  });

  it('rebuilding disposes the previous mesh instead of leaking it', () => {
    const overlay = new SpectralObjectEnvelopeMesh();
    overlay.build(makeEnvelope(), 64, 4);
    overlay.build(makeEnvelope(), 64, 4);
    expect(overlay.group.children).toHaveLength(1);
  });

  it('hide() and dispose() do not throw', () => {
    const overlay = new SpectralObjectEnvelopeMesh();
    overlay.build(makeEnvelope(), 64, 4);
    expect(() => overlay.hide()).not.toThrow();
    expect(() => overlay.dispose()).not.toThrow();
  });
});
