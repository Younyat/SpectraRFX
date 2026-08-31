# SpectraEase Frontend

React/TypeScript frontend for SpectraEase, a real SDR spectrum analyzer currently used with an **Ettus Research USRP-B200**.

The frontend controls the FastAPI backend and displays live RF spectrum frames captured from the real device through UHD/GNU Radio. It does not rely on mock spectrum data in the active application flow.

## Features

- Live spectrum canvas
- Device connect/disconnect and start/stop controls
- Center/span tuning
- Start/stop frequency tuning
- Spectrum pan buttons: `Spectrum Left` and `Spectrum Right`
- Configurable pan step in MHz
- RBW, VBW, reference level, noise offset, detector mode, averaging, and gain controls
- dB/div scale control
- Trace mode selector: Clear/Write, Average, Max Hold, Min Hold, Video Average
- Color scheme selector
- Marker placement by clicking the trace
- Marker dragging on the trace
- Marker table with frequency and signal level
- Delta readout between M1 and M2
- Demodulation tab driven by the M1/M2 marker band
- AM/FM/WFM audio playback from demodulated real captures
- WAV export for analog demodulation results
- ASK/FSK/PSK/OOK marker-band capture controls
- `Capture Lab` for controlled `train` / `val` / `predict` IQ acquisition, intelligent RF pre/post-capture guidance, download, and safe deletion
- `Dataset Builder` for capture review, rigorous offline QC recomputation, weak-label repair from RF band profiles, and QC-driven acceptance/rejection
- `Training`, `Retraining`, `Validation`, `Inference`, and `Models` tabs for the unified RF fingerprinting flow
- `RF Experiment Lab` tab for reproducible E0, E5, E1 and E3 experiment workflows
- `Models` tab separated by model family so operational artifacts are not mixed with experimental E1/E3/E5 runs
- Dataset Builder visibility for RF Signal Understanding capture candidates before they are promoted into fingerprinting datasets
- RF canonicalization-aware validation that allows different original SDR center frequencies when canonical preprocessing is compatible
- Persistent transparent global operation overlay for capture, training, retraining, validation, and prediction jobs
- Persistent `.cfile` and `.iq` metadata capture list with separate downloads
- Live marker-band QC preview with peak, noise floor, SNR, and peak frequency
- Non-blocking global operation overlay for SDR connect and capture operations
- Collapsible left navigation sidebar: circular toggle button remains visible when sidebar collapses to zero width, giving the full window to the spectrum display
- Collapsible right status panel in Spectrum view: same pattern, sidebar animates to zero width with scrollable inner content
- Demodulation result display adapts to signal type: analog audio results (AM/FM/WFM) show audio-specific fields; digital/IoT results show packet/protocol fields
- IoT protocol demodulation result cards for `ook_433_remote` (EV1527/PT2262), `zigbee` (IEEE 802.15.4), `ble_advertising`, `lora`, `wifi_80211`
- Peak marker button
- Auto peaks button
- Trace statistics panel
- Crosshair cursor readout
- Mouse-wheel zoom
- CSV export
- PNG export
- Device status panel
- Recording/session screens

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Zustand
- Axios
- Lucide React

## Development

Install dependencies:

```bash
cd frontend
npm install
```

Run the frontend:

```bash
npm run dev
```

The frontend runs at:

```text
http://localhost:5173
```

The backend must be running at:

```text
http://localhost:8000
```

## Recommended Full App Startup

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -RadioCondaPythonPath "C:\path\to\radioconda\python.exe"
```


## Modular Tab Architecture

The frontend tabs are physically separated into one folder per module and composed through a small registry instead of being hardcoded separately in the router and sidebar. The module area lives in:

```text
frontend/src/app/modules/
  capture-lab/module.tsx
  dataset-builder/module.tsx
  training/module.tsx
  validation/module.tsx
  ...
  labModules.tsx
  types.ts
```

Each `module.tsx` declares:

- stable `id`
- display `name`
- primary `path`
- optional `aliases`
- sidebar `icon`
- React `element`
- `enabled` flag
- `showInNavigation` flag
- ordering metadata
- short functional description

`AppRouter` consumes `moduleRoutes` from `labModules.tsx`. `AppLayout` consumes `navigationModules` and `findModuleByPath`. This means a tab can be added, disabled, hidden from navigation, or removed from the active UI by changing that module's own `module.tsx`, without editing the router and sidebar separately.

Disabling a module should be done by setting `enabled: false` in its own folder. Hiding a module while keeping its route active should be done by setting `showInNavigation: false`. Existing aliases such as `/guided-capture` and `/modulated-analysis` are preserved under the Capture Lab module for compatibility.

## Main UI Flow

1. Click `Connect USB`.
2. Click `Start`.
3. Tune frequency using `Center MHz`, `Span MHz`, `Start MHz`, or `Stop MHz`.
4. Use `Spectrum Left` and `Spectrum Right` to move across the spectrum without typing a new frequency.
5. Click the trace to create a marker.
6. Use `Peak` to mark the strongest visible signal.
7. Create M1 and M2 around the signal of interest.
8. Open `Demodulation`, select the mode, and click `Apply Demodulation`.
9. Open `Capture Lab` to record the selected band as `.cfile` or `.iq` and assign it to `train`, `val`, or `predict`.
10. Use `Dataset Builder` to run `Recompute QC`, repair missing labels from `band_profiles.json` when needed, and mark the imported record as `valid`, `doubtful`, or `rejected`.
11. Continue in `Training`, `Validation`, or `Inference` depending on the assigned split.

## Dataset Builder scientific review

Dataset Builder now exposes two separate actions:

- `Recompute QC`: recalculates offline quality from the stored IQ file and applies the backend QC policy, label status and metadata checks.
- `Fill label from band profile`: uses the backend RF band knowledge base to fill missing or placeholder class fields from the capture frequency window.

The band-profile action is deliberately conservative. It creates an editable `weak_label`, not scientific ground truth. The UI shows a separate `Confirm as strong label` action for cases where the operator has verified the class or transmitter identity. This matters because E5, E1 and E3 must not train on datasets dominated by `unknown` labels or by unreviewed weak labels.

Recommended rule for scientific experiments:

```text
capture_quality == valid
label_status == strong_label
review_status == accepted
training_readiness == ready_for_training
```

Samples with `weak_label`, `candidate`, `needs_review`, `manual_override` or `debug_only` status should be used only for exploration, training draft, robustness checks or explicit debug runs.

The RF Experiment Lab training forms now follow the same rule. If E1, E3 or E5 refuses to train, the usual causes are:

- the selected captures are still weak labels from `band_profiles.json`;
- the captures were not accepted in Dataset Builder;
- the split strategy places a class in validation/test that is absent from train;
- the selected label field is scientifically wrong for the task, for example using a band-profile `transmitter_id` for E1 physical fingerprinting.

For E5 signal-recognition baselines, prefer `signal_type` or `modulation_class`. For E1 physical fingerprinting, use operator-confirmed `transmitter_id`. For E3, choose `transmitter_id` only for device fingerprinting and `signal_type`/`modulation_class` for signal recognition.

The RF Experiment Lab tab now makes this explicit with a `Dataset eligibility` selector:

- `scientific_strict`: only reviewed `ready_for_training` captures enter E1/E3/E5.
- `training_draft`: includes `candidate` captures with `strong_label` and non-invalid QC for controlled exploratory baselines.
- `all_debug`: bypasses gates and allows weak labels only when explicitly enabled; this is not a scientific result mode.

The selected capture panel summarizes label counts, readiness, capture quality and label status so the user can see why E5 may report fewer than two trainable classes after filtering.

## Guided RF Experiment Lab Flow

The frontend now includes a dedicated `RF Experiment Lab` tab. It is designed so an operator can move from acquisition to reproducible evaluation without manually opening result JSON files.

Recommended workflow:

1. Use `Live Monitor` to find a signal and place markers around it.
2. Use `Capture Lab` to record `.cfile` or `.iq` with metadata and a clear label.
3. Use `Dataset Builder` to review QC, assign split policy and decide whether the capture is `valid`, `doubtful` or `rejected`.
4. If the capture was produced through `RF Signal Understanding`, import it from the Dataset Builder candidate area before training.
5. Open `RF Experiment Lab`.
6. Use the guided phases: Capture Dataset, Review Samples, Export Dataset, Train Models, Validate, Retrain, Live Prediction and Model Comparison.
7. Check health and dependency availability.
8. Preview export or representation steps before writing files.
9. Generate reusable representations: `raw_iq`, `fft_psd`, `spectrogram` or `waterfall`.
10. Preview the experiment to validate labels, split strategy, sample count and model availability.
11. Run E0, E5, E1 or E3 only after preview is coherent.
12. Use experiment comparison or benchmark report to compare results under the same dataset and split.

The tab also exposes a unified dataset section. Before training, the operator can normalize internal or external data into:

```text
RFExperimentDatasetV1
```

Available UI controls:

- dataset source: internal, ORACLE, WiSig, RadioML, Sig53 or custom external source;
- scientific task: device fingerprinting, signal recognition or modulation classification;
- representation: raw IQ, FFT/PSD, spectrogram or waterfall;
- label field: transmitter ID, signal type, modulation class or technology;
- split strategy: session, day, receiver, environment, device holdout or random debug;
- external path and format for imported datasets.

After export, the generated manifest path is reused by E1, E3 or E5 through `dataset_manifest_path`, so the model training code does not depend on the original source format.

The tab also surfaces RF Experiment Lab internal samples. These are experimental dataset records created inside the RF Experiment Lab workflow and expected to carry raw IQ, RF metadata, label, task, transmitter ID, signal type, modulation class, session, receiver, environment, distance, SHA-256, QC summary and split group before export.

`Capture Lab` now includes an experiment target guide. The operator can choose whether the capture is intended for the operational fingerprinting baseline, E1, E3, E5 or RF Signal Understanding. The guide explains the expected raw data, label field and scientific reason:

- E1 needs raw IQ and `transmitter_id` because it learns directly from `[2, N]` I/Q windows.
- E3 should start from raw IQ when possible so spectrogram/waterfall images are generated reproducibly.
- E5 should start from raw IQ when possible so PSD and spectral features are extracted with logged parameters.
- RF Signal Understanding should use `signal_type` or `modulation_class` style labels because it is signal recognition, not physical device fingerprinting.

`Dataset Builder` now includes a validated routing action for RF Signal Understanding. Only QC-valid captures should be registered there; doubtful or rejected samples remain blocked by the UI.

Scientific source policy shown by the UI/backend:

- ORACLE and WiSig are primarily for physical RF fingerprinting.
- RadioML and Sig53 are primarily for modulation or signal-type classification.
- Random split is allowed only as a quick debug mode, not as the main scientific result.

Current experiments visible from the UI:

| ID | Purpose | Input | Models |
|----|---------|-------|--------|
| E0 | Permanent morphological detector baseline | Waterfall/spectrogram metadata | `morphological_heuristic`, no training |
| E5 | Explainable spectral baseline | `fft_psd` / PSD features | Logistic Regression, Random Forest, SVM RBF, KNN |
| E1 | Closed-set raw-IQ fingerprinting | `raw_iq` `[2, N]` | CNN 1D |
| E3 | Closed-set RF-image classification | `spectrogram` or `waterfall` `[1, H, W]` | simple CNN 2D, optional ResNet18, optional VGG11 |

Scientific context shown in the UI:

- E0 is the RF-Fingerprint-Lab-v6 project baseline: `Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline`. The UI explains that this is the permanent explainable fallback, not a learned detector.
- E5 cites Kilic et al., Nie et al., and O Shea, Clancy and Ebeid by title: `Drone Classification Using RF Signal Based Spectral Features`, `UAV Detection and Identification Based on WiFi Signal and RF Fingerprint`, and `Practical Signal Detection and Classification in GNU Radio`. The UI explains that the adopted idea is PSD/spectral descriptors plus classical ML.
- E1 cites Riyaz et al. and Jian et al. by title: `Deep Learning Convolutional Neural Networks for Radio Identification` and `Deep Learning for RF Fingerprinting: A Massive Experimental Study`. The UI explains that the adopted idea is supervised CNN 1D over raw I/Q windows shaped `[2, N]`.
- E3 cites Shen et al., Lin et al., Liu et al., and Bremnes et al. by title: `Radio Frequency Fingerprint Identification for LoRa Using Deep Learning`, `A Radio Frequency Signal Recognition Method Based on Spectrogram`, `RF Fingerprint Recognition Based on Spectrum Waterfall Diagram`, and `Classification of UAVs Utilizing Fixed Boundary Empirical Wavelet Sub-Bands of RF Fingerprints and Deep CNN`. The UI explains that the adopted idea is time-frequency RF image classification.
- The reproducibility layer is presented as SigMF-style metadata discipline, ORACLE/WiSig dataset traceability and Jian-style experimental traceability: hashes, dataset versions, representation manifests and strict group-disjoint splits.

The wording intentionally says "adopted idea" or "paper-inspired implementation" because the project does not claim exact reproduction of the original datasets, devices, hyperparameters or full paper protocols.

The tab does not add SSD, YOLO, Faster R-CNN, Transformer, metric learning, open-set or spoofing workflows. Those model families remain future work and must not be shown as trained or available unless implemented and validated.

## Live Experiment Overlay

`Live Monitor` includes an `Experiment Overlay` next to `RF Overlay` and `Understanding Overlay`.

The overlay is a readiness and traceability overlay, not a claim of operational forensic identity. RF Experiment Lab also includes an experimental prediction panel that can persist reports for saved captures, Marker 1 / Marker 2 regions, frozen windows and live context. The report displays prediction, confidence, top-k, latency, model used, representation used and agreement/disagreement between selected E1/E3/E5 result packages.

## UI Screens

<table>
  <tr>
    <td width="50%">
      <img src="../readme_img/live_monitor_waterfall.png" alt="Live Monitor spectrum and waterfall workspace" width="100%">
      <br>
      <strong>Live Monitor</strong>
      <br>
      Spectrum, waterfall, analyzer controls, marker workflow, and device state in the primary operator view.
    </td>
    <td width="50%">
      <img src="../readme_img/live_monitor_rf_intelligence_overlay.png" alt="RF Intelligence overlay in Live Monitor" width="100%">
      <br>
      <strong>RF Overlay</strong>
      <br>
      Live RF Intelligence detections rendered directly on top of the spectrum and waterfall workspace.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="../readme_img/demodulation.png" alt="Demodulation workflow" width="100%">
      <br>
      <strong>Demodulation</strong>
      <br>
      Marker-band AM/FM/WFM demodulation with generated audio playback and export.
    </td>
    <td width="50%">
      <img src="../readme_img/capture_lab.png" alt="Capture Lab workflow" width="100%">
      <br>
      <strong>Capture Lab</strong>
      <br>
      Dataset-oriented IQ acquisition with marker/custom windows, metadata, labels, and split selection.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="../readme_img/dataset_builder.png" alt="Dataset Builder review workflow" width="100%">
      <br>
      <strong>Dataset Builder</strong>
      <br>
      QC-driven review, split assignment, and acceptance status before ML workflows.
    </td>
    <td width="50%">
      <img src="../readme_img/rf_intelligence.png" alt="RF Intelligence console" width="100%">
      <br>
      <strong>RF Intelligence</strong>
      <br>
      Explainable detected RF objects with bandwidth, confidence, SNR, candidate family, and evidence notes.
    </td>
  </tr>
</table>

## Demodulation Workflow

The frontend sends the first two markers as the selected RF band. The backend captures that real band from the USRP-B200.

- `AM`, `FM`, and `WFM` results include an audio player and WAV download button. The result card shows audio-specific fields: center frequency, bandwidth, sample rate, signal duration, audio presence, audio sample rate, gain and antenna.
- `ASK`, `FSK`, `PSK`, and `OOK` results expose IQ/metadata capture output for digital analysis. The result card shows packet-oriented fields: protocol, pipeline, packets decoded, CRC valid, channel.
- IoT pipelines (`ook_433_remote`, `zigbee`, `ble_advertising`, `lora`, `wifi_80211`) show protocol-specific decode results with address, frame and repeat information.
- If fewer than two markers exist, the demodulation button stays disabled because the RF band is not defined.
- Results persist across page refresh. The result loader reads both flat metadata files and enriched `{id}/demodulation_report.json` reports from the IoT pipelines.

## Capture Lab Workflow

`Capture Lab` is the acquisition screen for dataset generation. It can use:

- `Markers M1-M2`
- `Custom Frequencies` with synchronized `center + bandwidth` and `start + stop`

It creates dataset-style captures with:

- raw `.cfile` or `.iq` complex64 IQ samples, selected by the user
- `.json` metadata with frequency, bandwidth, sample rate, gain, antenna, label, modulation hint, SHA256, and replay parameters
- persistent listing of all generated files found on disk
- download buttons for the selected RF data file and metadata

It also shows a live QC preview for the selected capture band:

- peak level
- noise floor
- live SNR
- peak frequency

If auto-import is enabled, the capture is sent to the fingerprinting registry so later tabs can detect it by split.

## RF Fingerprinting Workflow In The UI

The ML tabs operate on curated registry captures rather than directly on arbitrary files. The expected flow is:

1. Capture raw `.cfile` or `.iq` in `Capture Lab`.
2. Import the capture into the fingerprinting registry.
3. Review QC in `Dataset Builder` and mark records as `valid`, `doubtful`, or `rejected`.
4. Assign each valid capture to `train`, `val`, or `predict`.
5. Launch `Training` or `Retraining`; the backend exports canonical I/Q automatically.
6. Launch `Validation`; selected validation captures are canonicalized with the trained model profile and checked for session leakage.
7. Use `Inference` for asynchronous prediction on `predict` captures.
8. Inspect `Models` for current model card, provenance, validation evidence, retraining history, and artifact readiness.

The UI no longer treats different original SDR `center_frequency_hz` values as an automatic validation blocker. It surfaces them as context while the backend enforces the scientifically relevant constraints: canonical preprocessing profile, canonical sample rate, canonical bandwidth, segment length, and train/validation session separation.

## Models Tab Organization

The `Models` tab now separates model information by family:

```text
current_baseline
rf_signal_understanding
E1 Raw IQ CNN 1D
E3 Spectrogram/Waterfall CNN 2D
E5 Spectral Feature Baseline
```

This separation avoids mixing legacy operational model values with new experimental runs. For example, the current `best_model.pt` size, current training records and current operational readiness are shown only when `current_baseline` is selected.

When E1, E3 or E5 is selected, the tab shows RF Experiment Lab run records only:

- experiment ID
- technique name
- model type
- input representation
- dataset version
- split strategy
- accuracy
- macro F1
- balanced accuracy when available
- inference time
- model size
- result package path

JSON files are not shown as raw dumps in the primary UI. Configs, manifests, metadata and metrics are rendered as cards, fields, tables and compact summaries so the operator can understand the model without reading raw result files.

## Dataset Builder And RF Signal Understanding Captures

`Dataset Builder` now also surfaces capture candidates generated by `RF Signal Understanding`.

This matters because RF Signal Understanding can create training examples through marker-driven teaching, region review and live/offline analysis. Those captures must still pass dataset curation before they are used by fingerprinting or RF Experiment Lab experiments.

Expected bridge:

```text
RF Signal Understanding teach/review/capture
  -> RF Signal Understanding capture registry
  -> Dataset Builder candidate list
  -> import into fingerprinting registry
  -> review QC and split
  -> RF Experiment Lab representations and experiments
```

This keeps RF Signal Understanding as the signal-analysis and labelling layer, while Dataset Builder remains the quality gate for training data.

## RF Signal Understanding AI Status

The `RF Signal Understanding` tab currently uses a hybrid signal-understanding pipeline:

- `morphological_region_detector`: non-trainable waterfall/STFT region detector based on thresholding, morphology and connected components.
- `waterfall_classifier_heuristic_v1`: non-trainable visual classifier using region bandwidth, duration and time/frequency variation.
- `numpy_softmax_regression`: trainable signal-type classifier stored as `mlp_spectral_classifier/model.npz`.
- `waterfall_visual_mlp_bispectral_fusion`: decision fusion layer combining detector output, visual classification, softmax classification, spectral features, optional bispectral hints and RF Intelligence context.

The trainable model is not a CNN, YOLO, SSD, Faster R-CNN, Transformer or metric-learning model. It is a lightweight multiclass softmax classifier for signal-type hypotheses over already detected regions.

Its dataset is the RF Signal Understanding learning buffer:

```text
backend/app/infrastructure/persistence/storage/rf_signal_understanding/learning_buffer/
```

Samples can include reviewed region images, I/Q segments, labels, label strength, training weight, frequency bounds, bandwidth, SNR, session ID and capture ID.

The model answers:

```text
Which signal-type label does this detected RF region resemble?
```

It does not answer:

```text
Which physical transmitter generated the signal?
Was the protocol decoded?
Is this open-set spoofing?
```

Those are separate RF Experiment Lab or future inference tasks.

## Validation And Inference Python Default

When the frontend is started through `run_dev.ps1`, `python_exe` in `Validation` and `Inference` is prefilled from the same RadioConda path used by the backend launcher. In normal use the operator does not need to type that path manually.

## Inference Behavior

`Inference` launches prediction as an asynchronous job. The frontend now:

- follows the returned `job_id`
- polls job status automatically
- shows `stdout`
- shows `stderr`
- shows the final prediction report when the JSON is generated

## Safety Feedback

The backend enforces safety limits before applying settings to the USRP-B200. If a value is outside the configured range, the request fails with `400 Bad Request` and the UI shows the backend error instead of applying the setting.

## Project Structure

```text
src/
  app/
    router/
    services/
    store/
  domain/
    models/
    valueObjects/
  presentation/
    controllers/
    hooks/
    views/
  shared/
    constants/
    types/
    utils/
```

## Notes

- The frontend expects real SDR data from the backend.
- If the backend returns `real_sdr_error`, the UI should show the device/backend error instead of fake data.
- If changes are not visible while Vite is running, hard-refresh with `Ctrl+F5` or restart the dev script.
