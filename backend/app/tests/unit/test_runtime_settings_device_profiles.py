"""Device profiles are pure bundles over the existing runtime settings
mechanism (UHD_DEVICE_ARGS/DEFAULT_ANTENNA/RF_* limits) -- applying one must
be exactly equivalent to hand-typing every one of its values via
save_runtime_values(), never a second, parallel config path.
"""
from __future__ import annotations

import pytest

from app.config import runtime_settings


@pytest.fixture(autouse=True)
def isolated_runtime_settings_path(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", tmp_path / "runtime_settings.json")
    # merged_runtime_values() also falls through to real os.environ for any
    # key with no saved value -- some other test in the full suite calls
    # apply_runtime_environment() (os.environ.setdefault(...)), which is
    # process-wide and outlives that test. Clear every key either profile
    # touches so this file's assertions hold regardless of run order.
    for profile in runtime_settings.DEVICE_PROFILES.values():
        for key in profile["values"]:
            monkeypatch.delenv(key, raising=False)


def test_device_profiles_payload_lists_both_real_profiles():
    payload = runtime_settings.device_profiles_payload()
    ids = [p["id"] for p in payload["profiles"]]
    assert ids == ["usrp_b200", "ni_usrp_2932"]


def test_no_profile_active_before_any_is_applied():
    # The as-shipped defaults (b200 numbers) happen to already match the
    # b200 profile's own values -- confirm that surfaces as active, not None.
    payload = runtime_settings.device_profiles_payload()
    assert payload["active_profile_id"] == "usrp_b200"


def test_apply_device_profile_writes_every_one_of_its_values():
    runtime_settings.apply_device_profile("ni_usrp_2932")
    saved = runtime_settings.load_runtime_values()
    expected = runtime_settings.DEVICE_PROFILES["ni_usrp_2932"]["values"]
    for key, value in expected.items():
        assert saved[key] == value


def test_applying_a_profile_also_updates_the_human_readable_device_name():
    # Regression: RF_SAFETY_DEVICE_NAME used to be a raw os.environ read
    # outside this settings system entirely -- switching profiles left the
    # OLD device's name showing in /api/device/status forever.
    runtime_settings.apply_device_profile("ni_usrp_2932")
    saved = runtime_settings.load_runtime_values()
    assert "2932" in saved["RF_SAFETY_DEVICE_NAME"]


def test_apply_device_profile_is_reported_as_active_afterwards():
    runtime_settings.apply_device_profile("ni_usrp_2932")
    payload = runtime_settings.device_profiles_payload()
    assert payload["active_profile_id"] == "ni_usrp_2932"


def test_switching_back_to_b200_profile_restores_its_own_values():
    runtime_settings.apply_device_profile("ni_usrp_2932")
    runtime_settings.apply_device_profile("usrp_b200")
    saved = runtime_settings.load_runtime_values()
    expected = runtime_settings.DEVICE_PROFILES["usrp_b200"]["values"]
    for key, value in expected.items():
        assert saved[key] == value
    assert runtime_settings.device_profiles_payload()["active_profile_id"] == "usrp_b200"


def test_unknown_profile_id_fails_closed():
    with pytest.raises(ValueError, match="Unknown device profile"):
        runtime_settings.apply_device_profile("does-not-exist")


def test_ni_usrp_2932_profile_never_exceeds_what_gigabit_ethernet_can_sustain():
    # Real math, not a guess: UHD's sc16 wire format is 4 bytes/complex
    # sample; Gigabit Ethernet sustains roughly 112-117 MB/s in practice.
    # This is a regression guard against silently raising the cap back to
    # the device's own DSP ceiling (50 MS/s), which drops packets over 1GbE.
    values = runtime_settings.DEVICE_PROFILES["ni_usrp_2932"]["values"]
    bytes_per_second = values["RF_MAX_SAMPLE_RATE_HZ"] * 4
    assert bytes_per_second < 117_000_000
