"""Stable anonymous live speaker groups with provenance-aware reconciliation."""

from __future__ import annotations

from dataclasses import asdict, dataclass


SPEAKER_SOURCE_PRIORITY = {
    "unknown": 0,
    "ocr_label": 1,
    "local_diarization": 2,
    "voice_profile": 3,
    "human_confirmed": 4,
    "platform_identity": 5,
}


@dataclass(slots=True)
class LiveSpeaker:
    id: str
    cluster_key: str
    display_label: str
    speaker_source: str = "local_diarization"
    provisional: bool = True
    reassignments: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class LiveSpeakerTracker:
    def __init__(self):
        self._by_cluster: dict[str, LiveSpeaker] = {}
        self.cluster_churn = 0

    @staticmethod
    def _anonymous(index: int) -> str:
        if index < 26:
            return f"Speaker {chr(ord('A') + index)}"
        return f"Speaker {index + 1}"

    def observe(self, cluster_key: str) -> LiveSpeaker:
        key = str(cluster_key)
        if key not in self._by_cluster:
            index = len(self._by_cluster)
            self._by_cluster[key] = LiveSpeaker(
                id=f"LS{index + 1:03d}", cluster_key=key,
                display_label=self._anonymous(index),
            )
        return self._by_cluster[key]

    def reconcile(self, cluster_key: str, display_label: str, speaker_source: str) -> LiveSpeaker:
        if speaker_source not in SPEAKER_SOURCE_PRIORITY:
            raise ValueError("unsupported speaker source")
        speaker = self.observe(cluster_key)
        if SPEAKER_SOURCE_PRIORITY[speaker_source] < SPEAKER_SOURCE_PRIORITY[speaker.speaker_source]:
            return speaker
        label = display_label.strip()
        if not label:
            return speaker
        if label != speaker.display_label:
            speaker.display_label = label
            speaker.reassignments += 1
        speaker.speaker_source = speaker_source
        speaker.provisional = speaker_source not in {"platform_identity", "human_confirmed"}
        return speaker

    def remap_cluster(self, old_cluster: str, new_cluster: str) -> LiveSpeaker:
        """Keep the internal ID stable when an online cluster key churns."""
        speaker = self._by_cluster.pop(old_cluster)
        speaker.cluster_key = new_cluster
        self._by_cluster[new_cluster] = speaker
        self.cluster_churn += 1
        return speaker

    def speakers(self) -> list[LiveSpeaker]:
        return sorted(self._by_cluster.values(), key=lambda item: item.id)


@dataclass(frozen=True, slots=True)
class SpeakerStrategyBenchmark:
    strategy: str
    rtf: float
    cluster_churn: int
    speaker_lag_p95: float


def select_speaker_strategy(results: list[SpeakerStrategyBenchmark], *, max_rtf: float = 0.5,
                            max_churn: int = 3) -> str:
    """Prefer measured near-live quality; otherwise keep anonymous groups for finalization."""
    eligible = [item for item in results if item.rtf <= max_rtf and item.cluster_churn <= max_churn]
    if not eligible:
        return "anonymous_live_then_post_session_diarization"
    return min(eligible, key=lambda item: (item.speaker_lag_p95, item.rtf)).strategy
