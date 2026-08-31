from __future__ import annotations

from collections import Counter

from app.modules.rf_intelligence.classifier_rules import classify_candidate, infer_temporal_type
from app.modules.rf_intelligence.detector import detect_signal_candidates
from app.modules.rf_intelligence.schemas import (
    RFIntelligenceSettings,
    RFObjectDetection,
    RFSceneAnalysis,
    SpectrumFrameInput,
)
from app.modules.rf_intelligence.tracker import RFSceneTracker


class RFIntelligenceService:
    def __init__(self) -> None:
        self._tracker = RFSceneTracker()

    def analyze_frame(self, frame: SpectrumFrameInput, settings: RFIntelligenceSettings | None = None) -> RFSceneAnalysis:
        active_settings = settings or RFIntelligenceSettings()
        candidates, noise_floor_db, threshold_db = detect_signal_candidates(frame, active_settings)
        detections: list[RFObjectDetection] = []

        for candidate in candidates:
            label, family, confidence, evidence = classify_candidate(candidate)
            track = self._tracker.update(candidate, frame.timestamp_utc)
            persistence = self._tracker.persistence(track)
            temporal_type = infer_temporal_type(candidate, family, persistence)
            evidence.temporal_match = temporal_type != "unknown"
            detections.append(
                RFObjectDetection(
                    id=candidate.candidate_id,
                    track_id=track.track_id,
                    label=label,
                    candidate_family=family,
                    confidence=confidence,
                    center_frequency_hz=candidate.center_frequency_hz,
                    start_frequency_hz=candidate.start_frequency_hz,
                    stop_frequency_hz=candidate.stop_frequency_hz,
                    bandwidth_hz=candidate.bandwidth_hz,
                    occupied_bandwidth_hz=candidate.occupied_bandwidth_hz,
                    snr_db=candidate.snr_db,
                    peak_power_db=candidate.peak_power_db,
                    mean_power_db=candidate.mean_power_db,
                    noise_floor_db=candidate.noise_floor_db,
                    temporal_type=temporal_type,
                    persistence=persistence,
                    first_seen_utc=track.first_seen_utc,
                    last_seen_utc=track.last_seen_utc,
                    evidence=evidence,
                )
            )

        families = Counter(detection.candidate_family for detection in detections)
        return RFSceneAnalysis(
            timestamp_utc=frame.timestamp_utc,
            noise_floor_db=noise_floor_db,
            threshold_db=threshold_db,
            detections=detections,
            summary={
                "total_detections": len(detections),
                "families": dict(families),
                "classifier_mode": active_settings.classifier_mode,
            },
        )
