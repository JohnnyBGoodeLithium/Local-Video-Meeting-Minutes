"""Vendor-neutral ASR provider boundary.

The default provider keeps the existing in-process Qwen3-ASR path.  An
OpenAI-compatible ``/audio/transcriptions`` endpoint can be selected explicitly
for a local service or an approved cloud service.  No remote fallback is ever
enabled implicitly.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from meeting_core.hardware import configured_path, inference_device, inference_dtype


class ASRError(RuntimeError):
    """Safe provider failure; messages must not contain transcript bodies."""


class ASRCapabilityError(ASRError):
    """The selected endpoint cannot provide a required pipeline capability."""


@dataclass
class ASRResult:
    text: str
    language: str
    time_stamps: list[dict]
    context_applied: bool = False


class ASRProvider(Protocol):
    name: str

    def transcribe(self, audio, *, context: str | list[str] = "",
                   language: str | list[str | None] | None = None,
                   return_time_stamps: bool = False) -> list[ASRResult]: ...


def _field(value, name: str):
    if isinstance(value, dict):
        return value[name]
    return getattr(value, name)


class NativeQwenProvider:
    """Optional native adapter; imports torch/qwen-asr only when selected."""

    name = "native-qwen"

    def __init__(self, *, batch_size: int = 8, max_new_tokens: int = 1024,
                 with_aligner: bool = True):
        import torch
        from qwen_asr import Qwen3ASRModel

        home = Path.home()
        asr_path = configured_path(
            "MEETING_ASR_MODEL", home / ".local/share/models/hf/Qwen/Qwen3-ASR-1.7B")
        aligner_path = configured_path(
            "MEETING_ALIGNER_MODEL",
            home / ".local/share/models/hf/Qwen/Qwen3-ForcedAligner-0.6B")
        device = inference_device(torch, indexed=True)
        dtype = inference_dtype(torch, device)
        kwargs = dict(dtype=dtype, device_map=device,
                      max_inference_batch_size=batch_size,
                      max_new_tokens=max_new_tokens)
        if with_aligner:
            kwargs["forced_aligner"] = str(aligner_path)
            kwargs["forced_aligner_kwargs"] = dict(dtype=dtype, device_map=device)
        self.device = device
        self.dtype = dtype
        self._model = Qwen3ASRModel.from_pretrained(str(asr_path), **kwargs)

    def transcribe(self, audio, *, context="", language=None,
                   return_time_stamps=False) -> list[ASRResult]:
        results = self._model.transcribe(
            audio=audio, context=context, language=language,
            return_time_stamps=return_time_stamps)
        contexts = context if isinstance(context, list) else [context]
        if len(contexts) == 1:
            contexts *= len(results)
        output = []
        for result, used_context in zip(results, contexts):
            stamps = []
            for stamp in (getattr(result, "time_stamps", None) or []):
                stamps.append({
                    "text": str(_field(stamp, "text")),
                    "start_time": float(_field(stamp, "start_time")),
                    "end_time": float(_field(stamp, "end_time")),
                })
            output.append(ASRResult(
                text=str(result.text or ""), language=str(result.language or ""),
                time_stamps=stamps, context_applied=bool(str(used_context or "").strip())))
        return output


def _wav_bytes(audio) -> tuple[bytes, str]:
    if isinstance(audio, (str, Path)):
        path = Path(audio)
        return path.read_bytes(), path.name or "audio.wav"
    try:
        array, sample_rate = audio
    except Exception as exc:
        raise ASRError("unsupported audio input") from exc
    import numpy as np
    values = np.asarray(array, dtype=np.float32)
    if values.ndim > 1:
        values = values.mean(axis=-1)
    pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue(), "segment.wav"


def _multipart(fields: list[tuple[str, str]], file_name: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"----meeting-minutes-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode())
    body.extend(b"Content-Type: audio/wav\r\n\r\n")
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class OpenAITranscriptionProvider:
    """OpenAI-compatible transcription endpoint with word timestamp support."""

    name = "openai-compatible"

    def __init__(self):
        base = os.environ.get("MEETING_ASR_API", "http://127.0.0.1:11439/v1").rstrip("/")
        self.url = base if base.endswith("/audio/transcriptions") else base + "/audio/transcriptions"
        self.model = os.environ.get("MEETING_ASR_API_MODEL", "whisper-1")
        self.api_key = os.environ.get("MEETING_ASR_API_KEY", "")
        self.timeout = float(os.environ.get("MEETING_ASR_API_TIMEOUT", "1800"))
        self.context_mode = os.environ.get("MEETING_ASR_CONTEXT_MODE", "auto").lower()

    def _one(self, audio, context: str, language: str | None,
             timestamps: bool, *, allow_context_retry: bool = True) -> ASRResult:
        file_bytes, file_name = _wav_bytes(audio)
        fields = [("model", self.model), ("response_format", "verbose_json")]
        if language:
            language_value = {"chinese": "zh", "english": "en"}.get(
                str(language).strip().casefold(), str(language))
            fields.append(("language", language_value))
        use_context = bool(context.strip()) and self.context_mode != "off"
        if use_context:
            fields.append(("prompt", context))
        if timestamps:
            fields.append(("timestamp_granularities[]", "word"))
        body, content_type = _multipart(fields, file_name, file_bytes)
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if (use_context and allow_context_retry and self.context_mode == "auto"
                    and exc.code in {400, 404, 415, 422}):
                return self._one(audio, "", language, timestamps, allow_context_retry=False)
            raise ASRError(f"ASR endpoint HTTP {exc.code}") from exc
        except Exception as exc:
            raise ASRError(f"ASR endpoint failed: {type(exc).__name__}") from exc
        if not isinstance(payload, dict) or not str(payload.get("text") or "").strip():
            raise ASRError("ASR endpoint returned no readable text")
        stamps = []
        if timestamps:
            words = payload.get("words") if isinstance(payload.get("words"), list) else []
            for word in words:
                if not isinstance(word, dict) or word.get("start") is None or word.get("end") is None:
                    continue
                stamps.append({"text": str(word.get("word") or word.get("text") or ""),
                               "start_time": float(word["start"]),
                               "end_time": float(word["end"])})
            if not stamps:
                raise ASRCapabilityError(
                    "configured ASR endpoint does not return word timestamps")
        return ASRResult(
            text=str(payload["text"]), language=str(payload.get("language") or language or ""),
            time_stamps=stamps, context_applied=use_context)

    def transcribe(self, audio, *, context="", language=None,
                   return_time_stamps=False) -> list[ASRResult]:
        audios = audio if isinstance(audio, list) else [audio]
        contexts = context if isinstance(context, list) else [context]
        if len(contexts) == 1:
            contexts *= len(audios)
        languages = language if isinstance(language, list) else [language]
        if len(languages) == 1:
            languages *= len(audios)
        if not (len(audios) == len(contexts) == len(languages)):
            raise ValueError("ASR audio/context/language batch sizes differ")
        return [self._one(item, str(ctx or ""), lang, return_time_stamps)
                for item, ctx, lang in zip(audios, contexts, languages)]


class ExplicitFallbackProvider:
    """Lazy failover used only when the operator explicitly configures it."""

    def __init__(self, primary_name: str, primary_factory,
                 fallback_name: str, fallback_factory):
        self.name = f"{primary_name}+explicit-fallback-{fallback_name}"
        self._primary_factory = primary_factory
        self._fallback_factory = fallback_factory
        self._primary = None
        self._fallback = None

    def transcribe(self, audio, *, context="", language=None, return_time_stamps=False):
        try:
            self._primary = self._primary or self._primary_factory()
            return self._primary.transcribe(
                audio, context=context, language=language,
                return_time_stamps=return_time_stamps)
        except Exception as primary_error:
            try:
                self._fallback = self._fallback or self._fallback_factory()
                return self._fallback.transcribe(
                    audio, context=context, language=language,
                    return_time_stamps=return_time_stamps)
            except Exception as fallback_error:
                raise ASRError(
                    f"primary and explicit fallback ASR failed: "
                    f"{type(primary_error).__name__}/{type(fallback_error).__name__}") from fallback_error


def create_provider(*, batch_size: int = 8, max_new_tokens: int = 1024,
                    with_aligner: bool = True) -> ASRProvider:
    selected = os.environ.get("MEETING_ASR_PROVIDER", "native").strip().lower()
    fallback = os.environ.get("MEETING_ASR_FALLBACK_PROVIDER", "").strip().lower()

    def factory(name: str):
        if name in {"native", "qwen", "qwen-native"}:
            return lambda: NativeQwenProvider(
                batch_size=batch_size, max_new_tokens=max_new_tokens,
                with_aligner=with_aligner)
        if name in {"openai", "openai-compatible", "http"}:
            return OpenAITranscriptionProvider
        raise ASRCapabilityError(f"unknown ASR provider: {name}")

    primary_factory = factory(selected)
    if fallback and fallback != selected:
        return ExplicitFallbackProvider(selected, primary_factory, fallback, factory(fallback))
    return primary_factory()
