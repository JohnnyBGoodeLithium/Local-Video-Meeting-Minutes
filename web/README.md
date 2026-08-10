# meeting-minutes Web 界面

本机 Web 应用（FastAPI + 原生前端，无构建步骤，不引用任何 CDN）。
**只监听 127.0.0.1:8899，内容不出本机。**

## 启动

```bash
cd ~/meeting-minutes
.venv/bin/python web/server.py
# 浏览器打开 http://127.0.0.1:8899/       会议列表 + 妙计式详情
# 浏览器打开 http://127.0.0.1:8899/admin  声纹库 + org chart 管理
```

## 功能

- 左栏拖入视频（可带同名 .vtt）或音频 → 自动路由：
  视频+vtt → `bin/teams_minutes.py`；裸视频 → `bin/video_minutes.py`；音频 → `bin/run_all.py`。
  上传存 `recordings/inbox/<jobid>/`，作业状态在 `web/jobs/<id>.json`（只存元数据行）。
  **左栏"处理队列"面板实时显示作业状态**（4s 轮询）；排队/运行中的作业有**取消按钮**
  （`POST /api/jobs/{id}/cancel`：排队直接作废；运行中整进程组 SIGTERM，5s 不死再 SIGKILL）。
- 详情页：转写（时间码点击跳转、跟随高亮）、播放器（自绘时间轴：页区间分段/刻度/议题标记/缩略图预览）、
  纪要（服务端渲染 markdown）、"重新生成纪要"按钮（后台跑 `minutes_by_page.py`，分钟级）。
- 说话人 chip → 绑定弹框（可试听该声音片段）→ 一次绑定该声纹在本会议的全部语句
  （同时改写 transcript.spk.json / transcript.spk.md；纪要需手动点"重新生成"）。
  **名字不要求在 org chart/声纹库里**：未命中时返回候选 + `can_create`，前端给"新建「名字」"按钮
  （绑定请求带 `create=true` → 自动新建 person）。
- /admin：声纹库（绑定/别名/合并/解绑，按来源会议过滤）、org chart 树编辑
  （按 leader 字段组装，PUT 整体回写扁平 list）、参考文件上传（PDF 用 pdftoppm 渲成页图）。

## 环境变量（测试用）

- `MEETING_WEB_BANK`：声纹库目录（默认 `speaker_bank/`）。测试时指向临时假库，不碰真实 bank.json。
- `MEETING_MINUTES_ROOT`：项目根（默认 `web/` 的上一级）。
- `MEETING_WEB_PORT`：端口（默认 8899；与其他实例冲突时可改，如测试用 8898）。
- `MEETING_WEB_DRYRUN=1`：作业干跑——管线只执行 `<脚本> --help` 校验调用链，regen 直接标记完成。

## 冒烟测试

```bash
.venv/bin/python web/tests/make_fake_bank.py   # 重置假声纹库 /tmp/mm_fake_bank
.venv/bin/python web/tests/make_smoke.py       # 重建合成夹具 meetings/_smoke(整目录重建)
MEETING_WEB_BANK=/tmp/mm_fake_bank MEETING_WEB_DRYRUN=1 MEETING_WEB_PORT=8898 \
    .venv/bin/python web/server.py &           # 测试实例(假库+干跑+独立端口)
MM_TEST_BASE=http://127.0.0.1:8898 .venv/bin/python web/tests/smoke_test.py
# 39 项断言全过即通过; 全程只碰合成数据
```

## 测试夹具

`meetings/_smoke/` 是**合成测试会议**（10s 静音 wav + 虚构的 Alice/Bob 两轮对话 +
2 页假 slides + 假 minutes.md），仅用于接口冒烟测试，不含任何真实数据。
重建：` .venv/bin/python web/tests/make_smoke.py `（幂等，会先清空再生成）。
声纹相关接口的回归验证需配合临时假声纹库（`MEETING_WEB_BANK` 指向临时目录），
不要对真实 `speaker_bank/bank.json` 跑绑定类测试。
