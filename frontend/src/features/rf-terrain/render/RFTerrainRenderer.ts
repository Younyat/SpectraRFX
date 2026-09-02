import * as THREE from 'three';
import { createTerrainScene } from './TerrainScene';
import { createTerrainCamera } from './TerrainCamera';
import { TerrainMesh } from './TerrainMesh';
import { raycastToGridCell } from './TerrainRaycaster';
import { TerrainOverlays, TerrainOverlayId } from './TerrainOverlays';
import { TerrainSelectionOverlay } from './TerrainSelectionOverlay';
import { SpectralObjectEnvelopeMesh } from './SpectralObjectEnvelope';
import { AiDetectionOverlay, type AiDetectionBox } from './AiDetectionOverlay';
import { RF_TERRAIN_MAX_EXCESS_DB, RF_TERRAIN_HEIGHT_VISUAL_SCALE } from '../model/rfTerrainConstants';
import type { RFTerrainCameraPreset } from '../model/rfTerrainTypes';
import type { SpectralObjectEnvelope } from '../engine/spectralObjectEnvelope';

const MAX_DISPLAY_HEIGHT_UNITS = RF_TERRAIN_MAX_EXCESS_DB * RF_TERRAIN_HEIGHT_VISUAL_SCALE;

export interface RFTerrainRendererCallbacks {
  onContextLost?: () => void;
  onContextRestored?: () => void;
  onFpsUpdate?: (fps: number) => void;
  // FSEI (spec-adjacent "OUT OF VIEW"): fired the instant the selected
  // reticle ages past the visible history depth, so the caller can update
  // whatever selection state it holds instead of silently pointing at a
  // marker that no longer exists in the scene.
  onSelectionOutOfView?: () => void;
}

// Scene composition + render loop (spec §54): PerspectiveCamera,
// WebGLRenderer, one BufferGeometry/Mesh, grid/axes, OrbitControls,
// Raycaster. No shadows/bloom/postprocessing in this pass. Owns every
// GPU resource it creates and disposes all of them in dispose() (spec
// §92/93: zero orphan WebGL contexts across mount/unmount).
export class RFTerrainRenderer {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: THREE.Scene;
  private readonly cameraRig: ReturnType<typeof createTerrainCamera>;
  private readonly terrainMesh: TerrainMesh;
  private readonly overlays: TerrainOverlays;
  private readonly selectionOverlay: TerrainSelectionOverlay;
  private readonly envelopeMesh: SpectralObjectEnvelopeMesh;
  private readonly aiDetectionOverlay: AiDetectionOverlay;
  private readonly raycaster = new THREE.Raycaster();
  private readonly canvas: HTMLCanvasElement;
  private readonly cols: number;
  private rafHandle: number | null = null;
  private callbacks: RFTerrainRendererCallbacks;
  private readonly frequencyMarker: THREE.Mesh;
  private readonly maskPlane: THREE.Mesh;

  // Smooth "driving down a highway" motion (spec §14/§58's NOW-at-front
  // geometry, made continuous): data arrives in discrete ~100ms steps, but
  // the render loop runs at 30-60 FPS. Rather than snapping the whole
  // terrain back by one row the instant a frame lands, the mesh is nudged
  // toward the camera every render frame in proportion to how much of the
  // expected inter-row interval has elapsed, then snapped back to 0 in the
  // same tick pushRow() shifts the data -- visually seamless, and it is
  // this continuous flow that reads as speed/motion instead of a slideshow.
  private lastRowTimeMs = performance.now();
  private estimatedIntervalMs = 100;
  // While viewing a rewound (non-live) history window, the flow animation
  // pauses -- there is no "next row about to arrive" to anticipate.
  private live = true;

  constructor(canvas: HTMLCanvasElement, rows: number, cols: number, callbacks: RFTerrainRendererCallbacks = {}) {
    this.canvas = canvas;
    this.cols = cols;
    this.callbacks = callbacks;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    this.scene = createTerrainScene(rows, cols);
    this.cameraRig = createTerrainCamera(canvas, rows, cols);
    this.terrainMesh = new TerrainMesh(rows, cols);
    this.scene.add(this.terrainMesh.mesh);

    // Children of the terrain mesh so they inherit its same flow animation
    // (position.z) -- the reference ribbons "surf" the front edge along
    // with the terrain instead of visually detaching from it.
    this.overlays = new TerrainOverlays(cols);
    this.terrainMesh.mesh.add(this.overlays.group);

    // FSEI selection/hover reticles (spec-adjacent "target brackets"):
    // same parenting trick as the reference ribbons above, so a selected
    // object visually "rides along" with the terrain as it flows/ages
    // instead of needing its own separate position tracking each frame.
    this.selectionOverlay = new TerrainSelectionOverlay(cols);
    this.terrainMesh.mesh.add(this.selectionOverlay.group);

    this.envelopeMesh = new SpectralObjectEnvelopeMesh();
    this.terrainMesh.mesh.add(this.envelopeMesh.group);

    // AI Research Plugin LIVE detection highlights (multiple, independently
    // aging boxes -- unlike the single selection reticle/envelope above).
    this.aiDetectionOverlay = new AiDetectionOverlay();
    this.terrainMesh.mesh.add(this.aiDetectionOverlay.group);

    // Center-frequency cursor (spec §41/§38 "Markers -> vertical plane"):
    // a bright, unmistakably-different-colored vertical wall marking where
    // in frequency space the receiver is currently tuned, spanning the
    // full visible history depth AND the full possible terrain height (not
    // a fixed 1-unit sliver, which would be invisible next to real peaks)
    // so it stays visible while scrubbing.
    const markerGeometry = new THREE.PlaneGeometry(rows, MAX_DISPLAY_HEIGHT_UNITS);
    const markerMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false });
    this.frequencyMarker = new THREE.Mesh(markerGeometry, markerMaterial);
    this.frequencyMarker.rotation.y = Math.PI / 2;
    this.frequencyMarker.position.set(0, MAX_DISPLAY_HEIGHT_UNITS / 2, -rows / 2);
    this.frequencyMarker.visible = false;
    this.frequencyMarker.renderOrder = 2;
    this.scene.add(this.frequencyMarker);

    // Spectrum mask (spec §39): a translucent threshold wall across the
    // whole visible width/depth at a user-set height.
    const maskGeometry = new THREE.PlaneGeometry(cols, rows);
    const maskMaterial = new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false });
    this.maskPlane = new THREE.Mesh(maskGeometry, maskMaterial);
    this.maskPlane.rotation.x = Math.PI / 2;
    this.maskPlane.position.set(0, 0, -rows / 2);
    this.maskPlane.visible = false;
    this.maskPlane.renderOrder = 2;
    this.scene.add(this.maskPlane);

    canvas.addEventListener('webglcontextlost', this.handleContextLost);
    canvas.addEventListener('webglcontextrestored', this.handleContextRestored);
  }

  private handleContextLost = (event: Event) => {
    // Spec §52: preventDefault() + stop RAF + surface DEGRADED, never let
    // the browser tear the context down permanently or reload the page.
    event.preventDefault();
    this.stop();
    this.callbacks.onContextLost?.();
  };

  private handleContextRestored = () => {
    this.callbacks.onContextRestored?.();
    this.start();
  };

  // Called once per newly-accepted row -- mirrors the exact moment
  // TerrainMesh.pushRow() shifts row content by one slot, so the reticle
  // ages in lockstep with the terrain instead of drifting out of sync.
  pushRow(heights: Float32Array, colorsFlat: Float32Array) {
    this.terrainMesh.pushRow(heights, colorsFlat);
    if (!this.selectionOverlay.ageSelectedByOneRow(this.terrainMesh.rows)) {
      this.callbacks.onSelectionOutOfView?.();
    }
    this.envelopeMesh.ageByOneRow(this.terrainMesh.rows);
    this.aiDetectionOverlay.ageByOneRow(this.terrainMesh.rows);
    const now = performance.now();
    const observedInterval = now - this.lastRowTimeMs;
    if (observedInterval > 5 && observedInterval < 5000) {
      // Track the real, possibly-jittery arrival cadence rather than
      // assuming a fixed poll interval -- an EWMA so one slow/fast tick
      // doesn't visibly kink the motion.
      this.estimatedIntervalMs = this.estimatedIntervalMs * 0.8 + observedInterval * 0.2;
    }
    this.lastRowTimeMs = now;
    this.terrainMesh.mesh.position.z = 0;
  }

  // Paints a full, static history window in one shot (a rewind/scrub
  // position) and pauses the live flow animation until setLive(true).
  renderStaticWindow(rows: Array<{ heights: Float32Array; colorsFlat: Float32Array }>) {
    this.live = false;
    this.terrainMesh.mesh.position.z = 0;
    rows.forEach((row, index) => this.terrainMesh.writeSlot(index, row.heights, row.colorsFlat));
    this.terrainMesh.commitWrites();
  }

  setLive(live: boolean) {
    this.live = live;
    if (live) {
      this.lastRowTimeMs = performance.now();
      this.terrainMesh.mesh.position.z = 0;
    }
  }

  clear() {
    this.terrainMesh.clear();
    this.terrainMesh.mesh.position.z = 0;
    this.lastRowTimeMs = performance.now();
    // A RESET invalidates every row index the reticle could be anchored
    // to (spec-adjacent generation-id discipline) -- never leave a gold
    // marker pointing at data that no longer exists after the reset.
    this.selectionOverlay.hideSelected();
    this.selectionOverlay.hideHover();
    this.envelopeMesh.hide();
    this.aiDetectionOverlay.clear();
  }

  setSelectedObjectEnvelope(envelope: SpectralObjectEnvelope, cols: number) {
    this.envelopeMesh.build(envelope, cols, RF_TERRAIN_HEIGHT_VISUAL_SCALE);
  }

  hideSelectedObjectEnvelope() {
    this.envelopeMesh.hide();
  }

  // Local mesh-space coordinates (x = col - cols/2, y = display height,
  // z = -row), the SAME convention TerrainMesh itself uses -- never a
  // separately-derived position.
  setSelectedMarker(x: number, y: number, z: number) {
    this.selectionOverlay.placeSelected(x, y, z);
  }

  hideSelectedMarker() {
    this.selectionOverlay.hideSelected();
  }

  setHoverMarker(x: number, y: number, z: number) {
    this.selectionOverlay.placeHover(x, y, z);
  }

  hideHoverMarker() {
    this.selectionOverlay.hideHover();
  }

  // Adds/updates one AI-detection highlight box. `xMin`/`xMax` are already
  // in local mesh-space X (same -cols/2-shifted convention as
  // setSelectedMarker); `meshRow` is 0 for the newest/front row.
  upsertAiDetection(box: AiDetectionBox) {
    this.aiDetectionOverlay.upsert(box);
  }

  removeAiDetection(id: string) {
    this.aiDetectionOverlay.remove(id);
  }

  clearAiDetections() {
    this.aiDetectionOverlay.clear();
  }

  setCameraPreset(preset: RFTerrainCameraPreset) {
    this.cameraRig.applyPreset(preset);
  }

  // xPosition is already in local mesh-space X units (bin index - cols/2),
  // matching TerrainMesh's own vertex layout -- never re-derived here.
  setFrequencyMarker(xPosition: number | null) {
    if (xPosition === null) {
      this.frequencyMarker.visible = false;
      return;
    }
    this.frequencyMarker.visible = true;
    this.frequencyMarker.position.x = xPosition;
  }

  setMaskPlane(heightUnits: number | null) {
    if (heightUnits === null) {
      this.maskPlane.visible = false;
      return;
    }
    this.maskPlane.visible = true;
    this.maskPlane.position.y = heightUnits;
  }

  // "Trace History" (spec §31): rather than duplicating hundreds of past
  // trace lines, toggling this reveals the terrain's own already-present
  // history as connected wireframe threads instead of a solid surface.
  setHistoryWireframe(enabled: boolean) {
    this.terrainMesh.setWireframe(enabled);
  }

  setOverlayVisible(id: TerrainOverlayId, visible: boolean) {
    this.overlays.setVisible(id, visible);
  }

  updateOverlay(id: TerrainOverlayId, heights: Float32Array) {
    this.overlays.update(id, heights);
  }

  // Local mesh-space point -> normalized [0,1] screen ratio, for the
  // frequency/power ruler labels (spec-adjacent request: axis ticks with
  // real values "in the space", not just in a side panel). `visible` is
  // false when the point falls behind the camera, so callers can hide the
  // label rather than pin it to a nonsense screen position.
  projectToScreenRatio(x: number, y: number, z: number): { xRatio: number; yRatio: number; visible: boolean } {
    const vector = new THREE.Vector3(x, y, z).project(this.cameraRig.camera);
    return {
      xRatio: (vector.x + 1) / 2,
      yRatio: (1 - vector.y) / 2,
      visible: vector.z < 1,
    };
  }

  resize(width: number, height: number) {
    if (width <= 0 || height <= 0) return;
    this.renderer.setSize(width, height, false);
    this.cameraRig.camera.aspect = width / height;
    this.cameraRig.camera.updateProjectionMatrix();
  }

  pickGridCell(ndcX: number, ndcY: number) {
    return raycastToGridCell(this.raycaster, this.cameraRig.camera, ndcX, ndcY, this.terrainMesh.mesh, this.cols);
  }

  start() {
    if (this.rafHandle !== null) {
      return;
    }
    let lastTime = performance.now();
    let frameCount = 0;
    let fpsAccumMs = 0;

    const loop = (time: number) => {
      this.rafHandle = requestAnimationFrame(loop);
      const delta = time - lastTime;
      lastTime = time;
      frameCount += 1;
      fpsAccumMs += delta;
      if (fpsAccumMs >= 500) {
        this.callbacks.onFpsUpdate?.(Math.round((frameCount * 1000) / fpsAccumMs));
        frameCount = 0;
        fpsAccumMs = 0;
      }
      if (this.live) {
        // New captures spawn ahead (z=0) and flow toward the camera
        // (-Z, spec-adjacent "driving through captured spectrum" framing)
        // as they age -- animate the same direction between arrivals.
        const progress = Math.min(1, (time - this.lastRowTimeMs) / this.estimatedIntervalMs);
        this.terrainMesh.mesh.position.z = -progress;
      }

      this.cameraRig.controls.update();
      this.renderer.render(this.scene, this.cameraRig.camera);
    };
    this.rafHandle = requestAnimationFrame(loop);
  }

  stop() {
    if (this.rafHandle !== null) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = null;
    }
  }

  dispose() {
    this.stop();
    this.canvas.removeEventListener('webglcontextlost', this.handleContextLost);
    this.canvas.removeEventListener('webglcontextrestored', this.handleContextRestored);
    this.overlays.dispose();
    this.selectionOverlay.dispose();
    this.envelopeMesh.dispose();
    this.aiDetectionOverlay.dispose();
    this.frequencyMarker.geometry.dispose();
    (this.frequencyMarker.material as THREE.Material).dispose();
    this.maskPlane.geometry.dispose();
    (this.maskPlane.material as THREE.Material).dispose();
    this.terrainMesh.dispose();
    this.cameraRig.controls.dispose();
    this.renderer.dispose();
  }
}
