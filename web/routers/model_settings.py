"""Local administrator settings; no meeting payload is used for connection tests."""
import json
import threading
import urllib.request
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from meeting_core import model_settings as settings

router = APIRouter(prefix='/api/settings/models')
LOCK = threading.Lock()
ACTIVE = settings.public_config({})
INITIAL_SAVED = settings.read_config()


def admin(request: Request, *, write=False):
    host = urlsplit('//' + request.headers.get('host', '')).hostname
    client = request.client.host if request.client else ''
    if host not in settings.LOOPBACK | {'testserver'} or client not in settings.LOOPBACK | {'testclient'}:
        raise HTTPException(403, '请在服务所在机器打开模型设置')
    if write:
        origin = urlsplit(request.headers.get('origin', ''))
        if origin.scheme not in {'http', 'https'} or origin.netloc != request.headers.get('host'):
            raise HTTPException(403, '请从本机设置页面操作')


def payload():
    saved = settings.public_config(settings.read_config())
    return {'settings': saved, 'active': ACTIVE, 'restart_required': settings.read_config() != INITIAL_SAVED,
            'recommendations': settings.RECOMMENDATIONS,
            'protocol': 'OpenAI-compatible Chat Completions'}


@router.get('')
def get_settings(request: Request):
    admin(request)
    return payload()


@router.put('')
async def put_settings(request: Request):
    admin(request, write=True)
    try:
        value = await request.json()
        with LOCK:
            previous = settings.read_config()
            # Permit blank-key preservation for an unchanged environment-based setup.
            if not previous:
                import os
                previous = {role: {field: os.environ.get(env, '') for field, env in mapping.items()}
                            for role, mapping in settings.FIELDS.items()}
            settings.save_config(settings.normalize(value, previous))
        return {**payload(), 'restart_required': True}
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, '配置无效：检查来源、HTTPS 地址、模型 ID 和云端授权') from None


@router.post('/test')
async def test_settings(request: Request):
    admin(request, write=True)
    try:
        value = await request.json()
        role = value.get('role')
        if role not in settings.FIELDS:
            raise ValueError('invalid_role')
        config = settings.normalize(value['settings'], settings.read_config())
        item = config[role]
        content = 'Reply with OK. This is a synthetic connection test.'
        if role == 'vision':
            content = [{'type': 'text', 'text': 'Describe this synthetic test image briefly.'},
                       {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG1kAAAAASUVORK5CYII='}}]
        body = {'model': item['model'], 'messages': [{'role': 'user', 'content': content}],
                'max_tokens': 64}
        headers = {'Content-Type': 'application/json'}
        if item.get('api_key'):
            headers['Authorization'] = 'Bearer ' + item['api_key']
        req = urllib.request.Request(item['api'] + '/chat/completions',
                                     data=json.dumps(body).encode(), headers=headers)
        # This explicit test uses the unsaved form, without changing runtime settings.
        import asyncio
        def send():
            with urllib.request.build_opener(settings.NoRedirect()).open(req, timeout=30) as response:
                return json.loads(response.read(1024 * 1024))
        result = await asyncio.to_thread(send)
        if not result['choices'][0]['message'].get('content'):
            raise ValueError('empty_result')
        return {'ok': True, 'message': '接口已响应；仅使用测试内容，不代表复杂图表质量已验证。'}
    except Exception:
        # Never echo provider error bodies, submitted keys or URLs.
        raise HTTPException(400, '连接测试失败，请检查接口、模型 ID、密钥及该模型的输入能力') from None
