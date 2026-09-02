import { describe, expect, it } from 'vitest';
import { AiDetectionOverlay } from '../render/AiDetectionOverlay';

const box = (id: string, overrides: Partial<{ xMin: number; xMax: number; meshRow: number }> = {}) => ({
  id,
  xMin: overrides.xMin ?? -5,
  xMax: overrides.xMax ?? 5,
  meshRow: overrides.meshRow ?? 0,
  label: `label-${id}`,
  color: 0xf97316,
});

describe('AiDetectionOverlay', () => {
  it('starts empty', () => {
    const overlay = new AiDetectionOverlay();
    expect(overlay.group.children.length).toBe(0);
  });

  it('upsert adds a new cage positioned at the box center, row 0 at the front', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a', { xMin: 0, xMax: 10, meshRow: 0 }));
    expect(overlay.group.children.length).toBe(1);
    const cage = overlay.group.children[0];
    expect(cage.position.x).toBe(5);
    expect(cage.position.z).toBeCloseTo(0); // -this.row at row 0 is -0, mathematically equal to 0
  });

  it('multiple simultaneous detections are independent (unlike the single-marker selection reticle)', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a', { xMin: 0, xMax: 10 }));
    overlay.upsert(box('b', { xMin: 20, xMax: 30 }));
    expect(overlay.group.children.length).toBe(2);
  });

  it('re-upserting the same id updates it in place rather than adding a duplicate', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a', { xMin: 0, xMax: 10 }));
    overlay.upsert(box('a', { xMin: 100, xMax: 110 }));
    expect(overlay.group.children.length).toBe(1);
    expect(overlay.group.children[0].position.x).toBe(105);
  });

  it('ageByOneRow shifts every detection back by one row', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a', { meshRow: 0 }));
    overlay.ageByOneRow(240);
    expect(overlay.group.children[0].position.z).toBe(-1);
  });

  it('removes a detection once it ages past the visible history depth', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a', { meshRow: 0 }));
    for (let i = 0; i < 5; i += 1) overlay.ageByOneRow(3);
    expect(overlay.group.children.length).toBe(0);
  });

  it('remove() deletes a specific detection without affecting others', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a'));
    overlay.upsert(box('b'));
    overlay.remove('a');
    expect(overlay.group.children.length).toBe(1);
  });

  it('clear() removes every detection', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a'));
    overlay.upsert(box('b'));
    overlay.clear();
    expect(overlay.group.children.length).toBe(0);
  });

  it('dispose() releases resources without throwing', () => {
    const overlay = new AiDetectionOverlay();
    overlay.upsert(box('a'));
    expect(() => overlay.dispose()).not.toThrow();
  });
});
