# AI Model Research Plugin

Standalone documentation for an experimental, **disabled-by-default** plugin. It is
deliberately not linked from the platform's main `README.md` or any other general
platform documentation, per its own design requirement (see §1 below) — this file is
the only place it is described.

---

## 1. What this is, and the one rule it must never break

A completely independent module that lets a researcher import an already-pretrained
AI model and apply it to real, preserved RF captures, to study *what a given model is
actually able to extract* from an RF observation — never to add a new "official"
detector to the platform.

The one rule that governs every design decision below:

```text
PLATFORM WITHOUT PLUGIN  ==  PLATFORM WITH PLUGIN DISABLED
```

This is enforced **structurally**, not just by convention, on both sides:

- **Backend**: `AI_RESEARCH_PLUGIN_ENABLED` defaults to `false`. When false,
  `app/modules/registry.py`'s `active_backend_modules()` filters this module out
  *before* its router is ever built — the router is never constructed, never mounted,
  and `onnx`/`onnxruntime` are never even imported (all such imports are deferred to
  inside `module.py`'s `_build()`, never at module top-level). Verified directly
  against the real `app.main.app` object: zero `ai-research-plugin` routes exist when
  the flag is off; all 12 real paths exist when it is on (some serving multiple HTTP
  methods) (`app/tests/unit/ai_research_plugin/test_module_registration.py`).
- **Frontend**: `VITE_AI_RESEARCH_PLUGIN_ENABLED` defaults to `false`. When false, the
  module is filtered out of `activeLabModules`/`navigationModules`/`moduleRoutes` —
  zero route, zero nav entry, and the view's own JS chunk (confirmed via
  `npm run build`: `AiResearchPluginView-*.js`, a genuinely separate lazy chunk) is
  never even requested by the browser.

Nothing in this plugin modifies: Live Monitor, SDR acquisition, existing RF
processing, existing storage, existing detections, the functional architecture, the
main README, general platform documentation, or any BLE/Wi-Fi module. The only
existing files touched at all are `backend/app/modules/registry.py` (one import line +
one list entry, to register the new module through the existing, unmodified
`BackendModuleDefinition` extension point) and
`frontend/src/{shared/config/runtime.ts,app/modules/labModules.tsx}` (one new flag,
one new list entry, through the existing, unmodified `LabModuleDefinition` extension
point). No other platform file changed.

## 2. Scope actually implemented in this pass (vs. the full design spec)

The originating specification is a 25-section design document covering ONNX/PyTorch/
TensorFlow support, process-isolated inference, frequency-region selection, a 3D
Terrain visual overlay, and a full 7-family output-interpretation model. This pass
implements a real, tested **core**, not 100% of it — every deviation below is a
disclosed scope decision, not a silent gap.

**Implemented:**

- **Framework: ONNX only.** `torch` is already a real dependency of this backend
  (used by `mlops`/`ble_rffi_studio`), which made TorchScript tempting, but ONNX was
  chosen instead because it is the one format where **Model Inspection is genuinely
  automatic** — the graph format stores real input/output tensor shapes and dtypes
  (`onnx_inspection.py`), so "what does this model expect" is a real inspection, not a
  guess. `onnx`/`onnxruntime` (CPU) were installed into `backend/.venv-validation`
  (see `backend/requirements.ai-research-plugin.txt`) — a small, additive, reversible
  dependency, isolated to this plugin's own lazy-imported code path.
- **Model Inspection + RFModelManifest** (`contracts.py`, `onnx_inspection.py`,
  `model_registry.py`): real input/output tensor shape, dtype, and name extracted
  directly from the ONNX graph on import. Every manifest keeps `*_discovered` (written
  once, from real inspection, never touched again) strictly separate from
  `*_overrides` (whatever the operator has since typed in) — `effective_input()`/
  `effective_output()` compute what is actually used, but the two sources stay
  independently inspectable. Nothing is ever silently invented for a field the ONNX
  graph does not declare (sample rate, task, bandwidth, class list all start `None`).
- **Representation Adapters** (`adapters.py`): `IQAdapter` (`[1,2,N]`),
  `SpectrogramAdapter` (`[1,1,F,T]`, real `scipy.signal.stft`, two-sided since I/Q is
  complex), `PSDAdapter` (`[1,F]`, real `scipy.signal.welch`). `FeatureVectorAdapter`
  (cyclostationary/kurtosis/spectral-moment features) is **not implemented** — a
  documented Phase-2 gap, not a silent fallback (`adapt()` raises a clear error
  naming it).
- **Read-only capture bridge** (`capture_bridge.py`): reads a real, preserved BLE
  `cf32_le` I/Q capture via the SAME shared `BleCaptureJobManager` instance
  `ble_lab`/`ble_rffi_studio` already use (`get_shared_managers()`) — never a second,
  competing manager against the real USRP B200. Only `.list_captures()`/`.metadata()`/
  `.data_path()` are ever called, and the data file is only ever opened `"rb"`. "RF
  capture" in this plugin means specifically this real, existing BLE campaign store —
  the only real preserved-capture format on the platform today (the same one RF
  Terrain 3D's Offline Reconstruction feature reads); a generic multi-protocol store
  does not exist, so this module does not invent one.
- **Compatibility check** (`compatibility.py`): compares real capture metadata and a
  real adapted-tensor shape against what the manifest actually declares.
  `COMPATIBLE`/`PARTIALLY_COMPATIBLE`/`INCOMPATIBLE`/`UNKNOWN`, with a per-field
  breakdown (`matched: true/false/null` — `null` means the model manifest never
  declared that field, an honest "could not be checked", never silently skipped). A
  dynamic ONNX batch dimension (`None` in the declared shape) is treated as a
  wildcard, not a mismatch. Per spec, `PARTIALLY_COMPATIBLE` (and, in this
  implementation, every other verdict too) never blocks inference — the compatibility
  result is always attached to the record so the operator judges for themselves.
- **Isolated-ish inference** (`inference_service.py`): runs
  `onnxruntime.InferenceSession` **in-process** — a disclosed, deliberate Phase-1
  scope decision, not the spec's "idealmente" separate-process/IPC isolation.
  onnxruntime's CPU execution provider carries none of the heavyweight,
  environment-polluting dependency footprint torch/tensorflow would, so the practical
  case for process isolation is much weaker here than for those frameworks. A tensor
  shape mismatch surfaces as a real `onnxruntime` error message, not a crash.
- **Result interpretation** (`interpretation.py`): classification (real `argmax`,
  never a fabricated softmax-derived "probability" when the model's declared output
  is logits — `score_type` is reported exactly as the manifest declares it, "logit" or
  "probability", never conflated) and embeddings (dimensionality + L2 norm).
  Reconstruction-error and detector-tuple outputs are **not implemented** (documented
  Phase-2 gap; raw output is still returned untouched). A static domain disclaimer
  (spec §20's own worked example, not a computed anomaly score — this plugin does not
  implement real out-of-distribution detection) always accompanies a classification
  result.
- **Reproducible InferenceRecord** (`contracts.py`, `storage.py`): model hash, full
  manifest snapshot, capture ID + its real `data_sha256`, selected time window, input
  transformation/shape/dtype, timestamp, software backend string, raw output, and the
  interpretation — one JSON file per run in the plugin's own storage directory
  (`storage/ai_research_plugin/`), never touching any existing dataset/model store.
- **Frontend** (`frontend/src/features/ai-research-plugin/`,
  `frontend/src/app/modules/ai-research-plugin/`): import a model, expand its
  Model Inspection panel (discovered vs. an editable override form — task, sample
  rate, class list), pick a real capture + a numeric time window + a representation,
  check compatibility, run inference against **one or more selected models
  simultaneously** (spec §17's model comparison — the same RF region against
  different models, side by side), see raw output / interpretation / RF evidence kept
  in three visually separate blocks (spec §12), and browse inference history. This
  standalone `/ai-research-plugin` page still exists and still works, but the primary
  surface an operator actually reaches this from today is the **"FSEI -- AI"
  floating panel inside RF Terrain 3D** (`frontend/src/features/rf-terrain/ui/
  RFTerrainAiPluginPanel.tsx`) — a compact panel matching RF Terrain's own
  Layers-button convention, supporting both OFFLINE (capture + time window) and
  LIVE (a bounded raw I/Q snapshot from the same live SDR stream Live Monitor/RF
  Terrain already use) inference against imported models.
- **Continuous LIVE detection + 3D overlay** (`frontend/src/features/rf-terrain/ai/useAiLiveDetection.ts`,
  `frontend/src/features/rf-terrain/render/AiDetectionOverlay.ts`): "Start continuous"
  in the FSEI panel's LIVE tab repeats `runInferenceLive()` in a self-scheduling
  loop (real backpressure -- never fires the next request before the previous
  one resolves; a real 800ms floor on top of that) and keeps running after the
  panel closes (state lives in `RFTerrainView`, same "outlives the panel" pattern
  OFFLINE RECONSTRUCTION already established for its own objects). Each real
  detection is rendered as an independently-aging wireframe box in the 3D
  terrain, spanning the model's real analyzed frequency window, anchored at the
  front/newest row (a live detection is "just now", not a historical range
  lookup) and aging backward exactly like every other overlay.
  - **Frequency applicability gating**: a model can declare
    `expected_center_frequency_hz`/`expected_frequency_tolerance_hz` as an
    OPERATOR OVERRIDE (never auto-discovered -- no ONNX graph knows physical RF
    context). Checked on every loop tick against the REAL, currently-tuned
    frequency before firing a request; when out of tolerance, the panel shows a
    plain-language "this model isn't applicable here" message instead of
    running inference, and automatically resumes once retuned back into range.
    A model with no declared frequency stays "applicable" but with an honest
    "unknown, not confirmed" disclaimer -- never silently treated as universal.
  - **Real, measured latency**: `InferenceRecord.capture_latency_ms`/
    `inference_latency_ms`/`total_latency_ms` are real wall-clock measurements
    (never estimated) taken around the live-snapshot wait and the onnxruntime
    call. The panel surfaces the real end-to-end number and an honest
    "not real-time at this cadence" note above 1s, rather than implying
    every model can keep up with the live stream.
  - Caught and fixed a real bug during development: the frequency-applicability
    `useEffect` originally depended on the `frequencyInfo` object itself, whose
    identity changes on every live spectrum row (~10 Hz) even when the tuned
    frequency hasn't changed -- an unbounded render→effect→setState loop that
    reproduced as a genuine JS heap OOM in this hook's own test suite. Fixed by
    depending on the real primitive (`centerFrequencyHz`) instead of object
    identity.
- **RF Model Discovery Catalog** (`backend/app/modules/ai_research_plugin/catalog/`,
  `frontend/src/features/ai-research-plugin/catalog/`): replaces the earlier "four
  static links" (ONNX Model Zoo / TorchSig / DeepSig / rfml) with a real catalog —
  reachable via "Discover RF Models" in the FSEI panel. Two sources:
  - A **curated seed catalog** (`catalog/seed_catalog.py`) of 16 real, individually
    verified entries (via a live fetch against each source, not from memory) spanning
    modulation classification, RF fingerprinting, wideband detection, protocol
    identification, and foundation models — each with a real taxonomy (`task`,
    `input_representation`, `conversion_status`) rather than being lumped into one
    generic "Signal classification" bucket, and with model/framework/dataset kept
    structurally distinct (`kind: MODEL | FRAMEWORK_TOOLKIT | DATASET`) so a dataset
    like DeepSig RadioML can never appear as a downloadable model. One entry (INRIA
    RFFI) could not be independently located and is explicitly flagged
    `independently_verified: false` rather than dropped or guessed at.
  - A **live search against the public Hugging Face Hub API**
    (`catalog/huggingface_provider.py`) — real, unauthenticated, and honestly
    disclosed as name/author-substring matching only (confirmed: multi-word queries
    like "modulation classification" return 0 results; short fragments like "rf" or
    a known repo name return real matches). Detects `onnx`/`safetensors`/`pt`/`pth`/
    `ckpt`/`bin`/`h5`/`keras`/`tflite` files directly from the repo's real file
    listing (`siblings`) to set `onnx_available`/`original_format`, but never
    invents `task`/`classes` — those stay `UNKNOWN`/`null` until a human reviews the
    model card.
  - GitHub code search, Zenodo, arXiv, Papers with Code, and Kaggle discovery (spec
    sections 14-15 of the catalog extension) are **not implemented** — a disclosed
    gap, not a silently-skipped source.
  - The catalog only links to and describes external sources; it never downloads,
    converts, or auto-imports anything. "Download → Convert → Import → Test →
    Enable" stay separate, manual steps (only Import — via the existing `.onnx`
    upload — and Test/Enable are actually implemented; Download and Convert are the
    operator's own step against the linked source, by design).
  - `download_url` is set on 9 of the 16 curated entries — a real, individually
    verified direct-file link (`raw.githubusercontent.com`/`huggingface.co/.../
    resolve/main/...`), each confirmed with a real HTTP 200 during development, never
    a guessed path. Two entries had a `paper_url` that was plain citation text
    (e.g. `"IEEE Access 2024"`) rather than a URL — a real broken-`<a href>` bug,
    caught via browser automation and fixed with the real DOI; a regression test
    (`test_paper_url_is_always_a_real_url_never_a_citation_string`) now guards this.
  - **Portal fix (2026-09-01)**: the modal is rendered via `createPortal(..., document.body)`,
    not inline in RF Terrain's own DOM tree. Reported bug: filters and the "ONNX
    available" checkbox were unusable. Root-caused via browser automation
    (`document.elementFromPoint()` at the checkbox's own coordinates returned RF
    Terrain's WebGL `<canvas>`, not the checkbox) — a `position: fixed` overlay
    nested under a Three.js canvas tree does not reliably escape it for
    hit-testing even at a high `z-index`. Same fix already used by
    `SpectrumToolsPanel`'s tooltip for the identical class of bug. Verified live,
    end-to-end, against the real running dev server: Task/Input/Kind filters and
    the ONNX checkbox now correctly change the entry list (confirmed 16 → 2 entries
    filtering by `RF_FINGERPRINTING`, 16 → 3 filtering by `onnx_available`).

**Explicitly not implemented in this pass** (real, disclosed gaps):

- PyTorch/TorchScript and TensorFlow model support (§9's own priority list; only
  ONNX chosen for the reasons above).
- Process-isolated / IPC-separated inference (§8's "idealmente"; runs in-process).
- `FeatureVectorAdapter` (cyclostationary/spectral-moment/kurtosis features, §6).
- Frequency-region selection (`f0`/`f1`) — only a time window (`t0`/`t1`) is
  implemented; `InferenceRecord.selected_frequency_hz` is always `null`.
- The RF Terrain 3D visual overlay (§13/§14/§15) — this plugin ships as its own
  standalone view (`/ai-research-plugin`), not a layer on top of the terrain. The
  architecture (adapters produce real frequency/time axes already) does not preclude
  wiring this in later without touching RF Terrain's own code.
- Reconstruction-error and detector-tuple output interpretation (§18).
- A graphical spectrogram/waterfall thumbnail as "visual evidence" — the evidence
  block is currently textual (capture ID, real time range, representation, shape).
- Model deletion/versioning UI polish beyond a basic delete button; no model registry
  search/filtering.

## 3. Enabling it

Both flags must be set independently (backend and frontend are separate processes):

```bash
# Backend (before starting uvicorn)
export AI_RESEARCH_PLUGIN_ENABLED=true

# Frontend (.env or shell, before `npm run dev`/`npm run build`)
VITE_AI_RESEARCH_PLUGIN_ENABLED=true
```

With both set, `AI Research Plugin` appears in navigation at `/ai-research-plugin`,
and `GET /api/ai-research-plugin/status` returns `{"enabled": true, ...}`.

## 4. API reference (all under `/api/ai-research-plugin`)

| Method & path | Purpose |
|---|---|
| `GET /status` | Whether the plugin (and its capture bridge) is available |
| `POST /models/import` | Upload a `.onnx` file (multipart, `file` + optional `model_name`) |
| `GET /models` | List imported models' manifests |
| `GET /models/{model_id}` | Get one manifest |
| `PATCH /models/{model_id}` | Apply operator overrides (task, input/output/preprocessing/provenance) |
| `DELETE /models/{model_id}` | Remove a model and its manifest |
| `GET /captures` | Real, read-only list of preserved BLE captures |
| `POST /compatibility` | Region read + adapt + compare, no inference run, nothing persisted |
| `POST /inference` | Full run: read region, adapt, infer, interpret, persist an `InferenceRecord` |
| `GET /inference` | List past inference records |
| `GET /inference/{record_id}` | Get one past record |
| `POST /inference/live` | Capture a bounded live I/Q snapshot from the shared SDR stream and run inference |
| `GET /catalog` | List the curated model/framework/dataset catalog, with optional `task`/`input_representation`/`kind`/`onnx_available`/`conversion_status`/`source_kind` filters |
| `GET /catalog/{entry_id}` | Get one curated catalog entry |
| `GET /catalog/search/huggingface?q=...` | Live search against the public Hugging Face Hub API, mapped into the same catalog shape |

## 5. Testing

`backend/app/tests/unit/ai_research_plugin/` — 101 tests (77 core plugin + 24 in
`catalog/`), run via:

```bash
cd backend
./.venv-validation/Scripts/python.exe -m pytest app/tests/unit/ai_research_plugin -q
```

Covers: real ONNX graph inspection (including a genuinely invalid file failing
closed), model import/override semantics (discovered vs. override never conflated),
all three implemented adapters (including a real peak-frequency correctness check
against a synthetic tone — this caught and fixed a real frequency-axis/data
misalignment bug during development), the read-only capture bridge against a
duck-typed fake matching the real manager's exact read-only interface, the
compatibility verdict matrix, output interpretation (classification/embedding/
not-interpretable, logit-vs-probability labeling), a full real ONNX forward pass
end-to-end against a synthetic 5-class toy model fixture (determinism verified:
identical raw output across two independent runs over the same region), the LIVE
I/Q snapshot bridge, and the disabled-by-default module-registration/isolation
guarantee itself, checked directly against `app.main.app`'s real route table.
`catalog/` additionally covers: filter combinations, the curated seed catalog's own
internal invariants (unique IDs, `DATASET` entries never `onnx_available`, `READY`
entries always really `onnx_available`, the one unverified entry never `READY`), and
the Hugging Face live-search response mapping (pure, mocked — no real network call in
the test suite; the real integration was separately exercised by hand against the
live public API during development).

`frontend/src/features/ai-research-plugin/tests/` plus `catalog/tests/` — 11 tests
(API client URL/payload correctness and error propagation for both the core plugin
client and the catalog client; disabled-by-default module registration checked
directly against `activeLabModules`/`navigationModules`/`moduleRoutes`).
`frontend/src/features/rf-terrain/tests/aiDetectionOverlay.test.ts` +
`tests/ai/useAiLiveDetection.test.ts` — 18 more tests covering the 3D overlay
primitive (multi-detection independence, row-aging, expiry) and the continuous
LIVE hook (frequency-applicability gating, real inference calls, latency/detection
recording, error propagation).

Full existing suites confirmed unaffected by this addition:
`pytest app/tests/unit -q` → 1128 passed, 36 skipped, 3 failed (all pre-existing,
unrelated to this plugin: `test_preflight_real_data`,
`test_rf_intelligence_detects_fm_broadcast_candidate`,
`test_ir_temperature_object_and_ambient_are_distinct_measurements`); frontend
`npx vitest run` → 281 passed; `npx tsc --noEmit` clean; `npm run build` succeeds.
