"""第一视角旅行实境预演（Phase 79）。

这是轻量游戏化体验，不是 3D 世界：后端负责返回事实可控的场景骨架和高德真实 POI 图片，
前端负责分支选择、HUD 与转行程。图片与 HUD 都是增强项，任何第三方失败不能让体验入口报废。
"""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.db.models import TravelUser
from app.tools.amap import enabled as amap_enabled, search_destination_cover, search_poi

router = APIRouter(prefix="/api/immersive", tags=["immersive"])
logger = logging.getLogger(__name__)

PREVIEW_SUCCESS_TTL_S = 6 * 60 * 60
PREVIEW_EMPTY_TTL_S = 60 * 60
_preview_cache: dict[str, tuple[float, dict]] = {}

_SAFE_PHOTO_HOSTS = ("amap.com", "autonavi.com")


TIANTANGZHAI_SCENES: list[dict] = [
    {
        "id": "arrival",
        "chapter": "序章",
        "title": "雾从山门醒来",
        "location": "天堂寨风景区",
        "query": "天堂寨风景区",
        "time": "08:10",
        "atmosphere": "晨雾 · 山风微凉",
        "narration": "你站在大别山深处的山门前。云雾压得很低，木栈道还带着昨夜的水汽，远处已经能听见瀑布。今天不追打卡数量，只决定自己想怎样走进这座山。",
        "energy_delta": -3,
        "cost": 0,
    },
    {
        "id": "fork",
        "chapter": "第一幕",
        "title": "峡谷与山脊的分岔",
        "location": "白马大峡谷",
        "query": "天堂寨白马大峡谷",
        "time": "09:00",
        "atmosphere": "水声渐近 · 林间湿润",
        "narration": "峡谷的水声从左侧传来，右侧石阶则一路没入山脊。你的脚步在岔路口停下：是沿溪慢慢进入峡谷，还是趁体力充足向高处挑战？",
        "energy_delta": -4,
        "cost": 0,
        "choices": [
            {"id": "canyon", "label": "沿峡谷慢慢走", "hint": "风景密集 · 体力友好", "energy_delta": -5},
            {"id": "summit", "label": "向主峰挑战", "hint": "爬升明显 · 视野更开阔", "energy_delta": -13},
        ],
    },
    {
        "id": "route",
        "chapter": "第二幕",
        "title": "水声越来越近",
        "location": "天堂寨瀑布群",
        "query": "天堂寨瀑布群",
        "time": "10:15",
        "atmosphere": "飞瀑水雾 · 光线穿林",
        "narration": "石阶在树林里一转，瀑布忽然出现在眼前。细小水雾落在脸上，你下意识放慢脚步。",
        "energy_delta": -8,
        "cost": 6,
        "variants": {
            "canyon": {
                "title": "沿水声进入峡谷",
                "narration": "你选择沿白马大峡谷缓行。溪水一直在脚边，栈道起伏不大，停下来拍照也不会打乱节奏。瀑布转角出现时，你还有余力继续向前。",
                "energy_delta": -6,
            },
            "summit": {
                "title": "石阶把呼吸拉长",
                "narration": "你选择向主峰爬升。连续石阶让呼吸明显变重，但每抬高一段，峡谷就向身后展开一点。你决定在瀑布旁补水，再继续上行。",
                "energy_delta": -16,
            },
        },
    },
    {
        "id": "cloud",
        "chapter": "第三幕",
        "title": "站到云的上面",
        "location": "哲人峰",
        "query": "天堂寨哲人峰",
        "time": "12:20",
        "atmosphere": "云隙放晴 · 山风增强",
        "narration": "云层被风推开了一道口子，层叠山脊从脚下延伸出去。你终于理解这里为什么让人想把脚步放慢——不是没有路要赶，而是眼前值得多停一会儿。",
        "energy_delta": -10,
        "cost": 12,
    },
    {
        "id": "summit",
        "chapter": "第四幕",
        "title": "山顶的风替你按下暂停",
        "location": "天堂顶",
        "query": "天堂寨天堂顶",
        "time": "14:10",
        "atmosphere": "高处阵风 · 视野开阔",
        "narration": "抵达高处时，风把衣角吹得猎猎作响。你没有立刻拿出手机，只是先看了一分钟。山谷、云影和来时的路在此刻连成了一条完整的线。",
        "energy_delta": -12,
        "cost": 0,
    },
    {
        "id": "dinner",
        "chapter": "终章",
        "title": "吊锅的热气升起来",
        "location": "天堂寨山村",
        "query": "天堂寨吊锅",
        "time": "18:30",
        "atmosphere": "暮色落山 · 炉火温暖",
        "narration": "回到山脚，吊锅的热气把一天的湿冷驱散。筷子碰到锅沿发出轻响，你开始复盘：今天真正记住的不是走了多少公里，而是自己选择了怎样的一条路。",
        "energy_delta": 12,
        "cost": 88,
    },
]


def normalize_destination(value: str) -> str:
    """接口只接受一个短目的地；多城表达取首项，避免用整句搜索 POI。"""
    text = (value or "").strip()
    for sep in ("→", "、", "，", ",", "/", "+"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text.strip()[:24]


def _safe_photo(url: str) -> str:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return ""
    host = urlparse(url).hostname or ""
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _SAFE_PHOTO_HOSTS):
        return ""
    return url


def _generic_scenes(destination: str) -> list[dict]:
    """非标杆目的地的安全通用骨架；不虚构具体景点事实。"""
    phases = [
        ("arrival", "序章", "抵达的第一分钟", destination, "08:30", "晨光 · 城市刚醒", -2, 0),
        ("fork", "第一幕", "今天想怎样走", f"{destination}景区", "09:20", "人流渐起 · 微风", -3, 0),
        ("route", "第二幕", "沿着风景向前", f"{destination}景点", "10:40", "光线变亮 · 步伐稳定", -8, 8),
        ("view", "第三幕", "在视野最好的地方停下", f"{destination}观景台", "12:30", "视野打开 · 适合休息", -9, 15),
        ("local", "第四幕", "走进当地人的日常", f"{destination}老街", "15:30", "街巷渐暖 · 香气出现", -6, 25),
        ("dinner", "终章", "用一顿饭记住这里", f"{destination}美食", "18:40", "夜色落下 · 灯火亮起", 10, 90),
    ]
    out: list[dict] = []
    for scene_id, chapter, title, query, at, atmosphere, energy, cost in phases:
        scene = {
            "id": scene_id,
            "chapter": chapter,
            "title": title,
            "location": destination,
            "query": query,
            "time": at,
            "atmosphere": atmosphere,
            "narration": f"你正在以第一视角走进{destination}。先观察周围、感受脚步，再决定下一段路要走得轻松还是更深入。",
            "energy_delta": energy,
            "cost": cost,
        }
        if scene_id == "fork":
            scene["choices"] = [
                {"id": "canyon", "label": "选择轻松路线", "hint": "留出停留和拍照时间", "energy_delta": -4},
                {"id": "summit", "label": "选择深入路线", "hint": "更多步行与探索", "energy_delta": -12},
            ]
        if scene_id == "route":
            scene["variants"] = {
                "canyon": {"title": "把脚步放慢", "narration": f"你选择用更松弛的节奏认识{destination}，给每一次停留留下余地。", "energy_delta": -5},
                "summit": {"title": "继续向更深处走", "narration": f"你选择投入更多体力，去看见{destination}更完整的一面。", "energy_delta": -14},
            }
        out.append(scene)
    return out


async def build_immersive_preview(destination: str) -> dict:
    dest = normalize_destination(destination)
    scenes = deepcopy(TIANTANGZHAI_SCENES if dest in {"天堂寨", "安徽天堂寨"} else _generic_scenes(dest))
    has_any_image = False

    if dest and amap_enabled():
        semaphore = asyncio.Semaphore(2)
        async with httpx.AsyncClient(trust_env=False) as client:
            async def enrich(index: int, scene: dict) -> tuple[int, str, str]:
                try:
                    async with semaphore:
                        info = await search_poi(client, scene["query"], city=dest)
                    return index, _safe_photo((info or {}).get("photo", "")), (info or {}).get("name", "")
                except Exception:  # noqa: BLE001
                    logger.warning("实境场景图片查询失败：%s/%s", dest, scene.get("query"), exc_info=True)
                    return index, "", ""

            resolved = await asyncio.gather(*(enrich(i, scene) for i, scene in enumerate(scenes)))
            fallback = ""
            if any(not photo for _, photo, _ in resolved):
                try:
                    fallback = _safe_photo(await search_destination_cover(client, dest))
                except Exception:  # noqa: BLE001
                    logger.warning("实境目的地封面查询失败：%s", dest, exc_info=True)

        for index, photo, poi_name in resolved:
            scenes[index]["image"] = photo or fallback
            scenes[index]["poi_name"] = poi_name or scenes[index]["location"]
            has_any_image = has_any_image or bool(scenes[index]["image"])
    else:
        for scene in scenes:
            scene["image"] = ""
            scene["poi_name"] = scene["location"]

    for scene in scenes:
        scene.pop("query", None)

    return {
        "destination": dest,
        "title": f"走进{dest}",
        "subtitle": "一段约 2 分钟的第一视角旅行预演",
        "disclaimer": "场景图片来自高德 POI；时间、体力与花费为体验模拟，不代表实时状态。",
        "scenes": scenes,
        "has_images": has_any_image,
    }


@router.get("/preview")
async def immersive_preview(
    destination: str = Query(default="天堂寨", min_length=1, max_length=24),
    user: TravelUser = Depends(get_current_user),
):
    del user
    dest = normalize_destination(destination)
    now = time.monotonic()
    cached = _preview_cache.get(dest)
    if cached and cached[0] > now:
        return deepcopy(cached[1])

    payload = await build_immersive_preview(dest)
    ttl = PREVIEW_SUCCESS_TTL_S if payload["has_images"] else PREVIEW_EMPTY_TTL_S
    _preview_cache[dest] = (time.monotonic() + ttl, deepcopy(payload))
    return payload
