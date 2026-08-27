"""视觉理解（Phase 105）。DeepSeek `deepseek-v4-flash-vision-exp`。

## 为什么接

不是为了「更快」——接图片**不会**让抓页面变快，导航那 30 秒一秒都省不掉，而被替换掉的
`_snapshot_to_text` 恰好是整条链路里唯一零成本的一步（Phase 96）。接它是为了**补一个
信息漏洞**：小红书笔记是图片媒介，实测 4 篇样本里 1 篇的 `desc` 是纯话题标签
（`#杭州[话题]##本地人做的攻略[话题]#`），而它的图里有完整的景点+票价+开放时间表。
我们花 75 秒预算（Phase 102）把它抓回来，最值钱的部分一个字没读。

## 三条实测得来的硬约束

1. **强制 json_object**（在 `LLMClient.parse_image` 里）。裸 prompt 下思考链吃满预算、
   空正文 2/6、延迟中位 23.7s；json_object 下 0/6、7.4s。详见那个函数的 docstring。
2. **只看值得看的图**。desc 本身就是干货的笔记（样本里 3/4），看图是纯浪费。
3. **自己的预算 + 部分收成**（照搬 Phase 102）：超时交回已完成的，迟到的丢掉——
   绝不能让一个 exp 模型拖住终稿。

## 安全

**图片输入绕过 Phase 69 的全部文本防线**：`wrap_external` 与 `EXTERNAL_POLICY` 作用在
文本上，一张图里印着「忽略之前的指令」是直接进模型的。两层防：
① schema 约束——模型只能往固定字段填数组，塞不进自由文本指令；
② 视觉产出的结果一律过 `wrap_external` 包裹再进 prompt，与网页正文同等待遇。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)


class NoteImageInfo(BaseModel):
    """小红书配图里**写着的**信息。字段全是数组——模型只能往里填条目，
    塞不进自由文本指令（这是注入防线的第一层，见模块 docstring）。"""

    has_text: bool = False
    places: list[str] = Field(default_factory=list)
    prices: list[str] = Field(default_factory=list)
    times: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


class PageJudgement(BaseModel):
    page_type: str = "content"
    evidence: str = ""


NOTE_IMAGE_PROMPT = (
    "这是一张小红书旅行笔记的配图。只提取图片里**实际写着的文字信息**，不要推测、不要补常识。\n"
    "图里没有可读的文字信息（纯风景照/自拍）就 has_text=false、其余数组留空。\n"
    "**思考纪律**：这是抽取任务，答案都在图里，思考最多两三行要点，把输出预算留给 JSON 正文。"
)

PAGE_JUDGE_PROMPT = (
    "判断这张网页截图属于哪一类，只看画面：\n"
    "content=正常内容页 | login_wall=要求登录/注册才能看 | "
    "captcha=人机验证(滑块/点选/拼图) | payment=支付页 | error=报错页或空白页\n"
    "evidence 用一句话说明画面里的什么让你这么判断。\n"
    "**思考纪律**：一眼就能看出来的判断，不要长推理。"
)


def enabled() -> bool:
    return bool(settings.vision_enabled and settings.model_vision)


def desc_is_thin(desc: str) -> bool:
    """这篇笔记的 desc 是不是「信息薄」，薄才值得花钱看图。

    实测样本：desc 868 字列着必去景点的笔记，看图是纯浪费；而
    `#杭州[话题]##本地人做的攻略[话题]##杭州旅游[话题]#` 这种**零信息**的，
    全部干货都在图里。判据两条——**去掉话题标签之后**还剩多少字。
    """
    import re

    body = re.sub(r"#[^#\s]{1,30}(\[话题\])?#?", "", desc or "")
    body = re.sub(r"\s+", "", body)
    return len(body) < settings.vision_desc_thin_chars


def _extract_one(url: str, cid: str | None) -> NoteImageInfo | None:
    """单张图 → 结构化信息。任何失败返回 None——视觉是增强，不能拖垮采集。"""
    from app.llm.client import get_llm

    try:
        return get_llm().parse_image(
            NOTE_IMAGE_PROMPT, NoteImageInfo, images=[url], cid=cid,
        )
    except Exception:  # noqa: BLE001
        logger.warning("vision note image failed url=%s", (url or "")[:80], exc_info=True)
        return None


def render_note_info(infos: list[NoteImageInfo]) -> str:
    """多张图的抽取结果 → 一段紧凑文本。全空返回空串（调用方据此决定不追加）。"""
    places: list[str] = []
    prices: list[str] = []
    times: list[str] = []
    tips: list[str] = []
    for info in infos:
        if not info or not info.has_text:
            continue
        places += info.places
        prices += info.prices
        times += info.times
        tips += info.tips
    lines = []
    for label, vals in (("地点", places), ("价格", prices), ("时间", times), ("提示", tips)):
        uniq = list(dict.fromkeys(v.strip() for v in vals if (v or "").strip()))
        if uniq:
            lines.append(f"{label}：{'；'.join(uniq[:12])}")
    return "\n".join(lines)


async def extract_note_images(
    urls: list[str], *, cid: str | None = None, budget_s: float | None = None,
) -> str:
    """一篇笔记的若干张图 → 一段文本。超预算就交回已完成的（Phase 102 的部分收成）。

    ⚠️ 小红书图 URL **有效期不到 30 分钟**（实测：40 分钟前取得的 URL 已 403，库里
    660 条历史 URL 全部 403）。所以视觉必须在**采集当时**做，事后一律拿不到图。
    """
    if not enabled() or not settings.vision_xhs_enabled or not urls:
        return ""
    picked = urls[: settings.vision_max_images_per_note]
    budget = settings.vision_budget_s if budget_s is None else budget_s
    tasks = [asyncio.create_task(asyncio.to_thread(_extract_one, u, cid)) for u in picked]
    done, pending = await asyncio.wait(tasks, timeout=budget)
    for t in pending:
        t.cancel()  # 迟到就迟到，绝不能拖住终稿
    infos = []
    for t in done:
        try:
            got = t.result()
        except Exception:  # noqa: BLE001
            continue
        if got is not None:
            infos.append(got)
    if pending:
        logger.info("vision note images partial: %d/%d 在 %.0fs 内完成",
                    len(infos), len(picked), budget)
    return render_note_info(infos)


class UserImageInfo(BaseModel):
    """用户在对话框里上传的图。比小红书那个宽——用户什么都可能传。"""

    kind: str = "other"      # itinerary/ticket/menu/screenshot/scenery/map/other
    summary: str = ""        # 一句话说这是什么
    places: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    prices: list[str] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)   # 其他关键文字


USER_IMAGE_TILED_PREFIX = (
    "下面 {n} 张图是**同一张长截图**按从上到下的顺序切开的，合起来是一整页，"
    "相邻两片有一点重叠。请把它们当作一份连续的文档来读，不要当成互不相干的几张图。\n"
)

USER_IMAGE_PROMPT = (
    "这是用户在旅行助手里上传的一张图片。判断它是什么，并提取图里**实际写着的**信息，"
    "不要推测、不要补常识。\n"
    "kind 取值：itinerary(行程单/行程截图) | ticket(机票/车票/订单确认) | menu(菜单/价目表) | "
    "screenshot(聊天或网页截图) | scenery(风景/自拍照) | map(地图/路线图) | other\n"
    "summary 一句话（60 字内）说这是什么。风景照没有可读文字时，summary 描述画面，其余数组留空。\n"
    "**思考纪律**：这是抽取任务，答案都在图里，思考最多两三行要点，把输出预算留给 JSON 正文。"
)


def describe_user_images(
    image_ids: list[str], *, cid: str | None = None,
    on_note: "Callable[[str], None] | None" = None,
) -> str:
    """用户上传的图 → 一段供下游链路使用的文本。任何失败返回空串。

    `on_note` 是给调用方播进度用的：长截图要切片多读几段，实测能到 40s+，而这段时间里
    界面上只有一句「正在看你发的 N 张图…」——Phase 71 的结论是**静默空隙**才是流失主因，
    所以切了片就说一声。

    ⚠️ 返回值是**外部内容**，调用方必须过 `wrap_external` 再进 prompt。
    图片输入绕过了 Phase 69 的全部文本防线——一张图里印着「忽略之前的指令」是直接进
    模型的；schema 约束只挡住「模型只能往固定字段填」，标签包裹才是那道熟悉的防线。
    """
    from app.agent.image_prep import prepare_for_vision
    from app.api.upload_api import stored_path
    from app.db.models import TravelUpload
    from app.db.session import get_session
    from app.llm.client import get_llm

    if not enabled() or not image_ids:
        return ""
    blocks: list[str] = []
    for iid in image_ids[: settings.vision_max_user_images]:
        try:
            with get_session() as db:
                row = db.get(TravelUpload, iid)
                mime = row.mime if row else ""
            if not mime:
                continue
            path = stored_path(iid, mime)
            if not path.exists():
                continue
            # Phase 111：长截图（实测 1800x25242）超视觉端单边 8192px 上限会被 400 拒。
            # 规格化会按需切片，多片按上下顺序放进**同一次**调用——同一份文档拆成多次
            # 调用会把上下文割裂（第 3 天的「续住」在片 2、酒店名在片 1）。
            uris = prepare_for_vision(path.read_bytes(), mime)
            prompt = USER_IMAGE_PROMPT
            if len(uris) > 1:
                prompt = USER_IMAGE_TILED_PREFIX.format(n=len(uris)) + prompt
                if on_note is not None:
                    try:
                        on_note(f"这是张长截图，分 {len(uris)} 段读，稍慢一点…")
                    except Exception:  # noqa: BLE001 — 播进度失败不能影响读图
                        logger.warning("vision progress note failed", exc_info=True)
            info = get_llm().parse_image(
                prompt, UserImageInfo, images=uris, cid=cid,
            )
        except Exception:  # noqa: BLE001 — 看不了就当没有这张图
            logger.warning("vision user image failed id=%s", iid, exc_info=True)
            continue
        # ⚠️ 这里的上限是**渲染上限**，不是模型的产出上限。原来写死 15 条，
        # 一张 8 天行程截图抽出来的逐日安排会被砍在 Day 2——用户问「路线合不合适」，
        # 而下游只看得到前两天。跟切片丢尾部是同一类静默失效（Phase 111）。
        lines = ["类型：" + info.kind, "说明：" + info.summary[:200]]
        cap = max(1, settings.vision_user_text_items)
        for label, vals in (("地点", info.places), ("日期", info.dates),
                            ("价格", info.prices), ("其他文字", info.texts)):
            uniq = list(dict.fromkeys(v.strip() for v in vals if (v or "").strip()))
            if uniq:
                if len(uniq) > cap:  # 真砍了就说一声，别让下游以为这就是全部
                    logger.info("用户图 %s 的「%s」有 %d 条，超过渲染上限 %d",
                                iid, label, len(uniq), cap)
                lines.append(label + "：" + "；".join(uniq[:cap]))
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def judge_page_image(image_bytes: bytes, mime: str = "image/jpeg",
                     cid: str | None = None) -> PageJudgement | None:
    """网页截图 → 页面类型。失败返回 None，调用方退回文本判定。

    实测：截图 0.0–0.1s、推理 1.2–1.7s、in=471 token —— 比现有 `_detect_page_type`
    （喂 3000 字给 v4-flash）更便宜；且在知乎那条上更准（文本链路把一个 55 字的 JSON
    错误页判成 `content` 放行了，视觉判 `error`）。
    """
    from app.llm.client import get_llm

    if not enabled() or not settings.vision_page_type_enabled or not image_bytes:
        return None
    try:
        from app.agent.image_prep import prepare_for_vision

        # 整页截图同样可能超高（Phase 111）。这里只判页面类型，看第一片就够——
        # 登录墙/验证码/报错都出现在首屏，不需要把整页都送过去。
        uris = prepare_for_vision(image_bytes, mime)
        return get_llm().parse_image(
            PAGE_JUDGE_PROMPT, PageJudgement, images=uris[:1], cid=cid, max_tokens=1200,
        )
    except Exception:  # noqa: BLE001
        logger.warning("vision page judge failed", exc_info=True)
        return None
