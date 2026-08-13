"""Phase 74：角色管理 / 邀请码 / 公告 / 图片上传。"""

import io

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import admin_api, upload_api
from app.config import settings
from app.db.models import Base, TravelInviteCode, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db, name, admin=False):
    u = TravelUser(username=name, password_hash="x", is_admin=admin)
    db.add(u)
    db.commit()
    return u


# ---------- 角色 ----------

def test_promote_user_to_admin(db):
    root, alice = _user(db, "root", True), _user(db, "alice")
    out = admin_api.set_role(alice.id, admin_api.RoleRequest(is_admin=True), me=root, db=db)
    assert out["is_admin"] is True


def test_demote_admin(db):
    root, other = _user(db, "root", True), _user(db, "other", True)
    out = admin_api.set_role(other.id, admin_api.RoleRequest(is_admin=False), me=root, db=db)
    assert out["is_admin"] is False


def test_cannot_change_own_role(db):
    """允许改自己 = 可以一键把自己锁在后台外面，且无法自助恢复。"""
    root = _user(db, "root", True)
    with pytest.raises(HTTPException) as e:
        admin_api.set_role(root.id, admin_api.RoleRequest(is_admin=False), me=root, db=db)
    assert e.value.status_code == 400


def test_cannot_demote_last_admin(db):
    """只剩一个管理员时不许降级——降完系统就没有管理员了，没有恢复路径。"""
    root, only = _user(db, "root", True), _user(db, "only", True)
    admin_api.set_role(root.id, admin_api.RoleRequest(is_admin=False), me=only, db=db)
    with pytest.raises(HTTPException) as e:
        admin_api.set_role(only.id, admin_api.RoleRequest(is_admin=False), me=root, db=db)
    assert "最后一个管理员" in e.value.detail


def test_set_role_unknown_user_404(db):
    root = _user(db, "root", True)
    with pytest.raises(HTTPException) as e:
        admin_api.set_role("nope", admin_api.RoleRequest(is_admin=True), me=root, db=db)
    assert e.value.status_code == 404


# ---------- 邀请码 ----------

def test_create_invite_defaults_to_five_uses(db):
    root = _user(db, "root", True)
    out = admin_api.create_invite(admin_api.CreateInvite(), me=root, db=db)
    assert out["max_uses"] == settings.invite_code_default_uses == 5
    assert out["usable"] is True


def test_invite_code_avoids_ambiguous_characters(db):
    """邀请码常被手抄/口述，0O1Il 必须排除。"""
    root = _user(db, "root", True)
    for _ in range(15):
        code = admin_api.create_invite(admin_api.CreateInvite(), me=root, db=db)["code"]
        assert not (set(code) & set("O0I1L"))


def test_invite_consumes_quota_and_expires_after_limit(db):
    root = _user(db, "root", True)
    code = admin_api.create_invite(admin_api.CreateInvite(max_uses=2), me=root, db=db)["code"]
    assert admin_api.consume_invite_code(db, code) is True
    assert admin_api.consume_invite_code(db, code) is True
    assert admin_api.consume_invite_code(db, code) is False, "用满后必须失效"


def test_invite_consume_is_case_insensitive(db):
    root = _user(db, "root", True)
    code = admin_api.create_invite(admin_api.CreateInvite(), me=root, db=db)["code"]
    assert admin_api.consume_invite_code(db, code.lower()) is True


def test_deactivated_invite_stops_working_but_row_is_kept(db):
    root = _user(db, "root", True)
    code = admin_api.create_invite(admin_api.CreateInvite(), me=root, db=db)["code"]
    admin_api.deactivate_invite(code, db=db)
    assert admin_api.consume_invite_code(db, code) is False
    assert db.get(TravelInviteCode, code) is not None, "停用应保留审计痕迹，不删行"


def test_unknown_invite_rejected(db):
    assert admin_api.consume_invite_code(db, "AAAA-BBBB") is False
    assert admin_api.consume_invite_code(db, "") is False


def test_invite_quota_is_not_oversold_under_concurrency(db):
    """守住「先读后写」的竞态：占位必须是带条件的原子 UPDATE。

    这里直接连打 N 次，断言成功次数**恰好**等于配额——若实现改回
    先 SELECT 再 +1，用满后仍会有额外成功。
    """
    root = _user(db, "root", True)
    code = admin_api.create_invite(admin_api.CreateInvite(max_uses=3), me=root, db=db)["code"]
    ok = sum(1 for _ in range(10) if admin_api.consume_invite_code(db, code))
    assert ok == 3
    assert db.get(TravelInviteCode, code).used_count == 3


def test_invite_required_only_when_configured(db):
    """没有任何码、也没配 .env → 开放注册（本地开发行为不变）。"""
    assert admin_api.invite_required(db) is False
    root = _user(db, "root", True)
    admin_api.create_invite(admin_api.CreateInvite(), me=root, db=db)
    assert admin_api.invite_required(db) is True


# ---------- 公告 ----------

def test_publish_and_unread_for_each_user(db):
    root, alice = _user(db, "root", True), _user(db, "alice")
    admin_api.publish(admin_api.CreateAnnouncement(title="上新", content="海报功能上线"),
                      me=root, db=db)
    assert admin_api.unread_count(db=db, user=alice)["unread"] == 1


def test_mark_read_clears_unread(db):
    root, alice = _user(db, "root", True), _user(db, "alice")
    ann = admin_api.publish(admin_api.CreateAnnouncement(title="t", content="c"),
                            me=root, db=db)
    admin_api.mark_read(ann["id"], db=db, user=alice)
    assert admin_api.unread_count(db=db, user=alice)["unread"] == 0


def test_read_is_per_user(db):
    root, alice, bob = _user(db, "root", True), _user(db, "alice"), _user(db, "bob")
    ann = admin_api.publish(admin_api.CreateAnnouncement(title="t", content="c"),
                            me=root, db=db)
    admin_api.mark_read(ann["id"], db=db, user=alice)
    assert admin_api.unread_count(db=db, user=bob)["unread"] == 1


def test_mark_read_is_idempotent(db):
    """复合主键下重复标记不能炸（前端可能连点/重放）。"""
    root, alice = _user(db, "root", True), _user(db, "alice")
    ann = admin_api.publish(admin_api.CreateAnnouncement(title="t", content="c"),
                            me=root, db=db)
    admin_api.mark_read(ann["id"], db=db, user=alice)
    admin_api.mark_read(ann["id"], db=db, user=alice)
    assert admin_api.unread_count(db=db, user=alice)["unread"] == 0


def test_withdraw_removes_announcement_and_its_read_marks(db):
    root, alice = _user(db, "root", True), _user(db, "alice")
    ann = admin_api.publish(admin_api.CreateAnnouncement(title="t", content="c"),
                            me=root, db=db)
    admin_api.mark_read(ann["id"], db=db, user=alice)
    admin_api.withdraw(ann["id"], db=db)
    # 撤下后未读不能变成负数（已读行若残留，total-read 会算成 -1）
    assert admin_api.unread_count(db=db, user=alice)["unread"] == 0
    assert admin_api.my_announcements(db=db, user=alice)["announcements"] == []


def test_empty_announcement_rejected(db):
    root = _user(db, "root", True)
    with pytest.raises(HTTPException) as e:
        admin_api.publish(admin_api.CreateAnnouncement(title=" ", content="c"), me=root, db=db)
    assert e.value.status_code == 400


# ---------- 上传：类型探测 ----------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 28
GIF = b"GIF89a" + b"\x00" * 26
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20


def test_sniff_accepts_real_images():
    assert upload_api.sniff_mime(PNG) == ("image/png", ".png")
    assert upload_api.sniff_mime(JPG) == ("image/jpeg", ".jpg")
    assert upload_api.sniff_mime(GIF) == ("image/gif", ".gif")
    assert upload_api.sniff_mime(WEBP) == ("image/webp", ".webp")


def test_sniff_rejects_non_images_regardless_of_claimed_type():
    """不信客户端的 content-type：改个 header 就能传任意文件。"""
    assert upload_api.sniff_mime(b"<?php system($_GET[0]); ?>") is None
    assert upload_api.sniff_mime(b"PK\x03\x04" + b"\x00" * 20) is None  # zip
    assert upload_api.sniff_mime(b"") is None


def test_sniff_rejects_svg_because_it_can_carry_script():
    assert upload_api.sniff_mime(b"<svg xmlns='http://www.w3.org/2000/svg'>") is None


def test_stored_path_never_uses_client_filename():
    """落盘文件名一律 uuid，杜绝路径穿越。"""
    p = upload_api.stored_path("abc123", "image/png")
    assert p.name == "abc123.png"
    evil = upload_api.stored_path("../../etc/passwd", "image/png")
    assert ".." not in evil.name


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(db, monkeypatch):
    """大小必须边读边判——Content-Length 是客户端说的。"""
    from fastapi import UploadFile

    monkeypatch.setattr(settings, "upload_max_bytes", 1024)
    u = _user(db, "alice")
    big = io.BytesIO(PNG + b"\x00" * 4096)
    with pytest.raises(HTTPException) as e:
        await upload_api.upload_image(
            file=UploadFile(filename="a.png", file=big), db=db, user=u)
    assert e.value.status_code == 413


@pytest.mark.asyncio
async def test_upload_file_lands_at_the_returned_id(db, tmp_path, monkeypatch):
    """回归：落盘路径必须与返回的 id 一致。

    踩过的坑——`TravelUpload.id` 的 `default=_uuid` 是**列默认值**，INSERT 时才求值，
    构造后 `row.id` 仍是 None。用它算路径 → 所有人的图都写成同一个 `None.png`
    互相覆盖，而响应返回的是 commit 后的真 id，于是每次取图都 404。
    """
    from fastapi import UploadFile

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    u = _user(db, "alice")
    out = await upload_api.upload_image(
        file=UploadFile(filename="a.png", file=io.BytesIO(PNG)), db=db, user=u)

    assert out["id"] and out["id"] != "None"
    stored = upload_api.stored_path(out["id"], out["mime"])
    assert stored.exists(), f"落盘路径与返回 id 不一致：{list(tmp_path.iterdir())}"
    assert not (tmp_path / "None.png").exists()


@pytest.mark.asyncio
async def test_two_uploads_do_not_overwrite_each_other(db, tmp_path, monkeypatch):
    from fastapi import UploadFile

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    u = _user(db, "alice")
    a = await upload_api.upload_image(
        file=UploadFile(filename="a.png", file=io.BytesIO(PNG)), db=db, user=u)
    b = await upload_api.upload_image(
        file=UploadFile(filename="b.gif", file=io.BytesIO(GIF)), db=db, user=u)
    assert a["id"] != b["id"]
    assert len(list(tmp_path.iterdir())) == 2, "两次上传不能落到同一个文件"
