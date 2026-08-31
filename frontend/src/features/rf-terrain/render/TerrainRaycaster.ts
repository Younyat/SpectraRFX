import * as THREE from 'three';

// Screen pixel -> ray -> terrain triangle -> nearest (row, col) vertex
// (spec §70). Returns grid coordinates only -- the caller looks up the
// real underlying measurement for that cell; this module never invents a
// value from the intersection point itself.
export const raycastToGridCell = (
  raycaster: THREE.Raycaster,
  camera: THREE.Camera,
  ndcX: number,
  ndcY: number,
  mesh: THREE.Mesh,
  cols: number,
): { row: number; col: number } | null => {
  raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
  const intersections = raycaster.intersectObject(mesh);
  if (intersections.length === 0 || !intersections[0].face) {
    return null;
  }
  const vertexIndex = intersections[0].face.a;
  return { row: Math.floor(vertexIndex / cols), col: vertexIndex % cols };
};
