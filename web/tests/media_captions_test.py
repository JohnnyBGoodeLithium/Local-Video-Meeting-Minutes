#!/usr/bin/env python3
"""Subtitle-first selection and safety contracts; synthetic offline fixtures only."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core import media_captions as captions  # noqa: E402
from meeting_core.media_captions import (  # noqa: E402
    CaptionCandidate, CaptionError, build_ytdlp_caption_fetcher, normalize_language,
    parse_caption_bytes, parse_caption_file, prepare_captions, project_caption_provenance,
)


VALID = b"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nA fictional product is ready.\n"
STAMP = "2026-01-02T03:04:05+00:00"


def track(label="human", **extra):
    return {"ext": "vtt", "url": f"https://example.invalid/{label}?token=private", **extra}


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="media-captions-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "source_captions"

    def prepare(self, info, fetch=lambda _candidate: VALID):
        return prepare_captions(info, self.directory, fetch, imported_at=STAMP)

    def assert_rejected(self, raw, reason, **kwargs):
        with self.assertRaises(CaptionError) as caught:
            parse_caption_bytes(raw, **kwargs)
        self.assertEqual(caught.exception.reason, reason)

    def test_human_original_beats_automatic_and_other_languages(self):
        seen = []
        info = {"language": "en", "duration": 8,
                "automatic_captions": {"en": [track("auto")]},
                "subtitles": {"fr": [track("translation")], "en": [track()]}}
        result = self.prepare(info, lambda candidate: seen.append(candidate.kind) or VALID)
        self.assertTrue(result.usable)
        self.assertEqual(seen, ["human"])
        self.assertEqual(result.provenance["selection_reason"], "original_human")
        self.assertEqual(result.provenance["timestamp_source"], "subtitle_cues")
        self.assertEqual(result.provenance["imported_at"], STAMP)
        self.assertEqual(result.raw_path.read_bytes(), VALID)
        self.assertEqual((self.directory / "attempt-1.vtt").read_bytes(), VALID)
        self.assertEqual(result.provenance["raw_sha256"], hashlib.sha256(VALID).hexdigest())

    def test_original_marker_identifies_language_without_guessing(self):
        info = {"automatic_captions": {"en-orig": [track("auto")],
                                       "fr": [track("translated", is_translated=True)]},
                "subtitles": {"en": [track()]}}
        result = self.prepare(info)
        self.assertEqual(result.provenance["kind"], "human")
        self.assertEqual(result.provenance["original_language"], "en")
        self.assertEqual(result.provenance["language_evidence"], "original_track")

    def test_automatic_original_is_usable_but_not_human_reviewed(self):
        result = self.prepare({"automatic_captions": {"en-orig": [track("auto")]}})
        self.assertTrue(result.usable)
        self.assertEqual(result.provenance["selection_reason"], "original_automatic")
        self.assertTrue(all(signal.text_review_status == "automatic" for signal in result.signals()))
        self.assertTrue(all(signal.review_needed for signal in result.signals()))

    def test_unknown_language_does_not_select_single_human_track(self):
        fetch = lambda _candidate: self.fail("unknown-language captions must not download")
        result = self.prepare({"subtitles": {"en": [track()]}}, fetch)
        self.assertFalse(result.usable)
        self.assertEqual(result.provenance["fallback_reason"], "original_language_unknown")
        self.assertEqual(result.provenance["language_evidence"], "unknown")
        self.assertIsNone(result.raw_path)

    def test_no_captions_retains_known_or_unknown_language_evidence(self):
        for info, evidence in (({}, "unknown"), ({"language": "en"}, "metadata")):
            result = self.prepare(info)
            self.assertEqual(result.provenance["fallback_reason"], "no_captions")
            self.assertEqual(result.provenance["language_evidence"], evidence)

    def test_language_conflict_does_not_guess(self):
        result = self.prepare({"language": "fr", "automatic_captions": {"en-orig": [track()]}})
        self.assertEqual(result.provenance["fallback_reason"], "original_language_conflict")
        self.assertEqual(result.provenance["language_evidence"], "conflict")

    def test_two_original_languages_are_ambiguous(self):
        result = self.prepare({"automatic_captions": {"en-orig": [track()], "fr-orig": [track()]}})
        self.assertEqual(result.provenance["fallback_reason"], "original_language_conflict")

    def test_translated_tracks_are_never_original(self):
        translations = [track(url="https://example.invalid/caption?lang=fr&tlang=en&token=private"),
                        track(is_translated=True), track(name="English translation"),
                        track(source_language="fr", language="en"), track(source_language="fr"),
                        track(language="fr")]
        for item in translations:
            with self.subTest(item=item):
                result = self.prepare({"language": "en", "subtitles": {"en": [item]}})
                self.assertFalse(result.usable)
                self.assertEqual(result.provenance["fallback_reason"], "translated_only")

    def test_other_language_does_not_replace_canonical_original(self):
        result = self.prepare({"language": "fr", "subtitles": {"en": [track()]}})
        self.assertEqual(result.provenance["fallback_reason"], "no_original_captions")

    def test_known_conflicting_scripts_are_not_original(self):
        for language, alternate in (("zh-Hant", "zh-Hans"), ("sr-Latn", "sr-Cyrl")):
            result = self.prepare({"language": language, "subtitles": {alternate: [track()]}})
            self.assertFalse(result.usable)
        generic = self.prepare({"language": "en", "subtitles": {"en-US": [track()]}})
        self.assertTrue(generic.usable)
        self.assertEqual(generic.provenance["language"], "en-us")

    def test_exact_language_match_preferred_within_authorship(self):
        seen = []
        result = self.prepare({"language": "en-US", "subtitles": {
            "en": [track("generic")], "en-US": [track("exact")]}},
            lambda candidate: seen.append(candidate.language) or VALID)
        self.assertTrue(result.usable)
        self.assertEqual(seen, ["en-us"])

    def test_invalid_human_bytes_retained_then_automatic_selected(self):
        invalid = b"WEBVTT\n\n00:00:04.000 --> 00:00:01.000\nInvalid timing.\n"
        info = {"language": "en", "subtitles": {"en": [track()]},
                "automatic_captions": {"en": [track("auto")]}}
        result = self.prepare(info, lambda candidate: invalid if candidate.kind == "human" else VALID)
        self.assertTrue(result.usable)
        self.assertEqual(result.provenance["kind"], "automatic")
        self.assertEqual((self.directory / "attempt-1.vtt").read_bytes(), invalid)
        self.assertEqual(result.raw_path.read_bytes(), VALID)
        attempt = result.provenance["attempts"][0]
        self.assertEqual(attempt["reason"], "invalid_timing")
        self.assertEqual(attempt["raw_sha256"], hashlib.sha256(invalid).hexdigest())

    def test_download_failure_then_human_alternate_then_auto(self):
        seen = []

        def fetch(candidate):
            seen.append(candidate.kind)
            if len(seen) == 1:
                raise OSError("https://example.invalid/?cookie=private /local/secret")
            return VALID

        result = self.prepare({"language": "en", "subtitles": {"en": [track(), track("second")]},
                               "automatic_captions": {"en": [track("auto")]}}, fetch)
        self.assertEqual(seen, ["human", "human"])
        self.assertEqual(result.provenance["attempts"][0]["reason"], "download_failed")
        self.assertNotIn("private", json.dumps(result.provenance))
        self.assertNotIn("secret", json.dumps(result.provenance))

    def test_all_unusable_falls_back_with_safe_reasons(self):
        result = self.prepare({"language": "en", "subtitles": {"en": [track()]}}, lambda _c: b"")
        self.assertEqual(result.provenance["source"], "local_asr")
        self.assertEqual(result.provenance["fallback_reason"], "captions_unusable")
        self.assertEqual(result.provenance["attempts"][0]["reason"], "invalid_header")
        self.assertIsNone(result.raw_path)

    def test_unsupported_formats_explicitly_fall_back(self):
        result = self.prepare({"language": "en", "subtitles": {"en": [track(ext="srt")]}})
        self.assertEqual(result.provenance["fallback_reason"], "unsupported_format")
        self.assert_rejected(VALID, "unsupported_format", ext="srt")

    def test_unsupported_human_format_allows_original_automatic_vtt(self):
        result = self.prepare({"language": "en", "subtitles": {"en": [track(ext="json3")]},
                               "automatic_captions": {"en": [track()]}})
        self.assertEqual(result.provenance["kind"], "automatic")

    def test_raw_bom_crlf_and_voice_markup_unchanged_without_identity(self):
        raw = ("\ufeffWEBVTT\r\n\r\n00:00:00.000 --> 00:00:03.000\r\n"
               "<v Example Presenter>One claim.</v> <v Other Presenter>Another claim.</v>\r\n").encode()
        result = self.prepare({"language": "en", "subtitles": {"en": [track()]}}, lambda _c: raw)
        self.assertEqual(result.raw_path.read_bytes(), raw)
        self.assertEqual(parse_caption_file(result.raw_path)[0].text, "One claim. Another claim.")
        self.assertIsNone(result.cues[0].speaker)
        self.assertIsNone(result.signals()[0].speaker)
        self.assertEqual(result.signals()[0].speaker_source, "unknown")
        self.assertEqual(result.signals()[0].text_review_status, "platform_provided")
        if os.name != "nt":
            self.assertEqual(result.raw_path.stat().st_mode & 0o777, 0o600)

    def test_rolling_cues_remove_only_temporally_overlapping_duplicate_text(self):
        raw = b"""WEBVTT

00:00:00.000 --> 00:00:03.000
The fictional product

00:00:01.000 --> 00:00:04.000
The fictional product is ready.

00:00:02.000 --> 00:00:05.000
product is ready. Next point.

00:00:06.000 --> 00:00:07.000
Next point.
"""
        cues = parse_caption_bytes(raw)
        self.assertEqual([cue.text for cue in cues],
                         ["The fictional product", "is ready.", "Next point.", "Next point."])
        self.assertEqual(cues[1].start, 1.0)
        self.assertEqual(cues[1].end, 4.0)

    def test_exact_rolling_duplicates_merge_display_time(self):
        raw = VALID + b"\n00:00:02.000 --> 00:00:04.000\nA fictional product is ready.\n"
        cues = parse_caption_bytes(raw)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].end, 4.0)

    def test_huge_overlapping_cues_are_bounded_without_dropping_text(self):
        first = "A" * 500_000 + " first conclusion."
        second = "A" * 500_000 + " second conclusion."
        raw = (f"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n{first}\n\n"
               f"00:00:01.000 --> 00:00:04.000\n{second}\n").encode()
        cues = parse_caption_bytes(raw)
        self.assertEqual([cue.text for cue in cues], [first, second])

    def test_long_exact_character_run_does_not_cut_partial_words(self):
        self.assertEqual(captions._suffix_overlap("A" * 500_000, "A" * 500_000 + " ending"), 0)
        self.assertEqual(captions._suffix_overlap("The old sentence.", "sentence. New sentence."), 9)

    def test_invalid_empty_encoding_header_and_timing(self):
        self.assert_rejected(b"WEBVTT\n\n", "empty_captions")
        self.assert_rejected(b"WEBVTT\n\n\xff", "invalid_encoding")
        self.assert_rejected(b"WEBVTT\n\x00", "invalid_encoding")
        self.assert_rejected(b"<html>Error</html>", "invalid_header")
        for timing in ("00:00:00.000 --> 00:00:00.000", "-00:00:01.000 --> 00:00:03.000",
                       "00:60:00.000 --> 01:01:00.000", "00:00:60.000 --> 00:01:02.000",
                       "00:00:03.000 --> 00:00:01.000"):
            self.assert_rejected(f"WEBVTT\n\n{timing}\nText.\n".encode(), "invalid_timing")

    def test_partial_malformed_track_is_not_silently_accepted(self):
        for bad in (b"\ninvalid --> timing\nLost claim.\n", b"\nuntimed lost claim\n",
                    b"00:00:04.000 --> 00:00:05.000\nMissing block break.\n"):
            self.assert_rejected(VALID + bad, "invalid_timing")

    def test_nonmonotonic_timestamps_rejected(self):
        raw = (b"WEBVTT\n\n00:00:02.000 --> 00:00:04.000\nFirst.\n\n"
               b"00:00:01.000 --> 00:00:03.000\nSecond.\n")
        self.assert_rejected(raw, "invalid_timing")

    def test_actual_media_duration_revalidation(self):
        self.assert_rejected(VALID, "media_timing_mismatch", duration=1)
        self.assertEqual(len(parse_caption_bytes(VALID, duration=3)), 1)
        result = self.prepare({"language": "en", "duration": 1, "subtitles": {"en": [track()]}})
        self.assertEqual(result.provenance["attempts"][0]["reason"], "media_timing_mismatch")

    def test_hls_timestamp_map_rejected_without_reconciliation(self):
        raw = VALID.replace(b"WEBVTT", b"WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:90000")
        self.assert_rejected(raw, "unsupported_timestamps")

    def test_cue_limit(self):
        with patch.object(captions, "MAX_CUES", 1):
            self.assert_rejected(VALID + b"\n00:00:04.000 --> 00:00:05.000\nSecond.\n", "too_many_cues")

    def test_oversized_bytes_bounded_and_marked_as_prefix(self):
        raw = b"x" * 128
        with patch.object(captions, "MAX_CAPTION_BYTES", 64):
            result = self.prepare({"language": "en", "subtitles": {"en": [track()]}}, lambda _c: raw)
            self.assertEqual((self.directory / "attempt-1.vtt").read_bytes(), raw[:64])
            attempt = result.provenance["attempts"][0]
            self.assertTrue(attempt["raw_truncated"])
            self.assertEqual(attempt["reason"], "caption_too_large")
            self.assertEqual(attempt["raw_sha256"], hashlib.sha256(raw[:64]).hexdigest())

    def test_attempts_bounded(self):
        seen = []
        result = self.prepare({"language": "en", "subtitles": {"en": [track(str(i)) for i in range(20)]}},
                              lambda candidate: seen.append(candidate) or b"")
        self.assertEqual(len(seen), captions.MAX_CANDIDATES)
        self.assertEqual(result.provenance["fallback_reason"], "candidate_limit")

    def test_many_bad_human_tracks_cannot_starve_automatic_fallback(self):
        seen = []

        def fetch(candidate):
            seen.append(candidate.kind)
            return VALID if candidate.kind == "automatic" else b""

        result = self.prepare({"language": "en", "subtitles": {"en": [track(str(i)) for i in range(20)]},
                               "automatic_captions": {"en": [track("auto")]}}, fetch)
        self.assertTrue(result.usable)
        self.assertEqual(result.provenance["kind"], "automatic")
        self.assertEqual(result.provenance["fallback_reason"], "candidate_limit")
        self.assertEqual(seen, ["human"] * (captions.MAX_CANDIDATES - 1) + ["automatic"])

    def test_duplicate_download_candidates_use_one_attempt(self):
        seen = []
        result = self.prepare({"language": "en", "subtitles": {"en": [track()] * 20},
                               "automatic_captions": {"en": [track("auto")]}},
                              lambda candidate: seen.append(candidate.kind) or (
                                  VALID if candidate.kind == "automatic" else b""))
        self.assertTrue(result.usable)
        self.assertEqual(seen, ["human", "automatic"])
        self.assertNotIn("fallback_reason", result.provenance)

    def test_provenance_projects_hostile_values_without_secrets(self):
        value = {"schema": captions.SCHEMA, "source": "native_subtitle", "kind": ["human"],
                 "language": "https://example.invalid/?token=private", "format": {"cookie": "private"},
                 "raw_sha256": "private", "imported_at": STAMP, "raw_bytes": True,
                 "url": "https://example.invalid/private", "headers": {"cookie": "private"},
                 "attempts": [{"kind": "human", "language": "en", "format": "vtt",
                               "status": ["selected"], "reason": {"private": 1}, "url": "private"}],
                 "fallback_reason": "user_requested_asr"}
        result = project_caption_provenance(value)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("raw_bytes", result)
        self.assertEqual(result["fallback_reason"], "user_requested_asr")
        self.assertEqual(result["attempts"], [{"kind": "human", "language": "en", "format": "vtt"}])
        self.assertEqual(project_caption_provenance({"schema": "other"}), {})

    def test_language_codes_are_sanitized(self):
        self.assertEqual(normalize_language(" ZH_Hant "), "zh-hant")
        self.assertEqual(normalize_language("en-orig"), "en")
        for language in (None, {}, "und", "mul", "zxx", "live_chat", "../../en", "en?token=private"):
            self.assertIsNone(normalize_language(language))

    def test_fetcher_uses_session_headers_but_never_persists_them(self):
        seen = []

        class Request:
            def __init__(self, url, headers):
                self.url, self.headers = url, headers

        response = io.BytesIO(VALID)
        downloader = types.SimpleNamespace(urlopen=lambda request: seen.append(request) or response)
        module = types.ModuleType("yt_dlp.networking")
        module.Request = Request
        with patch.dict(sys.modules, {"yt_dlp.networking": module}):
            fetch = build_ytdlp_caption_fetcher(downloader, validate_url=lambda url: url)
            result = self.prepare({"language": "en", "http_headers": {"Cookie": "private"},
                                   "subtitles": {"en": [track()]}}, fetch)
        self.assertTrue(result.usable)
        self.assertEqual(seen[0].headers, {"Cookie": "private"})
        self.assertTrue(response.closed)
        self.assertNotIn("private", json.dumps(result.provenance))

    def test_fetcher_inline_data_and_unsupported_fragmented_protocol(self):
        fetch = build_ytdlp_caption_fetcher(None)
        self.assertEqual(fetch(CaptionCandidate("human", "en", "vtt", inline_data=VALID)), VALID)
        with self.assertRaises(CaptionError) as caught:
            fetch(CaptionCandidate("human", "en", "vtt", protocol="m3u8_native"))
        self.assertEqual(caught.exception.reason, "unsupported_protocol")

    def test_fetcher_rejects_local_and_credentialed_endpoints(self):
        fetch = build_ytdlp_caption_fetcher(None)
        for url in ("file:///local/private", "https://name:private@example.invalid/x",
                    "http://localhost/caption", "http://host.internal/caption"):
            with self.assertRaises(CaptionError) as caught:
                fetch(CaptionCandidate("human", "en", "vtt", url=url))
            self.assertEqual(caught.exception.reason, "unsafe_caption_url")
        with patch.object(captions.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))]):
            with self.assertRaises(CaptionError) as caught:
                fetch(CaptionCandidate("human", "en", "vtt", url="https://example.invalid/caption"))
            self.assertEqual(caught.exception.reason, "unsafe_caption_url")


if __name__ == "__main__":
    unittest.main()
