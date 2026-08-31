"""Generates a clearly-labeled SYNTHETIC_DEMO project: multi-unit,
multi-session complex64 signals (a carrier at a per-unit frequency offset
plus noise -- NOT real captured RF data) written into the same on-disk
shape a real capture would have, so the exact same repository methods
(dataset build, quality gate, split, training, evaluation, export,
inference) run against it unmodified.

Exists only so the guided "sufficient evidence -> READY split -> trained
model -> exported bundle" path can be demonstrated end to end without SDR
hardware. Every id this seeder produces is prefixed SYNTHETIC- or carries
project_id=SYNTHETIC_DEMO, so real and synthetic results are never
ambiguous downstream.
"""
from __future__ import annotations

import zlib
from typing import Any

import numpy as np

from app.config.runtime_settings import get_runtime_value
from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl

from ..contracts import CaptureRecord, ExampleRecord
from ..evidence.evidence_stage import BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ

DEMO_PROJECT_ID = "SYNTHETIC_DEMO"
DEMO_CAMPAIGN_ID = "SYNTHETIC_DEMO-CAMPAIGN"
DEMO_DEVICE_FAMILY = "SYNTHETIC_DEMO_DEVICE"


class RealCampaignModeError(Exception):
    pass


class SyntheticDemoSeeder:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def seed(
        self,
        *,
        units: int = 2,
        sessions_per_unit: int = 3,
        examples_per_session: int = 12,
        samples_per_example: int = 800,
        sample_rate: float = 4_000_000.0,
        noise_scale: float = 0.2,
        cfo_step_hz: float = 50_000.0,
        ble_channel: int = 37,
    ) -> dict[str, Any]:
        if get_runtime_value("SCIENTIFIC_REAL_CAMPAIGN_MODE", False):
            raise RealCampaignModeError(
                "SCIENTIFIC_REAL_CAMPAIGN_MODE is on -- synthetic/demo data generation is forbidden while the real "
                "experimental campaign is running. Turn the setting off first if a demo is genuinely intended."
            )
        physical_unit_ids: list[str] = []
        capture_ids: list[str] = []
        created_at = utc_now()

        for unit_index in range(units):
            unit_id = f"SYNTHETIC-UNIT-{unit_index:02d}"
            physical_unit_ids.append(unit_id)
            self.repository.registry.register_physical_unit(
                physical_unit_id=unit_id, project_id=DEMO_PROJECT_ID, device_family=DEMO_DEVICE_FAMILY,
                operator_declaration_id=f"synthetic-demo-decl-{unit_id}", first_registered_at=created_at,
            )
            cfo_hz = cfo_step_hz * (unit_index + 1)
            for session_index in range(sessions_per_unit):
                session_id = f"SYNTHETIC-SESSION-{unit_id}-{session_index:02d}"
                capture_id = f"SYNTHETIC-CAP-{session_id}"
                capture_ids.append(capture_id)
                self._write_capture(capture_id, session_id, unit_id, cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, ble_channel, created_at)
                self._write_evidence(capture_id, session_id, unit_id, examples_per_session, samples_per_example, sample_rate, ble_channel, created_at)

        return {"project_id": DEMO_PROJECT_ID, "campaign_id": DEMO_CAMPAIGN_ID, "capture_ids": capture_ids, "physical_unit_ids": physical_unit_ids}

    def _write_capture(self, capture_id, session_id, unit_id, cfo_hz, examples_per_session, samples_per_example, sample_rate, noise_scale, ble_channel, created_at) -> None:
        # Not Python's built-in hash() -- str/tuple hashing is randomized
        # per-process (PYTHONHASHSEED, not pinned anywhere in this project),
        # so a seed built from it would make this "synthetic but
        # reproducible" demo data actually change across process runs.
        seed = zlib.crc32(f"{unit_id}:{session_id}".encode("utf-8")) % (2**32)
        rng = np.random.default_rng(seed)
        total_samples = examples_per_session * samples_per_example
        n = np.arange(total_samples)
        carrier = np.exp(1j * 2 * np.pi * cfo_hz * n / sample_rate)
        noise = (rng.standard_normal(total_samples) + 1j * rng.standard_normal(total_samples)) * noise_scale
        iq = (carrier + noise).astype(np.complex64)

        capture_dir = self.repository.legacy_capture_root / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        iq_path = capture_dir / "iq.cf32"
        iq.tofile(iq_path)

        capture = CaptureRecord(
            project_id=DEMO_PROJECT_ID, campaign_id=DEMO_CAMPAIGN_ID, capture_id=capture_id, session_id=session_id,
            execution_id=f"SYNTHETIC-EXEC-{session_id}", data_origin="SYNTHETIC_TEST_ONLY", physical_unit_id=unit_id,
            receiver_device_id="synthetic-demo-generator", sdr_model="SYNTHETIC_DEMO_GENERATOR", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=int(sample_rate), sample_dtype="cf32_le", byte_order="little_endian",
            sample_count=total_samples, channel_count=1, center_frequency_hz=BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ[ble_channel],
            frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=0.0, gain_mode="synthetic",
            capture_duration_s=total_samples / sample_rate, capture_tool="synthetic_demo_seeder",
            iq_path="iq.cf32", iq_size_bytes=iq_path.stat().st_size, iq_sha256=sha256_file(iq_path),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=created_at,
        )
        write_json(self.repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))

    def _write_evidence(self, capture_id, session_id, unit_id, examples_per_session, samples_per_example, sample_rate, ble_channel, created_at) -> None:
        examples = []
        for example_index in range(examples_per_session):
            start = example_index * samples_per_example
            end = start + samples_per_example
            # candidate_id/packet_id must be unique across the whole demo
            # project, not just within one session -- reusing "cand-0" per
            # session is exactly the kind of collision the leakage checker
            # (correctly) rejects, so capture_id is folded into both here.
            candidate_id = f"cand-{capture_id}-{example_index}"
            packet_id = f"pkt-{capture_id}-{example_index}"
            example_id = ExampleRecord.make_example_id(f"sha-{capture_id}", start, end, candidate_id, packet_id)
            examples.append(ExampleRecord(
                example_id=example_id, project_id=DEMO_PROJECT_ID, campaign_id=DEMO_CAMPAIGN_ID, capture_id=capture_id,
                execution_id=f"SYNTHETIC-EXEC-{session_id}", session_id=session_id, candidate_id=candidate_id, packet_id=packet_id,
                source_iq_sha256=f"sha-{capture_id}", iq_start_sample=start, iq_end_sample=end, physical_unit_id=unit_id,
                logical_transmitter_id=f"TX-{unit_id}", association_status="STRONG", quality_status="PASSED", dataset_eligibility="PENDING_ANALYSIS",
                channel=ble_channel, sample_rate_sps=int(sample_rate), center_frequency_hz=BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ[ble_channel], created_at=created_at,
            ))
        evidence_dir = self.repository.evidence_dir / capture_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in examples])
        write_jsonl(evidence_dir / "annotations.jsonl", [])
