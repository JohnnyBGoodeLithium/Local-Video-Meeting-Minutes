#!/usr/bin/env python3
"""造临时假声纹库（全虚构，不碰真实 speaker_bank/）。

配合 web/tests/smoke_test.py 的断言：
- persons 只有 Alice Example（aliases 必须为空，否则 "Alicia" 会被模糊命中而非 409）
- voices v_9001/v_9002 均未绑定
- orgchart 两条（Alice Example / Dave Example，aliases 空）
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

org = [
    {"name": "Alice Example", "aliases": [], "title": "Mgr", "team": "BU1", "leader": "", "note": ""},
    {"name": "Dave Example", "aliases": [], "title": "Dir", "team": "BU1", "leader": "", "note": ""},
]
(BANK / "orgchart.json").write_text(json.dumps(org, ensure_ascii=False, indent=1), encoding="utf-8")
print("fake bank ok:", BANK)
