"""Shared, deliberately-synthetic construction helpers for Fase 2+ tests.
Nothing here is presented as real RF data -- IDs are made-up and IQ sample
ranges are small integers, used only to exercise dataset/split/quality logic
independent of any specific capture.
"""
from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np

from app.modules.ble_rffi_studio.contracts import ExampleRecord


def _stable_seed(*parts: object) -> int:
    """Deterministic RNG seed from arbitrary parts -- NOT Python's built-in
    hash() (str/tuple hashing is randomized per-process by PYTHONHASHSEED,
    which is not pinned anywhere in this project, so a seed built from
    hash() changes across test-process runs even though it's stable within
    one run). zlib.crc32 has no such randomization."""
    return zlib.crc32(str(parts).encode("utf-8")) % (2**32)


def make_example(
    *,
    example_index: int,
    physical_unit_id: str | None,
    session_id: str,
    capture_id: str | None = None,
    execution_id: str | None = None,
    candidate_id: str | None = None,
    packet_id: str | None = None,
    source_iq_sha256: str = "synthetic-sha-0",
    iq_start_sample: int | None = None,
    iq_end_sample: int | None = None,
    association_status: str = "STRONG",
    quality_status: str = "PASSED",
    dataset_eligibility: str = "PENDING_ANALYSIS",
    project_id: str = "SYN-PROJECT",
    campaign_id: str = "SYN-CAMPAIGN-01",
    capture_purpose: str | None = None,
) -> ExampleRecord:
    start = iq_start_sample if iq_start_sample is not None else example_index * 2000
    end = iq_end_sample if iq_end_sample is not None else start + 1000
    candidate_id = candidate_id or f"cand-{example_index}"
    packet_id = packet_id or f"pkt-{example_index}"
    example_id = ExampleRecord.make_example_id(source_iq_sha256, start, end, candidate_id, packet_id)
    return ExampleRecord(
        example_id=example_id,
        project_id=project_id,
        campaign_id=campaign_id,
        capture_id=capture_id or f"SYN-CAP-{session_id}",
        execution_id=execution_id or f"SYN-EXEC-{session_id}",
        session_id=session_id,
        candidate_id=candidate_id,
        packet_id=packet_id,
        source_iq_sha256=source_iq_sha256,
        iq_start_sample=start,
        iq_end_sample=end,
        physical_unit_id=physical_unit_id,
        logical_transmitter_id=f"TX-{physical_unit_id}" if physical_unit_id else None,
        capture_purpose=capture_purpose,
        association_status=association_status,
        quality_status=quality_status,
        dataset_eligibility=dataset_eligibility,
        channel=37,
        sample_rate_sps=4_000_000,
        center_frequency_hz=2_402_000_000,
        created_at="2026-07-26T00:00:00Z",
    )


def make_multi_unit_multi_session_examples(units: int = 2, sessions_per_unit: int = 3, examples_per_session: int = 5) -> list[ExampleRecord]:
    """Enough independent sessions per unit for SAME_MODEL_UNIT_IDENTIFICATION
    to become READY (>=2 units, >=3 sessions each)."""
    examples: list[ExampleRecord] = []
    counter = 0
    for unit_index in range(units):
        unit_id = f"SYN-UNIT-{unit_index:02d}"
        for session_index in range(sessions_per_unit):
            session_id = f"SYN-SESSION-{unit_id}-{session_index:02d}"
            for _ in range(examples_per_session):
                examples.append(make_example(
                    example_index=counter, physical_unit_id=unit_id, session_id=session_id,
                    source_iq_sha256=f"synthetic-sha-{unit_id}-{session_index}",
                ))
                counter += 1
    return examples


def _write_session_iq(
    tmp_path: Path, capture_id: str, cfo_hz: float, examples_per_session: int, samples_per_example: int,
    sample_rate: float, noise_scale: float, seed_key: tuple,
) -> Path:
    rng = np.random.default_rng(_stable_seed(seed_key))
    total_samples = examples_per_session * samples_per_example
    n = np.arange(total_samples)
    carrier = np.exp(1j * 2 * np.pi * cfo_hz * n / sample_rate)
    noise = (rng.standard_normal(total_samples) + 1j * rng.standard_normal(total_samples)) * noise_scale
    iq = (carrier + noise).astype(np.complex64)
    iq_path = tmp_path / f"{capture_id}.cf32"
    iq.tofile(iq_path)
    return iq_path


def write_synthetic_capture_iq(
    tmp_path: Path,
    units: int = 2,
    sessions_per_unit: int = 3,
    examples_per_session: int = 6,
    samples_per_example: int = 800,
    sample_rate: float = 4_000_000.0,
    noise_scale: float = 0.3,
    cfo_step_hz: float = 20_000.0,
) -> tuple[list[ExampleRecord], dict[str, Path]]:
    """Writes one synthetic .cf32 (complex64) file per session: a carrier
    with a PER-UNIT frequency offset plus Gaussian noise. Not real RF data --
    a controllable, genuinely-separable-but-noisy toy signal so baseline/CNN
    training in tests exercises real convergence instead of a trivial or
    fabricated 100%-accuracy shortcut.
    """
    examples: list[ExampleRecord] = []
    capture_iq_paths: dict[str, Path] = {}
    counter = 0
    for unit_index in range(units):
        unit_id = f"SYN-UNIT-{unit_index:02d}"
        cfo_hz = cfo_step_hz * (unit_index + 1)
        for session_index in range(sessions_per_unit):
            session_id = f"SYN-SESSION-{unit_id}-{session_index:02d}"
            capture_id = f"SYN-CAP-{session_id}"
            iq_path = _write_session_iq(tmp_path, capture_id, cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, (unit_id, session_id))
            capture_iq_paths[capture_id] = iq_path

            for example_index in range(examples_per_session):
                start = example_index * samples_per_example
                end = start + samples_per_example
                examples.append(make_example(
                    example_index=counter, physical_unit_id=unit_id, session_id=session_id,
                    capture_id=capture_id, source_iq_sha256=f"sha-{capture_id}",
                    iq_start_sample=start, iq_end_sample=end,
                ))
                counter += 1
    return examples, capture_iq_paths


def write_unknown_device_rejection_fixture(
    tmp_path: Path,
    known_units: int = 2,
    known_sessions: int = 3,
    unknown_sessions: int = 2,
    examples_per_session: int = 16,
    samples_per_example: int = 800,
    sample_rate: float = 4_000_000.0,
    noise_scale: float = 0.15,
    known_cfo_step_hz: float = 60_000.0,
    unknown_cfo_hz: float = 260_000.0,
) -> tuple[list[ExampleRecord], dict[str, Path]]:
    """>=2 known physical units (a real closed-set classifier needs >=2
    classes in TRAIN to be meaningful) each with enough sessions for
    TRAIN/VALIDATION/TEST, plus a clearly-different synthetic signal (a much
    larger CFO) standing in for 'unknown device' sessions -- split only
    across VALIDATION/TEST by SplitBuilder, never TRAIN."""
    examples: list[ExampleRecord] = []
    capture_iq_paths: dict[str, Path] = {}
    counter = 0
    for unit_index in range(known_units):
        unit_id = f"SYN-KNOWN-UNIT-{unit_index:02d}"
        cfo_hz = known_cfo_step_hz * (unit_index + 1)
        for session_index in range(known_sessions):
            session_id = f"SYN-KNOWN-SESSION-{unit_id}-{session_index:02d}"
            capture_id = f"SYN-CAP-{session_id}"
            iq_path = _write_session_iq(tmp_path, capture_id, cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, (unit_id, session_id))
            capture_iq_paths[capture_id] = iq_path
            for example_index in range(examples_per_session):
                start, end = example_index * samples_per_example, example_index * samples_per_example + samples_per_example
                examples.append(make_example(example_index=counter, physical_unit_id=unit_id, session_id=session_id, capture_id=capture_id, source_iq_sha256=f"sha-{capture_id}", iq_start_sample=start, iq_end_sample=end))
                counter += 1

    for session_index in range(unknown_sessions):
        session_id = f"SYN-UNKNOWN-SESSION-{session_index:02d}"
        capture_id = f"SYN-CAP-{session_id}"
        iq_path = _write_session_iq(tmp_path, capture_id, unknown_cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, ("unknown", session_id))
        capture_iq_paths[capture_id] = iq_path
        for example_index in range(examples_per_session):
            start, end = example_index * samples_per_example, example_index * samples_per_example + samples_per_example
            examples.append(make_example(example_index=counter, physical_unit_id=None, session_id=session_id, capture_id=capture_id, source_iq_sha256=f"sha-{capture_id}", iq_start_sample=start, iq_end_sample=end))
            counter += 1

    return examples, capture_iq_paths


def write_target_vs_background_fixture(
    tmp_path: Path,
    target_sessions: int = 3,
    background_sessions: int = 3,
    examples_per_session: int = 16,
    samples_per_example: int = 800,
    sample_rate: float = 4_000_000.0,
    noise_scale: float = 0.15,
    target_cfo_hz: float = 80_000.0,
    background_cfo_hz: float = 280_000.0,
) -> tuple[list[ExampleRecord], dict[str, Path]]:
    """TARGET_VS_BACKGROUND needs BOTH classes genuinely present in
    TRAIN/VALIDATION/TEST (see split_builder.py's redesign) -- target
    sessions carry a real physical_unit_id match; background sessions are
    explicitly capture_purpose=BACKGROUND_ENVIRONMENT (the operator
    confirmed the target was off/removed), never just "no address match"."""
    examples: list[ExampleRecord] = []
    capture_iq_paths: dict[str, Path] = {}
    counter = 0
    unit_id = "SYN-TARGET-UNIT"
    for session_index in range(target_sessions):
        session_id = f"SYN-TARGET-SESSION-{session_index:02d}"
        capture_id = f"SYN-CAP-{session_id}"
        iq_path = _write_session_iq(tmp_path, capture_id, target_cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, (unit_id, session_id))
        capture_iq_paths[capture_id] = iq_path
        for example_index in range(examples_per_session):
            start, end = example_index * samples_per_example, example_index * samples_per_example + samples_per_example
            examples.append(make_example(
                example_index=counter, physical_unit_id=unit_id, session_id=session_id, capture_id=capture_id,
                source_iq_sha256=f"sha-{capture_id}", iq_start_sample=start, iq_end_sample=end, capture_purpose="TARGET_DEVICE_ON",
            ))
            counter += 1

    for session_index in range(background_sessions):
        session_id = f"SYN-BACKGROUND-SESSION-{session_index:02d}"
        capture_id = f"SYN-CAP-{session_id}"
        iq_path = _write_session_iq(tmp_path, capture_id, background_cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, ("background", session_id))
        capture_iq_paths[capture_id] = iq_path
        for example_index in range(examples_per_session):
            start, end = example_index * samples_per_example, example_index * samples_per_example + samples_per_example
            examples.append(make_example(
                example_index=counter, physical_unit_id=None, session_id=session_id, capture_id=capture_id,
                source_iq_sha256=f"sha-{capture_id}", iq_start_sample=start, iq_end_sample=end, capture_purpose="BACKGROUND_TARGET_OFF",
            ))
            counter += 1

    return examples, capture_iq_paths
