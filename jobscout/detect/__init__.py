from jobscout.detect.detector import DetectionResult, detect_company, run_detection
from jobscout.detect.slugs import slug_candidates
from jobscout.detect.urls import BoardRef, parse_board_url

__all__ = [
    "BoardRef",
    "DetectionResult",
    "detect_company",
    "parse_board_url",
    "run_detection",
    "slug_candidates",
]
