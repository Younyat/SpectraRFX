from __future__ import annotations


class RecordingController:
    def __init__(self, start_rf_recording_use_case, stop_rf_recording_use_case, settings):
        self._start_rf_recording_use_case = start_rf_recording_use_case
        self._stop_rf_recording_use_case = stop_rf_recording_use_case
        self._settings = settings
        self._active_recording_id: str | None = None
        self._recordings: dict[str, dict] = {}

    def start_recording(self, duration_seconds: float = 10.0, recording_type: str = "iq") -> dict:
        result = self._start_rf_recording_use_case.execute(duration_seconds, self._settings, recording_type)
        data = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        self._active_recording_id = data.get("recording_id")
        if self._active_recording_id:
            self._recordings[self._active_recording_id] = data
        return data

    def stop_recording(self) -> dict:
        recording_id = self._active_recording_id or ""
        result = self._stop_rf_recording_use_case.execute(recording_id)
        self._active_recording_id = None
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)

    def list_recordings(self) -> list:
        return list(self._recordings.values())
