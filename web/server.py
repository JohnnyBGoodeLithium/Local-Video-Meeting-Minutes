#!/usr/bin/env python3
"""会议纪要本机 Web 服务（FastAPI，只 bind 127.0.0.1:8899，内容不出机器）。

启动（在 meeting-minutes/ 下）：
    .venv/bin/python web/server.py

本文件只是装配入口：路径/锁/共享助手在 deps.py，作业状态与管线 runner 在
job_store.py，全部 HTTP 路由在 routers/（注册顺序见 routers/__init__.py）。

环境变量（一般不用动）：
    MEETING_DATA_ROOT      私有数据根（默认项目根；测试可指向一次性目录）
    MEETING_WEB_BANK       声纹库目录（默认 DATA_ROOT/speaker_bank）
    MEETING_WEB_JOBS       作业 JSON 目录（默认 web/jobs）
    MEETING_WEB_DRYRUN=1   作业干跑模式：管线只执行 `<脚本> --help` 校验调用链，
                           regen 直接标记完成（供冒烟测试，不碰 GPU 模型）

隐私约定：stdout/作业日志只保留管线脚本的元数据行（以 "[" 开头的进度行），
不写任何转写/纪要正文。作业 json 只存元数据。
"""

import os
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent.resolve()
# 保证 `from deps import ...` / `from routers import ...` 与 bin/ 下 service 模块
# 在任何启动方式（脚本、uvicorn、测试）下都可导入。
for _p in (str(WEB_DIR), str(ROOT / "bin")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from deps import STATIC  # noqa: E402
from job_store import load_jobs  # noqa: E402
from routers import all_routers  # noqa: E402

app = FastAPI(title="meeting-minutes web", docs_url=None, redoc_url=None)

for _router in all_routers:
    app.include_router(_router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")

load_jobs()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MEETING_WEB_PORT", 8899)),
                log_level="info")
