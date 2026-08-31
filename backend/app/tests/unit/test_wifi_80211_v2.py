from __future__ import annotations

import binascii
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

from app.modules.demodulation.wifi_80211.application.wifi_decode_service import WifiDecodeService
from app.modules.demodulation.wifi_80211.domain.models import WifiCaptureContract
from app.modules.demodulation.wifi_80211.infrastructure.capture_adapter import file_layout, iter_iq_chunks, sample_count, sha256_file
from app.modules.demodulation.wifi_80211.infrastructure.legacy_ofdm_decoder import find_stf_candidates
from app.modules.demodulation.wifi_80211.infrastructure.mac_parser import RecoveredPsdu, parse_mpdu


def _write_cf32(path: Path, iq: np.ndarray) -> None:
    iq.astype(np.complex64).tofile(path)


def test_chunk_reader_preserves_absolute_order_and_entire_file(tmp_path: Path) -> None:
    path = tmp_path / "capture.cfile"; expected = (np.arange(23) + 1j * np.arange(23)[::-1]).astype(np.complex64); _write_cf32(path, expected)
    chunks = list(iter_iq_chunks(path, "cf32_le", chunk_samples=7))
    assert [offset for offset, _ in chunks] == [0, 7, 14, 21]
    np.testing.assert_array_equal(np.concatenate([chunk for _, chunk in chunks]), expected)
    assert sample_count(path, "cf32_le") == expected.size


def test_cf32_le_endianness_iq_order_chunk_limit_and_trailing_bytes(tmp_path: Path) -> None:
    path = tmp_path / "cf32.iq"
    path.write_bytes(struct.pack("<ffffff", 1.0, -2.0, 3.5, 4.25, -5.0, 6.0) + b"\xaa\xbb\xcc")
    chunks = list(iter_iq_chunks(path, "cf32_le", chunk_samples=2))
    assert [len(chunk) for _, chunk in chunks] == [2, 1]
    np.testing.assert_array_equal(np.concatenate([chunk for _, chunk in chunks]), np.asarray([1-2j, 3.5+4.25j, -5+6j], np.complex64))
    assert file_layout(path, "cf32_le") == {"file_size_bytes": 27, "samples_total_in_file": 3, "trailing_incomplete_bytes": 3}


def test_ci16_le_endianness_iq_order_normalization_and_trailing_byte(tmp_path: Path) -> None:
    path = tmp_path / "ci16.iq"
    path.write_bytes(struct.pack("<hhhh", -32768, 16384, 32767, -8192) + b"\xff")
    chunks = list(iter_iq_chunks(path, "ci16_le", chunk_samples=1))
    assert [offset for offset, _ in chunks] == [0, 1]
    np.testing.assert_allclose(np.concatenate([chunk for _, chunk in chunks]), np.asarray([-1+0.5j, 32767/32768-0.25j], np.complex64))
    assert file_layout(path, "ci16_le")["trailing_incomplete_bytes"] == 1


def test_cu8_iq_order_normalization_chunk_bound_and_incomplete_tail(tmp_path: Path) -> None:
    path = tmp_path / "cu8.iq"
    path.write_bytes(bytes([0, 255, 127, 128, 64, 192, 99]))
    chunks = list(iter_iq_chunks(path, "cu8", chunk_samples=2))
    assert [len(chunk) for _, chunk in chunks] == [2, 1]
    expected = np.asarray([(0-127.5)/127.5 + 1j*((255-127.5)/127.5), (127-127.5)/127.5 + 1j*((128-127.5)/127.5), (64-127.5)/127.5 + 1j*((192-127.5)/127.5)], np.complex64)
    np.testing.assert_allclose(np.concatenate([chunk for _, chunk in chunks]), expected)
    assert file_layout(path, "cu8")["trailing_incomplete_bytes"] == 1


def test_stf_periodicity_detector_requires_a_plateau() -> None:
    rng = np.random.default_rng(7); short = (rng.normal(size=16) + 1j * rng.normal(size=16)).astype(np.complex64)
    iq = np.concatenate([np.zeros(80, np.complex64), np.tile(short, 12), np.zeros(80, np.complex64)])
    candidates = find_stf_candidates(iq, threshold=0.7, minimum_plateau=20)
    assert candidates and candidates[0]["evidence_level"] == "preamble_candidate"
    assert find_stf_candidates(np.zeros(256, np.complex64), threshold=0.7) == []


def test_service_processes_all_samples_without_silent_truncation(tmp_path: Path) -> None:
    path = tmp_path / "full.cfile"; _write_cf32(path, np.zeros(2_000_017, np.complex64))
    contract = WifiCaptureContract(str(path), "cf32_le", 30e6, 2462e6, 2462e6, 20e6, "2026-01-01T00:00:00Z", sample_count(path, "cf32_le"), 20.0, "RX2", "B200", "test", "dataset", sha256_file(path), 0, False, False, False, {"applied": False}, "legacy_ofdm", True)
    result = WifiDecodeService().decode(contract, tmp_path / "out")
    assert result["unique_samples_processed"] == 2_000_017
    assert result["analysis_truncated"] is False
    assert result["valid_demodulation"] is False


def test_protected_mpdu_never_exposes_clear_payload() -> None:
    fc = (2 << 2) | 0x4000
    header = fc.to_bytes(2, "little") + b"\x00\x00" + bytes.fromhex("00112233445566778899aabbccddeeff00112233") + b"\x10\x00"
    body = header + b"ciphertext"
    frame = body + (binascii.crc32(body) & 0xFFFFFFFF).to_bytes(4, "little")
    parsed = parse_mpdu(RecoveredPsdu(frame, complete=True))
    assert parsed["fcs_valid"] is True
    assert parsed["payload_state"] == "protected_ciphertext"
    assert "payload_hex" not in parsed


def test_mac_parser_rejects_arbitrary_bytes_without_phy_psdu_boundary() -> None:
    try:
        parse_mpdu(b"arbitrary")  # type: ignore[arg-type]
    except ValueError as error:
        assert "complete PSDU" in str(error)
    else:
        raise AssertionError("arbitrary bytes reached the MAC parser")


def test_external_worker_fails_closed_and_emits_versioned_artifact(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"decoder_sample_rate_hz": 20000000}', encoding="utf-8")
    worker = Path(__file__).resolve().parents[3] / "tools" / "wifi_80211_decoder_worker.py"
    completed = subprocess.run([sys.executable, str(worker), "--manifest", str(manifest), "--output-dir", str(tmp_path / "worker")], capture_output=True, text=True, timeout=10)
    assert completed.returncode in {69, 78}
    result = (tmp_path / "worker" / "worker_result.json").read_text(encoding="utf-8")
    assert '"frames": []' in result
    assert (tmp_path / "worker" / "software_versions.json").is_file()
