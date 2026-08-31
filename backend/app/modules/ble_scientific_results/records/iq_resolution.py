"""Single, shared resolver for CaptureRecord.iq_path -- extracted here
(Fase 2, B.1) so it exists in exactly one place instead of being
reimplemented per module. `CaptureRecord.iq_path` is a bare filename (e.g.
"BLE-IQ-...sigmf-data"), not an absolute path; the real file lives at
`legacy_capture_root/<capture_id>/<iq_path>` -- the same rule
`StudioRepository.resolve_iq_path()` already implements in ble_rffi_studio
(`api/studio_repository.py:560-561`) and that Fase 1's
`ScientificResultsRepository._resolve_iq_path` duplicated inline. Both call
into this function now.
"""
from __future__ import annotations

from pathlib import Path

from app.modules.ble_rffi_studio.contracts import CaptureRecord


def resolve_iq_path(legacy_capture_root: Path, capture: CaptureRecord) -> Path:
    if ".." in Path(capture.iq_path).parts or ".." in Path(capture.capture_id).parts:
        raise ValueError(f"PATH_TRAVERSAL_REJECTED:{capture.capture_id}:{capture.iq_path}")
    return legacy_capture_root / capture.capture_id / capture.iq_path


def resolve_replay_dir(legacy_capture_root: Path, capture_id: str) -> Path | None:
    """Most-recent offline_replays/<replay_run_id>/ for this capture, or
    None if the capture was never replayed (e.g. capture-only sessions that
    have not gone through offline replay yet). Reuses the SAME resolution
    rule ble_packet_analysis_service.py already uses
    (BleCaptureLocator.resolve_replay_dir), imported directly rather than
    reimplemented, so "which replay run is authoritative" is never decided
    two different ways in this codebase."""
    from app.infrastructure.ble.packet_analysis.ble_capture_locator import BleCaptureLocator

    locator = BleCaptureLocator(legacy_capture_root, legacy_capture_root)
    try:
        return locator.resolve_replay_dir(capture_id, None)
    except FileNotFoundError:
        return None
