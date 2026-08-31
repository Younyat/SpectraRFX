"""Orchestrates the BLE Packet Analysis Lab's read-only analysis of one
already-completed (or partial) offline replay.

Strict read-only contract: this module never writes into
offline_replays/<replay_run_id>/ (the Phase 1 replay tree). All of its own
artifacts are written under a separate ble_lab/packet_analysis/ tree.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..capture.ble_offline_replay import read_jsonl, sha256_file, write_json, write_jsonl
from .ble_ad_structure_parser import ad_structures_view, local_name_from_structures, manufacturer_summary, service_uuids_from_structures
from .ble_capture_locator import BleCaptureLocator
from .ble_link_layer_parser import link_layer_view
from .ble_sensor_data_parser import sensor_view_for_transmitter
from .ble_transmitter_catalog import build_transmitter_catalog
from .ble_windows_evidence_correlator import read_native_rows, windows_row_view
from .models import (
    JOB_PHASES,
    LEVEL_1_BLE_PACKET_VALID,
    LEVEL_2_ADDRESS_OBSERVED,
    LEVEL_3_VENDOR_COMPATIBLE,
    LEVEL_4_LOGICAL_DEVICE_COMPATIBLE,
    LEVEL_5_WINDOWS_CORROBORATED,
    PHYSICAL_UNIT_NOT_PROVEN,
    PROVENANCE_B200,
    PROVENANCE_BOTH,
    PROVENANCE_DERIVED,
    PROVENANCE_WINDOWS,
    SCHEMA_VERSION,
    TI_COMPANY_ID,
    WINDOWS_EVIDENCE_UNAVAILABLE,
    WINDOWS_MATCHED,
    WINDOWS_NOT_MATCHED,
    field,
)

ProgressHook = Callable[[str, float, str], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BlePacketAnalysisService:
    def __init__(self, capture_root: Path, session_root: Path, analysis_root: Path) -> None:
        self.capture_root = capture_root
        self.session_root = session_root
        self.analysis_root = analysis_root
        self.analysis_root.mkdir(parents=True, exist_ok=True)
        self.locator = BleCaptureLocator(capture_root, session_root)

    def list_captures(self) -> dict[str, Any]:
        rows = self.locator.list_captures()
        classification = self.locator.classify(rows)
        for row in rows:
            row.pop("_mtime", None)
        return {"schema_version": SCHEMA_VERSION, "captures": rows, "classification": classification}

    def analyze(self, capture_id: str, replay_run_id: str | None = None, progress: ProgressHook | None = None, cancel_requested: Callable[[], bool] | None = None) -> dict[str, Any]:
        def report(phase: str, phase_progress: float, message: str) -> None:
            if progress:
                progress(phase, phase_progress, message)

        report("LOAD_CAPTURE_METADATA", 0.0, f"Cargando metadatos de {capture_id}")
        capture = self.locator.get_capture(capture_id)
        if capture is None:
            raise FileNotFoundError(f"CAPTURE_NOT_FOUND:{capture_id}")
        replay_dir = self.locator.resolve_replay_dir(capture_id, replay_run_id)
        replay_run_id = replay_dir.name
        report("LOAD_CAPTURE_METADATA", 1.0, "Metadatos cargados")

        report("VERIFY_SOURCE_INTEGRITY", 0.0, "Verificando SHA-256 del I/Q preservado")
        capture_manifest = json.loads((self.capture_root / capture_id / "capture_manifest.json").read_text(encoding="utf-8-sig"))
        iq_path = self.capture_root / capture_id / str(capture_manifest.get("data_path"))
        actual_sha = sha256_file(iq_path) if iq_path.is_file() else None
        integrity_ok = actual_sha == capture_manifest.get("data_sha256")
        if not integrity_ok:
            raise ValueError("SOURCE_IQ_SHA256_MISMATCH_SINCE_REPLAY")
        report("VERIFY_SOURCE_INTEGRITY", 1.0, "Integridad verificada")

        report("LOAD_REPLAY_LEDGER", 0.0, "Cargando candidate_manifest.jsonl y replay_summary.json")
        replay_summary_path = replay_dir / "replay_summary.json"
        replay_summary = json.loads(replay_summary_path.read_text(encoding="utf-8")) if replay_summary_path.is_file() else {}
        ledger = read_jsonl(replay_dir / "packet_association_ledger.jsonl")
        report("LOAD_REPLAY_LEDGER", 1.0, f"{len(ledger)} filas de asociacion cargadas")
        if cancel_requested and cancel_requested():
            return self._cancelled_result(capture_id, replay_run_id)

        report("LOAD_PACKETS", 0.0, "Cargando paquetes decodificados")
        decoded_packets = {row.get("packet_sha256"): row for row in read_jsonl(replay_dir / "decoded" / "decoded_packets.jsonl") if row.get("packet_sha256")}
        semantic_packets = {row.get("packet_id"): row for row in read_jsonl(replay_dir / "decoded" / "semantic_packets.jsonl") if row.get("packet_id")}
        report("LOAD_PACKETS", 1.0, f"{len(decoded_packets)} paquetes decodificados disponibles")

        target_address = str((capture.get("target_address") or "")).upper()
        report("PARSE_LINK_LAYER", 0.0, "Interpretando capa de enlace")
        enriched: list[dict[str, Any]] = []
        for index, ledger_row in enumerate(ledger):
            decoded = decoded_packets.get(ledger_row.get("packet_sha256"), {})
            semantic = semantic_packets.get(ledger_row.get("packet_sha256"), {})
            llv = link_layer_view(decoded) if decoded else None
            structures = ad_structures_view(semantic) if semantic else []
            enriched.append(self._enrich_packet(ledger_row, decoded, llv, structures, target_address))
            if index % 100 == 0:
                report("PARSE_LINK_LAYER", index / max(1, len(ledger)), f"{index}/{len(ledger)}")
        report("PARSE_LINK_LAYER", 1.0, "Capa de enlace interpretada")

        report("PARSE_AD_STRUCTURES", 1.0, "Estructuras de advertising ya resueltas por el decoder existente")
        if cancel_requested and cancel_requested():
            return self._cancelled_result(capture_id, replay_run_id)

        report("GROUP_TRANSMITTERS", 0.0, "Agrupando transmisores")
        transmitters = build_transmitter_catalog(enriched, target_address)
        report("GROUP_TRANSMITTERS", 1.0, f"{len(transmitters)} transmisores encontrados")

        report("LOAD_WINDOWS_EVIDENCE", 0.0, "Cargando callbacks Windows preservados")
        native_scan_path = self._native_scan_path(capture_id)
        native_rows = read_native_rows(native_scan_path, capture_manifest.get("b200_rf_started_at"), capture_manifest.get("b200_rf_finished_at")) if native_scan_path else []
        windows_only = [windows_row_view(row) for row in native_rows]
        report("LOAD_WINDOWS_EVIDENCE", 1.0, f"{len(windows_only)} callbacks Windows en la ventana")

        report("CORRELATE_SOURCES", 1.0, "Correlacion ya calculada por el replay original (packet_association_ledger)")
        if cancel_requested and cancel_requested():
            return self._cancelled_result(capture_id, replay_run_id)

        report("BUILD_SENSOR_VIEWS", 0.0, "Construyendo vistas de sensores")
        sensor_views = [sensor_view_for_transmitter(tx, enriched) for tx in transmitters]
        report("BUILD_SENSOR_VIEWS", 1.0, f"{len(sensor_views)} fichas de sensores")

        summary = {
            "capture_id": capture_id,
            "execution_id": capture.get("execution_id"),
            "replay_run_id": replay_run_id,
            "candidates_analyzed": (replay_summary.get("coverage") or {}).get("total_candidate_segments"),
            "crc_valid_packets": len(ledger),
            "unique_contents": len({row.get("pdu_octets") for row in decoded_packets.values() if row.get("pdu_octets")}),
            "logical_transmitters_found": len(transmitters),
            "target_address_candidates": (replay_summary.get("candidate_funnel") or {}).get("target_address_candidates"),
            "strong_associations": sum(1 for row in enriched if row["knowledge_level"] == LEVEL_5_WINDOWS_CORROBORATED and row["is_target"]),
            "ambiguous_associations": (replay_summary.get("candidate_funnel") or {}).get("conflicting_matches"),
            "scientific_decision": (replay_summary.get("decision") or {}).get("scientific_decision"),
            "dataset_eligibility_status": (replay_summary.get("decision") or {}).get("dataset_eligibility_status"),
        }

        analysis_id = self._analysis_id(capture_id, replay_run_id)
        report("WRITE_ARTIFACTS", 0.0, "Guardando artefactos de analisis")
        result = {
            "schema_version": SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "capture_id": capture_id,
            "execution_id": capture.get("execution_id"),
            "replay_run_id": replay_run_id,
            "source_read_only": True,
            "source_artifact_modified": False,
            "purpose": "BLE_PACKET_ANALYSIS",
            "diagnostic_only": True,
            "scientific_campaign_member": False,
            "dataset_eligible": False,
            "training_eligible": False,
            "generated_at_utc": utc_now(),
            "capture": {k: v for k, v in capture.items() if k != "_mtime"},
            "summary": summary,
            "transmitters": transmitters,
            "sensor_views": sensor_views,
            "windows_only_observations": windows_only,
            "packets": enriched,
        }
        self._write_artifacts(analysis_id, result)
        report("WRITE_ARTIFACTS", 1.0, "Artefactos guardados")
        report("COMPLETED", 1.0, "Analisis completo")
        return result

    def _native_scan_path(self, capture_id: str) -> Path | None:
        for manifest_path in self.session_root.glob("BLE-HYBRID-*/session_manifest.json"):
            try:
                session = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if session.get("capture_id") != capture_id:
                continue
            configured = session.get("native_scan_path")
            if configured:
                return Path(configured) / "advertisements.jsonl"
            return self.session_root.parent.parent / "ble" / "native" / "scans" / session["session_id"] / "advertisements.jsonl"
        return None

    def _enrich_packet(self, ledger_row: dict[str, Any], decoded: dict[str, Any], llv: dict[str, Any] | None, structures: list[dict[str, Any]], target_address: str) -> dict[str, Any]:
        address = ledger_row.get("advertiser_address_canonical")
        address_present = bool(address)
        is_target = bool(ledger_row.get("target_address_match"))
        strength = ledger_row.get("association_strength")
        windows_match = WINDOWS_MATCHED if strength == "STRONG" else (WINDOWS_NOT_MATCHED if ledger_row.get("nearest_windows_callback_timestamp") is None and ledger_row.get("address_match_status") != "NO_CANDIDATE_IN_WINDOW" else WINDOWS_EVIDENCE_UNAVAILABLE if ledger_row.get("address_match_status") == "NO_CANDIDATE_IN_WINDOW" and ledger_row.get("association_rejection_reason") == "WINDOWS_TIMESTAMP_UNAVAILABLE" else WINDOWS_NOT_MATCHED)

        local_name = local_name_from_structures(structures)
        manufacturer = manufacturer_summary(structures)
        service_uuids = service_uuids_from_structures(structures)

        knowledge_level = LEVEL_1_BLE_PACKET_VALID
        if address_present:
            knowledge_level = LEVEL_2_ADDRESS_OBSERVED
        if manufacturer and manufacturer.get("company_id", {}).get("value") == TI_COMPANY_ID:
            knowledge_level = LEVEL_3_VENDOR_COMPATIBLE
        if is_target:
            knowledge_level = LEVEL_4_LOGICAL_DEVICE_COMPATIBLE
        if strength == "STRONG":
            knowledge_level = LEVEL_5_WINDOWS_CORROBORATED

        row = {
            "packet_id": ledger_row.get("packet_id"),
            "candidate_id": ledger_row.get("candidate_id"),
            "is_target": is_target,
            "knowledge_level": knowledge_level,
            "physical_unit_caveat": PHYSICAL_UNIT_NOT_PROVEN,
            "pdu_type": field(ledger_row.get("pdu_type"), PROVENANCE_B200),
            "crc_valid": field(decoded.get("crc_valid", True), PROVENANCE_B200),
            "advertiser_address_raw": field(ledger_row.get("advertiser_address_raw"), PROVENANCE_B200),
            "advertiser_address_canonical": field(address, PROVENANCE_B200),
            "address_type": field(ledger_row.get("address_type"), PROVENANCE_B200),
            "byte_order_conversion": "on-air little-endian octets reversed to display order (see address_raw_air_octets vs canonical)",
            "local_name": field(local_name, PROVENANCE_B200) if local_name else None,
            "company_id": (manufacturer or {}).get("company_id"),
            "company_name": (manufacturer or {}).get("company_name"),
            "manufacturer_parser_status": (manufacturer or {}).get("manufacturer_parser_status"),
            "service_uuids": service_uuids,
            "ad_structures": structures,
            "link_layer": llv,
            "rf_timestamp_utc": ledger_row.get("rf_timestamp_utc"),
            "packet_start_sample": ledger_row.get("packet_start_sample"),
            "pdu_payload_hex": llv["pdu_payload_hex"] if llv else field(None, PROVENANCE_B200),
            "windows_evidence": {
                "nearest_windows_callback_timestamp": field(ledger_row.get("nearest_windows_callback_timestamp"), PROVENANCE_WINDOWS) if ledger_row.get("nearest_windows_callback_timestamp") else None,
                "time_delta_ms": field(ledger_row.get("time_delta_ms"), PROVENANCE_BOTH) if ledger_row.get("time_delta_ms") is not None else None,
                "address_match_status": ledger_row.get("address_match_status"),
                "temporal_match_status": ledger_row.get("temporal_match_status"),
                "association_strength": strength,
                "association_rejection_reason": ledger_row.get("association_rejection_reason"),
            },
            "windows_match": field(windows_match, PROVENANCE_DERIVED),
        }
        return row

    def _analysis_id(self, capture_id: str, replay_run_id: str) -> str:
        digest = hashlib.sha256(f"{capture_id}:{replay_run_id}".encode("utf-8")).hexdigest()[:12]
        return f"BLE-PKTLAB-{digest}"

    def _write_artifacts(self, analysis_id: str, result: dict[str, Any]) -> None:
        out_dir = self.analysis_root / analysis_id
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(out_dir / "analysis_manifest.json", {
            "schema_version": SCHEMA_VERSION, "analysis_id": analysis_id, "capture_id": result["capture_id"],
            "execution_id": result["execution_id"], "replay_run_id": result["replay_run_id"],
            "generated_at_utc": result["generated_at_utc"], "source_read_only": True, "source_artifact_modified": False,
            "purpose": result["purpose"], "diagnostic_only": True, "scientific_campaign_member": False,
            "dataset_eligible": False, "training_eligible": False,
        })
        write_json(out_dir / "source_capture_reference.json", result["capture"])
        write_jsonl(out_dir / "packet_analysis.jsonl", result["packets"])
        write_json(out_dir / "transmitter_catalog.json", {"transmitters": result["transmitters"]})
        write_jsonl(out_dir / "windows_observation_catalog.jsonl", result["windows_only_observations"])
        write_jsonl(out_dir / "sensor_data_observations.jsonl", result["sensor_views"])
        write_json(out_dir / "analysis_summary.json", result["summary"])
        write_json(out_dir / "final_report.json", result["summary"])

    def _cancelled_result(self, capture_id: str, replay_run_id: str) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "capture_id": capture_id, "replay_run_id": replay_run_id, "cancelled": True}
