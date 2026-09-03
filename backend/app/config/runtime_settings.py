from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


def _storage_root() -> Path:
    return Path(__file__).resolve().parents[1] / "infrastructure" / "persistence" / "storage"


RUNTIME_SETTINGS_PATH = _storage_root() / "config" / "runtime_settings.json"


SETTING_CATALOG: dict[str, dict[str, Any]] = {
    "RADIOCONDA_PYTHON": {
        "section": "Runtime",
        "tab": "Startup / all SDR workers",
        "type": "string",
        "default": r"C:\Users\Usuario\radioconda\python.exe",
        "description": "Python executable used to run GNU Radio and UHD helper scripts.",
        "impact": "Affects live spectrum, capture, demodulation and device probes. Wrong path disables real SDR operations.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "high",
    },
    "RF_SAFETY_DEVICE_NAME": {
        "section": "Hardware",
        "tab": "Device, Live Spectrum, Capture Lab, Demodulation",
        "type": "string",
        "default": "USRP-B200 from Ettus Research",
        "description": "Human-readable name of the connected device, shown in /api/device/status's safety_limits and the Settings page.",
        "impact": "Display only -- never affects what UHD_DEVICE_ARGS actually connects to. Was previously a raw environment variable outside this settings system (a real bug: switching device profiles silently left the old device's name showing).",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "UHD_DEVICE_ARGS": {
        "section": "Hardware",
        "tab": "Device, Live Spectrum, Capture Lab, Demodulation",
        "type": "string",
        "default": "",
        "description": "UHD device selector. Examples: serial=XXXXXXXX or addr=192.168.10.2.",
        "impact": "Controls which USRP is opened. Empty means UHD auto-discovery.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "DEFAULT_ANTENNA": {
        "section": "Hardware",
        "tab": "Device, Live Spectrum, Capture Lab, Demodulation",
        "type": "string",
        "default": "RX2",
        "description": "Default receive antenna port passed to UHD workers.",
        "impact": "Wrong antenna can produce no signal or much lower SNR.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "medium",
    },
    "DEFAULT_CENTER_FREQUENCY_HZ": {
        "section": "Hardware defaults",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 89_400_000.0,
        "min": 70_000_000.0,
        "max": 6_000_000_000.0,
        "unit": "Hz",
        "description": "Center frequency applied when the backend starts.",
        "impact": "Only sets startup tuning. Live controls can still retune during a session.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "medium",
    },
    "DEFAULT_SAMPLE_RATE_HZ": {
        "section": "Hardware defaults",
        "tab": "Live Spectrum, Capture Lab",
        "type": "number",
        # 4 MSps: matches ble-worker-lab's hardcoded INTERNAL_SAMPLE_RATE_HZ
        # requirement (BLE Gate 2A.2 decode fails silently at any other rate
        # -- see real_spectrum_stream.py's SAMPLE_RATE_MISMATCH check), and
        # gives WiFi/Zigbee/other 2.4 GHz protocol work the same
        # out-of-the-box acquisition bandwidth. Independent of DEFAULT_SPAN_HZ
        # (the displayed/analyzed window) -- see spectrum_stream_worker.py.
        "default": 4_000_000.0,
        "min": 200_000.0,
        "max": 61_440_000.0,
        "unit": "samples/s",
        "description": "Default real ADC/USRP acquisition rate at backend startup, independent of the displayed span.",
        "impact": "Higher rates increase USB load, CPU load and file size. Hardware may fail before the configured maximum on weak USB controllers.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "DEFAULT_GAIN_DB": {
        "section": "Hardware defaults",
        "tab": "Live Spectrum, Capture Lab, Demodulation",
        "type": "number",
        "default": 20.0,
        "min": 0.0,
        "max": 60.0,
        "unit": "dB",
        "description": "Default manual RF gain.",
        "impact": "Too low reduces SNR. Too high can clip or saturate the receiver.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "DEFAULT_SPAN_HZ": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum",
        "type": "number",
        # Independent of DEFAULT_SAMPLE_RATE_HZ (the real acquisition rate)
        # -- this is only how much of that acquired bandwidth is displayed.
        # Defaulted to match so default visual behavior is the full
        # acquisition bandwidth unless narrowed deliberately.
        "default": 4_000_000.0,
        "min": 1_000.0,
        "max": 61_440_000.0,
        "unit": "Hz",
        "description": "Initial spectrum span (display window) shown after backend startup. Cannot exceed DEFAULT_SAMPLE_RATE_HZ.",
        "impact": "Wider span shows more of the acquired spectrum. Does not by itself require a higher sample rate -- set that independently.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "medium",
    },
    "DEFAULT_RBW_HZ": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 10_000.0,
        "min": 1.0,
        "max": 1_000_000.0,
        "unit": "Hz",
        "description": "Initial resolution bandwidth.",
        "impact": "Lower RBW gives more detail but more processing cost. Higher RBW hides narrow signals.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "DEFAULT_VBW_HZ": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 3_000.0,
        "min": 1.0,
        "max": 1_000_000.0,
        "unit": "Hz",
        "description": "Initial video bandwidth for trace smoothing.",
        "impact": "Lower VBW smooths more; higher VBW reacts faster to changes.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "DEFAULT_REFERENCE_LEVEL_DB": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 10.0,
        "min": -120.0,
        "max": 60.0,
        "unit": "dB",
        "description": "Initial top reference level for spectrum display.",
        "impact": "Display scaling only; it does not change RF gain or the saved IQ samples.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "DEFAULT_NOISE_FLOOR_OFFSET_DB": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum, RF Intelligence",
        "type": "number",
        "default": 0.0,
        "min": -40.0,
        "max": 40.0,
        "unit": "dB",
        "description": "Display and analysis offset added to the estimated noise floor.",
        "impact": "Changing it can move visual thresholds and RF object detection sensitivity.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "DEFAULT_AVERAGING_FACTOR": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 0.2,
        "min": 0.0,
        "max": 1.0,
        "unit": "ratio",
        "description": "Initial trace averaging factor.",
        "impact": "Higher values stabilize the trace but react more slowly.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "DEFAULT_SMOOTHING_FACTOR": {
        "section": "Spectrum defaults",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 0.15,
        "min": 0.0,
        "max": 1.0,
        "unit": "ratio",
        "description": "Initial smoothing factor for displayed spectrum traces.",
        "impact": "Higher values make the UI smoother but can hide fast bursts.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "DEFAULT_WATERFALL_HISTORY_SIZE": {
        "section": "Waterfall defaults",
        "tab": "Waterfall",
        "type": "number",
        "default": 400,
        "min": 20,
        "max": 5_000,
        "unit": "rows",
        "description": "Number of historical rows kept by the waterfall view.",
        "impact": "Higher values keep more history but use more browser memory.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "DEFAULT_RECORDING_DURATION_SECONDS": {
        "section": "Recording defaults",
        "tab": "Recording, Capture Lab, Dataset Builder",
        "type": "number",
        "default": 10.0,
        "min": 0.1,
        "max": 3_600.0,
        "unit": "s",
        "description": "Default recording duration when a workflow does not provide its own duration.",
        "impact": "Longer captures produce larger files and slower QC.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "DEFAULT_FM_DEVIATION_HZ": {
        "section": "Demodulation defaults",
        "tab": "Demodulation",
        "type": "number",
        "default": 75_000.0,
        "min": 1_000.0,
        "max": 250_000.0,
        "unit": "Hz",
        "description": "Default FM deviation used by demodulation workers.",
        "impact": "Wrong deviation can make demodulated audio distorted or weak.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "DEFAULT_AUDIO_SAMPLE_RATE_HZ": {
        "section": "Demodulation defaults",
        "tab": "Demodulation",
        "type": "number",
        "default": 48_000,
        "min": 8_000,
        "max": 192_000,
        "unit": "Hz",
        "description": "Default audio sample rate for demodulated output.",
        "impact": "Higher values increase file size; unsupported audio paths may reject unusual rates.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "RF_MIN_CENTER_FREQUENCY_HZ": {
        "section": "RF safety limits",
        "tab": "Device, Live Spectrum, Capture Lab",
        "type": "number",
        "default": 70_000_000.0,
        "min": 0.0,
        "max": 6_000_000_000.0,
        "unit": "Hz",
        "description": "Lowest center frequency accepted by backend safety checks.",
        "impact": "Requests below this value are rejected before opening the SDR.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "high",
    },
    "RF_MAX_CENTER_FREQUENCY_HZ": {
        "section": "RF safety limits",
        "tab": "Device, Live Spectrum, Capture Lab",
        "type": "number",
        "default": 6_000_000_000.0,
        "min": 1.0,
        "max": 6_000_000_000.0,
        "unit": "Hz",
        "description": "Highest center frequency accepted by backend safety checks.",
        "impact": "This is bounded by the practical USRP-B200/B210 tuning range used by this project.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "RF_MIN_SAMPLE_RATE_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum, Capture Lab",
        "type": "number",
        "default": 200_000.0,
        "min": 1.0,
        "max": 61_440_000.0,
        "unit": "samples/s",
        "description": "Minimum sample rate accepted by safety checks.",
        "impact": "Very low rates can break profiles that expect wider channels.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "RF_MAX_SAMPLE_RATE_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum, Capture Lab",
        "type": "number",
        "default": 61_440_000.0,
        "min": 1.0,
        "max": 61_440_000.0,
        "unit": "samples/s",
        "description": "Maximum sample rate accepted by safety checks.",
        "impact": "USRP-B200/B210 can reach 61.44 MS/s in ideal single-channel USB 3.0 conditions; practical stable rates may be lower.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "RF_MAX_SPAN_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum, Capture Lab",
        "type": "number",
        "default": 61_440_000.0,
        "min": 1.0,
        "max": 61_440_000.0,
        "unit": "Hz",
        "description": "Maximum spectrum/capture span accepted by safety checks.",
        "impact": "Large spans increase sample rate, CPU, USB bandwidth and capture file size.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "RF_MIN_GAIN_DB": {
        "section": "RF safety limits",
        "tab": "Device, Live Spectrum, Capture Lab",
        "type": "number",
        "default": 0.0,
        "min": 0.0,
        "max": 60.0,
        "unit": "dB",
        "description": "Minimum accepted manual gain.",
        "impact": "Prevents invalid gain values from reaching UHD.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "medium",
    },
    "RF_MAX_GAIN_DB": {
        "section": "RF safety limits",
        "tab": "Device, Live Spectrum, Capture Lab",
        "type": "number",
        "default": 60.0,
        "min": 0.0,
        "max": 76.0,
        "unit": "dB",
        "description": "Maximum accepted manual gain.",
        "impact": "Raising this can make clipping and front-end saturation easier.",
        "restart_required": True,
        "limit_kind": "hardware",
        "risk": "high",
    },
    "RF_MIN_RBW_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 1.0,
        "min": 1.0,
        "max": 1_000_000.0,
        "unit": "Hz",
        "description": "Minimum resolution bandwidth accepted by the backend.",
        "impact": "Very small RBW values increase processing cost and may not be meaningful for short FFTs.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "RF_MAX_RBW_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 1_000_000.0,
        "min": 1.0,
        "max": 10_000_000.0,
        "unit": "Hz",
        "description": "Maximum resolution bandwidth accepted by the backend.",
        "impact": "Larger RBW reduces spectral detail.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "RF_MIN_VBW_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 1.0,
        "min": 1.0,
        "max": 1_000_000.0,
        "unit": "Hz",
        "description": "Minimum video bandwidth accepted by the backend.",
        "impact": "Lower values smooth the displayed trace more heavily.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "RF_MAX_VBW_HZ": {
        "section": "RF safety limits",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 1_000_000.0,
        "min": 1.0,
        "max": 10_000_000.0,
        "unit": "Hz",
        "description": "Maximum video bandwidth accepted by the backend.",
        "impact": "Higher values show less trace smoothing.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "REAL_SDR_FPS": {
        "section": "Live stream",
        "tab": "Live Spectrum, Waterfall",
        "type": "number",
        "default": 10.0,
        "min": 1.0,
        "max": 60.0,
        "unit": "frames/s",
        "description": "Target frame rate for the real SDR spectrum worker.",
        "impact": "Higher values increase CPU and USB pressure.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "REAL_SDR_MAX_FFT_SIZE": {
        "section": "Live stream",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 65_536,
        "min": 256,
        "max": 262_144,
        "unit": "bins",
        "description": "Maximum FFT size accepted by the live SDR worker.",
        "impact": "Larger FFTs improve frequency granularity but increase CPU and latency.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "REAL_SDR_CONNECT_TIMEOUT": {
        "section": "Runtime",
        "tab": "Device",
        "type": "number",
        "default": 20.0,
        "min": 2.0,
        "max": 120.0,
        "unit": "s",
        "description": "Timeout for the device connection probe.",
        "impact": "Increase for slow UHD initialization; decrease for faster failure feedback.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "VITE_APP_SYNC_INTERVAL_MS": {
        "section": "Frontend polling",
        "tab": "Frontend",
        "type": "number",
        "default": 5_000,
        "min": 250,
        "max": 60_000,
        "unit": "ms",
        "description": "General frontend background sync interval.",
        "impact": "Lower values refresh UI state faster but create more API calls.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "low",
    },
    "VITE_SPECTRUM_POLL_INTERVAL_MS": {
        "section": "Frontend polling",
        "tab": "Live Spectrum",
        "type": "number",
        "default": 100,
        "min": 25,
        "max": 5_000,
        "unit": "ms",
        "description": "Frontend polling interval for spectrum frames.",
        "impact": "Lower values feel more live but increase browser and backend load.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "VITE_WATERFALL_POLL_INTERVAL_MS": {
        "section": "Frontend polling",
        "tab": "Waterfall",
        "type": "number",
        "default": 100,
        "min": 25,
        "max": 5_000,
        "unit": "ms",
        "description": "Frontend polling interval for waterfall frames.",
        "impact": "Lower values update waterfall more frequently and increase load.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "QC_MIN_VALID_SNR_DB": {
        "section": "Dataset QC",
        "tab": "Dataset Builder",
        "type": "number",
        "default": 12.0,
        "min": 0.0,
        "max": 60.0,
        "unit": "dB",
        "description": "Minimum SNR for a capture to be considered valid by default QC.",
        "impact": "Lowering admits noisier captures; raising requires cleaner data.",
        "restart_required": True,
        "limit_kind": "scientific_policy",
        "risk": "high",
    },
    "QC_MAX_VALID_CLIPPING_PCT": {
        "section": "Dataset QC",
        "tab": "Dataset Builder",
        "type": "number",
        "default": 0.5,
        "min": 0.0,
        "max": 20.0,
        "unit": "%",
        "description": "Maximum clipping percentage for a valid capture.",
        "impact": "Raising can admit distorted I/Q into training.",
        "restart_required": True,
        "limit_kind": "scientific_policy",
        "risk": "high",
    },
    "QC_MAX_SILENCE_PCT": {
        "section": "Dataset QC",
        "tab": "Dataset Builder",
        "type": "number",
        "default": 85.0,
        "min": 0.0,
        "max": 100.0,
        "unit": "%",
        "description": "Maximum allowed silence for burst captures before absence-of-activity warnings.",
        "impact": "Higher values admit captures with less activity.",
        "restart_required": True,
        "limit_kind": "scientific_policy",
        "risk": "medium",
    },
    "RF_INTELLIGENCE_THRESHOLD_OFFSET_DB": {
        "section": "RF Intelligence",
        "tab": "RF Intelligence, overlays",
        "type": "number",
        "default": 10.0,
        "min": 0.0,
        "max": 40.0,
        "unit": "dB",
        "description": "Detection threshold above the estimated noise floor.",
        "impact": "Lower values find weaker signals but increase false detections.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "RF_INTELLIGENCE_MIN_SNR_DB": {
        "section": "RF Intelligence",
        "tab": "RF Intelligence, overlays",
        "type": "number",
        "default": 6.0,
        "min": 0.0,
        "max": 60.0,
        "unit": "dB",
        "description": "Minimum SNR accepted for RF object candidates.",
        "impact": "Lower values increase weak detections; higher values reduce clutter.",
        "restart_required": True,
        "limit_kind": "software",
        "risk": "medium",
    },
    "SCIENTIFIC_REAL_CAMPAIGN_MODE": {
        "section": "Scientific study",
        "tab": "Study Control Center",
        "type": "boolean",
        "default": False,
        "description": "When on, forbids synthetic/demo data generation anywhere in the backend (e.g. the BLE-RFFI synthetic demo seeder) -- only REAL_B200-origin evidence may enter storage.",
        "impact": "Blocks SyntheticDemoSeeder.seed() (and any future synthetic-data entrypoint that checks this flag) with a clear error instead of running. Turn on before/during the real experimental campaign; leave off for demos.",
        "restart_required": False,
        "limit_kind": "scientific_policy",
        "risk": "high",
    },
}


# One-click bundles over the SAME runtime settings above (never a separate
# mechanism) -- picking a profile is exactly equivalent to hand-typing every
# one of its values into the Settings page yourself, just without having to
# know the real numbers. Every RF_* value in the "ni_usrp_2932" profile was
# read live off the actual connected device (never a datasheet guess):
# serial F4FA9D, addr=192.168.10.2, via `uhd_usrp_probe` and
# gnuradio.uhd.usrp_source.get_freq_range()/get_gain_range()/get_samp_rates()
# on 2026-09-02. Real findings: motherboard is an Ettus N210r4 (NI's 293x
# family rebrands standard Ettus/UHD-compatible hardware, not the separate
# RIO/LabVIEW-FPGA product line) with an SBX daughterboard and an internal
# GPSDO. max_sample_rate_hz is deliberately NOT the DSP's own ceiling (the
# device offers up to 50e6 -- see get_samp_rates()) -- at UHD's sc16 wire
# format that is 200 MB/s, which plain Gigabit Ethernet (~112-117 MB/s
# sustained) cannot carry without dropped packets. 25e6 (25 MS/s, itself one
# of the device's own real selectable rates) is the largest rate that
# reliably fits.
DEVICE_PROFILES: dict[str, dict[str, Any]] = {
    "usrp_b200": {
        "label": "USRP B200 (Ettus, USB)",
        "description": "The default device this platform was built against -- USB 3.0, 70 MHz-6 GHz, up to 61.44 MS/s.",
        "values": {
            "RF_SAFETY_DEVICE_NAME": "USRP-B200 from Ettus Research",
            "UHD_DEVICE_ARGS": "",
            "DEFAULT_ANTENNA": "RX2",
            # Real, valid starting point for THIS device -- also pushed into
            # the already-running AnalyzerSettings when a profile is applied
            # live (see frontend applyDeviceProfile()), not just used to seed
            # a future backend startup. Without this, switching from a
            # device with a narrower range (e.g. the 2932, 380 MHz-4.42 GHz)
            # back to the B200 would leave whatever frequency was last tuned
            # -- fine here since B200's range is a superset, but the 2932
            # profile below genuinely needs this to avoid an immediate
            # out-of-range rejection.
            "DEFAULT_CENTER_FREQUENCY_HZ": 89_400_000.0,
            "DEFAULT_SAMPLE_RATE_HZ": 4_000_000.0,
            "DEFAULT_GAIN_DB": 20.0,
            "RF_MIN_CENTER_FREQUENCY_HZ": 70_000_000.0,
            "RF_MAX_CENTER_FREQUENCY_HZ": 6_000_000_000.0,
            "RF_MIN_SAMPLE_RATE_HZ": 200_000.0,
            "RF_MAX_SAMPLE_RATE_HZ": 61_440_000.0,
            "RF_MAX_SPAN_HZ": 61_440_000.0,
            "RF_MIN_GAIN_DB": 0.0,
            "RF_MAX_GAIN_DB": 60.0,
        },
    },
    "ni_usrp_2932": {
        "label": "NI USRP-2932 (Ettus N210 + SBX, Ethernet, GPSDO)",
        "description": (
            "Connected over dedicated Gigabit Ethernet at 192.168.10.2 (serial F4FA9D). "
            "Wider RF frontend than the B200 (400-4400 MHz real tunable range, internal "
            "GPSDO for precision timing) but a narrower streaming ceiling (25 MS/s, "
            "Gigabit-Ethernet-limited -- the B200's USB 3.0 link carries more)."
        ),
        "values": {
            "RF_SAFETY_DEVICE_NAME": "NI USRP-2932 (Ettus N210r4 + SBX, serial F4FA9D)",
            "UHD_DEVICE_ARGS": "addr=192.168.10.2",
            "DEFAULT_ANTENNA": "RX2",
            # 2402 MHz = BLE primary advertising channel 37, real-tested and
            # confirmed working end-to-end on this exact device (real live
            # capture, source uhd_gnuradio_live) -- comfortably inside this
            # profile's 380 MHz-4.42 GHz range, unlike the B200 profile's own
            # 89.4 MHz default which is NOT.
            "DEFAULT_CENTER_FREQUENCY_HZ": 2_402_000_000.0,
            "DEFAULT_SAMPLE_RATE_HZ": 4_000_000.0,
            "DEFAULT_GAIN_DB": 20.0,
            "RF_MIN_CENTER_FREQUENCY_HZ": 380_000_000.0,
            "RF_MAX_CENTER_FREQUENCY_HZ": 4_420_000_000.0,
            "RF_MIN_SAMPLE_RATE_HZ": 195_312.0,
            "RF_MAX_SAMPLE_RATE_HZ": 25_000_000.0,
            "RF_MAX_SPAN_HZ": 25_000_000.0,
            "RF_MIN_GAIN_DB": 0.0,
            "RF_MAX_GAIN_DB": 38.0,
        },
    },
}


def device_profiles_payload() -> dict[str, Any]:
    values = merged_runtime_values()
    active_id = None
    for profile_id, profile in DEVICE_PROFILES.items():
        if all(values.get(key) == val for key, val in profile["values"].items()):
            active_id = profile_id
            break
    return {
        "profiles": [{"id": pid, **{k: v for k, v in p.items()}} for pid, p in DEVICE_PROFILES.items()],
        "active_profile_id": active_id,
    }


def apply_device_profile(profile_id: str) -> dict[str, Any]:
    profile = DEVICE_PROFILES.get(profile_id)
    if profile is None:
        raise ValueError(f"Unknown device profile: {profile_id}")
    return save_runtime_values(profile["values"])


def load_runtime_values() -> dict[str, Any]:
    if not RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    values = data.get("values") if isinstance(data, dict) else {}
    return values if isinstance(values, dict) else {}


def _coerce_value(key: str, value: Any) -> Any:
    spec = SETTING_CATALOG[key]
    kind = spec["type"]
    if kind == "number":
        parsed = float(value)
        if float(parsed).is_integer() and isinstance(spec.get("default"), int):
            parsed = int(parsed)
        if "min" in spec and parsed < float(spec["min"]):
            raise ValueError(f"{key} must be >= {spec['min']}")
        if "max" in spec and parsed > float(spec["max"]):
            raise ValueError(f"{key} must be <= {spec['max']}")
        return parsed
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return str(value)


def merged_runtime_values() -> dict[str, Any]:
    saved = load_runtime_values()
    merged = {}
    for key, spec in SETTING_CATALOG.items():
        env_value = os.environ.get(key)
        raw = saved.get(key, env_value if env_value is not None else spec["default"])
        try:
            merged[key] = _coerce_value(key, raw)
        except Exception:
            merged[key] = deepcopy(spec["default"])
    return merged


def get_runtime_value(key: str, default: Any | None = None) -> Any:
    return merged_runtime_values().get(key, default)


def apply_runtime_environment() -> None:
    for key, value in merged_runtime_values().items():
        os.environ.setdefault(key, str(value))


def save_runtime_values(values: dict[str, Any]) -> dict[str, Any]:
    # Starts from what was PREVIOUSLY explicitly saved (load_runtime_values),
    # never the fully-computed merged_runtime_values() snapshot -- a real
    # bug this replaces: writing the full merge baked every OTHER catalog
    # key's current env/default value into the file too, permanently
    # freezing it there. A key nobody has explicitly saved must stay ABSENT
    # from disk so it keeps falling through to os.environ/its own default at
    # read time (e.g. a test's monkeypatch.setenv(...) on an untouched key
    # silently stopped working once an unrelated save had persisted that
    # key's then-current value).
    current = load_runtime_values()
    errors: dict[str, str] = {}
    for key, value in values.items():
        if key not in SETTING_CATALOG:
            errors[key] = "Unknown setting"
            continue
        try:
            current[key] = _coerce_value(key, value)
        except Exception as exc:
            errors[key] = str(exc)
    if errors:
        raise ValueError(json.dumps(errors))
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(
        json.dumps({"values": current}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return current


def runtime_settings_payload() -> dict[str, Any]:
    values = merged_runtime_values()
    items = []
    for key, spec in SETTING_CATALOG.items():
        item = deepcopy(spec)
        item["key"] = key
        item["value"] = values[key]
        item["source"] = "saved" if key in load_runtime_values() else ("env" if key in os.environ else "default")
        items.append(item)
    return {
        "settings_path": str(RUNTIME_SETTINGS_PATH),
        "requires_restart_after_save": True,
        "items": items,
        "values": values,
    }
