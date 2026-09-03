#!/usr/bin/env python3
"""Caption capture limits sampling and OCR work to a configured region."""

import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.captions import (CaptionChangeDetector, CaptionRegion,
                                        FakeCaptionOCR, TesseractCaptionOCR,
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

with tempfile.TemporaryDirectory(prefix="mm-caption-region-") as tmp:
    frame = Path(tmp) / "frame.png"
    Image.new("RGB", (100, 100), "white").save(frame)
    region_capture = VisualCaptionCapture(
        CaptionRegion(0.0, 0.5, 1.0, 0.5), FakeCaptionOCR("Avery: Synthetic line"))
    assert region_capture.process_frame(frame, 1.0) == []
    signal = region_capture.flush(2.0)[0]
    assert signal.text == "Synthetic line"
    assert signal.speaker == "Avery" and signal.speaker_source == "ocr_label"

print("caption change tests: OK")
