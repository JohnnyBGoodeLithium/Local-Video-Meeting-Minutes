"""Bounded local image analysis with per-image provenance and independent review."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from meeting_core import visual_result as vr


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, data: dict):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


def local_api(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('visual_endpoint_must_be_local')
    return value.rstrip('/')


def producer(model: str, *, review: bool = False) -> dict:
    prefix = 'MEETING_VL_REVIEW_' if review else 'MEETING_VL_'
    return {'model': model, 'weights': vr.file_stamp(os.environ.get(prefix + 'MODEL')),
            'projector': vr.file_stamp(os.environ.get(prefix + 'MMPROJ')),
            'revision': os.environ.get(prefix + 'REVISION', ''),
            'schema': vr.SCHEMA, 'prompt': vr.PROMPT_VERSION}


def request(request_fn, api: str, model: str, image: Path, mode: str, *, max_tokens=2048,
            timeout=120, attempts=2, question='') -> tuple[dict, dict]:
    usage = {}; started = time.monotonic()
    error = None
    for attempt in range(attempts):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            break
        try:
            raw, tokens = request_fn(api, model, image, max_tokens,
                vr.prompt(mode, compact=attempt > 0 or mode == 'live', question=question),
                response_schema=(vr.LivePreview if mode == 'live' else vr.Observation).model_json_schema(), timeout=remaining)
            usage = {k: int(usage.get(k, 0)) + int(v) for k, v in tokens.items() if isinstance(v, int)}
            return (vr.live_observation(raw) if mode == 'live' else vr.validate(raw)), usage
        except Exception as exc:
            # One bounded compact retry. Never recover facts from malformed JSON.
            error = exc
    raise ValueError('visual_read_failed:' + type(error).__name__) from error


def mode(page: dict) -> str:
    return 'media' if page.get('shot') else 'meeting'


def valid_records(mdir: Path, pages: list[dict], model: str, cache: dict, *, display: bool = False) -> dict[int, dict]:
    result = {}
    for page in pages:
        if not str(page.get('page', '')).isdigit() or not page.get('image'):
            continue
        key = str(page['page']); record = cache.get('records', {}).get(key, {})
        image = mdir / 'slides' / page['image']
        try:
            current = producer(model)
            stored = record.get('producer', {})
            version = None
            if display and isinstance(stored, dict) and stored.get('prompt'):
                if {k: v for k, v in stored.items() if k != 'prompt'} == {k: v for k, v in current.items() if k != 'prompt'}:
                    current = stored
                    version = stored['prompt']
            expected = vr.cache_key(image, current, mode(page), prompt_version=version)
            if record.get('key') == expected:
                result[int(key)] = vr.validate(record['observation'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def summaries(mdir: Path, pages: list[dict]) -> dict[int, dict]:
    cache = load(mdir / 'page_desc.json')
    model = os.environ.get('MEETING_VL_MODEL_ID') or cache.get('model', '')
    return {n: vr.summary_context(v) for n, v in effective_records(mdir, pages, model, cache).items()}


def completed_budget_pass(pages: list[dict], available: dict, cache: dict) -> bool:
    """A completed bounded media pass may resume synthesis without extending it."""
    deferred = cache.get('deferred_pages')
    if not isinstance(deferred, list) or any(type(n) is not int for n in deferred):
        return False
    if any(not isinstance(p, dict) or type(p.get('page')) is not int for p in pages):
        return False
    required = {p['page'] for p in pages}
    deferred = set(deferred)
    media = {int(p['page']) for p in pages if p.get('shot')}
    selected = required - deferred
    return bool(selected) and deferred <= media and selected <= set(available)


def _facts(value):
    return value.get('facts', []) + [p for c in value.get('charts', []) for s in c['series'] for p in s['points']]


def reconcile(primary: dict, review: dict, *, crop=False) -> tuple[dict, str]:
    """Keep both candidates on disk. A contradictory second read is not authoritative."""
    primary, review = vr.validate(primary), vr.validate(review)
    known = {(f['subject'], f['period'], f['unit']): f['value'] for f in _facts(primary)
             if f['value'] is not None and f['basis'] == 'printed'}
    conflict = any((f['subject'], f['period'], f['unit']) in known and f['value'] is not None
                   and known[(f['subject'], f['period'], f['unit'])] != f['value'] for f in _facts(review))
    # Existing readable table cells must not silently change under a second model.
    tables = {t['title']: t for t in primary['tables']}
    for table in review['tables']:
        old = tables.get(table['title'])
        if old and old['columns'] == table['columns']:
            rows = {str(row[0]): row for row in table['rows'] if row}
            for a in old['rows']:
                b = rows.get(str(a[0]), []) if a else []
                if a and b and a[0] == b[0] and any(x is not None and y is not None and x != y for x, y in zip(a, b)):
                    conflict = True
    if conflict:
        merged = json.loads(json.dumps(primary))
        merged['status'] = 'partial'
        merged['unresolved'].append({'reason': 'source_conflict', 'question': '两次视觉读取的数值不一致，须对照原图核对',
                                     'importance': 'critical', 'region': None})
        return merged, 'conflict'
    if review['status'] != 'complete':
        return primary, 'partial'
    if not crop:
        # A shorter answer is not proof that the missing evidence was resolved.
        # Preserve qualifiers, readable cells and notes even when the reviewer
        # claims completeness. Conservative exact coverage can remain pending.
        reviewed_facts = _facts(review)
        covered = all(any(all(f.get(k) == r.get(k) for k in
            ('subject', 'value', 'unit', 'period', 'qualifier', 'basis'))
            for r in reviewed_facts) for f in _facts(primary))
        for old in primary['tables']:
            candidates = [t for t in review['tables'] if t['title'] == old['title'] and t['columns'] == old['columns']]
            covered = covered and any(set(old['notes']) <= set(t['notes']) and
                all(any(len(a) == len(b) and all(x is None or x == y for x, y in zip(a, b))
                        for b in t['rows']) for a in old['rows']) for t in candidates)
        if not covered:
            return primary, 'partial'
    # Only full-page candidates can replace the projection; crop candidates are retained separately.
    return review, 'resolved'


def effective_records(mdir: Path, pages: list[dict], model: str, cache: dict, *, display: bool = False) -> dict[int, dict]:
    records = valid_records(mdir, pages, model, cache, display=display)
    for n in list(records):
        entry = cache.get('reviews', {}).get(str(n), {})
        base = cache.get('records', {}).get(str(n), {})
        review_id = os.environ.get('MEETING_VL_REVIEW_MODEL_ID') or entry.get('producer', {}).get('model', '')
        expected_review = producer(review_id, review=True)
        stored_review = entry.get('producer', {})
        if display and isinstance(stored_review, dict):
            expected_review = {k: v for k, v in expected_review.items() if k != 'prompt'}
            stored_review = {k: v for k, v in stored_review.items() if k != 'prompt'}
        if entry and stored_review != expected_review:
            continue
        if entry.get('primary_key') == base.get('key') and entry.get('state') in {'resolved', 'partial'}:
            try:
                records[n] = vr.validate(entry['effective'])
            except (KeyError, ValueError):
                pass
        elif entry.get('primary_key') == base.get('key') and entry.get('state') == 'conflict':
            try:
                records[n], _ = reconcile(records[n], entry['observation'])
            except (KeyError, ValueError, TypeError):
                pass
    return records


def pending(observation: dict) -> bool:
    return observation['status'] != 'complete' or bool(observation['unresolved'])


def choose_review(pages: list[dict], observations: dict[int, dict], limit: int) -> list[dict]:
    ranked = []
    for page in pages:
        data = observations.get(int(page['page']))
        explicit = bool(page.get('review_requested') or page.get('review_question'))
        if not explicit and (not data or not pending(data)):
            continue
        critical = sum(i['importance'] == 'critical' for i in (data or {}).get('unresolved', []))
        ranked.append((int(explicit), critical, -float(page.get('first', 0)), page))
    ranked.sort(key=lambda x: x[:3], reverse=True)
    return [x[3] for x in ranked[:limit]]


def remap_regions(data: dict, bounds: tuple) -> dict:
    data = json.loads(json.dumps(data))
    def walk(value):
        if isinstance(value, dict):
            r = value.get('region')
            if r:
                l, t, right, bottom = bounds
                value['region'] = {'left': l+r['left']*(right-l), 'right': l+r['right']*(right-l),
                                   'top': t+r['top']*(bottom-t), 'bottom': t+r['bottom']*(bottom-t)}
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(data)
    return vr.validate(data)


def merge_region(primary: dict, candidate: dict, selected: list[dict]) -> tuple[dict, str]:
    checked, state = reconcile(primary, candidate, crop=True)
    if state != 'resolved':
        return checked, state
    merged = json.loads(json.dumps(primary))
    # A crop can resolve its own questions only; unrelated missing regions stay pending.
    merged['unresolved'] = [i for i in primary['unresolved'] if i not in selected]
    for field in ('facts', 'text_blocks', 'charts'):
        merged[field] += [v for v in candidate[field] if v not in merged[field]]
    for table in candidate['tables']:
        old = next((t for t in merged['tables'] if t['title'] == table['title']
                    and t['columns'] == table['columns']), None)
        if old is None:
            merged['tables'].append(table)
            continue
        for row in table['rows']:
            match = next((r for r in old['rows'] if r and row and r[0] == row[0]), None)
            if match is None:
                old['rows'].append(row)
            else:
                match[:] = [y if x is None else x for x, y in zip(match, row)]
        old['notes'] += [n for n in table['notes'] if n not in old['notes']]
    merged['status'] = 'partial' if merged['unresolved'] else 'complete'
    merged = vr.validate(merged)
    return merged, 'partial' if pending(merged) else 'resolved'


def reading_state(page: int, observation: dict | None, cache: dict, *, legacy: bool = False) -> str:
    """Read-only UI projection; classification and reading coverage are distinct."""
    if observation:
        return observation['status']
    if legacy:
        return 'legacy'
    deferred = cache.get('deferred_pages', [])
    if isinstance(deferred, list) and page in deferred:
        return 'deferred'
    return 'pending'
