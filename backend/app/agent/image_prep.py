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

## 降级必须能被下游看见（Phase 112）

本模块会在两处**有损处理**输入：太宽时等比缩、片数不够时先缩后切。此前这两处只写
`logger.info`，返回值里只有 data URI——**模型不知道自己在看一张被压过的图**，会照样自信
地念出缩糊了的价格和日期。现在返回 `PreparedImages`，把「原始尺寸 → 处理后尺寸 + 为什么」
一并交出去，由调用方并进 prompt。

一般化：**凡链路对输入做了有损处理，处理结果必须自带一段说明，与内容一起进模型。**
Phase 111 ⑤ 立的「失败必须可见」只做到了对用户可见，这条补上对模型可见的那一半。
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# 视觉端能收的编码。传进来的 mime 不在其中时一律重编码成 JPEG。
_SENDABLE = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@dataclass(frozen=True)
class PreparedImages:
    """规格化产物：既有图，也有「这张图被我们怎么动过」。

    `notices` 是给**模型**看的人话（调用方并进 prompt），不是日志。空列表表示原样通过——
    这一点要靠得住：规格内的图必须逐字节原样返回且不产生 notice，否则每张图都会被贴上
    一句无意义的说明，真正的降级就淹没了。
    """

    uris: list[str]
    notices: list[str] = field(default_factory=list)
    tiled: bool = False

    @property
    def degraded(self) -> bool:
        return bool(self.notices)


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


def prepare_for_vision(data: bytes, mime: str) -> PreparedImages:
    """原始图片字节 → 一组按**上下顺序**排列、每张都在规格内的 data URI + 降级说明。

    `uris` 多于一张即表示这是同一张长图的切片，调用方的 prompt 必须说明这一点，
    否则模型会把它们当成几张互不相干的图。

    规格内的图**原样返回、不重编码**——不做无谓的有损转码，且此时 `notices` 必须为空。
    解码失败或没装 Pillow 时同样原样返回：退化方向是「和这次改造前一样」，
    而不是凭空少一张图；但**要留下一条说明**，因为那种情况下图很可能读不出来
    （Phase 111 ⑤：前面播过「正在看你发的图」，就不能装作无事发生）。
    """
    max_side = max(1, settings.vision_max_image_side)
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — 没装就退回改造前的行为
        logger.warning("Pillow 不可用，图片未做规格化（长截图会被视觉端 400 拒绝）")
        return PreparedImages(
            uris=[_to_data_uri(data, mime)],
            notices=["图片未做尺寸规格化（服务端缺少图像库），超大图可能读不出来"],
        )

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            src_w, src_h = im.size
            width, height = src_w, src_h
            notices: list[str] = []
            if width <= max_side and height <= max_side and mime in _SENDABLE:
                return PreparedImages(uris=[_to_data_uri(data, mime)])

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

            # ⚠️ 说明基于**最终**尺寸与原始尺寸的对比，不是逐次 resize 的流水账——
            # 模型要判断的是「字还清不清楚」，中间经过几次缩放跟它无关。
            if (width, height) != (src_w, src_h):
                notices.append(
                    f"原图 {src_w}×{src_h}，为适配尺寸上限已缩放到 {width}×{height}，"
                    "细小文字可能不准确")
            if len(out) > 1:
                notices.append(f"这是同一张长图按上下顺序切成的 {len(out)} 段")
                logger.info("长截图切成 %d 片送视觉（原 %dx%d）", len(out), src_w, src_h)
            return PreparedImages(uris=out, notices=notices, tiled=len(out) > 1)
    except Exception:  # noqa: BLE001
        logger.warning("图片规格化失败，按原样送", exc_info=True)
        return PreparedImages(
            uris=[_to_data_uri(data, mime)],
            notices=["图片规格化失败，按原样送入，可能读不出来"],
        )
