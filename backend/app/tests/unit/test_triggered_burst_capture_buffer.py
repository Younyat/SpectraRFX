"""Regression tests for chronological pre-trigger ring-buffer retention."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


def _load_buffer_class():
    """Load the capture tool without requiring GNU Radio/UHD hardware modules."""
    gnuradio = types.ModuleType("gnuradio")
    gnuradio.gr = types.SimpleNamespace(sync_block=object, top_block=object)
    gnuradio.uhd = types.SimpleNamespace()
    previous = sys.modules.get("gnuradio")
    sys.modules["gnuradio"] = gnuradio
    try:
        tool = Path(__file__).resolve().parents[3] / "tools" / "triggered_burst_capture.py"
        spec = importlib.util.spec_from_file_location("triggered_burst_capture_for_test", tool)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module._CircularBlockBuffer
    finally:
        if previous is None:
            sys.modules.pop("gnuradio", None)
        else:
            sys.modules["gnuradio"] = previous


_CircularBlockBuffer = _load_buffer_class()


def _iq(values: range | list[int]) -> np.ndarray:
    return np.asarray(list(values), dtype=np.complex64)


def test_wrap_around_keeps_exact_newest_samples_in_chronological_order() -> None:
    buffer = _CircularBlockBuffer(5)
    buffer.push(_iq([0, 1, 2]))
    buffer.push(_iq([3, 4, 5]))
    np.testing.assert_array_equal(buffer.snapshot(), _iq([1, 2, 3, 4, 5]))


def test_block_sizes_need_not_divide_max_samples() -> None:
    buffer = _CircularBlockBuffer(7)
    buffer.push(_iq([0, 1, 2, 3]))
    buffer.push(_iq([4, 5, 6, 7]))
    np.testing.assert_array_equal(buffer.snapshot(), _iq([1, 2, 3, 4, 5, 6, 7]))


def test_multiple_complete_wraps_keep_only_latest_window() -> None:
    buffer = _CircularBlockBuffer(5)
    for start in range(0, 20, 2):
        buffer.push(_iq([start, start + 1]))
    np.testing.assert_array_equal(buffer.snapshot(), _iq([15, 16, 17, 18, 19]))


def test_oversized_blocks_and_following_push_preserve_exact_order() -> None:
    buffer = _CircularBlockBuffer(6)
    buffer.push(_iq(range(10)))
    np.testing.assert_array_equal(buffer.snapshot(), _iq([4, 5, 6, 7, 8, 9]))
    buffer.push(_iq([10, 11, 12]))
    np.testing.assert_array_equal(buffer.snapshot(), _iq([7, 8, 9, 10, 11, 12]))
