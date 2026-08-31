# Unified RF Fingerprinting Station

## Comparative analysis

### `spectrum-lab`

Strengths:

- Operational FastAPI + React/TypeScript stack already wired to real SDR workflows.
- Live spectrum, waterfall, demodulation, marker logic and IQ capture already exposed from a single web application.
- Hardware-centric controls and analyzer interaction are materially ahead of the ML repository.

Weaknesses:

- Capture metadata is still analyzer-oriented, not dataset-oriented.
- No rigorous distinction between transmitter identity, transmitter class, capture scenario and dataset policy.
- No explicit capture quality review stage before dataset inclusion.

### `RF_fingerprint_platform_v3`

Strengths:

- Scientific intent is clearer: train/val/predict splits, session-aware evaluation, model lifecycle, remote training.
- The repository already encodes the methodological language of RF fingerprinting rather than generic SDR monitoring.
- Dataset, validation and inference are modeled as distinct phases.

Weaknesses:

- The live RF acquisition path is much thinner than in `spectrum-lab`.
- Capture metadata and runtime integration with the SDR stack are not yet at the rigor level required for acquisition control.
- Frontend and backend cohesion are weaker due to parallel `.js`/`.ts` outputs and a lighter UI shell.

## Architectural decision

The merged project uses `spectrum-lab` as the execution base because it already owns the real-time SDR path. The RF fingerprinting platform was used as the methodological reference for model lifecycle design, but the operational implementation now lives inside `spectrum-lab`.

This is the correct direction for one reason: in RF fingerprinting the acquisition layer constrains everything downstream. If the system cannot guarantee reproducible receiver settings, burst boundaries and traceable metadata, training rigor is compromised before ML starts.

## What was integrated

### Shared backend

The FastAPI application now includes a `fingerprinting` module with:

- dashboard summary for acquisition/QC modes,
- persistent scientific capture manifests,
- automatic quality evaluation,
- manual review updates,
- import of real IQ captures produced by the existing `modulated-signals` acquisition path.

This creates a direct bridge between:

1. live SDR capture from `spectrum-lab`,
2. scientific dataset registration required by RF fingerprinting.

### Shared frontend

The React application now exposes three coordinated operational modes:

1. `Mission Control`: overview of acquisition rigor and QC thresholds.
2. `Guided Capture`: explicit blocks for SDR configuration, transmitter identity, scenario, burst extraction and quality metrics.
3. `Dataset Builder`: manual acceptance/rejection workflow with per-capture review summary.

The previous analyzer pages remain active under the same shell:

- `Live Monitor`
- `Waterfall`
- `Recordings`
- `Demodulation`
- `Signal Analysis`

## Scientific rationale

The merged design treats the capture dashboard as a controlled acquisition station, not a passive spectrum viewer. The stored manifest separates:

- receiver configuration,
- transmitter identity,
- acquisition scenario,
- burst extraction parameters,
- quality review,
- linked artifacts and SHA-256 traceability.

This separation is necessary to reduce the risk that the model learns:

- SDR gain state,
- session artifacts,
- acquisition operator effects,
- or repeated near-duplicate segments,

instead of transmitter-specific RF fingerprints.

## Current integration boundary

The acquisition/QC side and the model lifecycle now live under the same backend and frontend shell in `spectrum-lab`.

The absorbed lifecycle includes:

- internal dataset export policies under `storage/mlops/data`,
- remote training orchestration from `backend/app/infrastructure/scripts`,
- validation reports and async job tracking,
- inference workflows attached to the unified fingerprinting registry.

The legacy repository is no longer required at runtime.
