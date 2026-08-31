#!/usr/bin/env python3
"""Real IEEE 802.11 legacy-OFDM decoder worker, backed by the validated V3
instrumented gr-ieee802-11/gr-foo build produced and cross-checked in the
isolated wifi-worker-lab campaign (byte-exact MPDU/FCS matches against ground
truth on fixed IQ captures; see docs/WIFI_80211_V2_AUDIT.md).

MUST run under wifi-worker-env's Python interpreter (the pinned GNU Radio
3.10.12.0 environment), never the FastAPI backend's own interpreter -- this
mirrors the existing RADIOCONDA_PYTHON split convention used elsewhere in
this codebase for GNU-Radio-dependent tools.

Recovery is PARTIAL, not complete: the receiver is known (from extensive,
separately-documented campaign work) to lose some fraction of frames even on
a clean channel. Every frame this worker DOES report is FCS-valid by
construction (decode_mac only publishes a message after its own checksum
check passes) -- these are genuinely confirmed frames, not candidates. The
full receiver_internal_events.jsonl diagnostic trace is written alongside the
result for later investigation of the remaining loss.

Invocation contract (unchanged from the existing wifi_80211_decoder_worker.py
stub this replaces as the real implementation path):
    <wifi-worker-env>/python.exe wifi_80211_v3_worker.py --manifest <path> --output-dir <path>
Reads the manifest written by WifiDecodeService.decode() (a WifiCaptureContract
dict plus decoder_sample_rate_hz/input_kind). Writes, into --output-dir:
    software_versions.json  -- pinned vs. actually-loaded module identity
    worker_result.json      -- {"status", "frames": [...], "receiver_diagnostics_summary", ...}
    receiver_internal_events.jsonl -- full V3 diagnostic trace (copied through as-is)
Exit code 0 whenever the flowgraph itself ran to completion (zero frames
decoded is a valid, honestly-reported outcome, not a worker failure). Non-zero
only for real errors: bad manifest, missing/unsupported input, environment
mismatch, or a GNU Radio import failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# The validated, campaign-tested build. A separate, isolated copy from the
# admission-gate experiments (V4/V5/V5b) -- those are NOT used here.
INSTRUMENTED_PREFIX_V3 = Path(r"C:\Users\Usuario\wifi-worker-lab\instrumented-prefix-v3")
WIFI_WORKER_ENV = Path(r"C:\Users\Usuario\wifi-worker-lab\wifi-worker-env")
ARTIFACTS_PHY = Path(r"C:\Users\Usuario\wifi-worker-lab\artifacts\phy")

# SHA-256 of the exact V3 binaries this worker was validated against (recorded
# once, at the end of the campaign that produced them). Any mismatch is
# reported in software_versions.json, but does not by itself fail the run --
# it is evidence for later audit, since a content hash is the only meaningful
# "pin" check available for a sys.path-overridden build with no installed
# package metadata (importlib.metadata would report the wrong, RadioConda
# default package here, not what is actually imported).
PINNED_V3_HASHES = {
    "gnuradio-ieee802_11.dll": "dcdcb8b6893179904eeb104d45f0b61360ce21678b5d051ceb0ff4e532408c02",
    "ieee802_11_python.cp312-win_amd64.pyd": "e6bc159d032de5840d3641143b5bb90e898c42e6353ad7f72be25d77545a3095",
}
PINNED_GNURADIO_VERSION = "3.10.12.0"
PINNED_GR_IEEE802_11_COMMIT = "ad0598e4a874f4b8e1f391a1e0323e80df2b34ff"
PINNED_GR_FOO_COMMIT = "4c2a471b0453b9dca669b2d9dfcbfba6278741d7"

BYTES_PER_COMPLEX = {"cf32_le": 8, "ci16_le": 4, "cu8": 2}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_environment(output_dir: Path) -> dict:
    dll_path = INSTRUMENTED_PREFIX_V3 / "bin" / "gnuradio-ieee802_11.dll"
    pyd_path = INSTRUMENTED_PREFIX_V3 / "Lib" / "site-packages" / "ieee802_11" / "ieee802_11_python.cp312-win_amd64.pyd"
    detected = {
        "python_version": sys.version,
        "gnuradio_ieee802_11_dll_path": str(dll_path),
        "gnuradio_ieee802_11_dll_sha256": sha256_file(dll_path) if dll_path.is_file() else None,
        "ieee802_11_python_pyd_path": str(pyd_path),
        "ieee802_11_python_pyd_sha256": sha256_file(pyd_path) if pyd_path.is_file() else None,
    }
    try:
        from gnuradio import gr as _gr  # type: ignore
        detected["gnuradio_version"] = _gr.version()
    except Exception as exc:  # pragma: no cover - environment diagnostic path
        detected["gnuradio_version"] = None
        detected["gnuradio_import_error"] = str(exc)
    versions = {
        "pinned": {
            "gnuradio": PINNED_GNURADIO_VERSION,
            "gr_ieee802_11_commit": PINNED_GR_IEEE802_11_COMMIT,
            "gr_foo_commit": PINNED_GR_FOO_COMMIT,
            "binary_hashes": PINNED_V3_HASHES,
        },
        "detected": detected,
        "binary_hashes_match": {
            name: detected.get(f"{'gnuradio_ieee802_11_dll' if name.endswith('.dll') else 'ieee802_11_python_pyd'}_sha256") == expected
            for name, expected in PINNED_V3_HASHES.items()
        },
        "note": (
            "Binary content hashes are the authoritative pin check here, not "
            "importlib.metadata -- this build is loaded via sys.path override, "
            "not pip/conda install, so package metadata would reflect the "
            "unrelated default RadioConda package instead of what is actually "
            "imported."
        ),
    }
    (output_dir / "software_versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    return versions


def load_iq(input_file: str, datatype: str):
    import numpy as np

    bytes_per = BYTES_PER_COMPLEX.get(datatype)
    if bytes_per is None:
        raise ValueError(f"unsupported datatype: {datatype}")
    path = Path(input_file)
    raw_bytes = path.read_bytes()
    usable = len(raw_bytes) - (len(raw_bytes) % bytes_per)
    raw_bytes = raw_bytes[:usable]
    if datatype == "cf32_le":
        floats = np.frombuffer(raw_bytes, dtype="<f4")
        return (floats[0::2] + 1j * floats[1::2]).astype(np.complex64)
    if datatype == "ci16_le":
        ints = np.frombuffer(raw_bytes, dtype="<i2").astype(np.float32) / 32768.0
        return (ints[0::2] + 1j * ints[1::2]).astype(np.complex64)
    if datatype == "cu8":
        vals = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
        return (vals[0::2] + 1j * vals[1::2]).astype(np.complex64)
    raise ValueError(f"unsupported datatype: {datatype}")


def run_decoder(iq, sample_rate_hz: float, channel_center_hz: float, output_dir: Path) -> dict:
    os.add_dll_directory(str(INSTRUMENTED_PREFIX_V3 / "bin"))
    os.add_dll_directory(str(WIFI_WORKER_ENV / "Library" / "bin"))
    sys.path[:0] = [str(ARTIFACTS_PHY), str(INSTRUMENTED_PREFIX_V3 / "Lib" / "site-packages")]

    os.environ["WIFI_CAMPAIGN_RUN_ID"] = output_dir.name or "wifi_80211_v3_worker"
    os.environ["WIFI_CAMPAIGN_EVENTS_DIR"] = str(output_dir)

    from gnuradio import gr, blocks
    import pmt
    import ieee802_11
    from wifi_phy_hier import wifi_phy_hier

    import numpy as np

    class IqSource(gr.sync_block):
        def __init__(s, samples: np.ndarray):
            gr.sync_block.__init__(s, name="v3_worker_source", in_sig=None, out_sig=[np.complex64])
            s.samples = samples
            s.pos = 0

        def work(s, ii, oo):
            n = len(oo[0])
            remaining = len(s.samples) - s.pos
            if remaining <= 0:
                return -1
            n = min(n, remaining)
            oo[0][:n] = s.samples[s.pos:s.pos + n]
            s.pos += n
            return n

    class RxSink(gr.basic_block):
        def __init__(s, cb):
            gr.basic_block.__init__(s, name="v3_worker_rx", in_sig=None, out_sig=None)
            s.cb = cb
            s.message_port_register_in(pmt.intern("in"))
            s.set_msg_handler(pmt.intern("in"), s.handle)

        def handle(s, m):
            s.cb(bytes(pmt.to_python(pmt.cdr(m))))

    confirmed_frames = []

    def on_frame(mpdu: bytes) -> None:
        confirmed_frames.append({"arrival_order": len(confirmed_frames), "mpdu_hex": mpdu.hex(), "mpdu_length_bytes": len(mpdu)})

    tb = gr.top_block("wifi_80211_v3_worker")
    source = IqSource(iq)
    phy = wifi_phy_hier(20e6, ieee802_11.Equalizer(0), ieee802_11.Encoding(0), float(channel_center_hz) or 5.9e9, 0.56)
    rsink = RxSink(on_frame)
    tb.connect((source, 0), (phy, 0))
    tb.connect((phy, 0), (blocks.null_sink(gr.sizeof_gr_complex), 0))
    tb.msg_connect((phy, "mac_out"), (rsink, "in"))

    started = time.monotonic()
    tb.start()
    # Bound the run to roughly the real duration of the capture, plus a fixed
    # drain margin, so a very long capture cannot hang the worker forever.
    approx_duration_s = len(iq) / max(sample_rate_hz, 1.0)
    deadline = started + min(max(approx_duration_s * 1.5 + 5.0, 5.0), 900.0)
    while time.monotonic() < deadline and source.pos < len(iq):
        time.sleep(0.05)
    time.sleep(0.5)
    tb.stop()
    tb.wait()

    return {
        "frames": confirmed_frames,
        "samples_processed": int(source.pos),
        "samples_total": int(len(iq)),
        "duration_seconds": time.monotonic() - started,
    }


def summarize_diagnostics(output_dir: Path) -> dict:
    events_path = output_dir / "receiver_internal_events.jsonl"
    counts = {
        "sync_short_accepted": 0, "sync_long_accepted": 0, "sync_long_rejected": 0,
        "l_sig_valid": 0, "l_sig_rejected": 0, "fcs_valid": 0, "fcs_invalid": 0,
        "frames_abandoned": 0,
    }
    if not events_path.exists():
        return counts
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        block, stage = row.get("block"), row.get("stage")
        if block == "sync_short" and stage == "sync_short_accepted":
            counts["sync_short_accepted"] += 1
        elif block == "sync_long" and stage == "sync_long_accepted":
            counts["sync_long_accepted"] += 1
        elif block == "sync_long" and stage == "sync_long_rejected":
            counts["sync_long_rejected"] += 1
        elif block == "frame_equalizer" and stage == "l_sig_decoded":
            counts["l_sig_valid" if not row.get("rejection_reason") else "l_sig_rejected"] += 1
        elif block == "frame_equalizer" and stage == "frame_equalizer_completed" and row.get("rejection_reason"):
            counts["frames_abandoned"] += 1
        elif block == "decode_mac" and stage == "fcs_valid":
            counts["fcs_valid" if row.get("state_after") == "PSDU_RECOVERED" else "fcs_invalid"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    versions = check_environment(output_dir)

    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except Exception as exc:
        (output_dir / "worker_result.json").write_text(json.dumps({"status": "manifest_read_failed", "error": str(exc), "frames": []}, indent=2), encoding="utf-8")
        return 2

    errors = []
    if float(manifest.get("decoder_sample_rate_hz") or 0) != 20_000_000.0:
        errors.append("decoder_sample_rate_hz_must_equal_20000000")
    input_file = manifest.get("input_file")
    if not input_file or not Path(input_file).is_file():
        errors.append("input_file_not_found")
    datatype = manifest.get("datatype")
    if datatype not in BYTES_PER_COMPLEX:
        errors.append("unsupported_datatype")

    if errors:
        result = {"status": "input_rejected", "errors": errors, "frames": [], "versions": versions}
        (output_dir / "worker_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"status": result["status"], "errors": errors}))
        return 78

    try:
        iq = load_iq(input_file, datatype)
        decode_result = run_decoder(
            iq,
            sample_rate_hz=float(manifest.get("sample_rate_hz") or 20_000_000.0),
            channel_center_hz=float(manifest.get("channel_center_frequency_hz") or manifest.get("hardware_center_frequency_hz") or 0.0),
            output_dir=output_dir,
        )
    except Exception as exc:  # pragma: no cover - defensive: never crash the parent process silently
        result = {"status": "decode_error", "error": str(exc), "frames": [], "versions": versions}
        (output_dir / "worker_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"status": "decode_error", "error": str(exc)}))
        return 1

    diagnostics = summarize_diagnostics(output_dir)
    result = {
        "status": "complete",
        "decoder_version": "wifi_80211_v3_reference",
        "known_limitation": (
            "Recovery is partial: the validated receiver does not recover every "
            "transmitted frame even on a clean channel (see receiver_internal_events.jsonl "
            "and the campaign diagnostic history for the documented, still-open root cause)."
        ),
        "frames": decode_result["frames"],
        "samples_processed": decode_result["samples_processed"],
        "samples_total": decode_result["samples_total"],
        "processing_duration_seconds": decode_result["duration_seconds"],
        "receiver_diagnostics_summary": diagnostics,
        "versions": versions,
    }
    (output_dir / "worker_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "frames_confirmed": len(decode_result["frames"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
