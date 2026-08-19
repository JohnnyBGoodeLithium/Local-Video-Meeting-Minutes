"""路由汇总：server.py 创建 app 后按此顺序 include，保持原单文件注册顺序。"""

from routers import (assistant, export, jobs, media, meetings, orgchart, pages,
                     quality, speakers, transcript, translations)  # noqa: F401

all_routers = [
    pages.router,
    meetings.router,
    quality.router,
    translations.router,
    export.router,
    assistant.router,
    media.router,
    transcript.router,
    speakers.router,
    orgchart.router,
    jobs.router,
]
