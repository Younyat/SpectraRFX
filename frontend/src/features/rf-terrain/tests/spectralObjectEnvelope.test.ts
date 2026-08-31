import { describe, expect, it } from 'vitest';
import { buildSpectralObjectEnvelope, EnvelopeSourceRow } from '../engine/spectralObjectEnvelope';

const FREQS = [2_400_000_000, 2_400_100_000, 2_400_200_000, 2_400_300_000, 2_400_400_000];

const row = (meshRow: number, excessDb: number[]): EnvelopeSourceRow => ({
  meshRow,
  excessDb,
  frequencyHz: FREQS,
});

describe('buildSpectralObjectEnvelope', () => {
  it('returns null for an empty row list', () => {
    expect(buildSpectralObjectEnvelope([], FREQS[1], FREQS[3], 6)).toBeNull();
  });

  it('returns null when the sub-window is too small to triangulate (a single row or column)', () => {
    const rows = [row(0, [0, 20, 20, 20, 0])];
    expect(buildSpectralObjectEnvelope(rows, FREQS[1], FREQS[3], 6)).toBeNull();
  });

  it('builds a heights grid sized to the real frequency/time sub-window', () => {
    const rows = [row(0, [0, 20, 20, 20, 0]), row(1, [0, 20, 20, 20, 0])];
    const envelope = buildSpectralObjectEnvelope(rows, FREQS[1], FREQS[3], 6);
    expect(envelope).not.toBeNull();
    expect(envelope!.subRows).toBe(2);
    expect(envelope!.subCols).toBe(3);
    expect(envelope!.colOffset).toBe(1);
    expect(envelope!.meshRowOffset).toBe(0);
  });

  it('masks out cells at or below the grow threshold', () => {
    const rows = [row(0, [0, 20, 3, 20, 0]), row(1, [0, 20, 3, 20, 0])];
    const envelope = buildSpectralObjectEnvelope(rows, FREQS[1], FREQS[3], 6)!;
    // Middle column (index 1 within the sub-window) is below threshold.
    expect(envelope.mask[0 * envelope.subCols + 1]).toBe(0);
    expect(envelope.mask[0 * envelope.subCols + 0]).toBe(1);
  });

  it('a missing row inside the time range leaves its cells unmasked (honest "no data"), not fabricated', () => {
    const rows = [row(0, [0, 20, 20, 20, 0]), row(2, [0, 20, 20, 20, 0])];
    // meshRow=1 is missing entirely -- subRows spans 0..2 (3 rows).
    const envelope = buildSpectralObjectEnvelope(rows, FREQS[1], FREQS[3], 6)!;
    expect(envelope.subRows).toBe(3);
    const middleRowStart = 1 * envelope.subCols;
    expect(Array.from(envelope.mask.slice(middleRowStart, middleRowStart + envelope.subCols))).toEqual([0, 0, 0]);
  });

  it('smooths a masked plateau toward its own local values without leaking in zeros from outside the mask', () => {
    const rows = [
      row(0, [0, 20, 20, 20, 0]),
      row(1, [0, 20, 20, 20, 0]),
      row(2, [0, 20, 20, 20, 0]),
    ];
    const envelope = buildSpectralObjectEnvelope(rows, FREQS[1], FREQS[3], 6)!;
    // Interior cell (center of a uniform 3x3 masked plateau) should stay
    // close to the original 20dB value -- a naive unmasked convolution
    // would pull it toward 0 near the plateau's own true edges instead.
    const centerIdx = 1 * envelope.subCols + 1;
    expect(envelope.heights[centerIdx]).toBeCloseTo(20, 5);
  });

  it('handles a reversed start/stop frequency argument order the same as forward order', () => {
    const rows = [row(0, [0, 20, 20, 20, 0]), row(1, [0, 20, 20, 20, 0])];
    const forward = buildSpectralObjectEnvelope(rows, FREQS[1], FREQS[3], 6)!;
    const reversed = buildSpectralObjectEnvelope(rows, FREQS[3], FREQS[1], 6)!;
    expect(reversed.colOffset).toBe(forward.colOffset);
    expect(reversed.subCols).toBe(forward.subCols);
  });
});
