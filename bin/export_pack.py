#!/usr/bin/env python3
"""把多场会议导出为一个 .contentpack.zip 多内容包。

每个内容在 pack 暂存区先由 export_meeting 产出单会议 MeetingPack，再解压为
meetings/<slug>/ 完整文件树；pack 顶层叠加 README/AGENTS/manifest/index，
其中 index.json 是跨内容关键字贯穿线索（在 ≥2 个内容中出现的关键字）。
导出全程只读会议目录，不调用模型、不写回 canonical sidecar。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from export_meeting import _identity, _read_json, export_meeting
from product_version import PRODUCT_VERSION, PRODUCT_VERSION_LABEL

PACK_SCHEMA = "content-pack/v1"
INDEX_SCHEMA = "content-pack-index/v1"
MIN_MEETINGS, MAX_MEETINGS = 2, 12
KIND_LABELS = {"product": "产品", "project": "项目", "topic": "议题",
               "organization": "组织", "other": "其他"}


def _normalize_keyword(text: str) -> str:
    """与 web/keyword_service.normalize_keyword 同一规则：NFKC + casefold + 去空白。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def _safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_()（）" else "_" for c in text).strip("_")


def pack_filename(name: str, first_date: str = "", now: datetime | None = None) -> str:
    """pack 命名与单会议导出同约定：名称 + 首个会议日期 + 产品版本 + 导出时间。"""
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    base = _safe_name(name) or "内容包"
    date_part = f"_{first_date}" if first_date else ""
    return f"{base}{date_part}_{PRODUCT_VERSION_LABEL}_{stamp}.contentpack.zip"


def _meeting_keywords(pack_dir: Path, slug: str) -> list[dict]:
    """读暂存子包里的 keywords.json——索引只描述实际打进包的内容。"""
    data = _read_json(pack_dir / "meetings" / slug / "assets" / "keywords.json", {})
    if data.get("schema") != "meeting-keywords/v1":
        return []
    return [item for item in data.get("keywords", [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()]


def _shared_keyword_index(pack_dir: Path, slugs: list[str]) -> list[dict]:
    """在 ≥2 个内容中出现的关键字 → 涉及内容 slug 列表（贯穿线索）。"""
    merged: dict[str, dict] = {}
    for slug in slugs:
        for item in _meeting_keywords(pack_dir, slug):
            text = str(item["text"]).strip()
            normalized = _normalize_keyword(text)
            if not normalized:
                continue
            entry = merged.setdefault(normalized, {"text_counts": {}, "kinds": [], "meetings": []})
            texts = entry["text_counts"]
            texts[text] = texts.get(text, 0) + 1
            kind = str(item.get("kind") or "other")
            if kind not in KIND_LABELS:
                kind = "other"
            if kind not in entry["kinds"]:
                entry["kinds"].append(kind)
            if slug not in entry["meetings"]:
                entry["meetings"].append(slug)
    entries = []
    for normalized, entry in merged.items():
        if len(entry["meetings"]) < 2:
            continue
        text = max(entry["text_counts"].items(), key=lambda kv: kv[1])[0]
        entries.append({"text": text, "normalized": normalized,
                        "kinds": entry["kinds"], "meetings": sorted(entry["meetings"])})
    entries.sort(key=lambda e: (-len(e["meetings"]), e["normalized"]))
    return entries


def _meeting_summary(pack_dir: Path, slug: str) -> dict:
    manifest = _read_json(pack_dir / "meetings" / slug / "assets" / "manifest.json", {})
    turns = _read_json(pack_dir / "meetings" / slug / "assets" / "transcript.json", [])
    duration = max((float(t.get("end", 0)) for t in turns), default=0.0)
    counts = manifest.get("counts", {})
    return {"slug": slug,
            "title": str(manifest.get("title") or slug),
            "date": str(manifest.get("date") or ""),
            "duration": round(duration, 1),
            "counts": {"turns": counts.get("turns", 0), "pages": counts.get("pages", 0),
                       "claims": counts.get("claims", 0),
                       "keywords": counts.get("keywords", 0)}}


def _duration_text(seconds: float) -> str:
    total = max(0, int(seconds))
    if total >= 3600:
        return f"{total // 3600} 小时 {total % 3600 // 60} 分"
    return f"{total // 60} 分 {total % 60} 秒" if total else "时长未知"


def _readme(name: str, summaries: list[dict], index_entries: list[dict],
            media_mode: str) -> str:
    lines = [f"内容包：{name}", f"由 Meeting Minutes {PRODUCT_VERSION_LABEL} 生成", "",
             f"本包包含 {len(summaries)} 个会议内容，每个内容都是完整的离线 MeetingPack：",
             "进入 meetings/<目录名>/ 后双击 viewer.html 即可离线阅读，无需安装服务。", "",
             "内容清单"]
    for i, item in enumerate(summaries, 1):
        lines.append(f"{i}. {item['title']}"
                     f"{('（' + item['date'] + '）') if item['date'] else ''}"
                     f" · {_duration_text(item['duration'])} — meetings/{item['slug']}/")
    lines.append("")
    if index_entries:
        lines.append("贯穿线索（在至少两个内容中出现的关键字）")
        for entry in index_entries:
            kinds = "、".join(KIND_LABELS.get(k, k) for k in entry["kinds"])
            lines.append(f"- {entry['text']}（{kinds}）→ "
                         + "、".join(entry["meetings"]))
        lines.append("")
    lines += [
        "使用建议",
        "- 先看上面的贯穿线索确定感兴趣的主线，再进入对应内容目录逐个深读。",
        "- index.json 是同一贯穿线索的机器可读版；manifest.json 记录格式版本与各内容摘要。",
        "- 每个内容目录内还有自己的 README.txt 与 AGENTS.md，说明其内部结构与证据边界。",
        "- 音视频（如果选择携带）是分享压缩版；本项目中的原始母版不会被修改。",
        "",
        f"媒体策略：本次导出 media={media_mode}。",
    ]
    return "\n".join(lines) + "\n"


_AGENTS_MD = """# ContentPack — Agent 使用指引

这是多内容会议数据包（content-pack/v1）。顶层是导读与跨内容索引，正文在
`meetings/<slug>/` 下：每个 slug 目录都是一份完整的 MeetingPack v5。
**单内容内部的事实核验、引用与措辞规则，一律以该目录下的 AGENTS.md 为准**；本层不做事实裁决。

## 文件地图
- `README.md` — 人类导读：内容清单（标题/日期/时长）、贯穿线索、使用建议。
- `manifest.json` — content-pack/v1：生成器版本、导出时间、各内容摘要与汇总 counts。
- `index.json` — content-pack-index/v1：在 ≥2 个内容中出现的关键字 → 涉及内容 slug 列表，即贯穿线索。
- `meetings/<slug>/assets/rag/records.jsonl` — 每个内容的检索记录；跨内容建索引时逐文件读取，
  用 `meetings/<slug>` 作为内容来源字段。

## 常见任务
1. 跨内容主题/产品追踪：先读 `index.json`，按关键字拿到涉及 slug 列表，再逐个进入
   `meetings/<slug>/` 按其 AGENTS.md 的规则深读（evidence.json → transcript.json 逐级回溯）。
2. 对比与汇总：每条结论标注来源 slug + 会议日期 + C/T/P 编号；两场决定冲突时引用各自依据，
   不得合并成一个无出处的"结论"。
3. 关键字只表示名词共现，不等于因果关系或时间先后；时间线以各内容 manifest.json 的 date 为准。

## 边界
包内不含声纹向量、组织架构和原始媒体母版；无法回答语气核验、身份鉴定类问题。
"""


def export_pack(meetings: list[tuple[str, Path, str, str]], out: Path, *,
                bank_dir: Path | None = None, media_mode: str = "none",
                name: str | None = None, profile: str = "full",
                base_url: str | None = None) -> dict:
    """meetings 为 (slug, 会议目录, 标题, 日期) 列表；产物打成 .contentpack.zip。

    profile="kb" 时每场一份轻量 Markdown；profile="kb-html" 时每场一份
    内嵌关键画面的 HTML。两者都不含 MeetingPack 文件树。"""
    out = Path(out).resolve()
    if media_mode not in {"none", "audio", "video"}:
        raise ValueError("media_mode 必须是 none/audio/video")
    if profile not in {"full", "kb", "kb-html"}:
        raise ValueError("profile 必须是 full/kb/kb-html")
    if not MIN_MEETINGS <= len(meetings) <= MAX_MEETINGS:
        raise ValueError(f"内容包需要 {MIN_MEETINGS}–{MAX_MEETINGS} 场会议")
    slugs = [slug for slug, _mdir, _t, _d in meetings]
    if len(set(slugs)) != len(slugs):
        raise ValueError("内容包中会议重复")
    if profile in {"kb", "kb-html"}:
        import kb_document
        return kb_document.build_kb_pack(meetings, out, base_url=base_url,
                                         bank_dir=bank_dir,
                                         document_format=("html" if profile == "kb-html"
                                                          else "markdown"))

    with tempfile.TemporaryDirectory(prefix="contentpack-export-") as temp_name:
        temp_dir = Path(temp_name)
        pack_dir = temp_dir / "pack"
        meetings_root = pack_dir / "meetings"
        for slug, mdir, title, date in meetings:
            sub_zip = temp_dir / f"sub-{slug}.zip"
            export_meeting(Path(mdir), sub_zip, bank_dir=bank_dir,
                           media_mode=media_mode, title=title, date=date)
            target = meetings_root / slug
            target.mkdir(parents=True)
            with zipfile.ZipFile(sub_zip) as archive:
                archive.extractall(target)
            sub_zip.unlink()

        index_entries = _shared_keyword_index(pack_dir, slugs)
        if not name:
            name = index_entries[0]["text"] if index_entries else "内容包"
        summaries = [_meeting_summary(pack_dir, slug) for slug in slugs]
        first_date = next((item["date"] for item in summaries if item["date"]), "")

        index_doc = {"schema": INDEX_SCHEMA,
                     "built_at": datetime.now(timezone.utc).isoformat(),
                     "entries": index_entries}
        manifest = {
            "schema": PACK_SCHEMA,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generator": {"name": "Meeting Minutes", "version": PRODUCT_VERSION},
            "name": name,
            "media": {"mode": media_mode},
            "meetings": summaries,
            "counts": {
                "meetings": len(summaries),
                "turns": sum(item["counts"]["turns"] for item in summaries),
                "pages": sum(item["counts"]["pages"] for item in summaries),
                "claims": sum(item["counts"]["claims"] for item in summaries),
                "keywords": sum(item["counts"]["keywords"] for item in summaries),
                "shared_keywords": len(index_entries),
            },
        }
        top_files = {
            "README.md": _readme(name, summaries, index_entries, media_mode),
            "AGENTS.md": _AGENTS_MD,
            "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
            "index.json": json.dumps(index_doc, ensure_ascii=False, indent=2),
        }
        for arcname, text in top_files.items():
            (pack_dir / arcname).write_text(text, encoding="utf-8")

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w") as archive:
            for path in sorted(p for p in pack_dir.rglob("*") if p.is_file()):
                arcname = path.relative_to(pack_dir).as_posix()
                mime = mimetypes.guess_type(arcname)[0] or ""
                compressed = mime.startswith(("image/", "audio/", "video/"))
                archive.write(path, arcname,
                              compress_type=zipfile.ZIP_STORED if compressed
                              else zipfile.ZIP_DEFLATED)
    return {"path": str(out), "bytes": out.stat().st_size,
            "filename": pack_filename(name, first_date),
            "name": name, "product_version": PRODUCT_VERSION,
            "media": {"mode": media_mode}, **manifest["counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="导出多内容 .contentpack.zip")
    parser.add_argument("meeting_dirs", type=Path, nargs="+",
                        help=f"{MIN_MEETINGS}–{MAX_MEETINGS} 个会议目录")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--name", default=None,
                        help="包名；默认用最高频共享关键字，没有共享关键字时用“内容包”")
    parser.add_argument("--bank-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "speaker_bank")
    parser.add_argument("--media", choices=("none", "audio", "video"), default="none")
    parser.add_argument("--profile", choices=("full", "kb", "kb-html"), default="full",
                        help="kb：轻量 Markdown；kb-html：图文 HTML 知识库包")
    parser.add_argument("--base-url", default=None,
                        help="仅 kb profile：深链/外链 base；默认取 env MEETING_WEB_PUBLIC_BASE")
    args = parser.parse_args()
    meetings = []
    for mdir in args.meeting_dirs:
        mdir = mdir.resolve()
        title, date = _identity(mdir.name)
        meetings.append((mdir.name, mdir, title, date))
    probe = Path.cwd() / f".contentpack-export-{os.getpid()}.zip"
    try:
        # --out 缺省时先导出到同目录临时文件，再用返回的规范文件名原子落位。
        stats = export_pack(meetings, args.out or probe,
                            bank_dir=args.bank_dir, media_mode=args.media,
                            name=args.name, profile=args.profile,
                            base_url=args.base_url)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        probe.unlink(missing_ok=True)
        print(f"导出失败: {exc}", file=sys.stderr)
        return 1
    final = Path(stats["path"])
    if args.out is None:
        target = Path.cwd() / stats["filename"]
        final.replace(target)
        final = target
    if args.profile in {"kb", "kb-html"}:
        print(f"[meta] KB Pack: {final} | {stats['bytes']} bytes | "
              f"documents={stats['documents']} shared={stats['shared_keywords']} "
              f"base={stats['base_url']}")
    else:
        print(f"[meta] ContentPack: {final} | {stats['bytes']} bytes | "
              f"meetings={stats['meetings']} shared={stats['shared_keywords']} media={args.media}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
