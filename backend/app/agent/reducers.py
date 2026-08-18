"""工具输出按结构裁剪（Phase 96，借鉴 dsh 社区插件 toolshrink）

Phase 90 的 `truncate.py` 解决的是「截断本身要幂等」，没解决「**截哪里**」——
仍然按位置下刀。而按位置下刀在网页上有个要命的后果：**前面全是导航**。

实测维基百科「西湖」词条（生产参数 limit=4000）：喂给模型的 4000 字里
**3681 字是导航和目录，正文只有 319 字，有效率 8%**。预算再大也先被 chrome 吃掉。

这里按**结构**下刀：认出内容格式，套一条人写死的规则。注意「语义」不是"理解内容"，
而是"**认得这是什么格式**"——判断力是人在写 reducer 时付出的，运行时只是模式匹配。
所以**零模型调用、零额外延迟**（用 LLM 压缩会把省下的时间还回去）。

纯 stdlib（`html.parser` + `html.unescape`），**不引入任何新依赖**——服务器内存本来就紧。

## 不变式

1. **幂等**：`reduce(reduce(x)) == reduce(x)`。链路里会多次截断，不幂等就成头尾拼盘。
2. **只删不改**：绝不重写词句——那就是编造。唯一例外是 HTML 实体解码，见 `_unescape`。
3. **可回取**：裁剪只影响**预览**；原文照旧全量 spill 到 `source_store`，`read_source` 可翻页。
4. **失败退化**：抛任何异常都退回调用方的兜底截断，绝不影响主流程。
5. **留痕**：`Reduction.dropped/kind` 是排查时区分「原文就短」与「被裁过」的唯一依据。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# 整块丢弃的标签：内容对正文零贡献
_DROP_TAGS = frozenset({
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "select", "option", "button", "svg", "iframe", "template",
})

# class/id 命中即整块丢弃。故意保守——宁可漏掉一块导航，也不能吃掉正文。
# ⚠️ 不含 `ad`：它太短，会命中 `header`/`shadow`/`gradient` 之类，得不偿失。
_DROP_ATTR = re.compile(
    r"(?:^|[\s_-])(?:nav|navbar|menu|sidebar|side-bar|footer|masthead|breadcrumb|"
    r"toc|catalog|comment|comments|advert|advertisement|banner|popup|modal|cookie|"
    r"subscribe|share|related|recommend|widget|pagination|skip)(?:$|[\s_-])",
    re.I,
)

# **永不**按属性丢弃的结构性根元素。
# 踩过的坑：维基百科的 <html> 带 class `vector-feature-toc-pinned-clientpref-1`，
# 其中 `-toc-` 命中上面的规则 → 整个文档被当成导航丢光，产出为空。
# 根元素的 class 是页面级特性开关，跟"这块是不是导航"毫无关系。
_NEVER_DROP_BY_ATTR = frozenset({"html", "body", "main", "article"})

# 章节标题：前后补换行，让模型看得出结构
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

# 各占一行的块级元素
_BLOCKS = frozenset({
    "p", "li", "tr", "div", "section", "article", "blockquote", "pre",
    "dt", "dd", "figcaption", "caption", "td", "th", "br",
})

# 引用角标：维基那种 [12] / [註 1] / [注 3]，对旅行规划零价值且密集
_REF_MARK = re.compile(r"\[\s*(?:註|注|注释|註釋|ref)?\s*\d{1,3}\s*\]")

# a11y 快照的真实一行（chrome-devtools-mcp）形如：
#   uid=6_9 link "返回首页" description="去哪儿旅游搜索引擎 Qunar.com"
#   uid=6_13 listitem "" level="1"
#   uid=6_2 tooltip "请按…" focusable focused
# 规律：**可读内容全在引号里**，引号外一律是结构（uid / role / key="v" 属性 / 状态标志 / URL）。
# 所以取 label 就够了，不必逐类去剥——这是看了真机快照后才定下来的做法。
_A11Y_HINT = re.compile(r"uid=\S+|RootWebArea")
# 节点 label 是**不以 `=` 开头**的那个引号段。必须排除 `key="value"` 形式的属性值，
# 否则 `listitem "" level="1"` 会把属性值 `1` 当成内容（真机快照上踩到过：满屏孤零零的 "1"）。
_A11Y_LABEL = re.compile(r'(?<!=)"((?:[^"\\]|\\.)*)"')
# MCP 响应自带的 markdown 小标题（`# take_snapshot response` / `## Page content`）：
# 没有引号但要保留，它标示了快照的分段。
_A11Y_SECTION = re.compile(r"^\s*#{1,6}\s+\S")
# 零宽/不可见字符：在快照里会独占一行，纯噪声
_INVISIBLE = re.compile(r"[​-‏  ﻿­]")

# 多余空白/空行
_WS = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")


@dataclass
class Reduction:
    """一次裁剪的结果。`dropped` 是相对**输入**少了多少字符（可能为 0）。"""

    text: str
    dropped: int
    kind: str

    @property
    def ratio(self) -> float:
        total = len(self.text) + self.dropped
        return (self.dropped / total) if total else 0.0


def _unescape(text: str) -> str:
    """HTML 实体解码。

    这是「只删不改」的**唯一例外**，理由：`&#91; 註 1 &#93;` 是同一段文字的转义形态，
    解码是**无损还原**而不是改写；不解码等于把原文的错误形态喂给模型（实测维基正文里
    满屏都是）。除此之外本模块不改写任何一个字。
    """
    return unescape(text or "")


def _tidy(text: str) -> str:
    """折叠空白、压缩空行、去首尾。幂等。"""
    out = _WS.sub(" ", text or "")
    out = "\n".join(line.strip() for line in out.split("\n"))
    out = _BLANKS.sub("\n\n", out)
    return out.strip()


class _Extractor(HTMLParser):
    """把 HTML 抽成带结构的纯文本：丢弃 chrome 容器，保留标题/段落/列表/表格行。

    用 stdlib 的 HTMLParser 而不是 DOM 库：它是**流式**的，遇到畸形标签不会炸
    （`convert_charrefs=True` 顺带做实体解码）。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0          # >0 表示正处在被丢弃的子树里
        self._skip_tag: str | None = None
        self._open: list[str] = []
        self._inline_boundary = False  # 刚跨过一个内联标签边界

    # ---------- 丢弃判定 ----------

    @staticmethod
    def _is_chrome(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in _DROP_TAGS:
            return True
        if tag in _NEVER_DROP_BY_ATTR:  # 根元素的 class 是页面级开关，不是"这块是导航"
            return False
        for key, val in attrs:
            if key in ("class", "id", "role") and val and _DROP_ATTR.search(val):
                return True
        return False

    # ---------- 钩子 ----------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            # 已在丢弃子树里：只需跟踪同名标签的嵌套深度
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if self._is_chrome(tag, attrs):
            self._skip_depth, self._skip_tag = 1, tag
            return
        self._open.append(tag)
        if tag in _HEADINGS:
            self.parts.append("\n\n")
        elif tag in _BLOCKS:
            self.parts.append("\n")
        else:
            self._inline_boundary = True

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag in _HEADINGS:
            self.parts.append("\n")
        elif tag not in _BLOCKS:
            self._inline_boundary = True
        while self._open and self._open.pop() != tag:
            pass  # 未闭合标签：弹到匹配为止，不追求严格性

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data.strip():
            return
        # 跨内联标签边界时补空格——但**只在两侧都是 ASCII 字母数字**时补。
        # 不补：`<span>Hotel</span><span>Booking</span>` 会粘成 `HotelBooking`；
        # 全补：`西<b>湖</b>` 会裂成 `西 湖`（中文本来就不用空格分词）。
        # 这条规则是真机数据逼出来的：去哪儿页面把「清除 / 历史 / 记录」拆在三个内联标签里。
        if self._inline_boundary and self.parts:
            prev = self.parts[-1][-1:] if self.parts[-1] else ""
            nxt = data.lstrip()[:1]
            if prev.isascii() and prev.isalnum() and nxt.isascii() and nxt.isalnum():
                self.parts.append(" ")
        self._inline_boundary = False
        self.parts.append(data)

    # HTMLParser 对畸形输入可能回调这些；空实现避免污染正文
    def handle_comment(self, data: str) -> None:
        pass

    def handle_decl(self, decl: str) -> None:
        pass

    def result(self) -> str:
        return "".join(self.parts)


def looks_like_html(text: str) -> bool:
    """认得这是不是 HTML。保守：明确的文档标签，或标签密度够高。"""
    head = (text or "")[:4000].lower()
    if not head:
        return False
    if "<html" in head or "<body" in head or "<!doctype html" in head:
        return True
    tags = len(re.findall(r"</?[a-z][a-z0-9]*[\s/>]", head))
    return tags >= 8 and tags * 12 >= len(head) / 10


def looks_like_a11y(text: str) -> bool:
    """认得这是不是浏览器可访问性快照。"""
    return bool(_A11Y_HINT.search((text or "")[:4000]))


# 裁剪后可读文字若不足朴素提取的这个比例，判定为「吃掉了正文」，退回朴素提取。
# 这是对付「某条 chrome 规则误伤整块正文」的兜底——那种 bug 一旦发生是**静默**的
# （产出看起来正常，只是内容少了），必须有自动检测。开发期实测踩过一次：维基的
# <html class="...-toc-..."> 让整页归零。
_UNDERSHOOT_RATIO = 0.15


def naive_text(raw: str) -> str:
    """朴素提取：去 script/style/标签 → 解码实体 → 折叠空白。

    两个用途：① `dropped` 的基线（拿原始 HTML 当基线会把"去标签"也算成省略，
    那是虚高的数字）；② reducer 过度裁剪时的退路。
    """
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return _tidy(_unescape(html))


def reduce_html(raw: str) -> Reduction:
    """HTML → 带结构的正文文本。异常一律退化为「原样返回」，由调用方兜底截断。"""
    src = raw or ""
    if not src:
        return Reduction("", 0, "empty")
    try:
        base = naive_text(src)          # 基线：朴素提取能拿到的可读文字
        parser = _Extractor()
        parser.feed(src)
        parser.close()
        text = _tidy(_REF_MARK.sub("", _unescape(parser.result())))
        if not text or (base and len(text) < len(base) * _UNDERSHOOT_RATIO):
            # 裁过头了（某条 chrome 规则误伤正文）→ 退回朴素提取，宁可不裁也不能吃掉内容
            logger.warning(
                "reduce_html undershoot: %d < %d*%.2f, falling back to naive",
                len(text), len(base), _UNDERSHOOT_RATIO,
            )
            return Reduction(base, 0, "html_undershoot_fallback")
        return Reduction(text, max(0, len(base) - len(text)), "html")
    except Exception:  # noqa: BLE001 — 裁剪是增强，绝不能让抓取链路失败
        logger.warning("reduce_html failed, falling back to raw", exc_info=True)
        return Reduction(src, 0, "html_error_fallback")


def reduce_a11y(raw: str) -> Reduction:
    """可访问性快照 → 可读文本。

    剥掉 `uid=xxx` 与 role 名，取出引号里的可读标签，丢掉无文字的纯结构节点，
    并把**连续重复行**折叠——导航在 a11y 树里常整块重复出现。
    """
    src = raw or ""
    if not src:
        return Reduction("", 0, "empty")
    if not looks_like_a11y(src):
        # **幂等的关键**：裁剪后的产物里已经没有 uid/RootWebArea，不再是 a11y 树。
        # 没有这道门，第二遍会把「没有引号的行」全判成结构节点丢光（真机数据上实测
        # reduce(reduce(x)) 只剩两行标题）。不认得就别动。
        return Reduction(src, 0, "a11y_not_applicable")
    try:
        out: list[str] = []
        prev = None
        for line in src.splitlines():
            if not line.strip():
                continue
            if _A11Y_SECTION.match(line):
                cleaned = line.strip()
            else:
                # 只取引号里的 label。没有引号 = 纯结构节点（generic/list/listitem…），整行丢弃。
                labels = [g for g in _A11Y_LABEL.findall(line) if g.strip()]
                if not labels:
                    continue
                # 一行可能有多个引号段（label + description="…"）：第一个是本节点的可读文字，
                # 其余是辅助属性值，通常与 label 重复或是站点营销语，只取第一个。
                cleaned = _INVISIBLE.sub("", labels[0]).strip()
            if not cleaned or cleaned == prev:
                # 连续重复只留一份。a11y 树里父节点 label 与子 StaticText **必然重复**
                # （`link "登录"` 下面紧跟 `StaticText "登录"`），这是最大的一块冗余。
                continue
            out.append(cleaned)
            prev = cleaned
        text = _tidy(_unescape("\n".join(out)))
        if not text:
            return Reduction(src, 0, "a11y_empty_fallback")
        return Reduction(text, max(0, len(src) - len(text)), "a11y")
    except Exception:  # noqa: BLE001
        logger.warning("reduce_a11y failed, falling back to raw", exc_info=True)
        return Reduction(src, 0, "a11y_error_fallback")


def reduce_auto(raw: str) -> Reduction:
    """按内容形态自动挑 reducer；都不认得就原样返回（由调用方兜底截断）。

    **认不得就别动**是有意的：误把纯文本当 HTML 裁一遍，风险远大于不裁的收益。
    """
    src = raw or ""
    if not src:
        return Reduction("", 0, "empty")
    if looks_like_a11y(src):
        return reduce_a11y(src)
    if looks_like_html(src):
        return reduce_html(src)
    return Reduction(src, 0, "plain")


def note(reduction: Reduction) -> str:
    """给裁剪结果加一句留痕。裁掉的量不显著时返回空串（别拿噪声打扰模型）。"""
    if reduction.dropped <= 0 or reduction.ratio < 0.15:
        return ""
    return f"\n\n[已按结构裁剪：省略约 {reduction.dropped} 字符的导航/样式/重复内容]"
