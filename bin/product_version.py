"""产品发布版本的单一读取边界。

产品 SemVer、前端缓存构建号、Git commit 和各数据 schema 相互独立。发布时只修改
仓库根目录 VERSION；Web、MeetingPack 和 CLI 均从这里读取。
"""
from __future__ import annotations

import re
from pathlib import Path


VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def read_product_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER_RE.fullmatch(version):
        raise RuntimeError(f"VERSION 不是有效 SemVer: {version!r}")
    return version


PRODUCT_VERSION = read_product_version()
PRODUCT_VERSION_LABEL = f"v{PRODUCT_VERSION}"
