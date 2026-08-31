"""Exposes ble_lab's already-constructed capture/native/hybrid managers to
other modules (specifically ble_rffi_studio's real capture campaign
orchestrator) so a second module never constructs a COMPETING
BleCaptureJobManager/BleHybridCampaignManager against the same USRP B200 --
each of those managers has its own in-process exclusivity lock, and two
separate instances would have no way to see each other's lock.

ble_lab is registered with a lower `order` than ble_rffi_studio in
app/modules/registry.py, so its _build() always runs first and populates
this module-level singleton before ble_rffi_studio's _build() reads it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SharedBleManagers:
    capture_manager: Any
    native_manager: Any
    hybrid_manager: Any


_shared: SharedBleManagers | None = None


def set_shared_managers(capture_manager: Any, native_manager: Any, hybrid_manager: Any) -> None:
    global _shared
    _shared = SharedBleManagers(capture_manager=capture_manager, native_manager=native_manager, hybrid_manager=hybrid_manager)


def get_shared_managers() -> SharedBleManagers | None:
    return _shared
