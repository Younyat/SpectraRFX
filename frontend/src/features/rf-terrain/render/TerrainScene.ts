import * as THREE from 'three';

// Scene composition (spec §54): grid + axes, no shadow maps/bloom/
// postprocessing/particles -- but real diffuse lighting and fog, both
// cheap native Three.js scene properties, are what make the terrain read
// as actual 3D relief (mountains, ridges) instead of a flat painted plane,
// and what sell the "driving down a highway, terrain flowing toward you"
// depth cue the module is built around.
export const createTerrainScene = (rows: number, cols: number) => {
  const backgroundColor = 0x050810;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(backgroundColor);
  scene.fog = new THREE.Fog(backgroundColor, cols * 0.4, cols * 2.2);

  const grid = new THREE.GridHelper(Math.max(rows, cols), 20, 0x334155, 0x1e293b);
  grid.position.set(0, 0, -rows / 2);
  scene.add(grid);

  const axes = new THREE.AxesHelper(Math.max(rows, cols) / 4);
  scene.add(axes);

  const ambient = new THREE.AmbientLight(0xffffff, 0.45);
  scene.add(ambient);

  // Angled from above-front so slopes facing NOW pick up more light than
  // slopes facing PAST -- the shading gradient that makes a ridge read as
  // a ridge rather than a flat colored strip.
  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(cols * 0.3, cols * 0.6, cols * 0.4);
  scene.add(key);

  const fill = new THREE.DirectionalLight(0x88aaff, 0.35);
  fill.position.set(-cols * 0.3, cols * 0.2, -rows * 0.6);
  scene.add(fill);

  return scene;
};
