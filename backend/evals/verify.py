"""三层验证（2026-08-04，chapter8 机制①）。

    结果验证（环境真值）→ 过程验证（业务规则）→ 质量验证（Rubric 维度化）

书里强调的两点，这里都照做：
- **维度化输出而非单一总分**——质量验证给每个维度的通过/失败，不折成一个分数。
  一个分数掉了 0.1 没人知道该改哪；维度化才能直接落到修复动作。
- **evidence 必须是可核对的事实**，不是模型的判断。所有 evidence 都来自
  正文本身、消息 meta 或进度轨迹，任何人都能自己复核一遍。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from evals.checks import Query, run_checks


@dataclass
class VerificationResult:
    passed: bool
    reason: str
    evidence: dict = field(default_factory=dict)
    # 稳定机器码：给 compare.py 做前后对照用。reason 是给人看的散文，会随文案改动漂移，
    # 拿它当对照 key 会把「文案改了」误报成「出了新问题」。
    codes: list[str] = field(default_factory=list)
    # 不判失败、但需要人看一眼的信号（例如轨迹识别率下降）
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        """渲染成 VerificationResult(...) 的可读形态。"""
        lines = ["VerificationResult(", f"    passed={self.passed},", f"    reason={self.reason!r},"]
        if self.codes:
            lines.append(f"    codes={self.codes!r},")
        if self.warnings:
            lines.append("    warnings=[")
            lines += [f"        {w!r}," for w in self.warnings]
            lines.append("    ],")
        lines.append("    evidence={")
        for k, v in self.evidence.items():
            if isinstance(v, list) and len(v) > 1:
                lines.append(f"        {k!r}: [")
                lines += [f"            {x!r}," for x in v]
                lines.append("        ],")
            else:
                lines.append(f"        {k!r}: {v!r},")
        lines += ["    }", ")"]
        return "\n".join(lines)


# ---------- 轨迹 → 工具调用顺序 ----------

_STEP_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"理解你的旅行需求", "parse_request"),
    (r"复用了.*小红书资料", "reuse_recent_sources"),
    (r"已获取高德实时数据", "amap_city_brief"),
    (r"正在小红书搜索", "xhs_search"),
    (r"正在读第 \d+ 篇小红书笔记", "xhs_detail"),
    (r"检测到酒店需求.*携程|正在携程定位", "ctrip_hotels"),
    (r"跳过网页搜索", "web_search_skipped"),
    (r"正在搜索[:：]", "web_search"),
    (r"正在综合多个来源|正在生成你的旅行方案", "generate_guide"),
    (r"正在续写剩余部分", "continue_generation"),
    (r"正在补充资料", "research_more"),
)


# 少于这么多条进度就不判「模式过期」——轮次太短时轨迹本来就可能识别不出东西
_TRAIL_MIN = 3


def tool_sequence(progress_texts: list[str]) -> list[str]:
    """从进度轨迹还原本轮的工具调用顺序（连续重复的合并成一条）。"""
    seq: list[str] = []
    for text in progress_texts:
        for pattern, name in _STEP_PATTERNS:
            if re.search(pattern, text):
                if not seq or seq[-1] != name:
                    seq.append(name)
                break
    return seq


# ---------- 第一层：结果验证（环境真值） ----------

def verify_result(guide: str, meta: dict, q: Query) -> VerificationResult:
    """用户要的东西拿到了吗。真值取自产出物本身与实际抓到的来源。"""
    sources = meta.get("sources") or []
    days_found = sorted({int(m.group(1)) for m in re.finditer(r"Day\s*(\d+)", guide)})
    missing_days = [d for d in range(1, q.min_days + 1) if d not in days_found] if q.min_days else []
    missing_cities = [c for c in q.cities if c and c not in guide]
    truncated = any(h in guide for h in ("触及长度上限", "已截断", "续写几轮后仍未写完"))

    problems, codes = [], []
    if missing_days:
        problems.append(f"缺 Day {missing_days}")
        codes.append("res_missing_days")
    if missing_cities:
        problems.append(f"未覆盖 {missing_cities}")
        codes.append("res_missing_cities")
    if truncated:
        problems.append("正文被截断")
        codes.append("res_truncated")
    if not sources:
        problems.append("零来源")
        codes.append("res_no_sources")

    return VerificationResult(
        passed=not problems,
        reason="产出覆盖了用户要求的全部天数与城市，且有真实来源支撑"
        if not problems else "；".join(problems),
        codes=codes,
        evidence={
            "days_covered": days_found or "无 Day 结构",
            "days_required": q.min_days or "未指定",
            "cities_required": q.cities or "未指定",
            "cities_missing": missing_cities,
            "sources_count": len(sources),
            "source_sites": sorted({s.get("site") or "web" for s in sources}),
            "chars": len(guide),
            "truncated": truncated,
        },
    )


# ---------- 第二层：过程验证（业务规则） ----------

def verify_process(progress: list[str], meta: dict, q: Query) -> VerificationResult:
    """过程守没守住我们自己定的纪律。规则全部来自本周确立的设计约束。"""
    seq = tool_sequence(progress)
    sources = meta.get("sources") or []
    sites = {s.get("site") for s in sources}
    reused = "reuse_recent_sources" in seq
    all_text = "\n".join(progress)

    violations, codes, warnings = [], [], []
    # ① 复用命中时必应最多降到 light，不允许 skip（复用资料是上次那个问法抓的）
    if reused and "web_search_skipped" in seq:
        violations.append("复用来源后仍跳过了网页搜索（规则要求最多降到 light）")
        codes.append("proc_reuse_skipped_web")
    # ② 攻略类必须有内容型来源，不能只靠模型参数知识
    if q.category != "hotel" and not (sites & {"xhs", "web", None}) and not reused:
        violations.append("没有任何内容型来源")
        codes.append("proc_no_content_source")
    # ③ 不许把「判定不相关」说成站点风控（2026-08-01 误伤携程）
    if "风控" in all_text:
        violations.append("进度里出现无证据的「风控」归因")
        codes.append("proc_unfounded_riskcontrol")
    # ④ 不该在有明确目的地时反问
    if "想去哪里呢" in all_text and q.cities:
        violations.append("目的地明确却仍然反问")
        codes.append("proc_clarify_with_destination")
    # ⑤ 沿途中转轮不得复用终点城市的旧来源
    if q.category == "waypoint" and reused:
        violations.append("沿途中转轮复用了旧来源（语料不是一回事）")
        codes.append("proc_waypoint_reused")
    # ⑥ 元规则：轨迹识别不出来 = 这一层已经失效，必须报，不能静默放行。
    #    _STEP_PATTERNS 匹配的是进度气泡文案（很容易被顺手改掉），一旦全部落空，
    #    上面 5 条里依赖 seq 的规则会一条都打不着，整层退化成「无条件通过」。
    if len(progress) >= _TRAIL_MIN and not seq:
        violations.append(
            f"{len(progress)} 条进度轨迹一条都没匹配上 _STEP_PATTERNS——"
            "过程验证已失效（多半是进度文案改了，需同步更新模式）"
        )
        codes.append("proc_unrecognized_trail")
    elif len(progress) >= _TRAIL_MIN and "generate_guide" not in seq:
        warnings.append("轨迹里没识别到生成阶段（generate_guide），模式可能部分过期")

    return VerificationResult(
        passed=not violations,
        reason="调用顺序与降级策略均符合既定纪律" if not violations else "；".join(violations),
        codes=codes,
        warnings=warnings,
        evidence={
            "tool_sequence": seq,
            "reused_sources": reused,
            "web_search_skipped": "web_search_skipped" in seq,
            "continued_generation": "continue_generation" in seq,
            "progress_steps": len(progress),
        },
    )


# ---------- 第三层：质量验证（Rubric，维度化） ----------

_RUBRIC = {
    "排版完整性": ("broken_table", "img_placeholder_leak", "raw_bold_marker"),
    "数据可读性": ("swallowed_price_range",),
    "内容完整性": ("truncated", "missing_days", "too_short"),
    "上下文纪律": ("unrequested_holiday", "internal_jargon"),
    "安全合规": ("foreign_image",),
    "来源可溯": ("no_sources", "destination_missing"),
}


def verify_quality(guide: str, q: Query) -> VerificationResult:
    """维度化 Rubric——**不折成单一总分**：分数掉了没人知道该改哪。"""
    findings = run_checks(guide, q)
    by_code: dict[str, list[str]] = {}
    for f in findings:
        by_code.setdefault(f.code, []).append(f.detail)

    dims: dict[str, str] = {}
    failed_dims, codes = [], []
    for dim, dim_codes in _RUBRIC.items():
        hit = [c for c in dim_codes if c in by_code]
        if hit:
            dims[dim] = f"FAIL（{'、'.join(hit)}）"
            failed_dims.append(dim)
            codes.append(f"qual_{dim}")
        else:
            dims[dim] = "PASS"

    return VerificationResult(
        passed=not failed_dims,
        reason="全部质量维度通过" if not failed_dims else f"{len(failed_dims)} 个维度不达标：{failed_dims}",
        codes=codes,
        evidence={
            **dims,
            "findings": [f"{f.code}: {f.detail}" for f in findings] or "无",
        },
    )


# ---------- 汇总成一份报告 ----------

def verify_all(guide: str, meta: dict, progress: list[str], q: Query) -> dict:
    """跑完三层，返回结构化结果——快照要存它，compare.py 才对照得了过程层。"""
    layers = {
        "result": verify_result(guide, meta, q),
        "process": verify_process(progress, meta, q),
        "quality": verify_quality(guide, q),
    }
    return {
        "passed": all(v.passed for v in layers.values()),
        "failed_layers": [k for k, v in layers.items() if not v.passed],
        "codes": [c for v in layers.values() for c in v.codes],
        "warnings": [w for v in layers.values() for w in v.warnings],
        "layers": {k: {"passed": v.passed, "reason": v.reason, "codes": v.codes,
                       "warnings": v.warnings} for k, v in layers.items()},
    }


def build_report(
    guide: str, meta: dict, progress: list[str], q: Query, elapsed_s: float,
) -> tuple[str, bool]:
    """返回 (Markdown 报告, 三层是否全通过)。"""
    result = verify_result(guide, meta, q)
    process = verify_process(progress, meta, q)
    quality = verify_quality(guide, q)
    head = (guide.strip().split("\n")[0] if guide.strip() else "（空）")[:60]
    body = "\n".join([
        f"### {q.id}　<sub>{q.note}</sub>",
        "",
        f"**最终回复**：{head}…（{len(guide)} 字，耗时 {elapsed_s:.0f}s）",
        "",
        "**工具调用顺序**：",
        *[f"- {s}" for s in (tool_sequence(progress) or ["（无轨迹）"])],
        "",
        "**结果验证**：", "```", result.render(), "```",
        "",
        "**过程验证**：", "```", process.render(), "```",
        "",
        "**质量验证**：", "```", quality.render(), "```",
        "",
    ])
    return body, all([result.passed, process.passed, quality.passed])
