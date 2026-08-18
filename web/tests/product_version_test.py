"""产品版本单一真源回归。

不读任何真实会议数据；只验证 VERSION 语义、Web/CLI 导出命名和
MeetingPack 内嵌的生成器版本。
"""
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import product_version  # noqa: E402


version = product_version.PRODUCT_VERSION
assert version == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
assert product_version.PRODUCT_VERSION_LABEL == f"v{version}"

export_source = (ROOT / "bin" / "export_meeting.py").read_text(encoding="utf-8")
web_export_source = (ROOT / "web" / "routers" / "export.py").read_text(encoding="utf-8")
health_source = (ROOT / "web" / "routers" / "pages.py").read_text(encoding="utf-8")
assert '"generator": {"name": "Meeting Minutes", "version": PRODUCT_VERSION}' in export_source
assert "_{PRODUCT_VERSION_LABEL}_{stamp}.meetingpack.zip" in export_source
assert "_{PRODUCT_VERSION_LABEL}_{stamp}.meetingpack.zip" in web_export_source
assert '"product": {"name": "Meeting Minutes", "version": PRODUCT_VERSION}' in health_source

print(f"product version: v{version} single source passed")
