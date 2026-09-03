"""路由汇总：server.py 创建 app 后按此顺序 include，保持原单文件注册顺序。"""

from routers import (assistant, companion, export, jobs, keywords, knowledge, live, media, meetings, orgchart,
                     pages, photos, quality, speakers, transcript, translations)  # noqa: F401

all_routers = [
    pages.router,
    companion.router,
    meetings.router,
    quality.router,
    translations.router,
    keywords.router,
    export.router,
    knowledge.router,
    assistant.router,
    media.router,
    photos.router,
    transcript.router,
    speakers.router,
    orgchart.router,
    live.router,
    jobs.router,
]
