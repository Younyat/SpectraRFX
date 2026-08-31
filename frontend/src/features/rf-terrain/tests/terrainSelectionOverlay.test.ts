import { describe, expect, it } from 'vitest';
import { TerrainSelectionOverlay } from '../render/TerrainSelectionOverlay';

// No WebGL context needed here -- Group/RingGeometry/BufferGeometry are
// plain CPU-side Three.js objects, only the renderer itself needs a real
// canvas context.
describe('TerrainSelectionOverlay', () => {
  it('starts with both reticles hidden', () => {
    const overlay = new TerrainSelectionOverlay(64);
    const [selectedGroup, hoverGroup] = overlay.group.children;
    expect(selectedGroup.visible).toBe(false);
    expect(hoverGroup.visible).toBe(false);
  });

  it('placeSelected shows the gold reticle at the given local position', () => {
    const overlay = new TerrainSelectionOverlay(64);
    overlay.placeSelected(5, 2, -10);
    const [selectedGroup] = overlay.group.children;
    expect(selectedGroup.visible).toBe(true);
    expect(selectedGroup.position.x).toBe(5);
    expect(selectedGroup.position.z).toBe(-10);
  });

  it('ages the selected reticle back by one row per call, staying visible within history depth', () => {
    const overlay = new TerrainSelectionOverlay(64);
    overlay.placeSelected(0, 0, 0);
    const stillInView = overlay.ageSelectedByOneRow(240);
    expect(stillInView).toBe(true);
    const [selectedGroup] = overlay.group.children;
    expect(selectedGroup.position.z).toBe(-1);
    expect(selectedGroup.visible).toBe(true);
  });

  it('hides and reports OUT_OF_VIEW once the reticle ages past the visible history depth', () => {
    const overlay = new TerrainSelectionOverlay(64);
    overlay.placeSelected(0, 0, 0);
    // Once it goes OUT_OF_VIEW the reticle hides and ageSelectedByOneRow
    // short-circuits back to `true` (a harmless no-op on a hidden marker,
    // see the next test) -- so what matters is that the transition to
    // false happened at least once, not the value on the final call.
    let wentOutOfView = false;
    for (let i = 0; i < 5; i += 1) {
      if (!overlay.ageSelectedByOneRow(3)) wentOutOfView = true;
    }
    expect(wentOutOfView).toBe(true);
    const [selectedGroup] = overlay.group.children;
    expect(selectedGroup.visible).toBe(false);
  });

  it('ageing an already-hidden reticle is a harmless no-op that reports in-view', () => {
    const overlay = new TerrainSelectionOverlay(64);
    expect(overlay.ageSelectedByOneRow(240)).toBe(true);
  });

  it('hover and selected reticles are independent', () => {
    const overlay = new TerrainSelectionOverlay(64);
    overlay.placeSelected(1, 1, -1);
    overlay.placeHover(2, 2, -2);
    const [selectedGroup, hoverGroup] = overlay.group.children;
    expect(selectedGroup.visible).toBe(true);
    expect(hoverGroup.visible).toBe(true);
    overlay.hideHover();
    expect(hoverGroup.visible).toBe(false);
    expect(selectedGroup.visible).toBe(true);
  });

  it('dispose() releases geometry/material resources on both reticles without throwing', () => {
    const overlay = new TerrainSelectionOverlay(64);
    overlay.placeSelected(0, 0, 0);
    overlay.placeHover(0, 0, 0);
    expect(() => overlay.dispose()).not.toThrow();
  });
});
