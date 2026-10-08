#!/usr/bin/env python3
"""普通视频／通用原文字幕 → 带截图的按页会议纪要(全本地)。

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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from meeting_dir import for_teams, materialize_source
from meeting_core.terminology import configured_bank_dir, safe_harvest_screen_candidates
from meeting_core.model_resolver import ModelNotInstalledError, resolve_pyannote_model
from meeting_core.transcript_review import bind_review_to_transcript
from meeting_core.resource_policy import prepare_stage
from meeting_core.llm import DEFAULT_DRAFT_MODEL, DEFAULT_MINUTES_MODEL
from meeting_core.progress_events import (output_ready, phase_done,
                                          progress as progress_event)
import voice_bank as vb
from teams_minutes import extract_audio, diarize, slugify, mmss
from slide_pages import extract_pages
from meeting_core.visual_mode import configure_extraction
from meeting_core.live.signals import generic_subtitle_signals
from meeting_core.media_captions import (CaptionError, normalize_language,
                                         MAX_CAPTION_BYTES, parse_caption_bytes)
from minutes_by_page import generate as generate_minutes
import meeting_topic_map
import meeting_generation

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable)).expanduser()
BANK_DIR = Path(os.environ.get("MEETING_WEB_BANK", str(ROOT / "speaker_bank"))).expanduser()


def _read_source(mdir: Path) -> dict:
    try:
        value = json.loads((mdir / "source.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _caption_fallback(provenance: dict, reason: str) -> None:
    provenance.update(source="local_asr", fallback_reason=reason,
                      selection_reason="asr_fallback", timestamp_source="asr")
    attempts = provenance.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if isinstance(attempt, dict) and attempt.get("status") == "selected":
            attempt.update(status="rejected", reason=reason)
    for key in ("kind", "language", "cue_count", "raw_sha256", "raw_bytes", "format"):
        provenance.pop(key, None)


def subtitle_turns(cues, dia_turns, name_of, *, language: str, kind: str) -> list[dict]:
    """保留 cue 粒度；仅用明确覆盖该 cue 的声音簇归属，不猜逐字时间或字幕姓名。"""
    signals = generic_subtitle_signals(cues, language=language, provisional=False)
    result = []
    for signal in signals:
        duration = signal.end - signal.start
        overlaps = {}
        for start, end, label in dia_turns:
            overlap = max(0, min(end, signal.end) - max(start, signal.start))
            overlaps[label] = overlaps.get(label, 0) + overlap
        ranked = sorted(overlaps, key=overlaps.get, reverse=True)
        label = ranked[0] if ranked else None
        confident = (label is not None and overlaps[label] >= duration * 0.8
                     and sum(overlaps[other] for other in ranked[1:]) <= duration * 0.1)
        result.append({
            "start": signal.start, "end": signal.end, "text": signal.text,
            "speaker": name_of[label] if confident else "说话人未知",
            "text_source": signal.text_source,
            "speaker_source": "local_diarization" if confident else "unknown",
            "language": language,
            "text_review_status": "automatic" if kind == "automatic" else "platform_provided",
            "timestamp_source": "subtitle_cues",
        })
    return result


def enroll(name2vec, slug, threshold=0.70):
    """匿名声纹入库/比对。返回 (显示名映射, voice_id映射, linked, new)。
    与 teams 版不同: 占位名(说话人K)不自动建 person, 等人工绑定。"""
    bank = vb.load_bank(BANK_DIR)
    candidates = list(bank["voices"])
    claimed_unbound = set()
    claimed_persons = set()
    rename, voice_of, linked, new = {}, {}, 0, 0
    for name, vec in name2vec.items():
        entry, sim, _ = vb.match_session_voice(
            BANK_DIR, bank, candidates, vec, threshold, slug, name, claimed_unbound,
            claimed_persons)
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
    ap = argparse.ArgumentParser(description="普通视频／通用原文字幕 → 带截图纪要(全本地)")
    ap.add_argument("mp4", type=Path)
    ap.add_argument("--slug", default=None, help="会议标题(用于目录名, 默认从文件名生成)")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--match-threshold", type=float, default=0.70)
    ap.add_argument("--language", default=None, help="强制语言(如 Chinese)")
    ap.add_argument("--no-vl", action="store_true", help="跳过 VL 画面解读(更快)")
    ap.add_argument("--subtitle", type=Path, default=None,
                    help="已确认原语言的通用 WebVTT；有效时跳过 ASR，不使用字幕姓名")
    ap.add_argument("--subtitle-language", default=None, help="原字幕语言代码")
    ap.add_argument("--subtitle-kind", choices=["human", "automatic"], default="human")
    ap.add_argument("--subtitle-sha256", default=None,
                    help="恢复专用：严格复用该字幕哈希，失效时拒绝自动 ASR")
    ap.add_argument("--ignored-transcript", type=Path, default=None,
                    help="保留但不用于转写的 VTT/DOCX 原文件")
    ap.add_argument("--meeting-dir", type=Path, default=None,
                    help="在已有会议目录中重跑本地 ASR（只供受控包装器调用）")
    ap.add_argument("--reuse-visuals", action="store_true",
                    help="复用已有 slides/page_desc，不重新抽帧和读图")
    ap.add_argument("--reuse-asr", action="store_true",
                    help="故障恢复：复用完整 stamps.json，只重跑说话人及后续阶段")
    ap.add_argument("--media", action="store_true",
                    help="使用媒体总结语义；未指定画面类型时按视频镜头抽取")
    ap.add_argument("--visual-mode", choices=["slides", "media"], default=None,
                    help="画面抽取独立于内容分类：slides=共享屏幕，media=视频镜头")
    args = ap.parse_args()
    if not args.mp4.is_file():
        print("输入文件不存在", file=sys.stderr)
        return 1
    if args.subtitle and (args.ignored_transcript or args.reuse_asr):
        ap.error("--subtitle 不能与 --ignored-transcript 或 --reuse-asr 一起使用")
    if args.subtitle_sha256:
        if not args.subtitle or not re.fullmatch(r"[a-f0-9]{64}", args.subtitle_sha256):
            ap.error("--subtitle-sha256 需要 --subtitle 和有效哈希")
        try:
            with args.subtitle.open("rb") as stream:
                raw = stream.read(MAX_CAPTION_BYTES + 1)
            if len(raw) > MAX_CAPTION_BYTES \
                    or hashlib.sha256(raw).hexdigest() != args.subtitle_sha256:
                raise ValueError("changed_subtitle_checkpoint")
        except (OSError, ValueError):
            print("[error] 原字幕检查点已变化，不能安全恢复", file=sys.stderr)
            return 2

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
        data_root = Path(os.environ.get(
            "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", ROOT))).resolve()
        mdir = for_teams(data_root, args.slug or slugify(args.mp4.stem),
                         date_m.group(1) if date_m else "")
        mdir.mkdir(parents=True, exist_ok=True)
    if args.subtitle and (mdir / "source.vtt").is_file():
        # materialize_source 不覆盖母版；不能因此将保留的旧字节重标成新字幕来源。
        try:
            with args.subtitle.open("rb") as stream:
                incoming = stream.read(MAX_CAPTION_BYTES + 1)
            with (mdir / "source.vtt").open("rb") as stream:
                existing = stream.read(MAX_CAPTION_BYTES + 1)
            if len(incoming) > MAX_CAPTION_BYTES or len(existing) > MAX_CAPTION_BYTES \
                    or incoming != existing:
                raise ValueError("changed_subtitle_source")
        except (OSError, ValueError):
            print("[error] 已保存的原字幕与本次输入不同，不能覆盖已有资料", file=sys.stderr)
            return 2
    visual_mode = configure_extraction(mdir, args.visual_mode, media=args.media)
    original_mp4 = args.mp4.resolve()
    source_mp4 = materialize_source(original_mp4, mdir / f"source_video{args.mp4.suffix.lower()}")
    slug = mdir.name
    t_all = time.time()
    env = dict(os.environ, HF_HUB_OFFLINE="1")

    progress_event("prepare")
    print(f"[1/6] 抽音轨 → {mdir}", flush=True)
    wav = mdir / "audio.wav"
    extract_audio(source_mp4, wav)
    phase_done("prepare")

    source_meta = _read_source(mdir)
    source_meta.setdefault("original_mp4", str(original_mp4))
    source_meta["mp4"] = str(source_mp4)
    if not isinstance(source_meta.get("source_info"), dict):
        source_meta["source_info"] = {}
    source_info = source_meta["source_info"]
    if not isinstance(source_info.get("captions"), dict):
        source_info["captions"] = {}
    provenance = source_info["captions"]
    cues = None
    if args.subtitle:
        language = normalize_language(args.subtitle_language)
        provenance.setdefault("schema", "media-captions/v1")
        provenance.setdefault("selection_policy", "original_human_then_automatic_then_asr")
        provenance.setdefault("imported_at", datetime.now(timezone.utc).isoformat())
        provenance.setdefault("language_evidence", "metadata" if language else "unknown")
        try:
            if not language:
                raise CaptionError("original_language_unknown")
            source_subtitle = materialize_source(args.subtitle, mdir / "source.vtt")
            with source_subtitle.open("rb") as stream:
                raw = stream.read(MAX_CAPTION_BYTES + 1)
            digest = hashlib.sha256(raw).hexdigest()
            if args.subtitle_sha256 and digest != args.subtitle_sha256:
                raise CaptionError("captions_unusable")
            with wave.open(str(wav), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
            cues = parse_caption_bytes(raw, duration=duration)
            provenance.update(
                schema="media-captions/v1", source="native_subtitle",
                kind=args.subtitle_kind, language=language,
                timestamp_source="subtitle_cues", format="vtt", cue_count=len(cues),
                raw_sha256=digest,
                selection_policy="original_human_then_automatic_then_asr",
                selection_reason=f"original_{args.subtitle_kind}")
            provenance.setdefault("language_evidence", "metadata")
            provenance.setdefault("original_language", language)
            provenance.setdefault("imported_at", datetime.now(timezone.utc).isoformat())
            if provenance.get("fallback_reason") != "candidate_limit":
                provenance.pop("fallback_reason", None)
            source_meta.update(transcript_source="native_subtitle",
                               external_transcript_status="used",
                               external_transcript_format="vtt",
                               transcript=str(source_subtitle), vtt=str(source_subtitle))
        except (CaptionError, OSError, ValueError, wave.Error, EOFError) as exc:
            if args.subtitle_sha256:
                print("[error] 原字幕检查点不可用，不能安全恢复", file=sys.stderr)
                return 2
            # 显式失败原因，不打印私有字幕正文、地址或下载器异常。
            reason = exc.reason if isinstance(exc, CaptionError) else "caption_read_failed"
            _caption_fallback(provenance, reason)
            source_meta["external_transcript_status"] = "rejected"
            print("[meta] 原文字幕不可用，回退本地 ASR", flush=True)
    source_meta["transcript_source"] = "native_subtitle" if cues else "local_asr"
    if not args.subtitle and provenance.get("source") == "native_subtitle":
        _caption_fallback(provenance, "user_requested_asr")
    _write_json(mdir / "source.json", source_meta)

    print("[2/6] 原文字幕已验证，跳过 ASR；独立区分发言人 ..." if cues
          else "[2/6] 转写 ∥ 说话人分离 ...", flush=True)
    progress_event("speech_processing")
    prepare_stage("audio", keep=[DEFAULT_DRAFT_MODEL], progress_phase="speech_processing")
    try:
        resolve_pyannote_model(ROOT)
    except ModelNotInstalledError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    tr_cmd = [str(PY), str(BIN / "transcribe.py"), str(wav), "--out", str(mdir),
              "--context-title", args.slug or slug]
    if args.reuse_asr:
        tr_cmd += ["--reuse-stamps"]
    if args.language:
        tr_cmd += ["--language", args.language]
    p_tr = None if cues else subprocess.Popen(tr_cmd, env=env)
    t0 = time.time()
    dia_turns, centroids = diarize(wav, args.num_speakers)
    print(f"[meta] 分离 {time.time()-t0:.1f}s | 声纹聚类 {len(centroids)} 个"
          f" | 原始段数 {len(dia_turns)}", flush=True)
    if p_tr is not None and p_tr.wait():
        print("转写失败", file=sys.stderr)
        return 1

    labels = sorted({l for _, _, l in dia_turns})
    name_of = {l: f"说话人{i+1}" for i, l in enumerate(labels)}   # 与 diarize.py 命名规则一致
    (mdir / "diarization.json").write_text(json.dumps(
        [{"start": round(s, 3), "end": round(e, 3), "speaker": name_of[l]}
         for s, e, l in dia_turns], ensure_ascii=False, indent=1), encoding="utf-8")

    print("[3/6] 合并轮次 + 声纹入库 ...", flush=True)
    ts_path = mdir / "transcript.spk.json"
    if cues:
        turns = subtitle_turns(cues, dia_turns, name_of,
                               language=language, kind=args.subtitle_kind)
        # Cue 时间是字幕来源时间，不伪装成 ASR 的字/词级 stamps.json。
        _write_json(mdir / "subtitle.cues.json", [
            {**signal.to_dict(), "text_review_status": (
                "automatic" if args.subtitle_kind == "automatic" else "platform_provided")}
            for signal in generic_subtitle_signals(cues, language=language, provisional=False)])
        (mdir / "transcript.txt").write_text(
            "\n".join(cue.text for cue in cues) + "\n", encoding="utf-8")
        (mdir / "transcript.ts.md").write_text(
            "\n".join(f"[{mmss(cue.start)}] {cue.text}" for cue in cues) + "\n",
            encoding="utf-8")
    else:
        rc = subprocess.run([str(PY), str(BIN / "diarize.py"), str(wav),
                             "--from-segments", str(mdir / "diarization.json"),
                             "--out", str(mdir)], env=env).returncode
        if rc:
            return 1
        turns = json.loads(ts_path.read_text(encoding="utf-8"))
    used_speakers = {str(t.get("speaker") or "") for t in turns}
    name2vec = {name_of[label]: vector for label, vector in centroids.items()
                if name_of[label] in used_speakers}
    rename, voice_of, linked, new = enroll(name2vec, slug, args.match_threshold)
    for t in turns:
        t["voice"] = voice_of.get(t["speaker"])
        t["speaker"] = rename.get(t["speaker"], t["speaker"])
    _write_json(ts_path, turns)
    md = [f"# {slug} 逐字稿(具名)\n"]
    md += [f"[{mmss(t['start'])}] **{t['speaker']}**: {t['text']}\n" for t in turns]
    (mdir / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")
    if args.ignored_transcript is not None:
        transcript_format = args.ignored_transcript.suffix.lower().lstrip(".")
        source_transcript = materialize_source(
            args.ignored_transcript, mdir / f"source.{transcript_format}")
        source_meta["external_transcript_status"] = "ignored"
        source_meta["external_transcript_format"] = transcript_format
        source_meta.setdefault("original_transcript", str(args.ignored_transcript.resolve()))
        source_meta["transcript"] = str(source_transcript)
        source_meta[transcript_format] = str(source_transcript)
    _write_json(mdir / "source.json", source_meta)
    print(f"[meta] 声纹库: 新入库 {new} | 已有声纹命中 {linked}", flush=True)
    subprocess.run([sys.executable, str(BIN / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)
    review = None if cues else bind_review_to_transcript(mdir)
    if review:
        summary = review.get("summary", {})
        print(f"[meta] 逐字稿音频复核 | 自动修正 {summary.get('auto_corrected', 0)}"
              f" | 待核听 {summary.get('pending', 0)}", flush=True)
    phase_done("speech_processing")
    output_ready("transcript")
    output_ready("speaker_navigation")

    print("[4/6] 先生成语音草稿纪要 ...", flush=True)
    progress_event("voice_draft")
    draft_ready = meeting_generation.generate_voice_draft(mdir, python=sys.executable)
    if draft_ready:
        phase_done("voice_draft")
        output_ready("voice_draft")
    else:
        progress_event("voice_draft", state="degraded")
    if args.no_vl:
        meeting_generation.update(mdir, "voice_only_finalizing", result_mode="voice_only")
    else:
        meeting_generation.begin_visual_enrichment(mdir)

    progress_event("visual_extraction")
    if args.reuse_visuals and (mdir / "slides.json").is_file():
        try:
            pages = json.loads((mdir / "slides.json").read_text(encoding="utf-8"))
        except Exception:
            pages = []
        print(f"[5/6] 复用已有屏幕逻辑页 {len(pages)} 页", flush=True)
    else:
        print("[5/6] 抽媒体镜头页 ..." if visual_mode == "media"
              else "[5/6] 抽屏幕共享逻辑页 ...", flush=True)
        t0 = time.time()
        pages = extract_pages(source_mp4, mdir / "slides", mdir / "slides.json",
                              mode=visual_mode)
        print(f"[meta] 逻辑页 {len(pages)} 页 | 抽页耗时 {time.time()-t0:.1f}s", flush=True)
    phase_done("visual_extraction", done=len(pages), total=len(pages), unit="pages")

    print("[6/6] 生成语音版完整结果 ..." if args.no_vl
          else "[6/6] 用 VL 屏幕资料升级多模态纪要 ...", flush=True)
    if not args.no_vl:
        prepare_stage("visual", keep=[DEFAULT_MINUTES_MODEL],
                      progress_phase="visual_understanding")
    out_path, mstats = generate_minutes(
        mdir, video=source_mp4, vl=not args.no_vl,
        reuse_vl_cache_only=args.reuse_visuals)
    meeting_generation.finalize(
        mdir, pages=mstats["pages"], vl_pages=mstats["vl_pages"],
        visual_mode="skipped_by_user" if args.no_vl else "complete")
    print((f"[meta] 语音版完整结果已发布 | 画面理解已跳过 | "
           f"逻辑页 {mstats['pages']} 页") if args.no_vl else
          f"[meta] 多模态纪要已替换语音草稿 | VL {mstats['vl_pages']}/{mstats['pages']} 页",
          flush=True)
    meeting_topic_map.generate_for_pipeline(mdir)
    terminology = safe_harvest_screen_candidates(
        mdir, args.slug or slug, configured_bank_dir(ROOT))
    print(f"[meta] 术语候选 {terminology['state']} | 新增 {terminology['added']}"
          f" | 更新 {terminology['updated']}", flush=True)
    print(f"[meta] 总耗时 {time.time()-t_all:.1f}s | 纪要 {mstats['chars']} 字"
          f" | 画面 {mstats['pages']} | VL页数 {mstats['vl_pages']}",
          flush=True)
    print(f"[meta] 纪要: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
