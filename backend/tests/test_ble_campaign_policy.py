import pytest
from pathlib import Path

from app.infrastructure.ble.ble_hybrid_campaign_manager import BleHybridCampaignManager
from app.infrastructure.ble.campaign_policy import (
    EXPLORATORY_TARGET_SEARCH,
    contract_from_session,
    validate_campaign_contract,
)


TARGET_HISTORY={"kind":"device","address":"BC:6A:29:AB:DE:13","selection_source":"native_registry_history"}
TARGET_NOW={"kind":"device","address":"BC:6A:29:AB:DE:13","selection_source":"native_current_scan"}


def test_campaign_intent_is_required():
    with pytest.raises(ValueError,match="CAMPAIGN_INTENT_REQUIRED"):
        validate_campaign_contract({},TARGET_HISTORY)


def test_positive_validation_requires_seen_now():
    with pytest.raises(ValueError,match="POSITIVE_TARGET_REQUIRES_SEEN_NOW"):
        validate_campaign_contract({"campaign_intent":"positive_target_validation"},TARGET_HISTORY)
    contract=validate_campaign_contract({"campaign_intent":"positive_target_validation"},TARGET_NOW)
    assert contract["target_seen_before_start"] is True


def test_negative_control_requires_declaration_and_confirmation():
    with pytest.raises(ValueError,match="NEGATIVE_CONTROL_DECLARATION_REQUIRED"):
        validate_campaign_contract({"campaign_intent":"negative_control"},TARGET_HISTORY)
    with pytest.raises(ValueError,match="NEGATIVE_CONTROL_OPERATOR_CONFIRMATION_REQUIRED"):
        validate_campaign_contract({"campaign_intent":"negative_control","negative_control_type":"target_powered_off"},TARGET_HISTORY)
    contract=validate_campaign_contract({"campaign_intent":"negative_control","negative_control_type":"target_powered_off","operator_confirmation":True},TARGET_HISTORY)
    assert contract["negative_control_type"]=="target_powered_off" and contract["operator_confirmation"] is True


def test_legacy_session_is_conservatively_exploratory():
    contract=contract_from_session({"target_selection_source":"native_registry_history"})
    assert contract["campaign_intent"]==EXPLORATORY_TARGET_SEARCH
    assert contract["legacy_intent_inferred"] is True


def test_persisted_uppercase_negative_contract_is_normalized():
    contract=contract_from_session({
        "campaign_intent":"NEGATIVE_CONTROL",
        "negative_control_type":"TARGET_POWERED_OFF",
        "operator_confirmation":True,
    })
    assert contract["campaign_intent"]=="negative_control"
    assert contract["negative_control_type"]=="target_powered_off"
    assert contract["operator_confirmation"] is True


def test_new_hybrid_campaign_requires_complete_experimental_metadata(tmp_path):
    manager=BleHybridCampaignManager(tmp_path/"sessions",object(),object(),Path("python"),Path("decoder"),Path("correlator"),tmp_path)
    with pytest.raises(ValueError,match="EXPERIMENTAL_METADATA_REQUIRED"):
        manager.start({"device_id":"b200","channel":37,"duration_seconds":30,"target":TARGET_NOW,"campaign_intent":"positive_target_validation"})
