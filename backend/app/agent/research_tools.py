"""深度研究模式的工具集（Phase 21）

资源分工（用户拍板）：
- 浏览器（必应搜索/开页面）→ **主 agent**：串行有状态昂贵（池 busy=每用户串行、登录态）；
  整轮懒加载共享一个 ChromeMCP 会话，首次用到才 acquire，轮末统一关闭。
- 高德 API / fetch_url（纯 HTTP）→ **subagent**：httpx 无状态可并行。

所有工具内打 cancel.check(cid)（停止按钮可用）并写 progress（前端可见进度）。
工具用闭包工厂绑定 cid/user_id，避免全局状态。
"""

import asyncio
import ipaddress
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from app.agent.cancel import check as cancel_check
from app.config import settings
from app.tools.url_guard import UnsafeURLError, ensure_safe_url

logger = logging.getLogger(__name__)

FETCH_MAX_BYTES = 800_000
FETCH_TIMEOUT_S = 10  # 坏来源止损：15s → 10s（Phase 28）
SOURCE_FULL_MAX_CHARS = 20_000  # 留存全文的上限（Phase 29，超出部分对攻略无增量价值）
# 预算 nudge 阈值（Phase 29，借鉴 Claude Code tokenBudget：接近预算时把消耗显式喂回模型）
BUDGET_NOTE_AT = 0.6  # 用时超过预算 60%：工具结果尾部附用量报告
BUDGET_URGENT_AT = 0.8  # 超过 80%：附强收敛指令


def _now() -> float:
    """单调时钟（模块级函数，便于测试篡改）。"""
    return time.monotonic()


class BrowserSession:
    """整轮共享的懒加载浏览器会话——**actor 模式**。

    坑（线上踩过）：mcp 的 stdio_client 基于 anyio cancel scope，**必须在同一个 asyncio task
    里进入和退出**。deepagents/langgraph 的每次工具调用跑在不同 task 里，如果直接在工具里
    __aenter__、在 finally 里 __aexit__，会炸 "Attempted to exit cancel scope in a different
    task"，且池槽位泄漏为 busy（下一次 acquire 排队超时）。

    因此：一个专职 worker task **全程独占** ChromeMCP 的生命周期（同 task 进出），
    工具通过队列提交请求、await Future 拿结果。
    """

    def __init__(self, cid: str, user_id: str):
        self.cid = cid
        self.user_id = user_id
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        self._startup_error: Exception | None = None

    async def call(self, method: str, *args, **kwargs):
        """在 worker task 里执行 browser.<method>(*args, **kwargs)。"""
        if self._worker is None:
            self._queue = asyncio.Queue()
            self._worker = asyncio.create_task(self._run())
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((fut, method, args, kwargs))
        done, _ = await asyncio.wait({fut, self._worker}, return_when=asyncio.FIRST_COMPLETED)
        if fut in done:
            return fut.result()
        raise self._startup_error or RuntimeError("浏览器会话已退出")  # worker 先结束 = 启动失败/崩溃

    async def _run(self):
        from app.agent.orchestrator import _queue_cb
        from app.tools.browser_tool import BrowserTool
        from app.tools.mcp_client import ChromeMCP

        try:
            async with ChromeMCP(user_id=self.user_id, on_queue=_queue_cb(self.cid)) as chrome:
                browser = BrowserTool(chrome=chrome)
                while True:
                    item = await self._queue.get()
                    if item is None:
                        return
                    fut, method, args, kwargs = item
                    if fut.done():
                        continue
                    try:
                        fut.set_result(await getattr(browser, method)(*args, **kwargs))
                    except Exception as e:  # noqa: BLE001
                        fut.set_exception(e)
        except Exception as e:  # noqa: BLE001 — 启动失败（如排队超时）：记录并让等待者失败
            self._startup_error = e
            while self._queue is not None and not self._queue.empty():
                item = self._queue.get_nowait()
                if item is not None and not item[0].done():
                    item[0].set_exception(e)

    async def close(self):
        if self._worker is None:
            return
        try:
            await self._queue.put(None)
            await asyncio.wait_for(self._worker, timeout=20)
        except asyncio.TimeoutError:
            self._worker.cancel()  # 取消发生在 worker 自己的 task 里，anyio scope 同 task 解开
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            logger.warning("research browser close failed", exc_info=True)
        finally:
            self._worker = None
            self._queue = None


def _is_private_host(host: str) -> bool:
    """SSRF 防护：禁 localhost/内网 IP 字面量。

    Phase 69 起实际校验统一走 `app.tools.url_guard.ensure_safe_url`（多挡 link-local
    云元数据 + 解析 DNS 后复验）。本函数保留仅为兼容既有单测。
    """
    if not host or host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def _html_to_text(html: str, limit: int = 4000) -> str:
    """粗提取正文：去 script/style/标签，折叠空白。"""
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", html).strip()
    return text[:limit]



def _gist(text: str, limit: int = 42) -> str:
    """从抓回的正文里取一句能读的摘要，用于进度播报（纯函数，可单测）。

    只做展示用：折叠空白、去掉 a11y 噪声前缀，截到一句话长度。
    """
    t = re.sub(r"\s+", " ", (text or "")).strip()
    t = re.sub(r"^(uid=\S+\s*|link\s+\"[^\"]*\"\s*)+", "", t)
    if not t:
        return "（没读到正文）"
    # 优先切到第一个句末标点，读起来是完整一句
    m = re.search(r"[。！？!?]", t[:limit + 18])
    if m and m.end() >= 12:
        return t[:m.end()]
    return t[:limit] + ("…" if len(t) > limit else "")


def build_tools(cid: str, user_id: str, session: BrowserSession, sources: list[dict]):
    """构建 (主 agent 工具列表, subagent 工具列表)。sources 收集来源供终稿引用。

    工具硬配额（Phase 28）：prompt 里的资源纪律在长上下文里会漂移（线上实测一轮搜了
    5 次、fetch 了 18 个来源，把 600s 整轮超时烧光、产出全部作废），所以在工具层强制
    封顶。计数器在闭包里按**轮**记账——build_tools 每轮只调用一次，主 agent 和全部
    subagent 拿到的是同一批闭包，配额天然全轮共享。超限不抛异常，返回引导文案让
    agent 带着已有资料转入产出。

    上下文与预算治理（Phase 29）：
    - 抓取的长正文**留存换引用**——全文存 `source_store`（按轮，内存），工具只返回
      预览 + `read_source` 翻页提示，避免一轮抓 10 个页面把上下文灌爆；
    - 所有工具返回经 `_with_budget`：用时超预算 60% 附用量报告、超 80% 附强收敛指令，
      把「还剩多少预算」显式喂回模型（prompt 纪律会漂移，工具结果是模型必读的）。
    """
    from app.agent.orchestrator import _progress

    def _found(text: str) -> None:
        """Phase 71：报告**查到了什么**，而不只是**正在做什么**。

        深度研究要 4-6 分钟，用户放弃多半发生在静默期。工具每返回一批结果就播一条带
        实质内容的进度，等待期就变成了阅读期，同时也是「它还活着」的持续证据。
        """
        t = re.sub(r"\s+", " ", (text or "")).strip()
        if t:
            _progress(cid, t[:80])

    used = {"search": 0, "fetch": 0, "open": 0, "xhs": 0}
    source_store: dict[str, str] = {}  # s1/s2/… → 留存全文
    t0 = _now()

    def _with_budget(text: str) -> str:
        budget = settings.deep_research_timeout_s
        frac = (_now() - t0) / budget if budget else 0.0
        if frac < BUDGET_NOTE_AT:
            return text
        note = (f"\n\n⏳ 已用 {frac * budget / 60:.1f}/{budget / 60:.0f} 分钟"
                f"（搜索 {used['search']}/{settings.deep_research_max_searches}"
                f" · 读页 {used['open']}/{settings.deep_research_max_open_pages}"
                f" · 抓取 {used['fetch']}/{settings.deep_research_max_fetches}）")
        if frac >= BUDGET_URGENT_AT:
            note += "\n❗预算即将耗尽：立即停止收集与子任务，基于现有资料产出最终答案（缺的信息标注「待核实」）。"
        return text + note

    def _stash_source(full_text: str, label: str, url: str = "") -> str:
        """全文留存，返回给模型的预览。超过预览长度才留存换引用，短文原样返回。

        Phase 31：网页正文（外部不可信内容）包 <external_content> 标签；来源编号、
        read_source 提示这些「我们自己的话」留在标签外。
        """
        from app.agent.context_security import wrap_external

        preview_n = settings.deep_research_source_preview_chars
        if len(full_text) <= preview_n:
            return wrap_external(full_text, url=url, title=label)
        sid = f"s{len(source_store) + 1}"
        source_store[sid] = full_text[:SOURCE_FULL_MAX_CHARS]
        return (f"[来源 {sid} | {label} | 共 {len(source_store[sid])} 字，以下是前 {preview_n} 字]\n"
                f"{wrap_external(full_text[:preview_n], url=url, title=label)}\n"
                f"（如需后续内容：read_source(\"{sid}\", offset={preview_n})；通常预览已够用，别逐页读完）")

    # ---------- 主 agent：浏览器 ----------

    async def web_search(query: str) -> str:
        """用搜索引擎（必应）搜索网页，返回结果标题和 URL 列表。找资料的第一步（每轮有次数配额）。

        不要用于：天气/景点/地点核实（走高德工具）；已知确切 URL（直接 fetch_url）；
        同一个信息缺口换关键词反复搜（一次没搜到就换信息源，别耗配额）。
        """
        cancel_check(cid)
        if used["search"] >= settings.deep_research_max_searches:
            return _with_budget(
                f"⚠️ 本轮搜索配额已用完（上限 {settings.deep_research_max_searches} 次）。"
                "不要再搜索，立即基于已收集的资料进入下一步；确实缺的信息在产出里标注「待核实」即可。")
        used["search"] += 1
        _progress(cid, f"🔎 搜索：{query[:40]}")
        results = await session.call("search_web", query, top_n=6)
        if not results:
            return _with_budget("没有搜到结果，换个关键词试试。")
        titles = [r.get("title", "") for r in results if r.get("title")]
        if titles:
            _found("🔎 搜到 %d 条：%s" % (len(results), "、".join(t[:18] for t in titles[:3])))
        lines = [f"{i}. {r.get('title', '')} | {r.get('url', '')}" for i, r in enumerate(results, 1)]
        return _with_budget("\n".join(lines) + "\n\n提示：可派 api-researcher 子任务用 fetch_url 读具体页面。")

    async def open_page(url: str) -> str:
        """用浏览器打开并读取一个网页（很慢且每轮有次数配额）。

        只在 fetch_url 报告读不到时用（JS 渲染页/被反爬的站点）；不要当默认读页手段。
        """
        cancel_check(cid)
        if used["open"] >= settings.deep_research_max_open_pages:
            return _with_budget(
                f"⚠️ 本轮浏览器读页配额已用完（上限 {settings.deep_research_max_open_pages} 次）。"
                "不要再开页面，基于已收集的资料进入下一步。")
        used["open"] += 1
        _progress(cid, f"🌐 浏览器读取：{url[:50]}")
        page = await session.call("open_page", url)
        if page.status != "ok":
            return _with_budget(f"打开失败：{page.reason or page.status}")
        text = (page.text or "")[:SOURCE_FULL_MAX_CHARS]
        _found(f"🌐 读到 {urlparse(url).hostname or url}：{_gist(text)}")
        if len(text) >= 120:  # 与 fetch_url 同口径：真读到正文才算一个来源（此前漏计，来源卡少列）
            sources.append({"title": (urlparse(url).hostname or url)[:60], "url": url})
        return _with_budget(_stash_source(text, urlparse(url).hostname or url, url=url))

    async def read_source(source_id: str, offset: int = 0) -> str:
        """翻页读取此前抓取来源的后续内容（fetch_url/open_page 的预览里给出了来源编号如 "s2"）。

        不要用于：没抓过的 URL（先 fetch_url）；也不要把一个来源逐页读完——预览通常已够用，
        只在预览里明确提到但被截断的关键信息（价格表/时刻表）才值得翻页。
        """
        cancel_check(cid)
        full = source_store.get(source_id)
        if full is None:
            known = "、".join(source_store) or "（本轮还没有留存的来源）"
            return f"没有编号为 {source_id} 的来源。可用编号：{known}"
        chunk_n = settings.deep_research_read_source_chunk
        offset = max(0, int(offset))
        if offset >= len(full):
            return f"来源 {source_id} 共 {len(full)} 字，offset={offset} 已超出末尾。"
        from app.agent.context_security import wrap_external

        chunk = full[offset:offset + chunk_n]
        tail = offset + len(chunk)
        more = f"（后续还有 {len(full) - tail} 字：read_source(\"{source_id}\", offset={tail})）" if tail < len(full) else "（已到末尾）"
        return _with_budget(
            f"[来源 {source_id} 第 {offset}-{tail} 字，共 {len(full)} 字]\n{wrap_external(chunk)}\n{more}")

    # ---------- subagent：纯 API ----------

    async def amap_city_brief(city: str) -> str:
        """查询某城市的实时概览：未来几天天气预报 + 热门景点（评分/地址/坐标）。来自高德地图官方数据。"""
        cancel_check(cid)
        _progress(cid, f"📡 高德数据：{city}")
        from app.tools.amap import build_amap_source

        src = await build_amap_source(city)
        if not src:
            return _with_budget(f"高德没查到 {city} 的数据。")
        sources.append({"title": src["title"], "url": src["url"]})
        return _with_budget(src["summary"])

    async def amap_poi(keyword: str, city: str = "") -> str:
        """按关键词精确查询一个地点/商户（返回规范名/地址/坐标）。适合核实某景点、酒店、餐馆是否存在及位置。"""
        cancel_check(cid)
        from app.tools.amap import search_poi

        async with httpx.AsyncClient(trust_env=False) as client:
            info = await search_poi(client, keyword, city=city)
        if not info:
            return f"没查到「{keyword}」。"
        return f"{info['name']} | 坐标 {info['location']}"

    async def fetch_url(url: str) -> str:
        """纯 HTTP 抓取一个网页并提取正文文本（快，每轮有总配额）。JS 渲染页可能拿不到内容——那种情况报告主 agent 用浏览器。

        不要用于：已抓过的 URL（用 read_source 翻页）；天气/景点数据（走高德工具）。
        """
        cancel_check(cid)
        if used["fetch"] >= settings.deep_research_max_fetches:
            return _with_budget(
                f"⚠️ 本轮网页读取配额已用完（上限 {settings.deep_research_max_fetches} 个来源，"
                "全轮共享）。来源已经足够，请汇总现有资料进入下一步。")
        used["fetch"] += 1
        parsed = urlparse(url)
        # Phase 69：统一走 url_guard（比原来的 _is_private_host 多挡 link-local 云元数据
        # 169.254.169.254，并且会解析 DNS 后再判一次，防「域名解析到内网」绕过）
        try:
            ensure_safe_url(url)
        except UnsafeURLError as e:
            return f"该地址不可访问（{e}）。换一个公开网页。"
        _progress(cid, f"📄 读取：{(parsed.hostname or '')[:30]}")
        try:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            ) as client:
                resp = await client.get(url, timeout=FETCH_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            return _with_budget(f"抓取失败：{type(e).__name__}")
        if resp.status_code != 200:
            return _with_budget(f"HTTP {resp.status_code}，读不到内容。")
        text = _html_to_text(resp.text[:FETCH_MAX_BYTES], limit=SOURCE_FULL_MAX_CHARS)
        if len(text) < 120:
            return _with_budget("页面几乎没有正文（可能是 JS 渲染页），建议主 agent 用浏览器 open_page 读。")
        sources.append({"title": (parsed.hostname or url)[:60], "url": url})
        return _with_budget(_stash_source(text, parsed.hostname or url, url=url))

    async def xhs_search(keyword: str) -> str:
        """搜小红书笔记（攻略/美食/玩法体验类信息质量最高，优先于 web_search）。
        返回笔记列表（feed_id + xsec_token），用 xhs_detail 读正文。每轮有配额。
        """
        cancel_check(cid)
        from app.tools import xhs_mcp

        if not xhs_mcp.enabled():
            return "小红书服务未启用，改用 web_search/fetch_url。"
        if used["xhs"] >= settings.deep_research_max_xhs:
            return _with_budget(f"⚠️ 本轮小红书配额已用完（上限 {settings.deep_research_max_xhs} 次），基于已有资料继续。")
        used["xhs"] += 1
        _progress(cid, f"📕 小红书搜索：{keyword[:30]}")
        feeds = await xhs_mcp.search_notes(keyword)
        if not feeds:
            return _with_budget("小红书没搜到（或服务暂不可用），换 web_search 兜底。")
        picked = [f["title"] for f in feeds[:3] if f.get("title")]
        if picked:
            _found("📕 小红书找到：" + "、".join(t[:18] for t in picked))
        lines = [f"{i}. {f['title'] or '(标题见详情)'} | feed_id={f['feed_id']} | xsec_token={f['xsec_token']}"
                 for i, f in enumerate(feeds[:8], 1)]
        return _with_budget("\n".join(lines) + "\n\n用 xhs_detail(feed_id, xsec_token) 读正文（挑 1-2 篇最相关的即可）。")

    async def xhs_detail(feed_id: str, xsec_token: str) -> str:
        """读一篇小红书笔记正文（配合 xhs_search 的结果用）。每轮与 xhs_search 共享配额。"""
        cancel_check(cid)
        from app.tools import xhs_mcp

        if not xhs_mcp.enabled():
            return "小红书服务未启用。"
        if used["xhs"] >= settings.deep_research_max_xhs:
            return _with_budget(f"⚠️ 本轮小红书配额已用完（上限 {settings.deep_research_max_xhs} 次），基于已有资料继续。")
        used["xhs"] += 1
        det = await xhs_mcp.note_detail(feed_id, xsec_token)
        if det is None:
            return _with_budget("这篇笔记读取失败，换一篇或改用 web_search。")
        url = xhs_mcp.note_url(feed_id)
        _found(f"📕 {det['title'][:20]}：{_gist(det['desc'])}")
        sources.append({"title": f"小红书｜{det['title'][:40]}", "url": url})
        return _with_budget(_stash_source(det["desc"], f"小红书｜{det['title'][:40]}", url=url))

    main_tools = [web_search, open_page, read_source]
    sub_tools = [amap_city_brief, amap_poi, fetch_url, read_source, xhs_search, xhs_detail]
    return main_tools, sub_tools
