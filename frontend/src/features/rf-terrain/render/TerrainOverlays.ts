import * as THREE from 'three';

export type TerrainOverlayId = 'maxHold' | 'minHold' | 'average' | 'ewma' | 'p50' | 'p90' | 'p95' | 'p99';

const OVERLAY_COLORS: Record<TerrainOverlayId, number> = {
  maxHold: 0x38bdf8,
  minHold: 0x4ade80,
  average: 0xfbbf24,
  ewma: 0xf472b6,
  p50: 0xa3a3a3,
  p90: 0xfb923c,
  p95: 0xef4444,
  p99: 0x7f1d1d,
};

const ALL_OVERLAY_IDS: TerrainOverlayId[] = ['maxHold', 'minHold', 'average', 'ewma', 'p50', 'p90', 'p95', 'p99'];

// Front-edge reference ribbons (spec §26-28/§38: Max Hold/Min Hold/Average
// as curves at the current-spectrum edge, never full duplicate surfaces).
// One thin THREE.Line per metric, positioned at z=0 (NOW) and updated
// every accepted row -- cheap compared to the terrain mesh itself (cols
// points vs rows*cols).
export class TerrainOverlays {
  readonly group = new THREE.Group();
  private readonly lines: Record<TerrainOverlayId, { line: THREE.Line; positions: Float32Array }>;
  private readonly cols: number;

  constructor(cols: number) {
    this.cols = cols;
    const build = (id: TerrainOverlayId) => {
      const positions = new Float32Array(cols * 3);
      for (let c = 0; c < cols; c += 1) {
        positions[c * 3] = c - cols / 2;
        positions[c * 3 + 1] = 0;
        positions[c * 3 + 2] = 0;
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      const material = new THREE.LineBasicMaterial({ color: OVERLAY_COLORS[id], linewidth: 2, transparent: true, opacity: 0.9 });
      const line = new THREE.Line(geometry, material);
      line.visible = false;
      line.renderOrder = 1;
      this.group.add(line);
      return { line, positions };
    };

    this.lines = Object.fromEntries(ALL_OVERLAY_IDS.map((id) => [id, build(id)])) as unknown as Record<TerrainOverlayId, { line: THREE.Line; positions: Float32Array }>;
  }

  setVisible(id: TerrainOverlayId, visible: boolean) {
    this.lines[id].line.visible = visible;
  }

  update(id: TerrainOverlayId, heights: Float32Array) {
    const entry = this.lines[id];
    for (let c = 0; c < this.cols; c += 1) {
      entry.positions[c * 3 + 1] = heights[c];
    }
    (entry.line.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
  }

  dispose() {
    (Object.keys(this.lines) as TerrainOverlayId[]).forEach((id) => {
      this.lines[id].line.geometry.dispose();
      (this.lines[id].line.material as THREE.Material).dispose();
    });
  }
}
