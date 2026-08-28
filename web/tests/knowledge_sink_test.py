#!/usr/bin/env python3
"""KnowledgeSink revision 幂等、原位文字更新与图文安全替换。"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "bin")]

from meeting_core.knowledge_sink import (  # noqa: E402
    KnowledgeArtifact, KnowledgeTarget, PublishResult, load_publications, publish,
)


class FakeSink:
    provider = "fake"

    def __init__(self):
        self.calls = []
        self.number = 0

    def create(self, target, artifact):
        self.number += 1
        self.calls.append(("create", target.id, artifact.profile, artifact.revision))
        return PublishResult(f"doc-{self.number}", "processing")

    def update(self, target, document_id, artifact):
        self.calls.append(("update", document_id, artifact.profile, artifact.revision))
        return PublishResult(document_id, "processing")

    def delete(self, document_id):
        self.calls.append(("delete", document_id))


def artifact(profile: str, revision: str) -> KnowledgeArtifact:
    return KnowledgeArtifact(
        "Meeting · Example", profile, "meeting", revision,
        f"example-{revision}.{'html' if profile == 'kb-html' else 'md'}",
        "text/html" if profile == "kb-html" else "text/markdown", b"safe body")


def main():
    with tempfile.TemporaryDirectory(prefix="knowledge-sink-test-") as temp:
        mdir = Path(temp)
        target = KnowledgeTarget("kb-test-001", "Test KB")
        sink = FakeSink()

        first = publish(mdir, target, artifact("kb", "rev-a"), sink)
        assert first["outcome"] == "created"
        assert sink.calls == [("create", "kb-test-001", "kb", "rev-a")]

        same = publish(mdir, target, artifact("kb", "rev-a"), sink)
        assert same["outcome"] == "already_current" and len(sink.calls) == 1

        updated = publish(mdir, target, artifact("kb", "rev-b"), sink)
        assert updated["outcome"] == "updated"
        assert sink.calls[-1] == ("update", "doc-1", "kb", "rev-b")

        visual = publish(mdir, target, artifact("kb-html", "rev-c"), sink)
        assert visual["document_id"] == "doc-2"
        assert sink.calls[-2:] == [
            ("create", "kb-test-001", "kb-html", "rev-c"),
            ("delete", "doc-1"),
        ]

        back_to_text = publish(mdir, target, artifact("kb", "rev-d"), sink)
        assert back_to_text["document_id"] == "doc-3"
        assert sink.calls[-2:] == [
            ("create", "kb-test-001", "kb", "rev-d"),
            ("delete", "doc-2"),
        ]

        ledger = load_publications(mdir)
        assert ledger["schema"] == "knowledge-publications/v1"
        serialized = json.dumps(ledger)
        assert "safe body" not in serialized and "api_key" not in serialized
        assert ledger["publications"][0]["artifact_revision"] == "rev-d"
    print("knowledge sink: revision idempotency/replacement passed")


if __name__ == "__main__":
    main()
