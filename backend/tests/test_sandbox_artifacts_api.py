"""Phase 27c 沙箱产物下载端点单测：路径穿越防护、过期/不存在处理。全离线。"""

import pytest
from fastapi import HTTPException

from app.api import sandbox_artifacts_api as api


@pytest.fixture()
def artifacts_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_artifacts_dir", str(tmp_path))
    return tmp_path


def test_download_existing_artifact(artifacts_dir):
    batch = "abc123"
    (artifacts_dir / batch).mkdir()
    (artifacts_dir / batch / "report.pptx").write_bytes(b"fake pptx")

    resp = api.download_artifact(batch, "report.pptx")
    assert resp.path.endswith("report.pptx")


def test_download_missing_artifact_404(artifacts_dir):
    with pytest.raises(HTTPException) as exc_info:
        api.download_artifact("no-such-batch", "x.pptx")
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("batch,filename", [
    ("../etc", "passwd"),
    ("abc", "../../etc/passwd"),
    ("abc", "..%2f..%2fetc%2fpasswd"),
    ("a/b", "x.txt"),
    ("abc", "a/b.txt"),
])
def test_download_path_traversal_rejected(artifacts_dir, batch, filename):
    with pytest.raises(HTTPException) as exc_info:
        api.download_artifact(batch, filename)
    assert exc_info.value.status_code in (400, 404)


def test_download_expired_artifact_removed_returns_404(artifacts_dir):
    """懒清理已经把过期目录删掉的场景：下载应该 404 而不是报别的错。"""
    with pytest.raises(HTTPException) as exc_info:
        api.download_artifact("expired-batch", "old.pptx")
    assert exc_info.value.status_code == 404


def test_download_chinese_filename(artifacts_dir):
    """agent 产物文件名常含中文（如 slides__output__商丘旅游指南.pptx）——线上踩坑：
    ASCII 白名单把中文文件名 400 拦下，前端显示「网站出问题了」。"""
    batch = "abc123"
    name = "slides__output__商丘旅游指南.pptx"
    (artifacts_dir / batch).mkdir()
    (artifacts_dir / batch / name).write_bytes(b"fake pptx")

    resp = api.download_artifact(batch, name)
    assert resp.path.endswith(".pptx")


def test_download_chinese_filename_over_http(artifacts_dir):
    """走完整 HTTP 栈验证：URL 编码的中文文件名能 200 下载，Content-Disposition 可编码。"""
    from urllib.parse import quote

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(api.router)
    batch = "abc123"
    name = "商丘旅游指南.pptx"
    (artifacts_dir / batch).mkdir()
    (artifacts_dir / batch / name).write_bytes(b"fake pptx")

    client = TestClient(app)
    r = client.get(f"/api/sandbox-artifacts/{batch}/{quote(name)}")
    assert r.status_code == 200
    assert r.content == b"fake pptx"


@pytest.mark.parametrize("filename", [".hidden", ".", "..", "a\\b.txt", "a\x00b"])
def test_download_bad_filenames_rejected(artifacts_dir, filename):
    with pytest.raises(HTTPException) as exc_info:
        api.download_artifact("abc123", filename)
    assert exc_info.value.status_code == 400
