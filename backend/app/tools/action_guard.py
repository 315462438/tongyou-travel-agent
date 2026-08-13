"""Action Guard v1 —— 三层判定（评审 🔴4）

第一层（动作分层）：navigate/snapshot/screenshot/scroll → 永远 ALLOW，不看 page_text
第二层（元素判定）：仅 click/fill 检查目标元素自身文字 + href/URL
第三层（页面状态检测）：导航后独立执行，由 BrowserTool.detect_page_type() 调用 LLM 判定

误报修正核心：绝不拿整页文本做关键词匹配。
"""

from dataclasses import dataclass
from urllib.parse import urlparse


class Decision:
    ALLOW = "allow"
    REQUIRE_HANDOFF = "require_handoff"
    BLOCK = "block"


# 第一层：只读动作，永远放行
READ_ONLY_ACTIONS = {"navigate", "snapshot", "screenshot", "scroll", "wait", "read"}

# 第二层：高危 —— 目标元素文字（点击/填写目标本身，不是整页）
HIGH_RISK_KEYWORDS = [
    "支付", "付款", "提交订单", "确认付款", "立即预订并支付", "下单",
    "pay now", "checkout", "place order", "confirm payment", "book and pay",
]
HIGH_RISK_URL_PATTERNS = ["/pay", "/checkout", "/payment", "/order/confirm", "/booking/confirm"]

# 第二层：中危 —— 需要用户接管
MEDIUM_RISK_KEYWORDS = [
    "登录", "注册", "验证码", "手机号", "身份证", "护照",
    "login", "sign in", "sign up", "verify", "captcha",
]

# 例外白名单（精确匹配）：登录方式切换 tab（如携程登录页的「扫码登录」）。
# 只切换登录框的展示形态，不输入凭据、不提交任何东西——是登录 handoff 流程
# 自身的一环（把二维码翻出来给用户扫），必须允许自动执行。
LOGIN_METHOD_TOGGLE_TEXTS = {"扫码登录", "二维码登录"}
MEDIUM_RISK_URL_PATTERNS = ["/login", "/signin", "/register", "/passport", "/verify", "/captcha"]

# 第三层：页面类型 → 处置（detect_page_type 之后使用）
PAGE_TYPE_DISPOSITION = {
    "login_wall": Decision.REQUIRE_HANDOFF,
    "captcha": Decision.REQUIRE_HANDOFF,
    "payment": Decision.BLOCK,
}


@dataclass
class GuardResult:
    decision: str
    risk_level: str
    reason: str


def _match_any(text: str, keywords: list[str]) -> str | None:
    lower = text.lower()
    for k in keywords:
        if k.lower() in lower:
            return k
    return None


def _url_match(url: str, patterns: list[str]) -> str | None:
    path = urlparse(url).path.lower() if url else ""
    for p in patterns:
        if p in path:
            return p
    return None


def judge_action(
    action: str,
    *,
    target_text: str = "",
    target_href: str = "",
    url: str = "",
) -> GuardResult:
    """判定一个浏览器动作。

    action:      navigate/snapshot/screenshot/scroll/read/click/fill
    target_text: 点击/填写目标元素自身的可见文字（不是整页文本！）
    target_href: 目标元素的链接地址（如有）
    url:         当前页面 URL
    """
    # 第一层：只读动作直接放行
    if action in READ_ONLY_ACTIONS:
        return GuardResult(Decision.ALLOW, "low", "只读浏览动作，自动执行")

    if action not in {"click", "fill"}:
        return GuardResult(Decision.BLOCK, "high", f"未知动作类型: {action}")

    # 第二层：检查目标元素本身
    combined_url = f"{target_href} {url}"

    hit = _match_any(target_text, HIGH_RISK_KEYWORDS) or _url_match(
        target_href, HIGH_RISK_URL_PATTERNS
    )
    if hit:
        return GuardResult(Decision.BLOCK, "high", f"目标涉及支付/下单（命中: {hit}），禁止自动执行")

    if action == "click" and target_text.strip() in LOGIN_METHOD_TOGGLE_TEXTS:
        return GuardResult(Decision.ALLOW, "low", "登录方式切换 tab（不输入不提交），允许自动执行")

    hit = _match_any(target_text, MEDIUM_RISK_KEYWORDS) or _url_match(
        combined_url, MEDIUM_RISK_URL_PATTERNS
    )
    if hit:
        return GuardResult(
            Decision.REQUIRE_HANDOFF, "medium", f"目标涉及登录/验证码/个人信息（命中: {hit}），需要用户接管"
        )

    return GuardResult(Decision.ALLOW, "low", "普通交互动作，允许自动执行")


def judge_page_type(page_type: str) -> GuardResult:
    """第三层：导航后按页面类型处置。"""
    disposition = PAGE_TYPE_DISPOSITION.get(page_type)
    if disposition == Decision.REQUIRE_HANDOFF:
        return GuardResult(disposition, "medium", f"当前页面为 {page_type}，需要用户手动处理")
    if disposition == Decision.BLOCK:
        return GuardResult(disposition, "high", f"当前页面为 {page_type}，禁止自动操作")
    return GuardResult(Decision.ALLOW, "low", f"页面类型 {page_type}，正常浏览")
