from __future__ import annotations

from app.modules.ble_scientific_results.api import ScientificResultsRepository


def _payload(**overrides) -> dict:
    payload = dict(
        protocol_id="PAPER-PROTO", hardware_profile_id="usrp-b200-e3r04z1b2", receiver_profile_hash="rx-profile-hash",
        interpretation_matrix_hash="interp-hash-v1", device_population={"same_model_enrolled": 5},
    )
    payload.update(overrides)
    return payload


def test_freezing_twice_creates_a_new_version_never_overwrites(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")

    first = repository.freeze_protocol(_payload())
    assert first.protocol_version == 1

    second = repository.freeze_protocol(_payload(random_seeds=[1, 2, 3]))
    assert second.protocol_version == 2
    assert second.protocol_id == first.protocol_id

    # The first version's own file is untouched.
    reloaded_first = repository.get_protocol(first.protocol_id, 1)
    assert reloaded_first.random_seeds == []
    assert reloaded_first.content_hash() == first.content_hash()

    versions = repository.list_protocol_versions(first.protocol_id)
    assert [v.protocol_version for v in versions] == [1, 2]


def test_freeze_requires_hardware_and_interpretation_fields(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    payload = _payload()
    del payload["hardware_profile_id"]
    try:
        repository.freeze_protocol(payload)
        assert False, "expected ValueError for missing required field"
    except ValueError as error:
        assert "hardware_profile_id" in str(error)


def _log_access(repository, *, actor, access_path, protocol_id):
    return repository.log_holdout_access(
        actor=actor, process="pytest", access_type="READ", access_path=access_path, resource_id=access_path,
        resource_hash=None, reason="unit test access", paper_run_id=None, analysis_contract_hash=protocol_id,
    )


def test_holdout_access_is_logged_append_only(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_payload())

    _log_access(repository, actor="operator1", access_path="future_holdout/CH38", protocol_id=contract.protocol_id)
    _log_access(repository, actor="operator2", access_path="future_holdout/CH39", protocol_id=contract.protocol_id)

    entries = repository.list_holdout_access_log()
    assert len(entries) == 2
    assert entries[0].actor == "operator1"
    assert entries[1].actor == "operator2"
    assert entries[0].sequence_number == 1
    assert entries[1].sequence_number == 2
    assert entries[0].previous_entry_hash is None
    assert entries[1].previous_entry_hash == entries[0].entry_hash
    assert all(entry.analysis_contract_hash == contract.protocol_id for entry in entries)


def test_holdout_access_chain_verifies_intact_and_detects_tampering(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_payload())

    for i in range(4):
        _log_access(repository, actor=f"operator{i}", access_path=f"future_holdout/item-{i}", protocol_id=contract.protocol_id)

    intact = repository.verify_holdout_access_chain()
    assert intact.status == "VALID"
    assert intact.entry_count == 4
    assert intact.broken_at_sequence is None

    # Tamper directly with the .jsonl -- modify entry #3's reason without
    # updating its entry_hash, simulating a direct filesystem edit outside
    # log_holdout_access().
    log_path = repository._holdout_log_path()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    import json
    tampered = json.loads(lines[2])
    tampered["reason"] = "tampered reason"
    lines[2] = json.dumps(tampered, sort_keys=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    broken = repository.verify_holdout_access_chain()
    assert broken.status == "BROKEN"
    assert broken.broken_at_sequence == 3
    assert broken.findings


def test_holdout_access_chain_detects_deleted_entry(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_payload())
    for i in range(3):
        _log_access(repository, actor=f"operator{i}", access_path=f"future_holdout/item-{i}", protocol_id=contract.protocol_id)

    log_path = repository._holdout_log_path()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # remove the middle entry (sequence_number=2)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = repository.verify_holdout_access_chain()
    assert result.status == "BROKEN"
    assert result.broken_at_sequence == 3  # the next surviving entry now has the wrong sequence_number/previous_entry_hash
