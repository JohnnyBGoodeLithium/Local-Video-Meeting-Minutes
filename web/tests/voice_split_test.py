"""声纹按轮拆分的嵌入聚类单元测试（合成向量，不加载 pyannote 模型）。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))

from voice_enroll import cluster_embeddings  # noqa: E402

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

print("voice split clustering: synthetic partitions passed")
