#!/usr/bin/env python3
"""ASR provider boundary: compatible endpoint, context fallback and timestamps."""

import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.asr import (  # noqa: E402
    ASRCapabilityError,
    ExplicitFallbackProvider,
    OpenAITranscriptionProvider,
    create_provider,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class FailingProvider:
    def transcribe(self, *_args, **_kwargs):
        raise RuntimeError("fictional failure")


class WorkingProvider:
    def transcribe(self, *_args, **_kwargs):
        return ["fallback-ok"]


with tempfile.TemporaryDirectory() as td:
    wav = Path(td) / "fictional.wav"
    sf.write(wav, np.zeros(16000, dtype=np.float32), 16000)
    old = dict(os.environ)
    try:
        os.environ.update({
            "MEETING_ASR_PROVIDER": "openai-compatible",
            "MEETING_ASR_API": "http://127.0.0.1:9/v1",
            "MEETING_ASR_API_MODEL": "fictional-asr",
            "MEETING_ASR_CONTEXT_MODE": "auto",
        })
        provider = create_provider(with_aligner=True)
        assert isinstance(provider, OpenAITranscriptionProvider)
        payload = {"text": "Fictional original language.", "language": "en",
                   "words": [{"word": "Fictional", "start": 0.0, "end": 0.5},
                             {"word": " original", "start": 0.5, "end": 0.8}]}
        with patch("urllib.request.urlopen", return_value=Response(payload)) as request:
            result = provider.transcribe(str(wav), context="Example Term",
                                         return_time_stamps=True)[0]
        assert result.context_applied and len(result.time_stamps) == 2
        body = request.call_args.args[0].data
        assert b'Example Term' in body and b'timestamp_granularities' in body

        failure = urllib.error.HTTPError(provider.url, 422, "unsupported prompt", {}, None)
        with patch("urllib.request.urlopen", side_effect=[failure, Response(payload)]) as request:
            result = provider.transcribe(str(wav), context="Example Term",
                                         return_time_stamps=True)[0]
        assert request.call_count == 2 and result.context_applied is False

        with patch("urllib.request.urlopen", return_value=Response(
                {"text": "No timestamps", "language": "en"})):
            try:
                provider.transcribe(str(wav), return_time_stamps=True)
            except ASRCapabilityError:
                pass
            else:
                raise AssertionError("word timestamps are required for speaker alignment")

        fallback = ExplicitFallbackProvider(
            "primary", FailingProvider, "fallback", WorkingProvider)
        assert fallback.transcribe(str(wav)) == ["fallback-ok"]
    finally:
        os.environ.clear()
        os.environ.update(old)

print("ASR provider boundary: ok")
