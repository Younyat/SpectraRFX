import * as THREE from 'three';
import type { SpectralObjectEnvelope } from '../engine/spectralObjectEnvelope';

// The visual centerpiece of FSEI's object selection: a small, real
// triangulated surface patch reconstructed from the selected object's OWN
// measured cells (engine/spectralObjectEnvelope.ts), rendered in a gold
// metallic material distinct from the terrain's own vertex-colored heat
// map. Built ONCE per selection (or pinned-object update), never
// per-frame -- cheap by construction, not by luck: a real object's cell
// count is small (tens to a few hundred), nothing like the ~120k-vertex
// main terrain.
//
// Ages back by one row per newly-accepted terrain row, the exact same
// idiom TerrainSelectionOverlay's reticles use (see ageByOneRow there),
// so the envelope visually "rides along" with the terrain instead of
// needing its own per-frame position recomputation.
export class SpectralObjectEnvelopeMesh {
  readonly group = new THREE.Group();
  private mesh: THREE.Mesh | null = null;
  private meshRowOffset = 0;
  private age = 0;

  constructor() {
    this.group.visible = false;
  }

  private disposeMesh() {
    if (!this.mesh) return;
    this.mesh.geometry.dispose();
    (this.mesh.material as THREE.Material).dispose();
    this.group.remove(this.mesh);
    this.mesh = null;
  }

  // `cols` matches TerrainMesh's own vertex layout (x = col - cols/2) --
  // never re-derived independently.
  build(envelope: SpectralObjectEnvelope, cols: number, heightVisualScale: number) {
    this.disposeMesh();

    const { subRows, subCols, colOffset, meshRowOffset, heights, mask } = envelope;
    const positions = new Float32Array(subRows * subCols * 3);
    for (let sr = 0; sr < subRows; sr += 1) {
      for (let sc = 0; sc < subCols; sc += 1) {
        const idx = sr * subCols + sc;
        const base = idx * 3;
        positions[base] = (colOffset + sc) - cols / 2;
        positions[base + 1] = heights[idx] * heightVisualScale;
        // Local Z only -- the group's own position carries the real
        // mesh-row offset, updated by place()/ageByOneRow() below.
        positions[base + 2] = -sr;
      }
    }

    // Only triangulate quads whose four corners are all real object
    // members -- an organic, irregular silhouette that follows the
    // object's own approximate shape (see the module's masking
    // documentation) instead of padding it into a solid rectangle.
    const indices: number[] = [];
    for (let sr = 0; sr < subRows - 1; sr += 1) {
      for (let sc = 0; sc < subCols - 1; sc += 1) {
        const a = sr * subCols + sc;
        const b = sr * subCols + sc + 1;
        const c = (sr + 1) * subCols + sc;
        const d = (sr + 1) * subCols + sc + 1;
        if (!mask[a] || !mask[b] || !mask[c] || !mask[d]) continue;
        indices.push(a, c, b, b, c, d);
      }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();

    const material = new THREE.MeshStandardMaterial({
      color: 0xd4af37,
      metalness: 0.7,
      roughness: 0.28,
      emissive: 0x3a2c05,
      emissiveIntensity: 0.35,
      side: THREE.DoubleSide,
    });

    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.renderOrder = 1;
    this.group.add(this.mesh);

    this.meshRowOffset = meshRowOffset;
    this.age = 0;
    this.group.position.z = -meshRowOffset;
    this.group.visible = indices.length > 0;
  }

  hide() {
    this.group.visible = false;
  }

  /** Mirrors TerrainSelectionOverlay's reticle aging exactly. Returns
   * false once the envelope has aged past the visible history depth. */
  ageByOneRow(historyRows: number): boolean {
    if (!this.group.visible || !this.mesh) return true;
    this.age += 1;
    if (this.meshRowOffset + this.age >= historyRows) {
      this.hide();
      return false;
    }
    this.group.position.z = -(this.meshRowOffset + this.age);
    return true;
  }

  dispose() {
    this.disposeMesh();
  }
}
