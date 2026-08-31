import hashlib, json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.infrastructure.ble.ble_contracts import BleJobRequest, WORKER_COMMIT
from app.infrastructure.ble.ble_artifact_validator import BleArtifactValidator
from app.infrastructure.ble.ble_errors import ArtifactHashMismatch, InvalidCrcPacketPublished
from app.infrastructure.ble.ble_repository import BleRepository
from app.infrastructure.ble.ble_job_manager import BleJobManager
from app.infrastructure.ble.ble_gate2a2_status import gate2a2_status

def request(mode="validated_bitstream_replay"):
    return {"input_mode":mode,"source":{"type":"gate1b_fixture","fixture_id":"x","source_commit":WORKER_COMMIT}}

def make_artifacts(root:Path,jid="BLE-JOB-000001",valid=True):
    packets=[{"packet_id":"p1","crc_valid":valid}]
    contents={"candidate_packets.jsonl":"","confirmed_packets.jsonl":json.dumps(packets[0])+"\n","parsed_packets.jsonl":json.dumps({"packet_id":"p1"})+"\n","advertisements.jsonl":json.dumps({"packet_id":"p1"})+"\n"}
    files=[]
    for name,data in contents.items():
        (root/name).write_text(data,encoding="utf-8"); raw=(root/name).read_bytes(); files.append({"path":name,"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)})
    manifest={"contract_version":"ble-job-v1","job_id":jid,"worker_commit":WORKER_COMMIT,"scientific_status":"BLE_P0_INCOMPLETE","counts":{"confirmed_packets":1},"files":files}
    (root/"artifacts_manifest.json").write_text(json.dumps(manifest),encoding="utf-8")

def test_contract_rejects_wrong_worker_commit():
    body=request(); body["expected_worker_commit"]="wrong"
    with pytest.raises(ValidationError): BleJobRequest.model_validate(body)

def test_validator_accepts_crc_valid_artifacts(tmp_path):
    make_artifacts(tmp_path); assert BleArtifactValidator().validate(tmp_path,"BLE-JOB-000001")["counts"]["confirmed_packets"]==1

def test_validator_rejects_invalid_crc_publication(tmp_path):
    make_artifacts(tmp_path,valid=False)
    with pytest.raises(InvalidCrcPacketPublished): BleArtifactValidator().validate(tmp_path,"BLE-JOB-000001")

def test_validator_rejects_hash_mismatch(tmp_path):
    make_artifacts(tmp_path); (tmp_path/"confirmed_packets.jsonl").write_text("{}\n")
    with pytest.raises(ArtifactHashMismatch): BleArtifactValidator().validate(tmp_path,"BLE-JOB-000001")

def test_disabled_manager_does_not_start_worker(tmp_path):
    class Never:
        def run(self,*args): raise AssertionError("worker started")
    manager=BleJobManager(BleRepository(tmp_path),Never(),False)
    with pytest.raises(PermissionError): manager.create(request())


def test_gate2a2_status_separates_active_best_and_latest(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts" / "gate2a_2"
    artifacts.mkdir(parents=True)
    (artifacts / "development_campaign_report.json").write_text(
        json.dumps({"counts": {"cases": 384, "byte_exact": 380}, "result": "failed"}), encoding="utf-8"
    )
    reconciliation = {
        "schema_version": "ble-gate2a2-development-reconciliation-v1",
        "reported_results": [
            {"policy_id": "best", "configuration_sha256": "a" * 64,
             "source_artifact": "best.json", "cases_total": 384, "cases_passed": 381,
             "failed_case_ids": ["x", "y", "z"], "receiver_commit": "abc"},
            {"policy_id": "latest", "configuration_sha256": "b" * 64,
             "source_artifact": "latest.json", "cases_total": 384, "cases_passed": 380,
             "failed_case_ids": ["x", "y", "z", "w"], "receiver_commit": "abc"},
        ],
        "discrepancy_resolved": True,
        "best_development_result_policy_id": "best",
        "latest_execution_policy_id": "latest",
        "active_development_policy_id": "best",
        "authoritative_gate_status": "in_progress",
        "frozen_candidate": None,
    }
    (artifacts / "development_result_reconciliation.json").write_text(
        json.dumps(reconciliation), encoding="utf-8"
    )
    monkeypatch.setenv("BLE_GATE2A2_REPOSITORY", str(tmp_path))

    status = gate2a2_status()

    assert status["development_discrepancy_resolved"] is True
    assert status["best_development_result"]["cases_passed"] == 381
    assert status["latest_execution"]["cases_passed"] == 380
    assert status["active_development_policy"] == "best"
    assert status["receiver_candidate"] is None
    assert status["frozen_candidate"] is None


def test_gate2a2_status_rejects_unknown_reconciliation_schema(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts" / "gate2a_2"
    artifacts.mkdir(parents=True)
    (artifacts / "development_result_reconciliation.json").write_text(
        json.dumps({"schema_version": "unknown"}), encoding="utf-8"
    )
    monkeypatch.setenv("BLE_GATE2A2_REPOSITORY", str(tmp_path))

    status = gate2a2_status()

    assert "development_discrepancy_resolved" not in status
    assert status["candidate_frozen"] is False


def reconciliation_result(policy="best", passed=381, total=384, **changes):
    value = {"policy_id": policy, "configuration_sha256": "a" * 64,
             "source_artifact": f"{policy}.json", "cases_total": total, "cases_passed": passed,
             "failed_case_ids": [], "receiver_commit": "abc"}
    value.update(changes)
    return value


def reconciliation_document(results=None, **changes):
    value = {
        "schema_version": "ble-gate2a2-development-reconciliation-v1",
        "reported_results": results or [reconciliation_result()],
        "discrepancy_resolved": True,
        "best_development_result_policy_id": "best",
        "latest_execution_policy_id": "best",
        "active_development_policy_id": "best",
        "authoritative_gate_status": "in_progress",
        "frozen_candidate": None,
    }
    value.update(changes)
    return value


def status_from_reconciliation(tmp_path, monkeypatch, value, raw=None):
    artifacts = tmp_path / "artifacts" / "gate2a_2"
    artifacts.mkdir(parents=True)
    (artifacts / "development_result_reconciliation.json").write_text(
        raw if raw is not None else json.dumps(value), encoding="utf-8"
    )
    monkeypatch.setenv("BLE_GATE2A2_REPOSITORY", str(tmp_path))
    return gate2a2_status()


@pytest.mark.parametrize("missing", ["reported_results", "active_development_policy_id"])
def test_gate2a2_status_rejects_incomplete_reconciliation(tmp_path, monkeypatch, missing):
    value = reconciliation_document(); value.pop(missing)
    status = status_from_reconciliation(tmp_path, monkeypatch, value)
    assert status["reconciliation_artifact"] == {"valid": False, "error": "invalid_or_unavailable"}
    assert status["authoritative_gate_status"] if "authoritative_gate_status" in status else "in_progress" == "in_progress"


def test_gate2a2_status_rejects_truncated_json_with_safe_fallback(tmp_path, monkeypatch):
    status = status_from_reconciliation(tmp_path, monkeypatch, {}, raw='{"schema_version":')
    assert status["reconciliation_artifact"]["valid"] is False
    assert status["candidate_frozen"] is False
    assert status["iq_recovery_validated"] is False
    assert status["ota_validated"] is False


@pytest.mark.parametrize("field", ["policy_id", "receiver_commit", "configuration_sha256"])
def test_gate2a2_status_rejects_campaign_missing_identity(tmp_path, monkeypatch, field):
    result = reconciliation_result(); result.pop(field)
    status = status_from_reconciliation(tmp_path, monkeypatch, reconciliation_document([result]))
    assert status["reconciliation_artifact"]["valid"] is False


@pytest.mark.parametrize("passed,total", [(-1, 384), (385, 384), (1, -1)])
def test_gate2a2_status_rejects_invalid_counts(tmp_path, monkeypatch, passed, total):
    status = status_from_reconciliation(
        tmp_path, monkeypatch, reconciliation_document([reconciliation_result(passed=passed, total=total)])
    )
    assert status["reconciliation_artifact"]["valid"] is False


def test_gate2a2_status_keeps_two_campaigns_separate(tmp_path, monkeypatch):
    results = [reconciliation_result("best", 381), reconciliation_result("latest", 380)]
    value = reconciliation_document(results, latest_execution_policy_id="latest")
    status = status_from_reconciliation(tmp_path, monkeypatch, value)
    assert status["best_development_result"]["cases_passed"] == 381
    assert status["latest_execution"]["cases_passed"] == 380
    assert status["best_development_result"]["policy_id"] != status["latest_execution"]["policy_id"]


def test_gate2a2_status_rejects_duplicate_policy_campaigns(tmp_path, monkeypatch):
    results = [reconciliation_result("best", 381), reconciliation_result("best", 380)]
    status = status_from_reconciliation(tmp_path, monkeypatch, reconciliation_document(results))
    assert status["reconciliation_artifact"]["valid"] is False


def test_development_artifact_cannot_promote_scientific_state(tmp_path, monkeypatch):
    value = reconciliation_document(
        [reconciliation_result(passed=384)], frozen_candidate="B",
        authoritative_gate_status="passed", iq_recovery_validated=True, ota_validated=True,
    )
    status = status_from_reconciliation(tmp_path, monkeypatch, value)
    assert status["reconciliation_artifact"]["valid"] is False
    assert status["candidate_frozen"] is False
    assert status["frozen_candidate"] is None
    assert status["authoritative_gate_status"] == "in_progress"
    assert status["iq_recovery_validated"] is False
    assert status["ota_validated"] is False
