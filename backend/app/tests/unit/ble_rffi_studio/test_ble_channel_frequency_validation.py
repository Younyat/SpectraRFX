"""P0.5 correction (2026-08-08): validate_ble_channel_matches_frequency() is
the blocking guard between a declared BLE advertising channel and a
capture's real center_frequency_hz. The real bug it closes: 6 real
SYNTHETIC_TEST_ONLY captures (72 examples) on disk had channel=37 stamped
alongside center_frequency_hz=2476000000 -- not a real BLE advertising
frequency at all -- because evidence-building used a fixed default
ble_channel=37 regardless of what frequency a capture was actually tuned to,
and synthetic_demo_seeder.py computed that frequency with a formula
(2402 MHz + channel_index * 2 MHz) that is only valid for BLE DATA channels,
not the three advertising channels. These tests exercise the guard directly,
independent of any real-capture fixture."""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.evidence.evidence_stage import BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ, validate_ble_channel_matches_frequency


@pytest.mark.parametrize("channel,frequency_hz", list(BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ.items()))
def test_accepts_every_real_advertising_channel_at_its_real_frequency(channel, frequency_hz):
    validate_ble_channel_matches_frequency(channel, frequency_hz, capture_id="CAP-1")  # must not raise


def test_rejects_channel_37_with_the_exact_real_bug_frequency():
    with pytest.raises(ValueError, match="BLE_CHANNEL_FREQUENCY_MISMATCH"):
        validate_ble_channel_matches_frequency(37, 2_476_000_000, capture_id="CAP-1")


def test_rejects_a_channel_number_that_is_not_a_real_advertising_channel():
    with pytest.raises(ValueError, match="BLE_CHANNEL_FREQUENCY_MISMATCH"):
        validate_ble_channel_matches_frequency(0, 2_404_000_000, capture_id="CAP-1")


def test_tolerates_small_real_hardware_tuning_drift():
    validate_ble_channel_matches_frequency(37, 2_402_000_000 + 500_000, capture_id="CAP-1")  # 0.5 MHz drift, well within tolerance


def test_rejects_drift_beyond_the_blocking_tolerance():
    with pytest.raises(ValueError, match="BLE_CHANNEL_FREQUENCY_MISMATCH"):
        validate_ble_channel_matches_frequency(37, 2_402_000_000 + 2_000_000, capture_id="CAP-1")
