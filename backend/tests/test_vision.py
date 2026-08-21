"""视觉模型接入（Phase 105）单测。全离线：不调 DeepSeek、不开浏览器。

接它不是为了「更快」——抓页面的时间大头是导航那 30 秒，跟用什么方式读页面无关，
而被替换掉的 `_snapshot_to_text` 恰好是链路里唯一零成本的一步（Phase 96）。
接它是为了**补信息漏洞**：小红书是图片媒介，实测 4 篇样本里 1 篇的 desc 是纯话题标签，
而它的图里有完整的景点+票价+开放时间表。
"""

import asyncio

import pytest

from app.agent import vision
from app.config import settings


# --------------------------------------------------------------------- 调用契约

def test_parse_image_forces_json_object(monkeypatch):
    """**强制 json_object 是性能开关不是格式讲究。**

    实测（6 张真实小红书图，max_tokens 都是 3000）：
        裸 prompt     空正文 2/6   延迟中位 23.7s   out 中位 2622
        json_object   空正文 0/6   延迟中位  7.4s   out 中位  743
    prompt 里已经写了 Phase 101/102 那套思考纪律，它照样烧满预算；json_object 一开
    思考链自己收住。这条要是被人「优化」掉，表现是空白回答 + 延迟三倍。
    """
    from pydantic import BaseModel

    from app.llm.client import LLMClient

    class _S(BaseModel):
        ok: bool = True

    seen = {}

    class _Fake:
        def create(self, **kw):
            seen.update(kw)
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": '{"ok": true}'})(),
                "finish_reason": "stop"})()]})()

    c = LLMClient.__new__(LLMClient)
    c._client = type("X", (), {"chat": type("Y", (), {"completions": _Fake()})()})()
    c.parse_image("看图", _S, images=["https://x/y.jpg"])
    assert seen["response_format"] == {"type": "json_object"}


def test_parse_image_builds_multimodal_parts(monkeypatch):
    from pydantic import BaseModel

    from app.llm.client import LLMClient

    class _S(BaseModel):
        ok: bool = True

    seen = {}

    class _Fake:
        def create(self, **kw):
            seen.update(kw)
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": '{"ok": true}'})(),
                "finish_reason": "stop"})()]})()

    c = LLMClient.__new__(LLMClient)
    c._client = type("X", (), {"chat": type("Y", (), {"completions": _Fake()})()})()
    c.parse_image("看图", _S, images=["https://a/1.jpg", "https://a/2.jpg"])
    parts = seen["messages"][-1]["content"]
    assert parts[0]["type"] == "text"
    assert [p["image_url"]["url"] for p in parts[1:]] == ["https://a/1.jpg", "https://a/2.jpg"]


def test_parse_image_uses_vision_model(monkeypatch):
    from pydantic import BaseModel

    from app.llm.client import LLMClient

    class _S(BaseModel):
        ok: bool = True

    seen = {}

    class _Fake:
        def create(self, **kw):
            seen.update(kw)
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": '{"ok": true}'})(),
                "finish_reason": "stop"})()]})()

    c = LLMClient.__new__(LLMClient)
    c._client = type("X", (), {"chat": type("Y", (), {"completions": _Fake()})()})()
    c.parse_image("看图", _S, images=["u"])
    assert seen["model"] == settings.model_vision


# --------------------------------------------------------------------- desc 薄判定

@pytest.mark.parametrize("desc, thin", [
    ("#杭州[话题]##本地人做的攻略[话题]##杭州旅游[话题]#", True),   # 线上真实样本：零信息
    ("", True),
    ("短短一句", True),
    ("亚庇，一个被阳光、大海和雨林宠爱的地方，慢生活真的太治愈了。" * 6, False),
])
def test_desc_is_thin(desc, thin):
    """只对 desc 信息薄的笔记跑视觉。样本里 3/4 的 desc 本身就是干货，看图纯浪费；
    按这条过滤成本降约 75%，而且精准命中收益点。"""
    assert vision.desc_is_thin(desc) is thin


def test_hashtags_do_not_count_as_content():
    """话题标签必须先剥掉再数长度——满屏 `#xxx[话题]#` 看着很长，信息量是零。"""
    long_tags = "".join(f"#杭州景点{i}[话题]#" for i in range(20))
    assert len(long_tags) > settings.vision_desc_thin_chars
    assert vision.desc_is_thin(long_tags) is True


# --------------------------------------------------------------------- 渲染

def test_render_skips_images_without_text():
    from app.agent.vision import NoteImageInfo

    got = vision.render_note_info([
        NoteImageInfo(has_text=True, places=["西湖"], prices=["免费"]),
        NoteImageInfo(has_text=False, places=["不该出现"]),   # 纯风景照
    ])
    assert "西湖" in got and "不该出现" not in got


def test_render_dedupes_and_returns_empty_when_nothing():
    from app.agent.vision import NoteImageInfo

    got = vision.render_note_info([
        NoteImageInfo(has_text=True, places=["西湖", "西湖"]),
        NoteImageInfo(has_text=True, places=["西湖"]),
    ])
    assert got.count("西湖") == 1
    assert vision.render_note_info([]) == ""
    assert vision.render_note_info([NoteImageInfo(has_text=True)]) == ""


# --------------------------------------------------------------------- 开关与降级

def test_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "vision_enabled", False)
    assert vision.enabled() is False
    assert asyncio.run(vision.extract_note_images(["u"])) == ""
    assert vision.judge_page_image(b"x") is None
    assert vision.describe_user_images(["id"]) == ""


def test_xhs_switch_independent(monkeypatch):
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_xhs_enabled", False)
    assert asyncio.run(vision.extract_note_images(["u"])) == ""


def test_model_failure_is_silent(monkeypatch):
    """exp 模型随时可能变。任何失败一律当作「没有图」，绝不让整轮失败。"""
    class _Boom:
        def parse_image(self, *a, **k):
            raise RuntimeError("model gone")

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _Boom())
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_xhs_enabled", True)
    assert asyncio.run(vision.extract_note_images(["u"])) == ""
    assert vision.judge_page_image(b"jpegbytes") is None


def test_partial_harvest_on_budget(monkeypatch):
    """超预算交回已完成的（照搬 Phase 102）——绝不能让一个 exp 模型拖住终稿。"""
    import time

    from app.agent.vision import NoteImageInfo

    calls = {"n": 0}

    class _Slow:
        def parse_image(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return NoteImageInfo(has_text=True, places=["快的那张"])
            time.sleep(5)  # 慢的那张，超预算
            return NoteImageInfo(has_text=True, places=["慢的那张"])

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _Slow())
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_xhs_enabled", True)
    monkeypatch.setattr(settings, "vision_max_images_per_note", 2)
    got = asyncio.run(vision.extract_note_images(["a", "b"], budget_s=1.0))
    assert "快的那张" in got and "慢的那张" not in got


def test_respects_max_images_per_note(monkeypatch):
    from app.agent.vision import NoteImageInfo

    seen = []

    class _Fake:
        def parse_image(self, prompt, schema, *, images, **k):
            seen.append(images[0])
            return NoteImageInfo(has_text=True, places=[images[0]])

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _Fake())
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_xhs_enabled", True)
    monkeypatch.setattr(settings, "vision_max_images_per_note", 2)
    asyncio.run(vision.extract_note_images(["a", "b", "c", "d"]))
    assert len(seen) == 2
