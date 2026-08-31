import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { RFTerrainCameraPreset } from '../model/rfTerrainTypes';

// Camera presets (spec §58): TOP reads like the legacy waterfall, FRONT
// reads like a conventional spectrum trace -- connecting Spectrum/
// Waterfall/Terrain as three views of one underlying geometry.
export const presetCameraPosition = (preset: RFTerrainCameraPreset, rows: number, cols: number): { position: THREE.Vector3; target: THREE.Vector3 } => {
  const target = new THREE.Vector3(0, 0, -rows / 2);
  switch (preset) {
    case 'top':
      return { position: new THREE.Vector3(0, cols, -rows / 2 + 0.01), target };
    case 'front':
      return { position: new THREE.Vector3(0, cols / 6, cols / 2), target: new THREE.Vector3(0, 0, 0) };
    case 'side':
      return { position: new THREE.Vector3(cols, cols / 4, -rows / 2), target };
    case '3d':
    default:
      // New captures must come toward the viewer -- like driving through a
      // canyon of captured spectrum. Row 0 (NOW) spawns at z=0; older rows
      // recede toward z=-(rows-1) as they age (TerrainMesh.pushRow shifts
      // content in -Z). So the camera sits beyond the oldest row, looking
      // forward in +Z past NOW into the void where the next capture is
      // about to appear -- new terrain rises ahead of us and flows past.
      return {
        position: new THREE.Vector3(0, cols / 8, -(rows + cols / 3)),
        target: new THREE.Vector3(0, cols / 25, rows / 6),
      };
  }
};

export const createTerrainCamera = (canvas: HTMLCanvasElement, rows: number, cols: number) => {
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, cols * 10);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.maxDistance = cols * 6;

  const applyPreset = (preset: RFTerrainCameraPreset) => {
    const { position, target } = presetCameraPosition(preset, rows, cols);
    camera.position.copy(position);
    controls.target.copy(target);
    controls.update();
  };
  applyPreset('3d');

  return { camera, controls, applyPreset };
};
