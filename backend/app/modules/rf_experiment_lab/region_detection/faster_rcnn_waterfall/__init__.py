from app.modules.rf_experiment_lab.region_detection.learned_detector_interface import OptionalLearnedDetectorStub


def build_detector() -> OptionalLearnedDetectorStub:
    return OptionalLearnedDetectorStub("faster_rcnn_waterfall")
