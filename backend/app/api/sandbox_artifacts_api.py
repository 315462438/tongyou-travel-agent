"""沙箱产物下载（Phase 27c）：深度研究 agent 在 Docker 沙箱里生成的文件（PPT/Word/图表等）。

跟 `/api/img`、handoff-screenshot 同一套信任模型：不鉴权，靠 `batch_key`（服务端生成的
uuid4 hex，不可猜测）做访问控制——这类静态文件本来就无法带 Authorization header 加载
（下载链接/<img> 都一样），项目里已经是既定模式。到期后（`sandbox_artifacts_ttl_min`）
文件被懒清理删除，请求会 404。
"""

import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter(prefix="/api/sandbox-artifacts", tags=["sandbox-artifacts"])

# batch_key 是服务端生成的 uuid4 hex，保持严格白名单
_SAFE_BATCH = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _safe_batch(segment: str) -> bool:
    return bool(segment) and _SAFE_BATCH.match(segment) is not None and ".." not in segment


def _safe_filename(segment: str) -> bool:
    """文件名来自 agent 产物（相对路径 "/" 已在收集时换成 "__"），常含中文——
    不能用 ASCII 白名单（踩坑：`商丘旅游指南.pptx` 被 400 拦下）。改为黑名单：
    禁路径分隔符/父目录/隐藏文件/控制字符，路径穿越另有 abspath 双重保险。
    """
    if not segment or segment in (".", "..") or segment.startswith("."):
        return False
    return not any(c in segment for c in ("/", "\\", "\x00")) and ".." not in segment


@router.get("/{batch_key}/{filename}")
def download_artifact(batch_key: str, filename: str):
    if not _safe_batch(batch_key) or not _safe_filename(filename):
        raise HTTPException(400, "invalid path")

    path = os.path.join(settings.sandbox_artifacts_dir, batch_key, filename)
    # 双重保险：拼出来的真实路径必须仍在产物根目录下
    root = os.path.abspath(settings.sandbox_artifacts_dir)
    resolved = os.path.abspath(path)
    if not resolved.startswith(root + os.sep) or not os.path.isfile(resolved):
        raise HTTPException(404, "artifact not found (可能已过期被清理)")

    return FileResponse(resolved, filename=filename)
