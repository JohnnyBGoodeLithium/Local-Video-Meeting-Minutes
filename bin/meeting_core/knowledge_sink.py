"""Provider-neutral、revision 幂等的知识库发布合同。

Canonical 会议数据只在 Meeting Minutes 内修改。本模块只把确定性 KB 投影发布到
下游，并在会议目录保存不含正文/凭据的发布回执。当前 adapter 是 WeKnora。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PUBLICATION_SCHEMA = "knowledge-publications/v1"
TARGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_LOCK = threading.RLock()


class KnowledgeSinkError(RuntimeError):
    """不包含响应正文、凭据或文档内容的安全发布错误。"""


@dataclass(frozen=True)
class KnowledgeTarget:
    id: str
    name: str
    content_types: tuple[str, ...] = ("meeting", "media")
    tag_id: str = ""


@dataclass(frozen=True)
class KnowledgeArtifact:
    title: str
    profile: str
    content_type: str
    revision: str
    filename: str
    media_type: str
    body: bytes


@dataclass(frozen=True)
class PublishResult:
    document_id: str
    parse_status: str


class KnowledgeSink(Protocol):
    provider: str

    def create(self, target: KnowledgeTarget, artifact: KnowledgeArtifact) -> PublishResult: ...
    def update(self, target: KnowledgeTarget, document_id: str,
               artifact: KnowledgeArtifact) -> PublishResult: ...
    def delete(self, document_id: str) -> None: ...


def _safe_base_url(raw: str) -> str:
    value = str(raw or "").strip().rstrip("/")
    parsed = urlparse(value)
    if (not value or parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password):
        raise KnowledgeSinkError("知识库 API 地址未正确配置")
    return value


def _response_data(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


class WeKnoraSink:
    provider = "weknora"

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 45.0):
        self.base_url = _safe_base_url(base_url)
        self.api_key = str(api_key or "").strip()
        self.timeout = max(5.0, min(float(timeout), 180.0))
        if not self.api_key:
            raise KnowledgeSinkError("WeKnora API key 未配置")

    def _request(self, method: str, path: str, *, body: bytes | None = None,
                 content_type: str = "application/json") -> dict:
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = content_type
        request = Request(f"{self.base_url}/api/v1{path}", data=body,
                          headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise KnowledgeSinkError("WeKnora 拒绝访问，请检查 API key 与知识库权限") from None
            if exc.code == 404:
                raise KnowledgeSinkError("WeKnora 目标知识库或旧文档不存在") from None
            if exc.code == 409:
                raise KnowledgeSinkError("WeKnora 已存在相同内容，请刷新发布状态后重试") from None
            raise KnowledgeSinkError(f"WeKnora 发布请求失败（HTTP {exc.code}）") from None
        except (URLError, TimeoutError, OSError):
            raise KnowledgeSinkError("无法连接 WeKnora API，请检查服务和端口") from None
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KnowledgeSinkError("WeKnora 返回了不可识别的响应") from None
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _json(data: dict) -> bytes:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _multipart(fields: dict[str, str], filename: str, content_type: str,
                   content: bytes) -> tuple[bytes, str]:
        boundary = f"meeting-minutes-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            if not value:
                continue
            chunks += [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"), b"\r\n",
            ]
        safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(), content, b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def create(self, target: KnowledgeTarget, artifact: KnowledgeArtifact) -> PublishResult:
        if artifact.profile == "kb":
            payload = self._request(
                "POST", f"/knowledge-bases/{target.id}/knowledge/manual",
                body=self._json({"title": artifact.title,
                                 "content": artifact.body.decode("utf-8"),
                                 "status": "published", "tag_id": target.tag_id,
                                 "channel": "meeting-minutes"}))
        else:
            metadata = json.dumps({"source": "meeting-minutes",
                                   "revision": artifact.revision,
                                   "content_type": artifact.content_type},
                                  ensure_ascii=False, separators=(",", ":"))
            body, content_type = self._multipart(
                {"fileName": artifact.filename, "metadata": metadata,
                 "enable_multimodel": "false", "tag_id": target.tag_id,
                 "channel": "meeting-minutes",
                 "process_config": json.dumps({"enable_multimodel": False,
                                                "asr_config": {"enabled": False}},
                                               separators=(",", ":"))},
                artifact.filename, artifact.media_type, artifact.body)
            payload = self._request(
                "POST", f"/knowledge-bases/{target.id}/knowledge/file",
                body=body, content_type=content_type)
        data = _response_data(payload)
        document_id = str(data.get("id") or "").strip()
        if not document_id:
            raise KnowledgeSinkError("WeKnora 未返回新文档 ID")
        return PublishResult(document_id, str(data.get("parse_status") or "processing"))

    def update(self, target: KnowledgeTarget, document_id: str,
               artifact: KnowledgeArtifact) -> PublishResult:
        if artifact.profile != "kb":
            # 文件内容没有原位替换 API；调用方先创建新 revision，确认成功后再删旧文档。
            return self.create(target, artifact)
        payload = self._request(
            "PUT", f"/knowledge/manual/{document_id}",
            body=self._json({"title": artifact.title,
                             "content": artifact.body.decode("utf-8"),
                             "status": "published", "tag_id": target.tag_id,
                             "channel": "meeting-minutes"}))
        data = _response_data(payload)
        return PublishResult(str(data.get("id") or document_id),
                             str(data.get("parse_status") or "processing"))

    def delete(self, document_id: str) -> None:
        self._request("DELETE", f"/knowledge/{document_id}")


def configured_targets() -> list[KnowledgeTarget]:
    """读取显式 allowlist；不把凭据或未经选择的 WeKnora 库暴露给浏览器。"""
    raw = os.environ.get("MEETING_KB_TARGETS_JSON", "").strip()
    items: list[dict] = []
    if raw:
        try:
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    else:
        target_id = os.environ.get("MEETING_KB_DEFAULT_ID", "").strip()
        if target_id:
            items = [{"id": target_id,
                      "name": os.environ.get("MEETING_KB_DEFAULT_NAME", "Meeting Knowledge")}]
    targets = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("id") or "").strip()
        if not TARGET_ID_RE.fullmatch(target_id):
            continue
        types = tuple(value for value in item.get("content_types", ["meeting", "media"])
                      if value in {"meeting", "media"})
        targets.append(KnowledgeTarget(
            target_id, str(item.get("name") or target_id).strip()[:120],
            types or ("meeting", "media"), str(item.get("tag_id") or "").strip()))
    return targets[:20]


def configured_sink() -> WeKnoraSink:
    provider = os.environ.get("MEETING_KB_PROVIDER", "weknora").strip().lower()
    if provider != "weknora":
        raise KnowledgeSinkError(f"知识库 provider {provider or '-'} 尚未实现")
    api_url = os.environ.get("MEETING_KB_API_URL", "").strip()
    if not api_url:
        health = os.environ.get("MEETING_KB_HEALTH_URL", "").strip()
        api_url = health[:-7] if health.endswith("/health") else health
    return WeKnoraSink(api_url, os.environ.get("MEETING_KB_API_KEY", ""))


def load_publications(mdir: Path) -> dict:
    try:
        payload = json.loads((mdir / "meeting.knowledge-publications.json").read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return {"schema": PUBLICATION_SCHEMA, "updated_at": None, "publications": []}
    if not isinstance(payload, dict) or payload.get("schema") != PUBLICATION_SCHEMA:
        return {"schema": PUBLICATION_SCHEMA, "updated_at": None, "publications": []}
    payload["publications"] = (payload.get("publications")
                               if isinstance(payload.get("publications"), list) else [])
    return payload


def publication_for(mdir: Path, provider: str, target_id: str) -> dict | None:
    return next((item for item in load_publications(mdir)["publications"]
                 if item.get("provider") == provider and item.get("target_id") == target_id), None)


def _atomic_write(path: Path, payload: dict) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    os.replace(temp, path)


def publish(mdir: Path, target: KnowledgeTarget, artifact: KnowledgeArtifact,
            sink: KnowledgeSink) -> dict:
    """发布或更新一个 target；失败时保留上次成功回执和远端旧文档。"""
    with _LOCK:
        ledger = load_publications(mdir)
        current = next((item for item in ledger["publications"]
                        if item.get("provider") == sink.provider
                        and item.get("target_id") == target.id), None)
        if (current and current.get("status") == "published"
                and current.get("artifact_revision") == artifact.revision
                and current.get("profile") == artifact.profile):
            return {**current, "outcome": "already_current"}

        old_document_id = str((current or {}).get("document_id") or "")
        can_update_in_place = (old_document_id and current
                               and current.get("profile") == "kb"
                               and artifact.profile == "kb")
        if can_update_in_place:
            result = sink.update(target, old_document_id, artifact)
        else:
            result = sink.create(target, artifact)

        stale_document_id = ""
        if (old_document_id and not can_update_in_place
                and result.document_id != old_document_id):
            try:
                sink.delete(old_document_id)
            except KnowledgeSinkError:
                stale_document_id = old_document_id

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        record = {
            "provider": sink.provider, "target_id": target.id,
            "target_name": target.name, "document_id": result.document_id,
            "artifact_revision": artifact.revision, "profile": artifact.profile,
            "content_type": artifact.content_type, "status": "published",
            "parse_status": result.parse_status, "published_at": now,
            "stale_document_id": stale_document_id or None,
        }
        if current:
            ledger["publications"][ledger["publications"].index(current)] = record
        else:
            ledger["publications"].append(record)
        ledger["updated_at"] = now
        _atomic_write(mdir / "meeting.knowledge-publications.json", ledger)
        return {**record, "outcome": "updated" if old_document_id else "created"}


def artifact_revision(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:24]
