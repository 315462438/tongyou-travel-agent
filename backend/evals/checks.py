"""输出质量检查器（2026-08-04）。

全部是**规则化纯函数**——不做 LLM 打分：打分贵、会漂移，而且用它当回归闸门时，
分数波动到底是模型抖动还是真的退化根本分不清。

每个检查项都对应本周真实修过的一个 bug（见 docs/task_plans/输出质量回归评估集-2026-08-04.md）。
新增检查项的门槛：**必须是线上真实翻过车的形态**，不做臆想的规范检查。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Finding:
    code: str
    detail: str
    level: str = "error"  # error=硬伤 / warn=可疑


@dataclass
class Query:
    id: str
    text: str
    category: str = "single"
    cities: list[str] = field(default_factory=list)
    min_days: int = 0
    forbid_words: list[str] = field(default_factory=list)
    deep: bool = False
    note: str = ""


# ---------- 单项检查（每个都独立可测） ----------

_TRUNCATION_HINTS = ("触及长度上限", "已截断", "续写几轮后仍未写完")

# 「明显断裂」的结尾形态。用黑名单而不是白名单——正文以列表项/中文句子收尾
# 完全正常（`- 小红书｜成都攻略`），拿白名单判会大面积误报。
_BROKEN_TAIL = (
    (r"\*\*[^*\n]{0,24}$", "停在未闭合的 `**`"),          # 线上原样：`**人均（含`
    (r"[（(【\[「『][^）)】\]」』\n]{0,24}$", "停在未闭合的括号"),
    (r"[¥￥]\s*\d*$", "停在货币符号/半个金额"),
    (r"[，、：；]\s*$", "停在中文逗号/顿号（句子没写完）"),
)


def check_truncated(guide: str) -> list[Finding]:
    """守 2026-08-04：多城 7 天攻略被从「**人均（含」这种半句处硬切断。"""
    out: list[Finding] = []
    if any(h in guide for h in _TRUNCATION_HINTS):
        out.append(Finding("truncated", "正文里带「已截断/仍未写完」提示"))
    tail = guide.rstrip()
    if not tail:
        return out
    for pattern, why in _BROKEN_TAIL:
        if re.search(pattern, tail):
            out.append(Finding("truncated", f"{why}：…{tail[-24:]!r}", level="warn"))
            break
    # 表格最后一行没闭合竖线 = 从表格中间切断
    last = tail.split("\n")[-1].strip()
    if last.startswith("|") and not last.endswith("|"):
        out.append(Finding("truncated", f"停在表格行中间：{last[:40]!r}", level="warn"))
    return out


def check_days(guide: str, min_days: int) -> list[Finding]:
    if min_days <= 0:
        return []
    found = {int(m.group(1)) for m in re.finditer(r"Day\s*(\d+)", guide)}
    missing = [d for d in range(1, min_days + 1) if d not in found]
    if missing:
        return [Finding("missing_days", f"缺少 Day {'、'.join(map(str, missing))}")]
    return []


def check_broken_table(guide: str) -> list[Finding]:
    """守 2026-07-30：兜底插图插进表格行之间，后续行退化成裸 `| … |` 文本。

    真表格会被 Markdown 渲染掉；正文里出现**孤立的**竖线行就是断掉的表格。
    判据：某行以 `|` 开头，但它前一行不是表格行（说明表格被打断后重新开始）。
    """
    lines = guide.split("\n")
    bad: list[str] = []
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        prev = lines[i - 1].lstrip() if i else ""
        nxt = lines[i + 1].lstrip() if i + 1 < len(lines) else ""
        # 表格块的合法开头：下一行是分隔行（|---|）。既非块首也接不上前一行 = 碎片
        if not prev.startswith("|") and not re.match(r"^\|[\s:|-]+\|", nxt):
            bad.append(line.strip()[:40])
    return [Finding("broken_table", f"发现 {len(bad)} 处断裂的表格行：{bad[:2]}")] if bad else []


def check_placeholder_leak(guide: str) -> list[Finding]:
    """守 2026-07-30：`[img:小红书灵感·📍…✔️·2]` 原样漏进正文。"""
    leaks = re.findall(r"\[\[?img[:：][^\]]{0,60}\]?\]", guide)
    return [Finding("img_placeholder_leak", f"{len(leaks)} 处：{leaks[:2]}")] if leaks else []


# 前端 `interaction.ts` 的 prepareMarkdown 能修好的形态：**单行内配对**的加粗。
# 它往里塞零宽空格，让 `**` 重新满足 GFM 的 left/right-flanking 规则。
_PAIRED_BOLD = re.compile(r"\*\*[^*\n]+?\*\*")


def check_raw_bold(guide: str) -> list[Finding]:
    """守 2026-07-30：CJK 标点紧邻 `**` 时强调不成立，星号裸奔。

    **必须检「渲染后的产物」，不是库里的原始 markdown。**
    修复 2026-08-04：原实现直接对原文匹配 `[，。、；：！？）】」]\\*\\*[^\\s*]`，把
    `；**巴公房子**：` 这类**配对完好**的加粗全判成硬伤——而三个渲染入口
    （Home.tsx / Trips.tsx ×2）都会先过 `prepareMarkdown()` 补零宽空格，用户看到的是
    正常加粗。实测线上三条攻略被误报 5/3/7 处，闸门 0/3 全红，全是假阳性。
    （注：不能"套一遍变换再用老正则"——U+200B 不属于 Python `\\s`，照样命中。）

    现在的判据：把 prepareMarkdown 能修好的配对加粗整段剔除，**剩下的 `**` 才是渲染后
    仍会原样显示的**——即未闭合的（`**人均（含`，07-30 那个真 bug 的形态）
    与跨行的（`[^*\\n]` 修不了）。
    """
    residue = _PAIRED_BOLD.sub("", guide)
    hits = re.findall(r"\*\*", residue)
    if not hits:
        return []
    return [Finding("raw_bold_marker",
                    f"{len(hits)} 处无法配对的 `**`（prepareMarkdown 修不掉，会原样显示）")]


def check_swallowed_price(guide: str) -> list[Finding]:
    """守 2026-07-30：`¥400~600` 的两个 `~` 被 GFM 配成删除线，吞掉中间文字
    → 渲染成 `¥400600`。判据：金额位数异常多（6 位以上且非千分位写法）。"""
    hits = [m.group(0) for m in re.finditer(r"[¥￥]\s?\d{6,}(?![\d,])", guide)]
    return [Finding("swallowed_price_range", f"疑似被吞的价格区间：{hits[:3]}")] if hits else []


def check_destination(guide: str, cities: list[str]) -> list[Finding]:
    missing = [c for c in cities if c and c not in guide]
    return [Finding("destination_missing", f"正文未提及：{missing}")] if missing else []


def check_forbidden(guide: str, words: list[str]) -> list[Finding]:
    hits = [w for w in words if w and w in guide]
    if not hits:
        return []
    code = "unrequested_holiday" if any(h in ("国庆", "春节", "元旦", "五一") for h in hits) \
        else "internal_jargon"
    return [Finding(code, f"出现了不该出现的词：{hits}")]


_INTERNAL_JARGON = ("本轮参考资料", "参考资料中不含", "本轮抓取", "未抓取到携程")


def check_internal_jargon(guide: str) -> list[Finding]:
    """守 2026-07-30：住宿章节对用户说「因本轮参考资料中不含携程实时酒店列表」。"""
    hits = [w for w in _INTERNAL_JARGON if w in guide]
    return [Finding("internal_jargon", f"把内部实现讲给用户：{hits}")] if hits else []


_SAFE_IMG_PREFIX = ("/travel/api/img", "/api/img", "/travel/api/staticmap", "/api/staticmap")


def check_foreign_image(guide: str) -> list[Finding]:
    """守 Phase 69：正文里的图片必须走本站代理（数据外带防护）。"""
    urls = [m.group(1) for m in re.finditer(r"!\[[^\]]*\]\(\s*([^)\s]+)", guide)]
    bad = [u for u in urls if not u.startswith(_SAFE_IMG_PREFIX)]
    return [Finding("foreign_image", f"站外图片 {len(bad)} 张：{bad[:2]}")] if bad else []


def check_basics(guide: str, min_chars: int = 600) -> list[Finding]:
    out: list[Finding] = []
    if len(guide.strip()) < min_chars:
        out.append(Finding("too_short", f"正文仅 {len(guide.strip())} 字"))
    if "参考来源" not in guide:
        out.append(Finding("no_sources", "缺少「参考来源」章节", level="warn"))
    return out


# ---------- 汇总 ----------

def run_checks(guide: str, q: Query) -> list[Finding]:
    """对一条攻略正文跑全部检查，返回全部 Finding（空 = 通过）。"""
    findings: list[Finding] = []
    findings += check_truncated(guide)
    findings += check_days(guide, q.min_days)
    findings += check_broken_table(guide)
    findings += check_placeholder_leak(guide)
    findings += check_raw_bold(guide)
    findings += check_swallowed_price(guide)
    findings += check_destination(guide, q.cities)
    findings += check_forbidden(guide, q.forbid_words)
    findings += check_internal_jargon(guide)
    findings += check_foreign_image(guide)
    findings += check_basics(guide)
    return findings
