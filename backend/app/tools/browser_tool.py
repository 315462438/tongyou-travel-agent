"""BrowserTool —— 基于 chrome-devtools-mcp 真实工具集的业务封装（评审 🔴1）

两步交互模式：
  1. take_snapshot → 带 uid 的可访问性树
  2. LLM 从快照定位目标元素 uid → click(uid) / fill(uid, text)

所有交互动作先过 Action Guard；导航后独立执行页面状态检测（第三层）。
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.config import settings
from app.llm.client import get_llm
from app.schemas.note_schema import PageClassification
from app.tools.action_guard import Decision, GuardResult, judge_action, judge_page_type
from app.tools.mcp_client import ChromeMCP
from app.tools.url_guard import UnsafeURLError, ensure_safe_url

logger = logging.getLogger(__name__)


def _looks_like_timeout(err: BaseException) -> bool:
    """这个导航失败是不是超时（Phase 99）。

    识别不出来就返回 False——退化方向是保留重试（今天的行为），不会更差。
    `TimeoutError()` 的 str 常为空，所以 isinstance 单独判。
    """
    if isinstance(err, (TimeoutError, asyncio.TimeoutError)):
        return True
    msg = str(err).lower()
    return "timeout" in msg or "timed out" in msg


@dataclass
class PageResult:
    status: str  # ok / need_user_handoff / blocked
    url: str = ""
    title: str = ""
    text: str = ""
    page_type: str = "unknown"
    reason: str = ""


@dataclass
class BrowserTool:
    chrome: ChromeMCP
    pages_visited: int = 0
    _last_snapshot: str = field(default="", repr=False)

    async def _polite_delay(self):
        """礼貌性限速（评审 🟡4）"""
        await asyncio.sleep(random.uniform(settings.page_delay_min_s, settings.page_delay_max_s))

    async def open_page(self, url: str) -> PageResult:
        """打开页面 → 等待加载 → snapshot → 页面类型检测（第三层守卫）"""
        if self.pages_visited >= settings.max_pages_per_task:
            return PageResult(status="blocked", reason=f"已达单任务页面上限 {settings.max_pages_per_task}")

        # Phase 69：URL 安全校验必须在 action_guard 之前——navigate 在 guard 里永远放行，
        # 而本方法是深度研究 agent 的工具（URL 由模型决定，模型又会读不可信网页），
        # 没有这层就等于把 file:// 读本地文件和内网探测直接交给注入内容驱动。
        try:
            ensure_safe_url(url)
        except UnsafeURLError as e:
            return PageResult(status="blocked", reason=f"不允许访问该地址：{e}")

        # 第一层：navigate 永远放行（judge_action 保持调用以统一审计口径）
        guard = judge_action("navigate", url=url)
        assert guard.decision == Decision.ALLOW

        if self.pages_visited > 0:
            await self._polite_delay()

        try:
            await self.chrome.call("navigate_page", {"url": url, "timeout": 30000})
        except Exception as e:  # noqa: BLE001
            # Phase 99：按失败类型分流。**超时不重导航**——导航超时 ≠ 页面为空，
            # 首次超时时页面往往已部分加载，直接 snapshot 常能拿到内容；盲目重导航
            # 把已加载的内容重置掉，还再烧一次 30s（线上实测两轮各出现一个 ~62s 的
            # open_page，正是 30s+30s 的痕迹）。非超时（CDP 抖动/连接断）仍重试一次，
            # 那类失败是瞬时的且失败得快——这才是当初加重试的合理场景。
            if _looks_like_timeout(e):
                logger.warning("navigate timeout, salvaging via snapshot: %s", url)
            else:
                await self.chrome.call("navigate_page", {"url": url, "timeout": 30000})
        try:
            await self.chrome.call("wait_for", {"text": "", "timeout": 5000})
        except Exception:  # noqa: BLE001 — wait 失败不致命，snapshot 兜底
            pass
        self.pages_visited += 1
        return await self._evaluate_current_page(url)

    async def check_page(self) -> PageResult:
        """重新检测当前页面状态（不导航、不占页面预算）。

        站点路由 handoff 场景用：用户正在浏览器里手动登录时，轮询页面状态
        不能用 open_page 反复 navigate（会打断用户输入），只能 snapshot 旁观。
        """
        return await self._evaluate_current_page("")

    async def _evaluate_current_page(self, fallback_url: str) -> PageResult:
        """snapshot 当前页 → 页面类型检测（第三层守卫）→ PageResult"""
        snapshot = await self.chrome.call("take_snapshot", {})
        self._last_snapshot = snapshot
        text = self._snapshot_to_text(snapshot)
        title, current_url = self._extract_title_url(snapshot, fallback_url)

        # Phase 105：视觉判定作为**对照通道**。
        # ⚠️ 只在规则快判拿不准（要走模型兜底）时才跑。多数内容页命中 Phase 11 的
        # 「正文>1500 字直接判 content」规则，文本侧是 **0 秒**，此时并行跑视觉是净增
        # 1.4s/页（8 页就是 +11s）。而那个已知误判恰好就在模型兜底这一档：知乎返回
        # 55 字的 JSON 错误页 → 规则不命中 → 模型判成 `content` 放行，视觉判 `error`。
        # **刻意不直接替换**文本判定——它是 Action Guard 三层守卫的一环、跑了很久。
        # 先让两者打对台，不一致只记日志、仍以文本判定为准，攒够数据再决定谁说了算。
        head = text[:3000]
        rule_type = self._rule_page_type(current_url, head)
        if rule_type is not None:
            page_type = rule_type
        else:
            page_type, vision_type = await asyncio.gather(
                self._detect_page_type(current_url, head),
                self._vision_page_type(),
            )
            if vision_type and vision_type != page_type:
                logger.warning("page_type 分歧 url=%s 文本=%s 视觉=%s", current_url[:80],
                               page_type, vision_type)
        disposition: GuardResult = judge_page_type(page_type)
        if disposition.decision == Decision.REQUIRE_HANDOFF:
            return PageResult(
                status="need_user_handoff", url=current_url, title=title,
                text=text, page_type=page_type, reason=disposition.reason,
            )
        if disposition.decision == Decision.BLOCK:
            return PageResult(
                status="blocked", url=current_url, title=title,
                page_type=page_type, reason=disposition.reason,
            )
        return PageResult(status="ok", url=current_url, title=title, text=text, page_type=page_type)

    async def read_page(self) -> str:
        """重新读取当前页面文本（用户接管完成后调用）"""
        snapshot = await self.chrome.call("take_snapshot", {})
        self._last_snapshot = snapshot
        return self._snapshot_to_text(snapshot)

    async def search_web(self, query: str, top_n: int = 5) -> list[dict]:
        """搜索引擎查询（必应），返回 [{title, url}]（Phase 2，数据源优先级：搜索引擎优先）

        必应结果异步渲染，take_snapshot 抓不全，改用 evaluate_script 直接读 DOM。
        """
        from urllib.parse import quote

        if self.pages_visited > 0:
            await self._polite_delay()
        # 必应结果页是 SPA，连续导航会抓到旧 DOM/推荐流 → 先 about:blank 强制卸载
        js = (
            "() => JSON.stringify({q: (document.querySelector('#sb_form_q')||{}).value || '', "
            "results: [...document.querySelectorAll('#b_results li.b_algo h2 a')]"
            ".map(a => ({title: a.innerText.trim(), url: a.href}))"
            ".filter(x => x.title.length > 5)})"
        )
        for attempt in range(2):
            try:
                await self.chrome.call("navigate_page", {"url": "about:blank", "timeout": 10000})
                await self.chrome.call(
                    "navigate_page",
                    {"url": f"https://www.bing.com/search?q={quote(query)}", "timeout": 30000},
                )
            except Exception:  # noqa: BLE001 — 导航失败也要走 360 兜底，不能直接放弃
                break
            self.pages_visited += 1
            await asyncio.sleep(2.5 + attempt)  # 重试时多等
            try:
                raw = await self.chrome.call("evaluate_script", {"function": js})
            except Exception:  # noqa: BLE001
                continue
            payload = self._parse_search_payload(raw)
            # 校验结果对应当前查询：必应被限流时会返回垃圾页/旧 DOM，此时搜索框值为空
            # 或是别的词——这批结果与查询无关，混进来会浪费 agent 的搜索配额（线上踩坑：
            # 搜「商丘古城」返回 Doomworld 论坛。这个校验此前只写了注释没写代码）
            if payload and payload.get("results") and self._query_matches(payload.get("q", ""), query):
                # 搜索框校验只证明「页面对应本次查询」，不证明结果本身相关——线上抓到过
                # 搜索框正常但结果全是「Facebook / Log Into Facebook」的垃圾页。
                # 标题相关性再过一层；全被滤掉则视为垃圾页，走重试/360 兜底。
                kept = [r for r in payload["results"]
                        if self._relevant_to_query(r.get("title") or "", query)]
                if kept:
                    return self._filter_results(kept, top_n)
        # 必应对服务器 IP 会间歇性限流（返回空结果）→ 360 搜索兜底
        # （百度/搜狗对机房 IP 直接弹验证码，实测只有 360 可用）
        return await self._search_360(query, top_n)

    async def _search_360(self, query: str, top_n: int) -> list[dict]:
        """360 搜索兜底。结果链接是 so.com/link 跳转链（open_page 会跟随重定向），
        需要过滤 360 自家内容服务（文库/问答/AI/快资讯）。"""
        from urllib.parse import quote

        js = (
            "() => JSON.stringify([...document.querySelectorAll('h3 a')]"
            ".map(a => ({title: a.innerText.replace(/\\s+/g, ' ').trim(), url: a.href}))"
            ".filter(x => x.title.length > 5))"
        )
        try:
            await self.chrome.call("navigate_page", {"url": "about:blank", "timeout": 10000})
            await self.chrome.call(
                "navigate_page",
                {"url": f"https://www.so.com/s?q={quote(query)}", "timeout": 30000},
            )
        except Exception:  # noqa: BLE001
            return []
        self.pages_visited += 1
        await asyncio.sleep(3.0)
        try:
            raw = await self.chrome.call("evaluate_script", {"function": js})
        except Exception:  # noqa: BLE001
            return []
        val = self._decode_eval(raw)
        if not isinstance(val, list):
            return []
        # 相关性校验：360 结果页的 h3 a 混着推广位/信息流（线上真实抓到「唧唧Down下载」
        # 「哔哩哔哩下载中心」这类与查询毫无关系的广告标题）。必应路径有搜索框回读校验，
        # 360 这里按「标题与任一查询词元重叠」过滤——正常中文搜索结果标题必含查询词。
        kept = [
            r for r in val
            if isinstance(r, dict)
            and not self._is_360_self_service(r.get("url") or "")
            and self._relevant_to_query(r.get("title") or "", query)
        ]
        return self._filter_results(kept, top_n)

    @staticmethod
    def _relevant_to_query(title: str, query: str) -> bool:
        """结果标题是否与查询相关：任一长度 ≥2 的查询词元出现在标题里即相关。
        查询无有效词元时放行（没法校验，交给上层取舍）。"""
        import re as _re

        t = _re.sub(r"\s+", "", title or "")
        if not t:
            return False
        terms = [x for x in _re.split(r"\s+", (query or "").strip()) if len(x) >= 2]
        if not terms:
            return True
        return any(term in t for term in terms)

    @staticmethod
    def _is_360_self_service(url: str) -> bool:
        """360 自家内容服务（wenku/wenda/ai/xinwen 等）不作为来源；
        www.so.com/link 跳转链除外（那是通往外部真实页面的）。"""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.endswith("so.com"):
            return not parsed.path.startswith("/link")
        return host.endswith("360.cn")

    @staticmethod
    def _decode_eval(raw: str):
        """从 evaluate_script 返回文本解出 JSON 值。

        mcp 返回形如：```json\n<payload>\n```，payload 可能是真 JSON，
        也可能被再编码一层的 JSON 字符串。两种都兼容。
        """
        import json

        body = raw
        fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        if fence:
            body = fence.group(1).strip()
        try:
            val = json.loads(body)
        except Exception:  # noqa: BLE001
            return None
        if isinstance(val, str):  # 双重编码
            try:
                val = json.loads(val)
            except Exception:  # noqa: BLE001
                return None
        return val

    @staticmethod
    def _query_matches(box_value: str, query: str) -> bool:
        """搜索框值与查询词是否对应。框值为空（垃圾页/旧 DOM 没有搜索框）判不匹配；
        否则任一长度 ≥2 的查询词元出现在框值里即匹配（必应可能改写查询，不做全等）。"""
        import re as _re

        box = _re.sub(r"\s+", "", box_value or "")
        if not box:
            return False
        terms = [t for t in _re.split(r"\s+", (query or "").strip()) if len(t) >= 2]
        if not terms:
            return True  # 查询本身太短没法校验，放行交给结果过滤
        return any(t in box or box in t for t in terms)

    @classmethod
    def _parse_search_payload(cls, raw: str) -> dict | None:
        """解析 {q, results} 结构（q=搜索框当前值，用于校验结果对应当前查询）"""
        val = cls._decode_eval(raw)
        if isinstance(val, dict):
            return val
        if isinstance(val, list):  # 兼容旧结构（直接返回数组）
            return {"q": "", "results": val}
        return None

    @staticmethod
    def _filter_results(results: list, top_n: int) -> list[dict]:
        """过滤搜索引擎自身 + 常见非攻略垃圾域名（直播/电商/广告/邮箱/登录）"""
        out: list[dict] = []
        seen: set[str] = set()
        skip = (
            "bing.com", "microsoft.com", "msn.com", "outlook", "hotmail",
            "kuaishou.com", "e.kuaishou", "creator.", "ad.", "niu.",
            "live.", "login.", "passport.",
        )
        for item in results if isinstance(results, list) else []:
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            host = urlparse(url).netloc.lower()
            if not url or url in seen or any(h in host or h in url for h in skip):
                continue
            seen.add(url)
            out.append({"title": title, "url": url})
            if len(out) >= top_n:
                break
        return out

    async def scroll_and_read(self, times: int = 3) -> str:
        """滚动分批读取长页面，合并去重后返回"""
        chunks = [self._snapshot_to_text(self._last_snapshot)]
        for _ in range(times):
            await self.chrome.call(
                "evaluate_script",
                {"function": "() => { window.scrollBy(0, window.innerHeight * 2); }"},
            )
            await asyncio.sleep(1.0)
            snapshot = await self.chrome.call("take_snapshot", {})
            chunks.append(self._snapshot_to_text(snapshot))
        self._last_snapshot = ""
        seen: set[str] = set()
        merged: list[str] = []
        for chunk in chunks:
            for line in chunk.splitlines():
                if line.strip() and line not in seen:
                    seen.add(line)
                    merged.append(line)
        return "\n".join(merged)

    async def find_and_click(self, description: str, url: str = "") -> PageResult:
        """两步交互：LLM 从快照定位 uid → Action Guard → click(uid)"""
        snapshot = self._last_snapshot or await self.chrome.call("take_snapshot", {})
        target = self._locate_uid(snapshot, description)
        if target is None:
            return PageResult(status="blocked", reason=f"快照中找不到匹配元素: {description}")
        uid, target_text, target_href = target

        # 第二层：元素判定
        guard = judge_action("click", target_text=target_text, target_href=target_href, url=url)
        if guard.decision == Decision.BLOCK:
            return PageResult(status="blocked", reason=guard.reason)
        if guard.decision == Decision.REQUIRE_HANDOFF:
            return PageResult(status="need_user_handoff", reason=guard.reason)

        await self.chrome.call("click", {"uid": uid})
        await asyncio.sleep(1.5)
        return PageResult(status="ok", reason=f"已点击: {target_text}")

    # 携程酒店列表卡片抽取（Phase 6）。卡片异步渲染，snapshot 抓不全，
    # 用 evaluate_script 直读 DOM。选择器 `.list-item` 为线上实测，
    # 站点改版时返回空列表，由上层回退整页快照路径。
    CTRIP_CARDS_JS = r"""
() => {
  const cards = [...document.querySelectorAll('[class*="list-item"]')]
  const out = []
  for (const c of cards) {
    const lines = (c.innerText || '').split('\n').map(s => s.trim()).filter(Boolean)
    if (lines.length < 2) continue
    const name = lines[0]
    if (!name || name.length < 2 || name.includes('¥')) continue
    const pm = (c.innerText || '').match(/¥\s*([\d,]+)/)
    const img = [...c.querySelectorAll('img')].map(i => i.src || i.getAttribute('data-src') || '')
      .find(u => u && u.startsWith('http')) || ''
    out.push({
      name,
      ad: lines.includes('广告'),
      score: lines.find(s => /^\d\.\d$/.test(s)) || '',
      review: lines.find(s => s.includes('点评')) || '',
      loc: (lines.find(s => s.includes('查看地图')) || '').replace('查看地图', ''),
      price: pm ? '¥' + pm[1] : '',
      img,
    })
  }
  return JSON.stringify(out)
}
"""

    async def extract_ctrip_hotels(self, attempts: int = 5) -> list[dict]:
        """轮询等待卡片渲染并抽取。拿不到 ≥3 张卡时重试，最终失败返回 []。"""
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(2.5)
            try:
                raw = await self.chrome.call("evaluate_script", {"function": self.CTRIP_CARDS_JS})
            except Exception:  # noqa: BLE001 — 单次执行失败继续重试
                continue
            val = self._decode_eval(raw)
            if isinstance(val, list) and len(val) >= 3:
                return [v for v in val if isinstance(v, dict)]
        return []

    # 携程城市 ID 动态解析（Phase 8）：在携程页面上下文直调其城市建议接口
    # getHotelKeywords（CORS 允许 hotels.ctrip.com 源）。UI 自动化不可行：
    # 建议下拉的点击处理器校验 isTrusted，合成事件无效；a11y 树里建议项是
    # StaticText，mcp click 过不了可交互性检查（踩了一圈坑后的最优解）。
    @staticmethod
    def _city_suggest_js(city: str) -> str:
        import json as _json

        return (
            "async () => {"
            f" const CITY = {_json.dumps(city, ensure_ascii=False)};"
            " const body = {queryInfo: {keyword: CITY, actionType: 'destination'},"
            "   head: {platform: 'PC', cver: '0', bu: 'HBU', group: 'ctrip', locale: 'zh-CN',"
            "          region: 'CN', timezone: '8', currency: 'CNY', isSSR: false, extension: []}};"
            " const res = await fetch('//m.ctrip.com/restapi/soa2/34951/getHotelKeywords',"
            "   {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});"
            " const data = await res.json();"
            " const kws = (((data || {}).data || {}).mainKeywordList || {}).keywords || [];"
            " for (const k of kws) {"
            "   const info = ((k || {}).keyword || {}).keywordContentInfo || {};"
            "   if (info.typeName === '城市' && (info.keyword || '').includes(CITY)) {"
            "     return JSON.stringify({id: info.keywordId, name: info.keyword});"
            "   }"
            " }"
            " return JSON.stringify({id: null});"
            "}"
        )

    async def resolve_ctrip_city(self, city: str) -> int | None:
        """查携程城市建议接口，返回数字城市 ID；查不到/失败返回 None。"""
        page = await self.open_page("https://hotels.ctrip.com/hotels/listPage?city=2")
        if page.status != "ok":
            return None
        try:
            raw = await self.chrome.call(
                "evaluate_script", {"function": self._city_suggest_js(city)}
            )
        except Exception:  # noqa: BLE001
            return None
        val = self._decode_eval(raw)
        if isinstance(val, dict) and isinstance(val.get("id"), int):
            return val["id"]
        return None

    async def _vision_page_type(self) -> str | None:
        """截图 → 视觉判页面类型。任何失败返回 None（调用方只做对照，不依赖它）。

        实测（3 个真实页面）：截图 0.0–0.1s、推理 1.2–1.7s、in=471 token —— 比现有
        `_detect_page_type`（喂 3000 字给 v4-flash）更便宜。而且在知乎那条上更准：
        文本链路把一个 55 字的 JSON 错误页判成 `content` 放行了，视觉判 `error`
        并给出理由「页面显示的是 JSON 格式的错误信息」。
        """
        from app.agent import vision

        if not vision.enabled() or not settings.vision_page_type_enabled:
            return None
        import os
        import tempfile

        path = os.path.join(tempfile.gettempdir(), f"vpt_{os.getpid()}.jpg")
        try:
            await self.screenshot_to_file(path)
            data = await asyncio.to_thread(lambda: open(path, "rb").read())
            got = await asyncio.to_thread(vision.judge_page_image, data, "image/jpeg")
            return got.page_type if got else None
        except Exception:  # noqa: BLE001 — 对照通道绝不能影响主判定
            logger.warning("vision page type failed", exc_info=True)
            return None
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    async def screenshot(self) -> str:
        return await self.chrome.call("take_screenshot", {})

    async def screenshot_to_file(self, path: str) -> None:
        """把当前页截图存盘（Phase 5：登录页截图直播给前端扫码用）"""
        await self.chrome.call(
            "take_screenshot", {"filePath": path, "format": "jpeg", "quality": 60}
        )

    # ---------- 内部方法 ----------

    # 滑块/拖动类验证码的文案特征（远程模式无法操作，必须与可扫码的登录墙区分开）
    CAPTCHA_MARKERS = ("拖动滑块", "拖动下方滑块", "完成下方验证", "安全验证", "访问异常", "请进行验证")

    def _rule_page_type(self, url: str, text_head: str) -> str | None:
        """规则快判。返回 None = 规则拿不准，需要模型兜底。

        Phase 105 从 `_detect_page_type` 里抽出来（不是新逻辑，一字未改）：
        调用方要据此决定**要不要跑视觉对照**——规则已经确定的页面跑视觉是纯浪费。
        """
        path = url.lower()
        if any(p in path for p in ("/verify", "/captcha", "wappass.")):
            return "captcha"
        if any(m in text_head for m in self.CAPTCHA_MARKERS):
            return "captcha"
        if any(p in path for p in ("/login", "/signin", "/passport", "/register")):
            return "login_wall"
        # 规则快判（Phase 11）：正文足够长且无登录/验证特征词 → 直接判 content，
        # 跳过每页一次的 LLM 分类调用（8 页 × 1-3s）
        if len(text_head) > 1500 and not any(
            m in text_head for m in ("请登录", "立即登录", "登录后", "扫码登录", "登录/注册", "sign in to")
        ):
            return "content"
        if any(p in path for p in ("/pay", "/checkout", "/payment")):
            return "payment"
        return None

    async def _detect_page_type(self, url: str, text_head: str) -> str:
        """第三层检测：URL pattern / 文案特征快判 + LLM 兜底"""
        rule = self._rule_page_type(url, text_head)
        if rule is not None:
            return rule
        try:
            result = get_llm().classify(
                f"判断以下网页的类型。\n\nURL: {url}\n\n页面开头内容:\n{text_head}",
                PageClassification,
                system="你是网页类型判定助手。login_wall 指必须登录才能看到主要内容的页面；"
                "页面只是带登录按钮但内容可见时应判为 content/hotel/guide。",
            )
            return result.page_type
        except Exception:  # noqa: BLE001 — LLM 失败时保守返回 unknown，继续浏览
            return "unknown"

    @staticmethod
    def _snapshot_to_text(snapshot: str) -> str:
        """从可访问性树提取可读文本 + 超长截断。

        Phase 96：此前这个函数**名不副实**——docstring 写着「提取正文」，函数体只做了
        头部截断，喂给模型的是带 uid / role / `level="1"` 属性 / 嵌套缩进的 a11y 树原文。
        而 a11y 树里父节点 label 与子 StaticText **必然重复**（`link "登录"` 下面紧跟
        `StaticText "登录"`），冗余极大。现在真正做提取（`app.agent.reducers.reduce_a11y`，
        纯 stdlib、零模型调用）：真机快照实测去哪儿 31144→4324（-86%）、必应 8896→3130（-65%）、
        百度百科 995→203（-80%），结构残留为 0。

        契约不变：返回字符串、超 `max_snapshot_chars` 仍截断并带 `[截断]` 标记。
        裁剪不适用或失败时原样返回，不抛异常。
        """
        from app.agent.reducers import reduce_a11y

        text = reduce_a11y(snapshot).text
        if len(text) > settings.max_snapshot_chars:
            text = text[: settings.max_snapshot_chars] + "\n...[截断]"
        return text

    @staticmethod
    def _extract_title_url(snapshot: str, fallback_url: str) -> tuple[str, str]:
        # 兼容两种格式：`Page Title: xxx` 头部，或可访问性树的 RootWebArea "xxx"
        title_m = re.search(r"Page Title:\s*(.+)", snapshot) or re.search(
            r'RootWebArea\s+"([^"]+)"', snapshot
        )
        url_m = re.search(r"Page URL:\s*(\S+)", snapshot)
        return (
            title_m.group(1).strip() if title_m else "",
            url_m.group(1).strip() if url_m else fallback_url,
        )

    @staticmethod
    def _locate_uid(snapshot: str, description: str) -> tuple[str, str, str] | None:
        """从快照中定位元素 uid。先做精确文字匹配，匹配不到再用 LLM。

        snapshot 行格式形如: uid=1_23 link "东京酒店预订" /hotel/123
        """
        desc_lower = description.lower()
        for line in snapshot.splitlines():
            m = re.search(r'uid=(\S+).*?"([^"]*)"', line)
            if m and desc_lower in m.group(2).lower():
                href_m = re.search(r'"\s+(\S*/\S*)\s*$', line)
                return m.group(1), m.group(2), href_m.group(1) if href_m else ""
        return None
