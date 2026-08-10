#!/usr/bin/env python3
"""造临时假声纹库（全虚构，不碰真实 speaker_bank/）。

配合 web/tests/smoke_test.py 的断言：
- persons 只有 Alice Example（aliases 必须为空，否则 "Alicia" 会被模糊命中而非 409）
- voices v_9001/v_9002 均未绑定
- orgchart 两条（Alice Example / Dave Example，aliases 空）

设置 MM_TEST_ORG_SIZE=124 可生成完全虚构的大型层级树，用于前端布局/性能验收。
"""
import json
import os
import shutil
from pathlib import Path

import numpy as np

BANK = Path(os.environ.get("MM_TEST_BANK", "/tmp/mm_fake_bank")).resolve()
if BANK.exists():
    shutil.rmtree(BANK)
(BANK / "emb").mkdir(parents=True)

rng = np.random.default_rng(0)
for vid in ("v_9001", "v_9002"):
    v = rng.random(256, dtype=np.float32)
    np.save(BANK / "emb" / f"{vid}.npy", v / (np.linalg.norm(v) + 1e-9))

bank = {
    "schema": 2,
    "persons": [{"id": "p_0001", "name": "Alice Example", "aliases": [],
                 "created": "2026-01-01"}],
    "voices": [
        {"id": "v_9001", "person_id": None, "label_hint": "Alice",
         "emb": "emb/v_9001.npy", "sources": ["_smoke"], "created": "2026-01-01"},
        {"id": "v_9002", "person_id": None, "label_hint": "Bob",
         "emb": "emb/v_9002.npy", "sources": ["_smoke"], "created": "2026-01-01"},
    ],
}
(BANK / "bank.json").write_text(json.dumps(bank, ensure_ascii=False, indent=1), encoding="utf-8")

org_size = max(2, int(os.environ.get("MM_TEST_ORG_SIZE", "2")))
if org_size == 2:
    org = [
        {"name": "Alice Example", "aliases": [], "title": "Mgr", "team": "BU1", "leader": "", "note": ""},
        {"name": "Dave Example", "aliases": [], "title": "Dir", "team": "BU1", "leader": "", "note": ""},
    ]
else:
    # 大型视觉夹具：3 个根、每名经理最多 4 个直属下属，全是虚构名称。
    names = [f"Synthetic Person {i + 1:03d}" for i in range(org_size)]
    org = []
    for i, name in enumerate(names):
        parent = "" if i < 3 else names[(i - 3) // 4]
        org.append({"name": name, "aliases": [],
                    "title": "Director" if i < 3 else ("Manager" if i < 15 else "Engineer"),
                    "team": f"Synthetic BU {i % 3 + 1}", "leader": parent, "note": ""})
(BANK / "orgchart.json").write_text(json.dumps(org, ensure_ascii=False, indent=1), encoding="utf-8")
print("fake bank ok:", BANK)
