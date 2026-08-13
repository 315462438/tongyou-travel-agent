"""站点路由（Phase 3）单测：意图判定、URL 构造、登录 handoff 等待循环。

全部离线：browser 用 fake 对象，LLM/summarize 用简单函数，asyncio sleep 打桩加速。
"""

import asyncio
import os
from urllib.parse import quote

import pytest

from app.agent import site_router
from app.agent.site_router import (
    SiteTarget,
    collect_via_site,
    detect_intent_by_rules,
    format_ctrip_hotels,
    resolve_intent,
    route_for_intent,
)
from app.config import settings
from app.tools.browser_tool import PageResult


# ---------- 意图判定 ----------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("帮我查一下成都的酒店", "hotel"),
        ("成都住哪比较方便？推荐几家民宿", "hotel"),
        ("帮我规划成都3天的路线", "route"),
        ("成都怎么玩？给个行程安排", "route"),
        ("成都的攻略帮我整理下", "route"),
        ("三日游的住宿攻略", "hotel"),  # 酒店词优先于路线词
        ("成都好玩吗", "general"),
    ],
)
def test_detect_intent_by_rules(text, expected):
    assert detect_intent_by_rules(text) == expected


def test_resolve_intent_prefers_llm_value():
    assert resolve_intent("hotel", "随便说说") == "hotel"
    assert resolve_intent("route", "随便说说") == "route"


def test_resolve_wants_hotel_on_mixed_request():
    """复合需求（用户反馈 bug）：主意图 route，但提到酒店预算 → 酒店需求必须为真。"""
    text = "我想去香港玩三天，规划一下，酒店预算1000块钱一晚上"
    assert site_router.resolve_wants_hotel(False, text) is True  # 规则兜底
    assert site_router.resolve_wants_hotel(True, "随便说说") is True  # LLM 标记
    assert site_router.resolve_wants_hotel(False, "帮我规划成都3天的路线") is False


def test_resolve_intent_falls_back_to_rules():
    # LLM 给 general 或非法值时，规则兜底
    assert resolve_intent("general", "帮我订个酒店") == "hotel"
    assert resolve_intent("nonsense", "帮我规划路线") == "route"
    assert resolve_intent("", "成都好玩吗") == "general"


# ---------- 路由 ----------

def test_route_hotel_to_ctrip_uses_city_id():
    """携程列表页只认数字城市 ID（keyword 参数不生效，踩过坑：查成都开到上海页）"""
    t = route_for_intent("hotel", "成都")
    assert t is not None and t.site == "ctrip" and t.name == "携程"
    assert t.url == "https://hotels.ctrip.com/hotels/listPage?city=28"


def test_route_hotel_normalizes_city_suffix():
    t = route_for_intent("hotel", "成都市")
    assert t is not None and "city=28" in t.url


def test_route_hotel_unknown_city_falls_back():
    """不在城市 ID 表里的目的地不路由（回退公开搜索），绝不能开错城市页面。"""
    assert route_for_intent("hotel", "泸沽湖") is None


def test_route_route_disabled_by_default():
    """小红书默认不接入（云 IP 被风控），路线意图不路由、走搜索。"""
    assert route_for_intent("route", "成都") is None


def test_route_route_to_xhs_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "xhs_enabled", True)
    t = route_for_intent("route", "成都")
    assert t is not None and t.site == "xhs" and t.name == "小红书"
    assert t.url.startswith("https://www.xiaohongshu.com/search_result")
    assert quote("成都 旅游攻略") in t.url


def test_route_general_or_no_destination_returns_none():
    assert route_for_intent("general", "成都") is None
    assert route_for_intent("hotel", "") is None
    assert route_for_intent("route", "  ") is None


# ---------- collect_via_site ----------

class FakeBrowser:
    """脚本化 browser：open_page/check_page 依次弹出预设结果。"""

    def __init__(self, open_results, check_results=(), page_text="x" * 500):
        self.open_results = list(open_results)
        self.check_results = list(check_results)
        self.page_text = page_text
        self.open_calls = 0
        self.check_calls = 0
        self.screenshot_calls = 0

    async def open_page(self, url):
        self.open_calls += 1
        return self.open_results.pop(0)

    async def check_page(self):
        self.check_calls += 1
        return self.check_results.pop(0)

    async def scroll_and_read(self, times=3):
        return self.page_text

    async def screenshot_to_file(self, path):
        self.screenshot_calls += 1
        with open(path, "wb") as f:
            f.write(b"fake-jpeg")


class ProgressSpy:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, text, meta=None):
        self.calls.append((text, meta))

    @property
    def handoffs(self):
        return [m for _, m in self.calls if m and m.get("handoff")]

    @property
    def handoffs_text(self):
        return [t for t, m in self.calls if m and m.get("handoff")]


TARGET = SiteTarget(site="ctrip", name="携程", url="https://hotels.ctrip.com/x")


def _ok(text="内容" * 300):
    return PageResult(status="ok", url="https://hotels.ctrip.com/x", title="成都酒店", text=text)


def _login_wall():
    return PageResult(status="need_user_handoff", url="https://passport.ctrip.com", page_type="login_wall")


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    """加速轮询：不真实 sleep，窗口缩小到 2 次轮询。"""
    monkeypatch.setattr(settings, "handoff_wait_s", 2)
    monkeypatch.setattr(settings, "handoff_poll_s", 1.0)

    async def no_sleep(_):
        pass

    monkeypatch.setattr(site_router.asyncio, "sleep", no_sleep)


def _summarize(text):
    return "摘要：" + text[:20]


def test_collect_direct_ok():
    """无登录墙：直接抓取并返回来源。"""
    browser = FakeBrowser(open_results=[_ok()])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    src = sources[0]
    assert src["site"] == "ctrip" and src["title"] == "成都酒店"
    assert src["summary"].startswith("摘要：")
    assert not progress.handoffs  # 没有 handoff 卡片


def test_collect_handoff_then_login_succeeds():
    """本地模式：登录墙 → handoff 卡片（mode=local）→ 用户登录 → 重开页面继续抓取。"""
    browser = FakeBrowser(
        open_results=[_login_wall(), _ok()],  # 首开=登录墙；登录后重开=ok
        check_results=[_login_wall(), _ok()],  # 第一次轮询还在登录墙，第二次 ok
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    assert len(progress.handoffs) == 1
    handoff = progress.handoffs[0]["handoff"]
    assert handoff["site"] == "ctrip" and handoff["site_name"] == "携程"
    assert handoff["url"] and handoff["mode"] == "local"
    assert browser.check_calls == 2 and browser.open_calls == 2
    assert browser.screenshot_calls == 0  # 本地模式不截图


def test_collect_handoff_timeout_returns_empty():
    """用户一直没登录：轮询到超时后返回空，提示回退搜索。"""
    browser = FakeBrowser(
        open_results=[_login_wall()],
        check_results=[_login_wall()] * 10,
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert sources == []
    assert any("超时" in text for text, _ in progress.calls)


def test_collect_remote_handoff_streams_screenshots_and_continues(monkeypatch, tmp_path):
    """服务器 headless 模式（Phase 5）：登录墙 → 暂停 + 截图直播（mode=remote）→
    用户扫码登录 → 继续抓取；等待结束后截图文件被清理。"""
    monkeypatch.setattr(settings, "chrome_executable", "/usr/bin/google-chrome")
    shot = str(tmp_path / "handoff.jpg")
    browser = FakeBrowser(
        open_results=[_login_wall(), _ok()],
        check_results=[_login_wall(), _ok()],
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(
        TARGET, browser, progress=progress, summarize=_summarize, screenshot_path=shot,
    ))
    assert len(sources) == 1
    handoff = progress.handoffs[0]["handoff"]
    assert handoff["mode"] == "remote" and handoff["screenshot"] is True
    assert "扫" in progress.handoffs_text[0]  # 文案引导扫码
    assert browser.screenshot_calls >= 2  # 首帧 + 每轮轮询刷新
    assert not os.path.exists(shot)  # 等待结束清理截图
    assert any("登录成功" in text for text, _ in progress.calls)


def test_collect_remote_handoff_timeout_cleans_up(monkeypatch, tmp_path):
    """服务器模式超时：回退搜索，截图文件同样被清理。"""
    monkeypatch.setattr(settings, "chrome_executable", "/usr/bin/google-chrome")
    shot = str(tmp_path / "handoff.jpg")
    browser = FakeBrowser(
        open_results=[_login_wall()],
        check_results=[_login_wall()] * 10,
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(
        TARGET, browser, progress=progress, summarize=_summarize, screenshot_path=shot,
    ))
    assert sources == []
    assert not os.path.exists(shot)
    assert any("超时" in text for text, _ in progress.calls)


def test_collect_remote_without_screenshot_path_still_waits(monkeypatch):
    """服务器模式但没传截图路径：照常暂停等待，只是卡片不带截图。"""
    monkeypatch.setattr(settings, "chrome_executable", "/usr/bin/google-chrome")
    browser = FakeBrowser(
        open_results=[_login_wall(), _ok()],
        check_results=[_ok()],
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    assert progress.handoffs[0]["handoff"]["screenshot"] is False
    assert browser.screenshot_calls == 0


def test_collect_blocked_page_returns_empty():
    browser = FakeBrowser(open_results=[PageResult(status="blocked", reason="payment")])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert sources == []


def test_collect_thin_page_returns_empty():
    """页面内容过少（反爬空壳页）不当作有效来源。"""
    browser = FakeBrowser(open_results=[_ok()], page_text="太少")
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert sources == []


def test_collect_irrelevant_page_rejected():
    """站点风控页（如小红书「安全限制」）被页面分类器放行时，相关性校验必须挡掉。"""
    block_page = PageResult(status="ok", url="https://www.xiaohongshu.com/x",
                            title="安全限制", text="IP at risk. Switch to a secure network. " * 20)
    browser = FakeBrowser(open_results=[block_page], page_text=block_page.text)
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(
        TARGET, browser, progress=progress, summarize=_summarize,
        is_relevant=lambda title, text: "厦门" in f"{title}{text}",
    ))
    assert sources == []
    # 文案只陈述事实：我们判定这页不是目标城市的内容。不再断言「被风控拦截」——
    # 线上真实误伤过携程（多城目的地整串比对判死，用户以为携程封控，2026-08-01）。
    assert any("不是目标城市的内容" in text for text, _ in progress.calls)
    assert not any("风控" in text for text, _ in progress.calls)


# ---------- 携程酒店卡片定向抽取（Phase 6） ----------

HOTELS = [
    {"name": "维也纳国际(温江店)", "ad": True, "score": "4.8", "review": "1,574条点评", "loc": "近凤溪河地铁站", "price": ""},
    {"name": "成都太古里春熙美居酒店", "ad": False, "score": "4.8", "review": "23,340条点评", "loc": "近成都太古里·春熙路", "price": ""},
    {"name": "全季酒店(成都太古里春熙路店)", "ad": False, "score": "4.8", "review": "1,640条点评", "loc": "近武侯祠", "price": "¥452"},
    {"name": "成都瑞城名人酒店", "ad": False, "score": "4.7", "review": "21,075条点评", "loc": "近文殊院·天府广场", "price": ""},
]


def test_format_ctrip_hotels():
    listing = format_ctrip_hotels(HOTELS)
    assert listing.startswith("携程实时酒店列表")
    assert "维也纳" not in listing  # 广告卡被过滤
    assert "成都太古里春熙美居酒店" in listing and "评分4.8（23,340条点评）" in listing
    assert "¥452" in listing  # 有价格如实展示
    assert "登录携程后可见" in listing  # 无价格如实标注


def test_format_ctrip_hotels_too_few_returns_empty():
    assert format_ctrip_hotels(HOTELS[:2]) == ""  # 过滤广告后只剩 1 家 → 抽取失败
    assert format_ctrip_hotels([]) == ""


class FakeBrowserWithCards(FakeBrowser):
    """hotels 传批次列表时每次 extract 弹出一批（模拟登录前后两次抽取）。"""

    def __init__(self, *args, hotels=None, hotel_batches=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hotel_batches = list(hotel_batches) if hotel_batches else [hotels or []]

    async def extract_ctrip_hotels(self, attempts=5):
        if len(self.hotel_batches) > 1:
            return self.hotel_batches.pop(0)
        return self.hotel_batches[0]


def test_collect_ctrip_prefers_card_extraction():
    """携程分支：卡片抽取成功时来源 summary 是结构化清单，不走 LLM 摘要。"""
    browser = FakeBrowserWithCards(open_results=[_ok()], hotels=HOTELS)
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    assert sources[0]["summary"].startswith("携程实时酒店列表")
    assert "全季酒店" in sources[0]["summary"]
    assert any("实时酒店列表" in text for text, _ in progress.calls)


NOPRICE_HOTELS = [{**h, "price": ""} for h in HOTELS]


def test_collect_ctrip_no_price_triggers_login_then_gets_prices():
    """全部无价 → 主动打开携程登录页发 handoff 卡 → 登录后重抓拿到实价。"""
    browser = FakeBrowserWithCards(
        open_results=[_ok(), _login_wall(), _ok()],  # 列表页 → 登录页(墙) → 登录后重开列表
        check_results=[_ok()],  # 一次轮询即检测到登录完成
        hotel_batches=[NOPRICE_HOTELS, HOTELS],  # 登录前无价，登录后带 ¥452
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1 and "¥452" in sources[0]["summary"]
    assert len(progress.handoffs) == 1  # 引导登录的卡片
    assert "实时价格" in progress.handoffs_text[0]
    assert any("已补上当日实时价格" in t for t, _ in progress.calls)


def test_collect_ctrip_no_price_login_timeout_keeps_listing():
    """不扫码：超时后仍返回无价清单（不丢酒店数据、不报错）。"""
    browser = FakeBrowserWithCards(
        open_results=[_ok(), _login_wall(), _ok()],
        check_results=[_login_wall()] * 30,
        hotel_batches=[NOPRICE_HOTELS],
    )
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    assert "登录携程后可见" in sources[0]["summary"]
    assert any("先按无价清单继续" in t for t, _ in progress.calls)


def test_collect_ctrip_with_prices_skips_login_flow():
    """已有价格（如已登录）→ 不再打开登录页、不发卡。"""
    browser = FakeBrowserWithCards(open_results=[_ok()], hotel_batches=[HOTELS])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1 and "¥452" in sources[0]["summary"]
    assert browser.open_calls == 1 and not progress.handoffs


def test_collect_ctrip_card_extraction_failure_falls_back():
    """卡片抽取失败（DOM 改版/风控）→ 回退整页摘要路径，不报错。"""
    browser = FakeBrowserWithCards(open_results=[_ok()], hotels=[])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    assert sources[0]["summary"].startswith("摘要：")  # 走了 summarize 回退


def test_collect_summarize_failure_falls_back_to_raw_text():
    def boom(_):
        raise RuntimeError("llm down")

    browser = FakeBrowser(open_results=[_ok()])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=boom))
    assert len(sources) == 1 and sources[0]["summary"]  # 摘要退化为原文截断


def test_ctrip_city_cache(tmp_path):
    """城市 ID 缓存：动态解析一次后落库，下次直接命中。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.models import Base
    from app.agent.site_router import get_cached_city_id, save_cached_city_id, ctrip_target

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert get_cached_city_id(db, "开封") is None
        save_cached_city_id(db, "开封", 163)
        assert get_cached_city_id(db, "开封") == 163
        save_cached_city_id(db, "开封", 999)  # 已存在不覆盖
        assert get_cached_city_id(db, "开封") == 163
    t = ctrip_target(163)
    assert t.site == "ctrip" and t.url.endswith("city=163")


# ---------- 登录态过期（Phase 9） ----------

def _login_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_site_login_mark_and_stale():
    from datetime import datetime, timedelta, timezone
    from app.agent.site_router import clear_site_logins, mark_site_login, stale_site_logins
    from app.db.models import TravelSiteLogin

    db = _login_db()
    assert stale_site_logins(db, "u1", 60) == []  # 无记录不触发
    mark_site_login(db, "u1", "ctrip")
    assert stale_site_logins(db, "u1", 60) == []  # 刚登录，未过期
    # 把记录改老（70 分钟前）
    row = db.get(TravelSiteLogin, ("u1", "ctrip"))
    row.logged_in_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=70)
    db.commit()
    assert stale_site_logins(db, "u1", 60) == ["ctrip"]
    assert stale_site_logins(db, "u1", 0) == []  # ttl=0 永不过期
    # 另一个用户不受影响（隔离）
    assert stale_site_logins(db, "u2", 60) == []
    mark_site_login(db, "u1", "ctrip")  # 重新登录刷新时间
    assert stale_site_logins(db, "u1", 60) == []
    clear_site_logins(db, "u1")
    from sqlalchemy import select
    assert db.execute(select(TravelSiteLogin)).scalars().all() == []


def test_collect_remote_captcha_skips_without_card(monkeypatch):
    """滑块验证码（远程无法操作）：不弹 handoff/确认卡，直接回退搜索。"""
    monkeypatch.setattr(settings, "chrome_executable", "/usr/bin/google-chrome")
    captcha_page = PageResult(status="need_user_handoff", url="https://x.com/verify", page_type="captcha")
    browser = FakeBrowser(open_results=[captcha_page])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert sources == []
    assert not progress.handoffs
    assert any("验证码" in t for t, _ in progress.calls)


def test_local_captcha_still_hands_off():
    """本地模式：可见窗口里用户能拖滑块，保留接管流程。"""
    captcha_page = PageResult(status="need_user_handoff", url="https://x.com/verify", page_type="captcha")
    browser = FakeBrowser(open_results=[captcha_page, _ok()], check_results=[_ok()])
    progress = ProgressSpy()
    sources = asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize))
    assert len(sources) == 1
    assert len(progress.handoffs) == 1


def test_collect_login_wait_respects_cancel(monkeypatch):
    """Phase 47：登录等待循环中途点停止 → TurnCancelled 立即生效（不再干等到超时）。"""
    from app.agent.cancel import TurnCancelled, clear_cancel, request_cancel

    monkeypatch.setattr(settings, "chrome_executable", "/usr/bin/google-chrome")
    monkeypatch.setattr(settings, "handoff_poll_s", 0.01)
    clear_cancel("cX")
    # 登录墙一直不解除；若无取消会轮询到超时
    browser = FakeBrowser(open_results=[_login_wall()], check_results=[_login_wall()] * 100)
    progress = ProgressSpy()

    # 第 2 次轮询前请求取消
    orig = browser.check_page
    calls = {"n": 0}

    async def counting_check():
        calls["n"] += 1
        if calls["n"] >= 2:
            request_cancel("cX")
        return await orig()

    browser.check_page = counting_check
    try:
        with pytest.raises(TurnCancelled):
            asyncio.run(collect_via_site(TARGET, browser, progress=progress, summarize=_summarize, cid="cX"))
    finally:
        clear_cancel("cX")


# ---------- 多城拆分（修复：四城串当一个城市名查携程必然失败） ----------

def test_split_cities_multi():
    from app.agent.site_router import split_cities

    assert split_cities("武汉、开封、洛阳、西安") == ["武汉", "开封", "洛阳", "西安"]
    assert split_cities("成都，重庆") == ["成都", "重庆"]
    assert split_cities("北京市/上海市") == ["北京", "上海"]
    assert split_cities("武汉 武汉市") == ["武汉"]  # 去重 + 剥「市」


def test_split_cities_single_and_empty():
    from app.agent.site_router import split_cities

    assert split_cities("拉萨") == ["拉萨"]
    assert split_cities("成都市") == ["成都"]
    assert split_cities("") == []
    assert split_cities(None) == []
