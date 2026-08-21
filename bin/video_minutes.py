#!/usr/bin/env python3
"""无 VTT 的视频 → 带截图的按页会议纪要(全本地)。

与 teams_minutes.py 的差别：没有微软转写和姓名——转写走 Qwen3-ASR，
说话人是匿名聚类(说话人K)，声纹入库但不为占位名自动建 person(待网页/CLI 绑定)。

流程：
    [1/5] ffmpeg 抽 16k 单声道音轨
    [2/5] 转写(transcribe.py 子进程) ∥ 分离(pyannote 本进程, 含声纹质心)
    [3/5] 合并说话人轮次 → 声纹入库/比对(匿名) → 逐字稿写 voice 字段 + 试听片段
    [4/5] 屏幕共享逻辑页抽取(slide_pages)
    [5/5] 按页纪要(minutes_by_page: VL画面+总体摘要+板块+逐页详情)

用法：
    bin/video_minutes.py meeting.mp4 [--slug 标题] [--num-speakers N]

stdout 只打印元数据，不打印任何转写/纪要内容。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from meeting_dir import for_teams, materialize_source
from meeting_core.terminology import configured_bank_dir, safe_harvest_screen_candidates
from meeting_core.transcript_review import bind_review_to_transcript
import voice_bank as vb
from teams_minutes import extract_audio, diarize, slugify, mmss
from slide_pages import extract_pages
from minutes_by_page import generate as generate_minutes
import meeting_topic_map
import meeting_generation

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable)).expanduser()
BANK_DIR = ROOT / "speaker_bank"


def enroll(name2vec, slug, threshold=0.70):
    """匿名声纹入库/比对。返回 (显示名映射, voice_id映射, linked, new)。
    与 teams 版不同: 占位名(说话人K)不自动建 person, 等人工绑定。"""
    bank = vb.load_bank(BANK_DIR)
    candidates = list(bank["voices"])
    claimed_unbound = set()
    rename, voice_of, linked, new = {}, {}, 0, 0
    for name, vec in name2vec.items():
        entry, sim, _ = vb.match_session_voice(
            BANK_DIR, bank, candidates, vec, threshold, slug, name, claimed_unbound)
        if entry is None:
            entry = vb.add_voice(BANK_DIR, bank, vec, label_hint=name, source=slug)
            new += 1
        else:
            if slug not in entry.setdefault("sources", []):
                entry["sources"].append(slug)
            linked += 1
        vb.remember_source_cluster(entry, slug, name, bank=bank)
        rename[name] = vb.display_name(bank, entry)
        voice_of[name] = entry["id"]
    vb.save_bank(BANK_DIR, bank)
    return rename, voice_of, linked, new


def main() -> int:
    ap = argparse.ArgumentParser(description="无 VTT 视频 → 带截图按页纪要(全本地)")
    ap.add_argument("mp4", type=Path)
    ap.add_argument("--slug", default=None, help="会议标题(用于目录名, 默认从文件名生成)")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--match-threshold", type=float, default=0.70)
    ap.add_argument("--language", default=None, help="强制语言(如 Chinese)")
    ap.add_argument("--no-vl", action="store_true", help="跳过 VL 画面解读(更快)")
    ap.add_argument("--ignored-transcript", type=Path, default=None,
                    help="保留但不用于转写的 VTT/DOCX 原文件")
    ap.add_argument("--meeting-dir", type=Path, default=None,
                    help="在已有会议目录中重跑本地 ASR（只供受控包装器调用）")
    ap.add_argument("--reuse-visuals", action="store_true",
                    help="复用已有 slides/page_desc，不重新抽帧和读图")
    ap.add_argument("--reuse-asr", action="store_true",
                    help="故障恢复：复用完整 stamps.json，只重跑说话人及后续阶段")
    args = ap.parse_args()
    if not args.mp4.is_file():
        print("输入文件不存在", file=sys.stderr)
        return 1

    if args.ignored_transcript is not None:
        if (not args.ignored_transcript.is_file()
                or args.ignored_transcript.suffix.lower() not in {".vtt", ".docx"}):
            print("忽略的逐字稿必须是存在的 VTT 或 DOCX", file=sys.stderr)
            return 1
    if args.meeting_dir is not None:
        data_root = Path(os.environ.get(
            "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", ROOT))).resolve()
        mdir = args.meeting_dir.resolve()
        if mdir.parent != (data_root / "meetings").resolve() or not mdir.is_dir():
            print("已有会议目录不在受控 meetings 边界内", file=sys.stderr)
            return 1
    else:
        date_m = re.search(r"(\d{8})", args.mp4.name)
        mdir = for_teams(ROOT, args.slug or slugify(args.mp4.stem),
                         date_m.group(1) if date_m else "")
        mdir.mkdir(parents=True, exist_ok=True)
    original_mp4 = args.mp4.resolve()
    source_mp4 = materialize_source(original_mp4, mdir / f"source_video{args.mp4.suffix.lower()}")
    slug = mdir.name
    t_all = time.time()
    env = dict(os.environ, HF_HUB_OFFLINE="1")

    print(f"[1/6] 抽音轨 → {mdir}", flush=True)
    wav = mdir / "audio.wav"
    extract_audio(source_mp4, wav)

    print("[2/6] 转写 ∥ 说话人分离 ...", flush=True)
    tr_cmd = [str(PY), str(BIN / "transcribe.py"), str(wav), "--out", str(mdir),
              "--context-title", args.slug or slug]
    if args.reuse_asr:
        tr_cmd += ["--reuse-stamps"]
    if args.language:
        tr_cmd += ["--language", args.language]
    p_tr = subprocess.Popen(tr_cmd, env=env)
    t0 = time.time()
    dia_turns, centroids = diarize(wav, args.num_speakers)
    print(f"[meta] 分离 {time.time()-t0:.1f}s | 声纹聚类 {len(centroids)} 个"
          f" | 原始段数 {len(dia_turns)}", flush=True)
    if p_tr.wait():
        print("转写失败", file=sys.stderr)
        return 1

    labels = sorted({l for _, _, l in dia_turns})
    name_of = {l: f"说话人{i+1}" for i, l in enumerate(labels)}   # 与 diarize.py 命名规则一致
    (mdir / "diarization.json").write_text(json.dumps(
        [{"start": round(s, 3), "end": round(e, 3), "speaker": name_of[l]}
         for s, e, l in dia_turns], ensure_ascii=False, indent=1), encoding="utf-8")

    print("[3/6] 合并轮次 + 声纹入库 ...", flush=True)
    rc = subprocess.run([str(PY), str(BIN / "diarize.py"), str(wav),
                         "--from-segments", str(mdir / "diarization.json"),
                         "--out", str(mdir)], env=env).returncode
    if rc:
        return 1
    ts_path = mdir / "transcript.spk.json"
    turns = json.loads(ts_path.read_text(encoding="utf-8"))
    used_speakers = {str(t.get("speaker") or "") for t in turns}
    name2vec = {name_of[label]: vector for label, vector in centroids.items()
                if name_of[label] in used_speakers}
    rename, voice_of, linked, new = enroll(name2vec, slug, args.match_threshold)
    for t in turns:
        t["voice"] = voice_of.get(t["speaker"])
        t["speaker"] = rename.get(t["speaker"], t["speaker"])
    ts_path.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# {slug} 逐字稿(具名)\n"]
    md += [f"[{mmss(t['start'])}] **{t['speaker']}**: {t['text']}\n" for t in turns]
    (mdir / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")
    source_path = mdir / "source.json"
    try:
        source_meta = json.loads(source_path.read_text(encoding="utf-8")) \
            if source_path.is_file() else {}
    except Exception:
        source_meta = {}
    if not isinstance(source_meta, dict):
        source_meta = {}
    source_meta.setdefault("original_mp4", str(original_mp4))
    source_meta["mp4"] = str(source_mp4)
    source_meta["transcript_source"] = "local_asr"
    if args.ignored_transcript is not None:
        transcript_format = args.ignored_transcript.suffix.lower().lstrip(".")
        source_transcript = materialize_source(
            args.ignored_transcript, mdir / f"source.{transcript_format}")
        source_meta["external_transcript_status"] = "ignored"
        source_meta["external_transcript_format"] = transcript_format
        source_meta.setdefault("original_transcript", str(args.ignored_transcript.resolve()))
        source_meta["transcript"] = str(source_transcript)
        source_meta[transcript_format] = str(source_transcript)
    tmp_source = source_path.with_name(f".{source_path.name}.tmp-{os.getpid()}")
    tmp_source.write_text(json.dumps(source_meta, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(tmp_source, source_path)
    print(f"[meta] 声纹库: 新入库 {new} | 已有声纹命中 {linked}", flush=True)
    subprocess.run([sys.executable, str(BIN / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)
    review = bind_review_to_transcript(mdir)
    if review:
        summary = review.get("summary", {})
        print(f"[meta] 逐字稿音频复核 | 自动修正 {summary.get('auto_corrected', 0)}"
              f" | 待核听 {summary.get('pending', 0)}", flush=True)

    print("[4/6] 先生成语音草稿纪要 ...", flush=True)
    meeting_generation.generate_voice_draft(mdir, python=sys.executable)
    meeting_generation.begin_visual_enrichment(mdir)

    if args.reuse_visuals and (mdir / "slides.json").is_file():
        try:
            pages = json.loads((mdir / "slides.json").read_text(encoding="utf-8"))
        except Exception:
            pages = []
        print(f"[5/6] 复用已有屏幕逻辑页 {len(pages)} 页", flush=True)
    else:
        print("[5/6] 抽屏幕共享逻辑页 ...", flush=True)
        t0 = time.time()
        pages = extract_pages(source_mp4, mdir / "slides", mdir / "slides.json")
        print(f"[meta] 逻辑页 {len(pages)} 页 | 抽页耗时 {time.time()-t0:.1f}s", flush=True)

    print("[6/6] 用 VL 屏幕资料升级多模态纪要 ...", flush=True)
    out_path, mstats = generate_minutes(
        mdir, video=source_mp4, vl=not args.no_vl,
        reuse_vl_cache_only=args.reuse_visuals)
    meeting_generation.finalize(
        mdir, pages=mstats["pages"], vl_pages=mstats["vl_pages"])
    print(f"[meta] 多模态纪要已替换语音草稿 | VL {mstats['vl_pages']}/{mstats['pages']} 页",
          flush=True)
    meeting_topic_map.generate_for_pipeline(mdir)
    terminology = safe_harvest_screen_candidates(
        mdir, args.slug or slug, configured_bank_dir(ROOT))
    print(f"[meta] 术语候选 {terminology['state']} | 新增 {terminology['added']}"
          f" | 更新 {terminology['updated']}", flush=True)
    print(f"[meta] 总耗时 {time.time()-t_all:.1f}s | 纪要 {mstats['chars']} 字"
          f" | 页块 {mstats['page_blocks']}/{mstats['pages']} | VL页数 {mstats['vl_pages']}",
          flush=True)
    print(f"[meta] 纪要: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
