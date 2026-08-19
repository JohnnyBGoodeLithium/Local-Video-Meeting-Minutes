"""声纹按轮拆分的嵌入聚类单元测试（合成向量，不加载 pyannote 模型）。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))

from voice_enroll import (cluster_embeddings, reassign_by_centroids,
                          suggest_reassignments)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routers.speakers import _resolve_current_split_voice  # noqa: E402

DIM = 192


def cluster_vec(hot: int, seed: int, noise: float = 0.02) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(0, noise, DIM).astype(np.float32)
    v[hot] += 1.0
    return v


def partition(assign: list) -> list:
    groups = {}
    for i, c in enumerate(assign):
        groups.setdefault(c, set()).add(i)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


# 1. 交错序列中的两个清晰簇 → 恢复为两组
vecs = []
expect = []
for n in range(6):
    hot = n % 2  # 0,1,0,1,...
    vecs.append(cluster_vec(hot, seed=n))
    expect.append(hot)
assign = cluster_embeddings(np.vstack(vecs))
assert len(assign) == 6 and max(assign) == 1, assign
assert partition(assign) == [[0, 2, 4], [1, 3, 5]], assign

# 2. 全部相似 → 单簇
same = np.vstack([cluster_vec(3, seed=n) for n in range(5)])
assign = cluster_embeddings(same)
assert max(assign) == 0, assign

# 3. 两两正交且噪声极小 → 各自成簇
rng = np.random.default_rng(7)
ortho = np.eye(4, DIM, dtype=np.float32) + rng.normal(0, 1e-4, (4, DIM)).astype(np.float32)
assign = cluster_embeddings(np.vstack(ortho), threshold=0.5)
assert max(assign) == 3, assign

# 4. 空输入
assert cluster_embeddings(np.zeros((0, DIM), dtype=np.float32)) == []

# 5. 单条 → 单簇
assert cluster_embeddings(cluster_vec(9, seed=1).reshape(1, -1)) == [0]

# 6. 半监督重排：一条 B 样例建立新质心后，rest 中混入的 B 组全部移出、A 组留守
base = cluster_vec(0, seed=100)        # 原声纹校正质心（A）
example = cluster_vec(1, seed=101)     # 用户标记的一条“不是 TA”样例（B）
rest = np.vstack([cluster_vec(i % 2, seed=200 + i) for i in range(8)])  # ABAB…
moves = reassign_by_centroids(rest, base, [example])
assert moves == [None, 0, None, 0, None, 0, None, 0], moves

# 7. rest 全部更像基准 → 无移动
rest_same = np.vstack([cluster_vec(0, seed=300 + i) for i in range(5)])
assert all(m is None for m in reassign_by_centroids(rest_same, base, [example]))

# 8. 多新簇：两条样例各带一组
ex2 = cluster_vec(2, seed=102)
rest3 = np.vstack([cluster_vec(i % 3, seed=400 + i) for i in range(9)])  # ABCABC…
moves3 = reassign_by_centroids(rest3, cluster_vec(0, seed=103), [example, ex2])
assert moves3 == [None, 0, 1, None, 0, 1, None, 0, 1], moves3

# 9. 空输入 / 无新簇
assert reassign_by_centroids(np.zeros((0, DIM), dtype=np.float32), base, [example]) == []
assert reassign_by_centroids(rest_same, base, []) == [None] * 5

# 10. 建议扩散必须同时满足绝对相似度和相对差值；略胜旧簇只能进入存疑区。
strong = np.vstack([cluster_vec(1, seed=500 + i, noise=0.01) for i in range(3)])
safe_moves, safe_ambiguous = suggest_reassignments(strong, base, [example])
assert safe_moves == [0, 0, 0] and safe_ambiguous == [False, False, False]
borderline = np.vstack([(base + example) / 2])
border_moves, border_ambiguous = suggest_reassignments(
    borderline, base, [example], threshold=0.6, margin=0.2)
assert border_moves == [None] and border_ambiguous == [True]

# 11. 页面持有旧 voice 时，只要所选轮次在磁盘上仍同属一条当前声纹，就安全纠正。
turns = [{"voice": "v_new"}, {"voice": "v_new"}, {"voice": "v_other"}]
assert _resolve_current_split_voice(turns, [0, 1], "v_old") == ("v_new", True)
assert _resolve_current_split_voice(turns, [0, 1], "v_new") == ("v_new", False)

# 12. 当前所选轮次确实跨声纹时仍必须拒绝，不能为了通过操作而重新混绑。
try:
    _resolve_current_split_voice(turns, [0, 2], "v_old")
except Exception as exc:
    assert getattr(exc, "status_code", None) == 400
    assert "多条声纹" in str(getattr(exc, "detail", ""))
else:
    raise AssertionError("mixed current voices must be rejected")

print("voice split clustering: synthetic partitions passed")
