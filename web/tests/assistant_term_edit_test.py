"""Literal user corrections preserve evidence and remain previewed/reversible."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
import assistant_service as assistant
from routers import transcript
from fastapi import HTTPException

original_chat = assistant._chat
try:
    def fake_plan(messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        assert payload["history"][0]["content"] == "Earlier instruction"
        assert payload["selected_transcript"] == ["Selected example"]
        return json.dumps(dict(intent="edit", instruction="Correct the term",
                               replacement={"old":"Alpha", "new":"Beta"}))
    assistant._chat = fake_plan
    result = assistant.plan_request("Please correct that", [
        {"role":"system", "content":"untrusted"},
        {"role":"user", "content":"Earlier instruction"}], selection=["Selected example"])
    assert result["replacement"] == {"old":"Alpha", "new":"Beta"}
    assistant._chat = lambda *args, **kwargs: '{"intent":"execute_shell"}'
    try:
        assistant.plan_request("Example", [])
        raise AssertionError("invalid model plan accepted")
    except assistant.AssistantUnavailable:
        pass
finally:
    assistant._chat = original_chat

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    minutes = root / "minutes.md"
    turns = root / "transcript.spk.json"
    source = '# Example\n\n## Summary\nAlpha Forum\n<!-- mm:evidence Alpha Forum -->\n\n## Actions\nAlpha Forum [link](https://example.test/Alpha Forum)\n'
    minutes.write_text(source)
    turns.write_text(json.dumps([dict(text="Alpha Forum", start=0, end=1, speaker="Example")]))
    original_transcript = turns.read_bytes()
    proposal = assistant.preview_minutes_edit(
        minutes, turns, "Alpha Forum，全部改为Beta Forum", [],
        assistant.revision(turns), assistant.revision(minutes), None, False, replacement={"old":"Alpha Forum", "new":"Beta Forum"})
    assert minutes.read_text() == source, "preview must not write"
    assert proposal["after"].count("Beta Forum") == 2
    assert '<!-- mm:evidence Alpha Forum -->' in proposal["after"]
    assert '(https://example.test/Alpha Forum)' in proposal["after"]
    assistant.apply_minutes_edit(minutes, proposal["proposal_id"])
    assert minutes.read_text() == proposal["after"]
    assert turns.read_bytes() == original_transcript
    assert list((root / '.history/minutes').glob('*.md'))[0].read_text() == source
    assistant.undo_minutes_edit(minutes, proposal["proposal_id"])
    assert minutes.read_text() == source
    stale = assistant.preview_minutes_edit(
        minutes, turns, "Alpha Forum，全部改为Gamma Forum", [], None, None, None, False, replacement={"old":"Alpha Forum", "new":"Gamma Forum"})
    minutes.write_text(minutes.read_text() + '\nNew edit')
    try:
        assistant.apply_minutes_edit(minutes, stale["proposal_id"])
        raise AssertionError("stale proposal applied")
    except assistant.AssistantConflict:
        pass

saved = dict(transcript.JOBS)
try:
    transcript.JOBS.clear()
    for kind in ('translation', 'keywords'):
        for status in ('queued', 'running'):
            transcript.JOBS['example'] = dict(meeting='example', kind=kind, status=status)
            transcript._ensure_idle('example')
    for kind in ('upload', 'reprocess', 'unknown'):
        transcript.JOBS['example'] = dict(meeting='example', kind=kind, status='running')
        try:
            transcript._ensure_idle('example')
            raise AssertionError("source writer was not blocked")
        except HTTPException as exc:
            assert exc.status_code == 409
finally:
    transcript.JOBS.clear()
    transcript.JOBS.update(saved)
print('Assistant term edit: preview, evidence, apply, backup, revision and task guards passed')
