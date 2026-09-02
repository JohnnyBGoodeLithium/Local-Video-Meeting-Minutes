#!/usr/bin/env python3
"""声纹入库/比对(可复用):diarization.json + audio.wav → 每个说话人的声纹质心 →
声纹库匹配或匿名新建 → 回写 transcript.spk.json 的 voice 字段与显示名 + 试听片段。

用途:
    1. run_all.py(录音笔音频管线)在合并轮次后调用,补齐 voice 字段,使网页端可绑定;
    2. 存量会议回填: bin/voice_enroll.py meetings/<slug> [--threshold 0.70]

stdout 只打印元数据(人数/命中数),不打印任何姓名与内容。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_bank as vb  # noqa: E402
from meeting_core.hardware import configured_path, inference_device  # noqa: E402
from teams_minutes import mmss  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = Path(__import__("os").environ.get("MEETING_PYTHON", sys.executable)).expanduser()
EMB_DIR = configured_path(
    "MEETING_PYANNOTE_MODEL",
    Path.home() / ".local/share/models/hf/pyannote/speaker-diarization-community-1") / "embedding"


def centroids_from_segments(wav: Path, segments: list, device: str = None) -> dict:
    """滑窗提取整段音频的 embedding,按分离段聚合出每个说话人的均值质心。

    segments: [{"start": float, "end": float, "speaker": "说话人N"}, ...]
    返回 {说话人名: np.ndarray}。
    """
    import soundfile as sf
    import torch
    from pyannote.audio import Inference, Model
    from pyannote.core import Segment, Timeline

    model = Model.from_pretrained(str(EMB_DIR))
    inf = Inference(model, window="sliding", duration=1.5, step=0.75)
    inf.to(torch.device(device or inference_device(torch)))
    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    emb = inf({"waveform": torch.from_numpy(data.T), "sample_rate": sr})
    by_label = {}
    for seg in segments:
        by_label.setdefault(seg["speaker"], []).append(
            Segment(float(seg["start"]), float(seg["end"])))
    out = {}
    for label, spans in by_label.items():
        cropped = np.asarray(emb.crop(Timeline(spans)))
        if len(cropped):
            out[label] = cropped.mean(axis=0)
    return out


def embed_ranges(wav: Path, ranges: list, device: str = None) -> np.ndarray:
    """按任意时间区间逐段提取 embedding。ranges: [(start, end), ...]，返回 (N, D) 矩阵。
    用于声纹拆分：只对所选轮次的音频段推理，不再整音频滑窗。"""
    import soundfile as sf
    import torch
    from pyannote.audio import Inference, Model

    model = Model.from_pretrained(str(EMB_DIR))
    inf = Inference(model, window="whole")
    inf.to(torch.device(device or inference_device(torch)))
    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    mono = torch.from_numpy(data.mean(axis=1))
    min_len = int(0.4 * sr)
    out = []
    for start, end in ranges:
        lo = max(0, int(float(start) * sr))
        hi = min(mono.numel(), max(lo + 1, int(float(end) * sr)))
        seg = mono[lo:hi]
        if seg.numel() < min_len:
            seg = torch.nn.functional.pad(seg, (0, min_len - seg.numel()))
        vec = inf({"waveform": seg.unsqueeze(0), "sample_rate": sr})
        out.append(np.asarray(vec, dtype=np.float32).reshape(-1))
    return np.vstack(out) if out else np.zeros((0, 0), dtype=np.float32)


def cluster_embeddings(vecs: np.ndarray, threshold: float = 0.70) -> list:
    """贪心余弦聚类：每条向量归入第一个相似度达标的簇（质心取运行均值），否则开新簇。
    返回与输入等长的簇索引列表。"""
    if not len(vecs):
        return []
    norm = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    centroids, counts, assign = [], [], []
    for v in norm:
        best, best_sim = -1, threshold
        for k, c in enumerate(centroids):
            sim = float(np.dot(v, c))
            if sim >= best_sim:
                best, best_sim = k, sim
        if best < 0:
            centroids.append(v)
            counts.append(1)
            assign.append(len(centroids) - 1)
        else:
            counts[best] += 1
            centroids[best] = centroids[best] + (v - centroids[best]) / counts[best]
            assign.append(best)
    return assign


def reassign_by_centroids(rest_vecs: np.ndarray, base_centroid: np.ndarray,
                          new_centroids: list) -> list:
    """半监督重排：rest 中每条向量分别与基准质心（原声纹校正后）和各新簇质心求
    余弦相似度，若更接近某个新簇则返回该簇索引，否则返回 None（留在原声纹）。
    长会议拆分只需用户标出少量样例轮次，其余按“离谁近归谁”自动重排。"""
    if not len(rest_vecs):
        return []
    if not len(new_centroids):
        return [None] * len(rest_vecs)
    norm = rest_vecs / (np.linalg.norm(rest_vecs, axis=1, keepdims=True) + 1e-9)
    base = np.asarray(base_centroid, dtype=np.float32)
    base = base / (np.linalg.norm(base) + 1e-9)
    cents = [np.asarray(c, dtype=np.float32) for c in new_centroids]
    cents = [c / (np.linalg.norm(c) + 1e-9) for c in cents]
    out = []
    for v in norm:
        best, best_sim = None, float(np.dot(v, base))
        for k, c in enumerate(cents):
            sim = float(np.dot(v, c))
            if sim > best_sim:
                best, best_sim = k, sim
        out.append(best)
    return out


def suggest_reassignments(rest_vecs: np.ndarray, base_centroid: np.ndarray,
                          new_centroids: list, *, threshold: float = 0.78,
                          margin: float = 0.08) -> tuple[list, list[bool]]:
    """给人工拆分生成保守扩散建议，而不是强制二选一。

    新簇相似度必须同时达到绝对门槛，并比原簇高出 ``margin`` 才建议移动；
    仅仅“略像新簇”的轮次进入 ambiguous，保持原状等待人工判断。
    """
    if not len(rest_vecs):
        return [], []
    if not len(new_centroids):
        return [None] * len(rest_vecs), [False] * len(rest_vecs)
    norm = rest_vecs / (np.linalg.norm(rest_vecs, axis=1, keepdims=True) + 1e-9)
    base = np.asarray(base_centroid, dtype=np.float32)
    base = base / (np.linalg.norm(base) + 1e-9)
    cents = [np.asarray(value, dtype=np.float32) for value in new_centroids]
    cents = [value / (np.linalg.norm(value) + 1e-9) for value in cents]
    moves, ambiguous = [], []
    for vector in norm:
        base_sim = float(np.dot(vector, base))
        scores = [float(np.dot(vector, centroid)) for centroid in cents]
        best = int(np.argmax(scores))
        best_sim = scores[best]
        accepted = best_sim >= threshold and best_sim - base_sim >= margin
        moves.append(best if accepted else None)
        # 达到基础相似度、但没有拉开足够优势的轮次属于“存疑”；等距或轻微
        # 偏向原簇也应交给用户判断，不能悄悄当作无关项隐藏。
        ambiguous.append(not accepted and best_sim >= threshold
                         and best_sim >= base_sim - margin)
    return moves, ambiguous


def enroll(name2vec: dict, slug: str, threshold: float = 0.70, bank_dir: Path = None):
    """匿名声纹入库/比对。返回 (显示名映射, voice_id映射, linked, new)。
    与 video_minutes 同一语义: 占位名(说话人K)不自动建 person, 等人工绑定。"""
    bank_dir = bank_dir or (ROOT / "speaker_bank")
    bank = vb.load_bank(bank_dir)
    candidates = list(bank["voices"])
    claimed_unbound = set()
    claimed_persons = set()
    rename, voice_of, linked, new = {}, {}, 0, 0
    for name, vec in name2vec.items():
        entry, sim, _ = vb.match_session_voice(
            bank_dir, bank, candidates, vec, threshold, slug, name, claimed_unbound,
            claimed_persons)
        if entry is None:
            entry = vb.add_voice(bank_dir, bank, vec, label_hint=name, source=slug)
            new += 1
        else:
            if slug not in entry.setdefault("sources", []):
                entry["sources"].append(slug)
            linked += 1
        vb.remember_source_cluster(entry, slug, name, bank=bank)
        rename[name] = vb.display_name(bank, entry)
        voice_of[name] = entry["id"]
    vb.save_bank(bank_dir, bank)
    return rename, voice_of, linked, new


def merge_fragment_voices(mdir: Path, bank_dir: Path = None, max_turns: int = 2,
                          threshold: float = 0.80) -> dict:
    """会后碎片声纹清理：本会议中轮次 ≤max_turns 且未被人工绑定（person_id 为空）
    的声纹，用高于入库的阈值再匹配一次库内其他声纹；命中则把这些轮次并入目标
    声纹。只来源于本会议的碎片条目同时从库中删除；多会议共用的保留条目只摘
    source。返回 {"merged": 合并条数, "turns": 改派轮数}，不打印姓名。"""
    from collections import Counter
    bank_dir = Path(bank_dir or (ROOT / "speaker_bank"))
    ts_path = mdir / "transcript.spk.json"
    if not ts_path.is_file():
        return {"merged": 0, "turns": 0}
    turns = json.loads(ts_path.read_text(encoding="utf-8"))
    counts = Counter(t.get("voice") for t in turns if t.get("voice"))
    fragments = [v for v, c in counts.items() if 0 < c <= max_turns]
    if not fragments:
        return {"merged": 0, "turns": 0}
    bank = vb.load_bank(bank_dir)
    merged = moved = 0
    for frag in fragments:
        entry = next((v for v in bank["voices"] if v["id"] == frag), None)
        if entry is None or entry.get("person_id"):
            continue  # 库中不存在或已被人工绑定过的碎片不动
        vec = vb.vec_of(bank_dir, entry)
        best, best_sim = None, threshold
        for other in bank["voices"]:
            if other["id"] == frag:
                continue
            sim = float(np.dot(vec, vb.vec_of(bank_dir, other)))
            if sim >= best_sim:
                best, best_sim = other, sim
        if best is None:
            continue
        name = vb.display_name(bank, best)
        for t in turns:
            if t.get("voice") == frag:
                t["voice"] = best["id"]
                t["speaker"] = name
                moved += 1
        if set(entry.get("sources", [])) <= {mdir.name}:
            bank["voices"].remove(entry)
            (bank_dir / entry["emb"]).unlink(missing_ok=True)
        else:
            vb.forget_source(entry, mdir.name)
        merged += 1
    if not merged:
        return {"merged": 0, "turns": 0}
    vb.save_bank(bank_dir, bank)
    tmp = ts_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ts_path)
    md = [f"# {mdir.name} 逐字稿(具名)\n"]
    md += [f"[{mmss(t['start'])}] **{t['speaker']}**: {t['text']}\n" for t in turns]
    (mdir / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")
    return {"merged": merged, "turns": moved}


def enroll_meeting(mdir: Path, threshold: float = 0.70, device: str = None) -> int:
    """对单个会议目录执行回填/入库。返回进程退出码。"""
    dia_path = mdir / "diarization.json"
    ts_path = mdir / "transcript.spk.json"
    wav = mdir / "audio.wav"
    if not (dia_path.is_file() and ts_path.is_file() and wav.is_file()):
        print("[meta] 缺少 diarization.json / transcript.spk.json / audio.wav, 跳过", flush=True)
        return 1
    segments = json.loads(dia_path.read_text(encoding="utf-8"))
    name2vec = centroids_from_segments(wav, segments, device=device)
    if not name2vec:
        print("[meta] 未提取到声纹质心, 跳过", flush=True)
        return 1
    rename, voice_of, linked, new = enroll(name2vec, mdir.name, threshold)
    turns = json.loads(ts_path.read_text(encoding="utf-8"))
    for t in turns:
        if t.get("speaker") in voice_of:
            t["voice"] = voice_of[t["speaker"]]
            t["speaker"] = rename.get(t["speaker"], t["speaker"])
    tmp = ts_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ts_path)
    md = [f"# {mdir.name} 逐字稿(具名)\n"]
    md += [f"[{mmss(t['start'])}] **{t['speaker']}**: {t['text']}\n" for t in turns]
    (mdir / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[meta] 声纹库: 新入库 {new} | 已有声纹命中 {linked} | 轮次 {len(turns)}", flush=True)
    frag = merge_fragment_voices(mdir)
    if frag["merged"]:
        print(f"[meta] 碎片声纹清理: 合并 {frag['merged']} 条 | 改派 {frag['turns']} 轮",
              flush=True)
    subprocess.run([sys.executable, str(ROOT / "bin" / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="会议声纹入库/回填")
    ap.add_argument("meeting", type=Path, help="会议目录(meetings/<slug>)")
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--device", default=None, help="cpu/cuda(默认自动)")
    args = ap.parse_args()
    mdir = args.meeting.resolve()
    if not mdir.is_dir():
        print(f"会议目录不存在: {mdir}", file=sys.stderr)
        return 1
    return enroll_meeting(mdir, threshold=args.threshold, device=args.device)


if __name__ == "__main__":
    sys.exit(main())
