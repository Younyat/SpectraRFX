import { describe, expect, it } from 'vitest';
import { detectWebGLSupport } from '../model/rfTerrainCapabilities';

describe('detectWebGLSupport', () => {
  it('never throws even when canvas.getContext is entirely unavailable', () => {
    const original = HTMLCanvasElement.prototype.getContext;
    // @ts-expect-error -- simulate a browser that throws instead of
    // returning null (spec §3: must fail closed, not crash).
    HTMLCanvasElement.prototype.getContext = () => { throw new Error('no context'); };
    expect(() => detectWebGLSupport()).not.toThrow();
    expect(detectWebGLSupport()).toEqual({ supported: false, version: 0 });
    HTMLCanvasElement.prototype.getContext = original;
  });

  it('reports unsupported when getContext returns null for every WebGL variant (e.g. jsdom)', () => {
    const result = detectWebGLSupport();
    expect(result.supported).toBe(false);
    expect(result.version).toBe(0);
  });
});
