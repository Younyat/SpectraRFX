"""Evidence Stage: turns one already-replayed capture into ExampleRecord +
ExampleAnnotation pairs.

Reuses the validated BLE Packet Analysis Lab service (Phase 2) for every
per-packet judgement that already exists and works there -- knowledge level,
CRC validity, target-address matching, Windows corroboration -- instead of
re-parsing decoded packets from scratch. This stage's own job is narrower:
translate that already-computed evidence into the NEW, separated
association_status / quality_status / dataset_eligibility vocabulary, resolve
physical_unit_id through the Physical Device Registry (never through the
address itself), and produce the exact iq_start_sample/iq_end_sample pair
that makes example_id reproducible.

Strictly read-only over Phase 1/Phase 2 artifacts, exactly like the Packet
Analysis Lab it wraps: nothing here writes into offline_replays/<run>/.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_offline_replay import read_jsonl, utc_now
from app.infrastructure.ble.packet_analysis.ble_packet_analysis_service import BlePacketAnalysisService

from ..contracts import CaptureRecord, ExampleAnnotation, ExampleRecord, LabelDecision, LabelEvidenceItem
from ..registry import PhysicalDeviceRegistry

# BLE LE 1M PHY -- same constant ble_offline_replay.py's _associate() uses to
# convert a bit offset within a segment into a sample offset.
_SYMBOL_RATE_HZ = 1_000_000.0
_CONFLICT_REJECTION_REASON = "MULTIPLE_NATIVE_CALLBACKS"

# Real BLE advertising-channel center frequencies (Bluetooth Core Spec,
# Vol 6 Part B, 1.4.1) -- deliberately NOT the linear "2402 + 2*channel_index"
# formula, which is only valid for DATA channels 0-36 and gives a physically
# wrong frequency for the three advertising channels (e.g. channel 37 is at
# 2402 MHz, not 2402+2*37=2476 MHz). Duplicated rather than imported from
# studio_repository.py/campaign_orchestrator.py, matching this codebase's
# existing convention of small intentional constant duplication over
# cross-module coupling (see _CAPTURE_TERMINAL in campaign_orchestrator.py).
BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}
# P0.5 correction (2026-08-08): tight on purpose -- this is a blocking
# correctness gate at data-ingestion time, not the looser 10 MHz drift
# tolerance StudioRepository._resolve_ble_channel uses for live SDR-tuning
# compatibility checks. Real captures on disk tune to an exact integer Hz;
# a bug here previously produced a 74 MHz-off value (channel 37 stamped
# alongside a 2476 MHz center_frequency_hz), nowhere close to this margin.
_BLE_CHANNEL_FREQUENCY_BLOCKING_TOLERANCE_HZ = 1_000_000.0


def validate_ble_channel_matches_frequency(ble_channel: int, center_frequency_hz: float, *, capture_id: str) -> None:
    """Blocking guard: a declared BLE advertising channel must correspond to
    the capture's real center_frequency_hz, or every ExampleRecord built
    from it silently carries a self-contradictory channel/frequency pair
    (e.g. channel=37 with center_frequency_hz=2476000000 -- not a real BLE
    advertising frequency at all)."""
    expected_hz = BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ.get(ble_channel)
    if expected_hz is None:
        raise ValueError(
            f"BLE_CHANNEL_FREQUENCY_MISMATCH:{capture_id}: ble_channel={ble_channel} is not a real BLE "
            f"advertising channel (must be one of {sorted(BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ)})."
        )
    if abs(expected_hz - center_frequency_hz) > _BLE_CHANNEL_FREQUENCY_BLOCKING_TOLERANCE_HZ:
        raise ValueError(
            f"BLE_CHANNEL_FREQUENCY_MISMATCH:{capture_id}: ble_channel={ble_channel} expects "
            f"center_frequency_hz~={expected_hz}, but this capture's center_frequency_hz={center_frequency_hz}."
        )


class EvidenceStage:
    def __init__(self, legacy_capture_root: Path, legacy_session_root: Path, analysis_root: Path, registry: PhysicalDeviceRegistry) -> None:
        self.legacy_capture_root = legacy_capture_root
        self.registry = registry
        self.service = BlePacketAnalysisService(legacy_capture_root, legacy_session_root, analysis_root)

    def build_examples(
        self,
        *,
        capture: CaptureRecord,
        project_id: str,
        ble_channel: int,
        replay_run_id: str | None = None,
        generated_at: str | None = None,
    ) -> list[tuple[ExampleRecord, ExampleAnnotation]]:
        validate_ble_channel_matches_frequency(ble_channel, capture.center_frequency_hz, capture_id=capture.capture_id)
        analysis = self.service.analyze(capture.capture_id, replay_run_id)
        resolved_replay_run_id = analysis["replay_run_id"]
        replay_dir = self.legacy_capture_root / capture.capture_id / "offline_replays" / resolved_replay_run_id

        sha_by_packet_id = {row["packet_id"]: row.get("packet_sha256") for row in read_jsonl(replay_dir / "packet_association_ledger.jsonl")}
        bit_span_by_sha = {
            row["packet_sha256"]: (row.get("packet_start_bit"), row.get("packet_end_bit"))
            for row in read_jsonl(replay_dir / "decoded" / "decoded_packets.jsonl")
            if row.get("packet_sha256")
        }

        generated_at = generated_at or utc_now()
        rate = float(capture.sample_rate_sps)
        isolated_unit_id = capture.isolation_declared_physical_unit_id

        pairs: list[tuple[ExampleRecord, ExampleAnnotation]] = []
        for packet in analysis["packets"]:
            example = self._build_example(packet, capture, project_id, ble_channel, bit_span_by_sha, sha_by_packet_id, rate, generated_at, isolated_unit_id)
            annotation = self._build_annotation(packet, example, generated_at, isolated_unit_id, capture)
            pairs.append((example, annotation))
        return pairs

    # ------------------------------------------------------------------

    def _iq_end_sample(self, packet: dict[str, Any], iq_start_sample: int, sha_by_packet_id: dict, bit_span_by_sha: dict, rate: float) -> int:
        packet_sha256 = sha_by_packet_id.get(packet["packet_id"])
        start_bit, end_bit = bit_span_by_sha.get(packet_sha256, (None, None))
        if start_bit is None or end_bit is None:
            return iq_start_sample
        return iq_start_sample + round((int(end_bit) - int(start_bit)) * rate / _SYMBOL_RATE_HZ)

    def _association_status(self, packet: dict[str, Any]) -> str:
        strength = packet["windows_evidence"]["association_strength"]
        if packet["windows_evidence"]["association_rejection_reason"] == _CONFLICT_REJECTION_REASON:
            return "CONFLICT"
        if strength == "STRONG":
            return "STRONG"
        if strength == "WEAK":
            return "AMBIGUOUS"
        return "NONE"

    def _build_example(
        self, packet: dict[str, Any], capture: CaptureRecord, project_id: str, ble_channel: int,
        bit_span_by_sha: dict, sha_by_packet_id: dict, rate: float, generated_at: str,
        isolated_unit_id: str | None = None,
    ) -> ExampleRecord:
        iq_start_sample = int(packet["packet_start_sample"])
        iq_end_sample = self._iq_end_sample(packet, iq_start_sample, sha_by_packet_id, bit_span_by_sha, rate)
        address = packet["advertiser_address_canonical"]["value"]

        if isolated_unit_id:
            # Address-based association is meaningless here by construction:
            # the operator has declared this whole capture isolated to one
            # physical unit, precisely because address matching cannot be
            # trusted for it (rotating/private radio-layer addresses). Every
            # recovered packet is attributed to that unit -- ground truth
            # from physical setup, not from the (unreliable) address.
            association_status = "PHYSICAL_ISOLATION_DECLARED"
            physical_unit_id = isolated_unit_id
        else:
            association_status = self._association_status(packet)
            binding = self.registry.find_binding_for_address(project_id, address) if address else None
            physical_unit_id = binding.bound_physical_unit_id if binding and binding.binding_status == "BOUND" else None

        if (
            capture.capture_purpose == "BACKGROUND_TARGET_OFF"
            and capture.target_reference_id
            and physical_unit_id == capture.target_reference_id
        ):
            # The operator declared the target device off/removed for this
            # whole capture -- if the (unreliable) address match says
            # otherwise, that is a genuine contradiction between declaration
            # and evidence, not proof the device was actually on. Never
            # silently trust the address over the declaration by linking this
            # as a positive example: surface it as CONFLICT/quarantined
            # instead, same bucket as MULTIPLE_NATIVE_CALLBACKS.
            association_status = "CONFLICT"
            physical_unit_id = None

        quality_status = "PASSED" if packet["crc_valid"]["value"] else "FAILED"

        # Conservative first-pass rule: only CONFLICT is quarantined outright.
        # Everything else waits for the Fase 2 Dataset Builder gate (leakage,
        # duplicates, session-split feasibility) before it can become
        # ELIGIBLE -- Evidence Stage never promotes straight to ELIGIBLE.
        dataset_eligibility = "QUARANTINED" if association_status == "CONFLICT" else "PENDING_ANALYSIS"

        example_id = ExampleRecord.make_example_id(capture.iq_sha256, iq_start_sample, iq_end_sample, packet["candidate_id"], packet["packet_id"])
        return ExampleRecord(
            example_id=example_id,
            project_id=project_id,
            campaign_id=capture.campaign_id,
            capture_id=capture.capture_id,
            execution_id=capture.execution_id,
            session_id=capture.session_id,
            candidate_id=packet["candidate_id"],
            packet_id=packet["packet_id"],
            source_iq_sha256=capture.iq_sha256,
            iq_start_sample=iq_start_sample,
            iq_end_sample=iq_end_sample,
            physical_unit_id=physical_unit_id,
            logical_transmitter_id=f"TX-{address.replace(':', '')}" if address else None,
            capture_purpose=capture.capture_purpose,
            background_kind=capture.background_kind,
            association_status=association_status,
            quality_status=quality_status,
            dataset_eligibility=dataset_eligibility,
            channel=ble_channel,
            sample_rate_sps=capture.sample_rate_sps,
            center_frequency_hz=capture.center_frequency_hz,
            created_at=generated_at,
        )

    def _build_annotation(
        self, packet: dict[str, Any], example: ExampleRecord, generated_at: str,
        isolated_unit_id: str | None = None, capture: CaptureRecord | None = None,
    ) -> ExampleAnnotation:
        is_background_contradiction = (
            capture is not None
            and capture.capture_purpose == "BACKGROUND_TARGET_OFF"
            and bool(capture.target_reference_id)
            and example.association_status == "CONFLICT"
            and packet["windows_evidence"]["association_rejection_reason"] != _CONFLICT_REJECTION_REASON
        )
        evidence_items = [LabelEvidenceItem(
            source_type="B200_PACKET", artifact_id=packet["packet_id"], timestamp=example.created_at,
            strength="STRONG" if example.quality_status == "PASSED" else "WEAK",
            description=f"CRC-{'valid' if example.quality_status == 'PASSED' else 'invalid'} BLE packet, pdu_type={packet['pdu_type']['value']}",
        )]
        if isolated_unit_id:
            evidence_items.append(LabelEvidenceItem(
                source_type="OPERATOR_DECLARATION", artifact_id=example.capture_id, timestamp=example.created_at,
                strength="DOCUMENTARY",
                description=f"Operator declared physical isolation: only {isolated_unit_id} was transmitting nearby for the whole capture.",
            ))
        nearest_ts = packet["windows_evidence"]["nearest_windows_callback_timestamp"]
        if nearest_ts:
            delta = packet["windows_evidence"]["time_delta_ms"]
            evidence_items.append(LabelEvidenceItem(
                source_type="WINDOWS_OBSERVATION", artifact_id=packet["packet_id"], timestamp=nearest_ts["value"],
                strength="STRONG" if example.association_status == "STRONG" else "WEAK",
                description=f"Nearest native Windows callback, time_delta_ms={delta['value'] if delta else None}",
            ))

        if isolated_unit_id:
            label = isolated_unit_id
            decision_status, reason = "CONFIRMED", (
                "Physical isolation declared by the operator (only this unit was transmitting nearby) -- "
                "NOT an address-based or Windows-corroborated association. Weaker ground truth than a STRONG "
                "match: it depends entirely on the physical setup being correct, with no independent cross-check."
            )
        elif example.association_status == "STRONG" and example.physical_unit_id:
            label = example.physical_unit_id
            decision_status, reason = "CONFIRMED", "Strong B200+Windows association to a registered physical-unit address binding."
        elif is_background_contradiction:
            label = "UNKNOWN_ENVIRONMENTAL_TRANSMITTER"
            decision_status, reason = "AMBIGUOUS", (
                f"Address matched {capture.target_reference_id}, but the operator declared that unit powered off/removed "
                "for this whole BACKGROUND_ENVIRONMENT capture -- a contradiction between declaration and (unreliable) "
                "address evidence, never silently resolved in favour of the address. Not linked as a positive example."
            )
        elif example.association_status == "CONFLICT":
            label = "UNKNOWN_ENVIRONMENTAL_TRANSMITTER"
            decision_status, reason = "AMBIGUOUS", "Multiple native Windows callbacks fell inside the same association time window (MULTIPLE_NATIVE_CALLBACKS)."
        elif example.physical_unit_id:
            label = example.physical_unit_id
            decision_status, reason = "PROVISIONAL", "Address matches a registered physical-unit binding but without a strong Windows-corroborated association."
        else:
            label = "UNKNOWN_ENVIRONMENTAL_TRANSMITTER"
            decision_status, reason = "PROVISIONAL", "No registered physical-unit binding exists for this address in this project."

        return ExampleAnnotation(
            annotation_id=ExampleAnnotation.make_annotation_id(example.example_id, 1),
            example_id=example.example_id,
            annotation_version=1,
            label_evidence=evidence_items,
            label_decision=LabelDecision(
                label=label, decision_status=decision_status, decision_reason=reason,
                decided_by="system:ble_rffi_studio_evidence_stage", decided_at=generated_at,
            ),
            created_at=generated_at,
        )
