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

product_html = (ROOT / "web" / "static" / "product.html").read_text(encoding="utf-8")
major, minor, _ = version.split(".")
expected_content_version = f"{major}.{minor}"
assert f'data-product-content-version="{expected_content_version}"' in product_html
assert f'<meta name="product-content-version" content="{expected_content_version}">' in product_html

status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
build_match = re.search(r"Web 构建号：([0-9]{8}p[0-9]+)", status)
assert build_match, "STATUS 缺少 Web asset build number"
asset_builds = set(re.findall(
    r'/static/(?:fluent-foundation|product)\.css\?v=([0-9]{8}p[0-9]+)|'
    r'/static/product\.js\?v=([0-9]{8}p[0-9]+)', product_html,
))
flattened_builds = {value for pair in asset_builds for value in pair if value}
assert flattened_builds == {build_match.group(1)}, (
    f"产品页 asset build 与 STATUS 不一致：{flattened_builds}"
)

print(f"product version: v{version} single source passed")
