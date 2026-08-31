# RF Terrain 3D / ARST — Technical Report

Read-only technical report on **RF Terrain 3D**, SpectraRFˣ's real-time
three-dimensional spectral-terrain visualization (`/rf-terrain`), also
referred to by its working concept name **ARST — Adaptive RF Spectral
Terrain**. Every method, formula, and metric below is sourced directly from
the real, currently-implemented frontend code — no new experiment was run,
no scientific artifact, dataset, model, or paper file was touched, and
nothing here recomputes or supersedes any BLE-RFFI result documented in the
main [`README.md`](../../README.md). This document exists to give the
methods, metrics, and design decisions behind the 3D representation their
own technical depth, rather than compress them into a short platform
paragraph.

**No "first"/novelty claim without qualification.** Nothing in this
document should be read as asserting that any individual technique here
(adaptive baseline estimation, persistence tracking, connected-component
segmentation of a time-frequency surface) is new to the RF-visualization
literature — no literature, product, or patent search has been performed to
support such a claim. What is described as distinctive (§10) is the
specific *combination* implemented here, in this codebase, over a real live
SDR feed.

---

## 1. Scope and purpose

RF Terrain 3D reads the same live spectrum feed already exposed by
Live Monitor (`GET /api/spectrum/live`) and renders it as a real-time 3D
height field — frequency on one axis, time on another, a selected signal
magnitude as height — instead of, or alongside, the legacy 2D waterfall.
It is a **frontend-only** module: the backend spectrum controller, the SDR
acquisition worker, and the USRP B200 acquisition path are all consumed
as-is, unmodified, through the existing `ApiService`/`useSpectrumController`
contracts.

Directly relevant module and file references used throughout this
document (all paths relative to `frontend/src/features/rf-terrain/`):

```
data/     useRFTerrainFrameSource.ts, frameValidator.ts,
          acquisitionEpoch.ts, spectrumFrameAdapter.ts
engine/   noiseEstimator.ts, persistenceEngine.ts, occupancyEngine.ts,
          holdEngine.ts, averageEngine.ts, ewmaEngine.ts,
          percentileEngine.ts, rollingQuantileWindow.ts,
          terrainSegmentation.ts, ridgeTracking.ts, terrainMetrics.ts,
          ringBuffer.ts, frequencyResampler.ts,
          terrainWorkerState.ts, terrain.worker.ts, objectSelection.ts,
          morphologyClassifier.ts, objectTracker.ts, spectralObjectEnvelope.ts,
          frequencySmoothing.ts, traceSource.ts
render/   RFTerrainRenderer.ts, TerrainMesh.ts, TerrainScene.ts,
          TerrainCamera.ts, TerrainOverlays.ts, TerrainRaycaster.ts,
          TerrainColors.ts, TerrainSelectionOverlay.ts, SpectralObjectEnvelope.ts
ui/       RFTerrainView.tsx, RFTerrainCanvas.tsx, RFTerrainToolbar.tsx,
          RFTerrainOverlaysPanel.tsx, RFTerrainInspector.tsx,
          RFTerrainReceiverControls.tsx, RFTerrainPanControl.tsx,
          RFTerrainProfilesPanel.tsx, RFTerrainStatus.tsx,
          RFTerrainLegend.tsx, RFTerrainFallback2D.tsx, EpistemicTag.tsx
```

`objectSelection.ts`, `TerrainSelectionOverlay.ts`, and `EpistemicTag.tsx`
belong to FSEI (§14); `morphologyClassifier.ts` and `objectTracker.ts`
belong to §6.5/§6.6; `spectralObjectEnvelope.ts` and
`SpectralObjectEnvelope.ts` belong to the Spectral Object Envelope (§15) —
all layered on top of everything else in this list.

---

## 2. Geometry and the "terrain" concept

Axes: frequency bin (X), history row / time (one axis of the mesh), and a
selected magnitude (height). The newest accepted frame is always rendered
at the geometric front of the mesh; each subsequent frame shifts the
existing rows back by one slot (`TerrainMesh.pushRow()`,
[`render/TerrainMesh.ts`](../../frontend/src/features/rf-terrain/render/TerrainMesh.ts)) —
a typed-array shift, never a full reallocation of the vertex buffer.

The camera is positioned so that newly-arrived spectral content appears at
the far end of the visible history and moves toward the viewer as it ages
([`render/TerrainCamera.ts`](../../frontend/src/features/rf-terrain/render/TerrainCamera.ts)),
and the mesh's own `position.z` is interpolated every render frame between
row arrivals — using an exponentially-averaged estimate of the real,
possibly-jittery inter-frame interval, not a fixed assumed cadence — so the
terrain reads as continuous motion at the render frame rate (30-60 FPS)
even though data itself arrives roughly every 100 ms
([`render/RFTerrainRenderer.ts`](../../frontend/src/features/rf-terrain/render/RFTerrainRenderer.ts)).

### 2.1 Height/color modes

| Mode | Height | Default color source |
|---|---|---|
| RAW | Raw power, linearly normalized to a fixed display band | Same value as height (heat-map) |
| ADAPTIVE | Excess above the adaptively-estimated per-bin noise floor (§4.1) | Selectable: magnitude (heat-map), persistence, or occupancy |
| OCCUPANCY | Same as ADAPTIVE | Selectable, defaults toward occupancy reading |
| DENSITY | Same excess as ADAPTIVE, smoothed across the frequency axis (§2.2) | Same smoothed value (heat-map) |

Height and color are deliberately **independent selections** in this
implementation (`RFTerrainColorSource = 'magnitude' | 'persistence' |
'occupancy'`,
[`ui/RFTerrainCanvas.tsx`](../../frontend/src/features/rf-terrain/ui/RFTerrainCanvas.tsx)) —
a viewer can read the same underlying excess-height terrain colored either
as a conventional power heat-map (equal magnitude → equal color, the
default) or with color carrying a second, independent signal (persistence
or occupancy) while height stays fixed to magnitude.

### 2.2 DENSITY mode: frequency-axis smoothing

`engine/frequencySmoothing.ts` (`smoothAcrossFrequency`, pure function,
unit-tested in isolation) applies a normalized triangular convolution
across the bins of a single row's real excess values — a real-time-cheap
`O(bins)` operation per row (default radius 2, a 5-bin-wide kernel),
unlike the Spectral Object Envelope's 2D masked smoothing (§15), which
only ever runs on a small selected sub-region at selection time. DENSITY
mode's SURFACE reads this smoothed curve; nothing else does. Ribbons
(§5), the frequency/hover/selection markers, and every value the click
Inspector reports (§14) keep reading the real, unsmoothed per-bin value in
every mode, including DENSITY — the same raycaster-to-source-data
discipline (§9.3) applied consistently: a rendering readability choice
never becomes the record.

**Never labeled Power Spectral Density.** This mode still plots the same
uncalibrated, noise-referenced excess value ADAPTIVE/OCCUPANCY already
compute — smoothing does not calibrate it, and no `W/Hz` or other PSD unit
is claimed anywhere in this mode, consistent with §7's and §12's explicit
refusal to fabricate PSD from uncalibrated `dBFS` input.

---

## 3. Data pipeline

### 3.1 Single frame producer, backpressure

`useRFTerrainFrameSource`
([`data/useRFTerrainFrameSource.ts`](../../frontend/src/features/rf-terrain/data/useRFTerrainFrameSource.ts))
is the module's only consumer of `/api/spectrum/live`. It polls with a
recursive `setTimeout` (never `setInterval`, so a slow response cannot
cause overlapping requests), keeps exactly one request in flight via a
fresh `AbortController` per poll, and aborts on unmount.

Between the main thread and the analysis Web Worker (§3.3), backpressure
follows a "latest wins" rule: if a new validated frame arrives while the
previous one is still being processed by the worker, the older *pending*
frame is discarded and replaced — never queued — and a
`droppedProcessingFrames` counter is incremented for diagnostics.

### 3.2 Frame validation

`frameValidator.ts` rejects, without throwing, any frame where:
`frequencyArray.length <= 1`; `powerLevels.length != frequencyArray.length`;
any critical value is non-finite; `span <= 0`; `centerFrequency` is
non-finite; the frequency array is not monotonic; or the timestamp is
invalid. Rejected frames are counted (`invalidFrames`) and discarded, never
allowed to propagate an exception.

### 3.3 Acquisition generations

`acquisitionEpoch.ts` computes a composite key per frame — center
frequency, span, sample rate, FFT size, frequency-array length (grid-size
proxy), effective RBW, power unit, source ID, device serial, calibration
ID — and increments a **generation** counter whenever that key changes.
A generation change triggers a `RESET` message to the Web Worker, clearing
every accumulator (ring buffer, noise estimator, persistence, occupancy,
holds, averages, EWMA, percentiles); any worker output still tagged with a
superseded generation is discarded on arrival, so two acquisition
configurations are never mixed into one terrain. Gain, detector, and
averaging settings are not represented in the live-spectrum data contract
and therefore cannot be tracked by this mechanism — a documented gap, not
an oversight.

### 3.4 Frequency resampling

The native FFT (whatever size the backend reports, e.g. 4096 bins) is
resampled by nearest-neighbor decimation
([`engine/frequencyResampler.ts`](../../frontend/src/features/rf-terrain/engine/frequencyResampler.ts))
to a fixed grid of 512 columns before either rendering or analysis.
**Documented simplification:** analysis runs on this same resampled grid
rather than at native precision — the spec this module was built against
called for full-precision analysis alongside a separately-resampled render
mesh; this implementation uses one shared, resampled grid for both.

### 3.5 Web Worker offload

All historical/statistical computation (§4-§6) runs inside a dedicated Web
Worker (`terrain.worker.ts`), which is a thin `postMessage` wrapper around a
pure, dependency-free reducer,
[`engine/terrainWorkerState.ts`](../../frontend/src/features/rf-terrain/engine/terrainWorkerState.ts) —
kept pure specifically so it can be unit-tested directly (§11) without a
real `Worker` object, which is unavailable in the test environment. The
main thread only ever handles rendering, camera/input, and UI.

---

## 4. Adaptive baseline and persistence (ARST core)

### 4.1 Adaptive spectral floor

Per frequency bin, a rolling window of the last *W* raw power samples
(default `W ≈ 30` samples, ≈3 s at the default 100 ms poll interval) is
kept, and its 20th percentile is computed and exponentially smoothed:

```
Q_i(t) = P20 [ P_i(t-W), ..., P_i(t) ]
N_i(t) = β · N_i(t-Δt) + (1-β) · Q_i(t)          (β = 0.7, default)
```

(`engine/noiseEstimator.ts`, backed by the shared sliding-window utility
`engine/rollingQuantileWindow.ts`.) **Documented limitation:** a
continuously-present signal spanning the whole window is itself absorbed
into `Q_i(t)`, so a perfectly stable carrier's estimated excess height
decays toward zero after roughly one window duration — this is a known,
tested property of the estimator (§11), not a rendering bug. RAW mode
height is unaffected by this, since it plots raw power directly rather
than baseline-referenced excess.

### 4.2 Noise-referenced excess (height)

```
E_i(t) = clip( P_i(t) - N_i(t), 0, H_max )        (H_max = 40 dB, default)
```

This value is deliberately never labeled "SNR" in the UI — `N_i(t)` is an
estimated, uncalibrated local baseline, not a calibrated noise-power
reference.

### 4.3 Persistence

An independent, exponentially-decaying indicator of how consistently a bin
has been active, tracked as its own signal rather than derived from
height:

```
A_i(t) = 1 [ E_i(t) > θ ]                          (θ = 6 dB, default)
ρ_i(t) = e^(-Δt/τ) · ρ_i(t-Δt) + (1 - e^(-Δt/τ)) · A_i(t)   (τ = 2 s, default)
```

(`engine/persistenceEngine.ts`.) A brand-new, momentarily strong emission
and a long-running one at the same peak height render at the same height
but different persistence color.

### 4.4 Occupancy

Same exponential-decay mechanism as persistence, with its own longer time
constant (τ ≈ 20 s, default) and driven by the **real elapsed time**
between accepted frames rather than a raw frame count — polling jitter or
a dropped frame does not distort the ratio
(`engine/occupancyEngine.ts`). This is implemented as a continuous online
approximation of a windowed active-time-over-total-time ratio, documented
here as an approximation rather than an exact windowed sum.

---

## 5. Reference statistics (Live Monitor Spectrum Tools, read in 3D)

Computed per bin, every accepted frame, inside the same Web Worker:

| Overlay | Formula | File |
|---|---|---|
| Max Hold | `M_i(t) = max(M_i(t-Δt), P_i(t))` | `engine/holdEngine.ts` |
| Min Hold | `m_i(t) = min(m_i(t-Δt), P_i(t))` | `engine/holdEngine.ts` |
| Power Average | linear-domain EWMA: `P̄_lin(t) = (1-α)·P̄_lin(t-Δt) + α·10^(P_i(t)/10)`, `P_avg,dB = 10·log10(P̄_lin)` (α = 0.2) | `engine/averageEngine.ts` |
| EWMA | dB-domain: `S_t = α·X_t + (1-α)·S_{t-1}` (α = 0.3) | `engine/ewmaEngine.ts` |
| Percentiles P50/P90/P95/P99 | Quantiles of the same rolling window used by §4.1 | `engine/percentileEngine.ts` |

**RMS is not computed as an independently-derived metric.** Live Monitor's
own RMS is a linear-power-domain statistic; with only per-bin power in dB
available (no I/Q), it reduces to the exact same formula as Power Average
above. Rather than fabricate a cosmetically distinct number, RMS is
presented as an alias of Power Average, and this equivalence is stated
explicitly in the module's own UI (Overlays panel).

All five are rendered as thin front-edge reference ribbons
(`render/TerrainOverlays.ts`), individually toggleable, never as a second
full duplicate terrain surface.

### 5.1 Terrain trace source: applying a statistic to the whole surface

The ribbons above are additive lines drawn on top of the live terrain.
Separately, `engine/traceSource.ts` (`pickTraceValues`, pure function,
unit-tested in isolation) lets the terrain SURFACE itself be driven by any
one of the same already-computed per-bin quantities -- `live` (the
default), `maxHold`, `minHold`, `average`, `ewma`, `p50`, `p90`, `p95`, or
`p99` -- instead of the live power level. This never introduces a new
statistic: it only changes which already-real array `ui/RFTerrainCanvas.tsx`
reads as the height/color source, both for the terrain and (for
`density` mode) for the frequency-smoothing input (§2.2).

Two scopes control how far a trace-source change reaches:

- **`liveEdgeOnly`** (default) -- only rows arriving from that point on use
  the new source; rows already on screen keep whatever they were rendered
  with, matching every mode/colormap/color-source change's existing
  behavior in this module.
- **`entireHistory`** -- every row currently visible is repainted from ITS
  OWN real, previously-cached `TerrainProcessedRow` (the same
  `historyRef` cache the raycaster and rewind window already use) under
  the newly-selected trace source, mode, colormap, and color source
  together. This is the retroactive-repaint mechanism, not a special
  case of it -- switching mode or colormap while in `entireHistory` scope
  repaints the whole visible window too. Every repainted row is a real
  measurement that actually happened; nothing is fabricated to fill a gap
  (a missing cached row still renders as the unknown-row fog color, §9.2).

---

## 6. Terrain Objects (morphological segmentation)

### 6.1 Hysteresis (dual-threshold) mask and connected-component labeling

```
M_seed(f,t) = 1 [ E(f,t) > θ_H ]      (θ_H = 8 dB, default)
M_grow(f,t) = 1 [ E(f,t) > θ_L ]      (θ_L = 6 dB, default)
```

`engine/terrainSegmentation.ts` performs 8-connected (time/frequency
adjacency, INCLUDING diagonals) connected-component labeling over the
worker's own bounded history buffer, via iterative flood fill (explicit
stack, not recursive, to avoid call-stack limits on large regions), using
the same dual-threshold ("hysteresis") rule Canny edge detection uses: a
component is only ever CREATED at a cell above the higher seed threshold
`θ_H`, but once seeded it GROWS through any connected neighbor above the
lower grow threshold `θ_L`. A single-threshold rule (`θ_H === θ_L`, still
supported) fractures one real, continuously-active emission into many
disconnected slivers the moment it dips slightly below the line; hysteresis
absorbs that dip without lowering the bar for what starts a component in
the first place. 8-connectivity (rather than 4) additionally keeps a
diagonally-drifting ridge (a real chirp) as one component instead of
splitting it wherever it crosses exactly one bin per one row with no
shared edge, only a shared corner.

Three **physical filters** (`SegmentationFilters`: `minCellCount`,
`minRowSpan`, `minColSpan`, `minPeakExcessDb`) can additionally reject a
connected region below a minimum size/duration/bandwidth/peak — available
as real, tested knobs; the shipped defaults leave `minRowSpan`/`minColSpan`
permissive (a real single-row/single-bin burst is a legitimate detection,
morphologically classified `TRANSIENT`/`ISLAND` rather than filtered away)
so short real bursts are never silently discarded without validation data
to justify a stricter default.

Segmentation also produces a `labelGrid` (`Int32Array`, row-major,
component index or `-1`) alongside the component list — used internally
(and by the Spectral Object Envelope, §15) to know exactly which cells a
component contains, without shipping the full grid off the worker thread
in bulk (see §15's masking discussion for why the main thread does NOT
receive this grid directly).

Segmentation is intentionally **not run every frame** — it is triggered on
its own, slower cadence (every 2 s), independent of whether the operator
has the objects LIST panel open (§6.5), a deliberately separate rate
domain from the ~10 Hz frame-processing rate.

### 6.2 Ridge slope

For each object, the per-row peak-excess bin is recorded, and an ordinary
least-squares fit of frequency against timestamp gives a ridge velocity:

```
v_f = df/dt   (least-squares slope over the object's (t_row, f_peak) samples)
```

(`engine/ridgeTracking.ts`.) Ridge **curvature** is not computed in this
implementation (documented gap, not silently approximated).

### 6.3 Terrain Volume Index (TVI)

A purpose-built, explicitly **non-physical** morphology metric:

```
TVI = Σ_(f,t) max(E(f,t) - θ, 0) · Δf · Δt
```

accumulated directly during the same flood-fill pass (not a second
traversal) and reported per object.

### 6.4 Per-object metric set

`engine/terrainMetrics.ts` assembles, per detected object:
`start_time`, `end_time`, `duration_s`, `start_frequency_hz`,
`stop_frequency_hz`, `center_frequency_hz`, `bandwidth_hz`,
`peak_excess_db`, `mean_excess_db`, `frequency_centroid_hz`,
`temporal_centroid_s`, `terrain_volume_index`, `ridge_slope_hz_per_second`
(nullable), `cell_count`, `morphology` (§6.5), `track_id`, and `active`
(§6.6). Objects are surfaced as selectable regions in the Inspector panel.

**Explicitly not implemented:** spectral/temporal entropy, duty-cycle
estimate, frequency excursion — and, deliberately, no protocol/device
label. A detected shape is reported as a morphological region only; it is
never presented as a decoded protocol or an identified device, matching
the same discipline the main platform already applies to the RF
Intelligence overlay.

### 6.5 Morphological classification

`engine/morphologyClassifier.ts` derives a purely geometric label from a
component's own bounding-box shape (row/column span, cell-fill ratio, and
ridge slope) — never a protocol/device label:

| Value | Geometric signature |
|---|---|
| `DRIFTING` | Ridge slope magnitude at/above a documented threshold (2000 Hz/s default) — a real chirp |
| `IRREGULAR` | Connected-cell fill ratio below 35% of its own bounding box — sparse/holey, not a solid shape |
| `TRANSIENT` | Exactly one time-row |
| `PLATEAU` | Wide (≥4 columns, and ≥ its own row span) and short-lived (≤3 rows) |
| `RIDGE` | Narrow and long-lived (row span ≥4 and ≥2× its own column span) |
| `ISLAND` | Everything else — a brief, narrow burst |
| `HOPPING_CLUSTER` | Never assigned here — see §6.6, cross-pass context only |

### 6.6 Stable tracking and re-triggering (`trackId`)

Every SEGMENT pass re-segments the WHOLE bounded history window from
scratch (§6.1) — there is no incremental per-object state inside
segmentation itself. `id` (e.g. `obj-42-3`) is therefore recomputed fresh
every pass and is **not** stable across passes. `engine/objectTracker.ts`
assigns a separate, stable `trackId` (`RF-TRACK-000123`) by matching each
new pass's objects against the previous pass's real (frequency, time)
footprints — a persisting emission's own bounding box only grows or slides
slightly between two 2-second-apart passes, so a frequency-overlap-ratio
match (≥30% of the larger bandwidth, by default) within a small
cadence-sized continuity window (3 s default) is enough to recognize "the
same object, still going" without needing any worker-internal index.

An object with `active: true` is still being detected in the most recent
row of the current pass; `active: false` means its last detected row has
already receded into the past (but it may still be within the bounded
history window, and therefore still selectable/visible).

**Re-triggering (hopping) heuristic.** A new object with no continuously-
overlapping lineage, appearing within a longer window (10 s default) of a
recently-ended lineage and close to it in frequency (500 kHz default
tolerance), is treated as that lineage re-triggering rather than a
brand-new track — real signal-processing intuition, but a documented
heuristic, never a certainty. Once a lineage has re-triggered at least
twice (default), its morphology is overridden to `HOPPING_CLUSTER`
regardless of any single detection's own shape — the only morphology value
that requires cross-pass context, and the only one this tracker is
permitted to assign (§6.5 lists the rest, computed once, at segmentation
time, from a single component's own shape).

**Known parameter gap.** The interactive "Spectrum Mask" plane the operator
can position in the 3D view (§8) is a separate, user-adjustable rendering
reference and is **not** wired to the segmentation thresholds `θ_H`/`θ_L`
above. This is a real, current limitation, not an intentional design
choice presented as one.

---

## 7. Unit and calibration discipline

- `TerrainInputFrame` carries `powerUnit` (`dBFS`/`dBm`) and
  `calibrationId` through the entire pipeline; the Inspector always
  displays both alongside every value, never a bare number.
- RAW mode's display band (`[-100, -20]` dB, default) is an explicit
  **visual normalization constant**, not a scientific claim about the
  input's dynamic range.
- No Power Spectral Density, no physical energy/Joules figure, and no
  voltage/amplitude value is derived anywhere in this module. The original
  design spec this module follows explicitly prohibits fabricating PSD or
  energy from uncalibrated `dBFS` power, and neither is implemented here —
  not a partial or approximate version, simply absent.
- The purely-visual height exaggeration applied to the rendered mesh
  (`RF_TERRAIN_HEIGHT_VISUAL_SCALE`, a constant multiplier) is applied only
  to GPU geometry. Every value shown by the Inspector or exported (CSV)
  comes from the unscaled analytical model
  (`historyRef` lookup resolved from a raycaster hit — see §9.3), never
  read back from the exaggerated render geometry.

---

## 8. Interaction: freeze, reset, rewind, mask, receiver controls

- **Freeze** stops only data evolution (the hook stops forwarding frames to
  the worker); camera, selection, and the Inspector remain fully
  interactive.
- **Reset Terrain** clears history, holds, averages, the noise estimator,
  persistence, occupancy, and terrain objects, without touching device
  connection, streaming state, or tuning.
- **Bounded rewind.** A main-thread history cache is kept at 3× the live
  render depth (720 rows vs. 240 rendered live, ≈72 s vs. ≈24 s at the
  default poll rate) — a deliberately **capped** lookback window, not an
  unbounded buffer. A slider lets the operator scrub up to roughly 48 s
  back into that cache; live rows keep accumulating in the background while
  scrubbed, so returning to LIVE is instant.
- **Spectrum Mask.** A user-set threshold (in the active mode's height
  units) renders a translucent reference plane across the terrain — purely
  a visual reference (see the known gap in §6.6).
- **Receiver controls and frequency profiles.** Center/span/start-stop/
  sample-rate/RBW/VBW/reference-level/gain/detector/averaging controls, and
  a searchable list of frequency-band presets, both reuse
  `useSpectrumController` and the existing, shared `RF_PROFILES` table
  (`frontend/src/shared/rfProfiles.ts`) — the same controller and the same
  band presets Live Monitor's own controls already use, rather than a
  second, independent implementation.

---

## 9. Rendering technique

### 9.1 Scene and material

Three.js, used directly (not React Three Fiber). `MeshStandardMaterial`
with vertex colors and two directional lights (plus ambient) give the
terrain a real diffuse lighting response — earlier iterations used an
unlit `MeshBasicMaterial`, under which peaks/ridges did not read as 3D
relief. Scene fog is used for depth cueing. No shadow maps, bloom, or
post-processing.

### 9.2 Unobserved rows after a reset: fog, never a fabricated duplicate

An earlier version of this renderer worked around the empty-foreground
issue below by writing the FIRST post-reset row into every history slot at
once (`seedFill()`) — visually smooth, but scientifically dishonest: it
made one real measurement look like ~24 s of real history that was never
actually observed. That mechanism has been **removed**.

The real issue it was covering for is still real: naively clearing all 240
history rows on a `RESET` (e.g. after a large frequency retune) leaves a
large flat, empty region dominating the near field of view — since the
oldest/emptied rows sit closest to the camera under the "captures approach
the viewer" camera framing (§2) — while real data only slowly "grows" back
from the far edge over the full history duration. The current fix changes
what "empty" looks like instead of faking what fills it: `TerrainMesh`'s
neutral clear color is set to match the scene's own background/fog color
exactly (`0x050810`) rather than an arbitrary near-black. An unobserved row
optically recedes into the same fog the horizon already uses, instead of
reading as a distinct dark wall blocking the signal or as fabricated
terrain. Real rows still grow in from the front exactly as fast as they
are actually measured — honest, and no longer masked by an artificial
"instant full terrain" illusion.

### 9.3 Raycasting resolves to source data, not shader output

Clicking the terrain projects a ray against the mesh, resolves the nearest
vertex to a `(row, column)` pair
(`render/TerrainRaycaster.ts`), and looks that pair up in a main-thread
history cache of the original, unscaled `TerrainProcessedRow` objects — the
Inspector's values are always the real analytical-model output for that
cell, never interpolated from the (visually exaggerated, GPU-side) mesh
geometry.

### 9.4 Context loss and fallback

`webglcontextlost`/`webglcontextrestored` listeners stop the render loop
and attempt recovery without reloading the page. When WebGL is unavailable
at all, `RFTerrainFallback2D` renders a lightweight 2D canvas view (latest
trace + a small heatmap) fed by the same frame-source hook — never the full
legacy Waterfall view, which would start a second, competing polling loop.

---

## 10. What is distinctive about this implementation

Not any one technique in isolation (adaptive local baselines, persistence
tracking, and connected-component segmentation of a time-frequency surface
are all well-established ideas). What this module combines, concretely, in
one real-time pipeline over a live SDR feed:

- Height and color as **independently selectable** encodings of the same
  underlying data (§2.1), rather than one fixed visual mapping.
- A per-bin adaptive baseline (§4.1) with its own documented failure mode
  (§4.1), rather than a single global reference level.
- Morphological object extraction with a full, quantitative per-object
  metric set including a purpose-built terrain-volume metric (§6), with an
  explicit refusal to attach a protocol/device label to a detected shape.
- Camera presets that make the same underlying geometry read as a
  conventional waterfall (TOP) or a conventional spectrum trace (FRONT),
  connecting the 3D view back to the platform's existing 2D representations
  rather than replacing their reading conventions outright.
- A raycaster-to-source-data discipline (§9.3) that keeps the GPU strictly
  a rendering layer, never the analytical source of truth — the same
  discipline the rest of SpectraRFˣ already applies to its BLE-RFFI
  evidence chain.
- A per-field epistemic-status tagging discipline in the click Inspector
  (§14.4) that extends this same "never overstate what is known" posture
  from the BLE-RFFI evidence chain into the 3D view itself — a measured
  value, a derived metric, and an unavailable hypothesis are never given
  the same visual weight.
- A reconstruction layer (§15) that is visually additive but analytically
  inert: the Spectral Object Envelope can make a selected object read as a
  coherent mountain instead of a field of individual FFT-bin spikes, while
  every number the Inspector shows still comes from the same unsmoothed,
  unmasked raw grid the envelope is built FROM — the reconstruction never
  becomes the record.

---

## 11. Test coverage

209 unit/component tests across 34 files (`frontend/src/features/rf-terrain/tests/`,
including `tests/offline/`), run via
`npx vitest run --config vitest.config.ts src/features/rf-terrain` from
`frontend/`:

| File | What it verifies |
|---|---|
| `ringBuffer.test.ts` | Bounded size, correct wrap, chronological reconstruction, no memory growth |
| `frameValidator.test.ts` | Every malformed-frame case (NaN, Infinity, empty/mismatched arrays, non-monotonic frequency, bad timestamp) rejected without throwing |
| `acquisitionEpoch.test.ts` | Generation increments exactly on an acquisition-relevant key change; unaffected by unrelated field changes |
| `noiseEstimator.test.ts` | Converges toward the P20 floor; documents the continuous-signal absorption limitation as an asserted, expected behavior |
| `persistenceEngine.test.ts` | Rises/decays correctly; time-aware (same activation over a longer Δt moves persistence further) |
| `occupancyEngine.test.ts` | Time-aware convergence; jittered cadence converges to the same ratio as regular cadence |
| `holdEngine.test.ts` | `Min ≤ Live ≤ Max` invariant; monotonicity of each hold |
| `averageEngine.test.ts` | Linear-domain averaging verified against the naive dB-mean to confirm it is *not* a naive arithmetic mean |
| `ewmaEngine.test.ts` | Exact α-weighted blending; distinct from the linear-domain average engine |
| `percentileEngine.test.ts` | P50 ≤ P90 ≤ P95 ≤ P99 ordering; P99 responds correctly once strong samples enter the window |
| `frequencyResampler.test.ts` | Exact output length; no out-of-bounds source reads; graceful empty-input handling |
| `terrainSegmentation.test.ts` | Continuous carrier → one long ridge; single burst → one short island; frequency hopping → multiple islands; wideband block → one broad, short plateau; never attaches a protocol label; hysteresis absorbs a weak dip only when adjacent to a seed, never grows without one; 8-connectivity merges a diagonal run; physical filters reject undersized/weak components; `labelGrid` correctness on accepted and rejected components |
| `ridgeTracking.test.ts` | Correct slope sign/magnitude for ascending/descending/stationary synthetic chirps |
| `terrainWorkerState.test.ts` | Generation-based stale-message discard; RESET clears every accumulator, not just the ring buffer; capacity never exceeded |
| `useRFTerrainFrameSource.test.tsx` | Disabled state touches neither network nor Worker |
| `rfTerrainCapabilities.test.ts` | WebGL detection fails closed (never throws) |
| `rfTerrainLifecycle.test.tsx` | Module renders; local render failures stay contained to the module's own error boundary |
| `objectSelection.test.ts` | FSEI hit-test: exact match, outside-box → null, inclusive boundary, overlap tie-break toward the more-recently-started object, empty list → null |
| `terrainSelectionOverlay.test.ts` | FSEI reticles: hidden by default, placed at the given local position, age back one row per call, hide and report OUT_OF_VIEW once past the history depth, hover/selected independence, safe disposal |
| `morphologyClassifier.test.ts` | Each geometric signature (DRIFTING/IRREGULAR/TRANSIENT/PLATEAU/RIDGE/ISLAND) maps to its documented shape condition; never returns a protocol-shaped value |
| `objectTracker.test.ts` | Fresh objects get a stable-looking trackId; a persisting emission keeps the same trackId across passes; an unrelated frequency gets a different trackId; only the most-recently-ending object(s) in a pass are `active`; a recently-ended lineage reactivates near the same frequency; repeated reactivation overrides morphology to HOPPING_CLUSTER; `reset()` restarts numbering |
| `spectralObjectEnvelope.test.ts` | Empty/degenerate (single row or column) inputs return null; heights grid sized to the real frequency/time sub-window; below-threshold cells masked out; a missing row leaves its cells honestly unmasked rather than fabricated; masked normalized-convolution smoothing does not leak in zeros from outside the mask; frequency argument order is order-independent |
| `spectralObjectEnvelopeMesh.test.ts` | Hidden with no mesh until built; positioned at the envelope's real meshRowOffset; ages back one row per call; hides and reports OUT_OF_VIEW past the history depth; rebuilding disposes the previous mesh; hide()/dispose() do not throw |
| `frequencySmoothing.test.ts` | radius=0 is a no-op; a flat row stays flat; a lone spike spreads into real neighbors; edge bins are a true local average, never diluted by a phantom zero; array length preserved; single-element input handled |
| `traceSource.test.ts` | Each trace source (live/maxHold/minHold/average/ewma/p50/p90/p95/p99) returns the matching real per-row field, by reference -- never a fabricated array |
| `offline/fft.test.ts` | DC signal, pure-sinusoid bin concentration, Parseval's theorem, determinism, Hann window shape, magnitude-spectrum peak location |
| `offline/iqBytes.test.ts` | cf32_le byte parsing correctness; unsupported `sample_format` fails closed rather than misinterpreting bytes |
| `offline/captureMetadata.test.ts` | Real manifest fields extracted/validated field-by-field; fails closed with a specific reason on anything missing or malformed |
| `offline/captureClient.test.ts` | Manifest + Range-based `/iq` requests against the real, audited endpoint paths; inverted/negative ranges rejected before ever calling `fetch` |
| `offline/spectrumGenerator.test.ts` | Sample-index-based timestamps; chunk-boundary-independent determinism (identical output for one big chunk vs. many uneven small chunks) |
| `offline/contextAudit.test.ts` | C1/C2/C4 computed only from already-computed engine outputs; C4 returns `NaN` (not a fabricated zero) for a zero-duration/bandwidth window |
| `offline/reconstructionProfile.test.ts` | Hop size never smaller than `fftSize`; profile/reconstruction hashes deterministic and sensitive to every real input |
| `offline/offlineReconstructionController.test.ts` | Only the two real read-only capture endpoints are ever called (isolation from LIVE/SDR); reconstruction is deterministic end-to-end; unsupported `sample_format` fails closed; playback speed never changes replayed row values |
| `offline/sourceEvidence.test.ts` | FSEI sample-range derivation is an exact inverse of the real timestamp formula, for the first frame and arbitrary later frames; flags a timestamp that could not have come from the given evidence |

---

## 12. Explicitly not implemented

- **Multiresolution long-history compression** ("Spectral Geology" in the
  original design spec) — the bounded 3× rewind cache (§8) is used instead
  of an unbounded, progressively-aggregated history.
- **Power Spectral Density and physical energy/TVI-as-energy** — never
  fabricated from uncalibrated `dBFS` input (§7).
- **Gated Spectrum** — no gated-acquisition mode exists in the current
  backend to expose.
- **Zero Span** — requesting `span = 0` from the device would produce
  frames this module's own validator rejects (`span > 0`, §3.2); would need
  a dedicated data path, not a parameter toggle.
- **RF Intelligence overlay adapter** — optional in the original design
  spec, not built; no RF-object-detection model coupling exists between the
  two modules.
- **Ridge curvature**, entropy, fragmentation, duty-cycle estimate.
- **Independently-tunable object-segmentation threshold** (§6.6 known gap)
  — the interactive Spectrum Mask plane is not wired to `θ_H`/`θ_L`.
- **I/Q-evidence linkage for terrain objects** (§14.5) — no mechanism
  preserves or links a raw I/Q capture to a specific detected terrain
  object; FSEI's Evidence section renders this honestly as unavailable
  rather than simulating a link.
- **RF Intelligence hypothesis coupling inside FSEI** (§14.5) — same
  underlying gap as the RF Intelligence overlay adapter above; FSEI's
  Intelligent-hypothesis section never invents a device/protocol guess.
- **Physical-source signature comparison library** (§14.5) — no reference
  library of known-device RF signatures exists to compare a terrain object
  against.
- **Exact per-cell object-index grid shipped to the main thread** (§14.1,
  §15.1) — the worker computes one internally for its own segmentation
  pass, but a bounding-box match is used for click hit-testing and a
  per-cell magnitude gate is used for the Spectral Object Envelope's mask;
  both are documented tradeoffs, not oversights, and a real
  `PICK_OBJECT`/exact-mask worker round-trip remains a possible future
  step rather than something silently approximated as already-exact.
- **HOPPING_CLUSTER re-triggering is a documented heuristic** (§6.6) —
  frequency proximity plus a time window, not a certainty; never presented
  as a confirmed protocol-hopping pattern.
- **I/Q-evidence linkage for LIVE terrain objects** — unchanged by §16
  below: a LIVE selection still has no preserved capture to link back to,
  and FSEI's Evidence section still renders this honestly as unavailable
  for LIVE specifically. Only an OFFLINE-reconstructed selection gets a
  real Evidence section.
- **Offline Reconstruction's Context Audit C3/C5** (§16.5), main-thread
  execution during a large reconstruction, export/reporting with
  provenance, a BLE evidence overlay, and cancellation-mid-fetch UI polish
  are documented gaps within that feature specifically — see §16.6.

---

## 13. Relationship to the legacy Waterfall

RF Terrain 3D does not replace the legacy Waterfall's backend or data
contract — both read the same `/api/spectrum/live` endpoint independently.
The Waterfall route (`/waterfall`) remains fully operational and reachable
directly, including from links inside RF Terrain's own fallback views, as
described in the main [`README.md`](../../README.md#platform-modules-and-ui).

---

## 14. FSEI — Forensic Spectral Evidence Inspector

FSEI extends the click Inspector (§9.3) from a flat value dump into a
click-to-select, pin-and-review workflow with an explicit accounting of
what is actually known about a selected terrain object versus what would
need capability this build does not have. It changes only the interaction
and presentation layer — no new statistic, no new segmentation rule, and
no new data source. Every number FSEI shows was already computed by the
engines in §4–§6; FSEI's own code
(`engine/objectSelection.ts`, `render/TerrainSelectionOverlay.ts`,
`ui/EpistemicTag.tsx`, the rebuilt `ui/RFTerrainInspector.tsx`) is
presentation and selection logic only.

### 14.1 Selection: click, pin, hover

Clicking the terrain resolves a `(row, column)` cell exactly as in §9.3,
then matches it against the currently-segmented terrain objects
(`findObjectAtPoint`, `engine/objectSelection.ts`) by testing the clicked
`(frequencyHz, timeSeconds)` point against each object's own measured
bounding box (`start/stopFrequencyHz`, `start/endTimeSeconds` — the exact
fields §6 already computes, never a second independent notion of "where
the object is"). This is a deliberate simplification against the
originally-proposed design of a per-cell `Uint32Array` object-index grid:
building that grid would require reconciling two incompatible indexing
conventions across the worker/main-thread boundary (the worker's
chronological output order versus the main thread's unshift-based history
cache), assessed as materially more implementation risk than the benefit
for what is, in practice, a handful of simultaneously-visible objects. The
tradeoff is honest and documented in code: matching is `O(object count)`
per click (effectively instant at real object counts) rather than `O(1)`,
and a click can occasionally fall inside an object's bounding box without
falling inside its exact irregular segmented shape.

A **first click** selects (unpinned). A **second click on the same
target** (same object id, or the same frequency column for a plain point)
toggles **pinned**, so an operator can keep a specific detection under
review while the terrain continues flowing underneath it. Clicking a
*different* target always starts a fresh, unpinned selection. Mouse
movement over the terrain shows a lighter, throttled (~16 Hz) cyan hover
preview — a pure visual aid, it never touches selection state, issues an
HTTP request, or schedules Worker work.

### 14.2 Reticles, not bounding-box overlays

The selected (gold, `#d4af37`) and hovered (cyan, `#67e8f9`) targets are
marked with a small ring + crosshair built from primitive `RingGeometry`
and `LineSegments` (`TerrainSelectionOverlay.ts`) — no textures, no
bloom/post-processing, no shadow maps, matching §9.1's lightweight
material policy. Both are children of the same `TerrainMesh.mesh` group
the reference ribbons (§5) are parented under, so they inherit the same
continuous flow interpolation "for free" instead of needing their own
per-frame position math. Between live row arrivals, the selected reticle
ages back by exactly one row per newly-accepted row
(`ageSelectedByOneRow`), mirroring `TerrainMesh.pushRow()`'s own
one-row content shift — the same mechanism, not a second independent
motion model.

For a `TERRAIN_OBJECT` selection specifically, the gold reticle is joined
by a second, larger visual: a real reconstructed surface patch over the
object's own measured cells (the Spectral Object Envelope, §15) — the
reticle alone stays the primary marker for a plain `POINT` selection.

### 14.3 OUT OF VIEW

The bounded rewind cache (§8) is finite; a pinned selection's row
eventually ages past it. When the reticle's row index reaches the visible
history depth, `TerrainSelectionOverlay` hides it and reports the
transition back to the renderer, which — only if the selection is
currently **pinned** — flags it `outOfView: true` instead of silently
discarding it. The Inspector then shows an explicit "FUERA DE VISTA"
banner with the last real known values, rather than either quietly
dropping the selection or pretending it is still live. An **unpinned**
selection that ages out is simply cleared: it was never meant to survive
past the click that made it. Unpinning an already-out-of-view selection
clears it outright, since there is nothing left for "unpinned" to mean at
that point.

### 14.4 Epistemic status tagging

Every value in the Inspector is tagged with what kind of knowledge it
represents (`EpistemicStatus` in `model/rfTerrainTypes.ts`: `MEASURED`,
`DERIVED`, `HYPOTHESIS`, `EVIDENCE`, `SIMULATED`), rendered via
`EpistemicTag` with both a distinct color *and* a text label — never color
alone, so the distinction survives a grayscale reproduction. Raw values
read directly off the raycaster hit (power, frequency, timestamp) are
`MEASURED`; everything computed on top of them by the ARST/object engines
(noise floor, excess, persistence, occupancy, holds, average, EWMA,
bandwidth, duration, TVI, ridge slope) is `DERIVED`. This is a
zero-tolerance rule in the sense that no code path is permitted to render
a `HYPOTHESIS`-grade value with a `MEASURED`- or `EVIDENCE`-grade visual
weight.

### 14.5 The compact HUD and the seven-section dossier

By default the Inspector shows a compact set of ~7 fields (frequency,
time, raw power, noise floor, excess, persistence, occupancy) plus the
associated object id and the pin toggle. An "Expediente forense completo"
control expands it into seven sections: **(1) Measurement** — the raw
per-bin values only; **(2) Terrain derivation** — every ARST/reference
quantity for that cell; **(3) Context** — the matched object's full
metric set from §6 (or an explicit "does not apply, this is a point
selection" notice, never a fabricated per-object metric for a point);
**(4) Evidence**, **(5) Intelligent hypothesis**, and **(6)
Physical-source comparison** all render an honest, literal unavailable
notice — no I/Q-capture-to-terrain-object link, no RF Intelligence adapter
coupling (consistent with §12's existing "not implemented" list), and no
physical-source signature library exist in this build, so none of the
three is simulated or approximated; **(7) Quality/uncertainty** — power
unit, calibration id, acquisition generation, and the fixed 512-bin
render/analysis grid (§3.3).

### 14.6 What FSEI explicitly does not add

- No new HTTP request or Worker message is issued by any click, pin, or
  hover interaction — selection is resolved entirely from data already
  held in the main-thread history cache (§9.3).
- No I/Q-evidence linkage, RF Intelligence hypothesis, or physical-source
  comparison is fabricated to fill the dossier's Evidence/Hypothesis/
  Comparison sections — see §14.5 and the updated §12.
- No exact per-cell object-index grid — see the documented bounding-box
  tradeoff in §14.1.

---

## 15. Spectral Object Envelope (SOE)

Selecting a `TERRAIN_OBJECT` (as opposed to a plain `POINT`, §14.1) now
renders a second, distinct visual: a small, real, gold metallic surface
patch reconstructed from that object's own measured cells, replacing the
point reticle alone as the primary "this is what got selected" cue. This
addresses a real, reported readability problem: a raw per-bin height field
of narrow FFT bins reads as a dense field of thin spikes ("wheat") rather
than a coherent shape, because every bin is plotted independently. The
envelope is a reconstruction layer on top of that raw field, built ONLY
for the selected object, ONLY at selection time — it never replaces or
alters the underlying scientific terrain, which keeps rendering the exact
same raw, un-smoothed 512-bin grid it always has.

### 15.1 What it is built from

`engine/spectralObjectEnvelope.ts` (pure function, unit-tested in
isolation) takes the real, already-cached `TerrainProcessedRow` entries
spanning the selected object's own measured `[startTimeSeconds,
endTimeSeconds]` range — the SAME main-thread history cache the raycaster
and Inspector already treat as the source of truth (§9.3), never a second,
independent data source — and the object's own `[startFrequencyHz,
stopFrequencyHz]` range, mapped to bin indices via nearest-frequency
lookup (the same technique the frequency marker and hover reticle already
use).

**Masking is an honest, documented approximation**, not the object's exact
segmented shape: a cell counts as a real member of the envelope if its own
excess exceeds the segmentation grow threshold `θ_L` (§6.1) — a per-cell
magnitude gate, not the worker's exact flood-filled connected shape. The
worker DOES compute an exact per-cell `labelGrid` during segmentation
(§6.1), but it is deliberately never shipped to the main thread in bulk
(the same "don't transmit ~120k values continuously" reasoning behind the
bounding-box click-hit-test tradeoff, §14.1) — a real, current limitation,
not a hidden one. In practice, after §6.1's hysteresis/8-connectivity
change, the magnitude-gated approximation and the object's true shape
usually agree closely, because hysteresis already suppresses most of the
disconnected, sub-threshold noise a plain magnitude gate alone would
otherwise pick up.

### 15.2 Masked, normalized-convolution smoothing

Within the masked cells only, a small 3×3 normalized-convolution kernel
(Gaussian-shaped weights) smooths the raw excess values:

```
S(r,c) = Σ_masked-neighbors w·E(r,c)  /  Σ_masked-neighbors w
```

Unmasked neighbors contribute neither value nor weight to this sum —
critically different from a naive unmasked convolution, which would drag
every cell near the object's true edge toward zero by blending in the
surrounding background. The envelope's own edges therefore stay close to
where the real, thresholded shape actually ends, rather than fading out
into a soft, padded rectangle covering the whole bounding box.

### 15.3 Rendering: gold metallic, sparse triangulation, row-aged

`render/SpectralObjectEnvelope.ts` builds ONE small `BufferGeometry` from
the engine output, triangulating a quad only when all four of its corner
cells are real (masked) members — an organic, irregular silhouette that
follows the object's approximate real shape instead of padding it into a
solid rectangle. Material: `MeshStandardMaterial`, flat gold
(`0xd4af37`), `metalness=0.7`, `roughness=0.28`, a low emissive tint — no
bloom, no environment map, no post-processing, consistent with §9.1's
lightweight-material policy; the metallic read comes from material
parameters and the scene's existing two directional lights, not from
expensive render passes.

Built once per selection (or re-selection), never per render frame — a
real object's cell count is small (tens to a few hundred cells), nothing
like the ~120k-vertex main terrain. It is parented under the same
`TerrainMesh.mesh` group the reference ribbons and selection reticles
already are, and ages back by exactly one row per newly-accepted terrain
row via the identical `ageByOneRow` idiom `TerrainSelectionOverlay`'s
reticles use (§14.2) — the same mechanism, not a second independent motion
model — hiding itself once it ages past the visible history depth. A
rewind (§8) hides it outright, for the same reason markers are hidden
during a rewind (§14.1): its position would otherwise point at stale
content after `renderStaticWindow` repaints every row slot from scratch.

### 15.4 What SOE explicitly does not do

- Never alters the underlying terrain's own raw height/color data — a
  purely additive overlay.
- Never fabricates cells beyond the object's own real, measured excess
  values — smoothing only *redistributes* existing masked values via a
  normalized convolution, it never invents a new high point.
- No exact per-cell connected shape (§15.1) — a documented magnitude-gate
  approximation, not the worker's exact `labelGrid`.
- No per-frame rebuild — built once at selection, aged like every other
  overlay in this module.

---

## 16. Offline Spectral Reconstruction from Preserved I/Q

### 16.1 What this is, and what it deliberately is not

A second, strictly isolated frame source for the same rendering/analysis
engine described in §2-§9: instead of polling `/api/spectrum/live`, it
streams a preserved BLE I/Q capture from the platform's own capture store
and reconstructs the same 3D terrain from it offline. It exists for one
reason — studying the spectral context immediately around a preserved
BLE-RFFI capture/example/error, deterministically and with an exact,
provable link back to the original bytes.

It is **not** a general-purpose RF file player, and it is **not**
presented as a scientific contribution in its own right. The FFT/STFT
math is standard; nothing here is a novel signal-processing technique.
The only thing genuinely worth naming is the *combination*: a
deterministic, sample-index-exact, evidence-linked reconstruction that
reuses — rather than duplicates — every real analysis stage LIVE already
has, bounded honestly to the frequency span the receiver actually
captured.

### 16.2 LIVE stays untouched

Nothing in `data/useRFTerrainFrameSource.ts`, `engine/terrain.worker.ts`,
`TerrainMesh`, `TerrainSelectionOverlay`, `SpectralObjectEnvelope`, or any
persistence/segmentation code changed to build this. Offline
Reconstruction lives entirely under
`frontend/src/features/rf-terrain/engine/offline/` and
`frontend/src/features/rf-terrain/offline/` — a second, independent frame
source that happens to feed the same engine, per the "one internal
contract, two producers" design in §3. `RFTerrainView.tsx` gates the two
sources with a single `source: 'LIVE' | 'OFFLINE'` switch: only one
source's rows ever reach `RFTerrainCanvas.applyRow()`/`.clear()` at a
time, and LIVE's own polling/worker lifecycle (§3.1, §3.5) is disabled
(never partially degraded) whenever `source !== 'LIVE'`.

### 16.3 Data path

0. **Auto-detection (NO_CAPTURE)** — rather than requiring the operator to
   already know a capture ID, the panel calls
   `OfflineCaptureClient.fetchRecentCaptureManifests()` →
   `GET /api/ble/capture/recordings` as soon as it opens on `SOURCE:
   OFFLINE` with nothing loaded. This is the same real, already-existing,
   read-only endpoint `ble_capture_job_manager.list_captures()` already
   serves for the rest of the platform (no new backend code), returning
   every completed capture's manifest sorted newest-first by
   `created_at_utc`. `OfflineReconstructionController.refreshRecentCaptures()`
   validates each raw manifest the same way a single import does — a
   malformed individual entry is skipped, not fatal to the list — and caps
   the result at `RECENT_CAPTURES_LIMIT` (50). The list is **never
   filtered by center frequency**: a capture taken while tuned elsewhere is
   exactly as valid a reconstruction target, so nothing about the
   receiver's current tuning narrows what is offered. A manual capture-ID
   field remains available for a capture outside the most recent 50.
1. **Metadata** — `engine/offline/captureClient.ts` fetches
   `GET /api/ble/capture/recordings/{capture_id}` (a real, already-existing,
   read-only endpoint; no new backend code was written for this feature).
   `engine/offline/captureMetadata.ts` validates the real
   `capture_manifest.json` fields (`sample_rate_sps`, `center_frequency_hz`,
   `bandwidth_hz`, `sample_format`, `actual_samples`/`actual_size_bytes`,
   `device_serial`, `gain_configuration.gain_db`, `antenna`, `ble_channel`)
   field-by-field, failing closed with a specific reason on anything
   missing or malformed. `calibration_id` is not a real field in the
   manifest schema today, so it is always reported as `null` /
   "NOT DOCUMENTED" rather than fabricated.
2. **Bytes** — `fetchIqByteRange` issues `GET .../iq` with a real HTTP
   `Range` header (the endpoint is Starlette `FileResponse`, confirmed
   Range-capable) in fixed, pipelined 16 MiB chunks (§16.7) — a ~10 s /
   multi-Msps capture is never loaded into memory at once. Only `cf32_le` (interleaved
   little-endian float32 I/Q, the real, campaign-frozen format) is
   implemented; `engine/offline/iqBytes.ts` throws for any other
   `sample_format` rather than misinterpreting bytes.
3. **STFT** — `engine/offline/fft.ts` is a from-scratch iterative
   radix-2 Cooley-Tukey FFT plus a Hann window (verified against Parseval's
   theorem and pure-tone bin concentration in `tests/offline/fft.test.ts`;
   no FFT/DSP code existed anywhere in this frontend before this feature).
   `engine/offline/spectrumGenerator.ts`'s `OfflineSpectrumGenerator` is the
   only stateful piece of the pipeline: it keeps a small carry-over sample
   buffer across `pushChunk()` calls so STFT windows are correct across
   chunk boundaries, verified deterministic regardless of how a caller
   happens to chunk identical bytes (`tests/offline/spectrumGenerator.test.ts`).
4. **Adapter reuse** — each STFT frame's `spectrumData` is shaped as a
   real `SpectrumData` object and passed through the *exact same*
   `validateSpectrumFrame` (§3.2) and `adaptSpectrumFrame` (§3.4) LIVE
   uses — this only works because `SpectrumData` and `TerrainInputFrame`
   are structurally identical (minus `generation`), so zero validation or
   resampling logic was duplicated.
5. **Engine** — `offline/OfflineReconstructionController.ts` calls
   `engine/terrainWorkerState.ts`'s `createTerrainWorkerState` directly (the
   exact same pure reducer `terrain.worker.ts` wraps in `postMessage` for
   LIVE) rather than spinning a second `Worker`. This is a deliberate,
   disclosed tradeoff: offline reconstruction is a bounded, sequential
   computation (unlike LIVE's real-time backpressure, it must process
   *every* chunk-derived frame, never drop one), so running it in-process
   makes the whole controller synchronously, deterministically
   unit-testable without a `Worker` polyfill — at the cost that a very
   large reconstruction can block the main thread. Moving it to a real
   dedicated worker later would not change this class's public contract.

### 16.4 Determinism and time

`t_n = n / f_s` from the absolute sample index of each STFT window's first
sample — never `Date.now()`. `sampleIndexToTimestampMs` adds a constant
`+1` ms floor so the very first frame (`sampleIndex = 0`) still satisfies
`frameValidator.ts`'s `timestamp > 0` rule, without perturbing the real,
constant spacing between frames. Two independent reconstructions of the
same capture produce byte-identical rows
(`tests/offline/offlineReconstructionController.test.ts`). Hop size is
derived per-capture (`engine/offline/reconstructionProfile.ts`'s
`computeHopSizeSamples`) to target roughly 1,000 rows regardless of
capture length, and is never smaller than the FFT size — no finer time
resolution is ever fabricated than the FFT block itself provides. The
Reconstruction Profile (`OFFLINE_RECONSTRUCTION_PROFILE_V1`: `fftSize=4096`,
Hann window, `targetRowCount=1000`) is versioned and SHA-256-hashed
(`computeProfileConfigHash`), and a reproducibility fingerprint
(`computeReconstructionId = SHA256(iqSha256 + profileConfigHash +
softwareCommit)`) is computed once reconstruction completes.
`softwareCommit` defaults to the honest literal `"unknown"` — no build
step in this project injects a real git commit into the frontend bundle
today; a future CI-provided value can be passed in without any interface
change.

### 16.5 Spectral Context Audit

`engine/offline/contextAudit.ts` computes three real aggregates over
values the *same* adaptive-baseline/persistence/occupancy engine already
produced for every row — never a second, independent statistic, and never
fed into the BLE-RFFI classifier (enforced at the call site: the audit
report is attached to `OfflineReconstructionState`, which the
classification pipeline never reads):

- **C1 baseline** — median/IQR of every real per-bin noise-floor value in
  the window, plus how much the row-level median baseline moves over
  time.
- **C2 occupancy** — mean of the real, already-computed occupancy signal,
  reported *with* its estimator/threshold/τ, never as a bare probability.
- **C4 object density** — real segmented-object count divided by real
  window duration/bandwidth; returns `NaN` (not a fabricated zero) for a
  degenerate window.

**Not implemented:** C3 (nearby/adjacent spectral activity relative to a
specific selection) and the transient-event-count part of C5 — both need
a real target/context frequency-band split around a specific selection
that deserves its own design, not a rushed approximation.

### 16.6 FSEI SOURCE EVIDENCE

Extending §14's Evidence section for an OFFLINE-sourced selection: since a
row's `timestamp` is *exactly* `sampleIndexToTimestampMs(sampleIndex,
sampleRateSps)` by construction, `offline/sourceEvidence.ts`'s
`deriveSourceSampleRange` inverts that same formula to recover the
original `[startSampleIndex, startSampleIndex + fftSize - 1]` window in
the preserved capture — an exact computation, not a lookup into a second,
independently-maintained index. FSEI shows the real capture ID, the real
`data_sha256`, the real sample rate, and this derived sample/time range
whenever a selection exists while `source === 'OFFLINE'`; a LIVE
selection continues to show the unavailable notice from §14.5/§12
unchanged.

### 16.7 Chunk size and pipelined fetch (real reconstruction-time fix)

A real, measured problem with the first version of this feature: with
4 MiB chunks, a large capture (e.g. a ~1.6 GB / 10 s / 20 Msps `cf32_le`
file) needed on the order of 400 sequential HTTP range requests, each
paying real per-request backend overhead (routing, `Range` parsing, a
disk read) on top of the actual transfer — that per-request overhead,
multiplied 400 times, was the dominant cost, not the FFT/STFT/terrain
analysis itself (a few thousand rows of 4096-point FFT is cheap). Two
real, disclosed fixes:

- **`DEFAULT_CHUNK_BYTES` raised from 4 MiB to 16 MiB** (still bounded,
  still nowhere close to loading the whole file — a 1.6 GB capture is now
  ~100 requests instead of ~400). Configurable per controller instance
  (`chunkBytes` in the constructor config) — mainly so tests can force
  many small chunks deterministically without a huge synthetic capture.
- **Pipelined fetch**: `reconstruct()` now issues the *next* chunk's range
  request immediately after the *current* one resolves, before parsing/
  analyzing the current chunk — so network latency for chunk N+1 overlaps
  real CPU work for chunk N instead of both being paid serially. Processing
  order itself is untouched (`OfflineSpectrumGenerator.pushChunk` is still
  called strictly in order — the only thing pipelining changes is *when*
  the next byte range is requested, never the order data is analyzed in),
  so determinism (§16.4) is unaffected. A fetch that is still in flight
  when `cancel()` aborts it is always awaited (never abandoned) so its
  rejection is handled as a clean stop rather than an unhandled promise
  rejection or a spurious `ERROR_LOCAL`.

### 16.8 Reconstruction Monitor: precise time/progress telemetry

`OfflineReconstructionState` carries a fine-grained `stage` (`FETCHING_CHUNK`
→ `PARSING_CHUNK` → `ANALYZING_FRAMES`, repeated per chunk, then
`SEGMENTING` → `COMPUTING_CONTEXT_AUDIT` → `COMPUTING_HASHES` → `DONE`)
plus real telemetry updated at every real chunk boundary:
`bytesProcessed`/`totalBytes`, `chunksProcessed`/`totalChunks`, and
`elapsedMs` (wall-clock, `Date.now()`-based). `throughputBytesPerSecond`
and `estimatedRemainingMs` are pure arithmetic derivations of those same
real numbers (`bytesProcessed / elapsedSeconds`,
`remainingBytes / throughput`) — both stay `null` until at least one chunk
has actually completed, never a divide-by-zero guess or a fabricated
starting estimate. A periodic 200 ms ticker (`recomputeTiming()`, started
in `reconstruct()` and stopped on completion/error/cancel) keeps
`elapsedMs` visibly advancing even while a single chunk fetch is still in
flight, so the display never looks frozen between real updates — the
ticker only ever *recomputes* from already-known values, it never
advances `bytesProcessed`/`chunksProcessed` itself.

`ui/RFTerrainOfflineMonitor.tsx` is a dedicated, transparent glass HUD
window (top-center, independent of whether the Menu/Offline panel happens
to be open) that renders this state directly: stage label, a real
percentage progress bar, elapsed time to millisecond precision
(`mm:ss.mmm`), bytes/chunks/rows counters, throughput, and ETA. It
auto-reopens at the start of a new reconstruction and collapses to a
one-line summary once `COMPLETE`, without hiding the numbers.
`tests/offline/offlineReconstructionController.test.ts`'s "reconstruction
telemetry" suite verifies: exactly one `/iq` request per chunk with
`bytesProcessed` ending equal to `totalBytes`; every real stage is visited
on the way to `DONE`; elapsed time and throughput are real positive
numbers once chunks have completed; and throughput/ETA are strictly
`null` before the first chunk finishes.

### 16.9 Playback

Reconstruction computes every row once, up front; playback
(`play`/`pause`/`step`/`restart`/`seekToRowIndex`) only replays that
already-computed sequence into the same `applyRow`/`clear` calls LIVE
uses — `setPlaybackSpeed` only changes the `setTimeout` interval between
replayed rows, never a computed value
(`tests/offline/offlineReconstructionController.test.ts` asserts identical
row values at two different speeds). A "jump to time" scrub
(`seekToRowIndex`) replays every row from the start up to the target index
so the renderer's own incremental state (flow animation, reference
ribbons) stays correct — an `O(target index)` operation, a disclosed
tradeoff for reusing `RFTerrainCanvas.applyRow()` unmodified rather than
adding a new bulk-seek renderer method.

### 16.10 Explicitly not implemented

- Running the engine off the main thread during `RECONSTRUCTING` (§16.3).
- Context Audit C3 and the transient-event part of C5 (§16.5).
- Export/reporting with provenance, and a versioned Reconstruction Report
  artifact.
- A BLE evidence overlay sourced from real manifest data.
- End-to-end acceptance testing against a live backend and a real capture
  fixture — the test suite (§11) verifies determinism, isolation, and
  every pure-function boundary with synthetic data and a mocked `fetch`;
  it does not exercise the real `/api/ble/capture/recordings/*` endpoints
  against a running backend.
- A UI screenshot of the feature in this report — no browser tool is
  available in this environment to capture one, the same limitation
  disclosed for every other RF Terrain UI change in this document.
