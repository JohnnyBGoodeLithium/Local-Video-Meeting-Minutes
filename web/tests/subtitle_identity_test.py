#!/usr/bin/env python3
"""字幕人物边界：真实 Web bundle 与离线导出，全合成、零模型、零浏览器。"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "bin"), str(ROOT / "web")]

import deps  # noqa: E402
import export_meeting  # noqa: E402
from meeting_artifact import speaker_navigation  # noqa: E402
from meeting_core.media_captions import parse_caption_bytes  # noqa: E402
from meeting_core.source_info import transcript_identity_context  # noqa: E402
from routers import meetings  # noqa: E402
from teams_transcript import parse_vtt  # noqa: E402
from video_minutes import subtitle_turns  # noqa: E402


RAW_CAPTIONS = """WEBVTT

00:00:00.000 --> 00:00:04.000
<v Raw Caption Alpha>A synthetic opening without reliable audio identity.</v>

00:00:04.000 --> 00:00:08.000
<v Raw Caption Beta>A synthetic cue with a session voice cluster.</v>

00:00:08.000 --> 00:00:12.000
<v Raw Caption Gamma>A synthetic cue with a verified voice binding.</v>
"""


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def snapshot(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes()
            for p in path.rglob("*") if p.is_file()}


class SubtitleIdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="subtitle-identity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mdir = self.root / "meetings" / "synthetic-caption-review"
        self.mdir.mkdir(parents=True)
        self.bank = self.root / "bank"
        self.bank.mkdir()
        write_json(self.bank / "bank.json", {
            "persons": [{"id": "p_verified", "name": "Verified Example"}],
            "voices": [{"id": "v_verified", "person_id": "p_verified"},
                       {"id": "v_session", "person_id": None}],
        })
        (self.mdir / "minutes.md").write_text(
            "# Synthetic review\n\nThis fixture contains fictional examples.\n",
            encoding="utf-8")
        (self.mdir / "source.vtt").write_text(RAW_CAPTIONS, encoding="utf-8")
        (self.mdir / "source_captions").mkdir()
        (self.mdir / "source_captions" / "attempt-01.vtt").write_text(
            RAW_CAPTIONS, encoding="utf-8")
        write_json(self.mdir / "subtitle.cues.json", {"private_fixture": True})
        write_json(self.mdir / "meta.json", {
            "content_type": "media", "title": "Synthetic caption review"})

        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.dict(os.environ, {
            "MEETING_DATA_ROOT": str(self.root),
            "MEETING_WEB_BANK": str(self.bank),
            "MEETING_WEB_JOBS": str(self.root / "jobs"),
            "MEETING_WEB_DRYRUN": "1",
        }))
        # Imported dependency functions retain deps' globals, so isolate both.
        for module in (deps, meetings):
            stack.enter_context(patch.object(module, "MEETINGS", self.mdir.parent))
            stack.enter_context(patch.object(module, "BANK_DIR", self.bank))
            stack.enter_context(patch.object(module, "DRY_RUN", True))
        stack.enter_context(patch.object(meetings, "_mdir", return_value=self.mdir))
        stack.enter_context(patch.object(meetings, "JOBS", {}))
        stack.enter_context(patch.object(
            meetings.EXEC, "submit", side_effect=AssertionError("unexpected background work")))
        stack.enter_context(patch.object(
            export_meeting.subprocess, "run", side_effect=AssertionError("unexpected process")))
        stack.enter_context(patch.object(
            export_meeting.subprocess, "Popen", side_effect=AssertionError("unexpected process")))

    def write_fixture(self, origin: str | None, turns: list[dict], *, kind="human"):
        source = {
            # A retained extension cannot override explicit native_subtitle/local_asr.
            "transcript_format": "vtt",
            "source_info": {
                "schema": "media-source/v1", "kind": "public_url",
                "title": "Synthetic caption review", "platform": "Example",
                "captions": {
                    "schema": "media-captions/v1", "source": "native_subtitle",
                    "kind": kind, "language": "en", "original_language": "en",
                    "language_evidence": "metadata", "timestamp_source": "subtitle_cues",
                    "selection_reason": "original_human" if kind == "human" else "original_automatic",
                    "raw_sha256": hashlib.sha256(RAW_CAPTIONS.encode()).hexdigest(),
                    "cue_count": 3,
                    "download_url": "https://example.invalid/private-caption-token",
                },
            },
        }
        if origin is not None:
            source["transcript_source"] = origin
        write_json(self.mdir / "source.json", source)
        write_json(self.mdir / "transcript.spk.json", turns)
        return source

    def projections(self):
        before = snapshot(self.mdir)
        bank_before = snapshot(self.bank)
        bundle = meetings.get_bundle(self.mdir.name)
        out = self.root / "synthetic.meetingpack.zip"
        result = export_meeting.export_meeting(
            self.mdir, out, bank_dir=self.bank, media_mode="none")
        self.assertEqual(result["media"]["mode"], "none")
        self.assertFalse(result["media"]["included"])
        with zipfile.ZipFile(out) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files["assets/manifest.json"])
        viewer_html = files["viewer.html"].decode("utf-8")
        embedded = re.search(
            r'<script id="meeting-data" type="application/json">(.*?)</script>',
            viewer_html, re.S)
        self.assertIsNotNone(embedded, "export must contain actual embedded Viewer data")
        viewer = json.loads(embedded.group(1))
        self.assertEqual(viewer["speaker_navigation"], bundle["speaker_navigation"])
        self.assertEqual(json.loads(files["assets/transcript.json"]), bundle["transcript"])
        self.assertEqual(manifest["source_info"], viewer["source_info"])
        self.assertEqual(viewer["source_info"], bundle["source_info"])
        self.assertEqual(snapshot(self.mdir), before, "projections must not rewrite canonical files")
        self.assertEqual(snapshot(self.bank), bank_before, "projections must not update identity")
        self.assertFalse(any(Path(name).suffix == ".vtt" or "source_captions" in name
                             or Path(name).name == "subtitle.cues.json" for name in files))
        self.assertNotIn("private-caption-token", json.dumps(bundle))
        for name, contents in files.items():
            self.assertNotIn(b"private-caption-token", contents, name)
        return bundle, viewer, files

    def assert_navigation(self, payload, expected):
        actual = {row["speaker"]: (row["identity_basis"], row["selectable"])
                  for row in payload["speaker_navigation"]}
        self.assertEqual(actual, expected)

    def test_native_subtitles_in_real_web_and_export_projections(self):
        for kind in ("human", "automatic"):
            with self.subTest(kind=kind):
                cues = parse_caption_bytes(RAW_CAPTIONS.encode(), duration=12)
                turns = subtitle_turns(
                    cues, [(4, 8, "cluster_a"), (8, 12, "cluster_b")],
                    {"cluster_a": "说话人1", "cluster_b": "Verified Example"},
                    language="en", kind=kind)
                turns[1]["voice"] = "v_session"
                turns[2]["voice"] = "v_verified"
                self.write_fixture("native_subtitle", turns, kind=kind)
                bundle, viewer, files = self.projections()
                self.assertEqual(bundle["transcript_source"], "native_subtitle")
                self.assert_navigation(bundle, {
                    "说话人未知": ("insufficient_voice_sample", False),
                    "说话人1": ("session_voice_cluster", True),
                    "Verified Example": ("verified_voice_binding", True),
                })
                self.assertEqual(viewer["source_info"]["captions"]["kind"], kind)
                self.assertTrue(all(t["text_review_status"] != "human_corrected" for t in turns))
                self.assertNotIn("Raw Caption", json.dumps(bundle))
                for name, contents in files.items():
                    self.assertNotIn(b"Raw Caption", contents, name)

    def test_explicit_origin_wins_over_retained_vtt_without_turn_provenance(self):
        # Older canonical turns may lack per-turn source metadata. This catches
        # caller regressions even when the core's provenance defense is present.
        turns = [{"start": 0, "end": 4, "text": "Synthetic unnamed cue.",
                  "speaker": "Unverified Example"},
                 {"start": 4, "end": 8, "text": "Synthetic clustered cue.",
                  "speaker": "Session Example", "voice": "v_session"},
                 {"start": 8, "end": 12, "text": "Synthetic verified cue.",
                  "speaker": "Verified Example", "voice": "v_verified"}]
        for origin in ("native_subtitle", "local_asr"):
            with self.subTest(origin=origin):
                self.write_fixture(origin, turns)
                bundle, _, _ = self.projections()
                self.assertEqual(bundle["transcript_source"], origin)
                self.assert_navigation(bundle, {
                    "Unverified Example": ("insufficient_voice_sample", False),
                    "Session Example": ("session_voice_cluster", True),
                    "Verified Example": ("verified_voice_binding", True),
                })

    def test_genuine_external_teams_labels_remain_selectable(self):
        (self.mdir / "subtitle.cues.json").unlink()
        turns = [{"start": cue["start"], "end": cue["end"], "text": cue["text"],
                  "speaker": cue["name"]} for cue in parse_vtt(self.mdir / "source.vtt")]
        turns[-1]["voice"] = "v_verified"
        for origin in ("external", None):
            with self.subTest(origin=origin):
                source = self.write_fixture(origin, turns)
                source["source_info"].pop("captions")
                write_json(self.mdir / "source.json", source)
                bundle, _, _ = self.projections()
                self.assertEqual(bundle["transcript_source"], "external")
                self.assert_navigation(bundle, {
                    "Raw Caption Alpha": ("imported_transcript_label", True),
                    "Raw Caption Beta": ("imported_transcript_label", True),
                    "Raw Caption Gamma": ("verified_voice_binding", True),
                })

    def test_core_rejects_untrusted_labels_even_if_caller_passes_vtt(self):
        for provenance in ({"text_source": "native_subtitle"}, {"speaker_source": "unknown"}):
            for extension in ("vtt", ".docx", "DOCX"):
                with self.subTest(provenance=provenance, extension=extension):
                    turns = [{"speaker": "Unverified Example", **provenance},
                             {"speaker": "Session Example", "voice": "v_session", **provenance},
                             {"speaker": "Verified Example", "voice": "v_verified", **provenance},
                             {"speaker": "说话人未知"}]
                    rows = speaker_navigation(turns, [{"speaker": "Verified Example",
                                                       "person_id": "p_verified"}], extension)
                    self.assert_navigation({"speaker_navigation": rows}, {
                        "Unverified Example": ("insufficient_voice_sample", False),
                        "Session Example": ("session_voice_cluster", True),
                        "Verified Example": ("verified_voice_binding", True),
                        "说话人未知": ("insufficient_voice_sample", False),
                    })

    def test_source_identity_context_preserves_explicit_origin(self):
        for origin in ("native_subtitle", "local_asr"):
            for extension in (None, "vtt", ".DOCX"):
                with self.subTest(origin=origin, extension=extension):
                    self.assertEqual(transcript_identity_context(self.mdir, {
                        "transcript_source": origin, "transcript_format": extension}),
                        (origin, ""))
        self.assertEqual(transcript_identity_context(self.mdir, {}), ("native_subtitle", ""))
        (self.mdir / "subtitle.cues.json").unlink()
        self.assertEqual(transcript_identity_context(self.mdir, {
            "source_info": {"captions": {"source": "native_subtitle"}}}),
            ("native_subtitle", ""))
        self.assertEqual(transcript_identity_context(self.mdir, {}), ("external", "vtt"))
        (self.mdir / "source.vtt").unlink()
        self.assertEqual(transcript_identity_context(self.mdir, {}), ("local_asr", ""))
        (self.mdir / "source.docx").write_bytes(b"synthetic document placeholder")
        self.assertEqual(transcript_identity_context(self.mdir, {}), ("external", "docx"))


if __name__ == "__main__":
    unittest.main()
