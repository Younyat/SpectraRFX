import * as THREE from 'three';

// A "surrounds the zone" 3D highlight for an AI Research Plugin LIVE
// detection -- deliberately NOT the same primitive as TerrainSelectionOverlay
// (a single point reticle) or SpectralObjectEnvelopeMesh (a real per-cell
// excess surface, which an AI bounding box has no measured equivalent of).
// This is a wireframe cage spanning the detection's REAL col-range
// (frequency window), keyed by `box.id` (one live-updated slot per
// MODEL, not per poll/record -- see useAiLiveDetection's id comment) so a
// continuous session moves ONE cage as new detections arrive instead of
// leaving a trail of overlapping ones (real bug, reported: it read as the
// highlight "occupying the whole span"). The Map keyed by id still lets
// several DIFFERENT models be highlighted at once, if the UI ever allows
// running more than one concurrently. Sits with its base AT the terrain's
// own real measured peak height for that frequency/time (caller-supplied,
// see RFTerrainCanvas.addAiDetection) so it visually crowns the actual
// lobe instead of floating at a fixed, disconnected height, with a
// billboarded text label BELOW it (near the terrain surface, not
// stacked above a possibly-tall peak) so it never renders behind the
// fixed-position FREQUENCY/TIME/POWER HUD badges near the top of the
// viewport.
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
  // Real, measured display height (local units, same toDisplayHeight *
  // RF_TERRAIN_HEIGHT_VISUAL_SCALE convention as the terrain mesh itself)
  // of the actual terrain peak under this detection -- the cage's base
  // sits here, not at an arbitrary fixed height.
  baseY: number;
  meshRow: number; // 0 = newest/front row at insertion time
  label: string;
  color: number;
}

const DEFAULT_COLOR = 0xf97316; // amber/orange -- visually distinct from the gold "selected" reticle and cyan "hover" one

function createLabelSprite(text: string, color: number, width: number, height: number): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const hex = `#${color.toString(16).padStart(6, '0')}`;
    ctx.fillStyle = 'rgba(10, 12, 16, 0.82)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = hex;
    ctx.lineWidth = 6;
    ctx.strokeRect(3, 3, canvas.width - 6, canvas.height - 6);
    ctx.fillStyle = hex;
    ctx.font = '600 44px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    // Real, honest truncation -- never silently drops meaning without
    // showing the operator that something was cut.
    const truncated = text.length > 28 ? `${text.slice(0, 27)}…` : text;
    ctx.fillText(truncated, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  const material = new THREE.SpriteMaterial({ map: texture, depthWrite: false, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(width, height, 1);
  sprite.renderOrder = 4;
  return sprite;
}

class DetectionCage {
  readonly group = new THREE.Group();
  private readonly edges: THREE.LineSegments;
  private readonly labelSprite: THREE.Sprite;
  private row: number;
  private readonly boxHeight: number;
  readonly id: string;
  label: string;

  constructor(box: AiDetectionBox, boxHeight: number, labelWidth: number, labelHeight: number) {
    this.id = box.id;
    this.label = box.label;
    this.row = box.meshRow;
    this.boxHeight = boxHeight;

    const width = Math.max(1, box.xMax - box.xMin);
    const geometry = new THREE.BoxGeometry(width, boxHeight, 1);
    const edgesGeometry = new THREE.EdgesGeometry(geometry);
    geometry.dispose();
    const material = new THREE.LineBasicMaterial({ color: box.color, transparent: true, opacity: 0.85 });
    this.edges = new THREE.LineSegments(edgesGeometry, material);
    this.group.add(this.edges);
    this.group.renderOrder = 2;

    // Below the cage (near its base), not above it: a cage sits on the
    // real terrain peak, which can already be tall (peaks reach up to
    // RF_TERRAIN_MAX_EXCESS_DB * RF_TERRAIN_HEIGHT_VISUAL_SCALE = 160 local
    // units) -- a label stacked ABOVE it could project into the same
    // screen region as the fixed-position FREQUENCY/TIME/POWER HUD badges
    // and render hidden behind them (reported: "el mensaje de detección
    // está por detrás de las frecuencias y potencias"). Anchoring below
    // keeps it near the terrain surface regardless of peak height.
    this.labelSprite = createLabelSprite(box.label, box.color, labelWidth, labelHeight);
    this.labelSprite.position.set(0, -(boxHeight / 2 + labelHeight / 2 + labelHeight * 0.15), 0);
    this.group.add(this.labelSprite);

    this.place(box);
  }

  place(box: AiDetectionBox) {
    const centerX = (box.xMin + box.xMax) / 2;
    this.group.position.set(centerX, box.baseY + this.boxHeight / 2, -this.row);
  }

  setColor(color: number) {
    (this.edges.material as THREE.LineBasicMaterial).color.set(color);
  }

  setLabel(text: string, color: number, labelWidth: number, labelHeight: number) {
    if (this.label === text) return;
    this.label = text;
    const oldTexture = (this.labelSprite.material as THREE.SpriteMaterial).map;
    const oldMaterial = this.labelSprite.material as THREE.SpriteMaterial;
    const fresh = createLabelSprite(text, color, labelWidth, labelHeight);
    this.labelSprite.material = fresh.material;
    oldTexture?.dispose();
    oldMaterial.dispose();
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
    (this.labelSprite.material as THREE.SpriteMaterial).map?.dispose();
    (this.labelSprite.material as THREE.Material).dispose();
  }
}

export class AiDetectionOverlay {
  readonly group = new THREE.Group();
  private readonly cages = new Map<string, DetectionCage>();
  // Scaled off the real terrain width (same idiom TerrainSelectionOverlay
  // uses for its reticle radius: Math.max(2, cols/60)) so the cage/label
  // read as a real, proportionate highlight instead of a barely-visible
  // fixed-size prop next to peaks that can reach RF_TERRAIN_MAX_EXCESS_DB
  // (40) * RF_TERRAIN_HEIGHT_VISUAL_SCALE (4) = 160 local units tall.
  private readonly boxHeight: number;
  private readonly labelWidth: number;
  private readonly labelHeight: number;

  constructor(cols: number) {
    this.boxHeight = Math.max(4, cols / 20);
    this.labelWidth = Math.max(8, cols / 12);
    this.labelHeight = this.labelWidth / 4; // matches the label canvas's own 512x128 (4:1) aspect ratio
  }

  /** Adds or replaces the box for `box.id` -- a caller re-running the same
   * model on a new snapshot re-upserts under a fresh id each time (each
   * detection is its own row-anchored event), so this is really "add new,
   * unless a caller explicitly wants to update one in place (e.g. its
   * label after interpretation completes)". */
  upsert(box: AiDetectionBox) {
    const existing = this.cages.get(box.id);
    if (existing) {
      existing.place(box);
      existing.setColor(box.color);
      existing.setLabel(box.label, box.color, this.labelWidth, this.labelHeight);
      return;
    }
    const cage = new DetectionCage(box, this.boxHeight, this.labelWidth, this.labelHeight);
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
