# SpectraEase Backend

FastAPI backend for the SpectraEase RF spectrum analyzer.

The current active hardware path uses a real **Ettus Research USRP-B200** through **UHD/GNU Radio**. The backend starts helper tools with the RadioConda Python executable and returns live spectrum frames captured from the device.

## Active Device Flow

- Driver reported by the API: `uhd_gnuradio`
- Device currently used: `USRP-B200 from Ettus Research`
- Capture source: real UHD/GNU Radio samples
- Default antenna: `RX2`
- Default center frequency: `89.4 MHz`
- Default sample rate/span: `2 MS/s`
- Default gain: `20 dB`

The active API does not generate mock spectrum data. If the device cannot be opened or no frame is available, the spectrum endpoint returns a real SDR error or pending state.

## Main Components

- `app/infrastructure/web/controllers/device_controller.py`
  - Connects/disconnects the real SDR flow
  - Starts/stops live spectrum streaming
  - Reports device status

- `app/infrastructure/web/controllers/spectrum_controller.py`
  - Serves live spectrum data
  - Updates center frequency, span, start/stop, RBW, VBW, reference level, detector mode, and averaging

- `app/infrastructure/web/controllers/demodulation_controller.py`
  - Captures the RF band selected by M1 and M2
  - Runs marker-band AM/FM/WFM audio demodulation
  - Stores demodulation metadata and WAV output for dashboard playback/export

- `app/infrastructure/web/controllers/modulated_signal_controller.py`
  - Captures, lists, downloads, and safely deletes marker-limited or custom-window `.cfile` or `.iq` files for `Capture Lab`
  - Persists metadata for replay workflows and AI datasets, including live preview metrics
  - Lists and serves generated IQ/metadata files from disk

- `app/modules/fingerprinting/service.py`
  - Imports captures into the fingerprinting registry
  - Computes offline QC from stored IQ data
  - Estimates SNR, occupied bandwidth, peak frequency/offset, burst bounds, silence, and clipping
  - Applies automatic review flags before dataset curation
  - Recomputes QC with the stored QC policy, metadata completeness and label status instead of relying on a previous manual decision
  - Applies weak label/class defaults from `app/modules/rf_intelligence/band_profiles.json` when a capture lacks usable labels
  - Preserves burst RF samples as valid when the sample is usable but the capture window is tight
  - Recent update: for `burst_rf_v1`, conditions such as `occupied_bandwidth_near_capture_limit`, `peak_not_ideally_centered` and `low_margin_to_nearest_edge` are now warnings, not automatic reject/doubtful triggers, cuando el SNR es bueno y no hay clipping u otros fallos graves.

- `app/modules/rf_intelligence/knowledge_base.py`
  - Loads the RF band profile knowledge base from `band_profiles.json`
  - Resolves marker/capture frequency windows to editable technical labels
  - Produces weak defaults for `transmitter_label`, `transmitter_class`, `signal_type`, `modulation_class`, `protocol_family`, `band_label` and `profile_key`
  - Does not claim physical transmitter identity; operator confirmation is still required for `strong_label`

- `app/modules/mlops/service.py`
  - Starts training, retraining, validation, and inference jobs
  - Tracks async job status, stdout, stderr, and generated reports
  - Bridges the unified app with the RF fingerprint platform scripts
  - Exports curated captures into canonical RF fingerprinting datasets
  - Preserves raw I/Q files while creating ML-ready canonical I/Q copies
  - Estimates signal offset from QC metadata or Welch PSD, shifts to baseband, filters the useful band, resamples when required, normalizes RMS power, and writes segment manifests

- `app/modules/rf_experiment_lab/`
  - Adds the optional reproducible RF Experiment Lab layer
  - Consumes existing captures and metadata without modifying the operational capture, waterfall, RF Intelligence or RF Signal Understanding paths
  - Provides SigMF export, HDF5 experiment manifests, dataset versioning, representation extraction and experiment result packages
  - Implements E0 Morphological Baseline, E5 Spectral Feature Baseline, E1 Raw IQ CNN 1D and E3 Spectrogram/Waterfall CNN 2D
  - Registers experiment listing, detail, comparison and benchmark-report endpoints
  - Reports missing optional dependencies cleanly through stable JSON instead of breaking backend startup
  - Enforces the Dataset Builder scientific gate for E1, E3 and E5 by default: weak labels and not-ready samples are excluded unless an explicit debug policy is selected
  - Rejects closed-set runs when evaluation contains classes that are absent from the training split

- `app/infrastructure/sdr/real_spectrum_stream.py`
  - Manages the persistent spectrum worker process
  - Restarts the worker when tuning parameters change

- `tools/spectrum_stream_worker.py`
  - Opens the USRP through GNU Radio/UHD
  - Captures IQ samples
  - Produces FFT spectrum frames as JSON

## Run Backend Manually

On Windows, install the Ettus UHD runtime/USB driver before starting the backend:

- Windows 11 UHD builds/drivers: `https://files.ettus.com/binaries/uhd/latest_release/Windows11/VS2026/`
- All latest UHD release builds: `https://files.ettus.com/binaries/uhd/latest_release/`

Verify the radio is visible to UHD:

```powershell
& 'C:\Program Files\UHD\bin\uhd_find_devices.exe'
& 'C:\Program Files\UHD\bin\uhd_usrp_probe.exe'
```

The recommended development entrypoint is the project script:

```powershell
cd C:\path\to\spectrum-lab

$env:DEFAULT_CENTER_FREQUENCY_HZ="89400000"
$env:DEFAULT_SAMPLE_RATE_HZ="2000000"
$env:DEFAULT_GAIN_DB="20"
$env:DEFAULT_ANTENNA="RX2"
$env:UHD_DEVICE_ARGS=""

powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -RadioCondaPythonPath "C:\path\to\radioconda\python.exe"
```

The normal laboratory launcher enables the accepted experimental BLE real-IQ
recorder by default. This only makes the manual `Capture Real IQ` action
available: it does not open a receive stream or start a recording until the
operator presses that button, and it does not enable automatic BLE decoding,
Gate 2A.2, or OTA claims. To disable the manual capability for a session, use
`-EnableBleIqCapture 0`:

### BLE operator dashboard and hybrid campaigns

The BLE dashboard starts with an operator controller that reports the Windows
BLE adapter and USRP B200 independently. It offers native, B200-only, and
recommended hybrid modes; detailed native devices, packets, GATT diagnostics,
evidence, and sessions remain available in tabs.

`POST /api/ble/hybrid/sessions` starts one bounded CH37/38/39 campaign (1–60
seconds) using the existing native scan, IQ capture, burst detector, Gate 2A.2
decoder, and correlator. Poll `GET /api/ble/hybrid/sessions/{session_id}` for
real step status and counters, stop via
`POST /api/ble/hybrid/sessions/{session_id}/stop`, and list history via
`GET /api/ble/hybrid/sessions`.

Manual smoke test: select **Captura híbrida**, a detected target or **Cualquier
dispositivo**, CH37, and 10 seconds. Press **Iniciar** and verify that native
callbacks and B200 samples increase, followed by burst, CRC-valid packet, and
correlation counters. Inspect the detail tabs for the preserved evidence.

### TI SensorTag generations and GATT connection jobs

Native GATT connection is asynchronous: `POST
/api/ble/native/devices/{device_id}/connect` returns HTTP 202 with a stable
`connection_job_id`. Poll `/api/ble/native/connection-jobs/{job_id}` or cancel
it explicitly through `/api/ble/native/connection-jobs/{job_id}/cancel`.
Repeated connection requests for the same device return the active job.

Profile classification uses the complete discovered service topology. Legacy
SensorTags with separate AA10 accelerometer, AA30 magnetometer, and AA50
gyroscope services are reported as probable CC2541 generation. CC2650 devices
are distinguished by AA70 optical and AA80 combined movement services. A
legacy device without AA70 reports ambient light as not present in that
hardware generation. TMP006 object temperature is retained as raw data until
the calibrated nonlinear conversion is available; it is never exposed as a
physically valid temperature merely by scaling the thermopile word.

Completed hybrid sessions expose `/scientific-summary`, a derived and
auditable result containing the evidence funnel, independent general/target
outcomes, acquisition/decoder/correlation quality, E0–E4 evidence level,
limitations, and SHA-256 metadata for preserved artifacts. The target is
frozen in `session_manifest.json` at campaign start; refreshing the native BLE
registry never changes a completed session's target.

The dashboard target selector uses the same native registry as the device
table. The CC2650 (`B0:B4:48:C0:36:06`) and legacy CC2541
(`BC:6A:29:AB:DE:13`) SensorTags are prioritized but retain an honest current
or historical state. A completed native scan invalidates both views while
preserving the stable `device_id` selection. Run the selector regression with
`npm run test:ble-targets` from `frontend`.

### BLE-UC-02 — identificación híbrida de SensorTag

La pestaña `UC-02 · Identificar SensorTag` guía la primera validación E4 sin
alterar la cadena científica. Exige que uno de los SensorTag prioritarios sea
observado en el scan actual, congela su identidad en el manifest y ejecuta una
campaña híbrida completa de 30 segundos. El resultado general y el resultado
del objetivo se evalúan independientemente. Si CH37 produce
`TARGET_NATIVE_ONLY`, el operador puede repetir CH38 y CH39 manteniendo el
mismo objetivo, duración, ganancia y disposición física.

GATT se presenta sólo como evidencia lógica complementaria. No sustituye un
paquete B200 con CRC válido ni una correlación dentro de ±250 ms. E4 se concede
únicamente con `TARGET_MATCHED_STRONG` o `TARGET_MATCHED_BY_PAYLOAD`; E5 sigue
reservado para experimentos reales de fingerprint RF entre unidades y
sesiones. No debe crearse el commit de validación UC-02 hasta obtener evidencia
real accesible y cumplir estos criterios.

Estado de validación real (2026-07-17): la sesión
`BLE-HYBRID-20260717T123917Z-1a3d21` demuestra funcionalmente UC-02/E4 para el
CC2650 `B0:B4:48:C0:36:06` en CH37 (36 callbacks Windows, 4 paquetes objetivo
con CRC válido y 1 coincidencia fuerte; mejor |Δt| 248.889 ms). La captura tuvo
2 overflows y 2 discontinuidades: es válida para la demostración funcional,
pero no es evidencia limpia de fingerprint RF. Reproducibilidad queda
`PENDING`, fingerprinting `NOT_VALIDATED` e identidad física
`NOT_DEMONSTRATED`. Faltan repeticiones controladas CC2650 CH37/38/39 y después
CC2541, siempre con el objetivo observado en el scan inmediatamente anterior.

### BLE Dataset Studio

`Dataset Studio · Generador de datasets RF verificables` transforma sesiones
híbridas terminadas; no duplica el escaneo, captura B200, decoder, correlador ni
GATT. Cada versión vive en `storage/ble_lab/datasets/<dataset_id>/<version>` y
contiene `campaign_protocol.json`, `dataset_manifest.json`, `examples.jsonl`,
`devices.json`, `sessions.jsonl`, `quality_report.json`, `split_manifest.json`,
`dataset_datasheet.md` y `checksums.sha256`. El protocolo se congela antes de
ingerir datos y un cambio posterior requiere una versión derivada nueva.

Cada ejemplo conserva sesión, captura, ráfaga, intervalo exacto
`sample_start`/`sample_count`, canal, objetivo, unidad física, PDU, CRC,
observación Windows, regla temporal, E0–E4, calidad y hashes. Las muestras no
aceptadas permanecen en `examples.jsonl` como cuarentena con un estado y motivo;
no se borran. Los splits agrupan por sesión, día, unidad física, canal,
ubicación o receptor para evitar repartir ráfagas relacionadas entre train y
test. E5 permanece `not_implemented_not_validated`: una dirección, payload,
CRC, GATT o una captura aislada nunca se presenta como fingerprint físico.

Las definiciones compartidas y versionadas están en
`app/modules/ble_lab/definitions`. La API, el dashboard y las datasheets
registran sus versiones mediante `glossary_schema_version`,
`evidence_model_version` y `quality_model_version`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -EnableBleIqCapture 0 -RadioCondaPythonPath "C:\path\to\radioconda\python.exe"
```

If running only the backend, make sure `RADIOCONDA_PYTHON` points to the Python executable that has GNU Radio and UHD:

```powershell
$env:RADIOCONDA_PYTHON="C:\path\to\radioconda\python.exe"
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For the complete Windows application, use the single unified launcher. It
automatically keeps the FastAPI/Bleak backend environment separate from the
radioconda GNU Radio/UHD runtime used by the B200:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1 -RemoteUser "assouyat" -RemoteHost "192.168.193.49"
```


## Backend Modular API Architecture

The backend API surface is split physically under `backend/app/modules`. Each API/domain area owns a module definition, and `main.py` only calls the registry composer:

```text
backend/app/modules/
  capture_lab/module.py
  demodulation/module.py
  device/module.py
  fingerprinting/api_module.py
  kiwisdr/api_module.py
  markers/module.py
  mlops/api_module.py
  presets/module.py
  recordings/module.py
  rf_experiment_lab/api_module.py
  sessions/module.py
  spectrum/module.py
  waterfall/module.py
  registry.py
  types.py
```

Each backend module declares a stable ID, name, enabled flag, order, description, and a `build_router(context)` function. `backend/app/modules/registry.py` composes the active modules and registers their FastAPI routers under the configured API prefix. This keeps endpoint ownership physically separated while preserving the existing controllers, services, routes, and URL contracts. Existing domain modules such as `fingerprinting`, `kiwisdr`, and `mlops` keep their internal services and expose API registration through `api_module.py` to avoid breaking their current package structure.

To disable an API module without deleting code, set its `enabled` flag to `False` in that module's definition. To add a new backend module, create a new folder under `backend/app/modules/` with a `module.py` or `api_module.py` and add it to `backend_modules` in `registry.py`.

## Key API Endpoints

- `GET /api/device/status`
- `POST /api/device/connect`
- `POST /api/device/disconnect`
- `POST /api/device/stream/start`
- `POST /api/device/stream/stop`
- `POST /api/device/frequency`
- `POST /api/device/gain`
- `GET /api/spectrum/live`
- `POST /api/spectrum/center-frequency`
- `POST /api/spectrum/span`
- `POST /api/spectrum/start-stop`
- `POST /api/spectrum/rbw`
- `POST /api/spectrum/vbw`
- `POST /api/spectrum/reference-level`
- `POST /api/spectrum/noise-floor-offset`
- `POST /api/spectrum/detector-mode`
- `POST /api/spectrum/averaging`
- `POST /api/spectrum/scpi`
- `POST /api/demodulation/marker-band`
- `GET /api/demodulation/results`
- `GET /api/demodulation/results/{id}`
- `GET /api/demodulation/audio/{id}`
- `POST /api/rf-intelligence/band-profile/resolve`
- `POST /api/fingerprinting/captures/{capture_id}/recompute-qc`
- `POST /api/fingerprinting/captures/{capture_id}/apply-band-profile`

`GET /api/models/current` returns an explicit `{available: false, status: "not_found"}` payload when there is no current operational model. This avoids frontend polling noise while preserving the fact that no production model is registered.

## Dataset QC and label policy

Backend QC distinguishes signal quality from label authority:

- `capture_quality`: RF/file quality after offline analysis.
- `label_status`: `unlabeled`, `weak_label` or `strong_label`.
- `review_status`: human review state.
- `training_readiness`: whether the sample can enter training.

`Recompute QC` reads the stored IQ file and updates offline diagnostics, SNR estimates, burst bounds, occupied bandwidth, spectral peak, frequency offset, clipping, silence and profile-specific warnings. The recomputation evaluates the current QC profile and metadata completeness. This makes the result reproducible and prevents a manual UI decision from masking missing labels or poor RF quality.

`apply-band-profile` is a controlled label-repair endpoint. It resolves the capture frequency window against `band_profiles.json` and fills missing label/class fields only when they are absent or placeholder values, unless `overwrite_existing=true` is requested. By default it writes a `weak_label`. `confirm_as_strong_label=true` should be used only after operator review.

RF Experiment Lab training endpoints apply this label policy:

- E1 Raw IQ CNN 1D requires strong physical `transmitter_id` labels.
- E3 Spectrogram/Waterfall CNN 2D requires strong labels for the selected task and label field.
- E5 Spectral Feature Baseline defaults to `signal_type` for signal-recognition baselines and `transmitter_id` only when the task is explicitly `device_fingerprinting`.

The default `training_readiness_policy` is `scientific_strict`: only `strong_label`, `accepted`, `ready_for_training` captures with valid quality are eligible. `training_draft` admits `candidate` captures when they have `strong_label` and non-invalid QC, which is useful for exploratory E5/E1/E3 baselines while a dataset is still being curated. `all_debug` bypasses readiness gates and can include weak/not-ready records; those runs should not be reported as primary scientific results.
- `POST /api/modulated-signals/captures`
- `GET /api/modulated-signals/captures`
- `GET /api/modulated-signals/captures/{id}`
- `GET /api/modulated-signals/captures/{id}/iq`
- `GET /api/modulated-signals/captures/{id}/metadata`
- `GET /api/fingerprinting/dashboard`
- `GET /api/fingerprinting/captures`
- `POST /api/fingerprinting/captures`
- `POST /api/fingerprinting/captures/{capture_id}/review`
- `POST /api/fingerprinting/import/modulated-capture/{capture_id}`
- `GET /api/mlops/training/dashboard`
- `POST /api/mlops/training/start`
- `POST /api/mlops/training/retrain`
- `GET /api/mlops/training/status`
- `POST /api/mlops/validation/run`
- `POST /api/mlops/validation/start`
- `GET /api/mlops/validation/status`
- `GET /api/mlops/validation/reports`
- `POST /api/mlops/inference/predict/start`
- `GET /api/mlops/inference/predict/status`
- `GET /api/rf-experiment-lab/health`
- `GET /api/rf-experiment-lab/experiments`
- `GET /api/rf-experiment-lab/experiments/{experiment_id}`
- `POST /api/rf-experiment-lab/experiments/compare`
- `POST /api/rf-experiment-lab/benchmark/report`
- `POST /api/rf-experiment-lab/sigmf/preview`
- `POST /api/rf-experiment-lab/sigmf/export`
- `POST /api/rf-experiment-lab/hdf5-manifest/preview`
- `POST /api/rf-experiment-lab/hdf5-manifest/export`
- `POST /api/rf-experiment-lab/representations/raw-iq/preview`
- `POST /api/rf-experiment-lab/representations/raw-iq/export`
- `POST /api/rf-experiment-lab/representations/fft-psd/preview`
- `POST /api/rf-experiment-lab/representations/fft-psd/export`
- `POST /api/rf-experiment-lab/representations/spectrogram/preview`
- `POST /api/rf-experiment-lab/representations/spectrogram/export`
- `POST /api/rf-experiment-lab/representations/waterfall/preview`
- `POST /api/rf-experiment-lab/representations/waterfall/export`
- `POST /api/rf-experiment-lab/representations/manifest/export`
- `POST /api/rf-experiment-lab/experiments/e0-morphological-baseline/preview`
- `POST /api/rf-experiment-lab/experiments/e0-morphological-baseline/run`
- `POST /api/rf-experiment-lab/experiments/e5-spectral-baseline/preview`
- `POST /api/rf-experiment-lab/experiments/e5-spectral-baseline/run`
- `POST /api/rf-experiment-lab/experiments/e1-raw-iq-cnn1d/preview`
- `POST /api/rf-experiment-lab/experiments/e1-raw-iq-cnn1d/run`
- `POST /api/rf-experiment-lab/experiments/e3-spectrogram-cnn2d/preview`
- `POST /api/rf-experiment-lab/experiments/e3-spectrogram-cnn2d/run`

OpenAPI docs are available at `http://localhost:8000/docs` when the backend is running.

## RF Experiment Lab Backend Layer

RF Experiment Lab is a removable backend extension. It must remain optional and must not be a dependency of the current operational SDR laboratory.

The backend split is:

```text
Operational path
  device / spectrum / waterfall / markers
  demodulation
  Capture Lab
  Dataset Builder and fingerprinting registry
  RF Intelligence
  RF Signal Understanding
  MLOps training, validation and inference

Experimental path
  rf_experiment_lab dataset adapter
  exporters
  representations
  experiment families
  metrics and comparison
  benchmark report
```

Every RF Experiment Lab response uses a stable envelope:

```text
status
module
available
message
data
errors
```

This is important because some features depend on optional packages:

- `sklearn` for E5 classical model training
- `torch` for E1 and E3 training
- `torchvision` for E3 `resnet18` and `vgg11`
- `scipy` for optional Welch PSD support
- `h5py` for future binary HDF5 writing

If an optional dependency is missing, the affected endpoint returns `available=false` or a clean error in the stable envelope. Backend startup must continue.

### Implemented experiments

| ID | Name | Task | Input | Model type | Output |
|----|------|------|-------|------------|--------|
| E0 | Morphological Baseline | Region detection baseline | Waterfall or spectrogram metadata | Existing `morphological_heuristic` adapter | `detections.json`, `metrics.json`, runtime log |
| E5 | Spectral Feature Baseline | Explainable classification baseline | `fft_psd`, PSD summary, optional raw-IQ spectral features | Logistic Regression, Random Forest, SVM RBF, KNN | features, model, metrics, predictions, confusion matrices, feature importance |
| E1 | Raw IQ CNN 1D | Closed-set device fingerprinting | `raw_iq` windows shaped `[2, N]` | Small CNN 1D | model, metrics, predictions, history, group/confidence/overfitting summaries |
| E3 | Spectrogram/Waterfall CNN 2D | Closed-set signal recognition or fingerprinting | `spectrogram` or `waterfall` shaped `[1, H, W]` | simple CNN 2D, optional ResNet18, optional VGG11 | model, metrics, predictions, history, group/confidence/overfitting summaries |

E0 is the permanent fallback and baseline. Learned detectors such as SSD, Faster R-CNN and YOLO are not implemented yet and must report `not_implemented`, not fake results.

### Reproducibility services

The backend now supports:

- `RFExperimentDatasetV1`, a unified internal dataset manifest consumed by E1, E3 and E5
- RF Experiment Lab internal dataset samples with raw IQ, RF metadata, task, label, transmitter ID, signal type, modulation class, session, receiver, environment, distance, QC summary, SHA-256 and split group
- SigMF preview/export from `.cfile + .json` or `.iq + .json`
- HDF5 experiment manifest preview/export without requiring binary HDF5 support
- Dataset version objects with source capture hashes
- Representation extraction for `raw_iq`, `fft_psd`, `spectrogram` and `waterfall`
- Representation manifest export with artifact paths and SHA-256 hashes
- Experiment registry listing and detail loading
- Cross-experiment comparison
- Consolidated benchmark reports across E1, E3 and E5
- Experimental inference-report persistence for saved captures, Marker 1 / Marker 2 regions, frozen windows and live context

Preview endpoints do not write files. Export/run endpoints write into controlled output directories and preserve original captures.

### Unified dataset import

All dataset sources are normalized before training:

```text
Capture Lab / RF Signal Understanding / public dataset / custom folder
  -> RFExperimentDatasetV1
  -> E1, E3 or E5
  -> result package and optional inference report
```

The training services accept `dataset_manifest_path`. When set, records are read from the unified manifest instead of directly from the original capture registry. This keeps training code independent from dataset origin.

Trainable result packages also write `dataset_manifest_path.txt`, `training_config.json`, `label_schema.json`, `normalization_params.json` and `split_strategy.txt` so validation and retraining can be audited from the result folder.

Validated Capture Lab / Dataset Builder captures can also be registered into RF Signal Understanding through its existing capture registry endpoint. This supports the path:

```text
Capture Lab
  -> Dataset Builder QC
  -> valid capture only
  -> RF Signal Understanding capture registry
```

That route is for signal-type/modulation/protocol understanding. Device fingerprinting experiments still use RF Experiment Lab and `RFExperimentDatasetV1`.

Supported source profiles:

- `oracle`: primarily RF fingerprinting
- `wisig`: primarily RF fingerprinting and receiver/domain-shift studies
- `radioml`: primarily modulation or signal-type classification
- `sig53`: primarily modulation or signal-type classification
- `external_custom`: I/Q, SigMF, HDF5, NumPy, MATLAB, Pickle, CSV features, spectrogram images or waterfall images

Dataset endpoints:

```text
GET  /api/rf-experiment-lab/dataset/sources
GET  /api/rf-experiment-lab/dataset/internal-samples
POST /api/rf-experiment-lab/dataset/internal-samples
POST /api/rf-experiment-lab/dataset/internal-samples/{sample_id}/review
POST /api/rf-experiment-lab/datasets/rf-experiment-dataset-v1/preview
POST /api/rf-experiment-lab/datasets/rf-experiment-dataset-v1/export
POST /api/rf-experiment-lab/datasets/external/preview
POST /api/rf-experiment-lab/datasets/external/import
POST /api/rf-experiment-lab/inference/predict
POST /api/rf-experiment-lab/inference/compare-region
```

### Scientific split discipline

The experiment layer avoids random window splits as the scientific default. Supported group-disjoint strategies include:

- `capture_disjoint`
- `session_disjoint`
- `day_disjoint`
- `environment_disjoint`
- `distance_disjoint`
- `receiver_disjoint`
- `device_holdout`

The default split is `session_disjoint`. Benchmark reports warn when experiments use different dataset versions, different split strategies, missing metrics, missing group metrics, incompatible label spaces, low sample counts or debug/random splits.

## Marker-Band Demodulation

`POST /api/demodulation/marker-band` captures real IQ from the USRP-B200 between the two frequencies supplied by the frontend, normally M1 and M2.

<img src="../readme_img/demodulation.png" alt="Marker-band demodulation result generated by the backend" width="100%">

Example body:

```json
{
  "start_frequency_hz": 89320000,
  "stop_frequency_hz": 89450000,
  "mode": "fm",
  "duration_seconds": 5
}
```

Supported modes and IoT pipelines:

| Mode / Pipeline | Band | Output |
|---|---|---|
| `am`, `fm`, `wfm` | Broadcast | WAV audio; expose `/api/demodulation/audio/{id}` |
| `ask`, `fsk`, `psk`, `ook` | Any | IQ and metadata for digital analysis |
| `ook_433_remote` | 315 / 433 / 868 MHz | EV1527 / PT2262 remote decode: address, button, repeat analysis |
| `ook_ask_iot_sensor` | 315 / 433 / 868 MHz | Generic ISM-band OOK/ASK sensor decode |
| `zigbee` | 2.4 GHz | IEEE 802.15.4 MAC frame decode: FCS, PAN IDs, addresses |
| `ble_advertising` | 2.402 / 2.426 / 2.480 GHz | BLE advertising packet decode with CRC-24 validation |
| `wifi_80211` | 2.4 / 5 GHz | IEEE 802.11 frame detection and header parse |
| `lora` | 433 / 868 / 915 MHz | LoRa/LoRaWAN chirp spread-spectrum decode |

Live SDR path for IoT pipelines: the demodulation worker captures IQ using the
corresponding basic mode (`ook_433_remote` → `ook` worker), then the controller
runs the full protocol-specific IoT pipeline on the captured IQ.

Demodulation results survive page refresh. The loader reads flat `*.json`
metadata files and nested `{id}/demodulation_report.json` enriched reports; the
enriched report takes precedence when both exist for the same result ID.

The backend applies the same RF safety checks used by spectrum tuning before opening the USRP-B200.

## Modulated Signal IQ Captures

`POST /api/modulated-signals/captures` captures the selected RF band as raw complex64 IQ plus JSON metadata. The request can choose `file_format` as `cfile` or `iq`, and the frontend may define the band from markers or from a custom frequency window.

<table>
  <tr>
    <td width="50%">
      <img src="../readme_img/capture_lab.png" alt="Capture Lab IQ acquisition workflow" width="100%">
      <br>
      <strong>Capture request path</strong>
      <br>
      The backend receives marker/custom frequency windows, applies RF guardrails, and writes IQ plus metadata.
    </td>
    <td width="50%">
      <img src="../readme_img/capture_lab_signal_analysis.png" alt="Capture Lab marker-band cfile and IQ generation workflow" width="100%">
      <br>
      <strong>Generated artifacts</strong>
      <br>
      Persistent `.cfile` / `.iq` outputs are paired with replay metadata and dataset labels.
    </td>
  </tr>
</table>

Example body:

```json
{
  "start_frequency_hz": 89320000,
  "stop_frequency_hz": 89500000,
  "duration_seconds": 5,
  "file_format": "iq",
  "label": "device_01_signal_a",
  "modulation_hint": "fsk",
  "notes": "Capture for offline analysis and AI dataset generation"
}
```

Files are stored in:

```text
backend/app/infrastructure/persistence/storage/recordings/modulated_signal_captures/
backend/app/infrastructure/persistence/storage/recordings/modulated_signal_iq_captures/
```

Each metadata file includes capture identity, selected file format, frequency limits, center frequency, bandwidth, sample rate, gain, antenna, IQ format, sample count, file size, SHA256, label, modulation hint, notes, and replay parameters.

If the capture is imported into the fingerprinting registry, the backend runs offline QC on the stored IQ file and derives:

- estimated SNR
- occupied bandwidth
- peak frequency
- frequency offset
- burst start/end
- silence percentage
- clipping percentage

This is separate from the live preview shown in the frontend.


### RF QC Profiles

The fingerprinting registry now separates QC by signal family instead of applying one burst detector to every RF capture.

- `continuous_fm_v1`: for continuous FM/broadcast-like channels. Uses spectral peak detection, spectral/channel SNR, occupied bandwidth, channel presence, edge margin, clipping, and raw IQ diagnostics. Temporal silence is not a rejection criterion for this profile.
- `burst_rf_v1`: for intermittent RF, remotes, ASK/OOK, packet-like captures, and short events. Uses burst-region detection, burst SNR, silence, burst duration, clipping, and artifact diagnostics.

Each imported or recomputed capture stores `signal_family`, `qc_profile_id`, `qc_profile`, `snr`, and `iq_file_diagnostics`. The IQ diagnostics include sample count, actual duration, dtype, endianness, mean/RMS power, zero and near-zero ratios, NaN/Inf ratios, and spectral peak offset. This makes it possible to distinguish a genuinely bad/corrupt IQ file from a QC profile mismatch.

For continuous FM, the selected review SNR is spectral/channel SNR. For burst RF, the selected review SNR is burst/temporal SNR. Continuous FM captures are never rejected because a burst detector reports high temporal silence; if the channel is present but the occupied bandwidth nearly fills the selected capture window, the capture is marked doubtful rather than rejected.

### Behavior change for `burst_rf_v1`

The backend now distinguishes dataset usability from signal quality warnings in the same spirit as the older v3 policy for intermittent RF captures.

- `burst_rf_v1` sigue aceptando como `valid` una captura usable cuando:
  - el SNR es bueno (`>= 15 dB`)
  - no hay clipping significativo (`<= 1%`)
  - el IQ file es correcto y la adquisición es recuperable mediante canonicalización
  - el método de análisis es `spectral_peak_detection`
- Las condiciones de ventana ajustada se conservan como advertencias:
  - `occupied_bandwidth_near_capture_limit`
  - `peak_not_ideally_centered`
  - `low_margin_to_nearest_edge`
- Solo se consideran motivos de rechazo automático los fallos claros:
  - señal fuera de la banda
  - silencio excesivo
  - ráfaga demasiado corta
  - muestras perdidas o buffer overflow
  - margen al borde extremadamente bajo (< 20 kHz)

Este ajuste evita que una muestra usable para entrenamiento RF fingerprinting sea descartada solo porque la banda capturada está apretada o la señal está cercana al borde de la ventana.

### Políticas prácticas para `burst_rf_v1`

- `review_status` debe reflejar la usabilidad del dataset.
- `rf_intelligence` debe reflejar la calidad de adquisición y advertencias operativas.

En la política recomendada:

- `VALID` cuando:
  - `SNR >= 15 dB`
  - `clipping_pct <= 1%`
  - `silence_pct = 0%` o fallback espectral válido
  - `channel_presence_ratio` alto
  - `IQ near-zero` bajo
  - fichero IQ correcto
  - canonicalización posible
- `DOUBTFUL` cuando:
  - el margen al borde es pequeño pero no crítico
  - `occupied_bandwidth_near_capture_limit` está presente
  - `peak_not_ideally_centered` está presente
  - `pre_post_qc_mismatch` está presente
  - no hay fallos graves en el IQ o en la señal
- `REJECT` solo cuando hay fallos claros como:
  - IQ corrupto o vacío
  - IQ near-zero alto
  - clipping grave
  - SNR muy bajo
  - señal fuera de la ventana
  - margen prácticamente nulo

### Ejemplos de decisión

#### Captura 1
- Margen al borde: 11.84 kHz
- Estado recomendado: `doubtful`
- Motivo: margen de ventana demasiado pequeño para confiar plenamente en esta adquisición

#### Captura 2
- Margen al borde: 97.97 kHz
- Estado recomendado: `valid`
- Motivo: señal usable, margen razonable, sin clipping, sin silencio, IQ íntegro

### Analítica de sangre para QC

| Parámetro | Rango objetivo | Síntoma | Acción |
|---|---|---|---|
| `SNR` | >= 15 dB | Señal buena | Dataset usable |
| `Clipping` | 0–1% | Sin saturación | Dataset usable |
| `Silence` | 0% | Ráfaga presente | Dataset usable |
| `IQ near-zero` | 0% | Fichero íntegro | Dataset usable |
| `Occupied bandwidth ratio` | 90–99% | Ventana ajustada | Warning |
| `Margin al borde` | > 20 kHz | Suficiente guarda lateral | Valid |
| `Pre/post QC mismatch` | Bajo | Validación offline diferente | Warning |
| `Peak centering` | Centralizado idealmente | Band edge risk | Warning |

> En este modelo, los problemas de captura se leen como alteraciones de laboratorio: el resultado principal puede estar sano (`valid`) aun cuando algunas métricas estén en la zona de advertencia.

A comparison endpoint is available for investigating inconsistent captures:

```text
GET /api/fingerprinting/captures/compare/{left_capture_id}/{right_capture_id}
```

It reports metadata differences, sample-rate/duration differences, mean-power differences, spectral peak differences, occupied-bandwidth differences, SNR differences, zero/near-zero ratios, QC profile differences, detection method differences, ROI policy differences, and decision differences.

## RF Fingerprinting MLOps And Canonicalization

Training, retraining, and validation use curated captures from the fingerprinting registry. The backend rebuilds internal datasets before each ML lifecycle operation instead of training directly on arbitrary raw files.

The exported ML dataset is canonicalized. The original `.cfile` or `.iq` remains untouched, and the exported record keeps `original_center_frequency_hz`, `original_sample_rate_hz`, `original_bandwidth_hz`, estimated signal center, estimated offset, and the applied frequency shift as auditable metadata.

Canonical preprocessing performs:

```text
raw .cfile/.iq
  -> read original metadata
  -> estimate signal peak / occupied center from QC or Welch PSD
  -> estimate offset relative to SDR center
  -> digital frequency shift to baseband
  -> FIR low-pass useful-band filtering
  -> polyphase resampling when canonical sample rate differs
  -> RMS power normalization
  -> complete-window segment manifest generation
  -> canonical dataset for training/validation
```

Compatibility rules are based on canonical representation, not absolute SDR tuning center. Multiple original `center_frequency_hz` values are allowed when exported records share one `preprocessing_profile_id`, one `canonical_sample_rate_hz`, one `canonical_bandwidth_hz`, and one `canonical_segment_length_samples`. Validation must match the trained model canonical configuration and must not reuse `(device, session)` pairs from the training manifest.

## Validation And Inference Runtime

The backend accepts `python_exe` overrides for validation and inference, but if the field is empty it falls back to `RADIOCONDA_PYTHON`. The frontend launcher now forwards this path to the UI so the operator normally sees the correct value prefilled.

Inference prediction is asynchronous. The backend returns a `job_id`, then exposes status, `stdout`, `stderr`, and the final report through the prediction status endpoint.

## Runtime Configuration

| Variable | Purpose |
|----------|---------|
| `RADIOCONDA_PYTHON` | Python executable with GNU Radio/UHD |
| `DEFAULT_CENTER_FREQUENCY_HZ` | Startup center frequency |
| `DEFAULT_SAMPLE_RATE_HZ` | Startup sample rate/span |
| `DEFAULT_GAIN_DB` | Startup gain |
| `DEFAULT_ANTENNA` | UHD antenna name |
| `UHD_DEVICE_ARGS` | Optional UHD device selector |
| `VITE_RADIOCONDA_PYTHON` | Frontend runtime copy of the RadioConda path, injected by the dev launcher |
| `REAL_SDR_FPS` | Spectrum worker frame rate |
| `REAL_SDR_MAX_FFT_SIZE` | Maximum FFT size used to approach requested RBW |

RBW changes the FFT size used by the live spectrum worker. VBW applies frame-to-frame video smoothing after FFT detection; values much higher than the frame rate behave like no smoothing.

## RF Safety Guardrails

The backend rejects unsafe or invalid hardware-facing settings before they reach UHD:

| Parameter | Default software range |
|-----------|------------------------|
| Center frequency | `70 MHz` to `6 GHz` |
| Sample rate / span | `200 kS/s` to `61.44 MS/s` |
| Gain | `0 dB` to `60 dB` |
| RBW | `1 Hz` to `1 MHz` |
| VBW | `1 Hz` to `1 MHz` |

The safety status is also exposed through:

```text
GET /api/spectrum/safety-limits
```

These checks reduce accidental misconfiguration. They do not replace RF input protection; avoid injecting high-power signals directly into the USRP-B200 input.

## SCPI-Style Commands

Basic external-control commands are accepted through `POST /api/spectrum/scpi` with a JSON body:

```json
{ "command": "SENS:FREQ:CENT 89.4MHz" }
```

Supported commands:

- `SENS:FREQ:CENT <value>[Hz|kHz|MHz|GHz]`
- `SENS:FREQ:SPAN <value>[Hz|kHz|MHz|GHz]`
- `DISP:TRAC:Y:RLEV <value>[dB|dBm]`
- `DISP:TRAC:Y:SCAL:PDIV <value>dB`

## Model Artifacts And Export

Training produces artifacts in the result package directory reported by each
experiment run. The artifact format depends on the experiment family:

| Experiment | Checkpoint | Extra artifacts |
|---|---|---|
| E1 Raw IQ CNN 1D | `best_model.pt` (PyTorch) | `training_config.json`, `label_schema.json`, `normalization_params.json`, `split_strategy.txt` |
| E3 Spectrogram CNN 2D | `best_model.pt` (PyTorch) | same set; ResNet18/VGG11 if `torchvision` was available |
| E5 Spectral Baseline | `model.pkl` (scikit-learn) | `feature_names`, `label_schema.json`, feature importance CSV |
| RF Signal Understanding | `model.npz` (NumPy) | weight matrix `W`, bias `b`, label list, feature normalization |
| Operational fingerprinting | `best_model.pt` (PyTorch) | `device_to_label`, `window_size`, `stride`, `embedding_dim` inside the checkpoint |

### PyTorch `.pt` checkpoint contents

```python
{
    "model_state_dict": ...,   # weights
    "device_to_label": {...},  # int → class name
    "window_size": int,
    "stride": int,
    "embedding_dim": int,
}
```

Export options:
- **ONNX**: `torch.onnx.export(model, dummy_input, "model.onnx")`
- **TorchScript**: `torch.jit.trace(model, dummy_input).save("model.ts")`
- **SafeTensors**: `safetensors.torch.save_file(model.state_dict(), "model.safetensors")`

### scikit-learn `.pkl` structure

```python
{
    "model_name": str,
    "model": sklearn_estimator,
    "feature_names": list[str],
}
```

Export: `skl2onnx.convert_sklearn(pkl["model"], ...)` produces an ONNX graph
compatible with ONNX Runtime.

### NumPy `.npz` structure

```python
npz = np.load("model.npz")
W = npz["W"]          # weight matrix [n_classes, n_features]
b = npz["b"]          # bias [n_classes]
labels = npz["labels"]
```

Plain arrays; no ML framework required to load or run inference.

## BLE hybrid campaign intent

Every new hybrid campaign must declare exactly one `campaign_intent` before a
session is created:

- `positive_target_validation`: requires a specific target selected from the
  current native scan (`Visto ahora`). Historical or manual targets are
  rejected for a positive claim.
- `negative_control`: requires a specific target, a documented
  `negative_control_type`, and `operator_confirmation: true`. Supported types
  are `target_powered_off`, `target_physically_absent`,
  `other_device_substituted`, and `ambient_only`.
- `exploratory_target_search`: permits a historical target but makes neither a
  positive claim nor a negative-control claim.

Legacy manifests without `campaign_intent` are interpreted conservatively as
`exploratory_target_search`. `TARGET_NOT_OBSERVED` means only that evidence was
insufficient during that campaign; it never proves physical absence. The
versioned contract is published in
`app/modules/ble_lab/definitions/campaign_manifest.schema.json`.

## Troubleshooting

- Confirm the USRP-B200 is connected over USB.
- On Windows, reinstall or repair the Ettus UHD USB driver if UHD reports `No UHD Devices Found`.
- Confirm the radio is visible with `C:\Program Files\UHD\bin\uhd_find_devices.exe` and opens with `C:\Program Files\UHD\bin\uhd_usrp_probe.exe`.
- Confirm RadioConda can import `gnuradio` and `uhd`.
- Confirm the app was started with `-UseRealSdr 1`.
- Confirm `RADIOCONDA_PYTHON` points to `C:\path\to\radioconda\python.exe`.
- If `/api/spectrum/live` returns `real_sdr_pending`, wait for the first frame.
- If it returns `real_sdr_error`, check the error field and the backend terminal output.

## Center-frequency spectral artifact (LO leakage) — investigated 2026-08-01

**Symptom reported:** a persistent narrow spike visible in the live spectrum
display, always sitting exactly at the tuned center frequency, well above
the noise floor.

**Root cause, confirmed experimentally, not assumed:** this is **LO
(local-oscillator) leakage**, a real, physical characteristic of the USRP
B200's direct-conversion (zero-IF) receive architecture (AD9361 RFIC) — not
a software bug, not an external interferer, and not specific to any one
frequency band. In a zero-IF receiver, the LO is mixed down to exactly the
tuned center frequency; any imperfect isolation between the LO port and the
RF signal path leaks a small amount of LO energy straight into the receive
chain, which lands at DC in baseband — i.e. exactly at whatever frequency
the radio is tuned to, regardless of what that frequency is. This is a
well-documented characteristic of essentially every direct-conversion SDR,
including the B200/AD9361 family; it is not unique to this unit.

**How this was confirmed (not guessed):** the spike was measured at three
unrelated, widely separated frequencies (2402 MHz, 915 MHz, 1200 MHz) with
nothing else changed. In all three cases the spike sat at exactly the
tuned center frequency (0 Hz offset), moving instantly whenever the radio
was retuned. A real external transmitter would stay at its own fixed
frequency regardless of tuning; something that *follows the tuning itself*
can only be generated by the receiver's own local oscillator. This rules
out an external signal or antenna/cabling problem.

**Does it "destroy" or corrupt everything received?** No — measured
directly: the elevated region is only about **20–25 kHz wide**, roughly
**0.6% of a 4 MHz span**. It does not raise the noise floor anywhere else
in the displayed band, and it does not prevent real signals located away
from the exact center frequency from being received or decoded correctly
(confirmed live: BLE packet decode from real nearby devices kept working
normally, both before and after every change described below). It is a
narrow, cosmetic-but-real artifact confined to the middle of the display,
not a broadband degradation of reception.

**What was tried and did NOT fully fix it:** UHD's built-in digital
DC-offset correction (`usrp_source.set_auto_dc_offset(True, 0)`,
already enabled in `spectrum_stream_worker.py`). This helps with pure ADC
DC bias but left the LO-leakage component essentially unchanged in testing
— confirming this is closer to true analog LO-to-RF leakage than a simple
digital DC offset.

**What actually works, verified live:** LO-offset tuning. Instead of
tuning the LO exactly to the frequency of interest (a bare float passed to
`set_center_freq`, which is what puts the leakage dead center),
`spectrum_stream_worker.py`'s `_tune_request()` helper now builds a
`uhd.tune_request_t(target_freq, lo_offset)` with the LO offset set to 25%
of the current sample rate. UHD keeps the *reported/displayed* center
exactly at `target_freq` (it compensates with an internal digital mixer)
while physically placing the LO — and therefore the leakage — that offset
away from it. Measured result at 1200 MHz, 4 MSps: the artifact moved from
0 Hz offset (dead center) to ~1.02 MHz offset, and the level exactly at
the reported center frequency dropped from roughly 15–20 dB above the
noise floor to within a few dB of it. This is applied automatically on
every tune (`SpectrumStream.__init__` and `set_center_frequency`) — no
separate action is required from the operator, and it does not change the
reported center frequency, span, or sample rate seen by any downstream
consumer (BLE live-decode confirmed unaffected).

**Residual/known limitation:** LO-offset tuning relocates the artifact; it
does not delete it. It still exists somewhere inside the sampled
bandwidth (now off-center rather than dead center), and a downstream
consumer that scans the *entire* acquisition bandwidth without regard to
frequency — such as `_detect_energy_bursts()`'s pure time-domain energy
sum, used by the BLE live burst detector — is not helped by this fix,
since total energy across the band is essentially unchanged by moving
*where* within it the energy sits. This was a real, separate contributing
factor investigated earlier the same day for why BLE live detection kept
failing (see the BLE-RFFI Studio module's own README) — the sample-rate
mismatch found there was the dominant cause, not this artifact, but this
residual limitation is recorded here for completeness rather than implying
LO-offset tuning alone makes live burst detection immune to it.

## Declared BLE negative controls

A predeclared negative control is evaluated independently from the E0–E5
positive-evidence scale. `PASSED_SINGLE_RUN` means that one execution produced
zero attributions to the target under the operator-confirmed physical
condition. It is not a statistical false-positive estimate. The manifest
records target observations, target CRC-valid packets, target strong matches,
false target attributions, and the contract result.

Dataset Studio assigns `NEGATIVE_BY_EXPERIMENTAL_CONTRACT` and an explicit
`negative_ground_truth_source` to examples from that campaign. This relation
means only “not the declared target under this contract”; it does not identify
the ambient transmitter. E1/E2 remain unchanged. Sessions with any unlocalized
overflow or discontinuity remain `QUARANTINED_SESSION_LOSS`, so the negative
control can pass functionally while its IQ remains unavailable for training or
fingerprinting. A reinforced negative control additionally requires a known
second device with an E3 match and a clean capture.

### Dataset Studio: execution is not protocol acceptance

Dataset Studio keeps planned, executed, protocol-conformant, and scientifically
accepted conditions separate. A 3-second historical capture does not complete
a frozen 30-second condition. Missing distance, orientation, location,
physical unit, power state, or timestamp also makes an execution non-conformant.

Correlation reports both strong matches over all bursts and strong matches over
eligible advertisements; `SCAN_REQ` is excluded from the second denominator.
Loss is localized only when exact intervals exist. Otherwise the affected
examples use `QUARANTINED_SESSION_LOSS`. Split integrity is independent from
training readiness: with zero accepted examples `split_status` is `NOT_READY`
and its reason is `no_accepted_examples`.

### BLE Dataset Studio Pilot v1 baseline

This implementation is frozen as `BLE Dataset Studio Pilot v1`. The 30-second
protocol is the current versioned BLE pilot protocol only; it is not the global
scientific protocol for SpectraRFˣ. The global research protocol and
cross-domain roadmap remain pending. This baseline contains 3 historical
campaigns and 338 quarantined examples, with zero accepted training examples,
training `NOT_READY`, and fingerprinting `NOT_VALIDATED`.

## Device Scrubbing: training a real detector for an "always-on" device — 2026-08-03

**The problem:** `TARGET_VS_BACKGROUND` needs real examples of the target
device genuinely absent. A device that is **always powered on** (e.g.
`SHELLY-PLUG-01`, a mains smart plug with no accessible off switch) never
produces one: every capture nominally recorded as "background" for its
project still has it broadcasting in the room. `EvidenceStage` already
refuses to lie about this — a `BACKGROUND_TARGET_OFF` capture declared for
this exact device, if its packets are actually decoded, is flagged
`CONFLICT`/quarantined rather than silently counted as real negative
evidence — but the practical result was the same either way: no usable
"device absent" evidence, for any capture, ever.

**The technique:** rather than accept this as permanent, the device's own
decoded-packet windows are surgically removed from its real IQ captures.
Each removed window (`ExampleRecord.iq_start_sample`/`iq_end_sample`,
already computed by Evidence Stage — no new detection needed) is replaced
with a real "quiet" segment (no decoded packet from any device) copied from
elsewhere in the *same* recording, crossfaded at both edges to avoid a
splice discontinuity. This is the same principle as RFI blanking in radio
astronomy and click removal in audio restoration: borrow real material
already present in the file, never invent a sample. Filling the gap with,
say, the dataset mean was considered and rejected — a synthetic, near-flat
fill is itself a learnable artifact, exactly the failure mode this project
has repeatedly had to chase out elsewhere (the LO-leakage spike above; the
CC2541SensorTag/CC2650-UNIT-01 cross-device dataset contamination in the
BLE-RFFI Studio module's own README). See
`app/modules/ble_rffi_studio/scrubbing/device_scrubber.py`.

The result is registered and decoded as a brand-new capture through the
existing ingestion pipeline completely unchanged (`build_capture` +
replay-and-evidence, real CPU decode, no shortcuts) — never assumed clean.
`StudioRepository.scrub_device_from_background()` then re-reads that
capture's own fresh evidence and confirms zero examples still resolve to
the removed device before anything is trained on it.

**Real result, `SHELLY-PLUG-01` (project `BLE-RFFI-CC2650`), first run:**

- 3 background captures were auto-detected as contaminated (each held
  exactly 1 decoded `SHELLY-PLUG-01` packet among ~107–114 total examples).
  All 3 were scrubbed and verified: 0 residual examples of the device in
  any of them (704 samples replaced per capture — one BLE advertising
  packet's worth at 4 MSps).
- Training on the **original, unscrubbed** background captures did not even
  reach model training: the session-disjoint leakage check
  (`split_builder.py`) correctly refused the split as `NOT_FEASIBLE`,
  because the one contaminated session was contributing an example to
  *both* the target class (its own leaked packet) and the background class
  (everything else in that same capture) — an unavoidable conflict a
  leakage-safe split must reject rather than silently allow. This is a
  second, independent confirmation that the contamination was real and not
  cosmetic: it made the dataset structurally untrainable, not just noisy.
- Training on the **scrubbed** background captures passed the split and
  quality gates and all 5 candidates trained, but none reached
  `prepare_and_train()`'s own VALIDATION acceptance thresholds
  (macro_f1 ≥ 0.5, balanced_accuracy ≥ 0.5) — reported honestly as
  `NO_MODEL_ACCEPTED` rather than auto-selecting the least-bad one. All 5
  were still exported and TEST-evaluated anyway (same
  `export_and_approve_all_candidates()` mechanism used for every other
  device this project trains all 5 candidates for). Real TEST numbers:
  logistic_regression/svm_rbf/cnn1d/cnn2d all landed at macro_f1≈0.10,
  balanced_accuracy=0.50, recall(BACKGROUND_ENVIRONMENT)≈0.00 (i.e.
  effectively always predicting "device present"); random_forest was best
  but still weak (macro_f1≈0.21, balanced_accuracy≈0.55).

**Honest conclusion (first run, 3 background sessions):** the technique
worked exactly as designed — it turned a structurally infeasible dataset
into a trainable one, with the contamination's removal independently
confirmed twice (zero residual packets, and the leakage-check failure that
no longer occurs). It did not, on this first run, produce a good detector.
The most likely cause was data volume: only 3 background sessions existed
(the bare minimum the feasibility gate allows), leaving a thin, heavily
imbalanced TEST split (120 examples).

**Second run, same day, 8 background sessions:** 5 more real
`BACKGROUND_GENERAL` B200 captures were recorded for the same project (same
protocol: channel 37, 10 s, 20 dB gain), scrubbed and verified the same way
(0 residual `SHELLY-PLUG-01` examples in any of the 8). The original
(unscrubbed) side still failed the same session-disjoint leakage check even
with more sessions, confirming the contamination — not the session count —
was what made it untrainable. Training on the scrubbed side with the larger
pool produced a real, substantial improvement:

| model | macro_f1 | balanced_accuracy | precision(TARGET_DEVICE) | recall(BACKGROUND_ENVIRONMENT) |
|---|---|---|---|---|
| random_forest | 1.000 | 1.000 | 1.000 | 1.000 |
| svm_rbf | 0.945 | 0.986 | 0.824 | 0.972 |
| logistic_regression | 0.832 | 0.949 | 0.560 | 0.898 |
| cnn1d | 0.470 | 0.500 | 0.000 | 1.000 |
| cnn2d | 0.433 | 0.431 | 0.000 | 0.861 |

(TEST split, n=122: 108 background + 14 target examples — real but modest,
so `random_forest`'s perfect score should be read as strong, not as an
infinite-sample guarantee.) The two CNN candidates stayed degenerate
(cnn1d always predicts background, precision(TARGET_DEVICE)=0) — small,
still-limited real data penalizes deep models harder than classical ones
here, a plausible and unsurprising split, not a bug.

**Live verification, real B200, real device (2026-08-03):** with
`random_forest` active (calibrated `acceptance_threshold=0.7`, reachable —
contrast with the first run's `1.000000001`, i.e. deliberately
unreachable), live confidence measured 0.68–0.71 across ten samples, and
6 of 10 crossed the threshold and returned `final_decision: IDENTIFIED,
identified_device: SHELLY-PLUG-01` against real live traffic
(`decoded_address: 05:48:94:05:8F:B1`) — the first time this device has
ever been identified live in this project. The remaining 4/10 sat just
under threshold (0.68–0.69), consistent with a real, honest, non-perfect
recall right at the calibration boundary rather than a broken pipeline.
