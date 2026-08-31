"""Live status reader for the separate, external Gate 2A.2 DSP/IQ-recovery
development effort (C:\\Users\\Usuario\\ble-worker-lab). This is NOT the frozen
Gate 1B replay pipeline (ble_contracts.py/ble_job_manager.py) -- Gate 2A.2 is
still in development and must never be reported as approved, frozen, or
validated. Reads whatever ble-worker-lab's own artifacts currently say rather
than a hand-maintained snapshot, so this can never drift out of sync with the
real repository the way a manually copied summary could."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = Path(r"C:\Users\Usuario\ble-worker-lab")


def _repository() -> Path:
    return Path(os.environ.get("BLE_GATE2A2_REPOSITORY", str(DEFAULT_REPOSITORY)))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return None
        value = json.loads(raw.decode("utf-8-sig"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _read_reconciliation(path: Path) -> dict[str, Any] | None:
    value = _read_json(path)
    if not value or value.get("schema_version") != "ble-gate2a2-development-reconciliation-v1":
        return None
    required = {
        "reported_results", "discrepancy_resolved", "best_development_result_policy_id",
        "latest_execution_policy_id", "active_development_policy_id",
        "authoritative_gate_status", "frozen_candidate",
    }
    if not required.issubset(value) or not isinstance(value["reported_results"], list):
        return None
    if value["authoritative_gate_status"] != "in_progress" or value["frozen_candidate"] is not None:
        return None
    if value.get("iq_recovery_validated") not in (None, False) or value.get("ota_validated") not in (None, False):
        return None
    for result in value["reported_results"]:
        if not isinstance(result, dict) or not {
            "policy_id", "configuration_sha256", "source_artifact", "cases_total",
            "cases_passed", "failed_case_ids", "receiver_commit",
        }.issubset(result):
            return None
        total, passed = result["cases_total"], result["cases_passed"]
        if not isinstance(total, int) or isinstance(total, bool) or not isinstance(passed, int) or isinstance(passed, bool):
            return None
        if total < 0 or passed < 0 or passed > total:
            return None
    policies = [result["policy_id"] for result in value["reported_results"]]
    if len(policies) != len(set(policies)):
        return None
    for key in ("best_development_result_policy_id", "latest_execution_policy_id", "active_development_policy_id"):
        if value[key] not in policies:
            return None
    return value


def _result_for_policy(reconciliation: dict[str, Any], policy_id: str) -> dict[str, Any] | None:
    return next((item for item in reconciliation["reported_results"] if item["policy_id"] == policy_id), None)


def _git_head(repository: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repository}", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def gate2a2_status() -> dict[str, Any]:
    repository = _repository()
    artifacts = repository / "artifacts" / "gate2a_2"
    if not repository.is_dir() or not artifacts.is_dir():
        return {"available": False, "reason": "gate2a2_repository_unavailable"}

    status = _read_json(artifacts / "gate2a_2_status.json") or {}
    campaign = _read_json(artifacts / "development_campaign_report.json") or {}
    candidate = _read_json(artifacts / "receiver_candidate_manifest.json") or {}
    reconciliation = _read_reconciliation(artifacts / "development_result_reconciliation.json")

    counts = campaign.get("counts", {})
    cases = counts.get("cases")
    byte_exact = counts.get("byte_exact")
    residual_failures = (cases - byte_exact) if isinstance(cases, int) and isinstance(byte_exact, int) else None

    resolved: dict[str, Any] = {}
    if reconciliation:
        resolved = {
            "development_discrepancy_resolved": reconciliation["discrepancy_resolved"],
            "best_development_result": _result_for_policy(
                reconciliation, reconciliation["best_development_result_policy_id"]
            ),
            "latest_execution": _result_for_policy(
                reconciliation, reconciliation["latest_execution_policy_id"]
            ),
            "active_development_policy": reconciliation["active_development_policy_id"],
            "authoritative_gate_status": reconciliation["authoritative_gate_status"],
            "frozen_candidate": reconciliation["frozen_candidate"],
        }

    return {
        "available": True,
        "gate": status.get("gate", "Gate 2A.2"),
        "gate_2a1_status": "passed",
        "gate_2a2_status": status.get("status", "in_progress"),
        "dsp_gate": status.get("dsp_gate", "in_progress"),
        # This checkpoint is development code, not Receiver Candidate B.
        # Candidate B does not exist until an explicit freeze commit does.
        "receiver_candidate": None,
        "candidate_frozen": False,
        "frozen_candidate": None,
        "authoritative_gate_status": "in_progress",
        "development_timing_sweep": {
            "cases": cases,
            "byte_exact": byte_exact,
            "result": campaign.get("result"),
            "holdout_eligible": campaign.get("holdout_eligible"),
        },
        "residual_failures": residual_failures,
        # Holdout B (the independent evaluation that may only run after
        # Candidate B is frozen) has no artifact in this repository -- it does
        # not exist yet, by design. The ideal/CFO/timing/SNR holdouts recorded
        # in gate2a_2_status.json are earlier, in-development evaluations, not
        # Holdout B, and must not be reported as if they were.
        "holdout_b_created": False,
        "iq_recovery_validated": status.get("iq_recovery_validated", False),
        "ota_validated": status.get("ota_validated", False),
        "worker_repository_commit": _git_head(repository),
        "receiver_commit": candidate.get("receiver_commit"),
        "frozen_bitstream_commit": candidate.get("frozen_bitstream_commit"),
        "disabled_reason": (
            "Receiver Candidate B is not frozen and OTA validation has not been completed."
        ),
        "reconciliation_artifact": {
            "valid": reconciliation is not None,
            "error": None if reconciliation is not None else "invalid_or_unavailable",
        },
        **resolved,
    }
