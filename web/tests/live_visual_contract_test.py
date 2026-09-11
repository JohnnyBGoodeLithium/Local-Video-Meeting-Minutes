"""Live uses independent bounded vision, retains frames and defers expensive review."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'bin'))
from visual_fixture import observation
from meeting_core.live.evidence import LiveEvidence
from meeting_core.live.store import LiveSessionStore
from meeting_core.live.finalizer import _materialize_frames
from meeting_core import visual_workflow as vw
def preview_request(*args, **kwargs):
    assert set(kwargs['response_schema']['properties']) == {'kind', 'title', 'summary', 'unread_regions'}
    return json.dumps({'kind': 'chart', 'title': '虚构双轴图', 'summary': '展示季度趋势',
                       'unread_regions': ['详细数据与图例尚未读取']}), {}
preview, _ = vw.request(preview_request, 'http://fake/v1', 'test', Path('fake.jpg'), 'live')
assert preview['schema_version'] == 'visual-result/v1' and preview['status'] == 'partial'
assert preview['unresolved'] and not preview['charts']
with tempfile.TemporaryDirectory() as tmp:
    store=LiveSessionStore(Path(tmp));store.root.mkdir(parents=True,exist_ok=True)
    for i in range(12):store.write_frame(f'f{i}',b'synthetic',at=float(i*30),reason='periodic_safety')
    with patch.dict(os.environ,{'MEETING_LIVE_VL':'1','MEETING_VL_API':'http://127.0.0.1:11435/v1',
                               'MEETING_VL_MODEL_ID':'synthetic'}):
        evidence=LiveEvidence(store)
        calls=[]
        def request(*args,**kwargs):calls.append(kwargs);return observation(status='partial'),{}
        with patch.object(vw,'request',side_effect=request):assert evidence.analyze_next_frame()
        assert calls[0]['attempts']==1 and calls[0]['timeout']<=30
        frames=evidence.frames()
        assert len(frames)==12 and frames[-1]['visual_state']=='pending_review'
        assert any(f.get('visual_state')=='deferred_after_live' for f in frames)
        with patch.object(vw,'request',side_effect=TimeoutError):assert evidence.analyze_next_frame()
        assert len(evidence.frames())==12
    assert _materialize_frames(store,'media')==12
    assert all(p['shot'] for p in json.loads((Path(tmp)/'slides.json').read_text()))
print('live visual: isolated deadlines, deferred screenshots and media finalization passed')
