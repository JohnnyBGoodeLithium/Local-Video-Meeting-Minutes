# meeting-minutes Web 界面

本机 Web 应用（FastAPI + 原生前端，无构建步骤，不引用任何 CDN）。
**只监听 127.0.0.1:8899，内容不出本机。**

## 启动

```bash
cd ~/meeting-minutes
.venv/bin/python web/server.py
# 浏览器打开 http://127.0.0.1:8899/       会议回顾工作台
# 浏览器打开 http://127.0.0.1:8899/admin  人员身份 + 声纹试听/确认 + 图形化 org chart
```

## 功能

- 左栏“导入会议”可选择或拖入视频（可带同名 .vtt）或音频 → 自动路由：
  视频+vtt → `bin/teams_minutes.py`；裸视频 → `bin/video_minutes.py`；音频 → `bin/run_all.py`。
  上传存 `recordings/inbox/<jobid>/`，作业状态在 `web/jobs/<id>.json`（只存元数据行）。
  有活动作业时，左栏自动出现“正在处理”面板（4s 轮询）；排队/运行中的作业有**取消按钮**
  （`POST /api/jobs/{id}/cancel`：排队直接作废；运行中整进程组 SIGTERM，5s 不死再 SIGKILL）。
- 详情页：左侧常驻播放器、时间轴和逐字稿证据栏，右侧阅读纪要；时间轴支持页区间、议题标记和缩略图预览。
  重新生成、全文优化与高级配置收在“更多”中。
- 底部会议助手：直接输入问题或修改指令，也可逐轮点击或跨轮选择文字作为引用；本地 Qwen3.6 问答带时间来源。
  修改纪要先显示目标、说明和修改后预览；保存后在 `.history/minutes/` 留档，并可在没有后续改动时立即撤销。
- 说话人 chip → 绑定弹框（可试听该声音片段）→ 一次绑定该声纹在本会议的全部语句
  （同时改写 transcript.spk.json / transcript.spk.md；纪要需手动点"重新生成"）。
  **名字不要求预先存在**：唯一精确已确认名称可直接绑定；相似名称只返回候选，不写库；用户也可显式“新建人员”。
- `/admin` 人员身份：同一稳定人员 ID 可保存 Org Chart 原名、中文名、全拼、英文名加姓氏等类型化名称，并独立设置首选显示名。
- `/admin` 声音确认：列表内试听、确认弹窗试听及候选人 A/B 试听；支持绑定、新建、解绑和声纹合并。
- `/admin` Org Chart：图形画布增删节点、拖动确认上级、根节点放置区、未入图人员托盘、撤销和服务端环路校验；参考文件上传后可提取为增量草稿（PDF 用 pdftoppm 渲成页图）。

## 环境变量（测试用）

- `MEETING_WEB_BANK`：声纹库目录（默认 `speaker_bank/`）。测试时指向临时假库，不碰真实 bank.json。
- `MEETING_DATA_ROOT`：私有数据根（默认项目根）；测试时指向一次性目录。
- `MEETING_WEB_JOBS`：作业 JSON 目录（默认 `web/jobs/`）。
- `MEETING_WEB_PORT`：端口（默认 8899；与其他实例冲突时可改，如测试用 8898）。
- `MEETING_WEB_DRYRUN=1`：作业干跑——管线只执行 `<脚本> --help` 校验调用链，regen 直接标记完成。
- `MEETING_LLM_API` / `MEETING_LLM_MODEL`：助手使用的本机 OpenAI-compatible API 与模型。

`MEETING_MINUTES_ROOT` 仅作为旧版兼容变量保留。

## 冒烟测试

```bash
make smoke
# 自动创建一次性数据根、假声纹库和独立端口；全部断言通过后自动清理
```

## 测试夹具

合成夹具包含 10 秒静音、虚构 Alice/Bob 对话、2 页假 slides 和假 minutes.md。
`web/tests/run_smoke.py` 每次在独立 `tempfile` 根目录中生成并销毁它；不得把测试服务指向真实数据根。
