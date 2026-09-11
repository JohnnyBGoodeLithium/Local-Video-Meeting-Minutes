"""Synthetic private configuration, authorization and transport regression."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'bin'), str(Path(__file__).resolve().parents[1])]
from meeting_core import model_settings as m
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.model_settings import router

config = {'text': {'source':'local', 'api':'http://127.0.0.1:9999/v1', 'model':'synthetic', 'minutes_model':'synthetic-final'},
          'vision': {'source':'local', 'api':'http://127.0.0.1:9998/v1', 'model':'synthetic-vision'}}
with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MEETING_DATA_ROOT':tmp}):
    clean = m.normalize(config, {})
    m.save_config(clean)
    assert m.config_path().stat().st_mode & 0o777 == 0o600
    assert not m.public_config(clean)['text']['key_configured']
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
    app = FastAPI();app.include_router(router)
    client = TestClient(app)
    assert client.get('/api/settings/models').status_code == 200
    assert client.put('/api/settings/models', json=config).status_code == 403
    assert client.put('/api/settings/models', json=config, headers={'Origin':'https://evil.test'}).status_code == 403
    result = client.put('/api/settings/models', json=config, headers={'Origin':'http://testserver'})
    assert result.status_code == 200 and result.json()['restart_required']
    assert client.get('/api/settings/models', headers={'Host':'external.test'}).status_code == 403
    assert 'api_key' not in result.text
    assert m.NoRedirect().redirect_request(None,None,302,'',{},'https://other.test') is None
print('model settings: private secrets, cloud opt-in, stable snapshot, endpoint-bound auth and local administration passed')
