#!/usr/bin/env python3
"""Caption capture limits sampling and OCR work to a configured region."""

import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.captions import (CaptionChangeDetector, CaptionDetection,
                                        CaptionOCRResult, CaptionRegion,
                                        CaptionRegionTracker, FakeCaptionOCR,
                                        FakeCaptionRegionDetector, PaddleOCRv6CaptionOCR,
                                        TesseractCaptionOCR,
                                        VisualCaptionCapture)


region = CaptionRegion(x=0.1, y=0.75, width=0.8, height=0.2)
capture = VisualCaptionCapture(region, FakeCaptionOCR("Synthetic caption"))
assert [capture.should_sample(at) for at in (0.0, 0.2, 0.5, 0.75, 1.0)] == [
    True, False, True, False, True,
]
for fps in (1, 5):
    VisualCaptionCapture(region, FakeCaptionOCR(), fps=fps)
for bad in (
    (-0.1, 0, 0.5, 0.5),
    (0.8, 0.8, 0.3, 0.3),
):
    try:
        CaptionRegion(*bad)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid caption region accepted")

change = CaptionChangeDetector(threshold=0.1)
assert change.changed(b"a" * 100) is True
assert change.changed(b"a" * 100) is False
assert change.changed(b"b" * 100) is True
assert FakeCaptionOCR(" local only ").recognize(Path("unused")) == " local only "
assert isinstance(TesseractCaptionOCR().available(), bool)
assert PaddleOCRv6CaptionOCR(Path("/missing/det"), Path("/missing/rec")).available() is False

with tempfile.TemporaryDirectory(prefix="mm-caption-region-") as tmp:
    frame = Path(tmp) / "frame.png"
    Image.new("RGB", (100, 100), "white").save(frame)
    region_capture = VisualCaptionCapture(
        CaptionRegion(0.0, 0.5, 1.0, 0.5), FakeCaptionOCR("Avery: Synthetic line"))
    assert region_capture.process_frame(frame, 1.0) == []
    signal = region_capture.flush(2.0)[0]
    assert signal.text == "Synthetic line"
    assert signal.speaker == "Avery" and signal.speaker_source == "ocr_label"
    assert signal.text_review_status == "automatic"
    assert signal.confidence_facets["source"] == 0.55

    moving = CaptionRegion(0.08, 0.08, 0.84, 0.14)
    detector = FakeCaptionRegionDetector([CaptionDetection(moving, 0.92)])

    class ScoredOCR(FakeCaptionOCR):
        def recognize(self, image, *, language=None):
            return CaptionOCRResult("Verified-looking text", 0.86)

    adaptive = VisualCaptionCapture(None, ScoredOCR(), detector=detector)
    assert adaptive.process_frame(frame, 3.0) == []
    adaptive_signal = adaptive.flush(4.0)[0]
    assert adaptive_signal.confidence == 0.86
    assert adaptive_signal.confidence_facets == {
        "source": 0.55, "temporal": 0.5, "recognition": 0.86, "region": 0.92,
    }

tracker = CaptionRegionTracker(maximum_misses=1)
bottom = CaptionRegion(0.1, 0.76, 0.8, 0.16)
moved = CaptionRegion(0.1, 0.08, 0.8, 0.16)
assert tracker.update([CaptionDetection(bottom, 0.8)]) == bottom
assert tracker.update([CaptionDetection(moved, 0.95)]) == moved
assert tracker.update([]) == moved
assert tracker.update([]) is None

print("caption change tests: OK")
