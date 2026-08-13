"""Phase 27/27b 用户上传技能单测：校验、增删查、按用户隔离、zip 多文件包。sqlite 内存库，全部离线。"""

import io
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.skill_validation import SkillValidationError, parse_and_validate, parse_and_validate_zip
from app.api import skill_api
from app.db.models import Base, TravelUser, TravelUserSkill, _uuid

VALID_SKILL = """---
name: my-packing-list
description: 打包清单方法论
---

# 打包清单
先列必需品再列可选品。
"""


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def alice(db):
    user = TravelUser(id=_uuid(), username="alice", password_hash="x")
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def bob(db):
    user = TravelUser(id=_uuid(), username="bob", password_hash="x")
    db.add(user)
    db.commit()
    return user


# ---------- 校验 ----------

def test_parse_and_validate_ok():
    name, desc = parse_and_validate(VALID_SKILL)
    assert name == "my-packing-list"
    assert desc == "打包清单方法论"


def test_parse_and_validate_missing_frontmatter():
    with pytest.raises(SkillValidationError, match="frontmatter"):
        parse_and_validate("# 没有 frontmatter 的技能\n正文")


def test_parse_and_validate_bad_name():
    bad = VALID_SKILL.replace("my-packing-list", "My_Bad_Name")
    with pytest.raises(SkillValidationError, match="技能名不合法"):
        parse_and_validate(bad)


def test_parse_and_validate_missing_description():
    bad = "---\nname: foo\n---\n\nbody"
    with pytest.raises(SkillValidationError):
        parse_and_validate(bad)


def test_parse_and_validate_too_large(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "user_skill_max_bytes", 10)
    with pytest.raises(SkillValidationError, match="大小限制"):
        parse_and_validate(VALID_SKILL)


# ---------- API：上传 / 列表 / 删除 / 按用户隔离 ----------

def test_upload_then_list(db, alice):
    out = skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    assert out["name"] == "my-packing-list"

    listed = skill_api.list_skills(db, alice)
    assert len(listed) == 1
    assert listed[0]["name"] == "my-packing-list"
    assert listed[0]["content"] == VALID_SKILL


def test_upload_same_name_upserts(db, alice):
    skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    updated = VALID_SKILL.replace("打包清单方法论", "打包清单方法论 v2")
    skill_api.upload_skill(skill_api.SkillUploadRequest(content=updated), db, alice)

    listed = skill_api.list_skills(db, alice)
    assert len(listed) == 1  # 覆盖而不是新增一条
    assert listed[0]["description"] == "打包清单方法论 v2"


def test_upload_invalid_content_rejected(db, alice):
    with pytest.raises(HTTPException) as exc_info:
        skill_api.upload_skill(skill_api.SkillUploadRequest(content="不是合法技能"), db, alice)
    assert exc_info.value.status_code == 400


def test_upload_disabled_by_settings(db, alice, monkeypatch):
    monkeypatch.setattr(skill_api.settings, "user_skills_enabled", False)
    with pytest.raises(HTTPException) as exc_info:
        skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    assert exc_info.value.status_code == 403


def test_list_is_scoped_to_owner(db, alice, bob):
    skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    assert skill_api.list_skills(db, alice) != []
    assert skill_api.list_skills(db, bob) == []


def test_delete_own_skill(db, alice):
    out = skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    result = skill_api.delete_skill(out["id"], db, alice)
    assert result["status"] == "deleted"
    assert skill_api.list_skills(db, alice) == []


def test_delete_others_skill_404(db, alice, bob):
    out = skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    with pytest.raises(HTTPException) as exc_info:
        skill_api.delete_skill(out["id"], db, bob)
    assert exc_info.value.status_code == 404
    # bob 的越权删除没有影响 alice 的技能
    assert len(skill_api.list_skills(db, alice)) == 1


def test_delete_nonexistent_404(db, alice):
    with pytest.raises(HTTPException) as exc_info:
        skill_api.delete_skill("no-such-id", db, alice)
    assert exc_info.value.status_code == 404


# ---------- skills_loader._load_user_skill_files：查库转虚拟路径 ----------

def test_load_user_skill_files_from_db(db, alice, monkeypatch):
    from app.agent import skills_loader

    skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    monkeypatch.setattr("app.db.session.get_session", lambda: db)

    files = skills_loader._load_user_skill_files(alice.id)
    assert files == {"/user/my-packing-list/SKILL.md": VALID_SKILL}


def test_load_user_skill_files_db_error_returns_empty(monkeypatch):
    from app.agent import skills_loader

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.session.get_session", boom)
    assert skills_loader._load_user_skill_files("someone") == {}


# ---------- zip 多文件技能包校验（Phase 27b） ----------

def test_parse_and_validate_zip_ok():
    data = _make_zip({
        "SKILL.md": VALID_SKILL,
        "references/checklist.md": "详细清单正文",
    })
    name, desc, files = parse_and_validate_zip(data)
    assert name == "my-packing-list"
    assert desc == "打包清单方法论"
    assert files == {"SKILL.md": VALID_SKILL, "references/checklist.md": "详细清单正文"}


def test_parse_and_validate_zip_strips_wrapping_folder():
    """常见习惯：压缩了外层文件夹（如 my-packing-list/SKILL.md），自动剥掉这层前缀。"""
    data = _make_zip({
        "my-packing-list/SKILL.md": VALID_SKILL,
        "my-packing-list/scripts/helper.py": "print('hi')",
    })
    name, _desc, files = parse_and_validate_zip(data)
    assert name == "my-packing-list"
    assert set(files.keys()) == {"SKILL.md", "scripts/helper.py"}


def test_parse_and_validate_zip_not_a_zip():
    with pytest.raises(SkillValidationError, match="不是合法的 zip"):
        parse_and_validate_zip(b"not a zip file at all")


def test_parse_and_validate_zip_missing_skill_md():
    data = _make_zip({"references/notes.md": "只有参考文件，没有 SKILL.md"})
    with pytest.raises(SkillValidationError, match="SKILL.md"):
        parse_and_validate_zip(data)


def test_parse_and_validate_zip_path_traversal_rejected():
    """zip-slip：恶意路径最终会被拼成 /user/{name}/{relpath} 虚拟路径，
    ".." 逃逸可能落到 /main/ 之类内置技能的命名空间——必须在解析阶段就拒绝。
    """
    data = _make_zip({
        "SKILL.md": VALID_SKILL,
        "../../main/trip-comparison/SKILL.md": "冒充内置技能",
    })
    with pytest.raises(SkillValidationError, match="不合法"):
        parse_and_validate_zip(data)


def test_parse_and_validate_zip_absolute_path_rejected():
    data = _make_zip({"SKILL.md": VALID_SKILL, "/etc/passwd": "x"})
    with pytest.raises(SkillValidationError, match="不合法"):
        parse_and_validate_zip(data)


def test_parse_and_validate_zip_binary_file_rejected():
    data = _make_zip({"SKILL.md": VALID_SKILL})
    # 追加一个非 UTF-8 的二进制文件
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.writestr("assets/logo.png", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x00\x00")
    with pytest.raises(SkillValidationError, match="UTF-8"):
        parse_and_validate_zip(buf.getvalue())


def test_parse_and_validate_zip_too_many_files(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "user_skill_max_zip_files", 2)
    data = _make_zip({"SKILL.md": VALID_SKILL, "a.md": "a", "b.md": "b"})
    with pytest.raises(SkillValidationError, match="文件数超出上限"):
        parse_and_validate_zip(data)


def test_parse_and_validate_zip_too_large(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "user_skill_max_zip_bytes", 10)
    data = _make_zip({"SKILL.md": VALID_SKILL})
    with pytest.raises(SkillValidationError, match="总大小超出上限"):
        parse_and_validate_zip(data)


def test_parse_and_validate_zip_empty():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    with pytest.raises(SkillValidationError, match="没有文件"):
        parse_and_validate_zip(buf.getvalue())


# ---------- API：zip 上传端点 ----------

def test_handle_zip_upload_then_list(db, alice):
    data = _make_zip({
        "SKILL.md": VALID_SKILL,
        "references/checklist.md": "详细清单",
    })
    out = skill_api._handle_zip_upload(data, db, alice)
    assert out["name"] == "my-packing-list"
    assert set(out["files"]) == {"SKILL.md", "references/checklist.md"}

    listed = skill_api.list_skills(db, alice)
    assert len(listed) == 1
    assert set(listed[0]["files"]) == {"SKILL.md", "references/checklist.md"}


def test_handle_zip_upload_disabled_by_settings(db, alice, monkeypatch):
    monkeypatch.setattr(skill_api.settings, "user_skills_enabled", False)
    data = _make_zip({"SKILL.md": VALID_SKILL})
    with pytest.raises(HTTPException) as exc_info:
        skill_api._handle_zip_upload(data, db, alice)
    assert exc_info.value.status_code == 403


def test_handle_zip_upload_too_large_413_like(db, alice, monkeypatch):
    monkeypatch.setattr(skill_api.settings, "user_skill_max_zip_bytes", 10)
    data = _make_zip({"SKILL.md": VALID_SKILL})
    with pytest.raises(HTTPException) as exc_info:
        skill_api._handle_zip_upload(data, db, alice)
    assert exc_info.value.status_code == 400


def test_handle_zip_upload_invalid_zip_rejected(db, alice):
    with pytest.raises(HTTPException) as exc_info:
        skill_api._handle_zip_upload(b"garbage", db, alice)
    assert exc_info.value.status_code == 400


def test_zip_upload_and_text_upload_interop_same_name(db, alice):
    """同名技能：先 zip 上传带附带文件，再用纯文本覆盖——files 应该收窄回只有 SKILL.md
    （覆盖是整体替换，不是合并），且 list 能看到这个变化。
    """
    zip_data = _make_zip({"SKILL.md": VALID_SKILL, "references/checklist.md": "详细清单"})
    skill_api._handle_zip_upload(zip_data, db, alice)

    skill_api.upload_skill(skill_api.SkillUploadRequest(content=VALID_SKILL), db, alice)
    listed = skill_api.list_skills(db, alice)
    assert len(listed) == 1
    assert listed[0]["files"] == ["SKILL.md"]


# ---------- skills_loader：多文件技能展开成多个虚拟路径 ----------

def test_load_user_skill_files_multi_file_from_zip(db, alice, monkeypatch):
    from app.agent import skills_loader

    data = _make_zip({"SKILL.md": VALID_SKILL, "references/checklist.md": "详细清单"})
    skill_api._handle_zip_upload(data, db, alice)
    monkeypatch.setattr("app.db.session.get_session", lambda: db)

    files = skills_loader._load_user_skill_files(alice.id)
    assert files == {
        "/user/my-packing-list/SKILL.md": VALID_SKILL,
        "/user/my-packing-list/references/checklist.md": "详细清单",
    }
