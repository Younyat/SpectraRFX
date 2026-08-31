from __future__ import annotations

async def get_current_settings():
    return {
        "center_frequency_hz": 1_000_000_000,
        "span_hz": 10_000_000,
        "gain_db": 20.0,
    }


def get_device_controller():
    return get_container().device_controller


def get_spectrum_controller():
    return get_container().spectrum_controller


def get_marker_controller():
    return get_container().marker_controller


def get_recording_controller():
    return get_container().recording_controller


def get_demodulation_controller():
    return get_container().demodulation_controller


def get_preset_controller():
    return get_container().preset_controller


def get_create_session_use_case():
    return get_container().create_session_use_case


def get_active_device_state():
    container = get_container()
    return container.device_manager.get_device_state()