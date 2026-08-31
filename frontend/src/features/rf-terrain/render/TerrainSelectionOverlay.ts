import * as THREE from 'three';

// Lightweight selection/hover reticle (spec-adjacent "target brackets"):
// a ring + crosshair built from primitive line geometry -- no textures, no
// bloom/post-processing, one small MeshBasicMaterial-class object per
// state. Both markers are children of the terrain mesh so they inherit
// its same smooth flow interpolation "for free"; aging them back by a
// full row as new data arrives is done explicitly in `ageByOneRow()`,
// mirroring how TerrainMesh.pushRow() shifts row content by one slot.
class Reticle {
  readonly group = new THREE.Group();
  private row = 0;

  constructor(color: number, ringRadius: number, opacity: number) {
    const ringGeometry = new THREE.RingGeometry(ringRadius * 0.7, ringRadius, 32);
    const ringMaterial = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false });
    const ring = new THREE.Mesh(ringGeometry, ringMaterial);
    ring.rotation.x = -Math.PI / 2;
    this.group.add(ring);

    const crossPoints = new Float32Array([
      -ringRadius * 1.6, 0, 0, ringRadius * 1.6, 0, 0,
      0, 0, -ringRadius * 1.6, 0, 0, ringRadius * 1.6,
    ]);
    const crossGeometry = new THREE.BufferGeometry();
    crossGeometry.setAttribute('position', new THREE.BufferAttribute(crossPoints, 3));
    const crossMaterial = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
    const cross = new THREE.LineSegments(crossGeometry, crossMaterial);
    this.group.add(cross);

    this.group.visible = false;
    this.group.renderOrder = 3;
  }

  place(localX: number, localY: number, localZ: number) {
    this.row = -localZ;
    this.group.position.set(localX, localY + 0.5, localZ);
    this.group.visible = true;
  }

  hide() {
    this.group.visible = false;
  }

  /** Shifts the marker back by one row, matching TerrainMesh's own
   * content shift. Returns false once it has aged past the visible
   * history depth (caller should treat the selection as OUT OF VIEW). */
  ageByOneRow(historyRows: number): boolean {
    if (!this.group.visible) return true;
    this.row += 1;
    if (this.row >= historyRows) {
      this.hide();
      return false;
    }
    this.group.position.z = -this.row;
    return true;
  }

  dispose() {
    this.group.children.forEach((child) => {
      const mesh = child as THREE.Mesh | THREE.LineSegments;
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    });
  }
}

export class TerrainSelectionOverlay {
  readonly group = new THREE.Group();
  private readonly selected: Reticle;
  private readonly hover: Reticle;

  constructor(cols: number) {
    const ringRadius = Math.max(2, cols / 60);
    this.selected = new Reticle(0xd4af37, ringRadius, 0.9); // metallic gold
    this.hover = new Reticle(0x67e8f9, ringRadius * 0.8, 0.55); // cyan
    this.group.add(this.selected.group, this.hover.group);
  }

  placeSelected(x: number, y: number, z: number) { this.selected.place(x, y, z); }
  hideSelected() { this.selected.hide(); }
  ageSelectedByOneRow(historyRows: number) { return this.selected.ageByOneRow(historyRows); }

  placeHover(x: number, y: number, z: number) { this.hover.place(x, y, z); }
  hideHover() { this.hover.hide(); }

  dispose() {
    this.selected.dispose();
    this.hover.dispose();
  }
}
