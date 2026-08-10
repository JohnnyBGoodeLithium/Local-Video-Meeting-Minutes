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

from meeting_dir import for_teams
import voice_bank as vb
from diarize import smooth_dia
from teams_minutes import extract_audio, diarize, slugify, mmss
from slide_pages import extract_pages
from minutes_by_page import generate as generate_minutes

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
PY = ROOT / ".venv" / "bin" / "python"
BANK_DIR = ROOT / "speaker_bank"


def enroll(name2vec, slug, threshold=0.70):
    """匿名声纹入库/比对。返回 (显示名映射, voice_id映射, linked, new)。
    与 teams 版不同: 占位名(说话人K)不自动建 person, 等人工绑定。"""
    bank = vb.load_bank(BANK_DIR)
    rename, voice_of, linked, new = {}, {}, 0, 0
    for name, vec in name2vec.items():
        entry, sim = vb.match_voice(BANK_DIR, bank, vec, threshold)
        if entry is None:
            entry = vb.add_voice(BANK_DIR, bank, vec, label_hint=name, source=slug)
            new += 1
        else:
            if slug not in entry.setdefault("sources", []):
                entry["sources"].append(slug)
            linked += 1
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
    args = ap.parse_args()
    if not args.mp4.is_file():
        print("输入文件不存在", file=sys.stderr)
        return 1

    date_m = re.search(r"(\d{8})", args.mp4.name)
    mdir = for_teams(ROOT, args.slug or slugify(args.mp4.stem), date_m.group(1) if date_m else "")
    mdir.mkdir(parents=True, exist_ok=True)
    slug = mdir.name
    t_all = time.time()
    env = dict(os.environ, HF_HUB_OFFLINE="1")

    print(f"[1/5] 抽音轨 → {mdir}", flush=True)
    wav = mdir / "audio.wav"
    extract_audio(args.mp4, wav)

    print("[2/5] 转写 ∥ 说话人分离 ...", flush=True)
    tr_cmd = [str(PY), str(BIN / "transcribe.py"), str(wav), "--out", str(mdir)]
    if args.language:
        tr_cmd += ["--language", args.language]
    p_tr = subprocess.Popen(tr_cmd, env=env)
    t0 = time.time()
    dia_turns, centroids = diarize(wav, args.num_speakers)
    dia_turns = smooth_dia(dia_turns)   # 亚秒碎段平滑
    print(f"[meta] 分离 {time.time()-t0:.1f}s | 声纹聚类 {len(centroids)} 个"
          f" | 平滑后段数 {len(dia_turns)}", flush=True)
    if p_tr.wait():
        print("转写失败", file=sys.stderr)
        return 1

    labels = sorted({l for _, _, l in dia_turns})
    name_of = {l: f"说话人{i+1}" for i, l in enumerate(labels)}   # 与 diarize.py 命名规则一致
    (mdir / "diarization.json").write_text(json.dumps(
        [{"start": round(s, 3), "end": round(e, 3), "speaker": name_of[l]}
         for s, e, l in dia_turns], ensure_ascii=False, indent=1), encoding="utf-8")

    print("[3/5] 合并轮次 + 声纹入库 ...", flush=True)
    rc = subprocess.run([str(PY), str(BIN / "diarize.py"), str(wav),
                         "--from-segments", str(mdir / "diarization.json"),
                         "--out", str(mdir)], env=env).returncode
    if rc:
        return 1
    name2vec = {name_of[l]: c for l, c in centroids.items()}
    rename, voice_of, linked, new = enroll(name2vec, slug, args.match_threshold)
    ts_path = mdir / "transcript.spk.json"
    turns = json.loads(ts_path.read_text(encoding="utf-8"))
    for t in turns:
        t["voice"] = voice_of.get(t["speaker"])
        t["speaker"] = rename.get(t["speaker"], t["speaker"])
    ts_path.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# {slug} 逐字稿(具名)\n"]
    md += [f"[{mmss(t['start'])}] **{t['speaker']}**: {t['text']}\n" for t in turns]
    (mdir / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")
    (mdir / "source.json").write_text(json.dumps(
        {"mp4": str(args.mp4.resolve())}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meta] 声纹库: 新入库 {new} | 跨会议命中 {linked}", flush=True)
    subprocess.run([sys.executable, str(BIN / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)

    print("[4/5] 抽屏幕共享逻辑页 ...", flush=True)
    t0 = time.time()
    pages = extract_pages(args.mp4, mdir / "slides", mdir / "slides.json")
    print(f"[meta] 逻辑页 {len(pages)} 页 | 抽页耗时 {time.time()-t0:.1f}s", flush=True)

    print("[5/5] 生成按页纪要(VL画面内容+总体摘要+议题板块+逐页详情) ...", flush=True)
    out_path, mstats = generate_minutes(mdir, video=args.mp4, vl=not args.no_vl)
    print(f"[meta] 总耗时 {time.time()-t_all:.1f}s | 纪要 {mstats['chars']} 字"
          f" | 页块 {mstats['page_blocks']}/{mstats['pages']} | VL页数 {mstats['vl_pages']}",
          flush=True)
    print(f"[meta] 纪要: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
