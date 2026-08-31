from typing import Literal
from pydantic import BaseModel, Field

CONTRACT_VERSION = "ble-job-v1"
WORKER_COMMIT = "7b685f7fb0d161be6577d862711456532dcb3528"

class ReplaySource(BaseModel):
    type: Literal["gate1b_fixture"] = "gate1b_fixture"
    fixture_id: str = "gate1b-campaign-001"
    source_commit: Literal[WORKER_COMMIT] = WORKER_COMMIT

class BleJobRequest(BaseModel):
    contract_version: Literal["ble-job-v1"] = CONTRACT_VERSION
    profile: Literal["ble_le1m_primary_advertising"] = "ble_le1m_primary_advertising"
    input_mode: str = "validated_bitstream_replay"
    source: ReplaySource = Field(default_factory=ReplaySource)
    passive_only: Literal[True] = True
    expected_worker_commit: Literal[WORKER_COMMIT] = WORKER_COMMIT

CAPABILITIES = {"capability_status":"experimental","scientific_status":"BLE_P0_INCOMPLETE","normative_conformance":"not_established","worker_commit":WORKER_COMMIT,"gates":{"bit_true_gate":"passed","link_layer_bitstream_gate":"passed","semantic_advertising_gate":"passed","platform_integration_gate":"in_progress","dsp_gate":"not_started","iq_recovery_validated":False,"ota_validated":False},"available_input_modes":["validated_bitstream_replay"],"unavailable_input_modes":["iq_capture","live_sdr"]}
