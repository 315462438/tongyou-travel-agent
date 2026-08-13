"""平台内调用链面板（Phase 25）

`GET /api/chat/{cid}/trace?turn_id=` —— 服务端拿 Langfuse pk/sk（不出后端）查本机
Langfuse 公共 API，把该轮 trace 化简成前端可渲染的节点树。需登录 + 会话归属校验。
"""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.chat_api import _owned
from app.api.deps import get_current_user
from app.config import settings
from app.db.models import TravelUser
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["trace"])

_PAYLOAD_LIMIT = 6000  # input/output 截断，防大包拖垮轮询前端（缩进后字符膨胀，配额放宽）
# 小分页拉 observation：深度研究一轮的 observation 带完整 payload 动辄十几 MB，
# 一次 limit=100 会把小内存自托管的 langfuse-web 直接打挂（实测），limit=25 分页安全
_OBS_PAGE_SIZE = 25
_OBS_MAX_PAGES = 8  # 上限 200 条，超长轮次截断（前端树够用）


def _fetch_observations(client: httpx.Client, base: str, trace_id: str) -> list[dict]:
    """按小分页拉全 trace 的 observations（最多 _OBS_MAX_PAGES 页）。"""
    out: list[dict] = []
    for page in range(1, _OBS_MAX_PAGES + 1):
        resp = client.get(
            f"{base}/api/public/observations",
            params={"traceId": trace_id, "limit": _OBS_PAGE_SIZE, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json().get("data") or []
        out.extend(batch)
        if len(batch) < _OBS_PAGE_SIZE:
            break
    else:
        logger.warning("trace %s observations truncated at %d", trace_id, len(out))
    return out


def _clip(value) -> str:
    """payload → 人可读文本：先 2 空格缩进美化、再截断（Phase 32.1）。

    顺序不能反：先截断再美化的话，截断处 JSON 已不合法，前端只能显示单行原文
    （实测输入 payload 全都超 4000 字符，等于永远是乱的单行）。字符串型 payload
    也尝试按 JSON 解析后美化。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value[:_PAYLOAD_LIMIT] + ("…(截断)" if len(value) > _PAYLOAD_LIMIT else "")
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text[:_PAYLOAD_LIMIT] + ("\n…(截断)" if len(text) > _PAYLOAD_LIMIT else "")


def _pick_trace(traces: list[dict], turn_id: str) -> dict | None:
    """按 metadata.turn_id 匹配该轮；匹配不到回退最新一条（trace 列表已按时间倒序）。"""
    if not traces:
        return None
    if turn_id:
        for t in traces:
            meta = t.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except ValueError:
                    meta = {}
            if isinstance(meta, dict) and meta.get("turn_id") == turn_id:
                return t
    return traces[0]


def _dur_ms(o: dict) -> int | None:
    from datetime import datetime

    st, et = o.get("startTime"), o.get("endTime")
    if not st or not et:
        return None
    try:
        s = datetime.fromisoformat(st.replace("Z", "+00:00"))
        e = datetime.fromisoformat(et.replace("Z", "+00:00"))
        return int((e - s).total_seconds() * 1000)
    except ValueError:
        return None


def _simplify(observations: list[dict]) -> list[dict]:
    """观测列表 → 前端节点树（按开始时间排序，带父子关系与耗时）。"""
    nodes = []
    for o in observations:
        usage = o.get("usage") or {}
        nodes.append({
            "id": o.get("id"),
            "parentId": o.get("parentObservationId"),
            "type": o.get("type", ""),
            "name": o.get("name") or "",
            "model": o.get("model") or "",
            "startTime": o.get("startTime") or "",
            "durMs": _dur_ms(o),
            "input": _clip(o.get("input")),
            "output": _clip(o.get("output")),
            "usage": {k: usage.get(k) for k in ("input", "output", "total") if usage.get(k)},
        })
    nodes.sort(key=lambda n: n["startTime"])
    return nodes


@router.get("/{cid}/trace")
def get_turn_trace(
    cid: str, turn_id: str = "",
    db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user),
):
    _owned(db, cid, user)
    from app import observability as obs

    if not obs.enabled():
        return {"enabled": False, "trace": None, "nodes": []}

    auth = (settings.langfuse_public_key, settings.langfuse_secret_key)
    base = settings.langfuse_host.rstrip("/")
    try:
        with httpx.Client(trust_env=False, auth=auth, timeout=8) as client:
            tr = client.get(f"{base}/api/public/traces", params={"sessionId": cid, "limit": 20})
            tr.raise_for_status()
            trace = _pick_trace(tr.json().get("data") or [], turn_id)
            if trace is None:
                return {"enabled": True, "trace": None, "nodes": []}
            nodes = _simplify(_fetch_observations(client, base, trace["id"]))
    except Exception:  # noqa: BLE001
        logger.warning("trace fetch failed for %s", cid, exc_info=True)
        raise HTTPException(502, "调用链服务暂时不可用")

    meta = trace.get("metadata") or {}
    return {
        "enabled": True,
        "trace": {
            "id": trace.get("id"),
            "name": trace.get("name"),
            "latency": trace.get("latency"),
            "timestamp": trace.get("timestamp"),
            "route": meta.get("route") if isinstance(meta, dict) else None,
        },
        "nodes": nodes,
    }
