"""Regression cases from visual review: no stale facts, false resolution or broken rendering."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bin'))
from visual_fixture import observation
from meeting_core import visual_result as vr, visual_workflow as vw
import vl_page_test as vp
import minutes_by_page as mb

raw = observation(tables=[{'title': '<script>x</script>', 'columns': ['A', 'B'],
    'rows': [['<img src=x onerror=1>', None]], 'notes': ['Q4是预测'], 'region': None}])
value = vr.validate(raw)
assert value['status'] == 'partial' and value['unresolved']
rendered = vr.render_html(value)
assert '<script>' not in rendered and '<img ' not in rendered and '&lt;script&gt;' in rendered
assert '<table>' in rendered and '待核' in rendered
raw['tables'][0]['rows'] = [['missing column']]
try: vr.validate(raw)
except ValueError: pass
else: raise AssertionError('ragged table accepted')
issue = {'reason': 'unreadable', 'question': '背景数字看不清', 'importance': 'critical', 'region': None}
pages = [{'page': 1, 'first': 0, 'image': 'one.jpg', 'shot': True, 'talking_head': True}]
assert vw.choose_review(pages, {1: observation(unresolved=[issue], status='partial')}, 5)
assert not vw.choose_review(pages, {1: observation(summary='没有图表，无需复核')}, 5)
original = observation(status='partial', unresolved=[issue])
result, state = vw.reconcile(original, observation(status='unreadable', unresolved=[issue]))
assert state == 'partial' and result['unresolved']
fact = {'subject': '收入', 'text': '', 'raw_value': '14%', 'value': 14., 'unit': '%', 'period': 'Q4',
        'qualifier': '预测', 'basis': 'printed', 'region': None}
result, state = vw.reconcile(observation(facts=[fact]), observation(facts=[{**fact, 'value': 18.}]))
assert state == 'conflict' and result['facts'][0]['value'] == 14.
assert vr.summary_context(observation(summary='背景'*500, facts=[fact]))['facts'][0]['qualifier'] == '预测'
for candidate in (observation(), observation(facts=[{**fact, 'qualifier': ''}])):
    kept, state = vw.reconcile(observation(facts=[fact], status='partial', unresolved=[issue]), candidate)
    assert state == 'partial' and kept['facts'][0]['qualifier'] == '预测'
missing_table = vr.validate(observation(kind='table'))
assert vr.validate(missing_table) == missing_table, 'validation must be idempotent'
table = {'title': '虚构表', 'columns': ['项目', '读数'], 'rows': [['A', '1'], ['B', '2']],
         'notes': ['仅为预测'], 'region': None}
_, state = vw.reconcile(observation(tables=[table]), observation(tables=[{**table, 'rows': [['B', '3'], ['A', '1']]}]))
assert state == 'conflict', 'reordered table rows must still detect changed cells'
_, state = vw.reconcile(observation(tables=[table]), observation(tables=[{**table, 'rows': [['A', '1']]}]))
assert state == 'partial', 'missing readable rows must not be marked resolved'
partial_table = vr.validate(observation(tables=[{**table, 'rows': [['A', None], ['B', '2']]}]))
filled, state = vw.merge_region(partial_table, observation(tables=[{**table, 'rows': [['A', '1']]}]), partial_table['unresolved'])
assert state == 'resolved' and filled['tables'][0]['rows'] == table['rows']

class Response:
    def __init__(self, data): self.data=data
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self): return json.dumps(self.data).encode()

with tempfile.TemporaryDirectory() as tmp:
    mdir=Path(tmp);(mdir/'slides').mkdir();image=mdir/'slides/one.jpg';image.write_bytes(b'first')
    producer=vw.producer('new')
    cache={'model':'new','records':{'1':{'key':vr.cache_key(image,producer,'media'),
        'producer':producer,'observation':observation()}},'desc':{'1':'legacy'}}
    assert vw.valid_records(mdir,pages,'new',cache)
    assert not vw.valid_records(mdir,pages,'other',cache)
    image.write_bytes(b'changed')
    assert not vw.valid_records(mdir,pages,'new',cache)
    with patch.object(vp.urllib.request,'urlopen',return_value=Response({'choices':[{
            'finish_reason':'length','message':{'content':'{"title":"broken'}}]})):
        try: vp.chat_with_image('http://fake/v1','fake',image,128)
        except ValueError: pass
        else: raise AssertionError('truncated reply accepted')
    # Switching from legacy data must re-read, with the schema attached to the request.
    vw.save(mdir/'page_desc.json', {'model':'old','desc':{'1':'OLD'}})
    calls=[]
    def chat(*args, **kwargs):
        calls.append(kwargs);return json.dumps(original), {}
    with patch.object(mb.urllib.request,'urlopen',return_value=Response({'data':[{'id':'new'}]})), \
            patch.object(mb,'chat_with_image',side_effect=chat):
        mb.describe_pages(mdir,pages,'http://fake/v1')
    assert len(calls)==1 and calls[0]['response_schema']
    primary=vw.load(mdir/'page_desc.json')['records']['1']
    with patch.object(mb.urllib.request,'urlopen',return_value=Response({'data':[{'id':'review'}]})), \
            patch.object(mb,'chat_with_image',return_value=(json.dumps(original),{})):
        _, stats=mb.review_media_pages(mdir,pages,{1:'old'},'http://fake/v1')
    cached=vw.load(mdir/'page_desc.json')
    assert cached['records']['1']==primary
    assert cached['reviews']['1']['state']=='partial'
    assert 1 not in cached['reviewed_pages'] and stats['pending_pages']==[1]
print('visual contract: schema, cache invalidation, independent review and escaped rendering passed')

# Data tables and furniture must be distinguished in the model instruction.
for mode in ("meeting", "media"):
    assert "家具桌子" in vr.prompt(mode)

# A prompt refinement does not hide previous source-bound observations from readers,
# but a new inference run cannot pretend that old observations used the new prompt.
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp); (d / 'slides').mkdir(); (d / 'slides/one.jpg').write_bytes(b'synthetic')
    old = {**vw.producer('example'), 'prompt': 'older-prompt'}
    cache = {'records': {'1': {'producer': old, 'key': vr.cache_key(d/'slides/one.jpg', old, 'media', prompt_version='older-prompt'), 'observation': observation()}}}
    assert not vw.valid_records(d, pages, 'example', cache)
    assert vw.valid_records(d, pages, 'example', cache, display=True)
    cache['reviews'] = {'1': {'producer': {**vw.producer('review', review=True), 'prompt': 'older-prompt'}, 'primary_key': cache['records']['1']['key'], 'state': 'resolved', 'effective': observation(summary='Historical independent review')}}
    assert vw.effective_records(d, pages, 'example', cache, display=True)[1]['summary'] == 'Historical independent review'
    (d / 'slides/one.jpg').write_bytes(b'changed-image')
    assert not vw.valid_records(d, pages, 'example', cache, display=True)

from meeting_structure import _visual_value
assert _visual_value("场景中没有数据、图表或表格，不能读取行列。", "设备展示")["information_value"] != "high"
