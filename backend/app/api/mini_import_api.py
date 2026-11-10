"""Private mini-program import jobs; request content expires and is never written to DB."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field
from app.config import settings
from app.services.mini_import import ImportInput, extract

router = APIRouter(prefix='/api/mini-import', tags=['mini-import'])
_lock = threading.Lock()
_jobs = {}
_counts = {}
_logins = {}
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='mini-import')
_slots = threading.BoundedSemaphore(2)
TTL = 600


def enabled():
    if not settings.mini_import_enabled or not settings.mini_import_app_secret or len(settings.mini_import_token_secret) < 32:
        raise HTTPException(503, '导入服务尚未配置完成，请稍后再试')


def _mac(value):
    return hmac.new(settings.mini_import_token_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def issue_token(openid):
    body = base64.urlsafe_b64encode(json.dumps({'sub': _mac('openid:' + openid), 'exp': int(time.time()) + 1800, 'aud': 'mini-import'}).encode()).decode().rstrip('=')
    return body + '.' + _mac(body)


def subject(authorization: str = Header(default='')):
    enabled()
    try:
        scheme, token = authorization.split(' ', 1)
        body, signature = token.split('.')
        if scheme.lower() != 'bearer' or not hmac.compare_digest(signature, _mac(body)):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        if data['aud'] != 'mini-import' or data['exp'] <= time.time() or not isinstance(data['sub'], str) or len(data['sub']) != 64:
            raise ValueError()
        return data['sub']
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, '微信登录已过期，请重新识别') from None


class Login(BaseModel):
    code: str = Field(min_length=1, max_length=256)


@router.post('/session')
def session(body: Login, request: Request):
    enabled()
    now = time.time()
    ip = request.client.host if request.client else 'unknown'
    with _lock:
        for key in list(_logins):
            if _logins[key][0] < now - 60:
                del _logins[key]
        start, count = _logins.get(ip, (now, 0))
        if count >= 30:
            raise HTTPException(429, '登录请求过于频繁，请稍后再试')
        _logins[ip] = (start, count + 1)
    query = urllib.parse.urlencode({'appid': settings.mini_import_app_id, 'secret': settings.mini_import_app_secret,
                                    'js_code': body.code, 'grant_type': 'authorization_code'})
    try:
        # urllib does not emit httpx INFO URL logs containing the AppSecret.
        with urllib.request.urlopen('https://api.weixin.qq.com/sns/jscode2session?' + query, timeout=10) as response:
            data = json.load(response)
        if not data.get('openid') or data.get('errcode'):
            raise ValueError()
    except Exception:
        raise HTTPException(401, '微信登录校验失败，请重试') from None
    return {'token': issue_token(data['openid'])}


def _prune(now):
    for key in list(_jobs):
        if _jobs[key]['expires'] < now:
            del _jobs[key]
    today = int(now // 86400)
    for key in list(_counts):
        if key[0] != today:
            del _counts[key]


def _expire(job_id):
    with _lock:
        _jobs.pop(job_id, None)


def _run(job_id, body):
    try:
        result = extract(body)
        outcome = {'status': 'done', 'result': result}
    except Exception:
        # Do not log exceptions: SDK errors/validation messages may contain source content.
        outcome = {'status': 'failed', 'error': '内容识别未完成，请缩短内容后重试；原行程未作修改。'}
    finally:
        _slots.release()
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(outcome)


@router.post('/jobs', status_code=202)
def start(body: ImportInput, owner: str = Depends(subject)):
    now = time.time()
    with _lock:
        _prune(now)
        key = (int(now // 86400), owner)
        if _counts.get(key, 0) >= settings.mini_import_daily_limit:
            raise HTTPException(429, '今天的导入识别次数已用完，请明天再试')
        if len(_jobs) >= 32 or not _slots.acquire(blocking=False):
            raise HTTPException(429, '导入服务正忙，请稍后再试')
        job_id = secrets.token_urlsafe(24)
        _jobs[job_id] = {'owner': owner, 'expires': now + TTL, 'status': 'processing'}
        _counts[key] = _counts.get(key, 0) + 1
    try:
        timer = threading.Timer(TTL, _expire, args=(job_id,))
        timer.daemon = True
        timer.start()
        _executor.submit(_run, job_id, body)
    except Exception:
        with _lock:
            _jobs.pop(job_id, None)
            _counts[key] -= 1
        _slots.release()
        raise HTTPException(503, '导入服务暂不可用') from None
    return {'id': job_id, 'status': 'processing'}


def _owned(job_id, owner):
    _prune(time.time())
    job = _jobs.get(job_id)
    if not job or job['owner'] != owner:
        raise HTTPException(404, '导入任务已过期或不存在，请重新识别')
    return job


@router.get('/jobs/{job_id}')
def poll(job_id: str, owner: str = Depends(subject)):
    with _lock:
        job = _owned(job_id, owner)
        return {k: v for k, v in job.items() if k not in ('owner', 'expires')}


@router.delete('/jobs/{job_id}')
def discard(job_id: str, owner: str = Depends(subject)):
    with _lock:
        _owned(job_id, owner)
        del _jobs[job_id]
    return {'status': 'deleted'}


class MiniImportBodyLimit:
    """Bound request bytes before JSON decoding; only applies to the new endpoints."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/mini-import/'):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > 160000:
                return await JSONResponse({'detail': '导入内容过长，请拆分后重试'}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body'):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)
