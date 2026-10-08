#!/usr/bin/env python3
"""字幕优先集成回归：虚构媒体与音轨，不下载、不调用模型或外部程序。"""

from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "bin"), str(ROOT / "web")]

import media_url  # noqa: E402
import video_minutes  # noqa: E402
import job_recovery  # noqa: E402
from meeting_core.live.vtt import parse_webvtt_text  # noqa: E402
from meeting_core.media_captions import CaptionPreparation, parse_caption_file  # noqa: E402


CAPTIONS = """WEBVTT

00:00:00.000 --> 00:00:04.000
<v Avery Example>The synthetic introduction is here.</v>

00:00:04.000 --> 00:00:08.000
<v Blair Example>We compare the fictional examples.</v>

00:00:08.000 --> 00:00:12.000
This is the synthetic conclusion.
"""
TEXTS = ["The synthetic introduction is here.",
         "We compare the fictional examples.",
         "This is the synthetic conclusion."]
DIARIZATION = [(0.0, 4.0, "voice_a"), (4.0, 6.0, "voice_a"),
               (6.0, 8.0, "voice_b")]


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def write_wav(_source: Path, destination: Path, *, seconds: int = 12) -> None:
    with wave.open(str(destination), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * (16000 * seconds))


class PipelineFixture:
    """Keep parsing/materialization real; replace every compute/process boundary."""

    def __init__(self, root: Path, *, raw: str = CAPTIONS, kind: str = "human"):
        self.root = root
        self.mdir = root / "meetings" / "synthetic-subtitles"
        self.mdir.mkdir(parents=True)
        self.media = root / "synthetic.mp4"
        self.media.write_bytes(b"fictional-video-placeholder")
        self.subtitle = root / "captions.vtt"
        self.subtitle.write_text(raw, encoding="utf-8")
        self.kind = kind
        self.provenance = {"schema": "media-captions/v1", "source": "native_subtitle",
                           "language": "en", "kind": kind,
                           "original_language": "en", "selection_reason": "original_language"}
        self.source_info = {"schema": "media-source/v1", "kind": "public_url",
                            "title": "Synthetic subtitle fixture", "platform": "Example",
                            "canonical_url": "https://example.invalid/synthetic",
                            "captions": self.provenance}
        write_json(self.mdir / "source.json", {"source_info": self.source_info,
                                                "preserved_extension": {"synthetic": True}})
        self.argv = ["video_minutes.py", str(self.media), "--meeting-dir", str(self.mdir),
                     "--subtitle", str(self.subtitle), "--subtitle-language", "en",
                     "--subtitle-kind", kind, "--media", "--no-vl"]
        self.processes = []
        self.extract_audio = Mock(side_effect=write_wav)
        self.configure_extraction = Mock(wraps=video_minutes.configure_extraction)
        self.popen = Mock(side_effect=self._popen)
        self.run = Mock(side_effect=self._run)
        self.diarize = Mock(return_value=(DIARIZATION, {"voice_a": [1.0], "voice_b": [2.0]}))
        self.enroll = Mock(side_effect=lambda vectors, *_args: (
            {}, {name: "synthetic-voice-a" for name in vectors}, 0, len(vectors)))
        self.generate = Mock(side_effect=self._generate)
        self.bind_review = Mock(return_value=None)
        self.output = io.StringIO()

    def _popen(self, command, **_kwargs):
        self.processes.append(command)
        if Path(command[1]).name != "transcribe.py":
            raise AssertionError(f"Unexpected subprocess: {command[1]}")
        write_json(self.mdir / "stamps.json", {
            "language": "English", "text": "Synthetic local ASR fallback.",
            "time_stamps": [{"text": "Synthetic local ASR fallback.",
                             "start_time": 0.0, "end_time": 12.0}]})
        (self.mdir / "transcript.txt").write_text("Synthetic local ASR fallback.\n", encoding="utf-8")
        return SimpleNamespace(wait=Mock(return_value=0))

    def _run(self, command, **_kwargs):
        # materialize_source attempts a reflink; exercise its real copy fallback.
        if command[0] == "cp":
            return SimpleNamespace(returncode=1)
        script = Path(command[1]).name
        self.processes.append(command)
        if script == "diarize.py":
            write_json(self.mdir / "transcript.spk.json", [{
                "start": 0.0, "end": 12.0, "text": "Synthetic local ASR fallback.",
                "speaker": "说话人1"}])
        elif script != "voice_tool.py":
            raise AssertionError(f"Unexpected subprocess: {script}")
        return SimpleNamespace(returncode=0)

    @staticmethod
    def _generate(mdir: Path, **_kwargs):
        output = mdir / "minutes.md"
        output.write_text("# Synthetic summary\n", encoding="utf-8")
        return output, {"pages": 0, "vl_pages": 0, "chars": 20}

    def invoke(self) -> int:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", self.argv))
            stack.enter_context(patch.dict(os.environ, {"MEETING_DATA_ROOT": str(self.root)}))
            for name, replacement in {
                "extract_audio": self.extract_audio,
                "configure_extraction": self.configure_extraction,
                "prepare_stage": Mock(),
                "resolve_pyannote_model": Mock(return_value=Path("synthetic-model")),
                "diarize": self.diarize,
                "enroll": self.enroll,
                "generate_minutes": self.generate,
                "extract_pages": Mock(return_value=[]),
                "bind_review_to_transcript": self.bind_review,
                "configured_bank_dir": Mock(return_value=self.root / "bank"),
                "safe_harvest_screen_candidates": Mock(return_value={
                    "state": "skipped", "added": 0, "updated": 0}),
            }.items():
                stack.enter_context(patch.object(video_minutes, name, replacement))
            stack.enter_context(patch.object(video_minutes.subprocess, "Popen", self.popen))
            stack.enter_context(patch.object(video_minutes.subprocess, "run", self.run))
            for name in ("generate_voice_draft", "update", "begin_visual_enrichment", "finalize"):
                stack.enter_context(patch.object(video_minutes.meeting_generation, name,
                                                 Mock(return_value=True)))
            stack.enter_context(patch.object(video_minutes.meeting_topic_map, "generate_for_pipeline"))
            stack.enter_context(redirect_stdout(self.output))
            stack.enter_context(redirect_stderr(self.output))
            return video_minutes.main()


class SubtitlePipelineTest(unittest.TestCase):
    def assert_source_preserved(self, fixture: PipelineFixture) -> dict:
        source = read_json(fixture.mdir / "source.json")
        for key, value in fixture.source_info.items():
            if key != "captions":
                self.assertEqual(source["source_info"][key], value)
        captions = source["source_info"]["captions"]
        self.assertEqual(captions["source"], "native_subtitle")
        self.assertEqual(captions["kind"], fixture.kind)
        self.assertEqual(captions["language"], "en")
        self.assertEqual(captions["original_language"], "en")
        self.assertEqual(captions["raw_sha256"], hashlib.sha256(fixture.subtitle.read_bytes()).hexdigest())
        self.assertEqual(source["preserved_extension"], {"synthetic": True})
        return source

    def test_valid_captions_skip_asr_and_preserve_audio_identity_boundary(self):
        for kind, review in (("human", "platform_provided"), ("automatic", "automatic")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix="subtitle-pipeline-") as tmp:
                fixture = PipelineFixture(Path(tmp), kind=kind)
                self.assertEqual(fixture.invoke(), 0)
                fixture.popen.assert_not_called()
                fixture.diarize.assert_called_once_with(fixture.mdir / "audio.wav", None)
                fixture.bind_review.assert_not_called()
                self.assertFalse(any(Path(command[1]).name in {"diarize.py", "teams_minutes.py"}
                                     for command in fixture.processes))
                self.assertFalse((fixture.mdir / "stamps.json").exists())
                self.assertEqual((fixture.mdir / "source.vtt").read_bytes(),
                                 fixture.subtitle.read_bytes())
                turns = read_json(fixture.mdir / "transcript.spk.json")
                self.assertEqual([(item["start"], item["end"], item["text"]) for item in turns],
                                 [(0.0, 4.0, TEXTS[0]), (4.0, 8.0, TEXTS[1]), (8.0, 12.0, TEXTS[2])])
                self.assertEqual([item["speaker_source"] for item in turns],
                                 ["local_diarization", "unknown", "unknown"])
                self.assertEqual([item["speaker"] for item in turns],
                                 ["说话人1", "说话人未知", "说话人未知"])
                self.assertEqual([item["voice"] for item in turns], ["synthetic-voice-a", None, None])
                self.assertEqual(set(fixture.enroll.call_args.args[0]), {"说话人1"})
                for item in turns:
                    self.assertEqual(item["text_source"], "native_subtitle")
                    self.assertEqual(item["timestamp_source"], "subtitle_cues")
                    self.assertEqual(item["language"], "en")
                    self.assertEqual(item["text_review_status"], review)
                    self.assertNotIn("human_corrected", item.values())
                cues = read_json(fixture.mdir / "subtitle.cues.json")
                self.assertEqual([item["text"] for item in cues], TEXTS)
                self.assertTrue(all(item["speaker"] is None and item["speaker_source"] == "unknown"
                                    for item in cues))
                self.assertTrue(all(item["provisional"] is False for item in cues))
                self.assertTrue(all(item["text_review_status"] == review for item in cues))
                self.assertEqual((fixture.mdir / "transcript.txt").read_text(encoding="utf-8"),
                                 "\n".join(TEXTS) + "\n")
                timestamped = (fixture.mdir / "transcript.ts.md").read_text(encoding="utf-8")
                self.assertIn("[00:04] " + TEXTS[1], timestamped)
                source = self.assert_source_preserved(fixture)
                self.assertEqual(source["transcript_source"], "native_subtitle")
                self.assertEqual(source["external_transcript_status"], "used")
                for name in ("transcript.spk.json", "transcript.spk.md", "subtitle.cues.json"):
                    canonical = (fixture.mdir / name).read_text(encoding="utf-8")
                    self.assertNotIn("Avery Example", canonical)
                    self.assertNotIn("Blair Example", canonical)
                self.assertNotIn(TEXTS[0], fixture.output.getvalue())

    def test_candidate_limit_remains_visible_after_pipeline_validation(self):
        with tempfile.TemporaryDirectory(prefix="subtitle-limit-") as tmp:
            fixture = PipelineFixture(Path(tmp), kind="automatic")
            source = read_json(fixture.mdir / "source.json")
            source["source_info"]["captions"].update(
                fallback_reason="candidate_limit", original_language="en-us")
            write_json(fixture.mdir / "source.json", source)
            self.assertEqual(fixture.invoke(), 0)
            fixture.popen.assert_not_called()
            from meeting_core.source_info import load_source_info
            shared = load_source_info(fixture.mdir)["captions"]
            self.assertEqual(shared["source"], "native_subtitle")
            self.assertEqual(shared["kind"], "automatic")
            self.assertEqual(shared["original_language"], "en-us")
            self.assertEqual(shared["fallback_reason"], "candidate_limit")

    def test_invalid_captions_fall_back_to_local_asr(self):
        invalid = {
            "empty": "WEBVTT\n\n",
            "broken": "WEBVTT\n\ninvalid timing\nSynthetic unusable text.\n",
            "reverse_time": "WEBVTT\n\n00:00:09.000 --> 00:00:01.000\nSynthetic invalid cue.\n",
        }
        for name, raw in invalid.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="subtitle-fallback-") as tmp:
                fixture = PipelineFixture(Path(tmp), raw=raw)
                self.assertEqual(fixture.invoke(), 0)
                fixture.popen.assert_called_once()
                fixture.diarize.assert_called_once()
                fixture.bind_review.assert_called_once_with(fixture.mdir)
                self.assertTrue((fixture.mdir / "stamps.json").is_file())
                self.assertFalse((fixture.mdir / "subtitle.cues.json").exists())
                self.assertEqual((fixture.mdir / "source.vtt").read_bytes(), raw.encode("utf-8"))
                source = read_json(fixture.mdir / "source.json")
                self.assertEqual(source["transcript_source"], "local_asr")
                self.assertEqual(source["external_transcript_status"], "rejected")
                self.assertEqual(source["source_info"]["captions"]["source"], "local_asr")
                self.assertTrue(source["source_info"]["captions"]["fallback_reason"])
                self.assertEqual(source["source_info"]["captions"]["timestamp_source"], "asr")
                self.assertEqual(source["source_info"]["captions"]["selection_reason"], "asr_fallback")
                self.assertNotIn("kind", source["source_info"]["captions"])
                self.assertEqual(source["source_info"]["title"], fixture.source_info["title"])
                self.assertEqual(read_json(fixture.mdir / "transcript.spk.json")[0]["text"],
                                 "Synthetic local ASR fallback.")

    def test_model_failures_do_not_erase_caption_provenance(self):
        for boundary in ("diarize", "generate"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(prefix="subtitle-failure-") as tmp:
                fixture = PipelineFixture(Path(tmp))
                getattr(fixture, boundary).side_effect = RuntimeError("synthetic model unavailable")
                with self.assertRaisesRegex(RuntimeError, "synthetic model unavailable"):
                    fixture.invoke()
                fixture.popen.assert_not_called()
                source = self.assert_source_preserved(fixture)
                self.assertEqual(source["transcript_source"], "native_subtitle")
                self.assertEqual(source["preserved_extension"], {"synthetic": True})
                self.assertEqual((fixture.mdir / "source.vtt").read_bytes(), fixture.subtitle.read_bytes())
                self.assertFalse((fixture.mdir / "stamps.json").exists())
                if boundary == "generate":
                    self.assertEqual([turn["text"] for turn in read_json(
                        fixture.mdir / "transcript.spk.json")], TEXTS)

    def test_subtitle_recovery_reuses_verified_raw_and_rejects_corrupt_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="subtitle-recovery-") as tmp:
            fixture = PipelineFixture(Path(tmp), kind="automatic")
            fixture.diarize.side_effect = RuntimeError("synthetic interrupted diarization")
            with self.assertRaisesRegex(RuntimeError, "interrupted diarization"):
                fixture.invoke()
            fixture.popen.assert_not_called()
            self.assertFalse((fixture.mdir / "stamps.json").exists())
            command = job_recovery.build_speaker_resume_command(fixture.mdir)
            self.assertEqual(Path(command[1]).name, "video_minutes.py")
            self.assertEqual(command[command.index("--subtitle") + 1], str(fixture.mdir / "source.vtt"))
            self.assertEqual(command[command.index("--subtitle-language") + 1], "en")
            self.assertEqual(command[command.index("--subtitle-kind") + 1], "automatic")
            self.assertEqual(command[command.index("--subtitle-sha256") + 1],
                             hashlib.sha256(fixture.subtitle.read_bytes()).hexdigest())
            self.assertNotIn("--reuse-asr", command)

            # An unrelated ASR artifact must not bypass a rejected subtitle checkpoint.
            write_json(fixture.mdir / "stamps.json", {"time_stamps": [{"synthetic": True}]})
            raw = fixture.mdir / "source.vtt"
            raw.write_text(CAPTIONS.replace("introduction", "changed introduction"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid_subtitle_checkpoint"):
                job_recovery.build_speaker_resume_command(fixture.mdir)
            # Hash integrity alone is insufficient: the stored cue document must still parse.
            raw.write_text("WEBVTT\n\n", encoding="utf-8")
            source = read_json(fixture.mdir / "source.json")
            source["source_info"]["captions"]["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
            write_json(fixture.mdir / "source.json", source)
            with self.assertRaisesRegex(ValueError, "invalid_subtitle_checkpoint"):
                job_recovery.build_speaker_resume_command(fixture.mdir)
            raw.write_bytes(fixture.subtitle.read_bytes())
            source["source_info"]["captions"]["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
            write_json(fixture.mdir / "source.json", source)
            for audio_bytes in (b"invalid synthetic audio", b"", b"RIFF"):
                with self.subTest(audio_bytes=audio_bytes):
                    (fixture.mdir / "audio.wav").write_bytes(audio_bytes)
                    with self.assertRaisesRegex(ValueError, "invalid_subtitle_checkpoint"):
                        job_recovery.build_speaker_resume_command(fixture.mdir)

    def test_queued_subtitle_resume_revalidates_hash_and_actual_duration_without_asr(self):
        for changed in ("raw_mutated", "raw_deleted", "audio_shorter"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory(prefix="subtitle-queued-") as tmp:
                fixture = PipelineFixture(Path(tmp))
                self.assertEqual(fixture.invoke(), 0)
                command = job_recovery.build_speaker_resume_command(fixture.mdir)
                fixture.argv = command[1:]
                raw = fixture.mdir / "source.vtt"
                expected_hash = command[command.index("--subtitle-sha256") + 1]
                self.assertEqual(expected_hash, hashlib.sha256(raw.read_bytes()).hexdigest())
                preserved = {name: (fixture.mdir / name).read_bytes() for name in (
                    "source.json", "transcript.spk.json", "transcript.spk.md",
                    "transcript.txt", "transcript.ts.md", "subtitle.cues.json", "minutes.md")}
                for mocked in (fixture.extract_audio, fixture.popen, fixture.run, fixture.diarize,
                               fixture.enroll, fixture.generate, fixture.bind_review):
                    mocked.reset_mock()
                if changed == "raw_mutated":
                    raw.write_text(CAPTIONS.replace("introduction", "changed introduction"), encoding="utf-8")
                elif changed == "raw_deleted":
                    raw.unlink()
                else:
                    # The queued hash still matches, but extraction now proves the
                    # media is too short. Strict recovery must not silently rerun ASR.
                    fixture.extract_audio.side_effect = lambda source, destination: write_wav(
                        source, destination, seconds=3)

                self.assertEqual(fixture.invoke(), 2)
                fixture.popen.assert_not_called()
                fixture.diarize.assert_not_called()
                fixture.enroll.assert_not_called()
                fixture.generate.assert_not_called()
                fixture.bind_review.assert_not_called()
                self.assertFalse((fixture.mdir / "stamps.json").exists())
                for name, previous_bytes in preserved.items():
                    self.assertEqual((fixture.mdir / name).read_bytes(), previous_bytes, name)
                if changed == "audio_shorter":
                    fixture.extract_audio.assert_called_once()
                    self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), expected_hash)
                else:
                    fixture.extract_audio.assert_not_called()
                    fixture.run.assert_not_called()

    def test_subtitle_replacement_is_rejected_before_existing_artifacts_change(self):
        for variant in ("different_valid", "different_invalid", "existing_invalid", "identical"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(prefix="subtitle-existing-") as tmp:
                fixture = PipelineFixture(Path(tmp))
                self.assertEqual(fixture.invoke(), 0)
                if variant == "different_valid":
                    fixture.subtitle.write_text(CAPTIONS.replace("introduction", "updated introduction"),
                                                encoding="utf-8")
                elif variant == "different_invalid":
                    fixture.subtitle.write_text("WEBVTT\n\n", encoding="utf-8")
                elif variant == "existing_invalid":
                    (fixture.mdir / "source.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
                preserved = snapshot_files(fixture.mdir)
                for mocked in (fixture.configure_extraction, fixture.extract_audio,
                               fixture.popen, fixture.run, fixture.diarize,
                               fixture.enroll, fixture.generate, fixture.bind_review):
                    mocked.reset_mock()
                result = fixture.invoke()
                fixture.popen.assert_not_called()
                if variant == "identical":
                    self.assertEqual(result, 0)
                    fixture.diarize.assert_called_once()
                    self.assertEqual((fixture.mdir / "source.vtt").read_bytes(), fixture.subtitle.read_bytes())
                else:
                    self.assertEqual(result, 2)
                    fixture.configure_extraction.assert_not_called()
                    fixture.extract_audio.assert_not_called()
                    fixture.run.assert_not_called()
                    fixture.diarize.assert_not_called()
                    fixture.enroll.assert_not_called()
                    fixture.generate.assert_not_called()
                    fixture.bind_review.assert_not_called()
                    self.assertEqual(snapshot_files(fixture.mdir), preserved)

    def test_recovery_rejects_ambiguous_subtitle_provenance_despite_stale_asr(self):
        variants = ("missing_top_marker", "source_missing", "source_corrupt", "source_empty",
                    "top_asr_but_nested_native", "top_native_but_nested_asr")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(prefix="subtitle-ambiguous-") as tmp:
                fixture = PipelineFixture(Path(tmp))
                self.assertEqual(fixture.invoke(), 0)
                write_json(fixture.mdir / "stamps.json", {
                    "language": "English", "text": "Unrelated stale synthetic ASR.",
                    "time_stamps": [{"text": "Unrelated stale synthetic ASR.",
                                     "start_time": 0.0, "end_time": 12.0}]})
                source_path = fixture.mdir / "source.json"
                source = read_json(source_path)
                if variant == "source_missing":
                    source_path.unlink()
                elif variant == "source_corrupt":
                    source_path.write_text("{invalid synthetic json", encoding="utf-8")
                elif variant == "source_empty":
                    write_json(source_path, {})
                    # The raw external document alone still prevents treating a
                    # stale stamp file as a proven local-ASR checkpoint.
                    (fixture.mdir / "subtitle.cues.json").unlink()
                else:
                    if variant == "missing_top_marker":
                        source.pop("transcript_source")
                    elif variant == "top_asr_but_nested_native":
                        source["transcript_source"] = "local_asr"
                    else:
                        source["source_info"]["captions"]["source"] = "local_asr"
                    write_json(source_path, source)
                preserved = snapshot_files(fixture.mdir)
                with self.assertRaises(ValueError):
                    job_recovery.build_speaker_resume_command(fixture.mdir)
                self.assertEqual(snapshot_files(fixture.mdir), preserved)

    def test_cue_attribution_requires_clear_audio_coverage(self):
        cue = parse_webvtt_text("WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n<v Avery Example>Synthetic cue.</v>\n")
        cases = [([], "unknown"), ([(0, 7.9, "a")], "unknown"),
                 ([(0, 8, "a")], "local_diarization"),
                 ([(0, 9, "a"), (8, 10, "b")], "unknown"),
                 ([(0, 10, "a"), (0, 10, "b")], "unknown")]
        for audio, expected in cases:
            with self.subTest(audio=audio):
                turn = video_minutes.subtitle_turns(cue, audio, {"a": "说话人1", "b": "说话人2"},
                                                    language="en", kind="human")[0]
                self.assertEqual(turn["speaker_source"], expected)
                self.assertNotEqual(turn["speaker"], "Avery Example")
                self.assertEqual((turn["start"], turn["end"], turn["text"]),
                                 (0, 10, "Synthetic cue."))


class MediaURLSubtitleTest(unittest.TestCase):
    def test_repeated_url_import_preserves_existing_media_and_manual_edits(self):
        for variant in ("automatic_to_human", "changed_text", "invalid_old_raw", "invalid_old_source"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(prefix="subtitle-url-repeat-") as tmp:
                root = Path(tmp)
                inbox = root / "first"
                (inbox / "captions").mkdir(parents=True)
                media = inbox / "download.mp4"
                media.write_bytes(b"synthetic-media")
                raw = inbox / "captions" / "automatic.vtt"
                raw.write_text(CAPTIONS, encoding="utf-8")
                (inbox / "captions" / "rejected.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
                request, result = inbox / "request.json", inbox / "result.json"
                write_json(request, {"url": "https://example.invalid/repeated-synthetic"})
                info = {"title": "Synthetic repeated import", "upload_date": "20260102", "language": "en"}
                provenance = {"schema": "media-captions/v1", "source": "native_subtitle",
                              "language": "en", "kind": "automatic"}
                preparation = CaptionPreparation(parse_caption_file(raw, duration=12), raw, provenance)

                def run(command, **_kwargs):
                    return SimpleNamespace(returncode=1 if command[0] == "cp" else 0)

                with patch.object(sys, "argv", ["media_url.py", str(request), "--result", str(result)]), \
                        patch.dict(os.environ, {"MEETING_DATA_ROOT": str(root)}), \
                        patch.object(media_url, "validate_public_url", side_effect=lambda value: value), \
                        patch.object(media_url, "_download", return_value=(media, info, preparation)), \
                        patch.object(media_url.subprocess, "run", side_effect=run), redirect_stdout(io.StringIO()):
                    self.assertEqual(media_url.main(), 0)
                mdir = root / "meetings" / read_json(result)["meeting"]
                write_json(mdir / "transcript.spk.json", [{
                    "start": 0.0, "end": 4.0, "text": "Synthetic manually corrected wording.",
                    "speaker": "Synthetic confirmed speaker", "text_review_status": "human_corrected"}])
                write_json(mdir / "transcript.edits.json", {"edits": [{"synthetic_manual_edit": True}]})
                (mdir / ".versions").mkdir()
                write_json(mdir / ".versions" / "synthetic.json", {"synthetic_revision": "preserve"})
                (mdir / "minutes.md").write_text("# Synthetic manually reviewed summary\n", encoding="utf-8")
                if variant == "invalid_old_raw":
                    (mdir / "source.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
                elif variant == "invalid_old_source":
                    (mdir / "source.json").write_text("{invalid synthetic json", encoding="utf-8")
                preserved = snapshot_files(mdir)
                original_result = result.read_bytes()

                retry = root / "retry"
                (retry / "captions").mkdir(parents=True)
                incoming = retry / "captions" / "human.vtt"
                incoming.write_text(CAPTIONS.replace("introduction", "updated introduction")
                                    if variant == "changed_text" else CAPTIONS, encoding="utf-8")
                second_request = retry / "request.json"
                write_json(second_request, read_json(request))
                incoming_preparation = CaptionPreparation(
                    parse_caption_file(incoming, duration=12), incoming, {**provenance, "kind": "human"})
                earlier_imports = [(mdir, preserved)]
                for import_number in (2, 3):
                    second_result = retry / f"result-{import_number}.json"
                    with patch.object(sys, "argv", ["media_url.py", str(second_request), "--result", str(second_result)]), \
                            patch.dict(os.environ, {"MEETING_DATA_ROOT": str(root)}), \
                            patch.object(media_url, "validate_public_url", side_effect=lambda value: value), \
                            patch.object(media_url, "_download", return_value=(media, info, incoming_preparation)), \
                            patch.object(media_url.subprocess, "run", side_effect=run) as runner, \
                            redirect_stdout(io.StringIO()):
                        self.assertEqual(media_url.main(), 0)
                    commands = [call.args[0] for call in runner.call_args_list if call.args[0][0] != "cp"]
                    self.assertEqual(len(commands), 1)
                    command = commands[0]
                    self.assertEqual(Path(command[1]).name, "video_minutes.py")
                    copied_mdir = root / "meetings" / read_json(second_result)["meeting"]
                    self.assertEqual(copied_mdir.name, f"{mdir.name}-import-{import_number}")
                    self.assertEqual(command[command.index("--meeting-dir") + 1], str(copied_mdir))
                    self.assertEqual(command[command.index("--subtitle") + 1], str(copied_mdir / "source.vtt"))
                    self.assertEqual(command[command.index("--subtitle-kind") + 1], "human")
                    self.assertEqual((copied_mdir / "source.vtt").read_bytes(), incoming.read_bytes())
                    self.assertEqual((copied_mdir / "source_captions" / incoming.name).read_bytes(),
                                     incoming.read_bytes())
                    self.assertEqual(read_json(copied_mdir / "source.json")["source_info"]["captions"]["kind"],
                                     "human")
                    self.assertFalse((copied_mdir / "transcript.edits.json").exists())
                    for earlier_dir, earlier_bytes in earlier_imports:
                        self.assertEqual(snapshot_files(earlier_dir), earlier_bytes)
                    self.assertEqual(result.read_bytes(), original_result)
                    earlier_imports.append((copied_mdir, snapshot_files(copied_mdir)))

    def test_url_import_forwards_generic_subtitles_and_preserves_raw_attempts(self):
        with tempfile.TemporaryDirectory(prefix="subtitle-url-") as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            media = inbox / "download.mp4"
            media.write_bytes(b"fictional-video-placeholder")
            caption_dir = inbox / "captions"
            caption_dir.mkdir()
            raw = caption_dir / "synthetic-human.vtt"
            raw.write_text(CAPTIONS, encoding="utf-8")
            rejected = caption_dir / "synthetic-rejected.vtt"
            rejected.write_text("WEBVTT\n\n", encoding="utf-8")
            request = inbox / "request.json"
            result = inbox / "result.json"
            write_json(request, {"url": "https://example.invalid/synthetic"})
            info = {"title": "Synthetic public video", "upload_date": "20260102",
                    "extractor_key": "Example", "language": "en", "duration": 12,
                    "webpage_url": "https://example.invalid/synthetic"}
            provenance = {"schema": "media-captions/v1", "source": "native_subtitle",
                          "language": "en", "kind": "human"}
            preparation = CaptionPreparation(parse_caption_file(raw, duration=12), raw, provenance)
            commands = []

            def run(command, **_kwargs):
                if command[0] == "cp":
                    return SimpleNamespace(returncode=1)
                commands.append(command)
                return SimpleNamespace(returncode=0)

            argv = ["media_url.py", str(request), "--result", str(result), "--no-vl",
                    "--visual-mode", "slides"]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"MEETING_DATA_ROOT": str(root)}), \
                    patch.object(media_url, "validate_public_url", side_effect=lambda value: value), \
                    patch.object(media_url, "_download", return_value=(media, info, preparation)), \
                    patch.object(media_url.subprocess, "run", side_effect=run), redirect_stdout(io.StringIO()):
                self.assertEqual(media_url.main(), 0)
            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(Path(command[1]).name, "video_minutes.py")
            self.assertNotIn("teams_minutes.py", " ".join(command))
            self.assertEqual(command[command.index("--subtitle-language") + 1], "en")
            self.assertEqual(command[command.index("--subtitle-kind") + 1], "human")
            self.assertEqual(command[command.index("--visual-mode") + 1], "slides")
            self.assertIn("--media", command)
            self.assertIn("--no-vl", command)
            mdir = root / "meetings" / read_json(result)["meeting"]
            self.assertEqual(Path(command[command.index("--subtitle") + 1]), mdir / "source.vtt")
            self.assertEqual((mdir / "source.vtt").read_bytes(), raw.read_bytes())
            self.assertEqual((mdir / "source_captions" / raw.name).read_bytes(), raw.read_bytes())
            self.assertEqual((mdir / "source_captions" / rejected.name).read_bytes(), rejected.read_bytes())
            self.assertEqual(read_json(mdir / "source.json")["source_info"]["captions"], provenance)
            self.assertEqual(read_json(mdir / "meta.json")["content_type"], "media")

    def test_url_without_usable_subtitles_keeps_local_asr_route(self):
        with tempfile.TemporaryDirectory(prefix="subtitle-url-fallback-") as tmp:
            root = Path(tmp)
            media = root / "download.mp4"
            media.write_bytes(b"synthetic-media")
            request, result = root / "request.json", root / "result.json"
            write_json(request, {"url": "https://example.invalid/synthetic"})
            provenance = {"schema": "media-captions/v1", "source": "local_asr",
                          "fallback_reason": "translated_only"}
            preparation = CaptionPreparation((), None, provenance)
            info = {"title": "Synthetic fallback video", "language": "en"}
            argv = ["media_url.py", str(request), "--result", str(result)]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"MEETING_DATA_ROOT": str(root)}), \
                    patch.object(media_url, "validate_public_url", side_effect=lambda value: value), \
                    patch.object(media_url, "_download", return_value=(media, info, preparation)), \
                    patch.object(media_url.subprocess, "run", return_value=SimpleNamespace(returncode=7)) as run, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(media_url.main(), 7)
            run.assert_called_once()
            command = run.call_args.args[0]
            self.assertEqual(Path(command[1]).name, "video_minutes.py")
            self.assertNotIn("--subtitle", command)
            self.assertNotIn("teams_minutes.py", " ".join(command))
            mdir = root / "meetings" / read_json(result)["meeting"]
            self.assertEqual(read_json(mdir / "source.json")["source_info"]["captions"], provenance)
            self.assertFalse((mdir / "source.vtt").exists())

    def test_downloader_never_selects_caption_or_thumbnail_sidecars_as_media(self):
        for include_media in (True, False):
            with self.subTest(include_media=include_media), tempfile.TemporaryDirectory(prefix="subtitle-download-") as tmp:
                destination = Path(tmp)
                options_seen = []
                preparation = CaptionPreparation((), None, {"source": "local_asr"})
                info = {"title": "Synthetic download", "duration": 15}

                class FakeDownloader:
                    def __init__(self, options):
                        options_seen.append(options)

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                    def extract_info(self, _url, *, download):
                        if download:
                            names = (["download.mp4"] if include_media else []) + [
                                "download.en.vtt", "download.en.srt", "download.jpg", "download.info.json"]
                            for index, name in enumerate(names):
                                target = destination / name
                                target.write_bytes(b"synthetic payload")
                                os.utime(target, (100 + index, 100 + index))
                        return dict(info)

                with patch.dict(sys.modules, {"yt_dlp": SimpleNamespace(YoutubeDL=FakeDownloader)}), \
                        patch.object(media_url, "prepare_captions", return_value=preparation) as prepare, \
                        patch.object(media_url, "build_ytdlp_caption_fetcher", return_value=Mock()), \
                        patch.object(media_url, "_media_duration", return_value=12.0) as duration, \
                        redirect_stdout(io.StringIO()):
                    if include_media:
                        media, actual_info, actual_preparation = media_url._download(
                            "https://example.invalid/synthetic", destination)
                        self.assertEqual(media.name, "download.mp4")
                        self.assertEqual(actual_info, info)
                        self.assertIs(actual_preparation, preparation)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "download_missing"):
                            media_url._download("https://example.invalid/synthetic", destination)
                if include_media:
                    prepare.assert_called_once()
                    self.assertEqual(prepare.call_args.args[:2],
                                     ({**info, "duration": 12.0}, destination / "captions"))
                    duration.assert_called_once_with(destination / "download.mp4")
                else:
                    prepare.assert_not_called()
                    duration.assert_not_called()
                self.assertEqual(len(options_seen), 1)
                self.assertTrue(options_seen[0]["noplaylist"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
