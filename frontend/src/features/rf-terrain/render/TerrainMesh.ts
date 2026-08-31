import * as THREE from 'three';

// Matches TerrainScene's background/fog color (0x050810) exactly, so a
// row that has not yet been observed since the last RESET reads as
// "receding into the same fog as the horizon", not as a distinct wall or
// a fabricated measurement. Deliberately NOT reused to fake a
// measurement -- a real fix for a real, previously-reported bug: filling
// every slot with a copy of the first post-reset row made a single
// measurement LOOK like ~24s of real history (see git history for the
// "seed-fill" this replaced). Height stays 0 for the same reason: no
// elevation is claimed for a row that was never measured.
const UNKNOWN_ROW_COLOR: readonly [number, number, number] = [5 / 255, 8 / 255, 16 / 255];

// Height-field mesh (spec §14): X = frequency bin, Z = time (row 0 = NOW,
// at the front; increasing row index recedes into the past), Y = height
// (the spec's own diagram uses different axis letters for the same three
// semantic roles -- frequency, time, magnitude -- this just maps them onto
// Three.js's Y-up convention for sane camera/orbit behavior).
//
// New data is written at row 0 and every older row is shifted back by one
// slot (a plain typed-array copy, not a ring buffer -- the mesh's vertex
// grid is a fixed grid in space, so "the newest row is always at the
// front" has to be achieved by moving the content, not the geometry).
export class TerrainMesh {
  readonly mesh: THREE.Mesh;
  private readonly geometry: THREE.BufferGeometry;
  private readonly positions: Float32Array;
  private readonly colors: Float32Array;
  readonly rows: number;
  readonly cols: number;

  constructor(rows: number, cols: number) {
    this.rows = rows;
    this.cols = cols;
    this.geometry = new THREE.BufferGeometry();

    const vertexCount = rows * cols;
    this.positions = new Float32Array(vertexCount * 3);
    this.colors = new Float32Array(vertexCount * 3);

    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const idx = (r * cols + c) * 3;
        this.positions[idx] = c - cols / 2;
        this.positions[idx + 1] = 0;
        this.positions[idx + 2] = -r;
        this.colors[idx] = UNKNOWN_ROW_COLOR[0]; this.colors[idx + 1] = UNKNOWN_ROW_COLOR[1]; this.colors[idx + 2] = UNKNOWN_ROW_COLOR[2];
      }
    }

    const indices: number[] = [];
    for (let r = 0; r < rows - 1; r += 1) {
      for (let c = 0; c < cols - 1; c += 1) {
        const a = r * cols + c;
        const b = r * cols + c + 1;
        const rowBelow = (r + 1) * cols + c;
        const d = (r + 1) * cols + c + 1;
        indices.push(a, rowBelow, b, b, rowBelow, d);
      }
    }

    this.geometry.setAttribute('position', new THREE.BufferAttribute(this.positions, 3));
    this.geometry.setAttribute('color', new THREE.BufferAttribute(this.colors, 3));
    this.geometry.setIndex(indices);
    this.geometry.computeVertexNormals();

    // Lit material (not MeshBasicMaterial): terrain slopes need a real
    // diffuse response to light for peaks/ridges to read as 3D relief
    // instead of a flat, unlit color map painted onto a plane.
    const material = new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: 0.85, metalness: 0.05, flatShading: false });
    this.mesh = new THREE.Mesh(this.geometry, material);
  }

  setWireframe(enabled: boolean) {
    (this.mesh.material as THREE.MeshStandardMaterial).wireframe = enabled;
  }

  // Writes a single slot directly, with no shift of the other rows.
  // Used to paint a rewound, static history window (spec-adjacent feature:
  // scrubbing back within the already-bounded buffer) where every row is
  // being replaced at once rather than one new live row arriving.
  writeSlot(rowSlot: number, heights: Float32Array, colorsFlat: Float32Array) {
    const base = rowSlot * this.cols * 3;
    for (let c = 0; c < this.cols; c += 1) {
      const idx = base + c * 3;
      this.positions[idx + 1] = heights[c];
      this.colors[idx] = colorsFlat[c * 3];
      this.colors[idx + 1] = colorsFlat[c * 3 + 1];
      this.colors[idx + 2] = colorsFlat[c * 3 + 2];
    }
  }

  commitWrites() {
    (this.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
    (this.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true;
    this.geometry.computeVertexNormals();
    this.geometry.computeBoundingSphere();
  }

  pushRow(heights: Float32Array, colorsFlat: Float32Array) {
    const rowStride = this.cols * 3;
    // Shift every existing row back by one slot (oldest row falls off the end).
    for (let r = this.rows - 1; r > 0; r -= 1) {
      const dstBase = r * rowStride;
      const srcBase = (r - 1) * rowStride;
      for (let i = 0; i < rowStride; i += 3) {
        this.positions[dstBase + i + 1] = this.positions[srcBase + i + 1];
        this.colors[dstBase + i] = this.colors[srcBase + i];
        this.colors[dstBase + i + 1] = this.colors[srcBase + i + 1];
        this.colors[dstBase + i + 2] = this.colors[srcBase + i + 2];
      }
    }
    for (let c = 0; c < this.cols; c += 1) {
      const base = c * 3;
      this.positions[base + 1] = heights[c];
      this.colors[base] = colorsFlat[base];
      this.colors[base + 1] = colorsFlat[base + 1];
      this.colors[base + 2] = colorsFlat[base + 2];
    }

    (this.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
    (this.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true;
    this.geometry.computeVertexNormals();
    this.geometry.computeBoundingSphere();
  }

  clear() {
    this.positions.fill(0);
    for (let r = 0; r < this.rows; r += 1) {
      for (let c = 0; c < this.cols; c += 1) {
        const idx = (r * this.cols + c) * 3;
        this.positions[idx] = c - this.cols / 2;
        this.positions[idx + 1] = 0;
        this.positions[idx + 2] = -r;
      }
    }
    for (let i = 0; i < this.colors.length; i += 3) {
      this.colors[i] = UNKNOWN_ROW_COLOR[0]; this.colors[i + 1] = UNKNOWN_ROW_COLOR[1]; this.colors[i + 2] = UNKNOWN_ROW_COLOR[2];
    }
    (this.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
    (this.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true;
    this.geometry.computeVertexNormals();
  }

  dispose() {
    this.geometry.dispose();
    (this.mesh.material as THREE.Material).dispose();
  }
}
