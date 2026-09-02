import * as THREE from 'three';

// A "surrounds the zone" 3D highlight for an AI Research Plugin LIVE
// detection -- deliberately NOT the same primitive as TerrainSelectionOverlay
// (a single point reticle) or SpectralObjectEnvelopeMesh (a real per-cell
// excess surface, which an AI bounding box has no measured equivalent of).
// This is a wireframe cage spanning the detection's REAL col-range
// (frequency window) x row-range (time window), so multiple simultaneous,
// independently-aging detections can be shown at once -- something neither
// existing overlay supports (both are effectively singletons).
//
// Same "child of terrainMesh.mesh, aged one row per pushRow()" discipline
// as every other overlay here, so it inherits the terrain's own smooth
// row-flow animation for free.

export interface AiDetectionBox {
  id: string;
  // Local mesh-space X (already shifted by -cols/2, the SAME convention
  // every other overlay/marker in this renderer uses -- the caller is
  // responsible for that shift, this class never re-derives it).
  xMin: number;
  xMax: number;
  meshRow: number; // 0 = newest/front row at insertion time
  label: string;
  color: number;
}

const DEFAULT_COLOR = 0xf97316; // amber/orange -- visually distinct from the gold "selected" reticle and cyan "hover" one
const BOX_HEIGHT = 6; // fixed visual height (local units) -- a detection has no measured excess-dB extent to size this from

class DetectionCage {
  readonly group = new THREE.Group();
  private readonly edges: THREE.LineSegments;
  private row: number;
  readonly id: string;
  label: string;

  constructor(box: AiDetectionBox) {
    this.id = box.id;
    this.label = box.label;
    this.row = box.meshRow;

    const width = Math.max(1, box.xMax - box.xMin);
    const geometry = new THREE.BoxGeometry(width, BOX_HEIGHT, 1);
    const edgesGeometry = new THREE.EdgesGeometry(geometry);
    geometry.dispose();
    const material = new THREE.LineBasicMaterial({ color: box.color, transparent: true, opacity: 0.85 });
    this.edges = new THREE.LineSegments(edgesGeometry, material);
    this.group.add(this.edges);
    this.group.renderOrder = 2;

    this.place(box);
  }

  place(box: AiDetectionBox) {
    const centerX = (box.xMin + box.xMax) / 2;
    this.group.position.set(centerX, BOX_HEIGHT / 2, -this.row);
  }

  setColor(color: number) {
    (this.edges.material as THREE.LineBasicMaterial).color.set(color);
  }

  /** Mirrors Reticle.ageByOneRow -- shifts back by one row, returns false
   * once it has aged past the visible history depth. */
  ageByOneRow(historyRows: number): boolean {
    this.row += 1;
    if (this.row >= historyRows) return false;
    this.group.position.z = -this.row;
    return true;
  }

  dispose() {
    this.edges.geometry.dispose();
    (this.edges.material as THREE.Material).dispose();
  }
}

export class AiDetectionOverlay {
  readonly group = new THREE.Group();
  private readonly cages = new Map<string, DetectionCage>();

  /** Adds or replaces the box for `box.id` -- a caller re-running the same
   * model on a new snapshot re-upserts under a fresh id each time (each
   * detection is its own row-anchored event), so this is really "add new,
   * unless a caller explicitly wants to update one in place (e.g. its
   * label after interpretation completes)". */
  upsert(box: AiDetectionBox) {
    const existing = this.cages.get(box.id);
    if (existing) {
      existing.place(box);
      existing.label = box.label;
      existing.setColor(box.color);
      return;
    }
    const cage = new DetectionCage(box);
    this.cages.set(box.id, cage);
    this.group.add(cage.group);
  }

  remove(id: string) {
    const cage = this.cages.get(id);
    if (!cage) return;
    this.group.remove(cage.group);
    cage.dispose();
    this.cages.delete(id);
  }

  clear() {
    for (const id of Array.from(this.cages.keys())) this.remove(id);
  }

  /** Ages every live detection back by one row, removing any that have
   * scrolled out of the visible history depth -- called once per
   * pushRow(), exactly like TerrainSelectionOverlay/SpectralObjectEnvelopeMesh. */
  ageByOneRow(historyRows: number) {
    for (const [id, cage] of Array.from(this.cages.entries())) {
      if (!cage.ageByOneRow(historyRows)) this.remove(id);
    }
  }

  dispose() {
    this.clear();
  }
}

export { DEFAULT_COLOR as AI_DETECTION_DEFAULT_COLOR };
