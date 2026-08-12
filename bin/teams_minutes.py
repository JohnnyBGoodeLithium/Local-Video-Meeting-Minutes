#!/usr/bin/env python3
"""Teams 会议录制 → 带截图的会议纪要(全本地)。

输入：Teams 导出的 .mp4(含屏幕共享) + 微软 ASR 的 .vtt(自带说话人标签)。

流程：
    1. ffmpeg 抽 16k 单声道音轨 → 会议目录/audio.wav
    2. pyannote 本地分离(含每类聚类的声纹)
    3. 解析 VTT 具名 turns；把分离聚类对齐到 VTT 标签：
       - 远程参会者(自己设备) → 直接用 Teams 真实姓名
       - 主导标签(通常是会议室设备)覆盖多个声纹聚类 → 按聚类拆成"标签(声音K)"
    4. 声纹库 speaker_bank/：聚类质心与库内比对(跨会议认人)，命中则改用库内人名；
       新声纹自动入库(真名自动建 person，房间声音待人工绑定)
    5. 屏幕共享逻辑页：屏蔽摄像头条后逐秒比对画面、自动阈值切段、回翻认页
       → 会议目录/slides/ + slides.json(每页首次出现时间与图片)
    6. 具名逐字稿 + 页时间线 → 本地 Qwen3.6 多遍(关思考) → 按页纪要：
       总体摘要 + 议题板块(连续页归并) + 逐页讨论详情(每页内嵌该页截图)

输出：meetings/<日期>_<会议标题>/，自包含：
    audio.wav  transcript.spk.md/json  minutes.md  slides/

用法：
    bin/teams_minutes.py meeting.mp4 meeting.vtt
    bin/teams_minutes.py meeting.mp4 meeting.vtt --num-speakers 6 --match-threshold 0.72

隐私红线：全程本地；stdout 只打印元数据(数量/时长/耗时)，不打印人名与内容。
"""

import argparse
import json
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from meeting_dir import for_teams, materialize_source
from slide_pages import extract_pages
from minutes_by_page import generate as generate_minutes
import meeting_topic_map
import meeting_generation
import voice_bank as vb

ROOT = Path(__file__).resolve().parent.parent
PYANN = Path.home() / ".local/share/models/hf/pyannote/speaker-diarization-community-1"
BANK_DIR = ROOT / "speaker_bank"


def slugify(name: str) -> str:
    name = re.sub(r"-?\d{8}(_\d{6})?", "", name)          # 去日期时间
    name = re.sub(r"-?Meeting Recording", "", name, flags=re.I)
    name = re.sub(r"[^\w一-鿿-]+", "-", name).strip("-")  # 非字母数字转 -
    return re.sub(r"-{2,}", "-", name) or "meeting"


def to_sec(ts: str) -> float:
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    return int(parts[0]) * 60 + float(parts[1])


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s//60:02d}:{s%60:02d}"


def parse_vtt(path: Path):
    """VTT → [{name,start,end,text}]。只认 <v 名字>文本</v> 与 时间戳行。"""
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw)
    cues = []
    for b in blocks:
        m = re.search(r"(\d{2}:\d{2}:\d{2}[.,]\d{3}) --> (\d{2}:\d{2}:\d{2}[.,]\d{3})", b)
        if not m:
            continue
        vm = re.search(r"<v ([^>]+)>(.*?)</v>", b, re.S)
        if vm:
            name, text = vm.group(1).strip(), vm.group(2)
        else:
            name, text = "未具名", b[m.end():]
        text = re.sub(r"<[^>]+>", "", text).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            cues.append({"name": name, "start": to_sec(m.group(1).replace(",", ".")),
                         "end": to_sec(m.group(2).replace(",", ".")), "text": text})
    return cues


def merge_same(items, key, max_gap=2.0):
    """相邻且同 key 的项合并为 turns。"""
    turns = []
    for it in items:
        if turns and it[key] == turns[-1][key] and it["start"] - turns[-1]["end"] <= max_gap:
            turns[-1]["end"] = it["end"]
            turns[-1]["text"] += " " + it["text"]
        else:
            turns.append(dict(it))
    return turns


def extract_audio(mp4: Path, wav: Path):
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4),
                    "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav)], check=True)


def diarize(wav: Path, num_speakers=None):
    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(str(PYANN))
    pipeline.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    audio = {"waveform": torch.from_numpy(data.T), "sample_rate": sr}
    kw = {"num_speakers": num_speakers} if num_speakers else {}
    out = pipeline(audio, **kw)
    ann = out.speaker_diarization
    turns = sorted((t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True))
    labels = ann.labels()
    emb = getattr(out, "speaker_embeddings", None)
    centroids = {lab: emb[i] for i, lab in enumerate(labels)} if emb is not None else {}
    return turns, centroids


def align(vtt_cues, dia_turns):
    """聚类 ↔ VTT 标签对齐。返回 (final_cues, stats, lab2final)。

    lab2final: 分离聚类标签 → 最终显示名(远程=Teams 真名; 主导房间标签按聚类拆 声音K)。
    """
    labels = sorted({l for _, _, l in dia_turns})
    overlap = {l: {} for l in labels}
    for s, e, lab in dia_turns:
        for c in vtt_cues:
            ov = min(e, c["end"]) - max(s, c["start"])
            if ov > 0:
                overlap[lab][c["name"]] = overlap[lab].get(c["name"], 0) + ov
    # 主导标签 = cue 总时长最长者（视为会议室设备通道）
    dur = {}
    for c in vtt_cues:
        dur[c["name"]] = dur.get(c["name"], 0) + c["end"] - c["start"]
    room = max(dur, key=dur.get) if dur else None
    lab2name = {l: (max(o, key=o.get) if o else "未知") for l, o in overlap.items()}
    room_labs = [l for l in labels if lab2name[l] == room]
    first_seen = {l: min(s for s, _, x in dia_turns if x == l) for l in room_labs}
    room_labs.sort(key=lambda l: first_seen[l])
    do_split = len(room_labs) > 1
    sub = {l: f"{room}(声音{i+1})" for i, l in enumerate(room_labs)} if do_split else {}
    lab2final = {l: sub.get(l, lab2name[l]) for l in labels}
    final = []
    for c in vtt_cues:
        if c["name"] == room and do_split:
            best, best_ov = None, 0.0
            for s, e, lab in dia_turns:
                if lab not in sub:
                    continue
                ov = min(e, c["end"]) - max(s, c["start"])
                if ov > best_ov:
                    best, best_ov = sub[lab], ov
            c = dict(c, name=best or f"{room}(声音?)")
        final.append(c)
    stats = {"clusters": len(labels), "room_clusters": len(room_labs) if do_split else 0}
    return final, stats, lab2final


def update_bank(name2vec, slug, threshold):
    """声纹入库/比对。返回 (rename映射, voice_id映射, linked, new)。命中库的输入名会改成库内人名。"""
    bank = vb.load_bank(BANK_DIR)
    rename, voice_of, linked, new = {}, {}, 0, 0
    for name, vec in name2vec.items():
        entry, sim = vb.match_voice(BANK_DIR, bank, vec, threshold)
        if entry is not None:
            if slug not in entry.setdefault("sources", []):
                entry["sources"].append(slug)
            rename[name] = vb.display_name(bank, entry)
            linked += 1
        else:
            pid = None
            if "(声音" not in name and name not in ("未知", "未具名"):
                person, _ = vb.resolve_person(bank, name)  # 真名: 已有人则复用, 否则新建
                pid = person["id"] if person else vb.add_person(bank, name)["id"]
            entry = vb.add_voice(BANK_DIR, bank, vec, label_hint=name,
                                 source=slug, person_id=pid)
            rename[name] = vb.display_name(bank, entry)
            new += 1
        voice_of[name] = entry["id"]
    vb.save_bank(BANK_DIR, bank)
    return rename, voice_of, linked, new


def main() -> int:
    ap = argparse.ArgumentParser(description="Teams 录制 → 带截图纪要(全本地)")
    ap.add_argument("mp4", type=Path)
    ap.add_argument("vtt", type=Path)
    ap.add_argument("--slug", default=None, help="会议标题(用于目录名，默认从文件名生成)")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--match-threshold", type=float, default=0.70, help="声纹跨会议匹配阈值")
    ap.add_argument("--no-vl", action="store_true", help="跳过 VL 画面解读(更快)")
    args = ap.parse_args()

    if not args.mp4.is_file() or not args.vtt.is_file():
        print("输入文件不存在", file=sys.stderr)
        return 1

    date_m = re.search(r"(\d{8})", args.mp4.name)
    title_slug = args.slug or slugify(args.vtt.stem)
    mdir = for_teams(ROOT, title_slug, date_m.group(1) if date_m else "")
    mdir.mkdir(parents=True, exist_ok=True)
    original_mp4, original_vtt = args.mp4.resolve(), args.vtt.resolve()
    source_mp4 = materialize_source(original_mp4, mdir / f"source_video{args.mp4.suffix.lower()}")
    source_vtt = materialize_source(original_vtt, mdir / "source.vtt")
    slug = mdir.name
    t_all = time.time()

    print(f"[1/7] 抽音轨 → {mdir}", flush=True)
    wav = mdir / "audio.wav"
    extract_audio(source_mp4, wav)

    print("[2/7] 本地说话人分离 ...", flush=True)
    t0 = time.time()
    dia_turns, centroids = diarize(wav, args.num_speakers)
    print(f"[meta] 分离 {time.time()-t0:.1f}s | 声纹聚类 {len(centroids)} 个", flush=True)

    print("[3/7] 解析 VTT 并对齐姓名 ...", flush=True)
    cues = parse_vtt(source_vtt)
    final_cues, stats, lab2final = align(cues, dia_turns)
    turns = merge_same(final_cues, "name")

    print("[4/7] 声纹库比对/入库 ...", flush=True)
    name2vec = {lab2final[l]: centroids[l] for l in lab2final if l in centroids}
    rename, voice_of, linked, new = update_bank(name2vec, slug, args.match_threshold)
    # 显示名 → 声纹 id(多个聚类同名时取其一, best-effort)
    voice_by_display = {}
    for n, disp in rename.items():
        voice_by_display.setdefault(disp, voice_of[n])
    for t in turns:
        if t["name"] in rename:
            t["name"] = rename[t["name"]]
    print(f"[meta] 声纹库: 新入库 {new} | 跨会议命中 {linked}", flush=True)

    (mdir / "source.json").write_text(json.dumps(
        {"mp4": str(source_mp4), "vtt": str(source_vtt),
         "original_mp4": str(original_mp4), "original_vtt": str(original_vtt)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (mdir / "transcript.spk.json").write_text(json.dumps(
        [{"speaker": t["name"], "voice": voice_by_display.get(t["name"]),
          "start": round(t["start"], 3), "end": round(t["end"], 3), "text": t["text"]}
         for t in turns], ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# {slug} 逐字稿(具名)\n"]
    md += [f"[{mmss(t['start'])}] **{t['name']}**: {t['text']}\n" for t in turns]
    (mdir / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")

    # 未绑定声音自动切试听片段(供网页/CLI 绑定前试听)
    subprocess.run([sys.executable, str(ROOT / "bin" / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)

    print("[5/7] 先生成语音草稿纪要 ...", flush=True)
    meeting_generation.generate_voice_draft(mdir, python=sys.executable)
    meeting_generation.begin_visual_enrichment(mdir)

    print("[6/7] 抽屏幕共享逻辑页 ...", flush=True)
    t0 = time.time()
    pages = extract_pages(source_mp4, mdir / "slides", mdir / "slides.json")
    print(f"[meta] 逻辑页 {len(pages)} 页 | 抽页耗时 {time.time()-t0:.1f}s", flush=True)

    print("[7/7] 用 VL 屏幕资料升级多模态纪要 ...", flush=True)
    out_path, mstats = generate_minutes(mdir, video=source_mp4, vl=not args.no_vl)
    meeting_generation.finalize(
        mdir, pages=mstats["pages"], vl_pages=mstats["vl_pages"])
    print(f"[meta] 多模态纪要已替换语音草稿 | VL {mstats['vl_pages']}/{mstats['pages']} 页",
          flush=True)
    meeting_topic_map.generate_for_pipeline(mdir)

    speakers = sorted({t["name"] for t in turns})
    print(f"[meta] 总耗时 {time.time()-t_all:.1f}s | 说话人标签 {len(speakers)} 个"
          f"(含房间拆分 {stats['room_clusters']} 个声音) | 轮次 {len(turns)}"
          f" | 纪要 {mstats['chars']} 字 | 页块 {mstats['page_blocks']}/{mstats['pages']}", flush=True)
    print(f"[meta] 纪要: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
