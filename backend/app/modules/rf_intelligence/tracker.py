from __future__ import annotations

from dataclasses import dataclass

from app.modules.rf_intelligence.detector import SignalCandidate


@dataclass(slots=True)
class RFTrack:
    track_id: str
    center_frequency_hz: float
    bandwidth_hz: float
    first_seen_utc: str | None
    last_seen_utc: str | None
    hits: int = 1


class RFSceneTracker:
    def __init__(self, max_center_delta_hz: float = 250_000.0) -> None:
        self._tracks: dict[str, RFTrack] = {}
        self._max_center_delta_hz = max_center_delta_hz

    def update(self, candidate: SignalCandidate, timestamp_utc: str | None) -> RFTrack:
        track = self._find_track(candidate)
        if track is None:
            track_id = self._make_track_id(candidate)
            track = RFTrack(
                track_id=track_id,
                center_frequency_hz=candidate.center_frequency_hz,
                bandwidth_hz=candidate.bandwidth_hz,
                first_seen_utc=timestamp_utc,
                last_seen_utc=timestamp_utc,
            )
            self._tracks[track_id] = track
            return track

        track.center_frequency_hz = (track.center_frequency_hz * track.hits + candidate.center_frequency_hz) / (track.hits + 1)
        track.bandwidth_hz = (track.bandwidth_hz * track.hits + candidate.bandwidth_hz) / (track.hits + 1)
        track.last_seen_utc = timestamp_utc
        track.hits += 1
        return track

    def persistence(self, track: RFTrack) -> float:
        return min(1.0, track.hits / 8.0)

    def _find_track(self, candidate: SignalCandidate) -> RFTrack | None:
        for track in self._tracks.values():
            tolerance = max(self._max_center_delta_hz, candidate.bandwidth_hz, track.bandwidth_hz)
            if abs(track.center_frequency_hz - candidate.center_frequency_hz) <= tolerance:
                return track
        return None

    def _make_track_id(self, candidate: SignalCandidate) -> str:
        mhz = candidate.center_frequency_hz / 1e6
        base = f"track_{mhz:.3f}MHz".replace(".", "_")
        suffix = 1
        track_id = base
        while track_id in self._tracks:
            suffix += 1
            track_id = f"{base}_{suffix}"
        return track_id
