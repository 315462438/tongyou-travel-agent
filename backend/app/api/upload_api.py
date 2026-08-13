"""图片上传（Phase 74）：客服会话与行程群聊共用。

只存元数据入库，字节落磁盘。安全要点（都不能省）：
- **按文件头探测真实类型**，不信客户端的 content-type（改个 header 就能传任意文件）
- 落盘文件名一律用 uuid，**绝不使用用户提供的文件名**（路径穿越）
- 大小上限在**读取时**累计判断，不能只信 Content-Length（可伪造）
"""

from __future__ import annotations

import pathlib
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import get_current_user
from app.db.models import TravelUpload, TravelUser, _uuid
from app.db.session import get_db

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# 文件头 → mime。只认这四种位图，不收 svg（可内嵌脚本）。
_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
)
_CHUNK = 64 * 1024


def upload_dir() -> pathlib.Path:
    base = settings.upload_dir or str(pathlib.Path(tempfile.gettempdir()) / "travel_uploads")
    path = pathlib.Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def sniff_mime(head: bytes) -> tuple[str, str] | None:
    """按文件头判断真实类型。webp 是 RIFF....WEBP，需要看第 8-12 字节。"""
    for magic, mime, ext in _MAGIC:
        if head.startswith(magic):
            return mime, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def stored_path(upload_id: str, mime: str) -> pathlib.Path:
    ext = {"image/png": ".png", "image/jpeg": ".jpg",
           "image/gif": ".gif", "image/webp": ".webp"}.get(mime, ".bin")
    return upload_dir() / f"{upload_id}{ext}"


@router.post("")
async def upload_image(file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: TravelUser = Depends(get_current_user)):
    head = await file.read(32)
    sniffed = sniff_mime(head)
    if sniffed is None:
        raise HTTPException(400, "只支持 PNG / JPG / GIF / WebP 图片")
    mime, _ext = sniffed

    # id 必须**自己先生成**：`TravelUpload.id` 的 `default=_uuid` 是**列默认值**，
    # SQLAlchemy 在 INSERT 时才求值，此刻 `row.id` 还是 None。
    # 踩过：文件因此全部落成 `None.png`（互相覆盖），而响应里返回的是 commit 后的真 id，
    # 于是每次取图都 404。
    upload_id = _uuid()
    row = TravelUpload(id=upload_id, user_id=user.id, mime=mime, size=0)
    target = stored_path(upload_id, mime)
    total = 0
    try:
        with target.open("wb") as out:
            out.write(head)
            total += len(head)
            while chunk := await file.read(_CHUNK):
                total += len(chunk)
                # 边读边判：Content-Length 是客户端说的，不能当依据
                if total > settings.upload_max_bytes:
                    raise HTTPException(
                        413, f"图片不能超过 {settings.upload_max_bytes // 1024 // 1024} MB")
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise HTTPException(500, "图片保存失败，请重试")

    row.size = total
    db.add(row)
    db.commit()
    return {"id": row.id, "url": f"/api/uploads/{row.id}", "mime": mime, "size": total}


@router.get("/{upload_id}")
def fetch_image(upload_id: str, db: Session = Depends(get_db)):
    """**故意不鉴权**——与 `/api/img`、`/api/staticmap`、handoff-screenshot 同一先例。

    图片是通过 `<img src>` 加载的，浏览器**不会**带 `Authorization` 头，加了鉴权就是
    整片裂图。防护靠 id 是 uuid4（不可枚举）。

    这条必须登记进 tests/test_agent_api_auth.py 的 PUBLIC_ROUTES，否则路由扫描会拦下。
    """
    row = db.get(TravelUpload, upload_id)
    if row is None:
        raise HTTPException(404, "图片不存在")
    path = stored_path(upload_id, row.mime)
    if not path.exists():
        raise HTTPException(404, "图片已失效")
    return FileResponse(path, media_type=row.mime)
