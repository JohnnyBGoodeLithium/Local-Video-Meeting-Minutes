#!/usr/bin/env python3
"""Live speaker IDs survive display reconciliation and protect stronger identity."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.speaker import (LiveSpeakerTracker, SpeakerStrategyBenchmark,
                                       select_speaker_strategy)


tracker = LiveSpeakerTracker()
speaker = tracker.observe("cluster-0")
assert speaker.id == "LS001" and speaker.display_label == "Speaker A"
speaker = tracker.reconcile("cluster-0", "Avery Example", "platform_identity")
assert speaker.id == "LS001" and speaker.display_label == "Avery Example"
assert speaker.provisional is False

# A weaker diarization label cannot downgrade platform identity.
speaker = tracker.reconcile("cluster-0", "Speaker B", "local_diarization")
assert speaker.display_label == "Avery Example"
assert speaker.speaker_source == "platform_identity"

speaker = tracker.remap_cluster("cluster-0", "cluster-renamed")
assert speaker.id == "LS001" and tracker.cluster_churn == 1
assert speaker.reassignments == 1

fallback = select_speaker_strategy([
    SpeakerStrategyBenchmark("rolling_pipeline", 1.2, 1, 8),
    SpeakerStrategyBenchmark("online_clustering", 0.4, 9, 5),
])
assert fallback == "anonymous_live_then_post_session_diarization"
selected = select_speaker_strategy([
    SpeakerStrategyBenchmark("rolling_pipeline", 0.45, 2, 7),
    SpeakerStrategyBenchmark("online_clustering", 0.30, 2, 4),
])
assert selected == "online_clustering"

print("live speaker tests: OK")
