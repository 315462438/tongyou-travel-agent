"""站点路由（Phase 3）—— 按意图把 Agent 浏览器导航到指定站点

酒店/住宿相关 → 携程；路线/行程规划相关 → 小红书。
命中登录墙时向对话流写入 handoff 卡片消息（meta.handoff），提示用户在
Agent 调试 Chrome 窗口中自行登录，后台轮询页面状态直到登录完成或超时。

服务器 headless 模式（settings.is_headless_server）用户看不到浏览器窗口，
无法手动登录，直接跳过等待、回退公开搜索。
"""

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from urllib.parse import quote

from app.agent.cancel import check as cancel_check
from app.config import settings

logger = logging.getLogger(__name__)


def handoff_screenshot_path(cid: str) -> str:
    """登录页截图落盘路径（前端经 /api/chat/{cid}/handoff-screenshot 轮询展示）"""
    d = os.path.join(tempfile.gettempdir(), "travel_handoff")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{cid}.jpg")


# 规则兜底：LLM 未给出 intent 时按关键词判定
HOTEL_KEYWORDS = ("酒店", "住宿", "民宿", "宾馆", "旅馆", "客栈", "住哪", "订房", "房间", "hotel")
ROUTE_KEYWORDS = (
    "路线", "行程", "规划", "攻略", "怎么玩", "怎么安排", "玩几天", "几日游",
    "路书", "顺序", "先去", "itinerary",
)


def detect_intent_by_rules(text: str) -> str:
    """关键词兜底判定意图。酒店词优先于路线词（"三日游住宿攻略"应优先按酒店处理）。"""
    lower = (text or "").lower()
    if any(k in lower for k in HOTEL_KEYWORDS):
        return "hotel"
    if any(k in lower for k in ROUTE_KEYWORDS):
        return "route"
    return "general"


def resolve_intent(llm_intent: str, user_text: str) -> str:
    """优先采用 LLM 抽取的 intent；非法值时用规则兜底。"""
    if llm_intent in ("hotel", "route", "general"):
        if llm_intent != "general":
            return llm_intent
    return detect_intent_by_rules(user_text)


def resolve_wants_hotel(llm_wants_hotel: bool, user_text: str) -> bool:
    """复合需求判定：主意图之外是否还包含酒店/住宿需求。

    意图是单选的（「规划行程+看酒店」会被判成 route），酒店需求必须独立判定，
    否则携程路由不会触发（踩过坑）。LLM 标记 + 关键词规则双保险。
    """
    lower = (user_text or "").lower()
    return bool(llm_wants_hotel) or any(k in lower for k in HOTEL_KEYWORDS)


@dataclass(frozen=True)
class SiteTarget:
    site: str  # ctrip / xhs
    name: str  # 展示名
    url: str  # 搜索页 URL


# 携程酒店列表页只认数字城市 ID（?keyword= 参数不生效，会停留在 profile 记忆的
# 上次城市——踩过坑：查成都打开的是上海页）。以下 ID 已逐一在线上验证。
CTRIP_CITY_IDS = {
    "北京": 1, "上海": 2, "重庆": 4, "青岛": 7, "西安": 10, "南京": 12,
    "杭州": 17, "厦门": 25, "成都": 28, "深圳": 30, "广州": 32,
    "昆明": 34, "三亚": 43, "香港": 58,
}


def _norm_city(destination: str) -> str:
    return (destination or "").strip().removesuffix("市")


def split_cities(destination: str) -> list[str]:
    """多城目的地拆分：「武汉、开封、洛阳、西安」→ ["武汉","开封","洛阳","西安"]。

    多城行程的 Preference.destination 是整串顿号/逗号连接的字符串，直接拿去携程当
    「一个城市名」定位必然失败（踩坑：四城串定位失败 → 酒店整体回退搜索）。
    单城输入原样返回单元素列表；去重保序、剥「市」后缀。
    """
    import re as _re

    parts = _re.split(r"[、，,/／\s]+", destination or "")
    seen: list[str] = []
    for p in parts:
        c = _norm_city(p)
        if c and c not in seen:
            seen.append(c)
    return seen


def ctrip_target(city_id: int) -> SiteTarget:
    return SiteTarget(
        site="ctrip", name="携程",
        url=f"https://hotels.ctrip.com/hotels/listPage?city={city_id}",
    )


def get_cached_city_id(db, name: str) -> int | None:
    """携程城市 ID 的 DB 缓存（动态解析一次后落库）"""
    from app.db.models import TravelCtripCity

    row = db.get(TravelCtripCity, name)
    return row.city_id if row else None


def save_cached_city_id(db, name: str, city_id: int) -> None:
    from app.db.models import TravelCtripCity

    if db.get(TravelCtripCity, name) is None:
        db.add(TravelCtripCity(name=name, city_id=city_id))
        db.commit()


def lookup_ctrip_city_id(dest: str) -> int | None:
    """静态表 → DB 缓存。都没有返回 None（由上层走页面动态解析）。"""
    from app.db.session import get_session

    if dest in CTRIP_CITY_IDS:
        return CTRIP_CITY_IDS[dest]
    try:
        with get_session() as db:
            return get_cached_city_id(db, dest)
    except Exception:  # noqa: BLE001
        return None


# ---------- 站点登录态记录 / 过期（Phase 9） ----------

def mark_site_login(db, user_id: str, site: str) -> None:
    """记录（或刷新）某用户在某站点的扫码登录时间（Phase 15 按用户隔离）。"""
    from datetime import datetime, timezone

    from app.db.models import TravelSiteLogin

    row = db.get(TravelSiteLogin, (user_id, site))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row is None:
        db.add(TravelSiteLogin(user_id=user_id, site=site, logged_in_at=now))
    else:
        row.logged_in_at = now
    db.commit()


def stale_site_logins(db, user_id: str, ttl_min: int) -> list[str]:
    """返回某用户已超有效期的站点。ttl_min<=0 表示永不过期。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.models import TravelSiteLogin

    if ttl_min <= 0:
        return []
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=ttl_min)
    rows = db.execute(
        select(TravelSiteLogin).where(TravelSiteLogin.user_id == user_id)
    ).scalars().all()
    return [r.site for r in rows if r.logged_in_at is not None and r.logged_in_at < cutoff]


def clear_site_logins(db, user_id: str) -> None:
    from app.db.models import TravelSiteLogin

    db.query(TravelSiteLogin).filter(TravelSiteLogin.user_id == user_id).delete()
    db.commit()


def _record_login_success(target: SiteTarget, user_id: str) -> None:
    """服务器模式下记录扫码登录成功（本地模式登录态在用户自己的浏览器，不管理）。"""
    if not settings.is_headless_server or not user_id:
        return
    from app.db.session import get_session

    key = target.site if target.site in ("ctrip", "xhs") else target.name
    try:
        with get_session() as db:
            mark_site_login(db, user_id, key)
    except Exception:  # noqa: BLE001
        logger.warning("mark site login failed", exc_info=True)


def remember_ctrip_city_id(dest: str, city_id: int) -> None:
    from app.db.session import get_session

    try:
        with get_session() as db:
            save_cached_city_id(db, dest, city_id)
    except Exception:  # noqa: BLE001
        logger.warning("save ctrip city id failed", exc_info=True)


def route_for_intent(intent: str, destination: str) -> SiteTarget | None:
    """意图 → 站点搜索页。目的地为空或不在城市表时不路由（回退公开搜索）。

    多城目的地取**首城**：整串 `_norm_city("吉隆坡、仙本那、亚庇")` 查不到任何城市 ID，
    route 意图会直接不路由（2026-08-01 全量扫描）。hotel 意图另有逐城分支，不走这里。
    """
    cities = split_cities(destination)
    dest = _norm_city(cities[0] if cities else destination)
    if not dest:
        return None
    if intent == "hotel":
        city_id = CTRIP_CITY_IDS.get(dest)
        if city_id is None:
            return None
        return SiteTarget(
            site="ctrip",
            name="携程",
            url=f"https://hotels.ctrip.com/hotels/listPage?city={city_id}",
        )
    if intent == "route" and settings.xhs_enabled:
        # 默认关闭：小红书风控封锁云服务器 IP，路线规划走必应搜索
        return SiteTarget(
            site="xhs",
            name="小红书",
            url=f"https://www.xiaohongshu.com/search_result?keyword={quote(dest + ' 旅游攻略')}",
        )
    return None


async def collect_via_site(
    target: SiteTarget,
    browser,
    *,
    progress,
    summarize,
    screenshot_path: str | None = None,
    is_relevant=None,
    user_id: str = "",
    cid: str = "",
) -> list[dict]:
    """打开站点搜索页并抓取内容，登录墙暂停交给用户手动登录后继续。

    browser:  BrowserTool 实例（注入便于测试）
    progress: callable(text, meta=None)，向对话流写 progress 消息
    summarize: callable(text) -> str，页面摘要
    screenshot_path: 服务器 headless 模式下，登录页截图落盘路径（前端展示扫码）
    is_relevant: callable(title, text) -> bool，内容相关性校验——站点风控页
        （如小红书「安全限制」）可能被页面分类器判成可读内容混进来源，必须挡掉
    返回 sources: [{title, url, summary}]；失败/超时返回 []。
    """
    if cid:
        cancel_check(cid)  # 停止按钮：打开站点前检查
    page = await browser.open_page(target.url)

    if page.status == "need_user_handoff":
        remote = settings.is_headless_server
        if remote and page.page_type == "captcha":
            # 滑块类验证码无法远程操作（截图只读），不弹卡直接回退
            progress(f"{target.name} 弹出了滑块验证码，云端浏览器无法远程操作，改用公开搜索来源")
            return []
        await _try_switch_to_qr(browser)  # 登录页若默认账号密码表单，切到扫码 tab
        use_screenshot = remote and bool(screenshot_path)
        if use_screenshot:
            # 先截一帧再发卡片，保证前端第一次加载就有图
            await _capture(browser, screenshot_path)
        if remote:
            progress(
                f"{target.name} 需要登录，我先暂停一下：请打开{target.name} App "
                f"扫描下方登录页里的二维码完成登录，我会自动继续。"
                f"（约 {settings.handoff_wait_s // 60} 分钟内未登录将改用公开来源）",
                meta={"handoff": {
                    "site": target.site, "site_name": target.name,
                    "url": page.url or target.url, "mode": "remote",
                    "screenshot": use_screenshot,
                }},
            )
        else:
            progress(
                f"已打开{target.name}，需要登录后才能查看内容。"
                f"请在弹出的 Chrome 窗口中完成登录，我会自动继续。",
                meta={"handoff": {
                    "site": target.site, "site_name": target.name,
                    "url": page.url or target.url, "mode": "local",
                }},
            )
        try:
            page = await _wait_for_login(
                target, browser, progress,
                screenshot_path=screenshot_path if use_screenshot else None,
                user_id=user_id, cid=cid,
            )
        finally:
            if use_screenshot:
                try:
                    os.remove(screenshot_path)
                except OSError:
                    pass
        if page is None:
            progress(f"等待{target.name}登录超时，改用公开搜索来源")
            return []
        progress(f"登录成功，继续为你抓取{target.name}内容…")

    if page.status != "ok":
        progress(f"{target.name} 页面无法自动浏览（{page.reason or page.status}），改用公开搜索来源")
        return []

    try:
        text = await browser.scroll_and_read(times=3)
    except Exception:  # noqa: BLE001 — 滚动失败就用首屏
        text = page.text
    if len(text or "") < 200:
        progress(f"{target.name} 页面内容太少，改用公开搜索来源")
        return []
    if is_relevant is not None and not is_relevant(page.title or "", text):
        # 别把「我们判定不相关」说成「站点风控」——2026-08-01 线上事故里携程抓得好好的，
        # 是多城目的地整串比对判死的，用户却以为被封控。文案只陈述事实。
        progress(f"{target.name} 这页不是目标城市的内容，改用公开搜索来源")
        return []

    # 携程：优先 DOM 定向抽取真实酒店卡片（Phase 6），失败回退整页摘要
    if target.site == "ctrip" and hasattr(browser, "extract_ctrip_hotels"):
        hotels = await browser.extract_ctrip_hotels()
        listing = format_ctrip_hotels(hotels)
        if listing:
            n = listing.count("\n")
            progress(f"已抓取{target.name}实时酒店列表（{n} 家）")
            # 未登录时携程不渲染价格（卡片显示「登录以查看会员价」）——
            # 主动引导登录拿实价；不登录也继续，只是价格留空
            if _no_prices(hotels):
                listing = await _login_for_prices(
                    target, browser, progress=progress,
                    screenshot_path=screenshot_path, fallback_listing=listing,
                    user_id=user_id, cid=cid,
                )
            # 酒店配图（图 URL 与登录态无关，用初次抽取的卡片即可）
            return [{
                "title": page.title or f"{target.name}酒店列表",
                "url": page.url or target.url,
                "summary": listing,
                "site": target.site,
                "images": ctrip_hotel_images(hotels),
            }]

    try:
        summary = summarize(text)
    except Exception:  # noqa: BLE001
        summary = (text or "")[:800]
    title = page.title or f"{target.name}搜索结果"
    progress(f"已读取：{title[:28]}")
    return [{"title": title, "url": page.url or target.url, "summary": summary, "site": target.site}]


def ctrip_hotel_images(hotels: list[dict], top_n: int = 6) -> list[dict]:
    """酒店卡片 → 配图清单 [{name, url}]（过滤广告卡，仅取有图的）。"""
    out: list[dict] = []
    for h in hotels:
        if h.get("ad") or not h.get("name") or not h.get("img"):
            continue
        out.append({"name": h["name"], "url": h["img"]})
        if len(out) >= top_n:
            break
    return out


def format_ctrip_hotels(hotels: list[dict], top_n: int = 8) -> str:
    """酒店卡片 → 来源 summary 文本（直接进生成 prompt，不走 LLM 摘要）。

    过滤广告卡；不足 3 家返回空串（视为抽取失败，让上层回退整页摘要）。
    未登录时携程不展示价格（显示「登录以查看会员价」），price 为空时如实标注。
    """
    picked = [h for h in hotels if h.get("name") and not h.get("ad")][:top_n]
    if len(picked) < 3:
        return ""
    lines = []
    for i, h in enumerate(picked, 1):
        parts = [h["name"]]
        if h.get("score"):
            score = f"评分{h['score']}"
            if h.get("review"):
                score += f"（{h['review']}）"
            parts.append(score)
        if h.get("loc"):
            parts.append(f"位置：{h['loc']}")
        parts.append(f"价格：{h.get('price') or '未展示（登录携程后可见）'}")
        lines.append(f"{i}. " + "｜".join(parts))
    return "携程实时酒店列表（当日抓取）：\n" + "\n".join(lines)


CTRIP_LOGIN_URL = "https://passport.ctrip.com/user/login"


def _no_prices(hotels: list[dict]) -> bool:
    return not any(h.get("price") for h in hotels)


async def _login_for_prices(
    target: SiteTarget, browser, *, progress, screenshot_path, fallback_listing: str,
    user_id: str = "", cid: str = "",
) -> str:
    """主动打开携程登录页引导用户登录，登录后重抓列表拿实价。

    与登录墙 handoff 的区别：这里不登录也不算失败——超时/失败都返回
    fallback_listing（无价清单）继续主流程。登录态存持久 profile，只需引导一次。
    """
    try:
        login_page = await browser.open_page(CTRIP_LOGIN_URL)
    except Exception:  # noqa: BLE001
        return fallback_listing
    if login_page.status != "need_user_handoff":
        # 已有登录态却仍无价（或登录页未弹墙）：回到列表页，直接用无价清单
        try:
            await browser.open_page(target.url)
        except Exception:  # noqa: BLE001
            pass
        return fallback_listing

    remote = settings.is_headless_server
    await _try_switch_to_qr(browser)  # 携程登录页默认账号密码表单，先把二维码翻出来
    use_screenshot = remote and bool(screenshot_path)
    if use_screenshot:
        await _capture(browser, screenshot_path)
    hint = (
        f"请打开{target.name} App 扫描下方登录页里的二维码"
        if remote else f"请在弹出的 Chrome 窗口中登录{target.name}"
    )
    progress(
        f"酒店列表已拿到，但{target.name}未登录不展示实时价格。{hint}，"
        f"登录后我会补上当日实价；约 {settings.price_login_wait_s} 秒内未登录就先按无价清单继续。",
        meta={"handoff": {
            "site": target.site, "site_name": target.name,
            "url": login_page.url or CTRIP_LOGIN_URL,
            "mode": "remote" if remote else "local",
            "screenshot": use_screenshot,
        }},
    )
    try:
        page = await _wait_for_login(
            target, browser, progress,
            screenshot_path=screenshot_path if use_screenshot else None,
            wait_s=settings.price_login_wait_s, user_id=user_id, cid=cid,
        )
    finally:
        if use_screenshot:
            try:
                os.remove(screenshot_path)
            except OSError:
                pass
    if page is None:
        progress("未登录，先按无价清单继续（登录一次后以后都会带实价）")
        try:
            await browser.open_page(target.url)
        except Exception:  # noqa: BLE001
            pass
        return fallback_listing

    hotels = await browser.extract_ctrip_hotels()
    listing = format_ctrip_hotels(hotels)
    if listing and not _no_prices(hotels):
        progress("登录成功，已补上当日实时价格")
        return listing
    return listing or fallback_listing


async def _try_switch_to_qr(browser) -> None:
    """登录页默认是账号密码表单时，点「扫码登录」tab 把二维码翻出来。

    该点击在 Action Guard 里有精确白名单（LOGIN_METHOD_TOGGLE_TEXTS）：
    只切换展示形态，不输入不提交。找不到入口（如页面本来就是二维码）静默跳过。
    """
    if not hasattr(browser, "find_and_click"):
        return
    try:
        await browser.find_and_click("扫码登录")
    except Exception:  # noqa: BLE001
        pass


async def _capture(browser, path: str) -> None:
    """截当前页到文件。截图失败不致命（少一帧而已），只记日志。"""
    try:
        await browser.screenshot_to_file(path)
    except Exception:  # noqa: BLE001
        logger.warning("handoff screenshot failed", exc_info=True)


async def _wait_for_login(
    target: SiteTarget, browser, progress,
    screenshot_path: str | None = None, wait_s: float | None = None, user_id: str = "",
    cid: str = "",
):
    """轮询等待用户完成登录。返回可用的 PageResult，超时返回 None。

    轮询用 check_page（只 snapshot 旁观，不导航），避免打断用户正在进行的登录流程
    （本地=正在输入的表单；远程=二维码刷新由页面自己完成）；
    screenshot_path 非空时每轮刷新登录页截图供前端展示扫码。
    检测到页面可访问后，再重新打开目标搜索页拿最新内容。
    """
    waited = 0.0
    deadline = wait_s if wait_s is not None else settings.handoff_wait_s
    while waited < deadline:
        if cid:
            cancel_check(cid)  # 停止按钮：登录等待每轮检查（原来最长干等 180s 无法停）
        await asyncio.sleep(settings.handoff_poll_s)
        waited += settings.handoff_poll_s
        if screenshot_path:
            await _capture(browser, screenshot_path)
        try:
            page = await browser.check_page()
        except Exception:  # noqa: BLE001 — 单次轮询失败不终止等待
            logger.warning("polling %s failed, keep waiting", target.site, exc_info=True)
            continue
        if page.status == "blocked":
            return None
        if page.status == "ok":
            _record_login_success(target, user_id)  # 记录登录时间（按用户）
            # 登录完成后可能被跳转到首页等，重新打开目标搜索页
            final = await browser.open_page(target.url)
            return final if final.status == "ok" else None
    return None
