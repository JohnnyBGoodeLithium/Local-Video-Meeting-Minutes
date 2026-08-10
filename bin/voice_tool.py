#!/usr/bin/env python3
"""声纹绑定/管理工具（全本地，云端 agent 不读取库内容）。

用法（在 ~/meeting-minutes 下）：
    .venv/bin/python bin/voice_tool.py list                       # 看库里有哪些人和声纹
    .venv/bin/python bin/voice_tool.py sample meetings/2026-08-06_FY28-...   # 切试听片段
    .venv/bin/python bin/voice_tool.py bind v_0003 "Peter Yuan"   # 绑定（唯一精确已确认名称）
    .venv/bin/python bin/voice_tool.py alias "Peter Yuan" 彼得 Peter
    .venv/bin/python bin/voice_tool.py merge v_0003 v_0007        # v_0007 并入 v_0003 对应的人
    .venv/bin/python bin/voice_tool.py unbind v_0003

唯一精确匹配可以绑定；包含和 difflib 近似只列候选，绝不自动绑定。
org chart 放在 speaker_bank/orgchart.json(格式见 orgchart.template.json)，只被本工具本地读取。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "speaker_bank"
sys.path.insert(0, str(ROOT / "bin"))

import voice_bank as vb  # noqa: E402


def cmd_list(args):
    bank = vb.load_bank(BANK)
    print(f"人: {len(bank['persons'])} | 声纹: {len(bank['voices'])}")
    for p in bank["persons"]:
        n_v = sum(1 for v in bank["voices"] if v.get("person_id") == p["id"])
        names = ", ".join(f"{n['type']}:{n['value']}" for n in p.get("names", []))
        print(f"  {p['id']}  {p.get('display_name') or p['name']}"
              f"  [声纹 {n_v} 条]  名称={names}")
    for v in bank["voices"]:
        nm = vb.person_name(bank, v.get("person_id"))
        print(f"  {v['id']}  -> {nm or '(未绑定)'}  hint={v.get('label_hint','')}  来源 {len(v.get('sources',[]))} 场")
    return 0


def cmd_sample(args):
    """每个说话人切最长若干轮、拼成 ≤max-sec 的试听片段。"""
    import numpy as np
    import soundfile as sf

    mdir = Path(args.meeting_dir)
    turns_path = mdir / "transcript.spk.json"
    audio_path = mdir / "audio.wav"
    if not turns_path.is_file() or not audio_path.is_file():
        print("需要会议目录里的 transcript.spk.json 和 audio.wav", file=sys.stderr)
        return 1
    turns = json.loads(turns_path.read_text(encoding="utf-8"))
    data, sr = sf.read(str(audio_path), dtype="float32")
    out_dir = mdir / "samples"
    out_dir.mkdir(exist_ok=True)

    by_spk = {}
    for t in turns:
        by_spk.setdefault(t["speaker"], []).append(t)
    n = 0
    for spk, ts in by_spk.items():
        ts = sorted(ts, key=lambda t: -(t["end"] - t["start"]))[: args.top]
        ts.sort(key=lambda t: t["start"])
        clips, total = [], 0.0
        for t in ts:
            seg = data[int(t["start"] * sr):int(t["end"] * sr)]
            if len(seg) == 0:
                continue
            remain = int((args.max_sec - total) * sr)
            if remain <= 0:
                break
            clips.append(seg[:remain])
            total += min(len(seg), remain) / sr
        if not clips:
            continue
        safe = "".join(c if c.isalnum() or c in "-_()（）" else "_" for c in spk)
        sf.write(str(out_dir / f"{safe}.wav"), np.concatenate(clips), sr)
        n += 1
    print(f"[meta] 写出 {n} 个试听片段到 {out_dir}")
    return 0


def cmd_bind(args):
    bank = vb.load_bank(BANK)
    voice = next((v for v in bank["voices"] if v["id"] == args.voice_id), None)
    if not voice:
        print(f"没有这条声纹: {args.voice_id}", file=sys.stderr)
        return 1
    org = vb.load_orgchart(BANK)
    person, how = vb.resolve_person(bank, args.name, orgchart=org)
    if person is None:
        if how:  # 有候选但不确信 → 让用户定夺
            print("没精确命中，候选如下(用更准的名字重试或先加别名):")
            for p in how:
                print(f"  {p.get('id', '(org)')}  {p.get('display_name') or p['name']}"
                      f" 名称={[n.get('value') for n in p.get('names', [])]}")
            return 2
        person = vb.add_person(bank, args.name)
        how = "新建"
    voice["person_id"] = person["id"]
    vb.save_bank(BANK, bank)
    print(f"已绑定 {args.voice_id} -> {person.get('display_name') or person['name']} ({how})")
    return 0


def cmd_alias(args):
    bank = vb.load_bank(BANK)
    person, how = vb.resolve_person(bank, args.person)
    if person is None:
        print(f"没找到人: {args.person}", file=sys.stderr)
        return 1
    for a in args.aliases:
        if a not in person["aliases"]:
            person["aliases"].append(a)
    vb.normalize_person(person)
    vb.save_bank(BANK, bank)
    print(f"{person.get('display_name') or person['name']} 别名现为: {person['aliases']}")
    return 0


def cmd_merge(args):
    bank = vb.load_bank(BANK)
    keep = next((v for v in bank["voices"] if v["id"] == args.keep), None)
    if not keep:
        print(f"没有这条声纹: {args.keep}", file=sys.stderr)
        return 1
    if not keep.get("person_id"):
        hint = keep.get("label_hint") or keep["id"]
        p = vb.add_person(bank, hint)
        keep["person_id"] = p["id"]
    merged = 0
    for did in args.drop:
        drop = next((v for v in bank["voices"] if v["id"] == did), None)
        if not drop or did == args.keep:
            print(f"跳过 {did}", file=sys.stderr)
            continue
        drop["person_id"] = keep["person_id"]
        for s in drop.get("sources", []):
            if s not in keep["sources"]:
                keep["sources"].append(s)
        merged += 1
    vb.save_bank(BANK, bank)
    print(f"并入 {merged} 条声纹到 {vb.person_name(bank, keep['person_id'])}")
    return 0


def cmd_unbind(args):
    bank = vb.load_bank(BANK)
    voice = next((v for v in bank["voices"] if v["id"] == args.voice_id), None)
    if not voice:
        print(f"没有这条声纹: {args.voice_id}", file=sys.stderr)
        return 1
    voice["person_id"] = None
    vb.save_bank(BANK, bank)
    print(f"已解绑 {args.voice_id}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="声纹绑定/管理(本地)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sp = sub.add_parser("sample", help="切试听片段")
    sp.add_argument("meeting_dir")
    sp.add_argument("--top", type=int, default=3, help="每人取最长几轮")
    sp.add_argument("--max-sec", type=float, default=20.0, help="每人片段最长秒数")
    sb = sub.add_parser("bind", help="声纹绑人")
    sb.add_argument("voice_id")
    sb.add_argument("name")
    sa = sub.add_parser("alias", help="给人加别名")
    sa.add_argument("person")
    sa.add_argument("aliases", nargs="+")
    sm = sub.add_parser("merge", help="多条声纹并给同一人")
    sm.add_argument("keep")
    sm.add_argument("drop", nargs="+")
    su = sub.add_parser("unbind")
    su.add_argument("voice_id")
    args = ap.parse_args()
    return {"list": cmd_list, "sample": cmd_sample, "bind": cmd_bind,
            "alias": cmd_alias, "merge": cmd_merge, "unbind": cmd_unbind}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
