"""The detector, for the analysis scripts.

There is one detector, and it lives with the code that runs it on the board (../api/streaming_detector.py).
The scripts here import it through this module, so only one place knows where that is.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from streaming_detector import PRESETS, DetectorParams, Frame, SampleClock, StreamingDetector, run  # noqa: E402, F401
