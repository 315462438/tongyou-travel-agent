import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.skill_validation import SkillValidationError, parse_and_validate, parse_and_validate_zip
from app.api.deps import get_current_user
from app.config import settings
from app.db.models import TravelUser, TravelUserSkill
from app.db.session import get_db

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillUploadRequest(BaseModel):
    content: str


def _serialize(s: TravelUserSkill) -> dict:
    files = json.loads(s.files_json) if s.files_json else {"SKILL.md": s.content}
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "content": s.content,
        "files": sorted(files.keys()),
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _upsert_skill(
    db: Session, user: TravelUser, name: str, description: str, files: dict[str, str],
) -> TravelUserSkill:
    content = files["SKILL.md"]
    files_json = json.dumps(files, ensure_ascii=False)

    existing = db.execute(
        select(TravelUserSkill).where(
            TravelUserSkill.user_id == user.id, TravelUserSkill.name == name,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.description = description
        existing.content = content
        existing.files_json = files_json
        db.commit()
        db.refresh(existing)
        return existing

    row = TravelUserSkill(
        user_id=user.id, name=name, description=description,
        content=content, files_json=files_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("")
def list_skills(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    rows = db.execute(
        select(TravelUserSkill)
        .where(TravelUserSkill.user_id == user.id)
        .order_by(TravelUserSkill.updated_at.desc())
    ).scalars().all()
    return [_serialize(s) for s in rows]


@router.post("")
def upload_skill(
    body: SkillUploadRequest,
    db: Session = Depends(get_db),
    user: TravelUser = Depends(get_current_user),
):
    if not settings.user_skills_enabled:
        raise HTTPException(403, "用户上传技能功能未开启")

    try:
        name, description = parse_and_validate(body.content)
    except SkillValidationError as e:
        raise HTTPException(400, str(e)) from e

    row = _upsert_skill(db, user, name, description, {"SKILL.md": body.content})
    return _serialize(row)


def _handle_zip_upload(data: bytes, db: Session, user: TravelUser) -> dict:
    """zip 上传的核心逻辑，拆出来是为了测试时不用构造 `UploadFile`，直接传 bytes。"""
    if not settings.user_skills_enabled:
        raise HTTPException(403, "用户上传技能功能未开启")

    if len(data) > settings.user_skill_max_zip_bytes:
        raise HTTPException(400, f"上传文件超出大小限制（上限 {settings.user_skill_max_zip_bytes} 字节）")

    try:
        name, description, files = parse_and_validate_zip(data)
    except SkillValidationError as e:
        raise HTTPException(400, str(e)) from e

    row = _upsert_skill(db, user, name, description, files)
    return _serialize(row)


@router.post("/upload")
async def upload_skill_zip(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: TravelUser = Depends(get_current_user),
):
    """上传 zip 多文件技能包（SKILL.md + 参考文件/脚本）。Phase 27b。

    只存文本内容，不提供执行能力——脚本文件能被 agent `read_file` 当参考读，
    但不会被运行（除非另外开了沙箱 execute）。
    """
    data = await file.read()
    return _handle_zip_upload(data, db, user)


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    row = db.get(TravelUserSkill, skill_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "skill not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}
