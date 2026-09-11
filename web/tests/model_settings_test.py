"""Synthetic private configuration, authorization and transport regression."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'bin'), str(Path(__file__).resolve().parents[1])]
from meeting_core import model_settings as m
import asyncio
from fastapi import HTTPException
from starlette.requests import Request
from routers import model_settings as routes

config = {'text': {'source':'local', 'api':'http://127.0.0.1:9999/v1', 'model':'synthetic', 'minutes_model':'synthetic-final'},
          'vision': {'source':'local', 'api':'http://127.0.0.1:9998/v1', 'model':'synthetic-vision'}}
with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MEETING_DATA_ROOT':tmp}):
    with patch.dict(os.environ, {'MEETING_LLM_API':'https://example.test/v1', 'MEETING_ALLOW_REMOTE_LLM':'0'}):
        assert not m.public_config({})['text']['allow_cloud'], 'remote address alone is not consent'
    clean = m.normalize(config, {})
    m.save_config(clean)
    assert m.config_path().stat().st_mode & 0o777 == 0o600
    assert not m.public_config(clean)['text']['key_configured']
    with patch.dict(os.environ, {'MEETING_MODEL_SETTINGS_LOADED':'0', 'MEETING_VL_API':clean['vision']['api'], 'MEETING_VL_MODEL_ID':clean['vision']['model'], 'MEETING_VL_REVISION':'existing-revision'}):
        m.apply_saved_config()
        assert os.environ['MEETING_VL_REVISION'] == 'existing-revision', 'saving unchanged settings must not invalidate observations'
    cloud = {**config, 'text': {**config['text'], 'source':'cloud', 'api':'https://example.test/v1', 'api_key':'synthetic-secret'}}
    try: m.normalize(cloud, {})
    except ValueError: pass
    else: raise AssertionError('cloud consent required')
    cloud['text']['allow_cloud'] = True
    saved = m.normalize(cloud, {})
    assert 'synthetic-secret' not in json.dumps(m.public_config(saved))
    blank = {**cloud, 'text':{**cloud['text'], 'api_key':''}}
    assert m.normalize(blank, saved)['text']['api_key'] == 'synthetic-secret'
    changed = {**blank, 'text':{**blank['text'], 'api':'https://other.test/v1'}}
    assert not m.normalize(changed, saved)['text']['api_key']
    m.save_config(saved)
    with patch.dict(os.environ, {'MEETING_MODEL_SETTINGS_LOADED':'0'}):
        m.apply_saved_config()
        assert os.environ['MEETING_LLM_API_KEY'] == 'synthetic-secret'
        from meeting_core.resource_policy import router_models
        assert router_models() == []
        m.save_config(clean)
        m.apply_saved_config()
        assert os.environ['MEETING_LLM_API'] == 'https://example.test/v1', 'active snapshot must stay stable'
        response = MagicMock()
        with patch.object(m.urllib.request, 'build_opener', return_value=response):
            req = m.urllib.request.Request('https://example.test/v1/chat/completions', data=json.dumps({'chat_template_kwargs':{},'repeat_penalty':1,'model':'test'}).encode())
            m.open_request(req)
            assert req.get_header('Authorization') == 'Bearer synthetic-secret'
            assert 'repeat_penalty' not in json.loads(req.data)
        try:m.open_request('https://other.test/v1/models')
        except ValueError:pass
        else:raise AssertionError('unconfigured remote must fail')
    def request(body=None, *, origin='', host='testserver'):
        headers = [(b'host', host.encode())]
        if origin: headers.append((b'origin', origin.encode()))
        async def receive():
            return {'type':'http.request','body':json.dumps(body).encode(),'more_body':False}
        return Request({'type':'http','method':'PUT','path':'/api/settings/models',
                        'headers':headers,'client':('127.0.0.1',12345)}, receive)
    assert routes.get_settings(request())['settings']
    for origin in ('', 'https://evil.test'):
        try: asyncio.run(routes.put_settings(request(config, origin=origin)))
        except HTTPException as e: assert e.status_code == 403
        else: raise AssertionError('cross-origin write accepted')
    result = asyncio.run(routes.put_settings(request(config, origin='http://testserver')))
    assert result['restart_required'] and 'api_key' not in json.dumps(result)
    try: routes.get_settings(request(host='external.test'))
    except HTTPException as e: assert e.status_code == 403
    else: raise AssertionError('remote administration accepted')
    for candidate, is_local in ((config, True), (cloud, False)):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode()
        opener = MagicMock(); opener.open.return_value = response
        with patch.object(m.urllib.request, 'build_opener', return_value=opener):
            result = asyncio.run(routes.test_settings(request({'role':'text','settings':candidate}, origin='http://testserver')))
        assert result['ok']
        body = json.loads(opener.open.call_args.args[0].data)
        assert ('chat_template_kwargs' in body) == is_local
    assert m.NoRedirect().redirect_request(None,None,302,'',{},'https://other.test') is None
print('model settings: private secrets, cloud opt-in, stable snapshot, endpoint-bound auth and local administration passed')
