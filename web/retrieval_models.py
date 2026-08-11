"""本机 embedding / reranker 客户端与会议级持久向量索引。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from array import array
from pathlib import Path


INDEX_SCHEMA = "meeting-vector-index/v1"
EMBED_API = os.environ.get("MEETING_EMBED_API", "http://127.0.0.1:11437/v1").rstrip("/")
RERANK_API = os.environ.get("MEETING_RERANK_API", "http://127.0.0.1:11438").rstrip("/")
EMBED_MODEL = os.environ.get("MEETING_EMBED_MODEL", "qwen3-embedding-0.6b-q8")
RERANK_MODEL = os.environ.get("MEETING_RERANK_MODEL", "qwen3-reranker-0.6b-q8")
RAG_MODE = os.environ.get("MEETING_RAG_MODE", "hybrid").strip().lower()
MAX_PASSAGE_CHARS = 1800
EMBED_BATCH_SIZE = max(1, int(os.environ.get("MEETING_EMBED_BATCH_SIZE", "16")))
QUERY_INSTRUCTION = (
    "Instruct: Given a question about a recorded business meeting, retrieve passages that answer "
    "the question with decisions, actions, risks, speakers, or presentation evidence.\nQuery: "
)

_LOCK = threading.Lock()
_INDEX_LOCKS: dict[str, threading.Lock] = {}
_CACHE: dict[str, tuple[str, int, list[str], array]] = {}
_STATUS = {
    "embedding": {"state": "not_checked", "last_error": None, "updated_at": None},
    "reranker": {"state": "not_checked", "last_error": None, "updated_at": None},
}


class RetrievalModelError(RuntimeError):
    pass


def _mark(component: str, state: str, error: str | None = None) -> None:
    with _LOCK:
        _STATUS[component] = {
            "state": state,
            "last_error": error[:160] if error else None,
            "updated_at": time.time(),
        }


def status() -> dict:
    with _LOCK:
        components = json.loads(json.dumps(_STATUS))
    return {
        "mode": RAG_MODE,
        "embedding": {"model": EMBED_MODEL, "api": EMBED_API, **components["embedding"]},
        "reranker": {"model": RERANK_MODEL, "api": RERANK_API, **components["reranker"]},
    }


def _post_json(url: str, payload: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RetrievalModelError(type(exc).__name__) from exc


def _embed_batch(texts: list[str], *, query: bool = False) -> list[list[float]]:
    if not texts:
        return []
    inputs = [QUERY_INSTRUCTION + text if query else text for text in texts]
    result = _post_json(f"{EMBED_API}/embeddings", {
        "model": EMBED_MODEL,
        "input": inputs,
        "encoding_format": "float",
    })
    if result.get("error"):
        raise RetrievalModelError(str(result["error"]))
    rows = sorted(result.get("data", []), key=lambda row: row.get("index", 0))
    vectors = [row.get("embedding", []) for row in rows]
    if len(vectors) != len(texts) or not vectors or not vectors[0]:
        raise RetrievalModelError("embedding response incomplete")
    _mark("embedding", "ready")
    return vectors


def _record_key(record: dict) -> str:
    return f"{record.get('type')}:{record.get('source_id')}"


def _passage(record: dict) -> str:
    prefix = " | ".join(str(value) for value in (
        record.get("type"), record.get("section"), record.get("speaker"),
        f"page {record.get('page_number')}" if record.get("page_number") else None,
        record.get("status"),
    ) if value)
    return f"{prefix}\n{record.get('text', '')}"[:MAX_PASSAGE_CHARS]


def record_revision(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(_record_key(record).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_passage(record).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:20]


def _index_paths(mdir: Path) -> tuple[Path, Path]:
    root = Path(mdir) / ".rag"
    stem = re_safe(EMBED_MODEL)
    return root / f"{stem}.json", root / f"{stem}.f32"


def re_safe(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCK:
        return _INDEX_LOCKS.setdefault(key, threading.Lock())


def _load_index(manifest_path: Path, vector_path: Path, revision: str,
                expected_keys: list[str]) -> tuple[int, array] | None:
    cache_key = str(manifest_path)
    cached = _CACHE.get(cache_key)
    if cached and cached[0] == revision and cached[2] == expected_keys:
        return cached[1], cached[3]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dimension = int(manifest["dimension"])
        if (manifest.get("schema") != INDEX_SCHEMA or manifest.get("model") != EMBED_MODEL
                or manifest.get("record_revision") != revision
                or manifest.get("keys") != expected_keys):
            return None
        vectors = array("f")
        with vector_path.open("rb") as stream:
            vectors.fromfile(stream, len(expected_keys) * dimension)
        if len(vectors) != len(expected_keys) * dimension:
            return None
        _CACHE[cache_key] = (revision, dimension, expected_keys, vectors)
        return dimension, vectors
    except (OSError, ValueError, KeyError, json.JSONDecodeError, EOFError):
        return None


def _build_index(mdir: Path, records: list[dict], manifest_path: Path, vector_path: Path,
                 revision: str, keys: list[str]) -> tuple[int, array]:
    passages = [_passage(record) for record in records]
    vectors_list: list[list[float]] = []
    for start in range(0, len(passages), EMBED_BATCH_SIZE):
        vectors_list.extend(_embed_batch(passages[start:start + EMBED_BATCH_SIZE]))
    dimension = len(vectors_list[0]) if vectors_list else 0
    if not dimension or any(len(vector) != dimension for vector in vectors_list):
        raise RetrievalModelError("embedding dimensions are inconsistent")
    vectors = array("f", (value for vector in vectors_list for value in vector))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temp_vectors = vector_path.with_name(f".{vector_path.name}.{token}.tmp")
    temp_manifest = manifest_path.with_name(f".{manifest_path.name}.{token}.tmp")
    with temp_vectors.open("wb") as stream:
        vectors.tofile(stream)
    temp_manifest.write_text(json.dumps({
        "schema": INDEX_SCHEMA,
        "model": EMBED_MODEL,
        "record_revision": revision,
        "dimension": dimension,
        "count": len(keys),
        "keys": keys,
        "created_at": time.time(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_vectors.replace(vector_path)
    temp_manifest.replace(manifest_path)
    _CACHE[str(manifest_path)] = (revision, dimension, keys, vectors)
    return dimension, vectors


def _ensure_index(mdir: Path, records: list[dict]) -> tuple[str, str, int, array]:
    if not records:
        raise RetrievalModelError("meeting has no indexable records")
    manifest_path, vector_path = _index_paths(mdir)
    keys = [_record_key(record) for record in records]
    revision = record_revision(records)
    lock = _lock_for(manifest_path)
    with lock:
        loaded = _load_index(manifest_path, vector_path, revision, keys)
        if loaded:
            dimension, vectors = loaded
            return "cached", revision, dimension, vectors
        dimension, vectors = _build_index(
            mdir, records, manifest_path, vector_path, revision, keys)
        return "built", revision, dimension, vectors


def ensure_index(mdir: Path, records: list[dict]) -> dict:
    """预建当前会议索引；返回元数据，不暴露正文或向量。"""
    if RAG_MODE not in {"hybrid", "dense"}:
        return {"state": "disabled", "count": len(records), "mode": RAG_MODE}
    state, revision, dimension, _vectors = _ensure_index(Path(mdir), records)
    return {
        "state": state,
        "count": len(records),
        "dimension": dimension,
        "record_revision": revision,
        "model": EMBED_MODEL,
    }


def dense_rank(mdir: Path, records: list[dict], query: str, limit: int = 60) -> list[dict]:
    if RAG_MODE not in {"hybrid", "dense"} or not records:
        return []
    try:
        _state, _revision, dimension, vectors = _ensure_index(Path(mdir), records)
        query_vector = _embed_batch([query], query=True)[0]
        if len(query_vector) != dimension:
            raise RetrievalModelError("query embedding dimension mismatch")
        scored = []
        for index, record in enumerate(records):
            offset = index * dimension
            score = sum(query_vector[pos] * vectors[offset + pos] for pos in range(dimension))
            scored.append({**record, "_dense_score": float(score)})
        return sorted(scored, key=lambda row: row["_dense_score"], reverse=True)[:limit]
    except RetrievalModelError as exc:
        _mark("embedding", "error", str(exc))
        return []


def rerank(query: str, records: list[dict], limit: int = 18) -> list[dict]:
    if RAG_MODE != "hybrid" or not records:
        return records[:limit]
    documents = [_passage(record) for record in records]
    try:
        result = _post_json(f"{RERANK_API}/reranking", {
            "query": query,
            "documents": documents,
        })
        rows = result.get("results", [])
        if len(rows) != len(records):
            raise RetrievalModelError("reranker response incomplete")
        reranked = []
        for row in rows:
            index = int(row["index"])
            if 0 <= index < len(records):
                reranked.append({**records[index],
                                 "_rerank_score": float(row.get("relevance_score", 0))})
        _mark("reranker", "ready")
        return reranked[:limit]
    except (RetrievalModelError, KeyError, TypeError, ValueError) as exc:
        _mark("reranker", "error", str(exc))
        return records[:limit]


def cosine(a: list[float], b: list[float]) -> float:
    """供合成测试使用。生产向量已经 L2 归一化。"""
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / denom if denom else 0.0
