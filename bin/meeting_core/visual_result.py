"""Versioned visual observations, validation and deterministic presentation.

These are image observations, never meeting decisions. No model output is HTML.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = 'visual-result/v1'
PROMPT_VERSION = '2026-09-11.2'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Region(Strict):
    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def bounds(self):
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError('invalid_region')
        return self


class TextBlock(Strict):
    text: str = Field(max_length=4000)
    region: Region | None


class Fact(Strict):
    subject: str
    text: str
    raw_value: str
    value: float | None
    unit: str
    period: str
    qualifier: str
    basis: Literal['printed', 'estimated', 'unreadable']
    region: Region | None

    @model_validator(mode='after')
    def finite(self):
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError('nonfinite_value')
        if self.basis == 'unreadable' and self.value is not None:
            raise ValueError('unreadable_value_must_be_null')
        return self


class Table(Strict):
    title: str
    columns: list[str] = Field(max_length=40)
    rows: list[list[str | None]] = Field(max_length=100)
    notes: list[str]
    region: Region | None

    @model_validator(mode='after')
    def shape(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError('table_row_width')
        return self


class Axis(Strict):
    label: str
    unit: str
    scale: Literal['linear', 'log', 'categorical', 'unknown']


class Series(Strict):
    name: str
    points: list[Fact] = Field(max_length=100)


class Chart(Strict):
    title: str
    axes: list[Axis] = Field(max_length=4)
    series: list[Series] = Field(max_length=24)
    notes: list[str]
    region: Region | None


class Issue(Strict):
    reason: Literal['unreadable', 'missing_rows', 'ambiguous_mapping', 'unit_conflict',
                    'source_conflict', 'cutoff', 'other']
    question: str
    importance: Literal['critical', 'normal']
    region: Region | None


class Observation(Strict):
    schema_version: Literal['visual-result/v1']
    kind: Literal['text', 'table', 'chart', 'mixed', 'scene', 'blank']
    title: str = Field(max_length=500)
    status: Literal['complete', 'partial', 'unreadable']
    summary: str = Field(max_length=2000)
    text_blocks: list[TextBlock] = Field(max_length=100)
    facts: list[Fact] = Field(max_length=100)
    tables: list[Table] = Field(max_length=12)
    charts: list[Chart] = Field(max_length=12)
    interpretation: str = Field(max_length=2000)
    unresolved: list[Issue] = Field(max_length=32)


class LivePreview(Strict):
    """Small wire contract; expanded to the same observation format before storage."""
    kind: Literal['text', 'table', 'chart', 'mixed', 'scene', 'blank']
    title: str = Field(max_length=100)
    summary: str = Field(max_length=160)
    unread_regions: list[str] = Field(max_length=3)


def live_observation(raw: str) -> dict:
    preview = LivePreview.model_validate_json(raw)
    questions = preview.unread_regions or ['实时初读仅确认当前画面主题，完整内容待离线读取']
    return validate({'schema_version': SCHEMA, 'kind': preview.kind, 'title': preview.title,
        'summary': preview.summary, 'status': 'partial', 'text_blocks': [], 'facts': [],
        'tables': [], 'charts': [], 'interpretation': '', 'unresolved': [
            {'reason': 'other', 'question': q, 'importance': 'normal', 'region': None} for q in questions]})


def validate(value: dict | str) -> dict:
    obj = Observation.model_validate_json(value) if isinstance(value, str) else Observation.model_validate(value)
    data = obj.model_dump()
    # A valid JSON object is not proof that all image regions were read.
    if data['kind'] == 'table' and not data['tables'] and not any(i['reason'] == 'missing_rows' for i in data['unresolved']):
        data['unresolved'].append({'reason': 'missing_rows', 'question': '表格行列尚未读取',
                                  'importance': 'critical', 'region': None})
    if data['kind'] == 'chart' and not data['charts'] and not any(i['reason'] == 'ambiguous_mapping' for i in data['unresolved']):
        data['unresolved'].append({'reason': 'ambiguous_mapping', 'question': '图表轴与系列尚未读取',
                                  'importance': 'critical', 'region': None})
    if any(v is None for table in data['tables'] for row in table['rows'] for v in row):
        if not any(x['reason'] == 'missing_rows' for x in data['unresolved']):
            data['unresolved'].append({'reason': 'missing_rows', 'question': '表格存在未读取单元格',
                                      'importance': 'normal', 'region': None})
    if data['unresolved'] and data['status'] == 'complete':
        data['status'] = 'partial'
    if not (data['summary'].strip() or data['text_blocks'] or data['facts'] or data['tables'] or data['charts']):
        if data['kind'] != 'blank':
            data['status'] = 'unreadable'
    return data


def prompt(mode: str, *, compact: bool = False, question: str = '') -> str:
    if mode == 'live':
        return ('独立观察当前直播截图，只输出给定JSON。title用简短标题，summary用不超过60字说明当前画面主题。'
                '不展开图表或逐项抄录数值；unread_regions至多3条简短描述尚未读取的区域。'
                '看不清或有复杂图表就标明，不能猜填或把展示方案当作会议决定。')
    scene = {'meeting': '会议共享画面', 'media': '视频画面', 'live': '直播画面'}[mode]
    return (f'独立读取这张{scene}，不要参考或推测语音内容。输出符合给定schema的JSON，不要思考过程。'
            '所有字符串保留图中文字原文语言；summary和解释使用中文。空集合写[]，未知数值写null。'
            'facts保留对象、时期、单位与目标/预测/实际限定；14%记录value=14,unit="%"，不能写0.14。'
            '表格保留行列和脚注，缺单元格用null；图表保留轴、单位、图例、系列及脚注。'
            '明确印出的读数basis=printed，由坐标估读用estimated；看不清用unreadable，不可补造。'
            'region为原图归一化边界left/top/right/bottom，不确定位置用null。'
            '没有完全读完的表格、图表或小字必须列入unresolved，并标partial；不要因格式完整就称读完。'
            '解释与原文事实分开，展示内容不能证明会议决定或作者已经口述。'
            '每个数据只输出一次：已有tables/charts时，不在facts或text_blocks重复列出相同数据。'
            'Fact的text只补充其余字段未表达的内容，否则写空字符串。清晰读数无需逐个框选region，可用图表整体region；只为疑难区域定位。'
            + ('本轮预算很短：summary不超过60字，facts至多1条，text_blocks/tables/charts留空，interpretation为空。'
               '未展开的表格/图表/小字用1条unresolved概括并标partial，优先在时限内完成JSON。' if compact else
               'summary不超过100字，interpretation不超过100字。完整保留可读表格、图表数据及脚注，避免重复和长篇解释。')
            + (f'本轮只针对以下区域问题独立核对：{question}' if question else ''))


def file_stamp(path: str | Path | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    try:
        s = p.stat()
        return {'name': p.name, 'size': s.st_size, 'mtime_ns': s.st_mtime_ns}
    except OSError:
        return {'name': p.name, 'missing': True}


def cache_key(image: Path, producer: dict, mode: str) -> str:
    body = {'image': hashlib.sha256(image.read_bytes()).hexdigest(), 'producer': producer,
            'mode': mode, 'schema': SCHEMA, 'prompt': PROMPT_VERSION}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def fact_text(fact: dict) -> str:
    return ' · '.join(str(fact.get(k) or '') for k in
                      ('subject', 'period', 'raw_value', 'unit', 'qualifier', 'text') if fact.get(k))


def summary_context(data: dict) -> dict:
    """Whole facts including qualifiers; never substring an evidence-bearing fact."""
    data = validate(data)
    return {k: data[k] for k in ('title', 'kind', 'status', 'summary', 'text_blocks', 'facts', 'tables', 'charts', 'unresolved')} | {
        'table_notes': [n for t in data['tables'] for n in t['notes']],
        'chart_notes': [n for c in data['charts'] for n in c['notes']],
        'evidence_boundary': 'screen_observation_not_a_meeting_decision'}


def markdown(data: dict) -> str:
    """Compatibility projection. Structured objects remain the authoritative observation."""
    data = validate(data)
    def safe(value):
        return html.escape(str(value or '')).replace('|', '&#124;').replace('\n', ' ')
    lines = ['## 标题', safe(data['title']), '## 页面内容', safe(data['summary'])]
    lines += ['- ' + safe(b['text']) for b in data['text_blocks']]
    lines += ['- ' + safe(fact_text(f)) for f in data['facts']]
    for table in data['tables']:
        lines += ['', '### ' + safe(table['title'])]
        if table['columns']:
            lines += ['| ' + ' | '.join(map(safe, table['columns'])) + ' |',
                      '| ' + ' | '.join('---' for _ in table['columns']) + ' |']
            lines += ['| ' + ' | '.join('待核' if x is None else safe(x) for x in row) + ' |'
                      for row in table['rows']]
        lines += ['- ' + safe(n) for n in table['notes']]
    for chart in data['charts']:
        lines += ['', '### ' + safe(chart['title'])]
        lines += ['- 坐标轴：' + safe(' / '.join((a['label'], a['unit'], a['scale']))) for a in chart['axes']]
        for series in chart['series']:
            lines += ['- 系列：' + safe(series['name'])]
            lines += ['  - ' + safe(fact_text(p)) + ('（估读）' if p['basis'] == 'estimated' else '')
                      for p in series['points']]
        lines += ['- ' + safe(n) for n in chart['notes']]
    if data['interpretation']:
        lines += ['## 画面解释（模型推断）', safe(data['interpretation'])]
    lines += ['## 读取状态', {'complete': '初读完成，未人工核验', 'partial': '部分读取，仍有待核项',
                            'unreadable': '无法可靠读取'}[data['status']]]
    lines += ['- 待核：' + safe(i['question']) for i in data['unresolved']]
    return '\n'.join(lines)


def render_html(data: dict) -> str:
    """Fixed escaped UI layout; model strings never control tags or Markdown."""
    data = validate(data)
    e = lambda x: html.escape(str(x or ''), quote=True)
    def paras(items):
        return '<ul>' + ''.join('<li>' + e(x) + '</li>' for x in items) + '</ul>' if items else ''
    label = {'complete': '初读完成 · 未人工核验', 'partial': '部分读取 · 待核', 'unreadable': '无法可靠读取'}
    out = ['<section class="visual-observation">', '<p class="visual-read-status">' + label[data['status']] + '</p>',
           '<p>' + e(data['summary']) + '</p>', paras(b['text'] for b in data['text_blocks']),
           paras(fact_text(f) for f in data['facts'])]
    for t in data['tables']:
        out += ['<h4>' + e(t['title']) + '</h4><div class="visual-table-scroll"><table><thead><tr>',
                ''.join('<th>' + e(c) + '</th>' for c in t['columns']), '</tr></thead><tbody>']
        out += ['<tr>' + ''.join('<td>' + ('<span class="visual-unknown">待核</span>' if c is None else e(c)) + '</td>'
                                for c in row) + '</tr>' for row in t['rows']]
        out += ['</tbody></table></div>', paras(t['notes'])]
    for c in data['charts']:
        out += ['<h4>' + e(c['title']) + '</h4>', paras('坐标轴：' + ' / '.join((a['label'], a['unit'], a['scale'])) for a in c['axes'])]
        for s in c['series']:
            out += ['<details><summary>' + e(s['name']) + '</summary>',
                    paras(fact_text(p) + ('（估读）' if p['basis'] == 'estimated' else '') for p in s['points']), '</details>']
        out += [paras(c['notes'])]
    if data['interpretation']:
        out += ['<h4>画面解释（模型推断）</h4><p>' + e(data['interpretation']) + '</p>']
    if data['unresolved']:
        out += ['<h4>待核项</h4>', paras(i['question'] for i in data['unresolved'])]
    return ''.join(out) + '</section>'
