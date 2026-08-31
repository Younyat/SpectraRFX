export interface WebGLCapability {
  supported: boolean;
  version: 0 | 1 | 2;
}

// WebGL capability detection (spec §49/§52). Never throws -- a browser
// that refuses to create ANY context is exactly the case this must detect
// cleanly so the caller can fall back to RFTerrainFallback2D instead of
// crashing on the first Three.js call.
export const detectWebGLSupport = (): WebGLCapability => {
  try {
    const canvas = document.createElement('canvas');
    const gl2 = canvas.getContext('webgl2');
    if (gl2) {
      return { supported: true, version: 2 };
    }
    const gl1 = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (gl1) {
      return { supported: true, version: 1 };
    }
    return { supported: false, version: 0 };
  } catch {
    return { supported: false, version: 0 };
  }
};
