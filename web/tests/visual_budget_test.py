"""Synthetic checks for evidence retention, bounded passes and meeting review."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bin'))
import slide_pages as sp
import minutes_by_page as mb
import meeting_generation as mg
from visual_fixture import observation
from meeting_core import visual_result as vr, visual_workflow as vw
from meeting_core.visual_budget import select_pages

pages = [{'page': i + 1, 'first': i * 10, 'shot': True, 'talking_head': i % 2 == 0}
         for i in range(100)]
selected = select_pages(pages, {}, 10)
assert len(selected) == 10
assert selected[0]['page'] == 1 and selected[-1]['page'] == 100
seen = {}
for _ in range(10):
    batch = select_pages(pages, seen, 10)
    assert not set(seen).intersection(p['page'] for p in batch)
    seen.update({p['page']: 'read' for p in batch})
assert len(seen) == 100 and len(pages) == 100
assert len(select_pages(pages, {}, 0)) == 100
assert len(select_pages(pages, {}, 1)) == 1

with tempfile.TemporaryDirectory() as tmp:
    mdir = Path(tmp)
    frames = np.repeat(np.arange(90, dtype=np.uint8), 3)[:, None, None] * np.ones((1, 2, 2), dtype=np.uint8)
    stats = {'skin': np.zeros(270), 'edge': np.zeros(270)}
    with patch.object(sp, '_decode_small', return_value=(frames, stats)), patch.object(
            sp, '_grab_frame', side_effect=lambda _v, _t, _w, out: out.write_bytes(b'fixture')):
        output = sp.extract_pages('synthetic.mp4', mdir / 'slides', mode='media',
                                  threshold=.1, same_threshold=.1, verbose=False)
    assert len(output) == 90
    assert len(list((mdir / 'slides').glob('page_*.jpg'))) == 90
    assert not any(p.get('truncated') for p in json.loads((mdir / 'slides.json').read_text()))

    # The second pass supplements the first without losing high-tier provenance.
    selected = [{'page': i, 'first': i * 10, 'shot': True, 'image': f'{i}.jpg'} for i in range(1, 6)]
    for p in selected:
        (mdir / 'slides' / p['image']).write_bytes(b'fixture')
    record = {'key': vr.cache_key(mdir / 'slides/1.jpg', vw.producer('synthetic'), 'media'),
              'producer': vw.producer('synthetic'), 'observation': observation()}
    vw.save(mdir / 'page_desc.json', {'model': 'synthetic', 'records': {'1': record}})

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"data":[{"id":"synthetic"}]}'

    calls = []
    def chat(_api, _model, image, tokens, prompt, **kwargs):
        calls.append((image.name, tokens))
        return json.dumps(observation()), {'completion_tokens': 8}
    with patch.object(mb, 'VL_MEDIA_MAX_NEW_PAGES', 2), patch.object(
            mb.urllib.request, 'urlopen', return_value=Response()), patch.object(
            mb, 'chat_with_image', side_effect=chat), patch.object(mb, 'grab_fullres') as full:
        first = mb.describe_pages(mdir, selected, 'http://synthetic/v1', video=Path('synthetic.mp4'))
        assert len(first) == 3 and len(calls) == 2 and not full.called
        second = mb.describe_pages(mdir, selected, 'http://synthetic/v1')
        assert len(second) == 5 and len(calls) == 4
    cache = json.loads((mdir / 'page_desc.json').read_text())
    assert cache['records']['1'] == record
    assert cache['deferred_pages'] == []
    assert all(t <= 2048 for _, t in calls)
    assert len(list((mdir / 'slides').glob('page_*.jpg'))) == 90

    timeline_path = mdir / 'slides.json'
    timeline = json.loads(timeline_path.read_text())
    old_cache = (mdir / 'page_desc.json').read_text()
    (mdir / 'slides' / 'full_01.jpg').write_bytes(b'old-native-frame')
    (mdir / 'slides' / timeline[0]['image']).write_bytes(b'new-chart-values')
    sp._write_timeline(timeline_path, timeline, mdir / 'slides')
    assert not (mdir / 'page_desc.json').exists()
    assert not (mdir / 'slides' / 'full_01.jpg').exists()
    archived = list((mdir / '.visual-cache-history').glob('*/page_desc.json'))
    assert len(archived) == 1 and archived[0].read_text() == old_cache
    assert (archived[0].parent / 'full_01.jpg').read_bytes() == b'old-native-frame'

    (mdir / 'minutes.md').write_text('# Synthetic minutes\n')
    result = mg.finalize(mdir, pages=90, vl_pages=20, visual_mode='complete')
    assert result['enrichment']['visual_mode'] == 'partial'

candidates = mb.media_review_candidates(
    [{'page': 1}, {'page': 2}, {'page': 3, 'talking_head': True},
     {'page': 4, 'talking_head': True, 'review_requested': True}],
    {1: '复杂表格，坐标轴和图例', 3: '普通口播', 4: '请复核'}, limit=10)
assert {p['page'] for p in candidates} == {2, 4}
print('Visual budget: full evidence, bounded resumable passes, partial status and meeting review passed')
