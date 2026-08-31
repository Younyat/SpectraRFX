"""Paper progress dashboard, point 3 (2026-08-11): read-only decision-
provenance reconstruction. There is no single `decision_id` anywhere in
this codebase (confirmed: `inference_runs/<id>.json` is the only persisted
per-decision artifact, keyed by `example_id` within one
`inference_run_id`) -- so the addressable unit here is
`(inference_run_id, example_id)`, never an invented decision_id.

Every link in the chain is resolved by a real, deterministic lookup
(reading an already-persisted file, or searching real files for real
containment) -- NEVER a heuristic or a guess. A link that cannot be
resolved is reported as `missing_link`, and any two hashes that SHOULD
agree but do not are reported as `hash_mismatch` -- either one forces
`provenance_status` away from `COMPLETE`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROVENANCE_STATUS_COMPLETE = "COMPLETE"
PROVENANCE_STATUS_INCOMPLETE = "INCOMPLETE"
PROVENANCE_STATUS_FAIL = "FAIL"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reconstruct_decision_provenance(repository: Any, *, inference_run_id: str, example_id: str) -> dict[str, Any]:
    chain: dict[str, Any] = {"inference_run_id": inference_run_id, "example_id": example_id}
    missing_links: list[str] = []
    hash_mismatches: list[str] = []

    inference_run_path = repository.ble_root / "inference_runs" / f"{inference_run_id}.json"
    if not inference_run_path.is_file():
        return {
            **chain, "provenance_status": PROVENANCE_STATUS_FAIL,
            "missing_link": ["inference_run not found on disk"], "hash_mismatch": [],
        }
    inference_run = _read_json(inference_run_path)
    chain["bundle_id"] = inference_run.get("bundle_id")
    chain["bundle_sha256"] = inference_run.get("bundle_sha256")
    chain["representation_profile_id"] = inference_run.get("representation_profile_id")
    chain["base_preprocessing_profile_id"] = inference_run.get("base_preprocessing_profile_id")

    decision = next((d for d in inference_run.get("decisions", []) if d.get("example_id") == example_id), None)
    if decision is None:
        missing_links.append(f"example_id {example_id} not found among this inference run's decisions")
        return {**chain, "provenance_status": PROVENANCE_STATUS_INCOMPLETE, "missing_link": missing_links, "hash_mismatch": hash_mismatches}
    chain["decision"] = {
        "predicted_class": decision.get("predicted_class"), "final_decision": decision.get("final_decision"),
        "class_probability": decision.get("class_probability"),
    }

    # decision_window: never persisted anywhere today -- real, honest gap.
    missing_links.append("decision_window not persisted (run_decision_windows() output has no disk artifact today)")

    example = None
    example_capture_id = None
    for capture_id in inference_run.get("source_capture_ids", []):
        for candidate in repository._load_examples(capture_id):
            if candidate.example_id == example_id:
                example, example_capture_id = candidate, capture_id
                break
        if example is not None:
            break
    if example is None:
        missing_links.append(f"ExampleRecord for {example_id} not found among source_capture_ids' evidence")
        return {**chain, "provenance_status": PROVENANCE_STATUS_INCOMPLETE, "missing_link": missing_links, "hash_mismatch": hash_mismatches}

    chain["capture_id"] = example_capture_id
    chain["sample_start"] = example.iq_start_sample
    chain["sample_end"] = example.iq_end_sample
    chain["candidate_id"] = example.candidate_id
    chain["packet_id"] = example.packet_id
    chain["example_source_iq_sha256"] = example.source_iq_sha256

    capture = repository._load_capture(example_capture_id)
    if capture is None:
        missing_links.append(f"CaptureRecord {example_capture_id} not found")
    else:
        chain["capture_iq_sha256"] = capture.iq_sha256
        if example.source_iq_sha256 != capture.iq_sha256:
            hash_mismatches.append(f"ExampleRecord.source_iq_sha256 ({example.source_iq_sha256}) != CaptureRecord.iq_sha256 ({capture.iq_sha256})")
        recorded_at_inference = inference_run.get("source_iq_sha256_by_capture_id", {}).get(example_capture_id)
        if recorded_at_inference is not None and recorded_at_inference != capture.iq_sha256:
            hash_mismatches.append(f"inference_run's recorded source_iq_sha256 ({recorded_at_inference}) != current CaptureRecord.iq_sha256 ({capture.iq_sha256})")

    # Recovered PDU evidence -- real lookup in the real replay ledger,
    # keyed by packet_id/candidate_id (never guessed).
    pdu_evidence = _find_pdu_evidence(repository.legacy_capture_root, example_capture_id, example.packet_id, example.candidate_id)
    if pdu_evidence is None:
        missing_links.append(f"no packet_association_ledger.jsonl row found for packet_id={example.packet_id}")
    else:
        chain["recovered_pdu_evidence"] = {
            "pdu_type": pdu_evidence.get("pdu_type"), "packet_sha256": pdu_evidence.get("packet_sha256"),
            "advertiser_address_canonical": pdu_evidence.get("advertiser_address_canonical"),
            "association_strength": pdu_evidence.get("association_strength"),
        }

    # Dataset/split containing this example -- a real search over every
    # real dataset/split manifest on disk, never assumed from context.
    dataset_ref = _find_dataset_containing_example(repository.ble_root, example_id)
    if dataset_ref is None:
        missing_links.append("no DatasetManifest on disk contains this example_id")
    else:
        chain["dataset_id"], chain["dataset_version"], chain["dataset_manifest_sha256"] = dataset_ref

    split_ref = _find_split_containing_example(repository.ble_root, example_id)
    if split_ref is None:
        missing_links.append("no SplitManifest on disk contains this example_id")
    else:
        chain["scientific_task"], chain["split_manifest_sha256"] = split_ref

    # protocol_version/contract_sha256/git_sha: an inference run today
    # records no protocol linkage at all -- never substituted with
    # whatever protocol happens to be "current" (that could be a different,
    # later protocol than whichever was active when this decision was made).
    missing_links.append("inference_run records no protocol_id/protocol_version -- cannot link to a specific AnalysisContract")

    if hash_mismatches:
        status = PROVENANCE_STATUS_FAIL
    elif missing_links:
        status = PROVENANCE_STATUS_INCOMPLETE
    else:
        status = PROVENANCE_STATUS_COMPLETE
    return {**chain, "provenance_status": status, "missing_link": missing_links, "hash_mismatch": hash_mismatches}


def _find_pdu_evidence(legacy_capture_root: Path, capture_id: str, packet_id: str, candidate_id: str) -> dict[str, Any] | None:
    replays_dir = legacy_capture_root / capture_id / "offline_replays"
    if not replays_dir.is_dir():
        return None
    ledgers = sorted(replays_dir.glob("*/packet_association_ledger.jsonl"))
    for ledger_path in reversed(ledgers):  # most recent replay first
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("packet_id") == packet_id and row.get("candidate_id") == candidate_id:
                return row
    return None


def _find_dataset_containing_example(ble_root: Path, example_id: str) -> tuple[str, str, str] | None:
    datasets_dir = ble_root / "datasets"
    if not datasets_dir.is_dir():
        return None
    for path in sorted(datasets_dir.glob("*.json")):
        data = _read_json(path)
        if example_id in (data.get("example_ids") or []):
            return data.get("dataset_id"), data.get("dataset_version"), data.get("dataset_manifest_sha256")
    return None


def _find_split_containing_example(ble_root: Path, example_id: str) -> tuple[str, str] | None:
    splits_dir = ble_root / "splits"
    if not splits_dir.is_dir():
        return None
    for path in sorted(splits_dir.glob("*.json")):
        data = _read_json(path)
        assignments = data.get("assignments") or []
        if any(a.get("example_id") == example_id for a in assignments):
            return data.get("scientific_task"), data.get("split_manifest_sha256")
    return None


def list_inference_runs(repository: Any) -> list[dict[str, Any]]:
    inference_dir = repository.ble_root / "inference_runs"
    if not inference_dir.is_dir():
        return []
    summaries = []
    for path in sorted(inference_dir.glob("*.json")):
        data = _read_json(path)
        summaries.append({
            "inference_run_id": data.get("inference_run_id"), "bundle_id": data.get("bundle_id"),
            "prediction_count": data.get("prediction_count"), "created_at": data.get("created_at"),
            "example_ids": [d.get("example_id") for d in data.get("decisions", [])],
        })
    return summaries
