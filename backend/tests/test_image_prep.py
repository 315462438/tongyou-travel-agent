"""Phase 111：长截图规格化 + 切片。

被测的核心事实来自线上实测——视觉端单边上限 8192px，越界返回的 400 却说
「格式不支持」。这里钉住的是**修法的三条不可让步的性质**：
不重编码规格内的图、切片覆盖整页、片序自上而下。
"""

import io

import pytest

from app.agent.image_prep import plan_tiles, prepare_for_vision
from app.config import settings

PIL = pytest.importorskip("PIL.Image")


def _png(w: int, h: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 210, 220)).save(buf, format="PNG")
    return buf.getvalue()


def _decode(uri: str):
    import base64

    from PIL import Image

    head, b64 = uri.split(",", 1)
    return head, Image.open(io.BytesIO(base64.b64decode(b64)))


# ---------- plan_tiles：纯函数，覆盖性是全部重点 ----------

def test_short_image_is_a_single_tile():
    assert plan_tiles(1000, 8000, 4, 80) == [(0, 1000)]


def test_tiles_cover_the_whole_height():
    tiles = plan_tiles(20000, 8000, 4, 80)
    assert tiles[0][0] == 0
    assert tiles[-1][0] + tiles[-1][1] == 20000, "尾部被丢了——这正是最危险的失效"


def test_tiles_overlap_so_a_line_at_the_seam_survives():
    tiles = plan_tiles(20000, 8000, 4, 80)
    for (y0, h0), (y1, _h1) in zip(tiles, tiles[1:]):
        assert y1 < y0 + h0, "相邻片没有重叠，卡在切口的那行字两片都残"


def test_tiles_are_top_to_bottom():
    tiles = plan_tiles(20000, 8000, 4, 80)
    assert [t[0] for t in tiles] == sorted(t[0] for t in tiles)


def test_no_tile_exceeds_the_limit():
    for h in (8001, 12345, 20000, 60000):
        for _y, height in plan_tiles(h, 8000, 8, 80):
            assert height <= 8000


# ---------- prepare_for_vision ----------

def test_in_spec_image_is_returned_byte_identical():
    """规格内的图不重编码：无谓的有损转码既伤质量又费 CPU。"""
    import base64

    raw = _png(800, 600)
    prepared = prepare_for_vision(raw, "image/png")
    uris = prepared.uris
    assert len(uris) == 1
    head, b64 = uris[0].split(",", 1)
    assert head == "data:image/png;base64"
    assert base64.b64decode(b64) == raw


def test_tall_screenshot_is_split(monkeypatch):
    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    monkeypatch.setattr(settings, "vision_max_tiles", 8)
    monkeypatch.setattr(settings, "vision_tile_overlap_px", 20)
    prepared = prepare_for_vision(_png(300, 2000), "image/png")
    uris = prepared.uris
    assert len(uris) > 1
    for uri in uris:
        head, im = _decode(uri)
        assert head == "data:image/jpeg;base64"
        assert max(im.size) <= 500


def test_every_tile_is_within_the_limit_even_when_capped(monkeypatch):
    """片数不够时先缩后切——每片仍必须合规，否则整次调用还是 400。"""
    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    monkeypatch.setattr(settings, "vision_max_tiles", 2)
    monkeypatch.setattr(settings, "vision_tile_overlap_px", 20)
    prepared = prepare_for_vision(_png(300, 9000), "image/png")
    uris = prepared.uris
    assert len(uris) <= 2
    for uri in uris:
        _head, im = _decode(uri)
        assert max(im.size) <= 500


def test_capped_tiling_shrinks_instead_of_dropping_the_tail(monkeypatch):
    """**最重要的一条**：片数不够时缩小整页，绝不能只切前 N 片。

    只切前 N 片会让模型拿着半份行程自信作答（8 天说成 5 天）且不报错。
    判据是覆盖的总高度对得上原图比例：把图做成上白下黑，最后一片必须是黑的。
    """
    from PIL import Image

    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    monkeypatch.setattr(settings, "vision_max_tiles", 2)
    monkeypatch.setattr(settings, "vision_tile_overlap_px", 20)

    im = Image.new("RGB", (300, 9000), (255, 255, 255))
    im.paste(Image.new("RGB", (300, 200), (0, 0, 0)), (0, 8800))  # 页面最底部一条黑带
    buf = io.BytesIO()
    im.save(buf, format="PNG")

    prepared = prepare_for_vision(buf.getvalue(), "image/png")
    uris = prepared.uris
    _head, last = _decode(uris[-1])
    bottom = last.crop((0, last.size[1] - 5, last.size[0], last.size[1])).convert("L")
    assert min(bottom.tobytes()) < 100, "最后一片不是原图底部——尾部被静默丢掉了"


def test_wide_image_is_scaled_not_sliced(monkeypatch):
    """横向没有切片的语义：一行字被竖着切开更难读，等比缩。"""
    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    prepared = prepare_for_vision(_png(2000, 400), "image/png")
    uris = prepared.uris
    assert len(uris) == 1
    _head, im = _decode(uris[0])
    assert im.size[0] <= 500
    assert im.size[1] == pytest.approx(100, abs=2)  # 比例保住


def test_undecodable_bytes_fall_back_to_passthrough():
    """退化方向必须是「和改造前一样」，而不是凭空少一张图。"""
    prepared = prepare_for_vision(b"not an image at all", "image/png")
    uris = prepared.uris
    assert len(uris) == 1
    assert uris[0].startswith("data:image/png;base64,")


def test_missing_pillow_falls_back_to_passthrough(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real(name, *a, **kw)

    raw = _png(300, 40000)          # 先造好图，再断掉 PIL——helper 自己也要用它
    monkeypatch.setattr(builtins, "__import__", fake)
    prepared = prepare_for_vision(raw, "image/png")
    uris = prepared.uris
    assert len(uris) == 1


def test_max_side_default_leaves_headroom_under_the_measured_limit():
    """8192 实测过、8500 实测挂。默认值必须严格小于 8192，不是「等于上限」。"""
    from app.config import Settings

    assert Settings().vision_max_image_side < 8192


# ---------- 降级说明（Phase 112） ----------
# codex 的 `ImageResizeNotice` 那条纪律：链路对输入做了有损处理，处理结果必须自带说明。
# Phase 111 ⑤ 只做到「对用户可见」，这组用例钉的是「对模型可见」的那一半。

def test_in_spec_image_carries_no_notice():
    """**空 notices 这条要靠得住**：每张图都贴一句说明，真正的降级就淹没了。"""
    prepared = prepare_for_vision(_png(800, 600), "image/png")
    assert prepared.notices == []
    assert prepared.degraded is False
    assert prepared.tiled is False


def test_scaled_image_says_so_with_both_sizes(monkeypatch):
    """模型要判断的是「字还清不清楚」——只说「被缩过」没用，必须给出前后尺寸。"""
    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    prepared = prepare_for_vision(_png(2000, 400), "image/png")
    assert prepared.degraded
    joined = " ".join(prepared.notices)
    assert "2000×400" in joined, "没说原始尺寸"
    assert "500×100" in joined, "没说处理后尺寸"


def test_capped_tiling_reports_the_final_size_not_the_intermediate(monkeypatch):
    """先缩宽、再缩高时说明只报**最终**尺寸——中间经过几次 resize 与模型无关。"""
    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    monkeypatch.setattr(settings, "vision_max_tiles", 2)
    monkeypatch.setattr(settings, "vision_tile_overlap_px", 20)
    prepared = prepare_for_vision(_png(2000, 40000), "image/png")
    scale_notes = [n for n in prepared.notices if "缩放" in n]
    assert len(scale_notes) == 1, f"缩放说明应只有一条流水账之外的结论：{prepared.notices}"
    assert "2000×40000" in scale_notes[0]


def test_tiling_tells_the_model_the_parts_are_one_image(monkeypatch):
    """多片必须说明是同一张图的上下段，否则模型当成几张互不相干的图。"""
    monkeypatch.setattr(settings, "vision_max_image_side", 500)
    monkeypatch.setattr(settings, "vision_max_tiles", 8)
    monkeypatch.setattr(settings, "vision_tile_overlap_px", 20)
    prepared = prepare_for_vision(_png(300, 2000), "image/png")
    assert prepared.tiled
    assert any("同一张长图" in n for n in prepared.notices)


def test_fallback_paths_admit_they_may_fail():
    """解码失败仍原样送（退化方向不变），但**要留下一条说明**——
    前面播过「正在看你发的图」，就不能装作无事发生（Phase 111 ⑤）。"""
    prepared = prepare_for_vision(b"not an image at all", "image/png")
    assert prepared.uris and prepared.degraded


def test_missing_pillow_admits_it_did_not_normalize(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real(name, *a, **kw)

    raw = _png(300, 40000)
    monkeypatch.setattr(builtins, "__import__", fake)
    prepared = prepare_for_vision(raw, "image/png")
    assert prepared.degraded, "没装 Pillow 时超大图必然读不出来，不能静默"
