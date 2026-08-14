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


def enroll(name2vec: dict, slug: str, threshold: float = 0.70, bank_dir: Path = None):
    """匿名声纹入库/比对。返回 (显示名映射, voice_id映射, linked, new)。
    与 video_minutes 同一语义: 占位名(说话人K)不自动建 person, 等人工绑定。"""
    bank_dir = bank_dir or (ROOT / "speaker_bank")
    bank = vb.load_bank(bank_dir)
    rename, voice_of, linked, new = {}, {}, 0, 0
    for name, vec in name2vec.items():
        entry, sim = vb.match_voice(bank_dir, bank, vec, threshold)
        if entry is None:
            entry = vb.add_voice(bank_dir, bank, vec, label_hint=name, source=slug)
            new += 1
        else:
            if slug not in entry.setdefault("sources", []):
                entry["sources"].append(slug)
            linked += 1
        rename[name] = vb.display_name(bank, entry)
        voice_of[name] = entry["id"]
    vb.save_bank(bank_dir, bank)
    return rename, voice_of, linked, new


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
    print(f"[meta] 声纹库: 新入库 {new} | 跨会议命中 {linked} | 轮次 {len(turns)}", flush=True)
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
