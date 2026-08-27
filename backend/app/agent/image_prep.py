"""图片规格化（Phase 111）：把用户上传的图变成视觉模型收得下的形状。

## 为什么需要这一层

DeepSeek 视觉端对图片有**单边 8192 px** 的硬上限，越界返回 400，而报文写的是
「unsupported image，请确认格式是 webp/png/jpeg/gif」——**格式是对的，越界的是尺寸**。
照着报文去查格式会一路走错（2026-08-27 就是这么被误导的）。

实测判据（同一张 1800×25242 的行程长截图，逐档裁切）：

    1800× 8192   941KB  OK
    1800× 8500   988KB  FAIL
    1024×14360  1207KB  FAIL   ← 宽度压到 1024 也没用，卡的是高度
    1800× 6000   689KB  OK

所以不是字节数（941KB 过、988KB 挂），不是宽高比，是**单边像素**。

## 为什么是切片而不是缩小

25242 → 8192 是 0.32 倍，行程单上的字直接糊掉，抽出来的东西不可信。
长截图只能切，切完按上下顺序一次性交给模型（`parse_image` 本来就收多张）。

## 一条不可让步的约束

**宁可整体缩小一点，也不能只切前几片。** 片数超上限时先等比缩再切，让整页都被覆盖；
「切前 N 片、剩下丢掉」会让模型拿着半份行程自信作答——8 天说成 5 天，而且不报错。
静默的部分读取比读不出来更糟。
"""

from __future__ import annotations

import base64
import io
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# 视觉端能收的编码。传进来的 mime 不在其中时一律重编码成 JPEG。
_SENDABLE = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _to_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def plan_tiles(height: int, max_side: int, max_tiles: int, overlap: int) -> list[tuple[int, int]]:
    """算出切片的 (y, 高度) 列表。纯函数，不碰图像库，好测。

    返回的片**一定覆盖 [0, height) 全部**——调用方据此保证不会静默丢尾部。
    片数不够时由调用方先缩小再进来，这里不负责截断。
    """
    if height <= max_side:
        return [(0, height)]
    step = max_side - overlap
    tiles: list[tuple[int, int]] = []
    y = 0
    while y < height and len(tiles) < max_tiles:
        h = min(max_side, height - y)
        tiles.append((y, h))
        if y + h >= height:
            break
        y += step
    return tiles


def _needed_tiles(height: int, max_side: int, overlap: int) -> int:
    if height <= max_side:
        return 1
    step = max_side - overlap
    n = 1
    covered = max_side
    while covered < height:
        covered += step
        n += 1
    return n


def prepare_for_vision(data: bytes, mime: str) -> list[str]:
    """原始图片字节 → 一组按**上下顺序**排列、每张都在规格内的 data URI。

    返回多于一张即表示这是同一张长图的切片，调用方的 prompt 必须说明这一点，
    否则模型会把它们当成几张互不相干的图。

    规格内的图**原样返回、不重编码**——不做无谓的有损转码。
    解码失败或没装 Pillow 时同样原样返回：退化方向是「和这次改造前一样」，
    而不是凭空少一张图。
    """
    max_side = max(1, settings.vision_max_image_side)
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — 没装就退回改造前的行为
        logger.warning("Pillow 不可用，图片未做规格化（长截图会被视觉端 400 拒绝）")
        return [_to_data_uri(data, mime)]

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            width, height = im.size
            if width <= max_side and height <= max_side and mime in _SENDABLE:
                return [_to_data_uri(data, mime)]

            # 太宽：横向没有「切片」的语义（一行字被竖着切开更难读），等比缩。
            if width > max_side:
                height = max(1, round(height * max_side / width))
                width = max_side
                im = im.resize((width, height), Image.LANCZOS)

            overlap = max(0, min(settings.vision_tile_overlap_px, max_side - 1))
            max_tiles = max(1, settings.vision_max_tiles)
            need = _needed_tiles(height, max_side, overlap)
            if need > max_tiles:
                # 片数不够覆盖整页 → 先等比缩到「刚好切得下」，再切。
                # 绝不改成只切前 max_tiles 片：那是静默丢尾部（见模块 docstring）。
                budget = max_side + (max_tiles - 1) * (max_side - overlap)
                scale = budget / height
                width = max(1, round(width * scale))
                height = budget
                im = im.resize((width, height), Image.LANCZOS)
                logger.info("长图先缩后切: 需 %d 片 > 上限 %d，缩到 %dx%d",
                            need, max_tiles, width, height)

            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            out: list[str] = []
            for y, h in plan_tiles(height, max_side, max_tiles, overlap):
                buf = io.BytesIO()
                im.crop((0, y, width, y + h)).save(
                    buf, format="JPEG", quality=settings.vision_jpeg_quality)
                out.append(_to_data_uri(buf.getvalue(), "image/jpeg"))
            if len(out) > 1:
                logger.info("长截图切成 %d 片送视觉（原 %dx%d）", len(out), width, height)
            return out
    except Exception:  # noqa: BLE001
        logger.warning("图片规格化失败，按原样送", exc_info=True)
        return [_to_data_uri(data, mime)]
