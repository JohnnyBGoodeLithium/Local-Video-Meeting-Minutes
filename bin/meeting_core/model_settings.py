"""Explicit, private model configuration and authenticated compatible transport."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import urllib.request
from urllib.parse import urlsplit

LOOPBACK = {'localhost', '127.0.0.1', '::1'}
FIELDS = {
    'text': {'api': 'MEETING_LLM_API', 'model': 'MEETING_LLM_MODEL',
             'minutes_model': 'MEETING_MINUTES_MODEL', 'api_key': 'MEETING_LLM_API_KEY'},
    'vision': {'api': 'MEETING_VL_API', 'model': 'MEETING_VL_MODEL_ID',
               'api_key': 'MEETING_VL_API_KEY'},
}
RECOMMENDATIONS = [
    {'name': 'Qwen3.6-35B-A3B', 'use': '通用文本与画面理解；本地视觉服务需加载匹配的 mmproj',
     'url': 'https://huggingface.co/ggml-org/Qwen3.6-35B-A3B-GGUF'},
    {'name': 'Qwen3.8-27B', 'use': '正式纪要的质量优先选项；速度和内存需按本机验证',
     'url': 'https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF'},
]


def config_path() -> Path:
    root = Path(os.environ.get('MEETING_DATA_ROOT', os.environ.get(
        'MEETING_MINUTES_ROOT', Path(__file__).resolve().parents[2])))
    return root / 'config' / 'model-providers.json'


def read_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('invalid_model_settings')
    return value


def validate_endpoint(api: str, source: str) -> str:
    value = str(api).strip().rstrip('/')
    p = urlsplit(value)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('请输入不含密钥、查询参数的完整 API Base URL')
    if source not in {'local', 'cloud'}:
        raise ValueError('请选择本地或云端来源')
    if source == 'local' and p.hostname not in LOOPBACK:
        raise ValueError('本地来源请使用 localhost 或回环地址')
    if source == 'cloud' and (p.scheme != 'https' or p.hostname in LOOPBACK):
        raise ValueError('云端来源需要远程 HTTPS 地址')
    if any(c.isspace() for c in value):
        raise ValueError('API 地址不能包含空白字符')
    return value


def normalize(value: dict, previous: dict) -> dict:
    result = {}
    for role, mapping in FIELDS.items():
        item = value.get(role)
        if not isinstance(item, dict):
            raise ValueError('缺少模型配置')
        if role == 'vision' and not str(item.get('model', '')).strip():
            continue  # Optional vision override; preserve the deployment's environment.
        source = item.get('source', 'local')
        api = validate_endpoint(item.get('api', ''), source)
        if source == 'cloud' and item.get('allow_cloud') is not True:
            raise ValueError('启用云端前请确认会发送所选任务的内容')
        entry = {'source': source, 'api': api, 'allow_cloud': source == 'cloud'}
        for field in mapping:
            if field in {'api', 'api_key'}:
                continue
            text = str(item.get(field, '')).strip()
            if not text or len(text) > 200 or any(ord(c) < 32 for c in text):
                raise ValueError('请输入有效模型 ID')
            entry[field] = text
        key = item.get('api_key', '')
        if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 32 for c in key):
            raise ValueError('密钥格式无效')
        old = previous.get(role, {})
        # A blank field preserves a secret only for the exact original endpoint.
        entry['api_key'] = ('' if item.get('clear_key') else key or
                            (old.get('api_key', '') if old.get('api') == api else ''))
        result[role] = entry
    return result


def save_config(value: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.model-providers-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def public_config(value: dict) -> dict:
    result = {}
    for role, mapping in FIELDS.items():
        item = dict(value.get(role, {}))
        if not item:
            item = {field: os.environ.get(env, '') for field, env in mapping.items()}
            item['api'] = item['api'] or ('http://127.0.0.1:11435/v1' if role == 'text' else 'http://127.0.0.1:11436/v1')
            if role == 'text':
                item['model'] = item['model'] or 'qwen3.6-35b-a3b-operator'
                item['minutes_model'] = item['minutes_model'] or 'qwen3.8-27b-minutes'
            item['source'] = 'local' if urlsplit(item['api']).hostname in LOOPBACK else 'cloud'
            item['allow_cloud'] = os.environ.get('MEETING_ALLOW_REMOTE_LLM' if role == 'text' else 'MEETING_ALLOW_REMOTE_VL') == '1'
        item['key_configured'] = bool(item.pop('api_key', ''))
        result[role] = item
    return result


def apply_saved_config() -> None:
    # Children inherit a stable snapshot; saving settings cannot switch a live job.
    if os.environ.get('MEETING_MODEL_SETTINGS_LOADED') == '1':
        return
    value = read_config()
    prior_vision = (os.environ.get('MEETING_VL_API') or f"http://127.0.0.1:{os.environ.get('MEETING_VL_PORT', '11436')}/v1",
                    os.environ.get('MEETING_VL_MODEL_ID', ''))
    for role, mapping in FIELDS.items():
        if role not in value:
            continue
        item = value[role]
        validate_endpoint(item['api'], item['source'])
        if item['source'] == 'cloud' and item.get('allow_cloud') is not True:
            raise ValueError('cloud_model_not_authorized')
        for field, env in mapping.items():
            os.environ[env] = str(item.get(field, ''))
        os.environ['MEETING_ALLOW_REMOTE_LLM' if role == 'text' else 'MEETING_ALLOW_REMOTE_VL'] = '1' if item['source'] == 'cloud' else '0'
    if 'vision' in value and (value['vision']['api'], value['vision']['model']) != prior_vision:
        import hashlib
        identity = os.environ.get('MEETING_VL_REVISION', '') + '/' + value['vision']['api'] + '/' + value['vision']['model']
        os.environ['MEETING_VL_REVISION'] = 'settings-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
    os.environ['MEETING_MODEL_SETTINGS_LOADED'] = '1'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_request(request, timeout=30, *, role=None):
    """Attach endpoint-scoped credentials; remote redirects never receive secrets."""
    req = urllib.request.Request(request) if isinstance(request, str) else request
    url = req.full_url
    remote = urlsplit(url).hostname not in LOOPBACK
    authorized = False
    for candidate, mapping in FIELDS.items():
        if role and candidate != role:
            continue
        base = os.environ.get(mapping['api'], '').rstrip('/')
        if base and (url == base or url.startswith(base + '/')):
            allowed = os.environ.get('MEETING_ALLOW_REMOTE_LLM' if candidate == 'text' else 'MEETING_ALLOW_REMOTE_VL') == '1'
            if remote and not allowed:
                continue
            authorized = True
            key = os.environ.get(mapping['api_key'], '')
            if key:
                req.add_header('Authorization', 'Bearer ' + key)
            break
    if remote and not authorized:
        raise ValueError('remote_model_not_authorized')
    if remote:
        if urlsplit(url).scheme != 'https':
            raise ValueError('cloud_requires_https')
        if req.data:
            body = json.loads(req.data)
            body.pop('chat_template_kwargs', None)
            body.pop('repeat_penalty', None)
            req.data = json.dumps(body).encode()
        return urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout)
    if req.get_header('Authorization'):
        return urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)
