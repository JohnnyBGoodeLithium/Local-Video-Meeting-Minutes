"""Synthetic transcript failures: bounded repair, split checkpoints and cancellation."""
import json
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
import translation_service as t


def ids(messages):
    return re.findall(r"\[需翻译 (T\d+)\]", messages[-1]["content"])


def reply(selected):
    return json.dumps({"translations": [
        {"id": tid, "translated_text": "Synthetic translated statement."}
        for tid in reversed(selected)]})


with tempfile.TemporaryDirectory(prefix="transcript-batch-recovery-") as temp:
    root = Path(temp)
    turns = [{"speaker": "Instructor Example", "text": "这是一条虚构发言。"} for _ in range(10)]
    def fixture(name):
        d = root / name
        d.mkdir()
        (d / "transcript.spk.json").write_text(json.dumps(turns, ensure_ascii=False))
        return d

    calls = []
    def split_model(messages, **kwargs):
        selected = ids(messages)
        calls.append(selected)
        return '{}' if len(selected) > 3 else reply(selected)
    d = fixture("split")
    source = (d / "transcript.spk.json").read_bytes()
    saved = []
    with patch.object(t.assistant, "_chat", side_effect=split_model):
        result = t.translate_transcript(d, "Synthetic", {}, target="en",
                                        on_progress=lambda n, total: saved.append(n))
    assert result["status"] == "complete" and len(result["turns"]) == 10
    assert list(map(len, calls)) == [10, 10, 3, 3, 3, 1]
    assert all(n in saved for n in [3, 6, 9, 10])
    assert (d / "transcript.spk.json").read_bytes() == source

    d = fixture("partial")
    def fail_later(messages, **kwargs):
        selected = ids(messages)
        return reply(selected) if selected == ["T000001", "T000002", "T000003"] else '{}'
    with patch.object(t.assistant, "_chat", side_effect=fail_later) as model:
        try:
            t.translate_transcript(d, "Synthetic", {}, target="en")
            raise AssertionError("invalid fragment accepted")
        except t.TranslationError:
            assert model.call_count == 5
    partial = json.loads(t.sidecar_path(d, "en").read_text())
    assert partial["status"] == "failed" and len(partial["turns"]) == 3
    resumed = []
    def complete(messages, **kwargs):
        selected = ids(messages)
        resumed.extend(selected)
        return reply(selected)
    with patch.object(t.assistant, "_chat", side_effect=complete):
        result = t.translate_transcript(d, "Synthetic", {}, target="en")
    assert result["status"] == "complete"
    assert resumed == [f"T{i:06}" for i in range(4, 11)]

    d = fixture("transport")
    with patch.object(t.assistant, "_chat", side_effect=t.assistant.AssistantUnavailable("offline")) as model:
        try:
            t.translate_transcript(d, "Synthetic", {}, target="en")
            raise AssertionError("transport error swallowed")
        except t.assistant.AssistantUnavailable:
            assert model.call_count == 1

    d = fixture("truncated")
    attempts = []
    def truncated(messages, **kwargs):
        selected = ids(messages)
        attempts.append(selected)
        if len(selected) > 3:
            raise t.assistant.AssistantInvalidOutput("truncated")
        return reply(selected)
    with patch.object(t.assistant, "_chat", side_effect=truncated):
        assert t.translate_transcript(d, "Synthetic", {}, target="en")["status"] == "complete"
    assert len(attempts) == 6

    d = fixture("cancel")
    cancelled = False
    def cancel(messages, **kwargs):
        global cancelled
        cancelled = True
        return '{}'
    with patch.object(t.assistant, "_chat", side_effect=cancel) as model:
        try:
            t.translate_transcript(d, "Synthetic", {}, target="en", should_cancel=lambda: cancelled)
            raise AssertionError("cancel ignored")
        except t.TranslationCancelled:
            assert model.call_count == 1
    assert json.loads(t.sidecar_path(d, "en").read_text())["status"] == "cancelled"

    for invalid in [None, {}, [{"id": []}], [{"id": "T999999", "translated_text": "wrong"}],
                    [{"id": "T000001", "translated_text": 42}],
                    [{"id": "T000001", "translated_text": "x"}] * 2]:
        with patch.object(t.assistant, "_chat", return_value=json.dumps({"translations": invalid})):
            try:
                t._translate_batch([0], turns, "Synthetic", {}, False, target="en")
                raise AssertionError("invalid ID/text contract accepted")
            except t.TranslationError:
                pass
    with patch.object(t.assistant, "_chat", return_value=reply(["T000001", "T000002", "T000003"])):
        selected = t._translate_batch([0], turns, "Synthetic", {}, False, target="en")
        assert set(selected) == {0}, "context translations must never be persisted"
    long_turns = [{"text": "虚构讲解内容。" * 300}]
    with patch.object(t.assistant, "_chat", side_effect=lambda messages, **kw: reply(ids(messages))) as model:
        t._translate_batch([0], long_turns, "Synthetic", {}, False, target="en")
    assert 4000 < model.call_args.kwargs["max_tokens"] <= 8192

print("Transcript batches: bounded retry/split, durable fragments, transport and cancellation passed")

with tempfile.TemporaryDirectory(prefix='evidence-translation-') as temp:
    root = Path(temp)
    evidence = {'claims': [{'id': 'C001', 'text': '这是一条虚构结论。',
                           'status': 'proposal', 'turn_ids': ['T001'], 'section': '示例章节'}]}
    source = root / 'minutes.evidence.json'
    source.write_text(json.dumps(evidence))
    before = source.read_bytes()
    with patch.object(t.assistant, '_chat', side_effect=lambda messages, **kw: reply(ids(messages))):
        result = t.translate_evidence(root, 'Synthetic', evidence, target='en')
    assert result['status'] == 'complete' and len(result['texts']) == 2
    assert source.read_bytes() == before
    assert 'C001' not in result['texts'] and 'proposal' not in result['texts']
    with patch.object(t.assistant, '_chat', side_effect=AssertionError('cached evidence called model')):
        assert t.translate_evidence(root, 'Synthetic', evidence, target='en')['status'] == 'complete'
    source.write_text(json.dumps({**evidence, 'revision': 2}))
    with patch.object(t.assistant, '_chat', side_effect=lambda messages, **kw: reply(ids(messages))) as model:
        t.translate_evidence(root, 'Synthetic', evidence, target='en')
        assert model.call_count == 1
print('Evidence translation: display-only, revision-bound cache, canonical unchanged passed')
