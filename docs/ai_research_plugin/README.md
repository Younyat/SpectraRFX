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
  the flag is off; all 11 exist when it is on
  (`app/tests/unit/ai_research_plugin/test_module_registration.py`).
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
  in three visually separate blocks (spec §12), and browse inference history.

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

## 5. Testing

`backend/app/tests/unit/ai_research_plugin/` — 58 tests, run via:

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
identical raw output across two independent runs over the same region), and the
disabled-by-default module-registration/isolation guarantee itself, checked directly
against `app.main.app`'s real route table.

`frontend/src/features/ai-research-plugin/tests/` — 6 tests (API client URL/payload
correctness and error propagation; disabled-by-default module registration checked
directly against `activeLabModules`/`navigationModules`/`moduleRoutes`).

Full existing suites confirmed unaffected by this addition:
`pytest app/tests/unit -q` → 1070 passed, 36 skipped, 2 failed (both pre-existing,
unrelated: `test_rf_intelligence_detects_fm_broadcast_candidate`,
`test_ir_temperature_object_and_ambient_are_distinct_measurements`); frontend
`npx vitest run` → all passing; `npx tsc --noEmit` clean; `npm run build` succeeds
with `AiResearchPluginView` as its own separate lazy chunk.
