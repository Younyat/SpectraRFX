# RF Experiment Lab validation notes

The FastAPI backend is documented to run from `backend\venv\Scripts\python.exe`, with `RADIOCONDA_PYTHON` used for GNU Radio/UHD subprocesses. In this workspace, `backend\venv\Scripts\python.exe` currently points at a missing WindowsApps Python 3.12 executable and cannot start.

Runtime validation for the RF Experiment Lab integration should therefore use:

```powershell
$env:PYTHONPATH="backend"
$env:RADIOCONDA_PYTHON="C:\Users\Usuario\radioconda\python.exe"
& "C:\Users\Usuario\radioconda\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Validated interpreter:

```text
C:\Users\Usuario\radioconda\python.exe
```

This interpreter has the required backend dependencies used by the RF Experiment Lab validation layer (`pydantic`, `numpy`, `scipy`). Optional experiment dependencies such as `h5py`, `torch` or `sklearn` are treated as optional and reported through `GET /api/rf-experiment-lab/health`.

`pytest` is not installed in the current RadioConda interpreter, so the RF Experiment Lab integration test is also executable with the standard library:

```powershell
$env:PYTHONPATH="backend"
& "C:\Users\Usuario\radioconda\python.exe" -m unittest backend.app.tests.integration.test_rf_experiment_lab -v
```

The RF Experiment Lab is an optional backend module. It must not modify capture, live spectrum, waterfall, markers, Capture Lab, Dataset Builder, RF Intelligence, or RF Signal Understanding behavior.

## Implemented RF Experiment Lab Scope

The validated layer currently includes:

- stable health reporting at `GET /api/rf-experiment-lab/health`
- stable response envelope with `status`, `module`, `available`, `message`, `data` and `errors`
- explicit optional dependency reporting
- explicit `not_implemented` status for future learned detectors and future model families that are not ready
- E0 Morphological Baseline as a formal experiment around the existing `morphological_heuristic` detector
- SigMF preview/export preserving original `.cfile` / `.iq` and `.json` files
- HDF5 experiment manifest preview/export without requiring `h5py`
- dataset version objects with source hashes
- representation extraction for `raw_iq`, `fft_psd`, `spectrogram` and `waterfall`
- representation manifest export with artifact hashes
- E5 Spectral Feature Baseline with classical ML when `sklearn` is available
- E5 all-model comparison across Logistic Regression, Random Forest, SVM RBF and KNN
- experiment listing, detail and comparison endpoints
- E1 Raw IQ CNN 1D when `torch` is available
- E1 evaluation outputs: training history, overfitting summary, group metrics, confidence summary and model metadata
- E3 Spectrogram/Waterfall CNN 2D when `torch` is available
- optional E3 ResNet18 and VGG11 when `torchvision` is available, using offline `weights=None`
- consolidated benchmark report across E1, E3 and E5

The following are intentionally not implemented yet:

- SSD waterfall detector
- Faster R-CNN waterfall detector
- YOLO waterfall detector
- Transformer RF model
- metric learning
- open-set recognition
- spoofing detection

These future modules must not return fake model results. Until they are implemented and validated, they should report unavailable or `not_implemented`.

## Current Experiment Families

| ID | Name | Authors | Paper / reference title | Adopted idea in this implementation |
|----|------|---------|-------------------------|------------------------------------|
| E0 | Morphological Baseline | RF-Fingerprint-Lab-v6 project baseline | `Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline` | Wraps the existing waterfall morphological detector as a reproducible no-training baseline and fallback. |
| E5 | Spectral Feature Baseline | Kilic et al.; Nie et al.; O Shea, Clancy and Ebeid | `Drone Classification Using RF Signal Based Spectral Features`; `UAV Detection and Identification Based on WiFi Signal and RF Fingerprint`; `Practical Signal Detection and Classification in GNU Radio` | Uses PSD statistics, spectral descriptors and classical ML as an explainable baseline before deep learning. |
| E1 | Raw IQ CNN 1D | Riyaz et al.; Jian et al. | `Deep Learning Convolutional Neural Networks for Radio Identification`; `Deep Learning for RF Fingerprinting: A Massive Experimental Study` | Uses supervised CNN 1D on raw I/Q windows shaped `[2, N]` for closed-set transmitter identification. |
| E3 | Spectrogram/Waterfall CNN 2D | Shen et al.; Lin et al.; Liu et al.; Bremnes et al. | `Radio Frequency Fingerprint Identification for LoRa Using Deep Learning`; `A Radio Frequency Signal Recognition Method Based on Spectrogram`; `RF Fingerprint Recognition Based on Spectrum Waterfall Diagram`; `Classification of UAVs Utilizing Fixed Boundary Empirical Wavelet Sub-Bands of RF Fingerprints and Deep CNN` | Uses RF time-frequency images with simple CNN 2D and optional ResNet18/VGG11 for closed-set comparison. |
| Reproducibility layer | SigMF community practice; ORACLE/WiSig dataset methodology; Jian et al. | SigMF-style metadata discipline; ORACLE/WiSig dataset traceability; `Deep Learning for RF Fingerprinting: A Massive Experimental Study` | Uses metadata validation, hashes, dataset versions, representation manifests and strict group-disjoint splits. |

These are paper-inspired implementations, not claims of exact reproduction of the original datasets, hardware, hyperparameters or full experimental protocols.

## Validation Command

Run the integration test suite from the repository root:

```powershell
$env:PYTHONPATH="backend"
& "C:\Users\Usuario\radioconda\python.exe" -m unittest backend.app.tests.integration.test_rf_experiment_lab -v
```

This suite covers the RF Experiment Lab integration layer, E0, SigMF, HDF5 manifest, representations, E5, E1, E3, experiment comparison and benchmark report behavior. Tests that require unavailable optional dependencies should skip or fail cleanly according to the feature being tested.

## Frontend Validation Notes

The frontend now exposes RF Experiment Lab as a guided tab and keeps the Models tab separated by model family:

- `current_baseline` shows the operational model and artifacts such as `best_model.pt`
- `rf_signal_understanding` shows signal-understanding records
- `E1`, `E3` and `E5` show RF Experiment Lab experiment runs only

The UI should not display raw JSON files as the primary user experience. JSON-derived data is expected to be rendered as cards, tables, metrics and concise key/value summaries.
