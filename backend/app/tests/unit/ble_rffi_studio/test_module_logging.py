"""Every StudioJobManager background job (campaign session, capture-only,
replay+evidence, evidence build, training, prepare-and-train) writes its
progress AND its failures to a dedicated, human-readable log file -- not
just the job.json state a specific job_id's polling reads. This is what an
operator (or future me) reads to find out what actually happened without
re-running the action while watching the network tab.
"""
from __future__ import annotations

import time
from pathlib import Path

from app.modules.ble_rffi_studio.api import StudioJobManager, StudioRepository
from app.modules.ble_rffi_studio.module_logging import build_module_logger

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
REAL_CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
REAL_SESSION_ROOT = STORAGE_ROOT / "ble_lab" / "sessions"


def _log_path(module_root: Path) -> Path:
    return module_root / "logs" / "ble_rffi_studio.log"


def test_build_module_logger_creates_the_logs_directory_and_file(tmp_path):
    build_module_logger(tmp_path)
    logging_module = __import__("logging")
    logger = logging_module.getLogger("ble_rffi_studio")
    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()
    assert _log_path(tmp_path).is_file()
    assert "hello" in _log_path(tmp_path).read_text(encoding="utf-8")


def test_evidence_job_failure_is_logged_with_job_id_and_error(tmp_path):
    module_root = tmp_path / "studio"
    repository = StudioRepository(module_root, legacy_capture_root=REAL_CAPTURE_ROOT, legacy_session_root=REAL_SESSION_ROOT)
    job_manager = StudioJobManager(repository, module_root / "jobs")

    # No CaptureRecord was ever built for this capture_id -- a real, honest
    # failure (CAPTURE_NOT_BUILT_YET), not a contrived one.
    job = job_manager.start_evidence_job(capture_id="BLE-IQ-never-built", project_id="P1", ble_channel=37)
    deadline = time.time() + 10
    while time.time() < deadline:
        current = job_manager.get_job(job["job_id"])
        if current["state"] in {"completed", "failed"}:
            job = current
            break
        time.sleep(0.05)

    assert job["state"] == "failed"
    for handler in job_manager.logger.handlers:
        handler.flush()
    log_text = _log_path(module_root).read_text(encoding="utf-8")
    assert job["job_id"] in log_text
    assert "CAPTURE_NOT_BUILT_YET" in log_text
    assert "ERROR" in log_text


def test_two_job_managers_on_different_roots_never_stack_duplicate_handlers(tmp_path):
    # build_module_logger is called once per StudioJobManager construction --
    # constructing several (e.g. across test files reusing the same process)
    # must never leave old handlers (pointed at a now-irrelevant tmp_path)
    # still attached and receiving writes.
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    repository_a = StudioRepository(root_a, legacy_capture_root=REAL_CAPTURE_ROOT, legacy_session_root=REAL_SESSION_ROOT)
    StudioJobManager(repository_a, root_a / "jobs")
    repository_b = StudioRepository(root_b, legacy_capture_root=REAL_CAPTURE_ROOT, legacy_session_root=REAL_SESSION_ROOT)
    manager_b = StudioJobManager(repository_b, root_b / "jobs")

    assert len(manager_b.logger.handlers) == 1
