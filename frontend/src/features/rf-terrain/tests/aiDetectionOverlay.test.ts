import { describe, expect, it } from 'vitest';
import type * as THREE from 'three';
import { AiDetectionOverlay } from '../render/AiDetectionOverlay';

const box = (id: string, overrides: Partial<{ xMin: number; xMax: number; meshRow: number; baseY: number; label: string }> = {}) => ({
  id,
  xMin: overrides.xMin ?? -5,
  xMax: overrides.xMax ?? 5,
  baseY: overrides.baseY ?? 0,
  meshRow: overrides.meshRow ?? 0,
  label: overrides.label ?? `label-${id}`,
  color: 0xf97316,
});

describe('AiDetectionOverlay', () => {
  it('starts empty', () => {
    const overlay = new AiDetectionOverlay(64);
    expect(overlay.group.children.length).toBe(0);
  });

  it('upsert adds a new cage positioned at the box center, row 0 at the front', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a', { xMin: 0, xMax: 10, meshRow: 0 }));
    expect(overlay.group.children.length).toBe(1);
    const cage = overlay.group.children[0];
    expect(cage.position.x).toBe(5);
    expect(cage.position.z).toBeCloseTo(0); // -this.row at row 0 is -0, mathematically equal to 0
  });

  it('sits with its base AT the real supplied peak height, not a fixed disconnected height', () => {
    const overlay = new AiDetectionOverlay(64); // boxHeight = max(4, cols/20) = 4
    overlay.upsert(box('a', { baseY: 12 }));
    const cage = overlay.group.children[0];
    expect(cage.position.y).toBe(12 + 2); // baseY + boxHeight/2
  });

  it('scales the box/label size off a wider terrain (cols) instead of a fixed prop size', () => {
    const narrow = new AiDetectionOverlay(64); // boxHeight = max(4, 64/20) = 4
    narrow.upsert(box('a', { baseY: 0 }));
    const wide = new AiDetectionOverlay(2000); // boxHeight = max(4, 2000/20) = 100
    wide.upsert(box('a', { baseY: 0 }));
    expect(wide.group.children[0].position.y).toBeGreaterThan(narrow.group.children[0].position.y);
  });

  it('carries a visible label sprite as a child of the cage', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a', { label: 'QPSK (0.87)' }));
    const cage = overlay.group.children[0];
    const sprite = cage.children.find((child) => (child as unknown as { isSprite?: boolean }).isSprite);
    expect(sprite).toBeDefined();
  });

  it('places the label BELOW the cage, not above it -- so a tall peak never pushes it into the fixed FREQUENCY/TIME/POWER HUD badges near the top of the screen', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a'));
    const cage = overlay.group.children[0];
    const sprite = cage.children.find((child) => (child as unknown as { isSprite?: boolean }).isSprite) as THREE.Sprite;
    expect(sprite.position.y).toBeLessThan(0);
  });

  it('multiple simultaneous detections are independent (unlike the single-marker selection reticle)', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a', { xMin: 0, xMax: 10 }));
    overlay.upsert(box('b', { xMin: 20, xMax: 30 }));
    expect(overlay.group.children.length).toBe(2);
  });

  it('re-upserting the same id updates it in place rather than adding a duplicate', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a', { xMin: 0, xMax: 10 }));
    overlay.upsert(box('a', { xMin: 100, xMax: 110 }));
    expect(overlay.group.children.length).toBe(1);
    expect(overlay.group.children[0].position.x).toBe(105);
  });

  it('ageByOneRow shifts every detection back by one row', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a', { meshRow: 0 }));
    overlay.ageByOneRow(240);
    expect(overlay.group.children[0].position.z).toBe(-1);
  });

  it('removes a detection once it ages past the visible history depth', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a', { meshRow: 0 }));
    for (let i = 0; i < 5; i += 1) overlay.ageByOneRow(3);
    expect(overlay.group.children.length).toBe(0);
  });

  it('remove() deletes a specific detection without affecting others', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a'));
    overlay.upsert(box('b'));
    overlay.remove('a');
    expect(overlay.group.children.length).toBe(1);
  });

  it('clear() removes every detection', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a'));
    overlay.upsert(box('b'));
    overlay.clear();
    expect(overlay.group.children.length).toBe(0);
  });

  it('dispose() releases resources without throwing', () => {
    const overlay = new AiDetectionOverlay(64);
    overlay.upsert(box('a'));
    expect(() => overlay.dispose()).not.toThrow();
  });
});
